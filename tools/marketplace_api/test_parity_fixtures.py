"""Offline parity fixture contract tests."""

import copy
import unittest

from parity_fixtures import build, number


def sample():
    return {
        "now_unix": 1000,
        "agents": [
            {
                "agent_account": "drone",
                "agent_id": "11" * 32,
                "protocol_config": "config",
                "active": True,
                "status": "Active",
                "capabilities": 37,
            },
            {
                "agent_account": "sensor",
                "agent_id": "22" * 32,
                "protocol_config": "config",
                "active": True,
                "status": "Active",
                "capabilities": 4,
            },
        ],
        "work_orders": [
            {
                "work_order_account": "order",
                "protocol_config": "config",
                "required_capabilities": 33,
                "status": "Settled",
                "is_open": False,
                "execution_deadline": 900,
            },
        ],
    }


class ParityFixtureTests(unittest.TestCase):
    def setUp(self):
        self.result = build(
            sample(),
            {
                "aerial": "1",
                "gps": "32",
                "telemetry": "4",
            },
        )

        self.cases = {
            c["name"]: c
            for c in self.result["cases"]
        }

    def test_eight_scenarios(self):
        self.assertEqual(len(self.cases), 8)
        self.assertTrue(self.result["not_on_chain"])

    def test_only_drone_matches(self):
        result = self.cases[
            "open-drone-only"
        ]["expected"]

        self.assertEqual(
            result["eligible_agent_accounts"],
            ["drone"],
        )

        self.assertEqual(
            result["rejections_by_agent"]["sensor"],
            {
                "code": "MISSING_CAPABILITIES",
                "missing_mask": "33",
            },
        )

    def test_noneligible_scenarios(self):
        names = (
            "expired",
            "draft",
            "settled",
            "paused",
            "drone-suspended",
            "unknown-required-bit",
        )

        for name in names:
            with self.subTest(name=name):
                self.assertEqual(
                    self.cases[name]["expected"][
                        "eligible_agent_accounts"
                    ],
                    [],
                )

    def test_telemetry_accepts_both(self):
        self.assertEqual(
            self.cases["telemetry-both"][
                "expected"
            ]["eligible_agent_accounts"],
            ["drone", "sensor"],
        )

    def test_u64_are_decimal_strings(self):
        scenario = self.cases[
            "unknown-required-bit"
        ]["input"]

        self.assertIsInstance(
            scenario["agents"][0]["capabilities"],
            str,
        )

        self.assertIsInstance(
            scenario["work_orders"][0][
                "required_capabilities"
            ],
            str,
        )

    def test_duplicate_agent_rejected(self):
        data = sample()

        data["agents"].append(
            copy.deepcopy(data["agents"][0])
        )

        with self.assertRaisesRegex(
            ValueError, "Duplicated"
        ):
            build(
                data,
                {
                    "aerial": "1",
                    "gps": "32",
                    "telemetry": "4",
                },
            )

    def test_u64_bounds(self):
        for value in (-1, 2**64, True):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    number(value, "mask")


if __name__ == "__main__":
    unittest.main()
