"""Deterministic CON-25 tests; verifier fixtures do not represent live Solana evidence."""
import hashlib
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import sys
ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR / "tools" / "discovery") not in sys.path:
    sys.path.insert(0, str(ROOT_DIR / "tools" / "discovery"))

import agent_discovery as discovery

from tools.economic_ledger.ledger import (
    EconomicLedger,
    IsolatedTestAttestationVerifier,
    IsolatedTestCoverageVerifier,
    IsolatedTestReconcilerVerifier,
    ProductionAttestationVerifier,
    ProductionCoverageVerifier,
    ProductionReconciliationVerifier,
    canonical_coverage_message,
    sign_coverage_attestation,
    verify_ed25519_signature,
)
from tools.economic_ledger.models import EvidenceLineage, LedgerValidationError
from tools.economic_ledger.solvency import (
    assess_agent,
    assessment_history,
    calculate_side_data_digest,
    record_coverage,
    save_assessment,
)

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
        self.coverage_verifier = IsolatedTestCoverageVerifier()
        self.ledger = EconomicLedger(
            Path(self.temp.name) / "ledger.db",
            reconciliation_verifier=IsolatedTestReconcilerVerifier(),
            attestation_verifier=IsolatedTestAttestationVerifier(),
            coverage_verifier=self.coverage_verifier,
        )

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

    def coverage(self, side, *, mint=MINT, agent=AGENT, genesis=GENESIS, key=None, evidence_hash=None, verified_at=NOW):
        ev_hash = evidence_hash or (f"{HASH}-{key}" if key else HASH)
        return record_coverage(self.ledger, agent_account=agent, network=NETWORK,
            genesis_hash=genesis, program_id=PROGRAM, token_mint=mint,
            side=side, window_start=START, window_end=NOW, evidence_hash=ev_hash,
            verifier_id="test:coverage", verifier=self.coverage_verifier, verified_at=verified_at)

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
        # Incomplete coverage following new unverified expense fails closed
        self.assertEqual(self.assessment()["calculation_status"], "INSUFFICIENT_DATA")
        self.coverage("OPEX", key="extra-cov")
        self.assertEqual(self.assessment()["conatus_ratio"], "1.38461538")

    def test_equal_and_below_one(self):
        self.reconcile(self.income(100))
        self.cost(100)
        self.coverage("REVENUE")
        self.coverage("OPEX")
        self.assertEqual((self.assessment()["conatus_ratio"], self.assessment()["sustainability_class"]),
                         ("1.00000000", "STABLE"))
        self.cost(100, key="second-cost")
        # Uncovered expense causes digest mismatch until new coverage is attested
        self.assertEqual(self.assessment()["calculation_status"], "INSUFFICIENT_DATA")
        self.coverage("OPEX", key="second-cov")
        self.assertEqual((self.assessment()["conatus_ratio"], self.assessment()["sustainability_class"]),
                         ("0.50000000", "AT_RISK"))

    def test_stale_evidence_and_custom_window(self):
        old = NOW - 9 * 86400
        self.reconcile(self.income(100, when=old))
        self.cost(50, when=old)
        for side in ("REVENUE", "OPEX"):
            record_coverage(self.ledger, agent_account=AGENT, network=NETWORK,
                genesis_hash=GENESIS, program_id=PROGRAM, token_mint=MINT, side=side,
                window_start=START, window_end=NOW, evidence_hash=HASH, verifier_id="test:coverage",
                verifier=self.coverage_verifier, verified_at=old)
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
        self.coverage("OPEX", key="after-opening")
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
        self.cost(80, nature="ACCRUED_LIABILITY")
        self.coverage("REVENUE")
        self.coverage("OPEX")
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

    def test_reversed_cost_is_excluded_and_other_agent_isolated(self):
        self.reconcile(self.income(200))
        first = self.cost(50)
        self.cost(50, key="remaining")
        self.coverage("REVENUE")
        self.coverage("OPEX")
        self.assertEqual(self.assessment()["verified_opex_base_units_str"], "100")
        self.ledger.revert_cost(first.cost_id, reason="incorrect invoice")
        # Reversal modifies records and invalidates digest
        self.assertEqual(self.assessment()["calculation_status"], "INSUFFICIENT_DATA")
        self.coverage("OPEX", key="post-revert")
        self.assertEqual(self.assessment()["verified_opex_base_units_str"], "50")
        self.reconcile(self.income(100, agent=AGENT2))
        self.cost(20, agent=AGENT2)
        self.coverage("REVENUE", agent=AGENT2)
        self.coverage("OPEX", agent=AGENT2)
        other = assess_agent(self.ledger, AGENT2, now=NOW)[0]
        self.assertEqual(other["conatus_ratio"], "5.00000000")
        self.assertEqual(self.assessment()["conatus_ratio"], "4.00000000")

    def test_coverage_verifier_fail_closed(self):
        # Arbitrary callable is rejected
        with self.assertRaises(LedgerValidationError) as ctx:
            record_coverage(self.ledger, agent_account=AGENT, network=NETWORK,
                genesis_hash=GENESIS, program_id=PROGRAM, token_mint=MINT, side="OPEX",
                window_start=START, window_end=NOW, evidence_hash=HASH, verifier_id="test:coverage",
                verifier=lambda **_: True)
        self.assertIn("Coverage verifier must implement CoverageVerifier protocol", str(ctx.exception))

        # Rejected authority or signature in CoverageVerifier fails closed
        with self.assertRaises(LedgerValidationError):
            record_coverage(self.ledger, agent_account=AGENT, network=NETWORK,
                genesis_hash=GENESIS, program_id=PROGRAM, token_mint=MINT, side="OPEX",
                window_start=START, window_end=NOW, evidence_hash=HASH, verifier_id="bad:authority",
                verifier=self.coverage_verifier)

    def test_integrity_failure_has_error_state_without_ratio(self):
        self.reconcile(self.income(100))
        self.cost(50)
        self.coverage("REVENUE")
        self.coverage("OPEX")
        with patch.object(self.ledger, "get_economic_summary", side_effect=ValueError("bad ledger")):
            result = self.assessment()
        self.assertEqual(result["calculation_status"], "ERROR")
        self.assertIsNone(result["conatus_ratio"])
        self.assertIsNone(result["verified_revenue_base_units_str"])
        self.assertEqual(result["sustainability_class"], "UNDETERMINED")


class SolvencyCoverageHardeningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.coverage_verifier = IsolatedTestCoverageVerifier()
        self.ledger = EconomicLedger(
            Path(self.temp.name) / "ledger.db",
            reconciliation_verifier=IsolatedTestReconcilerVerifier(),
            attestation_verifier=IsolatedTestAttestationVerifier(),
            coverage_verifier=self.coverage_verifier,
        )

    def tearDown(self):
        self.ledger.close()
        self.temp.cleanup()

    def income(self, amount, *, when=NOW - 100, key=None, status="PROVISIONAL", ev_hash=HASH):
        key = key or f"inc-{amount}-{when}"
        return self.ledger.record_movement(
            idempotency_key=key, agent_id="11" * 32, agent_account=AGENT, owner_pubkey=OWNER,
            network=NETWORK, genesis_hash=GENESIS, program_id=PROGRAM, token_mint=MINT,
            amount_base_units=amount, nature="INCOME", status=status,
            tx_signature=f"sig-{hashlib.sha256(key.encode()).hexdigest()}",
            observed_at=when, evidence_hash=ev_hash if status == "RECONCILED" else None,
        )

    def reconcile(self, movement, ev_hash=HASH):
        return self.ledger.reconcile_movement(
            movement.movement_id, evidence_hash=ev_hash,
            authorized_by="conatus:protocol:reconciler:v1", slot=1000,
            tx_signature=movement.tx_signature,
        )

    def cost(self, amount, *, when=NOW - 90, nature="REALIZED", status="RECONCILED", key=None, ev_hash=HASH):
        key = key or f"cst-{amount}-{when}-{nature}-{status}"
        verified = status == "RECONCILED"
        return self.ledger.record_cost(
            idempotency_key=key, agent_id="11" * 32, agent_account=AGENT, owner_pubkey=OWNER,
            category="ENERGY_FUEL", cost_nature=nature, economic_period="2033-05",
            amount_base_units=amount, network=NETWORK, genesis_hash=GENESIS,
            program_id=PROGRAM, token_mint=MINT, incurred_at=when, status=status,
            provenance_source="EXTERNAL_VERIFIED" if verified else "MANUAL_ENTRY",
            attestation_id=f"attest-{key}" if verified else None,
            evidence_hash=ev_hash if verified else None,
            metadata={"authorized_by": "conatus:trusted:oracle:v1"} if verified else {},
        )

    def coverage(self, side, *, key=None, ev_hash=None, prov="SYNTHETIC_TEST"):
        eh = ev_hash or (f"{HASH}-{key}" if key else HASH)
        return record_coverage(
            self.ledger, agent_account=AGENT, network=NETWORK, genesis_hash=GENESIS,
            program_id=PROGRAM, token_mint=MINT, side=side, window_start=START, window_end=NOW,
            evidence_hash=eh, verifier_id="test:coverage", verifier=self.coverage_verifier,
            provenance_type=prov, verified_at=NOW,
        )

    def assessment(self):
        return assess_agent(
            self.ledger, AGENT, network=NETWORK, genesis_hash=GENESIS,
            program_id=PROGRAM, token_mint=MINT, now=NOW,
        )[0]

    def test_negative_1_new_expense_after_coverage(self):
        self.reconcile(self.income(100))
        self.cost(50)
        self.coverage("REVENUE")
        self.coverage("OPEX")
        a1 = self.assessment()
        self.assertEqual(a1["calculation_status"], "VALID")
        self.assertEqual(a1["conatus_ratio"], "2.00000000")

        # Ingest new expense into the covered window
        self.cost(25, key="new-expense-late")
        a2 = self.assessment()
        self.assertEqual(a2["calculation_status"], "INSUFFICIENT_DATA")
        self.assertIsNone(a2["conatus_ratio"])
        self.assertIn("opex_coverage_digest_mismatch", a2["exclusion_reasons"])

    def test_negative_2_late_reconciled_income(self):
        m = self.income(100, status="PROVISIONAL")
        self.cost(50)
        self.coverage("REVENUE")
        self.coverage("OPEX")
        self.assertEqual(self.assessment()["calculation_status"], "INSUFFICIENT_DATA")

        # Now late reconciliation alters the status in economic_movements
        self.reconcile(m)
        a2 = self.assessment()
        self.assertEqual(a2["calculation_status"], "INSUFFICIENT_DATA")
        self.assertIsNone(a2["conatus_ratio"])
        self.assertIn("revenue_coverage_digest_mismatch", a2["exclusion_reasons"])

    def test_negative_3_later_reversal(self):
        self.reconcile(self.income(100))
        c = self.cost(50)
        self.coverage("REVENUE")
        self.coverage("OPEX")
        self.assertEqual(self.assessment()["calculation_status"], "VALID")

        # Later reversal of the cost alters status and reversal fields
        self.ledger.revert_cost(c.cost_id, reason="audit dispute")
        a2 = self.assessment()
        self.assertEqual(a2["calculation_status"], "INSUFFICIENT_DATA")
        self.assertIsNone(a2["conatus_ratio"])
        self.assertIn("opex_coverage_digest_mismatch", a2["exclusion_reasons"])

    def test_negative_4_new_provisional_expense_or_estimate(self):
        self.reconcile(self.income(100))
        self.cost(50)
        self.coverage("REVENUE")
        self.coverage("OPEX")
        self.assertEqual(self.assessment()["calculation_status"], "VALID")

        # Incur new estimated cost
        self.cost(30, nature="ESTIMATED", status="PROVISIONAL", key="estimate-1")
        a2 = self.assessment()
        self.assertEqual(a2["calculation_status"], "INSUFFICIENT_DATA")
        self.assertIsNone(a2["conatus_ratio"])
        self.assertIn("opex_coverage_digest_mismatch", a2["exclusion_reasons"])

    def test_negative_5_record_corrected_with_other_evidence(self):
        m = self.income(100)
        self.reconcile(m, ev_hash=HASH)
        self.cost(50)
        self.coverage("REVENUE")
        self.coverage("OPEX")
        self.assertEqual(self.assessment()["calculation_status"], "VALID")

        # Direct tamper/correction of evidence hash in database
        self.ledger._conn.execute(
            "UPDATE economic_movements SET evidence_hash = ? WHERE movement_id = ?",
            ("tampered_or_updated_evidence_hash_1234567890", m.movement_id),
        )
        a2 = self.assessment()
        self.assertEqual(a2["calculation_status"], "INSUFFICIENT_DATA")
        self.assertIsNone(a2["conatus_ratio"])
        self.assertIn("revenue_coverage_digest_mismatch", a2["exclusion_reasons"])

    def test_negative_6_zero_event_coverage_receives_movements_later(self):
        # Attest zero coverage for both sides
        self.coverage("REVENUE")
        self.coverage("OPEX")
        self.assertEqual(self.assessment()["calculation_status"], "UNDEFINED_RATIO")

        # Ingest a movement into the supposedly zero window
        self.reconcile(self.income(100, key="late-arriving-movement"))
        a2 = self.assessment()
        self.assertEqual(a2["calculation_status"], "INSUFFICIENT_DATA")
        self.assertIsNone(a2["conatus_ratio"])
        self.assertIn("revenue_coverage_digest_mismatch", a2["exclusion_reasons"])

    def test_provenance_persists_across_sqlite_restart_without_promotion(self):
        db_path = Path(self.temp.name) / "restart_test.db"
        with EconomicLedger(
            db_path,
            reconciliation_verifier=IsolatedTestReconcilerVerifier(),
            attestation_verifier=IsolatedTestAttestationVerifier(),
            coverage_verifier=self.coverage_verifier,
        ) as led:
            m = led.record_movement(
                idempotency_key="prov-inc-1", agent_id="11" * 32, agent_account=AGENT,
                owner_pubkey=OWNER, network=NETWORK, genesis_hash=GENESIS,
                program_id=PROGRAM, token_mint=MINT, amount_base_units=100, nature="INCOME",
                status="PROVISIONAL", tx_signature="sig-prov-1", observed_at=NOW - 100,
            )
            led.reconcile_movement(m.movement_id, evidence_hash=HASH,
                authorized_by="conatus:protocol:reconciler:v1", slot=1000, tx_signature="sig-prov-1")
            led.record_cost(
                idempotency_key="prov-cst-1", agent_id="11" * 32, agent_account=AGENT,
                owner_pubkey=OWNER, category="ENERGY_FUEL", cost_nature="REALIZED",
                economic_period="2033-05", amount_base_units=50, network=NETWORK,
                genesis_hash=GENESIS, program_id=PROGRAM, token_mint=MINT, incurred_at=NOW - 90,
                status="RECONCILED", provenance_source="EXTERNAL_VERIFIED",
                attestation_id="attest-prov-1", evidence_hash=HASH,
                metadata={"authorized_by": "conatus:trusted:oracle:v1"},
            )
            record_coverage(
                led, agent_account=AGENT, network=NETWORK, genesis_hash=GENESIS,
                program_id=PROGRAM, token_mint=MINT, side="REVENUE", window_start=START,
                window_end=NOW, evidence_hash=HASH, verifier_id="test:coverage",
                verifier=self.coverage_verifier, provenance_type="SYNTHETIC_TEST",
            )
            record_coverage(
                led, agent_account=AGENT, network=NETWORK, genesis_hash=GENESIS,
                program_id=PROGRAM, token_mint=MINT, side="OPEX", window_start=START,
                window_end=NOW, evidence_hash=HASH, verifier_id="test:coverage",
                verifier=self.coverage_verifier, provenance_type="SYNTHETIC_TEST",
            )
            a = assess_agent(led, AGENT, network=NETWORK, genesis_hash=GENESIS,
                             program_id=PROGRAM, token_mint=MINT, now=NOW)[0]
            self.assertEqual(a["provenance"], "SYNTHETIC_TEST")
            save_assessment(led, a)

        # Reopen SQLite database cleanly in production mode (no test verifiers in memory)
        with EconomicLedger(db_path) as fresh_ledger:
            # 1. Historical snapshot retained persistent provenance
            hist = assessment_history(fresh_ledger, AGENT)
            self.assertEqual(len(hist), 1)
            self.assertEqual(hist[0]["provenance"], "SYNTHETIC_TEST")

            # 2. When evaluated without a coverage verifier or with default unconfigured authorities:
            reassessed = assess_agent(fresh_ledger, AGENT, network=NETWORK,
                                      genesis_hash=GENESIS, program_id=PROGRAM, token_mint=MINT, now=NOW)[0]
            self.assertEqual(reassessed["calculation_status"], "INSUFFICIENT_DATA")

            # 3. When evaluated with ProductionCoverageVerifier, synthetic test coverage is rejected from promotion
            prod_verifier = ProductionCoverageVerifier()
            fresh_ledger._coverage_verifier = prod_verifier
            fresh_ledger._trusted_coverage_authorities = set(prod_verifier.trusted_authorities)
            prod_reassessed = assess_agent(fresh_ledger, AGENT, network=NETWORK,
                                           genesis_hash=GENESIS, program_id=PROGRAM, token_mint=MINT, now=NOW)[0]
            # Synthetic coverage is NEVER promoted to LIVE_RPC or EXTERNAL_ATTESTED
            self.assertNotEqual(prod_reassessed["provenance"], "LIVE_RPC")
            self.assertNotEqual(prod_reassessed["provenance"], "EXTERNAL_ATTESTED")
            self.assertEqual(prod_reassessed["calculation_status"], "INSUFFICIENT_DATA")

    def test_migration_007_legacy_coverage_missing_digest_invalidated(self):
        legacy_dir = tempfile.TemporaryDirectory()
        legacy_db = Path(legacy_dir.name) / "legacy_006.db"
        conn = sqlite3.connect(str(legacy_db), isolation_level=None)
        conn.row_factory = sqlite3.Row

        # Apply migrations 001..006 manually
        from tools.economic_ledger.schema import split_sql_statements, MIGRATIONS_DIR
        for v in range(1, 7):
            mfile = next(MIGRATIONS_DIR.glob(f"{v:03d}_*.sql"))
            stmts = split_sql_statements(mfile.read_text(encoding="utf-8"))
            conn.execute("BEGIN IMMEDIATE;")
            for stmt in stmts:
                conn.execute(stmt)
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at INTEGER NOT NULL);"
            )
            conn.execute("INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?);",
                         (v, mfile.stem, int(time.time())))
            conn.execute("COMMIT;")

        # Insert a pre-migration-007 coverage row lacking data_digest and provenance_type
        cov_id = "legacy_cov_123"
        conn.execute(
            """INSERT INTO solvency_coverage (
                coverage_id, agent_account, network, genesis_hash, program_id,
                token_mint, side, window_start, window_end, evidence_hash,
                verifier_id, verified_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (cov_id, AGENT, NETWORK, GENESIS, PROGRAM, MINT, "REVENUE", START, NOW, HASH, "legacy_verifier", NOW)
        )
        conn.close()

        # Open with EconomicLedger, applying migration 007
        with EconomicLedger(legacy_db, coverage_verifier=self.coverage_verifier) as led:
            cur = led._conn.execute("SELECT data_digest, provenance_type FROM solvency_coverage WHERE coverage_id = ?", (cov_id,))
            row = cur.fetchone()
            self.assertEqual(row["data_digest"], "")
            self.assertEqual(row["provenance_type"], "HISTORICAL_UNVERIFIED")

            # Assessing agent with this legacy coverage fails closed with INSUFFICIENT_DATA
            res = assess_agent(led, AGENT, network=NETWORK, genesis_hash=GENESIS,
                               program_id=PROGRAM, token_mint=MINT, now=NOW)[0]
            self.assertEqual(res["calculation_status"], "INSUFFICIENT_DATA")
            self.assertIn("revenue_coverage_missing_verifiable_digest", res["exclusion_reasons"])

        legacy_dir.cleanup()



class SolvencyCryptographicCoverageAuthenticityTests(unittest.TestCase):
    """Gates 1 & 2: Cryptographic Ed25519 verification, canonical message binding, revocation, and candidate selection."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.seed_1 = b"sec-key-cov-auth-1-seed-32bytes!"
        self.seed_2 = b"sec-key-cov-auth-2-seed-32bytes!"
        from cryptography.hazmat.primitives.asymmetric import ed25519 as crypto_ed25519
        self.pk_1_bytes = crypto_ed25519.Ed25519PrivateKey.from_private_bytes(self.seed_1[:32]).public_key().public_bytes_raw()
        self.pk_2_bytes = crypto_ed25519.Ed25519PrivateKey.from_private_bytes(self.seed_2[:32]).public_key().public_bytes_raw()
        self.pub_1_b58 = discovery.b58encode(self.pk_1_bytes)
        self.pub_2_b58 = discovery.b58encode(self.pk_2_bytes)
        self.auth_1 = "conatus:coverage:authority:v1"
        self.auth_2 = "conatus:protocol:solvency-verifier:v1"

    def tearDown(self):
        self.temp.cleanup()

    def _sign(self, seed: bytes, *, side: str, digest: str, expires_at: int | None = None, auth: str | None = None, prov: str = "EXTERNAL_ATTESTED", evidence_hash: str = HASH):
        auth_id = auth or self.auth_1
        msg = canonical_coverage_message(
            agent_account=AGENT,
            network=NETWORK,
            genesis_hash=GENESIS,
            program_id=PROGRAM,
            token_mint=MINT,
            side=side,
            window_start=START,
            window_end=NOW,
            data_digest=digest,
            evidence_hash=evidence_hash,
            verifier_id=auth_id,
            provenance_type=prov,
            expires_at=expires_at,
        )
        sig_b58, pub_b58 = sign_coverage_attestation(seed, msg)
        return sig_b58, pub_b58, msg

    def test_gate1_valid_ed25519_signature_verifies(self):
        verifier = ProductionCoverageVerifier(
            trusted_authorities={self.auth_1},
            trusted_public_keys={self.auth_1: self.pub_1_b58},
        )
        sig_b58, pub_b58, _ = self._sign(self.seed_1, side="REVENUE", digest="d1234567890abcdef")
        ok = verifier.verify_coverage(
            agent_account=AGENT, network=NETWORK, genesis_hash=GENESIS, program_id=PROGRAM,
            token_mint=MINT, side="REVENUE", window_start=START, window_end=NOW,
            data_digest="d1234567890abcdef", evidence_hash=HASH, verifier_id=self.auth_1,
            provenance_type="EXTERNAL_ATTESTED", signature=sig_b58, authority_pubkey=pub_b58,
        )
        self.assertTrue(ok)

    def test_gate1_forged_signature_of_length_64_fails(self):
        verifier = ProductionCoverageVerifier(
            trusted_authorities={self.auth_1},
            trusted_public_keys={self.auth_1: self.pub_1_b58},
        )
        forged_sig = discovery.b58encode(b"\xfe" * 64)
        ok = verifier.verify_coverage(
            agent_account=AGENT, network=NETWORK, genesis_hash=GENESIS, program_id=PROGRAM,
            token_mint=MINT, side="REVENUE", window_start=START, window_end=NOW,
            data_digest="d1234567890abcdef", evidence_hash=HASH, verifier_id=self.auth_1,
            provenance_type="EXTERNAL_ATTESTED", signature=forged_sig, authority_pubkey=self.pub_1_b58,
        )
        self.assertFalse(ok)

    def test_gate1_tampered_canonical_message_fails(self):
        verifier = ProductionCoverageVerifier(
            trusted_authorities={self.auth_1},
            trusted_public_keys={self.auth_1: self.pub_1_b58},
        )
        sig_b58, pub_b58, _ = self._sign(self.seed_1, side="REVENUE", digest="original_digest_val")
        # Attempt to verify with modified data_digest
        ok = verifier.verify_coverage(
            agent_account=AGENT, network=NETWORK, genesis_hash=GENESIS, program_id=PROGRAM,
            token_mint=MINT, side="REVENUE", window_start=START, window_end=NOW,
            data_digest="tampered_digest_val", evidence_hash=HASH, verifier_id=self.auth_1,
            provenance_type="EXTERNAL_ATTESTED", signature=sig_b58, authority_pubkey=pub_b58,
        )
        self.assertFalse(ok)

    def test_gate1_wrong_public_key_fails(self):
        verifier = ProductionCoverageVerifier(
            trusted_authorities={self.auth_1},
            trusted_public_keys={self.auth_1: self.pub_2_b58},  # key 2 registered
        )
        sig_b58, pub_b58, _ = self._sign(self.seed_1, side="REVENUE", digest="d123")  # signed with key 1
        ok = verifier.verify_coverage(
            agent_account=AGENT, network=NETWORK, genesis_hash=GENESIS, program_id=PROGRAM,
            token_mint=MINT, side="REVENUE", window_start=START, window_end=NOW,
            data_digest="d123", evidence_hash=HASH, verifier_id=self.auth_1,
            provenance_type="EXTERNAL_ATTESTED", signature=sig_b58, authority_pubkey=pub_b58,
        )
        self.assertFalse(ok)

    def test_gate1_unregistered_authority_fails(self):
        verifier = ProductionCoverageVerifier(
            trusted_authorities={self.auth_1},
            trusted_public_keys={self.auth_1: self.pub_1_b58},
        )
        sig_b58, pub_b58, _ = self._sign(self.seed_1, side="REVENUE", digest="d123", auth="unregistered:auth")
        ok = verifier.verify_coverage(
            agent_account=AGENT, network=NETWORK, genesis_hash=GENESIS, program_id=PROGRAM,
            token_mint=MINT, side="REVENUE", window_start=START, window_end=NOW,
            data_digest="d123", evidence_hash=HASH, verifier_id="unregistered:auth",
            provenance_type="EXTERNAL_ATTESTED", signature=sig_b58, authority_pubkey=pub_b58,
        )
        self.assertFalse(ok)

    def test_gate1_revoked_authority_fails(self):
        verifier = ProductionCoverageVerifier(
            trusted_authorities={self.auth_1},
            trusted_public_keys={self.auth_1: self.pub_1_b58},
        )
        verifier.revoke_authority(self.auth_1)
        self.assertTrue(verifier.is_authority_revoked(self.auth_1))
        sig_b58, pub_b58, _ = self._sign(self.seed_1, side="REVENUE", digest="d123")
        ok = verifier.verify_coverage(
            agent_account=AGENT, network=NETWORK, genesis_hash=GENESIS, program_id=PROGRAM,
            token_mint=MINT, side="REVENUE", window_start=START, window_end=NOW,
            data_digest="d123", evidence_hash=HASH, verifier_id=self.auth_1,
            provenance_type="EXTERNAL_ATTESTED", signature=sig_b58, authority_pubkey=pub_b58,
        )
        self.assertFalse(ok)

    def test_gate1_expired_coverage_fails(self):
        verifier = ProductionCoverageVerifier(
            trusted_authorities={self.auth_1},
            trusted_public_keys={self.auth_1: self.pub_1_b58},
        )
        exp_time = NOW - 100
        sig_b58, pub_b58, _ = self._sign(self.seed_1, side="REVENUE", digest="d123", expires_at=exp_time)
        ok = verifier.verify_coverage(
            agent_account=AGENT, network=NETWORK, genesis_hash=GENESIS, program_id=PROGRAM,
            token_mint=MINT, side="REVENUE", window_start=START, window_end=NOW,
            data_digest="d123", evidence_hash=HASH, verifier_id=self.auth_1,
            provenance_type="EXTERNAL_ATTESTED", signature=sig_b58, authority_pubkey=pub_b58,
            expires_at=exp_time, now=NOW,
        )
        self.assertFalse(ok)

    def test_gate1_expired_by_ttl_fails(self):
        verifier = ProductionCoverageVerifier(
            trusted_authorities={self.auth_1},
            trusted_public_keys={self.auth_1: self.pub_1_b58},
            default_ttl_seconds=86400,
        )
        sig_b58, pub_b58, _ = self._sign(self.seed_1, side="REVENUE", digest="d123", expires_at=None)
        ok = verifier.verify_coverage(
            agent_account=AGENT, network=NETWORK, genesis_hash=GENESIS, program_id=PROGRAM,
            token_mint=MINT, side="REVENUE", window_start=START, window_end=NOW,
            data_digest="d123", evidence_hash=HASH, verifier_id=self.auth_1,
            provenance_type="EXTERNAL_ATTESTED", signature=sig_b58, authority_pubkey=pub_b58,
            verified_at=NOW - 90000, expires_at=None, now=NOW,
        )
        self.assertFalse(ok)

    def test_gate1_strictly_rejects_synthetic_or_fixture_in_production(self):
        verifier = ProductionCoverageVerifier(
            trusted_authorities={self.auth_1},
            trusted_public_keys={self.auth_1: self.pub_1_b58},
        )
        sig_b58, pub_b58, _ = self._sign(self.seed_1, side="REVENUE", digest="d123", prov="SYNTHETIC_TEST")
        ok = verifier.verify_coverage(
            agent_account=AGENT, network=NETWORK, genesis_hash=GENESIS, program_id=PROGRAM,
            token_mint=MINT, side="REVENUE", window_start=START, window_end=NOW,
            data_digest="d123", evidence_hash=HASH, verifier_id=self.auth_1,
            provenance_type="SYNTHETIC_TEST", signature=sig_b58, authority_pubkey=pub_b58,
        )
        self.assertFalse(ok)

    def test_gate2_sqlite_restart_with_authentic_ed25519_coverage(self):
        db_path = Path(self.temp.name) / "test_verifier_restart.db"
        prod_verifier = ProductionCoverageVerifier(
            trusted_authorities={self.auth_1},
            trusted_public_keys={self.auth_1: self.pub_1_b58},
        )
        with EconomicLedger(
            db_path,
            reconciliation_verifier=IsolatedTestReconcilerVerifier(),
            attestation_verifier=IsolatedTestAttestationVerifier(),
            coverage_verifier=prod_verifier,
        ) as led:
            m = led.record_movement(
                idempotency_key="inc-prod-1", agent_id="11" * 32, agent_account=AGENT,
                owner_pubkey=OWNER, network=NETWORK, genesis_hash=GENESIS,
                program_id=PROGRAM, token_mint=MINT, amount_base_units=400, nature="INCOME",
                status="PROVISIONAL", tx_signature="sig-prod-1", observed_at=NOW - 100,
            )
            led.reconcile_movement(m.movement_id, evidence_hash=HASH,
                authorized_by="conatus:protocol:reconciler:v1", slot=1000, tx_signature="sig-prod-1")
            led.record_cost(
                idempotency_key="cst-prod-1", agent_id="11" * 32, agent_account=AGENT,
                owner_pubkey=OWNER, category="CONNECTIVITY_COMPUTE", cost_nature="REALIZED",
                economic_period="2033-05", amount_base_units=100, network=NETWORK,
                genesis_hash=GENESIS, program_id=PROGRAM, token_mint=MINT, incurred_at=NOW - 90,
                status="RECONCILED", provenance_source="EXTERNAL_VERIFIED",
                attestation_id="attest-prod-1", evidence_hash=HASH,
                metadata={"authorized_by": "conatus:trusted:oracle:v1"},
            )

            # Compute digests
            rev_digest, _ = calculate_side_data_digest(led, AGENT, (NETWORK, GENESIS, PROGRAM, MINT), "REVENUE", START, NOW)
            opex_digest, _ = calculate_side_data_digest(led, AGENT, (NETWORK, GENESIS, PROGRAM, MINT), "OPEX", START, NOW)

            rev_sig, rev_pk, _ = self._sign(self.seed_1, side="REVENUE", digest=rev_digest, prov="EXTERNAL_ATTESTED")
            opex_sig, opex_pk, _ = self._sign(self.seed_1, side="OPEX", digest=opex_digest, prov="EXTERNAL_ATTESTED")

            record_coverage(
                led, agent_account=AGENT, network=NETWORK, genesis_hash=GENESIS,
                program_id=PROGRAM, token_mint=MINT, side="REVENUE", window_start=START,
                window_end=NOW, evidence_hash=HASH, verifier_id=self.auth_1,
                verifier=prod_verifier, provenance_type="EXTERNAL_ATTESTED",
                signature=rev_sig, authority_pubkey=rev_pk, verified_at=NOW,
            )
            record_coverage(
                led, agent_account=AGENT, network=NETWORK, genesis_hash=GENESIS,
                program_id=PROGRAM, token_mint=MINT, side="OPEX", window_start=START,
                window_end=NOW, evidence_hash=HASH, verifier_id=self.auth_1,
                verifier=prod_verifier, provenance_type="EXTERNAL_ATTESTED",
                signature=opex_sig, authority_pubkey=opex_pk, verified_at=NOW,
            )

        # 1. Reopen SQLite database in production: synthetic test movements/costs cannot be promoted
        # even with valid Ed25519 coverage signatures; fails closed to INSUFFICIENT_DATA
        reopened_verifier = ProductionCoverageVerifier(
            trusted_authorities={self.auth_1},
            trusted_public_keys={self.auth_1: self.pub_1_b58},
        )
        with EconomicLedger(db_path, coverage_verifier=reopened_verifier) as led_prod:
            res = assess_agent(led_prod, AGENT, network=NETWORK, genesis_hash=GENESIS,
                               program_id=PROGRAM, token_mint=MINT, now=NOW)[0]
            self.assertEqual(res["calculation_status"], "INSUFFICIENT_DATA")
            self.assertEqual(res["provenance"], "SYNTHETIC_TEST")
            self.assertIn("synthetic_or_unverified_revenue_lineage", res["exclusion_reasons"])
            self.assertIn("synthetic_or_unverified_cost_lineage", res["exclusion_reasons"])

        # 2. Reopen in explicit test mode: valid assessment allowed but strictly preserves provenance=SYNTHETIC_TEST
        test_cov_verifier = IsolatedTestCoverageVerifier(
            trusted_authorities={self.auth_1},
            trusted_public_keys={self.auth_1: self.pub_1_b58},
        )
        with EconomicLedger(db_path, coverage_verifier=test_cov_verifier) as led_test:
            res_test = assess_agent(led_test, AGENT, network=NETWORK, genesis_hash=GENESIS,
                                    program_id=PROGRAM, token_mint=MINT, now=NOW)[0]
            self.assertEqual(res_test["calculation_status"], "VALID")
            self.assertEqual(res_test["provenance"], "SYNTHETIC_TEST")
            self.assertEqual(res_test["conatus_ratio"], "4.00000000")

        # 3. Authentic production verification reaches full LIVE_RPC_AND_EXTERNAL_ATTESTED
        prod_db_path = Path(self.temp.name) / "authentic_prod_restart.db"
        with EconomicLedger(
            prod_db_path,
            reconciliation_verifier=ProductionReconciliationVerifier(),
            attestation_verifier=ProductionAttestationVerifier(),
            coverage_verifier=prod_verifier,
        ) as led_p:
            m = led_p.record_movement(
                idempotency_key="inc-real-1", agent_id="11" * 32, agent_account=AGENT,
                owner_pubkey=OWNER, network=NETWORK, genesis_hash=GENESIS,
                program_id=PROGRAM, token_mint=MINT, amount_base_units=400, nature="INCOME",
                status="PROVISIONAL", tx_signature="sig-real-prod-100", observed_at=NOW - 100,
            )
            led_p.reconcile_movement(m.movement_id, evidence_hash=HASH,
                authorized_by="conatus:protocol:reconciler:v1", slot=1000, tx_signature="sig-real-prod-100")
            led_p.record_cost(
                idempotency_key="cst-real-1", agent_id="11" * 32, agent_account=AGENT,
                owner_pubkey=OWNER, category="CONNECTIVITY_COMPUTE", cost_nature="REALIZED",
                economic_period="2033-05", amount_base_units=100, network=NETWORK,
                genesis_hash=GENESIS, program_id=PROGRAM, token_mint=MINT, incurred_at=NOW - 90,
                status="RECONCILED", provenance_source="EXTERNAL_VERIFIED",
                attestation_id="attest-real-1", evidence_hash=HASH,
                metadata={"authorized_by": "conatus:trusted:oracle:v1"},
            )
            r_dig, _ = calculate_side_data_digest(led_p, AGENT, (NETWORK, GENESIS, PROGRAM, MINT), "REVENUE", START, NOW)
            o_dig, _ = calculate_side_data_digest(led_p, AGENT, (NETWORK, GENESIS, PROGRAM, MINT), "OPEX", START, NOW)
            r_sig, r_pk, _ = self._sign(self.seed_1, side="REVENUE", digest=r_dig, prov="LIVE_RPC")
            o_sig, o_pk, _ = self._sign(self.seed_1, side="OPEX", digest=o_dig, prov="EXTERNAL_ATTESTED")
            record_coverage(
                led_p, agent_account=AGENT, network=NETWORK, genesis_hash=GENESIS,
                program_id=PROGRAM, token_mint=MINT, side="REVENUE", window_start=START,
                window_end=NOW, evidence_hash=HASH, verifier_id=self.auth_1,
                verifier=prod_verifier, provenance_type="LIVE_RPC",
                signature=r_sig, authority_pubkey=r_pk, verified_at=NOW,
            )
            record_coverage(
                led_p, agent_account=AGENT, network=NETWORK, genesis_hash=GENESIS,
                program_id=PROGRAM, token_mint=MINT, side="OPEX", window_start=START,
                window_end=NOW, evidence_hash=HASH, verifier_id=self.auth_1,
                verifier=prod_verifier, provenance_type="EXTERNAL_ATTESTED",
                signature=o_sig, authority_pubkey=o_pk, verified_at=NOW,
            )

        with EconomicLedger(prod_db_path, coverage_verifier=reopened_verifier) as led_prod_real:
            res_full = assess_agent(led_prod_real, AGENT, network=NETWORK, genesis_hash=GENESIS,
                                    program_id=PROGRAM, token_mint=MINT, now=NOW)[0]
            self.assertEqual(res_full["calculation_status"], "VALID")
            self.assertEqual(res_full["provenance"], "LIVE_RPC_AND_EXTERNAL_ATTESTED")
            self.assertEqual(res_full["conatus_ratio"], "4.00000000")

        # 2. Reopen without trusted keys: fails closed to INSUFFICIENT_DATA
        with EconomicLedger(db_path) as led_unconfigured:
            res_unconf = assess_agent(led_unconfigured, AGENT, network=NETWORK, genesis_hash=GENESIS,
                                      program_id=PROGRAM, token_mint=MINT, now=NOW)[0]
            self.assertEqual(res_unconf["calculation_status"], "INSUFFICIENT_DATA")

    def test_gate2_multiple_coverages_skips_tampered_and_selects_authentic(self):
        db_path = Path(self.temp.name) / "multi_candidates.db"
        prod_verifier = ProductionCoverageVerifier(
            trusted_authorities={self.auth_1},
            trusted_public_keys={self.auth_1: self.pub_1_b58},
        )
        test_verifier = IsolatedTestCoverageVerifier()
        with EconomicLedger(
            db_path,
            reconciliation_verifier=ProductionReconciliationVerifier(),
            attestation_verifier=ProductionAttestationVerifier(),
            coverage_verifier=test_verifier,
        ) as led:
            m = led.record_movement(
                idempotency_key="inc-multi-1", agent_id="11" * 32, agent_account=AGENT,
                owner_pubkey=OWNER, network=NETWORK, genesis_hash=GENESIS,
                program_id=PROGRAM, token_mint=MINT, amount_base_units=300, nature="INCOME",
                status="PROVISIONAL", tx_signature="sig-multi-prod-100", observed_at=NOW - 100,
            )
            led.reconcile_movement(m.movement_id, evidence_hash=HASH,
                authorized_by="conatus:protocol:reconciler:v1", slot=1000, tx_signature="sig-multi-prod-100")
            led.record_cost(
                idempotency_key="cst-multi-1", agent_id="11" * 32, agent_account=AGENT,
                owner_pubkey=OWNER, category="ENERGY_FUEL", cost_nature="REALIZED",
                economic_period="2033-05", amount_base_units=100, network=NETWORK,
                genesis_hash=GENESIS, program_id=PROGRAM, token_mint=MINT, incurred_at=NOW - 90,
                status="RECONCILED", provenance_source="EXTERNAL_VERIFIED",
                attestation_id="attest-multi-1", evidence_hash=HASH,
                metadata={"authorized_by": "conatus:trusted:oracle:v1"},
            )

            rev_digest, _ = calculate_side_data_digest(led, AGENT, (NETWORK, GENESIS, PROGRAM, MINT), "REVENUE", START, NOW)
            opex_digest, _ = calculate_side_data_digest(led, AGENT, (NETWORK, GENESIS, PROGRAM, MINT), "OPEX", START, NOW)

            # Insert authentic coverage (rowid 1)
            rev_sig, rev_pk, _ = self._sign(self.seed_1, side="REVENUE", digest=rev_digest, evidence_hash="hash-authentic-1")
            record_coverage(
                led, agent_account=AGENT, network=NETWORK, genesis_hash=GENESIS,
                program_id=PROGRAM, token_mint=MINT, side="REVENUE", window_start=START,
                window_end=NOW, evidence_hash="hash-authentic-1", verifier_id=self.auth_1,
                verifier=test_verifier, provenance_type="EXTERNAL_ATTESTED",
                signature=rev_sig, authority_pubkey=rev_pk, verified_at=NOW - 50,
            )
            # Insert newer tampered/forged coverage for the same window (rowid 2)
            forged_sig = discovery.b58encode(b"\x99" * 64)
            record_coverage(
                led, agent_account=AGENT, network=NETWORK, genesis_hash=GENESIS,
                program_id=PROGRAM, token_mint=MINT, side="REVENUE", window_start=START,
                window_end=NOW, evidence_hash="hash-forged-2", verifier_id=self.auth_1,
                verifier=test_verifier, provenance_type="EXTERNAL_ATTESTED",
                signature=forged_sig, authority_pubkey=rev_pk, verified_at=NOW - 10,
            )

            # OPEX authentic coverage
            opex_sig, opex_pk, _ = self._sign(self.seed_1, side="OPEX", digest=opex_digest, evidence_hash=HASH)
            record_coverage(
                led, agent_account=AGENT, network=NETWORK, genesis_hash=GENESIS,
                program_id=PROGRAM, token_mint=MINT, side="OPEX", window_start=START,
                window_end=NOW, evidence_hash=HASH, verifier_id=self.auth_1,
                verifier=test_verifier, provenance_type="EXTERNAL_ATTESTED",
                signature=opex_sig, authority_pubkey=opex_pk, verified_at=NOW,
            )

        # Reopen with ProductionCoverageVerifier
        with EconomicLedger(db_path, coverage_verifier=prod_verifier) as led_prod:
            res = assess_agent(led_prod, AGENT, network=NETWORK, genesis_hash=GENESIS,
                               program_id=PROGRAM, token_mint=MINT, now=NOW)[0]
            # Must successfully select the authentic coverage and discard the forged newer one
            self.assertEqual(res["calculation_status"], "VALID")
            self.assertEqual(res["conatus_ratio"], "3.00000000")

    def test_gate2_multiple_coverages_skips_revoked_authority_candidate(self):
        db_path = Path(self.temp.name) / "multi_revoked.db"
        prod_verifier = ProductionCoverageVerifier(
            trusted_authorities={self.auth_1, self.auth_2},
            trusted_public_keys={self.auth_1: self.pub_1_b58, self.auth_2: self.pub_2_b58},
        )
        test_verifier = IsolatedTestCoverageVerifier()
        with EconomicLedger(
            db_path,
            reconciliation_verifier=ProductionReconciliationVerifier(),
            attestation_verifier=ProductionAttestationVerifier(),
            coverage_verifier=test_verifier,
        ) as led:
            m = led.record_movement(
                idempotency_key="inc-rev-1", agent_id="11" * 32, agent_account=AGENT,
                owner_pubkey=OWNER, network=NETWORK, genesis_hash=GENESIS,
                program_id=PROGRAM, token_mint=MINT, amount_base_units=200, nature="INCOME",
                status="PROVISIONAL", tx_signature="sig-rev-prod-100", observed_at=NOW - 100,
            )
            led.reconcile_movement(m.movement_id, evidence_hash=HASH,
                authorized_by="conatus:protocol:reconciler:v1", slot=1000, tx_signature="sig-rev-prod-100")
            led.record_cost(
                idempotency_key="cst-rev-1", agent_id="11" * 32, agent_account=AGENT,
                owner_pubkey=OWNER, category="INSURANCE", cost_nature="REALIZED",
                economic_period="2033-05", amount_base_units=100, network=NETWORK,
                genesis_hash=GENESIS, program_id=PROGRAM, token_mint=MINT, incurred_at=NOW - 90,
                status="RECONCILED", provenance_source="EXTERNAL_VERIFIED",
                attestation_id="attest-rev-1", evidence_hash=HASH,
                metadata={"authorized_by": "conatus:trusted:oracle:v1"},
            )

            rev_digest, _ = calculate_side_data_digest(led, AGENT, (NETWORK, GENESIS, PROGRAM, MINT), "REVENUE", START, NOW)
            opex_digest, _ = calculate_side_data_digest(led, AGENT, (NETWORK, GENESIS, PROGRAM, MINT), "OPEX", START, NOW)

            # Insert Coverage signed by Authority 1 (which will be revoked)
            rev_sig_1, rev_pk_1, _ = self._sign(self.seed_1, side="REVENUE", digest=rev_digest, auth=self.auth_1, evidence_hash="hash-auth1")
            record_coverage(
                led, agent_account=AGENT, network=NETWORK, genesis_hash=GENESIS,
                program_id=PROGRAM, token_mint=MINT, side="REVENUE", window_start=START,
                window_end=NOW, evidence_hash="hash-auth1", verifier_id=self.auth_1,
                verifier=test_verifier, provenance_type="EXTERNAL_ATTESTED",
                signature=rev_sig_1, authority_pubkey=rev_pk_1, verified_at=NOW - 10,
            )
            # Insert Coverage signed by Authority 2 (which remains trusted)
            rev_sig_2, rev_pk_2, _ = self._sign(self.seed_2, side="REVENUE", digest=rev_digest, auth=self.auth_2, evidence_hash="hash-auth2")
            record_coverage(
                led, agent_account=AGENT, network=NETWORK, genesis_hash=GENESIS,
                program_id=PROGRAM, token_mint=MINT, side="REVENUE", window_start=START,
                window_end=NOW, evidence_hash="hash-auth2", verifier_id=self.auth_2,
                verifier=test_verifier, provenance_type="EXTERNAL_ATTESTED",
                signature=rev_sig_2, authority_pubkey=rev_pk_2, verified_at=NOW - 20,
            )

            # OPEX signed by Authority 2
            opex_sig, opex_pk, _ = self._sign(self.seed_2, side="OPEX", digest=opex_digest, auth=self.auth_2, evidence_hash=HASH)
            record_coverage(
                led, agent_account=AGENT, network=NETWORK, genesis_hash=GENESIS,
                program_id=PROGRAM, token_mint=MINT, side="OPEX", window_start=START,
                window_end=NOW, evidence_hash=HASH, verifier_id=self.auth_2,
                verifier=test_verifier, provenance_type="EXTERNAL_ATTESTED",
                signature=opex_sig, authority_pubkey=opex_pk, verified_at=NOW,
            )

        # Revoke Authority 1
        prod_verifier.revoke_authority(self.auth_1)

        with EconomicLedger(db_path, coverage_verifier=prod_verifier) as led_prod:
            res = assess_agent(led_prod, AGENT, network=NETWORK, genesis_hash=GENESIS,
                               program_id=PROGRAM, token_mint=MINT, now=NOW)[0]
            # Must skip the candidate from revoked Authority 1 and select the authentic one from Authority 2
            self.assertEqual(res["calculation_status"], "VALID")
            self.assertEqual(res["conatus_ratio"], "2.00000000")

    def test_rfc_8032_official_vectors(self):
        """Official RFC 8032 Test Vectors 1 and 2 verification with cryptography."""
        # Test 1 (empty message)
        sk_1 = bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60")
        pk_1 = bytes.fromhex("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a")
        msg_1 = b""
        sig_1 = bytes.fromhex(
            "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155"
            "5fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"
        )
        self.assertTrue(verify_ed25519_signature(sig_1, msg_1, pk_1))

        # Test 2 (1-byte message: 0x72)
        sk_2 = bytes.fromhex("4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb")
        pk_2 = bytes.fromhex("3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c")
        msg_2 = bytes.fromhex("72")
        sig_2 = bytes.fromhex(
            "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da"
            "085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00"
        )
        self.assertTrue(verify_ed25519_signature(sig_2, msg_2, pk_2))

    def test_gate1_non_canonical_or_invalid_curve_points_rejected(self):
        """Reject non-canonical encodings, invalid lengths, and invalid curve points."""
        msg = b"test message"
        # 1. Invalid signature lengths
        self.assertFalse(verify_ed25519_signature(b"\x00" * 63, msg, self.pk_1_bytes))
        self.assertFalse(verify_ed25519_signature(b"\x00" * 65, msg, self.pk_1_bytes))
        # 2. Invalid public key lengths
        self.assertFalse(verify_ed25519_signature(b"\x00" * 64, msg, b"\x00" * 31))
        self.assertFalse(verify_ed25519_signature(b"\x00" * 64, msg, b"\x00" * 33))
        # 3. Non-canonical S parameter (S >= L in signature)
        # RFC 8032: L = 2^252 + 27742317777372353535851937790883648493
        L = 2**252 + 27742317777372353535851937790883648493
        non_canonical_s = (L + 1).to_bytes(32, "little")
        non_canonical_sig = b"\x00" * 32 + non_canonical_s
        self.assertFalse(verify_ed25519_signature(non_canonical_sig, msg, self.pk_1_bytes))
        # 4. Point not on curve / invalid field element (y >= 2^255 - 19)
        p = 2**255 - 19
        invalid_point = (p + 5).to_bytes(32, "little")
        self.assertFalse(verify_ed25519_signature(b"\x00" * 64, msg, invalid_point))

    def test_forged_origin_lineage_rejected_at_ingestion(self):
        """Ledger strictly prevents unverified movements from claiming LIVE_RPC or EXTERNAL_ATTESTED lineage."""
        with EconomicLedger(":memory:") as led:
            # 1. Provisional movement claiming LIVE_RPC
            with self.assertRaises(LedgerValidationError) as ctx:
                led.record_movement(
                    idempotency_key="forged-prov-1", agent_id="11" * 32, agent_account=AGENT,
                    owner_pubkey=OWNER, network=NETWORK, genesis_hash=GENESIS,
                    program_id=PROGRAM, token_mint=MINT, amount_base_units=100, nature="INCOME",
                    status="PROVISIONAL", evidence_lineage="LIVE_RPC",
                )
            self.assertIn("LIVE_RPC", str(ctx.exception))

            # 2. Manual entry claiming LIVE_RPC
            with self.assertRaises(LedgerValidationError) as ctx:
                led.record_movement(
                    idempotency_key="forged-manual-1", agent_id="11" * 32, agent_account=AGENT,
                    owner_pubkey=OWNER, network=NETWORK, genesis_hash=GENESIS,
                    program_id=PROGRAM, token_mint=MINT, amount_base_units=100, nature="INCOME",
                    status="PROVISIONAL", provenance_source="MANUAL_ENTRY",
                    evidence_lineage="LIVE_RPC",
                )
            self.assertIn("MANUAL_ENTRY", str(ctx.exception))

            # 3. Unverified cost claiming EXTERNAL_ATTESTED
            with self.assertRaises(LedgerValidationError) as ctx:
                led.record_cost(
                    idempotency_key="forged-cost-1", agent_id="11" * 32, agent_account=AGENT,
                    owner_pubkey=OWNER, category="CONNECTIVITY_COMPUTE", cost_nature="REALIZED",
                    economic_period="2033-05", amount_base_units=100, network=NETWORK,
                    genesis_hash=GENESIS, program_id=PROGRAM, token_mint=MINT,
                    status="PROVISIONAL", provenance_source="MANUAL_ENTRY",
                    evidence_lineage="EXTERNAL_ATTESTED",
                )
            self.assertIn("EXTERNAL_ATTESTED", str(ctx.exception))

    def test_production_rejects_mixed_real_revenue_with_synthetic_costs(self):
        """Mixed authentic LIVE_RPC revenue with synthetic cost yields INSUFFICIENT_DATA in production."""
        db_path = Path(self.temp.name) / "mixed_real_rev_synth_cost.db"
        prod_verifier = ProductionCoverageVerifier(
            trusted_authorities={self.auth_1},
            trusted_public_keys={self.auth_1: self.pub_1_b58},
        )
        with EconomicLedger(
            db_path,
            reconciliation_verifier=ProductionReconciliationVerifier(),
            attestation_verifier=IsolatedTestAttestationVerifier(),
            coverage_verifier=prod_verifier,
        ) as led:
            m = led.record_movement(
                idempotency_key="inc-real-mix", agent_id="11" * 32, agent_account=AGENT,
                owner_pubkey=OWNER, network=NETWORK, genesis_hash=GENESIS,
                program_id=PROGRAM, token_mint=MINT, amount_base_units=500, nature="INCOME",
                status="PROVISIONAL", tx_signature="sig-real-prod-200", observed_at=NOW - 100,
            )
            led.reconcile_movement(m.movement_id, evidence_hash=HASH,
                authorized_by="conatus:protocol:reconciler:v1", slot=1000, tx_signature="sig-real-prod-200")

            led.record_cost(
                idempotency_key="cst-synth-mix", agent_id="11" * 32, agent_account=AGENT,
                owner_pubkey=OWNER, category="CONNECTIVITY_COMPUTE", cost_nature="REALIZED",
                economic_period="2033-05", amount_base_units=100, network=NETWORK,
                genesis_hash=GENESIS, program_id=PROGRAM, token_mint=MINT, incurred_at=NOW - 90,
                status="RECONCILED", provenance_source="EXTERNAL_VERIFIED",
                attestation_id="attest-synth-1", evidence_hash=HASH,
                metadata={"authorized_by": "conatus:trusted:oracle:v1"},
            )

            r_dig, _ = calculate_side_data_digest(led, AGENT, (NETWORK, GENESIS, PROGRAM, MINT), "REVENUE", START, NOW)
            o_dig, _ = calculate_side_data_digest(led, AGENT, (NETWORK, GENESIS, PROGRAM, MINT), "OPEX", START, NOW)
            r_sig, r_pk, _ = self._sign(self.seed_1, side="REVENUE", digest=r_dig, prov="LIVE_RPC")
            o_sig, o_pk, _ = self._sign(self.seed_1, side="OPEX", digest=o_dig, prov="EXTERNAL_ATTESTED")
            record_coverage(
                led, agent_account=AGENT, network=NETWORK, genesis_hash=GENESIS,
                program_id=PROGRAM, token_mint=MINT, side="REVENUE", window_start=START,
                window_end=NOW, evidence_hash=HASH, verifier_id=self.auth_1,
                verifier=prod_verifier, provenance_type="LIVE_RPC",
                signature=r_sig, authority_pubkey=r_pk, verified_at=NOW,
            )
            record_coverage(
                led, agent_account=AGENT, network=NETWORK, genesis_hash=GENESIS,
                program_id=PROGRAM, token_mint=MINT, side="OPEX", window_start=START,
                window_end=NOW, evidence_hash=HASH, verifier_id=self.auth_1,
                verifier=prod_verifier, provenance_type="EXTERNAL_ATTESTED",
                signature=o_sig, authority_pubkey=o_pk, verified_at=NOW,
            )

        with EconomicLedger(db_path, coverage_verifier=prod_verifier) as led_prod:
            res = assess_agent(led_prod, AGENT, network=NETWORK, genesis_hash=GENESIS,
                               program_id=PROGRAM, token_mint=MINT, now=NOW)[0]
            self.assertEqual(res["calculation_status"], "INSUFFICIENT_DATA")
            self.assertIn("synthetic_or_unverified_cost_lineage", res["exclusion_reasons"])
            self.assertEqual(res["provenance"], "SYNTHETIC_TEST")

    def test_production_rejects_mixed_synthetic_revenue_with_real_costs(self):
        """Mixed synthetic revenue with authentic EXTERNAL_ATTESTED costs yields INSUFFICIENT_DATA in production."""
        db_path = Path(self.temp.name) / "mixed_synth_rev_real_cost.db"
        prod_verifier = ProductionCoverageVerifier(
            trusted_authorities={self.auth_1},
            trusted_public_keys={self.auth_1: self.pub_1_b58},
        )
        with EconomicLedger(
            db_path,
            reconciliation_verifier=IsolatedTestReconcilerVerifier(),
            attestation_verifier=ProductionAttestationVerifier(),
            coverage_verifier=prod_verifier,
        ) as led:
            m = led.record_movement(
                idempotency_key="inc-synth-mix2", agent_id="11" * 32, agent_account=AGENT,
                owner_pubkey=OWNER, network=NETWORK, genesis_hash=GENESIS,
                program_id=PROGRAM, token_mint=MINT, amount_base_units=500, nature="INCOME",
                status="PROVISIONAL", tx_signature="sig-synth-prod-200", observed_at=NOW - 100,
            )
            led.reconcile_movement(m.movement_id, evidence_hash=HASH,
                authorized_by="conatus:protocol:reconciler:v1", slot=1000, tx_signature="sig-synth-prod-200")

            led.record_cost(
                idempotency_key="cst-real-mix2", agent_id="11" * 32, agent_account=AGENT,
                owner_pubkey=OWNER, category="CONNECTIVITY_COMPUTE", cost_nature="REALIZED",
                economic_period="2033-05", amount_base_units=100, network=NETWORK,
                genesis_hash=GENESIS, program_id=PROGRAM, token_mint=MINT, incurred_at=NOW - 90,
                status="RECONCILED", provenance_source="EXTERNAL_VERIFIED",
                attestation_id="attest-real-2", evidence_hash=HASH,
                metadata={"authorized_by": "conatus:trusted:oracle:v1"},
            )

            r_dig, _ = calculate_side_data_digest(led, AGENT, (NETWORK, GENESIS, PROGRAM, MINT), "REVENUE", START, NOW)
            o_dig, _ = calculate_side_data_digest(led, AGENT, (NETWORK, GENESIS, PROGRAM, MINT), "OPEX", START, NOW)
            r_sig, r_pk, _ = self._sign(self.seed_1, side="REVENUE", digest=r_dig, prov="EXTERNAL_ATTESTED")
            o_sig, o_pk, _ = self._sign(self.seed_1, side="OPEX", digest=o_dig, prov="EXTERNAL_ATTESTED")
            record_coverage(
                led, agent_account=AGENT, network=NETWORK, genesis_hash=GENESIS,
                program_id=PROGRAM, token_mint=MINT, side="REVENUE", window_start=START,
                window_end=NOW, evidence_hash=HASH, verifier_id=self.auth_1,
                verifier=prod_verifier, provenance_type="EXTERNAL_ATTESTED",
                signature=r_sig, authority_pubkey=r_pk, verified_at=NOW,
            )
            record_coverage(
                led, agent_account=AGENT, network=NETWORK, genesis_hash=GENESIS,
                program_id=PROGRAM, token_mint=MINT, side="OPEX", window_start=START,
                window_end=NOW, evidence_hash=HASH, verifier_id=self.auth_1,
                verifier=prod_verifier, provenance_type="EXTERNAL_ATTESTED",
                signature=o_sig, authority_pubkey=o_pk, verified_at=NOW,
            )

        with EconomicLedger(db_path, coverage_verifier=prod_verifier) as led_prod:
            res = assess_agent(led_prod, AGENT, network=NETWORK, genesis_hash=GENESIS,
                               program_id=PROGRAM, token_mint=MINT, now=NOW)[0]
            self.assertEqual(res["calculation_status"], "INSUFFICIENT_DATA")
            self.assertIn("synthetic_or_unverified_revenue_lineage", res["exclusion_reasons"])
            self.assertEqual(res["provenance"], "SYNTHETIC_TEST")

    def test_missing_lineage_fails_closed_in_production(self):
        """Records with missing or unverified lineage fail closed in production."""
        db_path = Path(self.temp.name) / "missing_lineage.db"
        prod_verifier = ProductionCoverageVerifier(
            trusted_authorities={self.auth_1},
            trusted_public_keys={self.auth_1: self.pub_1_b58},
        )
        with EconomicLedger(
            db_path,
            reconciliation_verifier=ProductionReconciliationVerifier(),
            attestation_verifier=ProductionAttestationVerifier(),
            coverage_verifier=prod_verifier,
        ) as led:
            m = led.record_movement(
                idempotency_key="inc-miss-1", agent_id="11" * 32, agent_account=AGENT,
                owner_pubkey=OWNER, network=NETWORK, genesis_hash=GENESIS,
                program_id=PROGRAM, token_mint=MINT, amount_base_units=400, nature="INCOME",
                status="PROVISIONAL", tx_signature="sig-miss-prod-100", observed_at=NOW - 100,
            )
            led.reconcile_movement(m.movement_id, evidence_hash=HASH,
                authorized_by="conatus:protocol:reconciler:v1", slot=1000, tx_signature="sig-miss-prod-100")
            # Clear evidence_lineage in the database for movement
            led._conn.execute("UPDATE economic_movements SET evidence_lineage = '' WHERE movement_id = ?", (m.movement_id,))

            led.record_cost(
                idempotency_key="cst-miss-1", agent_id="11" * 32, agent_account=AGENT,
                owner_pubkey=OWNER, category="CONNECTIVITY_COMPUTE", cost_nature="REALIZED",
                economic_period="2033-05", amount_base_units=100, network=NETWORK,
                genesis_hash=GENESIS, program_id=PROGRAM, token_mint=MINT, incurred_at=NOW - 90,
                status="RECONCILED", provenance_source="EXTERNAL_VERIFIED",
                attestation_id="attest-miss-1", evidence_hash=HASH,
                metadata={"authorized_by": "conatus:trusted:oracle:v1"},
            )

            r_dig, _ = calculate_side_data_digest(led, AGENT, (NETWORK, GENESIS, PROGRAM, MINT), "REVENUE", START, NOW)
            o_dig, _ = calculate_side_data_digest(led, AGENT, (NETWORK, GENESIS, PROGRAM, MINT), "OPEX", START, NOW)
            r_sig, r_pk, _ = self._sign(self.seed_1, side="REVENUE", digest=r_dig, prov="LIVE_RPC")
            o_sig, o_pk, _ = self._sign(self.seed_1, side="OPEX", digest=o_dig, prov="EXTERNAL_ATTESTED")
            record_coverage(
                led, agent_account=AGENT, network=NETWORK, genesis_hash=GENESIS,
                program_id=PROGRAM, token_mint=MINT, side="REVENUE", window_start=START,
                window_end=NOW, evidence_hash=HASH, verifier_id=self.auth_1,
                verifier=prod_verifier, provenance_type="LIVE_RPC",
                signature=r_sig, authority_pubkey=r_pk, verified_at=NOW,
            )
            record_coverage(
                led, agent_account=AGENT, network=NETWORK, genesis_hash=GENESIS,
                program_id=PROGRAM, token_mint=MINT, side="OPEX", window_start=START,
                window_end=NOW, evidence_hash=HASH, verifier_id=self.auth_1,
                verifier=prod_verifier, provenance_type="EXTERNAL_ATTESTED",
                signature=o_sig, authority_pubkey=o_pk, verified_at=NOW,
            )

        with EconomicLedger(db_path, coverage_verifier=prod_verifier) as led_prod:
            res = assess_agent(led_prod, AGENT, network=NETWORK, genesis_hash=GENESIS,
                               program_id=PROGRAM, token_mint=MINT, now=NOW)[0]
            self.assertEqual(res["calculation_status"], "INSUFFICIENT_DATA")
            self.assertIn("missing_revenue_evidence_lineage", res["exclusion_reasons"])


if __name__ == "__main__":
    unittest.main()
