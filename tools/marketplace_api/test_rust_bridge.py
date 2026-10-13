"""EPIC 3.3.2: execute real Rust matching on parity fixtures."""

import json
import unittest
from pathlib import Path

from rust_matching import RustMatcher, RustMatchingError

ROOT = Path(__file__).resolve().parents[2]
BIN = ROOT / "target/debug/examples/marketplace_match_bridge"

FIXTURES = (
    ROOT / ".aerosettle-local/marketplace-parity-v1.json"
)


class RustBridgeTests(unittest.TestCase):
    def test_eight_parity_vectors(self):
        self.assertTrue(
            BIN.is_file(),
            "Build marketplace_match_bridge first",
        )
        self.assertTrue(
            FIXTURES.is_file(),
            "Regenerate parity fixtures first",
        )

        document = json.loads(FIXTURES.read_text())

        self.assertEqual(
            document["schema"],
            "aerosettle.matching.parity.v1",
        )
        self.assertEqual(len(document["cases"]), 8)

        matcher = RustMatcher(BIN)

        for case in document["cases"]:
            with self.subTest(case=case["name"]):
                snapshot = case["input"]

                order = snapshot["work_orders"][0]

                actual = matcher(order, snapshot)
                expected = case["expected"]

                self.assertEqual(
                    sorted(actual["eligible_agent_accounts"]),
                    expected["eligible_agent_accounts"],
                )

                self.assertEqual(
                    actual["rejections_by_agent"],
                    expected["rejections_by_agent"],
                )

    def test_missing_executable_fails_closed(self):
        matcher = RustMatcher(
            ROOT / "target/debug/examples/does-not-exist"
        )

        fixture = json.loads(
            FIXTURES.read_text()
        )["cases"][0]["input"]

        with self.assertRaises(RustMatchingError):
            matcher(
                fixture["work_orders"][0],
                fixture,
            )


if __name__ == "__main__":
    unittest.main()
