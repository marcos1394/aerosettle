"""Official MCP client against a local, stateless Streamable HTTP ASGI server."""
from __future__ import annotations

import asyncio
import base64
from contextlib import asynccontextmanager
import json
from pathlib import Path
import time
import uuid

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import httpx2
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

from .backend import FixtureBackend
from .security import AuthBoundary, TokenVerifier
from .server import MCPReadService, TOOLS

URL = "http://127.0.0.1:8090/mcp"
ISSUER = "https://fixture-issuer.invalid"
FIXTURE = Path(__file__).parent / "fixtures/offline.json"


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def issue_test_token(key: Ed25519PrivateKey, *, subject="alice", client="test-client",
                     tenant="tenant-a", org="org-a", scopes=("workorders:read", "evidence:read"),
                     audience=URL, expires=None) -> str:
    now = int(time.time())
    header = _b64(b'{"alg":"EdDSA","typ":"JWT"}')
    claims = {"iss": ISSUER, "aud": audience, "resource": audience,
              "sub": subject, "client_id": client, "tenant_id": tenant,
              "organization_id": org, "scope": list(scopes),
              "iat": now - 1, "exp": expires or now + 300, "jti": uuid.uuid4().hex}
    payload = _b64(json.dumps(claims, sort_keys=True, separators=(",", ":")).encode())
    signing = f"{header}.{payload}".encode()
    return f"{header}.{payload}.{_b64(key.sign(signing))}"


@asynccontextmanager
async def client(app, token: str | None = None):
    headers = {"Authorization": "Bearer " + token} if token else {}
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app),
                                  base_url="http://127.0.0.1:8090", headers=headers) as http:
        async with streamable_http_client(URL, http_client=http) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                discovered = await session.discover()
                assert "2026-07-28" in discovered.supported_versions
                yield session


async def run_demo() -> dict:
    key = Ed25519PrivateKey.generate()
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    verifier = TokenVerifier(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw),
                             issuer=ISSUER, audience=URL)
    service = MCPReadService(FixtureBackend(FIXTURE))
    inner = service.mcp.streamable_http_app(stateless_http=True,
                         json_response=True, max_request_body_size=65536)
    app = AuthBoundary(inner,
                       verifier, hosts=frozenset({"127.0.0.1:8090"}))
    async with inner.router.lifespan_context(inner):
        return await _exercise(app, key)


async def _exercise(app, key) -> dict:
    async with client(app) as session:
        listing = await session.list_tools()
        names = {tool.name for tool in listing.tools}
        assert names == TOOLS
        assert all(tool.input_schema.get("type") == "object" for tool in listing.tools)
        public = await session.call_tool("conatus_get_protocol_status")
        assert public.structured_content["evidence_source"] == "OFFLINE_FIXTURE"
        no_token = await session.call_tool("conatus_get_workorder",
                                            {"work_order_pda": "OrderFixtureA1"})
        assert no_token.is_error and "INSUFFICIENT_SCOPE" in str(no_token.content)
        nonexistent = await session.call_tool("wallet_sign", {})
        assert nonexistent.is_error
    token = issue_test_token(key)
    async with client(app, token) as session:
        first = await session.call_tool("conatus_search_workorders", {"limit": 1})
        assert first.structured_content["items"][0]["work_order_pda"] == "OrderFixtureA1"
        cursor = first.structured_content["next_cursor"]
        second = await session.call_tool("conatus_search_workorders",
                                         {"limit": 1, "cursor": cursor})
        assert second.structured_content["items"][0]["work_order_pda"] == "OrderFixtureA2"
        allowed = await session.call_tool("conatus_get_workorder",
                                          {"work_order_pda": "OrderFixtureA1"})
        assert allowed.structured_content["data"]["status"] == "Open"
        cross = await session.call_tool("conatus_get_workorder",
                                        {"work_order_pda": "OrderFixtureB1"})
        assert cross.is_error and "RESOURCE_NOT_FOUND" in str(cross.content)
    scoped = issue_test_token(key, scopes=("workorders:read",))
    async with client(app, scoped) as session:
        forbidden = await session.call_tool("conatus_get_settlement_evidence",
                                            {"work_order_pda": "OrderFixtureA2"})
        assert forbidden.is_error and "INSUFFICIENT_SCOPE" in str(forbidden.content)
    return {"MCP_PROTOCOL_VERIFIED": True, "AUTHORIZATION_VERIFIED": True,
            "OFFLINE_FIXTURE": True, "LIVE_DEVNET_READ_ONLY": False,
            "tool_count": len(names), "pagination": True,
            "cross_tenant_denied": True, "financial_tools_absent": True}


if __name__ == "__main__":
    print(json.dumps(asyncio.run(run_demo()), sort_keys=True))
