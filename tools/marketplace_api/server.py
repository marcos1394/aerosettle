#!/usr/bin/env python3
"""AeroSettle Marketplace API: read-only local HTTP service."""
from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "discovery"))

import agent_discovery as discovery
import rust_matching
import cursor_pagination
import openapi_spec

PROGRAM_ID = "CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy"
GENESIS = "HP9XKTusRPGC78EFDpR9xdEq6simL2vqyDdrMvn6Vacg"

STATUSES = frozenset({
    "Draft", "Open", "Claimed",
    "Submitted", "Verified", "Settled",
})


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code


def require_pubkey(value: str) -> None:
    try:
        if len(value) > 50:
            raise ValueError("too long")
        discovery.b58decode(value, 32)
    except (discovery.DiscoveryError, ValueError) as exc:
        raise ApiError(
            400,
            "INVALID_PUBKEY",
            "Expected a canonical Solana pubkey",
        ) from exc


def metadata(snapshot: dict) -> dict:
    return {
        "program_id": snapshot["program_id"],
        "commitment": snapshot["commitment"],
        "chain_now_unix": snapshot["now_unix"],
        "rpc_context_slots": snapshot["rpc_context_slots"],
        "atomic_snapshot": False,
        "read_only": True,
        "matching_engine": "rust-epic-3.1",
        "matching_authority": "claim_work_order on-chain",
    }


def projected_agent(agent: dict) -> dict:
    return {
        **agent,
        "capabilities": str(agent["capabilities"]),
    }


def discoverable(order: dict, snapshot: dict) -> bool:
    return (
        not snapshot["protocol_paused"]
        and order["is_open"]
        and snapshot["now_unix"] < order["execution_deadline"]
    )


def projected_order(order: dict, snapshot: dict) -> dict:
    return {
        **order,
        "required_capabilities": str(
            order["required_capabilities"]
        ),
        "discoverable": discoverable(order, snapshot),
    }


def rejection(
    order: dict,
    agent: dict,
    snapshot: dict,
) -> dict | None:
    """Mirror the EPIC 3.1 eligibility predicate."""
    if snapshot["protocol_paused"]:
        return {"code": "PROTOCOL_PAUSED"}

    if not order["is_open"]:
        return {"code": "WORK_ORDER_NOT_OPEN"}

    if snapshot["now_unix"] >= order["execution_deadline"]:
        return {"code": "EXECUTION_DEADLINE_REACHED"}

    if order["protocol_config"] != agent["protocol_config"]:
        return {"code": "DIFFERENT_PROTOCOL"}

    if not agent["active"]:
        return {"code": "AGENT_INACTIVE"}

    missing = (
        order["required_capabilities"]
        & ~agent["capabilities"]
    )

    if missing:
        return {
            "code": "MISSING_CAPABILITIES",
            "missing_mask": str(missing),
        }

    return None


def decision_set(order: dict, snapshot: dict, matcher) -> dict:
    """Use Rust matching, cross-check against Discovery, fail closed."""
    result = matcher(order, snapshot)

    rejections = result["rejections_by_agent"]
    shortlisted = result["eligible_agent_accounts"]

    lookup = {
        agent["agent_account"]: agent
        for agent in snapshot["agents"]
    }

    if (
        len(lookup) != len(snapshot["agents"])
        or set(rejections) != set(lookup)
        or len(set(shortlisted)) != len(shortlisted)
        or any(
            account not in lookup
            for account in shortlisted
        )
        or set(shortlisted) != {
            account
            for account, reason in rejections.items()
            if reason is None
        }
    ):
        raise ApiError(
            502,
            "INVALID_RUST_MATCHING",
            "Rust matching response is inconsistent",
        )

    expected = snapshot["eligible_agents_by_order"].get(
        order["work_order_account"], []
    )

    if sorted(shortlisted) != sorted(expected):
        raise ApiError(
            502,
            "MATCHING_MISMATCH",
            "Rust and Discovery matching disagree",
        )

    return {
        "eligible_agents": [
            projected_agent(lookup[account])
            for account in shortlisted
        ],
        "evaluations": [
            {
                "agent_account": agent["agent_account"],
                "eligible":
                    rejections[agent["agent_account"]] is None,
                "rejection":
                    rejections[agent["agent_account"]],
            }
            for agent in snapshot["agents"]
        ],
    }



def capability_mask(value):
    if value is None:
        return None

    if (
        not isinstance(value, str)
        or not value
        or len(value) > 20
        or (
            value != "0"
            and (
                not value.isascii()
                or not value.isdecimal()
                or value.startswith("0")
            )
        )
    ):
        raise ApiError(
            400, "INVALID_CAPABILITIES",
            "Expected an unsigned decimal u64 mask",
        )

    mask = int(value)

    if mask > (1 << 64) - 1:
        raise ApiError(
            400, "INVALID_CAPABILITIES",
            "Capability mask exceeds u64",
        )

    return mask


def paged_collection(items, key, query, scope):
    try:
        return cursor_pagination.paginate(
            items,
            key,
            limit=query.get("limit"),
            cursor=query.get("cursor"),
            scope=scope,
        )
    except cursor_pagination.CursorError as exc:
        raise ApiError(
            exc.status, exc.code, str(exc)
        ) from exc


def arguments(
    raw_query: str,
    allowed: set[str],
) -> dict[str, str]:
    try:
        values = parse_qs(
            raw_query,
            keep_blank_values=True,
            strict_parsing=True,
        )
    except ValueError as exc:
        raise ApiError(
            400, "INVALID_QUERY", "Malformed query string"
        ) from exc

    if (
        set(values) - allowed
        or any(len(items) != 1 for items in values.values())
    ):
        raise ApiError(
            400,
            "INVALID_QUERY",
            "Unexpected or duplicate query parameters",
        )

    return {
        key: entries[0]
        for key, entries in values.items()
    }


def route(url: str, provider) -> tuple[int, dict]:
    if len(url) > 2048:
        raise ApiError(
            414, "URI_TOO_LONG", "Request URI too long"
        )

    parts = urlsplit(url)

    if parts.fragment:
        raise ApiError(
            400, "INVALID_QUERY", "Fragments not allowed"
        )

    pieces = [
        piece for piece in parts.path.split("/")
        if piece
    ]

    if pieces == ["openapi.json"]:
        arguments(parts.query, set())
        return 200, openapi_spec.build()

    if pieces == ["health"]:
        arguments(parts.query, set())
        return 200, {
            "status": "ok",
            "service": "aerosettle-marketplace",
            "genesis": provider.health(),
        }

    if len(pieces) < 2 or pieces[0] != "v1":
        raise ApiError(404, "NOT_FOUND", "Unknown route")

    entity = pieces[1]

    if entity not in {
        "agents", "work-orders", "marketplace"
    }:
        raise ApiError(404, "NOT_FOUND", "Unknown resource")

    allowed = (
        {
            "status", "discoverable",
            "required_capabilities_all",
            "limit", "cursor",
        }
        if entity == "work-orders" and len(pieces) == 2
        else set()
    )

    if entity == "agents" and len(pieces) == 2:
        allowed = {
            "status", "active",
            "capabilities_all",
            "limit", "cursor",
        }

    query = arguments(parts.query, allowed)

    if (
        entity == "marketplace" and len(pieces) != 2
    ) or len(pieces) > 4:
        raise ApiError(404, "NOT_FOUND", "Unknown route")

    if len(pieces) == 4 and not (
        entity == "work-orders"
        and pieces[3] == "matches"
    ):
        raise ApiError(404, "NOT_FOUND", "Unknown route")

    if len(pieces) >= 3:
        require_pubkey(pieces[2])

    snapshot = provider.snapshot()
    meta = metadata(snapshot)

    if entity == "marketplace":
        if (
            len(snapshot["agents"])
            + len(snapshot["work_orders"])
            > 200
        ):
            raise ApiError(
                413,
                "RESULT_TOO_LARGE",
                "Use paginated collection endpoints",
            )

        return 200, {
            "data": {
                "protocol_config": snapshot["protocol_config"],
                "paused": snapshot["protocol_paused"],
                "agents": [
                    projected_agent(a)
                    for a in snapshot["agents"]
                ],
                "work_orders": [
                    projected_order(o, snapshot)
                    for o in snapshot["work_orders"]
                ],
                "eligible_agents_by_order": {
                    order["work_order_account"]: [
                        agent["agent_account"]
                        for agent in decision_set(
                            order, snapshot, provider.match
                        )["eligible_agents"]
                    ]
                    for order in snapshot["work_orders"]
                    if discoverable(order, snapshot)
                },
            },
            "meta": meta,
        }

    if entity == "agents":
        if len(pieces) == 2:
            status = query.get("status")

            valid = {
                "Active", "OwnerSuspended",
                "AdminSuspended", "Revoked",
            }

            if status is not None and status not in valid:
                raise ApiError(
                    400, "INVALID_STATUS", "Unknown agent status"
                )

            active = query.get("active")

            if active not in (None, "true", "false"):
                raise ApiError(
                    400,
                    "INVALID_QUERY",
                    "active must be true or false",
                )

            mask = capability_mask(
                query.get("capabilities_all")
            )

            agents = [
                projected_agent(a)
                for a in snapshot["agents"]
                if (
                    status is None
                    or a["status"] == status
                )
                and (
                    active is None
                    or a["active"] == (active == "true")
                )
                and (
                    mask is None
                    or (int(a["capabilities"]) & mask) == mask
                )
            ]

            result = paged_collection(
                agents,
                "agent_account",
                query,
                {
                    "endpoint": "agents",
                    "status": status,
                    "active": active,
                    "capabilities_all": mask,
                },
            )

            return 200, {
                **result,
                "meta": meta,
            }

        agent = next(
            (
                a for a in snapshot["agents"]
                if a["agent_account"] == pieces[2]
            ),
            None,
        )

        if agent is None:
            raise ApiError(
                404,
                "AGENT_NOT_FOUND",
                "Agent not registered in current snapshot",
            )

        return 200, {
            "data": projected_agent(agent),
            "meta": meta,
        }

    if len(pieces) == 2:
        status = query.get("status")

        if status is not None and status not in STATUSES:
            raise ApiError(
                400,
                "INVALID_STATUS",
                "Unknown work-order status",
            )

        available = query.get("discoverable")

        if available is not None and available not in (
            "true", "false"
        ):
            raise ApiError(
                400,
                "INVALID_QUERY",
                "discoverable must be true or false",
            )

        required_mask = capability_mask(
            query.get("required_capabilities_all")
        )

        orders = [
            projected_order(o, snapshot)
            for o in snapshot["work_orders"]
            if (
                status is None or o["status"] == status
            )
            and (
                available is None
                or discoverable(o, snapshot)
                == (available == "true")
            )
            and (
                required_mask is None
                or (
                    int(o["required_capabilities"])
                    & required_mask
                ) == required_mask
            )
        ]

        result = paged_collection(
            orders,
            "work_order_account",
            query,
            {
                "endpoint": "work-orders",
                "status": status,
                "discoverable": available,
                "required_capabilities_all": required_mask,
            },
        )

        return 200, {
            **result,
            "meta": meta,
        }

    order = next(
        (
            o for o in snapshot["work_orders"]
            if o["work_order_account"] == pieces[2]
        ),
        None,
    )

    if order is None:
        raise ApiError(
            404,
            "WORK_ORDER_NOT_FOUND",
            "WorkOrder not registered in current snapshot",
        )

    if len(pieces) == 3:
        return 200, {
            "data": projected_order(order, snapshot),
            "meta": meta,
        }

    return 200, {
        "data": {
            "work_order": projected_order(order, snapshot),
            **decision_set(order, snapshot, provider.match),
        },
        "meta": meta,
    }


class LiveProvider:
    def __init__(
        self,
        rpc_url: str,
        idl_path: Path,
        commitment: str,
        expected_genesis: str,
    ):
        self.rpc = discovery.Rpc(rpc_url, timeout=10)

        self.idl = discovery.Idl(
            json.loads(idl_path.read_text())
        )

        self.idl.validate_marketplace_contract()

        if self.idl.address != PROGRAM_ID:
            raise ApiError(
                503, "WRONG_PROGRAM", "IDL program ID mismatch"
            )

        self.commitment = commitment
        self.expected_genesis = expected_genesis
        self.matcher = rust_matching.RustMatcher(
            ROOT / "target/debug/examples/marketplace_match_bridge"
        )
        if not self.matcher.executable.is_file():
            raise ApiError(
                503, "RUST_MATCHER_MISSING",
                "Build the Rust matching bridge before starting API",
            )

    def match(self, order, snapshot):
        return self.matcher(order, snapshot)

    def health(self) -> str:
        observed = self.rpc.call(
            "getGenesisHash", []
        )

        if observed != self.expected_genesis:
            raise ApiError(
                503,
                "WRONG_GENESIS",
                "RPC is not the expected localnet ledger",
            )

        return observed

    def snapshot(self) -> dict:
        self.health()

        return discovery.discover(
            self.rpc,
            self.idl,
            self.commitment,
        )


def handler_for(provider):
    class Handler(BaseHTTPRequestHandler):
        def respond(
            self,
            status: int,
            content: dict,
            extra: dict | None = None,
        ):
            raw = json.dumps(
                content,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")

            self.send_response(status)

            self.send_header(
                "Content-Type",
                "application/json; charset=utf-8",
            )
            self.send_header(
                "Content-Length", str(len(raw))
            )
            self.send_header(
                "Cache-Control", "no-store"
            )
            self.send_header(
                "X-Content-Type-Options", "nosniff"
            )

            if extra:
                for name, value in extra.items():
                    self.send_header(name, value)

            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            try:
                status, body = route(
                    self.path, provider
                )
                self.respond(status, body)

            except ApiError as exc:
                self.respond(
                    exc.status,
                    {
                        "error": {
                            "code": exc.code,
                            "message": str(exc),
                        }
                    },
                )

            except (
                rust_matching.RustMatchingError,
                discovery.DiscoveryError,
                OSError,
                ValueError,
                KeyError,
                TypeError,
                IndexError,
            ) as exc:
                print(
                    f"Marketplace upstream error: {exc}",
                    file=sys.stderr,
                )

                self.respond(
                    502,
                    {
                        "error": {
                            "code": "UPSTREAM_ERROR",
                            "message":
                                "RPC or account validation failed",
                        }
                    },
                )

        def unsupported(self):
            self.respond(
                405,
                {
                    "error": {
                        "code": "METHOD_NOT_ALLOWED",
                        "message": "Read-only: GET only",
                    }
                },
                {"Allow": "GET"},
            )

        do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = unsupported

        def log_message(self, fmt, *args):
            print(
                "marketplace-api:",
                fmt % args,
                file=sys.stderr,
            )

    return Handler


def main():
    parser = argparse.ArgumentParser(
        description=__doc__
    )

    parser.add_argument(
        "--rpc-url",
        default="http://127.0.0.1:8899",
    )
    parser.add_argument(
        "--idl",
        type=Path,
        default=ROOT / "target/idl/aerosettle.discovery.json",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8787,
    )
    parser.add_argument(
        "--commitment",
        choices=["confirmed", "finalized"],
        default="confirmed",
    )
    parser.add_argument(
        "--genesis",
        default=GENESIS,
    )

    args = parser.parse_args()

    if not 1 <= args.port <= 65535:
        parser.error("port must be 1..65535")

    provider = LiveProvider(
        args.rpc_url,
        args.idl,
        args.commitment,
        args.genesis,
    )

    provider.health()

    server = ThreadingHTTPServer(
        ("127.0.0.1", args.port),
        handler_for(provider),
    )

    print(
        "AeroSettle Marketplace API: "
        f"http://127.0.0.1:{args.port} (GET only)",
        flush=True,
    )

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nAPI stopped", flush=True)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
