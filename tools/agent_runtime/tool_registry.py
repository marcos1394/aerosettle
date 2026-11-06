"""Explicit read-only tool allowlist and narrow MCP/A2A adapters."""
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Awaitable, Callable

from tools.mcp.security import CURRENT, Principal
from .models import FORBIDDEN, RuntimeDenied, canonical


Handler = Callable[[dict[str, Any], Principal], Awaitable[dict[str, Any]]]
RISK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}


@dataclass(frozen=True)
class ToolSpec:
    tool_id: str
    name: str
    description: str
    provider: str
    protocol: str
    required_scopes: frozenset[str]
    risk_level: str
    read_only: bool
    allowed_agent_types: frozenset[str]
    timeout_ms: int
    max_calls: int
    input_schema: dict[str, type]
    output_schema: dict[str, type]

    def __post_init__(self):
        if (self.tool_id in FORBIDDEN or not self.read_only or
                self.risk_level not in RISK or not 1 <= self.timeout_ms <= 10000 or
                not 1 <= self.max_calls <= 100):
            raise RuntimeDenied("FORBIDDEN_TOOL")

    def check_input(self, value: dict) -> None:
        if not isinstance(value, dict) or set(value) != set(self.input_schema):
            raise RuntimeDenied("INVALID_TOOL_ARGUMENTS")
        for key, typ in self.input_schema.items():
            item = value[key]
            if type(item) is not typ or (typ is str and (len(item) > 128 or
                        "://" in item or item.startswith(("/", "~")))):
                raise RuntimeDenied("INVALID_TOOL_ARGUMENTS")
        canonical(value)

    def check_output(self, value: Any) -> dict:
        if not isinstance(value, dict) or any(k not in value or type(value[k]) is not typ
                                                for k, typ in self.output_schema.items()):
            raise RuntimeDenied("INVALID_TOOL_OUTPUT")
        if len(canonical(value)) > 8192:
            raise RuntimeDenied("INVALID_TOOL_OUTPUT")
        return value


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, tuple[ToolSpec, Handler]] = {}

    def register(self, spec: ToolSpec, handler: Handler) -> None:
        if spec.tool_id in self._tools or spec.tool_id in FORBIDDEN:
            raise RuntimeDenied("FORBIDDEN_TOOL")
        self._tools[spec.tool_id] = (spec, handler)

    def get(self, tool_id: str) -> tuple[ToolSpec, Handler]:
        if tool_id not in self._tools or tool_id in FORBIDDEN:
            raise RuntimeDenied("UNREGISTERED_TOOL")
        return self._tools[tool_id]

    def discover(self) -> tuple[str, ...]:
        return tuple(sorted(self._tools))


def mcp_registry(service, *, offline_quotes: dict[str, int] | None = None) -> ToolRegistry:
    """Call the actual CON-40 MCP handlers with the current verified principal."""
    registry = ToolRegistry()
    definitions = (
        ("conatus_search_agents", {}, {"query": str}, {"items": list}),
        ("conatus_get_agent", {}, {"agent_account": str}, {"data": dict}),
        ("conatus_get_agent_card", {}, {"card_id": str}, {"data": dict}),
        ("conatus_get_protocol_status", {}, {}, {"data": dict}),
        ("conatus_search_workorders", {"workorders:read"}, {"status": str}, {"items": list}),
        ("conatus_get_workorder", {"workorders:read"}, {"work_order_pda": str}, {"data": dict}),
        ("conatus_get_settlement_evidence", {"evidence:read"},
         {"work_order_pda": str}, {"data": dict}),
    )
    for name, scopes, inputs, outputs in definitions:
        async def invoke(args: dict, principal: Principal, tool=name) -> dict:
            marker = CURRENT.set(principal)
            try:
                try:
                    result = await service.mcp.call_tool(tool, args)
                except Exception as exc:
                    raise RuntimeDenied("TOOL_UNAVAILABLE") from exc
                if result.is_error or result.structured_content is None:
                    raise RuntimeDenied("TOOL_UNAVAILABLE")
                return result.structured_content
            finally:
                CURRENT.reset(marker)
        registry.register(ToolSpec(name, name, "CON-40 read-only tool", "conatus-mcp",
                                   "MCP", frozenset(scopes), "LOW", True,
                                   frozenset({"ANALYST"}), 3000, 4, inputs, outputs), invoke)
    quotes = dict(offline_quotes or {})
    async def quote(args: dict, principal: Principal) -> dict:
        amount = quotes.get(args["card_id"])
        if amount is None or type(amount) is not int or amount <= 0:
            raise RuntimeDenied("QUOTE_UNAVAILABLE")
        return {"card_id": args["card_id"], "service": args["service"],
                "estimated_base_units_str": str(amount), "evidence_source": "OFFLINE_FIXTURE",
                "is_reservation": False, "is_financial_authority": False}
    registry.register(ToolSpec("quote_task", "Quote task", "Informational offline estimate",
                               "conatus-a2a", "LOCAL_READ_ONLY", frozenset(), "LOW", True,
                               frozenset({"ANALYST"}), 1000, 2,
                               {"card_id": str, "service": str},
                               {"estimated_base_units_str": str, "evidence_source": str,
                                "is_reservation": bool, "is_financial_authority": bool}), quote)
    return registry
