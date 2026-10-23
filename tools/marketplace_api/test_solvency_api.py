"""Owner authorization and contract tests for read-only CON-25 routes."""
import unittest

import server
from test_economic_api import MockEconomicProvider, DRONE, OWNER_DRONE_SECRET, OWNER_OTHER_SECRET
from tools.economic_ledger.auth import create_auth_headers


class SolvencyApiTests(unittest.TestCase):
    def setUp(self):
        self.provider = MockEconomicProvider()
        self.path = f"/v1/agents/{DRONE}/solvency"

    def tearDown(self):
        self.provider.ledger.close()

    def test_owner_only_and_insufficient_empty_context(self):
        with self.assertRaises(server.ApiError) as ctx:
            server.route(self.path, self.provider)
        self.assertEqual(ctx.exception.status, 401)
        with self.assertRaises(server.ApiError) as ctx:
            server.route(self.path, self.provider, headers=create_auth_headers(OWNER_OTHER_SECRET, DRONE))
        self.assertEqual(ctx.exception.status, 403)
        headers = create_auth_headers(OWNER_DRONE_SECRET, DRONE)
        status, response = server.route(self.path + "?network=solana:localnet&genesis_hash=" + server.GENESIS +
            "&program_id=" + server.PROGRAM_ID + "&mint=EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", self.provider, headers=headers)
        self.assertEqual(status, 200)
        self.assertEqual(response["data"][0]["calculation_status"], "INSUFFICIENT_DATA")
        self.assertIsNone(response["data"][0]["conatus_ratio"])

    def test_methodology_history_and_invalid_window(self):
        headers = create_auth_headers(OWNER_DRONE_SECRET, DRONE)
        status, result = server.route(self.path + "/methodology", self.provider, headers=headers)
        self.assertEqual(status, 200)
        self.assertEqual(result["data"]["methodology_version"], "conatus-solvency-v1")
        status, result = server.route(self.path + "/history", self.provider, headers=headers)
        self.assertEqual((status, result["data"]), (200, []))
        with self.assertRaises(server.ApiError) as ctx:
            server.route(self.path + "?window=31", self.provider, headers=headers)
        self.assertEqual(ctx.exception.status, 400)


if __name__ == "__main__":
    unittest.main()
