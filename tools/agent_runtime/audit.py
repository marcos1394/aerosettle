"""Persistent run state and tamper-evident, unsigned audit chain."""
from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
import secrets
import sqlite3
import threading
import time
import uuid

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from tools.discovery.agent_discovery import b58decode

from .models import RuntimeDenied, TRANSITIONS, canonical


class RuntimeStore:
    def __init__(self, path: str | Path, *, approved_attestors: frozenset[str] = frozenset()):
        self.approved_attestors = approved_attestors
        self.conn = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False,
                                    timeout=10)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self.conn.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS runtime_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS runtime_policies(agent_id TEXT PRIMARY KEY, owner_id TEXT NOT NULL,
          tenant_id TEXT NOT NULL, organization_id TEXT NOT NULL, version INTEGER NOT NULL,
          policy_hash TEXT NOT NULL, policy_json TEXT NOT NULL, revoked INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS runtime_controls(name TEXT PRIMARY KEY, enabled INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS runtime_runs(run_id TEXT PRIMARY KEY, idempotency_key TEXT UNIQUE NOT NULL,
          agent_id TEXT NOT NULL, owner_id TEXT NOT NULL, tenant_id TEXT NOT NULL,
          organization_id TEXT NOT NULL, goal_hash TEXT NOT NULL, request_hash TEXT NOT NULL,
          policy_version INTEGER NOT NULL,
          policy_hash TEXT NOT NULL, plan_hash TEXT, step_number INTEGER NOT NULL DEFAULT 0,
          status TEXT NOT NULL, result_json TEXT, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS runtime_events(event_id TEXT PRIMARY KEY, run_id TEXT NOT NULL,
          sequence INTEGER NOT NULL, event_type TEXT NOT NULL, actor TEXT NOT NULL,
          tool_id TEXT, policy_version INTEGER NOT NULL, decision TEXT, input_hash TEXT,
          output_hash TEXT, previous_event_hash TEXT, event_hash TEXT NOT NULL,
          timestamp INTEGER NOT NULL, evidence_source TEXT NOT NULL,
          attestation TEXT NOT NULL, UNIQUE(run_id,sequence));
        CREATE TABLE IF NOT EXISTS runtime_event_attestations(event_id TEXT PRIMARY KEY,
          signer_pubkey TEXT NOT NULL, signature TEXT NOT NULL);
        """)
        with self.lock:
            row = self.conn.execute("SELECT value FROM runtime_meta WHERE key='hmac_key'").fetchone()
            if row is None:
                self.conn.execute("INSERT OR IGNORE INTO runtime_meta VALUES ('hmac_key',?)",
                                  (secrets.token_hex(32),))
            self.key = bytes.fromhex(self.conn.execute(
                "SELECT value FROM runtime_meta WHERE key='hmac_key'").fetchone()[0])

    def close(self):
        self.conn.close()

    def seal(self, value) -> str:
        return hmac.new(self.key, canonical(value), hashlib.sha256).hexdigest()

    def _append(self, run_id: str, event_type: str, actor: str, policy_version: int,
                *, tool_id=None, decision=None, input_hash=None, output_hash=None,
                evidence_source="UNVERIFIED") -> None:
        prior = self.conn.execute("SELECT sequence,event_hash FROM runtime_events WHERE run_id=? "
                                  "ORDER BY sequence DESC LIMIT 1", (run_id,)).fetchone()
        fields = {"event_id": uuid.uuid4().hex, "run_id": run_id,
                  "sequence": 1 if prior is None else prior["sequence"] + 1,
                  "event_type": event_type, "actor": actor, "tool_id": tool_id,
                  "policy_version": policy_version, "decision": decision,
                  "input_hash": input_hash, "output_hash": output_hash,
                  "previous_event_hash": prior["event_hash"] if prior else None,
                  "timestamp": int(time.time()), "evidence_source": evidence_source,
                  "attestation": "HASH_CHAIN_ONLY"}
        event_hash = hashlib.sha256(canonical(fields)).hexdigest()
        self.conn.execute("INSERT INTO runtime_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                          (fields["event_id"], run_id, fields["sequence"], event_type, actor,
                           tool_id, policy_version, decision, input_hash, output_hash,
                           fields["previous_event_hash"], event_hash, fields["timestamp"],
                           evidence_source, "HASH_CHAIN_ONLY"))

    def begin(self, identity, idempotency_key: str, goal: str, request: dict,
              policy: dict) -> tuple[str, dict | None]:
        goal_hash = self.seal(goal)
        request_hash = self.seal(request)
        with self.lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                old = self.conn.execute("SELECT * FROM runtime_runs WHERE idempotency_key=?",
                                        (idempotency_key,)).fetchone()
                if old:
                    if any(old[k] != value for k, value in {
                        "agent_id": identity.agent_id, "owner_id": identity.owner_id,
                        "tenant_id": identity.tenant_id, "organization_id": identity.organization_id,
                        "goal_hash": goal_hash, "request_hash": request_hash,
                        "policy_version": policy["version"],
                        "policy_hash": policy["policy_hash"]}.items()):
                        raise RuntimeDenied("IDEMPOTENCY_CONFLICT")
                    self.verify(old["run_id"])
                    if old["result_json"] is None:
                        raise RuntimeDenied("RUN_IN_PROGRESS")
                    self.conn.execute("COMMIT")
                    return old["run_id"], json.loads(old["result_json"])
                run_id, now = uuid.uuid4().hex, int(time.time())
                self.conn.execute("INSERT INTO runtime_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (run_id, idempotency_key, identity.agent_id, identity.owner_id,
                     identity.tenant_id, identity.organization_id, goal_hash, request_hash,
                     policy["version"],
                     policy["policy_hash"], None, 0, "CREATED", None, now, now))
                self._append(run_id, "CREATED", identity.agent_id, policy["version"],
                             input_hash=goal_hash)
                self.conn.execute("COMMIT")
                return run_id, None
            except Exception:
                self.conn.execute("ROLLBACK")
                raise

    def transition(self, run_id: str, status: str, *, actor: str, tool_id=None,
                   decision=None, input_hash=None, output_hash=None, step=None,
                   plan_hash=None, result=None, evidence_source="UNVERIFIED") -> None:
        with self.lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                row = self.conn.execute("SELECT * FROM runtime_runs WHERE run_id=?", (run_id,)).fetchone()
                if row is None or status not in TRANSITIONS[row["status"]]:
                    raise RuntimeDenied("INVALID_TRANSITION")
                self.verify(run_id)
                self.conn.execute("UPDATE runtime_runs SET status=?, step_number=?, plan_hash=COALESCE(?,plan_hash), "
                                  "result_json=?, updated_at=? WHERE run_id=?",
                    (status, row["step_number"] if step is None else step, plan_hash,
                     json.dumps(result, sort_keys=True) if result is not None else None,
                     int(time.time()), run_id))
                self._append(run_id, status, actor, row["policy_version"], tool_id=tool_id,
                             decision=decision, input_hash=input_hash, output_hash=output_hash,
                             evidence_source=evidence_source)
                self.conn.execute("COMMIT")
            except Exception:
                self.conn.execute("ROLLBACK")
                raise

    def verify(self, run_id: str) -> list[dict]:
        events = [dict(r) for r in self.conn.execute(
            "SELECT * FROM runtime_events WHERE run_id=? ORDER BY sequence", (run_id,))]
        row = self.conn.execute("SELECT status,result_json,plan_hash FROM runtime_runs WHERE run_id=?",
                                (run_id,)).fetchone()
        if row is None or not events or events[-1]["event_type"] != row["status"]:
            raise RuntimeDenied("AUDIT_INTEGRITY_CONFLICT")
        previous = None
        for number, event in enumerate(events, 1):
            fields = {k: event[k] for k in ("event_id", "run_id", "sequence", "event_type",
                "actor", "tool_id", "policy_version", "decision", "input_hash", "output_hash",
                "previous_event_hash", "timestamp", "evidence_source", "attestation")}
            if (event["sequence"] != number or event["previous_event_hash"] != previous or
                    event["attestation"] != "HASH_CHAIN_ONLY" or
                    hashlib.sha256(canonical(fields)).hexdigest() != event["event_hash"]):
                raise RuntimeDenied("AUDIT_INTEGRITY_CONFLICT")
            previous = event["event_hash"]
        if row["result_json"] is not None:
            try:
                result = json.loads(row["result_json"])
                if events[-1]["output_hash"] != self.seal(result):
                    raise RuntimeDenied("AUDIT_INTEGRITY_CONFLICT")
            except (ValueError, TypeError) as exc:
                raise RuntimeDenied("AUDIT_INTEGRITY_CONFLICT") from exc
        if row["plan_hash"] and not any(e["output_hash"] == row["plan_hash"]
                                            for e in events if e["event_type"] == "POLICY_CHECK"):
            raise RuntimeDenied("AUDIT_INTEGRITY_CONFLICT")
        for event in events:
            att = self.conn.execute("SELECT * FROM runtime_event_attestations WHERE event_id=?",
                                    (event["event_id"],)).fetchone()
            if att is not None:
                try:
                    if att["signer_pubkey"] not in self.approved_attestors:
                        raise RuntimeDenied("AUDIT_INTEGRITY_CONFLICT")
                    Ed25519PublicKey.from_public_bytes(b58decode(att["signer_pubkey"], 32)).verify(
                        b58decode(att["signature"], 64), bytes.fromhex(event["event_hash"]))
                except Exception as exc:
                    raise RuntimeDenied("AUDIT_INTEGRITY_CONFLICT") from exc
                event["attestation"] = "SIGNED"
                event["signer_pubkey"] = att["signer_pubkey"]
        return events

    def attest(self, event_id: str, signer_pubkey: str, signature: str) -> None:
        """Accept only an externally produced Ed25519 signature over event_hash bytes."""
        if signer_pubkey not in self.approved_attestors:
            raise RuntimeDenied("UNAUTHORIZED_ATTESTOR")
        with self.lock:
            event = self.conn.execute("SELECT event_hash FROM runtime_events WHERE event_id=?",
                                      (event_id,)).fetchone()
            if event is None:
                raise RuntimeDenied("EVENT_NOT_FOUND")
            try:
                Ed25519PublicKey.from_public_bytes(b58decode(signer_pubkey, 32)).verify(
                    b58decode(signature, 64), bytes.fromhex(event["event_hash"]))
            except Exception as exc:
                raise RuntimeDenied("INVALID_ATTESTATION") from exc
            try:
                self.conn.execute("INSERT INTO runtime_event_attestations VALUES (?,?,?)",
                                  (event_id, signer_pubkey, signature))
            except sqlite3.IntegrityError as exc:
                raise RuntimeDenied("ATTESTATION_EXISTS") from exc

    def snapshot(self, run_id: str, identity) -> dict:
        with self.lock:
            row = self.conn.execute("SELECT * FROM runtime_runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None or any(row[k] != getattr(identity, k) for k in
                                  ("agent_id", "owner_id", "tenant_id", "organization_id")):
                raise RuntimeDenied("RUN_NOT_FOUND")
            events = self.verify(run_id)
            return {"run_id": run_id, "status": row["status"],
                    "step_number": row["step_number"], "policy_version": row["policy_version"],
                    "plan_hash": row["plan_hash"], "events": events,
                    "result": json.loads(row["result_json"]) if row["result_json"] else None}
