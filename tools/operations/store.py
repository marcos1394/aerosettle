"""Isolated, versioned SQLite state for Devnet telemetry and incidents."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import threading
import time
from typing import Iterator

from tools.economic_ledger.schema import split_sql_statements

MIGRATIONS = Path(__file__).resolve().parent / "migrations"
SAFE = re.compile(r"^[A-Za-z0-9_:/.*-]{1,180}$")


class OperationalIntegrityError(RuntimeError):
    pass


def safe(value: str) -> str:
    if not isinstance(value, str) or not SAFE.fullmatch(value):
        raise ValueError("Operational label contains unsupported or sensitive characters")
    return value


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True,
        separators=(",", ":")).encode()).hexdigest()


class OperationalStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.path, isolation_level=None,
                                  check_same_thread=False, timeout=10)
        try:
            self.db.row_factory = sqlite3.Row
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA busy_timeout=10000")
            self.db.execute("PRAGMA foreign_keys=ON")
            if self.db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise OperationalIntegrityError("Operational SQLite integrity check failed")
            self._migrate()
        except Exception:
            self.db.close()
            raise

    def close(self) -> None:
        self.db.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                yield self.db
                self.db.execute("COMMIT")
            except BaseException:
                self.db.execute("ROLLBACK")
                raise

    def _migrate(self) -> None:
        with self.transaction() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS operational_schema_migrations (
                version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at INTEGER NOT NULL)""")
        for file in sorted(MIGRATIONS.glob("*.sql")):
            version = int(file.name.split("_", 1)[0])
            if self.db.execute("SELECT 1 FROM operational_schema_migrations WHERE version=?",
                               (version,)).fetchone():
                continue
            with self.transaction() as db:
                for statement in split_sql_statements(file.read_text()):
                    db.execute(statement)
                db.execute("INSERT INTO operational_schema_migrations VALUES (?,?,?)",
                           (version, file.name, int(time.time())))
        self.validate_schema()

    def validate_schema(self) -> None:
        expected = {"observability_samples", "alert_rules", "alert_instances",
                    "incident_events", "provider_health"}
        actual = {row[0] for row in self.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        versions = [row[0] for row in self.db.execute(
            "SELECT version FROM operational_schema_migrations ORDER BY version")]
        if not expected <= actual or versions != [1]:
            raise OperationalIntegrityError("Operational SQLite schema is incomplete")
        required_columns = {
            "observability_samples": {"observed_at", "metric", "value", "quality", "scope"},
            "alert_rules": {"rule_id", "metric", "comparison", "threshold", "severity"},
            "alert_instances": {"alert_key", "rule_id", "scope", "state", "evidence_hash"},
            "incident_events": {"event_id", "alert_key", "event_type", "evidence_hash"},
            "provider_health": {"provider_id", "network", "genesis_hash", "state",
                                "opened_until", "half_open_lease_until"},
        }
        for table, required in required_columns.items():
            columns = {row[1] for row in self.db.execute(f"PRAGMA table_info({table})")}
            if not required <= columns:
                raise OperationalIntegrityError("Operational SQLite columns are incomplete")
        if self.db.execute("PRAGMA foreign_key_check").fetchone():
            raise OperationalIntegrityError("Operational SQLite foreign key mismatch")

    def sample(self, metric: str, value: float | int | None, unit: str, scope: str,
               *, quality: str = "OBSERVED", correlation_id: str | None = None,
               evidence_hash: str | None = None, now: int | None = None) -> int:
        metric, unit, scope = safe(metric), safe(unit), safe(scope)
        if quality not in {"OBSERVED", "ESTIMATED", "INSUFFICIENT_DATA"}:
            raise ValueError("Invalid metric quality")
        if (quality == "INSUFFICIENT_DATA") != (value is None):
            raise ValueError("Unavailable metrics must have null values")
        if value is not None and (not isinstance(value, (int, float)) or
                                  not math.isfinite(value)):
            raise ValueError("Metric value must be finite")
        if correlation_id is not None:
            safe(correlation_id)
        timestamp = int(time.time()) if now is None else now
        with self.transaction() as db:
            row = db.execute("""INSERT INTO observability_samples
                (observed_at,metric,value,unit,quality,scope,correlation_id,evidence_hash)
                VALUES (?,?,?,?,?,?,?,?)""",
                (timestamp, metric, value, unit, quality, scope,
                 correlation_id, evidence_hash))
            return row.lastrowid

    def latest(self, metric: str, scope: str, since: int) -> list[dict]:
        with self.lock:
            rows = self.db.execute("""SELECT * FROM observability_samples
                WHERE metric=? AND scope=? AND observed_at>=? ORDER BY sample_id""",
                (safe(metric), safe(scope), since)).fetchall()
        return [dict(row) for row in rows]

    def put_rule(self, rule: dict) -> None:
        fields = ("rule_id", "metric", "comparison", "threshold", "severity",
                  "window_seconds", "min_samples", "enabled")
        values = [rule[field] for field in fields]
        safe(values[0]); safe(values[1])
        if values[2] not in {"GT", "GTE", "LT", "LTE"} or \
                values[4] not in {"INFO", "WARNING", "CRITICAL"} or \
                not isinstance(values[3], (int, float)) or not math.isfinite(values[3]) or \
                values[5] <= 0 or values[6] <= 0 or values[7] not in (0, 1):
            raise ValueError("Invalid alert rule")
        with self.transaction() as db:
            db.execute("""INSERT INTO alert_rules
                (rule_id,metric,comparison,threshold,severity,window_seconds,min_samples,enabled)
                VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(rule_id) DO UPDATE SET
                metric=excluded.metric,comparison=excluded.comparison,
                threshold=excluded.threshold,severity=excluded.severity,
                window_seconds=excluded.window_seconds,min_samples=excluded.min_samples,
                enabled=excluded.enabled""", values)

    def rules(self) -> list[dict]:
        with self.lock:
            return [dict(row) for row in self.db.execute(
                "SELECT * FROM alert_rules WHERE enabled=1 ORDER BY rule_id")]

    def transition_alert(self, rule: dict, scope: str, value: float,
                         evidence_hash: str, triggered: bool, *, now: int | None = None) -> None:
        scope = safe(scope)
        timestamp = int(time.time()) if now is None else now
        key = digest([rule["rule_id"], scope])
        with self.transaction() as db:
            old = db.execute("SELECT * FROM alert_instances WHERE alert_key=?", (key,)).fetchone()
            if triggered:
                if old and old["evidence_hash"] == evidence_hash and old["state"] != "RESOLVED":
                    return
                if old:
                    event = "REOPENED" if old["state"] == "RESOLVED" else "UPDATED"
                    db.execute("""UPDATE alert_instances SET state='OPEN',severity=?,last_seen=?,
                        occurrences=occurrences+1,evidence_hash=?,observed_value=?
                        WHERE alert_key=?""",
                        (rule["severity"], timestamp, evidence_hash, value, key))
                else:
                    event = "OPENED"
                    db.execute("""INSERT INTO alert_instances VALUES
                        (?,?,?,'OPEN',?,?,?,?,?,?)""",
                        (key, rule["rule_id"], scope, rule["severity"], timestamp,
                         timestamp, 1, evidence_hash, value))
                db.execute("""INSERT OR IGNORE INTO incident_events
                    (alert_key,event_type,observed_at,evidence_hash,detail)
                    VALUES (?,?,?,?,?)""",
                    (key, event, timestamp, evidence_hash,
                     json.dumps({"metric": rule["metric"], "value": value}, sort_keys=True)))
            elif old and old["state"] != "RESOLVED":
                db.execute("UPDATE alert_instances SET state='RESOLVED',last_seen=? WHERE alert_key=?",
                           (timestamp, key))
                db.execute("""INSERT OR IGNORE INTO incident_events
                    (alert_key,event_type,observed_at,evidence_hash,detail)
                    VALUES (?,'RESOLVED',?,?,?)""",
                    (key, timestamp, evidence_hash, "Threshold no longer exceeded"))

    def alerts(self) -> list[dict]:
        with self.lock:
            return [dict(row) for row in self.db.execute(
                "SELECT * FROM alert_instances ORDER BY last_seen DESC,alert_key")]

    def incidents(self) -> list[dict]:
        with self.lock:
            return [dict(row) for row in self.db.execute(
                "SELECT * FROM incident_events ORDER BY event_id")]

    def provider(self, provider_id: str, network: str, genesis_hash: str) -> dict:
        provider_id = safe(provider_id)
        with self.transaction() as db:
            db.execute("""INSERT OR IGNORE INTO provider_health
                (provider_id,network,genesis_hash,state,updated_at)
                VALUES (?,?,?,'CLOSED',?)""",
                (provider_id, safe(network), safe(genesis_hash), int(time.time())))
            row = db.execute("SELECT * FROM provider_health WHERE provider_id=?",
                             (provider_id,)).fetchone()
            if row["network"] != network or row["genesis_hash"] != genesis_hash:
                raise OperationalIntegrityError("Provider identity changed")
            return dict(row)

    def prune_samples(self, older_than: int, *, batch: int = 1000) -> int:
        if batch < 1 or batch > 10000:
            raise ValueError("Invalid retention batch")
        with self.transaction() as db:
            cursor = db.execute("""DELETE FROM observability_samples WHERE sample_id IN
                (SELECT sample_id FROM observability_samples WHERE observed_at<?
                 ORDER BY sample_id LIMIT ?)""", (older_than, batch))
            return cursor.rowcount
