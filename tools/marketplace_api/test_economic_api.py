"""Integration and HTTP API tests for the Economic Ledger endpoints (CON-22)."""
import json
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import agent_discovery as discovery
import server
from tools.economic_ledger import ed25519
from tools.economic_ledger.auth import create_auth_headers
from tools.economic_ledger.ledger import EconomicLedger, IsolatedTestReconcilerVerifier
from tools.economic_ledger.models import MovementNature, MovementStatus, ProvenanceSource

DRONE = "DcusvnYAdFFKzNDVzUkUvmgZ9fDhzszeRR5Fj8F5dMbB"
SENSOR = "FPbX4tQ2t9KSUDPix3NxBVEp2dD5LWoikhBVYYafU9H7"

# Deterministic test Ed25519 keypairs
OWNER_DRONE_SECRET = b"\x01" * 32
OWNER_DRONE_PUBKEY_BYTES = ed25519.public_key_from_secret(OWNER_DRONE_SECRET)
OWNER_DRONE = discovery.b58encode(OWNER_DRONE_PUBKEY_BYTES)

OWNER_OTHER_SECRET = b"\x02" * 32
OWNER_OTHER_PUBKEY_BYTES = ed25519.public_key_from_secret(OWNER_OTHER_SECRET)
OWNER_OTHER = discovery.b58encode(OWNER_OTHER_PUBKEY_BYTES)

MINT_USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
CONFIG = "3qnN5ZjRL516znKdWHeEvSGLWL6sf4EoCPcG8e28je62"


class MockEconomicProvider:
    def __init__(self):
        self.ledger = EconomicLedger(":memory:", reconciliation_verifier=IsolatedTestReconcilerVerifier())
        self.data = {
            "program_id": server.PROGRAM_ID,
            "protocol_config": CONFIG,
            "protocol_paused": False,
            "commitment": "confirmed",
            "now_unix": 1000,
            "rpc_context_slots": {"config": 4, "AgentAccount": 5, "clock": 7},
            "agents": [
                {
                    "agent_account": DRONE,
                    "agent_id": "11" * 32,
                    "owner": OWNER_DRONE,
                    "protocol_config": CONFIG,
                    "capabilities": 37,
                    "active": True,
                    "status": "Active",
                },
                {
                    "agent_account": SENSOR,
                    "agent_id": "22" * 32,
                    "owner": OWNER_OTHER,
                    "protocol_config": CONFIG,
                    "capabilities": 4,
                    "active": True,
                    "status": "Active",
                },
            ],
            "work_orders": [],
        }

    def health(self):
        return server.GENESIS

    def snapshot(self):
        return self.data


class EconomicApiTests(unittest.TestCase):
    def setUp(self):
        self.provider = MockEconomicProvider()
        self.httpd = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            server.handler_for(self.provider),
        )
        self.thread = threading.Thread(
            target=self.httpd.serve_forever,
            daemon=True,
        )
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.httpd.server_port}"

    def tearDown(self):
        self.httpd.shutdown()
        self.provider.ledger.close()

    def request(
        self,
        path: str,
        method: str = "GET",
        body: dict | None = None,
        headers: dict | None = None,
    ) -> tuple[int, dict]:
        req_headers = {"Content-Type": "application/json"}
        if headers:
            req_headers.update(headers)

        data = json.dumps(body).encode("utf-8") if body else None
        req = urllib.request.Request(
            f"{self.url}{path}",
            data=data,
            headers=req_headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=3) as resp:
                status = resp.status
                content = json.loads(resp.read().decode("utf-8"))
                return status, content
        except urllib.error.HTTPError as err:
            err_content = json.loads(err.read().decode("utf-8"))
            return err.code, err_content

    # ─────────────────────────────────────────────────────────────────────────
    # 1. API Security: Cryptographic Ed25519 Authentication & Backdoor Removal
    # ─────────────────────────────────────────────────────────────────────────

    def test_unauthorized_access_fails_closed(self):
        # 1. Request without authentication headers -> 401 UNAUTHORIZED
        status, res = self.request(f"/v1/agents/{DRONE}/economic-movements")
        self.assertEqual(status, 401)
        self.assertEqual(res["error"]["code"], "UNAUTHORIZED")

        # 2. Legacy self-asserted X-Owner-Pubkey header without signature -> 401 UNAUTHORIZED
        status, res = self.request(
            f"/v1/agents/{DRONE}/economic-movements",
            headers={"X-Owner-Pubkey": OWNER_DRONE},
        )
        self.assertEqual(status, 401)
        self.assertEqual(res["error"]["code"], "UNAUTHORIZED")

        # 3. Eliminated admin backdoor header X-Protocol-Admin -> 401 UNAUTHORIZED
        status, res = self.request(
            f"/v1/agents/{DRONE}/economic-movements",
            headers={"X-Protocol-Admin": "conatus-admin-key"},
        )
        self.assertEqual(status, 401)
        self.assertEqual(res["error"]["code"], "UNAUTHORIZED")

        # 4. Forged / invalid signature -> 401 INVALID_SIGNATURE
        bad_headers = {
            "X-Signer-Pubkey": OWNER_DRONE,
            "X-Timestamp": str(int(time.time())),
            "X-Signature": discovery.b58encode(b"\x00" * 64),
        }
        status, res = self.request(
            f"/v1/agents/{DRONE}/economic-movements",
            headers=bad_headers,
        )
        self.assertEqual(status, 401)
        self.assertEqual(res["error"]["code"], "INVALID_SIGNATURE")

        # 5. Expired timestamp (> 300s window) -> 401 EXPIRED_CREDENTIALS
        expired_ts = int(time.time()) - 400
        expired_headers = create_auth_headers(OWNER_DRONE_SECRET, DRONE, timestamp=expired_ts)
        status, res = self.request(
            f"/v1/agents/{DRONE}/economic-movements",
            headers=expired_headers,
        )
        self.assertEqual(status, 401)
        self.assertEqual(res["error"]["code"], "EXPIRED_CREDENTIALS")

        # 6. Valid signature from non-owner -> 403 FORBIDDEN
        other_headers = create_auth_headers(OWNER_OTHER_SECRET, DRONE)
        status, res = self.request(
            f"/v1/agents/{DRONE}/economic-movements",
            headers=other_headers,
        )
        self.assertEqual(status, 403)
        self.assertEqual(res["error"]["code"], "FORBIDDEN")

        # 7. Authentic Ed25519 signature from genuine registered owner -> 200 OK
        valid_headers = create_auth_headers(OWNER_DRONE_SECRET, DRONE)
        status, res = self.request(
            f"/v1/agents/{DRONE}/economic-movements",
            headers=valid_headers,
        )
        self.assertEqual(status, 200)
        self.assertIn("data", res)

    # ─────────────────────────────────────────────────────────────────────────
    # 2. Disabled HTTP Write Endpoints (Method Not Allowed)
    # ─────────────────────────────────────────────────────────────────────────

    def test_write_endpoints_disabled_method_not_allowed(self):
        # External HTTP POST to record movement is disabled (405 METHOD_NOT_ALLOWED)
        status, res = self.request(
            "/v1/economic-movements",
            method="POST",
            body={
                "idempotency_key": "write-attempt-1",
                "agent_account": DRONE,
                "amount_base_units": 1_000_000,
            },
        )
        self.assertEqual(status, 405)
        self.assertEqual(res["error"]["code"], "METHOD_NOT_ALLOWED")

        # External HTTP POST to revert movement is disabled (405 METHOD_NOT_ALLOWED)
        status, res = self.request(
            "/v1/economic-movements/dummy-id/revert",
            method="POST",
            body={"reason": "test"},
        )
        self.assertEqual(status, 405)
        self.assertEqual(res["error"]["code"], "METHOD_NOT_ALLOWED")

    # ─────────────────────────────────────────────────────────────────────────
    # 3. Balances and Filtered Movement Lists via Trusted Ingestion
    # ─────────────────────────────────────────────────────────────────────────

    def test_balances_and_filtered_movements(self):
        # Ingest movements via trusted internal ledger service
        m1 = self.provider.ledger.record_movement(
            idempotency_key="mov-inc-1",
            agent_id="11" * 32,
            agent_account=DRONE,
            owner_pubkey=OWNER_DRONE,
            network="solana:localnet",
            genesis_hash=server.GENESIS,
            program_id=server.PROGRAM_ID,
            token_mint=MINT_USDC,
            amount_base_units=10_000_000,
            nature=MovementNature.INCOME,
            tx_signature="sig-inc-111111111111111111111111",
        )
        self.provider.ledger.reconcile_movement(
            m1.movement_id,
            evidence_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            authorized_by="conatus:protocol:reconciler:v1",
            slot=100,
            tx_signature="sig-inc-111111111111111111111111",
        )

        m2 = self.provider.ledger.record_movement(
            idempotency_key="mov-exp-1",
            agent_id="11" * 32,
            agent_account=DRONE,
            owner_pubkey=OWNER_DRONE,
            network="solana:localnet",
            genesis_hash=server.GENESIS,
            program_id=server.PROGRAM_ID,
            token_mint=MINT_USDC,
            amount_base_units=3_000_000,
            nature=MovementNature.EXPENSE,
            tx_signature="sig-exp-111111111111111111111111",
        )
        self.provider.ledger.reconcile_movement(
            m2.movement_id,
            evidence_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            authorized_by="conatus:protocol:reconciler:v1",
            slot=101,
            tx_signature="sig-exp-111111111111111111111111",
        )

        self.provider.ledger.record_movement(
            idempotency_key="mov-prov-1",
            agent_id="11" * 32,
            agent_account=DRONE,
            owner_pubkey=OWNER_DRONE,
            network="solana:localnet",
            genesis_hash=server.GENESIS,
            program_id=server.PROGRAM_ID,
            token_mint=MINT_USDC,
            amount_base_units=1_500_000,
            nature=MovementNature.INCOME,
            tx_signature="sig-prov-1111111111111111111111",
        )

        # Check balances with cryptographic authentication:
        # Reconciled = 10M - 3M = 7M; Provisional = 1.5M; Total = 8.5M
        auth_headers = create_auth_headers(OWNER_DRONE_SECRET, DRONE)
        status, bal_res = self.request(
            f"/v1/agents/{DRONE}/balances?mint={MINT_USDC}",
            headers=auth_headers,
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(bal_res["data"]), 1)
        b = bal_res["data"][0]
        self.assertEqual(b["reconciled_balance"], 7_000_000)
        self.assertEqual(b["provisional_balance"], 1_500_000)
        self.assertEqual(b["total_effective_balance"], 8_500_000)

        # Filter movements by nature=EXPENSE
        status, exp_list = self.request(
            f"/v1/agents/{DRONE}/economic-movements?nature=EXPENSE",
            headers=auth_headers,
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(exp_list["data"]), 1)
        self.assertEqual(exp_list["data"][0]["nature"], "EXPENSE")

        # Filter movements by status=PROVISIONAL
        status, prov_list = self.request(
            f"/v1/agents/{DRONE}/economic-movements?status=PROVISIONAL",
            headers=auth_headers,
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(prov_list["data"]), 1)
        self.assertEqual(prov_list["data"][0]["nature"], "INCOME")

    def test_costs_reserves_and_economic_summary_api(self):
        # 0. Fund DRONE with reconciled income so it has available treasury balance
        m_fund = self.provider.ledger.record_movement(
            idempotency_key="fund-drone-api-costs",
            agent_id="11" * 32,
            agent_account=DRONE,
            owner_pubkey=OWNER_DRONE,
            network="solana:localnet",
            genesis_hash=server.GENESIS,
            program_id=server.PROGRAM_ID,
            token_mint=MINT_USDC,
            amount_base_units=10_000_000,
            nature=MovementNature.INCOME,
            tx_signature="sig-fund-api-111111111111111111",
        )
        self.provider.ledger.reconcile_movement(
            m_fund.movement_id,
            evidence_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            authorized_by="conatus:protocol:reconciler:v1",
            slot=100,
            tx_signature="sig-fund-api-111111111111111111",
        )

        # 1. Allocate a capital reserve for DRONE
        res = self.provider.ledger.create_or_allocate_reserve(
            idempotency_key="res-api-001",
            agent_id="11" * 32,
            agent_account=DRONE,
            owner_pubkey=OWNER_DRONE,
            reserve_type="MAINTENANCE",
            network="solana:localnet",
            token_mint=MINT_USDC,
            amount_base_units=2_000_000,
            description="API test reserve",
        )

        # 2. Record a realized operational cost
        cost_real = self.provider.ledger.record_cost(
            idempotency_key="cost-api-001",
            agent_id="11" * 32,
            agent_account=DRONE,
            owner_pubkey=OWNER_DRONE,
            category="ENERGY_FUEL",
            cost_nature="REALIZED",
            economic_period="2026-10",
            network="solana:localnet",
            token_mint=MINT_USDC,
            amount_base_units=500_000,
            description="Solar recharge API test",
        )

        # 3. Record a budget estimation
        cost_est = self.provider.ledger.record_cost(
            idempotency_key="cost-api-002",
            agent_id="11" * 32,
            agent_account=DRONE,
            owner_pubkey=OWNER_DRONE,
            category="MAINTENANCE",
            cost_nature="ESTIMATED",
            economic_period="2026-11",
            network="solana:localnet",
            token_mint=MINT_USDC,
            amount_base_units=1_000_000,
            description="Projected overhaul",
        )

        auth_headers = create_auth_headers(OWNER_DRONE_SECRET, DRONE)

        # 4. Query /v1/agents/{account}/costs
        status, costs_resp = self.request(
            f"/v1/agents/{DRONE}/costs",
            headers=auth_headers,
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(costs_resp["data"]), 2)
        self.assertIn("page", costs_resp)

        # Query filtered by category
        status, cat_resp = self.request(
            f"/v1/agents/{DRONE}/costs?category=ENERGY_FUEL",
            headers=auth_headers,
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(cat_resp["data"]), 1)
        self.assertEqual(cat_resp["data"][0]["cost_id"], cost_real.cost_id)

        # 5. Query /v1/agents/{account}/reserves
        status, res_resp = self.request(
            f"/v1/agents/{DRONE}/reserves",
            headers=auth_headers,
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(res_resp["data"]), 1)
        self.assertEqual(res_resp["data"][0]["reserve_id"], res.reserve_id)
        self.assertEqual(res_resp["data"][0]["current_reserved_base_units"], 2_000_000)

        # 6. Query /v1/agents/{account}/economic-summary
        status, sum_resp = self.request(
            f"/v1/agents/{DRONE}/economic-summary?mint={MINT_USDC}",
            headers=auth_headers,
        )
        self.assertEqual(status, 200)
        self.assertGreaterEqual(len(sum_resp["data"]), 1)
        s = sum_resp["data"][0]
        self.assertEqual(s["total_expenses_realized"], 500_000)
        self.assertEqual(s["total_estimated_costs"], 1_000_000)
        self.assertEqual(s["total_capital_reserved"], 2_000_000)

        # 7. Query /v1/costs/{cost_id}
        status, cost_detail = self.request(
            f"/v1/costs/{cost_real.cost_id}",
            headers=auth_headers,
        )
        self.assertEqual(status, 200)
        self.assertEqual(cost_detail["data"]["cost_id"], cost_real.cost_id)

        # 8. Query /v1/reserves/{reserve_id}
        status, res_detail = self.request(
            f"/v1/reserves/{res.reserve_id}",
            headers=auth_headers,
        )
        self.assertEqual(status, 200)
        self.assertEqual(res_detail["data"]["reserve_id"], res.reserve_id)

        # 9. Test unauthorized access
        unauth_status, _ = self.request(f"/v1/agents/{DRONE}/costs")
        self.assertEqual(unauth_status, 401)

        wrong_headers = create_auth_headers(OWNER_OTHER_SECRET, DRONE)
        forbid_status, _ = self.request(
            f"/v1/agents/{DRONE}/costs",
            headers=wrong_headers,
        )
        self.assertEqual(forbid_status, 403)

        # 10. Write endpoint disabled
        post_status, _ = self.request(
            f"/v1/costs",
            method="POST",
            body={"category": "ENERGY_FUEL"},
            headers=auth_headers,
        )
        self.assertEqual(post_status, 405)


if __name__ == "__main__":
    unittest.main()
