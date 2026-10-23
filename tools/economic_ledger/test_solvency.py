"""Deterministic CON-25 tests; verifier fixtures do not represent live Solana evidence."""
import hashlib
import tempfile
import time
import unittest
from pathlib import Path

from tools.economic_ledger.ledger import EconomicLedger, IsolatedTestAttestationVerifier, IsolatedTestReconcilerVerifier
from tools.economic_ledger.models import LedgerValidationError
from tools.economic_ledger.solvency import assess_agent, record_coverage, save_assessment, assessment_history

AGENT = "DcusvnYAdFFKzNDVzUkUvmgZ9fDhzszeRR5Fj8F5dMbB"
AGENT2 = "FPbX4tQ2t9KSUDPix3NxBVEp2dD5LWoikhBVYYafU9H7"
OWNER = "8rPDpYsLZxNBm8Q8GKSKki8Ag6dodkasedhUT9x3Ec1D"
MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
EURC = "HzwqbKZw8HxMN6bF2yFZNrht3c2iXXzpKcFu7uBEDKtr"
PROGRAM = "CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy"
GENESIS = "HP9XKTusRPGC78EFDpR9xdEq6simL2vqyDdrMvn6Vacg"
NETWORK = "solana:localnet"
HASH = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
NOW = 2_000_000_000
START = NOW - 30 * 86400


class SolvencyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.ledger = EconomicLedger(Path(self.temp.name) / "ledger.db",
                                     reconciliation_verifier=IsolatedTestReconcilerVerifier(),
                                     attestation_verifier=IsolatedTestAttestationVerifier())

    def tearDown(self):
        self.ledger.close()
        self.temp.cleanup()

    def income(self, amount, *, agent=AGENT, mint=MINT, when=NOW - 100, key=None, genesis=GENESIS):
        key = key or f"income-{agent}-{mint}-{amount}-{when}-{genesis}"
        m = self.ledger.record_movement(idempotency_key=key, agent_id="11" * 32,
            agent_account=agent, owner_pubkey=OWNER, network=NETWORK, genesis_hash=genesis,
            program_id=PROGRAM, token_mint=mint, amount_base_units=amount, nature="INCOME",
            status="PROVISIONAL", tx_signature=f"sig-{hashlib.sha256(key.encode()).hexdigest()}", observed_at=when)
        return m

    def reconcile(self, movement):
        return self.ledger.reconcile_movement(movement.movement_id, evidence_hash=HASH,
            authorized_by="conatus:protocol:reconciler:v1", slot=1000, tx_signature=movement.tx_signature)

    def cost(self, amount, *, agent=AGENT, mint=MINT, when=NOW - 90, nature="REALIZED",
             status="RECONCILED", key=None, category="ENERGY_FUEL", genesis=GENESIS):
        key = key or f"cost-{agent}-{mint}-{amount}-{when}-{nature}-{status}"
        verified = status == "RECONCILED"
        return self.ledger.record_cost(idempotency_key=key, agent_id="11" * 32,
            agent_account=agent, owner_pubkey=OWNER, category=category, cost_nature=nature,
            economic_period="2033-05", amount_base_units=amount, network=NETWORK,
            genesis_hash=genesis, program_id=PROGRAM, token_mint=mint, incurred_at=when,
            status=status, provenance_source="EXTERNAL_VERIFIED" if verified else "MANUAL_ENTRY",
            attestation_id=f"attest-{key}" if verified else None, evidence_hash=HASH if verified else None,
            metadata={"authorized_by": "conatus:trusted:oracle:v1"} if verified else {})

    def coverage(self, side, *, mint=MINT, agent=AGENT, genesis=GENESIS):
        return record_coverage(self.ledger, agent_account=agent, network=NETWORK,
            genesis_hash=genesis, program_id=PROGRAM, token_mint=mint,
            side=side, window_start=START, window_end=NOW, evidence_hash=HASH,
            verifier_id="test:coverage", verifier=lambda **_: True, verified_at=NOW)

    def assessment(self, **kwargs):
        return assess_agent(self.ledger, AGENT, network=NETWORK, genesis_hash=GENESIS,
                            program_id=PROGRAM, token_mint=MINT, now=NOW, **kwargs)[0]

    def test_ratios_margin_surplus_and_classification(self):
        self.reconcile(self.income(100))
        self.cost(50)
        self.coverage("REVENUE")
        self.coverage("OPEX")
        a = self.assessment()
        self.assertEqual((a["calculation_status"], a["conatus_ratio"], a["operating_margin"], a["sustainability_class"]),
                         ("VALID", "2.00000000", "0.50000000", "THRIVING"))
        self.assertEqual(a["operating_surplus_base_units_str"], "50")
        self.assertEqual(a["available_liquidity_base_units_str"], "50")
        self.assertEqual(a["runway_days"], "30.00000000")
        self.assertEqual(len(a["evidence_references"]), 4)
        self.assertEqual(self.assessment()["assessment_id"], a["assessment_id"])

    def test_below_one_and_large_exact_amounts(self):
        self.reconcile(self.income(18_000_000_000_000_000_000))
        self.cost(12_000_000_000_000_000_000)
        self.coverage("REVENUE")
        self.coverage("OPEX")
        self.assertEqual(self.assessment()["conatus_ratio"], "1.50000000")
        self.cost(1_000_000_000_000_000_000, key="extra")
        self.assertEqual(self.assessment()["conatus_ratio"], "1.38461538")

    def test_equal_and_below_one(self):
        self.reconcile(self.income(100))
        self.cost(100)
        self.coverage("REVENUE")
        self.coverage("OPEX")
        self.assertEqual((self.assessment()["conatus_ratio"], self.assessment()["sustainability_class"]),
                         ("1.00000000", "STABLE"))
        self.cost(100, key="second-cost")
        self.assertEqual((self.assessment()["conatus_ratio"], self.assessment()["sustainability_class"]),
                         ("0.50000000", "AT_RISK"))

    def test_stale_evidence_and_custom_window(self):
        old = NOW - 9 * 86400
        self.reconcile(self.income(100, when=old))
        self.cost(50, when=old)
        for side in ("REVENUE", "OPEX"):
            record_coverage(self.ledger, agent_account=AGENT, network=NETWORK,
                genesis_hash=GENESIS, program_id=PROGRAM, token_mint=MINT, side=side,
                window_start=START, window_end=NOW, evidence_hash=HASH, verifier_id="test:old",
                verifier=lambda **_: True, verified_at=old)
        self.assertEqual(self.assessment()["calculation_status"], "STALE_DATA")
        custom = self.assessment(from_ts=NOW - 10 * 86400, to_ts=NOW)
        self.assertEqual(custom["calculation_status"], "INSUFFICIENT_DATA")
        self.assertEqual(custom["verified_revenue_base_units_str"], "100")

    def test_zero_requires_coverage(self):
        self.reconcile(self.income(100))
        self.assertEqual(self.assessment()["calculation_status"], "INSUFFICIENT_DATA")
        self.coverage("REVENUE")
        self.coverage("OPEX")
        self.assertEqual(self.assessment()["calculation_status"], "UNDEFINED_RATIO")
        self.assertIsNone(self.assessment()["conatus_ratio"])

    def test_both_zero_and_zero_revenue(self):
        self.coverage("REVENUE")
        self.coverage("OPEX")
        self.assertEqual(self.assessment()["calculation_status"], "UNDEFINED_RATIO")
        # Funding before the window supplies cash without becoming 30-day revenue.
        self.reconcile(self.income(200, when=START - 1, key="opening-funds"))
        self.cost(100)
        a = self.assessment()
        self.assertEqual((a["calculation_status"], a["conatus_ratio"], a["sustainability_class"]),
                         ("VALID", "0.00000000", "AT_RISK"))

    def test_provisional_simulated_reversed_and_boundary(self):
        self.income(100)
        self.cost(50, status="PROVISIONAL")
        self.assertEqual(self.assessment()["calculation_status"], "INSUFFICIENT_DATA")
        old = self.income(10, when=START - 1, key="before")
        self.reconcile(old)
        self.assertEqual(self.assessment()["verified_revenue_base_units_str"], "0")
        boundary = self.income(20, when=START, key="boundary")
        self.reconcile(boundary)
        self.assertEqual(self.assessment()["verified_revenue_base_units_str"], "20")
        self.ledger.revert_movement(boundary.movement_id, reason="test reversal", authorized_by=OWNER)
        self.assertEqual(self.assessment()["verified_revenue_base_units_str"], "0")

    def test_reserves_capex_accrual_and_cash_are_separate(self):
        self.reconcile(self.income(1000))
        self.cost(100)
        self.coverage("REVENUE")
        self.coverage("OPEX")
        self.cost(80, nature="ACCRUED_LIABILITY")
        self.ledger.create_or_allocate_reserve(idempotency_key="reserve-one", agent_id="11" * 32,
            agent_account=AGENT, owner_pubkey=OWNER, reserve_type="CONTINGENCY",
            network=NETWORK, genesis_hash=GENESIS, program_id=PROGRAM, token_mint=MINT,
            amount_base_units=200)
        self.ledger.record_capital_investment(idempotency_key="capex-one", agent_id="11" * 32,
            agent_account=AGENT, owner_pubkey=OWNER, network=NETWORK, genesis_hash=GENESIS,
            program_id=PROGRAM, token_mint=MINT, amount_base_units=100)
        a = self.assessment()
        self.assertEqual(a["verified_opex_base_units_str"], "100")
        self.assertEqual(a["total_reserved_base_units_str"], "200")
        self.assertEqual(a["accrued_liabilities_base_units_str"], "80")
        self.assertEqual(a["available_liquidity_base_units_str"], "600")
        self.assertEqual(a["eligible_liquid_capital_base_units_str"], "520")

    def test_context_segregation_and_snapshots(self):
        self.reconcile(self.income(100))
        self.cost(50)
        self.coverage("REVENUE")
        self.coverage("OPEX")
        a = self.assessment()
        save_assessment(self.ledger, a)
        save_assessment(self.ledger, a)
        self.assertEqual(assessment_history(self.ledger, AGENT)[0], a)
        self.reconcile(self.income(200, mint=EURC))
        self.cost(50, mint=EURC)
        self.coverage("REVENUE", mint=EURC)
        self.coverage("OPEX", mint=EURC)
        separate = assess_agent(self.ledger, AGENT, now=NOW)
        self.assertEqual(len(separate), 2)
        mixed = assess_agent(self.ledger, AGENT, now=NOW, consolidated=True)
        self.assertEqual(mixed[0]["calculation_status"], "MIXED_ASSET_CONTEXT")
        self.assertIsNone(mixed[0]["conatus_ratio"])
        self.assertEqual(self.assessment()["conatus_ratio"], "2.00000000")

    def test_coverage_verifier_fail_closed(self):
        with self.assertRaises(LedgerValidationError):
            record_coverage(self.ledger, agent_account=AGENT, network=NETWORK,
                genesis_hash=GENESIS, program_id=PROGRAM, token_mint=MINT, side="OPEX",
                window_start=START, window_end=NOW, evidence_hash=HASH, verifier_id="bad",
                verifier=lambda **_: False)


if __name__ == "__main__":
    unittest.main()
