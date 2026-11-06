"""Reduce untrusted tool output to inert metadata before planner revision."""
from __future__ import annotations

import json
import re
from typing import Any

from .models import RuntimeDenied, canonical


INJECTION = re.compile(r"(?i)(ignore (all |the )?(previous|prior) instructions|wallet_sign|"
                       r"export.private.key|send.payment|change.the.policy|seed.phrase)")


def summarize(value: Any, seal) -> dict:
    raw = canonical(value)
    if len(raw) > 8192:
        raise RuntimeDenied("OBSERVATION_TOO_LARGE")
    text = raw.decode("utf-8")
    return {"observation_hash": seal(value),
            "injection_detected": bool(INJECTION.search(text)),
            "evidence_source": value.get("evidence_source", "UNVERIFIED")
            if isinstance(value, dict) else "UNVERIFIED"}
