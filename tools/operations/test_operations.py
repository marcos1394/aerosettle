"""Adversarial operational controls; no network calls or transactions."""
from __future__ import annotations

import base64
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from tools.deployment import devnet
from tools.economic_ledger.devnet_ingestion import DevnetIngestor, Scope
from tools.economic_ledger.spl_reconciler import (
    RpcError, SolanaRpcClient, b58decode,
)
from tools.operations.structured_logs import correlation_id, structured_event
from tools.operations.rpc_policy import (
    CircuitOpen, ProviderController, RequestLimit, RpcObserver, monitored_client,
)
from tools.operations.service import (
    collect_ledger, collect_rpc, evaluate_alerts, health, inspect_security,
    install_rules, load_config, percentile, readiness,
)
from tools.operations.store import OperationalStore, OperationalIntegrityError

WORK_ORDER = "2M2gMx8n5jDJ7ivKnLRxGVJepBAUst74vDuYZid4xRPr"


class OperationalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = TemporaryDirectory()
        self.path = Path(self.folder.name) / "ops.sqlite"
        self.store = OperationalStore(self.path)
        self.config = load_config()
        install_rules(self.store, self.config)

    def tearDown(self) -> None:
        self.store.close()
        self.folder.cleanup()

    def test_migration_restart_and_isolation(self) -> None:
        self.assertEqual(self.store.db.execute(
            "SELECT version FROM operational_schema_migrations").fetchone()[0], 1)
        sample_id = self.store.sample("rpc_duration_ms", 12.5, "ms", "official-devnet")
        self.store.close()
        self.store = OperationalStore(self.path)
        self.assertEqual(self.store.latest("rpc_duration_ms", "official-devnet", 0)[0]["sample_id"],
                         sample_id)
        self.assertEqual(self.store.db.execute(
            "SELECT count(*) FROM alert_rules").fetchone()[0], len(self.config["rules"]))

    def test_null_quality_and_no_fabricated_latency(self) -> None:
        self.assertIsNone(collect_rpc(self.store)["latency_ms"]["p95"])
        with self.assertRaises(ValueError):
            self.store.sample("rpc_duration_ms", 10, "ms", "official-devnet",
                              quality="INSUFFICIENT_DATA")
        self.assertEqual(percentile([1, 2, 3, 4], .95), 4)

    def test_alert_deduplication_resolution_and_reopen(self) -> None:
        rule = next(row for row in self.store.rules()
                    if row["rule_id"] == "economic_difference")
        self.store.sample(rule["metric"], 1, "incidents", "devnet", now=100)
        evaluate_alerts(self.store, now=100)
        evaluate_alerts(self.store, now=100)
        alert = next(row for row in self.store.alerts()
                     if row["rule_id"] == "economic_difference")
        self.assertEqual((alert["state"], alert["occurrences"]), ("OPEN", 1))
        self.store.sample(rule["metric"], 0, "incidents", "devnet", now=101)
        evaluate_alerts(self.store, now=101)
        self.assertEqual(next(row for row in self.store.alerts()
            if row["rule_id"] == "economic_difference")["state"], "RESOLVED")
        self.store.sample(rule["metric"], 2, "incidents", "devnet", now=102)
        evaluate_alerts(self.store, now=102)
        events = [row["event_type"] for row in self.store.incidents()
                  if row["alert_key"] == alert["alert_key"]]
        self.assertEqual(events, ["OPENED", "RESOLVED", "REOPENED"])

    def test_newer_insufficient_sample_cannot_promote_stale_alert(self) -> None:
        self.store.sample("genesis_mismatch", 1, "boolean", "devnet", now=100)
        self.store.sample("genesis_mismatch", None, "boolean", "devnet",
                          quality="INSUFFICIENT_DATA", now=101)
        evaluated = evaluate_alerts(self.store, now=101)
        row = next(item for item in evaluated if item["rule_id"] == "genesis_changed"
                   and item["scope"] == "devnet")
        self.assertEqual(row["status"], "INSUFFICIENT_DATA")
        self.assertFalse(any(item["rule_id"] == "genesis_changed"
                             for item in self.store.alerts()))

    def test_concurrent_alert_evaluation_is_idempotent(self) -> None:
        self.store.sample("genesis_mismatch", 1, "boolean", "devnet", now=100)
        threads = [threading.Thread(target=evaluate_alerts,
                   args=(self.store,), kwargs={"now": 100}) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        matches = [row for row in self.store.alerts()
                   if row["rule_id"] == "genesis_changed"]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["occurrences"], 1)

    def test_retention_keeps_audit_events(self) -> None:
        self.store.sample("rpc_duration_ms", 1, "ms", "official-devnet", now=1)
        self.store.sample("rpc_duration_ms", 2, "ms", "official-devnet", now=2)
        self.assertEqual(self.store.prune_samples(2), 1)
        self.assertEqual(len(self.store.latest("rpc_duration_ms", "official-devnet", 0)), 1)

    def test_secret_redaction_and_trace_identity(self) -> None:
        event = structured_event("INFO", "devnet_operations", "inspect",
            correlation_id=correlation_id("scope", "signature"), trace_id="abc")
        self.assertNotIn("signature", json.dumps(event))
        with self.assertRaises(ValueError):
            structured_event("INFO", "ops", "inspect", rpc_url="https://secret?key=private")
        with self.assertRaises(ValueError):
            structured_event("ERROR", "ops", "inspect", error_code="seed phrase private")

    def test_invalid_config_and_corrupt_sqlite_fail_closed(self) -> None:
        bad = {**self.config, "genesis_hash": "wrong"}
        config_path = Path(self.folder.name) / "bad.json"
        config_path.write_text(json.dumps(bad))
        with self.assertRaises(ValueError):
            load_config(config_path)
        corrupt = Path(self.folder.name) / "corrupt.sqlite"
        corrupt.write_bytes(b"not a sqlite database")
        with self.assertRaises(sqlite3.DatabaseError):
            OperationalStore(corrupt)

    def test_locked_sqlite_does_not_touch_economic_ledger(self) -> None:
        locker = sqlite3.connect(self.path)
        try:
            locker.execute("BEGIN EXCLUSIVE")
            self.store.db.execute("PRAGMA busy_timeout=1")
            with self.assertRaises(sqlite3.OperationalError):
                self.store.sample("rpc_requests_total", 1, "calls", "official-devnet")
        finally:
            locker.rollback()
            locker.close()

    def test_ledger_read_only_and_missing_data(self) -> None:
        ledger_path = Path(self.folder.name) / "ledger.sqlite"
        self.assertEqual(collect_ledger(self.store, ledger_path)["status"],
                         "INSUFFICIENT_DATA")
        ingestor = DevnetIngestor(ledger_path)
        scope = Scope(WORK_ORDER, 10, 30)
        ingestor._checkpoint(scope)
        ingestor.close()
        before = ledger_path.read_bytes()
        result = collect_ledger(self.store, ledger_path)
        self.assertEqual(result["metrics"]["movements_reconciled"]["value"], 0)
        self.assertEqual(result["metrics"]["duplicate_effect_count"]["value"], 0)
        self.assertEqual(result["metrics"]["historical_recovery_seconds"]["quality"],
                         "INSUFFICIENT_DATA")
        self.assertEqual(ledger_path.read_bytes(), before)
        self.assertEqual(result["metrics"]["block_to_ingest_p95_seconds"]["quality"],
                         "INSUFFICIENT_DATA")

    def test_stalled_explicit_scope_and_economic_difference_alert(self) -> None:
        ledger_path = Path(self.folder.name) / "ledger.sqlite"
        ingestor = DevnetIngestor(ledger_path)
        scope = Scope(WORK_ORDER, 10, 30)
        ingestor._checkpoint(scope)
        ingestor.db.execute("UPDATE ingestion_checkpoints SET last_successful_sync=? "
                            "WHERE scope_id=?", (int(time.time()) - 4000, scope.scope_id))
        ingestor._incident(scope, "sig-test", 20, "ECONOMIC_DIFFERENCE",
                           "amount mismatch")
        ingestor.close()
        config = {**self.config, "active_scope_ids": [scope.scope_id]}
        result = collect_ledger(self.store, ledger_path, config=config)
        self.assertEqual(result["metrics"]["checkpoint_stalled_count"]["value"], 1)
        self.assertEqual(result["metrics"]["economic_difference_count"]["value"], 1)
        self.assertEqual(result["metrics"]["movements_reconciled"]["value"], 0)
        self.assertEqual(result["source_incidents"][0]["correlation_id"],
                         correlation_id(scope.label, "sig-test"))
        evaluate_alerts(self.store)
        self.assertTrue(any(row["rule_id"] == "economic_difference" and
                            row["severity"] == "CRITICAL" for row in self.store.alerts()))

    def test_readiness_separates_liveness_and_safety(self) -> None:
        self.assertEqual(health()["status"], "HEALTHY")
        ledger_path = Path(self.folder.name) / "ledger.sqlite"
        ingestor = DevnetIngestor(ledger_path)
        scope = Scope(WORK_ORDER, 10, 30)
        ingestor._checkpoint(scope)
        ingestor.close()
        self.store.provider("official-devnet", "solana:devnet",
                            self.config["genesis_hash"])
        matches = {name: {"status": "MATCH"} for name in
            ("genesis", "program", "programdata", "upgrade_authority",
             "mint", "protocol_config", "test_wallet")}
        rpc = SolanaRpcClient("https://api.devnet.solana.com")
        with patch("tools.operations.service.inspect_security", return_value=matches):
            self.assertEqual(readiness(self.store, rpc, self.config, ledger_path)["status"],
                             "HEALTHY")
            self.assertEqual(readiness(self.store, rpc, self.config,
                Path(self.folder.name) / "absent.sqlite")["status"], "NOT_READY")
            low = {**matches, "test_wallet": {"status": "LOW_BALANCE"}}
        with patch("tools.operations.service.inspect_security", return_value=low):
            self.assertEqual(readiness(self.store, rpc, self.config, ledger_path)["status"],
                             "DEGRADED")

    def test_security_mismatch_and_low_balance_are_classified(self) -> None:
        rpc = SolanaRpcClient("https://api.devnet.solana.com")
        mint_evidence = json.loads(Path("evidence/con35/test-mint-verified.json").read_text())
        raw = bytearray(155)
        raw[:8] = __import__("hashlib").sha256(b"account:ProtocolConfig").digest()[:8]
        raw[8] = 1
        raw[9:41] = b58decode("27cyzd58RswQRbSuR3cKh4xv2gWgZ7awb3tUtoT7hYLB", 32)
        raw[41:73] = bytes.fromhex(
            "ce59db5080fc2c6d3bcf7ca90712d3c2e5e6c28f27f0dfbb9953bdb0894c03ab")
        raw[73:105] = b58decode(self.config["program_id"], 32)
        raw[105:137] = bytes.fromhex(
            "06c7dfa7528460969a5ca1e8bd001f9c9f1f1f0df3d69fe36649e413e0b14ae6")
        raw[137] = 255
        account = {"owner": self.config["program_id"],
                   "data": [base64.b64encode(raw).decode(), "base64"]}
        program = {"exists": True, "program_id": self.config["program_id"],
                   "program_data_address": "programdata",
                   "upgrade_authority_pubkey": "DdHrtAxE5SwcVQUgoKRzoWatZ5yw9UdtBQnRwBizPK2D"}
        with patch.object(rpc, "get_genesis_hash", return_value=self.config["genesis_hash"]), \
             patch("tools.operations.service.devnet.inspect_program", return_value=program), \
             patch("tools.operations.service.devnet.binary_matches_deployed", return_value=False), \
             patch("tools.operations.service.test_mint.verify", return_value=mint_evidence), \
             patch.object(rpc, "get_account_info", return_value=account), \
             patch.object(rpc, "_call", return_value={"value": 1}):
            result = inspect_security(rpc, self.store, self.config)
        self.assertEqual(result["genesis"]["status"], "MATCH")
        self.assertEqual(result["programdata"]["status"], "MISMATCH")
        self.assertEqual(result["test_wallet"]["status"], "LOW_BALANCE")
        self.assertEqual(result["protocol_config"]["status"], "MATCH")
        evaluate_alerts(self.store)
        self.assertTrue(any(row["rule_id"] == "programdata_changed" and
                            row["severity"] == "CRITICAL" for row in self.store.alerts()))

    def test_wrong_genesis_stops_dependent_security_claims(self) -> None:
        rpc = SolanaRpcClient("https://api.devnet.solana.com")
        with patch.object(rpc, "get_genesis_hash", return_value="wrong"), \
             patch("tools.operations.service.devnet.inspect_program",
                   side_effect=AssertionError("must not inspect a foreign network")):
            result = inspect_security(rpc, self.store, self.config)
        self.assertEqual(result["genesis"]["status"], "MISMATCH")
        self.assertEqual(result["program"]["status"], "INSUFFICIENT_DATA")
        self.assertEqual(result["mint"]["status"], "INSUFFICIENT_DATA")
        evaluate_alerts(self.store)
        self.assertIn("genesis_changed", {row["rule_id"] for row in self.store.alerts()})

    def test_upgrade_authority_and_mint_rejection(self) -> None:
        rpc = SolanaRpcClient("https://api.devnet.solana.com")
        with patch.object(rpc, "get_genesis_hash", return_value=self.config["genesis_hash"]), \
             patch("tools.operations.service.devnet.inspect_program",
                   side_effect=devnet.DeploymentError("Unrecognized upgrade authority")), \
             patch("tools.operations.service.test_mint.verify",
                   side_effect=devnet.DeploymentError("Invalid mint")), \
             patch.object(rpc, "get_account_info", return_value=None), \
             patch.object(rpc, "_call", return_value={"value": 1}):
            result = inspect_security(rpc, self.store, self.config)
        self.assertEqual(result["upgrade_authority"]["status"], "MISMATCH")
        self.assertEqual(result["mint"]["status"], "MISMATCH")
        evaluate_alerts(self.store)
        self.assertEqual({row["rule_id"] for row in self.store.alerts()} &
                         {"upgrade_authority_changed", "mint_changed"},
                         {"upgrade_authority_changed", "mint_changed"})


class CircuitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = TemporaryDirectory()
        self.path = Path(self.folder.name) / "ops.sqlite"
        self.store = OperationalStore(self.path)
        self.now = 100
        self.controller = ProviderController(self.store, failure_threshold=2,
            cooldown_seconds=10, clock=lambda: self.now, max_requests_per_minute=10)

    def tearDown(self) -> None:
        self.store.close()
        self.folder.cleanup()

    def test_open_restart_half_open_closed(self) -> None:
        self.controller.before_call(); self.controller.after_call(False, "HTTP_503")
        self.controller.before_call(); self.controller.after_call(False, "HTTP_503")
        self.assertEqual(self.controller.state()["state"], "OPEN")
        with self.assertRaises(CircuitOpen):
            self.controller.before_call()
        self.store.close()
        self.store = OperationalStore(self.path)
        self.controller = ProviderController(self.store, failure_threshold=2,
            cooldown_seconds=10, clock=lambda: self.now, max_requests_per_minute=10)
        with self.assertRaises(CircuitOpen):
            self.controller.before_call()
        self.now = 111
        self.controller.before_call()
        self.assertEqual(self.controller.state()["state"], "HALF_OPEN")
        with self.assertRaises(CircuitOpen):
            self.controller.before_call()
        self.controller.after_call(True, None)
        self.assertEqual(self.controller.state()["state"], "CLOSED")

    def test_rate_and_concurrency_limits(self) -> None:
        self.controller.before_call()
        controller = ProviderController(self.store, max_requests_per_minute=1,
            max_concurrency=1, clock=lambda: self.now)
        with self.assertRaises(RequestLimit):
            controller.before_call()
        self.controller.after_call(True, None)
        with self.assertRaises(RequestLimit):
            controller.before_call()

    def test_timeout_429_503_and_observer(self) -> None:
        client = monitored_client(self.store, self.controller, retry_budget=1,
                                  min_interval=0)
        failures = [
            HTTPError("https://api.devnet.solana.com", 429, "rate", {}, None),
            HTTPError("https://api.devnet.solana.com", 503, "unavailable", {}, None),
        ]
        with patch("tools.economic_ledger.spl_reconciler.urllib.request.urlopen",
                   side_effect=failures), \
             patch("tools.economic_ledger.spl_reconciler.time.sleep"):
            with self.assertRaises(RpcError):
                client.get_genesis_hash()
        rpc = collect_rpc(self.store, now=int(__import__("time").time()))
        self.assertEqual((rpc["http_429"], rpc["http_5xx"], rpc["retries"]), (1, 1, 1))
        with patch("tools.economic_ledger.spl_reconciler.urllib.request.urlopen",
                   side_effect=TimeoutError("timeout")), \
             patch("tools.economic_ledger.spl_reconciler.time.sleep"):
            with self.assertRaises(RpcError):
                client.get_genesis_hash()
        self.assertEqual(collect_rpc(self.store)["timeouts"], 2)
        self.assertEqual(self.controller.state()["state"], "OPEN")

    def test_telemetry_failure_does_not_change_rpc_result(self) -> None:
        def broken_observer(*args):
            raise sqlite3.OperationalError("telemetry disk unavailable")
        client = SolanaRpcClient("https://api.devnet.solana.com",
                                 request_observer=broken_observer)
        with patch.object(client, "_transport_call", return_value="genesis"):
            self.assertEqual(client.get_genesis_hash(), "genesis")


if __name__ == "__main__":
    unittest.main()
