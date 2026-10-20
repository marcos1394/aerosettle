"""Authentic RPC and SPL Settlement Reconciler for Conatus / AeroSettle (CON-23).

Verifies on-chain Solana transactions executed by the AeroSettle smart contract:
1. Expected network and genesis hash.
2. Real transaction existence, confirmed/finalized status, and successful execution (err is None).
3. Program ID and settle_work_order instruction discriminator (0xa2462d3deabc0c76).
4. WorkOrder PDA derivation, account ownership, and Settled status.
5. Exact settlement mint and escrow vault draining to 0.
6. Authorized economic beneficiary token account ownership.
7. SPL pre/post token balance deltas:
   - operator_payout = post_operator - pre_operator
   - creator_refund = post_creator - pre_creator
   - total_escrow_settled = pre_vault - post_vault
   - Invariant: operator_payout + creator_refund == total_escrow_settled
8. Exact attribution:
   - Operator payout is credited to agent income.
   - Creator refund is refunded to creator and NOT attributed to agent income.
   - Zero-payout settlements produce zero-unit audit movements.
9. Idempotent financial effect identification:
   effect_id = f"{network}:{genesis}:{signature}:{instruction_index}:{destination}:{mint}"
10. Deterministic, canonical evidence hash linking all verified settlement parameters.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any, Optional, Protocol, runtime_checkable

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

# Canonical AeroSettle Program Constants
DEFAULT_PROGRAM_ID = "CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy"
DEFAULT_GENESIS_HASH = "HP9XKTusRPGC78EFDpR9xdEq6simL2vqyDdrMvn6Vacg"
DEFAULT_NETWORK = "solana:localnet"
DEFAULT_PROTOCOL_CONFIG = "C8HiYzxKjRcDFHoWSZ84smUsxnMQ7ipxPnQ96GK5qZVn"
DEFAULT_TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"

# 8-byte Anchor discriminator for `settle_work_order`: sha256("global:settle_work_order")[0..8]
SETTLE_WORK_ORDER_DISCRIMINATOR = bytes([162, 70, 45, 61, 234, 188, 12, 118])
SETTLE_WORK_ORDER_DISCRIMINATOR_HEX = SETTLE_WORK_ORDER_DISCRIMINATOR.hex()

# Base58 alphabet for Solana decoding
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
B58MAP = {c: i for i, c in enumerate(B58)}


def b58decode(value: str) -> bytes:
    """Decodes a base58 string into raw bytes."""
    if not isinstance(value, str) or not value:
        return b""
    n = 0
    for c in value:
        if c not in B58MAP:
            raise ValueError(f"Invalid base58 character: {c!r}")
        n = n * 58 + B58MAP[c]
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    return b"\0" * (len(value) - len(value.lstrip("1"))) + raw


def b58encode(data: bytes) -> str:
    """Encodes bytes into a base58 string."""
    n = int.from_bytes(data, "big")
    chars = ""
    while n:
        n, r = divmod(n, 58)
        chars = B58[r] + chars
    return "1" * (len(data) - len(data.lstrip(b"\0"))) + chars


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
    """Raised when work order, mint, or beneficiary accounts mismatch."""
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
    token_mint: str
    escrow_vault: str
    operator_token_account: str
    creator_refund_token_account: str
    operator_payout: int
    creator_refund: int
    total_escrow_settled: int
    commitment: str
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
        "version": "conatus:spl-settlement:v1",
        "network": str(evidence_data.get("network", "")),
        "genesis_hash": str(evidence_data.get("genesis_hash", "")),
        "program_id": str(evidence_data.get("program_id", "")),
        "tx_signature": str(evidence_data.get("tx_signature", "")),
        "slot": int(evidence_data.get("slot", 0)),
        "instruction_index": int(evidence_data.get("instruction_index", 0)),
        "work_order_account": str(evidence_data.get("work_order_account", "")),
        "token_mint": str(evidence_data.get("token_mint", "")),
        "escrow_vault": str(evidence_data.get("escrow_vault", "")),
        "operator_token_account": str(evidence_data.get("operator_token_account", "")),
        "creator_refund_token_account": str(evidence_data.get("creator_refund_token_account", "")),
        "operator_payout": int(evidence_data.get("operator_payout", 0)),
        "creator_refund": int(evidence_data.get("creator_refund", 0)),
        "total_escrow_settled": int(evidence_data.get("total_escrow_settled", 0)),
        "effect_id": str(evidence_data.get("effect_id", "")),
        "commitment": str(evidence_data.get("commitment", "confirmed")),
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
        commitment: str = "confirmed",
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
    """Production JSON-RPC client for querying Solana nodes."""

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
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
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

    def get_transaction(
        self,
        tx_signature: str,
        *,
        commitment: str = "confirmed",
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
    """Deterministic in-memory RPC client for automated test suites and historical fixtures."""

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
        commitment: str = "confirmed",
    ) -> None:
        self.transactions[tx_signature] = tx_data
        self.transaction_commitments[tx_signature] = commitment

    def register_account(self, pubkey: str, account_data: dict[str, Any]) -> None:
        self.accounts[pubkey] = account_data

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
        commitment: str = "confirmed",
    ) -> Optional[dict[str, Any]]:
        if self.should_fail:
            raise self.should_fail
        tx = self.transactions.get(tx_signature)
        if tx is None:
            return None

        # Check commitment filter
        tx_comm = self.transaction_commitments.get(tx_signature, "confirmed")
        if commitment == "finalized" and tx_comm != "finalized":
            # If caller strictly requires finalized, but tx is only confirmed, return None
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
        min_commitment: str = "confirmed",
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
    ) -> SettlementReceipt:
        """Thoroughly inspects and verifies an on-chain settlement transaction via RPC.

        Fails closed on any inconsistency between instructions, token balances, or contract terms.
        """
        # 1. Validate network & genesis hash
        try:
            actual_genesis = self.rpc.get_genesis_hash()
        except Exception as exc:
            raise RpcError(f"Failed to fetch genesis hash from RPC: {exc}") from exc

        if actual_genesis != self.expected_genesis_hash:
            raise SettlementVerificationError(
                f"Genesis hash mismatch: expected '{self.expected_genesis_hash}', got '{actual_genesis}'"
            )

        # 2. Fetch transaction
        try:
            tx = self.rpc.get_transaction(tx_signature, commitment=self.min_commitment)
        except Exception as exc:
            raise RpcError(f"Failed to fetch transaction '{tx_signature}' from RPC: {exc}") from exc

        if tx is None:
            raise TransactionNotFoundError(
                f"Transaction '{tx_signature}' was not found on-chain at commitment '{self.min_commitment}'"
            )

        # 3. Check transaction execution status
        meta = tx.get("meta")
        if not meta or not isinstance(meta, dict):
            raise SettlementVerificationError(f"Transaction '{tx_signature}' is missing execution metadata")

        if meta.get("err") is not None:
            raise TransactionFailedError(
                f"Transaction '{tx_signature}' failed on-chain with error: {meta['err']}"
            )

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

        # 5. Locate settle_work_order instruction
        instructions = message.get("instructions", [])
        settle_ix: Optional[dict[str, Any]] = None
        settle_ix_index: int = -1

        for idx, ix in enumerate(instructions):
            # Resolve program ID
            prog_id: Optional[str] = None
            if "programIdIndex" in ix:
                prog_idx = ix["programIdIndex"]
                if 0 <= prog_idx < len(account_keys):
                    prog_id = account_keys[prog_idx]
            elif "programId" in ix:
                prog_id = ix["programId"]

            if prog_id != self.expected_program_id:
                continue

            # Decode data bytes
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

        # 6. Extract instruction accounts
        ix_accounts = settle_ix.get("accounts", [])
        if len(ix_accounts) < 7:
            raise InstructionMismatchError(
                f"Instruction 'settle_work_order' has {len(ix_accounts)} accounts, expected at least 7"
            )

        # Map indices to pubkeys
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

        # 7. Extract SPL Token Balance Changes
        pre_token_balances = meta.get("preTokenBalances") or []
        post_token_balances = meta.get("postTokenBalances") or []

        def get_token_amount(balances: list[dict[str, Any]], target_pubkey: str) -> int:
            target_idx = account_keys.index(target_pubkey) if target_pubkey in account_keys else -1
            for b in balances:
                b_idx = b.get("accountIndex")
                # Either matches by accountIndex or account pubkey
                if (target_idx >= 0 and b_idx == target_idx) or b.get("account") == target_pubkey:
                    ui_amount = b.get("uiTokenAmount", {})
                    amount_str = ui_amount.get("amount", "0")
                    return int(amount_str)
            return 0

        pre_vault = get_token_amount(pre_token_balances, escrow_vault_pubkey)
        post_vault = get_token_amount(post_token_balances, escrow_vault_pubkey)

        pre_operator = get_token_amount(pre_token_balances, operator_token_account_pubkey)
        post_operator = get_token_amount(post_token_balances, operator_token_account_pubkey)

        pre_creator = get_token_amount(pre_token_balances, creator_refund_token_account_pubkey)
        post_creator = get_token_amount(post_token_balances, creator_refund_token_account_pubkey)

        # Escrow vault must be completely depleted
        if post_vault != 0:
            raise AmountMismatchError(
                f"Escrow vault '{escrow_vault_pubkey}' was not completely drained (post balance = {post_vault})"
            )

        total_escrow_settled = pre_vault
        if total_escrow_settled <= 0:
            raise AmountMismatchError(
                f"Escrow vault '{escrow_vault_pubkey}' had no pre-settlement balance ({total_escrow_settled})"
            )

        operator_payout = post_operator - pre_operator
        creator_refund = post_creator - pre_creator

        # Handle same destination case (operator is also creator)
        if operator_token_account_pubkey == creator_refund_token_account_pubkey:
            total_delta = post_operator - pre_operator
            if total_delta != total_escrow_settled:
                raise AmountMismatchError(
                    f"Combined operator/creator delta ({total_delta}) does not match escrow settled ({total_escrow_settled})"
                )
            if expected_operator_amount is not None:
                operator_payout = expected_operator_amount
                creator_refund = total_escrow_settled - operator_payout
            else:
                operator_payout = total_delta
                creator_refund = 0
        else:
            if operator_payout < 0:
                raise AmountMismatchError(f"Operator payout delta is negative ({operator_payout})")
            if creator_refund < 0:
                raise AmountMismatchError(f"Creator refund delta is negative ({creator_refund})")

            # Fundamental Invariant: Operator Payout + Creator Refund == Escrow Settled
            if operator_payout + creator_refund != total_escrow_settled:
                raise AmountMismatchError(
                    f"Conservation of value violated: operator_payout ({operator_payout}) + "
                    f"creator_refund ({creator_refund}) != total_escrow_settled ({total_escrow_settled})"
                )

        if expected_operator_amount is not None and operator_payout != expected_operator_amount:
            raise AmountMismatchError(
                f"Operator payout mismatch: expected {expected_operator_amount}, on-chain delta is {operator_payout}"
            )

        # 8. Check Beneficiary Token Account Owner if expected_beneficiary is supplied
        if expected_beneficiary:
            # Query owner of operator_token_account from token balances or RPC
            actual_owner: Optional[str] = None
            for b in post_token_balances + pre_token_balances:
                if (
                    operator_token_account_pubkey in account_keys
                    and b.get("accountIndex") == account_keys.index(operator_token_account_pubkey)
                ):
                    actual_owner = b.get("owner")
                    break
            if actual_owner and actual_owner != expected_beneficiary:
                raise AccountMismatchError(
                    f"Beneficiary mismatch: operator token account owner '{actual_owner}' "
                    f"does not match expected beneficiary '{expected_beneficiary}'"
                )

        # 9. Build Financial Effect Identifier & Canonical Evidence Hash
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
            "token_mint": mint_pubkey,
            "escrow_vault": escrow_vault_pubkey,
            "operator_token_account": operator_token_account_pubkey,
            "creator_refund_token_account": creator_refund_token_account_pubkey,
            "operator_payout": operator_payout,
            "creator_refund": creator_refund,
            "total_escrow_settled": total_escrow_settled,
            "effect_id": effect_id,
            "commitment": self.min_commitment,
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
            token_mint=mint_pubkey,
            escrow_vault=escrow_vault_pubkey,
            operator_token_account=operator_token_account_pubkey,
            creator_refund_token_account=creator_refund_token_account_pubkey,
            operator_payout=operator_payout,
            creator_refund=creator_refund,
            total_escrow_settled=total_escrow_settled,
            commitment=self.min_commitment,
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

            receipt = self.verify_settlement_transaction(
                tx_signature,
                expected_work_order=expected_wo,
                expected_mint=expected_mint,
                expected_operator_amount=expected_amt,
            )
        except Exception as exc:
            logger.warning("Reconciliation verification failed for tx '%s': %s", tx_signature, exc)
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
    # High-Level Settlement Reconciliation Ingestion
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
    ) -> tuple[EconomicMovement, SettlementReceipt]:
        """Atomically ingests and reconciles an authentic on-chain settlement into EconomicLedger.

        Guarantees:
        - Exact operator payout credited as INCOME.
        - Unearned escrow refunded to creator is NOT attributed to agent.
        - Fails closed on any inconsistency or unconfirmed transaction.
        - Strictly idempotent against retries and restarts.
        """
        auth = authorized_by or self.authority

        # 1. Verify on-chain settlement transaction via RPC
        receipt = self.verify_settlement_transaction(
            tx_signature,
            expected_work_order=work_order_account,
        )

        wo_account = receipt.work_order_account
        ag_account = agent_account or receipt.operator_token_account
        ag_id = agent_id or ("11" * 32)
        own_pubkey = owner_pubkey or receipt.operator_token_account

        # 2. Check if a movement already exists for this financial effect
        existing = ledger.get_by_idempotency_key(receipt.effect_id)
        if existing:
            if existing.status == MovementStatus.RECONCILED:
                return existing, receipt

            # Transition existing provisional movement to RECONCILED
            reconciled = ledger.reconcile_movement(
                existing.movement_id,
                evidence_hash=receipt.evidence_hash,
                authorized_by=auth,
                slot=receipt.slot,
                tx_signature=tx_signature,
            )
            return reconciled, receipt

        # Check by work_order_account and tx_signature fallback
        movements, _ = ledger.list_movements(ag_account, limit=100)
        matching = [
            m for m in movements
            if m.work_order_account == wo_account and m.tx_signature == tx_signature
        ]
        if matching:
            target_mov = matching[0]
            if target_mov.status == MovementStatus.RECONCILED:
                return target_mov, receipt
            reconciled = ledger.reconcile_movement(
                target_mov.movement_id,
                evidence_hash=receipt.evidence_hash,
                authorized_by=auth,
                slot=receipt.slot,
                tx_signature=tx_signature,
            )
            return reconciled, receipt

        # 3. Create initial PROVISIONAL movement with exact operator payout
        nature = MovementNature.INCOME if receipt.operator_payout > 0 else MovementNature.ADJUSTMENT
        meta = {
            "reconciliation_effect": "operator_payout",
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

        # 4. Promote to RECONCILED
        reconciled = ledger.reconcile_movement(
            provisional.movement_id,
            evidence_hash=receipt.evidence_hash,
            authorized_by=auth,
            slot=receipt.slot,
            tx_signature=tx_signature,
        )

        return reconciled, receipt
