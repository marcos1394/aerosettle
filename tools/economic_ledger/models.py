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
    PROVISION = "PROVISION"    # Provisión de gasto futuro o pasivo devengado
    INTERNAL_TRANSFER = "INTERNAL_TRANSFER"  # Transferencia interna entre cuentas del agente
    CAPITAL_INVESTMENT = "CAPITAL_INVESTMENT"  # Inversión de capital en activos fijos (CAPEX)


class CostCategory(str, Enum):
    ENERGY_FUEL = "ENERGY_FUEL"                          # Energía y combustible
    MAINTENANCE = "MAINTENANCE"                          # Mantenimiento preventivo y correctivo
    CONNECTIVITY_COMPUTE = "CONNECTIVITY_COMPUTE"        # Conectividad y cómputo
    SUBSCRIPTIONS = "SUBSCRIPTIONS"                      # Suscripciones y servicios contratados
    INSURANCE = "INSURANCE"                              # Seguros
    DEPRECIATION_REPLACEMENT = "DEPRECIATION_REPLACEMENT"# Depreciación y reposición de activos
    OTHER = "OTHER"                                      # Otros costos documentados


class CostNature(str, Enum):
    REALIZED = "REALIZED"                    # Gasto efectivamente realizado / pagado
    ESTIMATED = "ESTIMATED"                  # Estimación / proyección presupuestaria (no afecta caja ni pasivos)
    ACCRUED_LIABILITY = "ACCRUED_LIABILITY"  # Obligación devengada / provisión pendiente de pago


class ReserveType(str, Enum):
    MAINTENANCE = "MAINTENANCE"                      # Mantenimiento programado y repuestos
    HARDWARE_REPLACEMENT = "HARDWARE_REPLACEMENT"    # Sustitución de hardware
    OPERATIONAL_CONTINUITY = "OPERATIONAL_CONTINUITY"# Continuidad operativa y fondo de maniobra
    CONTINGENCY = "CONTINGENCY"                      # Contingencias e imprevistos


class ReserveStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEPLETED = "DEPLETED"
    CLOSED = "CLOSED"
    PENDING_RESOLUTION = "PENDING_RESOLUTION"


class ReserveAction(str, Enum):
    ALLOCATE = "ALLOCATE"  # Apartar capital de tesorería hacia la reserva
    CONSUME = "CONSUME"    # Consumo parcial o total de la reserva para cubrir un gasto realizado
    RELEASE = "RELEASE"    # Liberación de fondos de la reserva de vuelta a tesorería disponible


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


DEFAULT_GENESIS_HASH = "HP9XKTusRPGC78EFDpR9xdEq6simL2vqyDdrMvn6Vacg"
DEFAULT_PROGRAM_ID = "CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy"


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
    genesis_hash: str = DEFAULT_GENESIS_HASH
    program_id: str = DEFAULT_PROGRAM_ID

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_account": self.agent_account,
            "network": self.network,
            "genesis_hash": self.genesis_hash,
            "program_id": self.program_id,
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


@dataclass(frozen=True)
class AgentCost:
    cost_id: str
    idempotency_key: str
    agent_id: str
    agent_account: str
    owner_pubkey: str
    category: CostCategory
    cost_nature: CostNature
    economic_period: str
    network: str
    token_mint: str
    amount_base_units: int
    amount_str: str
    status: MovementStatus
    provenance_source: ProvenanceSource
    created_at: int
    incurred_at: int
    journal_entry_id: Optional[str] = None
    movement_id: Optional[str] = None
    evidence_hash: Optional[str] = None
    evidence_url: Optional[str] = None
    attestation_id: Optional[str] = None
    description: Optional[str] = None
    reversal_of_cost_id: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    genesis_hash: str = DEFAULT_GENESIS_HASH
    program_id: str = DEFAULT_PROGRAM_ID

    def to_dict(self) -> dict[str, Any]:
        return {
            "cost_id": self.cost_id,
            "idempotency_key": self.idempotency_key,
            "agent_id": self.agent_id,
            "agent_account": self.agent_account,
            "owner_pubkey": self.owner_pubkey,
            "category": self.category.value if isinstance(self.category, CostCategory) else self.category,
            "cost_nature": self.cost_nature.value if isinstance(self.cost_nature, CostNature) else self.cost_nature,
            "economic_period": self.economic_period,
            "network": self.network,
            "genesis_hash": self.genesis_hash,
            "program_id": self.program_id,
            "token_mint": self.token_mint,
            "amount_base_units": self.amount_base_units,
            "amount_str": self.amount_str,
            "status": self.status.value if isinstance(self.status, MovementStatus) else self.status,
            "provenance_source": self.provenance_source.value if isinstance(self.provenance_source, ProvenanceSource) else self.provenance_source,
            "created_at": self.created_at,
            "incurred_at": self.incurred_at,
            "journal_entry_id": self.journal_entry_id,
            "movement_id": self.movement_id,
            "evidence_hash": self.evidence_hash,
            "evidence_url": self.evidence_url,
            "attestation_id": self.attestation_id,
            "description": self.description,
            "reversal_of_cost_id": self.reversal_of_cost_id,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class AgentReserve:
    """Agent economic capital reserve representation.

    An agent economic capital reserve is an off-chain accounting segregation of unencumbered
    reconciled treasury capital.
    NOTE: This off-chain accounting reservation does NOT directly freeze or lock Solana SPL tokens
    on-chain by itself; on-chain token movements require separate Solana smart contract interaction.
    """
    reserve_id: str
    idempotency_key: str
    agent_id: str
    agent_account: str
    owner_pubkey: str
    reserve_type: ReserveType
    network: str
    token_mint: str
    target_amount_base_units: int
    current_reserved_base_units: int
    status: ReserveStatus
    created_at: int
    updated_at: int
    description: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    genesis_hash: str = DEFAULT_GENESIS_HASH
    program_id: str = DEFAULT_PROGRAM_ID

    def to_dict(self) -> dict[str, Any]:
        return {
            "reserve_id": self.reserve_id,
            "idempotency_key": self.idempotency_key,
            "agent_id": self.agent_id,
            "agent_account": self.agent_account,
            "owner_pubkey": self.owner_pubkey,
            "reserve_type": self.reserve_type.value if isinstance(self.reserve_type, ReserveType) else self.reserve_type,
            "network": self.network,
            "genesis_hash": self.genesis_hash,
            "program_id": self.program_id,
            "token_mint": self.token_mint,
            "target_amount_base_units": self.target_amount_base_units,
            "target_amount_str": str(self.target_amount_base_units),
            "current_reserved_base_units": self.current_reserved_base_units,
            "current_reserved_str": str(self.current_reserved_base_units),
            "status": self.status.value if isinstance(self.status, ReserveStatus) else self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "description": self.description,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class ReserveTransaction:
    transaction_id: str
    reserve_id: str
    idempotency_key: str
    action: ReserveAction
    amount_base_units: int
    created_at: int
    associated_cost_id: Optional[str] = None
    journal_entry_id: Optional[str] = None
    movement_id: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "transaction_id": self.transaction_id,
            "reserve_id": self.reserve_id,
            "idempotency_key": self.idempotency_key,
            "action": self.action.value if isinstance(self.action, ReserveAction) else self.action,
            "amount_base_units": self.amount_base_units,
            "amount_str": str(self.amount_base_units),
            "created_at": self.created_at,
            "associated_cost_id": self.associated_cost_id,
            "journal_entry_id": self.journal_entry_id,
            "movement_id": self.movement_id,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class AgentEconomicSummary:
    agent_account: str
    network: str
    token_mint: str
    total_income_reconciled: int
    total_income_provisional: int
    total_expenses_realized: int
    total_obligations_accrued: int
    total_estimated_costs: int
    total_capital_reserved: int
    available_balance: int
    total_effective_balance: int
    total_income_reconciled_str: str
    total_income_provisional_str: str
    total_expenses_realized_str: str
    total_obligations_accrued_str: str
    total_estimated_costs_str: str
    total_capital_reserved_str: str
    available_balance_str: str
    total_effective_balance_str: str
    costs_by_category: dict[str, int]
    reserves_by_type: dict[str, int]
    investible_surplus: int = 0
    investible_surplus_str: str = "0"
    capex_investments: int = 0
    capex_investments_str: str = "0"
    genesis_hash: str = DEFAULT_GENESIS_HASH
    program_id: str = DEFAULT_PROGRAM_ID

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_account": self.agent_account,
            "network": self.network,
            "genesis_hash": self.genesis_hash,
            "program_id": self.program_id,
            "token_mint": self.token_mint,
            "total_income_reconciled": self.total_income_reconciled,
            "total_income_provisional": self.total_income_provisional,
            "total_expenses_realized": self.total_expenses_realized,
            "total_obligations_accrued": self.total_obligations_accrued,
            "total_estimated_costs": self.total_estimated_costs,
            "total_capital_reserved": self.total_capital_reserved,
            "available_balance": self.available_balance,
            "total_effective_balance": self.total_effective_balance,
            "investible_surplus": self.investible_surplus,
            "capex_investments": self.capex_investments,
            "total_income_reconciled_str": self.total_income_reconciled_str,
            "total_income_provisional_str": self.total_income_provisional_str,
            "total_expenses_realized_str": self.total_expenses_realized_str,
            "total_obligations_accrued_str": self.total_obligations_accrued_str,
            "total_estimated_costs_str": self.total_estimated_costs_str,
            "total_capital_reserved_str": self.total_capital_reserved_str,
            "available_balance_str": self.available_balance_str,
            "total_effective_balance_str": self.total_effective_balance_str,
            "investible_surplus_str": self.investible_surplus_str,
            "capex_investments_str": self.capex_investments_str,
            "costs_by_category": self.costs_by_category,
            "reserves_by_type": self.reserves_by_type,
        }
