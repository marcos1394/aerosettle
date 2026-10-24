"""CON-30 private, context-bound, read-only surplus API."""
import unittest

import server
from test_economic_api import DRONE, OWNER_DRONE, OWNER_DRONE_SECRET, OWNER_OTHER_SECRET, MockEconomicProvider
from tools.economic_ledger.auth import create_auth_headers
from tools.economic_ledger.test_budget_policies import body as policy_body


class InvestibleSurplusApiTests(unittest.TestCase):
    def setUp(self):
        self.provider = MockEconomicProvider()
        self.agent = self.provider.snapshot()["agents"][0]
        self.policies = server.get_policy_store(self.provider)
        self.policies.mutate(self.agent, "CREATE", policy_body(), OWNER_DRONE)
        self.policy = self.policies.mutate(self.agent, "ACTIVATE",
            policy_body("ACTIVATE", 1, "00000002"), OWNER_DRONE)[0]
        self.base = f"/v1/agents/{DRONE}/investible-surplus"
        self.auth = create_auth_headers(OWNER_DRONE_SECRET, DRONE)
        self.query = (f"?network={self.policy['network']}&genesis_hash={self.policy['genesis_hash']}"
                      f"&program_id={self.policy['program_id']}&token_mint={self.policy['asset_rules'][0]['token_mint']}")

    def tearDown(self):
        self.provider.ledger.close()

    def test_owner_only_empty_ledger_and_methodology(self):
        with self.assertRaises(server.ApiError) as unsigned:
            server.route(self.base + self.query, self.provider)
        self.assertEqual(unsigned.exception.status, 401)
        with self.assertRaises(server.ApiError) as stranger:
            server.route(self.base + self.query, self.provider,
                         create_auth_headers(OWNER_OTHER_SECRET, DRONE))
        self.assertEqual(stranger.exception.status, 403)
        status, response = server.route(self.base + self.query, self.provider, self.auth)
        self.assertEqual(status, 200)
        self.assertEqual(response["data"]["calculation_status"], "INSUFFICIENT_DATA")
        self.assertIsNone(response["data"]["verified_investible_surplus_base_units_str"])
        self.assertFalse(response["data"]["is_executable"])
        status, response = server.route(self.base + "/methodology", self.provider, self.auth)
        self.assertEqual(status, 200)
        self.assertEqual(response["data"]["methodology_version"], "conatus:investible-surplus:v1")

    def test_strict_context_and_scenarios_do_not_mutate_financial_records(self):
        tables = ("economic_movements", "journal_entries", "ledger_entries", "agent_costs", "agent_reserves",
                  "reserve_transactions", "spending_proposals", "spending_decisions", "spending_budget_claims",
                  "spending_approvals", "spending_approval_events")
        conn = self.provider.ledger._conn
        before = {name: conn.execute(f"SELECT count(*) FROM {name}").fetchone()[0] for name in tables}
        for scenario in ("BASE", "CONSERVATIVE", "STRESS"):
            _, response = server.route(self.base + self.query + f"&scenario={scenario}&horizon_days=30",
                                       self.provider, self.auth)
            self.assertEqual(response["data"]["scenario"], scenario)
            self.assertIsNone(response["data"]["estimated_investible_surplus_base_units_str"])
        after = {name: conn.execute(f"SELECT count(*) FROM {name}").fetchone()[0] for name in tables}
        self.assertEqual(before, after)
        for suffix in ("", "?network=solana:localnet", self.query + "&horizon_days=31",
                       self.query + "&scenario=TRADING", self.query + "&owner=forged",
                       self.query.replace(self.policy["asset_rules"][0]["token_mint"], self.policy["genesis_hash"])):
            with self.assertRaises(server.ApiError):
                server.route(self.base + suffix, self.provider, self.auth)


if __name__ == "__main__":
    unittest.main()
