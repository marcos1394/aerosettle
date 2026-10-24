"""CON-30 pure arithmetic, evidence, overlap and ledger read isolation."""
import tempfile
import unittest
from pathlib import Path

from tools.economic_ledger.budget_policies import BudgetPolicyStore
from tools.economic_ledger.investible_surplus import (
    SurplusError, assess_agent_surplus, assess_investible_surplus,
)
from tools.economic_ledger.ledger import EconomicLedger, IsolatedTestReconcilerVerifier
from tools.economic_ledger.models import MovementNature, MovementStatus, ReserveType
from tools.economic_ledger.test_budget_policies import (
    AGENT, AGENT_RECORD, MINT_TWO, OTHER, OWNER, body as policy_body,
)

NOW = 1_800_000_000
CONTEXT = {"agent_account": AGENT, "agent_id": AGENT_RECORD["agent_id"],
           "owner_pubkey": OWNER, "network": "solana:localnet",
           "genesis_hash": AGENT, "program_id": OTHER, "token_mint": MINT_TWO}


def inputs():
    return (
        dict(CONTEXT),
        {"available_base_units_str": "1000", "other_restrictions_base_units_str": "0",
         "data_as_of": NOW, "provenance": "SYNTHETIC_TEST", "ownership_verified": False,
         "coverage_complete": False, "evidence_references": ["fixture:treasury"]},
        {"accounting_reserved_base_units_str": "0", "eligible_policy_reserve_base_units_str": "0",
         "evidence_references": []},
        {"outstanding_base_units_str": "200", "not_reflected_in_treasury": True,
         "coverage_complete": True, "evidence_references": ["fixture:liability"]},
        {"pending_base_units_str": "100", "independent_of_ledger_costs": True,
         "coverage_complete": True, "evidence_references": ["fixture:claim"]},
        {"policy_id": "p1", "version": 1, "policy_hash": "a" * 64,
         "minimum_reserve_base_units_str": "150", "reserve_continuity_relation": "INDEPENDENT"},
        {"observed_cash_opex_base_units_str": "250", "observed_days": 30,
         "window_start": NOW - 30 * 86400, "window_end": NOW,
         "independent_of_liabilities": True, "coverage_complete": True,
         "evidence_references": ["fixture:opex"]},
        {"name": "BASE", "continuity_horizon_days": 30}, NOW,
    )


class PureSurplusTests(unittest.TestCase):
    def test_acceptance_fixture_is_estimate_not_verified_capital(self):
        args = inputs()
        result = assess_investible_surplus(*args)
        self.assertEqual(result["estimated_investible_surplus_base_units_str"], "300")
        self.assertIsNone(result["verified_investible_surplus_base_units_str"])
        self.assertEqual(result["calculation_status"], "ESTIMATED")
        self.assertEqual(result["provenance"], "SYNTHETIC_TEST")
        self.assertFalse(result["is_executable"])
        self.assertEqual(result, assess_investible_surplus(*args))

    def test_existing_reserve_is_not_deducted_twice(self):
        values = list(inputs())
        values[2] = {"accounting_reserved_base_units_str": "200",
                     "eligible_policy_reserve_base_units_str": "150", "evidence_references": ["reserve-1"]}
        result = assess_investible_surplus(*values)
        self.assertEqual(result["unfunded_policy_reserve_base_units_str"], "0")
        self.assertEqual(result["estimated_investible_surplus_base_units_str"], "450")
        reserve = result["deductions"][0]
        self.assertTrue(reserve["already_reflected_in_treasury"])
        self.assertFalse(reserve["applied_to_surplus"])

    def test_other_purpose_reserve_does_not_cover_policy_minimum(self):
        values = list(inputs())
        values[2] = {"accounting_reserved_base_units_str": "200",
                     "eligible_policy_reserve_base_units_str": "0", "evidence_references": ["hardware-reserve"]}
        result = assess_investible_surplus(*values)
        self.assertEqual(result["unfunded_policy_reserve_base_units_str"], "150")
        self.assertEqual(result["estimated_investible_surplus_base_units_str"], "300")

    def test_same_purpose_reserve_nets_only_the_overlapping_buffer(self):
        values = list(inputs())
        values[5] = {**values[5], "reserve_continuity_relation": "SAME_PURPOSE"}
        result = assess_investible_surplus(*values)
        self.assertEqual(result["operational_buffer_base_units_str"], "100")
        self.assertEqual(result["estimated_investible_surplus_base_units_str"], "450")
        values[5] = {**values[5], "reserve_continuity_relation": "UNKNOWN"}
        self.assertEqual(assess_investible_surplus(*values)["calculation_status"], "INSUFFICIENT_DATA")

    def test_unknown_overlap_or_cash_burn_never_becomes_zero(self):
        values = list(inputs())
        values[4] = {**values[4], "independent_of_ledger_costs": False}
        result = assess_investible_surplus(*values)
        self.assertEqual(result["calculation_status"], "INSUFFICIENT_DATA")
        self.assertIsNone(result["estimated_investible_surplus_base_units_str"])
        self.assertIsNone(result["verified_investible_surplus_base_units_str"])
        values = list(inputs())
        values[6] = {**values[6], "observed_cash_opex_base_units_str": None}
        self.assertIn("cash_opex", assess_investible_surplus(*values)["exclusion_reasons"])
        values[6] = {**values[6], "observed_cash_opex_base_units_str": "0", "coverage_complete": False}
        self.assertIn("zero_opex_coverage", assess_investible_surplus(*values)["exclusion_reasons"])
        values = list(inputs())
        values[6] = {**values[6], "coverage_complete": False}
        self.assertIn("opex_window_coverage", assess_investible_surplus(*values)["exclusion_reasons"])
        values[6] = {**values[6], "explicit_estimation_assumption": True}
        estimate = assess_investible_surplus(*values)
        self.assertEqual(estimate["calculation_status"], "ESTIMATED")
        self.assertTrue(estimate["scenario_assumptions"]["opex_window_estimation_assumed"])

    def test_stress_never_increases_surplus_and_horizons_are_monotone(self):
        values = list(inputs())
        baseline = assess_investible_surplus(*values)
        for name in ("CONSERVATIVE", "STRESS"):
            values[7] = {"name": name, "continuity_horizon_days": 30}
            result = assess_investible_surplus(*values)
            self.assertLessEqual(int(result["estimated_investible_surplus_base_units_str"]),
                                 int(baseline["estimated_investible_surplus_base_units_str"]))
        values[7] = {"name": "BASE", "continuity_horizon_days": 90}
        self.assertLessEqual(int(assess_investible_surplus(*values)["estimated_investible_surplus_base_units_str"]), 300)

    def test_stale_and_unverified_are_distinct(self):
        values = list(inputs())
        values[1] = {**values[1], "data_as_of": NOW - 86401}
        result = assess_investible_surplus(*values)
        self.assertEqual(result["calculation_status"], "STALE_DATA")
        self.assertIsNone(result["estimated_investible_surplus_base_units_str"])
        values = list(inputs())
        values[1] = {**values[1], "provenance": "LIVE_RPC", "ownership_verified": True,
                     "coverage_complete": True, "authenticated": True}
        for index in (2, 3, 4, 6):
            values[index] = {**values[index], "coverage_complete": True, "authenticated": True}
        values[5] = {**values[5], "authenticated": True}
        result = assess_investible_surplus(*values)
        self.assertEqual(result["calculation_status"], "VERIFIED")
        self.assertEqual(result["verified_investible_surplus_base_units_str"], "300")

    def test_context_and_amount_validation(self):
        values = list(inputs())
        values[0] = {**values[0], "genesis_hash": "PENDING_RESOLUTION"}
        with self.assertRaises(SurplusError):
            assess_investible_surplus(*values)
        for bad in ("-1", "1.2", 1.0, str(2**64)):
            values = list(inputs())
            values[1] = {**values[1], "available_base_units_str": bad}
            with self.assertRaises(SurplusError):
                assess_investible_surplus(*values)
        values = list(inputs())
        values[1] = {**values[1], "available_base_units_str": str(2**64 - 1)}
        self.assertEqual(assess_investible_surplus(*values)["treasury_available_base_units_str"], str(2**64 - 1))
        values = list(inputs())
        values[6] = {**values[6], "observed_cash_opex_base_units_str": str(2**64 - 1)}
        values[7] = {"name": "STRESS", "continuity_horizon_days": 90}
        with self.assertRaises(SurplusError) as overflow:
            assess_investible_surplus(*values)
        self.assertEqual(overflow.exception.code, "AMOUNT_OVERFLOW")

    def test_context_identity_changes_assessment_hash_without_mixing_amounts(self):
        original = assess_investible_surplus(*inputs())
        for key, changed in (("agent_account", MINT_TWO), ("owner_pubkey", OTHER),
                             ("token_mint", AGENT), ("network", "solana:devnet"),
                             ("genesis_hash", OTHER), ("program_id", OWNER)):
            values = list(inputs())
            values[0] = {**values[0], key: changed}
            result = assess_investible_surplus(*values)
            self.assertNotEqual(result["assessment_hash"], original["assessment_hash"])
            self.assertEqual(result["estimated_investible_surplus_base_units_str"], "300")


class ReadOnlyAdapterTests(unittest.TestCase):
    def test_empty_ledger_is_insufficient_and_financial_tables_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = EconomicLedger(Path(directory) / "surplus.db")
            policies = BudgetPolicyStore(ledger)
            create = policy_body()
            policies.mutate(AGENT_RECORD, "CREATE", create, OWNER)
            active = policies.mutate(AGENT_RECORD, "ACTIVATE", policy_body("ACTIVATE", 1, "00000002"), OWNER)[0]
            mint = active["asset_rules"][0]["token_mint"]
            tables = ("economic_movements", "journal_entries", "ledger_entries", "agent_costs", "agent_reserves",
                      "reserve_transactions", "spending_proposals", "spending_decisions", "spending_budget_claims",
                      "spending_approvals", "spending_approval_events")
            before = {table: ledger._conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in tables}
            result = assess_agent_surplus(ledger, policies, AGENT_RECORD, network=active["network"],
                genesis_hash=active["genesis_hash"], program_id=active["program_id"], token_mint=mint,
                now=NOW)
            after = {table: ledger._conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in tables}
            self.assertEqual(before, after)
            self.assertEqual(result["calculation_status"], "INSUFFICIENT_DATA")
            self.assertIsNone(result["treasury_available_base_units_str"])
            self.assertIsNone(result["verified_investible_surplus_base_units_str"])
            ledger.close()

    def test_real_ledger_reserve_is_already_outside_treasury(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = EconomicLedger(Path(directory) / "reserve.db",
                                    reconciliation_verifier=IsolatedTestReconcilerVerifier())
            policies = BudgetPolicyStore(ledger)
            policies.mutate(AGENT_RECORD, "CREATE", policy_body(), OWNER)
            active = policies.mutate(AGENT_RECORD, "ACTIVATE",
                policy_body("ACTIVATE", 1, "00000002"), OWNER)[0]
            mint = active["asset_rules"][0]["token_mint"]
            scope = dict(agent_id=AGENT_RECORD["agent_id"], agent_account=AGENT,
                         owner_pubkey=OWNER, network=active["network"],
                         genesis_hash=active["genesis_hash"], program_id=active["program_id"],
                         token_mint=mint)
            movement = ledger.record_movement(idempotency_key="surplus-income", amount_base_units=1000,
                nature=MovementNature.INCOME, status=MovementStatus.PROVISIONAL,
                tx_signature="5SurplusFixtureSig11111111111111111111111111111", **scope)
            ledger.reconcile_movement(movement.movement_id,
                evidence_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                authorized_by="conatus:protocol:reconciler:v1", slot=1000,
                tx_signature="5SurplusFixtureSig11111111111111111111111111111")
            ledger.create_or_allocate_reserve(idempotency_key="surplus-reserve",
                reserve_type=ReserveType.OPERATIONAL_CONTINUITY, amount_base_units=200, **scope)
            result = assess_agent_surplus(ledger, policies, AGENT_RECORD,
                network=active["network"], genesis_hash=active["genesis_hash"],
                program_id=active["program_id"], token_mint=mint)
            self.assertEqual(result["treasury_available_base_units_str"], "800")
            self.assertEqual(result["accounting_reserved_base_units_str"], "200")
            self.assertTrue(result["deductions"][0]["already_reflected_in_treasury"])
            self.assertFalse(result["deductions"][0]["applied_to_surplus"])
            self.assertIsNone(result["verified_investible_surplus_base_units_str"])
            ledger.close()


if __name__ == "__main__":
    unittest.main()
