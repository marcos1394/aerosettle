"""Signed governance lifecycle, integrity, quorum and financial isolation checks."""
import copy
import sqlite3
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from tools.discovery.agent_discovery import b58encode
from tools.organizations.signatures import OrganizationError, digest, mutation_message as organization_message
from tools.organizations.store import OrganizationStore
from tools.organizations.test_organizations import ORG, KEYS, WALLETS, request as org_request, signed as org_signed
from tools.governance.engine import (GovernanceRuleError, evaluate_governance_proposal,
    simulate_organization_distribution, validate_bylaws, validate_distribution_policy)
from tools.governance.signatures import GovernanceError, mutation_message, verify_mutation
from tools.governance.store import GovernanceStore

PID = "gp_"+"a"*32
POLICY = "gpol_"+"b"*32


def rules(period=60, quorum=5000):
    return {"title": "Collective charter", "purpose": "Administrative decisions only",
            "eligible_voter_roles": ["OWNER", "MEMBER"], "proposal_roles": ["OWNER", "MEMBER"],
            "proposal_permissions": ["BYLAWS_AMENDMENT", "MEMBERSHIP_RULE_CHANGE", "OPERATIONAL_POLICY",
                "RESOURCE_ALLOCATION_PROPOSAL", "ECONOMIC_DISTRIBUTION_POLICY",
                "RESERVE_POLICY_PROPOSAL", "DISPUTE_RESOLUTION", "OTHER_NON_FINANCIAL"],
            "distribution_policy_id": None,
            "quorum_bps": quorum, "approval_threshold_bps": 5001,
            "voting_period_seconds": period, "minimum_voting_period_seconds": 60,
            "dispute_window_seconds": 60, "vote_weighting_rule": "ONE_ELIGIBLE_WALLET_ONE_VOTE"}


class GovernanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)/"organizations.sqlite"
        self.org = OrganizationStore(self.path)
        self.change_org()
        self.gov = GovernanceStore(self.org)

    def tearDown(self):
        self.org.close()
        self.tmp.cleanup()

    def change_org(self, action="CREATE", actor=0, target_type="ORGANIZATION", target_id=ORG, payload=None):
        state, _ = self.org._load(ORG)
        body = org_request(action, actor, state["organization"]["version"] if state else 0,
                           target_type, target_id, payload)
        _, message, signature, _ = org_signed(body, actor)
        return self.org.mutate(body, signature, message, WALLETS[actor])[0]

    def add_member(self, actor=1, role="MEMBER"):
        ident = "inv_"+format(actor, "032x")
        now = int(time.time())
        self.change_org("INVITE_HUMAN", target_type="INVITATION", target_id=ident,
            payload={"subject_pubkey": WALLETS[actor], "role_id": role,
                     "valid_from": now, "expires_at": now+1000})
        self.change_org("ACCEPT_HUMAN", actor, "INVITATION", ident)

    def body(self, action, actor=0, proposal_id="", payload=None, version=None, signed_proposal=False):
        state, _ = self.gov._load(ORG, self.org._load(ORG)[1])
        current = state["bylaws"][-1] if state["bylaws"] else None
        proposal = state["proposals"].get(proposal_id) if signed_proposal else None
        now = int(time.time())
        return {"organization_id": ORG, "proposal_id": proposal_id, "actor_pubkey": WALLETS[actor],
            "action": action, "bylaws_version": proposal["bylaws_version"] if proposal else
                current["version"] if current else 0,
            "bylaws_hash": proposal["bylaws_hash"] if proposal else current["bylaws_hash"] if current else "",
            "electorate_snapshot_hash": proposal["electorate_snapshot_hash"] if proposal else "",
            "payload": payload if payload is not None else {}, "expected_version": state["version"] if version is None else version,
            "issued_at": now, "expires_at": now+300,
            "nonce": f"gov-nonce-{now}-{state['version']}-{action}-{actor}",
            "idempotency_key": f"gov-idem-{now}-{state['version']}-{action}-{actor}"}

    def change(self, action, actor=0, proposal_id="", payload=None, body=None, signed_proposal=False):
        body = body or self.body(action, actor, proposal_id, payload, signed_proposal=signed_proposal)
        path = f"/v1/organizations/{ORG}/governance/actions"
        message = mutation_message("POST", path, body)
        signature = b58encode(KEYS[actor].sign(message))
        headers = {"X-Signer-Pubkey": WALLETS[actor], "X-Timestamp": str(body["issued_at"]),
                   "X-Signature": signature}
        verify_mutation(path, body, headers)
        return self.gov.mutate(body, signature, message, WALLETS[actor]), body, headers

    def charter(self, quorum=5000):
        return self.change("CREATE_BYLAWS", payload={"bylaws": rules(quorum=quorum)})

    def proposal(self, kind="OTHER_NON_FINANCIAL", value=None):
        return self.change("CREATE_PROPOSAL", proposal_id=PID,
            payload={"proposal_type": kind, "title": "Proposal", "description": "Recorded only",
                     "proposal_payload": value or {}, "author_agent_account": None})

    def test_initial_bylaws_signature_and_replay(self):
        body = self.body("CREATE_BYLAWS", payload={"bylaws": rules()})
        path = f"/v1/organizations/{ORG}/governance/actions"
        message = mutation_message("POST", path, body)
        headers = {"X-Signer-Pubkey": WALLETS[0], "X-Timestamp": str(body["issued_at"]),
                   "X-Signature": b58encode(KEYS[0].sign(message))}
        self.assertEqual(verify_mutation(path, body, headers)[0], WALLETS[0])
        with self.assertRaises(OrganizationError): verify_mutation(path+"/wrong", body, headers)
        altered = copy.deepcopy(body)
        altered["payload"]["bylaws"]["quorum_bps"] = 9000
        with self.assertRaises(OrganizationError): verify_mutation(path, altered, headers)
        self.gov.mutate(body, headers["X-Signature"], message, WALLETS[0])
        same, created = self.gov.mutate(body, headers["X-Signature"], message, WALLETS[0])
        self.assertFalse(created)
        self.assertEqual(same["version"], 1)
        self.assertEqual(len(self.gov.read(ORG, WALLETS[0], "bylaws")), 1)
        self.org.close()
        self.org = OrganizationStore(self.path)
        self.gov = GovernanceStore(self.org)
        self.assertEqual(len(self.gov.read(ORG, WALLETS[0], "audit-events")), 1)

    def test_voting_snapshot_current_identity_and_quorum(self):
        self.add_member()
        self.charter()
        self.proposal()
        self.change("OPEN_VOTING", proposal_id=PID)
        first = self.gov.read(ORG, WALLETS[0], "proposal", PID)
        self.assertEqual(first["electorate"], {WALLETS[0]: 1, WALLETS[1]: 1})
        vote, body, _ = self.change("CAST_VOTE", actor=1, proposal_id=PID,
                                   payload={"choice": "YES"}, signed_proposal=True)
        self.assertEqual(vote[0]["status"], "OPEN")
        with self.assertRaises(GovernanceError):
            self.change("CAST_VOTE", actor=1, proposal_id=PID, payload={"choice": "NO"}, signed_proposal=True)
        with self.assertRaises(GovernanceError):
            self.change("CAST_VOTE", actor=2, proposal_id=PID, payload={"choice": "YES"}, signed_proposal=True)
        self.change_org("SUSPEND_MEMBER", target_type="MEMBER", target_id=WALLETS[1])
        with self.assertRaises(GovernanceError):
            self.change("CAST_VOTE", actor=1, proposal_id=PID, payload={"choice": "YES"}, signed_proposal=True)
        # Already committed votes are historical; suspension prevents new authority.
        close_body = self.body("CLOSE_VOTING", proposal_id=PID, signed_proposal=True)
        close_body["issued_at"] += 61
        close_body["expires_at"] += 61
        with mock.patch("tools.governance.store.time.time", return_value=close_body["issued_at"]):
            result, _, _ = self.change("CLOSE_VOTING", proposal_id=PID, body=close_body)
        self.assertEqual(result[0]["status"], "ACCEPTED")
        self.assertFalse(result[0]["is_executable"])
        self.assertEqual(result[0]["tally"]["yes_weight"], 1)
        self.assertTrue(result[0]["tally"]["quorum_met"])

    def test_quorum_exact_tie_abstention_and_empty(self):
        bylaws = validate_bylaws(rules(quorum=5000))
        proposal = {"proposal_id": PID}
        voters = {WALLETS[0]: 1, WALLETS[1]: 1}
        yes = {WALLETS[0]: {"choice": "YES"}}
        self.assertEqual(evaluate_governance_proposal(proposal, bylaws, voters, yes, 0)["outcome"], "ACCEPTED")
        bylaws["quorum_bps"] = 5001
        self.assertEqual(evaluate_governance_proposal(proposal, bylaws, voters, yes, 0)["outcome"], "REJECTED")
        bylaws["quorum_bps"] = 5000
        tie = {**yes, WALLETS[1]: {"choice": "NO"}}
        self.assertEqual(evaluate_governance_proposal(proposal, bylaws, voters, tie, 0)["outcome"], "REJECTED")
        abstain = {WALLETS[0]: {"choice": "ABSTAIN"}}
        self.assertEqual(evaluate_governance_proposal(proposal, bylaws, voters, abstain, 0)["participating_weight"], 1)
        self.assertEqual(evaluate_governance_proposal(proposal, bylaws, {}, {}, 0)["outcome"], "REJECTED")
        for invalid in (0, 10001, True):
            bad = rules(); bad["quorum_bps"] = invalid
            with self.assertRaises(GovernanceRuleError): validate_bylaws(bad)

    def test_policy_distribution_integer_and_rejections(self):
        policy = {"organization_id": ORG, "distribution_policy_id": POLICY, "mint": WALLETS[4],
                  "participant_shares_bps": {WALLETS[0]: 5000, WALLETS[1]: 3000},
                  "reserve_share_bps": 2000, "cost_allocation_method": "DECLARATIVE_ONLY",
                  "is_executable": False}
        value = {"organization_id": ORG, "mint": WALLETS[4], "amount_base_units": 1,
                 "provenance": "SYNTHETIC_POOL"}
        result = simulate_organization_distribution(value, policy)
        self.assertEqual(result["reserve_base_units"], 1)
        self.assertEqual(sum(result["participant_allocations_base_units"].values())+result["reserve_base_units"], 1)
        self.assertFalse(result["funds_transferred"])
        for bad in ({**value, "provenance": "LIVE_RPC"}, {**value, "mint": WALLETS[3]},
                    {**value, "organization_id": "org_"+"b"*32}):
            with self.assertRaises(GovernanceRuleError): simulate_organization_distribution(bad, policy)
        with self.assertRaises(GovernanceRuleError): validate_distribution_policy({
            "mint": WALLETS[4], "participant_shares_bps": {WALLETS[0]: 9000},
            "reserve_share_bps": 2000, "cost_allocation_method": "DECLARATIVE_ONLY"})

    def test_audit_tampering_truncation_and_cross_org(self):
        self.charter()
        self.proposal()
        with self.assertRaises(OrganizationError): self.gov.read(ORG, WALLETS[2], "proposals")
        with self.assertRaises(sqlite3.DatabaseError):
            self.org.conn.execute("DELETE FROM governance_events WHERE organization_id=?", (ORG,))
        self.org.conn.execute("DROP TRIGGER immutable_governance_events_update")
        self.org.conn.execute("UPDATE governance_events SET action='CAST_VOTE' WHERE version=1")
        with self.assertRaises(GovernanceError): self.gov.read(ORG, WALLETS[0], "proposals")

    def test_distribution_agreement_requires_final_vote_and_stays_hypothetical(self):
        self.charter()
        policy = {"mint": WALLETS[4], "participant_shares_bps": {WALLETS[0]: 8000},
                  "reserve_share_bps": 2000, "cost_allocation_method": "DECLARATIVE_ONLY"}
        self.proposal("ECONOMIC_DISTRIBUTION_POLICY", policy)
        self.change("OPEN_VOTING", proposal_id=PID)
        self.change("CAST_VOTE", proposal_id=PID, payload={"choice": "YES"}, signed_proposal=True)
        with self.assertRaises(GovernanceError):
            self.change("ADOPT_DISTRIBUTION_POLICY", proposal_id=PID,
                        payload={"distribution_policy_id": POLICY}, signed_proposal=True)
        opened = self.gov.read(ORG, WALLETS[0], "proposal", PID)["voting_starts_at"]
        with mock.patch("tools.governance.store.time.time", return_value=opened+61):
            self.change("CLOSE_VOTING", proposal_id=PID, signed_proposal=True)
        closed = self.gov.read(ORG, WALLETS[0], "proposal", PID)["resolved_at"]
        with mock.patch("tools.governance.store.time.time", return_value=closed+61):
            adopted, _, _ = self.change("ADOPT_DISTRIBUTION_POLICY", proposal_id=PID,
                payload={"distribution_policy_id": POLICY}, signed_proposal=True)
            self.assertFalse(adopted[0]["is_executable"])
            simulated, _, _ = self.change("SIMULATE_DISTRIBUTION", payload={
                "distribution_policy_id": POLICY,
                "hypothetical_pool": {"organization_id": ORG, "mint": WALLETS[4],
                    "amount_base_units": 1, "provenance": "SYNTHETIC_POOL"}, "assumptions": {}})
        self.assertEqual(simulated[0]["reserve_base_units"], 1)
        self.assertFalse(simulated[0]["funds_transferred"])
        self.assertEqual(len(self.gov.read(ORG, WALLETS[0], "distributions")["policies"]), 1)

    def test_dispute_recusal_and_historical_tally_remain_intact(self):
        self.add_member()
        self.charter()
        self.proposal()
        self.change("OPEN_VOTING", proposal_id=PID)
        self.change("CAST_VOTE", actor=1, proposal_id=PID, payload={"choice": "YES"}, signed_proposal=True)
        opened = self.gov.read(ORG, WALLETS[0], "proposal", PID)["voting_starts_at"]
        with mock.patch("tools.governance.store.time.time", return_value=opened+61):
            self.change("CLOSE_VOTING", proposal_id=PID, signed_proposal=True)
            dispute_id = "gd_"+"a"*32
            opened_dispute, _, _ = self.change("OPEN_DISPUTE", actor=1, proposal_id=PID,
                payload={"dispute_id": dispute_id, "reason_code": "EVIDENCE",
                         "evidence_refs": ["sha256:case-1"]}, signed_proposal=True)
            self.assertEqual(opened_dispute[0]["evidence_refs"], ["sha256:case-1"])
            with self.assertRaises(GovernanceError):
                self.change("RESOLVE_DISPUTE", proposal_id=PID,
                    payload={"dispute_id": dispute_id, "resolution": "UPHOLD"}, signed_proposal=True)
            self.change("RESOLVE_DISPUTE", proposal_id=PID,
                payload={"dispute_id": dispute_id, "resolution": "REFER_EXTERNAL"}, signed_proposal=True)
        result = self.gov.read(ORG, WALLETS[0], "proposal", PID)
        self.assertEqual(result["status"], "ACCEPTED")
        self.assertEqual(result["tally"]["yes_weight"], 1)
        self.assertEqual(result["resolution_status"], "EXTERNAL_REVIEW")

    def test_ten_concurrent_identical_retries_create_one_event(self):
        body = self.body("CREATE_BYLAWS", payload={"bylaws": rules()})
        path = f"/v1/organizations/{ORG}/governance/actions"
        message = mutation_message("POST", path, body)
        signature = b58encode(KEYS[0].sign(message))
        def retry(_):
            return self.gov.mutate(body, signature, message, WALLETS[0])[1]
        with ThreadPoolExecutor(max_workers=10) as pool:
            created = list(pool.map(retry, range(10)))
        self.assertEqual(sum(created), 1)
        self.assertEqual(len(self.gov.read(ORG, WALLETS[0], "audit-events")), 1)

    def test_truncated_history_is_detected(self):
        self.charter(); self.proposal()
        self.org.conn.execute("DROP TRIGGER immutable_governance_events_delete")
        self.org.conn.execute("DELETE FROM governance_events WHERE version=2")
        with self.assertRaises(GovernanceError): self.gov.read(ORG, WALLETS[0], "proposals")

    def test_amendment_cannot_rewrite_open_proposal_rules(self):
        self.charter()
        amended = rules(quorum=10000)
        self.proposal("BYLAWS_AMENDMENT", amended)
        self.change("OPEN_VOTING", proposal_id=PID)
        self.change("CAST_VOTE", proposal_id=PID, payload={"choice": "YES"}, signed_proposal=True)
        first_hash = self.gov.read(ORG, WALLETS[0], "proposal", PID)["bylaws_hash"]
        opened = self.gov.read(ORG, WALLETS[0], "proposal", PID)["voting_starts_at"]
        with mock.patch("tools.governance.store.time.time", return_value=opened+61):
            self.change("CLOSE_VOTING", proposal_id=PID, signed_proposal=True)
        other_id = "gp_"+"c"*32
        with mock.patch("tools.governance.store.time.time", return_value=opened+80):
            self.change("CREATE_PROPOSAL", proposal_id=other_id,
                payload={"proposal_type": "OTHER_NON_FINANCIAL", "title": "Earlier rules",
                         "description": "Still open", "proposal_payload": {}, "author_agent_account": None})
            self.change("OPEN_VOTING", proposal_id=other_id)
        with mock.patch("tools.governance.store.time.time", return_value=opened+122):
            self.change("AMEND_BYLAWS", proposal_id=PID,
                payload={"bylaws": amended, "approved_proposal_id": PID}, signed_proposal=True)
            self.change("CAST_VOTE", proposal_id=other_id, payload={"choice": "YES"}, signed_proposal=True)
        self.assertEqual(self.gov.read(ORG, WALLETS[0], "proposal", other_id)["bylaws_hash"], first_hash)
        self.assertEqual(self.gov.read(ORG, WALLETS[0], "bylaws")[-1]["quorum_bps"], 10000)
        self.assertEqual(self.gov.read(ORG, WALLETS[0], "bylaws")[0]["bylaws_hash"], first_hash)

    def test_owner_only_bootstrap_current_membership_and_conflicting_keys(self):
        self.add_member()
        with self.assertRaises(GovernanceError):
            self.change("CREATE_BYLAWS", actor=1, payload={"bylaws": rules()})
        self.charter()
        body = self.body("CREATE_PROPOSAL", proposal_id=PID,
            payload={"proposal_type": "OTHER_NON_FINANCIAL", "title": "No funds",
                     "description": "Instruction: transfer funds", "proposal_payload": {},
                     "author_agent_account": None})
        self.change("CREATE_PROPOSAL", proposal_id=PID, body=body)
        with self.assertRaises(GovernanceError):
            self.change("CREATE_PROPOSAL", proposal_id=PID,
                body={**body, "payload": {**body["payload"], "title": "Tampered"}})
        with self.assertRaises(GovernanceError):
            self.change("CREATE_PROPOSAL", proposal_id="gp_"+"b"*32,
                payload={"proposal_type": "OTHER_NON_FINANCIAL", "title": "Unsafe",
                         "description": "text", "proposal_payload": {"is_executable": True},
                         "author_agent_account": None})
        self.change_org("SUSPEND_MEMBER", target_type="MEMBER", target_id=WALLETS[1])
        with self.assertRaises(OrganizationError): self.gov.read(ORG, WALLETS[1], "proposals")
        self.change_org("UPDATE_METADATA", payload={"organization_status": "SUSPENDED"})
        with self.assertRaises(OrganizationError): self.gov.read(ORG, WALLETS[0], "proposals")

    def test_late_vote_and_unknown_participant_fail(self):
        self.charter()
        with self.assertRaises(GovernanceError):
            self.change("CREATE_PROPOSAL", proposal_id=PID,
                payload={"proposal_type": "ECONOMIC_DISTRIBUTION_POLICY", "title": "Unknown member",
                         "description": "Only hypothetical", "proposal_payload": {
                             "mint": WALLETS[4], "participant_shares_bps": {WALLETS[2]: 10000},
                             "reserve_share_bps": 0, "cost_allocation_method": "DECLARATIVE_ONLY"},
                         "author_agent_account": None})
        self.proposal()
        opened = self.change("OPEN_VOTING", proposal_id=PID)[0][0]
        with mock.patch("tools.governance.store.time.time", return_value=opened["voting_ends_at"]):
            with self.assertRaises(GovernanceError):
                self.change("CAST_VOTE", proposal_id=PID, payload={"choice": "YES"}, signed_proposal=True)

    def test_invalid_historical_signature_is_detected(self):
        self.charter()
        self.org.conn.execute("DROP TRIGGER immutable_governance_events_update")
        self.org.conn.execute("UPDATE governance_events SET signature=? WHERE version=1",
                              (b58encode(KEYS[1].sign(b"unrelated")),))
        with self.assertRaises(GovernanceError): self.gov.read(ORG, WALLETS[0], "bylaws")

    def test_second_organization_never_inherits_first_governance(self):
        self.charter(); self.proposal()
        other = "org_"+"b"*32
        body = org_request()
        body["organization_id"] = other
        body["target_id"] = other
        body["payload"]["organization_slug"] = "fleet-two"
        body["nonce"] = "second-organization-nonce"
        body["idempotency_key"] = "second-organization-idem"
        message = organization_message("POST", "/v1/organizations", body)
        self.org.mutate(body, b58encode(KEYS[0].sign(message)), message, WALLETS[0])
        self.assertEqual(self.gov.read(other, WALLETS[0], "proposals"), [])
        self.assertEqual(self.gov.read(other, WALLETS[0], "bylaws"), [])
        self.assertEqual(len(self.gov.read(ORG, WALLETS[0], "proposals")), 1)

    def test_linked_agent_and_technical_signer_do_not_gain_vote(self):
        account = WALLETS[4]
        registration = {"agent_account": account, "agent_id": "11"*32,
            "agent_owner_pubkey": WALLETS[2], "network": "localnet", "genesis_hash": WALLETS[3],
            "program_id": WALLETS[4], "agent_status": "Active", "active": True}
        self.org.agent_snapshot = lambda: {"network": "localnet", "genesis_hash": WALLETS[3],
            "program_id": WALLETS[4], "agents": [{"agent_account": account, "agent_id": "11"*32,
                "owner": WALLETS[2], "status": "Active", "active": True}]}
        invitation = "inv_"+"f"*32
        now = int(time.time())
        self.change_org("INVITE_AGENT", target_type="INVITATION", target_id=invitation,
            payload={"agent_account": account, "registration": registration,
                     "valid_from": now, "expires_at": now+1000})
        self.change_org("ACCEPT_AGENT", actor=2, target_type="INVITATION", target_id=invitation,
            payload={"agent_account": account, "registration_snapshot_hash": digest(registration)})
        self.charter(); self.proposal(); self.change("OPEN_VOTING", proposal_id=PID)
        with self.assertRaises(GovernanceError):
            self.change("CAST_VOTE", actor=4, proposal_id=PID,
                        payload={"choice": "YES"}, signed_proposal=True)
        with self.assertRaises(GovernanceError):
            self.change("CAST_VOTE", actor=2, proposal_id=PID,
                        payload={"choice": "YES"}, signed_proposal=True)

    def test_closed_tally_is_reconstructed_after_sqlite_restart(self):
        self.charter(); self.proposal(); self.change("OPEN_VOTING", proposal_id=PID)
        self.change("CAST_VOTE", proposal_id=PID, payload={"choice": "YES"}, signed_proposal=True)
        opened = self.gov.read(ORG, WALLETS[0], "proposal", PID)["voting_starts_at"]
        with mock.patch("tools.governance.store.time.time", return_value=opened+61):
            self.change("CLOSE_VOTING", proposal_id=PID, signed_proposal=True)
        expected = self.gov.read(ORG, WALLETS[0], "proposal", PID)["tally"]
        self.org.close()
        self.org = OrganizationStore(self.path)
        self.gov = GovernanceStore(self.org)
        actual = self.gov.read(ORG, WALLETS[0], "proposal", PID)["tally"]
        self.assertEqual(expected, actual)
        self.assertEqual(actual["outcome"], "ACCEPTED")


if __name__ == "__main__":
    unittest.main()
