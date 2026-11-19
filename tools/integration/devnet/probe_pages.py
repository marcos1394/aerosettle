"""Read-only public HTTPS verification of the approved CON-59 Pages release."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import ssl
import time
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

import certifi


BASE = "https://conatus-devnet-staging.pages.dev"
GENESIS = "EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG"
PROGRAM = "CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy"
MINT = "HpfaV9oRuTN1b3ktDKvJoWqUWFZ1o9VFmhejxxqQ1vyh"
CONTEXT = ssl.create_default_context(cafile=certifi.where())


def request(path: str, *, method: str = "GET", origin: str | None = None) -> dict:
    headers = {"User-Agent": "conatus-con59-public-probe/1"}
    if origin is not None:
        headers["Origin"] = origin
    started = time.monotonic()
    try:
        response = urlopen(Request(BASE + path, headers=headers, method=method),
                           context=CONTEXT, timeout=15)
    except HTTPError as error:
        response = error
    with response:
        assert response.geturl() == BASE + path, f"UNEXPECTED_REDIRECT:{path}"
        raw = response.read(100_001)
        assert len(raw) <= 100_000, f"OVERSIZE_RESPONSE:{path}"
        return {"status": response.status, "body": json.loads(raw) if raw else {},
                "headers": {key.lower(): value for key, value in response.headers.items()},
                "latency_ms": round((time.monotonic() - started) * 1000, 1),
                "body_sha256": hashlib.sha256(raw).hexdigest()}


def verify(release_id: str) -> dict:
    checks: list[dict] = []

    def get(path: str, status: int = 200, *, method: str = "GET",
            origin: str | None = None) -> dict:
        result = request(path, method=method, origin=origin)
        assert result["status"] == status, f"HTTP_STATUS:{path}:{result['status']}"
        checks.append({"path": path, "method": method, "status": status,
                       "latency_ms": result["latency_ms"],
                       "body_sha256": result["body_sha256"]})
        return result

    release = get("/release.json")
    assert release["body"]["release_id"] == release_id
    assert release["body"]["environment"] == "DEVNET_STAGING"
    assert release["body"]["transactions_sent"] == 0
    assert release["headers"].get("strict-transport-security") == "max-age=31536000"
    assert "default-src 'none'" in release["headers"].get("content-security-policy", "")
    health = get("/api/health")
    assert health["body"]["status"] == "ok"
    ready = get("/api/ready")
    assert ready["body"]["status"] == "ready"
    assert ready["body"]["genesis"] == GENESIS
    assert ready["body"]["program_id"] == PROGRAM
    assert ready["body"]["snapshot_sha256"] == release["body"]["snapshot_sha256"]
    for name in ("strict-transport-security", "content-security-policy", "referrer-policy",
                 "x-content-type-options", "x-frame-options", "permissions-policy"):
        assert name in ready["headers"], f"MISSING_HEADER:{name}"
    assert ready["headers"].get("access-control-allow-origin") is None
    network = get("/api/v1/network")["body"]
    program = get("/api/v1/program")["body"]
    assert network["data"]["genesis_hash"] == GENESIS
    assert program["data"]["program_id"] == PROGRAM
    assert program["data"]["mint"] == MINT

    counts = {}
    for resource, key in (("agents", "agent_account"), ("workorders", "work_order_account")):
        rows = []
        cursor = None
        while True:
            path = f"/api/v1/{resource}?limit=2"
            if cursor:
                path += "&cursor=" + quote(cursor, safe="")
            page = get(path)["body"]
            assert page["advisory_only"] is True
            assert page["is_financial_authority"] is False
            assert page["is_executable"] is False
            provenance = page["provenance"]
            assert provenance["commitment"] == "finalized"
            assert provenance["program_id"] == PROGRAM
            assert provenance["genesis_hash"] == GENESIS
            assert provenance["snapshot_sha256"] == ready["body"]["snapshot_sha256"]
            assert provenance["provenance"] == "RELEASE_BOUND_RPC_SNAPSHOT"
            rows.extend(page["data"]["items"])
            cursor = page["data"]["next_cursor"]
            if cursor is None:
                assert len(rows) == page["data"]["total"]
                break
            assert len(rows) < 500, "PAGINATION_LOOP"
        assert len(rows) == 7
        assert len({row[key] for row in rows}) == 7
        assert get(f"/api/v1/{resource}/{rows[0][key]}")["body"]["data"][key] == rows[0][key]
        counts[resource] = len(rows)

    empty = get("/api/v1/agents?status=Revoked")["body"]["data"]
    assert empty == {"items": [], "next_cursor": None, "total": 0}
    assert get("/api/v1/agents?limit=51", 400)["body"]["error"]["code"] == "INVALID_LIMIT"
    assert get("/api/v1/agents?limit=1&limit=2", 400)["body"]["error"]["code"] == "INVALID_QUERY"
    assert get("/api/v1/agents/not-a-key", 400)["body"]["error"]["code"] == "INVALID_PUBKEY"
    assert get("/api/v1/unknown", 404)["body"]["error"]["code"] == "ROUTE_NOT_FOUND"
    assert get("/api/v1/agents", 405, method="POST")["body"]["error"]["code"] == "METHOD_NOT_ALLOWED"
    assert get("/api/v1/agents", 403, origin="https://other.example")["body"]["error"]["code"] == "ORIGIN_NOT_ALLOWED"
    allowed = get("/api/v1/agents?limit=1", origin=BASE)
    assert allowed["headers"].get("access-control-allow-origin") == BASE
    assert allowed["headers"].get("cache-control") == "no-store"
    return {"observed_at": datetime.now(timezone.utc).isoformat(),
            "base_url": BASE + "/", "release_id": release_id,
            "source_commit": release["body"]["commit_sha"],
            "artifact_digest": release["body"]["artifact_digest"],
            "snapshot_sha256": ready["body"]["snapshot_sha256"],
            "snapshot_expires_at": ready["body"]["expires_at"],
            "network": "solana:devnet", "genesis_hash": GENESIS,
            "program_id": PROGRAM, "mint": MINT, "counts": counts,
            "https_verified": True, "security_headers_verified": True,
            "cors_verified": True, "pagination_verified": True,
            "negative_requests_verified": True, "checks": checks,
            "onchain_transactions_sent": 0}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("release_id")
    args = parser.parse_args()
    print(json.dumps(verify(args.release_id), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
