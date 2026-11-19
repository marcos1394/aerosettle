import hashlib
import json
from datetime import datetime, timezone
import unittest
from unittest.mock import patch

from tools.integration.devnet import gateway as g, snapshot
from tools.integration.devnet.test_gateway import FakeRpc, discovery_fixture


class SnapshotTest(unittest.TestCase):
    def test_verified_snapshot_has_bounded_expiry_and_complete_identity(self):
        with patch.object(g, "discover", side_effect=discovery_fixture):
            value = snapshot.create(g.Index(g.Provider("official-devnet", FakeRpc())),
                                    now=datetime(2026, 11, 17, tzinfo=timezone.utc))
        meta = value["metadata"]
        self.assertEqual(meta["genesis_hash"], g.GENESIS)
        self.assertEqual(meta["binary_sha256"], g.BINARY_SHA256)
        self.assertEqual(meta["commitment"], "finalized")
        self.assertEqual(meta["expires_at"], "2026-11-18T00:00:00Z")
        self.assertFalse(meta["atomic_snapshot"])
        self.assertEqual(meta["agent_count"], len(value["agents"]))
        raw = snapshot.serialize(value)
        self.assertEqual(json.loads(raw), value)
        self.assertEqual(len(hashlib.sha256(raw).hexdigest()), 64)

    def test_cached_or_wrong_identity_cannot_be_exported(self):
        valid = {"agents": [], "work_orders": [], "observed_slot": 1,
                 "context": {"source": "CACHED_VERIFIED", "network": g.NETWORK,
                             "genesis_hash": g.GENESIS, "program_id": g.PROGRAM,
                             "idl_sha256": g.IDL_SHA256, "mint": g.MINT,
                             "commitment": "finalized", "provider": "official-devnet",
                             "slot_min": 1, "slot_max": 1}}
        class Stub:
            def snapshot(self):
                return valid
        with self.assertRaisesRegex(ValueError, "SNAPSHOT_PROVENANCE_INVALID"):
            snapshot.create(Stub())
        valid["context"]["source"] = "INDEXED_FROM_RPC"
        valid["context"]["genesis_hash"] = "wrong"
        with self.assertRaisesRegex(ValueError, "SNAPSHOT_PROVENANCE_INVALID"):
            snapshot.create(Stub())


if __name__ == "__main__":
    unittest.main()
