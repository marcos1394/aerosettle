"""Integration and HTTP API tests for the Economic Ledger endpoints (CON-22)."""
import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import server
from tools.economic_ledger.ledger import EconomicLedger
from tools.economic_ledger.models import MovementNature, MovementStatus

DRONE = "DcusvnYAdFFKzNDVzUkUvmgZ9fDhzszeRR5Fj8F5dMbB"
SENSOR = "FPbX4tQ2t9KSUDPix3NxBVEp2dD5LWoikhBVYYafU9H7"
OWNER_DRONE = "8rPDpYsLZxNBm8Q8GKSKki8Ag6dodkasedhUT9x3Ec1D"
OWNER_OTHER = "9aA2jeb1Cds7m4VMhYRpGCv9UJzdREZBZAVEYmBxAzeZ"
MINT_USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
CONFIG = "3qnN5ZjRL516znKdWHeEvSGLWL6sf4EoCPcG8e28je62"


class MockEconomicProvider:
    def __init__(self):
        self.ledger = EconomicLedger(":memory:")
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

    def request(self, path: str, method: str = "GET", body: dict | None = None, headers: dict | None = None) -> tuple[int, dict]:
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
    # Security: Authentication & Authorization Tests
    # ─────────────────────────────────────────────────────────────────────────

    def test_unauthorized_access_fails_closed(self):
        # 1. Access without any auth header -> 401 UNAUTHORIZED
        status, res = self.request(f"/v1/agents/{DRONE}/economic-movements")
        self.assertEqual(status, 401)
        self.assertEqual(res["error"]["code"], "UNAUTHORIZED")

        # 2. Access with wrong owner header -> 403 FORBIDDEN
        status, res = self.request(
            f"/v1/agents/{DRONE}/economic-movements",
            headers={"X-Owner-Pubkey": OWNER_OTHER},
        )
        self.assertEqual(status, 403)
        self.assertEqual(res["error"]["code"], "FORBIDDEN")

        # 3. Access with correct owner header -> 200 OK
        status, res = self.request(
            f"/v1/agents/{DRONE}/economic-movements",
            headers={"X-Owner-Pubkey": OWNER_DRONE},
        )
        self.assertEqual(status, 200)
        self.assertIn("data", res)

    # ─────────────────────────────────────────────────────────────────────────
    # Movement Ingestion & Idempotency over HTTP
    # ─────────────────────────────────────────────────────────────────────────

    def test_post_movement_and_idempotency_over_http(self):
        payload = {
            "idempotency_key": "http-idemp-001",
            "agent_account": DRONE,
            "owner_pubkey": OWNER_DRONE,
            "token_mint": MINT_USDC,
            "amount_base_units": 5_000_000,
            "nature": "INCOME",
            "status": "RECONCILED",
            "provenance_source": "ONCHAIN_VERIFIED",
        }

        # 1. First POST: creates movement (201 Created)
        status, res = self.request(
            "/v1/economic-movements",
            method="POST",
            body=payload,
            headers={"X-Owner-Pubkey": OWNER_DRONE},
        )
        self.assertEqual(status, 201)
        mov_id = res["data"]["movement_id"]
        self.assertEqual(res["data"]["amount_base_units"], 5_000_000)

        # 2. Second POST with identical idempotency_key: returns existing movement idempotently
        status2, res2 = self.request(
            "/v1/economic-movements",
            method="POST",
            body=payload,
            headers={"X-Owner-Pubkey": OWNER_DRONE},
        )
        self.assertEqual(status2, 201)
        self.assertEqual(res2["data"]["movement_id"], mov_id)

        # 3. Retrieve movement directly by ID
        status_get, res_get = self.request(
            f"/v1/economic-movements/{mov_id}",
            headers={"X-Owner-Pubkey": OWNER_DRONE},
        )
        self.assertEqual(status_get, 200)
        self.assertEqual(res_get["data"]["movement_id"], mov_id)

    # ─────────────────────────────────────────────────────────────────────────
    # Balances and Filtered Movement Lists
    # ─────────────────────────────────────────────────────────────────────────

    def test_balances_and_filtered_movements(self):
        # Ingest income
        self.request(
            "/v1/economic-movements",
            method="POST",
            body={
                "idempotency_key": "mov-inc-1",
                "agent_account": DRONE,
                "token_mint": MINT_USDC,
                "amount_base_units": 10_000_000,
                "nature": "INCOME",
                "status": "RECONCILED",
            },
            headers={"X-Owner-Pubkey": OWNER_DRONE},
        )

        # Ingest expense
        self.request(
            "/v1/economic-movements",
            method="POST",
            body={
                "idempotency_key": "mov-exp-1",
                "agent_account": DRONE,
                "token_mint": MINT_USDC,
                "amount_base_units": 3_000_000,
                "nature": "EXPENSE",
                "status": "RECONCILED",
            },
            headers={"X-Owner-Pubkey": OWNER_DRONE},
        )

        # Ingest provisional income
        self.request(
            "/v1/economic-movements",
            method="POST",
            body={
                "idempotency_key": "mov-prov-1",
                "agent_account": DRONE,
                "token_mint": MINT_USDC,
                "amount_base_units": 1_500_000,
                "nature": "INCOME",
                "status": "PROVISIONAL",
            },
            headers={"X-Owner-Pubkey": OWNER_DRONE},
        )

        # Check balances: Reconciled = 10M - 3M = 7M; Provisional = 1.5M; Total = 8.5M
        status, bal_res = self.request(
            f"/v1/agents/{DRONE}/balances?mint={MINT_USDC}",
            headers={"X-Owner-Pubkey": OWNER_DRONE},
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
            headers={"X-Owner-Pubkey": OWNER_DRONE},
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(exp_list["data"]), 1)
        self.assertEqual(exp_list["data"][0]["nature"], "EXPENSE")

        # Filter movements by status=PROVISIONAL
        status, prov_list = self.request(
            f"/v1/agents/{DRONE}/economic-movements?status=PROVISIONAL",
            headers={"X-Owner-Pubkey": OWNER_DRONE},
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(prov_list["data"]), 1)
        self.assertEqual(prov_list["data"][0]["nature"], "INCOME")

    # ─────────────────────────────────────────────────────────────────────────
    # Movement Reversals over HTTP
    # ─────────────────────────────────────────────────────────────────────────

    def test_revert_movement_over_http(self):
        # Create an expense
        _, create_res = self.request(
            "/v1/economic-movements",
            method="POST",
            body={
                "idempotency_key": "rev-test-expense",
                "agent_account": DRONE,
                "token_mint": MINT_USDC,
                "amount_base_units": 800_000,
                "nature": "EXPENSE",
                "status": "RECONCILED",
            },
            headers={"X-Owner-Pubkey": OWNER_DRONE},
        )
        mov_id = create_res["data"]["movement_id"]

        # Call revert endpoint
        status, rev_res = self.request(
            f"/v1/economic-movements/{mov_id}/revert",
            method="POST",
            body={"reason": "Hardware telemetry falsely reported extra cycle"},
            headers={"X-Owner-Pubkey": OWNER_DRONE},
        )
        self.assertEqual(status, 200)
        self.assertEqual(rev_res["data"]["reverted"]["status"], "REVERTED")
        self.assertEqual(rev_res["data"]["compensating"]["nature"], "ADJUSTMENT")
        self.assertEqual(rev_res["data"]["compensating"]["reversal_of_movement_id"], mov_id)


if __name__ == "__main__":
    unittest.main()
