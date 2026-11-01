"""Authentic RPC and SPL Settlement Reconciler for Conatus / AeroSettle (CON-23).

Production-grade cryptographic and RPC verification of AeroSettle SPL settlements:
1. Expected network and genesis hash.
2. Real transaction existence, confirmed/finalized status, and execution without error.
3. Program ID and settle_work_order instruction discriminator (0xa2462d3deabc0c76).
4. WorkOrderAccount on-chain decoding, owner verification, discriminator check,
   canonical PDA derivation from Rust seeds, and Settled status validation.
5. Contractual settlement calculation matching Rust verified_operator_payout() and
   allocation_for_verification() for Fixed and Proportional payment models.
6. AgentAccount on-chain decoding, owner verification, discriminator check,
   canonical PDA derivation, and frozen economic beneficiary preservation.
7. Strict SPL token account ownership, mint matching, and Token Program validation
   (fails closed on missing or third-party owners).
8. Inner TransferChecked instructions inspection matching contractual allocation,
   disambiguating shared operator/creator destinations and zero-payout refunds.
9. Finality gating: 'confirmed' only records/observes PROVISIONAL movements;
   'finalized' is strictly required for RECONCILED status.
10. Strict separation of evidence sources: LIVE_RPC, HISTORICAL_FIXTURE, and SYNTHETIC_TEST.
11. Idempotent financial effect identification:
    effect_id = f"{network}:{genesis}:{signature}:{instruction_index}:{destination}:{mint}"
12. Canonical evidence hash linking all verified settlement parameters.
"""
from __future__ import annotations

import base64
from enum import Enum
import hashlib
import json
import logging
import struct
import time
from dataclasses import asdict, dataclass
from typing import Any, Optional, Protocol, runtime_checkable
import urllib.error
import urllib.request

from .models import (
    EconomicMovement,
    IdempotencyConflictError,
    LedgerValidationError,
    MovementNature,
    MovementStatus,
    ProvenanceSource,
    validate_base_units,
)

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Canonical AeroSettle Program Constants
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_PROGRAM_ID = "CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy"
DEFAULT_GENESIS_HASH = "HP9XKTusRPGC78EFDpR9xdEq6simL2vqyDdrMvn6Vacg"
DEFAULT_NETWORK = "solana:localnet"
DEFAULT_PROTOCOL_CONFIG = "C8HiYzxKjRcDFHoWSZ84smUsxnMQ7ipxPnQ96GK5qZVn"
DEFAULT_TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022_PROGRAM = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"

# Anchor Account Discriminators: sha256("account:<Name>")[0..8]
WORK_ORDER_ACCOUNT_DISCRIMINATOR = bytes([200, 252, 180, 124, 6, 47, 174, 229])  # 0xc8fcb47c062faee5
AGENT_ACCOUNT_DISCRIMINATOR = bytes([241, 119, 69, 140, 233, 9, 112, 50])        # 0xf177458ce9097032
PROTOCOL_CONFIG_DISCRIMINATOR = bytes([207, 91, 250, 28, 152, 179, 215, 209])    # 0xcf5bfa1c98b3d7d1

# Anchor Instruction Discriminator: sha256("global:settle_work_order")[0..8]
SETTLE_WORK_ORDER_DISCRIMINATOR = bytes([162, 70, 45, 61, 234, 188, 12, 118])     # 0xa2462d3deabc0c76

# SPL Token Instruction Type: TransferChecked = 12
SPL_TOKEN_TRANSFER_CHECKED_TYPE = 12

# PDA Marker
PDA_MARKER = b"ProgramDerivedAddress"


# ─────────────────────────────────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────────────────────────────────


class EvidenceSourceKind(str, Enum):
    """Categorization of evidence origin for auditability."""

    LIVE_RPC = "LIVE_RPC"
    HISTORICAL_FIXTURE = "HISTORICAL_FIXTURE"
    SYNTHETIC_TEST = "SYNTHETIC_TEST"


class WorkOrderStatus(int, Enum):
    """Anchor WorkOrderStatus enum matching Rust definition."""

    Draft = 0
    Open = 1
    Claimed = 2
    Submitted = 3
    Verified = 4
    Settled = 5
    Cancelled = 6
    Expired = 7


class AgentStatus(int, Enum):
    """Anchor AgentStatus enum matching Rust definition."""

    Active = 0
    OwnerSuspended = 1
    AdminSuspended = 2
    Revoked = 3


class PaymentModel(int, Enum):
    """Anchor PaymentModel enum matching Rust definition."""

    Fixed = 0
    Proportional = 1


class VerificationStatus(int, Enum):
    """Anchor VerificationStatus enum matching Rust definition."""

    Accepted = 0
    Rejected = 1


# ─────────────────────────────────────────────────────────────────────────────
# Base58 & Cryptographic Curve Utilities
# ─────────────────────────────────────────────────────────────────────────────

B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
B58MAP = {c: i for i, c in enumerate(B58)}
P_ED25519 = 2**255 - 19
D_ED25519 = (-121665 * pow(121666, P_ED25519 - 2, P_ED25519)) % P_ED25519


def b58decode(value: str, expected_len: Optional[int] = None) -> bytes:
    """Decodes a base58 string into raw bytes with optional length check."""
    if not isinstance(value, str) or not value:
        return b""
    n = 0
    for c in value:
        if c not in B58MAP:
            raise ValueError(f"Invalid base58 character: {c!r}")
        n = n * 58 + B58MAP[c]
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    res = b"\0" * (len(value) - len(value.lstrip("1"))) + raw
    if expected_len is not None and len(res) != expected_len:
        raise ValueError(f"Expected base58 length {expected_len}, got {len(res)}")
    return res


def b58encode(data: bytes) -> str:
    """Encodes bytes into a base58 string."""
    n = int.from_bytes(data, "big")
    chars = ""
    while n:
        n, r = divmod(n, 58)
        chars = B58[r] + chars
    return "1" * (len(data) - len(data.lstrip(b"\0"))) + chars


def is_on_curve(compressed: bytes) -> bool:
    """Check compressed Edwards-y decompression to verify if point is on Ed25519 curve."""
    if len(compressed) != 32:
        return False
    yraw = int.from_bytes(compressed, "little")
    y, sign = yraw & ((1 << 255) - 1), yraw >> 255
    if y >= P_ED25519:
        return False
    y2 = (y * y) % P_ED25519
    numerator = (y2 - 1) % P_ED25519
    denominator = (D_ED25519 * y2 + 1) % P_ED25519
    if denominator == 0:
        return False
    x2 = (numerator * pow(denominator, P_ED25519 - 2, P_ED25519)) % P_ED25519
    x = pow(x2, (P_ED25519 + 3) // 8, P_ED25519)
    if (x * x) % P_ED25519 != x2:
        x = (x * pow(2, (P_ED25519 - 1) // 4, P_ED25519)) % P_ED25519
    if (x * x) % P_ED25519 != x2 or (x == 0 and sign):
        return False
    return True


def create_program_address(seeds: list[bytes], program_id_bytes: bytes) -> Optional[bytes]:
    """Computes program derived address; returns None if address falls on Ed25519 curve."""
    buffer = b"".join(seeds) + program_id_bytes + PDA_MARKER
    h = hashlib.sha256(buffer).digest()
    if is_on_curve(h):
        return None
    return h


def find_program_address(seeds: list[bytes], program_id: str) -> tuple[str, int]:
    """Finds canonical Solana PDA by scanning bump seeds from 255 down to 0."""
    prog_bytes = b58decode(program_id, 32)
    for bump in range(255, -1, -1):
        candidate_seeds = list(seeds) + [bytes([bump])]
        addr = create_program_address(candidate_seeds, prog_bytes)
        if addr is not None:
            return b58encode(addr), bump
    raise ValueError(f"Unable to find valid PDA for program {program_id}")


def derive_work_order_pda(
    protocol_config: str,
    creator: str,
    work_order_id: bytes,
    program_id: str = DEFAULT_PROGRAM_ID,
) -> tuple[str, int]:
    """Derives canonical WorkOrder PDA using seeds: [b'work_order', config, creator, order_id]."""
    seeds = [
        b"work_order",
        b58decode(protocol_config, 32),
        b58decode(creator, 32),
        work_order_id,
    ]
    return find_program_address(seeds, program_id)


def derive_agent_pda(
    protocol_config: str,
    agent_id: bytes,
    program_id: str = DEFAULT_PROGRAM_ID,
) -> tuple[str, int]:
    """Derives canonical Agent PDA using seeds: [b'agent', config, agent_id]."""
    seeds = [
        b"agent",
        b58decode(protocol_config, 32),
        agent_id,
    ]
    return find_program_address(seeds, program_id)


def derive_escrow_vault_pda(
    work_order_pubkey: str,
    program_id: str = DEFAULT_PROGRAM_ID,
) -> tuple[str, int]:
    """Derives canonical Escrow Vault PDA using seeds: [b'escrow', work_order]."""
    seeds = [
        b"escrow",
        b58decode(work_order_pubkey, 32),
    ]
    return find_program_address(seeds, program_id)


def derive_protocol_config_pda(program_id: str = DEFAULT_PROGRAM_ID) -> tuple[str, int]:
    """Derives canonical ProtocolConfig PDA using seeds: [b'protocol_config']."""
    return find_program_address([b"protocol_config"], program_id)


# ─────────────────────────────────────────────────────────────────────────────
# Contractual Economic Policy (Rust Equivalents)
# ─────────────────────────────────────────────────────────────────────────────


def compute_contractual_operator_payout(
    *,
    payment_model: int,
    verification_status: Optional[int],
    total_amount: int,
    completion_bps: int,
) -> Optional[int]:
    """Calculates operator payout strictly matching Rust verified_operator_payout()."""
    if completion_bps > 10_000:
        return None

    if verification_status == VerificationStatus.Rejected.value:
        return 0 if completion_bps == 0 else None

    if verification_status != VerificationStatus.Accepted.value:
        return None

    if payment_model == PaymentModel.Fixed.value:
        return total_amount if completion_bps == 10_000 else 0

    if payment_model == PaymentModel.Proportional.value:
        numerator = total_amount * completion_bps
        payout = numerator // 10_000
        return payout

    return None


def compute_contractual_allocation(
    *,
    payment_model: int,
    verification_status: Optional[int],
    total_amount: int,
    completion_bps: int,
    vault_balance: int,
) -> tuple[int, int, int]:
    """Computes exact (operator_payout, creator_refund, surplus) matching Rust handle_settle_work_order.

    Invariants enforced:
    - Operator payout is calculated via verified_operator_payout().
    - unearned_refund = total_amount - operator_payout.
    - surplus = max(0, vault_balance - total_amount).
    - creator_refund = unearned_refund + surplus.
    - Invariant: operator_payout + creator_refund == vault_balance.
    """
    operator_payout = compute_contractual_operator_payout(
        payment_model=payment_model,
        verification_status=verification_status,
        total_amount=total_amount,
        completion_bps=completion_bps,
    )
    if operator_payout is None:
        raise AmountMismatchError(
            f"Invalid settlement terms: model={payment_model}, status={verification_status}, "
            f"completion_bps={completion_bps}, total_amount={total_amount}"
        )

    if vault_balance < total_amount:
        raise AmountMismatchError(
            f"Insufficient escrow vault balance: {vault_balance} < total_amount {total_amount}"
        )

    surplus = vault_balance - total_amount
    unearned_refund = total_amount - operator_payout
    creator_refund = unearned_refund + surplus

    return operator_payout, creator_refund, surplus


# ─────────────────────────────────────────────────────────────────────────────
# Account Decoding and Encoding Utilities
# ─────────────────────────────────────────────────────────────────────────────


def decode_work_order_account(raw: bytes) -> dict[str, Any]:
    """Decodes a serialized on-chain WorkOrderAccount into structured fields."""
    if len(raw) < 585:
        raise ValueError(f"Truncated WorkOrderAccount data: len={len(raw)}, expected at least 585")
    disc = raw[:8]
    if disc != WORK_ORDER_ACCOUNT_DISCRIMINATOR:
        raise ValueError(f"Invalid WorkOrderAccount discriminator: {disc.hex()}")

    protocol_version = raw[8]
    protocol_config = b58encode(raw[9:41])
    work_order_id = raw[41:73]
    creator = b58encode(raw[73:105])
    work_type = raw[105]
    required_capabilities = struct.unpack("<Q", raw[106:114])[0]
    evidence_requirements = struct.unpack("<Q", raw[114:122])[0]
    manifest_hash = raw[122:154]
    token_mint = b58encode(raw[154:186])
    total_amount = struct.unpack("<Q", raw[186:194])[0]
    payment_model = raw[194]
    verifier = b58encode(raw[195:227])
    escrow_vault = b58encode(raw[227:259])
    token_program = b58encode(raw[259:291])
    execution_deadline = struct.unpack("<q", raw[291:299])[0]
    verification_deadline = struct.unpack("<q", raw[299:307])[0]
    status_int = raw[307]
    claimed_agent = b58encode(raw[308:340])
    settlement_beneficiary = b58encode(raw[340:372])

    is_some_verification = raw[532] == 1
    verification_status = raw[533] if is_some_verification else None
    completion_bps = struct.unpack("<H", raw[534:536])[0]
    bump = raw[584]

    return {
        "protocol_version": protocol_version,
        "protocol_config": protocol_config,
        "work_order_id": work_order_id,
        "creator": creator,
        "work_type": work_type,
        "required_capabilities": required_capabilities,
        "evidence_requirements": evidence_requirements,
        "manifest_hash": manifest_hash,
        "token_mint": token_mint,
        "total_amount": total_amount,
        "payment_model": payment_model,
        "verifier": verifier,
        "escrow_vault": escrow_vault,
        "token_program": token_program,
        "execution_deadline": execution_deadline,
        "verification_deadline": verification_deadline,
        "status": status_int,
        "claimed_agent": claimed_agent,
        "settlement_beneficiary": settlement_beneficiary,
        "verification_status": verification_status,
        "completion_bps": completion_bps,
        "bump": bump,
    }


def encode_work_order_account(
    *,
    protocol_version: int = 1,
    protocol_config: str,
    work_order_id: bytes,
    creator: str,
    work_type: int = 0,
    required_capabilities: int = 1,
    evidence_requirements: int = 1,
    manifest_hash: bytes = b"\x00" * 32,
    token_mint: str,
    total_amount: int,
    payment_model: int = PaymentModel.Fixed.value,
    verifier: str,
    escrow_vault: str,
    token_program: str = DEFAULT_TOKEN_PROGRAM,
    execution_deadline: int = 1800000000,
    verification_deadline: int = 1800000000,
    status: int = WorkOrderStatus.Settled.value,
    claimed_agent: str,
    settlement_beneficiary: str,
    verification_status: Optional[int] = VerificationStatus.Accepted.value,
    completion_bps: int = 10000,
    bump: int = 254,
) -> bytes:
    """Serializes a WorkOrderAccount buffer for tests and fixtures."""
    buf = bytearray(WORK_ORDER_ACCOUNT_DISCRIMINATOR)
    buf.append(protocol_version)
    buf.extend(b58decode(protocol_config, 32))
    assert len(work_order_id) == 32
    buf.extend(work_order_id)
    buf.extend(b58decode(creator, 32))
    buf.append(work_type)
    buf.extend(struct.pack("<Q", required_capabilities))
    buf.extend(struct.pack("<Q", evidence_requirements))
    assert len(manifest_hash) == 32
    buf.extend(manifest_hash)
    buf.extend(b58decode(token_mint, 32))
    buf.extend(struct.pack("<Q", total_amount))
    buf.append(payment_model)
    buf.extend(b58decode(verifier, 32))
    buf.extend(b58decode(escrow_vault, 32))
    buf.extend(b58decode(token_program, 32))
    buf.extend(struct.pack("<q", execution_deadline))
    buf.extend(struct.pack("<q", verification_deadline))
    buf.append(status)
    buf.extend(b58decode(claimed_agent, 32))
    buf.extend(b58decode(settlement_beneficiary, 32))
    buf.extend(b"\x00" * 96)  # receipt_hash, manifest_hash, signer
    buf.extend(b"\x00" * 32)  # sequence, evidence, started, ended
    buf.extend(b"\x00" * 32)  # verification_attestation_hash

    if verification_status is not None:
        buf.extend(bytes([1, verification_status]))
    else:
        buf.extend(bytes([0, 0]))

    buf.extend(struct.pack("<H", completion_bps))
    buf.extend(struct.pack("<qqqqqq", 1700000000, 1700000001, 1700000002, 1700000003, 1700000004, 1700000005))
    buf.append(bump)
    assert len(buf) == 585
    return bytes(buf)


def decode_agent_account(raw: bytes) -> dict[str, Any]:
    """Decodes a serialized on-chain AgentAccount into structured fields."""
    if len(raw) < 196:
        raise ValueError(f"Truncated AgentAccount data: len={len(raw)}, expected at least 196")
    disc = raw[:8]
    if disc != AGENT_ACCOUNT_DISCRIMINATOR:
        raise ValueError(f"Invalid AgentAccount discriminator: {disc.hex()}")

    protocol_version = raw[8]
    protocol_config = b58encode(raw[9:41])
    agent_id = raw[41:73]
    owner = b58encode(raw[73:105])
    signing_authority = b58encode(raw[105:137])
    agent_type = raw[137]
    capabilities = struct.unpack("<Q", raw[138:146])[0]
    metadata_hash = raw[146:178]
    status_int = raw[178]
    next_sequence = struct.unpack("<Q", raw[179:187])[0]
    bump = raw[187]
    registered_at = struct.unpack("<q", raw[188:196])[0]

    return {
        "protocol_version": protocol_version,
        "protocol_config": protocol_config,
        "agent_id": agent_id,
        "owner": owner,
        "signing_authority": signing_authority,
        "agent_type": agent_type,
        "capabilities": capabilities,
        "metadata_hash": metadata_hash,
        "status": status_int,
        "next_sequence": next_sequence,
        "bump": bump,
        "registered_at": registered_at,
    }


def encode_agent_account(
    *,
    protocol_version: int = 1,
    protocol_config: str,
    agent_id: bytes,
    owner: str,
    signing_authority: str,
    agent_type: int = 1,
    capabilities: int = 1,
    metadata_hash: bytes = b"\x00" * 32,
    status: int = AgentStatus.Active.value,
    next_sequence: int = 1,
    bump: int = 255,
    registered_at: int = 1700000000,
) -> bytes:
    """Serializes an AgentAccount buffer for tests and fixtures."""
    buf = bytearray(AGENT_ACCOUNT_DISCRIMINATOR)
    buf.append(protocol_version)
    buf.extend(b58decode(protocol_config, 32))
    assert len(agent_id) == 32
    buf.extend(agent_id)
    buf.extend(b58decode(owner, 32))
    buf.extend(b58decode(signing_authority, 32))
    buf.append(agent_type)
    buf.extend(struct.pack("<Q", capabilities))
    assert len(metadata_hash) == 32
    buf.extend(metadata_hash)
    buf.append(status)
    buf.extend(struct.pack("<Q", next_sequence))
    buf.append(bump)
    buf.extend(struct.pack("<q", registered_at))
    assert len(buf) == 196
    return bytes(buf)


def decode_token_account(raw: bytes) -> dict[str, Any]:
    """Decodes a serialized SPL Token Account (165 bytes)."""
    if len(raw) < 165:
        raise ValueError(f"Truncated SPL Token account: len={len(raw)}, expected at least 165")
    mint = b58encode(raw[0:32])
    owner = b58encode(raw[32:64])
    amount = struct.unpack("<Q", raw[64:72])[0]
    state = raw[108]  # 1 = Initialized
    return {
        "mint": mint,
        "owner": owner,
        "amount": amount,
        "is_initialized": state == 1,
    }


def encode_token_account(
    *,
    mint: str,
    owner: str,
    amount: int,
    state: int = 1,
) -> bytes:
    """Serializes an SPL Token Account buffer (165 bytes)."""
    buf = bytearray(165)
    buf[0:32] = b58decode(mint, 32)
    buf[32:64] = b58decode(owner, 32)
    buf[64:72] = struct.pack("<Q", amount)
    buf[108] = state
    return bytes(buf)


def encode_spl_transfer_checked(amount: int, decimals: int) -> bytes:
    """Encodes an SPL Token TransferChecked instruction body: [12, amount:u64, decimals:u8]."""
    return bytes([SPL_TOKEN_TRANSFER_CHECKED_TYPE]) + struct.pack("<Q", amount) + bytes([decimals])


def decode_spl_transfer_checked(data: bytes) -> tuple[int, int]:
    """Decodes an SPL Token TransferChecked instruction; returns (amount, decimals)."""
    if len(data) < 10 or data[0] != SPL_TOKEN_TRANSFER_CHECKED_TYPE:
        raise ValueError("Not a valid SPL TransferChecked instruction data buffer")
    amount = struct.unpack("<Q", data[1:9])[0]
    decimals = data[9]
    return amount, decimals


# ─────────────────────────────────────────────────────────────────────────────
# Exceptions
# ─────────────────────────────────────────────────────────────────────────────


class SettlementVerificationError(LedgerValidationError):
    """Base error for on-chain settlement reconciliation failures."""

    pass


class RpcError(SettlementVerificationError):
    """Raised when communication with the Solana RPC fails."""

    pass


class TransactionNotFoundError(SettlementVerificationError):
    """Raised when the specified transaction signature does not exist on-chain."""

    pass


class TransactionFailedError(SettlementVerificationError):
    """Raised when the transaction completed on-chain with an error (err is not None)."""

    pass


class InstructionMismatchError(SettlementVerificationError):
    """Raised when the transaction does not execute settle_work_order for the target program."""

    pass


class AccountMismatchError(SettlementVerificationError):
    """Raised when work order, agent, mint, or beneficiary accounts mismatch."""

    pass


class WorkOrderNotSettledError(AccountMismatchError):
    """Raised when WorkOrder status is not WorkOrderStatus::Settled."""

    pass


class AgentMismatchError(AccountMismatchError):
    """Raised when agent identity, account, or frozen beneficiary does not match."""

    pass


class AmountMismatchError(SettlementVerificationError):
    """Raised when SPL token balance transfers do not match expected economic amounts."""

    pass


class CommitmentUnsatisfiedError(SettlementVerificationError):
    """Raised when the transaction has not achieved the required confirmation commitment."""

    pass


# ─────────────────────────────────────────────────────────────────────────────
# Data Structures
# ─────────────────────────────────────────────────────────────────────────────


def build_financial_effect_id(
    *,
    network: str,
    genesis_hash: str,
    tx_signature: str,
    instruction_index: int,
    destination: str,
    mint: str,
) -> str:
    """Canonical idempotent financial effect identifier as defined in CON-23.

    Format:
    `network + genesis + signature + instruction/effect index + destination + mint`
    """
    return f"{network}:{genesis_hash}:{tx_signature}:{instruction_index}:{destination}:{mint}"


@dataclass(frozen=True)
class SettlementReceipt:
    """Immutable verified receipt of an authentic on-chain settlement."""

    network: str
    genesis_hash: str
    program_id: str
    tx_signature: str
    slot: int
    block_time: Optional[int]
    instruction_index: int
    work_order_account: str
    agent_account: str
    agent_id: str
    owner_pubkey: str
    settlement_beneficiary: str
    agent_owner_current: str
    token_mint: str
    escrow_vault: str
    operator_token_account: str
    creator_refund_token_account: str
    operator_payout: int
    creator_refund: int
    total_escrow_settled: int
    surplus: int
    commitment: str
    evidence_source: str
    effect_id: str
    evidence_hash: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def canonical_json(self) -> str:
        d = self.to_dict()
        return json.dumps(d, sort_keys=True, separators=(",", ":"))


def compute_canonical_evidence_hash(evidence_data: dict[str, Any]) -> str:
    """Computes SHA-256 over canonical sorted JSON of verified settlement receipt."""
    payload = {
        "version": "conatus:spl-settlement:v3",
        "network": str(evidence_data.get("network", "")),
        "genesis_hash": str(evidence_data.get("genesis_hash", "")),
        "program_id": str(evidence_data.get("program_id", "")),
        "tx_signature": str(evidence_data.get("tx_signature", "")),
        "slot": int(evidence_data.get("slot", 0)),
        "instruction_index": int(evidence_data.get("instruction_index", 0)),
        "work_order_account": str(evidence_data.get("work_order_account", "")),
        "agent_account": str(evidence_data.get("agent_account", "")),
        "agent_id": str(evidence_data.get("agent_id", "")),
        "owner_pubkey": str(evidence_data.get("owner_pubkey", "")),
        "settlement_beneficiary": str(evidence_data.get("settlement_beneficiary", "")),
        "agent_owner_current": str(evidence_data.get("agent_owner_current", "")),
        "token_mint": str(evidence_data.get("token_mint", "")),
        "escrow_vault": str(evidence_data.get("escrow_vault", "")),
        "operator_token_account": str(evidence_data.get("operator_token_account", "")),
        "creator_refund_token_account": str(evidence_data.get("creator_refund_token_account", "")),
        "operator_payout": int(evidence_data.get("operator_payout", 0)),
        "creator_refund": int(evidence_data.get("creator_refund", 0)),
        "total_escrow_settled": int(evidence_data.get("total_escrow_settled", 0)),
        "surplus": int(evidence_data.get("surplus", 0)),
        "evidence_source": str(evidence_data.get("evidence_source", EvidenceSourceKind.LIVE_RPC.value)),
        "effect_id": str(evidence_data.get("effect_id", "")),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


# ─────────────────────────────────────────────────────────────────────────────
# RPC Client Protocol & Implementations
# ─────────────────────────────────────────────────────────────────────────────


@runtime_checkable
class SolanaRpcClientProtocol(Protocol):
    """Protocol for fetching on-chain data from a Solana RPC node."""

    def get_genesis_hash(self) -> str:
        ...

    def get_transaction(
        self,
        tx_signature: str,
        *,
        commitment: str = "finalized",
    ) -> Optional[dict[str, Any]]:
        ...

    def get_account_info(
        self,
        pubkey: str,
        *,
        commitment: str = "confirmed",
    ) -> Optional[dict[str, Any]]:
        ...

    def get_slot(self, *, commitment: str = "confirmed") -> int:
        ...


class SolanaRpcClient:
    """Production JSON-RPC client for querying authentic Solana nodes."""

    def __init__(self, rpc_url: str = "http://127.0.0.1:8899", timeout: float = 10.0) -> None:
        self.rpc_url = rpc_url.rstrip("/")
        self.timeout = timeout

    def _call(self, method: str, params: Optional[list[Any]] = None) -> Any:
        body = json.dumps({
            "jsonrpc": "2.0",
            "id": int(time.time() * 1000) % 1_000_000,
            "method": method,
            "params": params or [],
        }).encode("utf-8")

        req = urllib.request.Request(
            self.rpc_url,
            data=body,
            headers={"Content-Type": "application/json"},
        )
        for attempt in range(6):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                break
            except urllib.error.HTTPError as exc:
                if exc.code in (429, 500, 502, 503, 504) and attempt < 5:
                    time.sleep(min(0.5 * (2 ** attempt), 8.0))
                    continue
                raise RpcError(f"RPC HTTP error during '{method}': {exc}") from exc
            except urllib.error.URLError as exc:
                raise RpcError(f"RPC connection failed to '{self.rpc_url}': {exc}") from exc
            except Exception as exc:
                raise RpcError(f"RPC error during '{method}': {exc}") from exc

        if "error" in data:
            err = data["error"]
            raise RpcError(f"RPC returned error for '{method}': {err}")

        return data.get("result")

    def get_genesis_hash(self) -> str:
        res = self._call("getGenesisHash")
        if not isinstance(res, str):
            raise RpcError("Invalid getGenesisHash response")
        return res

    def get_signature_status(self, tx_signature: str) -> Optional[dict[str, Any]]:
        res = self._call("getSignatureStatuses", [[tx_signature], {"searchTransactionHistory": True}])
        values = res.get("value") if isinstance(res, dict) else None
        if not isinstance(values, list) or len(values) != 1:
            raise RpcError("Invalid getSignatureStatuses response")
        status = values[0]
        if status is not None and not isinstance(status, dict):
            raise RpcError("Invalid signature status")
        return status

    def get_token_account_balance(self, pubkey: str, *, commitment: str = "finalized") -> int:
        res = self._call("getTokenAccountBalance", [pubkey, {"commitment": commitment}])
        value = res.get("value") if isinstance(res, dict) else None
        amount = value.get("amount") if isinstance(value, dict) else None
        if not isinstance(amount, str) or not amount.isdigit():
            raise RpcError("Invalid getTokenAccountBalance response")
        return int(amount)

    def get_transaction(
        self,
        tx_signature: str,
        *,
        commitment: str = "finalized",
    ) -> Optional[dict[str, Any]]:
        params = [
            tx_signature,
            {
                "encoding": "json",
                "commitment": commitment,
                "maxSupportedTransactionVersion": 0,
            },
        ]
        res = self._call("getTransaction", params)
        return res

    def get_account_info(
        self,
        pubkey: str,
        *,
        commitment: str = "confirmed",
    ) -> Optional[dict[str, Any]]:
        params = [
            pubkey,
            {
                "encoding": "base64",
                "commitment": commitment,
            },
        ]
        res = self._call("getAccountInfo", params)
        if res and isinstance(res, dict):
            return res.get("value")
        return None

    def get_slot(self, *, commitment: str = "confirmed") -> int:
        res = self._call("getSlot", [{"commitment": commitment}])
        return int(res or 0)


class MockRpcClient:
    """Deterministic in-memory RPC client for test suites and offline historical fixtures."""

    def __init__(
        self,
        genesis_hash: str = DEFAULT_GENESIS_HASH,
        current_slot: int = 100_000,
    ) -> None:
        self.genesis_hash = genesis_hash
        self.current_slot = current_slot
        self.transactions: dict[str, dict[str, Any]] = {}
        self.transaction_commitments: dict[str, str] = {}
        self.accounts: dict[str, dict[str, Any]] = {}
        self.should_fail: Optional[Exception] = None

    def register_transaction(
        self,
        tx_signature: str,
        tx_data: dict[str, Any],
        *,
        commitment: str = "finalized",
    ) -> None:
        self.transactions[tx_signature] = tx_data
        self.transaction_commitments[tx_signature] = commitment

    def register_account(
        self,
        pubkey: str,
        account_data: Any,
        *,
        owner: str = DEFAULT_PROGRAM_ID,
        lamports: int = 1_000_000,
    ) -> None:
        if isinstance(account_data, (bytes, bytearray)):
            b64_str = base64.b64encode(bytes(account_data)).decode("utf-8")
            self.accounts[pubkey] = {
                "data": [b64_str, "base64"],
                "owner": owner,
                "lamports": lamports,
                "space": len(account_data),
            }
        elif isinstance(account_data, dict):
            self.accounts[pubkey] = account_data
        else:
            raise ValueError(f"Unsupported account data type: {type(account_data)}")

    def set_error(self, exc: Optional[Exception]) -> None:
        self.should_fail = exc

    def get_genesis_hash(self) -> str:
        if self.should_fail:
            raise self.should_fail
        return self.genesis_hash

    def get_transaction(
        self,
        tx_signature: str,
        *,
        commitment: str = "finalized",
    ) -> Optional[dict[str, Any]]:
        if self.should_fail:
            raise self.should_fail
        tx = self.transactions.get(tx_signature)
        if tx is None:
            return None

        # Check commitment filter: if caller requires finalized, confirmed is not returned
        tx_comm = self.transaction_commitments.get(tx_signature, "finalized")
        if commitment == "finalized" and tx_comm != "finalized":
            return None

        return tx

    def get_account_info(
        self,
        pubkey: str,
        *,
        commitment: str = "confirmed",
    ) -> Optional[dict[str, Any]]:
        if self.should_fail:
            raise self.should_fail
        return self.accounts.get(pubkey)

    def get_slot(self, *, commitment: str = "confirmed") -> int:
        if self.should_fail:
            raise self.should_fail
        return self.current_slot


# ─────────────────────────────────────────────────────────────────────────────
# Helper Functions for Account Inspection
# ─────────────────────────────────────────────────────────────────────────────


def extract_account_bytes(account_info: Optional[dict[str, Any]]) -> bytes:
    """Extracts raw bytes from an RPC getAccountInfo result object."""
    if not account_info or not isinstance(account_info, dict):
        return b""
    data = account_info.get("data")
    if isinstance(data, list) and len(data) >= 1:
        raw_b64 = data[0]
        if isinstance(raw_b64, str):
            return base64.b64decode(raw_b64)
    elif isinstance(data, str):
        return base64.b64decode(data)
    return b""


# ─────────────────────────────────────────────────────────────────────────────
# SplSettlementReconciler
# ─────────────────────────────────────────────────────────────────────────────


class SplSettlementReconciler:
    """Authentic on-chain SPL settlement verifier implementing ReconciliationVerifier."""

    def __init__(
        self,
        *,
        rpc_client: Optional[SolanaRpcClientProtocol] = None,
        rpc_url: str = "http://127.0.0.1:8899",
        expected_network: str = DEFAULT_NETWORK,
        expected_genesis_hash: str = DEFAULT_GENESIS_HASH,
        expected_program_id: str = DEFAULT_PROGRAM_ID,
        expected_protocol_config: Optional[str] = DEFAULT_PROTOCOL_CONFIG,
        min_commitment: str = "finalized",
        authority: str = "conatus:protocol:reconciler:v1",
    ) -> None:
        self.rpc: SolanaRpcClientProtocol = (
            rpc_client if rpc_client is not None else SolanaRpcClient(rpc_url)
        )
        self.expected_network = expected_network
        self.expected_genesis_hash = expected_genesis_hash
        self.expected_program_id = expected_program_id
        self.expected_protocol_config = expected_protocol_config
        self.min_commitment = min_commitment
        self.authority = authority
        self.reconciled_receipts: dict[str, SettlementReceipt] = {}

    # ─────────────────────────────────────────────────────────────────────────
    # Verification Engine
    # ─────────────────────────────────────────────────────────────────────────

    def verify_settlement_transaction(
        self,
        tx_signature: str,
        *,
        expected_work_order: Optional[str] = None,
        expected_mint: Optional[str] = None,
        expected_beneficiary: Optional[str] = None,
        expected_operator_amount: Optional[int] = None,
        require_finalized: bool = True,
        source_kind: Optional[EvidenceSourceKind] = None,
    ) -> SettlementReceipt:
        """Thoroughly inspects and verifies an on-chain settlement transaction via RPC.

        Fails closed on any inconsistency between instructions, inner SPL transfers,
        token balances, or verified on-chain account states.
        """
        # Detect evidence source kind cleanly: never let mock RPC masquerade as LIVE_RPC
        if source_kind == EvidenceSourceKind.LIVE_RPC and type(self.rpc) is not SolanaRpcClient:
            raise SettlementVerificationError("LIVE_RPC requires the actual SolanaRpcClient")
        effective_source = source_kind
        if effective_source is None:
            if type(self.rpc) is SolanaRpcClient:
                effective_source = EvidenceSourceKind.LIVE_RPC
            else:
                effective_source = EvidenceSourceKind.SYNTHETIC_TEST

        # 1. Validate network & genesis hash
        try:
            actual_genesis = self.rpc.get_genesis_hash()
        except Exception as exc:
            raise RpcError(f"Failed to fetch genesis hash from RPC: {exc}") from exc

        if actual_genesis != self.expected_genesis_hash:
            raise SettlementVerificationError(
                f"Genesis hash mismatch: expected '{self.expected_genesis_hash}', got '{actual_genesis}'"
            )

        # 2. Fetch transaction at required commitment level
        commitment_to_fetch = "finalized" if require_finalized else "confirmed"
        try:
            tx = self.rpc.get_transaction(tx_signature, commitment=commitment_to_fetch)
        except Exception as exc:
            raise RpcError(f"Failed to fetch transaction '{tx_signature}' from RPC: {exc}") from exc

        actual_tx_commitment = commitment_to_fetch
        if tx is None:
            if require_finalized:
                try:
                    tx_confirmed = self.rpc.get_transaction(tx_signature, commitment="confirmed")
                except Exception:
                    tx_confirmed = None
                if tx_confirmed is not None:
                    raise CommitmentUnsatisfiedError(
                        f"Transaction '{tx_signature}' is confirmed but not finalized; "
                        "finalized commitment is strictly required for reconciliation"
                    )
            raise TransactionNotFoundError(
                f"Transaction '{tx_signature}' was not found on-chain at commitment '{commitment_to_fetch}'"
            )

        # 3. Check transaction execution status
        meta = tx.get("meta")
        if not meta or not isinstance(meta, dict):
            raise SettlementVerificationError(f"Transaction '{tx_signature}' is missing execution metadata")

        if meta.get("err") is not None:
            raise TransactionFailedError(
                f"Transaction '{tx_signature}' failed on-chain with error: {meta['err']}"
            )

        if type(self.rpc) is SolanaRpcClient:
            status = self.rpc.get_signature_status(tx_signature)
            if status is None or status.get("err") is not None:
                raise SettlementVerificationError("Missing or failed RPC signature status")
            expected_status = "finalized" if require_finalized else "confirmed"
            if status.get("confirmationStatus") not in ({"finalized"} if require_finalized else {"confirmed", "finalized"}):
                raise CommitmentUnsatisfiedError(f"Signature has not reached {expected_status} commitment")
            if status.get("slot") != tx.get("slot"):
                raise SettlementVerificationError("Signature status slot does not match transaction slot")

        slot = int(tx.get("slot", 0))
        if slot <= 0:
            raise SettlementVerificationError(f"Invalid confirmed block slot {slot} in transaction")

        block_time = tx.get("blockTime")

        # 4. Extract account keys
        transaction_obj = tx.get("transaction", {})
        message = transaction_obj.get("message", {})
        raw_account_keys = message.get("accountKeys", [])
        account_keys: list[str] = []
        for k in raw_account_keys:
            if isinstance(k, str):
                account_keys.append(k)
            elif isinstance(k, dict) and "pubkey" in k:
                account_keys.append(k["pubkey"])

        if not account_keys:
            raise SettlementVerificationError(f"Transaction '{tx_signature}' has empty accountKeys")

        # 5. Locate settle_work_order instruction (supports multi-instruction transactions)
        instructions = message.get("instructions", [])
        settle_ix: Optional[dict[str, Any]] = None
        settle_ix_index: int = -1

        for idx, ix in enumerate(instructions):
            prog_id: Optional[str] = None
            if "programIdIndex" in ix:
                prog_idx = ix["programIdIndex"]
                if 0 <= prog_idx < len(account_keys):
                    prog_id = account_keys[prog_idx]
            elif "programId" in ix:
                prog_id = ix["programId"]

            if prog_id != self.expected_program_id:
                continue

            # Decode instruction data
            data_bytes = b""
            if "data" in ix:
                raw_data = ix["data"]
                if isinstance(raw_data, str):
                    try:
                        data_bytes = b58decode(raw_data)
                    except Exception:
                        try:
                            data_bytes = base64.b64decode(raw_data)
                        except Exception:
                            data_bytes = b""

            if len(data_bytes) >= 8 and data_bytes[:8] == SETTLE_WORK_ORDER_DISCRIMINATOR:
                settle_ix = ix
                settle_ix_index = idx
                break

        if settle_ix is None:
            raise InstructionMismatchError(
                f"Transaction '{tx_signature}' does not contain instruction 'settle_work_order' "
                f"for program '{self.expected_program_id}'"
            )

        # 6. Extract and validate instruction accounts order
        ix_accounts = settle_ix.get("accounts", [])
        if len(ix_accounts) < 7:
            raise InstructionMismatchError(
                f"Instruction 'settle_work_order' has {len(ix_accounts)} accounts, expected at least 7"
            )

        def resolve_pubkey(idx_val: Any) -> str:
            if isinstance(idx_val, int) and 0 <= idx_val < len(account_keys):
                return account_keys[idx_val]
            if isinstance(idx_val, str):
                return idx_val
            raise SettlementVerificationError(f"Cannot resolve account key: {idx_val}")

        protocol_config_pubkey = resolve_pubkey(ix_accounts[0])
        work_order_pubkey = resolve_pubkey(ix_accounts[1])
        escrow_vault_pubkey = resolve_pubkey(ix_accounts[2])
        mint_pubkey = resolve_pubkey(ix_accounts[3])
        operator_token_account_pubkey = resolve_pubkey(ix_accounts[4])
        creator_refund_token_account_pubkey = resolve_pubkey(ix_accounts[5])
        token_program_pubkey = resolve_pubkey(ix_accounts[6])

        # Validate Token Program
        if token_program_pubkey not in (DEFAULT_TOKEN_PROGRAM, TOKEN_2022_PROGRAM):
            raise InstructionMismatchError(
                f"Instruction 'settle_work_order' account 6 is not a valid Token Program: '{token_program_pubkey}'"
            )

        if self.expected_protocol_config and protocol_config_pubkey != self.expected_protocol_config:
            raise AccountMismatchError(
                f"ProtocolConfig mismatch: expected '{self.expected_protocol_config}', got '{protocol_config_pubkey}'"
            )

        if expected_work_order and work_order_pubkey != expected_work_order:
            raise AccountMismatchError(
                f"WorkOrder account mismatch: expected '{expected_work_order}', got '{work_order_pubkey}'"
            )

        if expected_mint and mint_pubkey != expected_mint:
            raise AccountMismatchError(
                f"Settlement mint mismatch: expected '{expected_mint}', got '{mint_pubkey}'"
            )

        # 7. Decode and verify WorkOrderAccount on-chain
        try:
            wo_info = self.rpc.get_account_info(work_order_pubkey)
        except Exception as exc:
            raise RpcError(f"Failed to fetch WorkOrder account '{work_order_pubkey}': {exc}") from exc

        if wo_info is None:
            raise AccountMismatchError(f"WorkOrder account '{work_order_pubkey}' does not exist on-chain")

        if wo_info.get("owner") != self.expected_program_id:
            raise AccountMismatchError(
                f"WorkOrder account owner mismatch: expected '{self.expected_program_id}', "
                f"got '{wo_info.get('owner')}'"
            )

        wo_bytes = extract_account_bytes(wo_info)
        try:
            wo_data = decode_work_order_account(wo_bytes)
        except Exception as exc:
            raise AccountMismatchError(f"Failed to decode WorkOrderAccount '{work_order_pubkey}': {exc}") from exc

        # Verify WorkOrder Status == Settled
        if wo_data["status"] != WorkOrderStatus.Settled.value:
            raise WorkOrderNotSettledError(
                f"WorkOrder '{work_order_pubkey}' is not Settled: status={wo_data['status']} "
                f"(expected {WorkOrderStatus.Settled.value})"
            )

        # Verify Canonical WorkOrder PDA derivation
        try:
            expected_wo_pda, _ = derive_work_order_pda(
                wo_data["protocol_config"],
                wo_data["creator"],
                wo_data["work_order_id"],
                self.expected_program_id,
            )
        except Exception as exc:
            raise AccountMismatchError(f"Error computing canonical WorkOrder PDA: {exc}") from exc

        if expected_wo_pda != work_order_pubkey:
            raise AccountMismatchError(
                f"WorkOrder address '{work_order_pubkey}' does not match canonical PDA '{expected_wo_pda}'"
            )

        # Verify parameters consistency
        if wo_data["protocol_config"] != protocol_config_pubkey:
            raise AccountMismatchError(
                f"WorkOrder protocol_config mismatch: account has '{wo_data['protocol_config']}', "
                f"tx has '{protocol_config_pubkey}'"
            )
        if wo_data["token_mint"] != mint_pubkey:
            raise AccountMismatchError(
                f"WorkOrder token_mint mismatch: account has '{wo_data['token_mint']}', tx has '{mint_pubkey}'"
            )
        if wo_data["escrow_vault"] != escrow_vault_pubkey:
            raise AccountMismatchError(
                f"WorkOrder escrow_vault mismatch: account has '{wo_data['escrow_vault']}', "
                f"tx has '{escrow_vault_pubkey}'"
            )
        if wo_data["token_program"] != token_program_pubkey:
            raise AccountMismatchError(
                f"WorkOrder token_program mismatch: account has '{wo_data['token_program']}', "
                f"tx has '{token_program_pubkey}'"
            )

        # Verify Escrow Vault Canonical PDA
        expected_vault_pda, _ = derive_escrow_vault_pda(work_order_pubkey, self.expected_program_id)
        if expected_vault_pda != escrow_vault_pubkey:
            raise AccountMismatchError(
                f"Escrow vault address '{escrow_vault_pubkey}' does not match canonical PDA '{expected_vault_pda}'"
            )

        claimed_agent_pubkey = wo_data["claimed_agent"]
        settlement_beneficiary = wo_data["settlement_beneficiary"]

        if not claimed_agent_pubkey or claimed_agent_pubkey == "1" * 32 or claimed_agent_pubkey == b58encode(bytes(32)):
            raise AccountMismatchError(f"WorkOrder '{work_order_pubkey}' has invalid or empty claimed_agent")
        if not settlement_beneficiary or settlement_beneficiary == "1" * 32 or settlement_beneficiary == b58encode(bytes(32)):
            raise AccountMismatchError(f"WorkOrder '{work_order_pubkey}' has uninitialized settlement_beneficiary")

        # 8. Decode and verify AgentAccount on-chain
        try:
            agent_info = self.rpc.get_account_info(claimed_agent_pubkey)
        except Exception as exc:
            raise RpcError(f"Failed to fetch Agent account '{claimed_agent_pubkey}': {exc}") from exc

        if agent_info is None:
            raise AgentMismatchError(f"Claimed AgentAccount '{claimed_agent_pubkey}' does not exist on-chain")

        if agent_info.get("owner") != self.expected_program_id:
            raise AgentMismatchError(
                f"AgentAccount owner mismatch: expected '{self.expected_program_id}', "
                f"got '{agent_info.get('owner')}'"
            )

        agent_bytes = extract_account_bytes(agent_info)
        try:
            agent_data = decode_agent_account(agent_bytes)
        except Exception as exc:
            raise AgentMismatchError(f"Failed to decode AgentAccount '{claimed_agent_pubkey}': {exc}") from exc

        # Verify Canonical Agent PDA derivation
        try:
            expected_agent_pda, _ = derive_agent_pda(
                agent_data["protocol_config"],
                agent_data["agent_id"],
                self.expected_program_id,
            )
        except Exception as exc:
            raise AgentMismatchError(f"Error computing canonical Agent PDA: {exc}") from exc

        if expected_agent_pda != claimed_agent_pubkey:
            raise AgentMismatchError(
                f"Agent account address '{claimed_agent_pubkey}' does not match canonical PDA '{expected_agent_pda}'"
            )

        # 9. Preservation of Frozen Settlement Beneficiary
        # Note: in AeroSettle protocol, order.settlement_beneficiary is frozen at claim.
        # If agent ownership was transferred post-claim, agent_data["owner"] will differ,
        # but the settlement payout MUST be attributed to the frozen settlement_beneficiary.
        current_agent_owner = agent_data["owner"]

        if expected_beneficiary and settlement_beneficiary != expected_beneficiary:
            raise AgentMismatchError(
                f"Expected beneficiary '{expected_beneficiary}' does not match on-chain '{settlement_beneficiary}'"
            )

        # 10. Extract Pre-settlement Escrow Vault Balance
        pre_token_balances = meta.get("preTokenBalances") or []
        post_token_balances = meta.get("postTokenBalances") or []

        def get_token_amount(balances: list[dict[str, Any]], target_pubkey: str) -> int:
            target_idx = account_keys.index(target_pubkey) if target_pubkey in account_keys else -1
            for b in balances:
                b_idx = b.get("accountIndex")
                if (target_idx >= 0 and b_idx == target_idx) or b.get("account") == target_pubkey:
                    ui_amount = b.get("uiTokenAmount", {})
                    amount_str = ui_amount.get("amount", "0")
                    return int(amount_str)
            return 0

        pre_vault = get_token_amount(pre_token_balances, escrow_vault_pubkey)
        post_vault = get_token_amount(post_token_balances, escrow_vault_pubkey)

        if post_vault != 0:
            raise AmountMismatchError(
                f"Escrow vault '{escrow_vault_pubkey}' was not completely drained (post balance = {post_vault})"
            )

        total_escrow_settled = pre_vault
        if total_escrow_settled <= 0:
            raise AmountMismatchError(
                f"Escrow vault '{escrow_vault_pubkey}' had no pre-settlement balance ({total_escrow_settled})"
            )

        # 11. Compute exact contractual allocation matching Rust verified_operator_payout()
        try:
            contract_operator, contract_creator, contract_surplus = compute_contractual_allocation(
                payment_model=wo_data["payment_model"],
                verification_status=wo_data["verification_status"],
                total_amount=wo_data["total_amount"],
                completion_bps=wo_data["completion_bps"],
                vault_balance=total_escrow_settled,
            )
        except Exception as exc:
            raise AmountMismatchError(f"Failed to calculate contractual settlement allocation: {exc}") from exc

        # 12. Strict Token Account Validations (Fails closed on missing or third-party owners)
        def resolve_token_account_metadata(account_pubkey: str) -> tuple[str, str]:
            owner = None
            mint = None
            target_idx = account_keys.index(account_pubkey) if account_pubkey in account_keys else -1
            for b in post_token_balances + pre_token_balances:
                if (target_idx >= 0 and b.get("accountIndex") == target_idx) or b.get("account") == account_pubkey:
                    if b.get("owner"):
                        owner = b["owner"]
                    if b.get("mint"):
                        mint = b["mint"]
                    if owner and mint:
                        break

            if not owner or not mint:
                acc_info = self.rpc.get_account_info(account_pubkey)
                if acc_info:
                    raw = extract_account_bytes(acc_info)
                    if len(raw) >= 165:
                        decoded = decode_token_account(raw)
                        owner = owner or decoded.get("owner")
                        mint = mint or decoded.get("mint")

            if not owner:
                raise AccountMismatchError(
                    f"Token account '{account_pubkey}' owner is missing from transaction metadata and RPC"
                )
            if not mint:
                raise AccountMismatchError(
                    f"Token account '{account_pubkey}' mint is missing from transaction metadata and RPC"
                )

            return owner, mint

        op_owner, op_mint = resolve_token_account_metadata(operator_token_account_pubkey)
        if op_mint != mint_pubkey:
            raise AccountMismatchError(
                f"Operator token account mint '{op_mint}' does not match expected mint '{mint_pubkey}'"
            )

        if operator_token_account_pubkey != creator_refund_token_account_pubkey:
            if op_owner != settlement_beneficiary:
                raise AccountMismatchError(
                    f"Operator token account owner '{op_owner}' does not match settlement beneficiary '{settlement_beneficiary}'"
                )
            cr_owner, cr_mint = resolve_token_account_metadata(creator_refund_token_account_pubkey)
            if cr_mint != mint_pubkey:
                raise AccountMismatchError(
                    f"Creator refund token account mint '{cr_mint}' does not match expected mint '{mint_pubkey}'"
                )
            if cr_owner != wo_data["creator"]:
                raise AccountMismatchError(
                    f"Creator refund token account owner '{cr_owner}' does not match creator '{wo_data['creator']}'"
                )
        else:
            # Anchor validates both Account<TokenAccount> owner constraints before
            # executing the instruction, even when either transfer amount is zero.
            if wo_data["creator"] != settlement_beneficiary:
                raise AccountMismatchError(
                    "Shared token account requires creator and frozen settlement beneficiary to match"
                )
            if op_owner != settlement_beneficiary:
                raise AccountMismatchError(
                    f"Shared token account owner '{op_owner}' does not match creator and settlement beneficiary '{settlement_beneficiary}'"
                )

        # 13. Examine Inner TransferChecked Instructions for settle_work_order
        inner_instructions_list = meta.get("innerInstructions") or []
        settle_inner_block: Optional[dict[str, Any]] = None
        for block in inner_instructions_list:
            if block.get("index") == settle_ix_index:
                settle_inner_block = block
                break

        if settle_inner_block is None:
            raise InstructionMismatchError(
                f"Transaction '{tx_signature}' is missing inner CPI instructions for settle_work_order (index {settle_ix_index})"
            )

        inner_ix_list = settle_inner_block.get("instructions") or []

        # Determine expected CPI transfers count and order based on Rust contract:
        # In Rust:
        #   if allocation.operator_amount > 0 -> CPI 1: TransferChecked to operator_token_account
        #   if creator_refund > 0 -> CPI 2: TransferChecked to creator_refund_token_account
        expected_cpis: list[tuple[str, int, str]] = []
        if contract_operator > 0:
            expected_cpis.append((operator_token_account_pubkey, contract_operator, "operator_payout"))
        if contract_creator > 0:
            expected_cpis.append((creator_refund_token_account_pubkey, contract_creator, "creator_refund"))

        if len(inner_ix_list) != len(expected_cpis):
            raise InstructionMismatchError(
                f"Inner TransferChecked count mismatch: expected {len(expected_cpis)} CPIs "
                f"({[c[2] for c in expected_cpis]}), but found {len(inner_ix_list)} CPIs in transaction"
            )

        for cpi_idx, (expected_dest, expected_amt, cpi_role) in enumerate(expected_cpis):
            in_ix = inner_ix_list[cpi_idx]

            prog_id = None
            if "programIdIndex" in in_ix:
                pidx = in_ix["programIdIndex"]
                if 0 <= pidx < len(account_keys):
                    prog_id = account_keys[pidx]
            elif "programId" in in_ix:
                prog_id = in_ix["programId"]

            if prog_id != token_program_pubkey:
                raise InstructionMismatchError(
                    f"Unexpected inner instruction program '{prog_id}', expected '{token_program_pubkey}'"
                )

            cpi_data = b""
            if "data" in in_ix:
                raw_cpi = in_ix["data"]
                if isinstance(raw_cpi, str):
                    try:
                        cpi_data = b58decode(raw_cpi)
                    except Exception:
                        try:
                            cpi_data = base64.b64decode(raw_cpi)
                        except Exception:
                            cpi_data = b""

            if len(cpi_data) < 10 or cpi_data[0] != SPL_TOKEN_TRANSFER_CHECKED_TYPE:
                raise InstructionMismatchError(
                    "Inner CPI instruction is not a valid SPL TransferChecked instruction"
                )

            amount_transferred, decimals = decode_spl_transfer_checked(cpi_data)

            in_accounts = in_ix.get("accounts", [])
            if len(in_accounts) < 4:
                raise InstructionMismatchError("Inner TransferChecked has fewer than 4 accounts")

            cpi_source = resolve_pubkey(in_accounts[0])
            cpi_mint = resolve_pubkey(in_accounts[1])
            cpi_dest = resolve_pubkey(in_accounts[2])
            cpi_auth = resolve_pubkey(in_accounts[3])

            if cpi_source != escrow_vault_pubkey:
                raise InstructionMismatchError(
                    f"Inner transfer source '{cpi_source}' != escrow_vault '{escrow_vault_pubkey}'"
                )
            if cpi_mint != mint_pubkey:
                raise InstructionMismatchError(
                    f"Inner transfer mint '{cpi_mint}' != expected mint '{mint_pubkey}'"
                )
            if cpi_auth != escrow_vault_pubkey:
                raise InstructionMismatchError(
                    f"Inner transfer authority '{cpi_auth}' != escrow_vault '{escrow_vault_pubkey}'"
                )
            if cpi_dest != expected_dest:
                raise InstructionMismatchError(
                    f"Inner transfer {cpi_role} destination '{cpi_dest}' != expected '{expected_dest}'"
                )
            if amount_transferred != expected_amt:
                raise AmountMismatchError(
                    f"Inner transfer {cpi_role} amount {amount_transferred} != expected {expected_amt}"
                )

        operator_payout = contract_operator
        creator_refund = contract_creator
        surplus = contract_surplus

        # 14. Verify Token Balance Deltas vs Contractual Amounts
        pre_operator = get_token_amount(pre_token_balances, operator_token_account_pubkey)
        post_operator = get_token_amount(post_token_balances, operator_token_account_pubkey)

        pre_creator = get_token_amount(pre_token_balances, creator_refund_token_account_pubkey)
        post_creator = get_token_amount(post_token_balances, creator_refund_token_account_pubkey)

        if operator_token_account_pubkey == creator_refund_token_account_pubkey:
            delta_combined = post_operator - pre_operator
            if delta_combined != (operator_payout + creator_refund):
                raise AmountMismatchError(
                    f"Combined balance delta ({delta_combined}) != total distribution ({operator_payout + creator_refund})"
                )
        else:
            delta_operator = post_operator - pre_operator
            delta_creator = post_creator - pre_creator

            if delta_operator != operator_payout:
                raise AmountMismatchError(
                    f"Operator balance delta ({delta_operator}) != expected payout ({operator_payout})"
                )
            if delta_creator != creator_refund:
                raise AmountMismatchError(
                    f"Creator refund delta ({delta_creator}) != expected refund ({creator_refund})"
                )

        # Invariant: Conservation of value
        if operator_payout + creator_refund != total_escrow_settled:
            raise AmountMismatchError(
                f"Conservation of value violated: operator_payout ({operator_payout}) + "
                f"creator_refund ({creator_refund}) != total_escrow_settled ({total_escrow_settled})"
            )

        if expected_operator_amount is not None and operator_payout != expected_operator_amount:
            raise AmountMismatchError(
                f"Operator payout mismatch: expected {expected_operator_amount}, on-chain delta is {operator_payout}"
            )

        # 15. Derive verified agent identities
        verified_agent_account = claimed_agent_pubkey
        verified_agent_id = agent_data["agent_id"].hex()
        # The financial recipient of this settlement is the frozen settlement beneficiary
        verified_owner_pubkey = settlement_beneficiary

        # 16. Build Financial Effect Identifier & Canonical Evidence Hash
        effect_id = build_financial_effect_id(
            network=self.expected_network,
            genesis_hash=self.expected_genesis_hash,
            tx_signature=tx_signature,
            instruction_index=settle_ix_index,
            destination=operator_token_account_pubkey,
            mint=mint_pubkey,
        )

        evidence_payload = {
            "network": self.expected_network,
            "genesis_hash": self.expected_genesis_hash,
            "program_id": self.expected_program_id,
            "tx_signature": tx_signature,
            "slot": slot,
            "instruction_index": settle_ix_index,
            "work_order_account": work_order_pubkey,
            "agent_account": verified_agent_account,
            "agent_id": verified_agent_id,
            "owner_pubkey": verified_owner_pubkey,
            "settlement_beneficiary": settlement_beneficiary,
            "agent_owner_current": current_agent_owner,
            "token_mint": mint_pubkey,
            "escrow_vault": escrow_vault_pubkey,
            "operator_token_account": operator_token_account_pubkey,
            "creator_refund_token_account": creator_refund_token_account_pubkey,
            "operator_payout": operator_payout,
            "creator_refund": creator_refund,
            "total_escrow_settled": total_escrow_settled,
            "surplus": surplus,
            "evidence_source": effective_source.value,
            "effect_id": effect_id,
        }
        evidence_hash = compute_canonical_evidence_hash(evidence_payload)

        receipt = SettlementReceipt(
            network=self.expected_network,
            genesis_hash=self.expected_genesis_hash,
            program_id=self.expected_program_id,
            tx_signature=tx_signature,
            slot=slot,
            block_time=block_time,
            instruction_index=settle_ix_index,
            work_order_account=work_order_pubkey,
            agent_account=verified_agent_account,
            agent_id=verified_agent_id,
            owner_pubkey=verified_owner_pubkey,
            settlement_beneficiary=settlement_beneficiary,
            agent_owner_current=current_agent_owner,
            token_mint=mint_pubkey,
            escrow_vault=escrow_vault_pubkey,
            operator_token_account=operator_token_account_pubkey,
            creator_refund_token_account=creator_refund_token_account_pubkey,
            operator_payout=operator_payout,
            creator_refund=creator_refund,
            total_escrow_settled=total_escrow_settled,
            surplus=surplus,
            commitment=actual_tx_commitment,
            evidence_source=effective_source.value,
            effect_id=effect_id,
            evidence_hash=evidence_hash,
        )

        self.reconciled_receipts[tx_signature] = receipt
        return receipt

    # ─────────────────────────────────────────────────────────────────────────
    # ReconciliationVerifier Protocol Implementation
    # ─────────────────────────────────────────────────────────────────────────

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
        """Verifies an economic movement promotion request against authentic on-chain evidence.

        Implements the ReconciliationVerifier protocol defined in CON-22.
        Enforces that RECONCILED status strictly requires finalized commitment.
        """
        if authorized_by != self.authority:
            logger.warning(
                "Reconciliation rejected: unauthorized authority '%s' (expected '%s')",
                authorized_by,
                self.authority,
            )
            return False

        try:
            expected_wo = movement.work_order_account if movement else None
            expected_mint = movement.token_mint if movement else None
            expected_amt = movement.amount_base_units if movement else None
            expected_beneficiary = movement.owner_pubkey if movement else None

            # Strictly require finalized commitment for RECONCILED status
            receipt = self.verify_settlement_transaction(
                tx_signature,
                expected_work_order=expected_wo,
                expected_mint=expected_mint,
                expected_beneficiary=expected_beneficiary,
                expected_operator_amount=expected_amt,
                require_finalized=True,
            )
        except Exception as exc:
            logger.warning("Reconciliation verification failed for tx '%s': %s", tx_signature, exc)
            return False

        # Verify that movement agent identities match verified receipt
        if movement:
            if movement.agent_account != receipt.agent_account:
                logger.warning(
                    "Reconciliation rejected: movement agent_account '%s' != verified '%s'",
                    movement.agent_account,
                    receipt.agent_account,
                )
                return False
            if movement.owner_pubkey != receipt.owner_pubkey:
                logger.warning(
                    "Reconciliation rejected: movement owner_pubkey '%s' != verified '%s'",
                    movement.owner_pubkey,
                    receipt.owner_pubkey,
                )
                return False

        # Slot consistency: tx slot must be at or after the claimed slot
        if receipt.slot < slot:
            logger.warning(
                "Reconciliation rejected: on-chain slot %d < claimed slot %d",
                receipt.slot,
                slot,
            )
            return False

        # Canonical evidence hash verification
        clean_evidence_hash = (
            evidence_hash[7:] if evidence_hash.startswith("sha256:") else evidence_hash
        )
        if clean_evidence_hash != receipt.evidence_hash:
            logger.warning(
                "Reconciliation rejected: evidence_hash mismatch (caller='%s', receipt='%s')",
                clean_evidence_hash,
                receipt.evidence_hash,
            )
            return False

        return True

    # ─────────────────────────────────────────────────────────────────────────
    # High-Level Settlement Ingestion
    # ─────────────────────────────────────────────────────────────────────────

    def reconcile_settlement(
        self,
        ledger: Any,  # EconomicLedger instance
        *,
        tx_signature: str,
        work_order_account: Optional[str] = None,
        agent_account: Optional[str] = None,
        agent_id: Optional[str] = None,
        owner_pubkey: Optional[str] = None,
        authorized_by: Optional[str] = None,
        source_kind: Optional[EvidenceSourceKind] = None,
    ) -> tuple[EconomicMovement, SettlementReceipt]:
        """Atomically ingests and reconciles an authentic on-chain settlement into EconomicLedger.

        Finality Policy:
        - If transaction is only 'confirmed', records an observed PROVISIONAL movement.
          Does NOT promote to RECONCILED until finalized.
        - If transaction is 'finalized', records/promotes movement to RECONCILED.
        - Preserves the frozen settlement_beneficiary from WorkOrderAccount even if
          ownership was transferred post-claim.
        """
        auth = authorized_by or self.authority

        # First attempt to verify at finalized; if not available, fall back to confirmed for observation
        is_finalized = True
        try:
            receipt = self.verify_settlement_transaction(
                tx_signature,
                expected_work_order=work_order_account,
                require_finalized=True,
                source_kind=source_kind,
            )
        except CommitmentUnsatisfiedError:
            is_finalized = False
            receipt = self.verify_settlement_transaction(
                tx_signature,
                expected_work_order=work_order_account,
                require_finalized=False,
                source_kind=source_kind,
            )

        # Cross-validate caller-provided agent parameters against verified on-chain accounts
        if agent_account is not None and agent_account != receipt.agent_account:
            raise AgentMismatchError(
                f"Caller-provided agent_account '{agent_account}' does not match "
                f"verified on-chain AgentAccount '{receipt.agent_account}'"
            )

        if owner_pubkey is not None and owner_pubkey != receipt.owner_pubkey:
            raise AgentMismatchError(
                f"Caller-provided owner_pubkey '{owner_pubkey}' does not match "
                f"verified settlement beneficiary '{receipt.owner_pubkey}'"
            )

        if agent_id is not None:
            clean_id = agent_id.lower().replace("-", "")
            if clean_id != receipt.agent_id.lower() and clean_id != receipt.agent_account:
                raise AgentMismatchError(
                    f"Caller-provided agent_id '{agent_id}' does not match "
                    f"verified on-chain agent_id '{receipt.agent_id}'"
                )

        wo_account = receipt.work_order_account
        ag_account = receipt.agent_account
        ag_id = receipt.agent_id
        own_pubkey = receipt.owner_pubkey

        def assert_same_effect(movement: EconomicMovement) -> None:
            expected = {
                "idempotency_key": receipt.effect_id,
                "agent_id": receipt.agent_id,
                "agent_account": receipt.agent_account,
                "owner_pubkey": receipt.owner_pubkey,
                "network": receipt.network,
                "genesis_hash": receipt.genesis_hash,
                "program_id": receipt.program_id,
                "token_mint": receipt.token_mint,
                "amount_base_units": receipt.operator_payout,
                "work_order_account": receipt.work_order_account,
                "tx_signature": receipt.tx_signature,
                "evidence_hash": receipt.evidence_hash,
            }
            for field, value in expected.items():
                if getattr(movement, field) != value:
                    raise IdempotencyConflictError(
                        f"Existing movement conflicts with verified settlement field '{field}'"
                    )

        # Check if movement already exists for this idempotent financial effect
        existing = ledger.get_by_idempotency_key(receipt.effect_id)
        if existing:
            assert_same_effect(existing)
            if existing.status == MovementStatus.RECONCILED:
                return existing, receipt

            if is_finalized:
                reconciled = ledger.reconcile_movement(
                    existing.movement_id,
                    evidence_hash=receipt.evidence_hash,
                    authorized_by=auth,
                    slot=receipt.slot,
                    tx_signature=tx_signature,
                )
                return reconciled, receipt
            else:
                return existing, receipt

        # Check by work_order_account and tx_signature fallback
        movements, _ = ledger.list_movements(ag_account, limit=100)
        matching = [
            m for m in movements
            if m.work_order_account == wo_account and m.tx_signature == tx_signature
        ]
        if matching:
            target_mov = matching[0]
            assert_same_effect(target_mov)
            if target_mov.status == MovementStatus.RECONCILED:
                return target_mov, receipt
            if is_finalized:
                reconciled = ledger.reconcile_movement(
                    target_mov.movement_id,
                    evidence_hash=receipt.evidence_hash,
                    authorized_by=auth,
                    slot=receipt.slot,
                    tx_signature=tx_signature,
                )
                return reconciled, receipt
            else:
                return target_mov, receipt

        # Record initial PROVISIONAL movement with exact verified operator payout
        nature = MovementNature.INCOME if receipt.operator_payout > 0 else MovementNature.ADJUSTMENT
        meta = {
            "reconciliation_effect": "operator_payout",
            "evidence_source": receipt.evidence_source,
            "settlement_beneficiary": receipt.settlement_beneficiary,
            "agent_owner_current": receipt.agent_owner_current,
            "ownership_transferred_post_claim": receipt.agent_owner_current != receipt.settlement_beneficiary,
            "settlement_receipt": receipt.to_dict(),
        }

        provisional = ledger.record_movement(
            idempotency_key=receipt.effect_id,
            agent_id=ag_id,
            agent_account=ag_account,
            owner_pubkey=own_pubkey,
            network=receipt.network,
            genesis_hash=receipt.genesis_hash,
            program_id=receipt.program_id,
            token_mint=receipt.token_mint,
            amount_base_units=receipt.operator_payout,
            nature=nature,
            status=MovementStatus.PROVISIONAL,
            provenance_source=ProvenanceSource.ONCHAIN_VERIFIED,
            work_order_account=wo_account,
            tx_signature=tx_signature,
            evidence_hash=receipt.evidence_hash,
            metadata=meta,
        )

        if not is_finalized:
            # Finality gate: confirmed movement remains PROVISIONAL
            return provisional, receipt

        # Promote to RECONCILED once finalized
        reconciled = ledger.reconcile_movement(
            provisional.movement_id,
            evidence_hash=receipt.evidence_hash,
            authorized_by=auth,
            slot=receipt.slot,
            tx_signature=tx_signature,
        )

        return reconciled, receipt


# ─────────────────────────────────────────────────────────────────────────────
# Historical Localnet Audit & Verification Helpers
# ─────────────────────────────────────────────────────────────────────────────


def audit_historical_localnet_settlement(
    rpc_client: Optional[SolanaRpcClientProtocol] = None,
    rpc_url: str = "http://127.0.0.1:8899",
) -> dict[str, Any]:
    """Inspects the historical Localnet deployment in read-only mode.

    Explicitly reports when live historical transactions are unverifiable due to
    validator downtime, preventing synthetic data from masquerading as authentic proof.
    """
    client = rpc_client or SolanaRpcClient(rpc_url)
    target_wo = "EnkZQWDqF5HeFeusZ7xnj7tngVN9xASofmKvXtDLeqbx"

    try:
        genesis = client.get_genesis_hash()
        if genesis != DEFAULT_GENESIS_HASH:
            return {
                "status": "UNVERIFIABLE_ON_LIVE_RPC",
                "live_verified": False,
                "reason": f"Cluster genesis hash mismatch: expected {DEFAULT_GENESIS_HASH}, got {genesis}",
                "target_work_order": target_wo,
            }

        wo_info = client.get_account_info(target_wo)
        if wo_info is None:
            return {
                "status": "UNVERIFIABLE_ON_LIVE_RPC",
                "live_verified": False,
                "reason": "Localnet validator is running but target WorkOrder account was not found in live memory.",
                "target_work_order": target_wo,
            }

        return {
            "status": "LIVE_ACCOUNT_DETECTED",
            "live_verified": True,
            "target_work_order": target_wo,
            "account_info": wo_info,
        }
    except Exception as exc:
        return {
            "status": "UNVERIFIABLE_ON_LIVE_RPC",
            "live_verified": False,
            "reason": f"Localnet validator at {rpc_url} is offline or unreachable: {exc}",
            "target_work_order": target_wo,
        }
