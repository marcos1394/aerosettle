"""Small, strictly validated values crossing the planner/runtime boundary."""
from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any


class RuntimeDenied(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


STATES = frozenset({"CREATED", "PLANNING", "POLICY_CHECK", "EXECUTING_TOOL",
                    "OBSERVING", "AWAITING_APPROVAL", "COMPLETED", "DENIED",
                    "FAILED", "CANCELED"})
TRANSITIONS = {
    "CREATED": {"PLANNING", "DENIED", "CANCELED"},
    "PLANNING": {"POLICY_CHECK", "DENIED", "FAILED", "CANCELED"},
    "POLICY_CHECK": {"EXECUTING_TOOL", "AWAITING_APPROVAL", "COMPLETED", "DENIED", "FAILED", "CANCELED"},
    "EXECUTING_TOOL": {"OBSERVING", "FAILED", "DENIED", "CANCELED"},
    "OBSERVING": {"POLICY_CHECK", "DENIED", "FAILED", "CANCELED"},
    "AWAITING_APPROVAL": {"CANCELED"},
    "COMPLETED": set(), "DENIED": set(), "FAILED": set(), "CANCELED": set(),
}
FORBIDDEN = frozenset({"wallet_sign", "transfer", "fund_workorder", "claim_workorder",
                       "verify_workorder", "settle_workorder", "refund", "change_beneficiary",
                       "change_budget_policy", "upgrade_program", "export_private_key"})
SECRET_PATTERN = re.compile(r"(?i)(private.?key|seed.?phrase|mnemonic|bearer\s+|api.?key|secret.?token)")
SAFE_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")


def canonical(value: Any) -> bytes:
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    except (TypeError, ValueError) as exc:
        raise RuntimeDenied("INVALID_JSON") from exc
    if len(raw) > 8192:
        raise RuntimeDenied("PAYLOAD_TOO_LARGE")
    return raw


def safe_text(value: str, *, maximum: int = 500) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= maximum or SECRET_PATTERN.search(value):
        raise RuntimeDenied("UNSAFE_INPUT")
    return value


@dataclass(frozen=True)
class Step:
    tool_id: str
    arguments: dict[str, Any]

    @classmethod
    def parse(cls, value: Any) -> "Step":
        if not isinstance(value, dict) or set(value) != {"tool_id", "arguments"}:
            raise RuntimeDenied("INVALID_PLAN")
        tool, args = value["tool_id"], value["arguments"]
        if not isinstance(tool, str) or not SAFE_ID.fullmatch(tool) or not isinstance(args, dict):
            raise RuntimeDenied("INVALID_PLAN")
        canonical(args)
        if SECRET_PATTERN.search(canonical(args).decode("utf-8")):
            raise RuntimeDenied("UNSAFE_INPUT")
        return cls(tool, args)


def validate_plan(raw: Any, *, max_steps: int) -> tuple[Step, ...]:
    if not isinstance(raw, list) or not 1 <= len(raw) <= max_steps:
        raise RuntimeDenied("INVALID_PLAN")
    steps = tuple(Step.parse(item) for item in raw)
    if len(steps) != len(raw):
        raise RuntimeDenied("INVALID_PLAN")
    return steps
