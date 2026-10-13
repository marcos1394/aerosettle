#!/usr/bin/env python3
"""Generate read-only Rust/Python marketplace parity fixtures."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

import server

VERSION = "aerosettle.matching.parity.v1"
ROOT = Path(__file__).resolve().parents[2]


def number(value, field):
    if (
        isinstance(value, bool)
        or not isinstance(value, (str, int))
    ):
        raise ValueError(f"{field}: invalid integer")

    result = int(value)

    if not 0 <= result < 2**64:
        raise ValueError(f"{field}: outside u64 range")

    return result


def build(live, masks):
    required = (
        number(masks["aerial"], "aerial")
        | number(masks["gps"], "gps")
    )

    telemetry = number(
        masks["telemetry"], "telemetry"
    )

    if (
        not required
        or not telemetry
        or required & telemetry
    ):
        raise ValueError("Invalid capability masks")

    now = int(live["now_unix"])

    if now < 0:
        raise ValueError("Negative chain timestamp")

    accounts = list(live["agents"])

    if len({
        a["agent_account"] for a in accounts
    }) != len(accounts):
        raise ValueError("Duplicated agent accounts")

    orders = [
        o for o in live["work_orders"]
        if number(
            o["required_capabilities"],
            "required_capabilities",
        ) == required
    ]

    if not orders:
        raise ValueError(
            "No work order with aerial + GPS requirements"
        )

    source_order = sorted(
        orders,
        key=lambda o: o["work_order_account"],
    )[0]

    config = source_order["protocol_config"]

    active_agents = [
        a for a in accounts
        if (
            a["protocol_config"] == config
            and a["active"]
        )
    ]

    compatible = [
        a for a in active_agents
        if (
            number(a["capabilities"], "capabilities")
            & required
        ) == required
    ]

    sensor_candidates = [
        a for a in active_agents
        if (
            (
                number(a["capabilities"], "capabilities")
                & required
            ) != required
            and (
                number(a["capabilities"], "capabilities")
                & telemetry
            )
        )
    ]

    if (
        len(compatible) != 1
        or len(sensor_candidates) != 1
    ):
        raise ValueError(
            "Expected one compatible drone and one sensor"
        )

    drone = compatible[0]
    sensor = sensor_candidates[0]

    agents = [
        {
            "agent_account": a["agent_account"],
            "agent_id": a["agent_id"],
            "protocol_config": a["protocol_config"],
            "status": a["status"],
            "active": bool(a["active"]),
            "capabilities": number(
                a["capabilities"], "capabilities"
            ),
        }
        for a in (drone, sensor)
    ]

    order = {
        "work_order_account":
            source_order["work_order_account"],
        "protocol_config": config,
        "status": "Open",
        "is_open": True,
        "execution_deadline": now + 3600,
        "required_capabilities": required,
    }

    def make_case(
        name,
        *,
        paused=False,
        status="Open",
        deadline=None,
        suspend_drone=False,
        capabilities=None,
    ):
        case_agents = copy.deepcopy(agents)
        case_order = dict(order)

        if suspend_drone:
            case_agents[0]["active"] = False
            case_agents[0]["status"] = "OwnerSuspended"

        case_order["status"] = status
        case_order["is_open"] = status == "Open"

        if deadline is not None:
            case_order["execution_deadline"] = deadline

        if capabilities is not None:
            case_order["required_capabilities"] = capabilities

        snapshot = {
            "protocol_paused": paused,
            "now_unix": now,
            "agents": case_agents,
            "work_orders": [case_order],
        }

        decisions = {
            a["agent_account"]: server.rejection(
                case_order, a, snapshot
            )
            for a in case_agents
        }

        eligible = sorted(
            address
            for address, rejection in decisions.items()
            if rejection is None
        )

        # JSON u64 values stay lossless as decimal strings.
        for a in case_agents:
            a["capabilities"] = str(a["capabilities"])

        case_order["required_capabilities"] = str(
            case_order["required_capabilities"]
        )

        return {
            "name": name,
            "input": snapshot,
            "expected": {
                "eligible_agent_accounts": eligible,
                "rejections_by_agent": decisions,
            },
        }

    unused = next(
        (
            1 << bit
            for bit in reversed(range(64))
            if all(
                (
                    number(a["capabilities"], "capabilities")
                    & (1 << bit)
                ) == 0
                for a in agents
            )
        ),
        None,
    )

    if unused is None:
        raise ValueError(
            "No unused capability bit available"
        )

    cases = [
        make_case("open-drone-only"),
        make_case("expired", deadline=now),
        make_case("draft", status="Draft"),
        make_case("settled", status="Settled"),
        make_case("paused", paused=True),
        make_case(
            "drone-suspended",
            suspend_drone=True,
        ),
        make_case(
            "telemetry-both",
            capabilities=telemetry,
        ),
        make_case(
            "unknown-required-bit",
            capabilities=required | unused,
        ),
    ]

    return {
        "schema": VERSION,
        "origin": "Synthetic scenarios derived from Discovery",
        "not_on_chain": True,
        "agent_accounts": {
            "aerial_agent": drone["agent_account"],
            "telemetry_agent": sensor["agent_account"],
        },
        "cases": cases,
    }


def main():
    parser = argparse.ArgumentParser(
        description=__doc__
    )

    parser.add_argument(
        "--snapshot",
        type=Path,
        required=True,
    )

    parser.add_argument(
        "--capabilities",
        type=Path,
        default=ROOT / (
            ".aerosettle-local/"
            "bootstrap-capabilities.json"
        ),
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / (
            ".aerosettle-local/"
            "marketplace-parity-v1.json"
        ),
    )

    args = parser.parse_args()

    result = build(
        json.loads(args.snapshot.read_text()),
        json.loads(args.capabilities.read_text()),
    )

    args.output.parent.mkdir(
        parents=True, exist_ok=True
    )

    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True)
        + "\n"
    )

    print(
        f"✅ {len(result['cases'])} fixtures: "
        f"{args.output}"
    )

    for case in result["cases"]:
        count = len(
            case["expected"]["eligible_agent_accounts"]
        )

        print(
            f"  {case['name']}: "
            f"{count} agente(s) elegible(s)"
        )


if __name__ == "__main__":
    main()
