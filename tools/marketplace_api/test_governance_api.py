"""Marketplace governance routes require signatures and preserve financial tables."""
import hashlib
import json
import threading
import time
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from unittest import mock

import server
from test_economic_api import MockEconomicProvider
from tools.discovery.agent_discovery import b58encode
from tools.organizations.signatures import read_message
from tools.organizations.test_organizations import ORG, KEYS, WALLETS, request as organization_request, signed as organization_signed
from tools.governance.signatures import mutation_message
from tools.governance.test_governance import rules


class GovernanceApiTests(unittest.TestCase):
    def setUp(self):
        self.provider = MockEconomicProvider()
        self.org = server.get_organization_store(self.provider)
        self.paper = server.get_paper_store(self.provider)
        body = organization_request()
        path, _, _, headers = organization_signed(body)
        server.organization_mutation_route("POST", path, self.provider, headers, body)
        self.gov = server.get_governance_store(self.provider)

    def tearDown(self):
        self.org.close(); self.paper.close(); self.provider.ledger.close()

    @staticmethod
    def headers(path, actor=0):
        at = int(time.time())
        return {"X-Signer-Pubkey": WALLETS[actor], "X-Timestamp": str(at),
                "X-Signature": b58encode(KEYS[actor].sign(read_message(path, WALLETS[actor], at)))}

    def fingerprint(self):
        names = ("economic_movements", "journal_entries", "ledger_entries", "agent_costs", "agent_reserves",
                 "reserve_transactions", "spending_proposals", "spending_decisions", "spending_budget_claims",
                 "spending_approvals", "spending_approval_events")
        result = {name: hashlib.sha256(repr([tuple(row) for row in self.provider.ledger._conn.execute(
            f"SELECT * FROM {name} ORDER BY rowid")]).encode()).hexdigest() for name in names}
        result["paper_simulation_runs"] = hashlib.sha256(repr([tuple(row) for row in self.paper.conn.execute(
            "SELECT * FROM paper_simulation_runs ORDER BY rowid")]).encode()).hexdigest()
        return result

    def test_signed_routes_and_financial_isolation(self):
        before = self.fingerprint()
        base = f"/v1/organizations/{ORG}/governance"
        with self.assertRaises(server.ApiError) as unsigned:
            server.route(base, self.provider)
        self.assertEqual(unsigned.exception.status, 401)
        self.assertEqual(server.route(base, self.provider, self.headers(base))[1]["data"]["governance_version"], 0)
        with self.assertRaises(server.ApiError) as outsider:
            server.route(base, self.provider, self.headers(base, 2))
        self.assertIn(outsider.exception.status, (403, 404))
        at = int(time.time())
        body = {"organization_id": ORG, "proposal_id": "", "actor_pubkey": WALLETS[0],
                "action": "CREATE_BYLAWS", "bylaws_version": 0, "bylaws_hash": "",
                "electorate_snapshot_hash": "", "payload": {"bylaws": rules()},
                "expected_version": 0, "issued_at": at, "expires_at": at+300,
                "nonce": "gov-api-nonce-1234", "idempotency_key": "gov-api-idem-1234"}
        action_path = base+"/actions"
        signed = {"X-Signer-Pubkey": WALLETS[0], "X-Timestamp": str(at),
                  "X-Signature": b58encode(KEYS[0].sign(mutation_message("POST", action_path, body)))}
        status, result = server.governance_mutation_route(action_path, self.provider, signed, body)
        self.assertEqual(status, 201)
        self.assertEqual(result["data"]["version"], 1)
        self.assertEqual(server.governance_mutation_route(action_path, self.provider, signed, body)[0], 200)
        with self.assertRaises(server.ApiError) as tampered:
            server.governance_mutation_route(action_path, self.provider, signed,
                {**body, "payload": {"bylaws": {**rules(), "quorum_bps": 9000}}})
        self.assertEqual(tampered.exception.status, 401)
        bylaws = server.route(base+"/bylaws", self.provider, self.headers(base+"/bylaws"))[1]["data"]
        self.assertEqual(len(bylaws), 1)
        self.assertEqual(before, self.fingerprint())
        self.assertIn('/v1/organizations/{organization_id}/governance/actions',
                      server.route('/openapi.json', self.provider)[1]['paths'])

    def test_proposal_vote_agreement_and_simulation_leave_ledger_unchanged(self):
        before = self.fingerprint()
        proposal_id = "gp_"+"e"*32
        policy_id = "gpol_"+"e"*32
        path = f"/v1/organizations/{ORG}/governance/actions"
        def action(name, payload, proposal="", proposal_scoped=False):
            gov, _ = self.gov._load(ORG, self.org._load(ORG)[1])
            bylaws = gov["bylaws"][-1] if gov["bylaws"] else None
            proposal_state = gov["proposals"].get(proposal) if proposal_scoped else None
            at = int(time.time())
            body = {"organization_id": ORG, "proposal_id": proposal, "actor_pubkey": WALLETS[0],
                    "action": name, "bylaws_version": proposal_state["bylaws_version"] if proposal_state else
                        bylaws["version"] if bylaws else 0,
                    "bylaws_hash": proposal_state["bylaws_hash"] if proposal_state else
                        bylaws["bylaws_hash"] if bylaws else "",
                    "electorate_snapshot_hash": proposal_state["electorate_snapshot_hash"] if proposal_state else "",
                    "payload": payload, "expected_version": gov["version"], "issued_at": at,
                    "expires_at": at+300, "nonce": f"api-gov-nonce-{gov['version']}-{name}",
                    "idempotency_key": f"api-gov-idem-{gov['version']}-{name}"}
            headers = {"X-Signer-Pubkey": WALLETS[0], "X-Timestamp": str(at),
                "X-Signature": b58encode(KEYS[0].sign(mutation_message("POST", path, body)))}
            return server.governance_mutation_route(path, self.provider, headers, body)[1]["data"]
        action("CREATE_BYLAWS", {"bylaws": rules()})
        policy = {"mint": WALLETS[4], "participant_shares_bps": {WALLETS[0]: 8000},
                  "reserve_share_bps": 2000, "cost_allocation_method": "DECLARATIVE_ONLY"}
        action("CREATE_PROPOSAL", {"proposal_type": "ECONOMIC_DISTRIBUTION_POLICY",
            "title": "Hypothetical agreement", "description": "No transfer",
            "proposal_payload": policy, "author_agent_account": None}, proposal_id)
        opened = action("OPEN_VOTING", {}, proposal_id)
        action("CAST_VOTE", {"choice": "YES"}, proposal_id, True)
        with mock.patch("tools.governance.store.time.time", return_value=opened["voting_starts_at"]+61):
            closed = action("CLOSE_VOTING", {}, proposal_id, True)
        with mock.patch("tools.governance.store.time.time", return_value=closed["resolved_at"]+61):
            adopted = action("ADOPT_DISTRIBUTION_POLICY", {"distribution_policy_id": policy_id}, proposal_id, True)
            simulated = action("SIMULATE_DISTRIBUTION", {"distribution_policy_id": policy_id,
                "hypothetical_pool": {"organization_id": ORG, "mint": WALLETS[4],
                    "amount_base_units": 1, "provenance": "SYNTHETIC_POOL"}, "assumptions": {}})
        self.assertFalse(adopted["is_executable"])
        self.assertTrue(simulated["is_simulation"])
        self.assertFalse(simulated["funds_transferred"])
        self.assertEqual(before, self.fingerprint())

    def test_http_dispatch_uses_governance_signature_domain(self):
        base = f"/v1/organizations/{ORG}/governance"
        at = int(time.time())
        body = {"organization_id": ORG, "proposal_id": "", "actor_pubkey": WALLETS[0],
                "action": "CREATE_BYLAWS", "bylaws_version": 0, "bylaws_hash": "",
                "electorate_snapshot_hash": "", "payload": {"bylaws": rules()},
                "expected_version": 0, "issued_at": at, "expires_at": at+300,
                "nonce": "gov-http-nonce-1234", "idempotency_key": "gov-http-idem-1234"}
        signature = b58encode(KEYS[0].sign(mutation_message("POST", base+"/actions", body)))
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.handler_for(self.provider))
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            root = f"http://127.0.0.1:{httpd.server_port}"
            request = urllib.request.Request(root+base+"/actions", data=json.dumps(body).encode(),
                headers={"Content-Type": "application/json", "X-Signer-Pubkey": WALLETS[0],
                         "X-Timestamp": str(at), "X-Signature": signature}, method="POST")
            with urllib.request.urlopen(request, timeout=3) as response:
                self.assertEqual(response.status, 201)
                self.assertEqual(json.loads(response.read())["data"]["version"], 1)
            with urllib.request.urlopen(urllib.request.Request(root+base,
                headers=self.headers(base)), timeout=3) as response:
                self.assertEqual(json.loads(response.read())["data"]["governance_version"], 1)
        finally:
            httpd.shutdown(); httpd.server_close()


if __name__ == "__main__": unittest.main()
