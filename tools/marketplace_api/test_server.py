"""Offline Marketplace API contract tests."""

import json
import threading
import unittest
import urllib.error
import urllib.request

from copy import deepcopy
from http.server import ThreadingHTTPServer

import server

DRONE = (
    "DcusvnYAdFFKzNDVzUkUvmgZ9fDhzszeRR5Fj8F5dMbB"
)

SENSOR = (
    "FPbX4tQ2t9KSUDPix3NxBVEp2dD5LWoikhBVYYafU9H7"
)

SETTLED = (
    "DcD34tC5THj7WkV9fzCYcpRSgUdt6wwybUFcG1YvSviy"
)

OPEN = (
    "2MYb6oZ4dzHAqSziopNjCdoXA6uzz4VJNPovcMsaScxs"
)

OWNER = (
    "8rPDpYsLZxNBm8Q8GKSKki8Ag6dodkasedhUT9x3Ec1D"
)

CONFIG = (
    "3qnN5ZjRL516znKdWHeEvSGLWL6sf4EoCPcG8e28je62"
)


def example():
    return {
        "program_id": server.PROGRAM_ID,
        "protocol_config": CONFIG,
        "protocol_paused": False,
        "commitment": "confirmed",
        "now_unix": 1000,
        "rpc_context_slots": {
            "config": 4,
            "AgentAccount": 5,
            "WorkOrderAccount": 6,
            "clock": 7,
        },
        "agents": [
            {
                "agent_account": DRONE,
                "agent_id": "11" * 32,
                "protocol_config": CONFIG,
                "capabilities": 37,
                "active": True,
                "status": "Active",
            },
            {
                "agent_account": SENSOR,
                "agent_id": "22" * 32,
                "protocol_config": CONFIG,
                "capabilities": 4,
                "active": True,
                "status": "Active",
            },
        ],
        "work_orders": [
            {
                "work_order_account": OPEN,
                "work_order_id": "33" * 32,
                "creator": OWNER,
                "protocol_config": CONFIG,
                "required_capabilities": 33,
                "execution_deadline": 2000,
                "is_open": True,
                "status": "Open",
            },
            {
                "work_order_account": SETTLED,
                "work_order_id": "44" * 32,
                "creator": OWNER,
                "protocol_config": CONFIG,
                "required_capabilities": 33,
                "execution_deadline": 2000,
                "is_open": False,
                "status": "Settled",
            },
        ],
        "eligible_agents_by_order": {
            OPEN: [DRONE],
        },
    }


class Provider:
    def __init__(self, data=None):
        self.data = example() if data is None else data

    def match(self, order, snapshot):
        reasons = {
            agent["agent_account"]:
                server.rejection(order, agent, snapshot)
            for agent in snapshot["agents"]
        }
        return {
            "eligible_agent_accounts": sorted(
                account
                for account, reason in reasons.items()
                if reason is None
            ),
            "rejections_by_agent": reasons,
        }

    def health(self):
        return server.GENESIS

    def snapshot(self):
        return deepcopy(self.data)


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.provider = Provider()

    def get(self, url):
        status, body = server.route(url, self.provider)
        self.assertEqual(status, 200)
        return body

    def fails(self, url, code, status):
        with self.assertRaises(server.ApiError) as caught:
            server.route(url, self.provider)

        self.assertEqual(caught.exception.status, status)
        self.assertEqual(caught.exception.code, code)

    def test_health_and_genesis(self):
        self.assertEqual(
            self.get("/health")["genesis"],
            server.GENESIS,
        )

    def test_agents_and_string_u64(self):
        data = self.get("/v1/agents")

        self.assertEqual(data["count"], 2)
        self.assertEqual(
            data["data"][0]["capabilities"], "37"
        )

    def test_agent_status_filter(self):
        self.assertEqual(
            self.get("/v1/agents?status=Active")["count"],
            2,
        )

        self.assertEqual(
            self.get("/v1/agents?status=Revoked")["count"],
            0,
        )

    def test_known_agent(self):
        self.assertEqual(
            self.get("/v1/agents/" + DRONE)["data"][
                "agent_account"
            ],
            DRONE,
        )

    def test_orders_filter_and_status(self):
        self.assertEqual(
            self.get(
                "/v1/work-orders?status=Settled"
            )["count"],
            1,
        )

        self.assertEqual(
            self.get(
                "/v1/work-orders?discoverable=true"
            )["count"],
            1,
        )

        self.assertEqual(
            self.get(
                "/v1/work-orders?discoverable=false"
            )["count"],
            1,
        )

    def test_decision_and_rejection_mask(self):
        value = self.get(
            "/v1/work-orders/" + OPEN + "/matches"
        )["data"]

        self.assertEqual(
            [
                a["agent_account"]
                for a in value["eligible_agents"]
            ],
            [DRONE],
        )

        self.assertEqual(
            value["evaluations"][1]["rejection"],
            {
                "code": "MISSING_CAPABILITIES",
                "missing_mask": "33",
            },
        )

        self.assertEqual(
            value["work_order"]["required_capabilities"],
            "33",
        )

    def test_settled_unclaimable(self):
        value = self.get(
            "/v1/work-orders/" + SETTLED + "/matches"
        )["data"]

        self.assertEqual(value["eligible_agents"], [])

        self.assertEqual(
            value["evaluations"][0]["rejection"]["code"],
            "WORK_ORDER_NOT_OPEN",
        )

    def test_expired_open_not_discoverable(self):
        self.provider.data["now_unix"] = 2000
        self.provider.data[
            "eligible_agents_by_order"
        ] = {OPEN: []}

        value = self.get(
            "/v1/work-orders/" + OPEN + "/matches"
        )["data"]

        self.assertFalse(
            value["work_order"]["discoverable"]
        )

        self.assertEqual(
            value["evaluations"][0]["rejection"]["code"],
            "EXECUTION_DEADLINE_REACHED",
        )

    def test_pause_takes_precedence(self):
        self.provider.data["protocol_paused"] = True
        self.provider.data[
            "eligible_agents_by_order"
        ] = {OPEN: []}

        value = self.get(
            "/v1/work-orders/" + OPEN + "/matches"
        )["data"]

        self.assertEqual(
            value["evaluations"][0]["rejection"]["code"],
            "PROTOCOL_PAUSED",
        )

    def test_mismatch_fails_closed(self):
        self.provider.data[
            "eligible_agents_by_order"
        ] = {OPEN: [DRONE, SENSOR]}

        self.fails(
            "/v1/work-orders/" + OPEN + "/matches",
            "MATCHING_MISMATCH",
            502,
        )

    def test_invalid_paths(self):
        self.fails(
            "/v1/agents/not-a-pubkey",
            "INVALID_PUBKEY",
            400,
        )

        self.fails(
            "/v1/work-orders/" + OWNER,
            "WORK_ORDER_NOT_FOUND",
            404,
        )

        self.fails(
            "/v1/foo",
            "NOT_FOUND",
            404,
        )

    def test_invalid_queries(self):
        self.fails(
            "/v1/agents?status=Active&status=Revoked",
            "INVALID_QUERY",
            400,
        )

        self.fails(
            "/v1/agents?unexpected=1",
            "INVALID_QUERY",
            400,
        )

        self.fails(
            "/v1/agents?brokenquery",
            "INVALID_QUERY",
            400,
        )

        self.fails(
            "/v1/work-orders?discoverable=yes",
            "INVALID_QUERY",
            400,
        )

        self.fails(
            "/v1/work-orders?status=Dummy",
            "INVALID_STATUS",
            400,
        )

    def test_large_u64_retains_precision(self):
        self.provider.data["agents"][0][
            "capabilities"
        ] = 2**63

        self.provider.data["work_orders"][0][
            "required_capabilities"
        ] = 2**63

        self.provider.data[
            "eligible_agents_by_order"
        ] = {OPEN: [DRONE]}

        response = self.get("/v1/marketplace")
        payload = json.loads(json.dumps(response))

        self.assertEqual(
            payload["data"]["agents"][0][
                "capabilities"
            ],
            str(2**63),
        )

        self.assertEqual(
            payload["data"]["work_orders"][0][
                "required_capabilities"
            ],
            str(2**63),
        )

    def test_http_get_and_post_405(self):
        httpd = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            server.handler_for(self.provider),
        )

        thread = threading.Thread(
            target=httpd.serve_forever,
            daemon=True,
        )
        thread.start()

        try:
            url = (
                "http://127.0.0.1:"
                + str(httpd.server_port)
            )

            with urllib.request.urlopen(
                url + "/health",
                timeout=3,
            ) as response:
                self.assertEqual(
                    json.load(response)["status"], "ok"
                )

            with self.assertRaises(
                urllib.error.HTTPError
            ) as err:
                urllib.request.urlopen(
                    urllib.request.Request(
                        url + "/v1/agents",
                        method="POST",
                    ),
                    timeout=3,
                )

            self.assertEqual(err.exception.code, 405)
            self.assertEqual(
                err.exception.headers["Allow"], "GET"
            )

        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
