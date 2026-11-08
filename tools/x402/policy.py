"""CON-27/28/29 gate, scoped to exact x402 terms; approvals remain non-executable."""
from __future__ import annotations

from tools.economic_ledger.budget_policies import BudgetPolicyStore
from tools.economic_ledger.spending_decisions import SpendingDecisionStore
from tools.economic_ledger.spending_approvals import SpendingApprovalStore
from .common import SandboxError, digest, NETWORK


class PaymentPolicyGate:
    def __init__(self, policies: BudgetPolicyStore, decisions: SpendingDecisionStore,
                 approvals: SpendingApprovalStore, agent_supplier):
        if (type(policies) is not BudgetPolicyStore or type(decisions) is not SpendingDecisionStore or
                type(approvals) is not SpendingApprovalStore or
                decisions.policy_store is not policies or approvals.policies is not policies or
                approvals.decisions is not decisions):
            raise SandboxError("ECONOMIC_GATE_UNAVAILABLE")
        self.policies, self.decisions, self.approvals = policies, decisions, approvals
        self.agent_supplier = agent_supplier

    def _agent(self, terms: dict) -> dict:
        agent = self.agent_supplier(terms["clientAgentAccount"])
        if (not isinstance(agent, dict) or agent.get("agent_account") != terms["clientAgentAccount"] or
                not agent.get("agent_id") or not agent.get("owner") or agent.get("active") is not True or
                agent.get("status") != "Active" or
                (agent.get("network"), agent.get("genesis_hash"), agent.get("program_id")) !=
                ("solana:devnet", terms["genesisHash"], terms["programId"])):
            raise SandboxError("AGENT_IDENTITY_MISMATCH", 403)
        return agent

    def _proposal(self, agent: dict, terms: dict, policy: dict) -> dict:
        key = digest(terms)
        return {"proposal_id": "xp_" + key[:32], "idempotency_key": "x402_" + key[:32],
                "nonce": "x402_" + digest([key, "nonce"])[:32],
                "agent_account": agent["agent_account"], "agent_id": agent["agent_id"],
                "requester_pubkey": agent["owner"], "network": "solana:devnet",
                "genesis_hash": terms["genesisHash"], "program_id": terms["programId"],
                "token_mint": terms["asset"], "recipient_pubkey": terms["payTo"],
                "amount_base_units_str": terms["amount"],
                "purpose": "x402 sandbox resource " + terms["resourceId"],
                "requested_at": terms["expiresAt"] - 60,
                "expected_policy_id": policy["policy_id"], "expected_policy_version": policy["version"],
                "expected_policy_hash": policy["policy_hash"],
                "metadata": {"resource_url": terms["resourceUrl"], "resource_id": terms["resourceId"],
                             "payment_id": terms["paymentId"], "payment_requirements_hash": terms["requirementsHash"],
                             "pay_to": terms["payTo"], "x402_network": NETWORK,
                             "expires_at": terms["expiresAt"]}}

    def evaluate(self, terms: dict, now: int) -> dict:
        if terms["network"] != NETWORK or now >= terms["expiresAt"]:
            raise SandboxError("UNTRUSTED_CONTEXT", 403)
        agent = self._agent(terms)
        try:
            policy = self.policies.current(agent)
            if (policy["network"], policy["genesis_hash"], policy["program_id"]) != (
                    "solana:devnet", terms["genesisHash"], terms["programId"]):
                raise SandboxError("POLICY_CONTEXT_MISMATCH", 403)
            proposal = self._proposal(agent, terms, policy)
            decision, _ = self.decisions.evaluate(agent, proposal, agent["owner"], now=now,
                                                   identity_supplier=lambda: self._agent(terms))
            if decision["decision"] == "DENY":
                return {"status": "BLOCK", "decision_id": decision["decision_id"], "approval_id": None}
            if decision["decision"] == "REQUIRE_APPROVAL":
                return {"status": "AWAITING_HUMAN_APPROVAL", "decision_id": decision["decision_id"],
                        "approval_id": None}
            return {"status": "ELIGIBLE_FOR_SEPARATE_PAYMENT_AUTHORIZATION",
                    "decision_id": decision["decision_id"], "approval_id": None}
        except SandboxError:
            raise
        except Exception as exc:
            raise SandboxError("ECONOMIC_GATE_UNAVAILABLE", 503) from exc

    def validate(self, terms: dict, decision_id: str, approval_id: str | None, now: int) -> dict:
        if now >= terms["expiresAt"]:
            raise SandboxError("PAYMENT_EXPIRED", 403)
        agent = self._agent(terms)
        try:
            policy = self.policies.current(agent)
            expected = self._proposal(agent, terms, policy)
            decision = self.decisions.get(agent, decision_id, now=now)
            context = self.approvals.context(agent, decision_id)
            if (context["proposal"] != expected or decision["decision"] == "DENY" or
                    (policy["policy_id"], policy["version"], policy["policy_hash"], policy["status"]) !=
                    (decision["policy_id"], decision["policy_version"], decision["policy_hash"], "ACTIVE")):
                raise SandboxError("POLICY_CHANGED", 403)
            if decision["decision"] == "ALLOW":
                if approval_id is not None:
                    raise SandboxError("APPROVAL_MISMATCH", 403)
                return {"status": "ELIGIBLE_FOR_SEPARATE_PAYMENT_AUTHORIZATION",
                        "decision_id": decision_id, "approval_id": None}
            if approval_id != context["approval_id"]:
                raise SandboxError("HUMAN_APPROVAL_REQUIRED", 403)
            approval = self.approvals.get(agent, approval_id, now=now)
            if approval["approval_status"] != "APPROVED" or approval["effective_status"] != "APPROVED":
                raise SandboxError("HUMAN_APPROVAL_REQUIRED", 403)
            self.approvals.history(agent, approval_id)
            return {"status": "SANDBOX_HUMAN_APPROVED", "decision_id": decision_id,
                    "approval_id": approval_id}
        except SandboxError:
            raise
        except Exception as exc:
            raise SandboxError("ECONOMIC_GATE_UNAVAILABLE", 503) from exc
