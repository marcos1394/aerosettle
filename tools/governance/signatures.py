"""Distinct Ed25519 challenge for organizational governance mutations."""
from __future__ import annotations

import time

from tools.organizations.signatures import (OrganizationError, TOKEN, ORG_ID, digest,
                                            pubkey, _verify)

DOMAIN = "conatus:governance:v1"
FIELDS = {"organization_id", "proposal_id", "actor_pubkey", "action", "bylaws_version",
          "bylaws_hash", "electorate_snapshot_hash", "payload", "expected_version",
          "issued_at", "expires_at", "nonce", "idempotency_key"}


class GovernanceError(OrganizationError):
    pass


def mutation_message(method: str, path: str, body: dict) -> bytes:
    return (f"{DOMAIN}:1:{body['organization_id']}:{body['proposal_id']}:"
            f"{body['actor_pubkey']}:{body['action']}:{body['bylaws_version']}:"
            f"{body['bylaws_hash']}:{body['electorate_snapshot_hash']}:"
            f"{method}:{path}:{digest(body)}:{body['issued_at']}:{body['nonce']}:"
            f"{body['idempotency_key']}:{body['expected_version']}:{body['expires_at']}").encode()


def verify_mutation(path: str, body: dict, headers: dict | None, now: int | None = None) -> tuple[str, bytes, str]:
    if not isinstance(body, dict) or set(body) != FIELDS:
        raise GovernanceError(400, "INVALID_BODY", "Exact governance mutation fields required")
    if not isinstance(body["organization_id"], str) or not ORG_ID.fullmatch(body["organization_id"]):
        raise GovernanceError(400, "INVALID_ORGANIZATION_ID", "Invalid organization identifier")
    actor = pubkey(body["actor_pubkey"])
    values = ("proposal_id", "action", "bylaws_hash", "electorate_snapshot_hash")
    if (any(not isinstance(body[key], str) for key in values) or
            any(type(body[key]) is not int or body[key] < 0 for key in
                ("bylaws_version", "expected_version", "issued_at", "expires_at")) or
            not isinstance(body["payload"], dict) or
            any(not isinstance(body[key], str) or not TOKEN.fullmatch(body[key]) for key in
                ("nonce", "idempotency_key"))):
        raise GovernanceError(400, "INVALID_BODY", "Invalid governance mutation controls")
    expected_path = f"/v1/organizations/{body['organization_id']}/governance/actions"
    if path != expected_path:
        raise GovernanceError(400, "INVALID_PATH", "Governance signature route mismatch")
    at = int(time.time()) if now is None else now
    if abs(at-body["issued_at"]) > 300 or not body["issued_at"] <= at < body["expires_at"]:
        raise GovernanceError(401, "EXPIRED_CREDENTIALS", "Governance signature expired")
    hdr = {str(key).lower(): str(value) for key, value in (headers or {}).items()}
    if hdr.get("x-signer-pubkey") != actor or hdr.get("x-timestamp") != str(body["issued_at"]):
        raise GovernanceError(401, "INVALID_SIGNATURE", "Governance signer headers required")
    signature = hdr.get("x-signature", "")
    message = mutation_message("POST", path, body)
    try:
        _verify(actor, signature, message)
    except OrganizationError as exc:
        raise GovernanceError(exc.status, exc.code, str(exc)) from exc
    return actor, message, signature
