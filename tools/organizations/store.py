"""Event-sourced, isolated organizational registry with verified Ed25519 history."""
from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Callable

from .rbac import PERMISSIONS, ROLES, evaluate_organization_permission
from .signatures import OrganizationError, canonical, digest, mutation_message, pubkey, _verify

ACTION_PERMISSION = {
    "UPDATE_METADATA": "organization.update_metadata", "INVITE_HUMAN": "members.invite",
    "INVITE_AGENT": "agents.invite", "SUSPEND_MEMBER": "members.suspend",
    "REINSTATE_MEMBER": "members.reinstate", "REMOVE_MEMBER": "members.remove",
    "ASSIGN_ROLE": "roles.assign", "REVOKE_ROLE": "roles.revoke",
    "CREATE_DELEGATION": "delegations.create", "REVOKE_DELEGATION": "delegations.revoke",
    "REMOVE_AGENT": "agents.remove_membership",
}
ACTION_TARGET = {"CREATE": "ORGANIZATION", "UPDATE_METADATA": "ORGANIZATION",
    "INVITE_HUMAN": "INVITATION", "INVITE_AGENT": "INVITATION",
    "ACCEPT_HUMAN": "INVITATION", "DECLINE_HUMAN": "INVITATION", "ACCEPT_AGENT": "INVITATION",
    "SUSPEND_MEMBER": "MEMBER", "REINSTATE_MEMBER": "MEMBER", "REMOVE_MEMBER": "MEMBER",
    "ASSIGN_ROLE": "MEMBER", "REVOKE_ROLE": "MEMBER", "REMOVE_AGENT": "AGENT",
    "CREATE_DELEGATION": "DELEGATION", "REVOKE_DELEGATION": "DELEGATION"}
ACTION_FIELDS = {
    "CREATE": {"owner_pubkey", "organization_name", "organization_slug", "description",
               "organization_type", "jurisdiction", "legal_entity_name", "legal_representative_pubkey"},
    "UPDATE_METADATA": {"organization_name", "description", "organization_status"},
    "INVITE_HUMAN": {"subject_pubkey", "role_id", "valid_from", "expires_at"},
    "INVITE_AGENT": {"agent_account", "registration", "valid_from", "expires_at"},
    "ACCEPT_HUMAN": set(), "DECLINE_HUMAN": set(),
    "ACCEPT_AGENT": {"agent_account", "registration_snapshot_hash"},
    "SUSPEND_MEMBER": set(), "REINSTATE_MEMBER": set(), "REMOVE_MEMBER": set(),
    "ASSIGN_ROLE": {"role_id"}, "REVOKE_ROLE": set(),
    "CREATE_DELEGATION": {"delegate_pubkey", "permission", "resource_scope", "valid_from", "expires_at"},
    "REVOKE_DELEGATION": set(), "REMOVE_AGENT": set(),
}
READ_PERMISSION = {"members": "members.read", "agents": "agents.read_membership",
                   "invitations": "members.read", "roles": "roles.read",
                   "delegations": "delegations.read", "audit-events": "audit.read",
                   "permissions": "organization.read"}
ID = re.compile(r"(inv|del)_[0-9a-f]{32}\Z")


def _reject(code: str, message: str, status: int = 409):
    raise OrganizationError(status, code, message)


def _member_active(member: dict | None, at: int) -> bool:
    return bool(member and member["status"] == "ACTIVE" and
                member["valid_from"] <= at < member["expires_at"])


def _text(value, field: str, maximum: int, minimum: int = 1) -> str:
    if not isinstance(value, str) or not minimum <= len(value.strip()) <= maximum:
        _reject("INVALID_FIELD", f"Invalid {field}", 400)
    return value.strip()


def _int(value, field: str) -> int:
    if type(value) is not int or value < 0:
        _reject("INVALID_FIELD", f"Invalid {field}", 400)
    return value


def _scope(state: dict, actor: str, permission: str, target: str, at: int):
    decision = evaluate_organization_permission(state["organization"], actor, state["members"],
        state["roles"], state["delegations"], permission, target, at)
    if decision["decision"] != "ALLOW":
        _reject("FORBIDDEN", "Organizational permission denied", 403)
    return decision


def _fresh_agent(snapshot: Callable[[], dict] | None, account: str) -> dict | None:
    if snapshot is None:
        return None
    value = snapshot()
    agent = next((item for item in value.get("agents", []) if item.get("agent_account") == account), None)
    if agent is None:
        return None
    return {"agent_account": account, "agent_id": agent.get("agent_id"),
            "agent_owner_pubkey": agent.get("owner"), "network": value.get("network", "localnet"),
            "genesis_hash": value.get("genesis_hash", value.get("genesis", "")),
            "program_id": value.get("program_id", ""), "agent_status": agent.get("status"),
            "active": agent.get("active")}


def _apply(state: dict | None, body: dict, at: int) -> dict:
    action, actor, payload = body["action"], body["actor_pubkey"], body["payload"]
    if body["target_type"] != ACTION_TARGET.get(action):
        _reject("INVALID_TARGET", "Action and target type mismatch", 400)
    if set(payload) - ACTION_FIELDS[action]:
        _reject("INVALID_BODY", "Unknown organization action fields", 400)
    if action == "CREATE":
        if (state is not None or body["expected_version"] != 0 or body["target_type"] != "ORGANIZATION" or
                body["target_id"] != body["organization_id"] or body["role_id"] != "OWNER" or
                body["permission_scope"] != "organization" or
                payload.get("owner_pubkey") != actor):
            _reject("INVALID_CREATION", "Invalid organization creation", 422)
        name = _text(payload.get("organization_name"), "organization_name", 120)
        slug = _text(payload.get("organization_slug"), "organization_slug", 64)
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
            _reject("INVALID_SLUG", "Slug must be lowercase words", 400)
        kind = payload.get("organization_type")
        if kind not in {"INDIVIDUAL_LED", "COLLECTIVE", "REGISTERED_ENTITY_CLAIMED"}:
            _reject("INVALID_TYPE", "Unknown organization type", 400)
        representative = payload.get("legal_representative_pubkey")
        if representative is not None:
            pubkey(representative)
        org = {"organization_id": body["organization_id"], "organization_name": name,
               "organization_slug": slug, "description": _text(payload.get("description", ""), "description", 1000, 0),
               "organization_type": kind, "founder_pubkey": actor, "owner_pubkey": actor,
               "legal_representative_pubkey": representative,
               "legal_representative_status": "PENDING_VERIFICATION" if representative else "UNVERIFIED",
               "jurisdiction": _text(payload.get("jurisdiction", "UNDECLARED"), "jurisdiction", 80),
               "legal_entity_name": _text(payload.get("legal_entity_name", ""), "legal_entity_name", 160, 0),
               "legal_entity_verification_status": "UNVERIFIED", "organization_status": "ACTIVE",
               "created_at": at, "updated_at": at, "version": 1,
               "is_financial_authority": False, "is_device_signing_authority": False}
        return {"organization": org, "members": {actor: {"membership_id": "root_" + body["organization_id"],
                "member_pubkey": actor, "role_id": "OWNER", "status": "ACTIVE",
                "valid_from": at, "expires_at": 2**63-1, "accepted_at": at, "invited_by": actor}},
                "agents": {}, "invitations": {}, "roles": {actor: "OWNER"}, "delegations": {}}
    if state is None or body["expected_version"] != state["organization"]["version"]:
        _reject("VERSION_CONFLICT", "Organization version changed")
    org = state["organization"]
    if body["organization_id"] != org["organization_id"]:
        _reject("IDENTITY_CONFLICT", "Wrong organization", 403)
    if org["organization_status"] != "ACTIVE" and not (action == "UPDATE_METADATA" and
            actor == org["owner_pubkey"] and payload.get("organization_status") == "ACTIVE"):
        _reject("ORGANIZATION_INACTIVE", "Suspended organization cannot mutate", 403)
    target = body["target_id"]
    if action == "UPDATE_METADATA" and target != org["organization_id"]:
        _reject("INVALID_TARGET", "Metadata action target must be this organization", 400)
    if action in ACTION_PERMISSION:
        if not (action == "UPDATE_METADATA" and actor == org["owner_pubkey"] and
                payload.get("organization_status") == "ACTIVE" and org["organization_status"] == "SUSPENDED"):
            _scope(state, actor, ACTION_PERMISSION[action],
               target if action in {"SUSPEND_MEMBER", "REINSTATE_MEMBER", "REMOVE_MEMBER", "ASSIGN_ROLE",
                                    "REVOKE_ROLE", "REMOVE_AGENT"} else "organization", at)
    elif action not in {"ACCEPT_HUMAN", "DECLINE_HUMAN", "ACCEPT_AGENT"}:
        _reject("INVALID_ACTION", "Unknown administrative action", 400)
    if action == "UPDATE_METADATA":
        if actor != org["owner_pubkey"] and any(key in payload for key in
                ("owner_pubkey", "legal_representative_pubkey", "organization_status")):
            _reject("FORBIDDEN", "Root identity and status cannot be delegated", 403)
        if not payload or set(payload) - {"organization_name", "description", "organization_status"}:
            _reject("INVALID_METADATA", "Only basic metadata and root suspension can change", 400)
        if "organization_name" in payload:
            org["organization_name"] = _text(payload["organization_name"], "organization_name", 120)
        if "description" in payload:
            org["description"] = _text(payload["description"], "description", 1000, 0)
        if "organization_status" in payload:
            if payload["organization_status"] not in ("ACTIVE", "SUSPENDED"):
                _reject("INVALID_STATUS", "Invalid organization status", 422)
            org["organization_status"] = payload["organization_status"]
    elif action in {"INVITE_HUMAN", "INVITE_AGENT"}:
        if not ID.fullmatch(target) or not target.startswith("inv_") or target in state["invitations"]:
            _reject("INVITATION_CONFLICT", "Invitation identifier already used", 409)
        subject = pubkey(payload.get("subject_pubkey")) if action == "INVITE_HUMAN" else pubkey(payload.get("agent_account"))
        role = payload.get("role_id", "MEMBER") if action == "INVITE_HUMAN" else "MEMBER"
        if role not in ROLES or role == "OWNER" or (role == "LEGAL_REPRESENTATIVE" and
              subject != org.get("legal_representative_pubkey")):
            _reject("INVALID_ROLE", "Proposed role cannot be granted", 403)
        start, end = _int(payload.get("valid_from"), "valid_from"), _int(payload.get("expires_at"), "expires_at")
        if not at-300 <= start < end or end <= at or end > at + 365*86400:
            _reject("INVALID_VALIDITY", "Invitation has invalid validity", 422)
        if action == "INVITE_HUMAN":
            if _member_active(state["members"].get(subject), at) or any(
                item["subject_id"] == subject and item["subject_type"] == "HUMAN" and item["status"] == "INVITED" and at < item["expires_at"]
                for item in state["invitations"].values()):
                _reject("DUPLICATE_MEMBER", "Membership or invitation already exists")
        else:
            registration = payload.get("registration")
            if (not isinstance(registration, dict) or registration.get("agent_account") != subject or
                    not all(registration.get(k) for k in ("agent_id", "agent_owner_pubkey", "network",
                        "genesis_hash", "program_id")) or registration.get("active") is not True or
                    registration.get("agent_status") != "Active"):
                _reject("INVALID_AGENT", "Active registered agent snapshot required", 422)
            existing = state["agents"].get(subject, {})
            if (existing.get("status") == "ACTIVE" and existing.get("agent_owner_pubkey") ==
                    registration["agent_owner_pubkey"]) or any(
                item["subject_id"] == subject and item["subject_type"] == "AGENT" and item["status"] == "INVITED" and
                item["registration"]["agent_owner_pubkey"] == registration["agent_owner_pubkey"] and at < item["expires_at"]
                for item in state["invitations"].values()):
                _reject("DUPLICATE_AGENT", "Agent is already invited or linked")
        state["invitations"][target] = {"invitation_id": target, "organization_id": org["organization_id"],
            "subject_type": "HUMAN" if action == "INVITE_HUMAN" else "AGENT", "subject_id": subject,
            "proposed_role": role, "proposed_permissions": [], "invited_by": actor,
            "created_at": at, "valid_from": start, "expires_at": end, "status": "INVITED",
            "registration": payload.get("registration") if action == "INVITE_AGENT" else None,
            "registration_snapshot_hash": digest(payload["registration"]) if action == "INVITE_AGENT" else None}
    elif action in {"ACCEPT_HUMAN", "DECLINE_HUMAN", "ACCEPT_AGENT"}:
        invitation = state["invitations"].get(target)
        if (not invitation or invitation["status"] != "INVITED" or not
                invitation["valid_from"] <= at < invitation["expires_at"]):
            _reject("INVITATION_INACTIVE", "Invitation is unavailable", 422)
        if (action == "ACCEPT_AGENT") != (invitation["subject_type"] == "AGENT"):
            _reject("INVITATION_TYPE", "Invitation subject type mismatch", 422)
        _scope(state, invitation["invited_by"],
               "agents.invite" if invitation["subject_type"] == "AGENT" else "members.invite",
               "organization", at)
        expected = (invitation["registration"]["agent_owner_pubkey"] if action == "ACCEPT_AGENT"
                    else invitation["subject_id"])
        if actor != expected:
            _reject("FORBIDDEN", "Only the invited wallet or current agent owner may consent", 403)
        if action == "ACCEPT_AGENT" and (payload.get("agent_account") != invitation["subject_id"] or
                payload.get("registration_snapshot_hash") != digest(invitation["registration"])):
            _reject("CONSENT_CONTEXT_MISMATCH", "Agent consent must bind the exact registration snapshot", 422)
        invitation["status"] = "DECLINED" if action == "DECLINE_HUMAN" else "ACCEPTED"
        invitation["responded_at"] = at
        if action == "ACCEPT_HUMAN":
            state["members"][actor] = {"membership_id": target, "member_pubkey": actor,
                "role_id": invitation["proposed_role"], "status": "ACTIVE",
                "valid_from": invitation["valid_from"], "expires_at": invitation["expires_at"],
                "invited_by": invitation["invited_by"], "accepted_at": at}
            state["roles"][actor] = invitation["proposed_role"]
            if invitation["proposed_role"] == "LEGAL_REPRESENTATIVE":
                org["legal_representative_status"] = "UNVERIFIED"
        elif action == "ACCEPT_AGENT":
            state["agents"][invitation["subject_id"]] = {
                "membership_id": target, "agent_account": invitation["subject_id"],
                **invitation["registration"], "registration_snapshot_hash": digest(invitation["registration"]),
                "membership_status": "ACTIVE", "status": "ACTIVE", "invited_by": invitation["invited_by"],
                "consented_by": actor, "consented_at": at, "valid_from": invitation["valid_from"],
                "expires_at": invitation["expires_at"]}
    elif action in {"SUSPEND_MEMBER", "REINSTATE_MEMBER", "REMOVE_MEMBER", "ASSIGN_ROLE", "REVOKE_ROLE"}:
        member = state["members"].get(target)
        if not member or target == org["owner_pubkey"]:
            _reject("ROOT_PROTECTED", "Root owner cannot be changed through membership actions", 403)
        if action == "SUSPEND_MEMBER" and member["status"] == "ACTIVE":
            member["status"], member["suspended_at"] = "SUSPENDED", at
        elif action == "REINSTATE_MEMBER" and member["status"] == "SUSPENDED" and at < member["expires_at"]:
            member["status"] = "ACTIVE"
        elif action == "REMOVE_MEMBER" and member["status"] in ("ACTIVE", "SUSPENDED"):
            member["status"], member["removed_at"] = "REMOVED", at
            for delegation in state["delegations"].values():
                if delegation["delegator_pubkey"] == target or delegation["delegate_pubkey"] == target:
                    delegation["status"] = "REVOKED"
            for invitation in state["invitations"].values():
                if invitation["invited_by"] == target and invitation["status"] == "INVITED":
                    invitation["status"] = "REVOKED"
        elif action == "ASSIGN_ROLE" and _member_active(member, at):
            role = payload.get("role_id")
            if role not in ROLES or role == "OWNER" or (role == "LEGAL_REPRESENTATIVE" and
                    target != org.get("legal_representative_pubkey")) or actor == target:
                _reject("ROLE_ESCALATION", "Role assignment is not authorized", 403)
            state["roles"][target] = role
            member["role_id"] = role
        elif action == "REVOKE_ROLE" and _member_active(member, at):
            state["roles"][target] = "MEMBER"
            member["role_id"] = "MEMBER"
        else:
            _reject("INVALID_TRANSITION", "Membership transition not allowed", 422)
    elif action == "CREATE_DELEGATION":
        if not ID.fullmatch(target) or not target.startswith("del_") or target in state["delegations"]:
            _reject("DELEGATION_CONFLICT", "Delegation identifier already used", 409)
        delegate = pubkey(payload.get("delegate_pubkey"))
        permission = payload.get("permission")
        origin = state["members"].get(actor)
        origin_role = state["roles"].get(actor, origin.get("role_id") if origin else None)
        if (not _member_active(state["members"].get(delegate), at) or delegate == actor or
                permission not in PERMISSIONS or permission not in ROLES.get(origin_role, ()) or
                permission in {"delegations.create", "roles.assign", "roles.revoke"}):
            _reject("DELEGATION_ESCALATION", "Delegation exceeds current base role", 403)
        scope = _text(payload.get("resource_scope"), "resource_scope", 128)
        start, end = _int(payload.get("valid_from"), "valid_from"), _int(payload.get("expires_at"), "expires_at")
        if (not at-300 <= start < end <= min(origin["expires_at"], state["members"][delegate]["expires_at"]) or
                end <= at or end > at + 30*86400):
            _reject("INVALID_VALIDITY", "Delegation must expire within both memberships", 422)
        state["delegations"][target] = {"delegation_id": target, "delegator_pubkey": actor,
            "delegate_pubkey": delegate, "permission": permission, "resource_scope": scope,
            "valid_from": start, "expires_at": end, "status": "ACTIVE", "created_at": at}
    elif action == "REVOKE_DELEGATION":
        delegation = state["delegations"].get(target)
        if not delegation or delegation["status"] != "ACTIVE":
            _reject("INVALID_TRANSITION", "Delegation cannot be revoked", 422)
        if actor != org["owner_pubkey"] and actor != delegation["delegator_pubkey"]:
            _reject("FORBIDDEN", "Only root owner or delegator may revoke", 403)
        delegation["status"], delegation["revoked_at"] = "REVOKED", at
    elif action == "REMOVE_AGENT":
        agent = state["agents"].get(target)
        if not agent or agent["status"] != "ACTIVE":
            _reject("INVALID_TRANSITION", "Agent is not linked", 422)
        agent["status"], agent["removed_at"] = "REMOVED", at
    org["version"] += 1
    org["updated_at"] = at
    return state


class OrganizationStore:
    def __init__(self, path: str | Path, agent_snapshot: Callable[[], dict] | None = None):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.lock = threading.RLock()
        self.agent_snapshot = agent_snapshot
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS organization_index (
                organization_id TEXT PRIMARY KEY, organization_slug TEXT NOT NULL UNIQUE,
                owner_pubkey TEXT NOT NULL, created_at INTEGER NOT NULL,
                head_version INTEGER NOT NULL DEFAULT 0, head_hash TEXT NOT NULL DEFAULT '');
            CREATE TABLE IF NOT EXISTS organization_events (
                event_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL REFERENCES organization_index(organization_id),
                version INTEGER NOT NULL, actor_pubkey TEXT NOT NULL, event_type TEXT NOT NULL,
                target_type TEXT NOT NULL, target_id TEXT NOT NULL,
                body_json TEXT NOT NULL, signature TEXT NOT NULL, signature_message TEXT NOT NULL,
                previous_state_hash TEXT NOT NULL, new_state_hash TEXT NOT NULL,
                previous_event_hash TEXT NOT NULL, event_hash TEXT NOT NULL,
                occurred_at INTEGER NOT NULL, nonce TEXT NOT NULL UNIQUE,
                idempotency_key TEXT NOT NULL UNIQUE,
                UNIQUE(organization_id,version));
            CREATE INDEX IF NOT EXISTS org_events_scope ON organization_events(organization_id,version);
            CREATE TRIGGER IF NOT EXISTS immutable_org_events_update BEFORE UPDATE ON organization_events
            BEGIN SELECT RAISE(ABORT,'organization events are immutable'); END;
            CREATE TRIGGER IF NOT EXISTS immutable_org_events_delete BEFORE DELETE ON organization_events
            BEGIN SELECT RAISE(ABORT,'organization events are immutable'); END;
        """)

    def close(self):
        self.conn.close()

    def _load(self, organization_id: str) -> tuple[dict | None, list[dict]]:
        rows = self.conn.execute("SELECT * FROM organization_events WHERE organization_id=? ORDER BY version",
                                 (organization_id,)).fetchall()
        state, previous_hash, previous_at = None, "0"*64, 0
        events = []
        for row in rows:
            try:
                body = json.loads(row["body_json"])
                if row["body_json"] != canonical(body).decode("utf-8"):
                    raise ValueError("noncanonical event body")
                path = "/v1/organizations" if body["action"] == "CREATE" else f"/v1/organizations/{organization_id}/actions"
                message = mutation_message("POST", path, body)
                if (body["organization_id"] != organization_id or
                        row["event_id"] != "oe_" + digest([organization_id, body["idempotency_key"]])[:32] or
                        not body["issued_at"] <= row["occurred_at"] < body["expires_at"] or
                        row["occurred_at"] < previous_at or
                        row["version"] != len(events)+1 or row["actor_pubkey"] != body["actor_pubkey"] or
                        row["event_type"] != body["action"] or row["target_type"] != body["target_type"] or
                        row["target_id"] != body["target_id"] or row["nonce"] != body["nonce"] or
                        row["idempotency_key"] != body["idempotency_key"] or
                        row["signature_message"] != message.decode() or
                        row["previous_event_hash"] != previous_hash or
                        row["previous_state_hash"] != digest(state)):
                    raise ValueError("event sequence mismatch")
                _verify(body["actor_pubkey"], row["signature"], message)
                state = _apply(state, body, row["occurred_at"])
                if row["new_state_hash"] != digest(state):
                    raise ValueError("state mismatch")
                event = {key: row[key] for key in row.keys() if key not in ("body_json",)}
                event["body"] = body
                calculated = digest({key: event[key] for key in event if key != "event_hash"})
                if calculated != row["event_hash"]:
                    raise ValueError("event hash mismatch")
                previous_hash = row["event_hash"]
                previous_at = row["occurred_at"]
                events.append(event)
            except (ValueError, KeyError, TypeError, OrganizationError) as exc:
                raise OrganizationError(409, "AUDIT_INTEGRITY_CONFLICT", "Organization history is inconsistent") from exc
        index = self.conn.execute("SELECT * FROM organization_index WHERE organization_id=?", (organization_id,)).fetchone()
        if (index is None) != (state is None) or state is not None and (
                index["organization_slug"] != state["organization"]["organization_slug"] or
                index["owner_pubkey"] != state["organization"]["owner_pubkey"] or
                index["created_at"] != state["organization"]["created_at"] or
                index["head_version"] != len(events) or index["head_hash"] != previous_hash):
            _reject("AUDIT_INTEGRITY_CONFLICT", "Organization index is inconsistent")
        return state, events

    def mutate(self, body: dict, signature: str, message: bytes, actor: str) -> tuple[dict, bool]:
        org_id = body["organization_id"]
        authenticated_at = int(time.time())
        if (type(body.get("issued_at")) is not int or type(body.get("expires_at")) is not int or
                not body["issued_at"] <= authenticated_at < body["expires_at"] or
                authenticated_at - body["issued_at"] > 300):
            _reject("EXPIRED_CREDENTIALS", "Signed organization mutation expired", 401)
        path = "/v1/organizations" if body["action"] == "CREATE" else f"/v1/organizations/{org_id}/actions"
        if actor != body["actor_pubkey"] or message != mutation_message("POST", path, body):
            _reject("INVALID_SIGNATURE", "Signed organization payload mismatch", 401)
        _verify(actor, signature, message)
        with self.lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                state, events = self._load(org_id)
                previous = self.conn.execute(
                    "SELECT * FROM organization_events WHERE idempotency_key=? OR nonce=?",
                    (body["idempotency_key"], body["nonce"])).fetchone()
                if previous is not None:
                    if (previous["organization_id"] != org_id or previous["actor_pubkey"] != actor or
                            previous["idempotency_key"] != body["idempotency_key"] or
                            previous["nonce"] != body["nonce"] or previous["body_json"] != canonical(body).decode()):
                        _reject("IDEMPOTENCY_CONFLICT", "Mutation key or nonce was reused")
                    if state is None:
                        _reject("FORBIDDEN", "Current identity is unavailable", 403)
                    if actor in state["members"] and not _member_active(state["members"][actor], int(time.time())):
                        _reject("FORBIDDEN", "Current membership is inactive", 403)
                    if actor not in state["members"]:
                        invitation = state["invitations"].get(body["target_id"])
                        registration = invitation.get("registration") if invitation else None
                        if not (body["action"] == "ACCEPT_AGENT" and registration and
                                _fresh_agent(self.agent_snapshot, registration["agent_account"]) == registration and
                                registration["agent_owner_pubkey"] == actor):
                            _reject("FORBIDDEN", "Current identity is unavailable", 403)
                    self.conn.execute("COMMIT")
                    return state["organization"], False
                if (state is not None and actor != state["organization"]["owner_pubkey"] and
                        actor not in state["members"] and not any(
                            inv["status"] == "INVITED" and
                            (inv["subject_id"] == actor or (inv.get("registration") or {}).get("agent_owner_pubkey") == actor)
                            for inv in state["invitations"].values())):
                    _reject("FORBIDDEN", "Actor is outside organization", 403)
                if body["action"] in ("INVITE_AGENT", "ACCEPT_AGENT"):
                    registration = (body["payload"].get("registration") if body["action"] == "INVITE_AGENT"
                        else state["invitations"].get(body["target_id"], {}).get("registration") if state else None)
                    if not isinstance(registration, dict) or _fresh_agent(self.agent_snapshot,
                            registration.get("agent_account", "")) != registration:
                        _reject("AGENT_IDENTITY_CHANGED", "Current AgentAccount differs from signed snapshot")
                committed_at = int(time.time())
                if events and committed_at < events[-1]["occurred_at"]:
                    _reject("CLOCK_CONFLICT", "Organization event clock moved backwards")
                previous_state_hash = digest(state)
                next_state = _apply(state, body, committed_at)
                if body["action"] in ("INVITE_AGENT", "ACCEPT_AGENT") and _fresh_agent(
                        self.agent_snapshot, registration["agent_account"]) != registration:
                    _reject("AGENT_IDENTITY_CHANGED", "AgentAccount changed before commit")
                if body["action"] == "CREATE":
                    self.conn.execute("INSERT INTO organization_index VALUES (?,?,?,?,?,?)",
                        (org_id, next_state["organization"]["organization_slug"], actor, committed_at,
                         0, ""))
                previous_event_hash = events[-1]["event_hash"] if events else "0"*64
                event = {"event_id": "oe_" + digest([org_id, body["idempotency_key"]])[:32],
                    "organization_id": org_id, "version": next_state["organization"]["version"],
                    "actor_pubkey": actor, "event_type": body["action"],
                    "target_type": body["target_type"], "target_id": body["target_id"],
                    "signature": signature, "signature_message": message.decode(),
                    "previous_state_hash": previous_state_hash, "new_state_hash": digest(next_state),
                    "previous_event_hash": previous_event_hash, "occurred_at": committed_at,
                    "nonce": body["nonce"], "idempotency_key": body["idempotency_key"], "body": body}
                event_hash = digest(event)
                self.conn.execute("INSERT INTO organization_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (event["event_id"], org_id, event["version"], actor, body["action"],
                     body["target_type"], body["target_id"], canonical(body).decode(), signature,
                     message.decode(), event["previous_state_hash"], event["new_state_hash"],
                     previous_event_hash, event_hash, committed_at, body["nonce"], body["idempotency_key"]))
                self.conn.execute("UPDATE organization_index SET head_version=?,head_hash=? WHERE organization_id=?",
                                  (event["version"], event_hash, org_id))
                self.conn.execute("COMMIT")
                return next_state["organization"], True
            except sqlite3.IntegrityError as exc:
                self.conn.execute("ROLLBACK")
                raise OrganizationError(409, "ORGANIZATION_CONFLICT", "Organization slug or identifier already used") from exc
            except Exception:
                self.conn.execute("ROLLBACK")
                raise

    def read(self, organization_id: str, actor: str, section: str | None = None,
             now: int | None = None):
        at = int(time.time()) if now is None else now
        with self.lock:
            state, events = self._load(organization_id)
            if state is None:
                _reject("NOT_FOUND", "Organization not found", 404)
            if (state["organization"]["organization_status"] != "ACTIVE" and
                    actor != state["organization"]["owner_pubkey"]):
                _reject("NOT_FOUND", "Organization resource not found", 404)
            invited = [item for item in state["invitations"].values() if item["status"] == "INVITED" and
                       item["valid_from"] <= at < item["expires_at"] and
                       (item["subject_type"] == "HUMAN" and item["subject_id"] == actor or
                        item["subject_type"] == "AGENT" and item["registration"]["agent_owner_pubkey"] == actor and
                        _fresh_agent(self.agent_snapshot, item["subject_id"]) == item["registration"])]
            if invited and not _member_active(state["members"].get(actor), at):
                if section is None:
                    return {"organization": state["organization"], "pending_invitations": invited,
                            "permissions": []}
                if section == "invitations":
                    return invited
                _reject("NOT_FOUND", "Organization resource not found", 404)
            permission = READ_PERMISSION.get(section, "organization.read")
            if state["organization"]["organization_status"] == "SUSPENDED" and actor == state["organization"]["owner_pubkey"]:
                if section is None:
                    return {"organization": state["organization"],
                            "permissions": ["organization.read", "organization.update_metadata"],
                            "member_count": 0, "agent_count": 0}
                _reject("NOT_FOUND", "Organization resource not found", 404)
            try:
                decision = _scope(state, actor, permission, "organization", at)
            except OrganizationError:
                _reject("NOT_FOUND", "Organization resource not found", 404)
            if section == "members":
                return list(state["members"].values())
            if section == "agents":
                output = []
                for item in state["agents"].values():
                    fresh = _fresh_agent(self.agent_snapshot, item["agent_account"])
                    same = fresh is not None and all(fresh.get(key) == item.get(key) for key in
                        ("agent_id", "agent_owner_pubkey", "network", "genesis_hash", "program_id"))
                    effective = ("REMOVED" if item["status"] == "REMOVED" else "ACTIVE" if
                        (same and fresh["active"] and fresh["agent_status"] == "Active" and
                         item["valid_from"] <= at < item["expires_at"]) else "REVIEW_REQUIRED")
                    output.append({**item, "effective_status": effective,
                                   "current_owner_pubkey": fresh.get("agent_owner_pubkey") if fresh else None})
                return output
            if section == "invitations":
                return [{**item, "effective_status": "EXPIRED" if item["status"] == "INVITED" and
                         at >= item["expires_at"] else item["status"]} for item in state["invitations"].values()]
            if section == "delegations":
                return list(state["delegations"].values())
            if section == "roles":
                return {"catalog": {role: sorted(perms) for role, perms in ROLES.items()},
                        "assignments": state["roles"]}
            if section == "audit-events":
                return events
            if section == "permissions":
                return decision
            return {"organization": state["organization"], "permissions": decision["effective_permissions"],
                    "member_count": sum(_member_active(m, at) for m in state["members"].values()),
                    "agent_count": sum(a["status"] == "ACTIVE" for a in state["agents"].values())}

    def list_for(self, actor: str) -> list[dict]:
        with self.lock:
            ids = [row[0] for row in self.conn.execute("SELECT organization_id FROM organization_index ORDER BY created_at DESC")]
        result = []
        for org_id in ids:
            try:
                result.append(self.read(org_id, actor))
            except OrganizationError as exc:
                if exc.code != "NOT_FOUND":
                    raise
        return result
