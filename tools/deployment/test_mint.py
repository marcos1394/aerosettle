"""Independent, approval-gated Devnet test mint preparation and RPC verification."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.deployment import devnet


MINT_SIZE = 82
MIN_FEE_RESERVE = 50_000
LABEL = "DEVNET_TEST_TOKEN"


def mint_id(plan: dict) -> str:
    return hashlib.sha256(devnet.canonical({
        key: plan[key] for key in (
            "genesis_hash", "token_program", "mint_pubkey", "mint_authority_pubkey",
            "fee_payer_pubkey", "decimals", "asset_label"
        )
    })).hexdigest()


def check_plan(plan: dict) -> None:
    devnet.require(plan.get("schema_version") == 1, "Unsupported test mint manifest")
    devnet.require(plan.get("environment") == "devnet" and plan.get("network") == "solana:devnet", "Test mint must target Devnet")
    devnet.require(plan.get("rpc_url") == devnet.OFFICIAL_RPC and plan.get("genesis_hash") == devnet.DEVNET_GENESIS, "Test mint network mismatch")
    devnet.require(plan.get("token_program") == devnet.TOKEN_PROGRAM and plan.get("asset_label") == LABEL, "Test mint must use legacy SPL Token Program")
    for field in ("mint_pubkey", "mint_authority_pubkey", "fee_payer_pubkey"):
        devnet.b58decode(plan[field], 32)
    devnet.require(len({plan["mint_pubkey"], plan["mint_authority_pubkey"], plan["fee_payer_pubkey"]}) == 3, "Test mint roles must be distinct")
    devnet.require(type(plan.get("decimals")) is int and 0 <= plan["decimals"] <= 9, "Invalid test mint decimals")
    devnet.require(plan.get("creation_id") == mint_id(plan), "Test mint creation ID mismatch")
    devnet.require(plan.get("verification_status") in {"PREPARED", "VERIFIED"}, "Invalid test mint status")
    if plan["verification_status"] == "PREPARED":
        devnet.require(plan.get("creation_signature") is None and plan.get("creation_slot") is None, "Prepared mint cannot claim a transaction")
    else:
        devnet.require(isinstance(plan.get("creation_signature"), str) and
                       re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{80,90}", plan["creation_signature"]) and
                       type(plan.get("creation_slot")) is int and plan["creation_slot"] > 0, "Verified mint needs real signature and slot")
    devnet.require(plan.get("manifest_integrity_sha256") == devnet.seal(plan)["manifest_integrity_sha256"], "Test mint manifest integrity mismatch")


def make_plan(mint: str, authority: str, payer: str, decimals: int = 6) -> dict:
    plan = {
        "schema_version": 1, "environment": "devnet", "network": "solana:devnet",
        "rpc_url": devnet.OFFICIAL_RPC, "genesis_hash": devnet.DEVNET_GENESIS,
        "asset_label": LABEL, "token_program": devnet.TOKEN_PROGRAM,
        "mint_pubkey": mint, "mint_authority_pubkey": authority,
        "fee_payer_pubkey": payer, "decimals": decimals,
        "creation_signature": None, "creation_slot": None, "verification_status": "PREPARED",
    }
    result = devnet.seal({**plan, "creation_id": mint_id(plan)})
    check_plan(result)
    return result


def check_wallets(plan: dict, mint_keypair: Path, authority_keypair: Path, payer_keypair: Path) -> None:
    for path, expected in (
        (mint_keypair, plan["mint_pubkey"]),
        (authority_keypair, plan["mint_authority_pubkey"]),
        (payer_keypair, plan["fee_payer_pubkey"]),
    ):
        devnet.require(devnet.keypair_pubkey(path) == expected, "Test mint wallet does not match approved identity")


def preflight(plan: dict, rpc: devnet.Rpc) -> dict:
    check_plan(plan)
    devnet.require(plan["verification_status"] == "PREPARED", "Mint is already verified")
    devnet.require(rpc.call("getGenesisHash") == devnet.DEVNET_GENESIS, "Test mint RPC genesis mismatch")
    devnet.require(devnet.account(rpc, plan["mint_pubkey"]) is None, "Test mint already exists; use verify")
    rent = rpc.call("getMinimumBalanceForRentExemption", [MINT_SIZE, {"commitment": "finalized"}])
    devnet.require(type(rent) is int and rent > 0, "Invalid test mint rent quote")
    available = devnet.balance(rpc, plan["fee_payer_pubkey"])
    devnet.require(available >= rent + MIN_FEE_RESERVE, "Test mint payer lacks Devnet test SOL")
    return {"creation_id": plan["creation_id"], "mint_pubkey": plan["mint_pubkey"],
            "rent_lamports": rent, "fee_reserve_lamports": MIN_FEE_RESERVE,
            "payer_balance_lamports": available, "transaction_submitted": False}


def _parsed_instructions(transaction: dict) -> list[dict]:
    message = transaction.get("transaction", {}).get("message", {})
    instructions = message.get("instructions")
    devnet.require(isinstance(instructions, list), "Mint creation instructions unavailable")
    return instructions


def verify(plan: dict, rpc: devnet.Rpc, signature: str) -> dict:
    check_plan(plan)
    if plan["verification_status"] == "VERIFIED":
        devnet.require(plan["creation_signature"] == signature, "Mint creation signature changed")
    devnet.require(rpc.call("getGenesisHash") == devnet.DEVNET_GENESIS, "Test mint RPC genesis mismatch")
    devnet.require(bool(re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{80,90}", signature)), "Invalid mint signature")
    statuses = rpc.call("getSignatureStatuses", [[signature], {"searchTransactionHistory": True}])
    status = (statuses or {}).get("value", [None])[0]
    devnet.require(isinstance(status, dict) and status.get("confirmationStatus") == "finalized" and
                   status.get("err") is None and type(status.get("slot")) is int and status["slot"] > 0, "Test mint transaction not finalized")
    if plan["verification_status"] == "VERIFIED":
        devnet.require(plan["creation_slot"] == status["slot"], "Mint creation slot changed")
    transaction = rpc.call("getTransaction", [signature, {"encoding": "jsonParsed", "commitment": "finalized", "maxSupportedTransactionVersion": 0}])
    devnet.require(isinstance(transaction, dict) and transaction.get("slot") == status["slot"] and
                   isinstance(transaction.get("meta"), dict) and transaction["meta"].get("err", "missing") is None and
                   signature in transaction.get("transaction", {}).get("signatures", []), "Test mint transaction evidence mismatch")
    instructions = _parsed_instructions(transaction)
    created = any(i.get("program") == "system" and i.get("parsed", {}).get("type") == "createAccount" and
                  i["parsed"].get("info", {}).get("newAccount") == plan["mint_pubkey"] and
                  i["parsed"]["info"].get("source") == plan["fee_payer_pubkey"] and
                  i["parsed"]["info"].get("owner") == devnet.TOKEN_PROGRAM and
                  i["parsed"]["info"].get("space") == MINT_SIZE for i in instructions)
    initialized = any(i.get("programId") == devnet.TOKEN_PROGRAM and
                      i.get("parsed", {}).get("type") in ("initializeMint", "initializeMint2") and
                      i["parsed"].get("info", {}).get("mint") == plan["mint_pubkey"] and
                      i["parsed"]["info"].get("mintAuthority") == plan["mint_authority_pubkey"] and
                      i["parsed"]["info"].get("decimals") == plan["decimals"] and
                      i["parsed"]["info"].get("freezeAuthority") is None for i in instructions)
    devnet.require(created and initialized, "Transaction did not create and initialize the approved test mint")
    value = devnet.account(rpc, plan["mint_pubkey"])
    devnet.require(isinstance(value, dict) and value.get("owner") == devnet.TOKEN_PROGRAM and
                   value.get("executable") is False, "Test mint absent or wrong owner")
    raw = devnet._data(value)
    devnet.require(len(raw) == MINT_SIZE and raw[45] == 1 and
                   int.from_bytes(raw[:4], "little") == 1 and
                   devnet.b58encode(raw[4:36]) == plan["mint_authority_pubkey"] and
                   raw[44] == plan["decimals"] and
                   int.from_bytes(raw[36:44], "little") == 0 and
                   int.from_bytes(raw[46:50], "little") == 0, "Test mint account configuration mismatch")
    result = devnet.seal({**plan, "creation_signature": signature, "creation_slot": status["slot"],
                          "verification_status": "VERIFIED"})
    check_plan(result)
    return result


def submit(plan: dict, rpc: devnet.Rpc, mint_keypair: Path, authority_keypair: Path,
           payer_keypair: Path, approval: str | None, enabled: bool) -> dict:
    devnet.require(enabled and approval == plan["creation_id"] and
                   os.environ.get("CON35_APPROVED_TEST_MINT_ID") == plan["creation_id"],
                   "Exact test mint creation approval required")
    check_wallets(plan, mint_keypair, authority_keypair, payer_keypair)
    preflight(plan, rpc)
    command = ["spl-token", "create-token", str(mint_keypair), "--url", devnet.OFFICIAL_RPC,
               "--fee-payer", str(payer_keypair), "--mint-authority", plan["mint_authority_pubkey"],
               "--decimals", str(plan["decimals"]), "--program-id", devnet.TOKEN_PROGRAM,
               "--output", "json"]
    run = subprocess.run(command, capture_output=True, text=True, check=False)
    devnet.require(run.returncode == 0, "Test mint submission failed; inspect RPC before retrying")
    try:
        output = json.loads(run.stdout)
        signature = output.get("signature") or output.get("commandOutput", {}).get("signature")
    except (ValueError, TypeError, AttributeError):
        match = re.search(r"(?m)^Signature:\s*([1-9A-HJ-NP-Za-km-z]{80,90})\s*$", run.stdout)
        signature = match.group(1) if match else None
    if not isinstance(signature, str) or not re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{80,90}", signature):
        raise devnet.DeploymentError("Test mint submitted but signature unavailable; recover by RPC")
    print(json.dumps({"submitted_test_mint_signature": signature}), flush=True)
    for attempt in range(30):
        try:
            return verify(plan, rpc, signature)
        except devnet.DeploymentError as exc:
            if "not finalized" not in str(exc) and "transaction evidence mismatch" not in str(exc):
                raise
            if attempt == 29:
                raise
            time.sleep(3)
    raise AssertionError("unreachable")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "preflight", "verify", "create"))
    parser.add_argument("--manifest", type=Path, default=devnet.ROOT / "evidence/con35/test-mint.json")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--mint-keypair", type=Path)
    parser.add_argument("--authority-keypair", type=Path)
    parser.add_argument("--payer-keypair", type=Path)
    parser.add_argument("--decimals", type=int, default=6)
    parser.add_argument("--signature")
    parser.add_argument("--submit", action="store_true")
    parser.add_argument("--approval")
    args = parser.parse_args()
    rpc = devnet.Rpc(devnet.OFFICIAL_RPC)
    if args.command == "prepare":
        devnet.require(all((args.mint_keypair, args.authority_keypair, args.payer_keypair)), "Three keypair paths required")
        plan = make_plan(devnet.keypair_pubkey(args.mint_keypair),
                         devnet.keypair_pubkey(args.authority_keypair),
                         devnet.keypair_pubkey(args.payer_keypair), args.decimals)
        preflight(plan, rpc)
        devnet.write_immutable(args.manifest, plan)
        print(json.dumps({"creation_id": plan["creation_id"], "mint_pubkey": plan["mint_pubkey"], "verification_status": "PREPARED"}))
        return
    plan = devnet.load_json(args.manifest)
    if args.command == "preflight":
        print(json.dumps(preflight(plan, rpc), sort_keys=True))
    elif args.command == "verify":
        devnet.require(args.signature and args.output, "Signature and independent output path required")
        result = verify(plan, rpc, args.signature)
        devnet.write_immutable(args.output, result)
        print(json.dumps({"creation_id": result["creation_id"], "verification_status": "VERIFIED", "creation_slot": result["creation_slot"]}))
    else:
        devnet.require(all((args.mint_keypair, args.authority_keypair, args.payer_keypair, args.output)), "Wallets and independent output path required")
        result = submit(plan, rpc, args.mint_keypair, args.authority_keypair,
                        args.payer_keypair, args.approval, args.submit)
        devnet.write_immutable(args.output, result)
        print(json.dumps({"creation_id": result["creation_id"], "verification_status": "VERIFIED", "creation_slot": result["creation_slot"]}))


if __name__ == "__main__":
    try:
        main()
    except devnet.DeploymentError as exc:
        print(f"Test mint error: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
