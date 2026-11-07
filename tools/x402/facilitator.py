"""Offline V2 facilitator: verify is read-only, settle records simulation only."""
from __future__ import annotations

import json
import time
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from x402.schemas import (PaymentPayload, PaymentRequired, PaymentRequirements,
                          SettleRequest, SettleResponse, SupportedKind, SupportedResponse,
                          VerifyRequest, VerifyResponse)

from .common import (Context, NETWORK, SCHEME, SandboxError, checked_requirements,
                     digest, requirements_hash)
from .signer import (authorization_terms, public_key, sign, verify, verify_payload)
from .store import SandboxStore


class SandboxFacilitator:
    def __init__(self, store: SandboxStore, context: Context, policy_gate, agent_supplier,
                 *, server_pubkey: str, sandbox_signer_pubkey: str,
                 key: Ed25519PrivateKey | None = None, facilitator_id: str = "conatus-local-sandbox"):
        self.store, self.context, self.policy_gate = store, context, policy_gate
        self.agent_supplier = agent_supplier
        self.server_pubkey = server_pubkey
        self.sandbox_signer_pubkey = sandbox_signer_pubkey
        self.key = key or Ed25519PrivateKey.generate()
        self.public_key = public_key(self.key)
        self.facilitator_id = facilitator_id

    def supported(self) -> SupportedResponse:
        return SupportedResponse(kinds=[SupportedKind(x402_version=2, scheme=SCHEME, network=NETWORK,
            extra={"simulationOnly": True})], extensions=[], signers={NETWORK: [self.public_key]})

    def _validate(self, raw: dict, now: int) -> tuple[PaymentPayload, PaymentRequirements, PaymentRequired, dict, dict]:
        if raw.get("x402Version") != 2 or set(raw) != {"x402Version", "paymentPayload", "paymentRequirements"}:
            raise SandboxError("UNSUPPORTED_VERSION")
        request = VerifyRequest.model_validate(raw)
        payload, req = request.payment_payload, request.payment_requirements
        if payload.x402_version != 2 or payload.resource is None or payload.accepted != req:
            raise SandboxError("PAYLOAD_MISMATCH")
        extension = (payload.extensions or {}).get("conatusSandbox")
        if not isinstance(extension, dict) or set(extension) != {"paymentRequired"}:
            raise SandboxError("INVALID_PAYLOAD")
        required = PaymentRequired.model_validate(extension["paymentRequired"])
        box = (required.extensions or {}).get("conatusSandbox")
        if not isinstance(box, dict) or not isinstance(box.get("serverSignature"), str):
            raise SandboxError("INVALID_REQUIREMENTS")
        unsigned = required.model_dump(by_alias=True, exclude_none=True)
        unsigned["extensions"]["conatusSandbox"].pop("serverSignature")
        verify(self.server_pubkey, b"PAYMENT-REQUIRED\n", unsigned, box["serverSignature"])
        provider = self.agent_supplier(box.get("providerAgentAccount"))
        client = self.agent_supplier(box.get("clientAgentAccount"))
        if (not isinstance(provider, dict) or not isinstance(client, dict) or
                provider.get("owner") != req.pay_to or
                provider.get("agent_account") != box["providerAgentAccount"] or
                client.get("agent_account") != box["clientAgentAccount"] or
                provider.get("active") is not True or client.get("active") is not True or
                provider.get("status") != "Active" or client.get("status") != "Active" or
                (provider.get("network"), provider.get("genesis_hash"), provider.get("program_id")) !=
                ("solana:devnet", self.context.genesis_hash, self.context.program_id)):
            raise SandboxError("AGENT_IDENTITY_MISMATCH", 403)
        option, box = checked_requirements(required, self.context,
            resource_url=payload.resource.url, resource_id="premium-analysis-v1", pay_to=provider["owner"],
            max_amount=req.amount, now=now)
        if option != req or required.resource != payload.resource or box["facilitatorId"] != self.facilitator_id:
            raise SandboxError("REQUIREMENTS_MISMATCH")
        terms = authorization_terms(box, req.model_dump(by_alias=True), payload.resource.url,
                                    requirements_hash(required))
        verify_payload(payload.payload, owner_pubkey=client["owner"],
                       signer_pubkey=self.sandbox_signer_pubkey, terms=terms, now=now)
        self.policy_gate.validate(terms, payload.payload["decisionId"],
                                  payload.payload["approvalId"], now)
        return payload, req, required, box, terms

    def verify(self, raw: dict, now: int | None = None) -> VerifyResponse:
        at = int(time.time()) if now is None else now
        try:
            payload, _, _, _, _ = self._validate(raw, at)
            return VerifyResponse(is_valid=True, payer=payload.payload["payer"],
                                  extensions={"conatusSandbox": {"simulationOnly": True}})
        except Exception as exc:
            code = exc.code if isinstance(exc, SandboxError) else "INVALID_PAYMENT"
            return VerifyResponse(is_valid=False, invalid_reason=code)

    def settle(self, raw: dict, now: int | None = None) -> SettleResponse:
        at = int(time.time()) if now is None else now
        try:
            payload, req, _, box, terms = self._validate(raw, at)
            payload_hash = digest(payload.model_dump(by_alias=True, exclude_none=True))
            requirement_hash = terms["requirementsHash"]
            receipt = {"receipt_id": "xr_" + digest([box["paymentId"], payload_hash])[:32],
                       "payment_id": box["paymentId"], "resource_id": box["resourceId"],
                       "resource_url": terms["resourceUrl"],
                       "client_agent_account": box["clientAgentAccount"],
                       "provider_agent_account": box["providerAgentAccount"],
                       "payer": payload.payload["payer"], "recipient": req.pay_to,
                       "network": NETWORK, "genesis_hash": box["genesisHash"],
                       "program_id": box["programId"], "asset": req.asset,
                       "amount_base_units_str": req.amount, "facilitator_id": self.facilitator_id,
                       "verification_result": "VALID_SANDBOX_AUTHORIZATION",
                       "settlement_status": "SIMULATED", "evidence_source": "SANDBOX_SIMULATION",
                       "transaction_signature": None, "commitment": None,
                       "payment_requirements_hash": requirement_hash,
                       "payment_payload_hash": payload_hash,
                       "created_at": terms["expiresAt"] - 60}
            receipt["facilitator_signature"] = sign(self.key, b"SANDBOX-RECEIPT\n", receipt)
            record = {"payment_id": box["paymentId"], "nonce": box["nonce"],
                      "requirements_hash": requirement_hash, "payload_hash": payload_hash,
                      "client_agent_account": box["clientAgentAccount"],
                      "provider_agent_account": box["providerAgentAccount"],
                      "resource_id": box["resourceId"], "resource_url": terms["resourceUrl"],
                      "network": NETWORK, "genesis_hash": box["genesisHash"],
                      "program_id": box["programId"], "asset": req.asset, "amount": req.amount,
                      "pay_to": req.pay_to, "settlement_intent": "SIMULATE_ONLY",
                      "receipt_id": receipt["receipt_id"],
                      "receipt_json": json.dumps(receipt, sort_keys=True, separators=(",", ":"))}
            stored, _ = self.store.settle(record)
            authentic = json.loads(stored["receipt_json"])
            verify_receipt(authentic, self.public_key, terms, payload_hash)
            return SettleResponse(success=True, payer=authentic["payer"], transaction="",
                network=NETWORK, amount=req.amount,
                extensions={"conatusSandbox": {"simulationOnly": True, "receipt": authentic}})
        except Exception as exc:
            code = exc.code if isinstance(exc, SandboxError) else "SETTLEMENT_FAILED"
            return SettleResponse(success=False, error_reason=code, transaction="", network=NETWORK)


def verify_receipt(receipt: dict, facilitator_pubkey: str, terms: dict,
                   payload_hash: str) -> None:
    if (not isinstance(receipt, dict) or
            receipt.get("evidence_source") != "SANDBOX_SIMULATION" or
            receipt.get("settlement_status") != "SIMULATED" or
            receipt.get("transaction_signature") is not None or
            receipt.get("commitment") is not None or
            receipt.get("verification_result") != "VALID_SANDBOX_AUTHORIZATION" or
            receipt.get("payment_id") != terms["paymentId"] or
            receipt.get("resource_id") != terms["resourceId"] or
            receipt.get("resource_url") != terms["resourceUrl"] or
            receipt.get("client_agent_account") != terms["clientAgentAccount"] or
            receipt.get("provider_agent_account") != terms["providerAgentAccount"] or
            receipt.get("payer") is None or receipt.get("recipient") != terms["payTo"] or
            receipt.get("network") != terms["network"] or
            receipt.get("genesis_hash") != terms["genesisHash"] or
            receipt.get("program_id") != terms["programId"] or
            receipt.get("asset") != terms["asset"] or
            receipt.get("amount_base_units_str") != terms["amount"] or
            receipt.get("payment_requirements_hash") != terms["requirementsHash"] or
            receipt.get("payment_payload_hash") != payload_hash):
        raise SandboxError("INVALID_RECEIPT", 403)
    if (receipt.get("receipt_id") != "xr_" + digest([terms["paymentId"], payload_hash])[:32] or
            receipt.get("created_at") != terms["expiresAt"] - 60 or
            receipt.get("facilitator_id") != terms["facilitatorId"]):
        raise SandboxError("INVALID_RECEIPT", 403)
    signature = receipt.get("facilitator_signature")
    verify(facilitator_pubkey, b"SANDBOX-RECEIPT\n",
           {k: v for k, v in receipt.items() if k != "facilitator_signature"}, signature)


class FacilitatorHTTP:
    paths = {"/supported": {"GET"}, "/verify": {"POST"}, "/settle": {"POST"}}

    def __init__(self, facilitator: SandboxFacilitator):
        self.facilitator = facilitator

    def dispatch(self, method: str, path: str, headers: dict, body: dict | None):
        if path == "/supported":
            return 200, {}, self.facilitator.supported().model_dump(by_alias=True, exclude_none=True)
        if not isinstance(body, dict):
            raise SandboxError("INVALID_REQUEST")
        if path == "/verify":
            result = self.facilitator.verify(body)
        else:
            result = self.facilitator.settle(body)
        return 200, {}, result.model_dump(by_alias=True, exclude_none=True)
