"""Data models, enums and validation for the persistent economic ledger."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Optional


class MovementNature(str, Enum):
    INCOME = "INCOME"          # Ingreso obtenido por misiones o transferencias entrantes
    EXPENSE = "EXPENSE"        # Gasto operativo (energía, mantenimiento, seguro, red)
    RESERVE = "RESERVE"        # Fondos congelados o en garantía/slashable bond
    ADJUSTMENT = "ADJUSTMENT"  # Asiento corrector, compensatorio o reclasificación


class MovementStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"  # Registrado pero pendiente de confirmación/conciliación
    RECONCILED = "RECONCILED"    # Verificado y conciliado con la fuente
    REVERTED = "REVERTED"        # Anulado/revertido mediante asiento compensatorio


class ProvenanceSource(str, Enum):
    ONCHAIN_VERIFIED = "ONCHAIN_VERIFIED"
    EXTERNAL_VERIFIED = "EXTERNAL_VERIFIED"
    SIMULATED = "SIMULATED"
    MANUAL_ENTRY = "MANUAL_ENTRY"
    SETTLEMENT_EVENT = "SETTLEMENT_EVENT"


class EntryType(str, Enum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


class LedgerValidationError(Exception):
    """Raised when an economic metric or entry violates accounting invariants."""
    pass


class IdempotencyConflictError(LedgerValidationError):
    """Raised when an idempotency key is reused with mismatched payload parameters."""
    pass


def validate_base_units(amount: Any, allow_zero: bool = False) -> int:
    """Validate that amount is an exact integer in base units, rejecting floating point."""
    if isinstance(amount, float):
        raise LedgerValidationError(
            f"Floating point values not permitted in monetary operations: {amount!r}"
        )
    if isinstance(amount, str):
        if not amount.isdigit():
            raise LedgerValidationError(
                f"Amount string must contain only digits: {amount!r}"
            )
        val = int(amount)
    elif isinstance(amount, int):
        val = amount
    else:
        raise LedgerValidationError(
            f"Amount must be integer or digit string, got {type(amount).__name__}"
        )

    if allow_zero:
        if val < 0:
            raise LedgerValidationError(f"Amount must be non-negative (>= 0), got {val}")
    else:
        if val <= 0:
            raise LedgerValidationError(f"Amount must be strictly positive (> 0), got {val}")
    return val


@dataclass(frozen=True)
class LedgerLeg:
    entry_id: str
    journal_entry_id: str
    account_name: str
    entry_type: EntryType
    amount_base_units: int
    agent_account: Optional[str] = None
    created_at: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "journal_entry_id": self.journal_entry_id,
            "agent_account": self.agent_account,
            "account_name": self.account_name,
            "entry_type": self.entry_type.value if isinstance(self.entry_type, EntryType) else self.entry_type,
            "amount_base_units": self.amount_base_units,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class JournalEntry:
    journal_entry_id: str
    idempotency_key: str
    network: str
    genesis_hash: str
    program_id: str
    token_mint: str
    description: str
    status: MovementStatus
    created_at: int
    observed_at: int
    tx_signature: Optional[str] = None
    work_order_account: Optional[str] = None
    legs: list[LedgerLeg] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "journal_entry_id": self.journal_entry_id,
            "idempotency_key": self.idempotency_key,
            "network": self.network,
            "genesis_hash": self.genesis_hash,
            "program_id": self.program_id,
            "token_mint": self.token_mint,
            "description": self.description,
            "status": self.status.value if isinstance(self.status, MovementStatus) else self.status,
            "created_at": self.created_at,
            "observed_at": self.observed_at,
            "tx_signature": self.tx_signature,
            "work_order_account": self.work_order_account,
            "legs": [leg.to_dict() for leg in self.legs],
        }


@dataclass(frozen=True)
class EconomicMovement:
    movement_id: str
    idempotency_key: str
    agent_id: str
    agent_account: str
    owner_pubkey: str
    network: str
    genesis_hash: str
    program_id: str
    token_mint: str
    amount_base_units: int
    amount_str: str
    nature: MovementNature
    status: MovementStatus
    provenance_source: ProvenanceSource
    registered_at: int
    observed_at: int
    journal_entry_id: Optional[str] = None
    work_order_account: Optional[str] = None
    work_order_id: Optional[str] = None
    evidence_hash: Optional[str] = None
    attestation_id: Optional[str] = None
    tx_signature: Optional[str] = None
    external_ref: Optional[str] = None
    reversal_of_movement_id: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "movement_id": self.movement_id,
            "journal_entry_id": self.journal_entry_id,
            "idempotency_key": self.idempotency_key,
            "agent_id": self.agent_id,
            "agent_account": self.agent_account,
            "owner_pubkey": self.owner_pubkey,
            "work_order_account": self.work_order_account,
            "work_order_id": self.work_order_id,
            "network": self.network,
            "genesis_hash": self.genesis_hash,
            "program_id": self.program_id,
            "token_mint": self.token_mint,
            "amount_base_units": self.amount_base_units,
            "amount_str": self.amount_str,
            "nature": self.nature.value if isinstance(self.nature, MovementNature) else self.nature,
            "status": self.status.value if isinstance(self.status, MovementStatus) else self.status,
            "provenance_source": self.provenance_source.value if isinstance(self.provenance_source, ProvenanceSource) else self.provenance_source,
            "evidence_hash": self.evidence_hash,
            "attestation_id": self.attestation_id,
            "tx_signature": self.tx_signature,
            "external_ref": self.external_ref,
            "registered_at": self.registered_at,
            "observed_at": self.observed_at,
            "reversal_of_movement_id": self.reversal_of_movement_id,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class BalanceReport:
    agent_account: str
    network: str
    token_mint: str
    reconciled_balance: int
    provisional_balance: int
    reserved_balance: int
    reconciled_balance_str: str
    provisional_balance_str: str
    reserved_balance_str: str
    total_effective_balance: int
    total_effective_balance_str: str
    movement_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_account": self.agent_account,
            "network": self.network,
            "token_mint": self.token_mint,
            "reconciled_balance": self.reconciled_balance,
            "provisional_balance": self.provisional_balance,
            "reserved_balance": self.reserved_balance,
            "reconciled_balance_str": self.reconciled_balance_str,
            "provisional_balance_str": self.provisional_balance_str,
            "reserved_balance_str": self.reserved_balance_str,
            "total_effective_balance": self.total_effective_balance,
            "total_effective_balance_str": self.total_effective_balance_str,
            "movement_count": self.movement_count,
        }
