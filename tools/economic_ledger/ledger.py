"""Core persistent economic ledger engine with balanced double-entry accounting."""
from __future__ import annotations

import base64
import json
import re
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Optional, Protocol, runtime_checkable

from .models import (
    AgentCost,
    AgentEconomicSummary,
    AgentReserve,
    BalanceReport,
    CostCategory,
    CostNature,
    EconomicMovement,
    EntryType,
    IdempotencyConflictError,
    JournalEntry,
    LedgerLeg,
    LedgerValidationError,
    MovementNature,
    MovementStatus,
    ProvenanceSource,
    ReserveAction,
    ReserveStatus,
    ReserveTransaction,
    ReserveType,
    validate_base_units,
)
from .schema import run_migrations

DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / ".aerosettle-local" / "economic_ledger.db"

DEFAULT_NETWORK = "localnet"
LOCALNET_GENESIS_HASH = "HP9XKTusRPGC78EFDpR9xdEq6simL2vqyDdrMvn6Vacg"
DEVNET_GENESIS_HASH = "EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG"
MAINNET_GENESIS_HASH = "5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d"

DEFAULT_GENESIS_HASH = LOCALNET_GENESIS_HASH
DEFAULT_PROGRAM_ID = "Conatus11111111111111111111111111111111111"

DEFAULT_TRUSTED_RECONCILER_AUTHORITIES: frozenset[str] = frozenset({
    "conatus:protocol:reconciler:v1",
    "conatus:internal:settlement-validator:v1",
})


def validate_monetary_context(
    *,
    network: str,
    genesis_hash: Optional[str] = None,
    program_id: Optional[str] = None,
    token_mint: Optional[str] = None,
) -> tuple[str, str, str, str]:
    """Validates that network, genesis_hash, program_id, and token_mint form a coherent monetary context."""
    if not network or not isinstance(network, str) or not network.strip():
        raise LedgerValidationError("network cannot be empty")
    net_clean = network.strip()

    eff_mint = (token_mint or "").strip()
    if not eff_mint:
        raise LedgerValidationError("token_mint cannot be empty")

    eff_prog = (program_id or DEFAULT_PROGRAM_ID).strip()
    if not eff_prog:
        raise LedgerValidationError("program_id cannot be empty")

    gen_candidate = genesis_hash.strip() if (genesis_hash and isinstance(genesis_hash, str) and genesis_hash.strip()) else None

    is_mainnet = net_clean in ("solana:mainnet-beta", "mainnet-beta", "mainnet")
    is_localnet = net_clean in ("solana:localnet", "localnet")
    is_devnet = net_clean in ("solana:devnet", "devnet")

    if gen_candidate:
        if is_mainnet and gen_candidate == LOCALNET_GENESIS_HASH:
            raise LedgerValidationError(
                f"Monetary context conflict: Localnet genesis hash '{gen_candidate}' cannot be used with network '{net_clean}'"
            )
        if is_mainnet and gen_candidate != MAINNET_GENESIS_HASH:
            raise LedgerValidationError(
                f"Monetary context conflict: network '{net_clean}' requires genesis hash '{MAINNET_GENESIS_HASH}', got '{gen_candidate}'"
            )
        if is_localnet and gen_candidate == MAINNET_GENESIS_HASH:
            raise LedgerValidationError(
                f"Monetary context conflict: Mainnet genesis hash '{gen_candidate}' cannot be used with localnet '{net_clean}'"
            )
        if is_devnet and gen_candidate == LOCALNET_GENESIS_HASH:
            raise LedgerValidationError(
                f"Monetary context conflict: Localnet genesis hash '{gen_candidate}' cannot be used with devnet '{net_clean}'"
            )
        eff_gen = gen_candidate
    else:
        if is_localnet:
            eff_gen = LOCALNET_GENESIS_HASH
        elif is_devnet:
            eff_gen = DEVNET_GENESIS_HASH
        elif is_mainnet:
            eff_gen = MAINNET_GENESIS_HASH
        elif net_clean in ("solana:testnet", "testnet"):
            eff_gen = "4uhcVJyU9pJkvQyS88uRDiswHXSCkY3zQawwpjk2NsNY"
        else:
            raise LedgerValidationError(
                f"genesis_hash is mandatory and cannot be defaulted for network '{net_clean}'"
            )

    return net_clean, eff_gen, eff_prog, eff_mint


@runtime_checkable
class ReconciliationVerifier(Protocol):
    """Protocol for authenticating and verifying on-chain evidence prior to reconciliation."""

    def verify_reconciliation(
        self,
        *,
        movement_id: str,
        evidence_hash: str,
        authorized_by: str,
        slot: int,
        tx_signature: str,
        movement: Optional[EconomicMovement] = None,
    ) -> bool:
        ...


class IsolatedTestReconcilerVerifier:
    """Isolated test reconciler verifier for automated testing environments.

    In production, reconciliation promotion is disabled pending authentic CON-23 RPC/SPL verification.
    This test verifier allows whitelisting valid test transactions/signatures and explicitly
    rejects fictitious, unverified, or dummy signatures.
    """

    def __init__(
        self,
        allowed_signatures: Optional[set[str] | list[str]] = None,
        *,
        reject_fictitious: bool = True,
    ) -> None:
        self.allowed_signatures = set(allowed_signatures) if allowed_signatures is not None else None
        self.reject_fictitious = reject_fictitious
        self.verified_calls: list[dict[str, Any]] = []

    def allow_signature(self, signature: str) -> None:
        if self.allowed_signatures is None:
            self.allowed_signatures = set()
        self.allowed_signatures.add(signature)

    def verify_reconciliation(
        self,
        *,
        movement_id: str,
        evidence_hash: str,
        authorized_by: str,
        slot: int,
        tx_signature: str,
        movement: Optional[EconomicMovement] = None,
    ) -> bool:
        sig_lower = tx_signature.lower()
        if self.reject_fictitious:
            if (
                sig_lower.startswith("fake")
                or sig_lower.startswith("fictitious")
                or "fake" in sig_lower
                or "fictitious" in sig_lower
                or "ficticia" in sig_lower
                or "dummy" in sig_lower
                or "mock" in sig_lower
            ):
                return False

        if self.allowed_signatures is not None and tx_signature not in self.allowed_signatures:
            return False

        self.verified_calls.append({
            "movement_id": movement_id,
            "evidence_hash": evidence_hash,
            "authorized_by": authorized_by,
            "slot": slot,
            "tx_signature": tx_signature,
        })
        return True


@runtime_checkable
class AttestationVerifier(Protocol):
    """Protocol for authenticating and verifying cryptographic cost attestations."""

    def verify_attestation(
        self,
        *,
        attestation_id: str,
        authorized_by: Optional[str] = None,
        evidence_hash: Optional[str] = None,
        cost_data: Optional[dict[str, Any]] = None,
    ) -> bool:
        ...


class IsolatedTestAttestationVerifier:
    """Isolated test attestation verifier for automated testing environments.

    In production, automatic assignment of EXTERNAL_VERIFIED or RECONCILED is disabled
    pending an authentic cryptographic attestation verifier. This verifier enables testing
    authorized vs unauthorized authorities and genuine vs forged/invented attestations.
    """

    def __init__(
        self,
        trusted_authorities: Optional[set[str] | list[str]] = None,
        allowed_attestations: Optional[set[str] | list[str]] = None,
        *,
        reject_fictitious: bool = True,
    ) -> None:
        self.trusted_authorities = (
            set(trusted_authorities)
            if trusted_authorities is not None
            else {"conatus:trusted:oracle:v1", "conatus:protocol:cost-verifier:v1"}
        )
        self.allowed_attestations = (
            set(allowed_attestations) if allowed_attestations is not None else None
        )
        self.reject_fictitious = reject_fictitious
        self.verified_calls: list[dict[str, Any]] = []

    def allow_attestation(self, attestation_id: str) -> None:
        if self.allowed_attestations is None:
            self.allowed_attestations = set()
        self.allowed_attestations.add(attestation_id)

    def verify_attestation(
        self,
        *,
        attestation_id: str,
        authorized_by: Optional[str] = None,
        evidence_hash: Optional[str] = None,
        cost_data: Optional[dict[str, Any]] = None,
    ) -> bool:
        if not authorized_by or authorized_by not in self.trusted_authorities:
            return False

        att_lower = attestation_id.lower()
        if self.reject_fictitious:
            if (
                att_lower.startswith("fake")
                or att_lower.startswith("invented")
                or att_lower.startswith("forged")
                or "fake" in att_lower
                or "invented" in att_lower
                or "forged" in att_lower
                or "dummy" in att_lower
                or "mock" in att_lower
            ):
                return False

        if self.allowed_attestations is not None and attestation_id not in self.allowed_attestations:
            return False

        self.verified_calls.append({
            "attestation_id": attestation_id,
            "authorized_by": authorized_by,
            "evidence_hash": evidence_hash,
            "cost_data": cost_data,
        })
        return True


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
    agent_id: str,
    agent_account: str,
    owner_pubkey: str,
    network: str,
    genesis_hash: str,
    program_id: str,
    token_mint: str,
    amount_base_units: int,
    nature: MovementNature,
    provenance_source: ProvenanceSource,
    work_order_account: Optional[str],
    work_order_id: Optional[str],
    tx_signature: Optional[str],
    evidence_hash: Optional[str],
    external_ref: Optional[str] = None,
    reversal_of_movement_id: Optional[str] = None,
) -> None:
    """Verifies that a reused idempotency key exactly matches the immutable initial event footprint.

    Decouples the initial event footprint from reconciliation enrichment fields:
    - Initial event parameters are preserved in metadata["initial_event"].
    - Subsequent lifecycle transitions (e.g. to RECONCILED) or evidence enrichment
      (reconciliation evidence_hash, slot, or tx_signature) do not cause false idempotency conflicts.
    - Divergent initial requests continue to raise IdempotencyConflictError (409).
    """
    init_evt = existing.metadata.get("initial_event") if existing.metadata else None
    if isinstance(init_evt, dict):
        base_agent_id = init_evt.get("agent_id")
        base_agent_account = init_evt.get("agent_account")
        base_owner_pubkey = init_evt.get("owner_pubkey")
        base_network = init_evt.get("network")
        base_genesis_hash = init_evt.get("genesis_hash")
        base_program_id = init_evt.get("program_id")
        base_token_mint = init_evt.get("token_mint")
        base_amount = int(init_evt.get("amount_base_units", 0))
        base_nature = init_evt.get("nature")
        base_source = init_evt.get("provenance_source")
        base_wo_account = init_evt.get("work_order_account")
        base_wo_id = init_evt.get("work_order_id")
        base_tx_sig = init_evt.get("tx_signature")
        base_ev_hash = init_evt.get("evidence_hash")
        base_ext_ref = init_evt.get("external_ref")
        base_reversal = init_evt.get("reversal_of_movement_id")
    else:
        # Fallback for legacy records without initial_event metadata
        base_agent_id = existing.agent_id
        base_agent_account = existing.agent_account
        base_owner_pubkey = existing.owner_pubkey
        base_network = existing.network
        base_genesis_hash = existing.genesis_hash
        base_program_id = existing.program_id
        base_token_mint = existing.token_mint
        base_amount = existing.amount_base_units
        base_nature = existing.nature.value
        base_source = existing.provenance_source.value
        base_wo_account = existing.work_order_account
        base_wo_id = existing.work_order_id
        base_tx_sig = existing.tx_signature
        base_ev_hash = existing.evidence_hash
        base_ext_ref = existing.external_ref
        base_reversal = existing.reversal_of_movement_id

    mismatches: list[str] = []
    if base_agent_id != agent_id:
        mismatches.append(f"agent_id ({base_agent_id} != {agent_id})")
    if base_agent_account != agent_account:
        mismatches.append(f"agent_account ({base_agent_account} != {agent_account})")
    if base_owner_pubkey != owner_pubkey:
        mismatches.append(f"owner_pubkey ({base_owner_pubkey} != {owner_pubkey})")
    if base_network != network:
        mismatches.append(f"network ({base_network} != {network})")
    if base_genesis_hash != genesis_hash:
        mismatches.append(f"genesis_hash ({base_genesis_hash} != {genesis_hash})")
    if base_program_id != program_id:
        mismatches.append(f"program_id ({base_program_id} != {program_id})")
    if base_token_mint != token_mint:
        mismatches.append(f"token_mint ({base_token_mint} != {token_mint})")
    if base_amount != amount_base_units:
        mismatches.append(f"amount_base_units ({base_amount} != {amount_base_units})")
    if base_nature != nature.value:
        mismatches.append(f"nature ({base_nature} != {nature.value})")
    if base_source != provenance_source.value:
        mismatches.append(f"provenance_source ({base_source} != {provenance_source.value})")
    if (base_wo_account or None) != (work_order_account or None):
        mismatches.append(f"work_order_account ({base_wo_account} != {work_order_account})")
    if (base_wo_id or None) != (work_order_id or None):
        mismatches.append(f"work_order_id ({base_wo_id} != {work_order_id})")
    if (base_tx_sig or None) != (tx_signature or None):
        mismatches.append(f"tx_signature ({base_tx_sig} != {tx_signature})")
    if (base_ev_hash or None) != (evidence_hash or None):
        mismatches.append(f"evidence_hash ({base_ev_hash} != {evidence_hash})")
    if (base_ext_ref or None) != (external_ref or None):
        mismatches.append(f"external_ref ({base_ext_ref} != {external_ref})")
    if (base_reversal or None) != (reversal_of_movement_id or None):
        mismatches.append(f"reversal_of_movement_id ({base_reversal} != {reversal_of_movement_id})")

    if mismatches:
        raise IdempotencyConflictError(
            f"Idempotency conflict for key '{existing.idempotency_key}': "
            f"existing record differs in {', '.join(mismatches)}"
        )


class EconomicLedger:
    """ACID-compliant, thread-safe persistent economic ledger for Conatus/AeroSettle agents."""

    def __init__(
        self,
        db_path: str | Path = DEFAULT_DB_PATH,
        *,
        trusted_reconciler_authorities: Optional[set[str] | frozenset[str]] = None,
        reconciliation_verifier: Optional[ReconciliationVerifier] = None,
        attestation_verifier: Optional[AttestationVerifier] = None,
    ):
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

        # Configure trusted reconcilers
        self._trusted_reconcilers = (
            set(trusted_reconciler_authorities)
            if trusted_reconciler_authorities is not None
            else set(DEFAULT_TRUSTED_RECONCILER_AUTHORITIES)
        )
        self._reconciliation_verifier = reconciliation_verifier
        self._attestation_verifier = attestation_verifier

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
        cursor: Optional[sqlite3.Cursor] = None,
    ) -> EconomicMovement:
        """Idempotently records an economic movement with balanced double-entry accounting."""
        if not idempotency_key or not idempotency_key.strip():
            raise LedgerValidationError("idempotency_key cannot be empty")

        clean_idempotency_key = idempotency_key.strip()
        nature_enum = MovementNature(nature)
        status_enum = MovementStatus(status)
        source_enum = ProvenanceSource(provenance_source)

        # Validate monetary context
        net_val, gen_val, prog_val, mint_val = validate_monetary_context(
            network=network,
            genesis_hash=genesis_hash,
            program_id=program_id,
            token_mint=token_mint,
        )

        # Monetary validation: allow zero base units for non-disbursement audit entries
        allow_zero = (amount_base_units == 0 or str(amount_base_units) == "0")
        amount_int = validate_base_units(amount_base_units, allow_zero=allow_zero)
        amount_str = str(amount_int)

        # Conservative Reconciliation Gate for CON-22:
        # All initial economic movements must start as PROVISIONAL.
        # Direct assignment of RECONCILED is restricted exclusively to system contrasientos (reversals).
        if reversal_of_movement_id is None and status_enum == MovementStatus.RECONCILED:
            raise LedgerValidationError(
                "Initial economic movements must be recorded as PROVISIONAL; "
                "transition to RECONCILED requires verified evidence via reconcile_movement()."
            )

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

        # Check existing by idempotency_key first (Fast Read with Complete Semantic Matching)
        existing = self.get_by_idempotency_key(clean_idempotency_key)
        if existing:
            _check_idempotency_match(
                existing,
                agent_id=agent_id,
                agent_account=agent_account,
                owner_pubkey=owner_pubkey,
                network=net_val,
                genesis_hash=gen_val,
                program_id=prog_val,
                token_mint=mint_val,
                amount_base_units=amount_int,
                nature=nature_enum,
                provenance_source=source_enum,
                work_order_account=work_order_account,
                work_order_id=work_order_id,
                tx_signature=tx_signature,
                evidence_hash=evidence_hash,
                external_ref=external_ref,
                reversal_of_movement_id=reversal_of_movement_id,
            )
            return existing

        now = int(time.time())
        obs_time = observed_at if observed_at is not None else now
        movement_id = str(uuid.uuid4())
        journal_entry_id = f"je_{movement_id}"
        meta = dict(metadata) if metadata else {}
        # Preserve immutable footprint of the initial event
        meta["initial_event"] = {
            "agent_id": agent_id,
            "agent_account": agent_account,
            "owner_pubkey": owner_pubkey,
            "network": net_val,
            "genesis_hash": gen_val,
            "program_id": prog_val,
            "token_mint": mint_val,
            "amount_base_units": amount_int,
            "nature": nature_enum.value,
            "provenance_source": source_enum.value,
            "work_order_account": work_order_account or None,
            "work_order_id": work_order_id or None,
            "tx_signature": tx_signature or None,
            "evidence_hash": evidence_hash or None,
            "external_ref": external_ref or None,
            "reversal_of_movement_id": reversal_of_movement_id or None,
        }

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

        # Atomic Transaction Management
        manage_tx = (cursor is None)
        tx_cursor = cursor if cursor is not None else self._conn.cursor()
        if manage_tx:
            tx_cursor.execute("BEGIN IMMEDIATE;")
        try:
            # Secondary concurrency check inside lock
            tx_cursor.execute(
                "SELECT movement_id FROM economic_movements WHERE idempotency_key = ?;",
                (clean_idempotency_key,),
            )
            row = tx_cursor.fetchone()
            if row:
                if manage_tx:
                    tx_cursor.execute("ROLLBACK;")
                locked_existing = self.get_movement(row["movement_id"])
                if locked_existing:
                    _check_idempotency_match(
                        locked_existing,
                        agent_id=agent_id,
                        agent_account=agent_account,
                        owner_pubkey=owner_pubkey,
                        network=net_val,
                        genesis_hash=gen_val,
                        program_id=prog_val,
                        token_mint=mint_val,
                        amount_base_units=amount_int,
                        nature=nature_enum,
                        provenance_source=source_enum,
                        work_order_account=work_order_account,
                        work_order_id=work_order_id,
                        tx_signature=tx_signature,
                        evidence_hash=evidence_hash,
                        external_ref=external_ref,
                        reversal_of_movement_id=reversal_of_movement_id,
                    )
                    return locked_existing

            # 1. Insert journal entry
            tx_cursor.execute(
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
                    net_val,
                    gen_val,
                    prog_val,
                    mint_val,
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
                tx_cursor.execute(
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
            tx_cursor.execute(
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
                    net_val,
                    gen_val,
                    prog_val,
                    mint_val,
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

            if manage_tx:
                tx_cursor.execute("COMMIT;")
        except sqlite3.IntegrityError as exc:
            if manage_tx:
                try:
                    tx_cursor.execute("ROLLBACK;")
                except Exception:
                    pass
            existing = self.get_by_idempotency_key(clean_idempotency_key)
            if existing:
                _check_idempotency_match(
                    existing,
                    agent_id=agent_id,
                    agent_account=agent_account,
                    owner_pubkey=owner_pubkey,
                    network=net_val,
                    genesis_hash=gen_val,
                    program_id=prog_val,
                    token_mint=mint_val,
                    amount_base_units=amount_int,
                    nature=nature_enum,
                    provenance_source=source_enum,
                    work_order_account=work_order_account,
                    work_order_id=work_order_id,
                    tx_signature=tx_signature,
                    evidence_hash=evidence_hash,
                    external_ref=external_ref,
                    reversal_of_movement_id=reversal_of_movement_id,
                )
                return existing
            raise LedgerValidationError(f"Integrity violation: {exc}") from exc
        except Exception:
            if manage_tx:
                try:
                    tx_cursor.execute("ROLLBACK;")
                except Exception:
                    pass
            raise

        created = self.get_movement(movement_id)
        if created is None:
            raise RuntimeError(f"Failed to retrieve recorded movement {movement_id}")
        return created

    # ─────────────────────────────────────────────────────────────────────────
    # Reconciliation Transition (Internal Trusted Reconciler Verification)
    # ─────────────────────────────────────────────────────────────────────────

    def reconcile_movement(
        self,
        movement_id: str,
        *,
        evidence_hash: str,
        authorized_by: str,
        slot: int,
        tx_signature: str,
    ) -> EconomicMovement:
        """Transitions a PROVISIONAL movement to RECONCILED with verified evidence from a trusted reconciler.

        Guards:
        1. Falsified or unauthorized reconcilers are strictly rejected.
        2. Evidence hash format must be a canonical 64-char hex SHA-256 string.
        3. Confirmed block slot must be a strictly positive integer (> 0).
        4. Valid on-chain transaction signature format is mandatory.
        5. Conflicting evidence or signatures against previously recorded movements fail closed.
        """
        if not authorized_by or not authorized_by.strip():
            raise LedgerValidationError("authorized_by is required for reconciliation")

        auth_clean = authorized_by.strip()
        if auth_clean not in self._trusted_reconcilers:
            raise LedgerValidationError(
                f"Reconciliation rejected: unauthorized reconciler authority '{auth_clean}'"
            )

        if not evidence_hash or not evidence_hash.strip():
            raise LedgerValidationError("evidence_hash is required for reconciliation")

        hash_clean = evidence_hash.strip()
        hex_part = hash_clean[7:] if hash_clean.startswith("sha256:") else hash_clean
        if len(hex_part) != 64 or not all(c in "0123456789abcdefABCDEF" for c in hex_part):
            raise LedgerValidationError(
                f"Reconciliation rejected: falsified or invalid evidence hash format '{evidence_hash}'"
            )

        if slot is None or not isinstance(slot, int) or slot <= 0:
            raise LedgerValidationError(
                f"Reconciliation rejected: slot must be a positive confirmed block slot, got {slot}"
            )

        if not tx_signature or not tx_signature.strip():
            raise LedgerValidationError("Reconciliation rejected: valid on-chain tx_signature is required")

        sig_clean = tx_signature.strip()
        if len(sig_clean) < 8 or len(sig_clean) > 128:
            raise LedgerValidationError(
                f"Reconciliation rejected: invalid transaction signature format '{tx_signature}'"
            )

        # Reliable reconciliation verifier check:
        # In production, promotion to RECONCILED is disabled pending authentic CON-23 RPC/SPL verification.
        # An isolated test verifier must be injected in automated test environments.
        if self._reconciliation_verifier is None:
            raise LedgerValidationError(
                "Reconciliation promotion is disabled in production pending authentic CON-23 RPC/SPL verification. "
                "No movement can transition to RECONCILED solely from caller parameters."
            )

        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT * FROM economic_movements WHERE movement_id = ?;",
            (movement_id,),
        )
        row = cursor.fetchone()
        if not row:
            raise LedgerValidationError(f"Movement not found: {movement_id}")

        current_status = row["status"]
        if current_status == MovementStatus.RECONCILED.value:
            return self._row_to_movement(row)
        if current_status == MovementStatus.REVERTED.value:
            raise LedgerValidationError(f"Cannot reconcile a REVERTED movement: {movement_id}")
        if current_status != MovementStatus.PROVISIONAL.value:
            raise LedgerValidationError(
                f"Only PROVISIONAL movements can be reconciled, got {current_status}"
            )

        movement_obj = self._row_to_movement(row)

        is_verified = self._reconciliation_verifier.verify_reconciliation(
            movement_id=movement_id,
            evidence_hash=hash_clean,
            authorized_by=auth_clean,
            slot=slot,
            tx_signature=sig_clean,
            movement=movement_obj,
        )
        if not is_verified:
            raise LedgerValidationError(
                f"Reconciliation rejected by verifier: unverified or fictitious signature '{sig_clean}' "
                f"for movement '{movement_id}'"
            )

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

            # Check consistency with previously recorded movement evidence/signature
            if row["tx_signature"] and row["tx_signature"] != sig_clean:
                raise LedgerValidationError(
                    f"Reconciliation rejected: tx_signature '{sig_clean}' conflicts with recorded movement tx_signature '{row['tx_signature']}'"
                )
            if row["evidence_hash"] and row["evidence_hash"] != hash_clean:
                raise LedgerValidationError(
                    f"Reconciliation rejected: evidence_hash '{hash_clean}' conflicts with recorded movement evidence_hash '{row['evidence_hash']}'"
                )

            now = int(time.time())
            meta = json.loads(row["metadata_json"]) if row["metadata_json"] else {}
            meta["reconciliation"] = {
                "reconciled_at": now,
                "authorized_by": auth_clean,
                "evidence_hash": hash_clean,
                "slot": slot,
                "tx_signature": sig_clean,
            }

            cursor.execute(
                """
                UPDATE economic_movements
                SET status = ?, evidence_hash = ?, tx_signature = ?, metadata_json = ?
                WHERE movement_id = ?;
                """,
                (
                    MovementStatus.RECONCILED.value,
                    hash_clean,
                    sig_clean,
                    json.dumps(meta),
                    movement_id,
                ),
            )

            if row["journal_entry_id"]:
                cursor.execute(
                    """
                    UPDATE journal_entries
                    SET status = ?, tx_signature = ?
                    WHERE journal_entry_id = ?;
                    """,
                    (
                        MovementStatus.RECONCILED.value,
                        sig_clean,
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
    ) -> EconomicMovement:
        """Records an economic movement resulting from an on-chain work order settlement.

        CRITICAL GUARDS:
        1. Starts in PROVISIONAL status. Reconciled status is never assumed on observation.
        2. Does NOT assume total_amount is agent income: computes exact operator payout.
        3. Non-disbursement (0 payout) settlements are recorded as 0-unit audit movements,
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
                status=MovementStatus.PROVISIONAL,
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
            status=MovementStatus.PROVISIONAL,
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
        cursor: Optional[sqlite3.Cursor] = None,
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

        manage_tx = (cursor is None)
        tx_cursor = cursor if cursor is not None else self._conn.cursor()
        if manage_tx:
            tx_cursor.execute("BEGIN IMMEDIATE;")
        try:
            tx_cursor.execute(
                "SELECT * FROM economic_movements WHERE movement_id = ?;",
                (movement_id,),
            )
            row = tx_cursor.fetchone()
            if not row:
                raise LedgerValidationError(f"Movement not found: {movement_id}")

            if row["status"] == MovementStatus.REVERTED.value:
                raise LedgerValidationError(f"Movement {movement_id} is already reverted")

            now = int(time.time())
            amount_int = int(row["amount_base_units"])
            amount_str = str(row["amount_str"])

            # 1. Update original movement status to REVERTED
            tx_cursor.execute(
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
                tx_cursor.execute(
                    """
                    SELECT * FROM ledger_entries
                    WHERE journal_entry_id = ?
                    ORDER BY entry_id ASC;
                    """,
                    (orig_journal_id,),
                )
                orig_legs = tx_cursor.fetchall()
                for leg in orig_legs:
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
            tx_cursor.execute(
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
                tx_cursor.execute(
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

            tx_cursor.execute(
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

            if manage_tx:
                tx_cursor.execute("COMMIT;")
        except Exception:
            if manage_tx:
                try:
                    tx_cursor.execute("ROLLBACK;")
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

    def get_journal_entry(self, journal_entry_id: str) -> Optional[JournalEntry]:
        row = self._conn.execute(
            "SELECT * FROM journal_entries WHERE journal_entry_id = ?;",
            (journal_entry_id,),
        ).fetchone()
        if not row:
            return None
        leg_rows = self._conn.execute(
            "SELECT * FROM ledger_entries WHERE journal_entry_id = ? ORDER BY entry_id ASC;",
            (journal_entry_id,),
        ).fetchall()
        legs = [
            LedgerLeg(
                entry_id=lr["entry_id"],
                journal_entry_id=lr["journal_entry_id"],
                agent_account=lr["agent_account"],
                account_name=lr["account_name"],
                entry_type=EntryType(lr["entry_type"]),
                amount_base_units=int(lr["amount_base_units"]),
                created_at=lr["created_at"],
            )
            for lr in leg_rows
        ]
        return JournalEntry(
            journal_entry_id=row["journal_entry_id"],
            idempotency_key=row["idempotency_key"],
            network=row["network"],
            genesis_hash=row["genesis_hash"],
            program_id=row["program_id"],
            token_mint=row["token_mint"],
            description=row["description"],
            status=MovementStatus(row["status"]),
            created_at=row["created_at"],
            observed_at=row["observed_at"],
            tx_signature=row["tx_signature"],
            work_order_account=row["work_order_account"],
            legs=legs,
        )

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

        # If agent_reserves entries exist, reflect exact active reserved balance
        for (net, mint), data in partitions.items():
            try:
                res_rows = self._conn.execute(
                    "SELECT current_reserved_base_units FROM agent_reserves WHERE agent_account = ? AND network = ? AND token_mint = ? AND status = 'ACTIVE';",
                    (agent_account, net, mint),
                ).fetchall()
                if res_rows:
                    data["reserved"] = sum(int(r["current_reserved_base_units"]) for r in res_rows)
            except sqlite3.OperationalError:
                pass

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
    # CON-24: Agent Costs & Operating Expenses
    # ─────────────────────────────────────────────────────────────────────────

    def record_cost(
        self,
        *,
        idempotency_key: str,
        agent_id: str,
        agent_account: str,
        owner_pubkey: str,
        category: str | CostCategory,
        cost_nature: str | CostNature,
        economic_period: str,
        amount_base_units: int | str,
        network: str,
        token_mint: str,
        genesis_hash: Optional[str] = None,
        program_id: Optional[str] = None,
        status: Optional[str | MovementStatus] = None,
        provenance_source: Optional[str | ProvenanceSource] = None,
        evidence_hash: Optional[str] = None,
        evidence_url: Optional[str] = None,
        attestation_id: Optional[str] = None,
        description: Optional[str] = None,
        incurred_at: Optional[int] = None,
        from_reserve_id: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
        cursor: Optional[sqlite3.Cursor] = None,
    ) -> AgentCost:
        """Records an agent operational cost, distinguishing realized expenses,

        provisions/accrued liabilities, and budget estimations.
        """
        if not idempotency_key or not idempotency_key.strip():
            raise LedgerValidationError("idempotency_key cannot be empty")
        clean_idempotency_key = idempotency_key.strip()

        # 1. Enums and input validation
        try:
            cat_enum = CostCategory(category)
        except ValueError as exc:
            raise LedgerValidationError(f"Invalid cost category: {category}") from exc

        try:
            nat_enum = CostNature(cost_nature)
        except ValueError as exc:
            raise LedgerValidationError(f"Invalid cost nature: {cost_nature}") from exc

        if not economic_period or not isinstance(economic_period, str) or not economic_period.strip():
            raise LedgerValidationError("economic_period must be a non-empty string")
        clean_period = economic_period.strip()

        amount_int = validate_base_units(amount_base_units, allow_zero=False)
        amount_str = str(amount_int)

        now = int(time.time())
        incurred_time = incurred_at if incurred_at is not None else now
        meta = dict(metadata or {})

        # Monetary context validation
        net_val, gen_val, prog_val, mint_val = validate_monetary_context(
            network=network,
            genesis_hash=genesis_hash,
            program_id=program_id,
            token_mint=token_mint,
        )

        # 2. Provenance & Status Enforcement:
        # Crucial Requirement: Do NOT declare EXTERNAL_VERIFIED simply for receiving a URL, file, or hash.
        # Authentic verification strictly requires an authorized attestation_id verified by a trusted verifier.
        stat_candidate = MovementStatus(status) if status else MovementStatus.PROVISIONAL
        prov_candidate = ProvenanceSource(provenance_source) if provenance_source else ProvenanceSource.MANUAL_ENTRY

        if prov_candidate == ProvenanceSource.EXTERNAL_VERIFIED or stat_candidate == MovementStatus.RECONCILED:
            if not attestation_id or not attestation_id.strip():
                raise LedgerValidationError(
                    "Cannot declare EXTERNAL_VERIFIED or RECONCILED without verified attestation_id. "
                    "Evidence hash or URL alone is insufficient."
                )
            if self._attestation_verifier is None:
                raise LedgerValidationError(
                    "No trusted attestation verifier configured: cannot assign EXTERNAL_VERIFIED or RECONCILED to costs. "
                    "Evidence hash or URL alone is insufficient."
                )
            auth_by = meta.get("authorized_by")
            verified = self._attestation_verifier.verify_attestation(
                attestation_id=attestation_id.strip(),
                authorized_by=auth_by,
                evidence_hash=evidence_hash,
                cost_data={
                    "agent_account": agent_account,
                    "category": cat_enum.value,
                    "cost_nature": nat_enum.value,
                    "amount_base_units": amount_int,
                    "network": net_val,
                    "token_mint": mint_val,
                },
            )
            if not verified:
                raise LedgerValidationError(
                    f"Attestation verification failed for attestation_id '{attestation_id}': unauthorized authority or forged attestation."
                )

        prov_enum = prov_candidate
        stat_enum = stat_candidate

        manage_tx = (cursor is None)
        tx_cursor = cursor if cursor is not None else self._conn.cursor()
        if manage_tx:
            tx_cursor.execute("BEGIN IMMEDIATE;")
        try:
            # 3. Idempotency Check
            tx_cursor.execute(
                "SELECT * FROM agent_costs WHERE idempotency_key = ?;",
                (clean_idempotency_key,),
            )
            existing_row = tx_cursor.fetchone()

            if existing_row:
                # Verify immutable semantic footprint
                if (
                    existing_row["agent_account"] != agent_account
                    or existing_row["category"] != cat_enum.value
                    or existing_row["cost_nature"] != nat_enum.value
                    or existing_row["economic_period"] != clean_period
                    or existing_row["network"] != net_val
                    or existing_row["token_mint"] != mint_val
                    or int(existing_row["amount_base_units"]) != amount_int
                ):
                    raise IdempotencyConflictError(
                        f"Idempotency key '{clean_idempotency_key}' reused with mismatched parameters"
                    )
                if manage_tx:
                    tx_cursor.execute("COMMIT;")
                return self._row_to_cost(existing_row)

            cost_id = f"cost_{uuid.uuid4().hex[:16]}"
            journal_entry_id: Optional[str] = None
            movement_id: Optional[str] = None

            # 4. Double-Entry and Movement Processing depending on cost_nature
            if nat_enum == CostNature.ESTIMATED:
                # Pure estimation: does NOT affect double-entry ledger or treasury balances
                pass
            elif nat_enum == CostNature.ACCRUED_LIABILITY:
                # Accrued liability (provisión): records expense and liability without moving cash
                legs = [
                    {
                        "account_name": f"EXPENSE:{cat_enum.value}",
                        "entry_type": EntryType.DEBIT.value,
                        "amount_base_units": amount_int,
                    },
                    {
                        "account_name": "LIABILITY:ACCRUED_EXPENSES",
                        "entry_type": EntryType.CREDIT.value,
                        "amount_base_units": amount_int,
                    },
                ]
                mov = self.record_movement(
                    idempotency_key=f"mov:{clean_idempotency_key}",
                    agent_id=agent_id,
                    agent_account=agent_account,
                    owner_pubkey=owner_pubkey,
                    network=net_val,
                    genesis_hash=gen_val,
                    program_id=prog_val,
                    token_mint=mint_val,
                    amount_base_units=amount_int,
                    nature=MovementNature.PROVISION,
                    status=stat_enum,
                    provenance_source=prov_enum,
                    evidence_hash=evidence_hash,
                    attestation_id=attestation_id,
                    observed_at=incurred_time,
                    metadata={"cost_id": cost_id, "category": cat_enum.value},
                    custom_journal_legs=legs,
                    cursor=tx_cursor,
                )
                movement_id = mov.movement_id
                journal_entry_id = mov.journal_entry_id
            elif nat_enum == CostNature.REALIZED:
                if from_reserve_id:
                    # Realized expense covered by an existing capital reserve
                    tx_cursor.execute(
                        "SELECT * FROM agent_reserves WHERE reserve_id = ?;",
                        (from_reserve_id,),
                    )
                    res_row = tx_cursor.fetchone()
                    if not res_row:
                        raise LedgerValidationError(f"Reserve '{from_reserve_id}' not found")
                    if res_row["agent_account"] != agent_account:
                        raise LedgerValidationError("Reserve belongs to a different agent")
                    if res_row["network"] != net_val or res_row["token_mint"] != mint_val:
                        raise LedgerValidationError("Reserve network/mint mismatch")

                    cur_reserved = int(res_row["current_reserved_base_units"])
                    if amount_int > cur_reserved:
                        raise LedgerValidationError(
                            f"Insufficient funds in reserve '{from_reserve_id}': available {cur_reserved}, requested {amount_int}"
                        )

                    new_reserved = cur_reserved - amount_int
                    new_status = ReserveStatus.DEPLETED.value if new_reserved == 0 else ReserveStatus.ACTIVE.value
                    tx_cursor.execute(
                        "UPDATE agent_reserves SET current_reserved_base_units = ?, status = ?, updated_at = ? WHERE reserve_id = ?;",
                        (str(new_reserved), new_status, now, from_reserve_id),
                    )

                    meta["from_reserve_id"] = from_reserve_id
                    meta["consumed_from_reserve_type"] = res_row["reserve_type"]

                    # Legs debit expense and credit the reserved asset account (NOT treasury cash)
                    legs = [
                        {
                            "account_name": f"EXPENSE:{cat_enum.value}",
                            "entry_type": EntryType.DEBIT.value,
                            "amount_base_units": amount_int,
                        },
                        {
                            "account_name": f"ASSET:RESERVED:{res_row['reserve_type']}",
                            "entry_type": EntryType.CREDIT.value,
                            "amount_base_units": amount_int,
                        },
                    ]
                    mov = self.record_movement(
                        idempotency_key=f"mov:{clean_idempotency_key}",
                        agent_id=agent_id,
                        agent_account=agent_account,
                        owner_pubkey=owner_pubkey,
                        network=net_val,
                        genesis_hash=gen_val,
                        program_id=prog_val,
                        token_mint=mint_val,
                        amount_base_units=amount_int,
                        nature=MovementNature.EXPENSE,
                        status=stat_enum,
                        provenance_source=prov_enum,
                        evidence_hash=evidence_hash,
                        attestation_id=attestation_id,
                        observed_at=incurred_time,
                        metadata={"cost_id": cost_id, "from_reserve_id": from_reserve_id},
                        custom_journal_legs=legs,
                        cursor=tx_cursor,
                    )
                    movement_id = mov.movement_id
                    journal_entry_id = mov.journal_entry_id
                else:
                    # Direct realized operational expense paid from treasury
                    legs = [
                        {
                            "account_name": f"EXPENSE:{cat_enum.value}",
                            "entry_type": EntryType.DEBIT.value,
                            "amount_base_units": amount_int,
                        },
                        {
                            "account_name": "ASSET:TREASURY",
                            "entry_type": EntryType.CREDIT.value,
                            "amount_base_units": amount_int,
                        },
                    ]
                    mov = self.record_movement(
                        idempotency_key=f"mov:{clean_idempotency_key}",
                        agent_id=agent_id,
                        agent_account=agent_account,
                        owner_pubkey=owner_pubkey,
                        network=net_val,
                        genesis_hash=gen_val,
                        program_id=prog_val,
                        token_mint=mint_val,
                        amount_base_units=amount_int,
                        nature=MovementNature.EXPENSE,
                        status=stat_enum,
                        provenance_source=prov_enum,
                        evidence_hash=evidence_hash,
                        attestation_id=attestation_id,
                        observed_at=incurred_time,
                        metadata={"cost_id": cost_id, "category": cat_enum.value},
                        custom_journal_legs=legs,
                        cursor=tx_cursor,
                    )
                    movement_id = mov.movement_id
                    journal_entry_id = mov.journal_entry_id

            # 5. Insert into agent_costs
            tx_cursor.execute(
                """
                INSERT INTO agent_costs (
                    cost_id, idempotency_key, agent_id, agent_account, owner_pubkey,
                    category, cost_nature, economic_period, network, token_mint,
                    amount_base_units, amount_str, status, provenance_source,
                    evidence_hash, evidence_url, attestation_id, description,
                    journal_entry_id, movement_id, reversal_of_cost_id,
                    created_at, incurred_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    cost_id,
                    clean_idempotency_key,
                    agent_id,
                    agent_account,
                    owner_pubkey,
                    cat_enum.value,
                    nat_enum.value,
                    clean_period,
                    net_val,
                    mint_val,
                    amount_str,
                    amount_str,
                    stat_enum.value,
                    prov_enum.value,
                    evidence_hash,
                    evidence_url,
                    attestation_id,
                    description,
                    journal_entry_id,
                    movement_id,
                    None,
                    now,
                    incurred_time,
                    json.dumps(meta),
                ),
            )

            # 6. If drawn from reserve, record audit trail in reserve_transactions (after cost_id exists)
            if nat_enum == CostNature.REALIZED and from_reserve_id:
                rtx_id = f"rtx_{uuid.uuid4().hex[:16]}"
                tx_cursor.execute(
                    """
                    INSERT INTO reserve_transactions (
                        transaction_id, reserve_id, idempotency_key, action,
                        amount_base_units, associated_cost_id, journal_entry_id,
                        movement_id, created_at, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        rtx_id,
                        from_reserve_id,
                        f"consume:{clean_idempotency_key}",
                        ReserveAction.CONSUME.value,
                        amount_str,
                        cost_id,
                        journal_entry_id,
                        movement_id,
                        now,
                        json.dumps({"cost_id": cost_id, "category": cat_enum.value}),
                    ),
                )

            if manage_tx:
                tx_cursor.execute("COMMIT;")
        except Exception:
            if manage_tx:
                try:
                    tx_cursor.execute("ROLLBACK;")
                except Exception:
                    pass
            raise

        return self.get_cost(cost_id)  # type: ignore

    def get_cost(self, cost_id: str) -> Optional[AgentCost]:
        row = self._conn.execute(
            "SELECT * FROM agent_costs WHERE cost_id = ?;",
            (cost_id,),
        ).fetchone()
        return self._row_to_cost(row) if row else None

    def list_costs(
        self,
        agent_account: str,
        *,
        category: Optional[str | CostCategory] = None,
        cost_nature: Optional[str | CostNature] = None,
        economic_period: Optional[str] = None,
        status: Optional[str | MovementStatus] = None,
        network: Optional[str] = None,
        token_mint: Optional[str] = None,
        provenance_source: Optional[str | ProvenanceSource] = None,
        from_ts: Optional[int] = None,
        to_ts: Optional[int] = None,
        limit: int = 50,
        cursor: Optional[str] = None,
    ) -> tuple[list[AgentCost], Optional[str]]:
        conditions = ["agent_account = ?"]
        params: list[Any] = [agent_account]

        if category is not None:
            cat_val = category.value if isinstance(category, CostCategory) else category
            conditions.append("category = ?")
            params.append(cat_val)
        if cost_nature is not None:
            nat_val = cost_nature.value if isinstance(cost_nature, CostNature) else cost_nature
            conditions.append("cost_nature = ?")
            params.append(nat_val)
        if economic_period is not None:
            conditions.append("economic_period = ?")
            params.append(economic_period)
        if status is not None:
            st_val = status.value if isinstance(status, MovementStatus) else status
            conditions.append("status = ?")
            params.append(st_val)
        if network is not None:
            conditions.append("network = ?")
            params.append(network)
        if token_mint is not None:
            conditions.append("token_mint = ?")
            params.append(token_mint)
        if provenance_source is not None:
            ps_val = provenance_source.value if isinstance(provenance_source, ProvenanceSource) else provenance_source
            conditions.append("provenance_source = ?")
            params.append(ps_val)
        if from_ts is not None:
            conditions.append("incurred_at >= ?")
            params.append(from_ts)
        if to_ts is not None:
            conditions.append("incurred_at <= ?")
            params.append(to_ts)

        if cursor:
            try:
                raw_cursor = base64.b64decode(cursor).decode("utf-8")
                c_incurred_at, c_cost_id = raw_cursor.split(":", 1)
                conditions.append(
                    "(incurred_at < ? OR (incurred_at = ? AND cost_id < ?))"
                )
                params.extend([int(c_incurred_at), int(c_incurred_at), c_cost_id])
            except Exception as exc:
                raise LedgerValidationError("Invalid cursor token") from exc

        where_clause = " AND ".join(conditions)
        sql = f"""
            SELECT * FROM agent_costs
            WHERE {where_clause}
            ORDER BY incurred_at DESC, cost_id DESC
            LIMIT ?;
        """
        params.append(limit + 1)
        rows = self._conn.execute(sql, params).fetchall()
        has_more = len(rows) > limit
        item_rows = rows[:limit]
        costs = [self._row_to_cost(r) for r in item_rows]
        next_cursor = None
        if has_more and item_rows:
            last = item_rows[-1]
            token = f"{last['incurred_at']}:{last['cost_id']}"
            next_cursor = base64.b64encode(token.encode("utf-8")).decode("utf-8")
        return costs, next_cursor

    def revert_cost(
        self,
        cost_id: str,
        *,
        reason: str,
        authorized_by: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        cursor: Optional[sqlite3.Cursor] = None,
    ) -> tuple[AgentCost, AgentCost]:
        """Reverts an operational cost, emitting compensating accounting entries and restoring reserves."""
        effective_key = idempotency_key or f"revert_cost:{cost_id}"
        clean_idempotency_key = effective_key.strip()
        auth_clean = (authorized_by or "conatus:protocol:cost_reverser:v1").strip()

        manage_tx = (cursor is None)
        tx_cursor = cursor if cursor is not None else self._conn.cursor()
        if manage_tx:
            tx_cursor.execute("BEGIN IMMEDIATE;")
        try:
            tx_cursor.execute(
                "SELECT * FROM agent_costs WHERE cost_id = ?;",
                (cost_id,),
            )
            cost_row = tx_cursor.fetchone()
            if not cost_row:
                raise LedgerValidationError(f"Cost '{cost_id}' not found")

            orig_cost = self._row_to_cost(cost_row)
            if orig_cost.status == MovementStatus.REVERTED:
                tx_cursor.execute(
                    "SELECT * FROM agent_costs WHERE reversal_of_cost_id = ?;",
                    (cost_id,),
                )
                comp_row = tx_cursor.fetchone()
                if comp_row:
                    if manage_tx:
                        tx_cursor.execute("COMMIT;")
                    return orig_cost, self._row_to_cost(comp_row)
                raise LedgerValidationError(f"Cost '{cost_id}' already reverted")

            now = int(time.time())
            comp_cost_id = f"comp_{uuid.uuid4().hex[:16]}"
            comp_movement_id: Optional[str] = None
            comp_journal_id: Optional[str] = None

            # Revert movement if exists
            if orig_cost.movement_id:
                rev_mov, comp_mov = self.revert_movement(
                    orig_cost.movement_id,
                    reason=reason,
                    authorized_by=auth_clean,
                    cursor=tx_cursor,
                )
                comp_movement_id = comp_mov.movement_id
                comp_journal_id = comp_mov.journal_entry_id

            # If it was drawn from a reserve, restore the reserve balance
            from_res_id = orig_cost.metadata.get("from_reserve_id")
            if from_res_id:
                tx_cursor.execute(
                    "SELECT * FROM agent_reserves WHERE reserve_id = ?;",
                    (from_res_id,),
                )
                res_row = tx_cursor.fetchone()
                if res_row:
                    restored = int(res_row["current_reserved_base_units"]) + orig_cost.amount_base_units
                    tx_cursor.execute(
                        """
                        UPDATE agent_reserves
                        SET current_reserved_base_units = ?, status = 'ACTIVE', updated_at = ?
                        WHERE reserve_id = ?;
                        """,
                        (str(restored), now, from_res_id),
                    )
                    rtx_id = f"rtx_{uuid.uuid4().hex[:16]}"
                    tx_cursor.execute(
                        """
                        INSERT INTO reserve_transactions (
                            transaction_id, reserve_id, idempotency_key, action,
                            amount_base_units, associated_cost_id, journal_entry_id,
                            movement_id, created_at, metadata_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                        """,
                        (
                            rtx_id,
                            from_res_id,
                            f"restore:{clean_idempotency_key}",
                            ReserveAction.ALLOCATE.value,
                            orig_cost.amount_str,
                            cost_id,
                            comp_journal_id,
                            comp_movement_id,
                            now,
                            json.dumps({"reason": f"revert_cost:{reason}"}),
                        ),
                    )

            # Mark original cost as REVERTED
            tx_cursor.execute(
                "UPDATE agent_costs SET status = 'REVERTED' WHERE cost_id = ?;",
                (cost_id,),
            )

            # Insert compensating cost record
            comp_meta = {
                "reversal_of_cost_id": cost_id,
                "reason": reason,
                "authorized_by": auth_clean,
            }
            tx_cursor.execute(
                """
                INSERT INTO agent_costs (
                    cost_id, idempotency_key, agent_id, agent_account, owner_pubkey,
                    category, cost_nature, economic_period, network, token_mint,
                    amount_base_units, amount_str, status, provenance_source,
                    evidence_hash, evidence_url, attestation_id, description,
                    journal_entry_id, movement_id, reversal_of_cost_id,
                    created_at, incurred_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    comp_cost_id,
                    clean_idempotency_key,
                    orig_cost.agent_id,
                    orig_cost.agent_account,
                    orig_cost.owner_pubkey,
                    orig_cost.category.value,
                    orig_cost.cost_nature.value,
                    orig_cost.economic_period,
                    orig_cost.network,
                    orig_cost.token_mint,
                    orig_cost.amount_str,
                    orig_cost.amount_str,
                    MovementStatus.REVERTED.value,
                    ProvenanceSource.MANUAL_ENTRY.value,
                    None,
                    None,
                    None,
                    f"Compensating reversal of cost {cost_id}: {reason}",
                    comp_journal_id,
                    comp_movement_id,
                    cost_id,
                    now,
                    now,
                    json.dumps(comp_meta),
                ),
            )

            if manage_tx:
                tx_cursor.execute("COMMIT;")
        except Exception:
            if manage_tx:
                try:
                    tx_cursor.execute("ROLLBACK;")
                except Exception:
                    pass
            raise

        return self.get_cost(cost_id), self.get_cost(comp_cost_id)  # type: ignore

    # ─────────────────────────────────────────────────────────────────────────
    # CON-24: Economic Reserves Management
    # ─────────────────────────────────────────────────────────────────────────

    def create_or_allocate_reserve(
        self,
        *,
        idempotency_key: str,
        agent_id: str,
        agent_account: str,
        owner_pubkey: str,
        reserve_type: str | ReserveType,
        amount_base_units: int | str,
        network: str,
        token_mint: str,
        genesis_hash: Optional[str] = None,
        program_id: Optional[str] = None,
        target_amount_base_units: Optional[int | str] = None,
        description: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
        cursor: Optional[sqlite3.Cursor] = None,
    ) -> AgentReserve:
        """Allocates unencumbered treasury capital into an agent reserve fund.

        A reserve is capital segregation, NOT an expense, and does not reduce agent net worth.
        NOTE: Off-chain accounting reserves do not directly freeze SPL tokens on Solana.
        """
        if not idempotency_key or not idempotency_key.strip():
            raise LedgerValidationError("idempotency_key cannot be empty")
        clean_idempotency_key = idempotency_key.strip()

        try:
            type_enum = ReserveType(reserve_type)
        except ValueError as exc:
            raise LedgerValidationError(f"Invalid reserve type: {reserve_type}") from exc

        amount_int = validate_base_units(amount_base_units, allow_zero=False)
        amount_str = str(amount_int)
        now = int(time.time())

        # Monetary context validation
        net_val, gen_val, prog_val, mint_val = validate_monetary_context(
            network=network,
            genesis_hash=genesis_hash,
            program_id=program_id,
            token_mint=token_mint,
        )

        manage_tx = (cursor is None)
        tx_cursor = cursor if cursor is not None else self._conn.cursor()
        if manage_tx:
            tx_cursor.execute("BEGIN IMMEDIATE;")
        try:
            # Check idempotency on reserve transaction
            tx_cursor.execute(
                "SELECT * FROM reserve_transactions WHERE idempotency_key = ?;",
                (clean_idempotency_key,),
            )
            existing_tx = tx_cursor.fetchone()
            if existing_tx:
                res = self.get_reserve(existing_tx["reserve_id"])
                if res:
                    if manage_tx:
                        tx_cursor.execute("COMMIT;")
                    return res

            # Reconciled Capital Availability Check strictly from ASSET:TREASURY in the partition (net_val, gen_val, mint_val)
            tx_cursor.execute(
                """
                SELECT
                    le.entry_type,
                    le.amount_base_units,
                    je.status
                FROM ledger_entries le
                JOIN journal_entries je ON le.journal_entry_id = je.journal_entry_id
                WHERE le.agent_account = ?
                  AND le.account_name = 'ASSET:TREASURY'
                  AND je.network = ?
                  AND je.genesis_hash = ?
                  AND je.token_mint = ?;
                """,
                (agent_account, net_val, gen_val, mint_val),
            )
            rows = tx_cursor.fetchall()
            rec_debits = 0
            all_credits = 0
            for r in rows:
                amt = int(r["amount_base_units"])
                if r["entry_type"] == EntryType.DEBIT.value:
                    if r["status"] == MovementStatus.RECONCILED.value:
                        rec_debits += amt
                elif r["entry_type"] == EntryType.CREDIT.value:
                    all_credits += amt

            reconciled_available = rec_debits - all_credits
            if reconciled_available <= 0 or amount_int > reconciled_available:
                raise LedgerValidationError(
                    f"Insufficient reconciled funds in ASSET:TREASURY: available {max(0, reconciled_available)}, requested {amount_int}. "
                    f"Reserves cannot be funded from provisional or simulated income."
                )

            # Check if an existing reserve exists for (agent_account, reserve_type, network, token_mint)
            tx_cursor.execute(
                """
                SELECT * FROM agent_reserves
                WHERE agent_account = ? AND reserve_type = ? AND network = ? AND token_mint = ?;
                """,
                (agent_account, type_enum.value, net_val, mint_val),
            )
            existing_res = tx_cursor.fetchone()

            if existing_res:
                reserve_id = existing_res["reserve_id"]
                cur_reserved = int(existing_res["current_reserved_base_units"]) + amount_int
                target_int = int(existing_res["target_amount_base_units"]) if target_amount_base_units is None else validate_base_units(target_amount_base_units, allow_zero=True)
                tx_cursor.execute(
                    """
                    UPDATE agent_reserves
                    SET current_reserved_base_units = ?, target_amount_base_units = ?, status = 'ACTIVE', updated_at = ?
                    WHERE reserve_id = ?;
                    """,
                    (str(cur_reserved), str(target_int), now, reserve_id),
                )
            else:
                reserve_id = f"res_{uuid.uuid4().hex[:16]}"
                target_int = amount_int if target_amount_base_units is None else validate_base_units(target_amount_base_units, allow_zero=True)
                tx_cursor.execute(
                    """
                    INSERT INTO agent_reserves (
                        reserve_id, idempotency_key, agent_id, agent_account, owner_pubkey,
                        reserve_type, network, token_mint, target_amount_base_units,
                        current_reserved_base_units, status, created_at, updated_at,
                        description, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        reserve_id,
                        clean_idempotency_key,
                        agent_id,
                        agent_account,
                        owner_pubkey,
                        type_enum.value,
                        net_val,
                        mint_val,
                        str(target_int),
                        amount_str,
                        ReserveStatus.ACTIVE.value,
                        now,
                        now,
                        description,
                        json.dumps(metadata or {}),
                    ),
                )

            # Double-entry: Debit ASSET:RESERVED:<TYPE>, Credit ASSET:TREASURY
            legs = [
                {
                    "account_name": f"ASSET:RESERVED:{type_enum.value}",
                    "entry_type": EntryType.DEBIT.value,
                    "amount_base_units": amount_int,
                },
                {
                    "account_name": "ASSET:TREASURY",
                    "entry_type": EntryType.CREDIT.value,
                    "amount_base_units": amount_int,
                },
            ]
            mov = self.record_movement(
                idempotency_key=f"mov_res:{clean_idempotency_key}",
                agent_id=agent_id,
                agent_account=agent_account,
                owner_pubkey=owner_pubkey,
                network=net_val,
                genesis_hash=gen_val,
                program_id=prog_val,
                token_mint=mint_val,
                amount_base_units=amount_int,
                nature=MovementNature.RESERVE,
                status=MovementStatus.PROVISIONAL,
                provenance_source=ProvenanceSource.MANUAL_ENTRY,
                observed_at=now,
                metadata={"reserve_id": reserve_id, "reserve_type": type_enum.value},
                custom_journal_legs=legs,
                cursor=tx_cursor,
            )

            rtx_id = f"rtx_{uuid.uuid4().hex[:16]}"
            tx_cursor.execute(
                """
                INSERT INTO reserve_transactions (
                    transaction_id, reserve_id, idempotency_key, action,
                    amount_base_units, associated_cost_id, journal_entry_id,
                    movement_id, created_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    rtx_id,
                    reserve_id,
                    clean_idempotency_key,
                    ReserveAction.ALLOCATE.value,
                    amount_str,
                    None,
                    mov.journal_entry_id,
                    mov.movement_id,
                    now,
                    json.dumps(metadata or {}),
                ),
            )

            if manage_tx:
                tx_cursor.execute("COMMIT;")
        except Exception:
            if manage_tx:
                try:
                    tx_cursor.execute("ROLLBACK;")
                except Exception:
                    pass
            raise

        return self.get_reserve(reserve_id)  # type: ignore

    def release_reserve(
        self,
        *,
        idempotency_key: str,
        reserve_id: str,
        amount_base_units: int | str,
        reason: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
        cursor: Optional[sqlite3.Cursor] = None,
    ) -> AgentReserve:
        """Releases segregated reserve funds back to available unencumbered treasury."""
        if not idempotency_key or not idempotency_key.strip():
            raise LedgerValidationError("idempotency_key cannot be empty")
        clean_idempotency_key = idempotency_key.strip()

        manage_tx = (cursor is None)
        tx_cursor = cursor if cursor is not None else self._conn.cursor()
        if manage_tx:
            tx_cursor.execute("BEGIN IMMEDIATE;")
        try:
            tx_cursor.execute(
                "SELECT * FROM agent_reserves WHERE reserve_id = ?;",
                (reserve_id,),
            )
            res_row = tx_cursor.fetchone()
            if not res_row:
                raise LedgerValidationError(f"Reserve '{reserve_id}' not found")

            amount_int = validate_base_units(amount_base_units, allow_zero=False)
            amount_str = str(amount_int)
            cur_reserved = int(res_row["current_reserved_base_units"])
            if amount_int > cur_reserved:
                raise LedgerValidationError(
                    f"Release amount ({amount_int}) exceeds current reserve balance ({cur_reserved})"
                )

            now = int(time.time())

            # Check idempotency
            tx_cursor.execute(
                "SELECT * FROM reserve_transactions WHERE idempotency_key = ?;",
                (clean_idempotency_key,),
            )
            existing_tx = tx_cursor.fetchone()
            if existing_tx:
                res = self.get_reserve(reserve_id)
                if res:
                    if manage_tx:
                        tx_cursor.execute("COMMIT;")
                    return res

            new_reserved = cur_reserved - amount_int
            new_status = ReserveStatus.CLOSED.value if new_reserved == 0 else ReserveStatus.ACTIVE.value
            tx_cursor.execute(
                """
                UPDATE agent_reserves
                SET current_reserved_base_units = ?, status = ?, updated_at = ?
                WHERE reserve_id = ?;
                """,
                (str(new_reserved), new_status, now, reserve_id),
            )

            # Releasing a reserve returns funds to ASSET:TREASURY as RECONCILED
            net_val, gen_val, prog_val, mint_val = validate_monetary_context(
                network=res_row["network"],
                token_mint=res_row["token_mint"],
            )

            # Double-entry: Debit ASSET:TREASURY, Credit ASSET:RESERVED:<TYPE>
            legs = [
                {
                    "account_name": "ASSET:TREASURY",
                    "entry_type": EntryType.DEBIT.value,
                    "amount_base_units": amount_int,
                },
                {
                    "account_name": f"ASSET:RESERVED:{res_row['reserve_type']}",
                    "entry_type": EntryType.CREDIT.value,
                    "amount_base_units": amount_int,
                },
            ]
            mov = self.record_movement(
                idempotency_key=f"mov_rel:{clean_idempotency_key}",
                agent_id=res_row["agent_id"],
                agent_account=res_row["agent_account"],
                owner_pubkey=res_row["owner_pubkey"],
                network=net_val,
                genesis_hash=gen_val,
                program_id=prog_val,
                token_mint=mint_val,
                amount_base_units=amount_int,
                nature=MovementNature.ADJUSTMENT,
                status=MovementStatus.RECONCILED,
                provenance_source=ProvenanceSource.MANUAL_ENTRY,
                observed_at=now,
                metadata={"reserve_id": reserve_id, "action": "release", "reason": reason},
                custom_journal_legs=legs,
                cursor=tx_cursor,
            )

            rtx_id = f"rtx_{uuid.uuid4().hex[:16]}"
            tx_cursor.execute(
                """
                INSERT INTO reserve_transactions (
                    transaction_id, reserve_id, idempotency_key, action,
                    amount_base_units, associated_cost_id, journal_entry_id,
                    movement_id, created_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    rtx_id,
                    reserve_id,
                    clean_idempotency_key,
                    ReserveAction.RELEASE.value,
                    amount_str,
                    None,
                    mov.journal_entry_id,
                    mov.movement_id,
                    now,
                    json.dumps({"reason": reason}),
                ),
            )

            if manage_tx:
                tx_cursor.execute("COMMIT;")
        except Exception:
            if manage_tx:
                try:
                    tx_cursor.execute("ROLLBACK;")
                except Exception:
                    pass
            raise

        return self.get_reserve(reserve_id)  # type: ignore

    def get_reserve(self, reserve_id: str) -> Optional[AgentReserve]:
        row = self._conn.execute(
            "SELECT * FROM agent_reserves WHERE reserve_id = ?;",
            (reserve_id,),
        ).fetchone()
        return self._row_to_reserve(row) if row else None

    def list_reserves(
        self,
        agent_account: str,
        *,
        reserve_type: Optional[str | ReserveType] = None,
        status: Optional[str | ReserveStatus] = None,
        network: Optional[str] = None,
        token_mint: Optional[str] = None,
    ) -> list[AgentReserve]:
        conditions = ["agent_account = ?"]
        params: list[Any] = [agent_account]
        if reserve_type is not None:
            rt_val = reserve_type.value if isinstance(reserve_type, ReserveType) else reserve_type
            conditions.append("reserve_type = ?")
            params.append(rt_val)
        if status is not None:
            st_val = status.value if isinstance(status, ReserveStatus) else status
            conditions.append("status = ?")
            params.append(st_val)
        if network is not None:
            conditions.append("network = ?")
            params.append(network)
        if token_mint is not None:
            conditions.append("token_mint = ?")
            params.append(token_mint)

        where_clause = " AND ".join(conditions)
        sql = f"SELECT * FROM agent_reserves WHERE {where_clause} ORDER BY created_at DESC;"
        rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_reserve(r) for r in rows]

    # ─────────────────────────────────────────────────────────────────────────
    # CON-24: Internal Transfers & Capital Investments
    # ─────────────────────────────────────────────────────────────────────────

    def record_internal_transfer(
        self,
        *,
        idempotency_key: str,
        agent_id: str,
        agent_account: str,
        owner_pubkey: str,
        source_account_name: str,
        destination_account_name: str,
        amount_base_units: int | str,
        network: str,
        token_mint: str,
        genesis_hash: Optional[str] = None,
        program_id: Optional[str] = None,
        description: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
        cursor: Optional[sqlite3.Cursor] = None,
    ) -> EconomicMovement:
        """Records an internal transfer between accounts of an agent without altering net worth or expenses."""
        amount_int = validate_base_units(amount_base_units, allow_zero=False)
        now = int(time.time())
        net_val, gen_val, prog_val, mint_val = validate_monetary_context(
            network=network,
            genesis_hash=genesis_hash,
            program_id=program_id,
            token_mint=token_mint,
        )
        legs = [
            {
                "account_name": destination_account_name,
                "entry_type": EntryType.DEBIT.value,
                "amount_base_units": amount_int,
            },
            {
                "account_name": source_account_name,
                "entry_type": EntryType.CREDIT.value,
                "amount_base_units": amount_int,
            },
        ]
        meta = dict(metadata or {})
        meta["source_account"] = source_account_name
        meta["destination_account"] = destination_account_name
        if description:
            meta["description"] = description
        return self.record_movement(
            idempotency_key=idempotency_key,
            agent_id=agent_id,
            agent_account=agent_account,
            owner_pubkey=owner_pubkey,
            network=net_val,
            genesis_hash=gen_val,
            program_id=prog_val,
            token_mint=mint_val,
            amount_base_units=amount_int,
            nature=MovementNature.INTERNAL_TRANSFER,
            status=MovementStatus.PROVISIONAL,
            provenance_source=ProvenanceSource.MANUAL_ENTRY,
            observed_at=now,
            metadata=meta,
            custom_journal_legs=legs,
            cursor=cursor,
        )

    def record_capital_investment(
        self,
        *,
        idempotency_key: str,
        agent_id: str,
        agent_account: str,
        owner_pubkey: str,
        amount_base_units: int | str,
        network: str,
        token_mint: str,
        asset_name: Optional[str] = None,
        asset_category: Optional[str] = None,
        genesis_hash: Optional[str] = None,
        program_id: Optional[str] = None,
        description: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
        cursor: Optional[sqlite3.Cursor] = None,
    ) -> EconomicMovement:
        """Records a capital expenditure (CAPEX) into hardware or fixed operational assets."""
        effective_asset_name = asset_name or asset_category or "EQUIPMENT"
        amount_int = validate_base_units(amount_base_units, allow_zero=False)
        now = int(time.time())
        net_val, gen_val, prog_val, mint_val = validate_monetary_context(
            network=network,
            genesis_hash=genesis_hash,
            program_id=program_id,
            token_mint=token_mint,
        )
        legs = [
            {
                "account_name": f"ASSET:{effective_asset_name}",
                "entry_type": EntryType.DEBIT.value,
                "amount_base_units": amount_int,
            },
            {
                "account_name": "ASSET:TREASURY",
                "entry_type": EntryType.CREDIT.value,
                "amount_base_units": amount_int,
            },
        ]
        meta = dict(metadata or {})
        meta["asset_name"] = effective_asset_name
        if description:
            meta["description"] = description
        return self.record_movement(
            idempotency_key=idempotency_key,
            agent_id=agent_id,
            agent_account=agent_account,
            owner_pubkey=owner_pubkey,
            network=net_val,
            genesis_hash=gen_val,
            program_id=prog_val,
            token_mint=mint_val,
            amount_base_units=amount_int,
            nature=MovementNature.CAPITAL_INVESTMENT,
            status=MovementStatus.PROVISIONAL,
            provenance_source=ProvenanceSource.MANUAL_ENTRY,
            observed_at=now,
            metadata=meta,
            custom_journal_legs=legs,
            cursor=cursor,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # CON-24: Comprehensive Agent Economic Summary
    # ─────────────────────────────────────────────────────────────────────────

    def get_economic_summary(
        self,
        agent_account: str,
        *,
        network: Optional[str] = None,
        token_mint: Optional[str] = None,
        economic_period: Optional[str] = None,
    ) -> list[AgentEconomicSummary]:
        """Calculates a comprehensive economic report distinguishing revenue, expenses,

        pending obligations, budget estimations, and segregated capital reserves.
        """
        # Discover all (network, token_mint) partitions for the agent
        sql_parts = """
            SELECT DISTINCT network, token_mint FROM economic_movements WHERE agent_account = ?
            UNION
            SELECT DISTINCT network, token_mint FROM agent_costs WHERE agent_account = ?
            UNION
            SELECT DISTINCT network, token_mint FROM agent_reserves WHERE agent_account = ?;
        """
        rows = self._conn.execute(sql_parts, (agent_account, agent_account, agent_account)).fetchall()
        found_pairs = {(r["network"], r["token_mint"]) for r in rows}
        if network and token_mint:
            found_pairs = {(network, token_mint)}
        elif network:
            found_pairs = {p for p in found_pairs if p[0] == network}
        elif token_mint:
            found_pairs = {p for p in found_pairs if p[1] == token_mint}

        summaries = []
        for net, mint in sorted(found_pairs):
            # 1. Income from economic_movements
            inc_rows = self._conn.execute(
                """
                SELECT status, amount_base_units FROM economic_movements
                WHERE agent_account = ? AND network = ? AND token_mint = ? AND nature = 'INCOME';
                """,
                (agent_account, net, mint),
            ).fetchall()
            inc_reconciled = 0
            inc_provisional = 0
            for ir in inc_rows:
                amt = int(ir["amount_base_units"])
                if ir["status"] == MovementStatus.RECONCILED.value:
                    inc_reconciled += amt
                elif ir["status"] == MovementStatus.PROVISIONAL.value:
                    inc_provisional += amt

            # 2. Costs from agent_costs
            cost_query = """
                SELECT category, cost_nature, status, amount_base_units FROM agent_costs
                WHERE agent_account = ? AND network = ? AND token_mint = ?
            """
            cost_params: list[Any] = [agent_account, net, mint]
            if economic_period is not None:
                cost_query += " AND economic_period = ?"
                cost_params.append(economic_period)

            cost_rows = self._conn.execute(cost_query, cost_params).fetchall()
            realized_exp = 0
            accrued_obs = 0
            estimated_c = 0
            by_category: dict[str, int] = {cat.value: 0 for cat in CostCategory}

            for cr in cost_rows:
                if cr["status"] == MovementStatus.REVERTED.value:
                    continue
                amt = int(cr["amount_base_units"])
                c_nature = cr["cost_nature"]
                c_cat = cr["category"]

                if c_nature == CostNature.REALIZED.value:
                    realized_exp += amt
                    if c_cat in by_category:
                        by_category[c_cat] += amt
                elif c_nature == CostNature.ACCRUED_LIABILITY.value:
                    accrued_obs += amt
                elif c_nature == CostNature.ESTIMATED.value:
                    estimated_c += amt

            # 3. Capital Reserves from agent_reserves
            res_rows = self._conn.execute(
                """
                SELECT reserve_type, current_reserved_base_units FROM agent_reserves
                WHERE agent_account = ? AND network = ? AND token_mint = ? AND status = 'ACTIVE';
                """,
                (agent_account, net, mint),
            ).fetchall()
            by_reserve: dict[str, int] = {rt.value: 0 for rt in ReserveType}
            total_reserved = 0
            for rr in res_rows:
                amt = int(rr["current_reserved_base_units"])
                total_reserved += amt
                r_type = rr["reserve_type"]
                if r_type in by_reserve:
                    by_reserve[r_type] += amt

            # 4. CAPEX Fixed Assets from General Ledger
            capex_rows = self._conn.execute(
                """
                SELECT le.entry_type, le.amount_base_units
                FROM ledger_entries le
                JOIN journal_entries je ON le.journal_entry_id = je.journal_entry_id
                WHERE le.agent_account = ?
                  AND je.network = ?
                  AND je.token_mint = ?
                  AND le.account_name LIKE 'ASSET:%'
                  AND le.account_name != 'ASSET:TREASURY'
                  AND NOT le.account_name LIKE 'ASSET:RESERVED:%';
                """,
                (agent_account, net, mint),
            ).fetchall()
            capex_total = 0
            for c_row in capex_rows:
                c_amt = int(c_row["amount_base_units"])
                if c_row["entry_type"] == EntryType.DEBIT.value:
                    capex_total += c_amt
                elif c_row["entry_type"] == EntryType.CREDIT.value:
                    capex_total -= c_amt
            capex_investments = max(0, capex_total)

            # 5. General Ledger Treasury Balance (ASSET:TREASURY)
            # Calculated directly from the General Ledger, avoiding double deductions of reserves or expenses.
            # Considers CAPEX, internal transfers, and reversions.
            treasury_rows = self._conn.execute(
                """
                SELECT le.entry_type, le.amount_base_units, je.status
                FROM ledger_entries le
                JOIN journal_entries je ON le.journal_entry_id = je.journal_entry_id
                WHERE le.agent_account = ?
                  AND le.account_name = 'ASSET:TREASURY'
                  AND je.network = ?
                  AND je.token_mint = ?;
                """,
                (agent_account, net, mint),
            ).fetchall()
            treasury_rec_debits = 0
            treasury_all_credits = 0
            for t_row in treasury_rows:
                t_amt = int(t_row["amount_base_units"])
                if t_row["entry_type"] == EntryType.DEBIT.value:
                    if t_row["status"] == MovementStatus.RECONCILED.value:
                        treasury_rec_debits += t_amt
                elif t_row["entry_type"] == EntryType.CREDIT.value:
                    treasury_all_credits += t_amt

            avail = max(0, treasury_rec_debits - treasury_all_credits)
            surplus = max(0, avail - accrued_obs)
            tot_effective = inc_reconciled + inc_provisional - realized_exp

            summaries.append(
                AgentEconomicSummary(
                    agent_account=agent_account,
                    network=net,
                    token_mint=mint,
                    total_income_reconciled=inc_reconciled,
                    total_income_provisional=inc_provisional,
                    total_expenses_realized=realized_exp,
                    total_obligations_accrued=accrued_obs,
                    total_estimated_costs=estimated_c,
                    total_capital_reserved=total_reserved,
                    available_balance=avail,
                    total_effective_balance=tot_effective,
                    investible_surplus=surplus,
                    capex_investments=capex_investments,
                    total_income_reconciled_str=str(inc_reconciled),
                    total_income_provisional_str=str(inc_provisional),
                    total_expenses_realized_str=str(realized_exp),
                    total_obligations_accrued_str=str(accrued_obs),
                    total_estimated_costs_str=str(estimated_c),
                    total_capital_reserved_str=str(total_reserved),
                    available_balance_str=str(avail),
                    total_effective_balance_str=str(tot_effective),
                    investible_surplus_str=str(surplus),
                    capex_investments_str=str(capex_investments),
                    costs_by_category=by_category,
                    reserves_by_type=by_reserve,
                )
            )

        return summaries

        return summaries

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
        elif nature == MovementNature.PROVISION:
            return [
                LedgerLeg(
                    entry_id=str(uuid.uuid4()),
                    journal_entry_id=journal_entry_id,
                    account_name="EXPENSE:PROVISION",
                    entry_type=EntryType.DEBIT,
                    amount_base_units=amount_base_units,
                    agent_account=agent_account,
                    created_at=created_at,
                ),
                LedgerLeg(
                    entry_id=str(uuid.uuid4()),
                    journal_entry_id=journal_entry_id,
                    account_name="LIABILITY:ACCRUED_EXPENSES",
                    entry_type=EntryType.CREDIT,
                    amount_base_units=amount_base_units,
                    agent_account=agent_account,
                    created_at=created_at,
                ),
            ]
        elif nature == MovementNature.INTERNAL_TRANSFER:
            return [
                LedgerLeg(
                    entry_id=str(uuid.uuid4()),
                    journal_entry_id=journal_entry_id,
                    account_name="ASSET:OPERATIONAL_FLOAT",
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
        elif nature == MovementNature.CAPITAL_INVESTMENT:
            return [
                LedgerLeg(
                    entry_id=str(uuid.uuid4()),
                    journal_entry_id=journal_entry_id,
                    account_name="ASSET:EQUIPMENT_CAPITAL",
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

    @staticmethod
    def _row_to_cost(row: sqlite3.Row) -> AgentCost:
        meta = {}
        if row["metadata_json"]:
            try:
                meta = json.loads(row["metadata_json"])
            except Exception:
                meta = {}

        return AgentCost(
            cost_id=row["cost_id"],
            idempotency_key=row["idempotency_key"],
            agent_id=row["agent_id"],
            agent_account=row["agent_account"],
            owner_pubkey=row["owner_pubkey"],
            category=CostCategory(row["category"]),
            cost_nature=CostNature(row["cost_nature"]),
            economic_period=row["economic_period"],
            network=row["network"],
            token_mint=row["token_mint"],
            amount_base_units=int(row["amount_base_units"]),
            amount_str=str(row["amount_str"]),
            status=MovementStatus(row["status"]),
            provenance_source=ProvenanceSource(row["provenance_source"]),
            created_at=int(row["created_at"]),
            incurred_at=int(row["incurred_at"]),
            journal_entry_id=row["journal_entry_id"],
            movement_id=row["movement_id"],
            evidence_hash=row["evidence_hash"],
            evidence_url=row["evidence_url"],
            attestation_id=row["attestation_id"],
            description=row["description"],
            reversal_of_cost_id=row["reversal_of_cost_id"],
            metadata=meta,
        )

    @staticmethod
    def _row_to_reserve(row: sqlite3.Row) -> AgentReserve:
        meta = {}
        if row["metadata_json"]:
            try:
                meta = json.loads(row["metadata_json"])
            except Exception:
                meta = {}

        return AgentReserve(
            reserve_id=row["reserve_id"],
            idempotency_key=row["idempotency_key"],
            agent_id=row["agent_id"],
            agent_account=row["agent_account"],
            owner_pubkey=row["owner_pubkey"],
            reserve_type=ReserveType(row["reserve_type"]),
            network=row["network"],
            token_mint=row["token_mint"],
            target_amount_base_units=int(row["target_amount_base_units"]),
            current_reserved_base_units=int(row["current_reserved_base_units"]),
            status=ReserveStatus(row["status"]),
            created_at=int(row["created_at"]),
            updated_at=int(row["updated_at"]),
            description=row["description"],
            metadata=meta,
        )

    @staticmethod
    def _row_to_reserve_tx(row: sqlite3.Row) -> ReserveTransaction:
        meta = {}
        if row["metadata_json"]:
            try:
                meta = json.loads(row["metadata_json"])
            except Exception:
                meta = {}

        return ReserveTransaction(
            transaction_id=row["transaction_id"],
            reserve_id=row["reserve_id"],
            idempotency_key=row["idempotency_key"],
            action=ReserveAction(row["action"]),
            amount_base_units=int(row["amount_base_units"]),
            created_at=int(row["created_at"]),
            associated_cost_id=row["associated_cost_id"],
            journal_entry_id=row["journal_entry_id"],
            movement_id=row["movement_id"],
            metadata=meta,
        )
