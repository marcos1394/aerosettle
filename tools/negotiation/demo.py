"""Python requester and Node provider negotiate an offline advisory proposal."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import time

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from tools.discovery.agent_discovery import b58encode
from tools.economic_ledger.budget_policies import BudgetPolicyStore
from tools.economic_ledger.ledger import EconomicLedger
from tools.economic_ledger.spending_decisions import SpendingDecisionStore
from tools.economic_ledger.test_budget_policies import (AGENT, AGENT_RECORD, MINT, OTHER,
    OWNER, SECRET, body as policy_body)

from .a2a_adapter import decode, encode
from .canonical import DOMAIN, canonical, digest
from .identity import IdentityVerifier, TrustedContext
from .models import TERMS, VERSION
from .negotiation import NegotiationService
from .policy import EconomicPolicyGate
from .signatures import sign
from .store import NegotiationStore

PROVIDER_ACCOUNT = b58encode(bytes([6]) * 32)
PROVIDER_ID = "22" * 32
NODE_PROVIDER = Path(__file__).with_name("demo_provider.cjs")


def fixture(now: int):
    policy = policy_body()
    context = TrustedContext(policy["network"], policy["genesis_hash"],
                             policy["program_id"], MINT, 6)
    requester = {**AGENT_RECORD, "network": context.network,
        "genesis_hash": context.genesis_hash, "program_id": context.program_id,
        "tenant_id": "tenant-demo", "organization_id": "org-demo",
        "status": "Active", "active": True, "signing_authority": ""}
    provider = {**requester, "agent_account": PROVIDER_ACCOUNT,
        "agent_id": PROVIDER_ID, "owner": OTHER}
    registry = {AGENT: requester, PROVIDER_ACCOUNT: provider}
    return policy, context, registry


def message(kind: str, now: int, registry: dict, context: TrustedContext,
            sequence: int, *, parent: dict | None = None, amount: str = "100") -> dict:
    requester, provider = registry[AGENT], registry[PROVIDER_ACCOUNT]
    sender = requester if kind in {"RFQ", "AcceptIntent", "RejectIntent"} else provider
    data = {"protocol_version": VERSION, "type": kind,
        "negotiation_id": "neg-demo-0001", "message_id": f"message-{sequence:08d}",
        "parent_message_id": parent["message_id"] if parent else "",
        "parent_hash": digest(parent) if parent else "",
        "requester_agent_id": requester["agent_id"],
        "provider_agent_id": provider["agent_id"],
        "requester_agent_account": requester["agent_account"],
        "provider_agent_account": provider["agent_account"],
        "invited_provider_accounts": [provider["agent_account"]],
        "agent_account": sender["agent_account"],
        "owner_pubkey": sender["owner"],
        "signing_authority": sender["signing_authority"],
        "tenant_id": "tenant-demo", "organization_id": "org-demo",
        "network": context.network, "genesis_hash": context.genesis_hash,
        "program_id": context.program_id, "token_mint": context.token_mint,
        "token_decimals": context.token_decimals, "amount_base_units_str": amount,
        "quantity": 1, "service_id": "data-analysis", "service_description": "Analyze data",
        "sla": "delivery-within-24h", "delivery_deadline": now + 1800,
        "expires_at": now + (1800 if kind == "RFQ" else 600),
        "nonce": f"nonce-{sequence:08d}", "round": 0 if kind == "RFQ" else
            1 if kind == "Quote" else 2 if kind == "Counteroffer" else parent["round"],
        "idempotency_key": f"idempotency-{sequence:08d}", "signature": ""}
    if kind in {"AcceptIntent", "RejectIntent"}:
        for key in TERMS:
            data[key] = parent[key]
    data["terms_hash"] = digest({key: data[key] for key in TERMS})
    return data


def provider_sign(data: dict) -> dict:
    done = subprocess.run(["node", str(NODE_PROVIDER)], input=canonical(data),
                          capture_output=True, check=True, timeout=5)
    return json.loads(done.stdout)


def history_proof(negotiation_id: str, account: str, now: int) -> str:
    challenge = DOMAIN + b"HISTORY\n" + canonical({"negotiation_id": negotiation_id,
        "requester_account": account, "signed_at": now})
    return b58encode(Ed25519PrivateKey.from_private_bytes(SECRET).sign(challenge))


def run_demo() -> dict:
    now = int(time.time())
    policy_body_value, context, registry = fixture(now)
    with tempfile.TemporaryDirectory() as directory:
        db = Path(directory)
        ledger = EconomicLedger(db / "ledger.sqlite")
        store = NegotiationStore(db / "negotiation.sqlite")
        try:
            policies = BudgetPolicyStore(ledger)
            policies.mutate(AGENT_RECORD, "CREATE", policy_body_value, OWNER)
            policies.mutate(AGENT_RECORD, "ACTIVATE",
                policy_body("ACTIVATE", 1, "00000002"), OWNER)
            decisions = SpendingDecisionStore(ledger, policies)
            identity = IdentityVerifier(lambda account: registry.get(account), context)
            service = NegotiationService(store, identity, EconomicPolicyGate(policies, decisions))
            tables = ("economic_movements", "journal_entries", "ledger_entries",
                "agent_costs", "agent_reserves", "reserve_transactions")
            before = {table: ledger._conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                      for table in tables}
            root = sign(message("RFQ", now, registry, context, 1),
                Ed25519PrivateKey.from_private_bytes(SECRET))
            quote = provider_sign(message("Quote", now, registry, context, 2,
                parent=root, amount="100"))
            counter = provider_sign(message("Counteroffer", now, registry, context, 3,
                parent=quote, amount="80"))
            intent = sign(message("AcceptIntent", now, registry, context, 4,
                parent=counter), Ed25519PrivateKey.from_private_bytes(SECRET))
            for signed_message in (root, quote, counter, intent):
                service.submit(decode(encode(signed_message)))
            selected = service.history(root["negotiation_id"], AGENT, signed_at=now,
                signature=history_proof(root["negotiation_id"], AGENT, now))
            store.close()
            store = NegotiationStore(db / "negotiation.sqlite")
            service = NegotiationService(store, identity, EconomicPolicyGate(policies, decisions))
            recovered = service.history(root["negotiation_id"], AGENT, signed_at=now,
                signature=history_proof(root["negotiation_id"], AGENT, now))
            retry = service.submit(intent)
            after = {table: ledger._conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                     for table in tables}
            proposal = recovered["proposal"]
            audit_last_hash = store.conn.execute("SELECT event_hash FROM negotiation_messages "
                "WHERE negotiation_id=? ORDER BY version DESC LIMIT 1",
                (root["negotiation_id"],)).fetchone()[0]
            report = {"NEGOTIATION_E2E_VERIFIED": selected == recovered,
                "OFFLINE_FIXTURE": True, "SIGNATURES_VERIFIED": True,
                "POLICY_GATE_VERIFIED": proposal["spending_decision"] == "REQUIRE_APPROVAL",
                "WORKORDER_PROPOSAL_CREATED": bool(proposal),
                "ONCHAIN_WORKORDER_CREATED": False, "FUNDS_TRANSFERRED": False,
                "DEVNET_FINANCIAL_EXECUTION": False,
                "approval_status": proposal["approval_status"],
                "selected_quote_id": proposal["accepted_quote_id"],
                "terms_hash": proposal["terms_hash"],
                "message_hashes": [digest(item) for item in recovered["messages"]],
                "audit_last_hash": audit_last_hash,
                "message_count": len(recovered["messages"]),
                "idempotent_replay_verified": not retry["inserted"],
                "sqlite_restart_verified": selected == recovered,
                "financial_tables_unchanged": before == after,
                "provenance": "OFFLINE_FIXTURE", "audit_attestation": "HASH_CHAIN_ONLY"}
            assert all(report[k] for k in ("NEGOTIATION_E2E_VERIFIED", "POLICY_GATE_VERIFIED",
                "WORKORDER_PROPOSAL_CREATED", "idempotent_replay_verified",
                "sqlite_restart_verified", "financial_tables_unchanged"))
            return report
        finally:
            store.close()
            ledger.close()


if __name__ == "__main__":
    print(json.dumps(run_demo(), sort_keys=True))
