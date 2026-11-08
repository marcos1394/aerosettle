"""Resource server with signed 402 challenges and idempotent sandbox delivery."""
from __future__ import annotations

import json
import secrets
import time
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from x402.schemas import PaymentPayload, PaymentRequired, PaymentRequirements, ResourceInfo, SettleResponse

from .common import (Context, NETWORK, SCHEME, SandboxError, checked_requirements,
                     decode_payment_signature_header, digest, encode_payment_required_header,
                     encode_payment_response_header, local_url, requirements_hash, strict_header)
from .facilitator import verify_receipt
from .transport import call
from .signer import authorization_terms, public_key, sign, verify
from .store import SandboxStore


class ResourceServer:
    paths = {"/premium-resource": {"GET"}}

    def __init__(self, store: SandboxStore, context: Context, *, client_agent_account: str,
                 provider_agent_account: str, recipient: str, facilitator_url: str,
                 facilitator_id: str, facilitator_pubkey: str,
                 price: str = "100", key: Ed25519PrivateKey | None = None):
        self.store, self.context = store, context
        self.client_agent_account, self.provider_agent_account = client_agent_account, provider_agent_account
        self.recipient, self.price = recipient, price
        self.facilitator_url = local_url(facilitator_url, "/") if facilitator_url.endswith("/") else local_url(facilitator_url + "/", "/")[:-1]
        self.facilitator_id, self.facilitator_pubkey = facilitator_id, facilitator_pubkey
        self.key = key or Ed25519PrivateKey.generate()
        self.public_key = public_key(self.key)
        self.base_url = None
        self.resource = {"analysis": "sandbox-only", "confidence": "fixture"}
        self.resource_hash = digest(self.resource)

    def bind(self, base_url: str):
        self.base_url = local_url(base_url + "/", "/")[:-1]

    def _challenge(self, now: int) -> tuple[int, dict, dict]:
        if self.base_url is None:
            raise SandboxError("SERVER_NOT_BOUND", 503)
        box = {"paymentId": secrets.token_urlsafe(24), "resourceId": "premium-analysis-v1",
               "clientAgentAccount": self.client_agent_account,
               "providerAgentAccount": self.provider_agent_account,
               "genesisHash": self.context.genesis_hash, "programId": self.context.program_id,
               "expiresAt": now + 60, "nonce": secrets.token_urlsafe(24),
               "facilitatorId": self.facilitator_id}
        required = PaymentRequired(x402_version=2, error="PAYMENT-SIGNATURE required",
            resource=ResourceInfo(url=self.base_url + "/premium-resource",
                description="Offline premium analysis fixture", mime_type="application/json"),
            accepts=[PaymentRequirements(scheme=SCHEME, network=NETWORK, asset=self.context.asset,
                amount=self.price, pay_to=self.recipient, max_timeout_seconds=60,
                extra={"simulationOnly": True, "tokenProgram": self.context.token_program,
                       "decimals": self.context.decimals})],
            extensions={"conatusSandbox": box})
        unsigned = required.model_dump(by_alias=True, exclude_none=True)
        required.extensions["conatusSandbox"]["serverSignature"] = sign(
            self.key, b"PAYMENT-REQUIRED\n", unsigned)
        return (402, {"PAYMENT-REQUIRED": encode_payment_required_header(required)},
                {"error": "PAYMENT_REQUIRED", "simulationOnly": True})

    def dispatch(self, method: str, path: str, headers: dict, body: dict | None):
        now = int(time.time())
        h = {key.lower(): value for key, value in headers.items()}
        if "x-payment" in h or "x-payment-response" in h:
            raise SandboxError("V1_HEADER_FORBIDDEN")
        if "payment-signature" not in h:
            return self._challenge(now)
        payload = decode_payment_signature_header(strict_header(h["payment-signature"]))
        if type(payload) is not PaymentPayload or payload.x402_version != 2 or payload.resource is None:
            raise SandboxError("UNSUPPORTED_VERSION")
        ext = (payload.extensions or {}).get("conatusSandbox")
        if not isinstance(ext, dict) or set(ext) != {"paymentRequired"}:
            raise SandboxError("INVALID_PAYLOAD")
        required = PaymentRequired.model_validate(ext["paymentRequired"])
        box = (required.extensions or {}).get("conatusSandbox")
        unsigned = required.model_dump(by_alias=True, exclude_none=True)
        signature = unsigned["extensions"]["conatusSandbox"].pop("serverSignature", None)
        verify(self.public_key, b"PAYMENT-REQUIRED\n", unsigned, signature)
        option, box = checked_requirements(required, self.context,
            resource_url=self.base_url + path, resource_id="premium-analysis-v1",
            pay_to=self.recipient, max_amount=self.price, now=now)
        if option != payload.accepted or required.resource != payload.resource or box["clientAgentAccount"] != self.client_agent_account or box["providerAgentAccount"] != self.provider_agent_account or box["facilitatorId"] != self.facilitator_id:
            raise SandboxError("REQUIREMENTS_MISMATCH")
        terms = authorization_terms(box, option.model_dump(by_alias=True), required.resource.url,
                                    requirements_hash(required))
        request = {"x402Version": 2, "paymentPayload": payload.model_dump(by_alias=True, exclude_none=True),
                   "paymentRequirements": option.model_dump(by_alias=True, exclude_none=True)}
        status, _, content = call(self.facilitator_url + "/verify", method="POST", body=request)
        if status != 200 or json.loads(content).get("isValid") is not True:
            raise SandboxError("VERIFICATION_FAILED", 403)
        status, _, content = call(self.facilitator_url + "/settle", method="POST", body=request)
        if status != 200:
            raise SandboxError("SETTLEMENT_UNAVAILABLE", 503)
        settlement = SettleResponse.model_validate_json(content)
        receipt = ((settlement.extensions or {}).get("conatusSandbox") or {}).get("receipt")
        if (not settlement.success or settlement.transaction != "" or settlement.network != NETWORK or
                settlement.amount != option.amount or not isinstance(receipt, dict)):
            raise SandboxError("SETTLEMENT_FAILED", 403)
        payload_hash = digest(payload.model_dump(by_alias=True, exclude_none=True))
        verify_receipt(receipt, self.facilitator_pubkey, terms, payload_hash)
        if receipt["payer"] != payload.payload.get("payer"):
            raise SandboxError("PAYER_MISMATCH", 403)
        self.store.deliver(box["paymentId"], terms["requirementsHash"], box["resourceId"], self.resource_hash)
        return 200, {"PAYMENT-RESPONSE": encode_payment_response_header(settlement)}, self.resource
