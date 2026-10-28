"""Fail-closed, approval-gated deployment preparation and verification for Devnet."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import ssl
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import certifi


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.economic_ledger.spl_reconciler import b58decode, b58encode, derive_protocol_config_pda, find_program_address  # noqa: E402

LOADER = "BPFLoaderUpgradeab1e11111111111111111111111"
TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
OFFICIAL_RPC = "https://api.devnet.solana.com"
DEVNET_GENESIS = "EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG"
PROGRAM_ID = "CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy"
STATES = {"PREPARED", "SUBMITTED", "FINALIZED", "VERIFIED", "FAILED"}


class DeploymentError(RuntimeError):
    pass


def canonical(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def seal(value: dict) -> dict:
    result = {key: item for key, item in value.items() if key != "manifest_integrity_sha256"}
    return {**result, "manifest_integrity_sha256": hashlib.sha256(canonical(result)).hexdigest()}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def deployment_fingerprint(config: dict, source: str, binary_hash: str, idl_hash: str) -> str:
    return hashlib.sha256(canonical({
        "source_commit": source, "binary_sha256": binary_hash, "idl_sha256": idl_hash,
        "genesis_hash": config["genesis_hash"], "program_id": config["program_id"],
        "upgrade_authority_pubkey": config.get("upgrade_authority_pubkey"),
        "fee_payer_pubkey": config.get("fee_payer_pubkey"),
        "protocol_admin_pubkey": config.get("protocol_admin_pubkey"),
        "test_mint_pubkey": config.get("test_mint_pubkey"),
        "test_mint_authority_pubkey": config.get("test_mint_authority_pubkey"),
        "test_mint_decimals": config.get("test_mint_decimals"),
        "protocol_network_id_hex": config.get("protocol_network_id_hex"),
        "protocol_deployment_id_hex": config.get("protocol_deployment_id_hex"),
        "minimum_fee_payer_lamports": config["minimum_fee_payer_lamports"],
        "maximum_airdrop_lamports": config["maximum_airdrop_lamports"],
        "maximum_test_wallet_lamports": config["maximum_test_wallet_lamports"],
    })).hexdigest()


def artifact_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def require(condition: bool, message: str) -> None:
    if not condition:
        raise DeploymentError(message)


def load_json(path: Path) -> dict:
    value = json.loads(path.read_text())
    require(isinstance(value, dict), "Expected a JSON object")
    return value


def validate_config(config: dict) -> None:
    require(config.get("environment") == "devnet" and config.get("cluster") == "devnet", "Devnet environment required")
    require(config.get("network") == "solana:devnet", "Devnet network required")
    require(config.get("rpc_url") == OFFICIAL_RPC, "Unknown or non-Devnet RPC")
    require(config.get("reference_rpc_url") == OFFICIAL_RPC, "Unverified reference RPC")
    require(config.get("genesis_hash") == DEVNET_GENESIS, "Unverified Devnet genesis")
    require(config.get("program_id") == PROGRAM_ID, "Program ID mismatch")
    require(config.get("genesis_reference"), "Genesis reference missing")
    for key in ("minimum_fee_payer_lamports", "maximum_airdrop_lamports", "maximum_test_wallet_lamports"):
        require(type(config.get(key)) is int and config[key] > 0, f"Invalid {key}")
    require(config["maximum_airdrop_lamports"] <= 100_000_000, "Airdrop limit exceeds 0.1 SOL")
    require(config["maximum_test_wallet_lamports"] <= 2_000_000_000, "Wallet funding limit exceeds 2 SOL")
    if config.get("test_mint_pubkey"):
        require(config.get("test_mint_authority_pubkey") and type(config.get("test_mint_decimals")) is int and
                0 <= config["test_mint_decimals"] <= 9, "Test mint identity incomplete")
    for key in ("protocol_network_id_hex", "protocol_deployment_id_hex"):
        value = config.get(key)
        require(value is None or bool(re.fullmatch(r"[0-9a-f]{64}", value)), f"Invalid {key}")


class Rpc:
    def __init__(self, url: str):
        require(url == OFFICIAL_RPC, "Unknown RPC")
        self.url = url

    def call(self, method: str, params: list | None = None):
        payload = canonical({"jsonrpc": "2.0", "id": 1, "method": method, "params": params or []})
        request = urllib.request.Request(self.url, payload, {"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=20, context=ssl.create_default_context(cafile=certifi.where())) as response:
                result = json.load(response)
        except Exception as exc:
            raise DeploymentError(f"Devnet RPC unavailable: {type(exc).__name__}") from exc
        require("error" not in result and "result" in result, f"Devnet RPC rejected {method}")
        return result["result"]


def verify_cluster(config: dict, rpc: Rpc) -> dict:
    validate_config(config)
    genesis = rpc.call("getGenesisHash")
    require(genesis == config["genesis_hash"], "Genesis mismatch")
    return {"cluster": "devnet", "network": "solana:devnet", "genesis_hash": genesis, "rpc_url": OFFICIAL_RPC}


def account(rpc: Rpc, pubkey: str) -> dict | None:
    response = rpc.call("getAccountInfo", [pubkey, {"encoding": "base64", "commitment": "finalized"}])
    require(isinstance(response, dict) and "value" in response, "Malformed account response")
    return response["value"]


def _data(value: dict) -> bytes:
    encoded = value.get("data")
    require(isinstance(encoded, list) and len(encoded) == 2 and encoded[1] == "base64", "Expected base64 account data")
    return base64.b64decode(encoded[0], validate=True)


def inspect_program(config: dict, rpc: Rpc) -> dict:
    verify_cluster(config, rpc)
    program = account(rpc, config["program_id"])
    if program is None:
        return {"exists": False, "program_id": config["program_id"], "verification_status": "PREPARED"}
    require(program.get("owner") == LOADER and program.get("executable") is True, "Program account is not executable under upgradeable loader")
    raw = _data(program)
    require(len(raw) == 36 and int.from_bytes(raw[:4], "little") == 2, "Invalid Program account state")
    program_data_address = b58encode(raw[4:36])
    expected_program_data, _ = find_program_address([b58decode(config["program_id"], 32)], LOADER)
    require(program_data_address == expected_program_data, "ProgramData address is not canonical")
    program_data = account(rpc, program_data_address)
    require(program_data is not None and program_data.get("owner") == LOADER, "ProgramData missing or wrong owner")
    data = _data(program_data)
    require(len(data) >= 45 and int.from_bytes(data[:4], "little") == 3, "Invalid ProgramData state")
    slot = int.from_bytes(data[4:12], "little")
    authority_option = data[12]
    require(authority_option in (0, 1), "Invalid upgrade authority encoding")
    authority = b58encode(data[13:45]) if authority_option == 1 else None
    expected = config.get("upgrade_authority_pubkey")
    require(expected and authority == expected, "Unrecognized upgrade authority")
    return {
        "exists": True, "program_id": config["program_id"], "program_data_address": program_data_address,
        "upgrade_authority_pubkey": authority, "deployment_slot": slot,
        "binary_sha256": hashlib.sha256(data[45:]).hexdigest(), "executable": True,
    }


def binary_matches_deployed(rpc: Rpc, program_data_address: str, binary: bytes) -> bool:
    value = account(rpc, program_data_address)
    require(value is not None and value.get("owner") == LOADER, "ProgramData missing")
    data = _data(value)
    require(len(data) >= 45 and int.from_bytes(data[:4], "little") == 3, "Invalid ProgramData state")
    deployed = data[45:]
    return len(deployed) >= len(binary) and deployed[:len(binary)] == binary and not any(deployed[len(binary):])


def keypair_pubkey(path: Path) -> str:
    require(path.is_file(), "Required wallet file missing")
    result = subprocess.run(["solana-keygen", "pubkey", str(path)], capture_output=True, text=True, check=False)
    require(result.returncode == 0, "Wallet cannot be read")
    return result.stdout.strip()


def verify_wallet(path: Path, binding: Path, expected_pubkey: str, role: str, config: dict) -> str:
    require(expected_pubkey, f"{role} pubkey not configured")
    info = load_json(binding)
    require(info == {"environment": "devnet", "genesis_hash": config["genesis_hash"], "role": role, "pubkey": expected_pubkey}, f"{role} wallet binding mismatch")
    require(keypair_pubkey(path) == expected_pubkey, f"{role} wallet pubkey mismatch")
    return expected_pubkey


def balance(rpc: Rpc, pubkey: str) -> int:
    value = rpc.call("getBalance", [pubkey, {"commitment": "finalized"}])
    require(isinstance(value, dict) and type(value.get("value")) is int, "Invalid balance response")
    return value["value"]


def verify_test_mint(config: dict, rpc: Rpc) -> None:
    test_mint = config.get("test_mint_pubkey")
    if not test_mint:
        return
    mint = account(rpc, test_mint)
    require(mint is not None and mint.get("owner") == TOKEN_PROGRAM, "Test mint absent on Devnet or wrong owner")
    raw = _data(mint)
    require(len(raw) == 82 and raw[45] == 1, "Invalid SPL test mint")
    require(int.from_bytes(raw[:4], "little") == 1 and
            b58encode(raw[4:36]) == config.get("test_mint_authority_pubkey") and
            raw[44] == config.get("test_mint_decimals"), "Test mint authority or decimals mismatch")


def preflight(config: dict, rpc: Rpc, wallets: dict | None = None, require_wallets: bool = False) -> dict:
    identity = verify_cluster(config, rpc)
    verify_test_mint(config, rpc)
    if not require_wallets:
        return {**identity, "deployment_ready": False, "reason": "Authority wallets were not checked"}
    require(wallets is not None, "Wallet paths and bindings required")
    roles = {
        "fee_payer": config.get("fee_payer_pubkey"),
        "upgrade_authority": config.get("upgrade_authority_pubkey"),
        "protocol_admin": config.get("protocol_admin_pubkey"),
    }
    require(all(roles.values()) and len(set(roles.values())) == 3, "Separate authority pubkeys required")
    for role, pubkey in roles.items():
        entry = wallets.get(role)
        require(entry and entry.get("keypair") and entry.get("binding"), f"Missing {role} wallet")
        verify_wallet(Path(entry["keypair"]), Path(entry["binding"]), pubkey, role, config)
    require(balance(rpc, roles["fee_payer"]) >= config["minimum_fee_payer_lamports"], "Fee payer lacks test SOL")
    return {**identity, "fee_payer_pubkey": roles["fee_payer"], "upgrade_authority_pubkey": roles["upgrade_authority"]}


def artifact_manifest(config: dict, binary: Path, idl: Path) -> dict:
    validate_config(config)
    require(binary.is_file() and idl.is_file(), "Build artifacts missing")
    idl_data = load_json(idl)
    require(idl_data.get("address") == config["program_id"], "IDL program ID mismatch")
    require(idl_data.get("instructions") and idl_data.get("accounts"), "IDL incomplete")
    require(idl_data == load_json(ROOT / "tools/integration/localnet/aerosettle-idl.json"), "IDL incompatible with validated ABI")
    source = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    lock_hash = sha256(ROOT / "Cargo.lock")
    binary_hash, idl_hash = sha256(binary), sha256(idl)
    comparison = binary.parent / "reproducibility.json"
    if comparison.is_file():
        comparison_data = load_json(comparison)
        require(comparison_data == {"status": "PASS", "source_commit": source, "cargo_lock_hash": lock_hash,
                                    "binary_sha256": binary_hash, "idl_sha256": idl_hash}, "Reproducibility attestation mismatch")
        reproducibility_status = "PASS"
        reproducibility_hash = sha256(comparison)
    else:
        reproducibility_status = "NOT_COMPARED"
        reproducibility_hash = None
    deployment_id = deployment_fingerprint(config, source, binary_hash, idl_hash)
    try:
        binary_name = str(binary.resolve().relative_to(ROOT))
    except ValueError:
        binary_name = str(binary.resolve())
    try:
        idl_name = str(idl.resolve().relative_to(ROOT))
    except ValueError:
        idl_name = str(idl.resolve())
    return seal({
        "environment": "devnet", "cluster": "devnet", "network": "solana:devnet",
        "rpc_identity": OFFICIAL_RPC, "genesis_hash": config["genesis_hash"], "program_id": config["program_id"],
        "deployment_id": deployment_id, "source_commit": source, "cargo_lock_hash": lock_hash,
        "binary_sha256": binary_hash, "idl_sha256": idl_hash,
        "reproducibility_status": reproducibility_status, "reproducibility_attestation_sha256": reproducibility_hash,
        "upgrade_authority_pubkey": config.get("upgrade_authority_pubkey"),
        "fee_payer_pubkey": config.get("fee_payer_pubkey"), "protocol_admin_pubkey": config.get("protocol_admin_pubkey"),
        "test_mint_pubkey": config.get("test_mint_pubkey"),
        "test_mint_authority_pubkey": config.get("test_mint_authority_pubkey"),
        "test_mint_decimals": config.get("test_mint_decimals"),
        "protocol_network_id_hex": config.get("protocol_network_id_hex"),
        "protocol_deployment_id_hex": config.get("protocol_deployment_id_hex"),
        "minimum_fee_payer_lamports": config["minimum_fee_payer_lamports"],
        "maximum_airdrop_lamports": config["maximum_airdrop_lamports"],
        "maximum_test_wallet_lamports": config["maximum_test_wallet_lamports"],
        "program_data_address": None, "deployment_transaction": None, "deployment_slot": None,
        "verification_status": "PREPARED", "binary_path": binary_name, "idl_path": idl_name,
        "rust_version": version(["rustc", "--version"]), "solana_version": version(["solana", "--version"]),
        "anchor_version": "1.2.0 (Anchor.toml; IDL generated from compiled crate)",
        "build_timestamp": datetime.now(timezone.utc).isoformat(),
    })


def version(command: list[str]) -> str:
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    require(result.returncode == 0, f"Tool missing: {command[0]}")
    return result.stdout.strip()


def verify_artifacts(config: dict, manifest: dict) -> None:
    validate_config(config)
    require(manifest.get("manifest_integrity_sha256") == seal(manifest)["manifest_integrity_sha256"], "Manifest integrity mismatch")
    require(manifest.get("environment") == "devnet" and manifest.get("cluster") == "devnet" and manifest.get("network") == "solana:devnet", "Manifest cluster mismatch")
    require(manifest.get("genesis_hash") == config["genesis_hash"] and manifest.get("program_id") == config["program_id"], "Manifest identity mismatch")
    require(manifest.get("upgrade_authority_pubkey") == config.get("upgrade_authority_pubkey"), "Manifest authority mismatch")
    require(manifest.get("fee_payer_pubkey") == config.get("fee_payer_pubkey") and
            manifest.get("protocol_admin_pubkey") == config.get("protocol_admin_pubkey") and
            manifest.get("test_mint_pubkey") == config.get("test_mint_pubkey") and
            manifest.get("test_mint_authority_pubkey") == config.get("test_mint_authority_pubkey") and
            manifest.get("test_mint_decimals") == config.get("test_mint_decimals") and
            manifest.get("protocol_network_id_hex") == config.get("protocol_network_id_hex") and
            manifest.get("protocol_deployment_id_hex") == config.get("protocol_deployment_id_hex") and
            manifest.get("minimum_fee_payer_lamports") == config["minimum_fee_payer_lamports"] and
            manifest.get("maximum_airdrop_lamports") == config["maximum_airdrop_lamports"] and
            manifest.get("maximum_test_wallet_lamports") == config["maximum_test_wallet_lamports"], "Manifest authority or mint context mismatch")
    require(manifest.get("verification_status") in STATES, "Invalid manifest state")
    binary, idl = artifact_path(manifest.get("binary_path", "")), artifact_path(manifest.get("idl_path", ""))
    require(binary.is_file() and idl.is_file(), "Artifact unavailable")
    require(sha256(binary) == manifest.get("binary_sha256"), "Binary hash mismatch")
    require(sha256(idl) == manifest.get("idl_sha256"), "IDL hash mismatch")
    require(load_json(idl) == load_json(ROOT / "tools/integration/localnet/aerosettle-idl.json"), "IDL incompatible")
    reproducibility = manifest.get("reproducibility_status")
    require(reproducibility in ("PASS", "NOT_COMPARED"), "Invalid reproducibility status")
    if reproducibility == "PASS":
        comparison = binary.parent / "reproducibility.json"
        require(comparison.is_file() and sha256(comparison) == manifest.get("reproducibility_attestation_sha256"), "Reproducibility attestation missing or altered")
        require(load_json(comparison) == {"status": "PASS", "source_commit": manifest.get("source_commit"),
                                          "cargo_lock_hash": manifest.get("cargo_lock_hash"),
                                          "binary_sha256": manifest.get("binary_sha256"), "idl_sha256": manifest.get("idl_sha256")}, "Reproducibility attestation mismatch")
    else:
        require(manifest.get("reproducibility_attestation_sha256") is None, "Unverified reproducibility attestation")
    status = manifest["verification_status"]
    if status == "PREPARED":
        require(manifest.get("deployment_transaction") is None and manifest.get("deployment_slot") is None, "Prepared manifest contains deployment evidence")
    if status in ("FINALIZED", "VERIFIED"):
        require(manifest.get("deployment_transaction") and type(manifest.get("deployment_slot")) is int, "Finalized manifest lacks transaction evidence")
    if status == "VERIFIED":
        require(manifest.get("deployment_transaction") and type(manifest.get("deployment_slot")) is int and manifest.get("program_data_address"), "Verified manifest lacks deployment evidence")
    fingerprint = deployment_fingerprint(config, manifest.get("source_commit"), manifest["binary_sha256"], manifest["idl_sha256"])
    require(fingerprint == manifest.get("deployment_id"), "Manifest altered")


def verify_signature(rpc: Rpc, signature: str, expected_slot: int | None = None, expected_program_id: str | None = None) -> int:
    require(bool(re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{80,90}", signature or "")), "Invalid transaction signature")
    statuses = rpc.call("getSignatureStatuses", [[signature], {"searchTransactionHistory": True}])
    value = statuses.get("value", [None])[0]
    require(value is not None and value.get("confirmationStatus") == "finalized" and value.get("err") is None, "Deployment transaction not finalized")
    tx = rpc.call("getTransaction", [signature, {"encoding": "json", "commitment": "finalized", "maxSupportedTransactionVersion": 0}])
    require(tx is not None and tx.get("meta", {}).get("err") is None, "Deployment transaction missing or failed")
    slot = tx.get("slot")
    require(type(slot) is int and slot == value.get("slot"), "Deployment transaction slot mismatch")
    if expected_program_id:
        message = tx.get("transaction", {}).get("message", {})
        keys = message.get("accountKeys", [])
        keys = [key.get("pubkey") if isinstance(key, dict) else key for key in keys]
        expected_program_data, _ = find_program_address([b58decode(expected_program_id, 32)], LOADER)
        require(expected_program_id in keys and LOADER in keys and expected_program_data in keys,
                "Deployment transaction does not reference the expected program and loader")
        found_deploy_instruction = False
        for instruction in message.get("instructions", []):
            program_index = instruction.get("programIdIndex")
            account_indices = instruction.get("accounts", [])
            if type(program_index) is not int or program_index >= len(keys) or keys[program_index] != LOADER:
                continue
            if not isinstance(account_indices, list) or any(type(index) is not int or index >= len(keys) for index in account_indices):
                continue
            instruction_accounts = {keys[index] for index in account_indices}
            if expected_program_id not in instruction_accounts or expected_program_data not in instruction_accounts:
                continue
            instruction_data = b58decode(instruction.get("data", ""))
            if len(instruction_data) >= 4 and int.from_bytes(instruction_data[:4], "little") in (2, 3):
                found_deploy_instruction = True
                break
        require(found_deploy_instruction, "Transaction lacks a loader deploy or upgrade instruction")
    if expected_slot is not None:
        require(slot == expected_slot, "Deployment slot mismatch")
    return slot


def post_deploy(config: dict, rpc: Rpc, manifest: dict, signature: str) -> dict:
    verify_artifacts(config, manifest)
    require(manifest.get("reproducibility_status") == "PASS", "Uncompared build cannot become VERIFIED")
    require(manifest.get("deployment_transaction") in (None, signature), "Deployment signature differs from submitted manifest")
    verify_cluster(config, rpc)
    slot = verify_signature(rpc, signature, expected_slot=manifest.get("deployment_slot"), expected_program_id=config["program_id"])
    observed = inspect_program(config, rpc)
    require(observed.get("exists") and observed["deployment_slot"] == slot, "ProgramData slot does not match deployment transaction")
    require(binary_matches_deployed(rpc, observed["program_data_address"], artifact_path(manifest["binary_path"]).read_bytes()), "On-chain binary does not match approved artifact")
    pda, bump = derive_protocol_config_pda(config["program_id"])
    config_account = account(rpc, pda)
    if config_account is not None:
        require(config_account.get("owner") == config["program_id"], "ProtocolConfig PDA owner mismatch")
        raw = _data(config_account)
        discriminator = hashlib.sha256(b"account:ProtocolConfig").digest()[:8]
        require(len(raw) == 155 and raw[:8] == discriminator and raw[8] == 1, "ProtocolConfig layout or version mismatch")
        require(b58encode(raw[9:41]) == config.get("protocol_admin_pubkey"), "Protocol admin mismatch")
        require(config.get("protocol_network_id_hex") and raw[41:73].hex() == config["protocol_network_id_hex"], "Protocol network ID mismatch")
        require(b58encode(raw[73:105]) == config["program_id"], "Protocol program ID mismatch")
        require(config.get("protocol_deployment_id_hex") and raw[105:137].hex() == config["protocol_deployment_id_hex"], "Protocol deployment ID mismatch")
        require(raw[137] == bump, "ProtocolConfig bump mismatch")
    return seal({**manifest, "deployment_transaction": signature, "deployment_slot": slot,
            "program_data_address": observed["program_data_address"], "verification_status": "VERIFIED",
            "protocol_config_pda": pda, "protocol_config_status": "PRESENT" if config_account else "UNINITIALIZED"})


def write_immutable(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(value, sort_keys=True, indent=2) + "\n"
    try:
        with path.open("x") as stream:
            stream.write(data)
    except FileExistsError:
        require(path.read_text() == data, "Manifest already exists with different content")


def approval_valid(manifest: dict, submit: bool, approval: str | None, env_approval: str | None) -> bool:
    return bool(submit and approval and approval == manifest.get("deployment_id") == env_approval)


def prepare_rollback(config: dict, rpc: Rpc, manifest: dict) -> dict:
    verify_artifacts(config, manifest)
    require(manifest.get("verification_status") == "VERIFIED", "Only a verified historic artifact can be restored")
    verify_signature(rpc, manifest["deployment_transaction"], manifest["deployment_slot"], config["program_id"])
    observed = inspect_program(config, rpc)
    require(observed.get("exists"), "No live deployment to recover")
    return {"status": "PREPARED", "action": "NEW_AUTHORIZED_UPGRADE", "target_deployment_id": manifest["deployment_id"],
            "target_binary_sha256": manifest["binary_sha256"], "current_binary_sha256": observed["binary_sha256"],
            "genesis_hash": config["genesis_hash"], "upgrade_authority_pubkey": observed["upgrade_authority_pubkey"]}


def request_test_funds(config: dict, rpc: Rpc, pubkey: str, lamports: int) -> dict:
    require(pubkey and type(lamports) is int and 0 < lamports <= config["maximum_airdrop_lamports"], "Airdrop request exceeds configured limit")
    verify_cluster(config, rpc)
    require(balance(rpc, pubkey) + lamports <= config["maximum_test_wallet_lamports"], "Test wallet funding limit exceeded")
    signature = rpc.call("requestAirdrop", [pubkey, lamports, {"commitment": "finalized"}])
    verify_signature(rpc, signature)
    return {"environment": "devnet", "asset": "DEVNET_TEST_SOL", "airdrop_signature": signature, "lamports": lamports}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["preflight", "build", "prepare-artifacts", "verify-artifacts", "inspect", "deploy", "finalize", "post-deploy-verification", "prepare-rollback", "request-test-funds"])
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("devnet.json"))
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--binary", type=Path, default=ROOT / "target/deploy/aerosettle.so")
    parser.add_argument("--idl", type=Path, default=ROOT / "target/idl/aerosettle.json")
    parser.add_argument("--wallets", type=Path, help="Private, untracked role-to-keypair/binding map")
    parser.add_argument("--program-keypair", type=Path)
    parser.add_argument("--signature")
    parser.add_argument("--approval", help="Must equal deployment_id and match CON35_APPROVED_DEPLOYMENT_ID")
    parser.add_argument("--submit", action="store_true")
    parser.add_argument("--airdrop-pubkey")
    parser.add_argument("--airdrop-lamports", type=int)
    args = parser.parse_args()
    try:
        config = load_json(args.config)
        validate_config(config)
        rpc = Rpc(config["rpc_url"])
        manifest = load_json(args.manifest) if args.manifest else None
        if args.command == "preflight":
            result = preflight(config, rpc, load_json(args.wallets) if args.wallets else None, bool(args.wallets))
        elif args.command == "build":
            subprocess.run(["cargo", "build-sbf", "--manifest-path", str(ROOT / "programs/aerosettle/Cargo.toml")], cwd=ROOT, check=True)
            subprocess.run([sys.executable, str(Path(__file__).with_name("build_idl.py")), "--idl", str(args.idl), "--error-catalog", str(args.idl.with_name("aerosettle-error-catalog.json"))], cwd=ROOT, check=True)
            result = artifact_manifest(config, args.binary, args.idl)
            require(args.output is not None, "--output required")
            write_immutable(args.output, result)
        elif args.command == "prepare-artifacts":
            require(args.output is not None, "--output required")
            result = artifact_manifest(config, args.binary, args.idl)
            write_immutable(args.output, result)
        elif args.command == "verify-artifacts":
            require(manifest is not None, "--manifest required")
            verify_artifacts(config, manifest)
            result = {"verification_status": "PREPARED", "binary_sha256": manifest["binary_sha256"], "idl_sha256": manifest["idl_sha256"]}
        elif args.command == "inspect":
            result = inspect_program(config, rpc)
        elif args.command == "post-deploy-verification":
            require(manifest is not None and args.signature and args.output, "--manifest, --signature and --output required")
            result = seal({**post_deploy(config, rpc, manifest, args.signature),
                           "previous_manifest_sha256": sha256(args.manifest)})
            write_immutable(args.output, result)
        elif args.command == "finalize":
            require(manifest is not None and args.signature and args.output, "--manifest, --signature and --output required")
            verify_artifacts(config, manifest)
            require(manifest["verification_status"] in ("PREPARED", "SUBMITTED"), "Manifest cannot transition to FINALIZED")
            require(manifest.get("deployment_transaction") in (None, args.signature), "Deployment signature mismatch")
            verify_cluster(config, rpc)
            slot = verify_signature(rpc, args.signature, expected_program_id=config["program_id"])
            result = seal({**manifest, "verification_status": "FINALIZED", "deployment_transaction": args.signature,
                           "deployment_slot": slot, "previous_manifest_sha256": sha256(args.manifest)})
            write_immutable(args.output, result)
        elif args.command == "deploy":
            require(manifest is not None and args.output, "--manifest and --output required")
            verify_artifacts(config, manifest)
            require(manifest["verification_status"] == "PREPARED", "Only prepared artifacts can be deployed")
            require(manifest.get("reproducibility_status") == "PASS", "Two clean builds must match before deployment")
            require(approval_valid(manifest, args.submit, args.approval, os.environ.get("CON35_APPROVED_DEPLOYMENT_ID")), "Explicit deployment approval required")
            require(args.wallets and args.program_keypair, "Wallet map and program keypair required")
            wallets = load_json(args.wallets)
            preflight(config, rpc, wallets, True)
            program_signer = wallets.get("program_signer")
            require(program_signer and program_signer.get("binding") and program_signer.get("keypair") == str(args.program_keypair), "Program signer binding required")
            verify_wallet(args.program_keypair, Path(program_signer["binding"]), config["program_id"], "program_signer", config)
            existing = inspect_program(config, rpc)
            require(not existing.get("exists") or existing["upgrade_authority_pubkey"] == config["upgrade_authority_pubkey"], "Upgrade authority mismatch")
            require(not existing.get("exists") or not binary_matches_deployed(rpc, existing["program_data_address"], artifact_path(manifest["binary_path"]).read_bytes()), "Identical binary already deployed")
            command = ["solana", "program", "deploy", "--url", OFFICIAL_RPC, "--use-rpc", "--output", "json", "--commitment", "finalized", "--fee-payer", wallets["fee_payer"]["keypair"], "--upgrade-authority", wallets["upgrade_authority"]["keypair"], "--program-id", str(args.program_keypair), str(artifact_path(manifest["binary_path"]))]
            process = subprocess.run(command, capture_output=True, text=True, check=False)
            require(process.returncode == 0, "Devnet deploy command failed; inspect chain state before retry")
            response = json.loads(process.stdout)
            require(response.get("programId") == config["program_id"], "Deploy returned a different program ID")
            signature = response.get("signature")
            require(isinstance(signature, str) and bool(re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{80,90}", signature)),
                    "Deploy returned no valid final transaction signature")
            result = seal({**manifest, "verification_status": "SUBMITTED", "deployment_transaction": signature,
                      "previous_manifest_sha256": sha256(args.manifest)})
            write_immutable(args.output, result)
        elif args.command == "prepare-rollback":
            require(manifest is not None and args.output, "--manifest and --output required")
            result = prepare_rollback(config, rpc, manifest)
            write_immutable(args.output, result)
        else:
            result = request_test_funds(config, rpc, args.airdrop_pubkey, args.airdrop_lamports)
        print(json.dumps(result, sort_keys=True, indent=2))
    except (DeploymentError, OSError, subprocess.CalledProcessError, ValueError, json.JSONDecodeError) as exc:
        print(f"CON-35 fail-closed: {exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
