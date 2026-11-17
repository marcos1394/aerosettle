"""Export a bounded, verified Devnet account snapshot for a Pages Free release.

The SHA-256 pins immutable release bytes; it is not an independent signature.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

from tools.integration.devnet import gateway as g

MAX_AGE = timedelta(hours=24)


def create(index: g.Index, *, now: datetime | None = None) -> dict:
    observed = now or datetime.now(timezone.utc)
    if observed.tzinfo is None:
        raise ValueError("SNAPSHOT_TIME_INVALID")
    observed = observed.astimezone(timezone.utc)
    snapshot = index.snapshot()
    context = snapshot["context"]
    if (context.get("source") != "INDEXED_FROM_RPC" or context.get("network") != g.NETWORK
            or context.get("genesis_hash") != g.GENESIS or context.get("program_id") != g.PROGRAM
            or context.get("idl_sha256") != g.IDL_SHA256 or context.get("mint") != g.MINT
            or context.get("commitment") != "finalized" or context.get("provider") != "official-devnet"):
        raise ValueError("SNAPSHOT_PROVENANCE_INVALID")
    if len(snapshot["agents"]) > g.MAX_ACCOUNTS or len(snapshot["work_orders"]) > g.MAX_ACCOUNTS:
        raise ValueError("SNAPSHOT_LIMIT_EXCEEDED")
    return {
        "schema_version": 1,
        "metadata": {
            "network": g.NETWORK, "genesis_hash": g.GENESIS, "program_id": g.PROGRAM,
            "idl_sha256": g.IDL_SHA256, "binary_sha256": g.BINARY_SHA256,
            "deployment_id": g.DEPLOYMENT_ID, "mint": g.MINT, "token_program": g.TOKEN,
            "mint_authority": g.MINT_AUTHORITY, "mint_decimals": 6,
            "source_rpc": g.OFFICIAL_RPC, "provider": context["provider"],
            "commitment": "finalized", "slot_min": context["slot_min"],
            "slot_max": context["slot_max"], "observed_slot": snapshot["observed_slot"],
            "generated_at": observed.isoformat().replace("+00:00", "Z"),
            "expires_at": (observed + MAX_AGE).isoformat().replace("+00:00", "Z"),
            "provenance": "RELEASE_BOUND_RPC_SNAPSHOT", "atomic_snapshot": False,
            "agent_count": len(snapshot["agents"]),
            "work_order_count": len(snapshot["work_orders"]),
        },
        "agents": snapshot["agents"], "work_orders": snapshot["work_orders"],
    }


def serialize(value: dict) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    index = g.Index(g.Provider("official-devnet", g.JsonRpc()))
    raw = serialize(create(index))
    args.output.write_bytes(raw)
    meta = json.loads(raw)["metadata"]
    print(json.dumps({"status": "SNAPSHOT_EXPORTED", "sha256": hashlib.sha256(raw).hexdigest(),
                      **meta}, sort_keys=True))


if __name__ == "__main__":
    main()
