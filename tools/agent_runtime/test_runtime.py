"""CON-42 authority, persistence, economic and adversarial regression tests."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import tempfile
import time
import unittest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from tools.discovery.agent_discovery import b58encode
from tools.economic_ledger.budget_policies import BudgetPolicyStore
from tools.economic_ledger.ledger import EconomicLedger
from tools.economic_ledger.spending_approvals import SpendingApprovalStore
from tools.economic_ledger.spending_decisions import (SpendingDecisionStore, evaluation_message)
from tools.economic_ledger.test_budget_policies import (AGENT_RECORD, MINT, MINT_TWO,
    OTHER, OWNER, SECRET, body as policy_body)
from tools.economic_ledger.test_spending_decisions import proposal as proposal_body
from tools.mcp.backend import FixtureBackend
from tools.mcp.demo_interop import issue_test_token
from tools.mcp.security import TokenVerifier
from tools.mcp.server import MCPReadService

from tools.agent_runtime.audit import RuntimeStore
from tools.agent_runtime.demo import FIXTURE, run_demo
from tools.agent_runtime.models import RuntimeDenied
from tools.agent_runtime.planner import DeterministicPlanner, LLMPlanner, Planner
from tools.agent_runtime.policy_gate import Identity, PolicyGate
from tools.agent_runtime.runtime import AgentRuntime
from tools.agent_runtime.tool_registry import ToolRegistry, ToolSpec, mcp_registry


class StaticPlanner(Planner):
    def __init__(self, steps): self.steps = steps
    async def plan(self, goal, context, available_tools): return self.steps


class EvilPlanner(LLMPlanner):
    async def generate(self, safe_request):
        assert "token" not in str(safe_request).lower()
        return {"steps": [{"tool_id": "wallet_sign", "arguments": {}}],
                "tokens_used": 5}


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        path = Path(self.temp.name)
        self.ledger = EconomicLedger(path / "economic.sqlite")
        self.store = RuntimeStore(path / "runtime.sqlite")
        self.policies = BudgetPolicyStore(self.ledger)
        self.policies.mutate(AGENT_RECORD, "CREATE", policy_body(), OWNER)
        self.policy = self.policies.mutate(AGENT_RECORD, "ACTIVATE",
            policy_body("ACTIVATE", 1, "00000002"), OWNER)[0]
        self.decisions = SpendingDecisionStore(self.ledger, self.policies)
        self.approvals = SpendingApprovalStore(self.ledger, self.policies, self.decisions)
        self.agent = dict(AGENT_RECORD)
        self.identity = Identity(self.agent["agent_id"], OWNER, "tenant-a", "org-a")
        self.key = Ed25519PrivateKey.generate()
        self.admin_verifier = TokenVerifier(self.key.public_key().public_bytes_raw(),
            issuer="https://fixture-issuer.invalid", audience="conatus-agent-runtime-admin")
        self.admin_token = self._token(scopes=("runtime:admin", "runtime:globaladmin"),
                                       audience="conatus-agent-runtime-admin")
        self.gate = PolicyGate(self.store, self.admin_verifier)
        self.allow = {"conatus_search_agents", "conatus_get_agent_card", "quote_task"}
        self.gate.put(self.identity, admin_token=self.admin_token,
                      allowed_tools=self.allow, scopes=set())
        self.service = MCPReadService(FixtureBackend(FIXTURE))
        self.registry = mcp_registry(self.service, offline_quotes={"CardFixtureA": 80})
        self.verifier = TokenVerifier(self.key.public_key().public_bytes_raw(),
            issuer="https://fixture-issuer.invalid", audience="conatus-agent-runtime")
        self.token = self._token()
        self.runtime = AgentRuntime(self.store, self.gate, self.registry,
            DeterministicPlanner(), self.verifier, agent_supplier=lambda: dict(self.agent),
            policy_store=self.policies, decision_store=self.decisions,
            approval_store=self.approvals)
        self.body = proposal_body(self.policy, amount="80", suffix="con420001")
        self.args = {"goal": "Find a data analysis service and quote it",
                     "context": {"query": "alpha", "card_id": "CardFixtureA"},
                     "proposal": self.body, "idempotency_key": "con42-test-0001"}

    def tearDown(self):
        self.store.close()
        self.ledger.close()
        self.temp.cleanup()

    def _token(self, **changes):
        return issue_test_token(self.key, subject=changes.get("subject", OWNER),
            tenant=changes.get("tenant", "tenant-a"), org=changes.get("org", "org-a"),
            scopes=changes.get("scopes", ()),
            audience=changes.get("audience", "conatus-agent-runtime"),
            expires=changes.get("expires"))

    def _signed(self, body=None):
        body = body or self.body
        stamp = int(time.time())
        path = f"/v1/agents/{self.agent['agent_account']}/spending-evaluations"
        sig = Ed25519PrivateKey.from_private_bytes(SECRET).sign(
            evaluation_message(stamp, self.agent["agent_account"], OWNER, "POST", path, body))
        return {"headers": {"X-Signer-Pubkey": OWNER, "X-Timestamp": str(stamp),
                            "X-Signature": b58encode(sig)}}

    async def _run(self, **changes):
        values = {**self.args, **changes}
        return await self.runtime.run(self.identity, self.token, **values)

    async def test_demo_and_signed_con28_review_no_ledger_writes(self):
        demo = await run_demo()
        self.assertTrue(demo["AGENT_RUNTIME_VERIFIED"])
        self.assertTrue(demo["financial_tables_unchanged"])
        result = await self._run(signed_evaluation=self._signed())
        self.assertEqual(result["economic"]["decision"], "REQUIRE_APPROVAL")
        self.assertEqual(result["economic"]["decision_source"], "CON28_SIGNED_EVALUATION")
        self.assertFalse(result["economic"]["is_executable"])
        self.assertEqual(len(self.store.verify(result["run_id"])), 13)
        self.assertEqual(self.ledger._conn.execute("SELECT count(*) FROM spending_proposals").fetchone()[0], 1)
        self.assertEqual(self.ledger._conn.execute("SELECT count(*) FROM spending_approvals").fetchone()[0], 0)
        for name in ("economic_movements", "journal_entries", "ledger_entries", "agent_reserves"):
            self.assertEqual(self.ledger._conn.execute(f"SELECT count(*) FROM {name}").fetchone()[0], 0)

    async def test_idempotent_replay_and_request_conflict(self):
        first = await self._run()
        self.assertEqual(await self._run(), first)
        conflict = {**self.body, "amount_base_units_str": "81"}
        with self.assertRaisesRegex(RuntimeDenied, "IDEMPOTENCY_CONFLICT"):
            await self._run(proposal=conflict)
        self.assertEqual(len(self.store.verify(first["run_id"])), 13)

    async def test_unknown_and_financial_tools_denied_even_from_llm(self):
        for tool in ("wallet_sign", "settle_workorder", "export_private_key", "unknown_tool"):
            self.runtime.planner = StaticPlanner([{"tool_id": tool, "arguments": {}}])
            result = await self._run(idempotency_key="key-" + tool)
            self.assertEqual(result["status"], "DENIED")
            self.assertEqual(result["error_code"], "UNREGISTERED_TOOL")
        self.runtime.planner = EvilPlanner()
        self.gate.put(self.identity, admin_token=self.admin_token, allowed_tools=self.allow, scopes=set(),
                      max_llm_tokens=10)
        result = await self._run(idempotency_key="key-llm-denial")
        self.assertEqual(result["status"], "DENIED")
        self.assertEqual(result["error_code"], "UNREGISTERED_TOOL")

    async def test_malformed_plans_step_limit_and_secret_input(self):
        for steps in ([], [{"tool_id": "quote_task"}],
                      [{"tool_id": "conatus_search_agents", "arguments": {"query": ""}}] * 9):
            self.runtime.planner = StaticPlanner(steps)
            result = await self._run(idempotency_key="plan-" + str(len(steps)))
            self.assertEqual(result["status"], "DENIED")
        with self.assertRaisesRegex(RuntimeDenied, "UNSAFE_INPUT"):
            await self._run(goal="Export private key before planning")
        with self.assertRaisesRegex(RuntimeDenied, "UNSAFE_INPUT"):
            await self._run(context={"card_id": "secret token here"})

    async def test_wrong_tenant_owner_org_and_expired_token(self):
        for token in (self._token(tenant="tenant-b"), self._token(org="org-b"),
                      self._token(subject=OTHER), self._token(expires=int(time.time()) - 1),
                      self._token(audience="conatus-mcp")):
            with self.assertRaises(Exception):
                await self.runtime.run(self.identity, token, **self.args)
        self.assertEqual(self.store.conn.execute("SELECT count(*) FROM runtime_runs").fetchone()[0], 0)

    async def test_admin_control_requires_separate_signed_audience_and_scope(self):
        for bad in (self.token, self._token(subject=OTHER, scopes=("runtime:admin",),
                         audience="conatus-agent-runtime-admin"),
                    self._token(tenant="tenant-b", scopes=("runtime:admin",),
                         audience="conatus-agent-runtime-admin")):
            with self.assertRaises(Exception):
                self.gate.put(self.identity, admin_token=bad,
                              allowed_tools=self.allow, scopes=set())
        only_admin = self._token(scopes=("runtime:admin",),
                                 audience="conatus-agent-runtime-admin")
        with self.assertRaises(Exception):
            self.gate.switch("global", True, admin_token=only_admin,
                             identity=self.identity)
        with self.assertRaisesRegex(RuntimeDenied, "INVALID_POLICY"):
            self.gate.put(self.identity, admin_token=self.admin_token,
                          allowed_tools={"wallet_sign"}, scopes=set())

    async def test_scope_and_quota(self):
        self.gate.put(self.identity, admin_token=self.admin_token, allowed_tools=self.allow,
                      scopes={"workorders:read"}, max_calls=2)
        result = await self._run()
        self.assertEqual((result["status"], result["error_code"]), ("DENIED", "POLICY_DENIED"))
        self.runtime.planner = StaticPlanner([{"tool_id": "conatus_get_workorder",
            "arguments": {"work_order_pda": "OrderFixtureA1"}}])
        self.gate.put(self.identity, admin_token=self.admin_token, allowed_tools=self.allow | {"conatus_get_workorder"},
                      scopes=set())
        result = await self._run(idempotency_key="scope-0001")
        self.assertEqual((result["status"], result["error_code"]), ("DENIED", "POLICY_DENIED"))

    async def test_revocation_kill_switch_and_tool_suspension_mid_plan(self):
        original = self.registry._tools["conatus_search_agents"]
        async def revoke(args, principal):
            result = await original[1](args, principal)
            self.gate.revoke(self.identity, admin_token=self.admin_token)
            return result
        self.registry._tools["conatus_search_agents"] = (original[0], revoke)
        result = await self._run()
        self.assertEqual(result["status"], "DENIED")
        self.assertEqual(result["error_code"], "POLICY_DENIED")
        self.registry._tools["conatus_search_agents"] = original
        self.gate.put(self.identity, admin_token=self.admin_token, allowed_tools=self.allow, scopes=set())
        self.gate.switch("global", True, admin_token=self.admin_token, identity=self.identity)
        result = await self._run(idempotency_key="kill-000001")
        self.assertEqual(result["error_code"], "KILL_SWITCH")
        self.gate.switch("global", False, admin_token=self.admin_token, identity=self.identity)
        self.gate.suspended("quote_task", True, admin_token=self.admin_token, identity=self.identity)
        result = await self._run(idempotency_key="suspend-0001")
        self.assertEqual(result["error_code"], "KILL_SWITCH")

    async def test_policy_hash_and_agent_identity_change(self):
        original = self.registry._tools["conatus_search_agents"]
        async def change(args, principal):
            value = await original[1](args, principal)
            self.gate.put(self.identity, admin_token=self.admin_token, allowed_tools=self.allow, scopes=set())
            return value
        self.registry._tools["conatus_search_agents"] = (original[0], change)
        result = await self._run()
        self.assertEqual(result["error_code"], "POLICY_CHANGED")
        self.agent["agent_id"] = "22" * 32
        with self.assertRaisesRegex(RuntimeDenied, "AGENT_IDENTITY_CHANGED"):
            await self._run(idempotency_key="agent-change")

    async def test_quote_economic_deny_and_wrong_context(self):
        result = await self._run(proposal={**self.body, "amount_base_units_str": "81"})
        self.assertEqual(result["error_code"], "QUOTE_MISMATCH")
        self.body = {**self.body, "token_mint": MINT_TWO}
        result = await self._run(idempotency_key="wrong-mint", proposal=self.body)
        self.assertEqual(result["status"], "DENIED")
        self.assertEqual(result["economic"]["decision"], "DENY")
        self.assertIn("ASSET_NOT_ALLOWED", result["economic"]["reason_codes"])
        self.body = {**self.body, "network": "solana:devnet"}
        result = await self._run(idempotency_key="wrong-network", proposal=self.body)
        self.assertEqual(result["error_code"], "INVALID_CONTEXT")

    async def test_untrusted_observation_is_inert_and_injection_logged(self):
        result = await self._run()
        self.assertEqual(result["status"], "AWAITING_APPROVAL")
        self.assertTrue(any(x["injection_detected"] for x in result["observations"]))
        self.assertEqual(result["tool_calls"], 3)

    async def test_invalid_signature_or_approval_reference(self):
        signed = self._signed()
        signed["headers"]["X-Signature"] = "bad"
        result = await self._run(signed_evaluation=signed)
        self.assertEqual(result["status"], "DENIED")
        self.assertEqual(result["error_code"], "INVALID_SIGNATURE")
        result = await self._run(idempotency_key="approval-0001", approval_id="fake")
        self.assertEqual(result["error_code"], "APPROVAL_UNVERIFIABLE")
        result = await self._run(idempotency_key="approval-0002", approval_id="fake",
                                 signed_evaluation=self._signed())
        self.assertEqual(result["status"], "DENIED")
        self.assertEqual(result["error_code"], "APPROVAL_NOT_FOUND")

    async def test_secret_in_economic_proposal_is_rejected_before_persistence(self):
        unsafe = {**self.body, "metadata": {"secret_token": "do-not-store"}}
        with self.assertRaisesRegex(RuntimeDenied, "UNSAFE_INPUT"):
            await self._run(proposal=unsafe)
        self.assertEqual(self.ledger._conn.execute("SELECT count(*) FROM spending_proposals").fetchone()[0], 0)

    async def test_audit_chain_and_result_tamper_fail_closed_after_restart(self):
        result = await self._run()
        run_id = result["run_id"]
        self.store.verify(run_id)
        self.store.conn.execute("UPDATE runtime_events SET event_hash='bad' WHERE run_id=? AND sequence=2",
                                (run_id,))
        with self.assertRaisesRegex(RuntimeDenied, "AUDIT_INTEGRITY_CONFLICT"):
            self.store.verify(run_id)
        with self.assertRaisesRegex(RuntimeDenied, "AUDIT_INTEGRITY_CONFLICT"):
            await self._run()

    async def test_signed_attestation_requires_real_ed25519(self):
        result = await self._run()
        event = self.store.verify(result["run_id"])[-1]
        key = Ed25519PrivateKey.generate()
        signer = b58encode(key.public_key().public_bytes_raw())
        self.store.approved_attestors = frozenset({signer})
        with self.assertRaisesRegex(RuntimeDenied, "INVALID_ATTESTATION"):
            self.store.attest(event["event_id"], signer, b58encode(b"0" * 64))
        self.store.attest(event["event_id"], signer,
                          b58encode(key.sign(bytes.fromhex(event["event_hash"]))))
        self.assertEqual(self.store.verify(result["run_id"])[-1]["attestation"], "SIGNED")

    async def test_tool_timeout_and_concurrent_idempotency(self):
        spec = ToolSpec("slow", "slow", "test", "fixture", "LOCAL_READ_ONLY",
            frozenset(), "LOW", True, frozenset({"ANALYST"}), 10, 1, {}, {"ok": bool})
        async def slow(args, principal):
            await asyncio.sleep(.1)
            return {"ok": True}
        registry = ToolRegistry()
        registry.register(spec, slow)
        self.runtime.registry = registry
        self.runtime.planner = StaticPlanner([{"tool_id": "slow", "arguments": {}}])
        self.gate.put(self.identity, admin_token=self.admin_token, allowed_tools={"slow"}, scopes=set())
        result = await self._run()
        self.assertEqual((result["status"], result["error_code"]), ("FAILED", "TIMEOUT"))
        self.runtime.registry = mcp_registry(self.service, offline_quotes={"CardFixtureA": 80})
        self.runtime.planner = DeterministicPlanner()
        self.gate.put(self.identity, admin_token=self.admin_token, allowed_tools=self.allow, scopes=set())
        outcomes = await asyncio.gather(self._run(idempotency_key="concurrent-1"),
                                        self._run(idempotency_key="concurrent-1"),
                                        return_exceptions=True)
        self.assertTrue(any(isinstance(x, dict) for x in outcomes))
        self.assertEqual(self.store.conn.execute("SELECT count(*) FROM runtime_runs WHERE idempotency_key=?",
                         ("concurrent-1",)).fetchone()[0], 1)

    async def test_cancel_pending_requires_owner_token_and_scope(self):
        result = await self._run()
        with self.assertRaisesRegex(RuntimeDenied, "POLICY_DENIED"):
            self.runtime.cancel(result["run_id"], self.identity, token=self.token)
        with self.assertRaises(Exception):
            self.runtime.cancel(result["run_id"], self.identity,
                                token=self._token(subject=OTHER, scopes=("runtime:cancel",)))
        self.runtime.cancel(result["run_id"], self.identity,
                            token=self._token(scopes=("runtime:cancel",)))
        self.assertEqual(self.store.snapshot(result["run_id"], self.identity)["status"], "CANCELED")
        self.assertEqual(self.ledger._conn.execute("SELECT count(*) FROM economic_movements").fetchone()[0], 0)

    async def test_cancellation_while_tool_is_running_discards_observation(self):
        entered, release = asyncio.Event(), asyncio.Event()
        original = self.registry._tools["conatus_search_agents"]
        async def paused(args, principal):
            entered.set()
            await release.wait()
            return await original[1](args, principal)
        self.registry._tools["conatus_search_agents"] = (original[0], paused)
        task = asyncio.create_task(self._run(idempotency_key="cancel-mid-run"))
        await asyncio.wait_for(entered.wait(), 1)
        run_id = self.store.conn.execute("SELECT run_id FROM runtime_runs WHERE idempotency_key=?",
                                         ("cancel-mid-run",)).fetchone()[0]
        self.runtime.cancel(run_id, self.identity,
                            token=self._token(scopes=("runtime:cancel",)))
        release.set()
        result = await task
        self.assertEqual(result["status"], "CANCELED")
        self.assertEqual(self.store.snapshot(run_id, self.identity)["status"], "CANCELED")
        self.assertEqual(self.ledger._conn.execute("SELECT count(*) FROM spending_proposals").fetchone()[0], 0)

    async def test_restart_preserves_chain_and_rejects_replay_after_policy_change(self):
        result = await self._run()
        path = self.store.conn.execute("PRAGMA database_list").fetchone()[2]
        self.store.close()
        self.store = RuntimeStore(path)
        self.gate = PolicyGate(self.store, self.admin_verifier)
        self.runtime.store, self.runtime.gate = self.store, self.gate
        self.assertEqual(self.store.snapshot(result["run_id"], self.identity)["status"],
                         "AWAITING_APPROVAL")
        self.assertEqual(await self._run(), result)
        self.gate.put(self.identity, admin_token=self.admin_token,
                      allowed_tools=self.allow, scopes=set())
        with self.assertRaisesRegex(RuntimeDenied, "IDEMPOTENCY_CONFLICT"):
            await self._run()

    async def test_tool_error_fails_closed_and_no_rpc_claim(self):
        self.runtime.planner = StaticPlanner([{"tool_id": "conatus_get_agent_card",
            "arguments": {"card_id": "MissingCard"}}])
        result = await self._run()
        self.assertEqual(result["status"], "DENIED")
        self.assertEqual(result["error_code"], "TOOL_UNAVAILABLE")
        self.assertNotIn("LIVE_RPC", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
