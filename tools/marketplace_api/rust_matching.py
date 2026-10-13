"""Strict stdio adapter for AeroSettle's original Rust matching engine."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


class RustMatchingError(RuntimeError):
    pass


def decimal(value, bits=64, signed=False):
    if isinstance(value, bool):
        raise RustMatchingError("Boolean is not an integer")

    if isinstance(value, int):
        text = str(value)
    elif isinstance(value, str):
        text = value
    else:
        raise RustMatchingError("Invalid integer type")

    pattern = r"-?(0|[1-9][0-9]*)" if signed else r"(0|[1-9][0-9]*)"

    if not re.fullmatch(pattern, text):
        raise RustMatchingError("Invalid decimal integer")

    number = int(text)
    lower = -(1 << (bits - 1)) if signed else 0
    upper = (1 << (bits - 1)) - 1 if signed else (1 << bits) - 1

    if not lower <= number <= upper:
        raise RustMatchingError("Integer outside range")

    return str(number)


def boolean(value):
    if type(value) is not bool:
        raise RustMatchingError("Expected boolean")

    return "1" if value else "0"


def safe_field(value):
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 128
        or any(x in value for x in ("\n", "\r", "|"))
    ):
        raise RustMatchingError("Invalid bridge field")

    return value


class RustMatcher:
    def __init__(self, executable):
        self.executable = Path(executable).resolve()

    def __call__(self, order, snapshot):
        agents = snapshot["agents"]

        if len(agents) > 500:
            raise RustMatchingError("Too many agents")

        header = [
            "AEROSETTLE_MATCH_V1",
            "paused|" + boolean(snapshot["protocol_paused"]),
            "now|" + decimal(snapshot["now_unix"], signed=True),
            "|".join([
                "order",
                safe_field(order["protocol_config"]),
                boolean(order["is_open"]),
                decimal(order["required_capabilities"]),
                decimal(order["execution_deadline"], signed=True),
            ]),
            "agents|" + str(len(agents)),
        ]

        known = set()
        known_ids = set()

        for agent in agents:
            account = safe_field(agent["agent_account"])
            agent_id = agent["agent_id"]

            if (
                not isinstance(agent_id, str)
                or not re.fullmatch(
                    r"[0-9a-fA-F]{64}", agent_id
                )
            ):
                raise RustMatchingError("Invalid agent_id")

            if account in known or agent_id.lower() in known_ids:
                raise RustMatchingError("Duplicate agent identity")

            known.add(account)
            known_ids.add(agent_id.lower())

            header.append("|".join([
                "agent",
                account,
                agent_id.lower(),
                safe_field(agent["protocol_config"]),
                decimal(agent["capabilities"]),
                boolean(agent["active"]),
            ]))

        payload = "\n".join(header + ["END"]) + "\n"

        if len(payload.encode("utf-8")) > 1_048_576:
            raise RustMatchingError("Bridge input too large")

        try:
            result = subprocess.run(
                [str(self.executable)],
                input=payload,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RustMatchingError(
                "Rust matcher unavailable or timed out"
            ) from exc

        if result.returncode != 0:
            raise RustMatchingError(
                "Rust matcher failed: "
                + result.stderr.strip()[:600]
            )

        lines = result.stdout.splitlines()

        if (
            len(lines) < 2
            or lines[0] != "AEROSETTLE_MATCH_RESULT_V1"
            or lines[-1] != "END"
        ):
            raise RustMatchingError(
                "Invalid Rust response envelope"
            )

        decisions = {}
        shortlist = []
        in_shortlist = False

        for line in lines[1:-1]:
            fields = line.split("|")

            if fields[0] == "evaluation":
                if (
                    in_shortlist
                    or len(fields) not in (3, 4)
                    or fields[1] not in known
                    or fields[1] in decisions
                ):
                    raise RustMatchingError(
                        "Invalid evaluation record"
                    )

                status = fields[2]

                if status == "ELIGIBLE" and len(fields) == 3:
                    reason = None
                elif (
                    status == "MISSING_CAPABILITIES"
                    and len(fields) == 4
                ):
                    mask = decimal(fields[3])

                    if mask == "0":
                        raise RustMatchingError(
                            "Invalid missing mask"
                        )

                    reason = {
                        "code": status,
                        "missing_mask": mask,
                    }
                elif len(fields) == 3 and status in {
                    "PROTOCOL_PAUSED",
                    "WORK_ORDER_NOT_OPEN",
                    "EXECUTION_DEADLINE_REACHED",
                    "DIFFERENT_PROTOCOL",
                    "AGENT_INACTIVE",
                }:
                    reason = {"code": status}
                else:
                    raise RustMatchingError(
                        "Unknown Rust rejection"
                    )

                decisions[fields[1]] = reason

            elif fields[0] == "shortlist":
                in_shortlist = True

                if (
                    len(fields) != 2
                    or fields[1] not in known
                    or fields[1] in shortlist
                ):
                    raise RustMatchingError(
                        "Invalid shortlist record"
                    )

                shortlist.append(fields[1])

            else:
                raise RustMatchingError(
                    "Unexpected Rust output"
                )

        if set(decisions) != known:
            raise RustMatchingError(
                "Incomplete Rust evaluations"
            )

        eligible_from_evaluation = {
            account
            for account, reason in decisions.items()
            if reason is None
        }

        if set(shortlist) != eligible_from_evaluation:
            raise RustMatchingError(
                "Rust shortlist differs from individual evaluations"
            )

        return {
            "eligible_agent_accounts": shortlist,
            "rejections_by_agent": decisions,
        }
