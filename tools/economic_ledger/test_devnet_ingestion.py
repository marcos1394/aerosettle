"""CON-37 cursor, isolation and immutable-effect tests; no network or signing."""
from __future__ import annotations

from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools.economic_ledger.devnet_ingestion import (
    DevnetIngestor, IngestionError, IngestionGap, IngestionIntegrityError,
    PendingFinality, Scope, UnavailableHistory, discover,
    validate_scope,
)
from tools.economic_ledger.spl_reconciler import (
    MockRpcClient, RpcError, SolanaRpcClient, SETTLE_WORK_ORDER_DISCRIMINATOR,
    b58encode,
)

WO = "2M2gMx8n5jDJ7ivKnLRxGVJepBAUst74vDuYZid4xRPr"
OTHER_WO = "72euFvUsPz5AJucVqKJKR9LhXq69WtJR4oHXZs33ogYm"


class Pager:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.calls = 0
        self.mutate_head = False

    def _call(self, method: str, params: list) -> list[dict]:
        assert method == "getSignaturesForAddress"
        self.calls += 1
        options = params[1]
        if self.mutate_head and self.calls > 1 and "before" not in options:
            return [{"signature": "new", "slot": 999}]
        start = 0
        if "before" in options:
            start = next(i + 1 for i, row in enumerate(self.rows)
                         if row["signature"] == options["before"])
        return self.rows[start:start + options["limit"]]


class DiscoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scope = Scope(WO, 10, 30)
        self.rows = [{"signature": f"sig-{slot}", "slot": slot}
                     for slot in range(25, 9, -1)]

    def test_pagination_anchor_replay_and_slot_bounds(self) -> None:
        pager = Pager(self.rows)
        found = discover(pager, self.scope, None, page_size=4, max_pages=5)
        self.assertEqual([x["slot"] for x in found], list(range(10, 26)))
        found = discover(Pager(self.rows), self.scope, "sig-20",
                         page_size=4, max_pages=5)
        self.assertEqual([x["slot"] for x in found], list(range(21, 26)))

    def test_incomplete_missing_anchor_and_head_change_fail_closed(self) -> None:
        with self.assertRaises(IngestionGap):
            discover(Pager(self.rows), self.scope, None, page_size=4, max_pages=2)
        with self.assertRaises(IngestionGap):
            discover(Pager(self.rows), self.scope, "missing", page_size=4, max_pages=5)
        pager = Pager(self.rows)
        pager.mutate_head = True
        with self.assertRaises(IngestionGap):
            discover(pager, self.scope, None, page_size=20, max_pages=1)

    def test_duplicate_page_or_bad_bounds_fail_closed(self) -> None:
        with self.assertRaises(IngestionGap):
            discover(Pager(self.rows[:4] + [self.rows[0]]), self.scope,
                     None, page_size=10, max_pages=1)
        with self.assertRaises(ValueError):
            discover(Pager(self.rows), self.scope, None, max_pages=0)

    def test_wrong_work_order_owner_and_foreign_rpc_fail_closed(self) -> None:
        rpc = SolanaRpcClient("https://api.devnet.solana.com")
        with patch.object(rpc, "get_account_info", return_value={"owner": "wrong"}):
            with self.assertRaises(IngestionIntegrityError):
                validate_scope(rpc, self.scope)
        with TemporaryDirectory() as folder:
            with self.assertRaises(IngestionError):
                DevnetIngestor(Path(folder) / "ledger.sqlite",
                               SolanaRpcClient("https://untrusted.example"))

    def test_rpc_timeout_has_bounded_retries(self) -> None:
        rpc = SolanaRpcClient("https://api.devnet.solana.com")
        with patch("tools.economic_ledger.spl_reconciler.urllib.request.urlopen",
                   side_effect=TimeoutError("timed out")) as send, \
             patch("tools.economic_ledger.spl_reconciler.time.sleep") as pause:
            with self.assertRaises(RpcError):
                rpc.get_genesis_hash()
        self.assertEqual(send.call_count, 6)
        self.assertEqual(pause.call_count, 5)


class PersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name) / "ledger.sqlite"
        self.scope = Scope(WO, 10, 30)
        self.ingestor = DevnetIngestor(self.path)
        self.ingestor._checkpoint(self.scope)

    def tearDown(self) -> None:
        self.ingestor.close()
        self.temp.cleanup()

    @staticmethod
    def receipt(signature: str, *, amount: int = 100,
                destination: str = "operator-ata", wo: str = WO):
        return SimpleNamespace(
            instruction_index=0, operator_token_account=destination,
            operator_payout=amount, creator_refund_token_account="creator-ata",
            creator_refund=1000 - amount, effect_id=f"effect:{signature}:{destination}",
            work_order_account=wo, agent_account=f"agent:{wo}",
            owner_pubkey=f"owner:{wo}", evidence_hash=f"hash:{signature}")

    def test_mock_cannot_claim_live_rpc(self) -> None:
        with self.assertRaises(IngestionError):
            DevnetIngestor(self.path, MockRpcClient())

    def test_two_effects_shared_destination_deduplicate_after_restart(self) -> None:
        receipt = self.receipt("sig-1", destination="shared-ata")
        receipt.creator_refund_token_account = "shared-ata"
        movement = SimpleNamespace(movement_id=None)
        self.assertFalse(self.ingestor._store(self.scope, "sig-1", 20,
                                              "RECONCILED", receipt, movement))
        self.assertTrue(self.ingestor._store(self.scope, "sig-1", 20,
                                             "RECONCILED", receipt, movement))
        self.assertEqual(self.ingestor.db.execute(
            "SELECT count(*) FROM ingestion_effects").fetchone()[0], 2)
        self.ingestor.close()
        self.ingestor = DevnetIngestor(self.path)
        self.assertTrue(self.ingestor._store(self.scope, "sig-1", 20,
                                             "RECONCILED", receipt, movement))
        self.assertEqual(self.ingestor.db.execute(
            "SELECT count(*) FROM ingestion_effects").fetchone()[0], 2)
        self.assertEqual(self.ingestor.db.execute(
            "SELECT count(*) FROM economic_movements").fetchone()[0], 0)

    def test_conflicting_amount_hash_and_identity_never_overwrite(self) -> None:
        original = self.receipt("sig-1")
        movement = SimpleNamespace(movement_id=None)
        self.ingestor._store(self.scope, "sig-1", 20, "RECONCILED", original, movement)
        with self.assertRaises(IngestionIntegrityError):
            self.ingestor._store(self.scope, "sig-1", 20, "RECONCILED",
                                 self.receipt("sig-1", amount=101), movement)
        changed_hash = self.receipt("sig-1")
        changed_hash.evidence_hash = "changed"
        with self.assertRaises(IngestionIntegrityError):
            self.ingestor._store(self.scope, "sig-1", 20, "RECONCILED", changed_hash, movement)
        self.assertEqual(self.ingestor.db.execute(
            "SELECT amount_base_units FROM ingestion_effects WHERE effect_kind='operator_payout'").fetchone()[0], 100)
        self.assertEqual(self.ingestor.db.execute(
            "SELECT count(*) FROM ingestion_effects").fetchone()[0], 2)

    def test_same_destination_separate_signature_and_scope_do_not_mix(self) -> None:
        other = Scope(OTHER_WO, 10, 30)
        self.ingestor._checkpoint(other)
        movement = SimpleNamespace(movement_id=None)
        self.ingestor._store(self.scope, "sig-1", 20, "RECONCILED",
                             self.receipt("sig-1"), movement)
        self.ingestor._store(other, "sig-2", 21, "RECONCILED",
                             self.receipt("sig-2", wo=OTHER_WO), movement)
        self.assertEqual(len(self.ingestor.report(self.scope)["effects"]), 2)
        self.assertEqual(len(self.ingestor.report(other)["effects"]), 2)

    def test_gap_keeps_cursor_and_resume_retries_missing_signature(self) -> None:
        self.ingestor._store(self.scope, "sig-1", 20, "FINALIZED")
        self.ingestor._incident(self.scope, "sig-2", 21, "GAP",
                                "Finalized transaction unavailable")
        cp = self.ingestor.report(self.scope)["checkpoint"]
        self.assertEqual(cp["last_processed_signature"], "sig-1")
        self.assertEqual(cp["checkpoint_status"], "GAP")
        self.ingestor.close()
        self.ingestor = DevnetIngestor(self.path)
        self.ingestor._checkpoint(self.scope)
        self.ingestor._store(self.scope, "sig-2", 21, "FINALIZED")
        cp = self.ingestor.report(self.scope)["checkpoint"]
        self.assertEqual(cp["last_processed_signature"], "sig-2")
        self.assertEqual(cp["checkpoint_status"], "READY")

    def test_corrupt_cursor_version_rejected_before_discovery(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            self.ingestor.db.execute("""UPDATE ingestion_checkpoints SET cursor_version=2
                WHERE scope_id=?""", (self.scope.scope_id,))
        self.assertIsNone(self.ingestor.report(self.scope)["checkpoint"]["last_processed_signature"])

    def test_preflight_error_is_audited_without_movement_or_cursor(self) -> None:
        with patch("tools.economic_ledger.devnet_ingestion.preflight",
                   side_effect=IngestionError("genesis mismatch")):
            report = self.ingestor.sync(self.scope)
        self.assertEqual(report["checkpoint"]["checkpoint_status"], "INCOMPLETE")
        self.assertIsNone(report["checkpoint"]["last_processed_signature"])
        self.assertEqual(report["incidents"][0]["error_category"], "PREFLIGHT")
        self.assertEqual(self.ingestor.db.execute(
            "SELECT count(*) FROM economic_movements").fetchone()[0], 0)

    def test_concurrent_writers_have_unique_effects(self) -> None:
        import concurrent.futures
        other = DevnetIngestor(self.path)
        receipt = self.receipt("sig-1")
        movement = SimpleNamespace(movement_id=None)
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(worker._store, self.scope, "sig-1", 20,
                                       "RECONCILED", receipt, movement)
                           for worker in (self.ingestor, other)]
                outcomes = [future.result() for future in futures]
            self.assertEqual(sorted(outcomes), [False, True])
            self.assertEqual(self.ingestor.db.execute(
                "SELECT count(*) FROM ingestion_effects").fetchone()[0], 2)
        finally:
            other.close()

    def test_pending_finality_and_pruned_history_do_not_create_movement(self) -> None:
        item = {"signature": "sig-1", "slot": 20}
        with patch.object(self.ingestor.rpc, "get_signature_status",
                          return_value={"confirmationStatus": "confirmed", "slot": 20}):
            with self.assertRaises(PendingFinality):
                self.ingestor._process(self.scope, item)
        with patch.object(self.ingestor.rpc, "get_signature_status",
                          return_value={"confirmationStatus": "finalized", "slot": 20}), \
             patch.object(self.ingestor.rpc, "get_transaction", return_value=None):
            with self.assertRaises(UnavailableHistory):
                self.ingestor._process(self.scope, item)
        self.assertIsNone(self.ingestor.report(self.scope)["checkpoint"]["last_processed_signature"])
        self.assertEqual(self.ingestor.db.execute(
            "SELECT count(*) FROM economic_movements").fetchone()[0], 0)

    def test_failed_and_nonsettlement_transactions_create_no_effect(self) -> None:
        item = {"signature": "sig-1", "slot": 20}
        transaction = {"slot": 20, "transaction": {"signatures": ["sig-1"],
            "message": {"accountKeys": ["payer", "program"],
                        "instructions": [{"programIdIndex": 1, "data": "1"}]}},
            "meta": {"err": None}}
        with patch.object(self.ingestor.rpc, "get_signature_status",
                          return_value={"confirmationStatus": "finalized", "slot": 20,
                                        "err": None}), \
             patch.object(self.ingestor.rpc, "get_transaction", return_value=transaction):
            self.assertEqual(self.ingestor._process(self.scope, item), ("FINALIZED", False))
        failed = {**transaction, "meta": {"err": {"InstructionError": [0, "Custom"]}}}
        failed_item = {"signature": "sig-2", "slot": 21}
        failed["transaction"] = {**transaction["transaction"], "signatures": ["sig-2"]}
        failed["slot"] = 21
        with patch.object(self.ingestor.rpc, "get_signature_status",
                          return_value={"confirmationStatus": "finalized", "slot": 21,
                                        "err": failed["meta"]["err"]}), \
             patch.object(self.ingestor.rpc, "get_transaction", return_value=failed):
            self.assertEqual(self.ingestor._process(self.scope, failed_item),
                             ("UNVERIFIABLE", False))
        self.assertEqual(self.ingestor.db.execute(
            "SELECT count(*) FROM ingestion_effects").fetchone()[0], 0)

    def test_status_disagreement_and_multiple_settlement_instructions_reject(self) -> None:
        item = {"signature": "sig-1", "slot": 20}
        discriminator = b58encode(SETTLE_WORK_ORDER_DISCRIMINATOR)
        transaction = {"slot": 20, "transaction": {"signatures": ["sig-1"],
            "message": {"accountKeys": ["payer",
                "CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy"],
                "instructions": [{"programIdIndex": 1, "data": discriminator},
                                 {"programIdIndex": 1, "data": discriminator}]}},
            "meta": {"err": None}}
        with patch.object(self.ingestor.rpc, "get_signature_status",
                          return_value={"confirmationStatus": "finalized", "slot": 20,
                                        "err": {"failure": True}}), \
             patch.object(self.ingestor.rpc, "get_transaction", return_value=transaction):
            with self.assertRaises(IngestionIntegrityError):
                self.ingestor._process(self.scope, item)
        with patch.object(self.ingestor.rpc, "get_signature_status",
                          return_value={"confirmationStatus": "finalized", "slot": 20,
                                        "err": None}), \
             patch.object(self.ingestor.rpc, "get_transaction", return_value=transaction):
            with self.assertRaises(IngestionIntegrityError):
                self.ingestor._process(self.scope, item)
        self.assertIsNone(self.ingestor.report(self.scope)["checkpoint"]["last_processed_signature"])


if __name__ == "__main__":
    unittest.main()
