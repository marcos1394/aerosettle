"""Allowlisted JSON logs; free-form RPC bodies, URLs and secrets are never accepted."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
import sys
import uuid

SAFE = re.compile(r"^[A-Za-z0-9_:/.*-]{1,180}$")
FIELDS = {"component", "operation", "correlation_id", "trace_id", "network",
          "genesis_hash", "program_id", "work_order_pda", "transaction_signature",
          "checkpoint_id", "error_code", "status"}


def correlation_id(scope: str, signature: str | None = None) -> str:
    return hashlib.sha256(f"{scope}|{signature or ''}".encode()).hexdigest()[:32]


def new_trace_id() -> str:
    return uuid.uuid4().hex


def structured_event(severity: str, component: str, operation: str,
                     **fields) -> dict:
    if severity not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise ValueError("Invalid log severity")
    values = {"component": component, "operation": operation, **fields}
    if any(key not in FIELDS | {"slot", "duration_ms"} for key in values):
        raise ValueError("Unsupported log field")
    for key, value in values.items():
        if value is None:
            continue
        if key == "slot":
            if type(value) is not int or value < 0:
                raise ValueError("Invalid log slot")
        elif key == "duration_ms":
            if not isinstance(value, (int, float)) or value < 0:
                raise ValueError("Invalid log duration")
        elif not isinstance(value, str) or not SAFE.fullmatch(value):
            raise ValueError("Unsafe log value rejected")
    return {"timestamp": datetime.now(timezone.utc).isoformat(),
            "severity": severity, **{key: value for key, value in values.items()
                                    if value is not None}}


def emit(severity: str, component: str, operation: str, **fields) -> dict:
    event = structured_event(severity, component, operation, **fields)
    print(json.dumps(event, sort_keys=True), file=sys.stderr, flush=True)
    return event
