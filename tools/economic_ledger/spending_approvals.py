"""CON-29 owner consent for CON-28 decisions; strictly off-chain and non-executable."""
from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Any, Callable

from cryptography.hazmat.primitives.asymmetric import ed25519

from .budget_policies import BudgetPolicyStore, PolicyError, canonical, digest, pubkey
from .spending_decisions import DecisionError, SpendingDecisionStore, SpendingProposal

DOMAIN = "conatus:spending-approval:v1"
ACTIONS = frozenset({"OPEN", "APPROVE", "REJECT", "REVOKE"})
CONTEXT_FIELDS = frozenset({
    "agent_account", "agent_id", "owner_pubkey", "proposal_id", "proposal_hash",
    "decision_id", "decision_hash", "policy_id", "policy_version", "policy_hash",
    "network", "genesis_hash", "program_id", "token_mint", "recipient_pubkey",
    "amount_base_units_str", "economic_snapshot_hash",
})
CONTROL_FIELDS = frozenset({"action", "issued_at", "expires_at", "nonce", "idempotency_key", "reason"})


class ApprovalError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code = status, code


def approval_id(account: str, decision_id: str, owner: str) -> str:
    return "sa_" + digest([account, decision_id, owner])[:32]


def validate_mutation(body: Any, action: str, now: int | None = None) -> None:
    if action not in ACTIONS:
        raise ApprovalError(400, "INVALID_APPROVAL", "Unknown approval action")
    if not isinstance(body, dict) or set(body) != CONTEXT_FIELDS | CONTROL_FIELDS or body.get("action") != action:
        raise ApprovalError(400, "INVALID_APPROVAL", "Approval body must contain the exact signed fields")
    try:
        if len(canonical(body)) > 8192:
            raise ApprovalError(400, "APPROVAL_TOO_LARGE", "Approval body is too large")
    except (TypeError, ValueError) as exc:
        raise ApprovalError(400, "INVALID_APPROVAL", "Approval body must be canonical JSON") from exc
    for field, minimum in (("nonce", 16), ("idempotency_key", 8)):
        if not isinstance(body[field], str) or not re.fullmatch(rf"[A-Za-z0-9._:-]{{{minimum},128}}", body[field]):
            raise ApprovalError(400, "INVALID_APPROVAL", f"Invalid {field}")
    if type(body["issued_at"]) is not int or type(body["expires_at"]) is not int:
        raise ApprovalError(400, "INVALID_TIMESTAMP", "Approval timestamps must be Unix seconds")
    if abs((int(time.time()) if now is None else now) - body["issued_at"]) > 300:
        raise ApprovalError(401, "EXPIRED_CREDENTIALS", "Approval signature timestamp expired")
    if not isinstance(body["reason"], str) or len(body["reason"]) > 500:
        raise ApprovalError(400, "INVALID_REASON", "Reason must be at most 500 characters")
    if action in ("REJECT", "REVOKE") and not body["reason"].strip():
        raise ApprovalError(400, "INVALID_REASON", "Rejection and revocation require a reason")
    for field in ("agent_account", "owner_pubkey", "genesis_hash", "program_id", "token_mint", "recipient_pubkey"):
        try:
            pubkey(body[field], field)
        except PolicyError as exc:
            raise ApprovalError(400, "INVALID_PUBKEY", str(exc)) from exc
    if not isinstance(body["agent_id"], str) or not re.fullmatch(r"[0-9a-fA-F]{64}", body["agent_id"]):
        raise ApprovalError(400, "INVALID_AGENT_ID", "Invalid agent ID")
    for field in ("proposal_hash", "decision_hash", "policy_hash", "economic_snapshot_hash"):
        if not isinstance(body[field], str) or not re.fullmatch(r"[0-9a-f]{64}", body[field]):
            raise ApprovalError(400, "INVALID_HASH", f"Invalid {field}")
    if (not isinstance(body["proposal_id"], str) or not isinstance(body["decision_id"], str) or
            not isinstance(body["policy_id"], str) or not isinstance(body["network"], str) or
            type(body["policy_version"]) is not int or body["policy_version"] < 1 or
            not isinstance(body["amount_base_units_str"], str) or
            not re.fullmatch(r"(0|[1-9][0-9]*)", body["amount_base_units_str"]) or
            int(body["amount_base_units_str"]) > 2**64 - 1):
        raise ApprovalError(400, "INVALID_CONTEXT", "Invalid approval context")


def canonical_approval_message(timestamp: int, account: str, owner: str, method: str,
                               path: str, body: dict[str, Any]) -> bytes:
    """Domain-separated bytes shared exactly with the TypeScript SDK."""
    return (f"{DOMAIN}:{timestamp}:{account}:{body['agent_id']}:{owner}:{method}:{path}:"
            f"{digest(body)}:{body['nonce']}:{body['idempotency_key']}:"
            f"{body['proposal_id']}:{body['proposal_hash']}:"
            f"{body['decision_id']}:{body['decision_hash']}:"
            f"{body['policy_id']}:{body['policy_version']}:{body['policy_hash']}:"
            f"{body['expires_at']}").encode("utf-8")


def verify_approval(agent: dict, method: str, path: str, body: dict, headers: Any,
                    now: int | None = None) -> tuple[str, str, str]:
    h = {str(k).lower(): str(v) for k, v in headers.items()} if headers else {}
    signer, timestamp, signature = h.get("x-signer-pubkey"), h.get("x-timestamp"), h.get("x-signature")
    if not signer or not timestamp or not signature:
        raise ApprovalError(401, "UNAUTHORIZED", "Signed owner approval headers are required")
    if signer != agent.get("owner") or signer != body.get("owner_pubkey"):
        raise ApprovalError(403, "FORBIDDEN", "Only the current AgentAccount owner may consent")
    if body.get("agent_account") != agent.get("agent_account") or body.get("agent_id") != agent.get("agent_id"):
        raise ApprovalError(403, "AGENT_IDENTITY_MISMATCH", "Approval identity differs from current agent")
    try:
        ts = int(timestamp)
        if ts != body["issued_at"] or abs((int(time.time()) if now is None else now) - ts) > 300:
            raise ApprovalError(401, "EXPIRED_CREDENTIALS", "Approval signature timestamp expired")
        from tools.discovery.agent_discovery import b58decode
        message = canonical_approval_message(ts, agent["agent_account"], signer, method, path, body)
        ed25519.Ed25519PublicKey.from_public_bytes(b58decode(signer, 32)).verify(
            b58decode(signature, 64), message)
    except ApprovalError:
        raise
    except Exception as exc:
        raise ApprovalError(401, "INVALID_SIGNATURE", "Invalid owner Ed25519 approval signature") from exc
    return signer, signature, hashlib.sha256(message).hexdigest()


class SpendingApprovalStore:
    def __init__(self, ledger, policy_store: BudgetPolicyStore, decision_store: SpendingDecisionStore):
        self.conn, self.policies, self.decisions = ledger._conn, policy_store, decision_store

    def _policy(self, agent: dict) -> dict:
        try:
            return self.policies.current(agent)
        except PolicyError as exc:
            raise ApprovalError(404, "APPROVAL_NOT_FOUND", "Approval not found for current identity") from exc

    def _context(self, agent: dict, decision_id: str) -> tuple[dict, dict, dict]:
        row = self.conn.execute(
            "SELECT p.*, d.decision_json, d.decision, d.economic_snapshot_json, d.economic_snapshot_hash "
            "FROM spending_proposals p JOIN spending_decisions d ON d.proposal_id=p.proposal_id "
            "WHERE d.decision_id=? AND p.agent_account=? AND p.agent_id=? AND p.owner_pubkey=?",
            (decision_id, agent.get("agent_account"), agent.get("agent_id"), agent.get("owner"))).fetchone()
        if row is None:
            raise ApprovalError(404, "DECISION_NOT_FOUND", "Decision not found for current identity")
        try:
            proposal = json.loads(row["payload_json"])
            decision = json.loads(row["decision_json"])
            economics = json.loads(row["economic_snapshot_json"])
            SpendingProposal.parse(proposal)
            if (digest(proposal) != row["proposal_hash"] or
                    (proposal["agent_account"], proposal["agent_id"], proposal["network"],
                     proposal["genesis_hash"], proposal["program_id"], proposal["token_mint"],
                     proposal["recipient_pubkey"], proposal["amount_base_units_str"]) !=
                    (row["agent_account"], row["agent_id"], row["network"], row["genesis_hash"],
                     row["program_id"], row["token_mint"], row["recipient_pubkey"], row["amount_base_units_str"]) or
                    digest(economics) != row["economic_snapshot_hash"] or
                    decision["proposal_id"] != row["proposal_id"] or
                    decision["decision"] != row["decision"] or
                    decision["economic_snapshot_hash"] != row["economic_snapshot_hash"] or
                    (decision["policy_id"], decision["policy_version"], decision["policy_hash"]) !=
                    (proposal["expected_policy_id"], proposal["expected_policy_version"],
                     proposal["expected_policy_hash"]) or
                    (decision["agent_account"], decision["network"], decision["genesis_hash"],
                     decision["program_id"], decision["token_mint"], decision["requested_amount_base_units_str"]) !=
                    (row["agent_account"], row["network"], row["genesis_hash"], row["program_id"],
                     row["token_mint"], row["amount_base_units_str"])):
                raise ValueError("Stored proposal or decision mismatch")
        except (DecisionError, KeyError, TypeError, ValueError) as exc:
            raise ApprovalError(409, "AUDIT_INTEGRITY_CONFLICT", "Stored economic evidence is inconsistent") from exc
        context = {
            "agent_account": row["agent_account"], "agent_id": row["agent_id"],
            "owner_pubkey": row["owner_pubkey"], "proposal_id": row["proposal_id"],
            "proposal_hash": row["proposal_hash"], "decision_id": decision_id,
            "decision_hash": digest(decision), "policy_id": decision["policy_id"],
            "policy_version": decision["policy_version"], "policy_hash": decision["policy_hash"],
            "network": row["network"], "genesis_hash": row["genesis_hash"],
            "program_id": row["program_id"], "token_mint": row["token_mint"],
            "recipient_pubkey": row["recipient_pubkey"],
            "amount_base_units_str": row["amount_base_units_str"],
            "economic_snapshot_hash": row["economic_snapshot_hash"],
        }
        return context, proposal, decision

    def context(self, agent: dict, decision_id: str) -> dict:
        with self.policies._lock:
            self._policy(agent)
            context, proposal, decision = self._context(agent, decision_id)
            return {**context, "approval_id": approval_id(agent["agent_account"], decision_id, agent["owner"]),
                    "proposal": proposal, "decision": decision}

    def _events(self, approval_id_value: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM spending_approval_events WHERE approval_id=? ORDER BY rowid",
            (approval_id_value,)).fetchall()
        events = [dict(row) for row in rows]
        previous = None
        for event in events:
            try:
                from tools.discovery.agent_discovery import b58decode
                message = event["signature_message"].encode("utf-8")
                signed_body = json.loads(event["signed_body_json"])
                signed_path = f"/v1/agents/{signed_body['agent_account']}/spending-approvals"
                if event["action"] != "OPEN":
                    signed_path += f"/{approval_id_value}/{event['action'].lower()}"
                ed25519.Ed25519PublicKey.from_public_bytes(b58decode(event["actor_pubkey"], 32)).verify(
                    b58decode(event["signature"], 64), message)
                valid = (event["previous_event_hash"] == previous and
                         event["event_hash"] == digest({key: value for key, value in event.items() if key != "event_hash"}) and
                         hashlib.sha256(message).hexdigest() == event["signature_message_hash"] and
                         digest(signed_body) == event["body_hash"] and
                         signed_body["action"] == event["action"] and
                         signed_body["idempotency_key"] == event["idempotency_key"] and
                         signed_body["nonce"] == event["nonce"] and
                         canonical_approval_message(signed_body["issued_at"], signed_body["agent_account"],
                                                    event["actor_pubkey"], "POST", signed_path, signed_body) == message)
            except Exception:
                valid = False
            if not valid:
                raise ApprovalError(409, "AUDIT_INTEGRITY_CONFLICT", "Approval event history is inconsistent")
            previous = event["event_hash"]
        return events

    def _view(self, agent: dict, row: Any, now: int) -> dict:
        events = self._events(row["approval_id"])
        if not events:
            raise ApprovalError(409, "AUDIT_INTEGRITY_CONFLICT", "Approval history is missing")
        state = {"OPEN": "PENDING_REVIEW", "APPROVE": "APPROVED", "REJECT": "REJECTED", "REVOKE": "REVOKED"}[events[-1]["action"]]
        effective = "EXPIRED" if state in ("PENDING_REVIEW", "APPROVED") and now >= row["expires_at"] else state
        try:
            decision = self.decisions.get(agent, row["decision_id"], now=now)
            economic_applicable = decision["is_currently_applicable"]
        except Exception:
            economic_applicable = False
        applicable = state == "APPROVED" and effective == "APPROVED" and economic_applicable
        return {
            **dict(row), "approval_status": state, "effective_status": effective,
            "last_event_id": events[-1]["event_id"], "approved_by": next(
                (event["actor_pubkey"] for event in events if event["action"] == "APPROVE"), None),
            "approved_at": next((event["occurred_at"] for event in events if event["action"] == "APPROVE"), None),
            "financial_eligibility": "ELIGIBLE_FOR_FUTURE_STAGE" if applicable else "NOT_EXECUTION_ELIGIBLE",
            "is_currently_applicable": applicable, "is_executable": False,
        }

    def list(self, agent: dict, now: int | None = None) -> list[dict]:
        at = int(time.time()) if now is None else now
        with self.policies._lock:
            self._policy(agent)
            rows = self.conn.execute(
                "SELECT * FROM spending_approvals WHERE agent_account=? AND agent_id=? AND owner_pubkey=? "
                "ORDER BY created_at DESC, approval_id DESC LIMIT 100",
                (agent["agent_account"], agent["agent_id"], agent["owner"])).fetchall()
            return [self._view(agent, row, at) for row in rows]

    def get(self, agent: dict, approval_id_value: str, now: int | None = None) -> dict:
        at = int(time.time()) if now is None else now
        with self.policies._lock:
            self._policy(agent)
            row = self.conn.execute(
                "SELECT * FROM spending_approvals WHERE approval_id=? AND agent_account=? AND agent_id=? AND owner_pubkey=?",
                (approval_id_value, agent["agent_account"], agent["agent_id"], agent["owner"])).fetchone()
            if row is None:
                raise ApprovalError(404, "APPROVAL_NOT_FOUND", "Approval not found for current identity")
            return self._view(agent, row, at)

    def history(self, agent: dict, approval_id_value: str) -> list[dict]:
        self.get(agent, approval_id_value)
        return self._events(approval_id_value)

    def mutate(self, agent: dict, action: str, body: dict, actor: str, signature: str,
               signature_message_hash: str, now: int | None = None,
               identity_supplier: Callable[[], dict | None] | None = None) -> tuple[dict, bool]:
        at = int(time.time()) if now is None else now
        validate_mutation(body, action, at)
        if actor != agent.get("owner") or body["owner_pubkey"] != actor:
            raise ApprovalError(403, "FORBIDDEN", "Only the current owner may consent")
        expected_id = approval_id(agent["agent_account"], body["decision_id"], actor)
        path = f"/v1/agents/{agent['agent_account']}/spending-approvals"
        if action != "OPEN":
            path += f"/{expected_id}/{action.lower()}"
        checked = verify_approval(agent, "POST", path, body, {
            "X-Signer-Pubkey": actor, "X-Timestamp": str(body["issued_at"]),
            "X-Signature": signature}, at)
        if checked[2] != signature_message_hash:
            raise ApprovalError(401, "INVALID_SIGNATURE", "Approval message hash mismatch")
        signed_message = canonical_approval_message(body["issued_at"], agent["agent_account"],
                                                    actor, "POST", path, body).decode("utf-8")
        with self.policies._lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                policy = self._policy(agent)
                context, proposal, decision = self._context(agent, body["decision_id"])
                if any(body[key] != context[key] for key in CONTEXT_FIELDS):
                    raise ApprovalError(409, "CONTEXT_CONFLICT", "Approval context differs from stored evidence")
                latest_policy = self._policy(agent)
                if (policy["policy_id"], policy["version"], policy["policy_hash"], policy["status"]) != (
                        latest_policy["policy_id"], latest_policy["version"],
                        latest_policy["policy_hash"], latest_policy["status"]):
                    raise ApprovalError(409, "POLICY_VERSION_CONFLICT", "Policy changed during approval")
                aid = expected_id
                existing = self.conn.execute("SELECT * FROM spending_approvals WHERE approval_id=?", (aid,)).fetchone()
                prior = self.conn.execute(
                    "SELECT * FROM spending_approval_events WHERE idempotency_key=? OR nonce=?",
                    (body["idempotency_key"], body["nonce"])).fetchone()
                if prior:
                    if (prior["idempotency_key"] != body["idempotency_key"] or prior["nonce"] != body["nonce"] or
                            prior["body_hash"] != digest(body) or prior["actor_pubkey"] != actor or
                            prior["approval_id"] != aid or prior["action"] != action or
                            prior["signature"] != signature or prior["signature_message_hash"] != signature_message_hash):
                        raise ApprovalError(409, "IDEMPOTENCY_CONFLICT", "Approval request identifier was reused")
                    if existing is None:
                        raise ApprovalError(409, "AUDIT_INTEGRITY_CONFLICT", "Approval review is missing")
                    current_events = self._events(aid)
                    if (action == "APPROVE" and (current_events[-1]["action"] != "APPROVE" or at >= existing["expires_at"])):
                        raise ApprovalError(409, "APPROVAL_NOT_CURRENT", "Prior approval cannot be restored")
                    if identity_supplier is not None:
                        live = identity_supplier()
                        if live is None or any(live.get(key) != agent.get(key) for key in
                                               ("agent_account", "agent_id", "owner")):
                            raise ApprovalError(403, "OWNER_CHANGED", "Agent identity changed")
                    result = self._view(agent, existing, at)
                    self.conn.execute("COMMIT")
                    return result, False
                if identity_supplier is not None:
                    live = identity_supplier()
                    if live is None or any(live.get(key) != agent.get(key) for key in
                                           ("agent_account", "agent_id", "owner")):
                        raise ApprovalError(403, "OWNER_CHANGED", "Agent identity changed")
                if action in ("OPEN", "APPROVE"):
                    if (policy["status"] != "ACTIVE" or at < policy["valid_from"] or at >= policy["expires_at"] or
                            (policy["policy_id"], policy["version"], policy["policy_hash"]) !=
                            (decision["policy_id"], decision["policy_version"], decision["policy_hash"])):
                        raise ApprovalError(409, "POLICY_VERSION_CONFLICT", "Current policy differs from decision")
                    if at >= decision["expires_at"]:
                        raise ApprovalError(422, "DECISION_EXPIRED", "A new economic evaluation is required")
                if action == "OPEN":
                    if existing is not None:
                        raise ApprovalError(409, "APPROVAL_EXISTS", "Review already exists")
                    if (body["expires_at"] <= at or body["expires_at"] > at + 3600 or
                            body["expires_at"] > decision["expires_at"] or body["expires_at"] > policy["expires_at"]):
                        raise ApprovalError(400, "INVALID_EXPIRY", "Review expiry must fit decision and policy validity")
                    self.conn.execute(
                        "INSERT INTO spending_approvals VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (aid, context["proposal_id"], context["decision_id"], context["agent_account"],
                         context["agent_id"], actor, context["network"], context["genesis_hash"],
                         context["program_id"], context["token_mint"], context["recipient_pubkey"],
                         context["amount_base_units_str"], context["proposal_hash"], context["decision_hash"],
                         context["economic_snapshot_hash"], context["policy_id"], context["policy_version"],
                         context["policy_hash"], at, body["expires_at"]))
                    previous = None
                else:
                    if existing is None:
                        raise ApprovalError(404, "APPROVAL_NOT_FOUND", "Review must be opened first")
                    if body["expires_at"] != existing["expires_at"]:
                        raise ApprovalError(409, "EXPIRY_CONFLICT", "Approval expiry cannot change")
                    events = self._events(aid)
                    previous = events[-1]["event_hash"]
                    state = events[-1]["action"]
                    if (action in ("APPROVE", "REJECT") and state != "OPEN") or (action == "REVOKE" and state != "APPROVE"):
                        raise ApprovalError(422, "INVALID_TRANSITION", "Approval transition is not permitted")
                    if action == "APPROVE":
                        if decision["decision"] == "DENY":
                            raise ApprovalError(422, "DECISION_DENIED", "A denied proposal cannot be approved")
                        if at >= existing["expires_at"]:
                            raise ApprovalError(422, "APPROVAL_EXPIRED", "Expired review requires a new evaluation")
                event_id = "ae_" + digest([aid, action, body["idempotency_key"], digest(body)])[:32]
                event_data = {"event_id": event_id, "approval_id": aid, "proposal_id": context["proposal_id"],
                              "decision_id": context["decision_id"], "action": action, "actor_pubkey": actor,
                              "policy_id": context["policy_id"], "policy_version": context["policy_version"],
                              "policy_hash": context["policy_hash"], "proposal_hash": context["proposal_hash"],
                              "decision_hash": context["decision_hash"], "occurred_at": at,
                              "reason": body["reason"], "signature": signature,
                              "signature_message_hash": signature_message_hash,
                              "signature_message": signed_message,
                              "signed_body_json": canonical(body).decode("utf-8"),
                              "idempotency_key": body["idempotency_key"], "nonce": body["nonce"],
                              "previous_event_hash": previous, "body_hash": digest(body)}
                self.conn.execute(
                    "INSERT INTO spending_approval_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (event_id, aid, context["proposal_id"], context["decision_id"], action, actor,
                     context["policy_id"], context["policy_version"], context["policy_hash"],
                     context["proposal_hash"], context["decision_hash"], at, body["reason"], signature,
                     signature_message_hash, signed_message, canonical(body).decode("utf-8"),
                     body["idempotency_key"], body["nonce"],
                     digest(event_data), previous, digest(body)))
                row = self.conn.execute("SELECT * FROM spending_approvals WHERE approval_id=?", (aid,)).fetchone()
                result = self._view(agent, row, at)
                self.conn.execute("COMMIT")
                return result, True
            except Exception:
                self.conn.execute("ROLLBACK")
                raise
