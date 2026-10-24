"""CON-28 advisory spending decisions. No payment or accounting mutation occurs here."""
from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass
from typing import Any, Callable

from cryptography.hazmat.primitives.asymmetric import ed25519

from .budget_policies import BudgetPolicyStore, PolicyError, amount, canonical, digest, pubkey
from .ledger import EconomicLedger, validate_monetary_context
from .models import LedgerValidationError

ENGINE_VERSION = "conatus.spending-decision.v1"
EVALUATION_DOMAIN = "conatus:spending-evaluation:v1"
PROPOSAL_FIELDS = frozenset({
    "proposal_id", "idempotency_key", "nonce", "agent_account", "agent_id",
    "requester_pubkey", "network", "genesis_hash", "program_id", "token_mint",
    "recipient_pubkey", "amount_base_units_str", "purpose", "requested_at",
    "expected_policy_id", "expected_policy_version", "expected_policy_hash", "metadata",
})
PRODUCTION_LINEAGES = frozenset({"LIVE_RPC", "EXTERNAL_ATTESTED"})


class DecisionError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code = status, code


@dataclass(frozen=True)
class SpendingProposal:
    proposal_id: str
    idempotency_key: str
    nonce: str
    agent_account: str
    agent_id: str
    requester_pubkey: str
    network: str
    genesis_hash: str
    program_id: str
    token_mint: str
    recipient_pubkey: str
    amount_base_units_str: str
    purpose: str
    requested_at: int
    expected_policy_id: str
    expected_policy_version: int
    expected_policy_hash: str
    metadata: dict[str, Any]

    @classmethod
    def parse(cls, body: Any) -> SpendingProposal:
        if not isinstance(body, dict) or set(body) != PROPOSAL_FIELDS:
            raise DecisionError(400, "INVALID_PROPOSAL", "Missing or unknown proposal fields")
        try:
            if len(canonical(body)) > 8192 or len(canonical(body["metadata"])) > 2048:
                raise DecisionError(400, "PROPOSAL_TOO_LARGE", "Proposal payload is too large")
        except (TypeError, ValueError) as exc:
            raise DecisionError(400, "INVALID_PROPOSAL", "Proposal must be canonical JSON") from exc
        for field in ("proposal_id", "idempotency_key", "nonce"):
            minimum = 16 if field == "nonce" else 8
            if not isinstance(body[field], str) or not re.fullmatch(rf"[A-Za-z0-9._:-]{{{minimum},128}}", body[field]):
                raise DecisionError(400, "INVALID_PROPOSAL", f"Invalid {field}")
        for field in ("agent_account", "requester_pubkey", "genesis_hash", "program_id", "token_mint", "recipient_pubkey"):
            try:
                pubkey(body[field], field)
            except PolicyError as exc:
                raise DecisionError(400, "INVALID_PUBKEY", str(exc)) from exc
        if not isinstance(body["agent_id"], str) or not re.fullmatch(r"[0-9a-fA-F]{64}", body["agent_id"]):
            raise DecisionError(400, "INVALID_AGENT_ID", "agent_id must be 32 bytes of hex")
        if not isinstance(body["network"], str) or not body["network"] or body["network"] == "PENDING_RESOLUTION":
            raise DecisionError(400, "INVALID_CONTEXT", "Resolved monetary network is required")
        try:
            validate_monetary_context(network=body["network"], genesis_hash=body["genesis_hash"],
                                      program_id=body["program_id"], token_mint=body["token_mint"])
        except LedgerValidationError as exc:
            raise DecisionError(422, "INVALID_CONTEXT", str(exc)) from exc
        if not isinstance(body["purpose"], str) or not 1 <= len(body["purpose"]) <= 500:
            raise DecisionError(400, "INVALID_PURPOSE", "Purpose must contain 1 to 500 characters")
        if not isinstance(body["metadata"], dict):
            raise DecisionError(400, "INVALID_METADATA", "Metadata must be a JSON object")
        if type(body["requested_at"]) is not int or body["requested_at"] < 0:
            raise DecisionError(400, "INVALID_TIMESTAMP", "requested_at must be Unix seconds")
        if not isinstance(body["expected_policy_id"], str) or not re.fullmatch(r"bp_[0-9a-f]{32}", body["expected_policy_id"]):
            raise DecisionError(400, "INVALID_POLICY_REFERENCE", "Expected policy ID is invalid")
        if type(body["expected_policy_version"]) is not int or body["expected_policy_version"] < 1:
            raise DecisionError(400, "INVALID_POLICY_REFERENCE", "Expected policy version is invalid")
        if not isinstance(body["expected_policy_hash"], str) or not re.fullmatch(r"[0-9a-f]{64}", body["expected_policy_hash"]):
            raise DecisionError(400, "INVALID_POLICY_REFERENCE", "Expected policy hash is invalid")
        if not isinstance(body["amount_base_units_str"], str) or not re.fullmatch(r"(0|[1-9][0-9]*)", body["amount_base_units_str"]):
            raise DecisionError(400, "INVALID_AMOUNT", "Amount must be an exact decimal u64 string")
        try:
            amount(body["amount_base_units_str"], "proposal amount")
        except PolicyError as exc:
            raise DecisionError(400, "INVALID_AMOUNT", str(exc)) from exc
        return cls(**body)


def evaluation_message(timestamp: int, account: str, requester: str, method: str,
                       path: str, body: dict[str, Any]) -> bytes:
    return (f"{EVALUATION_DOMAIN}:{timestamp}:{account}:{requester}:{method}:{path}:"
            f"{digest(body)}:{body['nonce']}:{body['idempotency_key']}:"
            f"{body['expected_policy_id']}:{body['expected_policy_version']}:"
            f"{body['expected_policy_hash']}").encode("utf-8")


def verify_evaluation(agent: dict[str, Any], method: str, path: str,
                      body: dict[str, Any], headers: Any, now: int | None = None) -> str:
    h = {str(k).lower(): str(v) for k, v in headers.items()} if headers else {}
    signer, timestamp, signature = h.get("x-signer-pubkey"), h.get("x-timestamp"), h.get("x-signature")
    if not signer or not timestamp or not signature:
        raise DecisionError(401, "UNAUTHORIZED", "Signed evaluation headers are required")
    try:
        pubkey(signer, "signer")
        ts = int(timestamp)
        if abs((int(time.time()) if now is None else now) - ts) > 300:
            raise DecisionError(401, "EXPIRED_CREDENTIALS", "Evaluation signature expired")
        from tools.discovery.agent_discovery import b58decode
        ed25519.Ed25519PublicKey.from_public_bytes(b58decode(signer, 32)).verify(
            b58decode(signature, 64), evaluation_message(ts, agent["agent_account"], signer, method, path, body))
    except DecisionError:
        raise
    except Exception as exc:
        raise DecisionError(401, "INVALID_SIGNATURE", "Invalid Ed25519 evaluation signature") from exc
    if signer != body.get("requester_pubkey"):
        raise DecisionError(403, "FORBIDDEN", "Authenticated requester differs from proposal")
    if signer not in (agent.get("owner"), agent.get("signing_authority")):
        raise DecisionError(403, "FORBIDDEN", "Requester is not the current owner or signing authority")
    return signer


def evaluate_spending_proposal(proposal: SpendingProposal, policy: dict[str, Any] | None,
                               economics: dict[str, Any], budget: dict[str, Any],
                               evaluated_at: int) -> dict[str, Any]:
    """Pure, time-explicit evaluator. DENY precedes uncertainty, which precedes ALLOW."""
    reasons: list[str] = []
    rule = None
    if policy is None:
        reasons.append("POLICY_NOT_FOUND")
    else:
        if (policy["agent_account"] != proposal.agent_account or policy["agent_id"] != proposal.agent_id or
                policy["owner_pubkey"] != economics.get("current_owner") or
                policy["agent_id"] != economics.get("current_agent_id")):
            reasons.append("AGENT_IDENTITY_MISMATCH")
        status = policy["status"]
        if status == "PAUSED": reasons.append("POLICY_PAUSED")
        elif status == "REVOKED": reasons.append("POLICY_REVOKED")
        elif status != "ACTIVE": reasons.append("POLICY_NOT_ACTIVE")
        if evaluated_at >= policy["expires_at"]: reasons.append("POLICY_EXPIRED")
        elif evaluated_at < policy["valid_from"]: reasons.append("POLICY_NOT_ACTIVE")
        if policy["policy_id"] != proposal.expected_policy_id or policy["version"] != proposal.expected_policy_version:
            reasons.append("POLICY_VERSION_MISMATCH")
        if policy["policy_hash"] != proposal.expected_policy_hash: reasons.append("POLICY_HASH_MISMATCH")
        if (policy["network"], policy["genesis_hash"], policy["program_id"]) != (
                proposal.network, proposal.genesis_hash, proposal.program_id):
            reasons.append("MONETARY_CONTEXT_MISMATCH")
        rule = next((r for r in policy["asset_rules"] if r["token_mint"] == proposal.token_mint), None)
        if rule is None or not rule["enabled"]: reasons.append("ASSET_NOT_ALLOWED")
        if proposal.recipient_pubkey not in policy["allowed_recipients"]:
            reasons.append("RECIPIENT_NOT_ALLOWED")
    proposed = int(proposal.amount_base_units_str)
    if proposed <= 0: reasons.append("INVALID_AMOUNT")
    if rule is not None and proposed > int(rule["max_per_operation_base_units_str"]):
        reasons.append("MAX_OPERATION_EXCEEDED")
    used, committed = budget.get("used"), budget.get("committed")
    daily_limit = int(rule["max_daily_spend_base_units_str"]) if rule else None
    if rule and budget.get("complete") and used is not None and committed is not None:
        if int(used) + int(committed) + proposed > daily_limit:
            reasons.append("DAILY_BUDGET_EXCEEDED")
    verified = economics.get("status") == "VERIFIED" or (
        economics.get("status") == "SYNTHETIC_TEST" and economics.get("allow_synthetic_test") is True)
    available, obligations, reserved = (economics.get(key) for key in ("available", "obligations", "reserved"))
    reserve_minimum = int(rule["minimum_reserve_base_units_str"]) if rule else None
    if verified and economics.get("complete") and all(x is not None for x in (available, obligations, reserved)) and rule:
        gap = max(0, reserve_minimum - int(reserved))
        capacity_before_claims = max(0, int(available) - int(obligations) - gap)
        capacity = max(0, capacity_before_claims - int(committed or 0))
        if proposed > capacity:
            reasons.append("MIN_RESERVE_COMPROMISED" if gap > 0 else "INSUFFICIENT_LIQUIDITY")
    if reasons:
        outcome = "DENY"
    else:
        uncertainty = []
        if economics.get("status") == "STALE": uncertainty.append("ECONOMIC_DATA_STALE")
        elif not verified: uncertainty.append("ECONOMIC_SOURCE_UNVERIFIED")
        if not economics.get("complete"): uncertainty.append("ECONOMIC_DATA_INSUFFICIENT")
        if available is None: uncertainty.append("TREASURY_BALANCE_UNKNOWN")
        if reserved is None or obligations is None: uncertainty.append("RESERVE_COVERAGE_UNCERTAIN")
        if not budget.get("complete") or used is None or committed is None:
            uncertainty.append("DAILY_SPEND_HISTORY_INCOMPLETE")
        if uncertainty: uncertainty.append("REQUIRES_OWNER_REVIEW")
        reasons = uncertainty
        outcome = "REQUIRE_APPROVAL" if uncertainty else "ALLOW"
    evidence_hash = digest({"economics": economics, "budget": budget})
    day_start = evaluated_at - evaluated_at % 86400
    expiry = min(evaluated_at + 300, day_start + 86400,
                 policy["expires_at"] if policy else evaluated_at + 300)
    decision_id = "sd_" + digest({"proposal": asdict(proposal), "policy": policy,
                                   "economics": economics, "budget": budget,
                                   "evaluated_at": evaluated_at, "engine": ENGINE_VERSION})[:32]
    return {
        "decision_id": decision_id, "proposal_id": proposal.proposal_id,
        "agent_account": proposal.agent_account, "decision": outcome,
        "reason_codes": reasons, "reason_details": [{"code": code} for code in reasons],
        "policy_id": policy["policy_id"] if policy else None,
        "policy_version": policy["version"] if policy else None,
        "policy_hash": policy["policy_hash"] if policy else None,
        "network": proposal.network, "genesis_hash": proposal.genesis_hash,
        "program_id": proposal.program_id, "token_mint": proposal.token_mint,
        "requested_amount_base_units_str": proposal.amount_base_units_str,
        "daily_window_start_utc": day_start, "daily_window_end_utc": day_start + 86400,
        "daily_limit_base_units_str": str(daily_limit) if daily_limit is not None else None,
        "daily_used_base_units_str": str(used) if used is not None else None,
        "daily_committed_base_units_str": str(committed) if committed is not None else None,
        "daily_remaining_base_units_str": str(max(0, daily_limit - int(used) - int(committed)))
        if daily_limit is not None and used is not None and committed is not None else None,
        "minimum_reserve_base_units_str": str(reserve_minimum) if reserve_minimum is not None else None,
        "accounting_reserved_base_units_str": str(reserved) if reserved is not None else None,
        "available_liquidity_base_units_str": str(available) if available is not None else None,
        "accrued_obligations_base_units_str": str(obligations) if obligations is not None else None,
        "economic_evidence_status": economics.get("status", "UNVERIFIED"),
        "economic_snapshot_hash": evidence_hash,
        "evaluated_at": evaluated_at, "expires_at": expiry,
        "decision_engine_version": ENGINE_VERSION, "is_executable": False,
        "historical": False, "is_currently_applicable": outcome == "ALLOW",
    }


class SpendingDecisionStore:
    """Atomic, append-only advisory evaluations and temporary capacity claims."""

    def __init__(self, ledger: EconomicLedger, policy_store: BudgetPolicyStore,
                 test_evidence_provider: Callable[..., tuple[dict, dict]] | None = None):
        self.ledger, self.policy_store, self.conn = ledger, policy_store, ledger._conn
        self.test_evidence_provider = test_evidence_provider

    def _ledger_snapshots(self, agent: dict, proposal: SpendingProposal, policy: dict | None,
                          now: int) -> tuple[dict, dict]:
        scope = (proposal.agent_account, proposal.network, proposal.genesis_hash,
                 proposal.program_id, proposal.token_mint)
        summaries = self.ledger.get_economic_summary(proposal.agent_account,
            network=proposal.network, genesis_hash=proposal.genesis_hash,
            program_id=proposal.program_id, token_mint=proposal.token_mint)
        summary = summaries[0] if len(summaries) == 1 else None
        reserve_rows = self.conn.execute(
            "SELECT reserve_id, current_reserved_base_units FROM agent_reserves WHERE agent_account=? AND network=? "
            "AND genesis_hash=? AND program_id=? AND token_mint=? AND status='ACTIVE'", scope).fetchall()
        reserved = sum(int(r["current_reserved_base_units"]) for r in reserve_rows)
        day_start = now - now % 86400
        movements = self.conn.execute(
            "SELECT movement_id, amount_base_units, evidence_lineage, status FROM economic_movements "
            "WHERE agent_account=? AND network=? AND genesis_hash=? AND program_id=? AND token_mint=? "
            "AND nature='EXPENSE' AND observed_at>=? AND observed_at<?",
            (*scope, day_start, day_start + 86400)).fetchall()
        costs = self.conn.execute(
            "SELECT cost_id, movement_id, amount_base_units, evidence_lineage, status FROM agent_costs "
            "WHERE agent_account=? AND network=? AND genesis_hash=? AND program_id=? AND token_mint=? "
            "AND cost_nature='REALIZED' AND incurred_at>=? AND incurred_at<?",
            (*scope, day_start, day_start + 86400)).fetchall()
        used = 0
        movement_ids = set()
        for row in movements:
            if row["status"] == "RECONCILED" and row["evidence_lineage"] in PRODUCTION_LINEAGES:
                used += int(row["amount_base_units"])
                movement_ids.add(row["movement_id"])
        for row in costs:
            if row["status"] == "RECONCILED" and row["evidence_lineage"] in PRODUCTION_LINEAGES and row["movement_id"] not in movement_ids:
                used += int(row["amount_base_units"])
        committed = 0
        if policy is not None:
            claims = self.conn.execute(
                "SELECT amount_base_units_str FROM spending_budget_claims WHERE agent_account=? AND network=? "
                "AND genesis_hash=? AND program_id=? AND token_mint=? AND policy_id=? AND policy_version=? "
                "AND day_start_utc=? AND expires_at>?",
                (*scope, policy["policy_id"], policy["version"], day_start, now)).fetchall()
            committed = sum(int(row["amount_base_units_str"]) for row in claims)
        # CON-34 has not supplied productive completeness/coverage. Ledger totals are
        # informative, but cannot by themselves authorize an autonomous spend.
        economics = {"status": "UNVERIFIED", "complete": False,
                     "current_owner": agent.get("owner"), "current_agent_id": agent.get("agent_id"),
                     "available": int(summary.available_balance_str) if summary else None,
                     "obligations": int(summary.total_obligations_accrued_str) if summary else None,
                     "reserved": reserved if summary else None,
                     "source_references": {
                         "movement_ids": sorted(row["movement_id"] for row in movements),
                         "cost_ids": sorted(row["cost_id"] for row in costs),
                         "reserve_ids": sorted(row["reserve_id"] for row in reserve_rows),
                     }}
        budget = {"used": used, "committed": committed, "complete": False, "day_start": day_start}
        return economics, budget

    def _applicable(self, decision: dict, policy: dict | None, now: int) -> bool:
        if decision["decision"] != "ALLOW" or policy is None or now >= decision["expires_at"]:
            return False
        if (decision["policy_id"], decision["policy_version"], decision["policy_hash"]) != (
                policy["policy_id"], policy["version"], policy["policy_hash"]):
            return False
        if policy["status"] != "ACTIVE" or now < policy["valid_from"] or now >= policy["expires_at"]:
            return False
        claim = self.conn.execute("SELECT expires_at FROM spending_budget_claims WHERE decision_id=?",
                                  (decision["decision_id"],)).fetchone()
        return claim is not None and now < claim["expires_at"]

    def evaluate(self, agent: dict, body: dict, requester: str, now: int | None = None,
                 identity_supplier: Callable[[], dict | None] | None = None) -> tuple[dict, bool]:
        proposal = SpendingProposal.parse(body)
        at = int(time.time()) if now is None else now
        if abs(at - proposal.requested_at) > 300:
            raise DecisionError(400, "STALE_PROPOSAL", "Proposal timestamp is outside the evaluation window")
        if (proposal.agent_account, proposal.agent_id, proposal.requester_pubkey) != (
                agent.get("agent_account"), agent.get("agent_id"), requester):
            raise DecisionError(403, "AGENT_IDENTITY_MISMATCH", "Proposal identity differs from current agent")
        if requester not in (agent.get("owner"), agent.get("signing_authority")) or not agent.get("owner"):
            raise DecisionError(403, "FORBIDDEN", "Current owner or signing authority is required")
        proposal_hash = digest(body)
        with self.policy_store._lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                try:
                    policy = self.policy_store.current(agent)
                except PolicyError as exc:
                    if exc.code != "POLICY_NOT_FOUND": raise
                    policy = None
                prior = self.conn.execute(
                    "SELECT * FROM spending_proposals WHERE idempotency_key=? OR proposal_id=? OR nonce=?",
                    (proposal.idempotency_key, proposal.proposal_id, proposal.nonce)).fetchone()
                if prior:
                    if (prior["proposal_hash"] != proposal_hash or prior["proposal_id"] != proposal.proposal_id or
                            prior["idempotency_key"] != proposal.idempotency_key or prior["nonce"] != proposal.nonce):
                        raise DecisionError(409, "IDEMPOTENCY_CONFLICT", "Proposal identifier was reused")
                    if (prior["agent_account"], prior["agent_id"], prior["owner_pubkey"], prior["requester_pubkey"]) != (
                            proposal.agent_account, proposal.agent_id, agent["owner"], requester):
                        raise DecisionError(404, "DECISION_NOT_FOUND", "Decision not found for current identity")
                    if identity_supplier is not None:
                        current_agent = identity_supplier()
                        if current_agent is None or any(current_agent.get(key) != agent.get(key) for key in
                                                        ("agent_account", "agent_id", "owner", "signing_authority")):
                            raise DecisionError(403, "AGENT_IDENTITY_MISMATCH", "Agent identity changed during evaluation")
                    row = self.conn.execute("SELECT decision_json FROM spending_decisions WHERE proposal_id=?",
                                            (proposal.proposal_id,)).fetchone()
                    result = json.loads(row["decision_json"])
                    result["historical"] = True
                    result["is_currently_applicable"] = self._applicable(result, policy, at)
                    self.conn.execute("COMMIT")
                    return result, False
                economics, budget = self._ledger_snapshots(agent, proposal, policy, at)
                if self.test_evidence_provider is not None:
                    ledger_committed = budget["committed"]
                    economics, budget = self.test_evidence_provider(agent, proposal, policy, at, economics, budget)
                    economics = {**economics, "status": "SYNTHETIC_TEST", "allow_synthetic_test": True,
                                 "agent_account": agent["agent_account"], "agent_id": agent["agent_id"],
                                 "owner_pubkey": agent["owner"]}
                    if int(budget.get("committed", -1)) < ledger_committed:
                        raise DecisionError(409, "BUDGET_SNAPSHOT_CONFLICT", "Test snapshot omitted active commitments")
                decision = evaluate_spending_proposal(proposal, policy, economics, budget, at)
                # Same SQLite transaction/connection as CON-27 mutations: a concurrent
                # version change cannot commit between this check and claim insertion.
                try:
                    latest = self.policy_store.current(agent)
                except PolicyError:
                    latest = None
                if (policy is None) != (latest is None) or (policy and latest and
                        (policy["version"], policy["policy_hash"]) != (latest["version"], latest["policy_hash"])):
                    raise DecisionError(409, "POLICY_VERSION_CONFLICT", "Policy changed during evaluation")
                if identity_supplier is not None:
                    current_agent = identity_supplier()
                    if current_agent is None or any(current_agent.get(key) != agent.get(key) for key in
                                                    ("agent_account", "agent_id", "owner", "signing_authority")):
                        raise DecisionError(403, "AGENT_IDENTITY_MISMATCH", "Agent identity changed during evaluation")
                self.conn.execute(
                    "INSERT INTO spending_proposals VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (proposal.proposal_id, proposal.idempotency_key, proposal.nonce, proposal_hash,
                     proposal.agent_account, proposal.agent_id, agent["owner"], requester,
                     proposal.network, proposal.genesis_hash, proposal.program_id,
                     proposal.token_mint, proposal.recipient_pubkey, proposal.amount_base_units_str,
                     proposal.requested_at, canonical(body).decode("utf-8")))
                self.conn.execute(
                    "INSERT INTO spending_decisions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (decision["decision_id"], proposal.proposal_id, decision["decision"],
                     decision["policy_id"], decision["policy_version"], decision["policy_hash"],
                     canonical(decision).decode("utf-8"), decision["economic_snapshot_hash"],
                     canonical({"economics": economics, "budget": budget}).decode("utf-8"),
                     at, decision["expires_at"], ENGINE_VERSION, 0))
                if decision["decision"] == "ALLOW":
                    self.conn.execute(
                        "INSERT INTO spending_budget_claims VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        (decision["decision_id"], proposal.proposal_id, proposal.agent_account,
                         proposal.network, proposal.genesis_hash, proposal.program_id,
                         proposal.token_mint, policy["policy_id"], policy["version"],
                         decision["daily_window_start_utc"], proposal.amount_base_units_str,
                         decision["expires_at"]))
                self.conn.execute("COMMIT")
                return decision, True
            except Exception:
                self.conn.execute("ROLLBACK")
                raise

    def list(self, agent: dict, now: int | None = None) -> list[dict]:
        at = int(time.time()) if now is None else now
        with self.policy_store._lock:
            try:
                policy = self.policy_store.current(agent)
            except PolicyError:
                return []
            rows = self.conn.execute(
                "SELECT d.decision_json FROM spending_decisions d JOIN spending_proposals p ON d.proposal_id=p.proposal_id "
                "WHERE p.agent_account=? AND p.agent_id=? AND p.owner_pubkey=? ORDER BY d.evaluated_at DESC, d.decision_id DESC LIMIT 100",
                (agent["agent_account"], agent["agent_id"], agent["owner"])).fetchall()
            return [dict(json.loads(row["decision_json"]), historical=True,
                         is_currently_applicable=self._applicable(json.loads(row["decision_json"]), policy, at))
                    for row in rows]

    def get(self, agent: dict, decision_id: str, now: int | None = None) -> dict:
        if not isinstance(decision_id, str) or not re.fullmatch(r"sd_[0-9a-f]{32}", decision_id):
            raise DecisionError(404, "DECISION_NOT_FOUND", "Decision not found")
        at = int(time.time()) if now is None else now
        with self.policy_store._lock:
            try:
                policy = self.policy_store.current(agent)
            except PolicyError as exc:
                raise DecisionError(404, "DECISION_NOT_FOUND", "Decision not found") from exc
            row = self.conn.execute(
                "SELECT d.decision_json FROM spending_decisions d JOIN spending_proposals p ON d.proposal_id=p.proposal_id "
                "WHERE d.decision_id=? AND p.agent_account=? AND p.agent_id=? AND p.owner_pubkey=?",
                (decision_id, agent["agent_account"], agent["agent_id"], agent["owner"])).fetchone()
            if row is None:
                raise DecisionError(404, "DECISION_NOT_FOUND", "Decision not found")
            result = json.loads(row["decision_json"])
            result["historical"] = True
            result["is_currently_applicable"] = self._applicable(result, policy, at)
            return result
