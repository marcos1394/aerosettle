"""Cryptographic authentication and ownership authorization for Economic Ledger access."""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "discovery"))

import agent_discovery as discovery
from . import ed25519

MAX_TIMESTAMP_DRIFT_SECONDS = 300  # 5 minutes freshness window


class AuthError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code


def canonical_challenge(timestamp: int, agent_account: str) -> bytes:
    """Build canonical challenge message for cryptographic authentication."""
    return f"conatus:economic-auth:v1:{timestamp}:{agent_account}".encode("utf-8")


def create_auth_headers(
    secret_key: bytes,
    agent_account: str,
    timestamp: Optional[int] = None,
) -> dict[str, str]:
    """Helper to generate authentic Ed25519 authentication headers for testing/clients."""
    ts = int(time.time()) if timestamp is None else timestamp
    pubkey_bytes = ed25519.public_key_from_secret(secret_key)
    pubkey_b58 = discovery.b58encode(pubkey_bytes)
    msg = canonical_challenge(ts, agent_account)
    sig_bytes = ed25519.sign(msg, secret_key, pubkey_bytes)
    sig_b58 = discovery.b58encode(sig_bytes)

    return {
        "X-Signer-Pubkey": pubkey_b58,
        "X-Timestamp": str(ts),
        "X-Signature": sig_b58,
    }


def verify_request_auth(
    headers: dict[str, Any] | None,
    agent: dict[str, Any],
    agent_account: str,
    current_time: Optional[int] = None,
) -> str:
    """Authenticates request using real Ed25519 cryptographic signatures and checks ownership.

    Returns the verified signer pubkey or raises AuthError.
    """
    if headers is None:
        headers = {}

    hdrs = {str(k).lower(): str(v) for k, v in headers.items()}
    signer_b58 = hdrs.get("x-signer-pubkey")
    timestamp_str = hdrs.get("x-timestamp")
    signature_b58 = hdrs.get("x-signature")

    if not signer_b58 or not timestamp_str or not signature_b58:
        raise AuthError(
            401,
            "UNAUTHORIZED",
            "Missing required cryptographic authentication headers (X-Signer-Pubkey, X-Timestamp, X-Signature)",
        )

    # 1. Parse and validate timestamp
    try:
        ts = int(timestamp_str)
    except ValueError as exc:
        raise AuthError(401, "INVALID_TIMESTAMP", "X-Timestamp must be an integer unix timestamp") from exc

    now = int(time.time()) if current_time is None else current_time
    if abs(now - ts) > MAX_TIMESTAMP_DRIFT_SECONDS:
        raise AuthError(
            401,
            "EXPIRED_CREDENTIALS",
            f"Authentication timestamp expired or drifted beyond {MAX_TIMESTAMP_DRIFT_SECONDS}s window",
        )

    # 2. Decode public key and signature
    try:
        pubkey_bytes = discovery.b58decode(signer_b58, 32)
    except Exception as exc:
        raise AuthError(401, "INVALID_PUBKEY", "Invalid Base58 public key in X-Signer-Pubkey") from exc

    try:
        sig_bytes = discovery.b58decode(signature_b58, 64)
    except Exception as exc:
        raise AuthError(401, "INVALID_SIGNATURE", "Invalid Base58 64-byte signature in X-Signature") from exc

    # 3. Cryptographically verify signature against canonical message
    challenge = canonical_challenge(ts, agent_account)
    if not ed25519.verify(sig_bytes, challenge, pubkey_bytes):
        raise AuthError(401, "INVALID_SIGNATURE", "Cryptographic Ed25519 signature verification failed")

    # 4. Check that the verified signer is authorized as the agent owner
    expected_owner = agent.get("owner")
    if expected_owner and signer_b58 != expected_owner:
        raise AuthError(
            403,
            "FORBIDDEN",
            f"Signer {signer_b58} is not the registered owner of agent {agent_account}",
        )

    return signer_b58
