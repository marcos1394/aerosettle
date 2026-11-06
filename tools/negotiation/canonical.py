"""Bounded canonical JSON and protocol-domain message signatures."""
from __future__ import annotations

import hashlib
import rfc8785

DOMAIN = b"CONATUS-AGENT-NEGOTIATION-v1\n"


def canonical(value: object) -> bytes:
    return rfc8785.dumps(value)


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def signed_bytes(message: dict) -> bytes:
    return DOMAIN + canonical({k: v for k, v in message.items() if k != "signature"})
