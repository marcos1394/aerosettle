"""Per-request authorization for the read-only MCP surface.

Tokens are Ed25519-signed JWT access tokens from a separately configured issuer.
This module never issues tokens or derives scopes from Agent Cards.
"""
from __future__ import annotations

import base64
from contextvars import ContextVar
from dataclasses import dataclass
import json
import re
import threading
import time
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


class Denied(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class Principal:
    subject: str
    client_id: str
    issuer: str
    audience: str
    scopes: frozenset[str]
    resource: str
    organization_id: str
    tenant_id: str
    expires_at: int
    token_id: str


ANONYMOUS = Principal("", "anonymous", "", "", frozenset(), "", "", "", 0, "")
CURRENT: ContextVar[Principal] = ContextVar("con40_principal", default=ANONYMOUS)
CLIENT_IP: ContextVar[str] = ContextVar("con40_ip", default="local")


def _decode(value: str) -> bytes:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", value) or len(value) > 8192:
        raise Denied("INVALID_TOKEN")
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, base64.binascii.Error) as exc:
        raise Denied("INVALID_TOKEN") from exc


class TokenVerifier:
    def __init__(self, public_key: bytes, *, issuer: str, audience: str,
                 revoked: set[str] | None = None, max_lifetime: int = 900):
        self.key = Ed25519PublicKey.from_public_bytes(public_key)
        self.issuer, self.audience = issuer, audience
        self.revoked = revoked if revoked is not None else set()
        self.max_lifetime = max_lifetime

    def verify(self, token: str, *, now: int | None = None) -> Principal:
        try:
            parts = token.split(".")
            if len(parts) != 3 or len(token) > 8192:
                raise Denied("INVALID_TOKEN")
            header = json.loads(_decode(parts[0]))
            claims = json.loads(_decode(parts[1]))
            if header != {"alg": "EdDSA", "typ": "JWT"} or not isinstance(claims, dict):
                raise Denied("INVALID_TOKEN")
            self.key.verify(_decode(parts[2]), f"{parts[0]}.{parts[1]}".encode())
            issued, expires = claims["iat"], claims["exp"]
            stamp = int(time.time()) if now is None else now
            if (type(issued) is not int or type(expires) is not int or
                    issued > stamp + 30 or expires <= stamp or
                    expires <= issued or expires - issued > self.max_lifetime):
                raise Denied("TOKEN_EXPIRED")
            if claims.get("iss") != self.issuer or claims.get("aud") != self.audience or \
                    claims.get("resource") != self.audience:
                raise Denied("WRONG_AUDIENCE")
            names = ("sub", "client_id", "organization_id", "tenant_id", "jti")
            if any(not isinstance(claims.get(name), str) or
                   not re.fullmatch(r"[A-Za-z0-9_.:@-]{1,128}", claims[name])
                   for name in names):
                raise Denied("INVALID_TOKEN")
            scopes = claims.get("scope")
            if not isinstance(scopes, list) or len(scopes) > 16 or \
                    any(not isinstance(scope, str) or not re.fullmatch(r"[a-z:]{1,64}", scope)
                        for scope in scopes):
                raise Denied("INVALID_TOKEN")
            if claims["jti"] in self.revoked:
                raise Denied("TOKEN_REVOKED")
            return Principal(claims["sub"], claims["client_id"], self.issuer,
                             self.audience, frozenset(scopes), claims["resource"],
                             claims["organization_id"], claims["tenant_id"],
                             expires, claims["jti"])
        except (KeyError, ValueError, TypeError, InvalidSignature, UnicodeDecodeError,
                json.JSONDecodeError) as exc:
            raise Denied("INVALID_TOKEN") from exc


def authorize(scope: str, *, tenant_id: str = "", organization_id: str = "",
              owner: str = "", resource: str = "") -> Principal:
    principal = CURRENT.get()
    if principal is ANONYMOUS or scope not in principal.scopes:
        raise Denied("INSUFFICIENT_SCOPE")
    if tenant_id and tenant_id != principal.tenant_id:
        raise Denied("TENANT_MISMATCH")
    if organization_id and organization_id != principal.organization_id:
        raise Denied("ORGANIZATION_MISMATCH")
    if owner and owner != principal.subject:
        raise Denied("OWNER_MISMATCH")
    if resource and resource != principal.resource:
        raise Denied("WRONG_AUDIENCE")
    return principal


class RateLimiter:
    def __init__(self, limit: int = 60, window: int = 60):
        self.limit, self.window = limit, window
        self.lock = threading.Lock()
        self.counts: dict[tuple[str, str, str], tuple[int, int]] = {}

    def check(self, tool: str, resource: str) -> None:
        principal = CURRENT.get()
        identity = principal.client_id if principal is not ANONYMOUS else CLIENT_IP.get()
        resource_key = str(hash(resource))
        keys = ((identity, tool, "*"), (identity, tool, resource_key))
        now = int(time.time())
        with self.lock:
            if len(self.counts) > 10000:
                self.counts = {key: value for key, value in self.counts.items()
                               if now - value[0] < self.window}
            if len(self.counts) > 10000:
                raise Denied("RATE_LIMITED")
            updates = []
            for key in keys:
                start, count = self.counts.get(key, (now, 0))
                if now - start >= self.window:
                    start, count = now, 0
                if count >= self.limit:
                    raise Denied("RATE_LIMITED")
                updates.append((key, (start, count + 1)))
            self.counts.update(updates)


class AuthBoundary:
    """Optional Bearer auth on each stateless Streamable HTTP request."""
    def __init__(self, app: Any, verifier: TokenVerifier, *, hosts: frozenset[str],
                 origins: frozenset[str] = frozenset(), on_transport_error=None):
        self.app, self.verifier = app, verifier
        self.hosts, self.origins = hosts, origins
        self.on_transport_error = on_transport_error

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        async def tracked_send(message):
            if (message["type"] == "http.response.start" and
                    message["status"] >= 400 and self.on_transport_error):
                self.on_transport_error("mcp_transport_errors")
            await send(message)
        pairs = [(k.decode("ascii", "ignore").lower(), v.decode("ascii", "ignore"))
                 for k, v in scope.get("headers", [])]
        if any(sum(1 for key, _ in pairs if key == guarded) > 1
               for guarded in ("host", "origin", "authorization")):
            await self._reject(tracked_send, 403)
            return
        headers = dict(pairs)
        host = headers.get("host", "")
        origin = headers.get("origin")
        if host not in self.hosts or origin and origin not in self.origins:
            await self._reject(tracked_send, 403)
            return
        auth = headers.get("authorization")
        try:
            principal = ANONYMOUS if auth is None else (
                self.verifier.verify(auth[7:]) if auth.startswith("Bearer ")
                else (_ for _ in ()).throw(Denied("INVALID_TOKEN")))
        except Denied:
            await self._reject(tracked_send, 401)
            return
        ctx = CURRENT.set(principal)
        ip = CLIENT_IP.set(str(scope.get("client", ("local",))[0]))
        try:
            await self.app(scope, receive, tracked_send)
        finally:
            CLIENT_IP.reset(ip)
            CURRENT.reset(ctx)

    @staticmethod
    async def _reject(send, status):
        body = b'{"error":"ACCESS_DENIED"}'
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"application/json"),
                                (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})
