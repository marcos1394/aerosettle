"""Signed CON-31 API boundaries keep fixtures and financial tables separate."""
import copy
import hashlib
import json
import threading
import time
import unittest
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer
from unittest import mock

import server
from test_economic_api import DRONE, OWNER_DRONE, OWNER_DRONE_SECRET, MockEconomicProvider
from tools.discovery.agent_discovery import b58encode
from cryptography.hazmat.primitives.asymmetric import ed25519
from tools.economic_ledger.auth import create_auth_headers
from tools.economic_ledger.test_budget_policies import OTHER, OTHER_SECRET, body as policy_body
from tools.paper_trading.store import paper_simulation_message
from tools.paper_trading.test_paper_trading import body as paper_body

PATH = f"/v1/agents/{DRONE}/paper-simulations"


class PaperApiTests(unittest.TestCase):
    def setUp(self):
        self.provider = MockEconomicProvider()
        self.agent = self.provider.snapshot()["agents"][0]
        policies = server.get_policy_store(self.provider)
        policies.mutate(self.agent, "CREATE", policy_body(), OWNER_DRONE)
        self.policy = policies.mutate(self.agent, "ACTIVATE",
            policy_body("ACTIVATE", 1, "00000002"), OWNER_DRONE)[0]
        self.auth = create_auth_headers(OWNER_DRONE_SECRET, DRONE)

    def tearDown(self):
        if hasattr(self.provider.ledger, "_paper_simulation_store"):
            self.provider.ledger._paper_simulation_store.close()
        self.provider.ledger.close()

    def request(self, **changes):
        return paper_body(agent_account=DRONE, agent_id=self.agent["agent_id"],
            owner_pubkey=OWNER_DRONE, network=self.policy["network"],
            genesis_hash=self.policy["genesis_hash"], program_id=self.policy["program_id"],
            treasury_token_mint=self.policy["asset_rules"][0]["token_mint"],
            trading_quote_currency=self.policy["asset_rules"][0]["token_mint"], **changes)

    @staticmethod
    def signed(value):
        ts = value["simulation_timestamp"]
        message = paper_simulation_message(ts, DRONE, OWNER_DRONE, PATH, value)
        signature = b58encode(ed25519.Ed25519PrivateKey.from_private_bytes(OWNER_DRONE_SECRET).sign(message))
        return {"X-Signer-Pubkey": OWNER_DRONE, "X-Timestamp": str(ts), "X-Signature": signature}

    def test_signed_run_history_public_fixtures_and_financial_isolation(self):
        tables = ("economic_movements", "journal_entries", "ledger_entries", "agent_costs",
                  "agent_reserves", "reserve_transactions", "spending_proposals", "spending_decisions",
                  "spending_budget_claims", "spending_approvals", "spending_approval_events")
        def fingerprints():
            return {name: hashlib.sha256(repr([tuple(row) for row in self.provider.ledger._conn.execute(
                f"SELECT * FROM {name} ORDER BY rowid")]).encode()).hexdigest() for name in tables}
        before = fingerprints()
        with self.assertRaises(server.ApiError) as unsigned:
            server.route(PATH, self.provider)
        self.assertEqual(unsigned.exception.status, 401)
        status, methodology = server.route("/v1/paper-trading/methodology", self.provider)
        self.assertEqual(status, 200)
        self.assertFalse(methodology["data"]["network_enabled"])
        _, instruments = server.route("/v1/paper-trading/instruments?treasury_token_mint=" +
            self.policy["asset_rules"][0]["token_mint"], self.provider)
        self.assertEqual(instruments["data"][0]["display_symbol"], instruments["data"][1]["display_symbol"])
        self.assertNotEqual(instruments["data"][0]["instrument_id"], instruments["data"][1]["instrument_id"])
        request = self.request()
        with self.assertRaises(server.ApiError) as altered:
            server.paper_simulation_route("POST", PATH, self.provider, self.signed(request),
                {**request, "paper_budget_base_units_str": "1001"})
        self.assertEqual(altered.exception.status, 401)
        status, response = server.paper_simulation_route("POST", PATH, self.provider,
            self.signed(request), request)
        self.assertEqual(status, 201)
        result = response["data"]
        self.assertEqual(result["fill_status"], "PARTIALLY_FILLED_SIMULATED")
        self.assertFalse(result["real_capital_authorized"])
        self.assertEqual(before, fingerprints())
        status, repeated = server.paper_simulation_route("POST", PATH, self.provider,
            self.signed(request), request)
        self.assertEqual(status, 200)
        self.assertEqual(repeated["data"], result)
        self.assertEqual(server.route(PATH, self.provider, self.auth)[1]["data"], [result])
        self.assertEqual(server.route(PATH + "/" + result["simulation_id"], self.provider, self.auth)[1]["data"], result)

    def test_owner_rotation_and_device_signer_cannot_mutate_or_read(self):
        request = self.request()
        self.provider.data["agents"][0]["signing_authority"] = OTHER
        with self.assertRaises(server.ApiError) as denied:
            server.route(PATH, self.provider, create_auth_headers(OTHER_SECRET, DRONE))
        self.assertEqual(denied.exception.status, 403)
        server.paper_simulation_route("POST", PATH, self.provider, self.signed(request), request)
        original = self.provider.snapshot
        def rotated():
            value = copy.deepcopy(original())
            value["agents"][0]["owner"] = OTHER
            return value
        with mock.patch.object(self.provider, "snapshot", side_effect=rotated):
            with self.assertRaises(server.ApiError): server.route(PATH, self.provider, self.auth)
            with self.assertRaises(server.ApiError) as denied:
                server.paper_simulation_route("POST", PATH, self.provider, self.signed(request), request)
            self.assertEqual(denied.exception.status, 403)

    def test_http_post_get_and_real_financial_writes_remain_closed(self):
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.handler_for(self.provider))
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        root = f"http://127.0.0.1:{httpd.server_port}"
        try:
            value = self.request()
            request = urllib.request.Request(root + PATH, data=json.dumps(value).encode(),
                headers={"Content-Type": "application/json", **self.signed(value)}, method="POST")
            with urllib.request.urlopen(request, timeout=3) as response:
                self.assertEqual(response.status, 201)
                simulation_id = json.loads(response.read())["data"]["simulation_id"]
            request = urllib.request.Request(root + PATH + "/" + simulation_id, headers=self.auth)
            with urllib.request.urlopen(request, timeout=3) as response:
                self.assertEqual(json.loads(response.read())["data"]["is_paper"], True)
            request = urllib.request.Request(root + "/v1/economic-movements", data=b"{}", method="POST")
            with self.assertRaises(urllib.error.HTTPError) as denied:
                urllib.request.urlopen(request, timeout=3)
            self.assertEqual(denied.exception.code, 405)
            denied.exception.close()
        finally:
            httpd.shutdown()
            httpd.server_close()


if __name__ == "__main__":
    unittest.main()
