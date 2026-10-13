import unittest

from types import SimpleNamespace
from funding_gateway import parse_request


class FundingGatewayTests(unittest.TestCase):

    def setUp(self):
        self.config = SimpleNamespace(
            rpc_url="http://127.0.0.1:8899",
            idl="target/idl/aerosettle.discovery.json",
        )
        self.wallet = (
            "9aA2jeb1Cds7m4VMhYRpGCv9UJzdREZBZAVEYmBxAzeZ"
        )

    def test_valid_request(self):
        result = parse_request(
            f"/preflight?wallet={self.wallet}",
            self.config,
        )
        self.assertEqual(result.wallet, self.wallet)

    def test_duplicate_wallet_rejected(self):
        with self.assertRaises(ValueError):
            parse_request(
                f"/preflight?wallet={self.wallet}"
                f"&wallet={self.wallet}",
                self.config,
            )

    def test_unexpected_parameter_rejected(self):
        with self.assertRaises(ValueError):
            parse_request(
                f"/preflight?wallet={self.wallet}"
                "&private_key=secret",
                self.config,
            )

    def test_invalid_wallet_rejected(self):
        with self.assertRaises(ValueError):
            parse_request(
                "/preflight?wallet=invalid",
                self.config,
            )

    def test_invalid_order_rejected(self):
        with self.assertRaises(ValueError):
            parse_request(
                f"/preflight?wallet={self.wallet}"
                "&work_order=invalid",
                self.config,
            )


if __name__ == "__main__":
    unittest.main()
