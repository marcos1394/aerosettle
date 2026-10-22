"""Comprehensive test suite for the Conatus Persistent Economic Ledger (CON-22)."""
import os
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.economic_ledger.ledger import (
    DEFAULT_TRUSTED_RECONCILER_AUTHORITIES,
    EconomicLedger,
    IsolatedTestReconcilerVerifier,
)
from tools.economic_ledger.models import (
    IdempotencyConflictError,
    LedgerValidationError,
    MovementNature,
    MovementStatus,
    ProvenanceSource,
    validate_base_units,
)
from tools.economic_ledger.schema import MigrationError, run_migrations, split_sql_statements

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

VALID_HASH = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
TRUSTED_RECONCILER = "conatus:protocol:reconciler:v1"


class EconomicLedgerTests(unittest.TestCase):
    def setUp(self):
        # Create an isolated temporary database for each test
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_ledger.db"
        self.test_verifier = IsolatedTestReconcilerVerifier()
        self.ledger = EconomicLedger(self.db_path, reconciliation_verifier=self.test_verifier)

    def tearDown(self):
        self.ledger.close()
        self.temp_dir.cleanup()

    # ─────────────────────────────────────────────────────────────────────────
    # 1. Idempotency & Full Semantic Conflict Verification
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
            status=MovementStatus.PROVISIONAL,
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
            status=MovementStatus.PROVISIONAL,
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
            status=MovementStatus.PROVISIONAL,
            tx_signature="sig-base",
            evidence_hash=VALID_HASH,
        )

        # 1. Differing amount
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
                amount_base_units=2_000_000,
                nature=MovementNature.INCOME,
                status=MovementStatus.PROVISIONAL,
                tx_signature="sig-base",
                evidence_hash=VALID_HASH,
            )
        self.assertIn("amount_base_units", str(ctx.exception))

        # 2. Differing nature
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
                nature=MovementNature.EXPENSE,
                status=MovementStatus.PROVISIONAL,
                tx_signature="sig-base",
                evidence_hash=VALID_HASH,
            )
        self.assertIn("nature", str(ctx.exception))

        # 3. Differing genesis_hash
        with self.assertRaises(IdempotencyConflictError) as ctx:
            self.ledger.record_movement(
                idempotency_key=key,
                agent_id="11" * 32,
                agent_account=AGENT_1,
                owner_pubkey=OWNER_1,
                network=NET_LOCALNET,
                genesis_hash="OtherGenesisHash11111111111111111111111111",
                program_id=PROGRAM_ID,
                token_mint=MINT_USDC,
                amount_base_units=1_000_000,
                nature=MovementNature.INCOME,
                status=MovementStatus.PROVISIONAL,
                tx_signature="sig-base",
                evidence_hash=VALID_HASH,
            )
        self.assertIn("genesis_hash", str(ctx.exception))

        # 4. Differing tx_signature
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
                nature=MovementNature.INCOME,
                status=MovementStatus.PROVISIONAL,
                tx_signature="sig-differing-tx-sig",
                evidence_hash=VALID_HASH,
            )
        self.assertIn("tx_signature", str(ctx.exception))

        # 5. Differing evidence_hash
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
                nature=MovementNature.INCOME,
                status=MovementStatus.PROVISIONAL,
                tx_signature="sig-base",
                evidence_hash="4b227777d4dd1fc61c6f884f48641d02b4d121d3fd328cb08b5531fcacdabf8a",
            )
        self.assertIn("evidence_hash", str(ctx.exception))

    def test_legitimate_retry_preserves_lifecycle_state_transitions(self):
        key = "legit-retry-transition-test"

        # 1. Record movement in initial PROVISIONAL state
        m = self.ledger.record_movement(
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
            status=MovementStatus.PROVISIONAL,
            tx_signature="sig-legit-initial",
            evidence_hash=VALID_HASH,
        )
        self.assertEqual(m.status, MovementStatus.PROVISIONAL)

        # 2. Trusted reconciler transitions it to RECONCILED
        rec = self.ledger.reconcile_movement(
            m.movement_id,
            evidence_hash=VALID_HASH,
            authorized_by=TRUSTED_RECONCILER,
            slot=104920,
            tx_signature="sig-legit-initial",
        )
        self.assertEqual(rec.status, MovementStatus.RECONCILED)

        # 3. Legitimate client retry with initial event parameters
        # Must return the existing record and NOT raise IdempotencyConflictError,
        # preserving the updated RECONCILED status without duplicating.
        retry_m = self.ledger.record_movement(
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
            status=MovementStatus.PROVISIONAL,
            tx_signature="sig-legit-initial",
            evidence_hash=VALID_HASH,
        )

        self.assertEqual(retry_m.movement_id, m.movement_id)
        self.assertEqual(retry_m.status, MovementStatus.RECONCILED)

        # Verify only 1 movement exists
        movements, _ = self.ledger.list_movements(AGENT_1)
        self.assertEqual(len(movements), 1)

    def test_idempotent_retry_after_reconciliation_preserves_initial_event_without_conflict(self):
        key = "idemp-initial-footprint-retry"

        # 1. Client records movement initially with no evidence_hash and provisional signature
        initial_sig = "sig-client-initial-submit-11111111111111111"
        m = self.ledger.record_movement(
            idempotency_key=key,
            agent_id="11" * 32,
            agent_account=AGENT_1,
            owner_pubkey=OWNER_1,
            network=NET_LOCALNET,
            genesis_hash=GENESIS_HASH,
            program_id=PROGRAM_ID,
            token_mint=MINT_USDC,
            amount_base_units=2_000_000,
            nature=MovementNature.INCOME,
            status=MovementStatus.PROVISIONAL,
            tx_signature=initial_sig,
            evidence_hash=None,
        )
        self.assertEqual(m.status, MovementStatus.PROVISIONAL)
        self.assertIsNone(m.evidence_hash)

        # 2. Reconciler promotes it to RECONCILED and attaches verified evidence hash
        reconciled = self.ledger.reconcile_movement(
            m.movement_id,
            evidence_hash=VALID_HASH,
            authorized_by=TRUSTED_RECONCILER,
            slot=104950,
            tx_signature=initial_sig,
        )
        self.assertEqual(reconciled.status, MovementStatus.RECONCILED)
        self.assertEqual(reconciled.evidence_hash, VALID_HASH)

        # 3. Client retries initial event (e.g. timeout on client side, retry queue)
        # The retry contains the initial event parameters (evidence_hash is None).
        # It must NOT produce an idempotency conflict despite evidence_hash being added by reconciliation.
        retry_res = self.ledger.record_movement(
            idempotency_key=key,
            agent_id="11" * 32,
            agent_account=AGENT_1,
            owner_pubkey=OWNER_1,
            network=NET_LOCALNET,
            genesis_hash=GENESIS_HASH,
            program_id=PROGRAM_ID,
            token_mint=MINT_USDC,
            amount_base_units=2_000_000,
            nature=MovementNature.INCOME,
            status=MovementStatus.PROVISIONAL,
            tx_signature=initial_sig,
            evidence_hash=None,
        )
        self.assertEqual(retry_res.movement_id, m.movement_id)
        self.assertEqual(retry_res.status, MovementStatus.RECONCILED)

        # 4. A truly conflicting request (e.g. different amount) must still fail with 409
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
                amount_base_units=9_999_999,  # Divergent amount!
                nature=MovementNature.INCOME,
                status=MovementStatus.PROVISIONAL,
                tx_signature=initial_sig,
                evidence_hash=None,
            )
        self.assertIn("amount_base_units", str(ctx.exception))

    def test_concurrent_writes_with_same_idempotency_key(self):
        shared_key = "concurrent-idemp-race-test"
        results = []
        errors = []

        def worker():
            try:
                with EconomicLedger(self.db_path, reconciliation_verifier=self.test_verifier) as thread_ledger:
                    res = thread_ledger.record_movement(
                        idempotency_key=shared_key,
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
                        tx_signature="sig-race-1111111111111111",
                        evidence_hash=VALID_HASH,
                    )
                    results.append(res.movement_id)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0, f"Concurrent identical writes produced errors: {errors}")
        self.assertEqual(len(results), 8)
        # All 8 threads must receive the EXACT same movement_id
        self.assertEqual(len(set(results)), 1)

        # Database must contain exactly 1 movement
        movements, _ = self.ledger.list_movements(AGENT_1)
        matching = [m for m in movements if m.idempotency_key == shared_key]
        self.assertEqual(len(matching), 1)

    # ─────────────────────────────────────────────────────────────────────────
    # 2. Reconciliation Integrity: Gates, Conservative Policy & Falsification
    # ─────────────────────────────────────────────────────────────────────────

    def test_initial_movement_cannot_be_recorded_directly_as_reconciled(self):
        # Even with signatures and hashes, direct RECONCILED declaration is forbidden
        with self.assertRaises(LedgerValidationError) as ctx:
            self.ledger.record_movement(
                idempotency_key="unauth-direct-rec",
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
                tx_signature="sig-direct-attempt",
                evidence_hash=VALID_HASH,
            )
        self.assertIn("Initial economic movements must be recorded as PROVISIONAL", str(ctx.exception))

    def test_record_settlement_starts_strictly_provisional(self):
        order_data = {
            "work_order_id": "01" * 32,
            "total_amount": 10_000_000,
            "payment_model": "Proportional",
            "verification_status": "Accepted",
            "completion_bps": 10000,
            "verification_attestation_hash": VALID_HASH,
        }

        m = self.ledger.record_settlement(
            work_order_account=WORK_ORDER_1,
            work_order_data=order_data,
            agent_account=AGENT_1,
            owner_pubkey=OWNER_1,
            agent_id="11" * 32,
            network=NET_LOCALNET,
            genesis_hash=GENESIS_HASH,
            program_id=PROGRAM_ID,
            token_mint=MINT_USDC,
            tx_signature="tx-settle-provisional-check",
        )

        # Must always be initially PROVISIONAL on observation
        self.assertEqual(m.status, MovementStatus.PROVISIONAL)

        # Balances reflect provisional, NOT reconciled
        bal = self.ledger.get_balances(AGENT_1, token_mint=MINT_USDC)[0]
        self.assertEqual(bal.reconciled_balance, 0)
        self.assertEqual(bal.provisional_balance, 10_000_000)

    def test_reconcile_movement_rejects_falsified_or_unauthorized_evidence(self):
        m = self.ledger.record_movement(
            idempotency_key="reconcile-guards-test",
            agent_id="11" * 32,
            agent_account=AGENT_1,
            owner_pubkey=OWNER_1,
            network=NET_LOCALNET,
            genesis_hash=GENESIS_HASH,
            program_id=PROGRAM_ID,
            token_mint=MINT_USDC,
            amount_base_units=500_000,
            nature=MovementNature.INCOME,
            tx_signature="sig-guard-base-signature-11111111111111111111111",
            evidence_hash=VALID_HASH,
        )

        # 1. Unauthorized reconciler authority
        with self.assertRaises(LedgerValidationError) as ctx:
            self.ledger.reconcile_movement(
                m.movement_id,
                evidence_hash=VALID_HASH,
                authorized_by="untrusted-bot-or-malicious-operator",
                slot=100,
                tx_signature="sig-guard-base-signature-11111111111111111111111",
            )
        self.assertIn("unauthorized reconciler authority", str(ctx.exception))

        # 2. Falsified / malformed evidence hash
        with self.assertRaises(LedgerValidationError) as ctx:
            self.ledger.reconcile_movement(
                m.movement_id,
                evidence_hash="fake-non-hex-hash",
                authorized_by=TRUSTED_RECONCILER,
                slot=100,
                tx_signature="sig-guard-base-signature-11111111111111111111111",
            )
        self.assertIn("falsified or invalid evidence hash format", str(ctx.exception))

        # 3. Invalid block slot (0 or negative)
        with self.assertRaises(LedgerValidationError) as ctx:
            self.ledger.reconcile_movement(
                m.movement_id,
                evidence_hash=VALID_HASH,
                authorized_by=TRUSTED_RECONCILER,
                slot=0,
                tx_signature="sig-guard-base-signature-11111111111111111111111",
            )
        self.assertIn("slot must be a positive confirmed block slot", str(ctx.exception))

        # 4. Conflicting tx_signature with existing recorded movement
        with self.assertRaises(LedgerValidationError) as ctx:
            self.ledger.reconcile_movement(
                m.movement_id,
                evidence_hash=VALID_HASH,
                authorized_by=TRUSTED_RECONCILER,
                slot=100,
                tx_signature="sig-different-conflicting-signature-2222222222222222",
            )
        self.assertIn("conflicts with recorded movement tx_signature", str(ctx.exception))

        # Verify that movement status remains strictly PROVISIONAL and was NOT reconciled
        after_failed_checks = self.ledger.get_movement(m.movement_id)
        self.assertEqual(after_failed_checks.status, MovementStatus.PROVISIONAL)

        # Reconciled balance remains 0
        bal = self.ledger.get_balances(AGENT_1, token_mint=MINT_USDC)[0]
        self.assertEqual(bal.reconciled_balance, 0)

        # 5. Genuine reconciliation by trusted authority with valid evidence succeeds
        reconciled = self.ledger.reconcile_movement(
            m.movement_id,
            evidence_hash=VALID_HASH,
            authorized_by=TRUSTED_RECONCILER,
            slot=105000,
            tx_signature="sig-guard-base-signature-11111111111111111111111",
        )
        self.assertEqual(reconciled.status, MovementStatus.RECONCILED)
        bal_after = self.ledger.get_balances(AGENT_1, token_mint=MINT_USDC)[0]
        self.assertEqual(bal_after.reconciled_balance, 500_000)

    def test_reconcile_movement_disabled_in_production_and_rejects_fictitious_signature(self):
        # Default EconomicLedger instance represents production mode (no verifier injected)
        prod_db = Path(self.temp_dir.name) / "prod_reconcile_test.db"
        prod_ledger = EconomicLedger(prod_db)
        try:
            m = prod_ledger.record_movement(
                idempotency_key="prod-fictitious-reconcile-test",
                agent_id="11" * 32,
                agent_account=AGENT_1,
                owner_pubkey=OWNER_1,
                network=NET_LOCALNET,
                genesis_hash=GENESIS_HASH,
                program_id=PROGRAM_ID,
                token_mint=MINT_USDC,
                amount_base_units=1_000_000,
                nature=MovementNature.INCOME,
                tx_signature="sig-initial-valid-111111111111111111111",
                evidence_hash=VALID_HASH,
            )
            self.assertEqual(m.status, MovementStatus.PROVISIONAL)

            # In production, promotion using a known authority, 64-char hash, positive slot,
            # and a fictitious signature MUST be rejected and NOT pass to RECONCILED.
            with self.assertRaises(LedgerValidationError) as ctx:
                prod_ledger.reconcile_movement(
                    m.movement_id,
                    evidence_hash=VALID_HASH,
                    authorized_by=TRUSTED_RECONCILER,
                    slot=100,
                    tx_signature="fictitious_signature_12345678",
                )
            self.assertIn("disabled in production", str(ctx.exception).lower())

            # Movement status in DB must remain PROVISIONAL
            after_attempt = prod_ledger.get_movement(m.movement_id)
            self.assertEqual(after_attempt.status, MovementStatus.PROVISIONAL)

            # Reconciled balance remains 0
            bal = prod_ledger.get_balances(AGENT_1, token_mint=MINT_USDC)[0]
            self.assertEqual(bal.reconciled_balance, 0)
        finally:
            prod_ledger.close()

    def test_isolated_verifier_rejects_fictitious_signature(self):
        m = self.ledger.record_movement(
            idempotency_key="isolated-verifier-fictitious-test",
            agent_id="11" * 32,
            agent_account=AGENT_1,
            owner_pubkey=OWNER_1,
            network=NET_LOCALNET,
            genesis_hash=GENESIS_HASH,
            program_id=PROGRAM_ID,
            token_mint=MINT_USDC,
            amount_base_units=500_000,
            nature=MovementNature.INCOME,
            tx_signature="sig-initial-111111111111111111111111",
            evidence_hash=VALID_HASH,
        )
        with self.assertRaises(LedgerValidationError) as ctx:
            self.ledger.reconcile_movement(
                m.movement_id,
                evidence_hash=VALID_HASH,
                authorized_by=TRUSTED_RECONCILER,
                slot=100,
                tx_signature="fake_test_signature_99999",
            )
        self.assertIn("unverified or fictitious", str(ctx.exception).lower())

        stored = self.ledger.get_movement(m.movement_id)
        self.assertEqual(stored.status, MovementStatus.PROVISIONAL)

    # ─────────────────────────────────────────────────────────────────────────
    # 3. Versioned Migrations & Atomic Rollback Tests
    # ─────────────────────────────────────────────────────────────────────────

    def test_migration_001_to_002_upgrade_preserves_existing_data(self):
        temp_upgrade_dir = tempfile.TemporaryDirectory()
        db_file = Path(temp_upgrade_dir.name) / "upgrade_test.db"

        conn = sqlite3.connect(str(db_file), isolation_level=None)
        conn.row_factory = sqlite3.Row

        # Manually apply ONLY 001_initial_schema.sql
        migrations_dir = Path(__file__).resolve().parent / "migrations"
        m001_content = (migrations_dir / "001_initial_schema.sql").read_text(encoding="utf-8")

        for stmt in split_sql_statements(m001_content):
            conn.execute(stmt)

        conn.execute(
            "INSERT INTO schema_migrations (version, name, applied_at) VALUES (1, '001_initial_schema.sql', ?);",
            (int(time.time()),),
        )

        # Insert test records under 001 schema (INTEGER amount)
        now = int(time.time())
        conn.execute(
            """
            INSERT INTO journal_entries (
                journal_entry_id, idempotency_key, network, genesis_hash,
                program_id, token_mint, description, status, created_at, observed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            ("je_mig_1", "idemp_mig_1", NET_LOCALNET, GENESIS_HASH, PROGRAM_ID, MINT_USDC, "Pre-upgrade", "PROVISIONAL", now, now),
        )
        conn.execute(
            """
            INSERT INTO ledger_entries (
                entry_id, journal_entry_id, agent_account, account_name,
                entry_type, amount_base_units, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?);
            """,
            ("le_mig_1", "je_mig_1", AGENT_1, "ASSET:TREASURY", "DEBIT", 1234567, now),
        )
        conn.execute(
            """
            INSERT INTO economic_movements (
                movement_id, journal_entry_id, idempotency_key, agent_id,
                agent_account, owner_pubkey, network, genesis_hash, program_id,
                token_mint, amount_base_units, amount_str, nature, status,
                provenance_source, registered_at, observed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            ("mov_mig_1", "je_mig_1", "idemp_mig_1", "11" * 32, AGENT_1, OWNER_1, NET_LOCALNET, GENESIS_HASH, PROGRAM_ID, MINT_USDC, 1234567, "1234567", "INCOME", "PROVISIONAL", "ONCHAIN_VERIFIED", now, now),
        )

        # Execute migration runner to apply pending 002 migration
        newly_applied = run_migrations(conn)
        self.assertIn(2, newly_applied)

        # Verify existing record was preserved intact
        cursor = conn.execute("SELECT amount_base_units, amount_str FROM economic_movements WHERE movement_id = 'mov_mig_1';")
        row = cursor.fetchone()
        self.assertEqual(row["amount_base_units"], "1234567")
        self.assertEqual(row["amount_str"], "1234567")

        # Verify new schema allows u64 values (> 2^63 - 1) and zero amounts
        u64_max = 2**64 - 1
        conn.execute(
            """
            INSERT INTO journal_entries (
                journal_entry_id, idempotency_key, network, genesis_hash,
                program_id, token_mint, description, status, created_at, observed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            ("je_mig_2", "idemp_mig_2", NET_LOCALNET, GENESIS_HASH, PROGRAM_ID, MINT_USDC, "Post-upgrade", "PROVISIONAL", now, now),
        )
        conn.execute(
            """
            INSERT INTO economic_movements (
                movement_id, journal_entry_id, idempotency_key, agent_id,
                agent_account, owner_pubkey, network, genesis_hash, program_id,
                token_mint, amount_base_units, amount_str, nature, status,
                provenance_source, registered_at, observed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            ("mov_mig_2", "je_mig_2", "idemp_mig_2", "11" * 32, AGENT_1, OWNER_1, NET_LOCALNET, GENESIS_HASH, PROGRAM_ID, MINT_USDC, str(u64_max), str(u64_max), "INCOME", "PROVISIONAL", "ONCHAIN_VERIFIED", now, now),
        )

        row2 = conn.execute("SELECT amount_base_units FROM economic_movements WHERE movement_id = 'mov_mig_2';").fetchone()
        self.assertEqual(row2["amount_base_units"], "18446744073709551615")

        conn.close()
        temp_upgrade_dir.cleanup()

    def test_migration_001_to_002_with_reversals_and_self_referencing_movements(self):
        temp_dir = tempfile.TemporaryDirectory()
        db_file = Path(temp_dir.name) / "upgrade_fk_test.db"

        conn = sqlite3.connect(str(db_file), isolation_level=None)
        conn.row_factory = sqlite3.Row

        # 1. Manually apply 001_initial_schema.sql
        migrations_dir = Path(__file__).resolve().parent / "migrations"
        m001_content = (migrations_dir / "001_initial_schema.sql").read_text(encoding="utf-8")
        for stmt in split_sql_statements(m001_content):
            conn.execute(stmt)

        now = int(time.time())
        conn.execute(
            "INSERT INTO schema_migrations (version, name, applied_at) VALUES (1, '001_initial_schema.sql', ?);",
            (now,),
        )

        # 2. Insert records with foreign key relationships under 001:
        # Original movement
        conn.execute(
            """
            INSERT INTO journal_entries (
                journal_entry_id, idempotency_key, network, genesis_hash,
                program_id, token_mint, description, status, created_at, observed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            ("je_orig", "idemp_orig", NET_LOCALNET, GENESIS_HASH, PROGRAM_ID, MINT_USDC, "Original payment", "PROVISIONAL", now, now),
        )
        conn.execute(
            """
            INSERT INTO economic_movements (
                movement_id, journal_entry_id, idempotency_key, agent_id,
                agent_account, owner_pubkey, network, genesis_hash, program_id,
                token_mint, amount_base_units, amount_str, nature, status,
                provenance_source, registered_at, observed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            ("mov_orig", "je_orig", "idemp_orig", "11" * 32, AGENT_1, OWNER_1, NET_LOCALNET, GENESIS_HASH, PROGRAM_ID, MINT_USDC, 2000000, "2000000", "INCOME", "PROVISIONAL", "ONCHAIN_VERIFIED", now, now),
        )

        # Reversal movement referencing mov_orig
        conn.execute(
            """
            INSERT INTO journal_entries (
                journal_entry_id, idempotency_key, network, genesis_hash,
                program_id, token_mint, description, status, created_at, observed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            ("je_rev", "idemp_rev", NET_LOCALNET, GENESIS_HASH, PROGRAM_ID, MINT_USDC, "Reversal entry", "RECONCILED", now, now),
        )
        conn.execute(
            """
            INSERT INTO economic_movements (
                movement_id, journal_entry_id, idempotency_key, agent_id,
                agent_account, owner_pubkey, network, genesis_hash, program_id,
                token_mint, amount_base_units, amount_str, nature, status,
                provenance_source, registered_at, observed_at, reversal_of_movement_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            ("mov_rev", "je_rev", "idemp_rev", "11" * 32, AGENT_1, OWNER_1, NET_LOCALNET, GENESIS_HASH, PROGRAM_ID, MINT_USDC, 2000000, "2000000", "ADJUSTMENT", "RECONCILED", "ONCHAIN_VERIFIED", now, now, "mov_orig"),
        )

        # Chained movement referencing mov_rev
        conn.execute(
            """
            INSERT INTO journal_entries (
                journal_entry_id, idempotency_key, network, genesis_hash,
                program_id, token_mint, description, status, created_at, observed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            ("je_chain", "idemp_chain", NET_LOCALNET, GENESIS_HASH, PROGRAM_ID, MINT_USDC, "Chained adjustment", "RECONCILED", now, now),
        )
        conn.execute(
            """
            INSERT INTO economic_movements (
                movement_id, journal_entry_id, idempotency_key, agent_id,
                agent_account, owner_pubkey, network, genesis_hash, program_id,
                token_mint, amount_base_units, amount_str, nature, status,
                provenance_source, registered_at, observed_at, reversal_of_movement_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            ("mov_chain", "je_chain", "idemp_chain", "11" * 32, AGENT_1, OWNER_1, NET_LOCALNET, GENESIS_HASH, PROGRAM_ID, MINT_USDC, 1000000, "1000000", "ADJUSTMENT", "RECONCILED", "ONCHAIN_VERIFIED", now, now, "mov_rev"),
        )

        # 3. Run migration runner to upgrade from 001 to 002
        newly_applied = run_migrations(conn)
        self.assertIn(2, newly_applied)

        # 4. Verify all records exist and relationships are preserved
        rows = {
            r["movement_id"]: r
            for r in conn.execute(
                "SELECT movement_id, amount_base_units, reversal_of_movement_id FROM economic_movements;"
            ).fetchall()
        }
        self.assertIn("mov_orig", rows)
        self.assertIn("mov_rev", rows)
        self.assertIn("mov_chain", rows)

        self.assertEqual(rows["mov_rev"]["reversal_of_movement_id"], "mov_orig")
        self.assertEqual(rows["mov_chain"]["reversal_of_movement_id"], "mov_rev")
        self.assertEqual(rows["mov_orig"]["amount_base_units"], "2000000")

        # 5. Verify PRAGMA foreign_keys is ON after migration by testing constraint enforcement
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO economic_movements (
                    movement_id, journal_entry_id, idempotency_key, agent_id,
                    agent_account, owner_pubkey, network, genesis_hash, program_id,
                    token_mint, amount_base_units, amount_str, nature, status,
                    provenance_source, registered_at, observed_at, reversal_of_movement_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                ("mov_bad_fk", "je_orig", "idemp_bad_fk", "11" * 32, AGENT_1, OWNER_1, NET_LOCALNET, GENESIS_HASH, PROGRAM_ID, MINT_USDC, "1000", "1000", "ADJUSTMENT", "RECONCILED", "ONCHAIN_VERIFIED", now, now, "non_existent_movement_id"),
            )

        conn.close()
        temp_dir.cleanup()

    def test_migration_failure_rolls_back_on_foreign_key_violation(self):
        temp_dir = tempfile.TemporaryDirectory()
        db_file = Path(temp_dir.name) / "rollback_fk_test.db"
        conn = sqlite3.connect(str(db_file), isolation_level=None)
        conn.row_factory = sqlite3.Row

        # Apply standard migrations
        run_migrations(conn)

        # Create a mock migration that violates foreign keys
        failing_sql = """
        CREATE TABLE dummy_fk_test (
            id TEXT PRIMARY KEY,
            movement_id TEXT REFERENCES economic_movements(movement_id)
        );
        INSERT INTO dummy_fk_test (id, movement_id) VALUES ('1', 'non_existent_movement_12345');
        """
        temp_mig_dir = Path(temp_dir.name) / "fake_migrations"
        temp_mig_dir.mkdir(parents=True, exist_ok=True)
        (temp_mig_dir / "006_fk_violation_migration.sql").write_text(failing_sql, encoding="utf-8")

        with patch("tools.economic_ledger.schema.MIGRATIONS_DIR", temp_mig_dir):
            with self.assertRaises(MigrationError) as ctx:
                run_migrations(conn)
            self.assertIn("Foreign key constraint violation", str(ctx.exception))

        # Check atomic rollback: dummy_fk_test must not exist
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='dummy_fk_test';"
        )
        self.assertIsNone(cursor.fetchone())

        # Version 6 must not be applied
        cursor = conn.execute("SELECT version FROM schema_migrations WHERE version = 6;")
        self.assertIsNone(cursor.fetchone())

        conn.close()
        temp_dir.cleanup()

    def test_migration_failure_rolls_back_atomically(self):
        temp_dir = tempfile.TemporaryDirectory()
        db_file = Path(temp_dir.name) / "rollback_test.db"
        conn = sqlite3.connect(str(db_file), isolation_level=None)
        conn.row_factory = sqlite3.Row

        # Apply standard migrations
        run_migrations(conn)

        # Create a mock failing migration in a temporary directory
        failing_sql = """
        -- Statement 1: succeeds
        CREATE TABLE should_be_rolled_back (id TEXT PRIMARY KEY);
        -- Statement 2: intentional syntax error that fails
        SYNTAX ERROR INVALID SQL HERE;
        """
        temp_mig_dir = Path(temp_dir.name) / "fake_migrations"
        temp_mig_dir.mkdir(parents=True, exist_ok=True)
        (temp_mig_dir / "006_failing_migration.sql").write_text(failing_sql, encoding="utf-8")

        with patch("tools.economic_ledger.schema.MIGRATIONS_DIR", temp_mig_dir):
            with self.assertRaises(MigrationError):
                run_migrations(conn)

        # Atomic rollback verification: Statement 1 must NOT exist in the database
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='should_be_rolled_back';"
        )
        self.assertIsNone(cursor.fetchone())

        # Version 6 must NOT be in schema_migrations
        cursor = conn.execute("SELECT version FROM schema_migrations WHERE version = 6;")
        self.assertIsNone(cursor.fetchone())

        conn.close()
        temp_dir.cleanup()

    # ─────────────────────────────────────────────────────────────────────────
    # 4. Concurrency & Contrasientos
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
                            status=MovementStatus.PROVISIONAL,
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

        movements, _ = self.ledger.list_movements(AGENT_1, limit=200)
        self.assertEqual(len(movements), num_threads * movements_per_thread)

        balances = self.ledger.get_balances(AGENT_1, network=NET_LOCALNET, token_mint=MINT_USDC)
        self.assertEqual(len(balances), 1)
        self.assertEqual(balances[0].provisional_balance, 8_000_000)

    def test_revert_movement_emits_balanced_contrasiento(self):
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
            status=MovementStatus.PROVISIONAL,
            tx_signature="sig-to-revert-sample-tx-11111111111111",
            evidence_hash=VALID_HASH,
        )

        # Reconcile movement first
        self.ledger.reconcile_movement(
            m.movement_id,
            evidence_hash=VALID_HASH,
            authorized_by=TRUSTED_RECONCILER,
            slot=104920,
            tx_signature="sig-to-revert-sample-tx-11111111111111",
        )

        totals_before = self.ledger.get_ledger_totals()
        self.assertTrue(totals_before["is_balanced"])
        self.assertEqual(totals_before["total_debit"], 1_500_000)
        self.assertEqual(totals_before["total_credit"], 1_500_000)

        # Revert movement: emits balanced contrasiento
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

        # Check invariant
        totals_after = self.ledger.get_ledger_totals()
        self.assertTrue(totals_after["is_balanced"])
        self.assertEqual(totals_after["total_debit"], 3_000_000)
        self.assertEqual(totals_after["total_credit"], 3_000_000)

        bal = self.ledger.get_balances(AGENT_1, token_mint=MINT_USDC)[0]
        self.assertEqual(bal.reconciled_balance, 0)
        self.assertEqual(bal.total_effective_balance, 0)

    # ─────────────────────────────────────────────────────────────────────────
    # 5. Zero-Payout Settlement Audit & u64 Boundary Tests
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

        self.assertEqual(rejected_movement.amount_base_units, 0)
        self.assertEqual(rejected_movement.amount_str, "0")
        self.assertEqual(rejected_movement.metadata["operator_payout"], 0)
        self.assertEqual(rejected_movement.metadata["creator_refund"], 10_000_000)

        totals = self.ledger.get_ledger_totals()
        self.assertTrue(totals["is_balanced"])

    def test_u64_monetary_exactness_at_boundary_limits(self):
        LIM_SIGNED_64 = 2**63 - 1
        LIM_POW_63 = 2**63
        U64_MAX = 2**64 - 1

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
            tx_signature="sig-lim1",
        )
        self.assertEqual(m1.amount_base_units, LIM_SIGNED_64)

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
            tx_signature="sig-lim2",
        )
        self.assertEqual(m2.amount_base_units, LIM_POW_63)

        expected_sum_1_2 = LIM_SIGNED_64 + LIM_POW_63
        bal = self.ledger.get_balances(AGENT_1, token_mint=MINT_USDC)[0]
        self.assertEqual(bal.provisional_balance, expected_sum_1_2)
        self.assertEqual(bal.provisional_balance_str, str(expected_sum_1_2))

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
            tx_signature="sig-max",
        )
        self.assertEqual(m_max.amount_base_units, U64_MAX)

        bal2 = self.ledger.get_balances(AGENT_2, token_mint=MINT_USDC)[0]
        self.assertEqual(bal2.provisional_balance, U64_MAX)
        self.assertEqual(bal2.provisional_balance_str, "18446744073709551615")
        self.assertTrue(bal2.provisional_balance_str.endswith("15"))

    def test_strict_isolation_across_networks_and_mints(self):
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
            tx_signature="sig-m1",
        )

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
            tx_signature="sig-m2",
        )

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
            tx_signature="sig-m3",
        )

        balances = self.ledger.get_balances(AGENT_1)
        self.assertEqual(len(balances), 3)

        b_local_usdc = next(b for b in balances if b.network == NET_LOCALNET and b.token_mint == MINT_USDC)
        b_local_test = next(b for b in balances if b.network == NET_LOCALNET and b.token_mint == MINT_TEST)
        b_main_usdc = next(b for b in balances if b.network == NET_MAINNET and b.token_mint == MINT_USDC)

        self.assertEqual(b_local_usdc.provisional_balance, 1_000_000)
        self.assertEqual(b_local_test.provisional_balance, 999_999)
        self.assertEqual(b_main_usdc.provisional_balance, 500_000)

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
