"""Fresh AgentAccount projection plus independently approved monetary context."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Callable
from .models import NegotiationError
from .signatures import verify


@dataclass(frozen=True)
class TrustedContext:
    network: str
    genesis_hash: str
    program_id: str
    token_mint: str
    token_decimals: int
    provenance: str = "OFFLINE_FIXTURE"

    def __post_init__(self):
        if self.provenance not in {"OFFLINE_FIXTURE", "VERIFIED_IDENTITY"}:
            raise NegotiationError("UNVERIFIABLE")

    @classmethod
    def verified_devnet(cls) -> TrustedContext:
        """Read-only CON-35 trust and finalized RPC checks; no signing or writes."""
        from tools.a2a.trust import (APPROVED_IDL, GENESIS_HASH, NETWORK,
            PROGRAM_ID, RPC_URL, verify_approved_identity, verify_live_program)
        from tools.deployment.devnet import Rpc
        from tools.deployment import test_mint
        plan_path = Path(__file__).resolve().parents[2] / "evidence/con35/test-mint-verified.json"
        try:
            verify_approved_identity(APPROVED_IDL, RPC_URL)
            rpc = Rpc(RPC_URL)
            if rpc.call("getGenesisHash") != GENESIS_HASH:
                raise NegotiationError("UNTRUSTED_CONTEXT")
            verify_live_program(rpc)
            plan = json.loads(plan_path.read_text())
            test_mint.check_plan(plan)
            if (plan["verification_status"] != "VERIFIED" or
                    plan["network"] != NETWORK or plan["genesis_hash"] != GENESIS_HASH):
                raise NegotiationError("UNTRUSTED_CONTEXT")
            verified = test_mint.verify(plan, rpc, plan["creation_signature"])
            if verified != plan:
                raise NegotiationError("UNTRUSTED_CONTEXT")
            return cls(NETWORK, GENESIS_HASH, PROGRAM_ID, plan["mint_pubkey"],
                       plan["decimals"], "VERIFIED_IDENTITY")
        except NegotiationError:
            raise
        except Exception as exc:
            raise NegotiationError("UNTRUSTED_CONTEXT") from exc


class IdentityVerifier:
    """supplier(account) must return a fresh, independently sourced projection."""

    def __init__(self, supplier: Callable[[str], dict], context: TrustedContext,
                 *, refresh_context: Callable[[], TrustedContext] | None = None):
        if context.provenance == "VERIFIED_IDENTITY" and refresh_context is None:
            raise NegotiationError("UNVERIFIABLE")
        self.supplier, self.context, self.refresh_context = supplier, context, refresh_context

    def check(self, message: dict) -> dict:
        if self.refresh_context is not None and self.refresh_context() != self.context:
            raise NegotiationError("UNTRUSTED_CONTEXT")
        if (message["network"], message["genesis_hash"], message["program_id"],
                message["token_mint"], message["token_decimals"]) != (
                self.context.network, self.context.genesis_hash, self.context.program_id,
                self.context.token_mint, self.context.token_decimals):
            raise NegotiationError("UNTRUSTED_CONTEXT")
        requester = self._agent(message["requester_agent_account"], message["requester_agent_id"], message)
        provider = self._agent(message["provider_agent_account"], message["provider_agent_id"], message)
        for account in message["invited_provider_accounts"]:
            self._agent(account, None, message)
        if message["type"] in {"RFQ", "AcceptIntent", "RejectIntent"}:
            sender = requester
        else:
            sender = provider
        if message["agent_account"] != sender["agent_account"] or (
                message["owner_pubkey"] != sender["owner"] or
                message["signing_authority"] != (sender.get("signing_authority") or "")):
            raise NegotiationError("IDENTITY_MISMATCH")
        authority = sender.get("signing_authority") or sender["owner"]
        verify(message, authority)
        return requester

    def _agent(self, account: str, agent_id: str | None, message: dict) -> dict:
        agent = self.supplier(account)
        if (not isinstance(agent, dict) or agent.get("agent_account") != account or
                (agent_id is not None and agent.get("agent_id") != agent_id) or
                agent.get("status") != "Active" or
                agent.get("active") is not True or not agent.get("owner") or
                agent.get("tenant_id") != message["tenant_id"] or
                agent.get("organization_id") != message["organization_id"] or
                (agent.get("network"), agent.get("genesis_hash"), agent.get("program_id")) !=
                (self.context.network, self.context.genesis_hash, self.context.program_id)):
            raise NegotiationError("IDENTITY_MISMATCH")
        return agent
