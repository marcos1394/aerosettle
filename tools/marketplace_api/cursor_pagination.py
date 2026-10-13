"""Stable, bounded cursor pagination for read-only API responses."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets

_SECRET = secrets.token_bytes(32)

DEFAULT_LIMIT = 50
MAX_LIMIT = 100
MAX_CURSOR_LENGTH = 2048


class CursorError(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status = status
        self.code = code


def canonical(value):
    return json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def encode(value):
    payload = base64.urlsafe_b64encode(
        canonical(value)
    ).decode("ascii").rstrip("=")

    signature = hmac.new(
        _SECRET,
        payload.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()

    return payload + "." + signature


def decode(token):
    if (
        not isinstance(token, str)
        or not token
        or len(token) > MAX_CURSOR_LENGTH
        or not re.fullmatch(
            r"[A-Za-z0-9_-]+\.[a-f0-9]{64}",
            token,
        )
    ):
        raise CursorError(
            400, "INVALID_CURSOR", "Malformed cursor"
        )

    payload, signature = token.split(".", 1)

    expected = hmac.new(
        _SECRET,
        payload.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(signature, expected):
        raise CursorError(
            400,
            "INVALID_CURSOR",
            "Invalid cursor signature",
        )

    try:
        raw = base64.b64decode(
            payload + "=" * (-len(payload) % 4),
            altchars=b"-_",
            validate=True,
        )

        value = json.loads(raw)

    except (ValueError, UnicodeError) as exc:
        raise CursorError(
            400, "INVALID_CURSOR", "Invalid cursor payload"
        ) from exc

    if (
        not isinstance(value, dict)
        or set(value) != {"v", "scope", "fingerprint", "after"}
        or type(value["v"]) is not int
        or value["v"] != 1
        or not isinstance(value["scope"], str)
        or not isinstance(value["fingerprint"], str)
        or not isinstance(value["after"], str)
    ):
        raise CursorError(
            400, "INVALID_CURSOR", "Invalid cursor structure"
        )

    return value


def parse_limit(value):
    if value is None:
        return DEFAULT_LIMIT

    if (
        not isinstance(value, str)
        or not re.fullmatch(r"[1-9][0-9]*", value)
        or len(value) > 3
    ):
        raise CursorError(
            400, "INVALID_LIMIT", "Invalid page limit"
        )

    result = int(value)

    if result > MAX_LIMIT:
        raise CursorError(
            400,
            "INVALID_LIMIT",
            f"limit must be between 1 and {MAX_LIMIT}",
        )

    return result


def paginate(items, key, *, limit=None, cursor=None, scope=None):
    page_limit = parse_limit(limit)
    records = sorted(items, key=lambda item: item[key])

    identifiers = [item[key] for item in records]

    if (
        any(
            not isinstance(identifier, str)
            or not identifier
            for identifier in identifiers
        )
        or len(set(identifiers)) != len(identifiers)
    ):
        raise CursorError(
            502,
            "INVALID_COLLECTION",
            "Duplicate or invalid account identifiers",
        )

    scope_digest = digest(scope)
    fingerprint = digest(records)
    start = 0

    if cursor is not None:
        saved = decode(cursor)

        if saved["scope"] != scope_digest:
            raise CursorError(
                400,
                "CURSOR_SCOPE_MISMATCH",
                "Cursor belongs to another query",
            )

        if saved["fingerprint"] != fingerprint:
            raise CursorError(
                409,
                "STALE_CURSOR",
                "Results changed; restart from page one",
            )

        try:
            start = identifiers.index(saved["after"]) + 1
        except ValueError as exc:
            raise CursorError(
                409,
                "STALE_CURSOR",
                "Cursor position no longer exists",
            ) from exc

    page = records[start:start + page_limit]
    has_more = start + len(page) < len(records)

    next_cursor = None

    if has_more and page:
        next_cursor = encode({
            "v": 1,
            "scope": scope_digest,
            "fingerprint": fingerprint,
            "after": page[-1][key],
        })

    return {
        "data": page,
        "count": len(page),
        "total_count": len(records),
        "page": {
            "limit": page_limit,
            "has_more": has_more,
            "next_cursor": next_cursor,
        },
    }
