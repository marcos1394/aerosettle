"""CON-40 protocol, authorization, tenancy and provenance regression matrix."""
from __future__ import annotations

import asyncio
import base64
from contextlib import asynccontextmanager
import copy
import json
from pathlib import Path
import tempfile
import time
import unittest
import sys

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
import httpx2
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from tools.mcp.backend import FixtureBackend
from tools.mcp.demo_interop import FIXTURE, ISSUER, URL, client, issue_test_token, run_demo
from tools.mcp.security import AuthBoundary, CURRENT, Denied, TokenVerifier
from tools.mcp.server import MCPReadService, TOOLS
from tools.operations.store import OperationalStore


class TokenTests(unittest.TestCase):
    def setUp(self):
        self.key = Ed25519PrivateKey.generate()
        self.verifier = TokenVerifier(self.key.public_key().public_bytes(
            Encoding.Raw, PublicFormat.Raw), issuer=ISSUER, audience=URL)

    def test_valid_and_tampered(self):
        token = issue_test_token(self.key)
        principal = self.verifier.verify(token)
        self.assertEqual((principal.subject, principal.tenant_id, principal.client_id),
                         ("alice", "tenant-a", "test-client"))
        parts = token.split(".")
        parts[2] = ("A" if parts[2][0] != "A" else "B") + parts[2][1:]
        with self.assertRaises(Denied):
            self.verifier.verify(".".join(parts))

    def test_expiry_audience_revocation_and_issuer(self):
        expired = issue_test_token(self.key, expires=int(time.time()) - 1)
        wrong = issue_test_token(self.key, audience="https://other.invalid/mcp")
        for token in (expired, wrong):
            with self.assertRaises(Denied):
                self.verifier.verify(token)
        valid = issue_test_token(self.key)
        self.verifier.revoked.add(self.verifier.verify(valid).token_id)
        with self.assertRaisesRegex(Denied, "TOKEN_REVOKED"):
            self.verifier.verify(valid)
        other_issuer = TokenVerifier(self.key.public_key().public_bytes(
            Encoding.Raw, PublicFormat.Raw), issuer="https://foreign.invalid", audience=URL)
        with self.assertRaises(Denied):
            other_issuer.verify(valid)

    def test_con38_operational_metric_bridge(self):
        with tempfile.TemporaryDirectory() as directory:
            store = OperationalStore(Path(directory) / "operations.sqlite")
            try:
                service = MCPReadService(FixtureBackend(FIXTURE), operational_store=store)
                service._metric("mcp_tool_invocations")
                self.assertEqual(service.metrics_snapshot()["mcp_tool_invocations"], 1)
                self.assertEqual(store.latest("mcp_tool_invocations", "mcp", 0)[0]["value"], 1)
            finally:
                store.close()

    def test_cursor_rejects_noncanonical_base64(self):
        service = MCPReadService(FixtureBackend(FIXTURE), cursor_key=b"test-cursor-key")
        principal = self.verifier.verify(issue_test_token(self.key))
        context = CURRENT.set(principal)
        try:
            rows = [{"id": "one"}, {"id": "two"}]
            for query in ("", "x", "xx"):
                cursor = service._page("conatus_search_workorders", "workorders", rows,
                                       limit=1, cursor=None, query=query,
                                       source="OFFLINE_FIXTURE").next_cursor
                if len(cursor) % 4 in (2, 3):
                    break
            else:
                self.fail("Could not construct a padded cursor")
            alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
            altered = cursor[:-1] + alphabet[alphabet.index(cursor[-1]) ^ 1]
            self.assertEqual(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)),
                             base64.urlsafe_b64decode(altered + "=" * (-len(altered) % 4)))
            with self.assertRaisesRegex(Denied, "INVALID_CURSOR"):
                service._page("conatus_search_workorders", "workorders", rows,
                              limit=1, cursor=altered, query=query,
                              source="OFFLINE_FIXTURE")
        finally:
            CURRENT.reset(context)


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.key = Ed25519PrivateKey.generate()
        self.verifier = TokenVerifier(self.key.public_key().public_bytes(
            Encoding.Raw, PublicFormat.Raw), issuer=ISSUER, audience=URL)
        self.backend = FixtureBackend(FIXTURE)
        self.service = MCPReadService(self.backend, rate_limit=100)
        self.inner = self.service.mcp.streamable_http_app(stateless_http=True,
                          json_response=True, max_request_body_size=65536)
        self.app = AuthBoundary(self.inner, self.verifier,
                                hosts=frozenset({"127.0.0.1:8090"}),
                                on_transport_error=self.service._metric)
    @asynccontextmanager
    async def open(self, token=None):
        inner = self.service.mcp.streamable_http_app(stateless_http=True,
                  json_response=True, max_request_body_size=65536)
        app = AuthBoundary(inner, self.verifier,
                           hosts=frozenset({"127.0.0.1:8090"}),
                           on_transport_error=self.service._metric)
        async with inner.router.lifespan_context(inner):
            async with client(app, token) as session:
                yield session

    async def test_official_client_demo_and_schemas(self):
        result = await run_demo()
        self.assertTrue(result["MCP_PROTOCOL_VERIFIED"])
        async with self.open() as session:
            listing = await session.list_tools()
            self.assertEqual({t.name for t in listing.tools}, TOOLS)
            self.assertTrue(all(t.input_schema["type"] == "object" and
                                t.output_schema["type"] == "object"
                                for t in listing.tools))
            self.assertTrue(all(t.annotations.read_only_hint for t in listing.tools))

    async def test_public_private_and_financial_allowlist(self):
        async with self.open() as session:
            public = await session.call_tool("conatus_search_agents", {"limit": 1})
            self.assertFalse(public.is_error)
            self.assertEqual(public.structured_content["evidence_source"], "OFFLINE_FIXTURE")
            private = await session.call_tool("conatus_search_workorders")
            self.assertTrue(private.is_error)
            for forbidden in ("wallet_sign", "transfer", "settle_workorder",
                              "fund_workorder", "claim_workorder", "change_beneficiary",
                              "upgrade_program", "change_policy", "export_private_key"):
                self.assertTrue((await session.call_tool(forbidden, {})).is_error)
        self.assertGreaterEqual(self.service.metrics_snapshot().get("mcp_unknown_tool_attempts", 0), 1)

    async def test_scope_tenant_org_owner_and_resource(self):
        for kwargs, expected in (
            ({"scopes": ()}, "INSUFFICIENT_SCOPE"),
            ({"tenant": "tenant-b"}, "RESOURCE_NOT_FOUND"),
            ({"org": "org-b"}, "RESOURCE_NOT_FOUND"),
            ({"subject": "bob"}, "RESOURCE_NOT_FOUND"),
        ):
            async with self.open(issue_test_token(self.key, **kwargs)) as session:
                result = await session.call_tool("conatus_get_workorder",
                                                 {"work_order_pda": "OrderFixtureA1"})
                self.assertTrue(result.is_error)
                self.assertIn(expected, str(result.content))
        async with self.open(issue_test_token(self.key)) as session:
            result = await session.call_tool("conatus_get_workorder",
                                             {"work_order_pda": "OrderFixtureB1"})
            self.assertIn("RESOURCE_NOT_FOUND", str(result.content))
        self.assertGreaterEqual(self.service.metrics_snapshot().get("mcp_cross_tenant_blocked", 0), 1)

    async def test_cursor_bound_to_principal_and_query(self):
        async with self.open(issue_test_token(self.key)) as session:
            first = await session.call_tool("conatus_search_workorders", {"limit": 1})
            cursor = first.structured_content["next_cursor"]
            changed = await session.call_tool("conatus_search_workorders",
                                              {"limit": 1, "status": "Open", "cursor": cursor})
            self.assertIn("INVALID_CURSOR", str(changed.content))
            middle = len(cursor) // 2
            corrupted_cursor = (cursor[:middle] + ("A" if cursor[middle] != "A" else "B")
                                + cursor[middle + 1:])
            tampered = await session.call_tool("conatus_search_workorders",
                                               {"limit": 1, "cursor": corrupted_cursor})
            self.assertTrue(tampered.is_error)
        async with self.open(issue_test_token(self.key, client="other-client")) as session:
            reused = await session.call_tool("conatus_search_workorders",
                                             {"limit": 1, "cursor": cursor})
            self.assertIn("INVALID_CURSOR", str(reused.content))

    async def test_untrusted_card_is_data_and_ssrf_rejected(self):
        async with self.open() as session:
            card = await session.call_tool("conatus_get_agent_card",
                                           {"card_id": "CardFixtureA"})
            self.assertIn("IGNORE PREVIOUS", card.structured_content["data"]["name"])
            self.assertEqual(card.structured_content["evidence_source"], "OFFLINE_FIXTURE")
            query = await session.call_tool("conatus_search_agents",
                                            {"query": "http://169.254.169.254/latest"})
            self.assertIn("INVALID_QUERY", str(query.content))
            self.assertEqual(self.backend.snapshot()["work_orders"][0]["status"], "Open")

    async def test_synthetic_evidence_cannot_claim_live(self):
        self.backend.data["evidence"][0]["evidence_source"] = "LIVE_RPC"
        async with self.open(issue_test_token(self.key)) as session:
            result = await session.call_tool("conatus_get_settlement_evidence",
                                             {"work_order_pda": "OrderFixtureA2"})
            self.assertIn("UNTRUSTED_EVIDENCE", str(result.content))

    async def test_rate_limit_and_bounds(self):
        self.service.limiter.limit = 1
        async with self.open() as session:
            first = await session.call_tool("conatus_get_protocol_status")
            second = await session.call_tool("conatus_get_protocol_status")
            self.assertFalse(first.is_error)
            self.assertIn("RATE_LIMITED", str(second.content))
            oversized = await session.call_tool("conatus_search_agents", {"limit": 999999})
            self.assertTrue(oversized.is_error)
            first_agent = await session.call_tool("conatus_get_agent",
                                                  {"agent_account": "AgentFixtureA"})
            rotated = await session.call_tool("conatus_get_agent",
                                              {"agent_account": "AgentFixtureB"})
            self.assertFalse(first_agent.is_error)
            self.assertIn("RATE_LIMITED", str(rotated.content))

    async def test_host_origin_and_invalid_bearer(self):
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=self.app)) as http:
            for headers in ({"host": "evil.invalid"},
                            {"host": "127.0.0.1:8090", "origin": "https://evil.invalid"},
                            {"host": "127.0.0.1:8090", "authorization": "Bearer garbage"},
                            {"host": "127.0.0.1:8090", "authorization": "Bearer " +
                             issue_test_token(self.key, expires=int(time.time()) - 1)},
                            {"host": "127.0.0.1:8090", "authorization": "Bearer " +
                             issue_test_token(self.key, audience="https://other.invalid/mcp")}):
                response = await http.post(URL, headers=headers, json={})
                self.assertIn(response.status_code, (401, 403))
        self.assertEqual(self.service.metrics_snapshot()["mcp_transport_errors"], 5)

    async def test_malformed_json_is_protocol_error(self):
        inner = self.service.mcp.streamable_http_app(stateless_http=True,
                   json_response=True, max_request_body_size=65536)
        app = AuthBoundary(inner, self.verifier,
                           hosts=frozenset({"127.0.0.1:8090"}),
                           on_transport_error=self.service._metric)
        async with inner.router.lifespan_context(inner):
            async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app)) as http:
                response = await http.post(URL, content=b"{",
                    headers={"host": "127.0.0.1:8090", "content-type": "application/json",
                             "accept": "application/json, text/event-stream",
                             "mcp-protocol-version": "2026-07-28"})
                self.assertEqual(response.status_code, 400)

    async def test_official_stdio_client_is_public_only(self):
        params = StdioServerParameters(command=sys.executable,
            args=["-m", "tools.mcp.server", "--fixture", str(FIXTURE)],
            cwd=str(Path(__file__).resolve().parents[2]))
        async with stdio_client(params) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                discovery = await session.discover()
                self.assertIn("2026-07-28", discovery.supported_versions)
                self.assertEqual({tool.name for tool in (await session.list_tools()).tools}, TOOLS)
                result = await session.call_tool("conatus_get_workorder",
                                                 {"work_order_pda": "OrderFixtureA1"})
                self.assertIn("INSUFFICIENT_SCOPE", str(result.content))


if __name__ == "__main__":
    unittest.main()
