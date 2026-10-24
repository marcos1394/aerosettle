"""CON-27 Marketplace policy routes retain owner-only access."""
import copy
import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest import mock

import server
from test_economic_api import MockEconomicProvider, DRONE, OWNER_DRONE_SECRET, OWNER_DRONE
from tools.economic_ledger.auth import create_auth_headers
from tools.economic_ledger.test_budget_policies import body, headers


PATH = f"/v1/agents/{DRONE}/budget-policy"


class BudgetPolicyApiTests(unittest.TestCase):
    def setUp(self):
        self.provider = MockEconomicProvider()

    def tearDown(self):
        self.provider.ledger.close()

    def test_signed_policy_routes_and_private_reads(self):
        with self.assertRaises(server.ApiError) as missing:
            server.route(PATH, self.provider)
        self.assertEqual(missing.exception.status, 401)
        with self.assertRaises(server.ApiError) as missing_policy:
            server.route(PATH, self.provider, create_auth_headers(OWNER_DRONE_SECRET, DRONE))
        self.assertEqual(missing_policy.exception.status, 404)
        value = body()
        with self.assertRaises(server.ApiError) as unsigned:
            server.policy_mutation_route("POST", PATH, self.provider, {}, value)
        self.assertEqual(unsigned.exception.status, 401)
        with self.assertRaises(server.ApiError) as tampered:
            server.policy_mutation_route("POST", PATH, self.provider, headers(value),
                                         {**value, "expires_at": value["expires_at"] + 10})
        self.assertEqual(tampered.exception.status, 401)
        status, created = server.policy_mutation_route("POST", PATH, self.provider, headers(value), value)
        self.assertEqual(status, 201)
        self.assertEqual(created["data"]["status"], "DRAFT")
        self.assertEqual(created["data"]["owner_pubkey"], OWNER_DRONE)
        status, retry = server.policy_mutation_route("POST", PATH, self.provider, headers(value), value)
        self.assertEqual(status, 200)
        self.assertEqual(retry["data"]["version"], 1)
        auth = create_auth_headers(OWNER_DRONE_SECRET, DRONE)
        status, current = server.route(PATH, self.provider, auth)
        self.assertEqual(status, 200)
        self.assertEqual(current["data"]["reserve_comparison"][0]["accounting_reserved_base_units_str"], "0")
        active_body = body("ACTIVATE", 1, "00000002")
        status, active = server.policy_mutation_route(
            "POST", PATH + "/activate", self.provider,
            headers(active_body, path=PATH + "/activate"), active_body)
        self.assertEqual(status, 200)
        self.assertEqual(active["data"]["status"], "ACTIVE")
        status, history = server.route(PATH + "/history", self.provider, auth)
        self.assertEqual(status, 200)
        self.assertEqual([x["version"] for x in history["data"]], [2, 1])
        status, old = server.route(PATH + "/1", self.provider, auth)
        self.assertEqual(status, 200)
        self.assertEqual(old["data"]["status"], "DRAFT")

    def test_other_owner_and_general_accounting_writes_fail(self):
        value = body()
        from tools.economic_ledger.test_budget_policies import OTHER, OTHER_SECRET
        with self.assertRaises(server.ApiError) as wrong:
            server.policy_mutation_route("POST", PATH, self.provider,
                                         headers(value, secret=OTHER_SECRET, signer=OTHER), value)
        self.assertEqual(wrong.exception.status, 403)
        for path in ("/v1/economic-movements", "/v1/costs", "/v1/reserves"):
            with self.assertRaises(server.ApiError) as general:
                server.policy_mutation_route("POST", path, self.provider, {}, value)
            self.assertEqual(general.exception.status, 405)

    def test_owner_change_between_signature_check_and_write_fails(self):
        value = body()
        original = self.provider.snapshot
        snapshots = 0
        def changed_snapshot():
            nonlocal snapshots
            snapshots += 1
            snapshot = original()
            if snapshots > 1:
                snapshot["agents"] = [
                    {**agent, "owner": "11111111111111111111111111111111"}
                    if agent["agent_account"] == DRONE else agent for agent in snapshot["agents"]
                ]
            return snapshot
        with mock.patch.object(self.provider, "snapshot", side_effect=changed_snapshot):
            with self.assertRaises(server.ApiError) as changed:
                server.policy_mutation_route("POST", PATH, self.provider, headers(value), value)
        self.assertEqual(changed.exception.status, 403)
        self.assertEqual(self.provider.ledger._conn.execute("SELECT count(*) FROM agent_budget_policies").fetchone()[0], 0)

    def test_historical_routes_close_after_owner_or_agent_id_change(self):
        value = body()
        _, created = server.policy_mutation_route("POST", PATH, self.provider, headers(value), value)
        policy_hash = created["data"]["policy_hash"]
        original = self.provider.snapshot
        from tools.economic_ledger.test_budget_policies import OTHER, OTHER_SECRET
        for changed_field, changed_value, secret in (
            ("owner", OTHER, OTHER_SECRET),
            ("agent_id", "22" * 32, OWNER_DRONE_SECRET),
        ):
            def changed_snapshot():
                snapshot = copy.deepcopy(original())
                snapshot["agents"] = [
                    {**agent, changed_field: changed_value} if agent["agent_account"] == DRONE else agent
                    for agent in snapshot["agents"]
                ]
                return snapshot
            with mock.patch.object(self.provider, "snapshot", side_effect=changed_snapshot):
                auth = create_auth_headers(secret, DRONE)
                for path in (PATH, PATH + "/history", PATH + "/1"):
                    with self.assertRaises(server.ApiError) as denied:
                        server.route(path, self.provider, auth)
                    self.assertEqual(denied.exception.status, 404)
                    self.assertNotIn(policy_hash, str(denied.exception))
                signer = OTHER if changed_field == "owner" else OWNER_DRONE
                with self.assertRaises(server.ApiError) as denied_retry:
                    server.policy_mutation_route(
                        "POST", PATH, self.provider,
                        headers(value, secret=secret, signer=signer), value)
                self.assertEqual(denied_retry.exception.status, 404)
                self.assertNotIn(policy_hash, str(denied_retry.exception))

    def test_http_signed_mutation_and_accounting_write_boundary(self):
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.handler_for(self.provider))
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        origin = f"http://127.0.0.1:{httpd.server_port}"
        def request(path, value, auth):
            req = urllib.request.Request(origin + path, data=json.dumps(value).encode(),
                                         headers={"Content-Type": "application/json", **auth}, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=3) as res:
                    return res.status, json.loads(res.read())
            except urllib.error.HTTPError as exc:
                return exc.code, json.loads(exc.read())
        try:
            value = body()
            status, created = request(PATH, value, headers(value))
            self.assertEqual(status, 201)
            self.assertEqual(created["data"]["version"], 1)
            status, rejected = request("/v1/economic-movements", value, headers(value))
            self.assertEqual(status, 405)
            self.assertEqual(rejected["error"]["code"], "METHOD_NOT_ALLOWED")
        finally:
            httpd.shutdown()
            httpd.server_close()


if __name__ == "__main__":
    unittest.main()
