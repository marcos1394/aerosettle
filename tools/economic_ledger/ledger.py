"""Core persistent economic ledger engine with balanced double-entry accounting."""
from __future__ import annotations

import base64
import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from .models import (
    BalanceReport,
    EconomicMovement,
    EntryType,
    IdempotencyConflictError,
    JournalEntry,
    LedgerLeg,
    LedgerValidationError,
    MovementNature,
    MovementStatus,
    ProvenanceSource,
    validate_base_units,
)
from .schema import run_migrations

DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / ".aerosettle-local" / "economic_ledger.db"


class ExactSum:
    """Custom SQLite aggregate ensuring arbitrary-precision integer accumulation without float drift."""

    def __init__(self) -> None:
        self.total = 0

    def step(self, value: Any) -> None:
        if value is not None:
            self.total += int(value)

    def finalize(self) -> str:
        return str(self.total)


def _check_idempotency_match(
    existing: EconomicMovement,
    *,
    agent_account: str,
    amount_base_units: int,
    token_mint: str,
    nature: MovementNature,
    network: str,
    owner_pubkey: str,
    work_order_account: Optional[str],
) -> None:
    """Verifies that a reused idempotency key exactly matches all essential event fields."""
    mismatches: list[str] = []
    if existing.agent_account != agent_account:
        mismatches.append(f"agent_account ({existing.agent_account} != {agent_account})")
    if existing.amount_base_units != amount_base_units:
        mismatches.append(f"amount_base_units ({existing.amount_base_units} != {amount_base_units})")
    if existing.token_mint != token_mint:
        mismatches.append(f"token_mint ({existing.token_mint} != {token_mint})")
    if existing.nature != nature:
        mismatches.append(f"nature ({existing.nature.value} != {nature.value})")
    if existing.network != network:
        mismatches.append(f"network ({existing.network} != {network})")
    if existing.owner_pubkey != owner_pubkey:
        mismatches.append(f"owner_pubkey ({existing.owner_pubkey} != {owner_pubkey})")
    if (existing.work_order_account or None) != (work_order_account or None):
        mismatches.append(f"work_order_account ({existing.work_order_account} != {work_order_account})")

    if mismatches:
        raise IdempotencyConflictError(
            f"Idempotency conflict for key '{existing.idempotency_key}': "
            f"existing record differs in {', '.join(mismatches)}"
        )


class EconomicLedger:
    """ACID-compliant, thread-safe persistent economic ledger for Conatus/AeroSettle agents."""

    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH):
        if str(db_path) != ":memory:":
            self.db_path = Path(db_path)
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._path_str = str(self.db_path)
        else:
            self.db_path = None
            self._path_str = ":memory:"

        self._conn = sqlite3.connect(
            self._path_str,
            timeout=15.0,
            check_same_thread=False,
            isolation_level=None,  # Autocommit mode; we manage explicit BEGIN / COMMIT
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON;")
        if self._path_str != ":memory:":
            self._conn.execute("PRAGMA journal_mode = WAL;")
        self._conn.execute("PRAGMA busy_timeout = 10000;")

        # Register custom exact aggregate to avoid float conversions in SQLite
        self._conn.create_aggregate("exact_sum", 1, ExactSum)

        # Run versioned schema migrations
        run_migrations(self._conn)

    def close(self) -> None:
        if self._conn:
            self._conn.close()

    def __enter__(self) -> EconomicLedger:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    # ─────────────────────────────────────────────────────────────────────────
    # Movement Ingestion & Record
    # ─────────────────────────────────────────────────────────────────────────

    def record_movement(
        self,
        *,
        idempotency_key: str,
        agent_id: str,
        agent_account: str,
        owner_pubkey: str,
        network: str,
        genesis_hash: str,
        program_id: str,
        token_mint: str,
        amount_base_units: int | str,
        nature: MovementNature | str,
        status: MovementStatus | str = MovementStatus.PROVISIONAL,
        provenance_source: ProvenanceSource | str = ProvenanceSource.ONCHAIN_VERIFIED,
        work_order_account: Optional[str] = None,
        work_order_id: Optional[str] = None,
        evidence_hash: Optional[str] = None,
        attestation_id: Optional[str] = None,
        tx_signature: Optional[str] = None,
        external_ref: Optional[str] = None,
        observed_at: Optional[int] = None,
        reversal_of_movement_id: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
        custom_journal_legs: Optional[list[dict[str, Any]]] = None,
    ) -> EconomicMovement:
        """Idempotently records an economic movement with balanced double-entry accounting."""
        if not idempotency_key or not idempotency_key.strip():
            raise LedgerValidationError("idempotency_key cannot be empty")

        clean_idempotency_key = idempotency_key.strip()
        nature_enum = MovementNature(nature)
        status_enum = MovementStatus(status)
        source_enum = ProvenanceSource(provenance_source)

        # Monetary validation: allow zero base units for non-disbursement audit entries
        allow_zero = (amount_base_units == 0 or str(amount_base_units) == "0")
        amount_int = validate_base_units(amount_base_units, allow_zero=allow_zero)
        amount_str = str(amount_int)

        # Reconciliation Guard: MANUAL_ENTRY cannot directly set RECONCILED or REVERTED
        if source_enum == ProvenanceSource.MANUAL_ENTRY and status_enum != MovementStatus.PROVISIONAL:
            raise LedgerValidationError(
                "MANUAL_ENTRY movements cannot be recorded directly as RECONCILED; "
                "they must be initiated in PROVISIONAL status."
            )

        # On-chain Guard: ONCHAIN_VERIFIED must be backed by evidence
        if source_enum == ProvenanceSource.ONCHAIN_VERIFIED and not (
            tx_signature or attestation_id or evidence_hash or work_order_account
        ):
            raise LedgerValidationError(
                "ONCHAIN_VERIFIED requires verifiable on-chain evidence (tx_signature, attestation_id, or evidence_hash)"
            )

        # Check existing by idempotency_key first (Fast Read with Semantic Matching)
        existing = self.get_by_idempotency_key(clean_idempotency_key)
        if existing:
            _check_idempotency_match(
                existing,
                agent_account=agent_account,
                amount_base_units=amount_int,
                token_mint=token_mint,
                nature=nature_enum,
                network=network,
                owner_pubkey=owner_pubkey,
                work_order_account=work_order_account,
            )
            return existing

        now = int(time.time())
        obs_time = observed_at if observed_at is not None else now
        movement_id = str(uuid.uuid4())
        journal_entry_id = f"je_{movement_id}"
        meta = metadata or {}

        # Prepare double-entry legs
        legs: list[LedgerLeg] = []
        if custom_journal_legs is not None and len(custom_journal_legs) > 0:
            for leg_dict in custom_journal_legs:
                leg_amt = validate_base_units(leg_dict["amount_base_units"], allow_zero=True)
                leg_type = EntryType(leg_dict["entry_type"])
                legs.append(
                    LedgerLeg(
                        entry_id=str(uuid.uuid4()),
                        journal_entry_id=journal_entry_id,
                        account_name=leg_dict["account_name"],
                        entry_type=leg_type,
                        amount_base_units=leg_amt,
                        agent_account=leg_dict.get("agent_account", agent_account),
                        created_at=now,
                    )
                )
        else:
            # Generate default balanced double-entry legs based on movement nature
            legs = self._generate_default_legs(
                journal_entry_id=journal_entry_id,
                agent_account=agent_account,
                nature=nature_enum,
                amount_base_units=amount_int,
                created_at=now,
                is_compensating=reversal_of_movement_id is not None,
            )

        # Invariant: Debits == Credits
        self._assert_balanced_legs(legs)

        # Atomic Transaction
        cursor = self._conn.cursor()
        try:
            cursor.execute("BEGIN IMMEDIATE;")

            # Secondary concurrency check inside lock
            cursor.execute(
                "SELECT movement_id FROM economic_movements WHERE idempotency_key = ?;",
                (clean_idempotency_key,),
            )
            row = cursor.fetchone()
            if row:
                cursor.execute("ROLLBACK;")
                locked_existing = self.get_movement(row["movement_id"])
                if locked_existing:
                    _check_idempotency_match(
                        locked_existing,
                        agent_account=agent_account,
                        amount_base_units=amount_int,
                        token_mint=token_mint,
                        nature=nature_enum,
                        network=network,
                        owner_pubkey=owner_pubkey,
                        work_order_account=work_order_account,
                    )
                    return locked_existing

            # 1. Insert journal entry
            cursor.execute(
                """
                INSERT INTO journal_entries (
                    journal_entry_id, idempotency_key, network, genesis_hash,
                    program_id, token_mint, description, tx_signature,
                    work_order_account, status, created_at, observed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    journal_entry_id,
                    clean_idempotency_key,
                    network,
                    genesis_hash,
                    program_id,
                    token_mint,
                    f"Movement {nature_enum.value} for {agent_account}",
                    tx_signature,
                    work_order_account,
                    status_enum.value,
                    now,
                    obs_time,
                ),
            )

            # 2. Insert ledger legs (stored as string representation of integer to prevent u64 float loss)
            for leg in legs:
                cursor.execute(
                    """
                    INSERT INTO ledger_entries (
                        entry_id, journal_entry_id, agent_account, account_name,
                        entry_type, amount_base_units, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        leg.entry_id,
                        leg.journal_entry_id,
                        leg.agent_account,
                        leg.account_name,
                        leg.entry_type.value,
                        str(leg.amount_base_units),
                        leg.created_at,
                    ),
                )

            # 3. Insert economic movement
            cursor.execute(
                """
                INSERT INTO economic_movements (
                    movement_id, journal_entry_id, idempotency_key, agent_id,
                    agent_account, owner_pubkey, work_order_account, work_order_id,
                    network, genesis_hash, program_id, token_mint,
                    amount_base_units, amount_str, nature, status,
                    provenance_source, evidence_hash, attestation_id,
                    tx_signature, external_ref, registered_at, observed_at,
                    reversal_of_movement_id, metadata_json
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                );
                """,
                (
                    movement_id,
                    journal_entry_id,
                    clean_idempotency_key,
                    agent_id,
                    agent_account,
                    owner_pubkey,
                    work_order_account,
                    work_order_id,
                    network,
                    genesis_hash,
                    program_id,
                    token_mint,
                    amount_str,
                    amount_str,
                    nature_enum.value,
                    status_enum.value,
                    source_enum.value,
                    evidence_hash,
                    attestation_id,
                    tx_signature,
                    external_ref,
                    now,
                    obs_time,
                    reversal_of_movement_id,
                    json.dumps(meta),
                ),
            )

            cursor.execute("COMMIT;")
        except sqlite3.IntegrityError as exc:
            try:
                cursor.execute("ROLLBACK;")
            except Exception:
                pass
            existing = self.get_by_idempotency_key(clean_idempotency_key)
            if existing:
                _check_idempotency_match(
                    existing,
                    agent_account=agent_account,
                    amount_base_units=amount_int,
                    token_mint=token_mint,
                    nature=nature_enum,
                    network=network,
                    owner_pubkey=owner_pubkey,
                    work_order_account=work_order_account,
                )
                return existing
            raise LedgerValidationError(f"Integrity violation: {exc}") from exc
        except Exception:
            try:
                cursor.execute("ROLLBACK;")
            except Exception:
                pass
            raise

        created = self.get_movement(movement_id)
        if created is None:
            raise RuntimeError(f"Failed to retrieve recorded movement {movement_id}")
        return created

    # ─────────────────────────────────────────────────────────────────────────
    # Reconciliation Transition (Internal Authorized Evidence)
    # ─────────────────────────────────────────────────────────────────────────

    def reconcile_movement(
        self,
        movement_id: str,
        *,
        evidence_hash: str,
        authorized_by: str,
        slot: Optional[int] = None,
        tx_signature: Optional[str] = None,
    ) -> EconomicMovement:
        """Transitions a PROVISIONAL movement to RECONCILED with authorized cryptographic evidence."""
        if not evidence_hash or not evidence_hash.strip():
            raise LedgerValidationError("evidence_hash is required for reconciliation")
        if not authorized_by or not authorized_by.strip():
            raise LedgerValidationError("authorized_by is required for reconciliation")

        cursor = self._conn.cursor()
        try:
            cursor.execute("BEGIN IMMEDIATE;")
            cursor.execute(
                "SELECT * FROM economic_movements WHERE movement_id = ?;",
                (movement_id,),
            )
            row = cursor.fetchone()
            if not row:
                raise LedgerValidationError(f"Movement not found: {movement_id}")

            current_status = row["status"]
            if current_status == MovementStatus.RECONCILED.value:
                cursor.execute("COMMIT;")
                return self._row_to_movement(row)
            if current_status == MovementStatus.REVERTED.value:
                raise LedgerValidationError(f"Cannot reconcile a REVERTED movement: {movement_id}")
            if current_status != MovementStatus.PROVISIONAL.value:
                raise LedgerValidationError(
                    f"Only PROVISIONAL movements can be reconciled, got {current_status}"
                )

            now = int(time.time())
            meta = json.loads(row["metadata_json"]) if row["metadata_json"] else {}
            meta["reconciliation"] = {
                "reconciled_at": now,
                "authorized_by": authorized_by.strip(),
                "evidence_hash": evidence_hash.strip(),
                "slot": slot,
                "tx_signature": tx_signature,
            }

            cursor.execute(
                """
                UPDATE economic_movements
                SET status = ?, evidence_hash = ?, tx_signature = COALESCE(?, tx_signature), metadata_json = ?
                WHERE movement_id = ?;
                """,
                (
                    MovementStatus.RECONCILED.value,
                    evidence_hash.strip(),
                    tx_signature,
                    json.dumps(meta),
                    movement_id,
                ),
            )

            if row["journal_entry_id"]:
                cursor.execute(
                    """
                    UPDATE journal_entries
                    SET status = ?, tx_signature = COALESCE(?, tx_signature)
                    WHERE journal_entry_id = ?;
                    """,
                    (
                        MovementStatus.RECONCILED.value,
                        tx_signature,
                        row["journal_entry_id"],
                    ),
                )

            cursor.execute("COMMIT;")
        except Exception:
            try:
                cursor.execute("ROLLBACK;")
            except Exception:
                pass
            raise

        updated = self.get_movement(movement_id)
        if not updated:
            raise RuntimeError(f"Failed to load reconciled movement {movement_id}")
        return updated

    # ─────────────────────────────────────────────────────────────────────────
    # Settlement Integration (Exact Operator Payouts & Zero-Disbursement Audits)
    # ─────────────────────────────────────────────────────────────────────────

    def record_settlement(
        self,
        *,
        work_order_account: str,
        work_order_data: dict[str, Any],
        agent_account: str,
        owner_pubkey: str,
        agent_id: str,
        network: str,
        genesis_hash: str,
        program_id: str,
        token_mint: str,
        tx_signature: Optional[str] = None,
        observed_at: Optional[int] = None,
        is_reconciled: bool = False,
    ) -> EconomicMovement:
        """Records an economic movement resulting from an on-chain work order settlement.

        CRITICAL GUARDS:
        1. Does NOT assume total_amount is agent income: computes exact operator payout.
        2. Non-disbursement (0 payout) settlements are recorded as 0-unit audit movements,
           completely eliminating symbolic 1 base unit workarounds.
        """
        total_amount = validate_base_units(work_order_data.get("total_amount", 0), allow_zero=True)
        verification_status = work_order_data.get("verification_status")
        completion_bps = int(work_order_data.get("completion_bps", 0))
        payment_model = work_order_data.get("payment_model", "Fixed")
        work_order_id = work_order_data.get("work_order_id")

        operator_payout = self._calculate_verified_payout(
            payment_model=payment_model,
            verification_status=verification_status,
            total_amount=total_amount,
            completion_bps=completion_bps,
        )

        creator_refund = total_amount - operator_payout
        status = MovementStatus.RECONCILED if is_reconciled else MovementStatus.PROVISIONAL
        attestation_hash = work_order_data.get("verification_attestation_hash")
        idempotency_key = f"settlement:{work_order_account}:{tx_signature or 'payout'}"

        if operator_payout == 0:
            meta = {
                "event": "settlement_zero_payout",
                "total_escrow_funded": total_amount,
                "creator_refund": creator_refund,
                "operator_payout": 0,
                "verification_status": verification_status,
                "completion_bps": completion_bps,
                "payment_model": payment_model,
                "audit_note": "Zero-payout settlement audit entry (rejected or zero-completion)",
            }
            return self.record_movement(
                idempotency_key=idempotency_key,
                agent_id=agent_id,
                agent_account=agent_account,
                owner_pubkey=owner_pubkey,
                network=network,
                genesis_hash=genesis_hash,
                program_id=program_id,
                token_mint=token_mint,
                amount_base_units=0,  # Exact 0 base units without distortion
                nature=MovementNature.ADJUSTMENT,
                status=status,
                provenance_source=ProvenanceSource.SETTLEMENT_EVENT,
                work_order_account=work_order_account,
                work_order_id=work_order_id,
                evidence_hash=attestation_hash,
                tx_signature=tx_signature,
                observed_at=observed_at,
                metadata=meta,
            )

        meta = {
            "event": "settlement_payout",
            "total_escrow_funded": total_amount,
            "creator_refund": creator_refund,
            "operator_payout": operator_payout,
            "verification_status": verification_status,
            "completion_bps": completion_bps,
            "payment_model": payment_model,
            "conatus_epic": "CON-22",
        }

        return self.record_movement(
            idempotency_key=idempotency_key,
            agent_id=agent_id,
            agent_account=agent_account,
            owner_pubkey=owner_pubkey,
            network=network,
            genesis_hash=genesis_hash,
            program_id=program_id,
            token_mint=token_mint,
            amount_base_units=operator_payout,
            nature=MovementNature.INCOME,
            status=status,
            provenance_source=ProvenanceSource.SETTLEMENT_EVENT,
            work_order_account=work_order_account,
            work_order_id=work_order_id,
            evidence_hash=attestation_hash,
            tx_signature=tx_signature,
            observed_at=observed_at,
            metadata=meta,
        )

    @staticmethod
    def _calculate_verified_payout(
        *,
        payment_model: str,
        verification_status: Optional[str],
        total_amount: int,
        completion_bps: int,
    ) -> int:
        if completion_bps > 10000:
            raise LedgerValidationError(f"Invalid completion_bps > 10000: {completion_bps}")

        if verification_status != "Accepted":
            return 0

        if payment_model == "Fixed":
            return total_amount if completion_bps == 10000 else 0
        elif payment_model == "Proportional":
            return (total_amount * completion_bps) // 10000
        else:
            raise LedgerValidationError(f"Unsupported payment_model: {payment_model}")

    # ─────────────────────────────────────────────────────────────────────────
    # Compensating Movements & Contrasientos (Append-Only Reversals)
    # ─────────────────────────────────────────────────────────────────────────

    def revert_movement(
        self,
        movement_id: str,
        *,
        reason: str,
        authorized_by: str,
    ) -> tuple[EconomicMovement, EconomicMovement]:
        """Atomically marks a movement as REVERTED and generates a balanced contrasiento (reversal entry).

        Strict append-only double-entry guarantee:
        1. Original movement status transitions to REVERTED.
        2. A formal compensating journal entry is inserted into journal_entries.
        3. Symmetrical inverse ledger legs (DEBIT <-> CREDIT) are inserted into ledger_entries,
           preserving the fundamental accounting invariant: sum(debit) == sum(credit).
        4. A compensating economic_movement is recorded referencing the original movement.
        """
        if not reason or not reason.strip():
            raise LedgerValidationError("Reversal reason is mandatory")
        if not authorized_by or not authorized_by.strip():
            raise LedgerValidationError("authorized_by is mandatory")

        cursor = self._conn.cursor()
        try:
            cursor.execute("BEGIN IMMEDIATE;")
            cursor.execute(
                "SELECT * FROM economic_movements WHERE movement_id = ?;",
                (movement_id,),
            )
            row = cursor.fetchone()
            if not row:
                raise LedgerValidationError(f"Movement not found: {movement_id}")

            if row["status"] == MovementStatus.REVERTED.value:
                raise LedgerValidationError(f"Movement {movement_id} is already reverted")

            now = int(time.time())
            amount_int = int(row["amount_base_units"])
            amount_str = str(row["amount_str"])

            # 1. Update original movement status to REVERTED
            cursor.execute(
                "UPDATE economic_movements SET status = ? WHERE movement_id = ?;",
                (MovementStatus.REVERTED.value, movement_id),
            )

            # 2. Build contrasiento journal entry and symmetrical inverse legs
            comp_movement_id = str(uuid.uuid4())
            comp_journal_id = f"je_rev_{comp_movement_id}"
            comp_idempotency = f"reversal:{movement_id}:{comp_movement_id}"

            reversal_legs: list[LedgerLeg] = []
            orig_journal_id = row["journal_entry_id"]

            if orig_journal_id:
                cursor.execute(
                    """
                    SELECT * FROM ledger_entries
                    WHERE journal_entry_id = ?
                    ORDER BY entry_id ASC;
                    """,
                    (orig_journal_id,),
                )
                orig_legs = cursor.fetchall()
                for leg in orig_legs:
                    # Invert DEBIT <-> CREDIT
                    inverted_type = (
                        EntryType.CREDIT
                        if leg["entry_type"] == EntryType.DEBIT.value
                        else EntryType.DEBIT
                    )
                    reversal_legs.append(
                        LedgerLeg(
                            entry_id=str(uuid.uuid4()),
                            journal_entry_id=comp_journal_id,
                            account_name=leg["account_name"],
                            entry_type=inverted_type,
                            amount_base_units=int(leg["amount_base_units"]),
                            agent_account=leg["agent_account"],
                            created_at=now,
                        )
                    )

            if not reversal_legs:
                # Fallback if no prior journal entry: generate inverted default legs
                default_legs = self._generate_default_legs(
                    journal_entry_id=comp_journal_id,
                    agent_account=row["agent_account"],
                    nature=MovementNature(row["nature"]),
                    amount_base_units=amount_int,
                    created_at=now,
                    is_compensating=True,
                )
                for leg in default_legs:
                    inverted_type = (
                        EntryType.CREDIT if leg.entry_type == EntryType.DEBIT else EntryType.DEBIT
                    )
                    reversal_legs.append(
                        LedgerLeg(
                            entry_id=leg.entry_id,
                            journal_entry_id=leg.journal_entry_id,
                            account_name=leg.account_name,
                            entry_type=inverted_type,
                            amount_base_units=leg.amount_base_units,
                            agent_account=leg.agent_account,
                            created_at=leg.created_at,
                        )
                    )

            # Verify contrasiento balance invariant
            self._assert_balanced_legs(reversal_legs)

            # 3. Insert contrasiento journal entry
            cursor.execute(
                """
                INSERT INTO journal_entries (
                    journal_entry_id, idempotency_key, network, genesis_hash,
                    program_id, token_mint, description, tx_signature,
                    work_order_account, status, created_at, observed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    comp_journal_id,
                    comp_idempotency,
                    row["network"],
                    row["genesis_hash"],
                    row["program_id"],
                    row["token_mint"],
                    f"Contrasiento / Reversal of movement {movement_id}: {reason.strip()}",
                    row["tx_signature"],
                    row["work_order_account"],
                    MovementStatus.RECONCILED.value,
                    now,
                    now,
                ),
            )

            # 4. Insert inverse ledger legs
            for leg in reversal_legs:
                cursor.execute(
                    """
                    INSERT INTO ledger_entries (
                        entry_id, journal_entry_id, agent_account, account_name,
                        entry_type, amount_base_units, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        leg.entry_id,
                        leg.journal_entry_id,
                        leg.agent_account,
                        leg.account_name,
                        leg.entry_type.value,
                        str(leg.amount_base_units),
                        leg.created_at,
                    ),
                )

            # 5. Insert compensating economic movement
            comp_meta = {
                "reversal_of_movement_id": movement_id,
                "reversal_reason": reason.strip(),
                "authorized_by": authorized_by.strip(),
                "original_nature": row["nature"],
                "original_amount": str(amount_int),
                "is_contrasiento": True,
            }

            cursor.execute(
                """
                INSERT INTO economic_movements (
                    movement_id, journal_entry_id, idempotency_key, agent_id,
                    agent_account, owner_pubkey, work_order_account, work_order_id,
                    network, genesis_hash, program_id, token_mint,
                    amount_base_units, amount_str, nature, status,
                    provenance_source, evidence_hash, attestation_id,
                    tx_signature, external_ref, registered_at, observed_at,
                    reversal_of_movement_id, metadata_json
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                );
                """,
                (
                    comp_movement_id,
                    comp_journal_id,
                    comp_idempotency,
                    row["agent_id"],
                    row["agent_account"],
                    row["owner_pubkey"],
                    row["work_order_account"],
                    row["work_order_id"],
                    row["network"],
                    row["genesis_hash"],
                    row["program_id"],
                    row["token_mint"],
                    amount_str,
                    amount_str,
                    MovementNature.ADJUSTMENT.value,
                    MovementStatus.RECONCILED.value,
                    ProvenanceSource.MANUAL_ENTRY.value,
                    None,
                    None,
                    row["tx_signature"],
                    f"comp-rev:{movement_id}",
                    now,
                    now,
                    movement_id,
                    json.dumps(comp_meta),
                ),
            )

            cursor.execute("COMMIT;")
        except Exception:
            try:
                cursor.execute("ROLLBACK;")
            except Exception:
                pass
            raise

        reverted_orig = self.get_movement(movement_id)
        compensating = self.get_movement(comp_movement_id)
        return reverted_orig, compensating  # type: ignore

    # ─────────────────────────────────────────────────────────────────────────
    # Lookups & Balances (Strict Isolation per Network & Mint + u64 Exactness)
    # ─────────────────────────────────────────────────────────────────────────

    def get_movement(self, movement_id: str) -> Optional[EconomicMovement]:
        cursor = self._conn.execute(
            "SELECT * FROM economic_movements WHERE movement_id = ?;",
            (movement_id,),
        )
        row = cursor.fetchone()
        return self._row_to_movement(row) if row else None

    def get_by_idempotency_key(self, idempotency_key: str) -> Optional[EconomicMovement]:
        cursor = self._conn.execute(
            "SELECT * FROM economic_movements WHERE idempotency_key = ?;",
            (idempotency_key,),
        )
        row = cursor.fetchone()
        return self._row_to_movement(row) if row else None

    def list_movements(
        self,
        agent_account: str,
        *,
        nature: Optional[str] = None,
        status: Optional[str] = None,
        token_mint: Optional[str] = None,
        network: Optional[str] = None,
        from_ts: Optional[int] = None,
        to_ts: Optional[int] = None,
        limit: int = 50,
        cursor: Optional[str] = None,
    ) -> tuple[list[EconomicMovement], Optional[str]]:
        """Queries movements for an agent with filters and deterministic cursor pagination."""
        if limit <= 0 or limit > 200:
            raise LedgerValidationError("limit must be between 1 and 200")

        conditions = ["agent_account = ?"]
        params: list[Any] = [agent_account]

        if nature:
            conditions.append("nature = ?")
            params.append(MovementNature(nature).value)

        if status:
            conditions.append("status = ?")
            params.append(MovementStatus(status).value)

        if token_mint:
            conditions.append("token_mint = ?")
            params.append(token_mint)

        if network:
            conditions.append("network = ?")
            params.append(network)

        if from_ts is not None:
            conditions.append("observed_at >= ?")
            params.append(from_ts)

        if to_ts is not None:
            conditions.append("observed_at <= ?")
            params.append(to_ts)

        if cursor:
            try:
                raw_cursor = base64.b64decode(cursor).decode("utf-8")
                c_registered_at, c_movement_id = raw_cursor.split(":", 1)
                conditions.append(
                    "(registered_at < ? OR (registered_at = ? AND movement_id < ?))"
                )
                params.extend([int(c_registered_at), int(c_registered_at), c_movement_id])
            except Exception as exc:
                raise LedgerValidationError("Invalid cursor token") from exc

        where_clause = " AND ".join(conditions)
        sql = f"""
            SELECT * FROM economic_movements
            WHERE {where_clause}
            ORDER BY registered_at DESC, movement_id DESC
            LIMIT ?;
        """
        params.append(limit + 1)

        rows = self._conn.execute(sql, params).fetchall()
        has_more = len(rows) > limit
        items_rows = rows[:limit]

        movements = [self._row_to_movement(r) for r in items_rows]
        next_cursor = None
        if has_more and items_rows:
            last = items_rows[-1]
            token = f"{last['registered_at']}:{last['movement_id']}"
            next_cursor = base64.b64encode(token.encode("utf-8")).decode("utf-8")

        return movements, next_cursor

    def get_balances(
        self,
        agent_account: str,
        *,
        network: Optional[str] = None,
        token_mint: Optional[str] = None,
    ) -> list[BalanceReport]:
        """Calculates exact balances strictly partitioned by (network, token_mint).

        Monetary exactness guarantee:
        All summations are performed using Python arbitrary-precision integers (int),
        avoiding any SQLite internal float conversions for amounts near or exceeding 2^63 - 1.
        """
        conditions = ["agent_account = ?"]
        params: list[Any] = [agent_account]

        if network:
            conditions.append("network = ?")
            params.append(network)
        if token_mint:
            conditions.append("token_mint = ?")
            params.append(token_mint)

        where_clause = " AND ".join(conditions)

        sql = f"""
            SELECT
                network,
                token_mint,
                nature,
                status,
                amount_base_units,
                reversal_of_movement_id
            FROM economic_movements
            WHERE {where_clause}
            ORDER BY network, token_mint;
        """

        rows = self._conn.execute(sql, params).fetchall()

        partitions: dict[tuple[str, str], dict[str, Any]] = {}
        for r in rows:
            key = (r["network"], r["token_mint"])
            if key not in partitions:
                partitions[key] = {
                    "movement_count": 0,
                    "reconciled": 0,
                    "provisional": 0,
                    "reserved": 0,
                }
            p = partitions[key]
            p["movement_count"] += 1

            amt = int(r["amount_base_units"])
            st = r["status"]
            nat = r["nature"]
            is_reversal = r["reversal_of_movement_id"] is not None

            if st == MovementStatus.RECONCILED.value:
                if nat == MovementNature.INCOME.value:
                    p["reconciled"] += amt
                elif nat == MovementNature.EXPENSE.value:
                    p["reconciled"] -= amt
                elif nat == MovementNature.ADJUSTMENT.value and not is_reversal:
                    p["reconciled"] += amt
            elif st == MovementStatus.PROVISIONAL.value:
                if nat == MovementNature.INCOME.value:
                    p["provisional"] += amt
                elif nat == MovementNature.EXPENSE.value:
                    p["provisional"] -= amt

            if st != MovementStatus.REVERTED.value and nat == MovementNature.RESERVE.value:
                p["reserved"] += amt

        reports = []
        for (net, mint), data in sorted(partitions.items()):
            rec = data["reconciled"]
            prov = data["provisional"]
            res = data["reserved"]
            tot = rec + prov

            reports.append(
                BalanceReport(
                    agent_account=agent_account,
                    network=net,
                    token_mint=mint,
                    reconciled_balance=rec,
                    provisional_balance=prov,
                    reserved_balance=res,
                    reconciled_balance_str=str(rec),
                    provisional_balance_str=str(prov),
                    reserved_balance_str=str(res),
                    total_effective_balance=tot,
                    total_effective_balance_str=str(tot),
                    movement_count=data["movement_count"],
                )
            )

        return reports

    def get_ledger_totals(self) -> dict[str, Any]:
        """Returns exact sum of all debits and credits across the ledger to verify accounting invariants."""
        rows = self._conn.execute(
            "SELECT entry_type, amount_base_units FROM ledger_entries;"
        ).fetchall()
        total_debit = 0
        total_credit = 0
        for r in rows:
            amt = int(r["amount_base_units"])
            if r["entry_type"] == EntryType.DEBIT.value:
                total_debit += amt
            elif r["entry_type"] == EntryType.CREDIT.value:
                total_credit += amt
        return {
            "total_debit": total_debit,
            "total_credit": total_credit,
            "is_balanced": total_debit == total_credit,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Double-Entry Helpers & Invariants
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _assert_balanced_legs(legs: list[LedgerLeg]) -> None:
        if not legs:
            raise LedgerValidationError("Journal entry must have at least one debit and one credit leg")

        total_debit = sum(
            leg.amount_base_units for leg in legs if leg.entry_type == EntryType.DEBIT
        )
        total_credit = sum(
            leg.amount_base_units for leg in legs if leg.entry_type == EntryType.CREDIT
        )

        if total_debit != total_credit:
            raise LedgerValidationError(
                f"Double-entry accounting out of balance: DEBIT={total_debit} != CREDIT={total_credit}"
            )

    @staticmethod
    def _generate_default_legs(
        *,
        journal_entry_id: str,
        agent_account: str,
        nature: MovementNature,
        amount_base_units: int,
        created_at: int,
        is_compensating: bool = False,
    ) -> list[LedgerLeg]:
        """Generates balanced double-entry accounting legs."""
        if nature == MovementNature.INCOME:
            return [
                LedgerLeg(
                    entry_id=str(uuid.uuid4()),
                    journal_entry_id=journal_entry_id,
                    account_name="ASSET:TREASURY",
                    entry_type=EntryType.DEBIT,
                    amount_base_units=amount_base_units,
                    agent_account=agent_account,
                    created_at=created_at,
                ),
                LedgerLeg(
                    entry_id=str(uuid.uuid4()),
                    journal_entry_id=journal_entry_id,
                    account_name="REVENUE:SETTLEMENT",
                    entry_type=EntryType.CREDIT,
                    amount_base_units=amount_base_units,
                    agent_account=agent_account,
                    created_at=created_at,
                ),
            ]
        elif nature == MovementNature.EXPENSE:
            return [
                LedgerLeg(
                    entry_id=str(uuid.uuid4()),
                    journal_entry_id=journal_entry_id,
                    account_name="EXPENSE:OPERATING",
                    entry_type=EntryType.DEBIT,
                    amount_base_units=amount_base_units,
                    agent_account=agent_account,
                    created_at=created_at,
                ),
                LedgerLeg(
                    entry_id=str(uuid.uuid4()),
                    journal_entry_id=journal_entry_id,
                    account_name="ASSET:TREASURY",
                    entry_type=EntryType.CREDIT,
                    amount_base_units=amount_base_units,
                    agent_account=agent_account,
                    created_at=created_at,
                ),
            ]
        elif nature == MovementNature.RESERVE:
            return [
                LedgerLeg(
                    entry_id=str(uuid.uuid4()),
                    journal_entry_id=journal_entry_id,
                    account_name="ASSET:LOCKED_RESERVE",
                    entry_type=EntryType.DEBIT,
                    amount_base_units=amount_base_units,
                    agent_account=agent_account,
                    created_at=created_at,
                ),
                LedgerLeg(
                    entry_id=str(uuid.uuid4()),
                    journal_entry_id=journal_entry_id,
                    account_name="LIABILITY:BOND_DEPOSIT",
                    entry_type=EntryType.CREDIT,
                    amount_base_units=amount_base_units,
                    agent_account=agent_account,
                    created_at=created_at,
                ),
            ]
        elif nature == MovementNature.ADJUSTMENT:
            debit_acc = "EQUITY:ADJUSTMENT" if is_compensating else "ASSET:TREASURY"
            credit_acc = "ASSET:TREASURY" if is_compensating else "EQUITY:ADJUSTMENT"
            return [
                LedgerLeg(
                    entry_id=str(uuid.uuid4()),
                    journal_entry_id=journal_entry_id,
                    account_name=debit_acc,
                    entry_type=EntryType.DEBIT,
                    amount_base_units=amount_base_units,
                    agent_account=agent_account,
                    created_at=created_at,
                ),
                LedgerLeg(
                    entry_id=str(uuid.uuid4()),
                    journal_entry_id=journal_entry_id,
                    account_name=credit_acc,
                    entry_type=EntryType.CREDIT,
                    amount_base_units=amount_base_units,
                    agent_account=agent_account,
                    created_at=created_at,
                ),
            ]
        else:
            raise LedgerValidationError(f"Unknown movement nature: {nature}")

    @staticmethod
    def _row_to_movement(row: sqlite3.Row) -> EconomicMovement:
        meta = {}
        if row["metadata_json"]:
            try:
                meta = json.loads(row["metadata_json"])
            except Exception:
                meta = {}

        return EconomicMovement(
            movement_id=row["movement_id"],
            journal_entry_id=row["journal_entry_id"],
            idempotency_key=row["idempotency_key"],
            agent_id=row["agent_id"],
            agent_account=row["agent_account"],
            owner_pubkey=row["owner_pubkey"],
            work_order_account=row["work_order_account"],
            work_order_id=row["work_order_id"],
            network=row["network"],
            genesis_hash=row["genesis_hash"],
            program_id=row["program_id"],
            token_mint=row["token_mint"],
            amount_base_units=int(row["amount_base_units"]),
            amount_str=str(row["amount_str"]),
            nature=MovementNature(row["nature"]),
            status=MovementStatus(row["status"]),
            provenance_source=ProvenanceSource(row["provenance_source"]),
            evidence_hash=row["evidence_hash"],
            attestation_id=row["attestation_id"],
            tx_signature=row["tx_signature"],
            external_ref=row["external_ref"],
            registered_at=int(row["registered_at"]),
            observed_at=int(row["observed_at"]),
            reversal_of_movement_id=row["reversal_of_movement_id"],
            metadata=meta,
        )
