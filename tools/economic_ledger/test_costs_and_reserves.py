"""Comprehensive test suite for Conatus Agent Costs and Reserves (CON-24)."""
import tempfile
import unittest
from pathlib import Path

from tools.economic_ledger.ledger import (
    EconomicLedger,
    IsolatedTestReconcilerVerifier,
)
from tools.economic_ledger.models import (
    CostCategory,
    CostNature,
    EntryType,
    IdempotencyConflictError,
    LedgerValidationError,
    MovementNature,
    MovementStatus,
    ProvenanceSource,
    ReserveAction,
    ReserveStatus,
    ReserveType,
)

AGENT_1 = "DcusvnYAdFFKzNDVzUkUvmgZ9fDhzszeRR5Fj8F5dMbB"
AGENT_2 = "FPbX4tQ2t9KSUDPix3NxBVEp2dD5LWoikhBVYYafU9H7"
OWNER_1 = "8rPDpYsLZxNBm8Q8GKSKki8Ag6dodkasedhUT9x3Ec1D"
MINT_USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
MINT_EURC = "HzwqbKZw8HxMN6bF2yFZNrht3c2iXXzpKcFu7uBEDKtr"
PROGRAM_ID = "CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy"
GENESIS_HASH = "HP9XKTusRPGC78EFDpR9xdEq6simL2vqyDdrMvn6Vacg"
NET_LOCALNET = "solana:localnet"
NET_MAINNET = "solana:mainnet-beta"
VALID_HASH = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


class AgentCostsAndReservesTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_ledger_costs.db"
        self.test_verifier = IsolatedTestReconcilerVerifier()
        self.ledger = EconomicLedger(self.db_path, reconciliation_verifier=self.test_verifier)

    def tearDown(self):
        self.ledger.close()
        self.temp_dir.cleanup()

    def _fund_agent(self, agent_account=AGENT_1, mint=MINT_USDC, network=NET_LOCALNET, amount=100_000_000):
        """Helper to record reconciled income so agent has positive balance."""
        sig = f"5FundSig{amount}{agent_account[:8]}"
        m = self.ledger.record_movement(
            idempotency_key=f"fund-{agent_account}-{mint}-{network}-{amount}",
            agent_id="11" * 32,
            agent_account=agent_account,
            owner_pubkey=OWNER_1,
            network=network,
            genesis_hash=GENESIS_HASH,
            program_id=PROGRAM_ID,
            token_mint=mint,
            amount_base_units=amount,
            nature=MovementNature.INCOME,
            status=MovementStatus.PROVISIONAL,
            tx_signature=sig,
        )
        return self.ledger.reconcile_movement(
            m.movement_id,
            evidence_hash=VALID_HASH,
            authorized_by="conatus:protocol:reconciler:v1",
            slot=1000,
            tx_signature=sig,
        )

    def _summary(self, agent_account=AGENT_1, network=NET_LOCALNET, token_mint=MINT_USDC, economic_period=None):
        summaries = self.ledger.get_economic_summary(
            agent_account,
            network=network,
            token_mint=token_mint,
            economic_period=economic_period,
        )
        return summaries[0] if summaries else None

    # ─────────────────────────────────────────────────────────────────────────
    # 1. Duplicate Cost Detection & Idempotency Conflict
    # ─────────────────────────────────────────────────────────────────────────

    def test_duplicate_cost_is_strictly_idempotent_when_matching(self):
        self._fund_agent(amount=50_000_000)
        key = "cost-idem-001"

        c1 = self.ledger.record_cost(
            idempotency_key=key,
            agent_id="11" * 32,
            agent_account=AGENT_1,
            owner_pubkey=OWNER_1,
            category=CostCategory.ENERGY_FUEL,
            cost_nature=CostNature.REALIZED,
            economic_period="2026-10",
            network=NET_LOCALNET,
            token_mint=MINT_USDC,
            amount_base_units=10_000_000,
            description="Recharge at Solar Station Alpha",
        )

        c2 = self.ledger.record_cost(
            idempotency_key=key,
            agent_id="11" * 32,
            agent_account=AGENT_1,
            owner_pubkey=OWNER_1,
            category=CostCategory.ENERGY_FUEL,
            cost_nature=CostNature.REALIZED,
            economic_period="2026-10",
            network=NET_LOCALNET,
            token_mint=MINT_USDC,
            amount_base_units=10_000_000,
            description="Recharge at Solar Station Alpha",
        )

        self.assertEqual(c1.cost_id, c2.cost_id)
        self.assertEqual(c1.amount_base_units, c2.amount_base_units)

        # Ensure only 1 cost record exists
        costs, _ = self.ledger.list_costs(AGENT_1)
        self.assertEqual(len(costs), 1)

    def test_duplicate_cost_with_tampered_payload_raises_idempotency_conflict(self):
        self._fund_agent(amount=50_000_000)
        key = "cost-conflict-001"

        self.ledger.record_cost(
            idempotency_key=key,
            agent_id="11" * 32,
            agent_account=AGENT_1,
            owner_pubkey=OWNER_1,
            category=CostCategory.ENERGY_FUEL,
            cost_nature=CostNature.REALIZED,
            economic_period="2026-10",
            network=NET_LOCALNET,
            token_mint=MINT_USDC,
            amount_base_units=10_000_000,
        )

        # Alter amount
        with self.assertRaises(IdempotencyConflictError):
            self.ledger.record_cost(
                idempotency_key=key,
                agent_id="11" * 32,
                agent_account=AGENT_1,
                owner_pubkey=OWNER_1,
                category=CostCategory.ENERGY_FUEL,
                cost_nature=CostNature.REALIZED,
                economic_period="2026-10",
                network=NET_LOCALNET,
                token_mint=MINT_USDC,
                amount_base_units=15_000_000,
            )

        # Alter category
        with self.assertRaises(IdempotencyConflictError):
            self.ledger.record_cost(
                idempotency_key=key,
                agent_id="11" * 32,
                agent_account=AGENT_1,
                owner_pubkey=OWNER_1,
                category=CostCategory.MAINTENANCE,
                cost_nature=CostNature.REALIZED,
                economic_period="2026-10",
                network=NET_LOCALNET,
                token_mint=MINT_USDC,
                amount_base_units=10_000_000,
            )

    # ─────────────────────────────────────────────────────────────────────────
    # 2. Capital Reserves Without Expense (No Reduction in Net Worth)
    # ─────────────────────────────────────────────────────────────────────────

    def test_reserve_allocation_without_expense_preserves_net_worth(self):
        self._fund_agent(amount=100_000_000)

        # Allocate 40 USDC to MAINTENANCE reserve
        res = self.ledger.create_or_allocate_reserve(
            idempotency_key="res-alloc-001",
            agent_id="11" * 32,
            agent_account=AGENT_1,
            owner_pubkey=OWNER_1,
            reserve_type=ReserveType.MAINTENANCE,
            network=NET_LOCALNET,
            token_mint=MINT_USDC,
            amount_base_units=40_000_000,
            description="Motor replacement fund",
        )

        self.assertEqual(res.status, ReserveStatus.ACTIVE)
        self.assertEqual(res.current_reserved_base_units, 40_000_000)

        # Verify economic summary
        summary = self._summary()
        self.assertIsNotNone(summary)
        self.assertEqual(summary.total_income_reconciled, 100_000_000)
        self.assertEqual(summary.total_expenses_realized, 0, "Reserve allocation must NOT count as expense!")
        self.assertEqual(summary.total_capital_reserved, 40_000_000)
        self.assertEqual(summary.available_balance, 60_000_000)
        self.assertEqual(summary.total_effective_balance, 100_000_000, "Net worth must remain unchanged!")

        # Verify double-entry consistency
        totals = self.ledger.get_ledger_totals()
        self.assertTrue(totals["is_balanced"])

    # ─────────────────────────────────────────────────────────────────────────
    # 3. Partial Reserve Consumption (No Double Counting)
    # ─────────────────────────────────────────────────────────────────────────

    def test_partial_reserve_consumption_and_accounting_integrity(self):
        self._fund_agent(amount=100_000_000)

        # Step 1: Allocate 50 USDC to HARDWARE_REPLACEMENT
        res = self.ledger.create_or_allocate_reserve(
            idempotency_key="res-hard-001",
            agent_id="11" * 32,
            agent_account=AGENT_1,
            owner_pubkey=OWNER_1,
            reserve_type=ReserveType.HARDWARE_REPLACEMENT,
            network=NET_LOCALNET,
            token_mint=MINT_USDC,
            amount_base_units=50_000_000,
        )

        # Step 2: Incur realized cost of 20 USDC drawn from the reserve
        cost = self.ledger.record_cost(
            idempotency_key="cost-from-res-001",
            agent_id="11" * 32,
            agent_account=AGENT_1,
            owner_pubkey=OWNER_1,
            category=CostCategory.MAINTENANCE,
            cost_nature=CostNature.REALIZED,
            economic_period="2026-10",
            network=NET_LOCALNET,
            token_mint=MINT_USDC,
            amount_base_units=20_000_000,
            from_reserve_id=res.reserve_id,
            description="Propeller swap",
        )

        # Reserve balance must decrease to 30 USDC
        updated_res = self.ledger.get_reserve(res.reserve_id)
        self.assertEqual(updated_res.current_reserved_base_units, 30_000_000)
        self.assertEqual(updated_res.status, ReserveStatus.ACTIVE)

        summary = self._summary()
        self.assertIsNotNone(summary)
        self.assertEqual(summary.total_income_reconciled, 100_000_000)
        self.assertEqual(summary.total_expenses_realized, 20_000_000)
        self.assertEqual(summary.total_capital_reserved, 30_000_000)
        self.assertEqual(summary.available_balance, 50_000_000)
        self.assertEqual(summary.total_effective_balance, 80_000_000)

        # Audit trail check in reserve_transactions
        cur = self.ledger._conn.execute(
            "SELECT action, amount_base_units, associated_cost_id FROM reserve_transactions WHERE reserve_id = ? ORDER BY rowid ASC",
            (res.reserve_id,),
        )
        rows = cur.fetchall()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["action"], ReserveAction.ALLOCATE.value)
        self.assertEqual(int(rows[0]["amount_base_units"]), 50_000_000)
        self.assertEqual(rows[1]["action"], ReserveAction.CONSUME.value)
        self.assertEqual(int(rows[1]["amount_base_units"]), 20_000_000)
        self.assertEqual(rows[1]["associated_cost_id"], cost.cost_id)

        self.assertTrue(self.ledger.get_ledger_totals()["is_balanced"])

    def test_overdrawing_reserve_raises_validation_error(self):
        self._fund_agent(amount=100_000_000)
        res = self.ledger.create_or_allocate_reserve(
            idempotency_key="res-small-001",
            agent_id="11" * 32,
            agent_account=AGENT_1,
            owner_pubkey=OWNER_1,
            reserve_type=ReserveType.CONTINGENCY,
            network=NET_LOCALNET,
            token_mint=MINT_USDC,
            amount_base_units=10_000_000,
        )

        with self.assertRaises(LedgerValidationError):
            self.ledger.record_cost(
                idempotency_key="cost-overdraw-001",
                agent_id="11" * 32,
                agent_account=AGENT_1,
                owner_pubkey=OWNER_1,
                category=CostCategory.OTHER,
                cost_nature=CostNature.REALIZED,
                economic_period="2026-10",
                network=NET_LOCALNET,
                token_mint=MINT_USDC,
                amount_base_units=15_000_000,  # exceeds 10M reserve
                from_reserve_id=res.reserve_id,
            )

    # ─────────────────────────────────────────────────────────────────────────
    # 4. Reversal of an Expense & Restoring Reserve/Treasury
    # ─────────────────────────────────────────────────────────────────────────

    def test_revert_cost_drawn_from_reserve_restores_reserve_balance(self):
        self._fund_agent(amount=100_000_000)
        res = self.ledger.create_or_allocate_reserve(
            idempotency_key="res-rev-001",
            agent_id="11" * 32,
            agent_account=AGENT_1,
            owner_pubkey=OWNER_1,
            reserve_type=ReserveType.MAINTENANCE,
            network=NET_LOCALNET,
            token_mint=MINT_USDC,
            amount_base_units=50_000_000,
        )

        cost = self.ledger.record_cost(
            idempotency_key="cost-to-revert-001",
            agent_id="11" * 32,
            agent_account=AGENT_1,
            owner_pubkey=OWNER_1,
            category=CostCategory.MAINTENANCE,
            cost_nature=CostNature.REALIZED,
            economic_period="2026-10",
            network=NET_LOCALNET,
            token_mint=MINT_USDC,
            amount_base_units=25_000_000,
            from_reserve_id=res.reserve_id,
            description="Faulty sensor purchase",
        )

        # Before revert: reserve has 25M, realized expense 25M
        res_mid = self.ledger.get_reserve(res.reserve_id)
        self.assertEqual(res_mid.current_reserved_base_units, 25_000_000)

        # Revert cost
        reverted, comp = self.ledger.revert_cost(cost.cost_id, reason="Vendor full refund")
        self.assertEqual(reverted.status, MovementStatus.REVERTED)
        self.assertEqual(comp.reversal_of_cost_id, cost.cost_id)

        # After revert: reserve must be restored to 50M
        res_after = self.ledger.get_reserve(res.reserve_id)
        self.assertEqual(res_after.current_reserved_base_units, 50_000_000)

        summary = self._summary()
        self.assertIsNotNone(summary)
        self.assertEqual(summary.total_expenses_realized, 0)
        self.assertEqual(summary.total_capital_reserved, 50_000_000)
        self.assertEqual(summary.available_balance, 50_000_000)
        self.assertEqual(summary.total_effective_balance, 100_000_000)

        self.assertTrue(self.ledger.get_ledger_totals()["is_balanced"])

    def test_revert_direct_realized_cost_restores_treasury_cash(self):
        self._fund_agent(amount=100_000_000)
        cost = self.ledger.record_cost(
            idempotency_key="cost-direct-revert-001",
            agent_id="11" * 32,
            agent_account=AGENT_1,
            owner_pubkey=OWNER_1,
            category=CostCategory.CONNECTIVITY_COMPUTE,
            cost_nature=CostNature.REALIZED,
            economic_period="2026-10",
            network=NET_LOCALNET,
            token_mint=MINT_USDC,
            amount_base_units=30_000_000,
            description="Satellite uplink",
        )

        sum_before = self._summary()
        self.assertIsNotNone(sum_before)
        self.assertEqual(sum_before.available_balance, 70_000_000)
        self.assertEqual(sum_before.total_expenses_realized, 30_000_000)

        self.ledger.revert_cost(cost.cost_id, reason="Subscription cancelled and refunded")

        sum_after = self._summary()
        self.assertIsNotNone(sum_after)
        self.assertEqual(sum_after.available_balance, 100_000_000)
        self.assertEqual(sum_after.total_expenses_realized, 0)
        self.assertTrue(self.ledger.get_ledger_totals()["is_balanced"])

    # ─────────────────────────────────────────────────────────────────────────
    # 5. Multi-Mint and Multi-Network Segregation
    # ─────────────────────────────────────────────────────────────────────────

    def test_multi_mint_and_network_strict_segregation(self):
        # Fund 100 USDC on localnet, and 50 EURC on localnet
        self._fund_agent(amount=100_000_000, mint=MINT_USDC, network=NET_LOCALNET)
        self._fund_agent(amount=50_000_000, mint=MINT_EURC, network=NET_LOCALNET)

        # Allocate reserve in USDC
        res_usdc = self.ledger.create_or_allocate_reserve(
            idempotency_key="res-usdc-seg",
            agent_id="11" * 32,
            agent_account=AGENT_1,
            owner_pubkey=OWNER_1,
            reserve_type=ReserveType.OPERATIONAL_CONTINUITY,
            network=NET_LOCALNET,
            token_mint=MINT_USDC,
            amount_base_units=30_000_000,
        )

        # Attempt to consume USDC reserve with EURC cost -> Must Fail
        with self.assertRaises(LedgerValidationError):
            self.ledger.record_cost(
                idempotency_key="cost-mismatched-mint",
                agent_id="11" * 32,
                agent_account=AGENT_1,
                owner_pubkey=OWNER_1,
                category=CostCategory.ENERGY_FUEL,
                cost_nature=CostNature.REALIZED,
                economic_period="2026-10",
                network=NET_LOCALNET,
                token_mint=MINT_EURC,  # EURC cost attempting to use USDC reserve
                amount_base_units=10_000_000,
                from_reserve_id=res_usdc.reserve_id,
            )

        # Check summaries independently
        sum_usdc = self._summary(token_mint=MINT_USDC)
        self.assertIsNotNone(sum_usdc)
        self.assertEqual(sum_usdc.total_income_reconciled, 100_000_000)
        self.assertEqual(sum_usdc.total_capital_reserved, 30_000_000)
        self.assertEqual(sum_usdc.available_balance, 70_000_000)

        sum_eurc = self._summary(token_mint=MINT_EURC)
        self.assertIsNotNone(sum_eurc)
        self.assertEqual(sum_eurc.total_income_reconciled, 50_000_000)
        self.assertEqual(sum_eurc.total_capital_reserved, 0)
        self.assertEqual(sum_eurc.available_balance, 50_000_000)

    # ─────────────────────────────────────────────────────────────────────────
    # 6. Arbitrary Precision u64 Amounts
    # ─────────────────────────────────────────────────────────────────────────

    def test_u64_large_amounts_handled_with_full_precision(self):
        huge_amount = 18_000_000_000_000_000_000  # Within u64 max
        self._fund_agent(amount=huge_amount)

        res = self.ledger.create_or_allocate_reserve(
            idempotency_key="res-huge-001",
            agent_id="11" * 32,
            agent_account=AGENT_1,
            owner_pubkey=OWNER_1,
            reserve_type=ReserveType.CONTINGENCY,
            network=NET_LOCALNET,
            token_mint=MINT_USDC,
            amount_base_units=9_000_000_000_000_000_000,
        )

        self.ledger.record_cost(
            idempotency_key="cost-huge-001",
            agent_id="11" * 32,
            agent_account=AGENT_1,
            owner_pubkey=OWNER_1,
            category=CostCategory.DEPRECIATION_REPLACEMENT,
            cost_nature=CostNature.REALIZED,
            economic_period="2026-10",
            network=NET_LOCALNET,
            token_mint=MINT_USDC,
            amount_base_units=4_000_000_000_000_000_000,
            from_reserve_id=res.reserve_id,
        )

        summary = self._summary()
        self.assertIsNotNone(summary)
        self.assertEqual(summary.total_income_reconciled, huge_amount)
        self.assertEqual(summary.total_expenses_realized, 4_000_000_000_000_000_000)
        self.assertEqual(summary.total_capital_reserved, 5_000_000_000_000_000_000)
        self.assertEqual(summary.available_balance, 9_000_000_000_000_000_000)
        self.assertTrue(self.ledger.get_ledger_totals()["is_balanced"])

    # ─────────────────────────────────────────────────────────────────────────
    # 7. Economic Period Filtering
    # ─────────────────────────────────────────────────────────────────────────

    def test_economic_period_filtering(self):
        self._fund_agent(amount=100_000_000)

        self.ledger.record_cost(
            idempotency_key="cost-p1",
            agent_id="11" * 32,
            agent_account=AGENT_1,
            owner_pubkey=OWNER_1,
            category=CostCategory.ENERGY_FUEL,
            cost_nature=CostNature.REALIZED,
            economic_period="2026-Q1",
            network=NET_LOCALNET,
            token_mint=MINT_USDC,
            amount_base_units=10_000_000,
        )

        self.ledger.record_cost(
            idempotency_key="cost-p2",
            agent_id="11" * 32,
            agent_account=AGENT_1,
            owner_pubkey=OWNER_1,
            category=CostCategory.ENERGY_FUEL,
            cost_nature=CostNature.REALIZED,
            economic_period="2026-Q2",
            network=NET_LOCALNET,
            token_mint=MINT_USDC,
            amount_base_units=15_000_000,
        )

        costs_q1, _ = self.ledger.list_costs(AGENT_1, economic_period="2026-Q1")
        self.assertEqual(len(costs_q1), 1)
        self.assertEqual(costs_q1[0].economic_period, "2026-Q1")

        costs_q2, _ = self.ledger.list_costs(AGENT_1, economic_period="2026-Q2")
        self.assertEqual(len(costs_q2), 1)
        self.assertEqual(costs_q2[0].economic_period, "2026-Q2")

        sum_q1 = self._summary(economic_period="2026-Q1")
        self.assertIsNotNone(sum_q1)
        self.assertEqual(sum_q1.total_expenses_realized, 10_000_000)

    # ─────────────────────────────────────────────────────────────────────────
    # 8. Evidence Handling & Fail Closed Rules
    # ─────────────────────────────────────────────────────────────────────────

    def test_unverified_evidence_url_or_hash_fails_closed(self):
        self._fund_agent(amount=50_000_000)

        # Attempting EXTERNAL_VERIFIED without an attestation_id must raise LedgerValidationError
        with self.assertRaises(LedgerValidationError):
            self.ledger.record_cost(
                idempotency_key="cost-unauth-ext-ver",
                agent_id="11" * 32,
                agent_account=AGENT_1,
                owner_pubkey=OWNER_1,
                category=CostCategory.SUBSCRIPTIONS,
                cost_nature=CostNature.REALIZED,
                economic_period="2026-10",
                network=NET_LOCALNET,
                token_mint=MINT_USDC,
                amount_base_units=5_000_000,
                provenance_source=ProvenanceSource.EXTERNAL_VERIFIED,
                evidence_hash=VALID_HASH,
                evidence_url="https://vendor.example.com/invoice.pdf",
                # attestation_id missing!
            )

        # When recorded with MANUAL_ENTRY, status must remain PROVISIONAL regardless of evidence hash
        cost_manual = self.ledger.record_cost(
            idempotency_key="cost-manual-with-evidence",
            agent_id="11" * 32,
            agent_account=AGENT_1,
            owner_pubkey=OWNER_1,
            category=CostCategory.SUBSCRIPTIONS,
            cost_nature=CostNature.REALIZED,
            economic_period="2026-10",
            network=NET_LOCALNET,
            token_mint=MINT_USDC,
            amount_base_units=5_000_000,
            provenance_source=ProvenanceSource.MANUAL_ENTRY,
            evidence_hash=VALID_HASH,
            evidence_url="https://vendor.example.com/invoice.pdf",
        )
        self.assertEqual(cost_manual.status, MovementStatus.PROVISIONAL)
        self.assertEqual(cost_manual.provenance_source, ProvenanceSource.MANUAL_ENTRY)

    # ─────────────────────────────────────────────────────────────────────────
    # 9. Informational Budget Estimations (No Cash / Balance Impact)
    # ─────────────────────────────────────────────────────────────────────────

    def test_estimated_cost_budgeting_does_not_affect_cash_or_balances(self):
        self._fund_agent(amount=50_000_000)

        est_cost = self.ledger.record_cost(
            idempotency_key="cost-budget-estimate-001",
            agent_id="11" * 32,
            agent_account=AGENT_1,
            owner_pubkey=OWNER_1,
            category=CostCategory.MAINTENANCE,
            cost_nature=CostNature.ESTIMATED,
            economic_period="2026-11",
            network=NET_LOCALNET,
            token_mint=MINT_USDC,
            amount_base_units=20_000_000,
            description="Projected scheduled maintenance next month",
        )

        self.assertIsNone(est_cost.journal_entry_id, "Estimations must not generate journal entries!")

        summary = self._summary()
        self.assertIsNotNone(summary)
        self.assertEqual(summary.total_estimated_costs, 20_000_000)
        self.assertEqual(summary.total_expenses_realized, 0)
        self.assertEqual(summary.available_balance, 50_000_000, "Cash must be completely untouched by estimates!")
        self.assertEqual(summary.total_effective_balance, 50_000_000)

    # ─────────────────────────────────────────────────────────────────────────
    # 10. Accrued Liability Provisions (Obligation Without Touching Cash)
    # ─────────────────────────────────────────────────────────────────────────

    def test_accrued_liability_provision_records_obligation_without_reducing_cash(self):
        self._fund_agent(amount=50_000_000)

        prov = self.ledger.record_cost(
            idempotency_key="cost-accrued-prov-001",
            agent_id="11" * 32,
            agent_account=AGENT_1,
            owner_pubkey=OWNER_1,
            category=CostCategory.INSURANCE,
            cost_nature=CostNature.ACCRUED_LIABILITY,
            economic_period="2026-10",
            network=NET_LOCALNET,
            token_mint=MINT_USDC,
            amount_base_units=12_000_000,
            description="Accrued annual liability premium payable next quarter",
        )

        self.assertIsNotNone(prov.journal_entry_id)

        # Journal entry must debit EXPENSE and credit LIABILITY:ACCRUED_EXPENSES, NOT ASSET:TREASURY!
        journal = self.ledger.get_journal_entry(prov.journal_entry_id)
        self.assertIsNotNone(journal)
        account_names = [leg.account_name for leg in journal.legs]
        self.assertIn("EXPENSE:INSURANCE", account_names)
        self.assertIn("LIABILITY:ACCRUED_EXPENSES", account_names)
        self.assertNotIn("ASSET:TREASURY", account_names, "Treasury cash must not be touched for accrued liability!")

        summary = self._summary()
        self.assertIsNotNone(summary)
        self.assertEqual(summary.total_obligations_accrued, 12_000_000)
        self.assertEqual(summary.total_expenses_realized, 0)
        self.assertEqual(summary.available_balance, 50_000_000, "Cash remains full 50M until paid!")
        self.assertTrue(self.ledger.get_ledger_totals()["is_balanced"])

    # ─────────────────────────────────────────────────────────────────────────
    # 11. Internal Transfers & Capital Investments (CAPEX)
    # ─────────────────────────────────────────────────────────────────────────

    def test_internal_transfer_and_capital_investment(self):
        self._fund_agent(amount=100_000_000)

        # Internal transfer: move 20 USDC from OPERATIONAL to ESCROW subaccount
        xfer = self.ledger.record_internal_transfer(
            idempotency_key="xfer-int-001",
            agent_id="11" * 32,
            agent_account=AGENT_1,
            owner_pubkey=OWNER_1,
            network=NET_LOCALNET,
            genesis_hash=GENESIS_HASH,
            program_id=PROGRAM_ID,
            token_mint=MINT_USDC,
            amount_base_units=20_000_000,
            source_account_name="ASSET:OPERATIONAL",
            destination_account_name="ASSET:ESCROW_BUFFER",
            description="Internal escrow buffer",
        )
        self.assertEqual(xfer.nature, MovementNature.INTERNAL_TRANSFER)
        self.assertTrue(self.ledger.get_ledger_totals()["is_balanced"])

        # Capital investment: acquire fixed asset (CAPEX) for 35 USDC
        capex = self.ledger.record_capital_investment(
            idempotency_key="capex-001",
            agent_id="11" * 32,
            agent_account=AGENT_1,
            owner_pubkey=OWNER_1,
            network=NET_LOCALNET,
            genesis_hash=GENESIS_HASH,
            program_id=PROGRAM_ID,
            token_mint=MINT_USDC,
            amount_base_units=35_000_000,
            asset_category="EQUIPMENT",
            description="Sensor payload upgrade",
        )
        self.assertEqual(capex.nature, MovementNature.CAPITAL_INVESTMENT)
        self.assertTrue(self.ledger.get_ledger_totals()["is_balanced"])

        # Verify journal legs: Debits ASSET:EQUIPMENT, Credits ASSET:TREASURY
        journal = self.ledger.get_journal_entry(capex.journal_entry_id)
        self.assertIsNotNone(journal)
        legs_by_type = {leg.entry_type: leg for leg in journal.legs}
        self.assertEqual(legs_by_type[EntryType.DEBIT].account_name, "ASSET:EQUIPMENT")
        self.assertEqual(legs_by_type[EntryType.CREDIT].account_name, "ASSET:TREASURY")


if __name__ == "__main__":
    unittest.main()
