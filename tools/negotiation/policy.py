"""CON-27/28 advisory gate; never writes claims or approvals."""
from __future__ import annotations

from tools.economic_ledger.spending_decisions import SpendingProposal, evaluate_spending_proposal
from tools.economic_ledger.spending_decisions import SpendingDecisionStore
from tools.economic_ledger.budget_policies import BudgetPolicyStore
from .canonical import digest
from .models import NegotiationError


class EconomicPolicyGate:
    def __init__(self, policy_store, decision_store):
        if (type(policy_store) is not BudgetPolicyStore or
                type(decision_store) is not SpendingDecisionStore or
                decision_store.policy_store is not policy_store):
            raise NegotiationError("ECONOMIC_GATE_UNAVAILABLE")
        self.policy_store, self.decision_store = policy_store, decision_store

    def evaluate(self, requester: dict, provider: dict, offer: dict, now: int) -> dict:
        try:
            policy = self.policy_store.current(requester)
            if (policy["agent_account"] != requester["agent_account"] or
                    policy["agent_id"] != requester["agent_id"] or
                    policy["owner_pubkey"] != requester["owner"] or
                    (policy["network"], policy["genesis_hash"], policy["program_id"]) !=
                    (offer["network"], offer["genesis_hash"], offer["program_id"])):
                raise NegotiationError("POLICY_IDENTITY_CHANGED")
            body = {"proposal_id": "nq_" + digest([offer["message_id"], "proposal"])[:32],
                "idempotency_key": "nq_" + digest([offer["message_id"], "idempotency"])[:32],
                "nonce": digest([offer["message_id"], "nonce"])[:32],
                "agent_account": requester["agent_account"], "agent_id": requester["agent_id"],
                "requester_pubkey": requester.get("signing_authority") or requester["owner"],
                "network": offer["network"], "genesis_hash": offer["genesis_hash"],
                "program_id": offer["program_id"], "token_mint": offer["token_mint"],
                "recipient_pubkey": provider["owner"],
                "amount_base_units_str": offer["amount_base_units_str"],
                "purpose": offer["service_description"], "requested_at": now,
                "expected_policy_id": policy["policy_id"],
                "expected_policy_version": policy["version"],
                "expected_policy_hash": policy["policy_hash"], "metadata": {}}
            proposal = SpendingProposal.parse(body)
            economics, budget = self.decision_store._ledger_snapshots(requester, proposal, policy, now)
            decision = evaluate_spending_proposal(proposal, policy, economics, budget, now)
            if decision["decision"] not in {"DENY", "REQUIRE_APPROVAL", "ALLOW"}:
                raise NegotiationError("UNVERIFIABLE_DECISION")
            return decision
        except NegotiationError:
            raise
        except Exception as exc:
            raise NegotiationError("ECONOMIC_GATE_UNAVAILABLE") from exc
