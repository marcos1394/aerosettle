"""Explicit read-only live probe and bounded offline load evidence for CON-59."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import time
import tracemalloc
from unittest.mock import patch

from tools.integration.devnet import gateway as g


def live() -> dict:
    index = g.Index(g.Provider("official-devnet", g.JsonRpc()))
    snap = index.snapshot()
    return {
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "status": "LIVE_RPC_VERIFIED",
        "network": g.NETWORK, "genesis_hash": g.GENESIS, "program_id": g.PROGRAM,
        "mint": g.MINT, "idl_sha256": g.IDL_SHA256,
        "binary_sha256": g.BINARY_SHA256,
        "deployment_id": g.DEPLOYMENT_ID, "network_id_hex": g.NETWORK_ID_HEX,
        "provider": snap["context"]["provider"],
        "commitment": snap["context"]["commitment"],
        "slot_min": snap["context"]["slot_min"],
        "slot_max": snap["context"]["slot_max"],
        "observed_slot": snap["observed_slot"],
        "agent_count": len(snap["agents"]),
        "work_order_count": len(snap["work_orders"]),
        "snapshot_sha256": hashlib.sha256(json.dumps(snap, sort_keys=True,
            separators=(",", ":")).encode()).hexdigest(),
        "atomic_snapshot": False,
        "metrics": index.stats(), "alerts": index.alert_codes(),
        "solana_transactions_sent": 0,
    }


def offline_load() -> dict:
    from tools.integration.devnet.test_gateway import FakeRpc, discovery_fixture
    rpc = FakeRpc()
    with patch.object(g, "discover", side_effect=discovery_fixture):
        index = g.Index(g.Provider("offline-fixture", rpc))
        api = g.Gateway(index)
        tracemalloc.start()
        started = time.monotonic()
        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(lambda n: api.handle("GET", "/v1/agents?limit=1",
                                                        client=f"offline-{n}"), range(40)))
        elapsed = (time.monotonic() - started) * 1000
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        assert all(status == 200 for status, _, _ in results)
        return {"observed_at": datetime.now(timezone.utc).isoformat(),
                "mode": "OFFLINE_FIXTURE", "requests": len(results), "concurrency": 8,
                "elapsed_ms": round(elapsed, 2), "mean_latency_ms": round(elapsed / len(results), 2),
                "peak_traced_bytes": peak, "errors": 0,
                "cache_hits": index.metrics["cache_hit"],
                "scan_count": index.metrics["scan_ok"],
                "rpc_calls": len(rpc.calls), "metrics": index.stats()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    choices = parser.add_mutually_exclusive_group(required=True)
    choices.add_argument("--live", action="store_true")
    choices.add_argument("--offline-load", action="store_true")
    args = parser.parse_args()
    print(json.dumps(live() if args.live else offline_load(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
