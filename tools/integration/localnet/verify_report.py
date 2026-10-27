"""Recover Localnet settlement receipts from actual JSON-RPC and test ledger replay.

Run with a report made by run_settlement.cjs and an isolated SQLite path.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys

from tools.economic_ledger.ledger import EconomicLedger
from tools.economic_ledger.models import MovementStatus
from tools.economic_ledger.spl_reconciler import (
    EvidenceSourceKind,
    SolanaRpcClient,
    SplSettlementReconciler,
)


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("Usage: python3 -m tools.integration.localnet.verify_report REPORT.json LEDGER.sqlite")
    report_path, db_path = map(Path, sys.argv[1:])
    if not report_path.is_file() or db_path.parent.resolve() != report_path.parent.resolve():
        raise SystemExit("Report and isolated SQLite path must share the same directory")
    report = json.loads(report_path.read_text())
    cases = [row for row in report["scenarios"] if row["result"] == "FINALIZED"]
    if not cases or not {row["scenario"] for row in cases}.issubset({
        "full", "zero", "proportional", "valid_shared"
    }):
        raise ValueError("Missing finalized Localnet scenario")
    if len(cases) == 4 and not any(
        row["scenario"] == "invalid_shared" and row["result"] == "ANCHOR_REJECTED" and
        row.get("anchor_error_code") == "SettlementInvalidCreatorRefund"
        for row in report["scenarios"]
    ):
        raise ValueError("Missing Anchor rejection scenario in full matrix")
    rpc_urls = {row["rpc_url"] for row in cases}
    if len(rpc_urls) != 1 or not next(iter(rpc_urls)).startswith("http://127.0.0.1:"):
        raise ValueError("Expected a single loopback Localnet RPC")
    rpc = SolanaRpcClient(next(iter(rpc_urls)))
    if rpc.get_genesis_hash() != report["genesis_hash"]:
        raise ValueError("Validator genesis changed")
    reconciler = SplSettlementReconciler(
        rpc_client=rpc, expected_genesis_hash=report["genesis_hash"],
    )
    ledger = EconomicLedger(db_path=db_path, reconciliation_verifier=reconciler)
    recorded = []
    try:
        for case in cases:
            receipt = reconciler.verify_settlement_transaction(
                case["transaction_signature"], expected_work_order=case["work_order_pda"],
            )
            if receipt.evidence_source != EvidenceSourceKind.LIVE_RPC.value or receipt.commitment != "finalized":
                raise ValueError("Non-finalized or synthetic receipt")
            if (receipt.operator_payout != int(case["expected_payout"]) or
                    receipt.creator_refund != int(case["creator_refund"]) or
                    receipt.token_mint != case["mint"] or
                    receipt.settlement_beneficiary != case["settlement_beneficiary"]):
                raise ValueError("Economic identity differs from finalized SPL execution")
            if (rpc.get_token_account_balance(case["escrow_vault"]) !=
                    int(case["final_balances"]["vault"]) or
                    rpc.get_token_account_balance(case["operator_token_account"]) !=
                    int(case["final_balances"]["operator"]) or
                    rpc.get_token_account_balance(case["creator_refund_token_account"]) !=
                    int(case["final_balances"]["refund"])):
                raise ValueError("Current SPL balances differ from captured final balances")
            movement, checked = reconciler.reconcile_settlement(
                ledger, tx_signature=receipt.tx_signature,
                work_order_account=receipt.work_order_account,
            )
            if movement.status != MovementStatus.RECONCILED or movement.evidence_hash != receipt.evidence_hash:
                raise ValueError("Movement did not reconcile to finalized evidence")
            again, _ = reconciler.reconcile_settlement(ledger, tx_signature=receipt.tx_signature)
            if again.movement_id != movement.movement_id:
                raise ValueError("Immediate retry duplicated movement")
            recorded.append({
                "scenario": case["scenario"], "transaction_signature": receipt.tx_signature,
                "slot": receipt.slot, "effect_id": receipt.effect_id,
                "evidence_hash": checked.evidence_hash, "movement_id": movement.movement_id,
                "ledger_status": movement.status.value, "provenance": receipt.evidence_source,
                "operator_payout": receipt.operator_payout, "creator_refund": receipt.creator_refund,
            })
        # Two genuine RPC reads race for one existing financial effect.
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(reconciler.reconcile_settlement, ledger,
                                   tx_signature=cases[0]["transaction_signature"]) for _ in range(2)]
            if any(f.result()[0].movement_id != recorded[0]["movement_id"] for f in futures):
                raise ValueError("Concurrent retry duplicated movement")
    finally:
        ledger.close()

    # A fresh EconomicLedger instance must preserve effect identity and balance.
    reopened = EconomicLedger(db_path=db_path, reconciliation_verifier=reconciler)
    try:
        for row in recorded:
            prior = reopened.get_by_idempotency_key(row["effect_id"])
            if prior is None or prior.movement_id != row["movement_id"] or prior.evidence_hash != row["evidence_hash"]:
                raise ValueError("SQLite restart changed movement identity or evidence")
            again, _ = reconciler.reconcile_settlement(reopened,
                                                        tx_signature=row["transaction_signature"])
            if again.movement_id != row["movement_id"]:
                raise ValueError("SQLite restart duplicated movement")
    finally:
        reopened.close()
    verified_path = report_path.with_name("verified.json")
    verified_path.write_text(json.dumps({"genesis_hash": report["genesis_hash"],
                                         "program_id": report["program_id"],
                                         "receipts": recorded}, indent=2) + "\n")
    print(f"Verified {len(recorded)} finalized LIVE_RPC receipts; SQLite and concurrent retries preserved effect IDs")


if __name__ == "__main__":
    main()
