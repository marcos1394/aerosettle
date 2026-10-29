import base64
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.deployment import devnet, test_mint


MINT = devnet.b58encode(bytes([7] * 32))
AUTHORITY = devnet.b58encode(bytes([8] * 32))
PAYER = devnet.b58encode(bytes([9] * 32))
SIGNATURE = "3" * 88
PLAN = test_mint.make_plan(MINT, AUTHORITY, PAYER)


class MintRpc:
    def __init__(self):
        raw = (1).to_bytes(4, "little") + devnet.b58decode(AUTHORITY, 32)
        raw += (0).to_bytes(8, "little") + bytes([6, 1]) + bytes(36)
        self.mint = {"owner": devnet.TOKEN_PROGRAM, "executable": False,
                     "data": [base64.b64encode(raw).decode(), "base64"]}
        self.genesis = devnet.DEVNET_GENESIS
        self.status = {"value": [{"confirmationStatus": "finalized", "err": None, "slot": 42}]}
        self.transaction = {
            "slot": 42, "meta": {"err": None},
            "transaction": {"signatures": [SIGNATURE], "message": {"instructions": [
                {"program": "system", "parsed": {"type": "createAccount", "info": {
                    "newAccount": MINT, "source": PAYER, "owner": devnet.TOKEN_PROGRAM,
                    "space": test_mint.MINT_SIZE}}},
                {"programId": devnet.TOKEN_PROGRAM, "parsed": {"type": "initializeMint2", "info": {
                    "mint": MINT, "mintAuthority": AUTHORITY, "decimals": 6,
                    "freezeAuthority": None}}},
            ]}}}
        self.calls = []

    def call(self, method, params=None):
        self.calls.append((method, params))
        if method == "getGenesisHash":
            return self.genesis
        if method == "getAccountInfo":
            return {"value": self.mint}
        if method == "getSignatureStatuses":
            return self.status
        if method == "getTransaction":
            return self.transaction
        if method == "getMinimumBalanceForRentExemption":
            return 1_066_800
        if method == "getBalance":
            return {"value": 10_000_000}
        raise AssertionError(method)


class TestMintTests(unittest.TestCase):
    def test_preflight_is_read_only_and_requires_absent_mint(self):
        rpc = MintRpc()
        rpc.mint = None
        self.assertFalse(test_mint.preflight(PLAN, rpc)["transaction_submitted"])
        self.assertEqual([m for m, _ in rpc.calls], ["getGenesisHash", "getAccountInfo",
                                                     "getMinimumBalanceForRentExemption", "getBalance"])
        rpc.mint = MintRpc().mint
        with self.assertRaisesRegex(devnet.DeploymentError, "already exists"):
            test_mint.preflight(PLAN, rpc)

    def test_real_creation_evidence_and_account_are_required(self):
        result = test_mint.verify(PLAN, MintRpc(), SIGNATURE)
        self.assertEqual(result["verification_status"], "VERIFIED")
        self.assertEqual(result["creation_slot"], 42)
        self.assertEqual(result["creation_signature"], SIGNATURE)

        for mutate, message in (
            (lambda r: setattr(r, "genesis", "wrong"), "genesis mismatch"),
            (lambda r: r.status["value"][0].update(confirmationStatus="confirmed"), "not finalized"),
            (lambda r: r.transaction["transaction"].update(signatures=["4" * 88]), "evidence mismatch"),
            (lambda r: r.transaction["transaction"]["message"].update(instructions=[]), "did not create"),
            (lambda r: r.mint.update(owner=devnet.LOADER), "wrong owner"),
            (lambda r: r.mint.update(data=[base64.b64encode(bytes([0]) + devnet._data(r.mint)[1:]).decode(), "base64"]), "configuration mismatch"),
            (lambda r: r.mint.update(data=[base64.b64encode(devnet._data(r.mint)[:44] + bytes([9]) + devnet._data(r.mint)[45:]).decode(), "base64"]), "configuration mismatch"),
        ):
            with self.subTest(message=message):
                rpc = MintRpc()
                mutate(rpc)
                with self.assertRaisesRegex(devnet.DeploymentError, message):
                    test_mint.verify(PLAN, rpc, SIGNATURE)

    def test_wrong_authority_and_decimals_in_live_mint_fail(self):
        for start, replacement in ((4, bytes([6] * 32)), (44, bytes([9]))):
            with self.subTest(start=start):
                rpc = MintRpc()
                raw = bytearray(devnet._data(rpc.mint))
                raw[start:start + len(replacement)] = replacement
                rpc.mint["data"][0] = base64.b64encode(raw).decode()
                with self.assertRaisesRegex(devnet.DeploymentError, "configuration mismatch"):
                    test_mint.verify(PLAN, rpc, SIGNATURE)

    def test_no_creation_without_exact_separate_approval(self):
        rpc = MintRpc()
        rpc.mint = None
        with patch.object(test_mint.subprocess, "run") as run:
            for submit, approval, environment in ((False, PLAN["creation_id"], PLAN["creation_id"]),
                                                   (True, "wrong", PLAN["creation_id"]),
                                                   (True, PLAN["creation_id"], "wrong")):
                with self.subTest(submit=submit, approval=approval, environment=environment):
                    with patch.dict(test_mint.devnet.os.environ, {"CON35_APPROVED_TEST_MINT_ID": environment}):
                        with self.assertRaisesRegex(devnet.DeploymentError, "approval required"):
                            test_mint.submit(PLAN, rpc, Path("mint"), Path("authority"), Path("payer"), approval, submit)
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
