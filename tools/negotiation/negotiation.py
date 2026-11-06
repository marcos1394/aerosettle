"""Bounded RFQ state machine with independent identity and economic gates."""
from __future__ import annotations

from dataclasses import dataclass
import json
import time

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from tools.discovery.agent_discovery import b58decode, DiscoveryError

from tools.operations.structured_logs import emit
from .canonical import canonical, digest, DOMAIN
from .comparison import compare, require_eligible
from .identity import IdentityVerifier
from .models import NegotiationError, TERMS, validate
from .policy import EconomicPolicyGate
from .store import NegotiationStore


@dataclass(frozen=True)
class Limits:
    max_providers: int = 4
    max_rounds: int = 3
    max_duration_seconds: int = 3600
    max_quote_ttl_seconds: int = 900
    max_amount_base_units: int = 1_000_000_000
    max_deviation_bps: int = 2500
    max_quantity: int = 100
    max_calls_per_agent: int = 20
    max_concurrent: int = 4

    def __post_init__(self):
        if (min(self.max_providers, self.max_rounds, self.max_duration_seconds,
                self.max_quote_ttl_seconds, self.max_amount_base_units,
                self.max_quantity, self.max_calls_per_agent, self.max_concurrent) < 1 or
                not 0 <= self.max_deviation_bps <= 10000):
            raise NegotiationError("INVALID_LIMITS")


class NegotiationService:
    def __init__(self, store: NegotiationStore, identity: IdentityVerifier,
                 economic_gate, *, limits: Limits | None = None, clock=None,
                 operational_store=None):
        if type(economic_gate) is not EconomicPolicyGate:
            raise NegotiationError("ECONOMIC_GATE_UNAVAILABLE")
        if (identity.context.provenance == "VERIFIED_IDENTITY" and
                economic_gate.decision_store.test_evidence_provider is not None):
            raise NegotiationError("UNVERIFIABLE")
        self.store, self.identity, self.economic_gate = store, identity, economic_gate
        self.limits = limits or Limits()
        self.clock = clock or (lambda: int(time.time()))
        self.operational_store = operational_store

    def _log(self, message: dict, code: str, policy_version: int | None = None) -> None:
        try:
            emit("INFO" if code == "ACCEPTED" else "WARNING", "negotiation", "message",
                 correlation_id=message["negotiation_id"], status=message["type"],
                 error_category=None if code == "ACCEPTED" else code,
                 authorization_result=code)
            if self.operational_store is not None:
                self.operational_store.sample("negotiation_messages" if code == "ACCEPTED"
                    else "negotiation_denials", 1, "events", "agent-negotiation")
        except Exception:
            pass

    def submit(self, message: dict) -> dict:
        validate(message)
        now = self.clock()
        requester = self.identity.check(message)
        if message["expires_at"] <= now or message["delivery_deadline"] <= now:
            raise NegotiationError("EXPIRED")
        def transition(session: dict | None, history: list[dict]):
            # Recheck inside the write transaction so identity revocation cannot be
            # converted into a stored commercial intent by a racing request.
            current_requester = self.identity.check(message)
            if message["type"] == "RFQ":
                if session is not None:
                    raise NegotiationError("OUT_OF_ORDER")
                if (len(message["invited_provider_accounts"]) > self.limits.max_providers or
                        message["quantity"] > self.limits.max_quantity or
                        int(message["amount_base_units_str"]) > self.limits.max_amount_base_units or
                        message["expires_at"] > now + self.limits.max_duration_seconds):
                    raise NegotiationError("LIMIT_EXCEEDED")
                active = self.store.conn.execute("SELECT COUNT(*) FROM negotiation_sessions WHERE "
                    "requester_account=? AND state NOT IN ('INTENT_ACCEPTED','INTENT_REJECTED','EXPIRED','CANCELED','FAILED')",
                    (message["requester_agent_account"],)).fetchone()[0]
                if active >= self.limits.max_concurrent:
                    raise NegotiationError("CONCURRENCY_LIMIT")
                return "RFQ_SENT", None, None
            if session is None:
                raise NegotiationError("OUT_OF_ORDER")
            root = history[0]
            if session["state"] in {"INTENT_ACCEPTED", "INTENT_REJECTED", "CANCELED", "FAILED"}:
                raise NegotiationError("TERMINAL_STATE")
            if now >= root["expires_at"]:
                raise NegotiationError("EXPIRED")
            stable = ("requester_agent_id", "requester_agent_account", "tenant_id",
                "organization_id", "network", "genesis_hash", "program_id", "token_mint",
                "token_decimals", "service_id", "service_description", "invited_provider_accounts")
            if any(message[k] != root[k] for k in stable):
                raise NegotiationError("CONTEXT_MISMATCH")
            if (session["requester_account"] != current_requester["agent_account"] or
                    session["tenant_id"] != message["tenant_id"] or
                    session["organization_id"] != message["organization_id"]):
                raise NegotiationError("IDENTITY_MISMATCH")
            if sum(m["agent_account"] == message["agent_account"] for m in history) >= self.limits.max_calls_per_agent:
                raise NegotiationError("CALL_LIMIT")
            parent = next((m for m in history if m["message_id"] == message["parent_message_id"]), None)
            if parent is None or digest(parent) != message["parent_hash"]:
                raise NegotiationError("INVALID_PARENT")
            if (message["type"] in {"Quote", "Counteroffer"} and
                    message["expires_at"] > now + self.limits.max_quote_ttl_seconds):
                raise NegotiationError("QUOTE_TTL_EXCEEDED")
            if (message["quantity"] > self.limits.max_quantity or
                    int(message["amount_base_units_str"]) > self.limits.max_amount_base_units):
                raise NegotiationError("LIMIT_EXCEEDED")
            if message["type"] == "Quote":
                if parent != root or message["round"] != 1:
                    raise NegotiationError("OUT_OF_ORDER")
                if any(m["type"] == "Quote" and m["provider_agent_account"] ==
                       message["provider_agent_account"] for m in history):
                    raise NegotiationError("DOUBLE_QUOTE")
                if (int(message["amount_base_units_str"]) * 10000 >
                        int(root["amount_base_units_str"]) * (10000 + self.limits.max_deviation_bps)):
                    raise NegotiationError("DEVIATION_LIMIT")
                return "QUOTING", None, None
            if message["type"] == "Counteroffer":
                if (parent["type"] not in {"Quote", "Counteroffer"} or
                        parent["provider_agent_account"] != message["provider_agent_account"] or
                        message["round"] != parent["round"] + 1 or
                        message["round"] > self.limits.max_rounds or
                        any(m["parent_message_id"] == parent["message_id"] for m in history)):
                    raise NegotiationError("OUT_OF_ORDER")
                if (int(message["amount_base_units_str"]) * 10000 >
                        int(root["amount_base_units_str"]) * (10000 + self.limits.max_deviation_bps)):
                    raise NegotiationError("DEVIATION_LIMIT")
                return "COUNTEROFFER_PENDING", None, None
            if (message["type"] == "RejectIntent" and parent == root and
                    message["round"] == 0 and
                    all(message[k] == root[k] for k in TERMS)):
                return "CANCELED", None, None
            if message["type"] not in {"AcceptIntent", "RejectIntent"} or (
                    parent["type"] not in {"Quote", "Counteroffer"} or
                    message["round"] != parent["round"] or
                    any(message[k] != parent[k] for k in TERMS) or
                    message["provider_agent_account"] != parent["provider_agent_account"] or
                    message["provider_agent_id"] != parent["provider_agent_id"]):
                raise NegotiationError("OUT_OF_ORDER")
            if message["type"] == "RejectIntent":
                return "INTENT_REJECTED", None, None
            offers = [m for m in history if m["type"] in {"Quote", "Counteroffer"} and
                      not any(child["type"] == "Counteroffer" and
                              child["parent_message_id"] == m["message_id"] for child in history)]
            ranked = compare(offers, budget=int(root["amount_base_units_str"]),
                quantity=root["quantity"], sla=root["sla"],
                deadline=root["delivery_deadline"], now=now)
            require_eligible(ranked, parent["message_id"])
            if not ranked or ranked[0]["message_id"] != parent["message_id"]:
                raise NegotiationError("NOT_TOP_RANKED")
            provider = self.identity._agent(parent["provider_agent_account"], parent["provider_agent_id"], parent)
            decision = self.economic_gate.evaluate(current_requester, provider, parent, now)
            if decision["decision"] == "DENY":
                raise NegotiationError("POLICY_DENIED")
            if decision["decision"] not in {"ALLOW", "REQUIRE_APPROVAL"}:
                raise NegotiationError("UNVERIFIABLE_DECISION")
            # A successful policy evaluation is advisory. No approval, payment,
            # escrow, ledger movement, or Anchor call is made here.
            proposal = {"proposal_id": "nwp_" + digest([message["negotiation_id"], parent["message_id"]])[:32],
                "negotiation_id": message["negotiation_id"], "accepted_quote_id": parent["message_id"],
                "requester_identity": {"agent_account": current_requester["agent_account"],
                    "agent_id": current_requester["agent_id"], "owner_pubkey": current_requester["owner"]},
                "provider_identity": {"agent_account": provider["agent_account"],
                    "agent_id": provider["agent_id"], "owner_pubkey": provider["owner"]},
                "agent_account": current_requester["agent_account"],
                "network": parent["network"], "genesis_hash": parent["genesis_hash"],
                "program_id": parent["program_id"], "token_mint": parent["token_mint"],
                "token_decimals": parent["token_decimals"],
                "amount_base_units_str": parent["amount_base_units_str"],
                "payment_model": "OFFCHAIN_PROPOSAL_ONLY", "quantity": parent["quantity"],
                "sla": parent["sla"], "terms_hash": parent["terms_hash"],
                "approval_status": "PENDING_HUMAN_APPROVAL" if decision["decision"] ==
                    "REQUIRE_APPROVAL" else "ELIGIBLE_INTENT_ONLY",
                "policy_version": decision["policy_version"],
                "policy_hash": decision["policy_hash"],
                "spending_decision": decision["decision"],
                "spending_decision_id": decision["decision_id"],
                "provenance": self.identity.context.provenance,
                "is_onchain": False, "escrow_created": False, "funds_transferred": False,
                "settlement_verified": False, "requires_independent_authorization": True}
            return "INTENT_ACCEPTED", parent["message_id"], proposal
        try:
            result, inserted = self.store.append(message, transition,
                lambda history: [self.identity.check(old) for old in history])
            self._log(message, "ACCEPTED")
            return {**result, "inserted": inserted,
                    "negotiation_id": message["negotiation_id"],
                    "provenance": self.identity.context.provenance,
                    "signature_status": "SIGNED_MESSAGE",
                    "is_financial_authority": False}
        except NegotiationError as exc:
            self._log(message, exc.code)
            raise

    def history(self, negotiation_id: str, requester_account: str, *,
                signed_at: int, signature: str) -> dict:
        session, messages = self.store.read(negotiation_id)
        if session["requester_account"] != requester_account:
            raise NegotiationError("NOT_FOUND")
        if type(signed_at) is not int or abs(self.clock() - signed_at) > 300:
            raise NegotiationError("UNAUTHORIZED")
        requester = self.identity._agent(requester_account, messages[0]["requester_agent_id"], messages[0])
        challenge = DOMAIN + b"HISTORY\n" + canonical({"negotiation_id": negotiation_id,
            "requester_account": requester_account, "signed_at": signed_at})
        try:
            Ed25519PublicKey.from_public_bytes(b58decode(requester["owner"], 32)).verify(
                b58decode(signature, 64), challenge)
        except (InvalidSignature, ValueError, DiscoveryError, TypeError) as exc:
            raise NegotiationError("UNAUTHORIZED") from exc
        for message in messages:
            self.identity.check(message)
        state = ("EXPIRED" if session["state"] not in
            {"INTENT_ACCEPTED", "INTENT_REJECTED", "CANCELED", "FAILED"} and
            self.clock() >= messages[0]["expires_at"] else session["state"])
        return {"state": state, "version": session["version"],
                "selected_id": session["selected_id"], "messages": messages,
                "proposal": json.loads(session["proposal_json"])
                    if session["proposal_json"] else None,
                "audit_attestation": "HASH_CHAIN_ONLY",
                "provenance": self.identity.context.provenance}


__all__ = ["NegotiationService", "NegotiationError", "Limits"]
