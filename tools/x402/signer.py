"""Isolated, ephemeral sandbox signer; cannot construct a Solana transaction."""
from __future__ import annotations

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives import serialization

from tools.discovery.agent_discovery import b58encode, b58decode
from .common import DOMAIN, SandboxError, canonical, digest, pubkey


def public_key(key: Ed25519PrivateKey) -> str:
    return b58encode(key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw))


def sign(key: Ed25519PrivateKey, purpose: bytes, value: dict) -> str:
    return b58encode(key.sign(DOMAIN + purpose + canonical(value)))


def verify(signer: str, purpose: bytes, value: dict, signature: str) -> None:
    try:
        Ed25519PublicKey.from_public_bytes(b58decode(pubkey(signer), 32)).verify(
            b58decode(signature, 64), DOMAIN + purpose + canonical(value))
    except Exception as exc:
        raise SandboxError("INVALID_SIGNATURE", 401) from exc


def authorization_terms(box: dict, option: dict, resource_url: str, requirement_hash: str) -> dict:
    return {"paymentId": box["paymentId"], "clientAgentAccount": box["clientAgentAccount"],
            "providerAgentAccount": box["providerAgentAccount"], "resourceId": box["resourceId"],
            "resourceUrl": resource_url, "network": option["network"],
            "genesisHash": box["genesisHash"], "programId": box["programId"],
            "asset": option["asset"], "amount": option["amount"], "payTo": option["payTo"],
            "scheme": option["scheme"], "requirementsHash": requirement_hash,
            "expiresAt": box["expiresAt"], "nonce": box["nonce"],
            "facilitatorId": box["facilitatorId"]}


class SandboxSigner:
    """Only accepts a separately signed owner consent for exact immutable terms."""

    def __init__(self, key: Ed25519PrivateKey | None = None):
        self._key = key or Ed25519PrivateKey.generate()
        self.public_key = public_key(self._key)

    def sign_payload(self, terms: dict, owner_pubkey: str, owner_signature: str,
                     gate: dict, now: int) -> dict:
        verify(owner_pubkey, b"OWNER-AUTHORIZATION\n", terms, owner_signature)
        if now >= terms["expiresAt"] or gate.get("status") not in {
                "ELIGIBLE_FOR_SEPARATE_PAYMENT_AUTHORIZATION", "SANDBOX_HUMAN_APPROVED"}:
            raise SandboxError("AUTHORIZATION_REQUIRED", 403)
        body = {"authorizationType": "SANDBOX_AUTHORIZATION", "paymentId": terms["paymentId"],
                "payer": owner_pubkey, "sandboxSigner": self.public_key,
                "ownerSignature": owner_signature, "terms": terms,
                "termsHash": digest(terms), "nonce": terms["nonce"],
                "expiresAt": terms["expiresAt"], "settlementIntent": "SIMULATE_ONLY",
                "decisionId": gate["decision_id"], "approvalId": gate.get("approval_id")}
        return {**body, "sandboxSignature": sign(self._key, b"SIGNED-SANDBOX-PAYLOAD\n", body)}


def verify_payload(payload: dict, *, owner_pubkey: str, signer_pubkey: str,
                   terms: dict, now: int) -> None:
    if (not isinstance(payload, dict) or set(payload) != {
            "authorizationType", "paymentId", "payer", "sandboxSigner", "ownerSignature",
            "terms", "termsHash", "nonce", "expiresAt", "settlementIntent", "sandboxSignature",
            "decisionId", "approvalId"} or
            payload["authorizationType"] != "SANDBOX_AUTHORIZATION" or
            payload["settlementIntent"] != "SIMULATE_ONLY" or
            payload["paymentId"] != terms["paymentId"] or payload["payer"] != owner_pubkey or
            payload["sandboxSigner"] != signer_pubkey or payload["terms"] != terms or
            payload["termsHash"] != digest(terms) or payload["nonce"] != terms["nonce"] or
            payload["expiresAt"] != terms["expiresAt"] or now >= terms["expiresAt"]):
        raise SandboxError("PAYLOAD_MISMATCH", 403)
    verify(owner_pubkey, b"OWNER-AUTHORIZATION\n", terms, payload["ownerSignature"])
    verify(signer_pubkey, b"SIGNED-SANDBOX-PAYLOAD\n",
           {k: v for k, v in payload.items() if k != "sandboxSignature"}, payload["sandboxSignature"])
