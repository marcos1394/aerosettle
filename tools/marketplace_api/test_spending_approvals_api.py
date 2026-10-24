"""CON-29 private owner consent routes and signed HTTP mutation boundaries."""
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
from tools.discovery.agent_discovery import b58encode
from tools.economic_ledger.auth import create_auth_headers
from tools.economic_ledger.spending_approvals import CONTEXT_FIELDS, canonical_approval_message
from tools.economic_ledger.spending_decisions import evaluation_message
from tools.economic_ledger.test_budget_policies import OTHER, OTHER_SECRET, body as policy_body
from tools.economic_ledger.test_spending_decisions import proposal

BASE = f"/v1/agents/{DRONE}/spending-approvals"
DECISIONS = f"/v1/agents/{DRONE}/spending-evaluations"


class SpendingApprovalApiTests(unittest.TestCase):
    def setUp(self):
        self.provider = MockEconomicProvider()
        policies = server.get_policy_store(self.provider)
        agent = self.provider.snapshot()["agents"][0]
        policies.mutate(agent, "CREATE", policy_body(), OWNER_DRONE)
        self.policy = policies.mutate(agent, "ACTIVATE", policy_body("ACTIVATE", 1, "00000002"), OWNER_DRONE)[0]
        value = proposal(self.policy)
        ts = int(time.time())
        signature = b58encode(ed25519.Ed25519PrivateKey.from_private_bytes(OWNER_DRONE_SECRET).sign(
            evaluation_message(ts, DRONE, OWNER_DRONE, "POST", DECISIONS, value)))
        _, response = server.spending_evaluation_route("POST", DECISIONS, self.provider,
            {"X-Signer-Pubkey": OWNER_DRONE, "X-Timestamp": str(ts), "X-Signature": signature}, value)
        self.decision = response["data"]
        self.auth = create_auth_headers(OWNER_DRONE_SECRET, DRONE)
        _, context_response = server.route(BASE + "/context/" + self.decision["decision_id"], self.provider, self.auth)
        self.context = context_response["data"]

    def tearDown(self):
        self.provider.ledger.close()

    def body(self, action, suffix, expiry=None, reason=""):
        return {**{key: self.context[key] for key in CONTEXT_FIELDS}, "action": action,
                "issued_at": int(time.time()),
                "expires_at": expiry if expiry is not None else min(self.decision["expires_at"], int(time.time()) + 120),
                "nonce": f"api-approval-nonce-{suffix}-unique",
                "idempotency_key": f"api-approval-idem-{suffix}", "reason": reason}

    @staticmethod
    def signed(path, body, secret=OWNER_DRONE_SECRET, signer=OWNER_DRONE):
        signature = ed25519.Ed25519PrivateKey.from_private_bytes(secret).sign(
            canonical_approval_message(body["issued_at"], DRONE, signer, "POST", path, body))
        return {"X-Signer-Pubkey": signer, "X-Timestamp": str(body["issued_at"]),
                "X-Signature": b58encode(signature)}

    def test_private_context_owner_only_mutations_and_history(self):
        self.assertEqual(self.context["proposal"]["purpose"], "Fuel")
        with self.assertRaises(server.ApiError) as unsigned:
            server.route(BASE, self.provider)
        self.assertEqual(unsigned.exception.status, 401)
        self.provider.data["agents"][0]["signing_authority"] = OTHER
        with self.assertRaises(server.ApiError) as device_read:
            server.route(BASE, self.provider, create_auth_headers(OTHER_SECRET, DRONE))
        self.assertEqual(device_read.exception.status, 403)
        opening = self.body("OPEN", "open")
        with self.assertRaises(server.ApiError) as device_write:
            server.spending_approval_route("POST", BASE, self.provider,
                self.signed(BASE, opening, OTHER_SECRET, OTHER), opening)
        self.assertEqual(device_write.exception.status, 403)
        status, created = server.spending_approval_route("POST", BASE, self.provider,
            self.signed(BASE, opening), opening)
        self.assertEqual(status, 201)
        aid = created["data"]["approval_id"]
        approve_path = BASE + "/" + aid + "/approve"
        approving = self.body("APPROVE", "approve", created["data"]["expires_at"])
        with self.assertRaises(server.ApiError) as altered:
            server.spending_approval_route("POST", approve_path, self.provider,
                self.signed(approve_path, approving), {**approving, "amount_base_units_str": "999"})
        self.assertEqual(altered.exception.status, 401)
        status, approved = server.spending_approval_route("POST", approve_path, self.provider,
            self.signed(approve_path, approving), approving)
        self.assertEqual(status, 200)
        self.assertEqual(approved["data"]["approval_status"], "APPROVED")
        self.assertFalse(approved["data"]["is_currently_applicable"])
        self.assertFalse(approved["data"]["is_executable"])
        _, listed = server.route(BASE, self.provider, self.auth)
        _, detail = server.route(BASE + "/" + aid, self.provider, self.auth)
        _, history = server.route(BASE + "/" + aid + "/history", self.provider, self.auth)
        self.assertEqual(len(listed["data"]), 1)
        self.assertEqual(detail["data"]["approval_status"], "APPROVED")
        self.assertEqual([event["action"] for event in history["data"]], ["OPEN", "APPROVE"])
        with self.assertRaises(server.ApiError):
            server.spending_approval_route("POST", BASE + "/" + aid + "/revoke", self.provider,
                self.signed(approve_path, approving), approving)
        revoking = self.body("REVOKE", "revoke", created["data"]["expires_at"], "Withdrawn")
        _, revoked = server.spending_approval_route("POST", BASE + "/" + aid + "/revoke", self.provider,
            self.signed(BASE + "/" + aid + "/revoke", revoking), revoking)
        self.assertEqual(revoked["data"]["approval_status"], "REVOKED")

    def test_identity_rotation_blocks_old_owner_and_history(self):
        opening = self.body("OPEN", "open")
        server.spending_approval_route("POST", BASE, self.provider, self.signed(BASE, opening), opening)
        original = self.provider.snapshot
        def rotated():
            snapshot = copy.deepcopy(original())
            snapshot["agents"][0]["owner"] = OTHER
            return snapshot
        with mock.patch.object(self.provider, "snapshot", side_effect=rotated):
            with self.assertRaises(server.ApiError):
                server.route(BASE, self.provider, self.auth)
            with self.assertRaises(server.ApiError) as denied:
                server.spending_approval_route("POST", BASE, self.provider, self.signed(BASE, opening), opening)
            self.assertEqual(denied.exception.status, 403)

    def test_http_post_get_and_closed_financial_writes(self):
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.handler_for(self.provider))
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        root = f"http://127.0.0.1:{httpd.server_port}"
        try:
            opening = self.body("OPEN", "http")
            req = urllib.request.Request(root + BASE, data=json.dumps(opening).encode(),
                headers={"Content-Type": "application/json", **self.signed(BASE, opening)}, method="POST")
            with urllib.request.urlopen(req, timeout=3) as response:
                self.assertEqual(response.status, 201)
                aid = json.loads(response.read())["data"]["approval_id"]
            req = urllib.request.Request(root + BASE + "/" + aid + "/history", headers=self.auth)
            with urllib.request.urlopen(req, timeout=3) as response:
                self.assertEqual(len(json.loads(response.read())["data"]), 1)
            req = urllib.request.Request(root + "/v1/economic-movements", data=b"{}", method="POST")
            with self.assertRaises(urllib.error.HTTPError) as denied:
                urllib.request.urlopen(req, timeout=3)
            self.assertEqual(denied.exception.code, 405)
            denied.exception.close()
        finally:
            httpd.shutdown()
            httpd.server_close()


if __name__ == "__main__":
    unittest.main()
