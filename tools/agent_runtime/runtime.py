"""Deterministic authority boundary around planner, tools and economic proposals."""
from __future__ import annotations

import asyncio
from dataclasses import asdict
import re
import time
import uuid

from tools.economic_ledger.spending_decisions import (
    SpendingProposal, evaluate_spending_proposal, verify_evaluation)
from tools.mcp.security import TokenVerifier
from tools.operations.structured_logs import emit

from .audit import RuntimeStore
from .models import RuntimeDenied, SAFE_ID, SECRET_PATTERN, canonical, safe_text, validate_plan
from .observations import summarize
from .planner import LLMPlanner, Planner
from .policy_gate import Identity, PolicyGate
from .tool_registry import ToolRegistry


class AgentRuntime:
    def __init__(self, store: RuntimeStore, gate: PolicyGate, registry: ToolRegistry,
                 planner: Planner, verifier: TokenVerifier, *, agent_supplier,
                 policy_store, decision_store, approval_store=None,
                 operational_store=None):
        self.store, self.gate, self.registry, self.planner = store, gate, registry, planner
        self.verifier = verifier
        self.agent_supplier = agent_supplier
        self.policy_store, self.decision_store = policy_store, decision_store
        self.approval_store = approval_store
        self.operational_store = operational_store

    def _identity(self, identity: Identity, token: str) -> tuple[object, dict]:
        principal = self.verifier.verify(token)
        if (principal.audience != "conatus-agent-runtime" or
                principal.subject != identity.owner_id or
                principal.tenant_id != identity.tenant_id or
                principal.organization_id != identity.organization_id):
            raise RuntimeDenied("IDENTITY_MISMATCH")
        agent = self.agent_supplier()
        if (not isinstance(agent, dict) or agent.get("agent_id") != identity.agent_id or
                agent.get("owner") != identity.owner_id or not agent.get("agent_account")):
            raise RuntimeDenied("AGENT_IDENTITY_CHANGED")
        return principal, agent

    def _metric(self, name: str) -> None:
        if self.operational_store is not None:
            try:
                self.operational_store.sample(name, 1, "count", "agent-runtime")
            except Exception:
                pass

    def _log(self, run_id: str, status: str, code: str = "") -> None:
        emit("INFO" if not code else "WARNING", "agent_runtime", "run",
             correlation_id=run_id, status=status, error_category=code or None)

    def _economics(self, identity: Identity, agent: dict, body: dict,
                   signed_evaluation: dict | None, approval_id: str | None) -> dict:
        proposal = SpendingProposal.parse(body)
        if (proposal.agent_account != agent["agent_account"] or
                proposal.agent_id != identity.agent_id or
                proposal.requester_pubkey not in (agent["owner"], agent.get("signing_authority"))):
            raise RuntimeDenied("ECONOMIC_IDENTITY_MISMATCH")
        policy = self.policy_store.current(agent)
        if any((proposal.expected_policy_id != policy["policy_id"],
                proposal.expected_policy_version != policy["version"],
                proposal.expected_policy_hash != policy["policy_hash"],
                proposal.network != policy["network"],
                proposal.genesis_hash != policy["genesis_hash"],
                proposal.program_id != policy["program_id"])):
            raise RuntimeDenied("ECONOMIC_CONTEXT_MISMATCH")
        if signed_evaluation is not None:
            if set(signed_evaluation) != {"headers"}:
                raise RuntimeDenied("INVALID_SIGNATURE")
            path = f"/v1/agents/{agent['agent_account']}/spending-evaluations"
            requester = verify_evaluation(agent, "POST", path, body,
                                          signed_evaluation["headers"])
            decision, _ = self.decision_store.evaluate(agent, body, requester,
                identity_supplier=self.agent_supplier)
            source = "CON28_SIGNED_EVALUATION"
        else:
            economics, budget = self.decision_store._ledger_snapshots(
                agent, proposal, policy, int(time.time()))
            decision = evaluate_spending_proposal(proposal, policy, economics, budget,
                                                   int(time.time()))
            source = "CON28_ADVISORY_UNPERSISTED"
        if approval_id is not None:
            if self.approval_store is None or signed_evaluation is None:
                raise RuntimeDenied("APPROVAL_UNVERIFIABLE")
            approval = self.approval_store.get(agent, approval_id)
            if (approval["decision_id"] != decision["decision_id"] or
                    approval["policy_hash"] != policy["policy_hash"] or
                    approval["owner_pubkey"] != identity.owner_id or
                    approval["network"] != proposal.network or
                    approval["token_mint"] != proposal.token_mint or
                    not approval["is_currently_applicable"]):
                raise RuntimeDenied("APPROVAL_NOT_CURRENT")
        return {"decision": decision["decision"], "decision_id": decision["decision_id"],
                "reason_codes": decision["reason_codes"],
                "economic_evidence_status": decision["economic_evidence_status"],
                "is_currently_applicable": decision["is_currently_applicable"],
                "is_executable": False, "decision_source": source,
                "approval_reference": approval_id}

    async def run(self, identity: Identity, token: str, *, goal: str, context: dict,
                  proposal: dict, idempotency_key: str,
                  signed_evaluation: dict | None = None,
                  approval_id: str | None = None, environment: str = "offline") -> dict:
        safe_text(goal)
        if not isinstance(idempotency_key, str) or not SAFE_ID.fullmatch(idempotency_key):
            raise RuntimeDenied("INVALID_IDEMPOTENCY_KEY")
        if not isinstance(context, dict) or set(context) - {"query", "card_id"}:
            raise RuntimeDenied("INVALID_CONTEXT")
        for key, value in context.items():
            if not isinstance(value, str) or len(value) > 128 or "://" in value or "/" in value:
                raise RuntimeDenied("INVALID_CONTEXT")
            if value:
                safe_text(value, maximum=128)
        if SECRET_PATTERN.search(canonical(proposal).decode("utf-8")):
            raise RuntimeDenied("UNSAFE_INPUT")
        principal, agent = self._identity(identity, token)
        policy = self.gate.current(identity)
        if environment != policy["environment"]:
            raise RuntimeDenied("POLICY_DENIED")
        request = {"goal": goal, "context": context, "proposal": proposal,
                   "signed_evaluation": signed_evaluation, "approval_id": approval_id,
                   "environment": environment}
        run_id, replay = self.store.begin(identity, idempotency_key, goal, request, policy)
        if replay is not None:
            return replay
        started = time.monotonic()
        def elapsed(): return int((time.monotonic() - started) * 1000)
        actor = identity.agent_id
        try:
            self.store.transition(run_id, "PLANNING", actor=actor)
            public_context = {k: context[k] for k in ("query", "card_id") if k in context}
            if isinstance(self.planner, LLMPlanner) and policy["max_llm_tokens"] <= 0:
                raise RuntimeDenied("LLM_DISABLED")
            raw_plan = await asyncio.wait_for(
                self.planner.plan(goal, public_context, self.registry.discover()), timeout=3)
            if isinstance(self.planner, LLMPlanner):
                if (not isinstance(raw_plan, dict) or
                        raw_plan.get("tokens_used", policy["max_llm_tokens"] + 1) >
                        policy["max_llm_tokens"]):
                    raise RuntimeDenied("LLM_QUOTA_EXCEEDED")
                raw_plan = raw_plan["steps"]
            steps = validate_plan(raw_plan, max_steps=policy["max_steps"])
            plan_hash = self.store.seal([asdict(s) for s in steps])
            self.store.transition(run_id, "POLICY_CHECK", actor=actor, plan_hash=plan_hash,
                                  output_hash=plan_hash)
            observations = []
            counts: dict[str, int] = {}
            compute = 0
            quoted_amount = None
            for index, step in enumerate(steps, 1):
                if self.store.snapshot(run_id, identity)["status"] == "CANCELED":
                    return self.store.snapshot(run_id, identity)["result"]
                principal, agent = self._identity(identity, token)
                spec, handler = self.registry.get(step.tool_id)
                spec.check_input(step.arguments)
                self.gate.check(identity, principal, principal.expires_at, spec,
                    expected_hash=policy["policy_hash"], calls=index-1,
                    tool_calls=counts.get(step.tool_id, 0), elapsed_ms=elapsed(),
                    compute_used=compute, environment=environment)
                self.store.transition(run_id, "EXECUTING_TOOL", actor=actor,
                    tool_id=step.tool_id, decision="ALLOW",
                    input_hash=self.store.seal(step.arguments), step=index)
                output = await asyncio.wait_for(handler(step.arguments, principal),
                                                timeout=spec.timeout_ms / 1000)
                if self.store.snapshot(run_id, identity)["status"] == "CANCELED":
                    return self.store.snapshot(run_id, identity)["result"]
                output = spec.check_output(output)
                if step.tool_id == "conatus_get_agent_card":
                    card = output.get("data", {})
                    if (card.get("is_executable") is not False or
                            card.get("is_financial_authority") is not False):
                        raise RuntimeDenied("UNTRUSTED_CARD")
                if step.tool_id == "quote_task":
                    if (output.get("is_reservation") is not False or
                            output.get("is_financial_authority") is not False or
                            output.get("evidence_source") != "OFFLINE_FIXTURE"):
                        raise RuntimeDenied("UNTRUSTED_QUOTE")
                    quoted_amount = output["estimated_base_units_str"]
                # A revocation while the handler was in flight discards its output.
                principal, agent = self._identity(identity, token)
                self.gate.check(identity, principal, principal.expires_at, spec,
                    expected_hash=policy["policy_hash"], calls=index-1,
                    tool_calls=counts.get(step.tool_id, 0), elapsed_ms=elapsed(),
                    compute_used=compute, environment=environment)
                obs = summarize(output, self.store.seal)
                observations.append(obs)
                counts[step.tool_id] = counts.get(step.tool_id, 0) + 1
                compute += 1
                self.store.transition(run_id, "OBSERVING", actor=actor,
                    tool_id=step.tool_id, output_hash=obs["observation_hash"],
                    evidence_source=obs["evidence_source"])
                self.store.transition(run_id, "POLICY_CHECK", actor=actor)
            principal, agent = self._identity(identity, token)
            self.gate.check_active(identity, policy["policy_hash"])
            if elapsed() >= policy["max_duration_ms"]:
                raise RuntimeDenied("TIME_LIMIT")
            if quoted_amount is None or proposal.get("amount_base_units_str") != quoted_amount:
                raise RuntimeDenied("QUOTE_MISMATCH")
            economic = self._economics(identity, agent, proposal, signed_evaluation, approval_id)
            self._identity(identity, token)
            self.gate.check_active(identity, policy["policy_hash"])
            status = "DENIED" if economic["decision"] == "DENY" else "AWAITING_APPROVAL"
            request_id = ("approval_request_" + self.store.seal([run_id, economic["decision_id"]])[:32]
                          if status == "AWAITING_APPROVAL" else None)
            result = {"run_id": run_id, "status": status, "goal_hash": self.store.seal(goal),
                      "plan_hash": plan_hash, "policy_version": policy["version"],
                      "tool_calls": len(steps), "observations": observations,
                      "economic": economic, "approval_request_id": request_id,
                      "funds_transferred": False, "devnet_financial_execution": False,
                      "audit_attestation": "HASH_CHAIN_ONLY"}
            self.store.transition(run_id, status, actor=actor, decision=economic["decision"],
                output_hash=self.store.seal(result), result=result,
                evidence_source=economic["economic_evidence_status"])
            self._metric("agent_runtime_runs")
            self._log(run_id, status)
            return result
        except Exception as exc:
            code = exc.code if hasattr(exc, "code") else (
                "TIMEOUT" if isinstance(exc, asyncio.TimeoutError) else "UNAVAILABLE")
            target = "DENIED" if isinstance(exc, RuntimeDenied) or hasattr(exc, "code") else "FAILED"
            if code == "TIMEOUT": target = "FAILED"
            try:
                result = {"run_id": run_id, "status": target, "error_code": code,
                          "funds_transferred": False, "devnet_financial_execution": False,
                          "audit_attestation": "HASH_CHAIN_ONLY"}
                self.store.transition(run_id, target, actor=actor, decision="DENY",
                    output_hash=self.store.seal(result), result=result)
            except RuntimeDenied:
                raise
            self._metric("agent_runtime_denials" if target == "DENIED" else "agent_runtime_failures")
            self._log(run_id, target, code)
            return result

    def cancel(self, run_id: str, identity: Identity, *, token: str) -> None:
        principal, _ = self._identity(identity, token)
        if "runtime:cancel" not in principal.scopes:
            raise RuntimeDenied("POLICY_DENIED")
        self.store.snapshot(run_id, identity)
        result = {"run_id": run_id, "status": "CANCELED", "funds_transferred": False}
        self.store.transition(run_id, "CANCELED", actor=identity.owner_id, decision="DENY",
                              output_hash=self.store.seal(result), result=result)
