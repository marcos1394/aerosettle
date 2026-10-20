"""Comprehensive test suite for the Conatus Persistent Economic Ledger (CON-22)."""
import os
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

from tools.economic_ledger.ledger import EconomicLedger
from tools.economic_ledger.models import (
    LedgerValidationError,
    MovementNature,
    MovementStatus,
    ProvenanceSource,
    validate_base_units,
)
from tools.economic_ledger.schema import run_migrations

AGENT_1 = "DcusvnYAdFFKzNDVzUkUvmgZ9fDhzszeRR5Fj8F5dMbB"
AGENT_2 = "FPbX4tQ2t9KSUDPix3NxBVEp2dD5LWoikhBVYYafU9H7"
OWNER_1 = "8rPDpYsLZxNBm8Q8GKSKki8Ag6dodkasedhUT9x3Ec1D"
WORK_ORDER_1 = "DcD34tC5THj7WkV9fzCYcpRSgUdt6wwybUFcG1YvSviy"
MINT_USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
MINT_TEST = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
PROGRAM_ID = "CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy"
GENESIS_HASH = "HP9XKTusRPGC78EFDpR9xdEq6simL2vqyDdrMvn6Vacg"
NET_LOCALNET = "solana:localnet"
NET_MAINNET = "solana:mainnet-beta"


class EconomicLedgerTests(unittest.TestCase):
    def setUp(self):
        # Create an isolated temporary database for each test
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_ledger.db"
        self.ledger = EconomicLedger(self.db_path)

    def tearDown(self):
        self.ledger.close()
        self.temp_dir.cleanup()

    # ─────────────────────────────────────────────────────────────────────────
    # 1. Idempotency: Duplicate writes of the same event
    # ─────────────────────────────────────────────────────────────────────────

    def test_duplicate_write_is_strictly_idempotent(self):
        idempotency_key = "tx-12345-settlement-income"
        
        # 1st write
        m1 = self.ledger.record_movement(
            idempotency_key=idempotency_key,
            agent_id="11" * 32,
            agent_account=AGENT_1,
            owner_pubkey=OWNER_1,
            network=NET_LOCALNET,
            genesis_hash=GENESIS_HASH,
            program_id=PROGRAM_ID,
            token_mint=MINT_USDC,
            amount_base_units=5_000_000,
            nature=MovementNature.INCOME,
            status=MovementStatus.RECONCILED,
        )

        # 2nd write with identical idempotency_key
        m2 = self.ledger.record_movement(
            idempotency_key=idempotency_key,
            agent_id="11" * 32,
            agent_account=AGENT_1,
            owner_pubkey=OWNER_1,
            network=NET_LOCALNET,
            genesis_hash=GENESIS_HASH,
            program_id=PROGRAM_ID,
            token_mint=MINT_USDC,
            amount_base_units=5_000_000,
            nature=MovementNature.INCOME,
            status=MovementStatus.RECONCILED,
        )

        self.assertEqual(m1.movement_id, m2.movement_id)
        self.assertEqual(m1.amount_base_units, m2.amount_base_units)

        # Verify only 1 movement exists in DB
        movements, _ = self.ledger.list_movements(AGENT_1)
        self.assertEqual(len(movements), 1)

    # ─────────────────────────────────────────────────────────────────────────
    # 2. Concurrency: Multiple threads writing simultaneously
    # ─────────────────────────────────────────────────────────────────────────

    def test_concurrent_transactions_without_corruption(self):
        num_threads = 8
        movements_per_thread = 10
        errors = []

        def worker(thread_idx: int):
            try:
                # Each thread uses a connection to the WAL-mode database
                with EconomicLedger(self.db_path) as local_ledger:
                    for i in range(movements_per_thread):
                        key = f"concurrent-t{thread_idx}-m{i}"
                        local_ledger.record_movement(
                            idempotency_key=key,
                            agent_id="11" * 32,
                            agent_account=AGENT_1,
                            owner_pubkey=OWNER_1,
                            network=NET_LOCALNET,
                            genesis_hash=GENESIS_HASH,
                            program_id=PROGRAM_ID,
                            token_mint=MINT_USDC,
                            amount_base_units=100_000,
                            nature=MovementNature.INCOME,
                            status=MovementStatus.RECONCILED,
                        )
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0, f"Concurrent worker encountered errors: {errors}")

        # Total movements should be exactly num_threads * movements_per_thread
        movements, _ = self.ledger.list_movements(AGENT_1, limit=200)
        self.assertEqual(len(movements), num_threads * movements_per_thread)

        # Balance check: (8 * 10) * 100_000 = 8_000_000
        balances = self.ledger.get_balances(AGENT_1, token_mint=MINT_USDC)
        self.assertEqual(len(balances), 1)
        self.assertEqual(balances[0].reconciled_balance, 8_000_000)

    # ─────────────────────────────────────────────────────────────────────────
    # 3. Reversals & Corrections: Append-only compensating movements
    # ─────────────────────────────────────────────────────────────────────────

    def test_reversal_creates_compensating_movement_and_updates_status(self):
        orig = self.ledger.record_movement(
            idempotency_key="expense-battery-charging-001",
            agent_id="11" * 32,
            agent_account=AGENT_1,
            owner_pubkey=OWNER_1,
            network=NET_LOCALNET,
            genesis_hash=GENESIS_HASH,
            program_id=PROGRAM_ID,
            token_mint=MINT_USDC,
            amount_base_units=250_000,
            nature=MovementNature.EXPENSE,
            status=MovementStatus.RECONCILED,
        )

        # Initial balance: -250_000
        bal1 = self.ledger.get_balances(AGENT_1)[0]
        self.assertEqual(bal1.reconciled_balance, -250_000)

        # Revert movement with audit reason
        reverted, compensating = self.ledger.revert_movement(
            orig.movement_id,
            reason="Erroneous charge duplicated by hardware telemetry",
            authorized_by=OWNER_1,
        )

        self.assertEqual(reverted.status, MovementStatus.REVERTED)
        self.assertEqual(compensating.nature, MovementNature.ADJUSTMENT)
        self.assertEqual(compensating.reversal_of_movement_id, orig.movement_id)
        self.assertEqual(compensating.amount_base_units, 250_000)
        self.assertEqual(compensating.metadata["reversal_reason"], "Erroneous charge duplicated by hardware telemetry")

        # Balance after compensating reversal: net 0
        bal2 = self.ledger.get_balances(AGENT_1)[0]
        # Since the original expense is REVERTED, it no longer reduces the reconciled balance
        self.assertEqual(bal2.reconciled_balance, 0)

        # Attempting to revert already-reverted movement raises error
        with self.assertRaises(LedgerValidationError):
            self.ledger.revert_movement(orig.movement_id, reason="Second try", authorized_by=OWNER_1)

    # ─────────────────────────────────────────────────────────────────────────
    # 4. Strict Asset & Network Separation
    # ─────────────────────────────────────────────────────────────────────────

    def test_strict_separation_of_mints_and_networks(self):
        # Localnet USDC Income
        self.ledger.record_movement(
            idempotency_key="m1",
            agent_id="11" * 32,
            agent_account=AGENT_1,
            owner_pubkey=OWNER_1,
            network=NET_LOCALNET,
            genesis_hash=GENESIS_HASH,
            program_id=PROGRAM_ID,
            token_mint=MINT_USDC,
            amount_base_units=1_000_000,
            nature=MovementNature.INCOME,
            status=MovementStatus.RECONCILED,
        )

        # Localnet TEST token Income
        self.ledger.record_movement(
            idempotency_key="m2",
            agent_id="11" * 32,
            agent_account=AGENT_1,
            owner_pubkey=OWNER_1,
            network=NET_LOCALNET,
            genesis_hash=GENESIS_HASH,
            program_id=PROGRAM_ID,
            token_mint=MINT_TEST,
            amount_base_units=999_999,
            nature=MovementNature.INCOME,
            status=MovementStatus.RECONCILED,
        )

        # Mainnet USDC Income
        self.ledger.record_movement(
            idempotency_key="m3",
            agent_id="11" * 32,
            agent_account=AGENT_1,
            owner_pubkey=OWNER_1,
            network=NET_MAINNET,
            genesis_hash="5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d",
            program_id=PROGRAM_ID,
            token_mint=MINT_USDC,
            amount_base_units=500_000,
            nature=MovementNature.INCOME,
            status=MovementStatus.RECONCILED,
        )

        balances = self.ledger.get_balances(AGENT_1)
        self.assertEqual(len(balances), 3)

        b_local_usdc = next(b for b in balances if b.network == NET_LOCALNET and b.token_mint == MINT_USDC)
        b_local_test = next(b for b in balances if b.network == NET_LOCALNET and b.token_mint == MINT_TEST)
        b_main_usdc = next(b for b in balances if b.network == NET_MAINNET and b.token_mint == MINT_USDC)

        self.assertEqual(b_local_usdc.reconciled_balance, 1_000_000)
        self.assertEqual(b_local_test.reconciled_balance, 999_999)
        self.assertEqual(b_main_usdc.reconciled_balance, 500_000)

        # Querying with specific filter returns only that partition
        filtered = self.ledger.get_balances(AGENT_1, network=NET_LOCALNET, token_mint=MINT_USDC)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0].reconciled_balance, 1_000_000)

    # ─────────────────────────────────────────────────────────────────────────
    # 5. Exact Monetary Units: Large Integers & Float Rejection
    # ─────────────────────────────────────────────────────────────────────────

    def test_float_rejection_and_large_integers(self):
        # Floats must be strictly rejected
        with self.assertRaises(LedgerValidationError):
            validate_base_units(123.45)

        with self.assertRaises(LedgerValidationError):
            self.ledger.record_movement(
                idempotency_key="float-test",
                agent_id="11" * 32,
                agent_account=AGENT_1,
                owner_pubkey=OWNER_1,
                network=NET_LOCALNET,
                genesis_hash=GENESIS_HASH,
                program_id=PROGRAM_ID,
                token_mint=MINT_USDC,
                amount_base_units=100.5,  # float
                nature=MovementNature.INCOME,
            )

        # Large uint64 value (e.g. 10 billion USDC in micro-units: 10_000_000_000_000_000)
        large_val = 10_000_000_000_000_000
        m = self.ledger.record_movement(
            idempotency_key="large-val-test",
            agent_id="11" * 32,
            agent_account=AGENT_1,
            owner_pubkey=OWNER_1,
            network=NET_LOCALNET,
            genesis_hash=GENESIS_HASH,
            program_id=PROGRAM_ID,
            token_mint=MINT_USDC,
            amount_base_units=large_val,
            nature=MovementNature.INCOME,
            status=MovementStatus.RECONCILED,
        )

        self.assertEqual(m.amount_base_units, large_val)
        self.assertEqual(m.amount_str, str(large_val))

        bal = self.ledger.get_balances(AGENT_1, token_mint=MINT_USDC)[0]
        self.assertEqual(bal.reconciled_balance, large_val)

    # ─────────────────────────────────────────────────────────────────────────
    # 6. Database Error & Rollback Integrity
    # ─────────────────────────────────────────────────────────────────────────

    def test_transaction_rollback_on_unbalanced_double_entry(self):
        # Manually supplying unbalanced legs must rollback and create nothing
        bad_legs = [
            {"account_name": "ASSET:TREASURY", "entry_type": "DEBIT", "amount_base_units": 100},
            {"account_name": "REVENUE:SETTLEMENT", "entry_type": "CREDIT", "amount_base_units": 50},  # Unbalanced!
        ]

        with self.assertRaises(LedgerValidationError):
            self.ledger.record_movement(
                idempotency_key="bad-legs-entry",
                agent_id="11" * 32,
                agent_account=AGENT_1,
                owner_pubkey=OWNER_1,
                network=NET_LOCALNET,
                genesis_hash=GENESIS_HASH,
                program_id=PROGRAM_ID,
                token_mint=MINT_USDC,
                amount_base_units=100,
                nature=MovementNature.INCOME,
                custom_journal_legs=bad_legs,
            )

        # Confirm nothing was committed
        self.assertIsNone(self.ledger.get_by_idempotency_key("bad-legs-entry"))

    # ─────────────────────────────────────────────────────────────────────────
    # 7. Provisional vs Reconciled Separation
    # ─────────────────────────────────────────────────────────────────────────

    def test_provisional_vs_reconciled_records(self):
        # 1. Reconciled income
        self.ledger.record_movement(
            idempotency_key="rec-inc",
            agent_id="11" * 32,
            agent_account=AGENT_1,
            owner_pubkey=OWNER_1,
            network=NET_LOCALNET,
            genesis_hash=GENESIS_HASH,
            program_id=PROGRAM_ID,
            token_mint=MINT_USDC,
            amount_base_units=1_000_000,
            nature=MovementNature.INCOME,
            status=MovementStatus.RECONCILED,
        )

        # 2. Provisional income (e.g. pending on-chain block confirmation)
        self.ledger.record_movement(
            idempotency_key="prov-inc",
            agent_id="11" * 32,
            agent_account=AGENT_1,
            owner_pubkey=OWNER_1,
            network=NET_LOCALNET,
            genesis_hash=GENESIS_HASH,
            program_id=PROGRAM_ID,
            token_mint=MINT_USDC,
            amount_base_units=300_000,
            nature=MovementNature.INCOME,
            status=MovementStatus.PROVISIONAL,
        )

        # 3. Reserved bond (slashable)
        self.ledger.record_movement(
            idempotency_key="bond-res",
            agent_id="11" * 32,
            agent_account=AGENT_1,
            owner_pubkey=OWNER_1,
            network=NET_LOCALNET,
            genesis_hash=GENESIS_HASH,
            program_id=PROGRAM_ID,
            token_mint=MINT_USDC,
            amount_base_units=500_000,
            nature=MovementNature.RESERVE,
            status=MovementStatus.RECONCILED,
        )

        bal = self.ledger.get_balances(AGENT_1, token_mint=MINT_USDC)[0]
        self.assertEqual(bal.reconciled_balance, 1_000_000)
        self.assertEqual(bal.provisional_balance, 300_000)
        self.assertEqual(bal.reserved_balance, 500_000)
        self.assertEqual(bal.total_effective_balance, 1_300_000)

        # Filtering by status in list_movements
        prov_list, _ = self.ledger.list_movements(AGENT_1, status="PROVISIONAL")
        self.assertEqual(len(prov_list), 1)
        self.assertEqual(prov_list[0].idempotency_key, "prov-inc")

        rec_list, _ = self.ledger.list_movements(AGENT_1, status="RECONCILED")
        self.assertEqual(len(rec_list), 2)

    # ─────────────────────────────────────────────────────────────────────────
    # 8. Settlement Protocol Verification & Operator Payout Calculation
    # ─────────────────────────────────────────────────────────────────────────

    def test_settlement_calculates_exact_operator_payout_and_refunds(self):
        # Scenario: Escrow has 10_000_000 total_amount funded.
        # Completion is 75% (7500 bps) with Proportional payment model.
        # Verified operator payout is exactly 7_500_000, NOT 10_000_000!
        order_data = {
            "work_order_id": "01" * 32,
            "total_amount": 10_000_000,
            "payment_model": "Proportional",
            "verification_status": "Accepted",
            "completion_bps": 7500,
            "verification_attestation_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        }

        movement = self.ledger.record_settlement(
            work_order_account=WORK_ORDER_1,
            work_order_data=order_data,
            agent_account=AGENT_1,
            owner_pubkey=OWNER_1,
            agent_id="11" * 32,
            network=NET_LOCALNET,
            genesis_hash=GENESIS_HASH,
            program_id=PROGRAM_ID,
            token_mint=MINT_USDC,
            tx_signature="tx-settle-proportional-75",
            is_reconciled=True,
        )

        self.assertEqual(movement.amount_base_units, 7_500_000)
        self.assertEqual(movement.metadata["operator_payout"], 7_500_000)
        self.assertEqual(movement.metadata["creator_refund"], 2_500_000)
        self.assertEqual(movement.metadata["total_escrow_funded"], 10_000_000)
        self.assertEqual(movement.status, MovementStatus.RECONCILED)

        # Rejected work scenario: operator payout must be 0
        rejected_order = {
            "work_order_id": "02" * 32,
            "total_amount": 10_000_000,
            "payment_model": "Fixed",
            "verification_status": "Rejected",
            "completion_bps": 0,
        }
        rejected_movement = self.ledger.record_settlement(
            work_order_account="RejectedWorkOrder111111111111111111111111",
            work_order_data=rejected_order,
            agent_account=AGENT_1,
            owner_pubkey=OWNER_1,
            agent_id="11" * 32,
            network=NET_LOCALNET,
            genesis_hash=GENESIS_HASH,
            program_id=PROGRAM_ID,
            token_mint=MINT_USDC,
            tx_signature="tx-settle-rejected",
        )
        self.assertEqual(rejected_movement.metadata["operator_payout"], 0)
        self.assertEqual(rejected_movement.metadata["creator_refund"], 10_000_000)

    # ─────────────────────────────────────────────────────────────────────────
    # 9. Loss of Database Connection / Connection Failure Handling
    # ─────────────────────────────────────────────────────────────────────────

    def test_loss_of_db_connection_fails_closed_and_raises_error(self):
        # Force-close the underlying connection to simulate unexpected disconnect / I/O loss
        self.ledger._conn.close()

        with self.assertRaises(sqlite3.ProgrammingError):
            self.ledger.record_movement(
                idempotency_key="disconnected-test",
                agent_id="11" * 32,
                agent_account=AGENT_1,
                owner_pubkey=OWNER_1,
                network=NET_LOCALNET,
                genesis_hash=GENESIS_HASH,
                program_id=PROGRAM_ID,
                token_mint=MINT_USDC,
                amount_base_units=100_000,
                nature=MovementNature.INCOME,
            )

        with self.assertRaises(sqlite3.ProgrammingError):
            self.ledger.get_balances(AGENT_1)

    # ─────────────────────────────────────────────────────────────────────────
    # 10. Reproducible Schema Migrations
    # ─────────────────────────────────────────────────────────────────────────

    def test_reproducible_and_idempotent_migrations(self):
        # Run migrations again on an already migrated database
        applied = run_migrations(self.ledger._conn)
        self.assertEqual(len(applied), 0)  # No new migrations applied

        # Verify tables exist
        cursor = self.ledger._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;"
        )
        tables = {row[0] for row in cursor.fetchall()}
        self.assertIn("economic_movements", tables)
        self.assertIn("journal_entries", tables)
        self.assertIn("ledger_entries", tables)
        self.assertIn("schema_migrations", tables)


if __name__ == "__main__":
    unittest.main()
