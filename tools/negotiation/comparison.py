"""Deterministic hard constraints, then price/deadline ranking."""
from __future__ import annotations

from .models import NegotiationError


def compare(offers: list[dict], *, budget: int, quantity: int, sla: str,
            deadline: int, now: int) -> list[dict]:
    ranked = []
    for offer in offers:
        reasons = []
        if offer["expires_at"] <= now: reasons.append("EXPIRED")
        if offer["quantity"] != quantity: reasons.append("QUANTITY_MISMATCH")
        if offer["sla"] != sla: reasons.append("SLA_MISMATCH")
        if offer["delivery_deadline"] > deadline: reasons.append("DELIVERY_LATE")
        if int(offer["amount_base_units_str"]) > budget: reasons.append("OVER_BUDGET")
        ranked.append({"message_id": offer["message_id"], "eligible": not reasons,
                       "reason_codes": reasons,
                       "amount_base_units_str": offer["amount_base_units_str"],
                       "delivery_deadline": offer["delivery_deadline"],
                       "provider_agent_account": offer["provider_agent_account"]})
    return sorted(ranked, key=lambda item: (
        not item["eligible"], int(item["amount_base_units_str"]),
        item["delivery_deadline"], item["provider_agent_account"], item["message_id"]))


def require_eligible(rows: list[dict], selected_id: str) -> None:
    selected = next((row for row in rows if row["message_id"] == selected_id), None)
    if selected is None or not selected["eligible"]:
        raise NegotiationError("OFFER_INELIGIBLE")
