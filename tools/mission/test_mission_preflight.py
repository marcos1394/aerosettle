import unittest

from mission_preflight import (
    assess,
    has_capabilities,
)


class MissionPreflightTests(unittest.TestCase):

    def setUp(self):
        self.order = {
            "status": "Open",
            "discoverable": True,
            "execution_deadline": 1000,
            "protocol_config": "config",
            "required_capabilities": "33",
        }

        self.agent = {
            "status": "Active",
            "active": True,
            "protocol_config": "config",
            "capabilities": "32801",
        }

    def test_capabilities_match(self):
        self.assertTrue(
            has_capabilities(32801, 33)
        )

    def test_capabilities_mismatch(self):
        self.assertFalse(
            has_capabilities(32768, 33)
        )

    def test_eligible_metadata(self):
        self.assertEqual(
            assess(
                self.order,
                self.agent,
                500
            ),
            []
        )

    def test_expired(self):
        reasons = assess(
            self.order,
            self.agent,
            1000
        )

        self.assertIn(
            "ORDER_EXPIRED",
            reasons
        )

    def test_undiscoverable(self):
        order = {
            **self.order,
            "discoverable": False,
        }

        reasons = assess(
            order,
            self.agent,
            500
        )

        self.assertIn(
            "NOT_DISCOVERABLE",
            reasons
        )


if __name__ == "__main__":
    unittest.main()
