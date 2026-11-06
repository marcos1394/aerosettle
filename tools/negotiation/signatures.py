"""Ed25519 signatures over a domain-separated complete message."""
from __future__ import annotations

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from tools.discovery.agent_discovery import b58decode, b58encode, DiscoveryError
from .canonical import signed_bytes
from .models import NegotiationError


def sign(message: dict, private_key: Ed25519PrivateKey) -> dict:
    result = dict(message)
    result["signature"] = b58encode(private_key.sign(signed_bytes(result)))
    return result


def verify(message: dict, pubkey: str) -> None:
    try:
        Ed25519PublicKey.from_public_bytes(b58decode(pubkey, 32)).verify(
            b58decode(message["signature"], 64), signed_bytes(message))
    except (InvalidSignature, ValueError, DiscoveryError, KeyError, TypeError) as exc:
        raise NegotiationError("INVALID_SIGNATURE") from exc
