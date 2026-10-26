"""Governance events share CON-32 SQLite transactions and verified identity history."""
from __future__ import annotations

import copy
import json
import re
import sqlite3
import time

from tools.organizations.store import OrganizationStore, _apply as apply_organization, _fresh_agent
from tools.organizations.signatures import OrganizationError, canonical, digest, _verify
from .engine import (GovernanceRuleError, PROPOSAL_TYPES, electorate_from_organization,
                     evaluate_governance_proposal, simulate_organization_distribution,
                     validate_bylaws, validate_distribution_policy)
from .signatures import GovernanceError, mutation_message

PROPOSAL_ID = re.compile(r"gp_[0-9a-f]{32}\Z")
DISPUTE_ID = re.compile(r"gd_[0-9a-f]{32}\Z")
POLICY_ID = re.compile(r"gpol_[0-9a-f]{32}\Z")
ACTIONS = frozenset({"CREATE_BYLAWS", "AMEND_BYLAWS", "CREATE_PROPOSAL", "OPEN_VOTING",
    "CAST_VOTE", "CLOSE_VOTING", "OPEN_DISPUTE", "RESOLVE_DISPUTE",
    "ADOPT_DISTRIBUTION_POLICY", "SIMULATE_DISTRIBUTION"})


def _reject(code: str, message: str, status: int = 409):
    raise GovernanceError(status, code, message)


def _member(state: dict, actor: str, at: int) -> dict | None:
    member = state["members"].get(actor)
    return member if (state["organization"]["organization_status"] == "ACTIVE" and member and
                      member["status"] == "ACTIVE" and member["valid_from"] <= at < member["expires_at"]) else None


def _role(state: dict, actor: str, at: int) -> str | None:
    member = _member(state, actor, at)
    return state["roles"].get(actor, member["role_id"]) if member else None


def _root(state: dict, actor: str, at: int):
    if actor != state["organization"]["owner_pubkey"] or not _member(state, actor, at):
        _reject("FORBIDDEN", "Current organization owner required", 403)


def _proposal(gov: dict, proposal_id: str) -> dict:
    proposal = gov["proposals"].get(proposal_id)
    if proposal is None:
        _reject("NOT_FOUND", "Governance proposal not found", 404)
    return proposal


def _bylaws(gov: dict) -> dict:
    if not gov["bylaws"]:
        _reject("NO_BYLAWS", "Governance bylaws have not been created", 422)
    return gov["bylaws"][-1]


def _payload(body: dict, expected: set[str]):
    if set(body["payload"]) != expected:
        _reject("INVALID_PAYLOAD", "Exact governance action fields required", 400)


def _declarative(value, depth: int = 0):
    if depth > 8:
        _reject("INVALID_PROPOSAL", "Proposal payload is too deeply nested", 422)
    if isinstance(value, dict):
        for key, item in value.items():
            if (not isinstance(key, str) or key.lower() in {"is_executable", "funds_transferred",
                    "real_capital_authorized", "is_financial_authority", "execute", "transfer",
                    "wallet_private_key", "signing_authority", "escrow_withdraw", "settlement"}):
                _reject("INVALID_PROPOSAL", "Proposal may only contain declarative content", 422)
            _declarative(item, depth+1)
    elif isinstance(value, list):
        for item in value:
            _declarative(item, depth+1)
    elif value is not None and type(value) not in (str, int, bool):
        _reject("INVALID_PROPOSAL", "Unsupported proposal payload value", 422)


def _participants(policy: dict, org: dict, at: int):
    for participant in policy["participant_shares_bps"]:
        if _member(org, participant, at):
            continue
        agent = org["agents"].get(participant)
        if not agent or agent["status"] != "ACTIVE" or not agent["valid_from"] <= at < agent["expires_at"]:
            _reject("INVALID_PARTICIPANT", "Participant must be an active organization member", 422)


def _current_agent_participants(policy: dict, org: dict, snapshot):
    for participant in policy["participant_shares_bps"]:
        agent = org["agents"].get(participant)
        if agent and _fresh_agent(snapshot, participant) != {
                key: agent[key] for key in ("agent_account", "agent_id", "agent_owner_pubkey",
                    "network", "genesis_hash", "program_id", "agent_status", "active")}:
            _reject("AGENT_IDENTITY_CHANGED", "Agent participant identity changed", 409)


def _apply(gov: dict, body: dict, org: dict, at: int) -> dict:
    action, actor, payload = body["action"], body["actor_pubkey"], body["payload"]
    if action not in ACTIONS:
        _reject("INVALID_ACTION", "Unknown governance action", 400)
    if org["organization"]["organization_id"] != body["organization_id"] or not _member(org, actor, at):
        _reject("FORBIDDEN", "Current organization membership required", 403)
    if gov["version"] != body["expected_version"]:
        _reject("VERSION_CONFLICT", "Governance version changed")
    current = gov["bylaws"][-1] if gov["bylaws"] else None
    proposal_actions = {"CAST_VOTE", "CLOSE_VOTING", "OPEN_DISPUTE", "RESOLVE_DISPUTE",
                        "ADOPT_DISTRIBUTION_POLICY"}
    signed_rules = (_proposal(gov, body["proposal_id"]) if action in proposal_actions else current)
    if signed_rules:
        if body["bylaws_version"] != signed_rules["bylaws_version" if action in proposal_actions else "version"] or body["bylaws_hash"] != signed_rules["bylaws_hash"]:
            _reject("BYLAWS_CONFLICT", "Signed bylaws version differs from current version")
        if action in proposal_actions and body["electorate_snapshot_hash"] != signed_rules["electorate_snapshot_hash"]:
            _reject("ELECTORATE_CONFLICT", "Signed electorate differs from proposal snapshot")
    elif body["bylaws_version"] != 0 or body["bylaws_hash"]:
        _reject("BYLAWS_CONFLICT", "No bylaws exist yet")
    if action == "CREATE_BYLAWS":
        _root(org, actor, at)
        _payload(body, {"bylaws"})
        if current or body["proposal_id"] or body["electorate_snapshot_hash"]:
            _reject("BYLAWS_CONFLICT", "Initial bylaws already exist")
        rules = validate_bylaws(payload["bylaws"])
        if rules["distribution_policy_id"] is not None:
            _reject("INVALID_BYLAWS", "Initial bylaws cannot reference a distribution policy", 422)
        record = {**rules, "organization_id": body["organization_id"], "bylaws_id": "byl_"+digest(body)[:32],
                  "version": 1, "effective_from": at, "expires_at": None, "created_by": actor,
                  "created_at": at, "status": "ADOPTED"}
        record["bylaws_hash"] = digest(record)
        gov["bylaws"].append(record)
    elif action == "AMEND_BYLAWS":
        _root(org, actor, at)
        _payload(body, {"bylaws", "approved_proposal_id"})
        if not isinstance(payload["approved_proposal_id"], str):
            _reject("INVALID_PAYLOAD", "Approved proposal identifier required", 400)
        proposal = _proposal(gov, payload["approved_proposal_id"])
        if (body["proposal_id"] != proposal["proposal_id"] or
                body["electorate_snapshot_hash"] != proposal["electorate_snapshot_hash"]):
            _reject("ELECTORATE_CONFLICT", "Amendment must bind its approved electorate")
        source_rules = next(b for b in gov["bylaws"] if b["bylaws_hash"] == proposal["bylaws_hash"])
        if (proposal["proposal_type"] != "BYLAWS_AMENDMENT" or proposal["status"] != "ACCEPTED" or
                proposal["consumed"] or proposal["resolution_status"] != "FINAL" or
                at < proposal["resolved_at"] + source_rules["dispute_window_seconds"] or
                any(d["proposal_id"] == proposal["proposal_id"] and d["status"] == "OPEN"
                    for d in gov["disputes"].values()) or
                proposal["proposal_payload_hash"] != digest(payload["bylaws"])):
            _reject("UNAPPROVED_AMENDMENT", "Matching accepted amendment required", 403)
        rules = validate_bylaws(payload["bylaws"])
        if rules["distribution_policy_id"] is not None and rules["distribution_policy_id"] not in gov["policies"]:
            _reject("INVALID_BYLAWS", "Referenced distribution policy is not adopted", 422)
        record = {**rules, "organization_id": body["organization_id"], "bylaws_id": "byl_"+digest(body)[:32],
                  "version": current["version"]+1, "effective_from": at, "expires_at": None,
                  "created_by": actor, "created_at": at, "status": "ADOPTED",
                  "approved_proposal_id": proposal["proposal_id"]}
        record["bylaws_hash"] = digest(record)
        gov["bylaws"].append(record)
        proposal["consumed"] = True
    elif action == "CREATE_PROPOSAL":
        _payload(body, {"proposal_type", "title", "description", "proposal_payload", "author_agent_account"})
        if (not current or not PROPOSAL_ID.fullmatch(body["proposal_id"]) or
                body["proposal_id"] in gov["proposals"] or body["electorate_snapshot_hash"]):
            _reject("INVALID_PROPOSAL", "New proposal identifier and current bylaws required", 422)
        if _role(org, actor, at) not in current["proposal_roles"]:
            _reject("FORBIDDEN", "Current role cannot create proposals", 403)
        if (not isinstance(payload["proposal_type"], str) or payload["proposal_type"] not in PROPOSAL_TYPES or
                payload["proposal_type"] not in current["proposal_permissions"] or
                not isinstance(payload["proposal_payload"], dict)):
            _reject("INVALID_PROPOSAL", "Unknown proposal type or payload", 422)
        if len(canonical(payload["proposal_payload"])) > 8192:
            _reject("INVALID_PROPOSAL", "Proposal payload is too large", 422)
        _declarative(payload["proposal_payload"])
        if (not isinstance(payload["title"], str) or not 1 <= len(payload["title"].strip()) <= 160 or
                not isinstance(payload["description"], str) or len(payload["description"]) > 4000):
            _reject("INVALID_PROPOSAL", "Invalid proposal text", 422)
        account = payload["author_agent_account"]
        if account is not None:
            if not isinstance(account, str):
                _reject("INVALID_PROPOSAL", "Agent account must be a public key", 422)
            linked = org["agents"].get(account)
            if (not linked or linked["status"] != "ACTIVE" or linked["agent_owner_pubkey"] != actor or
                    not linked["valid_from"] <= at < linked["expires_at"]):
                _reject("FORBIDDEN", "Agent proposal requires current owner consent", 403)
        if payload["proposal_type"] == "BYLAWS_AMENDMENT":
            validate_bylaws(payload["proposal_payload"])
        if payload["proposal_type"] == "ECONOMIC_DISTRIBUTION_POLICY":
            validate_distribution_policy(payload["proposal_payload"])
            _participants(payload["proposal_payload"], org, at)
        gov["proposals"][body["proposal_id"]] = {"proposal_id": body["proposal_id"],
            "organization_id": body["organization_id"], "proposal_type": payload["proposal_type"],
            "title": payload["title"].strip(), "description": payload["description"],
            "proposal_payload": payload["proposal_payload"],
            "proposal_payload_hash": digest(payload["proposal_payload"]), "created_by": actor,
            "author_agent_account": account, "created_at": at,
            "bylaws_version": current["version"], "bylaws_hash": current["bylaws_hash"],
            "electorate_snapshot_hash": "", "electorate": {}, "membership_snapshot_hash": "",
            "voting_starts_at": None, "voting_ends_at": None, "status": "DRAFT",
            "resolution_status": "PENDING", "resolved_at": None, "tally": None,
            "consumed": False, "is_executable": False}
    elif action == "OPEN_VOTING":
        _payload(body, set())
        proposal = _proposal(gov, body["proposal_id"])
        if (proposal["status"] != "DRAFT" or
                actor not in (proposal["created_by"], org["organization"]["owner_pubkey"]) or
                _role(org, actor, at) not in current["proposal_roles"]):
            _reject("FORBIDDEN", "Only author or owner may open draft voting", 403)
        if proposal["bylaws_hash"] != current["bylaws_hash"] or body["electorate_snapshot_hash"]:
            _reject("BYLAWS_CONFLICT", "Draft must open under its original bylaws")
        electorate = electorate_from_organization(org, current, at)
        proposal["electorate"] = electorate
        proposal["electorate_snapshot_hash"] = digest(electorate)
        proposal["membership_snapshot_hash"] = digest({"version": org["organization"]["version"],
                                                       "members": org["members"], "roles": org["roles"]})
        proposal["voting_starts_at"] = at
        proposal["voting_ends_at"] = at + current["voting_period_seconds"]
        proposal["status"] = "OPEN"
        gov["votes"][proposal["proposal_id"]] = {}
    elif action == "CAST_VOTE":
        _payload(body, {"choice"})
        proposal = _proposal(gov, body["proposal_id"])
        if (proposal["status"] != "OPEN" or not proposal["voting_starts_at"] <= at < proposal["voting_ends_at"] or
                body["electorate_snapshot_hash"] != proposal["electorate_snapshot_hash"] or
                proposal["bylaws_hash"] != body["bylaws_hash"] or actor not in proposal["electorate"] or
                _role(org, actor, at) not in next(b for b in gov["bylaws"] if b["bylaws_hash"] == proposal["bylaws_hash"])["eligible_voter_roles"]):
            _reject("VOTE_INELIGIBLE", "Vote is closed or current eligibility is unavailable", 403)
        if payload["choice"] not in ("YES", "NO", "ABSTAIN"):
            _reject("INVALID_VOTE", "Unknown vote choice", 422)
        if actor in gov["votes"][proposal["proposal_id"]]:
            _reject("DUPLICATE_VOTE", "Wallet already voted on this proposal")
        gov["votes"][proposal["proposal_id"]][actor] = {"voter_pubkey": actor,
            "choice": payload["choice"], "voted_at": at, "signature_body_hash": digest(body),
            "bylaws_hash": proposal["bylaws_hash"], "electorate_snapshot_hash": proposal["electorate_snapshot_hash"]}
    elif action == "CLOSE_VOTING":
        _payload(body, set())
        proposal = _proposal(gov, body["proposal_id"])
        if (proposal["status"] != "OPEN" or at < proposal["voting_ends_at"] or
                actor != org["organization"]["owner_pubkey"] or
                body["electorate_snapshot_hash"] != proposal["electorate_snapshot_hash"]):
            _reject("INVALID_CLOSE", "Voting can be closed by owner after its deadline", 403)
        rules = next(b for b in gov["bylaws"] if b["bylaws_hash"] == proposal["bylaws_hash"])
        tally = evaluate_governance_proposal(proposal, rules, proposal["electorate"],
                                             gov["votes"][proposal["proposal_id"]], at)
        proposal["tally"] = tally
        proposal["status"] = tally["outcome"]
        proposal["resolution_status"] = "FINAL"
        proposal["resolved_at"] = at
    elif action == "OPEN_DISPUTE":
        _payload(body, {"dispute_id", "reason_code", "evidence_refs"})
        proposal = _proposal(gov, body["proposal_id"])
        rules = next(b for b in gov["bylaws"] if b["bylaws_hash"] == proposal["bylaws_hash"])
        if (proposal["status"] not in ("ACCEPTED", "REJECTED") or
                not proposal["resolved_at"] <= at < proposal["resolved_at"]+rules["dispute_window_seconds"] or
                actor not in proposal["electorate"] or _role(org, actor, at) not in rules["eligible_voter_roles"] or
                not isinstance(payload["dispute_id"], str) or
                not DISPUTE_ID.fullmatch(payload["dispute_id"]) or
                payload["dispute_id"] in gov["disputes"] or
                any(d["proposal_id"] == body["proposal_id"] for d in gov["disputes"].values())):
            _reject("INVALID_DISPUTE", "Current eligible voter and dispute window required", 403)
        if (payload["reason_code"] not in ("PROCEDURAL", "IDENTITY", "EVIDENCE", "OTHER") or
                not isinstance(payload["evidence_refs"], list) or len(payload["evidence_refs"]) > 20 or
                any(not isinstance(ref, str) or len(ref) > 300 for ref in payload["evidence_refs"])):
            _reject("INVALID_DISPUTE", "Invalid dispute evidence", 422)
        gov["disputes"][payload["dispute_id"]] = {"dispute_id": payload["dispute_id"],
            "organization_id": body["organization_id"], "proposal_id": body["proposal_id"],
            "opened_by": actor, "reason_code": payload["reason_code"],
            "evidence_refs": payload["evidence_refs"], "opened_at": at,
            "response_deadline": at+rules["dispute_window_seconds"], "status": "OPEN",
            "resolution": None, "resolved_by": None, "resolved_at": None}
        proposal["resolution_status"] = "DISPUTED"
    elif action == "RESOLVE_DISPUTE":
        _payload(body, {"dispute_id", "resolution"})
        _root(org, actor, at)
        if not isinstance(payload["dispute_id"], str):
            _reject("INVALID_PAYLOAD", "Dispute identifier required", 400)
        dispute = gov["disputes"].get(payload["dispute_id"])
        if (not dispute or dispute["proposal_id"] != body["proposal_id"] or dispute["status"] != "OPEN" or
                at >= dispute["response_deadline"]):
            _reject("INVALID_DISPUTE", "Open dispute required", 422)
        if payload["resolution"] not in ("UPHOLD", "REFER_EXTERNAL"):
            _reject("INVALID_DISPUTE", "Unsupported resolution", 422)
        proposal = _proposal(gov, body["proposal_id"])
        if actor == proposal["created_by"] and payload["resolution"] != "REFER_EXTERNAL":
            _reject("RECUSAL_REQUIRED", "Affected author cannot uphold own result", 403)
        dispute.update({"status": "RESOLVED", "resolution": payload["resolution"],
                        "resolved_by": actor, "resolved_at": at})
        proposal["resolution_status"] = "FINAL" if payload["resolution"] == "UPHOLD" else "EXTERNAL_REVIEW"
    elif action == "ADOPT_DISTRIBUTION_POLICY":
        _payload(body, {"distribution_policy_id"})
        _root(org, actor, at)
        proposal = _proposal(gov, body["proposal_id"])
        policy_id = payload["distribution_policy_id"]
        rules = next(b for b in gov["bylaws"] if b["bylaws_hash"] == proposal["bylaws_hash"])
        if (not isinstance(policy_id, str) or not POLICY_ID.fullmatch(policy_id) or policy_id in gov["policies"] or
                proposal["proposal_type"] != "ECONOMIC_DISTRIBUTION_POLICY" or
                proposal["status"] != "ACCEPTED" or proposal["resolution_status"] != "FINAL" or
                at < proposal["resolved_at"] + rules["dispute_window_seconds"] or
                proposal["consumed"] or any(d["proposal_id"] == body["proposal_id"] and
                d["status"] == "OPEN" for d in gov["disputes"].values())):
            _reject("UNAPPROVED_POLICY", "Matching final distribution agreement required", 403)
        policy = validate_distribution_policy(proposal["proposal_payload"])
        _participants(policy, org, at)
        gov["policies"][policy_id] = {**policy, "distribution_policy_id": policy_id,
            "organization_id": body["organization_id"], "version": len(gov["policies"])+1,
            "policy_hash": digest(policy), "created_by": actor,
            "approved_proposal_id": body["proposal_id"], "created_at": at,
            "status": "ADOPTED", "is_executable": False}
        proposal["consumed"] = True
    elif action == "SIMULATE_DISTRIBUTION":
        _payload(body, {"distribution_policy_id", "hypothetical_pool", "assumptions"})
        if not isinstance(payload["distribution_policy_id"], str):
            _reject("INVALID_PAYLOAD", "Distribution policy identifier required", 400)
        policy = gov["policies"].get(payload["distribution_policy_id"])
        if not policy or not isinstance(payload["assumptions"], dict) or len(canonical(payload["assumptions"])) > 2000:
            _reject("INVALID_SIMULATION", "Adopted policy and bounded assumptions required", 422)
        result = simulate_organization_distribution(payload["hypothetical_pool"], policy, payload["assumptions"])
        gov["simulations"]["gs_"+digest(body)[:32]] = result
    gov["version"] += 1
    return gov


class GovernanceStore:
    def __init__(self, organizations: OrganizationStore):
        self.organizations = organizations
        self.conn = organizations.conn
        self.lock = organizations.lock
        with self.lock:
            self.conn.executescript("""
                CREATE TABLE IF NOT EXISTS governance_heads (
                    organization_id TEXT PRIMARY KEY REFERENCES organization_index(organization_id),
                    head_version INTEGER NOT NULL, head_hash TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS governance_events (
                    event_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL REFERENCES organization_index(organization_id),
                    version INTEGER NOT NULL, organization_version INTEGER NOT NULL,
                    organization_event_hash TEXT NOT NULL, actor_pubkey TEXT NOT NULL,
                    action TEXT NOT NULL, body_json TEXT NOT NULL, signature TEXT NOT NULL,
                    previous_state_hash TEXT NOT NULL, new_state_hash TEXT NOT NULL,
                    previous_event_hash TEXT NOT NULL, event_hash TEXT NOT NULL,
                    occurred_at INTEGER NOT NULL, nonce TEXT NOT NULL UNIQUE,
                    idempotency_key TEXT NOT NULL UNIQUE, UNIQUE(organization_id,version));
                CREATE INDEX IF NOT EXISTS governance_events_scope ON governance_events(organization_id,version);
                CREATE TRIGGER IF NOT EXISTS immutable_governance_events_update BEFORE UPDATE ON governance_events
                BEGIN SELECT RAISE(ABORT,'governance events are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS immutable_governance_events_delete BEFORE DELETE ON governance_events
                BEGIN SELECT RAISE(ABORT,'governance events are immutable'); END;
            """)

    def _load(self, org_id: str, org_events: list[dict]) -> tuple[dict, list[dict]]:
        gov = {"version": 0, "bylaws": [], "proposals": {}, "votes": {}, "policies": {},
               "disputes": {}, "simulations": {}}
        org_states = {}
        org_state = None
        for event in org_events:
            org_state = apply_organization(org_state, event["body"], event["occurred_at"])
            org_states[event["version"]] = copy.deepcopy(org_state)
        rows = self.conn.execute("SELECT * FROM governance_events WHERE organization_id=? ORDER BY version",
                                 (org_id,)).fetchall()
        events, previous_hash, previous_at = [], "0"*64, 0
        for row in rows:
            try:
                body = json.loads(row["body_json"])
                anchor = org_events[row["organization_version"]-1]
                if (row["body_json"] != canonical(body).decode() or body["organization_id"] != org_id or
                        row["organization_event_hash"] != anchor["event_hash"] or
                        row["version"] != len(events)+1 or body["expected_version"] != len(events) or
                        row["actor_pubkey"] != body["actor_pubkey"] or row["action"] != body["action"] or
                        row["nonce"] != body["nonce"] or row["idempotency_key"] != body["idempotency_key"] or
                        row["previous_state_hash"] != digest(gov) or row["previous_event_hash"] != previous_hash or
                        row["occurred_at"] < anchor["occurred_at"] or row["occurred_at"] < previous_at or
                        not body["issued_at"] <= row["occurred_at"] < body["expires_at"] or
                        row["event_id"] != "ge_"+digest([org_id, body["idempotency_key"]])[:32]):
                    raise ValueError("governance event sequence mismatch")
                _verify(body["actor_pubkey"], row["signature"], mutation_message("POST",
                    f"/v1/organizations/{org_id}/governance/actions", body))
                gov = _apply(gov, body, copy.deepcopy(org_states[row["organization_version"]]), row["occurred_at"])
                if row["new_state_hash"] != digest(gov):
                    raise ValueError("governance state mismatch")
                event = {key: row[key] for key in row.keys() if key != "body_json"}
                event["body"] = body
                if row["event_hash"] != digest({key: value for key, value in event.items() if key != "event_hash"}):
                    raise ValueError("governance event hash mismatch")
                events.append(event)
                previous_hash, previous_at = row["event_hash"], row["occurred_at"]
            except (ValueError, KeyError, IndexError, TypeError, OrganizationError, StopIteration) as exc:
                raise GovernanceError(409, "AUDIT_INTEGRITY_CONFLICT", "Governance history is inconsistent") from exc
        head = self.conn.execute("SELECT * FROM governance_heads WHERE organization_id=?", (org_id,)).fetchone()
        if (head is None and events or head is not None and
                (head["head_version"] != len(events) or head["head_hash"] != previous_hash)):
            _reject("AUDIT_INTEGRITY_CONFLICT", "Governance head is inconsistent")
        return gov, events

    def mutate(self, body: dict, signature: str, message: bytes, actor: str) -> tuple[dict, bool]:
        org_id = body["organization_id"]
        path = f"/v1/organizations/{org_id}/governance/actions"
        at = int(time.time())
        if (actor != body["actor_pubkey"] or message != mutation_message("POST", path, body) or
                not body["issued_at"] <= at < body["expires_at"] or abs(at-body["issued_at"]) > 300):
            _reject("INVALID_SIGNATURE", "Governance signature is invalid or expired", 401)
        _verify(actor, signature, message)
        with self.lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                org, org_events = self.organizations._load(org_id)
                if org is None:
                    _reject("NOT_FOUND", "Organization not found", 404)
                gov, events = self._load(org_id, org_events)
                previous = self.conn.execute("SELECT * FROM governance_events WHERE idempotency_key=? OR nonce=?",
                    (body["idempotency_key"], body["nonce"])).fetchone()
                if previous:
                    if (previous["organization_id"] != org_id or previous["actor_pubkey"] != actor or
                            previous["idempotency_key"] != body["idempotency_key"] or
                            previous["nonce"] != body["nonce"] or previous["body_json"] != canonical(body).decode()):
                        _reject("IDEMPOTENCY_CONFLICT", "Governance nonce or key was reused")
                    if not _member(org, actor, at):
                        _reject("FORBIDDEN", "Current membership is inactive", 403)
                    prior_action = body["action"]
                    if prior_action in {"CREATE_BYLAWS", "AMEND_BYLAWS", "CLOSE_VOTING",
                                        "RESOLVE_DISPUTE", "ADOPT_DISTRIBUTION_POLICY"}:
                        _root(org, actor, at)
                    if prior_action == "CAST_VOTE":
                        proposal = _proposal(gov, body["proposal_id"])
                        rules = next(b for b in gov["bylaws"] if b["bylaws_hash"] == proposal["bylaws_hash"])
                        if actor not in proposal["electorate"] or _role(org, actor, at) not in rules["eligible_voter_roles"]:
                            _reject("FORBIDDEN", "Current voting eligibility is unavailable", 403)
                    if prior_action == "CREATE_PROPOSAL":
                        if _role(org, actor, at) not in _bylaws(gov)["proposal_roles"]:
                            _reject("FORBIDDEN", "Current proposal authority is unavailable", 403)
                        account = body["payload"].get("author_agent_account")
                        if account is not None:
                            linked = org["agents"].get(account)
                            if (not linked or linked["agent_owner_pubkey"] != actor or
                                    _fresh_agent(self.organizations.agent_snapshot, account) != {
                                        key: linked[key] for key in ("agent_account", "agent_id", "agent_owner_pubkey",
                                            "network", "genesis_hash", "program_id", "agent_status", "active")}):
                                _reject("FORBIDDEN", "Current agent proposal authority is unavailable", 403)
                    self.conn.execute("COMMIT")
                    return self._result(gov, body), False
                if not _member(org, actor, at):
                    _reject("FORBIDDEN", "Current organization membership required", 403)
                linked = None
                if body["action"] == "CREATE_PROPOSAL":
                    account = body["payload"].get("author_agent_account")
                    if account is not None:
                        if not isinstance(account, str):
                            _reject("INVALID_PROPOSAL", "Agent account must be a public key", 422)
                        linked = org["agents"].get(account)
                        if (not linked or _fresh_agent(self.organizations.agent_snapshot, account) !=
                                {key: linked[key] for key in ("agent_account", "agent_id", "agent_owner_pubkey",
                                    "network", "genesis_hash", "program_id", "agent_status", "active")}):
                            _reject("AGENT_IDENTITY_CHANGED", "Agent proposal identity requires current owner", 409)
                previous_hash = events[-1]["event_hash"] if events else "0"*64
                previous_state_hash = digest(gov)
                committed_at = int(time.time())
                if events and committed_at < events[-1]["occurred_at"]:
                    _reject("CLOCK_CONFLICT", "Governance clock moved backwards")
                participant_policy = None
                if body["action"] == "CREATE_PROPOSAL" and body["payload"].get("proposal_type") == "ECONOMIC_DISTRIBUTION_POLICY":
                    participant_policy = body["payload"].get("proposal_payload")
                elif body["action"] == "ADOPT_DISTRIBUTION_POLICY":
                    proposal = gov["proposals"].get(body["proposal_id"])
                    participant_policy = proposal["proposal_payload"] if proposal else None
                if isinstance(participant_policy, dict) and isinstance(participant_policy.get("participant_shares_bps"), dict):
                    _current_agent_participants(participant_policy, org, self.organizations.agent_snapshot)
                next_gov = _apply(gov, body, copy.deepcopy(org), committed_at)
                if linked and _fresh_agent(self.organizations.agent_snapshot, linked["agent_account"]) != {
                        key: linked[key] for key in ("agent_account", "agent_id", "agent_owner_pubkey",
                            "network", "genesis_hash", "program_id", "agent_status", "active")}:
                    _reject("AGENT_IDENTITY_CHANGED", "Agent changed before governance commit", 409)
                if isinstance(participant_policy, dict) and isinstance(participant_policy.get("participant_shares_bps"), dict):
                    _current_agent_participants(participant_policy, org, self.organizations.agent_snapshot)
                event = {"event_id": "ge_"+digest([org_id, body["idempotency_key"]])[:32],
                    "organization_id": org_id, "version": next_gov["version"],
                    "organization_version": org["organization"]["version"],
                    "organization_event_hash": org_events[-1]["event_hash"], "actor_pubkey": actor,
                    "action": body["action"], "signature": signature,
                    "previous_state_hash": previous_state_hash, "new_state_hash": digest(next_gov),
                    "previous_event_hash": previous_hash, "occurred_at": committed_at,
                    "nonce": body["nonce"], "idempotency_key": body["idempotency_key"], "body": body}
                event_hash = digest(event)
                if not events:
                    self.conn.execute("INSERT INTO governance_heads VALUES (?,?,?)", (org_id, 0, "0"*64))
                self.conn.execute("INSERT INTO governance_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (event["event_id"], org_id, event["version"], event["organization_version"],
                     event["organization_event_hash"], actor, body["action"], canonical(body).decode(),
                     signature, previous_state_hash, event["new_state_hash"], previous_hash,
                     event_hash, committed_at, body["nonce"], body["idempotency_key"]))
                self.conn.execute("UPDATE governance_heads SET head_version=?,head_hash=? WHERE organization_id=?",
                                  (event["version"], event_hash, org_id))
                self.conn.execute("COMMIT")
                return self._result(next_gov, body), True
            except sqlite3.IntegrityError as exc:
                self.conn.execute("ROLLBACK")
                raise GovernanceError(409, "GOVERNANCE_CONFLICT", "Governance identity or key conflict") from exc
            except Exception:
                self.conn.execute("ROLLBACK")
                raise

    @staticmethod
    def _result(gov: dict, body: dict) -> dict:
        action, pid = body["action"], body["proposal_id"]
        if action in {"CREATE_BYLAWS", "AMEND_BYLAWS"}:
            return gov["bylaws"][-1]
        if action in {"CREATE_PROPOSAL", "OPEN_VOTING", "CAST_VOTE", "CLOSE_VOTING"}:
            return gov["proposals"][pid]
        if action in {"OPEN_DISPUTE", "RESOLVE_DISPUTE"}:
            return gov["disputes"][body["payload"]["dispute_id"]]
        if action == "ADOPT_DISTRIBUTION_POLICY":
            return gov["policies"][body["payload"]["distribution_policy_id"]]
        return gov["simulations"]["gs_"+digest(body)[:32]]

    @staticmethod
    def _proposal_view(gov: dict, proposal: dict, actor: str) -> dict:
        votes = gov["votes"].get(proposal["proposal_id"], {})
        return {**proposal, "vote_count": len(votes), "my_vote": votes.get(actor, {}).get("choice")}

    def read(self, org_id: str, actor: str, section: str, proposal_id: str | None = None):
        # CON-32 read performs current authorization and concealment before exposing history.
        with self.lock:
            self.organizations.read(org_id, actor)
            org, org_events = self.organizations._load(org_id)
            at = int(time.time())
            if org is None or not _member(org, actor, at):
                _reject("NOT_FOUND", "Governance resource not found", 404)
            gov, events = self._load(org_id, org_events)
            if section == "overview":
                return {"organization_id": org_id, "governance_version": gov["version"],
                        "current_bylaws": gov["bylaws"][-1] if gov["bylaws"] else None,
                        "proposal_count": len(gov["proposals"]), "is_executable": False}
            if section == "bylaws":
                return gov["bylaws"]
            if section == "proposals":
                return [self._proposal_view(gov, proposal, actor) for proposal in gov["proposals"].values()]
            if section == "proposal":
                return self._proposal_view(gov, _proposal(gov, proposal_id or ""), actor)
            if section == "votes":
                return list(gov["votes"].get((proposal_id or ""), {}).values()) if proposal_id in gov["proposals"] else _proposal(gov, proposal_id or "")
            if section == "disputes":
                return list(gov["disputes"].values())
            if section == "distributions":
                return {"policies": list(gov["policies"].values()), "simulations": list(gov["simulations"].values())}
            if section == "audit-events":
                if _role(org, actor, at) not in {"OWNER", "ADMIN", "AUDITOR", "LEGAL_REPRESENTATIVE"}:
                    _reject("NOT_FOUND", "Governance resource not found", 404)
                return events
            _reject("NOT_FOUND", "Governance resource not found", 404)
