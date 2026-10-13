#!/usr/bin/env python3
"""AeroSettle Mission Preflight — read only."""

import json
import urllib.request

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

RPC = "http://127.0.0.1:8899"
API = "http://127.0.0.1:8787"

EXPECTED_GENESIS = (
    "HP9XKTusRPGC78EFDpR9xdEq6simL2vqyDdrMvn6Vacg"
)

EXPECTED_PROGRAM = (
    "CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy"
)


def fetch_json(url):
    with urllib.request.urlopen(
        url,
        timeout=15
    ) as response:
        return json.load(response)


def rpc(method, params=None):
    payload = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params or [],
    }).encode()

    request = urllib.request.Request(
        RPC,
        data=payload,
        headers={
            "Content-Type": "application/json"
        }
    )

    with urllib.request.urlopen(
        request,
        timeout=15
    ) as response:
        result = json.load(response)

    if "error" in result:
        raise RuntimeError(result["error"])

    return result["result"]


def has_capabilities(available, required):
    available = int(available)
    required = int(required)

    return (
        required > 0
        and available >= 0
        and available & required == required
    )


def assess(order, agent, now):
    reasons = []

    if order["status"] != "Open":
        reasons.append("ORDER_NOT_OPEN")

    if now >= int(order["execution_deadline"]):
        reasons.append("ORDER_EXPIRED")

    if order.get("discoverable") is not True:
        reasons.append("NOT_DISCOVERABLE")

    if agent.get("active") is not True:
        reasons.append("AGENT_INACTIVE")

    if (
        order["protocol_config"]
        != agent["protocol_config"]
    ):
        reasons.append("PROTOCOL_MISMATCH")

    if not has_capabilities(
        agent["capabilities"],
        order["required_capabilities"]
    ):
        reasons.append("CAPABILITY_MISMATCH")

    return reasons


def local_time(unix):
    return datetime.fromtimestamp(
        int(unix),
        ZoneInfo("America/Mazatlan")
    ).isoformat()


def load_collection(path):
    payload = fetch_json(API + path)

    if (
        payload.get("meta", {}).get("program_id")
        != EXPECTED_PROGRAM
    ):
        raise RuntimeError(
            "Marketplace API program_id incorrecto"
        )

    if payload.get("page", {}).get("has_more"):
        raise RuntimeError(
            "Existen más páginas; auditoría incompleta"
        )

    if not isinstance(payload.get("data"), list):
        raise RuntimeError(
            "Respuesta Marketplace inesperada"
        )

    return payload


def main():
    genesis = rpc("getGenesisHash")

    if genesis != EXPECTED_GENESIS:
        raise RuntimeError(
            "Genesis incorrecto. Auditoría bloqueada."
        )

    work_orders = load_collection(
        "/v1/work-orders?status=Open"
    )

    agents_result = load_collection(
        "/v1/agents"
    )

    now = int(
        work_orders["meta"]["chain_now_unix"]
    )

    orders = work_orders["data"]
    agents = agents_result["data"]

    print("=== AEROSETTLE MISSION PREFLIGHT ===")
    print("Genesis:", genesis)
    print("Chain time:", local_time(now))
    print("WorkOrders Open:", len(orders))
    print("Registered agents:", len(agents))

    results = []

    for order in orders:
        print("\nWORKORDER:", order["work_order_account"])
        print("Status:", order["status"])
        print(
            "Deadline:",
            local_time(order["execution_deadline"])
        )
        print(
            "Discoverable:",
            order.get("discoverable")
        )
        print(
            "Required capabilities:",
            order["required_capabilities"]
        )

        for agent in agents:
            reasons = assess(order, agent, now)

            eligible_by_metadata = not reasons

            result = {
                "work_order": order["work_order_account"],
                "agent_account": agent["agent_account"],
                "capabilities_match": has_capabilities(
                    agent["capabilities"],
                    order["required_capabilities"]
                ),
                "eligible_by_metadata":
                    eligible_by_metadata,
                "blocking_reasons": reasons,
                "signing_authority_verified": False,
                "claim_authorized": False,
            }

            results.append(result)

            print(
                "  Agent:",
                agent["agent_account"]
            )
            print(
                "  Capabilities match:",
                result["capabilities_match"]
            )
            print(
                "  Metadata eligibility:",
                "YES" if eligible_by_metadata else "NO"
            )
            print(
                "  Reasons:",
                reasons or ["NONE"]
            )

    report = {
        "schema_version":
            "aerosettle.mission_preflight.v1",
        "mode": "read-only",
        "genesis": genesis,
        "chain_now_unix": now,
        "work_orders_count": len(orders),
        "agents_count": len(agents),
        "results": results,
        "write_operations": 0,
    }

    output = Path(
        ".aerosettle-local/mission-preflight.json"
    )

    output.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    output.write_text(
        json.dumps(
            report,
            indent=2,
            ensure_ascii=False
        ) + "\n"
    )

    print("\nReport:", output)
    print("Read-only: 0 transactions")
    print(
        "NOTE: signing authority is not yet verified."
    )


if __name__ == "__main__":
    main()
