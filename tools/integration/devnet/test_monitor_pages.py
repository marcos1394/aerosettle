"""Deterministic alert and failure-channel tests for CON-59 operations."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch

from tools.integration.devnet import gateway as g, monitor_pages as m


NOW = datetime(2026, 11, 18, 12, tzinfo=timezone.utc)


def healthy(*, hours: int = 12) -> dict:
    return {"release": {"status": 200, "json": {
        "environment": "DEVNET_STAGING", "network": g.NETWORK,
        "genesis_hash": g.GENESIS, "program_id": g.PROGRAM,
        "token_mint": g.MINT, "idl_sha256": g.IDL_SHA256,
        "release_id": "approved-release", "snapshot_sha256": "digest",
        "snapshot_expires_at": (NOW + timedelta(hours=hours)).isoformat()}},
        "health": {"status": 200, "json": {"status": "ok"}},
        "ready": {"status": 200, "json": {"status": "ready",
                                "genesis": g.GENESIS, "program_id": g.PROGRAM,
                                "snapshot_sha256": "digest"}},
        "rpc": {"status": "VERIFIED", "genesis_hash": g.GENESIS,
                "slot": 123, "latency_ms": 120},
        "quota": {"status": "NOT_CONFIGURED"}}


def codes(value: dict) -> set[str]:
    return {alert["code"] for alert in m.assess(value, NOW)}


class PagesMonitorTest(unittest.TestCase):
    def test_healthy_public_snapshot(self):
        self.assertEqual(codes(healthy()), set())

    def test_expiring_expired_and_invalid_identity(self):
        self.assertIn("SNAPSHOT_EXPIRING", codes(healthy(hours=7)))
        self.assertIn("SNAPSHOT_EXPIRED", codes(healthy(hours=-1)))
        value = healthy()
        value["release"]["json"]["program_id"] = "other-program"
        self.assertIn("RELEASE_IDENTITY_MISMATCH", codes(value))
        value = healthy()
        value["ready"]["json"]["snapshot_sha256"] = "other-digest"
        self.assertIn("API_RELEASE_MISMATCH", codes(value))

    def test_api_503_html_quota_and_unavailable_json(self):
        value = healthy()
        value["ready"] = {"status": 503, "json": None, "cloudflare_1027": False}
        self.assertIn("API_503", codes(value))
        value["ready"]["cloudflare_1027"] = True
        self.assertIn("CLOUDFLARE_QUOTA_EXHAUSTED", codes(value))
        value["health"] = {"status": 0, "json": None}
        self.assertIn("API_HEALTH_FAILED", codes(value))

    def test_rpc_outage_rate_limit_latency_and_identity(self):
        value = healthy()
        value["rpc"] = {"status": "ERROR", "code": "RPC_UNAVAILABLE"}
        self.assertIn("RPC_DEGRADED", codes(value))
        value["rpc"]["code"] = "RPC_RATE_LIMITED"
        self.assertIn("RPC_DEGRADED", codes(value))
        value["rpc"] = {"status": "VERIFIED", "genesis_hash": g.GENESIS,
                        "slot": 123, "latency_ms": 2_001}
        self.assertIn("RPC_SLOW", codes(value))
        value["rpc"]["genesis_hash"] = "wrong"
        self.assertIn("RPC_IDENTITY_MISMATCH", codes(value))

    def test_account_wide_quota_threshold_and_missing_telemetry(self):
        value = healthy()
        value["quota"] = {"status": "OBSERVED", "requests_today": 79_999}
        self.assertEqual(codes(value), set())
        value["quota"]["requests_today"] = 80_000
        self.assertIn("CLOUDFLARE_QUOTA_NEAR_LIMIT", codes(value))
        value["quota"]["requests_today"] = 100_000
        self.assertIn("CLOUDFLARE_QUOTA_EXHAUSTED", codes(value))
        value["quota"] = {"status": "UNAVAILABLE"}
        self.assertIn("QUOTA_TELEMETRY_UNAVAILABLE", codes(value))

    def test_live_collection_is_read_only_and_never_requests_local_quota_by_default(self):
        value = healthy()
        with patch.object(m, "http_get", side_effect=[value["release"], value["health"], value["ready"]]) as web, \
                patch.object(m, "rpc_probe", return_value=value["rpc"]) as rpc, \
                patch.object(m, "cloudflare_usage") as quota:
            result = m.collect_live(now=NOW)
        self.assertEqual(result["status"], "HEALTHY")
        self.assertEqual([row.args[0] for row in web.call_args_list],
                         ["/release.json", "/api/health", "/api/ready"])
        rpc.assert_called_once()
        quota.assert_not_called()
        self.assertEqual(result["quota"]["status"], "NOT_CONFIGURED")

    def test_demo_emits_all_required_incident_classes(self):
        value = m.demo(NOW)
        self.assertTrue({"SNAPSHOT_EXPIRED", "API_503", "RPC_DEGRADED",
                         "CLOUDFLARE_QUOTA_EXHAUSTED"}.issubset(codes(value)))


if __name__ == "__main__":
    unittest.main()
