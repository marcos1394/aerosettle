"""Strict versioned wire schema and exact monetary validation."""
from __future__ import annotations

import re
from .canonical import digest
from tools.discovery.agent_discovery import b58decode, DiscoveryError

VERSION = "conatus.agent-negotiation.v1"
TYPES = {"RFQ", "Quote", "Counteroffer", "AcceptIntent", "RejectIntent"}
ID = re.compile(r"[A-Za-z0-9._:-]{8,128}\Z")
HEX = re.compile(r"[0-9a-f]{64}\Z")
U64 = 2**64 - 1
UNSAFE = re.compile(r"(?i)(ignore\s+(all\s+)?(previous|system)\s+instructions|"
                    r"system\s+prompt|private\s+key|seed\s+phrase|"
                    r"(transfer|send)\s+funds|execute\s+settlement|create\s+escrow)")
TERMS = ("token_mint", "token_decimals", "amount_base_units_str", "quantity",
         "service_id", "service_description", "sla", "delivery_deadline")
FIELDS = frozenset({"protocol_version", "type", "negotiation_id", "message_id",
    "parent_message_id", "parent_hash", "requester_agent_id", "provider_agent_id",
    "requester_agent_account", "provider_agent_account", "agent_account",
    "invited_provider_accounts",
    "owner_pubkey", "signing_authority", "tenant_id", "organization_id",
    "network", "genesis_hash", "program_id", "token_mint", "token_decimals",
    "amount_base_units_str", "quantity", "service_id", "service_description",
    "sla", "delivery_deadline", "expires_at", "nonce", "terms_hash", "round",
    "idempotency_key", "signature"})


class NegotiationError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _pk(value: str) -> None:
    try:
        b58decode(value, 32)
    except (DiscoveryError, TypeError) as exc:
        raise NegotiationError("INVALID_CONTEXT") from exc


def validate(message: dict) -> None:
    if not isinstance(message, dict) or set(message) != FIELDS:
        raise NegotiationError("INVALID_SCHEMA")
    if (message["protocol_version"] != VERSION or
            not isinstance(message["type"], str) or message["type"] not in TYPES):
        raise NegotiationError("UNSUPPORTED_VERSION_OR_TYPE")
    if any(not isinstance(message[k], str) or not ID.fullmatch(message[k]) for k in
           ("negotiation_id", "message_id", "nonce", "idempotency_key")):
        raise NegotiationError("INVALID_IDENTIFIER")
    if not isinstance(message["parent_message_id"], str) or not isinstance(message["parent_hash"], str):
        raise NegotiationError("INVALID_PARENT")
    if message["type"] == "RFQ":
        if message["parent_message_id"] or message["parent_hash"] or message["round"] != 0:
            raise NegotiationError("INVALID_PARENT")
    elif not ID.fullmatch(message["parent_message_id"]) or not HEX.fullmatch(message["parent_hash"]):
        raise NegotiationError("INVALID_PARENT")
    for key in ("requester_agent_id", "provider_agent_id"):
        if not isinstance(message[key], str) or not HEX.fullmatch(message[key]):
            raise NegotiationError("INVALID_IDENTITY")
    for key in ("requester_agent_account", "provider_agent_account", "agent_account",
                "owner_pubkey", "genesis_hash", "program_id", "token_mint"):
        _pk(message[key])
    invited = message["invited_provider_accounts"]
    if (not isinstance(invited, list) or not 1 <= len(invited) <= 16 or
            any(not isinstance(account, str) for account in invited) or
            len(set(invited)) != len(invited)):
        raise NegotiationError("INVALID_PROVIDERS")
    for account in invited:
        _pk(account)
    if message["provider_agent_account"] not in invited:
        raise NegotiationError("INVALID_PROVIDERS")
    if message["requester_agent_account"] in invited:
        raise NegotiationError("INVALID_PROVIDERS")
    if message["signing_authority"]:
        _pk(message["signing_authority"])
    for key in ("tenant_id", "organization_id", "network", "service_id"):
        if not isinstance(message[key], str) or not 1 <= len(message[key]) <= 128:
            raise NegotiationError("INVALID_CONTEXT")
    if message["network"] == "PENDING_RESOLUTION":
        raise NegotiationError("INVALID_CONTEXT")
    if (not isinstance(message["service_description"], str) or
            not 1 <= len(message["service_description"]) <= 500 or
            any(ord(c) < 32 for c in message["service_description"]) or
            UNSAFE.search(message["service_description"])):
        raise NegotiationError("INVALID_SERVICE")
    if not isinstance(message["sla"], str) or not 1 <= len(message["sla"]) <= 200:
        raise NegotiationError("INVALID_SLA")
    if (type(message["amount_base_units_str"]) is not str or
            not re.fullmatch(r"[1-9][0-9]*", message["amount_base_units_str"]) or
            int(message["amount_base_units_str"]) > U64):
        raise NegotiationError("INVALID_AMOUNT")
    for key, minimum, maximum in (("token_decimals", 0, 18), ("quantity", 1, 1_000_000),
                                  ("round", 0, 100), ("delivery_deadline", 1, 2**53),
                                  ("expires_at", 1, 2**53)):
        if type(message[key]) is not int or not minimum <= message[key] <= maximum:
            raise NegotiationError("INVALID_SCHEMA")
    if (not isinstance(message["terms_hash"], str) or
            not HEX.fullmatch(message["terms_hash"]) or
            message["terms_hash"] != digest({k: message[k] for k in TERMS})):
        raise NegotiationError("TERMS_TAMPERED")
    if not isinstance(message["signature"], str) or len(message["signature"]) > 128:
        raise NegotiationError("INVALID_SIGNATURE")
    from .canonical import canonical
    try:
        size = len(canonical(message))
    except (TypeError, ValueError, OverflowError) as exc:
        raise NegotiationError("INVALID_SCHEMA") from exc
    if size > 8192:
        raise NegotiationError("MESSAGE_TOO_LARGE")
