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

        # Check existing by idempotency_key first (Fast Read without locking)
        existing = self.get_by_idempotency_key(clean_idempotency_key)
        if existing:
            return existing

        # Validate monetary exactness (strictly integer base units, rejection of floats)
        amount_int = validate_base_units(amount_base_units)
        amount_str = str(amount_int)

        nature_enum = MovementNature(nature)
        status_enum = MovementStatus(status)
        source_enum = ProvenanceSource(provenance_source)

        now = int(time.time())
        obs_time = observed_at if observed_at is not None else now
        movement_id = str(uuid.uuid4())
        journal_entry_id = f"je_{movement_id}"
        meta = metadata or {}

        # Prepare double-entry legs
        legs: list[LedgerLeg] = []
        if custom_journal_legs is not None and len(custom_journal_legs) > 0:
            for leg_dict in custom_journal_legs:
                leg_amt = validate_base_units(leg_dict["amount_base_units"])
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
                return self.get_movement(row["movement_id"])  # type: ignore

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

            # 2. Insert ledger legs
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
                        leg.amount_base_units,
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
                    amount_int,
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
            # If unique constraint on idempotency_key tripped concurrently:
            existing = self.get_by_idempotency_key(clean_idempotency_key)
            if existing:
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
    # Settlement Integration (CON-22 / CON-23 bridge)
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
        
        CRITICAL GUARD: Does NOT automatically consider `total_amount` as agent income.
        Calculates exact operator payout in accordance with verification terms.
        """
        total_amount = validate_base_units(work_order_data.get("total_amount", 0))
        verification_status = work_order_data.get("verification_status")
        completion_bps = int(work_order_data.get("completion_bps", 0))
        payment_model = work_order_data.get("payment_model", "Fixed")
        work_order_id = work_order_data.get("work_order_id")

        # Exact protocol calculation matching Anchor settlement.rs
        operator_payout = self._calculate_verified_payout(
            payment_model=payment_model,
            verification_status=verification_status,
            total_amount=total_amount,
            completion_bps=completion_bps,
        )

        creator_refund = total_amount - operator_payout

        # If payout is 0 (e.g. work rejected), record zero-fee audit movement or return
        status = MovementStatus.RECONCILED if is_reconciled else MovementStatus.PROVISIONAL
        attestation_hash = work_order_data.get("verification_attestation_hash")

        # Deterministic idempotency key for this settlement event
        idempotency_key = f"settlement:{work_order_account}:{tx_signature or 'payout'}"

        if operator_payout == 0:
            # Rejection or zero completion: record audit adjustment/zero movement
            meta = {
                "event": "settlement_zero_payout",
                "total_escrow_funded": total_amount,
                "creator_refund": creator_refund,
                "operator_payout": 0,
                "verification_status": verification_status,
                "completion_bps": completion_bps,
                "payment_model": payment_model,
            }
            # Minimal record representing the rejected settlement audit trail
            return self.record_movement(
                idempotency_key=idempotency_key,
                agent_id=agent_id,
                agent_account=agent_account,
                owner_pubkey=owner_pubkey,
                network=network,
                genesis_hash=genesis_hash,
                program_id=program_id,
                token_mint=token_mint,
                amount_base_units=1,  # symbolic 1 base unit adjustment or note
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

        if verification_status == "Rejected":
            return 0
        if verification_status != "Accepted":
            return 0

        if payment_model == "Fixed":
            return total_amount if completion_bps == 10000 else 0
        elif payment_model == "Proportional":
            return (total_amount * completion_bps) // 10000
        else:
            raise LedgerValidationError(f"Unsupported payment_model: {payment_model}")

    # ─────────────────────────────────────────────────────────────────────────
    # Compensating Movements & Corrections (Append-Only Reversals)
    # ─────────────────────────────────────────────────────────────────────────

    def revert_movement(
        self,
        movement_id: str,
        *,
        reason: str,
        authorized_by: str,
    ) -> tuple[EconomicMovement, EconomicMovement]:
        """Atomically marks a movement as REVERTED and generates a compensating movement.
        
        Strict append-only guarantee: previously reconciled/recorded data is NEVER deleted.
        """
        if not reason or not reason.strip():
            raise LedgerValidationError("Reversal reason is mandatory")

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

            # 1. Update original movement status to REVERTED
            cursor.execute(
                "UPDATE economic_movements SET status = ? WHERE movement_id = ?;",
                (MovementStatus.REVERTED.value, movement_id),
            )

            # 2. Build compensating movement
            comp_id = str(uuid.uuid4())
            comp_idempotency = f"reversal:{movement_id}:{comp_id}"
            now = int(time.time())

            comp_meta = {
                "reversal_of_movement_id": movement_id,
                "reversal_reason": reason.strip(),
                "authorized_by": authorized_by,
                "original_nature": row["nature"],
                "original_amount": row["amount_base_units"],
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
                    comp_id,
                    None,
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
                    row["amount_base_units"],
                    row["amount_str"],
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
        compensating = self.get_movement(comp_id)
        return reverted_orig, compensating  # type: ignore

    # ─────────────────────────────────────────────────────────────────────────
    # Lookups & Balances (Strict Isolation per Network & Mint)
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
            # Cursor format: base64 encoded (registered_at, movement_id)
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
        
        CRITICAL GUARD: Never combines amounts across different mints or networks.
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
                COUNT(*) as movement_count,
                -- Reconciled balance: Active Incomes - Active Expenses + Direct Adjustments
                -- Reverted movements (and their corresponding reversal audit markers) are net-zeroed.
                COALESCE(SUM(CASE
                    WHEN status = 'RECONCILED' AND nature = 'INCOME' THEN amount_base_units
                    WHEN status = 'RECONCILED' AND nature = 'EXPENSE' THEN -amount_base_units
                    WHEN status = 'RECONCILED' AND nature = 'ADJUSTMENT' AND reversal_of_movement_id IS NULL THEN amount_base_units
                    ELSE 0
                END), 0) AS reconciled_balance,
                -- Provisional balance
                COALESCE(SUM(CASE
                    WHEN status = 'PROVISIONAL' AND nature = 'INCOME' THEN amount_base_units
                    WHEN status = 'PROVISIONAL' AND nature = 'EXPENSE' THEN -amount_base_units
                    ELSE 0
                END), 0) AS provisional_balance,
                -- Reserved balance (e.g. staked bond, slashable reserve)
                COALESCE(SUM(CASE
                    WHEN status != 'REVERTED' AND nature = 'RESERVE' THEN amount_base_units
                    ELSE 0
                END), 0) AS reserved_balance
            FROM economic_movements
            WHERE {where_clause}
            GROUP BY network, token_mint
            ORDER BY network, token_mint;
        """

        rows = self._conn.execute(sql, params).fetchall()
        reports = []
        for r in rows:
            rec = int(r["reconciled_balance"])
            prov = int(r["provisional_balance"])
            res = int(r["reserved_balance"])
            tot = rec + prov

            reports.append(
                BalanceReport(
                    agent_account=agent_account,
                    network=r["network"],
                    token_mint=r["token_mint"],
                    reconciled_balance=rec,
                    provisional_balance=prov,
                    reserved_balance=res,
                    reconciled_balance_str=str(rec),
                    provisional_balance_str=str(prov),
                    reserved_balance_str=str(res),
                    total_effective_balance=tot,
                    total_effective_balance_str=str(tot),
                    movement_count=int(r["movement_count"]),
                )
            )

        return reports

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
            # Normal: Debit ASSET:TREASURY, Credit REVENUE:SETTLEMENT
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
            # Normal: Debit EXPENSE:OPERATING, Credit ASSET:TREASURY
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
            # Normal: Debit ASSET:LOCKED_RESERVE, Credit LIABILITY:BOND_DEPOSIT
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
            # Compensating or manual adjustment
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
            amount_str=row["amount_str"],
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
