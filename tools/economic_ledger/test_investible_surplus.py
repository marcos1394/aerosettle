"""CON-30 pure arithmetic, evidence, overlap and ledger read isolation."""
import tempfile
import time
import unittest
import hashlib
import json
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric import ed25519

from tools.discovery.agent_discovery import b58encode
from tools.economic_ledger.budget_policies import BudgetPolicyStore, canonical, digest
from tools.economic_ledger.investible_surplus import (
    SurplusError, assess_agent_surplus, assess_investible_surplus,
)
from tools.economic_ledger.ledger import EconomicLedger, IsolatedTestReconcilerVerifier
from tools.economic_ledger.models import MovementNature, MovementStatus, ReserveType
from tools.economic_ledger.spending_approvals import (
    CONTEXT_FIELDS, SpendingApprovalStore, canonical_approval_message, verify_approval,
)
from tools.economic_ledger.spending_decisions import SpendingDecisionStore
from tools.economic_ledger.test_budget_policies import (
    AGENT, AGENT_RECORD, MINT, MINT_TWO, OTHER, OTHER_SECRET, OWNER, SECRET, body as policy_body,
)
from tools.economic_ledger.test_spending_approvals import synthetic_provider
from tools.economic_ledger.test_spending_decisions import proposal

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

    def test_positive_haircut_rounds_up_at_minimum_and_u64_limit(self):
        for balance, expected in ((1, 1), (2, 1), (10000, 1500),
                                  (2**64 - 1, (15 * (2**64 - 1) + 99) // 100)):
            values = list(inputs())
            values[1] = {**values[1], "available_base_units_str": str(balance)}
            values[7] = {"name": "STRESS", "continuity_horizon_days": 30}
            result = assess_investible_surplus(*values)
            self.assertEqual(result["liquidity_haircut_base_units_str"], str(expected))
            self.assertIsNone(result["verified_investible_surplus_base_units_str"])
            for component in result["deductions"]:
                if component["component"] == "LIQUIDITY_HAIRCUT":
                    self.assertEqual(component["amount_base_units_str"], str(expected))
            values[7] = {"name": "CONSERVATIVE", "continuity_horizon_days": 30}
            conservative = assess_investible_surplus(*values)
            self.assertLessEqual(int(conservative["liquidity_haircut_base_units_str"]), expected)
            values[7] = {"name": "BASE", "continuity_horizon_days": 30}
            self.assertEqual(assess_investible_surplus(*values)["liquidity_haircut_base_units_str"], "0")

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
    def _claim_fixture(self, path):
        ledger = EconomicLedger(path)
        policies = BudgetPolicyStore(ledger)
        create = policy_body()
        create["asset_rules"][0].update({
            "max_per_operation_base_units_str": "100", "max_daily_spend_base_units_str": "100",
            "minimum_reserve_base_units_str": "0"})
        policies.mutate(AGENT_RECORD, "CREATE", create, OWNER)
        active = policies.mutate(AGENT_RECORD, "ACTIVATE",
                                 policy_body("ACTIVATE", 1, "00000002"), OWNER)[0]
        decisions = SpendingDecisionStore(ledger, policies, synthetic_provider)
        decision = decisions.evaluate(AGENT_RECORD, proposal(active, amount="100"), OWNER)[0]
        self.assertEqual(decision["decision"], "ALLOW")
        approvals = SpendingApprovalStore(ledger, policies, decisions)
        context = approvals.context(AGENT_RECORD, decision["decision_id"])
        return ledger, policies, approvals, context, active

    def _approval_action(self, approvals, context, action, suffix):
        now = int(time.time())
        # Subsequent actions must reuse the immutable expiry chosen by OPEN.
        # Recomputing now + 120 can cross a second boundary on slower CI runners.
        existing = approvals.conn.execute(
            "SELECT expires_at FROM spending_approvals WHERE approval_id=?",
            (context["approval_id"],)).fetchone()
        expires_at = (existing["expires_at"] if existing is not None else
                      min(context["decision"]["expires_at"], now + 120))
        body = {**{key: context[key] for key in CONTEXT_FIELDS},
                "action": action, "issued_at": now,
                "expires_at": expires_at,
                "nonce": f"surplus-approval-nonce-{suffix}",
                "idempotency_key": f"surplus-approval-idem-{suffix}",
                "reason": "Owner declined request" if action in ("REVOKE", "REJECT") else ""}
        path = f"/v1/agents/{AGENT}/spending-approvals"
        if action != "OPEN":
            path += f"/{context['approval_id']}/{action.lower()}"
        message = canonical_approval_message(now, AGENT, OWNER, "POST", path, body)
        signature = b58encode(ed25519.Ed25519PrivateKey.from_private_bytes(SECRET).sign(message))
        actor, checked_signature, message_hash = verify_approval(AGENT_RECORD, "POST", path, body, {
            "X-Signer-Pubkey": OWNER, "X-Timestamp": str(now), "X-Signature": signature})
        return approvals.mutate(AGENT_RECORD, action, body, actor, checked_signature, message_hash)[0]

    def _assessment(self, ledger, policies, active, agent=AGENT_RECORD):
        return assess_agent_surplus(ledger, policies, agent, network=active["network"],
            genesis_hash=active["genesis_hash"], program_id=active["program_id"], token_mint=MINT)

    def _insert_invalid_event(self, ledger, approval_id_value, *, hash_chain=False, wrong_owner=False):
        row = dict(ledger._conn.execute(
            "SELECT * FROM spending_approval_events WHERE approval_id=? ORDER BY rowid DESC LIMIT 1",
            (approval_id_value,)).fetchone())
        previous_hash = row["event_hash"]
        row.update(event_id="ae_invalid_surplus_revoke", action="REVOKE",
                   idempotency_key="surplus-fake-revoke-idem", nonce="surplus-fake-revoke-nonce",
                   previous_event_hash="broken" if hash_chain else previous_hash)
        if hash_chain or wrong_owner:
            review = ledger._conn.execute("SELECT * FROM spending_approvals WHERE approval_id=?",
                                          (approval_id_value,)).fetchone()
            signer, secret = (OTHER, OTHER_SECRET) if wrong_owner else (OWNER, SECRET)
            now = int(time.time())
            body = {**{key: review[key] for key in CONTEXT_FIELDS},
                    "action": "REVOKE", "issued_at": now, "expires_at": review["expires_at"],
                    "nonce": row["nonce"], "idempotency_key": row["idempotency_key"],
                    "reason": "Owner withdrew consent"}
            path = f"/v1/agents/{AGENT}/spending-approvals/{approval_id_value}/revoke"
            message = canonical_approval_message(now, AGENT, signer, "POST", path, body)
            row.update(actor_pubkey=signer, occurred_at=now, reason=body["reason"],
                       signature=b58encode(ed25519.Ed25519PrivateKey.from_private_bytes(secret).sign(message)),
                       signature_message=message.decode("utf-8"),
                       signature_message_hash=hashlib.sha256(message).hexdigest(),
                       signed_body_json=canonical(body).decode("utf-8"), body_hash=digest(body))
            row["event_hash"] = digest({key: value for key, value in row.items() if key != "event_hash"})
        columns = list(row)
        ledger._conn.execute(
            f"INSERT INTO spending_approval_events ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
            tuple(row.values()))

    def test_forged_revoke_cannot_release_claim_or_write_financial_tables(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger, policies, approvals, context, active = self._claim_fixture(Path(directory) / "forged.db")
            try:
                self._approval_action(approvals, context, "OPEN", "open")
                self._approval_action(approvals, context, "APPROVE", "approve")
                before = self._assessment(ledger, policies, active)
                self.assertEqual(before["pending_commitments_base_units_str"], "100")
                financial = ("economic_movements", "journal_entries", "ledger_entries", "agent_costs", "agent_reserves")
                counts = {table: ledger._conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                          for table in financial}
                self._insert_invalid_event(ledger, context["approval_id"])
                with self.assertRaises(SurplusError) as conflict:
                    self._assessment(ledger, policies, active)
                self.assertEqual(conflict.exception.code, "APPROVAL_INTEGRITY_CONFLICT")
                self.assertEqual(counts, {table: ledger._conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                                          for table in financial})
            finally:
                ledger.close()

    def test_authentic_revoke_releases_only_administrative_claim(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger, policies, approvals, context, active = self._claim_fixture(Path(directory) / "authentic.db")
            try:
                self._approval_action(approvals, context, "OPEN", "open")
                self._approval_action(approvals, context, "APPROVE", "approve")
                self.assertEqual(self._assessment(ledger, policies, active)["pending_commitments_base_units_str"], "100")
                self._approval_action(approvals, context, "REVOKE", "revoke")
                result = self._assessment(ledger, policies, active)
                self.assertEqual(result["pending_commitments_base_units_str"], "0")
                self.assertEqual(result["calculation_status"], "INSUFFICIENT_DATA")
                self.assertIsNone(result["verified_investible_surplus_base_units_str"])
                self.assertEqual(ledger._conn.execute("SELECT count(*) FROM economic_movements").fetchone()[0], 0)
            finally:
                ledger.close()

    def test_authentic_reject_releases_only_administrative_claim(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger, policies, approvals, context, active = self._claim_fixture(Path(directory) / "rejected.db")
            try:
                self._approval_action(approvals, context, "OPEN", "open")
                self.assertEqual(self._assessment(ledger, policies, active)["pending_commitments_base_units_str"], "100")
                self._approval_action(approvals, context, "REJECT", "reject")
                result = self._assessment(ledger, policies, active)
                self.assertEqual(result["pending_commitments_base_units_str"], "0")
                self.assertIsNone(result["verified_investible_surplus_base_units_str"])
            finally:
                ledger.close()

    def test_review_expiry_stays_immutable_across_second_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger, policies, approvals, context, active = self._claim_fixture(
                Path(directory) / "review-expiry.db")
            try:
                self._approval_action(approvals, context, "OPEN", "open-delayed")
                stored = ledger._conn.execute(
                    "SELECT expires_at FROM spending_approvals WHERE approval_id=?",
                    (context["approval_id"],)).fetchone()["expires_at"]
                time.sleep(1.05)
                self._approval_action(approvals, context, "REJECT", "reject-delayed")
                current = ledger._conn.execute(
                    "SELECT expires_at FROM spending_approvals WHERE approval_id=?",
                    (context["approval_id"],)).fetchone()["expires_at"]
                self.assertEqual(current, stored)
                self.assertEqual(self._assessment(ledger, policies, active)
                                 ["pending_commitments_base_units_str"], "0")
            finally:
                ledger.close()

    def test_changed_identity_and_inconsistent_hash_chain_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger, policies, approvals, context, active = self._claim_fixture(Path(directory) / "identity.db")
            try:
                self._approval_action(approvals, context, "OPEN", "open")
                self._approval_action(approvals, context, "APPROVE", "approve")
                for changed in ({**AGENT_RECORD, "owner": OTHER},
                                {**AGENT_RECORD, "agent_id": "22" * 32}):
                    with self.assertRaises(SurplusError):
                        self._assessment(ledger, policies, active, changed)
                self._insert_invalid_event(ledger, context["approval_id"], hash_chain=True)
                with self.assertRaises(SurplusError) as conflict:
                    self._assessment(ledger, policies, active)
                self.assertEqual(conflict.exception.code, "APPROVAL_INTEGRITY_CONFLICT")
            finally:
                ledger.close()

    def test_other_owner_signed_revoke_cannot_release_claim(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger, policies, approvals, context, active = self._claim_fixture(Path(directory) / "other-owner.db")
            try:
                self._approval_action(approvals, context, "OPEN", "open")
                self._approval_action(approvals, context, "APPROVE", "approve")
                self._insert_invalid_event(ledger, context["approval_id"], wrong_owner=True)
                with self.assertRaises(SurplusError) as conflict:
                    self._assessment(ledger, policies, active)
                self.assertEqual(conflict.exception.code, "APPROVAL_INTEGRITY_CONFLICT")
            finally:
                ledger.close()

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
            self.assertEqual(result["calculation_status"], "INSUFFICIENT_DATA")
            self.assertIsNone(result["estimated_investible_surplus_base_units_str"])
            self.assertEqual(result["accounting_reserved_base_units_str"], "200")
            self.assertTrue(result["deductions"][0]["already_reflected_in_treasury"])
            self.assertFalse(result["deductions"][0]["applied_to_surplus"])
            self.assertIsNone(result["verified_investible_surplus_base_units_str"])
            ledger.close()


if __name__ == "__main__":
    unittest.main()
