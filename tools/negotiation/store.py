"""Append-only SQLite messages, nonces, idempotency and hash-chain audit."""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import threading
from .canonical import canonical, digest
from .models import NegotiationError


class NegotiationStore:
    def __init__(self, path: str | Path):
        self.conn = sqlite3.connect(str(path), isolation_level=None, timeout=30,
                                    check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=30000")
        self.lock = threading.RLock()
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS negotiation_sessions (
              negotiation_id TEXT PRIMARY KEY, requester_account TEXT NOT NULL,
              tenant_id TEXT NOT NULL, organization_id TEXT NOT NULL,
              state TEXT NOT NULL, version INTEGER NOT NULL, selected_id TEXT,
              proposal_json TEXT, root_hash TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS negotiation_messages (
              message_id TEXT PRIMARY KEY, negotiation_id TEXT NOT NULL,
              version INTEGER NOT NULL, agent_account TEXT NOT NULL,
              network TEXT NOT NULL, genesis_hash TEXT NOT NULL, program_id TEXT NOT NULL,
              nonce TEXT NOT NULL, idempotency_key TEXT NOT NULL,
              message_hash TEXT NOT NULL, message_json TEXT NOT NULL,
              state TEXT NOT NULL, selected_id TEXT, proposal_hash TEXT NOT NULL,
              previous_event_hash TEXT NOT NULL, event_hash TEXT NOT NULL,
              UNIQUE(negotiation_id, version),
              UNIQUE(agent_account, network, genesis_hash, program_id, nonce),
              UNIQUE(agent_account, idempotency_key),
              FOREIGN KEY(negotiation_id) REFERENCES negotiation_sessions(negotiation_id));
            CREATE INDEX IF NOT EXISTS negotiation_messages_by_session
              ON negotiation_messages(negotiation_id, version);
        """)

    def close(self) -> None:
        self.conn.close()

    def _messages(self, negotiation_id: str) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM negotiation_messages WHERE negotiation_id=? ORDER BY version",
                                 (negotiation_id,)).fetchall()
        previous = "0" * 64
        result = []
        for index, row in enumerate(rows, 1):
            try:
                message = json.loads(row["message_json"])
                message_hash = digest(message)
                expected = digest({"negotiation_id": negotiation_id, "version": index,
                                   "message_hash": message_hash, "state": row["state"],
                                   "selected_id": row["selected_id"],
                                   "proposal_hash": row["proposal_hash"], "previous": previous})
                if (row["version"] != index or row["message_hash"] != message_hash or
                        row["previous_event_hash"] != previous or row["event_hash"] != expected or
                        message["message_id"] != row["message_id"] or
                        message["negotiation_id"] != negotiation_id or
                        any(row[field] != message[field] for field in
                            ("agent_account", "network", "genesis_hash", "program_id",
                             "nonce", "idempotency_key"))):
                    raise ValueError("broken chain")
            except (ValueError, TypeError, KeyError) as exc:
                raise NegotiationError("INTEGRITY_CONFLICT") from exc
            result.append(message)
            previous = expected
        return result

    def read(self, negotiation_id: str) -> tuple[dict, list[dict]]:
        with self.lock:
            row = self.conn.execute("SELECT * FROM negotiation_sessions WHERE negotiation_id=?",
                                    (negotiation_id,)).fetchone()
            if row is None:
                raise NegotiationError("NOT_FOUND")
            messages = self._messages(negotiation_id)
            last = self.conn.execute("SELECT state, selected_id, proposal_hash FROM "
                "negotiation_messages WHERE negotiation_id=? ORDER BY version DESC LIMIT 1",
                (negotiation_id,)).fetchone()
            try:
                proposal = json.loads(row["proposal_json"]) if row["proposal_json"] else None
            except (ValueError, TypeError) as exc:
                raise NegotiationError("INTEGRITY_CONFLICT") from exc
            if (len(messages) != row["version"] or not messages or
                    digest(messages[0]) != row["root_hash"] or
                    row["requester_account"] != messages[0]["requester_agent_account"] or
                    row["tenant_id"] != messages[0]["tenant_id"] or
                    row["organization_id"] != messages[0]["organization_id"] or
                    row["state"] != last["state"] or
                    row["selected_id"] != last["selected_id"] or
                    (digest(proposal) if proposal else "0" * 64) != last["proposal_hash"]):
                raise NegotiationError("INTEGRITY_CONFLICT")
            return dict(row), messages

    def append(self, message: dict, transition, verify_history) -> tuple[dict, bool]:
        """transition(session, history) returns (new_state, selected_id, proposal)."""
        with self.lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                existing = self.conn.execute("SELECT * FROM negotiation_messages WHERE message_id=? OR "
                    "(agent_account=? AND idempotency_key=?) OR "
                    "(agent_account=? AND network=? AND genesis_hash=? AND program_id=? AND nonce=?)",
                    (message["message_id"], message["agent_account"], message["idempotency_key"],
                     message["agent_account"], message["network"], message["genesis_hash"],
                     message["program_id"], message["nonce"])).fetchall()
                if existing:
                    if (len(existing) != 1 or existing[0]["message_id"] != message["message_id"] or
                            existing[0]["message_hash"] != digest(message) or
                            existing[0]["negotiation_id"] != message["negotiation_id"]):
                        raise NegotiationError("REPLAY_CONFLICT")
                    session, history = self.read(message["negotiation_id"])
                    verify_history(history)
                    self.conn.execute("COMMIT")
                    return {"state": session["state"], "version": session["version"],
                            "selected_id": session["selected_id"],
                            "proposal": json.loads(session["proposal_json"]) if session["proposal_json"] else None,
                            "message_hash": existing[0]["message_hash"]}, False
                row = self.conn.execute("SELECT * FROM negotiation_sessions WHERE negotiation_id=?",
                                        (message["negotiation_id"],)).fetchone()
                if row:
                    session, history = self.read(message["negotiation_id"])
                    verify_history(history)
                else:
                    session, history = None, []
                state, selected_id, proposal = transition(session, history)
                version = len(history) + 1
                message_hash = digest(message)
                previous = (self.conn.execute("SELECT event_hash FROM negotiation_messages "
                    "WHERE negotiation_id=? ORDER BY version DESC LIMIT 1",
                    (message["negotiation_id"],)).fetchone() or ["0" * 64])[0]
                proposal_hash = digest(proposal) if proposal else "0" * 64
                event_hash = digest({"negotiation_id": message["negotiation_id"],
                    "version": version, "message_hash": message_hash, "state": state,
                    "selected_id": selected_id, "proposal_hash": proposal_hash,
                    "previous": previous})
                if session is None:
                    self.conn.execute("INSERT INTO negotiation_sessions VALUES (?,?,?,?,?,?,?,?,?)",
                        (message["negotiation_id"], message["requester_agent_account"],
                         message["tenant_id"], message["organization_id"], state, version,
                         selected_id, canonical(proposal).decode() if proposal else None, message_hash))
                else:
                    self.conn.execute("UPDATE negotiation_sessions SET state=?, version=?, selected_id=?, "
                        "proposal_json=? WHERE negotiation_id=?",
                        (state, version, selected_id, canonical(proposal).decode() if proposal else None,
                         message["negotiation_id"]))
                self.conn.execute("INSERT INTO negotiation_messages VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (message["message_id"], message["negotiation_id"], version,
                     message["agent_account"], message["network"], message["genesis_hash"],
                     message["program_id"], message["nonce"], message["idempotency_key"],
                     message_hash, canonical(message).decode(), state, selected_id,
                     proposal_hash, previous, event_hash))
                self.conn.execute("COMMIT")
                return {"state": state, "version": version, "selected_id": selected_id,
                        "proposal": proposal, "message_hash": message_hash}, True
            except Exception:
                self.conn.execute("ROLLBACK")
                raise
