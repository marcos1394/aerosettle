"""EPIC 3.3.3 contract tests, entirely offline."""

import copy
import unittest
from urllib.parse import quote

import server
from test_server import Provider, example


class PaginationApiTests(unittest.TestCase):

    def setUp(self):
        self.provider = Provider(copy.deepcopy(example()))

    def get(self, url):
        status, body = server.route(url, self.provider)
        self.assertEqual(status, 200)
        return body

    def fails(self, url, expected_status, expected_code):
        with self.assertRaises(server.ApiError) as caught:
            server.route(url, self.provider)

        self.assertEqual(
            caught.exception.status,
            expected_status,
        )

        self.assertEqual(
            caught.exception.code,
            expected_code,
        )

    def test_two_agent_pages(self):
        first = self.get("/v1/agents?limit=1")

        self.assertEqual(first["count"], 1)
        self.assertEqual(first["total_count"], 2)
        self.assertTrue(first["page"]["has_more"])

        cursor = first["page"]["next_cursor"]

        self.assertIsInstance(cursor, str)

        second = self.get(
            "/v1/agents?limit=1&cursor="
            + quote(cursor)
        )

        self.assertEqual(second["count"], 1)
        self.assertFalse(second["page"]["has_more"])
        self.assertIsNone(second["page"]["next_cursor"])

        addresses = {
            first["data"][0]["agent_account"],
            second["data"][0]["agent_account"],
        }

        self.assertEqual(len(addresses), 2)

    def test_deterministic_order(self):
        result = self.get("/v1/agents")

        accounts = [
            agent["agent_account"]
            for agent in result["data"]
        ]

        self.assertEqual(accounts, sorted(accounts))

    def test_capability_filter(self):
        result = self.get(
            "/v1/agents?capabilities_all=33"
        )

        self.assertEqual(result["total_count"], 1)

        self.assertEqual(
            result["data"][0]["capabilities"],
            "37",
        )

    def test_active_filter(self):
        self.provider.data["agents"][0]["active"] = False

        result = self.get(
            "/v1/agents?active=false"
        )

        self.assertEqual(result["total_count"], 1)

    def test_order_capability_filter(self):
        result = self.get(
            "/v1/work-orders?"
            "required_capabilities_all=33&limit=1"
        )

        self.assertEqual(result["count"], 1)
        self.assertEqual(result["total_count"], 2)
        self.assertTrue(result["page"]["has_more"])

    def test_order_cursor(self):
        first = self.get(
            "/v1/work-orders?limit=1"
        )

        cursor = first["page"]["next_cursor"]

        second = self.get(
            "/v1/work-orders?limit=1&cursor="
            + quote(cursor)
        )

        self.assertEqual(second["count"], 1)
        self.assertFalse(second["page"]["has_more"])

    def test_changed_data_invalidates_cursor(self):
        first = self.get(
            "/v1/agents?limit=1"
        )

        cursor = first["page"]["next_cursor"]

        self.provider.data["agents"][0][
            "capabilities"
        ] = 63

        self.fails(
            "/v1/agents?limit=1&cursor="
            + quote(cursor),
            409,
            "STALE_CURSOR",
        )

    def test_cursor_reused_with_other_filter(self):
        first = self.get(
            "/v1/agents?limit=1"
        )

        cursor = first["page"]["next_cursor"]

        self.fails(
            "/v1/agents?limit=1&status=Active&cursor="
            + quote(cursor),
            400,
            "CURSOR_SCOPE_MISMATCH",
        )

    def test_modified_cursor_is_rejected(self):
        first = self.get(
            "/v1/agents?limit=1"
        )

        cursor = first["page"]["next_cursor"]

        modified = (
            ("A" if cursor[0] != "A" else "B")
            + cursor[1:]
        )

        self.fails(
            "/v1/agents?limit=1&cursor="
            + quote(modified),
            400,
            "INVALID_CURSOR",
        )

    def test_invalid_limits(self):
        for limit in ("0", "101", "-1", "1.5", "001"):
            with self.subTest(limit=limit):
                self.fails(
                    "/v1/agents?limit=" + limit,
                    400,
                    "INVALID_LIMIT",
                )

    def test_invalid_masks(self):
        for mask in (
            "-1",
            "18446744073709551616",
            "1.5",
        ):
            with self.subTest(mask=mask):
                self.fails(
                    "/v1/agents?capabilities_all="
                    + mask,
                    400,
                    "INVALID_CAPABILITIES",
                )

    def test_duplicate_account_fails_closed(self):
        self.provider.data["agents"].append(
            copy.deepcopy(
                self.provider.data["agents"][0]
            )
        )

        self.fails(
            "/v1/agents",
            502,
            "INVALID_COLLECTION",
        )

    def test_openapi_contract(self):
        spec = self.get("/openapi.json")

        self.assertEqual(
            spec["openapi"], "3.1.1"
        )

        for path in (
            "/health",
            "/v1/agents",
            "/v1/work-orders",
            "/v1/work-orders/{work_order_id}/matches",
            "/v1/marketplace",
        ):
            self.assertIn(path, spec["paths"])
            self.assertIn("get", spec["paths"][path])

        self.assertIn(
            "409",
            spec["paths"]["/v1/agents"]
            ["get"]["responses"],
        )

        components = spec["components"]

        def check_refs(value):
            if isinstance(value, dict):
                if "$ref" in value:
                    reference = value["$ref"]

                    self.assertTrue(
                        reference.startswith("#/components/")
                    )

                    _, _, section, name = (
                        reference.split("/")
                    )

                    self.assertIn(
                        name, components[section]
                    )

                for child in value.values():
                    check_refs(child)

            elif isinstance(value, list):
                for child in value:
                    check_refs(child)

        check_refs(spec)

    def test_marketplace_large_snapshot_rejected(self):
        agent = copy.deepcopy(
            self.provider.data["agents"][0]
        )

        for index in range(201):
            extra = copy.deepcopy(agent)
            extra["agent_account"] = f"test-{index}"
            self.provider.data["agents"].append(extra)

        self.fails(
            "/v1/marketplace",
            413,
            "RESULT_TOO_LARGE",
        )


if __name__ == "__main__":
    unittest.main()
