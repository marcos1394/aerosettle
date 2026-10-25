"""Distinct Ed25519 domains for organization reads and mutations."""
from __future__ import annotations

import hashlib
import json
import re
import time

from cryptography.hazmat.primitives.asymmetric import ed25519
from tools.discovery.agent_discovery import b58decode

DOMAIN = "conatus:organization-admin:v1"
READ_DOMAIN = "conatus:organization-read:v1"
ORG_ID = re.compile(r"org_[0-9a-f]{32}\Z")
TOKEN = re.compile(r"[A-Za-z0-9._:-]{8,128}\Z")


class OrganizationError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code = status, code


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def pubkey(value: object) -> str:
    try:
        if not isinstance(value, str) or len(b58decode(value, 32)) != 32:
            raise ValueError("key")
    except Exception as exc:
        raise OrganizationError(400, "INVALID_PUBKEY", "A valid Solana public key is required") from exc
    return value


def mutation_message(method: str, path: str, body: dict) -> bytes:
    return (f"{DOMAIN}:1:{body['organization_id']}:{body['actor_pubkey']}:"
            f"{body['target_type']}:{body['target_id']}:{body['action']}:"
            f"{body['role_id']}:{body['permission_scope']}:{method}:{path}:{digest(body)}:"
            f"{body['issued_at']}:{body['nonce']}:{body['idempotency_key']}:"
            f"{body['expected_version']}:{body['expires_at']}").encode("utf-8")


def read_message(path: str, actor: str, timestamp: int) -> bytes:
    return f"{READ_DOMAIN}:{timestamp}:{actor}:{path}".encode("utf-8")


def _verify(actor: str, signature: str, message: bytes) -> None:
    try:
        ed25519.Ed25519PublicKey.from_public_bytes(b58decode(pubkey(actor), 32)).verify(
            b58decode(signature, 64), message)
    except Exception as exc:
        raise OrganizationError(401, "INVALID_SIGNATURE", "Invalid organization Ed25519 signature") from exc


def verify_mutation(method: str, path: str, body: dict, headers: dict | None,
                    now: int | None = None) -> tuple[str, bytes]:
    fields = {"organization_id", "actor_pubkey", "target_type", "target_id", "action",
              "role_id", "permission_scope", "payload", "expected_version", "issued_at",
              "expires_at", "nonce", "idempotency_key"}
    if not isinstance(body, dict) or set(body) != fields:
        raise OrganizationError(400, "INVALID_BODY", "Exact organization mutation fields are required")
    if not isinstance(body["organization_id"], str) or not ORG_ID.fullmatch(body["organization_id"]):
        raise OrganizationError(400, "INVALID_ORGANIZATION_ID", "Invalid organization identifier")
    actor = pubkey(body["actor_pubkey"])
    if (type(body["expected_version"]) is not int or body["expected_version"] < 0 or
            type(body["issued_at"]) is not int or type(body["expires_at"]) is not int or
            not isinstance(body["payload"], dict) or
            any(not isinstance(body[key], str) for key in
                ("target_type", "target_id", "action", "role_id", "permission_scope")) or
            not all(isinstance(body[key], str) and TOKEN.fullmatch(body[key]) for key in
                    ("nonce", "idempotency_key"))):
        raise OrganizationError(400, "INVALID_BODY", "Invalid organization mutation controls")
    at = int(time.time()) if now is None else now
    if abs(at - body["issued_at"]) > 300 or not body["issued_at"] <= at < body["expires_at"]:
        raise OrganizationError(401, "EXPIRED_CREDENTIALS", "Organization mutation signature expired")
    if (method, path) not in (("POST", "/v1/organizations"),
                              ("POST", f"/v1/organizations/{body['organization_id']}/actions")):
        raise OrganizationError(400, "INVALID_PATH", "Organization mutation path mismatch")
    if (path == "/v1/organizations") != (body["action"] == "CREATE"):
        raise OrganizationError(400, "INVALID_ACTION", "Creation needs its own signed route")
    hdr = {str(key).lower(): str(value) for key, value in (headers or {}).items()}
    if hdr.get("x-signer-pubkey") != actor or hdr.get("x-timestamp") != str(body["issued_at"]):
        raise OrganizationError(401, "INVALID_SIGNATURE", "Actor signature headers are required")
    message = mutation_message(method, path, body)
    _verify(actor, hdr.get("x-signature", ""), message)
    return actor, message


def verify_read(path: str, headers: dict | None, now: int | None = None) -> str:
    hdr = {str(key).lower(): str(value) for key, value in (headers or {}).items()}
    actor = pubkey(hdr.get("x-signer-pubkey")) if hdr.get("x-signer-pubkey") else None
    if actor is None:
        raise OrganizationError(401, "UNAUTHORIZED", "Signed organization read is required")
    try:
        ts = int(hdr.get("x-timestamp", ""))
    except ValueError as exc:
        raise OrganizationError(401, "INVALID_TIMESTAMP", "Invalid read timestamp") from exc
    at = int(time.time()) if now is None else now
    if abs(at - ts) > 300:
        raise OrganizationError(401, "EXPIRED_CREDENTIALS", "Organization read challenge expired")
    _verify(actor, hdr.get("x-signature", ""), read_message(path, actor, ts))
    return actor
