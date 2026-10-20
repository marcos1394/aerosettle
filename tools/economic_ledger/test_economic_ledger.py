"""Comprehensive test suite for the Conatus Persistent Economic Ledger (CON-22)."""
import os
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

from tools.economic_ledger.ledger import EconomicLedger
from tools.economic_ledger.models import (
    IdempotencyConflictError,
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
    # 1. Idempotency & Semantic Conflict Verification
    # ─────────────────────────────────────────────────────────────────────────

    def test_duplicate_write_is_strictly_idempotent_when_matching(self):
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
            tx_signature="sig-1",
        )

        # 2nd write with identical idempotency_key and matching payload
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
            tx_signature="sig-1",
        )

        self.assertEqual(m1.movement_id, m2.movement_id)
        self.assertEqual(m1.amount_base_units, m2.amount_base_units)

        # Verify only 1 movement exists in DB
        movements, _ = self.ledger.list_movements(AGENT_1)
        self.assertEqual(len(movements), 1)

    def test_idempotency_key_reuse_with_mismatched_payload_raises_conflict(self):
        key = "idemp-semantic-conflict-key"

        self.ledger.record_movement(
            idempotency_key=key,
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
            tx_signature="sig-base",
        )

        # Reusing key with different amount must fail with IdempotencyConflictError
        with self.assertRaises(IdempotencyConflictError) as ctx:
            self.ledger.record_movement(
                idempotency_key=key,
                agent_id="11" * 32,
                agent_account=AGENT_1,
                owner_pubkey=OWNER_1,
                network=NET_LOCALNET,
                genesis_hash=GENESIS_HASH,
                program_id=PROGRAM_ID,
                token_mint=MINT_USDC,
                amount_base_units=2_000_000,  # Differs!
                nature=MovementNature.INCOME,
                status=MovementStatus.RECONCILED,
                tx_signature="sig-base",
            )
        self.assertIn("amount_base_units", str(ctx.exception))

        # Reusing key with different nature must fail
        with self.assertRaises(IdempotencyConflictError) as ctx:
            self.ledger.record_movement(
                idempotency_key=key,
                agent_id="11" * 32,
                agent_account=AGENT_1,
                owner_pubkey=OWNER_1,
                network=NET_LOCALNET,
                genesis_hash=GENESIS_HASH,
                program_id=PROGRAM_ID,
                token_mint=MINT_USDC,
                amount_base_units=1_000_000,
                nature=MovementNature.EXPENSE,  # Differs!
                status=MovementStatus.RECONCILED,
                tx_signature="sig-base",
            )
        self.assertIn("nature", str(ctx.exception))

    # ─────────────────────────────────────────────────────────────────────────
    # 2. Concurrency: Multiple threads writing simultaneously
    # ─────────────────────────────────────────────────────────────────────────

    def test_concurrent_transactions_without_corruption(self):
        num_threads = 8
        movements_per_thread = 10
        errors = []

        def worker(thread_idx: int):
            try:
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
                            tx_signature=f"sig-{key}",
                        )
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0, f"Concurrent execution produced errors: {errors}")

        # Total movements should be exactly num_threads * movements_per_thread
        movements, _ = self.ledger.list_movements(AGENT_1, limit=200)
        self.assertEqual(len(movements), num_threads * movements_per_thread)

        # Check balance exactness: 80 * 100_000 = 8_000_000
        balances = self.ledger.get_balances(AGENT_1, network=NET_LOCALNET, token_mint=MINT_USDC)
        self.assertEqual(len(balances), 1)
        self.assertEqual(balances[0].reconciled_balance, 8_000_000)

    # ─────────────────────────────────────────────────────────────────────────
    # 3. Reconciliation Integrity: Guardrails & Internal Transition
    # ─────────────────────────────────────────────────────────────────────────

    def test_manual_entry_cannot_be_directly_recorded_as_reconciled(self):
        # Client cannot arbitrarily mark MANUAL_ENTRY as RECONCILED
        with self.assertRaises(LedgerValidationError) as ctx:
            self.ledger.record_movement(
                idempotency_key="unauth-manual-rec",
                agent_id="11" * 32,
                agent_account=AGENT_1,
                owner_pubkey=OWNER_1,
                network=NET_LOCALNET,
                genesis_hash=GENESIS_HASH,
                program_id=PROGRAM_ID,
                token_mint=MINT_USDC,
                amount_base_units=500_000,
                nature=MovementNature.INCOME,
                status=MovementStatus.RECONCILED,
                provenance_source=ProvenanceSource.MANUAL_ENTRY,
            )
        self.assertIn("MANUAL_ENTRY movements cannot be recorded directly as RECONCILED", str(ctx.exception))

        # Must be initiated as PROVISIONAL
        m = self.ledger.record_movement(
            idempotency_key="auth-manual-prov",
            agent_id="11" * 32,
            agent_account=AGENT_1,
            owner_pubkey=OWNER_1,
            network=NET_LOCALNET,
            genesis_hash=GENESIS_HASH,
            program_id=PROGRAM_ID,
            token_mint=MINT_USDC,
            amount_base_units=500_000,
            nature=MovementNature.INCOME,
            status=MovementStatus.PROVISIONAL,
            provenance_source=ProvenanceSource.MANUAL_ENTRY,
        )
        self.assertEqual(m.status, MovementStatus.PROVISIONAL)

        # Transition to RECONCILED requires internal authorized evidence
        reconciled = self.ledger.reconcile_movement(
            m.movement_id,
            evidence_hash="sha256:4b227777d4dd1fc61c6f884f48641d02b4d121d3fd328cb08b5531fcacdabf8a",
            authorized_by="conatus:reconciler:service",
            slot=104920,
            tx_signature="5xSigOnChainReconciledEvidence1111111111111111111",
        )
        self.assertEqual(reconciled.status, MovementStatus.RECONCILED)
        self.assertEqual(
            reconciled.evidence_hash,
            "sha256:4b227777d4dd1fc61c6f884f48641d02b4d121d3fd328cb08b5531fcacdabf8a",
        )
        self.assertEqual(reconciled.metadata["reconciliation"]["authorized_by"], "conatus:reconciler:service")

    # ─────────────────────────────────────────────────────────────────────────
    # 4. Contrasientos & Double-Entry Invariant Verification
    # ─────────────────────────────────────────────────────────────────────────

    def test_revert_movement_emits_balanced_contrasiento(self):
        # 1. Record an income movement with double-entry legs
        m = self.ledger.record_movement(
            idempotency_key="mov-to-revert",
            agent_id="11" * 32,
            agent_account=AGENT_1,
            owner_pubkey=OWNER_1,
            network=NET_LOCALNET,
            genesis_hash=GENESIS_HASH,
            program_id=PROGRAM_ID,
            token_mint=MINT_USDC,
            amount_base_units=1_500_000,
            nature=MovementNature.INCOME,
            status=MovementStatus.RECONCILED,
            tx_signature="sig-to-revert",
        )

        totals_before = self.ledger.get_ledger_totals()
        self.assertTrue(totals_before["is_balanced"])
        self.assertEqual(totals_before["total_debit"], 1_500_000)
        self.assertEqual(totals_before["total_credit"], 1_500_000)

        # 2. Revert the movement: must emit formal contrasiento
        reverted, comp = self.ledger.revert_movement(
            m.movement_id,
            reason="Incorrect mission payout attribution",
            authorized_by="AdminAuthority111111111111111111111111111",
        )

        self.assertEqual(reverted.status, MovementStatus.REVERTED)
        self.assertEqual(comp.nature, MovementNature.ADJUSTMENT)
        self.assertEqual(comp.status, MovementStatus.RECONCILED)
        self.assertEqual(comp.reversal_of_movement_id, m.movement_id)
        self.assertTrue(comp.metadata.get("is_contrasiento"))

        # 3. Check accounting invariant: total debits == total credits across the ledger
        totals_after = self.ledger.get_ledger_totals()
        self.assertTrue(totals_after["is_balanced"])
        # Original (1.5M debit, 1.5M credit) + Contrasiento (1.5M debit, 1.5M credit) = 3M each
        self.assertEqual(totals_after["total_debit"], 3_000_000)
        self.assertEqual(totals_after["total_credit"], 3_000_000)

        # 4. Check that balance report is net-zeroed and not distorted
        bal = self.ledger.get_balances(AGENT_1, token_mint=MINT_USDC)[0]
        self.assertEqual(bal.reconciled_balance, 0)
        self.assertEqual(bal.total_effective_balance, 0)

    # ─────────────────────────────────────────────────────────────────────────
    # 5. Zero-Payout Settlement Audit Trails (No 1-Unit Symbolic Hack)
    # ─────────────────────────────────────────────────────────────────────────

    def test_zero_payout_settlement_records_exact_zero_audit_entry(self):
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
            tx_signature="tx-settle-rejected-0",
        )

        # Must be strictly 0 base units (NOT 1!)
        self.assertEqual(rejected_movement.amount_base_units, 0)
        self.assertEqual(rejected_movement.amount_str, "0")
        self.assertEqual(rejected_movement.metadata["operator_payout"], 0)
        self.assertEqual(rejected_movement.metadata["creator_refund"], 10_000_000)

        # Invariant holds
        totals = self.ledger.get_ledger_totals()
        self.assertTrue(totals["is_balanced"])

        # Agent balance should not have received a phantom 1 unit
        balances = self.ledger.get_balances(AGENT_1, token_mint=MINT_USDC)
        self.assertEqual(balances[0].reconciled_balance, 0)

    # ─────────────────────────────────────────────────────────────────────────
    # 6. u64 Monetary Exactness: 2^63 - 1, 2^63, and 2^64 - 1 Limits
    # ─────────────────────────────────────────────────────────────────────────

    def test_u64_monetary_exactness_at_boundary_limits(self):
        # 2^63 - 1 (Max signed 64-bit int where SQLite normally starts float casting)
        LIM_SIGNED_64 = 2**63 - 1  # 9223372036854775807
        # 2^63
        LIM_POW_63 = 2**63        # 9223372036854775808
        # 2^64 - 1 (Solana u64::MAX)
        U64_MAX = 2**64 - 1        # 18446744073709551615

        # Record movements with each boundary amount
        m1 = self.ledger.record_movement(
            idempotency_key="limit-2pow63-minus-1",
            agent_id="11" * 32,
            agent_account=AGENT_1,
            owner_pubkey=OWNER_1,
            network=NET_LOCALNET,
            genesis_hash=GENESIS_HASH,
            program_id=PROGRAM_ID,
            token_mint=MINT_USDC,
            amount_base_units=LIM_SIGNED_64,
            nature=MovementNature.INCOME,
            status=MovementStatus.RECONCILED,
            tx_signature="sig-lim1",
        )
        self.assertEqual(m1.amount_base_units, LIM_SIGNED_64)
        self.assertEqual(m1.amount_str, str(LIM_SIGNED_64))

        m2 = self.ledger.record_movement(
            idempotency_key="limit-2pow63",
            agent_id="11" * 32,
            agent_account=AGENT_1,
            owner_pubkey=OWNER_1,
            network=NET_LOCALNET,
            genesis_hash=GENESIS_HASH,
            program_id=PROGRAM_ID,
            token_mint=MINT_USDC,
            amount_base_units=LIM_POW_63,
            nature=MovementNature.INCOME,
            status=MovementStatus.RECONCILED,
            tx_signature="sig-lim2",
        )
        self.assertEqual(m2.amount_base_units, LIM_POW_63)
        self.assertEqual(m2.amount_str, str(LIM_POW_63))

        # Check exact sum in Python without float truncation
        expected_sum_1_2 = LIM_SIGNED_64 + LIM_POW_63
        bal = self.ledger.get_balances(AGENT_1, token_mint=MINT_USDC)[0]
        self.assertEqual(bal.reconciled_balance, expected_sum_1_2)
        self.assertEqual(bal.reconciled_balance_str, str(expected_sum_1_2))

        # Record movement with Solana u64::MAX
        m_max = self.ledger.record_movement(
            idempotency_key="limit-u64-max",
            agent_id="22" * 32,
            agent_account=AGENT_2,
            owner_pubkey=OWNER_1,
            network=NET_LOCALNET,
            genesis_hash=GENESIS_HASH,
            program_id=PROGRAM_ID,
            token_mint=MINT_USDC,
            amount_base_units=U64_MAX,
            nature=MovementNature.INCOME,
            status=MovementStatus.RECONCILED,
            tx_signature="sig-max",
        )
        self.assertEqual(m_max.amount_base_units, U64_MAX)
        self.assertEqual(m_max.amount_str, "18446744073709551615")

        bal2 = self.ledger.get_balances(AGENT_2, token_mint=MINT_USDC)[0]
        self.assertEqual(bal2.reconciled_balance, U64_MAX)
        self.assertEqual(bal2.reconciled_balance_str, "18446744073709551615")
        # Ensure that no lower bits were lost (float IEEE 754 precision would lose last digits)
        self.assertTrue(bal2.reconciled_balance_str.endswith("15"))

    # ─────────────────────────────────────────────────────────────────────────
    # 7. Strict Network & Token Mint Isolation
    # ─────────────────────────────────────────────────────────────────────────

    def test_strict_isolation_across_networks_and_mints(self):
        # Localnet USDC
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
            tx_signature="sig-m1",
        )

        # Localnet TEST mint
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
            tx_signature="sig-m2",
        )

        # Mainnet USDC
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
            tx_signature="sig-m3",
        )

        balances = self.ledger.get_balances(AGENT_1)
        self.assertEqual(len(balances), 3)

        b_local_usdc = next(b for b in balances if b.network == NET_LOCALNET and b.token_mint == MINT_USDC)
        b_local_test = next(b for b in balances if b.network == NET_LOCALNET and b.token_mint == MINT_TEST)
        b_main_usdc = next(b for b in balances if b.network == NET_MAINNET and b.token_mint == MINT_USDC)

        self.assertEqual(b_local_usdc.reconciled_balance, 1_000_000)
        self.assertEqual(b_local_test.reconciled_balance, 999_999)
        self.assertEqual(b_main_usdc.reconciled_balance, 500_000)

    # ─────────────────────────────────────────────────────────────────────────
    # 8. Floating Point Rejection
    # ─────────────────────────────────────────────────────────────────────────

    def test_float_rejection(self):
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
                amount_base_units=100.5,
                nature=MovementNature.INCOME,
            )

    # ─────────────────────────────────────────────────────────────────────────
    # 9. Rollback Integrity
    # ─────────────────────────────────────────────────────────────────────────

    def test_transaction_rollback_on_unbalanced_double_entry(self):
        bad_legs = [
            {"account_name": "ASSET:TREASURY", "entry_type": "DEBIT", "amount_base_units": 100},
            {"account_name": "REVENUE:SETTLEMENT", "entry_type": "CREDIT", "amount_base_units": 50},
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

        self.assertIsNone(self.ledger.get_by_idempotency_key("bad-legs-entry"))

    # ─────────────────────────────────────────────────────────────────────────
    # 10. Database Disconnection Fails Closed
    # ─────────────────────────────────────────────────────────────────────────

    def test_loss_of_db_connection_fails_closed_and_raises_error(self):
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
                tx_signature="sig-disconnect",
            )


if __name__ == "__main__":
    unittest.main()
