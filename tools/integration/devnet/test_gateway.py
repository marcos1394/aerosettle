"""Offline CON-59 adversarial tests. No Devnet writes or network calls."""
import base64
import copy
import json
import threading
import unittest
from unittest.mock import patch

from tools.discovery.agent_discovery import b58decode, find_program_address
from tools.integration.devnet import gateway as g


def account(raw, owner, executable=False):
    return {"owner": owner, "executable": executable,
            "data": [base64.b64encode(raw).decode(), "base64"]}


class FakeRpc:
    def __init__(self, *, genesis=g.GENESIS, slot=500):
        self.genesis, self.slot = genesis, slot
        self.fail = False
        self.calls = []
        idl = g.Idl(json.loads(g.IDL_PATH.read_bytes()))
        config_raw = (idl.accounts["ProtocolConfig"] + b"\x01" + b58decode(g.PROTOCOL_ADMIN, 32)
                      + bytes.fromhex(g.NETWORK_ID_HEX) + b58decode(g.PROGRAM, 32)
                      + bytes.fromhex(g.DEPLOYMENT_ID) + b"\xff" + (0).to_bytes(8, "little")
                      + b"\0" + (0).to_bytes(8, "little", signed=True))
        self.accounts = {
            g.PROGRAM: account(b"\x02\0\0\0" + b58decode(g.PROGRAM_DATA, 32), g.LOADER, True),
            g.PROGRAM_DATA: account(b"\x03\0\0\0" + b"\0" * 8 + b"\x01"
                                    + b58decode(g.UPGRADE_AUTHORITY, 32)
                                    + (g.ROOT / "evidence/con35/artifacts/aerosettle.so").read_bytes(), g.LOADER),
            g.MINT: account(b"\x01\0\0\0" + b58decode(g.MINT_AUTHORITY, 32)
                            + b"\0" * 8 + b"\x06\x01" + b"\0" * 36, g.TOKEN),
            find_program_address([b"protocol_config"], g.PROGRAM): account(config_raw, g.PROGRAM),
        }

    def call(self, method, params):
        self.calls.append((method, params))
        if self.fail:
            raise g.GatewayError(503, "RPC_UNAVAILABLE")
        if method == "getGenesisHash":
            return self.genesis
        if method == "getSlot":
            return self.slot
        if method == "getAccountInfo":
            return {"context": {"slot": self.slot}, "value": self.accounts.get(params[0])}
        raise AssertionError(method)


def discovery_fixture(rpc, *args):
    slot = rpc.provider.rpc.slot
    return {"agents": [
        {"agent_account": "A" * 32, "agent_id": "01", "status": "Active", "owner": "B" * 32,
         "signing_authority": "B" * 32},
        {"agent_account": "C" * 32, "agent_id": "02", "status": "Revoked", "owner": "D" * 32,
         "signing_authority": "D" * 32},
    ], "work_orders": [{"work_order_account": "E" * 32, "status": "Open",
                        "token_mint": g.MINT, "token_program": g.TOKEN}],
        "rpc_context_slots": {"config": slot, "AgentAccount": slot, "WorkOrderAccount": slot, "clock": slot}}


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.rpc = FakeRpc()
        self.patcher = patch.object(g, "discover", side_effect=discovery_fixture)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.index = g.Index(g.Provider("official-devnet", self.rpc))
        self.api = g.Gateway(self.index)

    def test_live_index_pagination_and_cache_slot_invalidation(self):
        status, body, _ = self.api.handle("GET", "/v1/agents?limit=1", origin=g.STAGING_ORIGIN)
        self.assertEqual(status, 200)
        self.assertEqual(body["provenance"]["source"], "INDEXED_FROM_RPC")
        self.assertFalse(body["provenance"]["atomic_snapshot"])
        self.assertFalse(body["is_financial_authority"])
        cursor = body["data"]["page"]["next_cursor"]
        status, body, _ = self.api.handle("GET", "/v1/agents?limit=1&cursor=" + cursor,
                                          origin=g.STAGING_ORIGIN)
        self.assertEqual(status, 200)
        self.assertEqual(body["provenance"]["source"], "CACHED_VERIFIED")
        self.assertEqual(body["data"]["count"], 1)
        self.rpc.slot += 1
        status, body, _ = self.api.handle("GET", "/v1/agents?limit=1&cursor=" + cursor,
                                          origin=g.STAGING_ORIGIN)
        self.assertEqual(status, 400)
        self.assertEqual(body["error"]["code"], "CURSOR_SCOPE_MISMATCH")

    def test_identity_and_account_adversaries(self):
        cases = [
            (lambda r: setattr(r, "genesis", "other"), "GENESIS_MISMATCH"),
            (lambda r: r.accounts[g.PROGRAM].update(owner=g.TOKEN), "ACCOUNT_IDENTITY_MISMATCH"),
            (lambda r: r.accounts[g.MINT].update(owner=g.PROGRAM), "ACCOUNT_IDENTITY_MISMATCH"),
            (lambda r: r.accounts[g.MINT].update(data=[base64.b64encode(b"bad").decode(), "base64"]),
             "MINT_IDENTITY_MISMATCH"),
            (lambda r: r.accounts.pop(find_program_address([b"protocol_config"], g.PROGRAM)),
             "ACCOUNT_IDENTITY_MISMATCH"),
        ]
        for mutate, code in cases:
            with self.subTest(code=code):
                rpc = FakeRpc()
                mutate(rpc)
                api = g.Gateway(g.Index(g.Provider("test", rpc)))
                status, body, _ = api.handle("GET", "/v1/agents")
                self.assertEqual(status, 503)
                self.assertEqual(body["error"]["code"], code)

    def test_idl_mutation_and_discriminator_rejected(self):
        with patch.object(g, "IDL_SHA256", "0" * 64):
            with self.assertRaisesRegex(g.GatewayError, "IDL_HASH_MISMATCH"):
                g.Index(g.Provider("test", FakeRpc()))
        idl = g.Idl(json.loads(g.IDL_PATH.read_bytes()))
        with self.assertRaisesRegex(g.DiscoveryError, "discriminator"):
            idl.decode_account("AgentAccount", b"\0" * 100)

    def test_failover_and_both_down(self):
        first = FakeRpc()
        first.fail = True
        second = FakeRpc()
        api = g.Gateway(g.Index(g.Provider("first", first), g.Provider("second", second)))
        status, body, _ = api.handle("GET", "/v1/network")
        self.assertEqual(status, 200)
        self.assertEqual(body["provenance"]["provider"], "second")
        self.assertEqual(api.index.metrics["failover"], 1)
        second.fail = True
        api.index.cached = None
        status, body, _ = api.handle("GET", "/v1/network")
        self.assertEqual(status, 503)
        self.assertIn(body["error"]["code"], {"RPC_UNAVAILABLE", "RPC_CIRCUIT_OPEN"})

    def test_identity_mismatch_never_fails_over(self):
        first = FakeRpc(genesis="wrong")
        second = FakeRpc()
        api = g.Gateway(g.Index(g.Provider("first", first), g.Provider("second", second)))
        status, body, _ = api.handle("GET", "/v1/network")
        self.assertEqual((status, body["error"]["code"]), (503, "GENESIS_MISMATCH"))
        self.assertEqual(second.calls, [])

    def test_stale_cache_not_served_after_failure(self):
        self.assertEqual(self.api.handle("GET", "/v1/network")[0], 200)
        self.rpc.fail = True
        self.assertEqual(self.api.handle("GET", "/v1/network")[0], 503)

    def test_cache_poison_and_cross_network_rejected(self):
        self.assertEqual(self.api.handle("GET", "/v1/network")[0], 200)
        self.index.cached["context"]["network"] = "solana:mainnet-beta"
        status, body, _ = self.api.handle("GET", "/v1/network")
        self.assertEqual((status, body["error"]["code"]), (503, "CACHE_INTEGRITY_MISMATCH"))

    def test_protocol_config_deployment_and_authority_binding(self):
        for offset in (9, 41, 73, 105):
            with self.subTest(offset=offset):
                rpc = FakeRpc()
                key = find_program_address([b"protocol_config"], g.PROGRAM)
                raw = bytearray(base64.b64decode(rpc.accounts[key]["data"][0]))
                raw[offset] ^= 1
                rpc.accounts[key]["data"][0] = base64.b64encode(raw).decode()
                api = g.Gateway(g.Index(g.Provider("altered", rpc)))
                self.assertEqual(api.handle("GET", "/v1/network")[0], 503)

    def test_inconsistent_slots_and_asset_projections(self):
        self.rpc.slot = 499
        self.assertEqual(self.api.handle("GET", "/v1/network")[0], 200)
        self.index.cached = None
        with patch.object(g, "discover", return_value={**discovery_fixture(g._BoundRpc(g.Provider("fake", FakeRpc()))),
                "rpc_context_slots": {"config": 501, "AgentAccount": 501, "WorkOrderAccount": 501,
                                      "clock": 501}}):
            status, body, _ = self.api.handle("GET", "/v1/network")
            self.assertEqual((status, body["error"]["code"]), (503, "RPC_CONTEXT_CHANGED"))
        self.index.cached = None
        wrong = discovery_fixture(g._BoundRpc(g.Provider("fake", FakeRpc())))
        wrong["work_orders"][0]["token_mint"] = g.PROGRAM
        with patch.object(g, "discover", return_value=wrong):
            status, body, _ = self.api.handle("GET", "/v1/workorders")
            self.assertEqual((status, body["error"]["code"]), (503, "WORK_ORDER_ASSET_MISMATCH"))

    def test_rpc_response_size_and_id_binding(self):
        class Reply:
            def __init__(self, body):
                self.body = body
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return None
            def read(self, size):
                return self.body[:size]
        rpc = g.JsonRpc(verify_dns=False)
        for body, code in ((b"x" * (g.MAX_RPC_BYTES + 1), "RPC_RESPONSE_TOO_LARGE"),
                           (b'{"jsonrpc":"2.0","id":"wrong","result":"yes"}', "RPC_RESPONSE_INVALID")):
            with self.subTest(code=code), patch.object(g, "_public_rpc_url"), patch.object(
                    rpc.opener, "open", return_value=Reply(body)):
                with self.assertRaisesRegex(g.GatewayError, code):
                    rpc.call("getGenesisHash", [])

    def test_rpc_http_errors_and_partial_response(self):
        rpc = g.JsonRpc(verify_dns=False)
        class Reply:
            def __enter__(self): return self
            def __exit__(self, *args): return None
            def read(self, size): return b'{"jsonrpc":"2.0"}'
        for code, expected in ((429, "RPC_RATE_LIMITED"), (500, "RPC_HTTP_ERROR"),
                               (503, "RPC_HTTP_ERROR")):
            error = g.urllib.error.HTTPError(rpc.url, code, "error", {}, None)
            with self.subTest(code=code), patch.object(g, "_public_rpc_url"), patch.object(
                    rpc.opener, "open", side_effect=error):
                with self.assertRaisesRegex(g.GatewayError, expected):
                    rpc.call("getGenesisHash", [])
        with patch.object(g, "_public_rpc_url"), patch.object(rpc.opener, "open", return_value=Reply()):
            with self.assertRaisesRegex(g.GatewayError, "RPC_RESPONSE_INVALID"):
                rpc.call("getGenesisHash", [])

    def test_circuit_recovers_with_one_half_open_probe(self):
        now = [0.0]
        rpc = FakeRpc()
        rpc.fail = True
        provider = g.Provider("recovering", rpc, clock=lambda: now[0])
        for _ in range(3):
            with self.assertRaises(g.GatewayError): provider.call("getGenesisHash", [])
        now[0] = 31
        provider.start()
        with self.assertRaisesRegex(g.GatewayError, "RPC_CIRCUIT_OPEN"):
            provider.start()
        rpc.fail = False
        self.assertEqual(provider.call("getGenesisHash", []), g.GENESIS)
        provider.start()

    def test_alert_hooks_report_failures(self):
        self.index.metrics["scan_failed"] = 1
        self.index.metrics["network_mismatch"] = 1
        self.assertEqual(self.index.alert_codes(), ["NETWORK_MISMATCH", "INDEX_UNAVAILABLE"])

    def test_gateway_concurrency_limit_and_metrics(self):
        for _ in range(8): self.api.semaphore.acquire()
        try:
            status, body, _ = self.api.handle("GET", "/v1/network")
            self.assertEqual((status, body["error"]["code"]), (503, "CONCURRENCY_LIMITED"))
        finally:
            for _ in range(8): self.api.semaphore.release()
        self.assertEqual(self.api.handle("GET", "/v1/network")[0], 200)
        self.assertGreater(self.api.stats()["requests_per_second_60s"], 0)

    def test_http_security_and_private_routes(self):
        checks = [
            ("POST", "/v1/agents", None, 405),
            ("GET", "/v1/transactions/abc", None, 404),
            ("GET", "/v1/agents?limit=999", None, 400),
            ("GET", "/v1/agents?limit=1&limit=2", None, 400),
            ("GET", "/v1/agents?rpc=https://evil.example", None, 400),
            ("GET", "/v1/agents", "https://evil.example", 403),
            ("GET", "/v1/agents?status=Settled", None, 400),
        ]
        for method, path, origin, expected in checks:
            with self.subTest(path=path, origin=origin):
                status, _, headers = self.api.handle(method, path, origin=origin)
                self.assertEqual(status, expected)
                self.assertNotIn("Access-Control-Allow-Origin", headers)
        self.assertEqual(self.api.handle("GET", "/v1/agents", origin=g.STAGING_ORIGIN)[2]
                         ["Access-Control-Allow-Origin"], g.STAGING_ORIGIN)

    def test_rate_limit_and_circuit(self):
        for _ in range(20):
            self.assertEqual(self.api.handle("GET", "/v1/network", client="limited")[0], 200)
        self.assertEqual(self.api.handle("GET", "/v1/network", client="limited")[0], 429)
        rpc = FakeRpc()
        rpc.fail = True
        provider = g.Provider("down", rpc)
        for _ in range(3):
            with self.assertRaises(g.GatewayError):
                provider.call("getGenesisHash", [])
        with self.assertRaisesRegex(g.GatewayError, "RPC_CIRCUIT_OPEN"):
            provider.start()

    def test_rpc_allowlist_and_ssrf(self):
        with patch.object(g.socket, "getaddrinfo", return_value=[(None, None, None, None,
                                                                    ("127.0.0.1", 443))]):
            with self.assertRaisesRegex(g.GatewayError, "RPC_ENDPOINT_NOT_PUBLIC"):
                g.JsonRpc()
        for url in ("http://api.devnet.solana.com", "https://localhost", "https://127.0.0.1",
                    "https://api.devnet.solana.com.evil.example", "https://api.devnet.solana.com@evil.example"):
            with self.subTest(url=url), self.assertRaises(g.GatewayError):
                g.JsonRpc(url, verify_dns=False)
        rpc = g.JsonRpc(verify_dns=False)
        with self.assertRaisesRegex(g.GatewayError, "RPC_METHOD_NOT_ALLOWED"):
            rpc.call("sendTransaction", [])
        with self.assertRaisesRegex(g.GatewayError, "RPC_PARAMS_NOT_ALLOWED"):
            rpc.call("getProgramAccounts", ["11111111111111111111111111111111", {}])

    def test_concurrent_refresh_is_single_scan(self):
        outcomes = []
        threads = [threading.Thread(target=lambda: outcomes.append(self.api.handle("GET", "/v1/network")[0]))
                   for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(outcomes, [200] * 8)
        self.assertEqual(self.index.metrics["scan_ok"], 1)


if __name__ == "__main__":
    unittest.main()
