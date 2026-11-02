"""Read-only recovery of CON-36 finalized Devnet transactions and SQLite replay.

Usage: python3 -m tools.integration.devnet.verify_matrix LEDGER.sqlite RESULT.json
The SQLite database must be an ignored, isolated test file. No Devnet signing occurs.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

from tools.economic_ledger.ledger import EconomicLedger
from tools.economic_ledger.models import MovementStatus
from tools.economic_ledger.spl_reconciler import (
    EvidenceSourceKind, SolanaRpcClient, SplSettlementReconciler, b58decode,
)

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = ROOT / "evidence/con36"
RPC_URL = "https://api.devnet.solana.com"
GENESIS = "EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG"
PROGRAM = "CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy"
MINT = "HpfaV9oRuTN1b3ktDKvJoWqUWFZ1o9VFmhejxxqQ1vyh"


def load(path: Path) -> dict:
    return json.loads(path.read_text())


def report_rows() -> list[tuple[dict, dict]]:
    inventory = load(EVIDENCE / "scenario-plan.json")
    assert inventory["genesis_hash"] == GENESIS
    assert inventory["program_id"] == PROGRAM
    assert inventory["mint_pubkey"] == MINT
    rows = []
    for scenario in inventory["scenarios"]:
        report = load(EVIDENCE / "matrix" / f"{scenario['scenario']}.json")
        assert report["network"] == "solana:devnet"
        assert report["genesis_hash"] == GENESIS
        assert report["program_id"] == PROGRAM
        assert report["scenario"] == scenario["scenario"]
        assert report["work_order_pda"] == scenario["work_order_pda"]
        assert report["token_mint"] == MINT
        phases = [event["phase"] for event in report["events"]]
        assert len(phases) == len(set(phases))
        expected = [] if scenario["scenario"] == "E2E-01-full" else ["create"]
        if scenario["negative_attempt"] == "WrongMintOnFund":
            expected.append("wrong_mint")
        expected.append("fund")
        if scenario["donated_surplus_base_units"]:
            expected.append("donate")
        expected.extend(["register", "claim", "submit", "verify"])
        if scenario["negative_attempt"] == "SettlementInvalidCreatorRefund":
            expected.append("invalid_shared")
        if scenario["negative_attempt"] == "SettlementInvalidBeneficiary":
            expected.append("wrong_beneficiary")
        expected.append("settle")
        if scenario["scenario"] == "E2E-01-full":
            expected.append("duplicate")
        assert phases == expected
        assert all(event["state"] in ("FINALIZED", "FINALIZED_REJECTED")
                   for event in report["events"])
        settle = next(event for event in report["events"] if event["phase"] == "settle")
        assert settle["state"] == "FINALIZED"
        before, after = (settle[f"settlement_balances_{part}"]
                         for part in ("before", "after"))
        assert int(before["vault"]) == (scenario["escrow_funding_base_units"] +
                                        scenario["donated_surplus_base_units"])
        assert int(after["vault"]) == 0
        if scenario["same_operator_and_refund_destination"]:
            assert (int(after["operator"]) - int(before["operator"]) ==
                    int(before["vault"]))
            assert after["operator"] == after["refund"]
        else:
            assert (int(after["operator"]) - int(before["operator"]) ==
                    scenario["operator_payout_base_units"])
            assert (int(after["refund"]) - int(before["refund"]) ==
                    scenario["creator_refund_base_units"])
        rows.append((scenario, report))
    return rows


def verify_event(rpc: SolanaRpcClient, scenario: dict, event: dict) -> None:
    phase = event["phase"]
    manifest = load(EVIDENCE / event["manifest_file"].removeprefix("evidence/con36/"))
    body = {key: value for key, value in manifest.items() if key != "manifest_id"}
    expected_id = hashlib.sha256(json.dumps(body, separators=(",", ":"),
                                            ensure_ascii=False).encode()).hexdigest()
    assert manifest["manifest_id"] == event["manifest_id"] == expected_id
    assert manifest["genesis_hash"] == GENESIS
    assert manifest["program_id"] == PROGRAM
    assert manifest["test_mint"] == MINT
    assert manifest["work_order_pda"] == scenario["work_order_pda"]
    assert manifest["phase"] == phase
    assert manifest["max_fee_lamports"] <= 20_000
    assert (manifest["max_payer_debit_lamports"] ==
            manifest["max_fee_lamports"] + manifest["max_rent_lamports"])
    signature = event["signature"]
    status = rpc.get_signature_status(signature)
    assert status and status["confirmationStatus"] == "finalized"
    assert status["slot"] == event["slot"]
    transaction = rpc.get_transaction(signature)
    assert transaction and transaction["slot"] == event["slot"]
    assert transaction["transaction"]["signatures"][0] == signature
    meta = transaction["meta"]
    assert meta["fee"] == event["fee_lamports"] <= manifest["max_fee_lamports"]
    assert meta.get("preTokenBalances", []) == event["pre_token_balances"]
    assert meta.get("postTokenBalances", []) == event["post_token_balances"]
    assert meta["err"] == event["transaction_error"] == status["err"]
    failure = event["anchor_error_code"]
    assert bool(failure) == (event["state"] == "FINALIZED_REJECTED")
    if failure:
        assert failure in "\n".join(meta["logMessages"])
        if event["settlement_balances_before"]:
            assert (event["settlement_balances_before"] ==
                    event["settlement_balances_after"])
    else:
        assert meta["err"] is None
    message = transaction["transaction"]["message"]
    keys = message["accountKeys"]
    if isinstance(keys[0], dict):
        keys = [key["pubkey"] for key in keys]
    instructions = message["instructions"]
    assert len(instructions) == 1
    actual = instructions[0]
    assert keys[actual["programIdIndex"]] == manifest["instruction_program"]
    assert [keys[index] for index in actual["accounts"]] == [
        row["pubkey"] for row in manifest["instruction_accounts"]]
    assert b58decode(actual["data"]).hex() == manifest["instruction_data_hex"]
    assert keys[0] == manifest["payer"]


def check_block(rpc: SolanaRpcClient, event: dict) -> None:
    block = rpc._call("getBlock", [event["slot"], {
        "encoding": "json", "transactionDetails": "signatures", "rewards": False,
        "maxSupportedTransactionVersion": 0,
    }])
    assert block is not None and event["signature"] in block["signatures"]


def movement_count(db_path: Path) -> int:
    with sqlite3.connect(db_path) as db:
        return db.execute("SELECT COUNT(*) FROM economic_movements").fetchone()[0]


def verify_matrix(db_path: Path, output_path: Path) -> dict:
    assert db_path.resolve() != output_path.resolve()
    rows = report_rows()
    assert len(rows) == 7
    rpc = SolanaRpcClient(RPC_URL, timeout=20)
    assert rpc.get_genesis_hash() == GENESIS
    for scenario, report in rows:
        for event in report["events"]:
            verify_event(rpc, scenario, event)
        check_block(rpc, next(event for event in report["events"]
                              if event["phase"] == "settle"))
        print(f"Recovered finalized Devnet history: {scenario['scenario']}", flush=True)
    first_creation = load(EVIDENCE / "e2e-01-create-verified.json")
    assert first_creation["verification_status"] == "VERIFIED"
    first_status = rpc.get_signature_status(first_creation["signature"])
    assert first_status and first_status["confirmationStatus"] == "finalized"
    assert first_status["slot"] == first_creation["slot"]
    assert rpc.get_transaction(first_creation["signature"]) is not None

    reconciler = SplSettlementReconciler(
        rpc_client=rpc, expected_network="solana:devnet",
        expected_genesis_hash=GENESIS, expected_program_id=PROGRAM,
    )
    db_path.parent.mkdir(parents=True, exist_ok=True)
    ledger = EconomicLedger(db_path=db_path, reconciliation_verifier=reconciler)
    receipts = []
    try:
        for scenario, report in rows:
            event = next(event for event in report["events"]
                         if event["phase"] == "settle")
            signature = event["signature"]
            receipt = reconciler.verify_settlement_transaction(
                signature, expected_work_order=scenario["work_order_pda"],
                expected_mint=MINT,
                expected_beneficiary=scenario["agent_owner_pubkey"],
                expected_operator_amount=scenario["operator_payout_base_units"],
            )
            assert receipt.evidence_source == EvidenceSourceKind.LIVE_RPC.value
            assert receipt.commitment == "finalized"
            assert receipt.slot == event["slot"]
            assert receipt.creator_refund == scenario["creator_refund_base_units"]
            assert receipt.settlement_beneficiary == scenario["agent_owner_pubkey"]
            movement, checked = reconciler.reconcile_settlement(
                ledger, tx_signature=signature,
                work_order_account=scenario["work_order_pda"],
            )
            assert movement.status == MovementStatus.RECONCILED
            assert movement.evidence_hash == receipt.evidence_hash == checked.evidence_hash
            retry, _ = reconciler.reconcile_settlement(ledger, tx_signature=signature)
            assert retry.movement_id == movement.movement_id
            receipts.append({"scenario": scenario["scenario"],
                             "transaction_signature": signature,
                             "slot": receipt.slot, "effect_id": receipt.effect_id,
                             "evidence_hash": receipt.evidence_hash,
                             "movement_id": movement.movement_id,
                             "ledger_status": movement.status.value,
                             "provenance": receipt.evidence_source,
                             "operator_payout": receipt.operator_payout,
                             "creator_refund": receipt.creator_refund})
            print(f"Reconciled LIVE_RPC settlement: {scenario['scenario']}", flush=True)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(reconciler.reconcile_settlement, ledger,
                                   tx_signature=receipts[0]["transaction_signature"])
                       for _ in range(2)]
            assert all(future.result()[0].movement_id == receipts[0]["movement_id"]
                       for future in futures)
        assert movement_count(db_path) == 7
    finally:
        ledger.close()

    reopened = EconomicLedger(db_path=db_path, reconciliation_verifier=reconciler)
    try:
        for row in receipts:
            prior = reopened.get_by_idempotency_key(row["effect_id"])
            assert prior and prior.movement_id == row["movement_id"]
            assert prior.evidence_hash == row["evidence_hash"]
            retry, _ = reconciler.reconcile_settlement(
                reopened, tx_signature=row["transaction_signature"])
            assert retry.movement_id == row["movement_id"]
        assert movement_count(db_path) == 7
    finally:
        reopened.close()
    creator_ata = rows[0][0]["creator_source_and_refund_ata"]
    operator_ata = rows[0][0]["operator_payout_ata"]
    creator_final = rpc.get_token_account_balance(creator_ata)
    operator_final = rpc.get_token_account_balance(operator_ata)
    assert creator_final == 2_900_000
    assert operator_final == 4_200_000
    assert creator_final + operator_final == 7_100_000
    assert all(rpc.get_token_account_balance(scenario["escrow_vault"]) == 0
               for scenario, _ in rows)
    supply = rpc._call("getTokenSupply", [MINT, {"commitment": "finalized"}])
    assert supply["value"]["amount"] == "7100000"
    assert supply["value"]["decimals"] == 6
    result = {"network": "solana:devnet", "genesis_hash": GENESIS,
              "program_id": PROGRAM, "mint": MINT,
              "scenario_count": 8, "settlement_count": 7,
              "economic_movement_count": 7,
              "rejected_transaction_count": 4,
              "creator_final_base_units": creator_final,
              "operator_final_base_units": operator_final,
              "zero_escrow_vault_count": 7,
              "mint_supply_base_units": 7_100_000,
              "sqlite_restart_idempotent": True,
              "concurrent_retry_idempotent": True,
              "receipts": receipts}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("Usage: python3 -m tools.integration.devnet.verify_matrix LEDGER.sqlite RESULT.json")
    result = verify_matrix(Path(sys.argv[1]), Path(sys.argv[2]))
    print(json.dumps({"scenario_count": result["scenario_count"],
                      "settlement_count": result["settlement_count"],
                      "economic_movement_count": result["economic_movement_count"],
                      "rejected_transaction_count": result["rejected_transaction_count"],
                      "provenance": "LIVE_RPC", "sqlite_restart_idempotent": True,
                      "concurrent_retry_idempotent": True}))


if __name__ == "__main__":
    main()
