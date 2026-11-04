"""Persistent A2A task correlation; never writes an economic or Anchor state."""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
from pathlib import Path
import re
import secrets
import sqlite3
import threading
import time
import uuid

from a2a.types import Artifact, Message, Part, Task, TaskState
from google.protobuf.json_format import MessageToDict, ParseDict
from google.protobuf.struct_pb2 import Struct
from google.protobuf.timestamp_pb2 import Timestamp

from tools.mcp.security import Principal
from tools.operations.structured_logs import emit, correlation_id


class TaskDenied(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


SAFE_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
STATES = {
    "SUBMITTED": TaskState.TASK_STATE_SUBMITTED,
    "WORKING": TaskState.TASK_STATE_WORKING,
    "INPUT_REQUIRED": TaskState.TASK_STATE_INPUT_REQUIRED,
    "AUTH_REQUIRED": TaskState.TASK_STATE_AUTH_REQUIRED,
    "COMPLETED": TaskState.TASK_STATE_COMPLETED,
    "FAILED": TaskState.TASK_STATE_FAILED,
    "CANCELED": TaskState.TASK_STATE_CANCELED,
    "REJECTED": TaskState.TASK_STATE_REJECTED,
}
TERMINAL = {"COMPLETED", "FAILED", "CANCELED", "REJECTED"}
TRANSITIONS = {
    "SUBMITTED": {"WORKING", "INPUT_REQUIRED", "AUTH_REQUIRED", "REJECTED", "FAILED", "CANCELED"},
    "WORKING": {"INPUT_REQUIRED", "AUTH_REQUIRED", "COMPLETED", "FAILED", "CANCELED"},
    "INPUT_REQUIRED": {"WORKING", "FAILED", "CANCELED"},
    "AUTH_REQUIRED": {"WORKING", "REJECTED", "FAILED", "CANCELED"},
}
MEDIA_TYPES = {"text/plain", "application/json", "image/png"}
MAX_ARTIFACT = 8192


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _struct(value: dict) -> Struct:
    result = Struct()
    result.update(value)
    return result


def _timestamp(stamp: int) -> Timestamp:
    result = Timestamp()
    result.FromSeconds(stamp)
    return result


class OfflineWorkOrders:
    """Explicit offline fixture, never an RPC or financial verification source."""
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def get(self, work_order_pda: str) -> dict:
        try:
            data = json.loads(self.path.read_text())
            if (data.get("evidence_source") != "OFFLINE_FIXTURE" or
                    not isinstance(data.get("network"), str) or
                    not data["network"].startswith("offline:") or
                    not str(data.get("genesis_hash", "")).startswith("OFFLINE_") or
                    not str(data.get("program_id", "")).startswith("OFFLINE_")):
                raise TaskDenied("UNVERIFIABLE")
            matches = [row for row in data["work_orders"]
                       if row.get("work_order_pda") == work_order_pda]
            if len(matches) != 1:
                raise TaskDenied("RESOURCE_NOT_FOUND")
            row = dict(matches[0])
            for field in ("network", "genesis_hash", "program_id"):
                row[field] = data[field]
            row["evidence_source"] = "OFFLINE_FIXTURE"
            required = ("work_order_pda", "agent_account", "agent_id", "requester_identity",
                        "executor_identity", "owner_pubkey", "signing_authority", "tenant_id",
                        "organization_id", "network", "genesis_hash", "program_id", "work_order_status")
            if any(not isinstance(row.get(key), str) or not row[key] for key in required):
                raise TaskDenied("UNVERIFIABLE")
            if type(row.get("escrow_funded")) is not bool:
                raise TaskDenied("UNVERIFIABLE")
            if (row["work_order_status"] not in ("Draft", "Open", "Claimed", "Submitted", "Verified") or
                    (row["work_order_status"] != "Draft" and not row["escrow_funded"])):
                # A fixture cannot prove finalized settlement or inconsistent escrow.
                raise TaskDenied("UNVERIFIABLE")
            return row
        except (OSError, KeyError, ValueError, TypeError) as exc:
            if isinstance(exc, TaskDenied):
                raise
            raise TaskDenied("UNVERIFIABLE") from exc


class TaskLedger:
    """Single-writer SQLite task store with per-operation authorization and replay checks."""
    def __init__(self, path: str | Path, work_orders: OfflineWorkOrders,
                 operational_store=None):
        self.work_orders = work_orders
        self.operational_store = operational_store
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(str(path), check_same_thread=False, timeout=10)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript("""
        CREATE TABLE IF NOT EXISTS a2a_tasks (
          task_id TEXT PRIMARY KEY, context_id TEXT NOT NULL, binding_json TEXT NOT NULL,
          requester_identity TEXT NOT NULL, executor_identity TEXT NOT NULL,
          work_order_pda TEXT NOT NULL UNIQUE, task_status TEXT NOT NULL,
          work_order_status TEXT NOT NULL, evidence_source TEXT NOT NULL,
          created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL, expires_at INTEGER NOT NULL,
          version INTEGER NOT NULL, cancel_requested INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS a2a_messages (
          task_id TEXT NOT NULL REFERENCES a2a_tasks(task_id), message_id TEXT NOT NULL,
          sequence INTEGER NOT NULL, actor TEXT NOT NULL, body_json TEXT NOT NULL,
          content_hash TEXT NOT NULL,
          created_at INTEGER NOT NULL, PRIMARY KEY(task_id, message_id), UNIQUE(task_id, sequence)
        );
        CREATE TABLE IF NOT EXISTS a2a_artifacts (
          artifact_id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES a2a_tasks(task_id),
          media_type TEXT NOT NULL, content_hash TEXT NOT NULL, size INTEGER NOT NULL,
          producer TEXT NOT NULL, provenance TEXT NOT NULL, content BLOB NOT NULL,
          created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS a2a_events (
          event_id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES a2a_tasks(task_id),
          sequence INTEGER NOT NULL, event_type TEXT NOT NULL, state_before TEXT NOT NULL,
          state_after TEXT NOT NULL, actor TEXT NOT NULL, previous_hash TEXT NOT NULL,
          event_hash TEXT NOT NULL, created_at INTEGER NOT NULL,
          UNIQUE(task_id, sequence)
        );
        CREATE TABLE IF NOT EXISTS a2a_idempotency (
          subject TEXT NOT NULL, client_id TEXT NOT NULL, operation TEXT NOT NULL,
          idem_key TEXT NOT NULL, fingerprint TEXT NOT NULL, task_id TEXT NOT NULL,
          PRIMARY KEY(subject, client_id, operation, idem_key)
        );
        CREATE TABLE IF NOT EXISTS a2a_meta (
          key TEXT PRIMARY KEY, value BLOB NOT NULL
        );
        """)
        with self.conn:
            self.conn.execute("INSERT OR IGNORE INTO a2a_meta VALUES ('cursor_secret', ?)",
                              (secrets.token_bytes(32),))
        self.cursor_secret = self.conn.execute(
            "SELECT value FROM a2a_meta WHERE key='cursor_secret'").fetchone()[0]

    def close(self) -> None:
        self.conn.close()

    @staticmethod
    def _scope(principal: Principal, scope: str) -> None:
        if scope not in principal.scopes or not principal.subject or not principal.client_id:
            raise TaskDenied("ACCESS_DENIED")

    @staticmethod
    def _identity(principal: Principal, binding: dict, *, executor: bool = False) -> None:
        identity = binding["executor_identity"] if executor else binding["requester_identity"]
        if (principal.subject != identity or principal.tenant_id != binding["tenant_id"] or
                principal.organization_id != binding["organization_id"]):
            raise TaskDenied("RESOURCE_NOT_FOUND")
        if not executor and principal.subject != binding["owner_pubkey"]:
            raise TaskDenied("RESOURCE_NOT_FOUND")
        if executor and principal.subject != binding["signing_authority"]:
            raise TaskDenied("RESOURCE_NOT_FOUND")

    def _current(self, row: sqlite3.Row) -> dict:
        binding = json.loads(row["binding_json"])
        current = self.work_orders.get(row["work_order_pda"])
        immutable = ("agent_account", "agent_id", "requester_identity", "executor_identity",
                     "owner_pubkey", "signing_authority", "tenant_id", "organization_id",
                     "network", "genesis_hash", "program_id", "work_order_pda", "evidence_source",
                     "escrow_funded")
        if any(current[key] != binding[key] for key in immutable):
            raise TaskDenied("RESOURCE_NOT_FOUND")
        return current

    def _read_row(self, task_id: str, principal: Principal, scope: str) -> tuple[sqlite3.Row, dict]:
        self._scope(principal, scope)
        if not isinstance(task_id, str) or not SAFE_ID.fullmatch(task_id):
            raise TaskDenied("RESOURCE_NOT_FOUND")
        row = self.conn.execute("SELECT * FROM a2a_tasks WHERE task_id=?", (task_id,)).fetchone()
        if row is None:
            raise TaskDenied("RESOURCE_NOT_FOUND")
        current = self._current(row)
        self._identity(principal, current, executor=principal.subject == current["executor_identity"])
        return row, current

    def _event(self, task_id: str, kind: str, before: str, after: str,
               actor: str, stamp: int) -> None:
        previous = self.conn.execute(
            "SELECT sequence,event_hash FROM a2a_events WHERE task_id=? ORDER BY sequence DESC LIMIT 1",
            (task_id,)).fetchone()
        sequence = 1 if previous is None else previous["sequence"] + 1
        prior_hash = "0" * 64 if previous is None else previous["event_hash"]
        event_id = str(uuid.uuid4())
        event_hash = _digest({"event_id": event_id, "task_id": task_id, "sequence": sequence,
                              "event_type": kind, "before": before, "after": after,
                              "actor": actor, "previous_hash": prior_hash, "at": stamp})
        self.conn.execute("INSERT INTO a2a_events VALUES (?,?,?,?,?,?,?,?,?,?)",
                          (event_id, task_id, sequence, kind, before, after,
                           actor, prior_hash, event_hash, stamp))
        try:
            task_row = self.conn.execute("SELECT requester_identity,executor_identity,work_order_pda "
                                         "FROM a2a_tasks WHERE task_id=?", (task_id,)).fetchone()
            emit("INFO", "a2a_tasks", "transition", task_id=task_id,
                 requester_id=task_row["requester_identity"],
                 executor_id=task_row["executor_identity"],
                 work_order_pda=task_row["work_order_pda"],
                 event_type=kind, state_before=before or "NONE", state_after=after,
                 authorization_result="AUTHORIZED", evidence_source="OFFLINE_FIXTURE",
                 correlation_id=correlation_id("a2a-task", task_id))
            if self.operational_store is not None:
                name = ("a2a_tasks_created" if kind == "CREATED" else
                        "a2a_tasks_timed_out" if kind == "TIMEOUT" else
                        "a2a_tasks_canceled" if after == "CANCELED" else
                        "a2a_tasks_completed" if after == "COMPLETED" else
                        "a2a_tasks_failed" if after == "FAILED" else
                        "a2a_task_events")
                self.operational_store.sample(name, 1, "events", "a2a-tasks",
                                              correlation_id=correlation_id("a2a-task", task_id))
        except Exception:
            # Telemetry is never a source of authorization or task state.
            pass

    def _message(self, task_id: str, message: Message, actor: str, stamp: int) -> None:
        if not SAFE_ID.fullmatch(message.message_id):
            raise TaskDenied("INVALID_MESSAGE")
        body = MessageToDict(message, preserving_proto_field_name=True)
        if len(_canonical(body)) > 2048 or not message.parts or len(message.parts) > 8:
            raise TaskDenied("INVALID_MESSAGE")
        for part in message.parts:
            if part.WhichOneof("content") != "text" or len(part.text) > 1024:
                raise TaskDenied("INVALID_MESSAGE")
        seq = self.conn.execute("SELECT COUNT(*) FROM a2a_messages WHERE task_id=?",
                                (task_id,)).fetchone()[0] + 1
        if seq > 8:
            raise TaskDenied("MESSAGE_LIMIT")
        encoded = _canonical(body)
        self.conn.execute("INSERT INTO a2a_messages VALUES (?,?,?,?,?,?,?)",
                          (task_id, message.message_id, seq, actor, encoded.decode(),
                           hashlib.sha256(encoded).hexdigest(), stamp))

    def _idempotent(self, principal: Principal, operation: str, key: str,
                    fingerprint: str, task_id: str | None = None) -> str | None:
        if not isinstance(key, str) or not SAFE_ID.fullmatch(key):
            raise TaskDenied("INVALID_IDEMPOTENCY_KEY")
        row = self.conn.execute("SELECT * FROM a2a_idempotency WHERE subject=? AND client_id=? AND operation=? AND idem_key=?",
                                (principal.subject, principal.client_id, operation, key)).fetchone()
        if row is None:
            return None
        if row["fingerprint"] != fingerprint or task_id and task_id != row["task_id"]:
            raise TaskDenied("IDEMPOTENCY_CONFLICT")
        # Crucially recheck current identity before exposing an older result.
        self._read_row(row["task_id"], principal,
                       "tasks:execute" if operation == "executor_update" else
                       "tasks:cancel" if operation == "cancel" else "tasks:write")
        try:
            if self.operational_store is not None:
                self.operational_store.sample("a2a_task_duplicates", 1, "events", "a2a-tasks")
        except Exception:
            pass
        return row["task_id"]

    def _save_idem(self, principal: Principal, operation: str, key: str,
                   fingerprint: str, task_id: str) -> None:
        self.conn.execute("INSERT INTO a2a_idempotency VALUES (?,?,?,?,?,?)",
                          (principal.subject, principal.client_id, operation, key, fingerprint, task_id))

    def create(self, principal: Principal, message: Message, *, work_order_pda: str,
               idempotency_key: str, expires_at: int, now: int | None = None) -> Task:
        stamp = int(time.time()) if now is None else now
        self._scope(principal, "tasks:write")
        if (message.role != 1 or message.task_id or type(expires_at) is not int or
                not isinstance(work_order_pda, str) or not SAFE_ID.fullmatch(work_order_pda) or
                expires_at > stamp + 86400):
            raise TaskDenied("INVALID_REQUEST")
        binding = self.work_orders.get(work_order_pda)
        self._identity(principal, binding)
        if binding["work_order_status"] not in ("Open", "Claimed", "Submitted", "Verified"):
            raise TaskDenied("INVALID_WORK_ORDER_STATE")
        fingerprint = _digest({"message": MessageToDict(message, preserving_proto_field_name=True),
                               "work_order": work_order_pda, "expires_at": expires_at})
        with self.lock, self.conn:
            self.conn.execute("BEGIN IMMEDIATE")
            previous = self._idempotent(principal, "create", idempotency_key, fingerprint)
            if previous:
                row = self.conn.execute("SELECT * FROM a2a_tasks WHERE task_id=?",
                                        (previous,)).fetchone()
                return self._as_task(self._expire_row(row, stamp))
            if expires_at <= stamp:
                raise TaskDenied("INVALID_REQUEST")
            if self.conn.execute("SELECT 1 FROM a2a_tasks WHERE work_order_pda=?",
                                 (work_order_pda,)).fetchone():
                raise TaskDenied("WORK_ORDER_ALREADY_LINKED")
            task_id, context_id = str(uuid.uuid4()), message.context_id or str(uuid.uuid4())
            self.conn.execute("INSERT INTO a2a_tasks VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                              (task_id, context_id, _canonical(binding).decode(),
                               binding["requester_identity"], binding["executor_identity"],
                               work_order_pda, "SUBMITTED", binding["work_order_status"],
                               "OFFLINE_FIXTURE", stamp, stamp, expires_at, 1, 0))
            self._message(task_id, message, principal.subject, stamp)
            self._event(task_id, "CREATED", "", "SUBMITTED", principal.subject, stamp)
            self._save_idem(principal, "create", idempotency_key, fingerprint, task_id)
            return self._as_task(self.conn.execute("SELECT * FROM a2a_tasks WHERE task_id=?",
                                                   (task_id,)).fetchone())

    def _as_task(self, row: sqlite3.Row) -> Task:
        events = self._verify_chain(row["task_id"])
        if events[-1]["state_after"] != row["task_status"] or len(events) != row["version"]:
            raise TaskDenied("INTEGRITY_CONFLICT")
        binding = json.loads(row["binding_json"])
        current = self.work_orders.get(row["work_order_pda"])
        immutable = ("agent_account", "agent_id", "requester_identity", "executor_identity",
                     "owner_pubkey", "signing_authority", "tenant_id", "organization_id",
                     "network", "genesis_hash", "program_id", "work_order_pda", "evidence_source",
                     "escrow_funded")
        if any(current[key] != binding[key] for key in immutable):
            raise TaskDenied("RESOURCE_NOT_FOUND")
        task = Task(id=row["task_id"], context_id=row["context_id"])
        task.status.state = STATES[row["task_status"]]
        task.status.timestamp.CopyFrom(_timestamp(row["updated_at"]))
        task.metadata.CopyFrom(_struct({
            "conatus": {"agent_account": binding["agent_account"],
                        "work_order_pda": row["work_order_pda"],
                        "work_order_status": current["work_order_status"],
                        "work_order_status_at_link": row["work_order_status"],
                        "fixture_escrow_funded": current["escrow_funded"],
                        "network": binding["network"], "genesis_hash": binding["genesis_hash"],
                        "program_id": binding["program_id"],
                        "evidence_source": row["evidence_source"],
                        "is_financial_authority": False, "settlement_verified": False,
                        "cancel_requested": bool(row["cancel_requested"]),
                        "version": row["version"], "expires_at": row["expires_at"]}}))
        for item in self.conn.execute("SELECT body_json,content_hash FROM a2a_messages WHERE task_id=? ORDER BY sequence",
                                      (row["task_id"],)):
            if hashlib.sha256(item["body_json"].encode()).hexdigest() != item["content_hash"]:
                raise TaskDenied("INTEGRITY_CONFLICT")
            task.history.add().CopyFrom(ParseDict(json.loads(item["body_json"]), Message()))
        for item in self.conn.execute("SELECT * FROM a2a_artifacts WHERE task_id=? ORDER BY created_at,artifact_id",
                                      (row["task_id"],)):
            if (len(item["content"]) != item["size"] or
                    hashlib.sha256(item["content"]).hexdigest() != item["content_hash"]):
                raise TaskDenied("INTEGRITY_CONFLICT")
            artifact = task.artifacts.add()
            artifact.artifact_id = item["artifact_id"]
            artifact.name = "Conatus task artifact"
            artifact.parts.add(raw=item["content"], media_type=item["media_type"])
            artifact.metadata.CopyFrom(_struct({"content_hash": item["content_hash"],
                                                "size": item["size"], "producer": item["producer"],
                                                "provenance": item["provenance"],
                                                "created_at": item["created_at"]}))
        return task

    def _expire_row(self, row: sqlite3.Row, stamp: int) -> sqlite3.Row:
        if row["expires_at"] <= stamp and row["task_status"] not in TERMINAL:
            self.conn.execute("UPDATE a2a_tasks SET task_status='FAILED',updated_at=?,version=version+1 WHERE task_id=?",
                              (stamp, row["task_id"]))
            self._event(row["task_id"], "TIMEOUT", row["task_status"], "FAILED", "system", stamp)
            return self.conn.execute("SELECT * FROM a2a_tasks WHERE task_id=?",
                                     (row["task_id"],)).fetchone()
        return row

    def get(self, principal: Principal, task_id: str, *, now: int | None = None) -> Task:
        stamp = int(time.time()) if now is None else now
        with self.lock, self.conn:
            self.conn.execute("BEGIN IMMEDIATE")
            row, _ = self._read_row(task_id, principal, "tasks:read")
            row = self._expire_row(row, stamp)
            return self._as_task(row)

    def list_page(self, principal: Principal, *, limit: int = 20,
                  cursor: str = "") -> tuple[list[Task], str, int]:
        self._scope(principal, "tasks:read")
        if not 1 <= limit <= 20:
            raise TaskDenied("INVALID_REQUEST")
        with self.lock, self.conn:
            self.conn.execute("BEGIN IMMEDIATE")
            rows = self.conn.execute("SELECT * FROM a2a_tasks WHERE requester_identity=? OR executor_identity=? ORDER BY created_at DESC,task_id LIMIT ?",
                                     (principal.subject, principal.subject, 1001)).fetchall()
            if len(rows) > 1000:
                raise TaskDenied("RESULT_LIMIT")
            authorized = []
            for row in rows:
                try:
                    binding = self._current(row)
                    self._identity(principal, binding,
                                   executor=principal.subject == binding["executor_identity"])
                except TaskDenied:
                    continue
                authorized.append(self._expire_row(row, int(time.time())))
            snapshot = _digest([(row["task_id"], row["version"]) for row in authorized])
            identity = {"subject": principal.subject, "client": principal.client_id,
                        "tenant": principal.tenant_id, "organization": principal.organization_id,
                        "scopes": sorted(principal.scopes), "limit": limit, "snapshot": snapshot}
            offset = 0
            if cursor:
                try:
                    encoded, signature = cursor.split(".")
                    if len(cursor) > 2048 or not re.fullmatch(r"[A-Za-z0-9_-]+", encoded) or \
                            not re.fullmatch(r"[0-9a-f]{64}", signature):
                        raise ValueError
                    expected = hmac.new(self.cursor_secret, encoded.encode(), hashlib.sha256).hexdigest()
                    if not hmac.compare_digest(signature, expected):
                        raise ValueError
                    payload = json.loads(base64.urlsafe_b64decode(
                        encoded + "=" * (-len(encoded) % 4)))
                    if payload.get("identity") != identity or type(payload.get("offset")) is not int:
                        raise ValueError
                    offset = payload["offset"]
                    if offset < 0 or offset > len(authorized):
                        raise ValueError
                except (ValueError, UnicodeDecodeError, TypeError, binascii.Error) as exc:
                    raise TaskDenied("INVALID_CURSOR") from exc
            page = authorized[offset:offset + limit]
            next_cursor = ""
            if offset + limit < len(authorized):
                body = {"identity": identity, "offset": offset + limit}
                encoded = base64.urlsafe_b64encode(_canonical(body)).rstrip(b"=").decode()
                signature = hmac.new(self.cursor_secret, encoded.encode(), hashlib.sha256).hexdigest()
                next_cursor = encoded + "." + signature
            return [self._as_task(row) for row in page], next_cursor, len(authorized)

    def list(self, principal: Principal, *, limit: int = 20) -> list[Task]:
        return self.list_page(principal, limit=limit)[0]

    def cancel(self, principal: Principal, task_id: str, *, now: int | None = None) -> Task:
        stamp = int(time.time()) if now is None else now
        with self.lock, self.conn:
            self.conn.execute("BEGIN IMMEDIATE")
            row, binding = self._read_row(task_id, principal, "tasks:cancel")
            self._identity(principal, binding)
            row = self._expire_row(row, stamp)
            if row["task_status"] in TERMINAL:
                return self._as_task(row)
            if row["task_status"] == "SUBMITTED":
                after, kind, requested = "CANCELED", "CANCEL_CONFIRMED", 1
            else:
                after, kind, requested = row["task_status"], "CANCEL_REQUESTED", 1
            if row["cancel_requested"]:
                return self._as_task(row)
            self.conn.execute("UPDATE a2a_tasks SET task_status=?,cancel_requested=?,updated_at=?,version=version+1 WHERE task_id=?",
                              (after, requested, stamp, task_id))
            self._event(task_id, kind, row["task_status"], after, principal.subject, stamp)
            return self._as_task(self.conn.execute("SELECT * FROM a2a_tasks WHERE task_id=?", (task_id,)).fetchone())

    def requester_message(self, principal: Principal, message: Message, *,
                          idempotency_key: str, now: int | None = None) -> Task:
        stamp = int(time.time()) if now is None else now
        task_id = message.task_id
        if message.role != 1:
            raise TaskDenied("INVALID_MESSAGE")
        fingerprint = _digest(MessageToDict(message, preserving_proto_field_name=True))
        with self.lock, self.conn:
            self.conn.execute("BEGIN IMMEDIATE")
            row, binding = self._read_row(task_id, principal, "tasks:write")
            self._identity(principal, binding)
            row = self._expire_row(row, stamp)
            previous = self._idempotent(principal, "message", idempotency_key,
                                        fingerprint, task_id)
            if previous:
                return self._as_task(row)
            if row["expires_at"] <= stamp or row["task_status"] in TERMINAL:
                raise TaskDenied("INVALID_TRANSITION")
            if message.context_id != row["context_id"]:
                raise TaskDenied("INVALID_CONTEXT")
            self._message(task_id, message, principal.subject, stamp)
            self._event(task_id, "MESSAGE_RECEIVED", row["task_status"],
                        row["task_status"], principal.subject, stamp)
            self.conn.execute("UPDATE a2a_tasks SET updated_at=?,version=version+1 WHERE task_id=?",
                              (stamp, task_id))
            self._save_idem(principal, "message", idempotency_key, fingerprint, task_id)
            return self._as_task(self.conn.execute("SELECT * FROM a2a_tasks WHERE task_id=?", (task_id,)).fetchone())

    def executor_update(self, principal: Principal, task_id: str, *, state: str,
                        idempotency_key: str, message: Message | None = None,
                        artifact: tuple[str, bytes] | None = None,
                        now: int | None = None) -> Task:
        stamp = int(time.time()) if now is None else now
        if not isinstance(state, str) or state not in STATES:
            raise TaskDenied("INVALID_STATE")
        if artifact and (not isinstance(artifact[0], str) or
                         not isinstance(artifact[1], bytes) or
                         artifact[0] not in MEDIA_TYPES or len(artifact[1]) > MAX_ARTIFACT or
                         not artifact[1]):
            raise TaskDenied("INVALID_ARTIFACT")
        fingerprint = _digest({"state": state, "message": MessageToDict(message, preserving_proto_field_name=True)
                               if message else None, "artifact": [artifact[0], hashlib.sha256(artifact[1]).hexdigest()]
                               if artifact else None})
        with self.lock, self.conn:
            self.conn.execute("BEGIN IMMEDIATE")
            row, binding = self._read_row(task_id, principal, "tasks:execute")
            self._identity(principal, binding, executor=True)
            row = self._expire_row(row, stamp)
            previous = self._idempotent(principal, "executor_update", idempotency_key,
                                        fingerprint, task_id)
            if previous:
                return self._as_task(row)
            if row["expires_at"] <= stamp:
                raise TaskDenied("TASK_EXPIRED")
            if state not in TRANSITIONS.get(row["task_status"], set()):
                raise TaskDenied("INVALID_TRANSITION")
            if row["cancel_requested"] and state not in ("CANCELED", "FAILED"):
                raise TaskDenied("CANCEL_PENDING")
            if message:
                if message.role != 2 or message.task_id != task_id or message.context_id != row["context_id"]:
                    raise TaskDenied("INVALID_MESSAGE")
                self._message(task_id, message, principal.subject, stamp)
            if artifact:
                if self.conn.execute("SELECT COUNT(*) FROM a2a_artifacts WHERE task_id=?",
                                     (task_id,)).fetchone()[0] >= 2:
                    raise TaskDenied("ARTIFACT_LIMIT")
                content_hash = hashlib.sha256(artifact[1]).hexdigest()
                artifact_id = hashlib.sha256(f"{task_id}:{content_hash}".encode()).hexdigest()
                self.conn.execute("INSERT INTO a2a_artifacts VALUES (?,?,?,?,?,?,?,?,?)",
                                  (artifact_id, task_id, artifact[0], content_hash, len(artifact[1]),
                                   principal.subject, "OFFLINE_FIXTURE", artifact[1], stamp))
            self.conn.execute("UPDATE a2a_tasks SET task_status=?,updated_at=?,version=version+1 WHERE task_id=?",
                              (state, stamp, task_id))
            self._event(task_id, "ARTIFACT" if artifact else "STATE_CHANGE", row["task_status"],
                        state, principal.subject, stamp)
            self._save_idem(principal, "executor_update", idempotency_key, fingerprint, task_id)
            return self._as_task(self.conn.execute("SELECT * FROM a2a_tasks WHERE task_id=?", (task_id,)).fetchone())

    def _verify_chain(self, task_id: str) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM a2a_events WHERE task_id=? ORDER BY sequence",
                                 (task_id,)).fetchall()
        result = [dict(row) for row in rows]
        prior = "0" * 64
        if not result:
            raise TaskDenied("INTEGRITY_CONFLICT")
        for index, event in enumerate(result, 1):
            expected = _digest({"event_id": event["event_id"], "task_id": task_id,
                                "sequence": event["sequence"], "event_type": event["event_type"],
                                "before": event["state_before"], "after": event["state_after"],
                                "actor": event["actor"], "previous_hash": prior,
                                "at": event["created_at"]})
            if (event["sequence"] != index or event["previous_hash"] != prior or
                    event["event_hash"] != expected):
                raise TaskDenied("INTEGRITY_CONFLICT")
            prior = event["event_hash"]
        return result

    def event_history(self, principal: Principal, task_id: str) -> list[dict]:
        with self.lock:
            self._read_row(task_id, principal, "tasks:read")
            return self._verify_chain(task_id)

    def metrics_snapshot(self) -> dict[str, int]:
        """Local aggregate counters; never exposes task contents or balances."""
        with self.lock:
            counts = {row["task_status"]: row["count"] for row in self.conn.execute(
                "SELECT task_status, COUNT(*) AS count FROM a2a_tasks GROUP BY task_status")}
            duplicates = self.conn.execute("SELECT COUNT(*) FROM a2a_idempotency").fetchone()[0]
            return {"created": sum(counts.values()),
                    "active": sum(value for state, value in counts.items() if state not in TERMINAL),
                    "completed": counts.get("COMPLETED", 0),
                    "failed": counts.get("FAILED", 0),
                    "canceled": counts.get("CANCELED", 0),
                    "recorded_idempotent_operations": duplicates}
