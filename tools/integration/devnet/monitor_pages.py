"""CON-59 public read-only health monitor and optional local Cloudflare quota check.

The scheduled mode needs no secrets. Quota analytics require a local Wrangler
session and are never requested by GitHub Actions.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import ssl
import subprocess
import time
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

import certifi

from tools.integration.devnet import gateway as g


BASE = "https://conatus-devnet-staging.pages.dev"
ACCOUNT_ID = "54cb929430c4a02b90d6ea3ce356d0d9"
FREE_DAILY_REQUESTS = 100_000
EXPIRY_WARNING_SECONDS = 8 * 60 * 60
RPC_SLOW_MS = 2_000
MAX_RESPONSE = 100_000


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise ValueError("REDIRECT_REJECTED")


def http_get(path: str) -> dict:
    assert path in {"/release.json", "/api/health", "/api/ready"}
    opener = build_opener(HTTPSHandler(context=ssl.create_default_context(cafile=certifi.where())),
                          NoRedirect())
    request = Request(BASE + path, headers={"User-Agent": "conatus-con59-monitor/1"})
    try:
        try:
            response = opener.open(request, timeout=8)
        except HTTPError as error:
            response = error
        with response:
            if response.geturl() != BASE + path:
                raise ValueError("HOST_CHANGED")
            raw = response.read(MAX_RESPONSE + 1)
            if len(raw) > MAX_RESPONSE:
                raise ValueError("RESPONSE_TOO_LARGE")
            body = raw.decode("utf-8", errors="replace")
            try:
                parsed = json.loads(body)
            except ValueError:
                parsed = None
            return {"status": response.status, "json": parsed,
                    "cloudflare_1027": response.status >= 500 and "1027" in body}
    except Exception as error:
        return {"status": 0, "json": None, "cloudflare_1027": False,
                "error": type(error).__name__}


def rpc_probe() -> dict:
    start = time.monotonic()
    try:
        rpc = g.JsonRpc(g.OFFICIAL_RPC, timeout=5)
        genesis = rpc.call("getGenesisHash", [])
        slot = rpc.call("getSlot", [{"commitment": "finalized"}])
        if genesis != g.GENESIS or type(slot) is not int or slot < 0:
            return {"status": "IDENTITY_MISMATCH", "latency_ms": round((time.monotonic()-start)*1000, 1)}
        return {"status": "VERIFIED", "genesis_hash": genesis, "slot": slot,
                "latency_ms": round((time.monotonic()-start)*1000, 1),
                "provider_mode": "SINGLE_PROVIDER_MODE"}
    except g.GatewayError as error:
        return {"status": "ERROR", "code": error.code,
                "latency_ms": round((time.monotonic()-start)*1000, 1),
                "provider_mode": "SINGLE_PROVIDER_MODE"}
    except Exception as error:
        return {"status": "ERROR", "code": type(error).__name__,
                "latency_ms": round((time.monotonic()-start)*1000, 1),
                "provider_mode": "SINGLE_PROVIDER_MODE"}


def cloudflare_usage(wrangler: Path, now: datetime) -> dict:
    """Read account-wide daily usage via GraphQL; keep OAuth token in memory."""
    try:
        credential = subprocess.run([str(wrangler), "auth", "token", "--json"],
                                    capture_output=True, text=True, timeout=15, check=True)
        token = json.loads(credential.stdout)["token"]
        if not isinstance(token, str) or not token:
            raise ValueError("AUTH_UNAVAILABLE")
        start = now.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        query = """query($accountTag: string!, $start: Time!, $end: Time!) {
          viewer { accounts(filter: {accountTag: $accountTag}) {
            workersInvocationsAdaptive(limit: 1,
              filter: {datetime_geq: $start, datetime_leq: $end}) {
                sum { requests errors }
            }
          } }
        }"""
        payload = json.dumps({"query": query, "variables": {
            "accountTag": ACCOUNT_ID, "start": start.isoformat().replace("+00:00", "Z"),
            "end": now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")}}).encode()
        request = Request("https://api.cloudflare.com/client/v4/graphql", data=payload,
                          headers={"Authorization": "Bearer " + token,
                                   "Content-Type": "application/json",
                                   "User-Agent": "conatus-con59-monitor/1"}, method="POST")
        opener = build_opener(HTTPSHandler(context=ssl.create_default_context(cafile=certifi.where())),
                              NoRedirect())
        with opener.open(request, timeout=10) as response:
            raw = response.read(MAX_RESPONSE + 1)
        if len(raw) > MAX_RESPONSE:
            raise ValueError("ANALYTICS_TOO_LARGE")
        result = json.loads(raw)
        rows = result["data"]["viewer"]["accounts"]
        if len(rows) != 1 or result.get("errors"):
            raise ValueError("ANALYTICS_UNAVAILABLE")
        metrics = rows[0]["workersInvocationsAdaptive"]
        used = sum(int(row["sum"]["requests"]) for row in metrics)
        if used < 0:
            raise ValueError("ANALYTICS_INVALID")
        return {"status": "OBSERVED", "scope": "ACCOUNT_WIDE", "requests_today": used,
                "free_daily_limit": FREE_DAILY_REQUESTS, "day_utc": start.date().isoformat()}
    except Exception:
        return {"status": "UNAVAILABLE", "scope": "ACCOUNT_WIDE"}


def assess(observed: dict, now: datetime) -> list[dict]:
    alerts: list[dict] = []

    def add(code: str, detail: str) -> None:
        if not any(alert["code"] == code for alert in alerts):
            alerts.append({"code": code, "severity": "CRITICAL", "detail": detail})

    release, health, ready = (observed[name] for name in ("release", "health", "ready"))
    if any(item.get("cloudflare_1027") for item in (release, health, ready)):
        add("CLOUDFLARE_QUOTA_EXHAUSTED", "Pages Function returned Cloudflare 1027")
    if release.get("status") != 200 or not isinstance(release.get("json"), dict):
        add("RELEASE_UNAVAILABLE", "Public release.json is unavailable or invalid")
    else:
        value = release["json"]
        if (value.get("environment") != "DEVNET_STAGING" or value.get("network") != g.NETWORK
                or value.get("genesis_hash") != g.GENESIS or value.get("program_id") != g.PROGRAM
                or value.get("token_mint") != g.MINT or value.get("idl_sha256") != g.IDL_SHA256
                or not isinstance(value.get("release_id"), str)):
            add("RELEASE_IDENTITY_MISMATCH", "Public release identity differs from approved Devnet")
        try:
            expires = datetime.fromisoformat(value["snapshot_expires_at"].replace("Z", "+00:00"))
            if expires.tzinfo is None:
                raise ValueError("NAIVE_EXPIRY")
            remaining = (expires - now.astimezone(timezone.utc)).total_seconds()
            if remaining <= 0:
                add("SNAPSHOT_EXPIRED", "Release-bound snapshot has expired")
            elif remaining <= EXPIRY_WARNING_SECONDS:
                add("SNAPSHOT_EXPIRING", f"Snapshot expires in {int(remaining)} seconds")
        except (KeyError, TypeError, ValueError):
            add("RELEASE_EXPIRY_INVALID", "Snapshot expiry is absent or invalid")
    health_body = health.get("json") if isinstance(health.get("json"), dict) else {}
    ready_body = ready.get("json") if isinstance(ready.get("json"), dict) else {}
    if health.get("status") != 200 or health_body.get("status") != "ok":
        add("API_HEALTH_FAILED", "Public API health endpoint is unavailable")
    if ready.get("status") == 503:
        add("API_503", "Public API readiness returned HTTP 503")
    elif ready.get("status") != 200 or ready_body.get("status") != "ready":
        add("API_READINESS_FAILED", "Public API readiness is unavailable or invalid")
    elif isinstance(release.get("json"), dict) and (ready_body.get("genesis") != g.GENESIS
            or ready_body.get("program_id") != g.PROGRAM or
            ready_body.get("snapshot_sha256") != release["json"].get("snapshot_sha256")):
        add("API_RELEASE_MISMATCH", "Readiness is not bound to the public release")
    rpc = observed["rpc"]
    if rpc.get("status") != "VERIFIED":
        add("RPC_DEGRADED", f"Official Devnet RPC probe failed: {rpc.get('code', rpc.get('status'))}")
    elif rpc.get("genesis_hash") != g.GENESIS or type(rpc.get("slot")) is not int:
        add("RPC_IDENTITY_MISMATCH", "RPC genesis or finalized slot is invalid")
    elif rpc.get("latency_ms", 0) >= RPC_SLOW_MS:
        add("RPC_SLOW", "Official Devnet RPC probe exceeded 2 seconds")
    quota = observed.get("quota", {"status": "NOT_CONFIGURED"})
    if quota.get("status") == "OBSERVED":
        used = quota.get("requests_today")
        if type(used) is not int or used < 0:
            add("QUOTA_TELEMETRY_INVALID", "Cloudflare usage count is invalid")
        elif used >= FREE_DAILY_REQUESTS:
            add("CLOUDFLARE_QUOTA_EXHAUSTED", "Account-wide Workers Free quota is exhausted")
        elif used >= FREE_DAILY_REQUESTS * 0.8:
            add("CLOUDFLARE_QUOTA_NEAR_LIMIT", "Account-wide Workers Free quota is at least 80% used")
    elif quota.get("status") == "UNAVAILABLE":
        add("QUOTA_TELEMETRY_UNAVAILABLE", "Local Cloudflare analytics read failed")
    return alerts


def collect_live(*, wrangler: Path | None = None, now: datetime | None = None) -> dict:
    observed_at = now or datetime.now(timezone.utc)
    result = {"observed_at": observed_at.isoformat(), "base_url": BASE,
              "release": http_get("/release.json"), "health": http_get("/api/health"),
              "ready": http_get("/api/ready"), "rpc": rpc_probe(),
              "quota": cloudflare_usage(wrangler, observed_at) if wrangler else
              {"status": "NOT_CONFIGURED", "scope": "ACCOUNT_WIDE"}}
    result["alerts"] = assess(result, observed_at)
    result["status"] = "ALERT" if result["alerts"] else "HEALTHY"
    return result


def demo(now: datetime) -> dict:
    return {"observed_at": now.isoformat(), "base_url": BASE,
            "release": {"status": 200, "json": {"environment": "DEVNET_STAGING",
                "network": g.NETWORK, "genesis_hash": g.GENESIS, "program_id": g.PROGRAM,
                "token_mint": g.MINT, "idl_sha256": g.IDL_SHA256, "release_id": "demo",
                "snapshot_expires_at": now.isoformat(), "snapshot_sha256": "demo"}},
            "health": {"status": 200, "json": {"status": "ok"}},
            "ready": {"status": 503, "json": {"status": "stale"}, "cloudflare_1027": True},
            "rpc": {"status": "ERROR", "code": "RPC_RATE_LIMITED"},
            "quota": {"status": "OBSERVED", "requests_today": 100_000}}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wrangler-bin", type=Path,
                        help="Optional local quota telemetry; never use in GitHub Actions")
    parser.add_argument("--demo", action="store_true", help="Induce synthetic alerts without network")
    parser.add_argument("--output", type=Path, help="Write JSON evidence without secrets")
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    result = demo(now) if args.demo else collect_live(wrangler=args.wrangler_bin, now=now)
    if args.demo:
        result["alerts"] = assess(result, now)
        result["status"] = "ALERT"
        result["provenance"] = "SYNTHETIC_TEST"
    else:
        result["provenance"] = "PUBLIC_READ_ONLY_PROBE"
    encoded = json.dumps(result, sort_keys=True, indent=2) + "\n"
    if args.output:
        args.output.write_text(encoded)
    else:
        print(encoded)
    for alert in result["alerts"]:
        print(f"::error title=CON-59 {alert['code']}::{alert['detail']}")
    if result["alerts"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
