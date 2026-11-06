"""Planner output is only a proposal; authorization is exclusively deterministic."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any
from .models import RuntimeDenied, safe_text, validate_plan


class Planner(ABC):
    @abstractmethod
    async def plan(self, goal: str, context: dict, available_tools: tuple[str, ...]) -> list[dict]:
        raise NotImplementedError

    async def revise(self, plan: list[dict], observations: tuple[dict, ...]) -> list[dict]:
        return plan


class DeterministicPlanner(Planner):
    """Offline discovery/quote plan; input context contains public IDs only."""
    async def plan(self, goal: str, context: dict, available_tools: tuple[str, ...]) -> list[dict]:
        safe_text(goal)
        return [
            {"tool_id": "conatus_search_agents", "arguments": {"query": context.get("query", "")}},
            {"tool_id": "conatus_get_agent_card", "arguments": {"card_id": context["card_id"]}},
            {"tool_id": "quote_task", "arguments": {"card_id": context["card_id"],
                                                    "service": "data-analysis"}},
        ]


class LLMPlanner(Planner):
    """Provider-neutral interface. Subclasses provide *data*, never tool authority."""
    @abstractmethod
    async def generate(self, safe_request: dict[str, Any]) -> Any:
        raise NotImplementedError

    async def plan(self, goal: str, context: dict, available_tools: tuple[str, ...]) -> dict:
        safe_text(goal)
        safe_context = {k: v for k, v in context.items() if k in {"query", "card_id"}}
        raw = await self.generate({"goal": goal, "context": safe_context,
                                   "available_tools": available_tools})
        if (not isinstance(raw, dict) or set(raw) != {"steps", "tokens_used"} or
                type(raw["tokens_used"]) is not int or raw["tokens_used"] < 0):
            raise RuntimeDenied("INVALID_PLAN")
        return {"steps": [{"tool_id": s.tool_id, "arguments": s.arguments}
                          for s in validate_plan(raw["steps"], max_steps=20)],
                "tokens_used": raw["tokens_used"]}
