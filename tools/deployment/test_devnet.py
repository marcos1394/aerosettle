import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.deployment import build_idl, devnet


CONFIG = json.loads(Path(__file__).with_name("devnet.json").read_text())
SIGNATURE = "3" * 88


class FakeRpc:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def call(self, method, params=None):
        self.calls.append((method, params))
        result = self.responses.get(method)
        if isinstance(result, Exception):
            raise result
        return result


def rpc_with_program(config, binary=b"ELF"):
    program_data_address, _ = devnet.find_program_address([devnet.b58decode(config["program_id"], 32)], devnet.LOADER)
    program_data_key = devnet.b58decode(program_data_address, 32)
    authority = devnet.b58encode(bytes([8] * 32))
    config["upgrade_authority_pubkey"] = authority
    program = {"owner": devnet.LOADER, "executable": True, "data": [__import__("base64").b64encode((2).to_bytes(4, "little") + program_data_key).decode(), "base64"]}
    data = (3).to_bytes(4, "little") + (42).to_bytes(8, "little") + b"\x01" + bytes([8] * 32) + binary
    program_data = {"owner": devnet.LOADER, "data": [__import__("base64").b64encode(data).decode(), "base64"]}

    class Accounts(FakeRpc):
        def call(self, method, params=None):
            if method == "getAccountInfo":
                return {"value": program if params[0] == config["program_id"] else program_data if params[0] == devnet.b58encode(program_data_key) else None}
            return super().call(method, params)

    return Accounts({"getGenesisHash": config["genesis_hash"]})


class DevnetTests(unittest.TestCase):
    def test_cluster_identity_rejects_mainnet_unknown_rpc_and_missing_fields(self):
        for change in ({"rpc_url": "https://api.mainnet-beta.solana.com"}, {"rpc_url": "https://other.devnet.example"}, {"network": "solana:mainnet"}, {"program_id": "incorrect"}, {"genesis_hash": "incorrect"}, {"environment": None}):
            with self.subTest(change=change), self.assertRaises(devnet.DeploymentError):
                devnet.validate_config({**CONFIG, **change})

    def test_rpc_genesis_mismatch(self):
        with self.assertRaisesRegex(devnet.DeploymentError, "Genesis mismatch"):
            devnet.verify_cluster(CONFIG, FakeRpc({"getGenesisHash": "wrong"}))

    def test_rpc_failure_does_not_log_exception_secrets(self):
        with patch.object(devnet.urllib.request, "urlopen", side_effect=RuntimeError("sensitive-provider-token")):
            with self.assertRaises(devnet.DeploymentError) as failure:
                devnet.Rpc(devnet.OFFICIAL_RPC).call("getGenesisHash")
        self.assertNotIn("sensitive-provider-token", str(failure.exception))

    def test_program_absent_is_not_verified(self):
        rpc = FakeRpc({"getGenesisHash": CONFIG["genesis_hash"], "getAccountInfo": {"value": None}})
        self.assertEqual(devnet.inspect_program(CONFIG, rpc)["verification_status"], "PREPARED")

    def test_program_executable_programdata_and_authority(self):
        config = copy.deepcopy(CONFIG)
        rpc = rpc_with_program(config)
        self.assertEqual(devnet.inspect_program(config, rpc)["binary_sha256"], __import__("hashlib").sha256(b"ELF").hexdigest())
        rpc = rpc_with_program(config)
        old = rpc.call
        def broken(method, params=None):
            value = old(method, params)
            if method == "getAccountInfo" and params[0] == config["program_id"]:
                value["value"]["executable"] = False
            return value
        rpc.call = broken
        with self.assertRaisesRegex(devnet.DeploymentError, "not executable"):
            devnet.inspect_program(config, rpc)
        config["upgrade_authority_pubkey"] = "wrong"
        with self.assertRaisesRegex(devnet.DeploymentError, "Unrecognized upgrade authority"):
            devnet.inspect_program(config, rpc_with_program(copy.deepcopy(CONFIG)))

    def test_programdata_missing(self):
        config = copy.deepcopy(CONFIG)
        rpc = rpc_with_program(config)
        old = rpc.call
        def missing(method, params=None):
            response = old(method, params)
            if method == "getAccountInfo" and params[0] != config["program_id"]:
                return {"value": None}
            return response
        rpc.call = missing
        with self.assertRaisesRegex(devnet.DeploymentError, "ProgramData missing"):
            devnet.inspect_program(config, rpc)

    def test_mint_must_exist_on_devnet_with_exact_authority_and_decimals(self):
        config = copy.deepcopy(CONFIG)
        config.update({"test_mint_pubkey": "test-mint", "test_mint_authority_pubkey": devnet.b58encode(bytes([9] * 32)), "test_mint_decimals": 6})
        raw = (1).to_bytes(4, "little") + bytes([9] * 32) + (0).to_bytes(8, "little") + bytes([6, 1]) + bytes(36)
        mint = {"owner": devnet.TOKEN_PROGRAM, "data": [__import__("base64").b64encode(raw).decode(), "base64"]}
        rpc = FakeRpc({"getGenesisHash": config["genesis_hash"], "getAccountInfo": {"value": mint}})
        self.assertFalse(devnet.preflight(config, rpc)["deployment_ready"])
        bad = copy.deepcopy(config)
        bad["test_mint_decimals"] = 9
        with self.assertRaisesRegex(devnet.DeploymentError, "authority or decimals"):
            devnet.preflight(bad, rpc)
        mint["owner"] = "wrong"
        with self.assertRaisesRegex(devnet.DeploymentError, "wrong owner"):
            devnet.preflight(config, rpc)

    def test_manifest_binary_idl_and_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / "program.so"
            binary.write_bytes(b"ELF")
            idl = root / "idl.json"
            idl.write_bytes((devnet.ROOT / "tools/integration/localnet/aerosettle-idl.json").read_bytes())
            with patch.object(devnet, "version", return_value="test-toolchain"):
                manifest = devnet.artifact_manifest(CONFIG, binary, idl)
            devnet.verify_artifacts(CONFIG, manifest)
            manifest_path = root / "manifest.json"
            devnet.write_prepared_manifest(CONFIG, manifest_path, manifest)
            retry = devnet.seal({**manifest, "build_timestamp": "later"})
            self.assertEqual(devnet.write_prepared_manifest(CONFIG, manifest_path, retry), manifest)
            with self.assertRaisesRegex(devnet.DeploymentError, "different artifacts or context"):
                devnet.write_prepared_manifest(CONFIG, manifest_path, devnet.seal({**retry, "source_commit": "other"}))
            altered = {**manifest, "verification_status": "VERIFIED"}
            with self.assertRaisesRegex(devnet.DeploymentError, "integrity"):
                devnet.verify_artifacts(CONFIG, altered)
            binary.write_bytes(b"BAD")
            with self.assertRaisesRegex(devnet.DeploymentError, "Binary hash"):
                devnet.verify_artifacts(CONFIG, manifest)
            binary.write_bytes(b"ELF")
            idl.write_text(json.dumps({"address": "wrong", "instructions": [{"name": "x"}], "accounts": [{"name": "y"}]}))
            with self.assertRaisesRegex(devnet.DeploymentError, "IDL hash"):
                devnet.verify_artifacts(CONFIG, manifest)
            with self.assertRaisesRegex(devnet.DeploymentError, "IDL program ID mismatch"):
                devnet.artifact_manifest(CONFIG, binary, idl)

    def test_wallet_binding_and_insufficient_funds(self):
        config = copy.deepcopy(CONFIG)
        config.update({"fee_payer_pubkey": "fee", "upgrade_authority_pubkey": "upgrade", "protocol_admin_pubkey": "admin"})
        with tempfile.TemporaryDirectory() as directory:
            entries = {}
            for role, pubkey in (("fee_payer", "fee"), ("upgrade_authority", "upgrade"), ("protocol_admin", "admin")):
                keypair = Path(directory) / (role + ".json")
                keypair.write_text("private-test-fixture")
                binding = Path(directory) / (role + ".binding.json")
                binding.write_text(json.dumps({"environment": "devnet", "genesis_hash": config["genesis_hash"], "role": role, "pubkey": pubkey}))
                entries[role] = {"keypair": str(keypair), "binding": str(binding)}
            rpc = FakeRpc({"getGenesisHash": config["genesis_hash"], "getBalance": {"value": 0}})
            with patch.object(devnet, "keypair_pubkey", side_effect=["fee", "upgrade", "admin"]):
                with self.assertRaisesRegex(devnet.DeploymentError, "lacks test SOL"):
                    devnet.preflight(config, rpc, entries, True)
            binding = Path(entries["fee_payer"]["binding"])
            binding.write_text(binding.read_text().replace("devnet", "localnet"))
            with self.assertRaisesRegex(devnet.DeploymentError, "binding mismatch"):
                devnet.preflight(config, rpc, entries, True)

    def test_deployment_checks_dynamic_rent_before_submit(self):
        rpc = FakeRpc({"getMinimumBalanceForRentExemption": 2_500_000_000})
        initial = devnet.required_deploy_lamports(CONFIG, rpc, 500_000, False)
        upgrade = devnet.required_deploy_lamports(CONFIG, rpc, 500_000, True)
        self.assertEqual(initial, 5_000_000_000 + CONFIG["minimum_fee_payer_lamports"])
        self.assertEqual(upgrade, 2_500_000_000 + CONFIG["minimum_fee_payer_lamports"])
        self.assertEqual(rpc.calls[0][0], "getMinimumBalanceForRentExemption")
        self.assertEqual(rpc.calls[0][1][0], 500_045)
        with self.assertRaisesRegex(devnet.DeploymentError, "Invalid Devnet rent quote"):
            devnet.required_deploy_lamports(CONFIG, FakeRpc({"getMinimumBalanceForRentExemption": None}), 500_000, False)

    def test_signature_finality_and_incomplete_deployment(self):
        for responses in (
            {"getSignatureStatuses": {"value": [None]}},
            {"getSignatureStatuses": {"value": [{"confirmationStatus": "confirmed", "err": None}]}},
            {"getSignatureStatuses": {"value": [{"confirmationStatus": "finalized", "err": None, "slot": 42}]}, "getTransaction": None},
            {"getSignatureStatuses": {"value": [{"confirmationStatus": "finalized", "err": None, "slot": 42}]},
             "getTransaction": {"slot": 42, "meta": {"err": None}, "transaction": {"signatures": ["4" * 88]}}},
            {"getSignatureStatuses": {"value": [{"confirmationStatus": "finalized", "err": None, "slot": 42}]},
             "getTransaction": {"slot": 42, "transaction": {"signatures": [SIGNATURE]}}},
        ):
            with self.subTest(responses=responses), self.assertRaises(devnet.DeploymentError):
                devnet.verify_signature(FakeRpc(responses), SIGNATURE)

    def test_approval_and_idempotent_immutable_history(self):
        manifest = {"deployment_id": "abc"}
        self.assertFalse(devnet.approval_valid(manifest, False, "abc", "abc"))
        self.assertFalse(devnet.approval_valid(manifest, True, "abc", None))
        self.assertFalse(devnet.approval_valid(manifest, True, "other", "abc"))
        self.assertTrue(devnet.approval_valid(manifest, True, "abc", "abc"))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "immutable.json"
            devnet.write_immutable(path, manifest)
            devnet.write_immutable(path, manifest)
            with self.assertRaisesRegex(devnet.DeploymentError, "different content"):
                devnet.write_immutable(path, {"deployment_id": "other"})

    def test_airdrop_limit_and_rollback_gate(self):
        self.assertLessEqual(CONFIG["maximum_airdrop_lamports"], 2_000_000_000)
        self.assertLessEqual(CONFIG["maximum_test_wallet_lamports"], 10_000_000_000)
        self.assertEqual(devnet.STATES, {"PREPARED", "SUBMITTED", "FINALIZED", "VERIFIED", "FAILED"})
        rpc = FakeRpc({"getGenesisHash": CONFIG["genesis_hash"], "getBalance": {"value": 10_000_000_000}})
        with self.assertRaisesRegex(devnet.DeploymentError, "limit"):
            devnet.request_test_funds(CONFIG, rpc, "test-wallet", 1)
        with self.assertRaisesRegex(devnet.DeploymentError, "limit"):
            devnet.request_test_funds(CONFIG, rpc, "test-wallet", 2_000_000_001)
        failed = FakeRpc({"getGenesisHash": CONFIG["genesis_hash"], "getBalance": {"value": 0}, "requestAirdrop": devnet.DeploymentError("Airdrop rejected")})
        with self.assertRaisesRegex(devnet.DeploymentError, "Airdrop rejected"):
            devnet.request_test_funds(CONFIG, failed, "test-wallet", 1)
        with patch.object(devnet, "verify_artifacts", side_effect=devnet.DeploymentError("Binary hash mismatch")):
            with self.assertRaisesRegex(devnet.DeploymentError, "Binary hash mismatch"):
                devnet.prepare_rollback(CONFIG, rpc, {"verification_status": "VERIFIED"})
        with patch.object(devnet, "verify_artifacts"):
            with self.assertRaisesRegex(devnet.DeploymentError, "verified historic artifact"):
                devnet.prepare_rollback(CONFIG, rpc, {"verification_status": "PREPARED"})

    def test_postdeploy_requires_matching_slot_binary_and_finalized_signature(self):
        config = copy.deepcopy(CONFIG)
        config.update({"protocol_admin_pubkey": devnet.b58encode(bytes([7] * 32)),
                       "protocol_network_id_hex": "11" * 32, "protocol_deployment_id_hex": "22" * 32})
        rpc = rpc_with_program(config)
        program_data_address, _ = devnet.find_program_address([devnet.b58decode(config["program_id"], 32)], devnet.LOADER)
        rpc.responses.update({
            "getSignatureStatuses": {"value": [{"confirmationStatus": "finalized", "err": None, "slot": 42}]},
            "getTransaction": {"slot": 42, "meta": {"err": None}, "transaction": {"signatures": [SIGNATURE], "message": {
                "accountKeys": [config["program_id"], devnet.LOADER, program_data_address],
                "instructions": [{"programIdIndex": 1, "accounts": [0, 2], "data": devnet.b58encode((2).to_bytes(4, "little"))}],
            }}},
        })
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / "program.so"
            binary.write_bytes(b"ELF")
            idl = Path(directory) / "idl.json"
            idl.write_bytes((devnet.ROOT / "tools/integration/localnet/aerosettle-idl.json").read_bytes())
            source = __import__("subprocess").check_output(["git", "rev-parse", "HEAD"], cwd=devnet.ROOT, text=True).strip()
            (Path(directory) / "reproducibility.json").write_text(json.dumps({
                "status": "PASS", "source_commit": source, "cargo_lock_hash": devnet.sha256(devnet.ROOT / "Cargo.lock"),
                "binary_sha256": devnet.sha256(binary), "idl_sha256": devnet.sha256(idl),
            }))
            with patch.object(devnet, "version", return_value="test-toolchain"):
                manifest = devnet.artifact_manifest(config, binary, idl)
            verified = devnet.post_deploy(config, rpc, manifest, SIGNATURE)
            self.assertEqual(verified["verification_status"], "VERIFIED")
            self.assertEqual(verified["deployment_slot"], 42)
            self.assertEqual(verified["protocol_config_status"], "UNINITIALIZED")
            pda, bump = devnet.derive_protocol_config_pda(config["program_id"])
            raw = (__import__("hashlib").sha256(b"account:ProtocolConfig").digest()[:8] + b"\x01" +
                   bytes([7] * 32) + bytes([0x11] * 32) + devnet.b58decode(config["program_id"], 32) +
                   bytes([0x22] * 32) + bytes([bump]) + bytes(17))
            config_account = {"owner": config["program_id"], "data": [__import__("base64").b64encode(raw).decode(), "base64"]}
            original_call = rpc.call
            def with_protocol_config(method, params=None):
                if method == "getAccountInfo" and params[0] == pda:
                    return {"value": config_account}
                return original_call(method, params)
            rpc.call = with_protocol_config
            self.assertEqual(devnet.post_deploy(config, rpc, manifest, SIGNATURE)["protocol_config_status"], "PRESENT")
            corrupted = bytearray(raw)
            corrupted[41] ^= 1
            config_account["data"][0] = __import__("base64").b64encode(corrupted).decode()
            with self.assertRaisesRegex(devnet.DeploymentError, "Protocol network ID mismatch"):
                devnet.post_deploy(config, rpc, manifest, SIGNATURE)
            config_account["data"][0] = __import__("base64").b64encode(raw).decode()
            config_account["owner"] = devnet.LOADER
            with self.assertRaisesRegex(devnet.DeploymentError, "ProtocolConfig PDA owner mismatch"):
                devnet.post_deploy(config, rpc, manifest, SIGNATURE)
            padded = rpc_with_program(config, b"ELF\x00\x00")
            padded.responses.update(rpc.responses)
            self.assertEqual(devnet.post_deploy(config, padded, manifest, SIGNATURE)["verification_status"], "VERIFIED")
            mismatched = rpc_with_program(config, b"BAD")
            mismatched.responses.update(rpc.responses)
            with self.assertRaisesRegex(devnet.DeploymentError, "On-chain binary"):
                devnet.post_deploy(config, mismatched, manifest, SIGNATURE)
            binary.write_bytes(b"BAD")
            with self.assertRaisesRegex(devnet.DeploymentError, "Binary hash"):
                devnet.post_deploy(config, rpc, manifest, SIGNATURE)
            binary.write_bytes(b"ELF")
            rpc.responses["getTransaction"]["slot"] = 43
            with self.assertRaisesRegex(devnet.DeploymentError, "slot mismatch"):
                devnet.post_deploy(config, rpc, manifest, SIGNATURE)
            rpc.responses["getTransaction"]["slot"] = 42
            rpc.responses["getTransaction"]["transaction"]["message"]["accountKeys"] = ["other"]
            with self.assertRaisesRegex(devnet.DeploymentError, "does not reference"):
                devnet.post_deploy(config, rpc, manifest, SIGNATURE)
            rpc.responses["getTransaction"]["transaction"]["message"]["accountKeys"] = [config["program_id"], devnet.LOADER, program_data_address]
            rpc.responses["getTransaction"]["transaction"]["message"]["instructions"] = []
            with self.assertRaisesRegex(devnet.DeploymentError, "lacks a loader"):
                devnet.post_deploy(config, rpc, manifest, SIGNATURE)

    def test_later_protocol_config_requires_finalized_bound_evidence(self):
        config = copy.deepcopy(CONFIG)
        pda, _ = devnet.derive_protocol_config_pda(config["program_id"])
        manifest = {"deployment_id": "ab" * 32}
        evidence = {
            "verification_status": "VERIFIED", "approval_id": devnet.CON36_PROTOCOL_APPROVAL_ID,
            "network": config["network"], "genesis_hash": config["genesis_hash"],
            "protocol_config_pda": pda, "protocol_deployment_id_hex": manifest["deployment_id"],
            "network_id_hex": "cd" * 32, "signature": SIGNATURE, "slot": 99,
        }
        transaction = {"slot": 99, "meta": {"err": None}, "transaction": {
            "signatures": [SIGNATURE], "message": {
                "accountKeys": [config["program_id"], pda],
                "instructions": [{"programIdIndex": 0, "accounts": [1], "data": "1"}],
            },
        }}
        rpc = FakeRpc({
            "getSignatureStatuses": {"value": [{"confirmationStatus": "finalized", "err": None, "slot": 99}]},
            "getTransaction": transaction,
        })
        self.assertEqual(devnet.protocol_context_from_finalized_evidence(config, rpc, manifest, pda, evidence),
                         ("cd" * 32, "ab" * 32))
        for field, wrong in (("approval_id", "wrong"), ("genesis_hash", "wrong"),
                             ("network", "solana:mainnet-beta"), ("protocol_config_pda", "wrong"),
                             ("protocol_deployment_id_hex", "ef" * 32)):
            with self.subTest(field=field):
                altered = {**evidence, field: wrong}
                with self.assertRaisesRegex(devnet.DeploymentError, "identity mismatch"):
                    devnet.protocol_context_from_finalized_evidence(config, rpc, manifest, pda, altered)
        rpc.responses["getSignatureStatuses"]["value"][0]["confirmationStatus"] = "confirmed"
        with self.assertRaisesRegex(devnet.DeploymentError, "not finalized"):
            devnet.protocol_context_from_finalized_evidence(config, rpc, manifest, pda, evidence)
        rpc.responses["getSignatureStatuses"]["value"][0]["confirmationStatus"] = "finalized"
        transaction["transaction"]["message"]["instructions"] = []
        with self.assertRaisesRegex(devnet.DeploymentError, "instruction missing"):
            devnet.protocol_context_from_finalized_evidence(config, rpc, manifest, pda, evidence)
        transaction["transaction"]["message"]["instructions"] = "malformed"
        with self.assertRaisesRegex(devnet.DeploymentError, "Malformed ProtocolConfig transaction"):
            devnet.protocol_context_from_finalized_evidence(config, rpc, manifest, pda, evidence)

    def test_idl_compilation_matches_existing_abi(self):
        synthetic = '\n'.join([
            '--- IDL begin address ---', json.dumps(json.dumps(devnet.PROGRAM_ID)), '--- IDL end address ---',
            '--- IDL begin errors ---', json.dumps([{"code": 6000, "name": "InvalidNetworkId"}]), '--- IDL end errors ---',
            '--- IDL begin errors ---', json.dumps([{"code": 6000, "name": "Unauthorized"}]), '--- IDL end errors ---',
            '--- IDL begin errors ---', json.dumps([{"code": 6000, "name": "InvalidWorkOrderId"}]), '--- IDL end errors ---',
            '--- IDL begin program ---', json.dumps({"instructions": [], "accounts": [], "types": []}), '--- IDL end program ---',
        ])
        generated, catalog = build_idl.generate(synthetic)
        self.assertEqual(generated["address"], devnet.PROGRAM_ID)
        self.assertEqual(generated["errors"], [])
        self.assertEqual(set(catalog["error_groups"]), {"ErrorCode", "IdentityError", "WorkOrderError"})


if __name__ == "__main__":
    unittest.main()
