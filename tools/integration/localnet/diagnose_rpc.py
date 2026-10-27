"""Record and assert independent JSON-RPC recovery evidence for CON-34."""

import base64
import hashlib
import json
import os
import shutil
import sys
import urllib.request
from pathlib import Path


def rpc(method, params=None):
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params or []}).encode()
    request = urllib.request.Request(
        os.environ.get("CON34_RPC_URL", "http://127.0.0.1:18899"),
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        result = json.load(response)
    if "error" in result:
        raise RuntimeError(f"{method}: {result['error']}")
    return result["result"]


def main():
    report_path, output_path, ledger_path = map(Path, sys.argv[1:4])
    before_path = Path(sys.argv[4]) if len(sys.argv) > 4 else None
    report = json.loads(report_path.read_text())
    genesis = rpc("getGenesisHash")
    slot = rpc("getSlot", [{"commitment": "finalized"}])
    evidence = {
        "genesis_hash": genesis,
        "finalized_slot_at_probe": slot,
        "first_available_block": rpc("getFirstAvailableBlock"),
        "minimum_ledger_slot": rpc("minimumLedgerSlot"),
        "agave_version": rpc("getVersion"),
        "ledger_bytes": sum(p.stat().st_size for p in ledger_path.rglob("*") if p.is_file()),
        "disk_free_bytes": shutil.disk_usage(ledger_path).free,
        "transactions": [],
    }
    errors = []
    if genesis != report["genesis_hash"]:
        errors.append("genesis hash changed")
    for item in report["scenarios"]:
        if item["result"] != "FINALIZED":
            continue
        signature = item["transaction_signature"]
        status = rpc("getSignatureStatuses", [[signature], {"searchTransactionHistory": True}])["value"][0]
        transaction = rpc("getTransaction", [signature, {"commitment": "finalized", "maxSupportedTransactionVersion": 0}])
        block = rpc("getBlock", [item["slot"], {"commitment": "finalized", "transactionDetails": "signatures", "rewards": False, "maxSupportedTransactionVersion": 0}])
        account = rpc("getAccountInfo", [item["work_order_pda"], {"commitment": "finalized", "encoding": "base64"}])["value"]
        balances = {
            name: rpc("getTokenAccountBalance", [item[key], {"commitment": "finalized"}])["value"]["amount"]
            for name, key in (
                ("vault", "escrow_vault"),
                ("operator", "operator_token_account"),
                ("refund", "creator_refund_token_account"),
            )
        }
        tx_evidence = {
            "scenario": item["scenario"],
            "transaction_signature": signature,
            "expected_slot": item["slot"],
            "status_slot": status["slot"] if status else None,
            "status_confirmation": status["confirmationStatus"] if status else None,
            "status_error": status["err"] if status else None,
            "transaction_slot": transaction["slot"] if transaction else None,
            "transaction_error": transaction["meta"]["err"] if transaction else None,
            "block_hash": block["blockhash"] if block else None,
            "block_contains_signature": signature in block.get("signatures", []) if block else False,
            "account_owner": account["owner"] if account else None,
            "account_data_sha256": hashlib.sha256(base64.b64decode(account["data"][0])).hexdigest() if account else None,
            "token_balances": balances,
        }
        evidence["transactions"].append(tx_evidence)
        if not status or status["confirmationStatus"] != "finalized" or status["err"] is not None or status["slot"] != item["slot"]:
            errors.append(f"{item['scenario']}: status missing or changed")
        if not transaction or transaction["slot"] != item["slot"] or transaction["meta"]["err"] is not None:
            errors.append(f"{item['scenario']}: getTransaction missing or changed")
        if not block or signature not in block.get("signatures", []):
            errors.append(f"{item['scenario']}: getBlock missing signature")
        if not account or account["owner"] != report["program_id"]:
            errors.append(f"{item['scenario']}: WorkOrder account missing")
        if balances != item["final_balances"]:
            errors.append(f"{item['scenario']}: SPL balances changed")
    if before_path:
        before = json.loads(before_path.read_text())
        if genesis != before["genesis_hash"]:
            errors.append("genesis hash changed after restart")
        if slot < before["finalized_slot_at_probe"]:
            errors.append("finalized slot regressed after restart")
        earlier = {tx["transaction_signature"]: tx for tx in before["transactions"]}
        for tx in evidence["transactions"]:
            old = earlier.get(tx["transaction_signature"])
            if old is None or any(tx[key] != old[key] for key in (
                "expected_slot", "status_slot", "transaction_slot", "block_hash",
                "account_owner", "account_data_sha256", "token_balances",
            )):
                errors.append(f"{tx['scenario']}: RPC evidence changed after restart")
    evidence["errors"] = errors
    output_path.write_text(json.dumps(evidence, indent=2) + "\n")
    if errors:
        raise RuntimeError("RPC recovery failed: " + "; ".join(errors))
    print(f"RPC evidence verified: {len(evidence['transactions'])} finalized transactions at {output_path}")


if __name__ == "__main__":
    main()
