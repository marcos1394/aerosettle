"""A2A 1.0 Message envelope for offline negotiation payloads.

This is not the CON-39 read-only card binding or a public task endpoint.
The signed payload is checked by NegotiationService after decoding.
"""
from __future__ import annotations

import json
from a2a.types import Message, Role
from .canonical import canonical
from .models import NegotiationError, validate

MEDIA_TYPE = "application/vnd.conatus.negotiation.v1+json"


def encode(message: dict) -> Message:
    validate(message)
    role = Role.ROLE_USER if message["type"] in {"RFQ", "AcceptIntent", "RejectIntent"} else Role.ROLE_AGENT
    envelope = Message(message_id=message["message_id"], role=role)
    envelope.parts.add(raw=canonical(message), media_type=MEDIA_TYPE)
    return envelope


def decode(envelope: Message) -> dict:
    if len(envelope.parts) != 1 or envelope.parts[0].WhichOneof("content") != "raw" or (
            envelope.parts[0].media_type != MEDIA_TYPE):
        raise NegotiationError("INVALID_A2A_ENVELOPE")
    raw = bytes(envelope.parts[0].raw)
    if len(raw) > 8192:
        raise NegotiationError("MESSAGE_TOO_LARGE")
    try:
        message = json.loads(raw)
    except (UnicodeError, ValueError, TypeError) as exc:
        raise NegotiationError("INVALID_A2A_ENVELOPE") from exc
    validate(message)
    if raw != canonical(message) or envelope.message_id != message["message_id"] or (
            envelope.role != (Role.ROLE_USER if message["type"] in
                {"RFQ", "AcceptIntent", "RejectIntent"} else Role.ROLE_AGENT)):
        raise NegotiationError("INVALID_A2A_ENVELOPE")
    return message
