"""Comprehensive test suite for Authentic SPL Settlement Reconciliation (CON-23).

Covers all mandatory test conditions specified in Jira CON-23 and the audit feedback:
1. Valid settlement with full payout (Fixed 100% Accepted).
2. Proportional settlement (partial operator payout + partial creator refund).
3. Creator refund settlement (Rejected / 0% payout -> 100% creator refund).
4. Zero payout settlement (audit entry created, never positive income).
5. Non-existent signature (fails closed with TransactionNotFoundError).
6. Wrong program ID (fails closed with InstructionMismatchError).
7. Incorrect token mint (fails closed with AccountMismatchError).
8. Incorrect beneficiary (fails closed with AccountMismatchError).
9. Non-existent or mismatched SPL transfer amount (fails closed with AmountMismatchError).
10. Failed on-chain transaction (meta.err != null -> fails closed with TransactionFailedError).
11. Event repetition & idempotency (retries return existing reconciled movement without duplicating).
12. Process restart & disk persistence reload (balances and status preserved across restarts).
13. RPC failure & timeout handling (fails closed without corrupting provisional state).
14. Differences between confirmed and finalized commitments (finality gating).
15. Integration with live RPC probe and historical case fixture.
16. Negative: WorkOrder account not found on-chain.
17. Negative: WorkOrder wrong owner.
18. Negative: WorkOrder wrong Anchor discriminator.
19. Negative: WorkOrder address does not match canonical PDA derivation from seeds.
20. Negative: WorkOrder status is not Settled (e.g. Verified or Open).
21. Negative: Claimed AgentAccount not found on-chain.
22. Negative: Claimed AgentAccount wrong owner.
23. Negative: Claimed AgentAccount wrong discriminator.
24. Negative: Claimed AgentAccount address does not match canonical PDA derivation.
25. Negative: AgentAccount owner != WorkOrder frozen settlement beneficiary.
26. Negative: Caller provided mismatching agent_account, agent_id, or owner_pubkey.
27. Adversarial: Multi-instruction transaction (settle_work_order preceded and followed by other instructions).
28. Adversarial: Inner TransferChecked amount does not match token balance deltas.
29. Adversarial: Inner TransferChecked routed to unauthorized destination.
30. Adversarial: Shared destination for operator and creator does not misattribute total vault to operator.
31. Adversarial: Donated surplus in escrow vault is refunded to creator and not paid to operator.
32. Historical Localnet: Live RPC probe explicitly reports UNVERIFIABLE_ON_LIVE_RPC when validator is offline.
"""
from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any, Optional

from tools.economic_ledger.ledger import DEFAULT_TRUSTED_RECONCILER_AUTHORITIES, EconomicLedger
from tools.economic_ledger.models import (
    IdempotencyConflictError,
    LedgerValidationError,
    MovementNature,
    MovementStatus,
    ProvenanceSource,
)
from tools.economic_ledger.spl_reconciler import (
    DEFAULT_GENESIS_HASH,
    DEFAULT_NETWORK,
    DEFAULT_PROGRAM_ID,
    DEFAULT_PROTOCOL_CONFIG,
    DEFAULT_TOKEN_PROGRAM,
    SETTLE_WORK_ORDER_DISCRIMINATOR,
    AccountMismatchError,
    AgentMismatchError,
    AmountMismatchError,
    CommitmentUnsatisfiedError,
    EvidenceSourceKind,
    InstructionMismatchError,
    MockRpcClient,
    RpcError,
    SettlementReceipt,
    SettlementVerificationError,
    SolanaRpcClient,
    SplSettlementReconciler,
    TransactionFailedError,
    TransactionNotFoundError,
    WorkOrderNotSettledError,
    WorkOrderStatus,
    audit_historical_localnet_settlement,
    b58decode,
    b58encode,
    build_financial_effect_id,
    compute_canonical_evidence_hash,
    derive_agent_pda,
    derive_escrow_vault_pda,
    derive_work_order_pda,
    encode_agent_account,
    encode_spl_transfer_checked,
    encode_token_account,
    encode_work_order_account,
)

# Canonical historical entities from AeroSettle testbed
WORK_ORDER_TARGET = "EnkZQWDqF5HeFeusZ7xnj7tngVN9xASofmKvXtDLeqbx"
CREATOR_TARGET = "9aA2jeb1Cds7m4VMhYRpGCv9UJzdREZBZAVEYmBxAzeZ"
BENEFICIARY_TARGET = "8rPDpYsLZxNBm8Q8GKSKki8Ag6dodkasedhUT9x3Ec1D"
AGENT_TARGET = "DcusvnYAdFFKzNDVzUkUvmgZ9fDhzszeRR5Fj8F5dMbB"
MINT_TARGET = "HTHpns7gqLAhSBhAzqxhYdyHv9HeXkkRW6aHQfdUjL1G"
VAULT_TARGET = "6nWoFVfJayAbJmkqWnJHfCCHCCvJMj3AGQ9iLtBEGt4k"
PAYOUT_ACCOUNT_TARGET = "4rP2ysKwup5pFKmk7L3hBDdedp3tytcoDQvwNy5xqpoG"
REFUND_ACCOUNT_TARGET = "ATGAiYWA7gXAWmCZyzHK2J52G8sw8Ccre38RhPHQMEgr"
FEE_PAYER = "8rPDpYsLZxNBm8Q8GKSKki8Ag6dodkasedhUT9x3Ec1D"
TRUSTED_AUTHORITY = "conatus:protocol:reconciler:v1"

WO_ID_TARGET = bytes.fromhex("42da2b1aa632c52591c8b6ed2806001335e8d2b85af9174b6e8010e28885a99e")
AGENT_ID_TARGET = bytes.fromhex("04bf7a1d47e225b5ffa90aa190d6f2be0c295aa1eff11f9330c10893b6ecae3b")


def get_single_balance(ledger: EconomicLedger, agent_account: str, token_mint: str) -> tuple[int, int]:
    """Helper returning (reconciled, provisional) amounts for an agent and mint."""
    reports = ledger.get_balances(agent_account, token_mint=token_mint)
    if not reports:
        return 0, 0
    return reports[0].reconciled_balance, reports[0].provisional_balance


def setup_canonical_mock_accounts(
    mock_rpc: MockRpcClient,
    *,
    work_order_pubkey: str = WORK_ORDER_TARGET,
    work_order_id: bytes = WO_ID_TARGET,
    creator: str = CREATOR_TARGET,
    token_mint: str = MINT_TARGET,
    total_amount: int = 10_000_000,
    escrow_vault: str = VAULT_TARGET,
    work_order_status: int = WorkOrderStatus.Settled.value,
    claimed_agent: str = AGENT_TARGET,
    settlement_beneficiary: str = BENEFICIARY_TARGET,
    agent_id: bytes = AGENT_ID_TARGET,
    agent_owner: str = BENEFICIARY_TARGET,
    operator_token_account: str = PAYOUT_ACCOUNT_TARGET,
    creator_refund_token_account: str = REFUND_ACCOUNT_TARGET,
    work_order_owner: str = DEFAULT_PROGRAM_ID,
    agent_owner_program: str = DEFAULT_PROGRAM_ID,
    custom_wo_raw: Optional[bytes] = None,
    custom_agent_raw: Optional[bytes] = None,
) -> None:
    """Registers authentic decoded on-chain accounts into MockRpcClient."""
    if custom_wo_raw is not None:
        mock_rpc.register_account(work_order_pubkey, custom_wo_raw, owner=work_order_owner)
    else:
        wo_raw = encode_work_order_account(
            protocol_config=DEFAULT_PROTOCOL_CONFIG,
            work_order_id=work_order_id,
            creator=creator,
            token_mint=token_mint,
            total_amount=total_amount,
            verifier="DmWQhuVujHrJb4jFzo62UnCT3mwnx9GFtVdo8VUu82Wu",
            escrow_vault=escrow_vault,
            status=work_order_status,
            claimed_agent=claimed_agent,
            settlement_beneficiary=settlement_beneficiary,
        )
        mock_rpc.register_account(work_order_pubkey, wo_raw, owner=work_order_owner)

    if custom_agent_raw is not None:
        mock_rpc.register_account(claimed_agent, custom_agent_raw, owner=agent_owner_program)
    else:
        ag_raw = encode_agent_account(
            protocol_config=DEFAULT_PROTOCOL_CONFIG,
            agent_id=agent_id,
            owner=agent_owner,
            signing_authority=agent_owner,
        )
        mock_rpc.register_account(claimed_agent, ag_raw, owner=agent_owner_program)

    # Register token accounts
    mock_rpc.register_account(
        operator_token_account,
        encode_token_account(mint=token_mint, owner=settlement_beneficiary, amount=total_amount),
        owner=DEFAULT_TOKEN_PROGRAM,
    )
    if creator_refund_token_account != operator_token_account:
        mock_rpc.register_account(
            creator_refund_token_account,
            encode_token_account(mint=token_mint, owner=creator, amount=0),
            owner=DEFAULT_TOKEN_PROGRAM,
        )


def make_settlement_tx(
    *,
    tx_signature: str,
    slot: int = 105432,
    program_id: str = DEFAULT_PROGRAM_ID,
    work_order: str = WORK_ORDER_TARGET,
    protocol_config: str = DEFAULT_PROTOCOL_CONFIG,
    mint: str = MINT_TARGET,
    escrow_vault: str = VAULT_TARGET,
    operator_account: str = PAYOUT_ACCOUNT_TARGET,
    creator_refund_account: str = REFUND_ACCOUNT_TARGET,
    beneficiary_owner: str = BENEFICIARY_TARGET,
    creator_owner: str = CREATOR_TARGET,
    total_escrow: int = 10_000_000,
    operator_payout: int = 10_000_000,
    creator_refund: int = 0,
    err: Optional[Any] = None,
    discriminator: bytes = SETTLE_WORK_ORDER_DISCRIMINATOR,
    include_instruction: bool = True,
    token_program: str = DEFAULT_TOKEN_PROGRAM,
    multi_instruction: bool = False,
    corrupt_inner_amount: Optional[int] = None,
    unauthorized_inner_dest: Optional[str] = None,
    missing_inner_instructions: bool = False,
) -> dict[str, Any]:
    """Helper to synthesize authentic Solana getTransaction response objects."""
    account_keys = [
        FEE_PAYER,
        protocol_config,
        work_order,
        escrow_vault,
        mint,
        operator_account,
        creator_refund_account,
        token_program,
        program_id,
    ]

    settle_ix_index = 0
    instructions = []

    if multi_instruction:
        # Prepend a dummy compute budget or transfer instruction
        dummy_prog = "ComputeBudget111111111111111111111111111111"
        account_keys.append(dummy_prog)
        instructions.append({
            "programIdIndex": len(account_keys) - 1,
            "accounts": [],
            "data": b58encode(b"\x00" * 8),
        })
        settle_ix_index = 1

    if include_instruction:
        instructions.append({
            "programIdIndex": 8,
            "accounts": [1, 2, 3, 4, 5, 6, 7],
            "data": b58encode(discriminator),
        })

    if multi_instruction:
        # Append another dummy instruction
        instructions.append({
            "programIdIndex": len(account_keys) - 1,
            "accounts": [],
            "data": b58encode(b"\x01" * 8),
        })

    pre_token_balances = [
        {
            "accountIndex": 3,
            "mint": mint,
            "owner": escrow_vault,
            "uiTokenAmount": {"amount": str(total_escrow), "decimals": 6},
        },
        {
            "accountIndex": 5,
            "mint": mint,
            "owner": beneficiary_owner,
            "uiTokenAmount": {"amount": "0", "decimals": 6},
        },
    ]
    if operator_account != creator_refund_account:
        pre_token_balances.append({
            "accountIndex": 6,
            "mint": mint,
            "owner": creator_owner,
            "uiTokenAmount": {"amount": "0", "decimals": 6},
        })

    post_token_balances = [
        {
            "accountIndex": 3,
            "mint": mint,
            "owner": escrow_vault,
            "uiTokenAmount": {"amount": "0", "decimals": 6},
        },
    ]

    if operator_account == creator_refund_account:
        post_token_balances.append({
            "accountIndex": 5,
            "mint": mint,
            "owner": beneficiary_owner,
            "uiTokenAmount": {"amount": str(operator_payout + creator_refund), "decimals": 6},
        })
    else:
        post_token_balances.append({
            "accountIndex": 5,
            "mint": mint,
            "owner": beneficiary_owner,
            "uiTokenAmount": {"amount": str(operator_payout), "decimals": 6},
        })
        post_token_balances.append({
            "accountIndex": 6,
            "mint": mint,
            "owner": creator_owner,
            "uiTokenAmount": {"amount": str(creator_refund), "decimals": 6},
        })

    # Inner TransferChecked instructions
    inner_cpi_list = []
    if not missing_inner_instructions:
        if operator_payout > 0:
            cpi_dest_idx = 5
            if unauthorized_inner_dest:
                if unauthorized_inner_dest not in account_keys:
                    account_keys.append(unauthorized_inner_dest)
                cpi_dest_idx = account_keys.index(unauthorized_inner_dest)

            cpi_amt = corrupt_inner_amount if corrupt_inner_amount is not None else operator_payout
            inner_cpi_list.append({
                "programId": token_program,
                "accounts": [3, 4, cpi_dest_idx, 3],
                "data": b58encode(encode_spl_transfer_checked(cpi_amt, 6)),
            })

        if creator_refund > 0:
            dest_idx = 5 if operator_account == creator_refund_account else 6
            inner_cpi_list.append({
                "programId": token_program,
                "accounts": [3, 4, dest_idx, 3],
                "data": b58encode(encode_spl_transfer_checked(creator_refund, 6)),
            })

    inner_instructions = []
    if inner_cpi_list:
        inner_instructions.append({
            "index": settle_ix_index,
            "instructions": inner_cpi_list,
        })

    return {
        "slot": slot,
        "blockTime": 1791876630,
        "transaction": {
            "message": {
                "accountKeys": account_keys,
                "instructions": instructions,
            }
        },
        "meta": {
            "err": err,
            "preTokenBalances": pre_token_balances,
            "postTokenBalances": post_token_balances,
            "innerInstructions": inner_instructions,
        },
    }


class SplSettlementReconcilerTests(unittest.TestCase):
    """Test suite testing authentic SPL settlement reconciliation."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "test_ledger.db")
        self.mock_rpc = MockRpcClient(genesis_hash=DEFAULT_GENESIS_HASH, current_slot=200_000)
        setup_canonical_mock_accounts(self.mock_rpc)

        self.reconciler = SplSettlementReconciler(
            rpc_client=self.mock_rpc,
            min_commitment="finalized",
            authority=TRUSTED_AUTHORITY,
        )
        self.ledger = EconomicLedger(
            db_path=self.db_path,
            reconciliation_verifier=self.reconciler,
        )

    def tearDown(self) -> None:
        try:
            self.ledger.close()
        except Exception:
            pass
        self.temp_dir.cleanup()

    # ─────────────────────────────────────────────────────────────────────────
    # Condition 1: Valid Settlement Full Payout (10.0 USDC)
    # ─────────────────────────────────────────────────────────────────────────

    def test_condition_1_valid_full_payout(self) -> None:
        sig = "5FullPayoutSignature111111111111111111111111111111"
        tx = make_settlement_tx(
            tx_signature=sig,
            operator_payout=10_000_000,
            creator_refund=0,
            total_escrow=10_000_000,
        )
        self.mock_rpc.register_transaction(sig, tx, commitment="finalized")

        movement, receipt = self.reconciler.reconcile_settlement(
            self.ledger,
            tx_signature=sig,
        )

        self.assertEqual(movement.status, MovementStatus.RECONCILED)
        self.assertEqual(movement.nature, MovementNature.INCOME)
        self.assertEqual(movement.amount_base_units, 10_000_000)
        self.assertEqual(movement.agent_account, AGENT_TARGET)
        self.assertEqual(movement.owner_pubkey, BENEFICIARY_TARGET)
        self.assertEqual(receipt.operator_payout, 10_000_000)
        self.assertEqual(receipt.creator_refund, 0)
        self.assertEqual(receipt.total_escrow_settled, 10_000_000)

        # Check balance in ledger
        rec_bal, prov_bal = get_single_balance(self.ledger, AGENT_TARGET, MINT_TARGET)
        self.assertEqual(rec_bal, 10_000_000)
        self.assertEqual(prov_bal, 0)

    # ─────────────────────────────────────────────────────────────────────────
    # Condition 2: Proportional Settlement (Partial payout + refund)
    # ─────────────────────────────────────────────────────────────────────────

    def test_condition_2_proportional_settlement(self) -> None:
        sig = "5ProportionalPayoutSig222222222222222222222222222"
        # 60% completion: 6.0 USDC to operator, 4.0 USDC to creator
        tx = make_settlement_tx(
            tx_signature=sig,
            operator_payout=6_000_000,
            creator_refund=4_000_000,
            total_escrow=10_000_000,
        )
        self.mock_rpc.register_transaction(sig, tx, commitment="finalized")

        movement, receipt = self.reconciler.reconcile_settlement(
            self.ledger,
            tx_signature=sig,
        )

        self.assertEqual(movement.status, MovementStatus.RECONCILED)
        self.assertEqual(movement.nature, MovementNature.INCOME)
        self.assertEqual(movement.amount_base_units, 6_000_000)
        self.assertEqual(receipt.operator_payout, 6_000_000)
        self.assertEqual(receipt.creator_refund, 4_000_000)
        self.assertEqual(receipt.total_escrow_settled, 10_000_000)

        # Ledger must only credit operator payout, NOT the total escrow
        rec_bal, _ = get_single_balance(self.ledger, AGENT_TARGET, MINT_TARGET)
        self.assertEqual(rec_bal, 6_000_000)

    # ─────────────────────────────────────────────────────────────────────────
    # Condition 3: Creator Refund (0% operator payout -> 100% creator refund)
    # ─────────────────────────────────────────────────────────────────────────

    def test_condition_3_creator_refund_full(self) -> None:
        sig = "5CreatorRefundOnlySig3333333333333333333333333333"
        tx = make_settlement_tx(
            tx_signature=sig,
            operator_payout=0,
            creator_refund=10_000_000,
            total_escrow=10_000_000,
        )
        self.mock_rpc.register_transaction(sig, tx, commitment="finalized")

        movement, receipt = self.reconciler.reconcile_settlement(
            self.ledger,
            tx_signature=sig,
        )

        self.assertEqual(movement.status, MovementStatus.RECONCILED)
        self.assertEqual(movement.amount_base_units, 0)
        self.assertEqual(receipt.operator_payout, 0)
        self.assertEqual(receipt.creator_refund, 10_000_000)

        # Agent balance must be strictly 0
        rec_bal, _ = get_single_balance(self.ledger, AGENT_TARGET, MINT_TARGET)
        self.assertEqual(rec_bal, 0)

    # ─────────────────────────────────────────────────────────────────────────
    # Condition 4: Zero Payout Settlement (Audit movement)
    # ─────────────────────────────────────────────────────────────────────────

    def test_condition_4_zero_payout_creates_audit_movement(self) -> None:
        sig = "5ZeroPayoutSig44444444444444444444444444444444444"
        tx = make_settlement_tx(
            tx_signature=sig,
            operator_payout=0,
            creator_refund=10_000_000,
            total_escrow=10_000_000,
        )
        self.mock_rpc.register_transaction(sig, tx, commitment="finalized")

        movement, receipt = self.reconciler.reconcile_settlement(
            self.ledger,
            tx_signature=sig,
        )

        self.assertEqual(movement.nature, MovementNature.ADJUSTMENT)
        self.assertEqual(movement.amount_base_units, 0)
        self.assertIn("settlement_receipt", movement.metadata)

    # ─────────────────────────────────────────────────────────────────────────
    # Condition 5: Non-existent Signature Fails Closed
    # ─────────────────────────────────────────────────────────────────────────

    def test_condition_5_non_existent_signature(self) -> None:
        non_existent_sig = "5J3mNonExistentSignatureOnSolanaChain5555555555555"
        with self.assertRaises(TransactionNotFoundError):
            self.reconciler.verify_settlement_transaction(non_existent_sig)

    # ─────────────────────────────────────────────────────────────────────────
    # Condition 6: Wrong Program ID Fails Closed
    # ─────────────────────────────────────────────────────────────────────────

    def test_condition_6_wrong_program_id(self) -> None:
        sig = "5WrongProgramIdSig6666666666666666666666666666666"
        tx = make_settlement_tx(
            tx_signature=sig,
            program_id="11111111111111111111111111111111",
        )
        self.mock_rpc.register_transaction(sig, tx, commitment="finalized")

        with self.assertRaises(InstructionMismatchError):
            self.reconciler.verify_settlement_transaction(sig)

    # ─────────────────────────────────────────────────────────────────────────
    # Condition 7: Incorrect Token Mint Fails Closed
    # ─────────────────────────────────────────────────────────────────────────

    def test_condition_7_incorrect_token_mint(self) -> None:
        sig = "5WrongMintSig777777777777777777777777777777777777"
        tx = make_settlement_tx(
            tx_signature=sig,
            mint="So11111111111111111111111111111111111111112",
        )
        self.mock_rpc.register_transaction(sig, tx, commitment="finalized")

        with self.assertRaises(AccountMismatchError):
            self.reconciler.verify_settlement_transaction(sig, expected_mint=MINT_TARGET)

    # ─────────────────────────────────────────────────────────────────────────
    # Condition 8: Incorrect Beneficiary Fails Closed
    # ─────────────────────────────────────────────────────────────────────────

    def test_condition_8_incorrect_beneficiary(self) -> None:
        sig = "5WrongBeneficiarySig88888888888888888888888888888"
        tx = make_settlement_tx(
            tx_signature=sig,
            beneficiary_owner="99999999999999999999999999999999999999999999",
        )
        self.mock_rpc.register_transaction(sig, tx, commitment="finalized")

        with self.assertRaises(AccountMismatchError):
            self.reconciler.verify_settlement_transaction(
                sig,
                expected_beneficiary=BENEFICIARY_TARGET,
            )

    # ─────────────────────────────────────────────────────────────────────────
    # Condition 9: Mismatched Amount Fails Closed
    # ─────────────────────────────────────────────────────────────────────────

    def test_condition_9_mismatched_amount(self) -> None:
        sig = "5MismatchedAmountSig9999999999999999999999999999"
        # On-chain says 5.0 USDC, caller expected 10.0 USDC
        tx = make_settlement_tx(
            tx_signature=sig,
            operator_payout=5_000_000,
            creator_refund=5_000_000,
            total_escrow=10_000_000,
        )
        self.mock_rpc.register_transaction(sig, tx, commitment="finalized")

        with self.assertRaises(AmountMismatchError):
            self.reconciler.verify_settlement_transaction(
                sig,
                expected_operator_amount=10_000_000,
            )

    # ─────────────────────────────────────────────────────────────────────────
    # Condition 10: Failed On-Chain Transaction Fails Closed
    # ─────────────────────────────────────────────────────────────────────────

    def test_condition_10_failed_onchain_tx(self) -> None:
        sig = "5FailedOnChainTxSig00000000000000000000000000000"
        tx = make_settlement_tx(
            tx_signature=sig,
            err={"InstructionError": [0, {"Custom": 6001}]},
        )
        self.mock_rpc.register_transaction(sig, tx, commitment="finalized")

        with self.assertRaises(TransactionFailedError):
            self.reconciler.verify_settlement_transaction(sig)

    # ─────────────────────────────────────────────────────────────────────────
    # Condition 11: Idempotency & Repeat Submissions
    # ─────────────────────────────────────────────────────────────────────────

    def test_condition_11_idempotency_repeat_submissions(self) -> None:
        sig = "5IdempotencySignature1111111111111111111111111111"
        tx = make_settlement_tx(tx_signature=sig)
        self.mock_rpc.register_transaction(sig, tx, commitment="finalized")

        # First ingestion
        mov1, rec1 = self.reconciler.reconcile_settlement(self.ledger, tx_signature=sig)
        self.assertEqual(mov1.status, MovementStatus.RECONCILED)

        # Second ingestion of the same transaction
        mov2, rec2 = self.reconciler.reconcile_settlement(self.ledger, tx_signature=sig)
        self.assertEqual(mov1.movement_id, mov2.movement_id)
        self.assertEqual(rec1.effect_id, rec2.effect_id)

        # Balance must remain exactly 10.0 USDC, never duplicated to 20.0 USDC
        rec_bal, _ = get_single_balance(self.ledger, AGENT_TARGET, MINT_TARGET)
        self.assertEqual(rec_bal, 10_000_000)

    # ─────────────────────────────────────────────────────────────────────────
    # Condition 12: Process Restart & Disk Persistence
    # ─────────────────────────────────────────────────────────────────────────

    def test_condition_12_process_restart_persistence(self) -> None:
        sig = "5PersistenceSig1212121212121212121212121212121212"
        tx = make_settlement_tx(tx_signature=sig)
        self.mock_rpc.register_transaction(sig, tx, commitment="finalized")

        # Ingest into initial ledger instance
        mov1, _ = self.reconciler.reconcile_settlement(self.ledger, tx_signature=sig)

        # Simulate process termination and reload from SQLite file
        reloaded_ledger = EconomicLedger(
            db_path=self.db_path,
            reconciliation_verifier=self.reconciler,
        )

        loaded_mov = reloaded_ledger.get_movement(mov1.movement_id)
        self.assertIsNotNone(loaded_mov)
        self.assertEqual(loaded_mov.status, MovementStatus.RECONCILED)
        self.assertEqual(loaded_mov.amount_base_units, 10_000_000)

        rec_bal, _ = get_single_balance(reloaded_ledger, AGENT_TARGET, MINT_TARGET)
        self.assertEqual(rec_bal, 10_000_000)
        reloaded_ledger.close()

    # ─────────────────────────────────────────────────────────────────────────
    # Condition 13: RPC Failure & Timeout Handling
    # ─────────────────────────────────────────────────────────────────────────

    def test_condition_13_rpc_failure_handling(self) -> None:
        sig = "5RpcFailureSig131313131313131313131313131313131313"
        self.mock_rpc.set_error(RpcError("RPC timeout connecting to Solana node"))

        with self.assertRaises(RpcError):
            self.reconciler.verify_settlement_transaction(sig)

    # ─────────────────────────────────────────────────────────────────────────
    # Condition 14: Finality Gating (Confirmed vs Finalized)
    # ─────────────────────────────────────────────────────────────────────────

    def test_condition_14_finality_gating(self) -> None:
        sig = "5ConfirmedOnlySig14141414141414141414141414141414"
        tx = make_settlement_tx(tx_signature=sig)
        # Register ONLY as confirmed
        self.mock_rpc.register_transaction(sig, tx, commitment="confirmed")

        # Reconcile settlement when tx is confirmed only -> yields PROVISIONAL
        mov, receipt = self.reconciler.reconcile_settlement(self.ledger, tx_signature=sig)
        self.assertEqual(mov.status, MovementStatus.PROVISIONAL)
        self.assertEqual(receipt.commitment, "confirmed")

        # Ledger balances show provisional, NOT reconciled
        rec_bal, prov_bal = get_single_balance(self.ledger, AGENT_TARGET, MINT_TARGET)
        self.assertEqual(prov_bal, 10_000_000)
        self.assertEqual(rec_bal, 0)

        # Attempting verify_reconciliation for RECONCILED status fails closed
        verified = self.reconciler.verify_reconciliation(
            movement_id=mov.movement_id,
            evidence_hash=receipt.evidence_hash,
            authorized_by=TRUSTED_AUTHORITY,
            slot=receipt.slot,
            tx_signature=sig,
            movement=mov,
        )
        self.assertFalse(verified)

        # Now simulate cluster reaching finalized commitment
        self.mock_rpc.register_transaction(sig, tx, commitment="finalized")

        # Calling reconcile_settlement again promotes to RECONCILED
        mov_finalized, rec_finalized = self.reconciler.reconcile_settlement(
            self.ledger,
            tx_signature=sig,
        )
        self.assertEqual(mov_finalized.status, MovementStatus.RECONCILED)
        rec_bal_final, prov_bal_final = get_single_balance(self.ledger, AGENT_TARGET, MINT_TARGET)
        self.assertEqual(rec_bal_final, 10_000_000)
        self.assertEqual(prov_bal_final, 0)

    # ─────────────────────────────────────────────────────────────────────────
    # Condition 15: Historical Case Fixture & Offline Probe
    # ─────────────────────────────────────────────────────────────────────────

    def test_condition_15_historical_audit_offline_probe(self) -> None:
        # Probe offline validator
        res = audit_historical_localnet_settlement(rpc_url="http://127.0.0.1:8899")
        self.assertEqual(res["status"], "UNVERIFIABLE_ON_LIVE_RPC")
        self.assertFalse(res["live_verified"])

        # Deterministic fixture validation
        sig = "5HistoricalDeterministicFixtureSig151515151515"
        tx = make_settlement_tx(
            tx_signature=sig,
            work_order=WORK_ORDER_TARGET,
            mint=MINT_TARGET,
            beneficiary_owner=BENEFICIARY_TARGET,
            operator_payout=10_000_000,
        )
        self.mock_rpc.register_transaction(sig, tx, commitment="finalized")

        receipt = self.reconciler.verify_settlement_transaction(
            sig,
            source_kind=EvidenceSourceKind.HISTORICAL_FIXTURE,
        )
        self.assertEqual(receipt.evidence_source, EvidenceSourceKind.HISTORICAL_FIXTURE.value)
        self.assertEqual(receipt.operator_payout, 10_000_000)

    # ─────────────────────────────────────────────────────────────────────────
    # Negative Test 16: WorkOrder Account Not Found
    # ─────────────────────────────────────────────────────────────────────────

    def test_negative_16_work_order_not_found(self) -> None:
        sig = "5WoNotFoundSig16161616161616161616161616161616"
        tx = make_settlement_tx(tx_signature=sig)
        self.mock_rpc.register_transaction(sig, tx, commitment="finalized")
        # Remove WorkOrder from RPC accounts
        self.mock_rpc.accounts.pop(WORK_ORDER_TARGET, None)

        with self.assertRaises(AccountMismatchError) as ctx:
            self.reconciler.verify_settlement_transaction(sig)
        self.assertIn("does not exist on-chain", str(ctx.exception))

    # ─────────────────────────────────────────────────────────────────────────
    # Negative Test 17: WorkOrder Wrong Owner Program
    # ─────────────────────────────────────────────────────────────────────────

    def test_negative_17_work_order_wrong_owner(self) -> None:
        sig = "5WoWrongOwnerSig171717171717171717171717171717"
        tx = make_settlement_tx(tx_signature=sig)
        self.mock_rpc.register_transaction(sig, tx, commitment="finalized")
        # Change owner to malicious program
        setup_canonical_mock_accounts(
            self.mock_rpc,
            work_order_owner="11111111111111111111111111111111",
        )

        with self.assertRaises(AccountMismatchError) as ctx:
            self.reconciler.verify_settlement_transaction(sig)
        self.assertIn("owner mismatch", str(ctx.exception))

    # ─────────────────────────────────────────────────────────────────────────
    # Negative Test 18: WorkOrder Corrupted Discriminator
    # ─────────────────────────────────────────────────────────────────────────

    def test_negative_18_work_order_wrong_discriminator(self) -> None:
        sig = "5WoWrongDiscSig18181818181818181818181818181818"
        tx = make_settlement_tx(tx_signature=sig)
        self.mock_rpc.register_transaction(sig, tx, commitment="finalized")
        # Set bad discriminator
        bad_wo = bytearray(encode_work_order_account(
            protocol_config=DEFAULT_PROTOCOL_CONFIG,
            work_order_id=WO_ID_TARGET,
            creator=CREATOR_TARGET,
            token_mint=MINT_TARGET,
            total_amount=10_000_000,
            verifier="DmWQhuVujHrJb4jFzo62UnCT3mwnx9GFtVdo8VUu82Wu",
            escrow_vault=VAULT_TARGET,
            claimed_agent=AGENT_TARGET,
            settlement_beneficiary=BENEFICIARY_TARGET,
        ))
        bad_wo[:8] = b"\x00" * 8
        setup_canonical_mock_accounts(self.mock_rpc, custom_wo_raw=bytes(bad_wo))

        with self.assertRaises(AccountMismatchError) as ctx:
            self.reconciler.verify_settlement_transaction(sig)
        self.assertIn("Failed to decode WorkOrderAccount", str(ctx.exception))

    # ─────────────────────────────────────────────────────────────────────────
    # Negative Test 19: WorkOrder Wrong PDA Derivation
    # ─────────────────────────────────────────────────────────────────────────

    def test_negative_19_work_order_wrong_pda(self) -> None:
        sig = "5WoWrongPdaSig19191919191919191919191919191919"
        tx = make_settlement_tx(tx_signature=sig)
        self.mock_rpc.register_transaction(sig, tx, commitment="finalized")
        # Tamper with work_order_id so derivation fails to match WORK_ORDER_TARGET
        tampered_wo_id = b"\xff" * 32
        setup_canonical_mock_accounts(self.mock_rpc, work_order_id=tampered_wo_id)

        with self.assertRaises(AccountMismatchError) as ctx:
            self.reconciler.verify_settlement_transaction(sig)
        self.assertIn("does not match canonical PDA", str(ctx.exception))

    # ─────────────────────────────────────────────────────────────────────────
    # Negative Test 20: WorkOrder Not Settled (e.g. Verified or Open)
    # ─────────────────────────────────────────────────────────────────────────

    def test_negative_20_work_order_not_settled(self) -> None:
        sig = "5WoNotSettledSig202020202020202020202020202020"
        tx = make_settlement_tx(tx_signature=sig)
        self.mock_rpc.register_transaction(sig, tx, commitment="finalized")
        # Set status = Verified (4)
        setup_canonical_mock_accounts(
            self.mock_rpc,
            work_order_status=WorkOrderStatus.Verified.value,
        )

        with self.assertRaises(WorkOrderNotSettledError) as ctx:
            self.reconciler.verify_settlement_transaction(sig)
        self.assertIn("is not Settled", str(ctx.exception))

    # ─────────────────────────────────────────────────────────────────────────
    # Negative Test 21: Claimed AgentAccount Not Found
    # ─────────────────────────────────────────────────────────────────────────

    def test_negative_21_agent_not_found(self) -> None:
        sig = "5AgentNotFoundSig212121212121212121212121212121"
        tx = make_settlement_tx(tx_signature=sig)
        self.mock_rpc.register_transaction(sig, tx, commitment="finalized")
        # Remove Agent from RPC
        self.mock_rpc.accounts.pop(AGENT_TARGET, None)

        with self.assertRaises(AgentMismatchError) as ctx:
            self.reconciler.verify_settlement_transaction(sig)
        self.assertIn("does not exist on-chain", str(ctx.exception))

    # ─────────────────────────────────────────────────────────────────────────
    # Negative Test 22: Claimed Agent Wrong Owner Program
    # ─────────────────────────────────────────────────────────────────────────

    def test_negative_22_agent_wrong_owner_program(self) -> None:
        sig = "5AgentWrongOwnerProgramSig2222222222222222222222"
        tx = make_settlement_tx(tx_signature=sig)
        self.mock_rpc.register_transaction(sig, tx, commitment="finalized")
        setup_canonical_mock_accounts(
            self.mock_rpc,
            agent_owner_program="11111111111111111111111111111111",
        )

        with self.assertRaises(AgentMismatchError) as ctx:
            self.reconciler.verify_settlement_transaction(sig)
        self.assertIn("AgentAccount owner mismatch", str(ctx.exception))

    # ─────────────────────────────────────────────────────────────────────────
    # Negative Test 23: Claimed Agent Wrong Discriminator
    # ─────────────────────────────────────────────────────────────────────────

    def test_negative_23_agent_wrong_discriminator(self) -> None:
        sig = "5AgentWrongDiscSig232323232323232323232323232323"
        tx = make_settlement_tx(tx_signature=sig)
        self.mock_rpc.register_transaction(sig, tx, commitment="finalized")
        bad_ag = bytearray(encode_agent_account(
            protocol_config=DEFAULT_PROTOCOL_CONFIG,
            agent_id=AGENT_ID_TARGET,
            owner=BENEFICIARY_TARGET,
            signing_authority=BENEFICIARY_TARGET,
        ))
        bad_ag[:8] = b"\x00" * 8
        setup_canonical_mock_accounts(self.mock_rpc, custom_agent_raw=bytes(bad_ag))

        with self.assertRaises(AgentMismatchError) as ctx:
            self.reconciler.verify_settlement_transaction(sig)
        self.assertIn("Failed to decode AgentAccount", str(ctx.exception))

    # ─────────────────────────────────────────────────────────────────────────
    # Negative Test 24: Claimed Agent Wrong PDA Derivation
    # ─────────────────────────────────────────────────────────────────────────

    def test_negative_24_agent_wrong_pda(self) -> None:
        sig = "5AgentWrongPdaSig242424242424242424242424242424"
        tx = make_settlement_tx(tx_signature=sig)
        self.mock_rpc.register_transaction(sig, tx, commitment="finalized")
        # Tamper with agent_id
        setup_canonical_mock_accounts(self.mock_rpc, agent_id=b"\xff" * 32)

        with self.assertRaises(AgentMismatchError) as ctx:
            self.reconciler.verify_settlement_transaction(sig)
        self.assertIn("does not match canonical PDA", str(ctx.exception))

    # ─────────────────────────────────────────────────────────────────────────
    # Negative Test 25: Beneficiary Mismatch (Agent Owner != WorkOrder Beneficiary)
    # ─────────────────────────────────────────────────────────────────────────

    def test_negative_25_beneficiary_mismatch(self) -> None:
        sig = "5BeneficiaryMismatchSig252525252525252525252525"
        tx = make_settlement_tx(tx_signature=sig)
        self.mock_rpc.register_transaction(sig, tx, commitment="finalized")
        # Agent owner is malicious key != BENEFICIARY_TARGET
        setup_canonical_mock_accounts(
            self.mock_rpc,
            agent_owner="99999999999999999999999999999999999999999999",
        )

        with self.assertRaises(AgentMismatchError) as ctx:
            self.reconciler.verify_settlement_transaction(sig)
        self.assertIn("Settlement beneficiary mismatch", str(ctx.exception))

    # ─────────────────────────────────────────────────────────────────────────
    # Negative Test 26: Caller Identity Spoofing Fails Closed
    # ─────────────────────────────────────────────────────────────────────────

    def test_negative_26_caller_identity_spoofing(self) -> None:
        sig = "5CallerSpoofingSig262626262626262626262626262626"
        tx = make_settlement_tx(tx_signature=sig)
        self.mock_rpc.register_transaction(sig, tx, commitment="finalized")

        # Caller claims different agent_account
        with self.assertRaises(AgentMismatchError):
            self.reconciler.reconcile_settlement(
                self.ledger,
                tx_signature=sig,
                agent_account="FPbX4tQ2t9KSUDPix3NxBVEp2dD5LWoikhBVYYafU9H7",
            )

        # Caller claims different owner_pubkey
        with self.assertRaises(AgentMismatchError):
            self.reconciler.reconcile_settlement(
                self.ledger,
                tx_signature=sig,
                owner_pubkey="99999999999999999999999999999999999999999999",
            )

        # Caller claims different agent_id
        with self.assertRaises(AgentMismatchError):
            self.reconciler.reconcile_settlement(
                self.ledger,
                tx_signature=sig,
                agent_id="ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
            )

    # ─────────────────────────────────────────────────────────────────────────
    # Adversarial Test 27: Multi-Instruction Transaction
    # ─────────────────────────────────────────────────────────────────────────

    def test_adversarial_27_multi_instruction_transaction(self) -> None:
        sig = "5MultiIxSig27272727272727272727272727272727272727"
        tx = make_settlement_tx(
            tx_signature=sig,
            multi_instruction=True,
            operator_payout=10_000_000,
        )
        self.mock_rpc.register_transaction(sig, tx, commitment="finalized")

        receipt = self.reconciler.verify_settlement_transaction(sig)
        self.assertEqual(receipt.instruction_index, 1)
        self.assertEqual(receipt.operator_payout, 10_000_000)

    # ─────────────────────────────────────────────────────────────────────────
    # Adversarial Test 28: Inner TransferChecked Amount Mismatch
    # ─────────────────────────────────────────────────────────────────────────

    def test_adversarial_28_inner_transfer_amount_mismatch(self) -> None:
        sig = "5InnerAmountMismatchSig28282828282828282828282828"
        # Inner transfer says 9.0 USDC, but balance delta says 10.0 USDC
        tx = make_settlement_tx(
            tx_signature=sig,
            corrupt_inner_amount=9_000_000,
        )
        self.mock_rpc.register_transaction(sig, tx, commitment="finalized")

        with self.assertRaises(AmountMismatchError):
            self.reconciler.verify_settlement_transaction(sig)

    # ─────────────────────────────────────────────────────────────────────────
    # Adversarial Test 29: Inner TransferChecked Unauthorized Destination
    # ─────────────────────────────────────────────────────────────────────────

    def test_adversarial_29_inner_transfer_unauthorized_destination(self) -> None:
        sig = "5UnauthorizedDestSig2929292929292929292929292929"
        tx = make_settlement_tx(
            tx_signature=sig,
            unauthorized_inner_dest="11111111111111111111111111111111",
        )
        self.mock_rpc.register_transaction(sig, tx, commitment="finalized")

        with self.assertRaises(InstructionMismatchError):
            self.reconciler.verify_settlement_transaction(sig)

    # ─────────────────────────────────────────────────────────────────────────
    # Adversarial Test 30: Shared Destination No Overattribution
    # ─────────────────────────────────────────────────────────────────────────

    def test_adversarial_30_shared_destination_no_overattribution(self) -> None:
        sig = "5SharedDestSig303030303030303030303030303030303030"
        # Operator and creator share destination token account!
        # Operator payout = 6.0 USDC, Creator refund = 4.0 USDC. Total delta = 10.0 USDC.
        tx = make_settlement_tx(
            tx_signature=sig,
            operator_account=PAYOUT_ACCOUNT_TARGET,
            creator_refund_account=PAYOUT_ACCOUNT_TARGET,
            operator_payout=6_000_000,
            creator_refund=4_000_000,
            total_escrow=10_000_000,
        )
        self.mock_rpc.register_transaction(sig, tx, commitment="finalized")

        receipt = self.reconciler.verify_settlement_transaction(sig)

        # Crucial: operator must receive strictly 6.0 USDC, NOT the total 10.0 USDC
        self.assertEqual(receipt.operator_payout, 6_000_000)
        self.assertEqual(receipt.creator_refund, 4_000_000)
        self.assertEqual(receipt.total_escrow_settled, 10_000_000)

        # Ingest into ledger
        movement, _ = self.reconciler.reconcile_settlement(self.ledger, tx_signature=sig)
        self.assertEqual(movement.amount_base_units, 6_000_000)
        rec_bal, _ = get_single_balance(self.ledger, AGENT_TARGET, MINT_TARGET)
        self.assertEqual(rec_bal, 6_000_000)

    # ─────────────────────────────────────────────────────────────────────────
    # Adversarial Test 31: Donated Surplus in Escrow Refunded to Creator
    # ─────────────────────────────────────────────────────────────────────────

    def test_adversarial_31_escrow_surplus_refunded_to_creator(self) -> None:
        sig = "5SurplusRefundSig31313131313131313131313131313131"
        # Total escrow = 15.0 USDC (surplus of 5.0 USDC beyond contracted 10.0 USDC)
        # Operator gets max contracted 10.0 USDC.
        # Creator gets 5.0 USDC surplus refund.
        tx = make_settlement_tx(
            tx_signature=sig,
            operator_payout=10_000_000,
            creator_refund=5_000_000,
            total_escrow=15_000_000,
        )
        self.mock_rpc.register_transaction(sig, tx, commitment="finalized")

        receipt = self.reconciler.verify_settlement_transaction(sig)
        self.assertEqual(receipt.operator_payout, 10_000_000)
        self.assertEqual(receipt.creator_refund, 5_000_000)
        self.assertEqual(receipt.surplus, 5_000_000)
        self.assertEqual(receipt.total_escrow_settled, 15_000_000)

        # If an attacker attempts to claim operator payout = 15_000_000, it must fail closed
        sig_corrupt = "5SurplusCorruptSig3131313131313131313131313131"
        tx_corrupt = make_settlement_tx(
            tx_signature=sig_corrupt,
            operator_payout=15_000_000,
            creator_refund=0,
            total_escrow=15_000_000,
        )
        self.mock_rpc.register_transaction(sig_corrupt, tx_corrupt, commitment="finalized")

        with self.assertRaises(AmountMismatchError) as ctx:
            self.reconciler.verify_settlement_transaction(sig_corrupt)
        self.assertIn("exceeds WorkOrder contracted amount", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
