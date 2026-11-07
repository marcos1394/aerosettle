"""Adversarial x402 V2 sandbox tests: all financial paths remain offline."""
from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from x402.schemas import PaymentPayload, PaymentRequired, SettleResponse

from tools.economic_ledger.budget_policies import BudgetPolicyStore
from tools.economic_ledger.ledger import EconomicLedger
from tools.economic_ledger.spending_approvals import SpendingApprovalStore
from tools.economic_ledger.spending_decisions import SpendingDecisionStore
from tools.economic_ledger.test_budget_policies import AGENT, AGENT_RECORD, OTHER, OWNER, SECRET
from tools.economic_ledger.test_budget_policies import body as policy_body
from tools.economic_ledger.spending_approvals import CONTEXT_FIELDS, canonical_approval_message
from tools.discovery.agent_discovery import b58encode

from tools.x402.client import SandboxClient
from tools.x402.common import (Context, NETWORK, SCHEME, SandboxError, checked_requirements,
    decode_payment_required_header, decode_payment_signature_header, digest,
    encode_payment_signature_header, local_url)
from tools.x402.demo import PROVIDER_ACCOUNT, approval_provider, fixtures, run_demo, setup_policy
from tools.x402.facilitator import FacilitatorHTTP, SandboxFacilitator, verify_receipt
from tools.x402.transport import LocalHTTP, call
from tools.x402.policy import PaymentPolicyGate
from tools.x402.server import ResourceServer
from tools.x402.signer import SandboxSigner, public_key, sign
from tools.x402.store import SandboxStore


class X402Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.context = Context.fixture()
        self.registry = fixtures(self.context)
        self.ledger = EconomicLedger(self.root / "ledger.sqlite")
        self.policies = BudgetPolicyStore(self.ledger)
        setup_policy(self.policies, self.context)
        self.decisions = SpendingDecisionStore(self.ledger, self.policies)
        self.approvals = SpendingApprovalStore(self.ledger, self.policies, self.decisions)
        self.gate = PaymentPolicyGate(self.policies, self.decisions, self.approvals, self.registry.get)
        self.store = SandboxStore(self.root / "pay.sqlite")
        self.client_store = SandboxStore(self.root / "client.sqlite")
        self.server_key = Ed25519PrivateKey.generate()
        self.signer = SandboxSigner()
        self.facilitator = SandboxFacilitator(self.store, self.context, self.gate, self.registry.get,
            server_pubkey=public_key(self.server_key), sandbox_signer_pubkey=self.signer.public_key)
        self.fac_http_service = FacilitatorHTTP(self.facilitator)
        self.fac_http = LocalHTTP(self.fac_http_service).start()
        self.server = ResourceServer(self.store, self.context, client_agent_account=AGENT,
            provider_agent_account=PROVIDER_ACCOUNT, recipient=OTHER,
            facilitator_url=self.fac_http.base_url, facilitator_id=self.facilitator.facilitator_id,
            facilitator_pubkey=self.facilitator.public_key, key=self.server_key)
        self.resource_http = LocalHTTP(self.server).start()
        self.server.bind(self.resource_http.base_url)
        owner_key = Ed25519PrivateKey.from_private_bytes(SECRET)
        self.client = SandboxClient(self.context, self.client_store, self.gate, self.signer,
            resource_url=self.resource_http.base_url + "/premium-resource",
            facilitator_url=self.fac_http.base_url, resource_server_pubkey=self.server.public_key,
            facilitator_pubkey=self.facilitator.public_key, client_agent_account=AGENT,
            provider_agent_account=PROVIDER_ACCOUNT, pay_to=OTHER, max_amount="1000",
            owner_pubkey=OWNER,
            owner_authorize=lambda terms: sign(owner_key, b"OWNER-AUTHORIZATION\n", terms),
            approval_provider=lambda terms, decision_id: approval_provider(self.approvals, decision_id))

    def tearDown(self):
        self.resource_http.close(); self.fac_http.close()
        self.client_store.close(); self.store.close(); self.ledger.close(); self.tmp.cleanup()

    def raw_request(self):
        envelope = decode_payment_signature_header(self.client.last_header)
        return {"x402Version": 2,
                "paymentPayload": envelope.model_dump(by_alias=True, exclude_none=True),
                "paymentRequirements": envelope.accepted.model_dump(by_alias=True, exclude_none=True)}

    def test_official_sdk_v2_headers_and_persisted_single_settlement(self):
        first = self.client.pay()
        self.assertEqual(first, self.client.retry())
        self.assertIsNone(first["receipt"]["transaction_signature"])
        self.assertEqual(first["receipt"]["settlement_status"], "SIMULATED")
        self.assertEqual(self.store.conn.execute("SELECT COUNT(*) FROM sandbox_settlements").fetchone()[0], 1)
        self.assertEqual(self.store.conn.execute("SELECT COUNT(*) FROM sandbox_deliveries").fetchone()[0], 1)
        self.assertFalse(self.decisions.get(AGENT_RECORD,
            self.approvals.context(AGENT_RECORD, self.approvals.list(AGENT_RECORD)[0]["decision_id"])["decision_id"])["is_executable"])

    def test_v1_header_rejected(self):
        status, _, body = call(self.client.resource_url, headers={"X-PAYMENT": "legacy"})
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(body)["error"], "V1_HEADER_FORBIDDEN")

    def test_mainnet_and_wrong_network_fail(self):
        _, headers, _ = call(self.client.resource_url)
        required = decode_payment_required_header(headers["PAYMENT-REQUIRED"])
        for network in ("solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp", "solana:devnet"):
            forged = required.model_copy(deep=True)
            forged.accepts[0].network = network
            with self.assertRaises(SandboxError):
                checked_requirements(forged, self.context, resource_url=self.client.resource_url,
                    resource_id="premium-analysis-v1", pay_to=OTHER, max_amount="1000", now=int(time.time()))

    def test_mint_recipient_amount_decimals_and_scheme_rejected(self):
        _, headers, _ = call(self.client.resource_url)
        required = decode_payment_required_header(headers["PAYMENT-REQUIRED"])
        for field, bad in (("asset", OWNER), ("pay_to", OWNER), ("amount", "1001"),
                           ("scheme", "exact")):
            forged = required.model_copy(deep=True)
            setattr(forged.accepts[0], field, bad)
            with self.assertRaises(SandboxError):
                checked_requirements(forged, self.context, resource_url=self.client.resource_url,
                    resource_id="premium-analysis-v1", pay_to=OTHER, max_amount="1000", now=int(time.time()))
        forged = required.model_copy(deep=True)
        forged.accepts[0].extra["decimals"] = 9
        with self.assertRaises(SandboxError):
            checked_requirements(forged, self.context, resource_url=self.client.resource_url,
                resource_id="premium-analysis-v1", pay_to=OTHER, max_amount="1000", now=int(time.time()))

    def test_facilitator_without_real_support_rejected(self):
        self.facilitator.supported = lambda: __import__("x402.schemas", fromlist=["SupportedResponse"]).SupportedResponse(kinds=[])
        with self.assertRaisesRegex(SandboxError, "UNSUPPORTED_FACILITATOR"):
            self.client.pay()

    def test_facilitator_false_exact_claim_rejected(self):
        original = self.facilitator.supported
        def false_support():
            response = original()
            response.kinds[0].scheme = "exact"
            return response
        self.facilitator.supported = false_support
        with self.assertRaisesRegex(SandboxError, "UNSUPPORTED_FACILITATOR"):
            self.client.pay()

    def test_missing_human_approval_blocks(self):
        self.client.approval_provider = None
        with self.assertRaisesRegex(SandboxError, "HUMAN_APPROVAL_REQUIRED"):
            self.client.pay()
        self.assertEqual(self.store.conn.execute("SELECT COUNT(*) FROM sandbox_settlements").fetchone()[0], 0)

    def test_economic_deny_blocks(self):
        self.server.price = "1500"
        self.client.max_amount = "2000"
        with self.assertRaisesRegex(SandboxError, "POLICY_DENIED"):
            self.client.pay()

    def test_overprice_blocks_before_policy(self):
        self.server.price = "2000"
        with self.assertRaisesRegex(SandboxError, "OVER_BUDGET"):
            self.client.pay()

    def test_invalid_owner_signature_blocks(self):
        self.client.owner_authorize = lambda terms: "not-a-signature"
        with self.assertRaisesRegex(SandboxError, "INVALID_SIGNATURE"):
            self.client.pay()

    def test_wrong_signer_and_mutated_payload_fail_verify(self):
        self.client.pay()
        original = self.raw_request()
        for field, bad in (("sandboxSignature", "bad"), ("settlementIntent", "WORKORDER_ESCROW"),
                           ("payer", OTHER), ("nonce", "reused-nonce")):
            forged = copy.deepcopy(original)
            forged["paymentPayload"]["payload"][field] = bad
            self.assertFalse(self.facilitator.verify(forged).is_valid)

    def test_network_resource_mint_amount_recipient_replay_fail_verify(self):
        self.client.pay()
        original = self.raw_request()
        for key, bad in (("network", "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp"),
                         ("asset", OWNER), ("amount", "101"), ("payTo", OWNER)):
            forged = copy.deepcopy(original)
            forged["paymentRequirements"][key] = bad
            forged["paymentPayload"]["accepted"][key] = bad
            self.assertFalse(self.facilitator.verify(forged).is_valid)
        forged = copy.deepcopy(original)
        forged["paymentPayload"]["resource"]["url"] = "http://127.0.0.1:8000/other"
        self.assertFalse(self.facilitator.verify(forged).is_valid)

    def test_expired_signature_rejected(self):
        self.client.pay()
        raw = self.raw_request()
        self.assertFalse(self.facilitator.verify(raw, now=self.client.last_terms["expiresAt"]).is_valid)
        self.assertFalse(self.facilitator.settle(raw, now=self.client.last_terms["expiresAt"]).success)

    def test_duplicate_payment_and_nonce_conflict(self):
        self.client.pay()
        raw = self.raw_request()
        before = self.store.conn.execute("SELECT COUNT(*) FROM sandbox_settlements").fetchone()[0]
        self.assertTrue(self.facilitator.settle(raw).success)
        self.assertEqual(self.store.conn.execute("SELECT COUNT(*) FROM sandbox_settlements").fetchone()[0], before)
        prior = self.store.settlement(self.client.last_terms["paymentId"])
        forged = {key: prior[key] for key in prior if key != "record_hash"}
        forged["payment_id"] = "other-payment-id"
        with self.assertRaisesRegex(SandboxError, "REPLAY_CONFLICT"):
            self.store.settle(forged)

    def test_idempotency_across_clock_seconds(self):
        self.client.pay()
        raw = self.raw_request()
        at = int(time.time()) + 2
        self.assertTrue(self.facilitator.settle(raw, now=at).success)
        self.assertEqual(self.store.conn.execute("SELECT COUNT(*) FROM sandbox_settlements").fetchone()[0], 1)

    def test_concurrent_retry_single_settlement(self):
        self.client.pay()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.client.retry(), range(2)))
        self.assertEqual(results[0], results[1])
        self.assertEqual(self.store.conn.execute("SELECT COUNT(*) FROM sandbox_settlements").fetchone()[0], 1)

    def test_receipt_mutation_and_wrong_facilitator_rejected(self):
        result = self.client.pay()
        receipt = result["receipt"]
        changed = {**receipt, "amount_base_units_str": "101"}
        with self.assertRaises(SandboxError):
            verify_receipt(changed, self.facilitator.public_key, self.client.last_terms,
                           receipt["payment_payload_hash"])
        with self.assertRaises(SandboxError):
            verify_receipt(receipt, OWNER, self.client.last_terms, receipt["payment_payload_hash"])

    def test_missing_payment_response_rejected(self):
        self.client.pay()
        original = self.server.dispatch
        def omit(method, path, headers, body):
            status, hdr, response = original(method, path, headers, body)
            if status == 200:
                hdr.pop("PAYMENT-RESPONSE", None)
            return status, hdr, response
        self.server.dispatch = omit
        with self.assertRaisesRegex(SandboxError, "RESOURCE_NOT_AUTHORIZED"):
            self.client.retry()

    def test_repeated_402_rejected(self):
        self.client.pay()
        self.server.dispatch = lambda method, path, headers, body: self.server._challenge(int(time.time()))
        with self.assertRaisesRegex(SandboxError, "RESOURCE_NOT_AUTHORIZED"):
            self.client.retry()

    def test_facilitator_failure_and_429_rejected(self):
        self.client.pay()
        self.facilitator.settle = lambda raw: SettleResponse(success=False,
            error_reason="FAILED", transaction="", network=NETWORK)
        with self.assertRaisesRegex(SandboxError, "RESOURCE_NOT_AUTHORIZED"):
            self.client.retry()
        self.fac_http_service.dispatch = lambda method, path, headers, body: (429, {}, {"error": "RATE_LIMIT"})
        with self.assertRaisesRegex(SandboxError, "RESOURCE_NOT_AUTHORIZED"):
            self.client.retry()

    def test_facilitator_timeout_fails_closed(self):
        self.client.pay()
        with patch("tools.x402.server.call", side_effect=SandboxError("FACILITATOR_UNAVAILABLE", 503)):
            with self.assertRaisesRegex(SandboxError, "RESOURCE_NOT_AUTHORIZED"):
                self.client.retry()

    def test_lost_settlement_response_recovers_without_second_charge(self):
        from tools.x402.transport import call as real_call
        dropped = False
        def lose_once(url, **kwargs):
            nonlocal dropped
            result = real_call(url, **kwargs)
            if url.endswith("/settle") and not dropped:
                dropped = True
                raise SandboxError("FACILITATOR_UNAVAILABLE", 503)
            return result
        with patch("tools.x402.server.call", side_effect=lose_once):
            with self.assertRaisesRegex(SandboxError, "RESOURCE_NOT_AUTHORIZED"):
                self.client.pay()
        self.assertTrue(dropped)
        recovered = self.client.retry()
        self.assertEqual(recovered["receipt"]["settlement_status"], "SIMULATED")
        self.assertEqual(self.store.conn.execute("SELECT COUNT(*) FROM sandbox_settlements").fetchone()[0], 1)

    def test_policy_identity_change_fails_closed(self):
        self.client.pay()
        self.registry[AGENT] = {**self.registry[AGENT], "owner": OTHER}
        self.assertFalse(self.facilitator.verify(self.raw_request()).is_valid)

    def test_policy_pause_fails_closed(self):
        self.client.pay()
        self.policies.mutate(AGENT_RECORD, "PAUSE", policy_body("PAUSE", 2, "00000003"), OWNER)
        self.assertFalse(self.facilitator.verify(self.raw_request()).is_valid)

    def test_revoked_con29_approval_fails_closed(self):
        self.client.pay()
        raw = self.raw_request()
        aid = raw["paymentPayload"]["payload"]["approvalId"]
        context = self.approvals.context(AGENT_RECORD,
            raw["paymentPayload"]["payload"]["decisionId"])
        now = int(time.time())
        body = {**{key: context[key] for key in CONTEXT_FIELDS},
                "action": "REVOKE", "issued_at": now,
                "expires_at": self.approvals.get(AGENT_RECORD, aid)["expires_at"],
                "nonce": "x402-revoke-nonce-unique", "idempotency_key": "x402-revoke-idem-unique",
                "reason": "Owner withdrew sandbox review"}
        path = f"/v1/agents/{AGENT}/spending-approvals/{aid}/revoke"
        message = canonical_approval_message(now, AGENT, OWNER, "POST", path, body)
        signature = b58encode(Ed25519PrivateKey.from_private_bytes(SECRET).sign(message))
        self.approvals.mutate(AGENT_RECORD, "REVOKE", body, OWNER, signature,
                              hashlib.sha256(message).hexdigest(), now=now)
        self.assertFalse(self.facilitator.verify(raw).is_valid)

    def test_no_dns_no_redirect_no_mainnet_fallback(self):
        for url in ("http://localhost:8888/premium-resource", "http://127.0.0.2:8888/premium-resource",
                    "https://127.0.0.1:8888/premium-resource", "http://user@127.0.0.1:8888/premium-resource",
                    "http://127.0.0.1:8888/premium-resource?next=http://evil"):
            with self.assertRaises(SandboxError): local_url(url)

    def test_sqlite_restart_and_demo_evidence(self):
        report = run_demo()
        self.assertTrue(report["SQLITE_RESTART_VERIFIED"])
        self.assertTrue(report["FINANCIAL_TABLES_UNCHANGED"])
        self.assertEqual(report["ONCHAIN_TRANSACTIONS_SENT"], 0)
        self.assertFalse(report["DEVNET_SETTLEMENT_VERIFIED"])


if __name__ == "__main__":
    unittest.main()
