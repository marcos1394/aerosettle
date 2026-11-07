"""Atomic sandbox settlement and delivery journal, separate from the economic ledger."""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

from .common import SandboxError, digest


class SandboxStore:
    def __init__(self, path: str | Path):
        self.conn = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False, timeout=10)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self.conn.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS sandbox_settlements (
              payment_id TEXT PRIMARY KEY, nonce TEXT NOT NULL UNIQUE,
              requirements_hash TEXT NOT NULL UNIQUE, payload_hash TEXT NOT NULL UNIQUE,
              client_agent_account TEXT NOT NULL, provider_agent_account TEXT NOT NULL,
              resource_id TEXT NOT NULL, resource_url TEXT NOT NULL,
              network TEXT NOT NULL, genesis_hash TEXT NOT NULL, program_id TEXT NOT NULL,
              asset TEXT NOT NULL, amount TEXT NOT NULL, pay_to TEXT NOT NULL,
              settlement_intent TEXT NOT NULL, receipt_id TEXT NOT NULL UNIQUE,
              receipt_json TEXT NOT NULL, record_hash TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sandbox_deliveries (
              payment_id TEXT PRIMARY KEY REFERENCES sandbox_settlements(payment_id),
              requirements_hash TEXT NOT NULL, resource_id TEXT NOT NULL,
              resource_hash TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sandbox_client_receipts (
              receipt_id TEXT PRIMARY KEY, payment_id TEXT NOT NULL UNIQUE,
              requirements_hash TEXT NOT NULL, payload_hash TEXT NOT NULL,
              receipt_json TEXT NOT NULL, record_hash TEXT NOT NULL
            );
        """)

    def close(self):
        self.conn.close()

    @staticmethod
    def _check(row: sqlite3.Row) -> dict:
        data = dict(row)
        if digest({k: v for k, v in data.items() if k != "record_hash"}) != data["record_hash"]:
            raise SandboxError("AUDIT_INTEGRITY_CONFLICT", 409)
        return data

    def settlement(self, payment_id: str) -> dict | None:
        with self.lock:
            row = self.conn.execute("SELECT * FROM sandbox_settlements WHERE payment_id=?", (payment_id,)).fetchone()
            return self._check(row) if row else None

    def settle(self, record: dict) -> tuple[dict, bool]:
        with self.lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                existing = self.conn.execute("SELECT * FROM sandbox_settlements WHERE payment_id=? OR nonce=? OR "
                    "requirements_hash=? OR payload_hash=? OR receipt_id=?", (
                    record["payment_id"], record["nonce"], record["requirements_hash"],
                    record["payload_hash"], record["receipt_id"])).fetchone()
                if existing:
                    prior = self._check(existing)
                    if any(prior[k] != record[k] for k in record):
                        raise SandboxError("REPLAY_CONFLICT", 409)
                    self.conn.execute("COMMIT")
                    return prior, False
                row = {**record, "record_hash": digest(record)}
                columns = list(row)
                self.conn.execute(f"INSERT INTO sandbox_settlements ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                                  tuple(row[k] for k in columns))
                self.conn.execute("COMMIT")
                return row, True
            except sqlite3.IntegrityError as exc:
                self.conn.execute("ROLLBACK")
                raise SandboxError("REPLAY_CONFLICT", 409) from exc
            except Exception:
                self.conn.execute("ROLLBACK")
                raise

    def deliver(self, payment_id: str, requirements_hash: str, resource_id: str, resource_hash: str) -> bool:
        with self.lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                prior = self.conn.execute("SELECT * FROM sandbox_deliveries WHERE payment_id=?", (payment_id,)).fetchone()
                if prior:
                    if dict(prior) != {"payment_id": payment_id, "requirements_hash": requirements_hash,
                                       "resource_id": resource_id, "resource_hash": resource_hash}:
                        raise SandboxError("DELIVERY_CONFLICT", 409)
                    self.conn.execute("COMMIT")
                    return False
                if self.settlement(payment_id) is None:
                    raise SandboxError("SETTLEMENT_MISSING", 409)
                self.conn.execute("INSERT INTO sandbox_deliveries VALUES (?,?,?,?)",
                                  (payment_id, requirements_hash, resource_id, resource_hash))
                self.conn.execute("COMMIT")
                return True
            except Exception:
                self.conn.execute("ROLLBACK")
                raise

    def save_client_receipt(self, receipt: dict) -> bool:
        row = {"receipt_id": receipt["receipt_id"], "payment_id": receipt["payment_id"],
               "requirements_hash": receipt["payment_requirements_hash"],
               "payload_hash": receipt["payment_payload_hash"],
               "receipt_json": json.dumps(receipt, sort_keys=True, separators=(",", ":"))}
        row["record_hash"] = digest({k: v for k, v in row.items() if k != "record_hash"})
        with self.lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                old = self.conn.execute("SELECT * FROM sandbox_client_receipts WHERE receipt_id=? OR payment_id=?",
                                        (row["receipt_id"], row["payment_id"])).fetchone()
                if old:
                    if self._check(old) != row:
                        raise SandboxError("RECEIPT_CONFLICT", 409)
                    self.conn.execute("COMMIT")
                    return False
                self.conn.execute("INSERT INTO sandbox_client_receipts VALUES (?,?,?,?,?,?)", tuple(row.values()))
                self.conn.execute("COMMIT")
                return True
            except Exception:
                self.conn.execute("ROLLBACK")
                raise
