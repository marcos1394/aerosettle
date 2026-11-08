"""Adversarial CON-45 tests; no test submits or recognizes an on-chain payment."""
from __future__ import annotations

import copy
import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock

from tools.discovery.agent_discovery import b58encode
from tools.x402.common import Context, digest
from tools.x402.demo import FINANCIAL_TABLES, fixtures, run_demo
from tools.economic_ledger.ledger import EconomicLedger
from tools.economic_ledger.spl_reconciler import SolanaRpcClient
from tools.economic_ledger.x402_reconciliation import (
    OFFICIAL_DEVNET_RPC, X402EconomicStore, X402IntegrityError, canonical_effect_id)
from tools.economic_ledger.x402_reconciliation_demo import run_reconciliation_demo


class X402ReconciliationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = run_demo(include_artifacts=True)
        cls.receipt = cls.source["signed_receipt"]
        cls.context = Context.fixture()
        cls.signature = b58encode(bytes([7]) * 64)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "ledger.sqlite"
        self.agents = fixtures(self.context)
        self.ledger = EconomicLedger(self.path)
        self.store = X402EconomicStore(self.ledger, self.context,
                                       self.source["facilitator_pubkey"], self.agents.get)

    def tearDown(self):
        self.store.close()
        self.ledger.close()
        self.tmp.cleanup()

    def imported(self):
        return self.store.import_sandbox_receipt(self.receipt)

    def read(self):
        return self.store.get(self.receipt["payment_id"],
                              self.receipt["client_agent_account"], self.receipt["payer"])

    def rpc(self, *, status=None, transaction=None, genesis=None, account=None):
        rpc = SolanaRpcClient(OFFICIAL_DEVNET_RPC, max_attempts=1)
        rpc.get_genesis_hash = Mock(return_value=genesis or self.context.genesis_hash)
        rpc.get_signature_status = Mock(return_value=status)
        rpc.get_transaction = Mock(return_value=transaction)
        rpc.get_account_info = Mock(return_value=account)
        return rpc

    def inspect(self, signature=None, rpc=None):
        self.imported()
        return self.store.inspect_rpc(self.receipt["payment_id"],
            self.receipt["client_agent_account"], self.receipt["payer"],
            signature, rpc)

    def test_signed_receipt_imports_without_financial_posting(self):
        before = {table: self.ledger._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                  for table in FINANCIAL_TABLES}
        row, inserted = self.imported()
        self.assertTrue(inserted)
        self.assertEqual(row["provenance"], "SANDBOX_SIMULATION")
        self.assertEqual(row["finality"], "UNVERIFIED")
        self.assertEqual(row["reconciliation_status"], "INSUFFICIENT_DATA")
        self.assertIsNone(row["transaction_signature"])
        self.assertEqual(self.read(), row)
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM x402_verified_effects").fetchone()[0], 0)
        after = {table: self.ledger._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                 for table in FINANCIAL_TABLES}
        self.assertEqual(before, after)

    def test_exact_retry_adds_no_payment_or_effect(self):
        first, yes = self.imported()
        second, no = self.imported()
        self.assertTrue(yes)
        self.assertFalse(no)
        self.assertEqual(first, second)
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM x402_payments").fetchone()[0], 1)
        self.assertEqual(len(self.store.events(self.receipt["payment_id"],
            self.receipt["client_agent_account"], self.receipt["payer"])), 2)

    def test_restart_rechecks_signature_and_history(self):
        self.imported()
        before = self.read()
        self.store.close(); self.ledger.close()
        self.ledger = EconomicLedger(self.path)
        self.store = X402EconomicStore(self.ledger, self.context,
                                       self.source["facilitator_pubkey"], self.agents.get)
        self.assertEqual(self.read(), before)
        self.assertFalse(self.imported()[1])
        self.assertEqual(self.store.agent_view(self.receipt["provider_agent_account"],
            self.receipt["recipient"])["realized_revenue_base_units_str"], "0")

    def test_forged_receipt_and_wrong_facilitator_fail(self):
        forged = copy.deepcopy(self.receipt)
        forged["facilitator_signature"] = b58encode(bytes([9]) * 64)
        with self.assertRaises(X402IntegrityError):
            self.store.import_sandbox_receipt(forged)
        other = X402EconomicStore(self.ledger, self.context, b58encode(bytes([8]) * 32), self.agents.get)
        try:
            with self.assertRaises(X402IntegrityError):
                other.import_sandbox_receipt(self.receipt)
        finally:
            other.close()
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM x402_payments").fetchone()[0], 0)

    def test_sandbox_cannot_claim_live_finalized_or_reconciled(self):
        for field, bad in (("evidence_source", "LIVE_RPC"),
                           ("settlement_status", "FINALIZED"),
                           ("transaction_signature", self.signature),
                           ("commitment", "finalized")):
            forged = copy.deepcopy(self.receipt)
            forged[field] = bad
            with self.subTest(field=field), self.assertRaises(X402IntegrityError):
                self.store.import_sandbox_receipt(forged)

    def test_mutated_recipient_mint_amount_network_resource_and_hashes_fail(self):
        changes = (("recipient", self.receipt["payer"]), ("asset", self.receipt["payer"]),
                   ("amount_base_units_str", "101"), ("network", "solana:mainnet-beta"),
                   ("genesis_hash", self.receipt["payer"]),
                   ("resource_id", "other-resource"), ("resource_url", "https://example.com/premium-resource"),
                   ("payment_requirements_hash", "0" * 64),
                   ("payment_payload_hash", "0" * 64), ("payer", self.receipt["recipient"]))
        for field, bad in changes:
            forged = copy.deepcopy(self.receipt)
            forged[field] = bad
            with self.subTest(field=field), self.assertRaises(X402IntegrityError):
                self.store.import_sandbox_receipt(forged)
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM x402_payments").fetchone()[0], 0)

    def test_payment_id_and_receipt_id_collision_rejected(self):
        self.imported()
        for field in ("payment_id", "receipt_id", "payment_requirements_hash", "payment_payload_hash"):
            forged = copy.deepcopy(self.receipt)
            forged["amount_base_units_str"] = "101"
            with self.subTest(field=field), self.assertRaises(X402IntegrityError):
                self.store.import_sandbox_receipt(forged)
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM x402_payments").fetchone()[0], 1)

    def test_owner_and_agent_identity_changes_block_reuse_and_read(self):
        self.imported()
        client = self.receipt["client_agent_account"]
        saved = dict(self.agents[client])
        for field, bad in (("owner", self.receipt["recipient"]), ("agent_id", "ab" * 32)):
            self.agents[client] = {**saved, field: bad}
            with self.subTest(field=field):
                with self.assertRaises(X402IntegrityError): self.imported()
                with self.assertRaises(X402IntegrityError): self.read()
                with self.assertRaises(X402IntegrityError):
                    self.store.agent_view(client, self.receipt["payer"])
        self.agents[client] = saved

    def test_cross_tenant_and_provider_history_isolation(self):
        self.imported()
        with self.assertRaises(X402IntegrityError) as err:
            self.store.get(self.receipt["payment_id"], self.receipt["provider_agent_account"],
                           self.receipt["payer"])
        self.assertNotIn(self.receipt["resource_url"], str(err.exception))
        provider = self.store.agent_view(self.receipt["provider_agent_account"],
                                         self.receipt["recipient"])
        client = self.store.agent_view(self.receipt["client_agent_account"], self.receipt["payer"])
        self.assertEqual(provider["sandbox_receivable_base_units_str"], "100")
        self.assertEqual(client["sandbox_payable_base_units_str"], "100")
        self.assertEqual(provider["realized_revenue_base_units_str"], "0")
        self.assertIsNone(provider["realized_profit_base_units_str"])

    def test_stored_receipt_and_event_tampering_detected(self):
        self.imported()
        self.store.db.execute("UPDATE x402_payments SET amount_base_units='999' WHERE payment_id=?",
                              (self.receipt["payment_id"],))
        with self.assertRaisesRegex(X402IntegrityError, "STORED_RECEIPT_INTEGRITY_CONFLICT"):
            self.read()
        self.store.db.execute("UPDATE x402_payments SET amount_base_units='100' WHERE payment_id=?",
                              (self.receipt["payment_id"],))
        self.store.db.execute("UPDATE x402_events SET detail_code='FORGED' WHERE payment_id=?",
                              (self.receipt["payment_id"],))
        with self.assertRaisesRegex(X402IntegrityError, "EVENT_INTEGRITY_CONFLICT"):
            self.store.events(self.receipt["payment_id"], self.receipt["client_agent_account"],
                              self.receipt["payer"])

    def test_rehashed_database_context_tampering_still_rejected(self):
        self.imported()
        row = self.read()
        changed = {**row, "token_program": self.receipt["payer"]}
        changed["record_hash"] = digest({key: value for key, value in changed.items()
                                         if key != "record_hash"})
        self.store.db.execute("UPDATE x402_payments SET token_program=?,record_hash=? WHERE payment_id=?",
            (changed["token_program"], changed["record_hash"], changed["payment_id"]))
        with self.assertRaisesRegex(X402IntegrityError, "STORED_RECEIPT_CONTEXT_CONFLICT"):
            self.read()

    def test_sqlite_cannot_promote_sandbox_to_live_or_attach_signature(self):
        self.imported()
        for sql, value in (("UPDATE x402_payments SET provenance=?", "LIVE_RPC"),
                           ("UPDATE x402_payments SET finality=?", "FINALIZED"),
                           ("UPDATE x402_payments SET reconciliation_status=?", "RECONCILED"),
                           ("UPDATE x402_payments SET transaction_signature=?", self.signature)):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                self.store.db.execute(sql, (value,))
        self.assertEqual(self.read()["provenance"], "SANDBOX_SIMULATION")

    def test_forged_live_event_is_not_returned_as_productive_provenance(self):
        self.imported()
        event = dict(self.store.db.execute("SELECT * FROM x402_events WHERE payment_id=?",
                                           (self.receipt["payment_id"],)).fetchone())
        event["status"] = "LIVE_RPC"
        event["event_hash"] = digest({key: value for key, value in event.items()
                                      if key != "event_hash"})
        self.store.db.execute("UPDATE x402_events SET status=?,event_hash=? WHERE event_id=?",
                              (event["status"], event["event_hash"], event["event_id"]))
        with self.assertRaisesRegex(X402IntegrityError, "EVENT_INTEGRITY_CONFLICT"):
            self.store.events(self.receipt["payment_id"], self.receipt["client_agent_account"],
                              self.receipt["payer"])

    def test_rpc_check_and_difference_are_audited_once(self):
        self.imported()
        first = self.store.inspect_and_record(self.receipt["payment_id"],
            self.receipt["client_agent_account"], self.receipt["payer"], None)
        second = self.store.inspect_and_record(self.receipt["payment_id"],
            self.receipt["client_agent_account"], self.receipt["payer"], None)
        self.assertEqual(first, second)
        history = self.store.events(self.receipt["payment_id"],
            self.receipt["client_agent_account"], self.receipt["payer"])
        self.assertEqual([e["event_type"] for e in history].count("RPC_EVIDENCE_CHECKED"), 1)
        self.assertEqual([e["event_type"] for e in history].count("RECONCILIATION_DIFFERENCE"), 1)
        self.assertTrue(all(e["schema_version"] == 1 for e in history))

    def test_pending_and_rejected_rpc_observations_never_promote_receipt(self):
        self.imported()
        account = self.receipt["client_agent_account"]
        payment = self.receipt["payment_id"]
        owner = self.receipt["payer"]
        pending = self.store.inspect_and_record(payment, account, owner, self.signature,
            self.rpc(status={"slot": 20, "confirmationStatus": "confirmed", "err": None}))
        rejected = self.store.inspect_and_record(payment, account, owner, self.signature,
            self.rpc(status={"slot": 20, "confirmationStatus": "finalized", "err": "failed"}))
        self.assertEqual((pending["status"], rejected["status"]), ("PENDING", "REJECTED"))
        history = self.store.events(payment, account, owner)
        self.assertIn("PENDING", [event["status"] for event in history])
        self.assertIn("REJECTED", [event["status"] for event in history])
        row = self.read()
        self.assertEqual((row["provenance"], row["finality"], row["reconciliation_status"]),
                         ("SANDBOX_SIMULATION", "UNVERIFIED", "INSUFFICIENT_DATA"))

    def test_two_concurrent_consumers_one_payment(self):
        self.store.close(); self.ledger.close()
        def consume(_):
            ledger = EconomicLedger(self.path)
            store = X402EconomicStore(ledger, self.context,
                                       self.source["facilitator_pubkey"], self.agents.get)
            try:
                return store.import_sandbox_receipt(self.receipt)[1]
            finally:
                store.close(); ledger.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(consume, range(2)))
        self.assertEqual(sorted(outcomes), [False, True])
        self.ledger = EconomicLedger(self.path)
        self.store = X402EconomicStore(self.ledger, self.context,
                                       self.source["facilitator_pubkey"], self.agents.get)
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM x402_payments").fetchone()[0], 1)

    def test_no_rpc_or_fictitious_signature_is_insufficient(self):
        self.assertEqual(self.inspect()["reason"], "CON96_EVIDENCE_UNAVAILABLE")
        self.assertEqual(self.inspect("sig-fake")["reason"], "INVALID_SIGNATURE_FORMAT")
        self.assertEqual(self.inspect(self.signature)["reason"], "UNTRUSTED_RPC")

    def test_foreign_rpc_and_genesis_replay_fail_closed(self):
        foreign = SolanaRpcClient("https://api.mainnet-beta.solana.com")
        self.assertEqual(self.inspect(self.signature, foreign)["reason"], "UNTRUSTED_RPC")
        rpc = self.rpc(genesis=self.receipt["payer"])
        self.assertEqual(self.inspect(self.signature, rpc)["reason"], "GENESIS_MISMATCH")

    def test_pending_reorg_error_and_pruned_history_not_finalized(self):
        status = {"slot": 20, "confirmationStatus": "confirmed", "err": None}
        pending = self.inspect(self.signature, self.rpc(status=status))
        self.assertEqual((pending["status"], pending["reason"]), ("PENDING", "AWAITING_FINALITY"))
        status["confirmationStatus"] = "finalized"; status["err"] = {"InstructionError": [0, "Failed"]}
        rejected = self.inspect(self.signature, self.rpc(status=status))
        self.assertEqual((rejected["status"], rejected["reason"]), ("REJECTED", "TRANSACTION_REJECTED"))
        status["err"] = None
        self.assertEqual(self.inspect(self.signature, self.rpc())["reason"], "SIGNATURE_NOT_FOUND")
        self.assertEqual(self.inspect(self.signature, self.rpc(status=status))["reason"],
                         "TRANSACTION_UNAVAILABLE")
        rpc = self.rpc(status=status)
        rpc.get_transaction.side_effect = TimeoutError("RPC 429 or partition")
        self.assertEqual(self.inspect(self.signature, rpc)["reason"],
                         "RPC_UNAVAILABLE_OR_HISTORY_PRUNED")

    def test_finalized_rpc_claim_without_valid_effects_stays_insufficient(self):
        status = {"slot": 20, "confirmationStatus": "finalized", "err": None}
        base = {"slot": 20, "meta": {"err": None, "fee": 5000,
                "preTokenBalances": [], "postTokenBalances": []},
                "transaction": {"signatures": [self.signature], "message": {"accountKeys": []}}}
        self.assertEqual(self.inspect(self.signature, self.rpc(status=status, transaction=base))["reason"],
                         "TOKEN_BALANCE_DELTA_MISMATCH")
        wrong = copy.deepcopy(base); wrong["meta"]["fee"] = -1
        self.assertEqual(self.inspect(self.signature, self.rpc(status=status, transaction=wrong))["reason"],
                         "TRANSACTION_INTEGRITY_INCOMPLETE")
        wrong = copy.deepcopy(base); wrong["transaction"]["signatures"] = [b58encode(bytes([8]) * 64)]
        self.assertEqual(self.inspect(self.signature, self.rpc(status=status, transaction=wrong))["reason"],
                         "TRANSACTION_SIGNATURE_MISMATCH")

    def test_mint_decimals_owner_amount_and_partial_payment_fail_closed(self):
        status = {"slot": 20, "confirmationStatus": "finalized", "err": None}
        def token(owner, amount, *, mint=None, decimals=None, program=None, index=0):
            return {"accountIndex": index, "mint": mint or self.context.asset,
                    "owner": owner, "programId": program or self.context.token_program,
                    "uiTokenAmount": {"amount": amount,
                                      "decimals": self.context.decimals if decimals is None else decimals}}
        tx = {"slot": 20, "meta": {"err": None, "fee": 5000,
              "preTokenBalances": [token(self.receipt["payer"], "100", index=0),
                                   token(self.receipt["recipient"], "0", index=1)],
              "postTokenBalances": [token(self.receipt["payer"], "0", index=0),
                                    token(self.receipt["recipient"], "100", index=1)]},
              "transaction": {"signatures": [self.signature],
                              "message": {"accountKeys": [self.receipt["payer"],
                                                         self.receipt["recipient"]]}}}
        rpc = self.rpc(status=status, transaction=tx,
                       account={"owner": self.context.token_program})
        self.assertEqual(self.inspect(self.signature, rpc)["reason"],
                         "CON96_RECEIPT_AND_SPL_EFFECT_CORRELATION_REQUIRED")
        variants = [
            ("TOKEN_CONTEXT_MISMATCH", lambda v: v["meta"]["postTokenBalances"][1]["uiTokenAmount"].update(decimals=9)),
            ("TOKEN_CONTEXT_MISMATCH", lambda v: v["meta"]["postTokenBalances"][1].update(programId=self.receipt["payer"])),
            ("TOKEN_BALANCE_DELTA_MISMATCH", lambda v: v["meta"]["postTokenBalances"][1]["uiTokenAmount"].update(amount="99")),
            ("TOKEN_BALANCE_DELTA_MISMATCH", lambda v: v["meta"]["postTokenBalances"][1].update(mint=self.receipt["payer"])),
            ("TOKEN_OWNER_MISMATCH", lambda v: v["meta"]["postTokenBalances"][1].update(owner=self.receipt["payer"])),
        ]
        for expected, mutate in variants:
            variant = copy.deepcopy(tx); mutate(variant)
            with self.subTest(expected=expected, variant=variant):
                self.assertEqual(self.inspect(self.signature, self.rpc(status=status, transaction=variant,
                    account={"owner": self.context.token_program}))["reason"], expected)
        rpc = self.rpc(status=status, transaction=tx, account={"owner": self.receipt["payer"]})
        self.assertEqual(self.inspect(self.signature, rpc)["reason"], "TOKEN_ACCOUNT_PROGRAM_MISMATCH")

    def test_effect_identity_and_workorder_collision_are_read_only(self):
        a = canonical_effect_id(network=self.receipt["network"],
            genesis_hash=self.receipt["genesis_hash"], payment_id=self.receipt["payment_id"],
            transaction_signature=self.signature, instruction_index=0,
            effect_type="RESOURCE_REVENUE", agent_account=self.receipt["provider_agent_account"],
            asset=self.receipt["asset"])
        b = canonical_effect_id(network=self.receipt["network"],
            genesis_hash=self.receipt["genesis_hash"], payment_id=self.receipt["payment_id"],
            transaction_signature=self.signature, instruction_index=1,
            effect_type="RESOURCE_REVENUE", agent_account=self.receipt["provider_agent_account"],
            asset=self.receipt["asset"])
        self.assertNotEqual(a, b)
        self.assertFalse(self.store.workorder_collision(self.signature, 0))
        self.store.db.execute("INSERT INTO ingestion_effects VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (self.receipt["network"], self.receipt["genesis_hash"], self.signature, 0,
             "operator_payout", self.receipt["recipient"], self.receipt["asset"],
             "fixture-effect", "fixture-workorder", self.receipt["provider_agent_account"],
             self.receipt["recipient"], 100, "fixture-evidence", None, 1))
        self.assertTrue(self.store.workorder_collision(self.signature, 0))
        self.assertFalse(self.store.workorder_collision(self.signature, 1))
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM x402_verified_effects").fetchone()[0], 0)

    def test_offline_demo_compares_existing_workorders_and_zero_revenue(self):
        report = run_reconciliation_demo()
        self.assertTrue(report["X402_SANDBOX_IMPORTED"])
        self.assertTrue(report["RECEIPT_VERIFIED"])
        self.assertTrue(report["SQLITE_RESTART_VERIFIED"])
        self.assertGreater(report["WORKORDER_EVIDENCE_COMPARED"], 0)
        self.assertFalse(report["WORKORDER_DOUBLE_COUNT"])
        self.assertEqual(report["SANDBOX_RECOGNIZED_REVENUE"], 0)
        self.assertEqual(report["ONCHAIN_TRANSACTIONS_SENT"], 0)


if __name__ == "__main__":
    unittest.main()
