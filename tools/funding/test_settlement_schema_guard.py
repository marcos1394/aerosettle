import unittest

from funding_preflight import (
    extract_settlement_terms,
)


MINT = (
    "HTHpns7gqLAhSBhAzqxhYdyHv9HeXkkRW6aHQfdUjL1G"
)


class FakeIDL:

    def __init__(self, nested=True):
        financial_fields = [
            {
                "name": "tokenMint",
                "type": "pubkey",
            },
            {
                "name": "totalAmount",
                "type": "u64",
            },
        ]

        self.types = {
            "SettlementTerms": {
                "kind": "struct",
                "fields": financial_fields,
            },
            "WorkOrderAccount": {
                "kind": "struct",
                "fields": (
                    [{
                        "name": "settlementTerms",
                        "type": {
                            "defined": {
                                "name": "SettlementTerms"
                            }
                        },
                    }]
                    if nested
                    else financial_fields
                ),
            },
        }


class SettlementSchemaTests(unittest.TestCase):

    def test_nested_financial_struct(self):
        order = {
            "settlement_terms": {
                "token_mint": MINT,
                "total_amount": 10_000_000,
            }
        }

        result, source = extract_settlement_terms(
            order,
            FakeIDL(nested=True),
        )

        self.assertEqual(
            result["token_mint"],
            MINT,
        )

        self.assertEqual(
            result["total_amount"],
            10_000_000,
        )

        self.assertIn(
            "settlementTerms",
            source,
        )

    def test_flat_financial_fields(self):
        order = {
            "token_mint": MINT,
            "total_amount": 10_000_000,
        }

        result, _ = extract_settlement_terms(
            order,
            FakeIDL(nested=False),
        )

        self.assertEqual(
            result["total_amount"],
            10_000_000,
        )

    def test_missing_amount_rejected(self):
        order = {
            "settlement_terms": {
                "token_mint": MINT,
            },
        }

        with self.assertRaises(RuntimeError):
            extract_settlement_terms(
                order,
                FakeIDL(nested=True),
            )

    def test_wrong_declared_type_rejected(self):
        idl = FakeIDL(nested=False)

        idl.types["WorkOrderAccount"][
            "fields"
        ][1]["type"] = "u32"

        with self.assertRaises(RuntimeError):
            extract_settlement_terms(
                {
                    "token_mint": MINT,
                    "total_amount": 10_000_000,
                },
                idl,
            )


if __name__ == "__main__":
    unittest.main()
