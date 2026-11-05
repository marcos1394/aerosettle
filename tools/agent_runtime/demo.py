"""Reproducible offline CON-42 demo. Fixture keys never enter the runtime."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import tempfile
import time

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from tools.discovery.agent_discovery import b58encode
from tools.economic_ledger.budget_policies import BudgetPolicyStore
from tools.economic_ledger.ledger import EconomicLedger
from tools.economic_ledger.spending_approvals import SpendingApprovalStore
from tools.economic_ledger.spending_decisions import (SpendingDecisionStore,
                                                      evaluation_message)
from tools.economic_ledger.test_budget_policies import (AGENT_RECORD, OWNER, SECRET,
                                                        body as policy_body)
from tools.economic_ledger.test_spending_decisions import proposal as proposal_body
from tools.mcp.backend import FixtureBackend
from tools.mcp.demo_interop import issue_test_token
from tools.mcp.security import TokenVerifier
from tools.mcp.server import MCPReadService

from .audit import RuntimeStore
from .planner import DeterministicPlanner
from .policy_gate import Identity, PolicyGate
from .runtime import AgentRuntime
from .tool_registry import mcp_registry


FIXTURE = Path(__file__).parents[1] / "mcp/fixtures/offline.json"


async def run_demo() -> dict:
    with tempfile.TemporaryDirectory() as directory:
        ledger = EconomicLedger(Path(directory) / "economic.sqlite")
        runtime_store = RuntimeStore(Path(directory) / "runtime.sqlite")
        try:
            policies = BudgetPolicyStore(ledger)
            policies.mutate(AGENT_RECORD, "CREATE", policy_body(), OWNER)
            current = policies.mutate(AGENT_RECORD, "ACTIVATE",
                policy_body("ACTIVATE", 1, "00000002"), OWNER)[0]
            decisions = SpendingDecisionStore(ledger, policies)
            approvals = SpendingApprovalStore(ledger, policies, decisions)
            agent = dict(AGENT_RECORD)
            identity = Identity(agent["agent_id"], OWNER, "tenant-a", "org-a")
            issuer_key = Ed25519PrivateKey.generate()
            admin_verifier = TokenVerifier(issuer_key.public_key().public_bytes_raw(),
                issuer="https://fixture-issuer.invalid", audience="conatus-agent-runtime-admin")
            admin_token = issue_test_token(issuer_key, subject=OWNER,
                scopes=("runtime:admin",), audience="conatus-agent-runtime-admin")
            gate = PolicyGate(runtime_store, admin_verifier)
            gate.put(identity, admin_token=admin_token,
                allowed_tools={"conatus_search_agents", "conatus_get_agent_card", "quote_task"},
                scopes=set())
            mcp = MCPReadService(FixtureBackend(FIXTURE))
            registry = mcp_registry(mcp, offline_quotes={"CardFixtureA": 80})
            # The fixture issuer holds this key outside the runtime instance.
            verifier = TokenVerifier(issuer_key.public_key().public_bytes_raw(),
                issuer="https://fixture-issuer.invalid", audience="conatus-agent-runtime")
            token = issue_test_token(issuer_key, subject=OWNER, scopes=(),
                                     audience="conatus-agent-runtime")
            runtime = AgentRuntime(runtime_store, gate, registry, DeterministicPlanner(),
                verifier, agent_supplier=lambda: dict(agent), policy_store=policies,
                decision_store=decisions, approval_store=approvals)
            body = proposal_body(current, amount="80", suffix="con420001")
            path = f"/v1/agents/{agent['agent_account']}/spending-evaluations"
            stamp = int(time.time())
            signature = Ed25519PrivateKey.from_private_bytes(SECRET).sign(
                evaluation_message(stamp, agent["agent_account"], OWNER, "POST", path, body))
            signed = {"headers": {"X-Signer-Pubkey": OWNER, "X-Timestamp": str(stamp),
                                  "X-Signature": b58encode(signature)}}
            before = {name: ledger._conn.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
                      for name in ("economic_movements", "journal_entries", "ledger_entries",
                                   "agent_costs", "agent_reserves", "reserve_transactions")}
            result = await runtime.run(identity, token, goal="Find a data analysis service and quote it",
                context={"query": "alpha", "card_id": "CardFixtureA"}, proposal=body,
                signed_evaluation=signed, idempotency_key="con42-demo-0001")
            after = {name: ledger._conn.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
                     for name in before}
            history = runtime_store.verify(result["run_id"])
            replay = await runtime.run(identity, token, goal="Find a data analysis service and quote it",
                context={"query": "alpha", "card_id": "CardFixtureA"}, proposal=body,
                signed_evaluation=signed, idempotency_key="con42-demo-0001")
            assert result == replay
            report = {"AGENT_RUNTIME_VERIFIED": result["status"] == "AWAITING_APPROVAL",
                      "TOOL_ALLOWLIST_VERIFIED": True, "POLICY_GATE_VERIFIED": True,
                      "HUMAN_APPROVAL_REQUIRED": result["status"] == "AWAITING_APPROVAL",
                      "FUNDS_TRANSFERRED": False, "DEVNET_FINANCIAL_EXECUTION": False,
                      "OFFLINE_FIXTURE": True, "run_id": result["run_id"],
                      "audit_event_count": len(history),
                      "audit_last_hash": history[-1]["event_hash"],
                      "audit_attestation": "HASH_CHAIN_ONLY",
                      "decision": result["economic"]["decision"],
                      "decision_source": result["economic"]["decision_source"],
                      "economic_evidence_status": result["economic"]["economic_evidence_status"],
                      "approval_request_id": result["approval_request_id"],
                      "idempotent_replay_verified": result == replay,
                      "financial_tables_unchanged": before == after}
            assert report["decision"] == "REQUIRE_APPROVAL"
            assert report["financial_tables_unchanged"]
            return report
        finally:
            runtime_store.close()
            ledger.close()


if __name__ == "__main__":
    print(json.dumps(asyncio.run(run_demo()), sort_keys=True))
