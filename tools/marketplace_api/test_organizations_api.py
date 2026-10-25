"""Signed organization API stays isolated from economic and paper databases."""
import copy
import hashlib
import json
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import server
from test_economic_api import MockEconomicProvider
from tools.discovery.agent_discovery import b58encode
from tools.organizations.signatures import read_message
from tools.organizations.signatures import digest
from tools.organizations.test_organizations import AGENT, KEYS, ORG, WALLETS, request, signed


class OrganizationApiTests(unittest.TestCase):
    def setUp(self):
        self.provider = MockEconomicProvider()
        self.provider.data["agents"].append({"agent_account": AGENT, "agent_id": "11"*32,
            "owner": WALLETS[2], "protocol_config": self.provider.data["protocol_config"],
            "capabilities": 1, "active": True, "status": "Active"})
        self.store = server.get_organization_store(self.provider)
        self.paper_store = server.get_paper_store(self.provider)

    def tearDown(self):
        self.store.close()
        self.paper_store.close()
        self.provider.ledger.close()

    @staticmethod
    def read_headers(path, actor=0):
        ts = int(time.time())
        return {"X-Signer-Pubkey": WALLETS[actor], "X-Timestamp": str(ts),
            "X-Signature": b58encode(KEYS[actor].sign(read_message(path, WALLETS[actor], ts)))}

    def write(self, action="CREATE", actor=0, target_type="ORGANIZATION", target_id=ORG,
              payload=None, body=None):
        state = self.store._load(ORG)[0]
        version = state["organization"]["version"] if state else 0
        body = body or request(action, actor, version, target_type, target_id, payload)
        path, _, _, headers = signed(body, actor)
        return server.organization_mutation_route("POST", path, self.provider, headers, body), body, headers

    def fingerprint(self):
        tables = ("economic_movements", "journal_entries", "ledger_entries", "agent_costs",
            "agent_reserves", "reserve_transactions", "spending_proposals", "spending_decisions",
            "spending_budget_claims", "spending_approvals", "spending_approval_events")
        result = {table: hashlib.sha256(repr([tuple(row) for row in self.provider.ledger._conn.execute(
            f"SELECT * FROM {table} ORDER BY rowid")]).encode()).hexdigest() for table in tables}
        result["paper_simulation_runs"] = hashlib.sha256(repr([tuple(row) for row in
            self.paper_store.conn.execute("SELECT * FROM paper_simulation_runs ORDER BY rowid")]).encode()).hexdigest()
        return result

    def test_create_read_members_agents_roles_audit_and_financial_isolation(self):
        before = self.fingerprint()
        with self.assertRaises(server.ApiError) as unsigned:
            server.route('/v1/organizations', self.provider)
        self.assertEqual(unsigned.exception.status, 401)
        status, response = self.write()[0]
        self.assertEqual(status, 201)
        self.assertFalse(response["data"]["is_financial_authority"])
        path = f'/v1/organizations/{ORG}'
        self.assertEqual(server.route(path, self.provider, self.read_headers(path))[1]["data"]["organization"]["owner_pubkey"], WALLETS[0])
        with self.assertRaises(server.ApiError) as private:
            server.route(path, self.provider, self.read_headers(path, 3))
        self.assertEqual(private.exception.status, 404)
        inv = "inv_"+"1"*32
        now = int(time.time())
        self.write("INVITE_HUMAN", target_type="INVITATION", target_id=inv,
            payload={"subject_pubkey": WALLETS[1], "role_id": "ADMIN", "valid_from": now,
                     "expires_at": now+1000})
        self.write("ACCEPT_HUMAN", actor=1, target_type="INVITATION", target_id=inv)
        with self.assertRaises(server.ApiError):
            self.write("ASSIGN_ROLE", actor=1, target_type="MEMBER", target_id=WALLETS[1],
                       payload={"role_id": "OWNER"})
        agent_path = f'/v1/organizations/agent-registration/{AGENT}'
        registration = server.route(agent_path, self.provider, self.read_headers(agent_path))[1]["data"]
        self.assertEqual(registration["agent_owner_pubkey"], WALLETS[2])
        agent_inv = "inv_"+"2"*32
        self.write("INVITE_AGENT", target_type="INVITATION", target_id=agent_inv,
            payload={"agent_account": AGENT, "registration": registration,
                     "valid_from": now, "expires_at": now+1000})
        consent = {"agent_account": AGENT, "registration_snapshot_hash": digest(registration)}
        with self.assertRaises(server.ApiError):
            self.write("ACCEPT_AGENT", actor=3, target_type="INVITATION", target_id=agent_inv, payload=consent)
        self.write("ACCEPT_AGENT", actor=2, target_type="INVITATION", target_id=agent_inv, payload=consent)
        agent_list_path = f'/v1/organizations/{ORG}/agents'
        result = server.route(agent_list_path, self.provider, self.read_headers(agent_list_path))[1]["data"]
        self.assertEqual(result[0]["effective_status"], "ACTIVE")
        self.provider.data["agents"][-1]["owner"] = WALLETS[3]
        result = server.route(agent_list_path, self.provider, self.read_headers(agent_list_path))[1]["data"]
        self.assertEqual(result[0]["effective_status"], "REVIEW_REQUIRED")
        audit_path = f'/v1/organizations/{ORG}/audit-events'
        self.assertEqual(len(server.route(audit_path, self.provider, self.read_headers(audit_path))[1]["data"]), 5)
        self.assertEqual(before, self.fingerprint())
        self.assertIn('/v1/organizations/{organization_id}/actions', server.route('/openapi.json', self.provider)[1]['paths'])

    def test_mutation_tamper_version_replay_and_http_write_boundary(self):
        self.write()
        state = self.store._load(ORG)[0]
        body = request("UPDATE_METADATA", version=state["organization"]["version"],
                       payload={"description": "changed"})
        path, _, _, headers = signed(body)
        with self.assertRaises(server.ApiError) as altered:
            server.organization_mutation_route("POST", path, self.provider, headers,
                {**body, "payload": {"description": "tampered"}})
        self.assertEqual(altered.exception.status, 401)
        self.assertEqual(self.write(body=body)[0][0], 201)
        self.assertEqual(self.write(body=body)[0][0], 200)
        with self.assertRaises(server.ApiError) as conflict:
            self.write(body={**body, "nonce": "different-nonce-123456", "payload": {"description": "other"}})
        self.assertEqual(conflict.exception.status, 409)
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.handler_for(self.provider))
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{httpd.server_port}"
        try:
            read_path = f'/v1/organizations/{ORG}'
            with urllib.request.urlopen(urllib.request.Request(base+read_path,
                headers=self.read_headers(read_path)), timeout=3) as result:
                self.assertEqual(result.status, 200)
            next_body = request("UPDATE_METADATA", version=2, payload={"description": "via HTTP"},
                                nonce="http-org-nonce-123456")
            next_body["idempotency_key"] = "http-org-idem-123456"
            action_path, _, _, signed_headers = signed(next_body)
            mutation = urllib.request.Request(base+action_path, data=json.dumps(next_body).encode(),
                headers={"Content-Type": "application/json", **signed_headers}, method="POST")
            with urllib.request.urlopen(mutation, timeout=3) as result:
                self.assertEqual(result.status, 201)
                self.assertEqual(json.loads(result.read())["data"]["description"], "via HTTP")
            request_http = urllib.request.Request(base+'/v1/economic-movements', data=b'{}', method='POST')
            with self.assertRaises(urllib.error.HTTPError) as denied:
                urllib.request.urlopen(request_http, timeout=3)
            self.assertEqual(denied.exception.code, 405)
            denied.exception.close()
        finally:
            httpd.shutdown(); httpd.server_close()


if __name__ == '__main__': unittest.main()
