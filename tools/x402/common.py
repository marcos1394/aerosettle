"""Strict V2 wire and independently pinned local sandbox context."""
from __future__ import annotations

import hashlib
import ipaddress
import json
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

import rfc8785
from x402.schemas import PaymentPayload, PaymentRequired, PaymentRequirements, ResourceInfo
from x402.http.utils import (decode_payment_required_header, decode_payment_response_header,
                             decode_payment_signature_header, encode_payment_required_header,
                             encode_payment_response_header, encode_payment_signature_header)

from tools.discovery.agent_discovery import b58decode
from tools.a2a.trust import GENESIS_HASH, PROGRAM_ID

NETWORK = "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1"
SCHEME = "conatus-sandbox-exact"
TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
DOMAIN = b"CONATUS-X402-SANDBOX-v1\n"
MAX_HEADER = 16384
MAX_BODY = 32768
U64_MAX = 2**64 - 1
APPROVED_TEST_MINT = "HpfaV9oRuTN1b3ktDKvJoWqUWFZ1o9VFmhejxxqQ1vyh"


class SandboxError(Exception):
    def __init__(self, code: str, status: int = 400):
        super().__init__(code)
        self.code, self.status = code, status


def canonical(value: object) -> bytes:
    return rfc8785.dumps(value)


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def pubkey(value: str) -> str:
    try:
        b58decode(value, 32)
    except Exception as exc:
        raise SandboxError("INVALID_SOLANA_ADDRESS") from exc
    return value


def amount(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]*", value) or int(value) > U64_MAX:
        raise SandboxError("INVALID_AMOUNT")
    return value


def local_url(value: str, path: str | None = None) -> str:
    """No DNS, redirects, credentials, external hosts, or ambiguous URL syntax."""
    parsed = None
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        valid = (parsed.scheme == "http" and host == "127.0.0.1" and
                 ipaddress.ip_address(host).is_loopback and parsed.port is not None and
                 parsed.username is None and parsed.password is None and
                 not parsed.query and not parsed.fragment and
                 (path is None or parsed.path == path))
    except (ValueError, TypeError):
        valid = False
    if not valid or value != f"http://127.0.0.1:{parsed.port}{parsed.path}":
        raise SandboxError("UNTRUSTED_ENDPOINT")
    return value


@dataclass(frozen=True)
class Context:
    genesis_hash: str
    program_id: str
    asset: str
    decimals: int
    token_program: str
    provenance: str = "OFFLINE_FIXTURE"

    def __post_init__(self):
        if (self.genesis_hash != GENESIS_HASH or self.program_id != PROGRAM_ID or
                self.token_program != TOKEN_PROGRAM or self.provenance != "OFFLINE_FIXTURE" or
                type(self.decimals) is not int or not 0 <= self.decimals <= 9):
            raise SandboxError("UNTRUSTED_CONTEXT")
        for value in (self.genesis_hash, self.program_id, self.asset, self.token_program):
            pubkey(value)

    @classmethod
    def fixture(cls) -> Context:
        from pathlib import Path
        from tools.deployment.test_mint import check_plan
        manifest = json.loads((Path(__file__).resolve().parents[2] /
                               "evidence/con35/test-mint-verified.json").read_text())
        try:
            check_plan(manifest)
        except Exception as exc:
            raise SandboxError("UNTRUSTED_CONTEXT") from exc
        if (manifest.get("verification_status") != "VERIFIED" or
                manifest.get("genesis_hash") != GENESIS_HASH or
                manifest.get("mint_pubkey") != APPROVED_TEST_MINT or
                manifest.get("mint_account_owner_program") != TOKEN_PROGRAM or
                manifest.get("asset_label") != "DEVNET_TEST_TOKEN"):
            raise SandboxError("UNTRUSTED_CONTEXT")
        return cls(GENESIS_HASH, PROGRAM_ID, manifest["mint_pubkey"],
                   manifest["decimals"], TOKEN_PROGRAM)


def checked_requirements(required: PaymentRequired, context: Context, *,
                         resource_url: str, resource_id: str, pay_to: str,
                         max_amount: str, now: int) -> tuple[PaymentRequirements, dict]:
    if type(required) is not PaymentRequired or required.x402_version != 2 or required.resource is None:
        raise SandboxError("UNSUPPORTED_VERSION")
    if required.resource.url != local_url(resource_url, "/premium-resource"):
        raise SandboxError("RESOURCE_MISMATCH")
    if len(required.accepts) != 1:
        raise SandboxError("UNSUPPORTED_PAYMENT_OPTIONS")
    option = required.accepts[0]
    if (option.scheme != SCHEME or option.network != NETWORK or option.asset != context.asset or
            option.pay_to != pubkey(pay_to) or option.max_timeout_seconds != 60 or
            option.extra != {"simulationOnly": True, "tokenProgram": context.token_program,
                             "decimals": context.decimals}):
        raise SandboxError("TERMS_MISMATCH")
    if int(amount(option.amount)) > int(amount(max_amount)):
        raise SandboxError("OVER_BUDGET")
    ext = required.extensions or {}
    box = ext.get("conatusSandbox")
    if not isinstance(box, dict) or set(box) != {
            "paymentId", "resourceId", "clientAgentAccount", "providerAgentAccount",
            "genesisHash", "programId", "expiresAt", "nonce", "facilitatorId",
            "serverSignature"}:
        raise SandboxError("INVALID_REQUIREMENTS")
    if (box["resourceId"] != resource_id or box["genesisHash"] != context.genesis_hash or
            box["programId"] != context.program_id or type(box["expiresAt"]) is not int or
            not now < box["expiresAt"] <= now + 60 or
            not re.fullmatch(r"[a-zA-Z0-9_-]{16,96}", box["paymentId"]) or
            not re.fullmatch(r"[a-zA-Z0-9_-]{16,96}", box["nonce"])):
        raise SandboxError("INVALID_REQUIREMENTS")
    pubkey(box["clientAgentAccount"]); pubkey(box["providerAgentAccount"])
    return option, box


def requirements_hash(required: PaymentRequired) -> str:
    data = required.model_dump(by_alias=True, exclude_none=True)
    data["extensions"]["conatusSandbox"].pop("serverSignature", None)
    return digest(data)


def strict_header(value: str | None) -> str:
    if not isinstance(value, str) or not 0 < len(value) <= MAX_HEADER or not re.fullmatch(r"[A-Za-z0-9+/=]+", value):
        raise SandboxError("INVALID_HEADER")
    return value

__all__ = ["Context", "SandboxError", "NETWORK", "SCHEME", "DOMAIN", "MAX_BODY",
           "canonical", "digest", "pubkey", "amount", "local_url", "checked_requirements",
           "requirements_hash", "strict_header", "PaymentPayload", "PaymentRequired",
           "PaymentRequirements", "ResourceInfo", "decode_payment_required_header",
           "decode_payment_response_header", "decode_payment_signature_header",
           "encode_payment_required_header", "encode_payment_response_header",
           "encode_payment_signature_header"]
