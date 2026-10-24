"""CON-27 policy configuration, persistence, authentication and accounting isolation."""
import copy
import concurrent.futures
import sqlite3
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock
from cryptography.hazmat.primitives.asymmetric import ed25519 as crypto_ed25519

from tools.discovery import agent_discovery as discovery
from tools.economic_ledger.budget_policies import (
    BudgetPolicyStore, PolicyError, digest, mutation_message, normalized_config,
    verify_mutation,
)
from tools.economic_ledger.ed25519 import public_key_from_secret
from tools.economic_ledger.ledger import EconomicLedger, LOCALNET_GENESIS_HASH, DEFAULT_PROGRAM_ID
from tools.economic_ledger import schema


SECRET = b"\x01" * 32
OWNER = discovery.b58encode(public_key_from_secret(SECRET))
OTHER_SECRET = b"\x02" * 32
OTHER = discovery.b58encode(public_key_from_secret(OTHER_SECRET))
AGENT = "DcusvnYAdFFKzNDVzUkUvmgZ9fDhzszeRR5Fj8F5dMbB"
MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
MINT_TWO = "So11111111111111111111111111111111111111112"
AGENT_RECORD = {"agent_account": AGENT, "agent_id": "11" * 32, "owner": OWNER}


def config():
    now = int(time.time())
    return {
        "network": "solana:localnet", "genesis_hash": LOCALNET_GENESIS_HASH,
        "program_id": DEFAULT_PROGRAM_ID,
        "asset_rules": [{
            "token_mint": MINT, "max_per_operation_base_units_str": "9007199254740993",
            "max_daily_spend_base_units_str": "18446744073709551615",
            "minimum_reserve_base_units_str": "2500000", "enabled": True,
        }],
        "allowed_recipients": [OTHER],
        "valid_from": now - 10, "expires_at": now + 3600,
    }


def body(action="CREATE", expected=0, suffix="00000001", **changes):
    data = {
        "expected_version": expected, "idempotency_key": f"policy-idem-{suffix}",
        "nonce": f"policy-nonce-{suffix}-unique",
    }
    if action in ("CREATE", "UPDATE"):
        data.update(config())
    data.update(changes)
    return data


def headers(body_value, method="POST", path=f"/v1/agents/{AGENT}/budget-policy",
            secret=SECRET, signer=OWNER):
    ts = int(time.time())
    signature = crypto_ed25519.Ed25519PrivateKey.from_private_bytes(secret).sign(
        mutation_message(ts, AGENT, signer, method, path, body_value))
    return {"X-Signer-Pubkey": signer, "X-Timestamp": str(ts),
            "X-Signature": discovery.b58encode(signature)}


class BudgetPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "ledger.db"
        self.ledger = EconomicLedger(self.path)
        self.store = BudgetPolicyStore(self.ledger)

    def tearDown(self):
        self.ledger.close()
        self.temp.cleanup()

    def apply(self, action, value):
        return self.store.mutate(AGENT_RECORD, action, value, OWNER)[0]

    def test_validation_and_canonical_hash(self):
        one = config()
        normalized = normalized_config(one)
        self.assertEqual(normalized["asset_rules"][0]["max_per_operation_base_units_str"], "9007199254740993")
        multi = copy.deepcopy(one)
        multi["asset_rules"].append({**multi["asset_rules"][0], "token_mint": MINT_TWO, "enabled": False})
        self.assertEqual(len(normalized_config(multi)["asset_rules"]), 2)
        self.assertEqual(digest(normalized_config(multi)), digest(normalized_config({**multi, "asset_rules": list(reversed(multi["asset_rules"]))})))
        self.assertEqual(normalized_config({**one, "allowed_recipients": []})["allowed_recipients"], [])
        for bad in ("-1", "18446744073709551616", "1.5", 5):
            invalid = copy.deepcopy(one)
            invalid["asset_rules"][0]["minimum_reserve_base_units_str"] = bad
            with self.assertRaises(PolicyError):
                normalized_config(invalid)
        for invalid in (
            {**one, "allowed_recipients": [OTHER, OTHER]},
            {**one, "allowed_recipients": ["not-a-pubkey"]},
            {**one, "expires_at": one["valid_from"]},
            {**one, "asset_rules": one["asset_rules"] * 2},
            {**one, "genesis_hash": "PENDING_RESOLUTION"},
        ):
            with self.assertRaises(PolicyError):
                normalized_config(invalid)

    def test_lifecycle_history_idempotency_and_accounting_isolation(self):
        tables = ("economic_movements", "journal_entries", "ledger_entries", "agent_reserves",
                  "reserve_transactions", "agent_costs")
        before = {table: self.ledger._conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in tables}
        first_body = body()
        draft = self.apply("CREATE", first_body)
        self.assertEqual((draft["version"], draft["status"]), (1, "DRAFT"))
        self.assertFalse(draft["is_currently_valid"])
        retry, created = self.store.mutate(AGENT_RECORD, "CREATE", first_body, OWNER)
        self.assertFalse(created)
        self.assertEqual(retry["policy_hash"], draft["policy_hash"])
        active = self.apply("ACTIVATE", body("ACTIVATE", 1, "00000002"))
        self.assertTrue(active["is_currently_valid"])
        updated_body = body("UPDATE", 2, "00000003")
        updated_body["asset_rules"][0]["max_per_operation_base_units_str"] = "50"
        updated = self.apply("UPDATE", updated_body)
        self.assertEqual(updated["version"], 3)
        self.assertEqual(self.store.version(AGENT_RECORD, 1)["asset_rules"][0]["max_per_operation_base_units_str"], "9007199254740993")
        self.assertNotEqual(updated["policy_hash"], draft["policy_hash"])
        paused = self.apply("PAUSE", body("PAUSE", 3, "00000004"))
        self.assertEqual(paused["status"], "PAUSED")
        resumed = self.apply("RESUME", body("RESUME", 4, "00000005"))
        self.assertEqual(resumed["status"], "ACTIVE")
        revoked = self.apply("REVOKE", body("REVOKE", 5, "00000006"))
        self.assertEqual(revoked["status"], "REVOKED")
        self.assertEqual(len(self.store.history(AGENT_RECORD)), 6)
        with self.assertRaises(PolicyError):
            self.apply("RESUME", body("RESUME", 6, "00000007"))
        after = {table: self.ledger._conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in tables}
        self.assertEqual(before, after)
        self.assertEqual(self.store.reserve_comparison(draft)[0]["accounting_reserved_base_units_str"], "0")
        self.assertIsNone(self.store.reserve_comparison(draft)[0]["ledger_available_balance_str"])
        self.ledger.close()
        self.ledger = EconomicLedger(self.path)
        self.store = BudgetPolicyStore(self.ledger)
        self.assertEqual(self.store.current(AGENT_RECORD)["status"], "REVOKED")
        self.assertEqual(len(self.store.history(AGENT_RECORD)), 6)

    def test_conflicts_replay_owner_change_and_expiration(self):
        first = body()
        self.apply("CREATE", first)
        with self.assertRaisesRegex(PolicyError, "Idempotency key reused"):
            self.apply("CREATE", {**first, "nonce": "different-nonce-unique"})
        with self.assertRaisesRegex(PolicyError, "nonce was already used"):
            self.apply("ACTIVATE", {**body("ACTIVATE", 1, "00000002"), "nonce": first["nonce"]})
        self.apply("ACTIVATE", body("ACTIVATE", 1, "00000002"))
        with self.assertRaisesRegex(PolicyError, "version has changed"):
            self.apply("PAUSE", body("PAUSE", 1, "00000003"))
        self.assertEqual(self.store.current(AGENT_RECORD)["version"], 2)
        rotated = {**AGENT_RECORD, "owner": OTHER}
        with self.assertRaises(PolicyError):
            self.store.current(rotated)
        with self.assertRaises(PolicyError):
            self.store.mutate(rotated, "PAUSE", body("PAUSE", 2, "00000004"), OTHER)
        with mock.patch("tools.economic_ledger.budget_policies.time.time", return_value=first["expires_at"] + 1):
            self.assertEqual(self.store.current(AGENT_RECORD)["effective_status"], "EXPIRED")
            self.assertFalse(self.store.current(AGENT_RECORD)["is_currently_valid"])
        with self.assertRaises(sqlite3.IntegrityError):
            self.ledger._conn.execute("UPDATE agent_budget_policy_versions SET status = 'DRAFT' WHERE version = 2")
        with self.assertRaises(sqlite3.IntegrityError):
            self.ledger._conn.execute("UPDATE agent_budget_policies SET owner_pubkey = ? WHERE agent_account = ?", (OTHER, AGENT))
        with self.assertRaises(sqlite3.IntegrityError):
            self.ledger._conn.execute("DELETE FROM agent_budget_policies WHERE agent_account = ?", (AGENT,))

    def test_signature_binds_body_method_path_owner_and_freshness(self):
        value = body()
        path = f"/v1/agents/{AGENT}/budget-policy"
        valid = headers(value)
        self.assertEqual(verify_mutation(AGENT_RECORD, "POST", path, value, valid), OWNER)
        for method, request_path, request_body in (
            ("PUT", path, value), ("POST", path + "/pause", value),
            ("POST", path, {**value, "expires_at": value["expires_at"] + 1}),
        ):
            with self.assertRaises(PolicyError):
                verify_mutation(AGENT_RECORD, method, request_path, request_body, valid)
        with self.assertRaises(PolicyError):
            verify_mutation(AGENT_RECORD, "POST", path, value, headers(value, secret=OTHER_SECRET, signer=OTHER))
        with self.assertRaises(PolicyError):
            verify_mutation(AGENT_RECORD, "POST", path, value, {"X-Signer-Pubkey": OWNER})
        with self.assertRaises(PolicyError):
            verify_mutation(AGENT_RECORD, "POST", path, value, valid, now=int(time.time()) + 400)

    def test_concurrent_versions_and_failed_write_roll_back(self):
        self.apply("CREATE", body())
        inputs = [body("UPDATE", 1, "00000002"), body("UPDATE", 1, "00000003")]
        def attempt(item):
            try:
                return self.store.mutate(AGENT_RECORD, "UPDATE", item, OWNER)[0]
            except PolicyError as exc:
                return exc
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(attempt, inputs))
        # A strict expected-version race has one winner; the second must conflict.
        self.assertEqual(sum(isinstance(item, dict) and item["version"] == 2 for item in outcomes), 1)
        self.assertEqual(sum(isinstance(item, PolicyError) and item.status == 409 for item in outcomes), 1)
        self.ledger._conn.execute("""CREATE TRIGGER force_rule_failure BEFORE INSERT ON agent_budget_policy_asset_rules
            WHEN NEW.version = 3 BEGIN SELECT RAISE(ABORT, 'forced test failure'); END;""")
        with self.assertRaises(sqlite3.IntegrityError):
            self.apply("UPDATE", body("UPDATE", 2, "00000004"))
        self.assertEqual(self.store.current(AGENT_RECORD)["version"], 2)
        self.assertEqual(len(self.store.history(AGENT_RECORD)), 2)

    def test_upgrade_from_008_and_context_isolation(self):
        prior = Path(self.temp.name) / "prior"
        prior.mkdir()
        for migration in schema.MIGRATIONS_DIR.glob("*.sql"):
            if int(migration.name[:3]) <= 8:
                shutil.copy2(migration, prior / migration.name)
        upgrade_path = Path(self.temp.name) / "upgrade.db"
        with mock.patch.object(schema, "MIGRATIONS_DIR", prior):
            prior_ledger = EconomicLedger(upgrade_path)
            self.assertEqual(prior_ledger._conn.execute("SELECT max(version) FROM schema_migrations").fetchone()[0], 8)
            prior_ledger.close()
        upgraded = EconomicLedger(upgrade_path)
        self.assertEqual(upgraded._conn.execute("SELECT max(version) FROM schema_migrations").fetchone()[0], 9)
        upgraded.close()
        self.apply("CREATE", body())
        other_agent = {**AGENT_RECORD, "agent_account": MINT_TWO}
        other = self.store.mutate(other_agent, "CREATE", body("CREATE", 0, "00000002"), OWNER)[0]
        self.assertNotEqual(other["policy_id"], self.store.current(AGENT_RECORD)["policy_id"])
        changed = body("UPDATE", 1, "00000003", genesis_hash="EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG",
                       network="solana:devnet")
        with self.assertRaises(PolicyError):
            self.apply("UPDATE", changed)
        self.assertEqual(self.store.current(AGENT_RECORD)["version"], 1)


if __name__ == "__main__":
    unittest.main()
