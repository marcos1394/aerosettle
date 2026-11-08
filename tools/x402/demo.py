"""Reproducible localhost HTTP V2 demonstration; every signature is sandbox-only."""
from __future__ import annotations

import hashlib
import json
import tempfile
import time
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from tools.discovery.agent_discovery import b58encode
from tools.economic_ledger.budget_policies import BudgetPolicyStore
from tools.economic_ledger.ledger import EconomicLedger
from tools.economic_ledger.spending_approvals import (CONTEXT_FIELDS, SpendingApprovalStore,
    canonical_approval_message)
from tools.economic_ledger.spending_decisions import SpendingDecisionStore
from tools.economic_ledger.test_budget_policies import (AGENT, AGENT_RECORD, OTHER,
    OWNER, SECRET, body as policy_body)

from .client import SandboxClient
from .common import Context, SandboxError, digest
from .facilitator import FacilitatorHTTP, SandboxFacilitator
from .transport import LocalHTTP
from .policy import PaymentPolicyGate
from .server import ResourceServer
from .signer import SandboxSigner, public_key, sign
from .store import SandboxStore

PROVIDER_ACCOUNT = b58encode(bytes([6]) * 32)
FINANCIAL_TABLES = ("economic_movements", "journal_entries", "ledger_entries",
                    "agent_costs", "agent_reserves", "reserve_transactions")


def fixtures(context: Context):
    requester = {**AGENT_RECORD, "network": "solana:devnet",
                 "genesis_hash": context.genesis_hash, "program_id": context.program_id,
                 "status": "Active", "active": True, "signing_authority": ""}
    provider = {**requester, "agent_account": PROVIDER_ACCOUNT,
                "agent_id": "22" * 32, "owner": OTHER}
    return {AGENT: requester, PROVIDER_ACCOUNT: provider}


def setup_policy(policies: BudgetPolicyStore, context: Context):
    config = policy_body()
    config.update(network="solana:devnet", genesis_hash=context.genesis_hash,
                  program_id=context.program_id, allowed_recipients=[OTHER])
    config["asset_rules"][0].update(token_mint=context.asset,
        max_per_operation_base_units_str="1000", max_daily_spend_base_units_str="10000",
        minimum_reserve_base_units_str="0")
    policies.mutate(AGENT_RECORD, "CREATE", config, OWNER)
    policies.mutate(AGENT_RECORD, "ACTIVATE", policy_body("ACTIVATE", 1, "00000002"), OWNER)


def approval_provider(approvals: SpendingApprovalStore, decision_id: str) -> str:
    context = approvals.context(AGENT_RECORD, decision_id)
    expiry = min(context["decision"]["expires_at"], int(time.time()) + 120)
    private = Ed25519PrivateKey.from_private_bytes(SECRET)
    for action in ("OPEN", "APPROVE"):
        now = int(time.time())
        body = {**{key: context[key] for key in CONTEXT_FIELDS},
                "action": action, "issued_at": now, "expires_at": expiry,
                "nonce": f"x402-approval-{action.lower()}-{digest(context['proposal'])[:24]}",
                "idempotency_key": f"x402-approval-{action.lower()}-{decision_id}",
                "reason": "Offline x402 fixture review"}
        path = f"/v1/agents/{AGENT}/spending-approvals"
        if action == "APPROVE":
            path += f"/{context['approval_id']}/approve"
        message = canonical_approval_message(now, AGENT, OWNER, "POST", path, body)
        signature = b58encode(private.sign(message))
        approvals.mutate(AGENT_RECORD, action, body, OWNER, signature,
                         hashlib.sha256(message).hexdigest(), now=now)
    return context["approval_id"]


def run_demo() -> dict:
    context = Context.fixture()
    registry = fixtures(context)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ledger = EconomicLedger(root / "ledger.sqlite")
        payment_store = SandboxStore(root / "payments.sqlite")
        client_store = SandboxStore(root / "client.sqlite")
        try:
            policies = BudgetPolicyStore(ledger)
            setup_policy(policies, context)
            decisions = SpendingDecisionStore(ledger, policies)
            approvals = SpendingApprovalStore(ledger, policies, decisions)
            gate = PaymentPolicyGate(policies, decisions, approvals, registry.get)
            before = {table: ledger._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                      for table in FINANCIAL_TABLES}
            server_key = Ed25519PrivateKey.generate()
            signer = SandboxSigner()
            facilitator = SandboxFacilitator(payment_store, context, gate, registry.get,
                server_pubkey=public_key(server_key),
                sandbox_signer_pubkey=signer.public_key)
            with LocalHTTP(FacilitatorHTTP(facilitator)) as facilitator_http:
                server = ResourceServer(payment_store, context, client_agent_account=AGENT,
                    provider_agent_account=PROVIDER_ACCOUNT, recipient=OTHER,
                    facilitator_url=facilitator_http.base_url,
                    facilitator_id=facilitator.facilitator_id,
                    facilitator_pubkey=facilitator.public_key, key=server_key)
                with LocalHTTP(server) as resource_http:
                    server.bind(resource_http.base_url)
                    owner_key = Ed25519PrivateKey.from_private_bytes(SECRET)
                    client = SandboxClient(context, client_store, gate, signer,
                        resource_url=resource_http.base_url + "/premium-resource",
                        facilitator_url=facilitator_http.base_url,
                        resource_server_pubkey=server.public_key,
                        facilitator_pubkey=facilitator.public_key,
                        client_agent_account=AGENT, provider_agent_account=PROVIDER_ACCOUNT,
                        pay_to=OTHER, max_amount="1000", owner_pubkey=OWNER,
                        owner_authorize=lambda terms: sign(owner_key, b"OWNER-AUTHORIZATION\n", terms),
                        approval_provider=lambda terms, decision_id: approval_provider(approvals, decision_id))
                    first = client.pay()
                    second = client.retry()
                    payment_id = first["receipt"]["payment_id"]
                    settled = payment_store.settlement(payment_id)
                    count = payment_store.conn.execute("SELECT COUNT(*) FROM sandbox_settlements").fetchone()[0]
                    deliveries = payment_store.conn.execute("SELECT COUNT(*) FROM sandbox_deliveries").fetchone()[0]
                    after = {table: ledger._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                             for table in FINANCIAL_TABLES}
            payment_store.close()
            client_store.close()
            payment_store = SandboxStore(root / "payments.sqlite")
            client_store = SandboxStore(root / "client.sqlite")
            recovered = payment_store.settlement(payment_id)
            saved = client_store.conn.execute("SELECT * FROM sandbox_client_receipts").fetchone()
            client_store._check(saved)
            report = {"X402_V2_PROTOCOL_VERIFIED": first == second,
                "SANDBOX_SIMULATION": first["receipt"]["evidence_source"] == "SANDBOX_SIMULATION",
                "POLICY_GATE_VERIFIED": approvals.list(AGENT_RECORD)[0]["approval_status"] == "APPROVED",
                "RESOURCE_AUTHORIZATION_VERIFIED": first["resource"] == server.resource,
                "REPLAY_PROTECTION_VERIFIED": count == 1,
                "DOUBLE_CHARGE_PREVENTION_VERIFIED": count == 1 and deliveries == 1,
                "SQLITE_RESTART_VERIFIED": settled == recovered and saved is not None,
                "FINANCIAL_TABLES_UNCHANGED": before == after,
                "ONCHAIN_TRANSACTIONS_SENT": 0, "DEVNET_SETTLEMENT_VERIFIED": False,
                "MAINNET_USED": False, "receipt_id": first["receipt"]["receipt_id"],
                "payment_requirements_hash": first["receipt"]["payment_requirements_hash"],
                "payment_payload_hash": first["receipt"]["payment_payload_hash"],
                "receipt_evidence_source": first["receipt"]["evidence_source"],
                "settlement_status": first["receipt"]["settlement_status"],
                "transaction_signature": first["receipt"]["transaction_signature"],
                "network": first["receipt"]["network"], "genesis_hash": context.genesis_hash,
                "asset": context.asset, "scheme": "conatus-sandbox-exact",
                "provenance": context.provenance}
            assert all(report[key] for key in ("X402_V2_PROTOCOL_VERIFIED", "SANDBOX_SIMULATION",
                "POLICY_GATE_VERIFIED", "RESOURCE_AUTHORIZATION_VERIFIED", "REPLAY_PROTECTION_VERIFIED",
                "DOUBLE_CHARGE_PREVENTION_VERIFIED", "SQLITE_RESTART_VERIFIED",
                "FINANCIAL_TABLES_UNCHANGED"))
            return report
        finally:
            payment_store.close(); client_store.close(); ledger.close()


if __name__ == "__main__":
    print(json.dumps(run_demo(), sort_keys=True))
