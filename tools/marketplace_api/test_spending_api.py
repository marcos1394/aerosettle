"""CON-28 authenticated advisory evaluation API and closed accounting routes."""
import copy
import json
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest import mock

from cryptography.hazmat.primitives.asymmetric import ed25519
import server
from test_economic_api import DRONE, OWNER_DRONE, OWNER_DRONE_SECRET, MockEconomicProvider
from tools.economic_ledger.auth import create_auth_headers
from tools.economic_ledger.spending_decisions import evaluation_message
from tools.economic_ledger.test_budget_policies import OTHER, OTHER_SECRET, body as policy_body
from tools.economic_ledger.test_spending_decisions import proposal
from tools.discovery.agent_discovery import b58encode

PATH = f"/v1/agents/{DRONE}/spending-evaluations"


class SpendingApiTests(unittest.TestCase):
    def setUp(self):
        self.provider = MockEconomicProvider()
        policies = server.get_policy_store(self.provider)
        policies.mutate(self.provider.snapshot()["agents"][0], "CREATE", policy_body(), OWNER_DRONE)
        self.policy = policies.mutate(self.provider.snapshot()["agents"][0], "ACTIVATE",
                                      policy_body("ACTIVATE", 1, "00000002"), OWNER_DRONE)[0]

    def tearDown(self):
        self.provider.ledger.close()

    @staticmethod
    def signed(value, secret=OWNER_DRONE_SECRET, signer=OWNER_DRONE):
        ts = int(time.time())
        signature = ed25519.Ed25519PrivateKey.from_private_bytes(secret).sign(
            evaluation_message(ts, DRONE, signer, "POST", PATH, value))
        return {"X-Signer-Pubkey": signer, "X-Timestamp": str(ts), "X-Signature": b58encode(signature)}

    def test_signed_evaluation_history_and_closed_general_writes(self):
        value = proposal(self.policy)
        with self.assertRaises(server.ApiError) as unsigned:
            server.spending_evaluation_route("POST", PATH, self.provider, {}, value)
        self.assertEqual(unsigned.exception.status, 401)
        with self.assertRaises(server.ApiError) as tampered:
            server.spending_evaluation_route("POST", PATH, self.provider,
                                             self.signed(value), {**value, "purpose": "tampered"})
        self.assertEqual(tampered.exception.status, 401)
        status, created = server.spending_evaluation_route("POST", PATH, self.provider, self.signed(value), value)
        self.assertEqual(status, 201)
        self.assertEqual(created["data"]["decision"], "REQUIRE_APPROVAL")
        self.assertFalse(created["data"]["is_executable"])
        status, retry = server.spending_evaluation_route("POST", PATH, self.provider, self.signed(value), value)
        self.assertEqual(status, 200)
        self.assertEqual(retry["data"]["decision_id"], created["data"]["decision_id"])
        auth = create_auth_headers(OWNER_DRONE_SECRET, DRONE)
        _, history = server.route(PATH, self.provider, auth)
        self.assertEqual(len(history["data"]), 1)
        _, detail = server.route(PATH + "/" + created["data"]["decision_id"], self.provider, auth)
        self.assertTrue(detail["data"]["historical"])
        with self.assertRaises(server.ApiError) as private:
            server.route(PATH, self.provider)
        self.assertEqual(private.exception.status, 401)
        for path in ("/v1/economic-movements", "/v1/reserves", "/v1/costs"):
            with self.assertRaises(server.ApiError) as blocked:
                server.spending_evaluation_route("POST", path, self.provider, self.signed(value), value)
            self.assertEqual(blocked.exception.status, 405)

    def test_owner_change_closes_history_and_old_idempotency(self):
        value = proposal(self.policy)
        _, created = server.spending_evaluation_route("POST", PATH, self.provider, self.signed(value), value)
        old_id = created["data"]["decision_id"]
        original = self.provider.snapshot
        def rotated():
            snapshot = copy.deepcopy(original())
            snapshot["agents"][0]["owner"] = OTHER
            return snapshot
        with mock.patch.object(self.provider, "snapshot", side_effect=rotated):
            with self.assertRaises(server.ApiError):
                server.route(PATH + "/" + old_id, self.provider, create_auth_headers(OWNER_DRONE_SECRET, DRONE))
            with self.assertRaises(server.ApiError) as denied:
                server.spending_evaluation_route("POST", PATH, self.provider, self.signed(value), value)
            self.assertEqual(denied.exception.status, 403)
            self.assertNotIn(old_id, str(denied.exception))

    def test_current_device_authority_can_request_advice_without_payment_rights(self):
        self.provider.data["agents"][0]["signing_authority"] = OTHER
        value = proposal(self.policy, requester=OTHER, suffix="00000003")
        status, result = server.spending_evaluation_route(
            "POST", PATH, self.provider, self.signed(value, OTHER_SECRET, OTHER), value)
        self.assertEqual(status, 201)
        self.assertEqual(result["data"]["decision"], "REQUIRE_APPROVAL")
        self.assertFalse(result["data"]["is_executable"])
        _, history = server.route(PATH, self.provider, create_auth_headers(OTHER_SECRET, DRONE))
        self.assertEqual(len(history["data"]), 1)
        self.provider.data["agents"][0]["signing_authority"] = OWNER_DRONE
        with self.assertRaises(server.ApiError) as rotated:
            server.route(PATH, self.provider, create_auth_headers(OTHER_SECRET, DRONE))
        self.assertEqual(rotated.exception.status, 403)

    def test_http_post_and_get(self):
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.handler_for(self.provider))
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        root = f"http://127.0.0.1:{httpd.server_port}"
        try:
            value = proposal(self.policy)
            req = urllib.request.Request(root + PATH, data=json.dumps(value).encode(),
                headers={"Content-Type": "application/json", **self.signed(value)}, method="POST")
            with urllib.request.urlopen(req, timeout=3) as response:
                self.assertEqual(response.status, 201)
                self.assertEqual(json.loads(response.read())["data"]["decision"], "REQUIRE_APPROVAL")
            req = urllib.request.Request(root + PATH, headers=create_auth_headers(OWNER_DRONE_SECRET, DRONE))
            with urllib.request.urlopen(req, timeout=3) as response:
                self.assertEqual(len(json.loads(response.read())["data"]), 1)
            req = urllib.request.Request(root + "/v1/reserves", data=b"{}", method="POST")
            with self.assertRaises(urllib.error.HTTPError) as denied:
                urllib.request.urlopen(req, timeout=3)
            self.assertEqual(denied.exception.code, 405)
            denied.exception.close()
        finally:
            httpd.shutdown()
            httpd.server_close()


if __name__ == "__main__":
    unittest.main()
