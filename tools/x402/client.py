"""Pinned, bounded x402 V2 client with separate economic and human gates."""
from __future__ import annotations

import json
import time
from x402.schemas import PaymentPayload, SupportedResponse

from .common import (Context, NETWORK, SCHEME, SandboxError, checked_requirements,
                     decode_payment_required_header, decode_payment_response_header,
                     encode_payment_signature_header, local_url, requirements_hash, strict_header,
                     digest)
from .facilitator import verify_receipt
from .transport import call
from .signer import authorization_terms, verify
from .store import SandboxStore


class SandboxClient:
    def __init__(self, context: Context, store: SandboxStore, policy_gate, sandbox_signer,
                 *, resource_url: str, facilitator_url: str, resource_server_pubkey: str,
                 facilitator_pubkey: str, client_agent_account: str,
                 provider_agent_account: str, pay_to: str, max_amount: str,
                 owner_pubkey: str, owner_authorize, approval_provider=None):
        self.context, self.store, self.policy_gate, self.sandbox_signer = (
            context, store, policy_gate, sandbox_signer)
        self.resource_url = local_url(resource_url, "/premium-resource")
        self.facilitator_url = local_url(facilitator_url + "/", "/")[:-1]
        self.resource_server_pubkey = resource_server_pubkey
        self.facilitator_pubkey = facilitator_pubkey
        self.client_agent_account, self.provider_agent_account = client_agent_account, provider_agent_account
        self.pay_to, self.max_amount = pay_to, max_amount
        self.owner_pubkey, self.owner_authorize = owner_pubkey, owner_authorize
        self.approval_provider = approval_provider
        self.last_header = None
        self.last_terms = None

    def _supported(self):
        status, _, body = call(self.facilitator_url + "/supported")
        if status != 200:
            raise SandboxError("FACILITATOR_UNAVAILABLE", 503)
        response = SupportedResponse.model_validate_json(body)
        if (len(response.kinds) != 1 or response.kinds[0].x402_version != 2 or
                response.kinds[0].scheme != SCHEME or response.kinds[0].network != NETWORK or
                response.kinds[0].extra != {"simulationOnly": True} or response.extensions or
                response.signers != {NETWORK: [self.facilitator_pubkey]}):
            raise SandboxError("UNSUPPORTED_FACILITATOR", 403)

    def pay(self) -> dict:
        status, headers, _ = call(self.resource_url)
        if status != 402 or "X-PAYMENT" in headers or "X-PAYMENT-RESPONSE" in headers:
            raise SandboxError("EXPECTED_V2_402", 403)
        required = decode_payment_required_header(strict_header(headers.get("PAYMENT-REQUIRED")))
        now = int(time.time())
        option, box = checked_requirements(required, self.context,
            resource_url=self.resource_url, resource_id="premium-analysis-v1",
            pay_to=self.pay_to, max_amount=self.max_amount, now=now)
        unsigned = required.model_dump(by_alias=True, exclude_none=True)
        signature = unsigned["extensions"]["conatusSandbox"].pop("serverSignature")
        verify(self.resource_server_pubkey, b"PAYMENT-REQUIRED\n", unsigned, signature)
        if box["clientAgentAccount"] != self.client_agent_account or box["providerAgentAccount"] != self.provider_agent_account:
            raise SandboxError("AGENT_IDENTITY_MISMATCH", 403)
        self._supported()
        terms = authorization_terms(box, option.model_dump(by_alias=True), self.resource_url,
                                    requirements_hash(required))
        gate = self.policy_gate.evaluate(terms, now)
        if gate["status"] == "BLOCK":
            raise SandboxError("POLICY_DENIED", 403)
        if gate["status"] == "AWAITING_HUMAN_APPROVAL":
            if self.approval_provider is None:
                raise SandboxError("HUMAN_APPROVAL_REQUIRED", 403)
            approval_id = self.approval_provider(terms, gate["decision_id"])
            gate = self.policy_gate.validate(terms, gate["decision_id"], approval_id, now)
        else:
            gate = self.policy_gate.validate(terms, gate["decision_id"], None, now)
        owner_signature = self.owner_authorize(terms)
        payload = self.sandbox_signer.sign_payload(terms, self.owner_pubkey, owner_signature, gate, now)
        envelope = PaymentPayload(x402_version=2, accepted=option, resource=required.resource,
                                  payload=payload, extensions={"conatusSandbox": {
                                      "paymentRequired": required.model_dump(by_alias=True, exclude_none=True)}})
        self.last_header = encode_payment_signature_header(envelope)
        self.last_terms = terms
        return self.retry()

    def retry(self) -> dict:
        if self.last_header is None or self.last_terms is None:
            raise SandboxError("PAYMENT_MISSING")
        status, headers, body = call(self.resource_url, headers={"PAYMENT-SIGNATURE": self.last_header})
        if status != 200 or "PAYMENT-RESPONSE" not in headers:
            raise SandboxError("RESOURCE_NOT_AUTHORIZED", 403)
        settlement = decode_payment_response_header(strict_header(headers["PAYMENT-RESPONSE"]))
        receipt = ((settlement.extensions or {}).get("conatusSandbox") or {}).get("receipt")
        if (not settlement.success or settlement.transaction != "" or settlement.network != NETWORK or
                settlement.amount != self.last_terms["amount"] or not isinstance(receipt, dict)):
            raise SandboxError("INVALID_SETTLEMENT_RESPONSE", 403)
        decoded = json.loads(body)
        if not isinstance(decoded, dict) or len(body) > 32768:
            raise SandboxError("INVALID_RESOURCE", 403)
        # Derive the signed payload hash from the retained header, never from a server assertion.
        from .common import decode_payment_signature_header
        envelope = decode_payment_signature_header(self.last_header)
        payload_hash = digest(envelope.model_dump(by_alias=True, exclude_none=True))
        verify_receipt(receipt, self.facilitator_pubkey, self.last_terms, payload_hash)
        if receipt["payer"] != self.owner_pubkey:
            raise SandboxError("PAYER_MISMATCH", 403)
        self.store.save_client_receipt(receipt)
        return {"resource": decoded, "receipt": receipt}
