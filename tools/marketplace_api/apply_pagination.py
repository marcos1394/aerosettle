#!/usr/bin/env python3
"""Apply reversible EPIC 3.3.3 API pagination patch."""

from pathlib import Path
import ast

root = Path("tools/marketplace_api")
target = root / "server.py"

backup = Path(
    ".aerosettle-backups/epic-3-3-3/server.py"
)

source = target.read_text()


def replace_once(text, before, after, label):
    count = text.count(before)

    if count != 1:
        raise SystemExit(
            f"Unexpected server.py structure: {label} "
            f"({count} matches). No changes installed."
        )

    return text.replace(before, after, 1)


updated = source

updated = replace_once(
    updated,
    "import rust_matching\n",
    "import rust_matching\n"
    "import cursor_pagination\n"
    "import openapi_spec\n",
    "imports",
)

updated = replace_once(
    updated,
    "def arguments(\n",
    '''def capability_mask(value):
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
''',
    "pagination helpers",
)

updated = replace_once(
    updated,
    '    if pieces == ["health"]:\n',
    '''    if pieces == ["openapi.json"]:
        arguments(parts.query, set())
        return 200, openapi_spec.build()

    if pieces == ["health"]:
''',
    "OpenAPI endpoint",
)

updated = replace_once(
    updated,
    '''        {"status", "discoverable"}
        if entity == "work-orders" and len(pieces) == 2''',
    '''        {
            "status", "discoverable",
            "required_capabilities_all",
            "limit", "cursor",
        }
        if entity == "work-orders" and len(pieces) == 2''',
    "WorkOrder allowed filters",
)

updated = replace_once(
    updated,
    '        allowed = {"status"}\n',
    '''        allowed = {
            "status", "active",
            "capabilities_all",
            "limit", "cursor",
        }
''',
    "Agent allowed filters",
)

updated = replace_once(
    updated,
    '''    if entity == "marketplace":
        return 200, {''',
    '''    if entity == "marketplace":
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

        return 200, {''',
    "Marketplace bounded response",
)

updated = replace_once(
    updated,
    '''            agents = [
                projected_agent(a)
                for a in snapshot["agents"]
                if status is None or a["status"] == status
            ]

            return 200, {
                "data": agents,
                "count": len(agents),
                "meta": meta,
            }''',
    '''            active = query.get("active")

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
            }''',
    "Agents list",
)

updated = replace_once(
    updated,
    '''        orders = [
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
        ]

        return 200, {
            "data": orders,
            "count": len(orders),
            "meta": meta,
        }''',
    '''        required_mask = capability_mask(
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
        }''',
    "WorkOrders list",
)

ast.parse(updated, filename=str(target))

if backup.exists():
    raise SystemExit(
        "Backup already exists. "
        "No file was modified."
    )

backup.parent.mkdir(parents=True, exist_ok=True)

with backup.open("x") as handle:
    handle.write(source)

target.write_text(updated)

print("✅ server.py actualizado")
print("✅ Backup:", backup)
print("✅ Python syntax validated")
print("✅ Rust matcher remains the matching authority")
