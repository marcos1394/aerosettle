import importlib.util
import hashlib
import tempfile
import unittest

from pathlib import Path


MODULE = Path(__file__).with_name(
    "funding_preflight.py"
)

spec = importlib.util.spec_from_file_location(
    "funding_preflight",
    MODULE,
)

f = importlib.util.module_from_spec(spec)

spec.loader.exec_module(f)


class FundingPreflightTests(unittest.TestCase):

    def test_anchor_discriminator(self):

        result = f.check_idl_discriminator({
            "instructions": []
        })

        expected = hashlib.sha256(
            b"global:fund_work_order"
        ).digest()[:8]

        self.assertEqual(
            result,
            expected,
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "discriminador|Discriminador",
        ):
            f.check_idl_discriminator({
                "instructions": [{
                    "name": "fundWorkOrder",
                    "args": [],
                    "discriminator": [0] * 8,
                }]
            })

    def test_escrow_seed(self):

        with tempfile.TemporaryDirectory() as td:

            root = Path(td)

            src = (
                root
                / "programs"
                / "aerosettle"
                / "src"
            )

            src.mkdir(parents=True)

            file = src / "constants.rs"

            file.write_text(
                'pub const ESCROW_VAULT_SEED: '
                '&[u8] = b"escrow_vault";'
            )

            self.assertEqual(
                f.read_escrow_seed(root),
                b"escrow_vault",
            )

            file.write_text(
                'pub const OTHER_SEED: '
                '&[u8] = b"other";'
            )

            with self.assertRaises(RuntimeError):
                f.read_escrow_seed(root)

    def test_choose_token_source(self):

        def account(
            address,
            amount,
            owner="wallet1",
            state="initialized",
        ):
            return {
                "pubkey": address,
                "account": {
                    "owner": f.TOKEN_PROGRAM,
                    "data": {
                        "parsed": {
                            "type": "account",
                            "info": {
                                "owner": owner,
                                "mint": f.MINT,
                                "state": state,
                                "tokenAmount": {
                                    "amount": str(amount)
                                },
                            },
                        },
                    },
                },
            }

        accounts = [
            account("A", 100),
            account("B", 1200),
            account("C", 800, owner="other"),
            account("D", 5000, state="frozen"),
        ]

        selected, candidates = f.choose_source(
            accounts,
            "wallet1",
            f.MINT,
            500,
        )

        self.assertEqual(
            selected,
            (1200, "B"),
        )

        self.assertEqual(
            len(candidates),
            2,
        )

        selected, _ = f.choose_source(
            accounts,
            "wallet1",
            f.MINT,
            2000,
        )

        self.assertIsNone(selected)

    def test_rust_account_order(self):

        with tempfile.TemporaryDirectory() as td:

            root = Path(td)

            src = (
                root
                / "programs"
                / "aerosettle"
                / "src"
            )

            src.mkdir(parents=True)

            file = src / "fund_work_order.rs"

            accounts = "".join(
                f"  pub {name}: AccountInfo<'info>,\n"
                for name, _, _
                in f.EXPECTED_ACCOUNTS
            )

            file.write_text(
                "pub struct FundWorkOrder<'info> {\n"
                + accounts
                + "}\n"
            )

            result = f.rust_account_audit(root)

            self.assertEqual(
                len(result["accounts_in_rust_order"]),
                8,
            )

            file.write_text(
                "pub struct FundWorkOrder<'info> {\n"
                "pub creator: Signer<'info>,\n"
                "}\n"
            )

            with self.assertRaises(RuntimeError):
                f.rust_account_audit(root)


if __name__ == "__main__":
    unittest.main()
