"""CON-59 bounded, read-only Devnet RPC index and HTTP gateway.

No wallet, transaction submission, storage service, or public JSON-RPC proxy.
The HTTP server is intended for a separately approved host, not Pages Free.
"""
from __future__ import annotations

import base64
import argparse
from collections import Counter, deque
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
from pathlib import Path
import random
import re
import socket
import ssl
import threading
import time
from typing import Any
from urllib.parse import parse_qs, urlsplit
import urllib.error
import urllib.request
import uuid

import certifi

from tools.discovery.agent_discovery import (
    CLOCK_SYSVAR, DiscoveryError, Idl, b58decode, b58encode, discover,
    find_program_address,
)
from tools.marketplace_api.cursor_pagination import CursorError, paginate
from tools.operations.structured_logs import emit

ROOT = Path(__file__).resolve().parents[3]
IDL_PATH = ROOT / "evidence/con35/artifacts/aerosettle-idl.json"
NETWORK = "solana:devnet"
GENESIS = "EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG"
PROGRAM = "CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy"
MINT = "HpfaV9oRuTN1b3ktDKvJoWqUWFZ1o9VFmhejxxqQ1vyh"
TOKEN = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
LOADER = "BPFLoaderUpgradeab1e11111111111111111111111"
PROGRAM_DATA = "7kYZxnujXJ9sKGhG9CbDwThJECb693WvvqVFHGmNSsrr"
UPGRADE_AUTHORITY = "DdHrtAxE5SwcVQUgoKRzoWatZ5yw9UdtBQnRwBizPK2D"
MINT_AUTHORITY = "4om6LcFXaZ2Wtbn3P2ZvvyqssXFQs1xjNmE2Fnj7mRHa"
PROTOCOL_ADMIN = "27cyzd58RswQRbSuR3cKh4xv2gWgZ7awb3tUtoT7hYLB"
NETWORK_ID_HEX = "ce59db5080fc2c6d3bcf7ca90712d3c2e5e6c28f27f0dfbb9953bdb0894c03ab"
DEPLOYMENT_ID = "06c7dfa7528460969a5ca1e8bd001f9c9f1f1f0df3d69fe36649e413e0b14ae6"
IDL_SHA256 = "a6e436aa1c6468b4f518b742e40a2664e38dcdf7bc1419e53e1624444888e15d"
BINARY_SHA256 = "6cf3412c55c38e91b2ba0039aea24d58782c5db0d18759ffdab1c88788cdc3a2"
OFFICIAL_RPC = "https://api.devnet.solana.com"
STAGING_ORIGIN = "https://conatus-devnet-staging.pages.dev"
RPC_METHODS = frozenset({"getGenesisHash", "getAccountInfo", "getProgramAccounts", "getSlot"})
MAX_RPC_BYTES = 2_000_000
MAX_ACCOUNTS = 500
MAX_PAGE = 50
CACHE_TTL = 10


class GatewayError(Exception):
    def __init__(self, status: int, code: str):
        super().__init__(code)
        self.status, self.code = status, code


def _slot(value: Any) -> int:
    if type(value) is not int or value < 0:
        raise GatewayError(502, "RPC_CONTEXT_INVALID")
    return value


def _account_result(result: Any) -> tuple[int, Any]:
    if not isinstance(result, dict) or not isinstance(result.get("context"), dict) or "value" not in result:
        raise GatewayError(502, "RPC_RESPONSE_INCOMPLETE")
    return _slot(result["context"].get("slot")), result["value"]


def _data(info: dict, owner: str, executable: bool) -> bytes:
    if not isinstance(info, dict) or info.get("owner") != owner or info.get("executable") is not executable:
        raise GatewayError(502, "ACCOUNT_IDENTITY_MISMATCH")
    try:
        encoded = info["data"]
        if not isinstance(encoded, list) or len(encoded) != 2 or encoded[1] != "base64":
            raise ValueError("Invalid encoding")
        return base64.b64decode(encoded[0], validate=True)
    except (DiscoveryError, ValueError, TypeError) as exc:
        raise GatewayError(502, "ACCOUNT_DATA_INVALID") from exc


def _public_rpc_url(url: str, approved_hosts: frozenset[str]) -> None:
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.hostname not in approved_hosts
            or parsed.port is not None or parsed.username or parsed.password or parsed.path not in ("", "/")
            or parsed.query or parsed.fragment):
        raise GatewayError(400, "RPC_ENDPOINT_NOT_APPROVED")
    try:
        addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise GatewayError(503, "RPC_DNS_UNAVAILABLE") from exc
    if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
        raise GatewayError(400, "RPC_ENDPOINT_NOT_PUBLIC")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise GatewayError(502, "RPC_REDIRECT_REJECTED")


class JsonRpc:
    """Only fixed, audited methods; endpoint comes from operator config, never HTTP input."""

    def __init__(self, url: str = OFFICIAL_RPC, *, approved_hosts: frozenset[str] | None = None,
                 timeout: float = 6, verify_dns: bool = True):
        self.url = url
        self.approved_hosts = approved_hosts or frozenset({"api.devnet.solana.com"})
        self.timeout = timeout
        if timeout <= 0 or timeout > 10:
            raise GatewayError(400, "RPC_TIMEOUT_INVALID")
        if verify_dns:
            _public_rpc_url(url, self.approved_hosts)
        else:
            parsed = urlsplit(url)
            if parsed.scheme != "https" or parsed.hostname not in self.approved_hosts:
                raise GatewayError(400, "RPC_ENDPOINT_NOT_APPROVED")
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=certifi.where())),
            _NoRedirect())

    def call(self, method: str, params: list[Any]) -> Any:
        if method not in RPC_METHODS or not isinstance(params, list):
            raise GatewayError(400, "RPC_METHOD_NOT_ALLOWED")
        if method == "getGenesisHash" and params != []:
            raise GatewayError(400, "RPC_PARAMS_NOT_ALLOWED")
        if method == "getSlot" and params != [{"commitment": "finalized"}]:
            raise GatewayError(400, "RPC_PARAMS_NOT_ALLOWED")
        if method == "getAccountInfo":
            allowed = {PROGRAM, PROGRAM_DATA, MINT, CLOCK_SYSVAR,
                       find_program_address([b"protocol_config"], PROGRAM)}
            if (len(params) != 2 or params[0] not in allowed or not isinstance(params[1], dict)
                    or params[1].get("encoding") != "base64" or params[1].get("commitment") != "finalized"
                    or set(params[1]) - {"encoding", "commitment", "minContextSlot"}
                    or ("minContextSlot" in params[1] and
                        (type(params[1]["minContextSlot"]) is not int or params[1]["minContextSlot"] < 0))):
                raise GatewayError(400, "RPC_PARAMS_NOT_ALLOWED")
        if method == "getProgramAccounts":
            if len(params) != 2 or params[0] != PROGRAM or not isinstance(params[1], dict):
                raise GatewayError(400, "RPC_PARAMS_NOT_ALLOWED")
            options = params[1]
            if (options.get("encoding") != "base64" or options.get("commitment") != "finalized"
                    or options.get("withContext") is not True or set(options) !=
                    {"encoding", "commitment", "withContext", "minContextSlot", "filters"}
                    or type(options.get("minContextSlot")) is not int or options["minContextSlot"] < 0
                    or not isinstance(options.get("filters"), list) or len(options["filters"]) != 1
                    or not isinstance(options["filters"][0], dict)
                    or set(options["filters"][0]) != {"memcmp"}):
                raise GatewayError(400, "RPC_PARAMS_NOT_ALLOWED")
            memcmp = options["filters"][0]["memcmp"]
            idl = Idl(json.loads(IDL_PATH.read_bytes()))
            if (not isinstance(memcmp, dict) or memcmp.get("offset") != 0 or
                    memcmp.get("bytes") not in {b58encode(idl.accounts["AgentAccount"]),
                                                b58encode(idl.accounts["WorkOrderAccount"])}):
                raise GatewayError(400, "RPC_PARAMS_NOT_ALLOWED")
        _public_rpc_url(self.url, self.approved_hosts)
        request_id = uuid.uuid4().hex
        body = json.dumps({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
                          separators=(",", ":")).encode()
        req = urllib.request.Request(self.url, data=body, headers={"Content-Type": "application/json"},
                                     method="POST")
        try:
            with self.opener.open(req, timeout=self.timeout) as response:
                raw = response.read(MAX_RPC_BYTES + 1)
        except urllib.error.HTTPError as exc:
            raise GatewayError(503 if exc.code in (429, 500, 502, 503, 504) else 502,
                               "RPC_RATE_LIMITED" if exc.code == 429 else "RPC_HTTP_ERROR") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise GatewayError(503, "RPC_UNAVAILABLE") from exc
        if len(raw) > MAX_RPC_BYTES:
            raise GatewayError(502, "RPC_RESPONSE_TOO_LARGE")
        try:
            value = json.loads(raw)
        except (ValueError, UnicodeError) as exc:
            raise GatewayError(502, "RPC_RESPONSE_INVALID") from exc
        if not isinstance(value, dict) or value.get("jsonrpc") != "2.0" or value.get("id") != request_id:
            raise GatewayError(502, "RPC_RESPONSE_INVALID")
        if value.get("error") is not None:
            raise GatewayError(503, "RPC_PROVIDER_ERROR")
        if "result" not in value:
            raise GatewayError(502, "RPC_RESPONSE_INCOMPLETE")
        return value["result"]


class Provider:
    def __init__(self, name: str, rpc: Any, *, clock=time.monotonic):
        if not re.fullmatch(r"[a-z][a-z0-9-]{0,31}", name):
            raise ValueError("Invalid provider name")
        self.name, self.rpc, self.clock = name, rpc, clock
        self.failures = 0
        self.open_until = 0.0
        self.probe = False
        self.calls: deque[float] = deque()
        self.lock = threading.Lock()

    def start(self) -> None:
        with self.lock:
            now = self.clock()
            if now < self.open_until or self.probe:
                raise GatewayError(503, "RPC_CIRCUIT_OPEN")
            if self.open_until:
                self.probe = True
            while self.calls and now - self.calls[0] >= 60:
                self.calls.popleft()
            if len(self.calls) >= 120:
                self.probe = False
                raise GatewayError(429, "RPC_BUDGET_EXHAUSTED")

    def call(self, method: str, params: list[Any]) -> Any:
        with self.lock:
            now = self.clock()
            while self.calls and now - self.calls[0] >= 60:
                self.calls.popleft()
            if len(self.calls) >= 120:
                raise GatewayError(429, "RPC_BUDGET_EXHAUSTED")
            self.calls.append(self.clock())
        try:
            result = self.rpc.call(method, params)
        except Exception as exc:
            with self.lock:
                self.failures += 1
                if self.failures >= 3 or self.probe:
                    self.open_until = self.clock() + 30
                self.probe = False
            if isinstance(exc, GatewayError):
                raise
            raise GatewayError(503, "RPC_UNAVAILABLE") from exc
        with self.lock:
            self.failures = 0
            self.open_until = 0
            self.probe = False
        return result


class _BoundRpc:
    def __init__(self, provider: Provider):
        self.provider = provider

    def call(self, method: str, params: list[Any]) -> Any:
        return self.provider.call(method, params)


class Index:
    def __init__(self, primary: Provider, secondary: Provider | None = None, *, clock=time.monotonic):
        self.providers = (primary,) if secondary is None else (primary, secondary)
        self.clock = clock
        self.lock = threading.Lock()
        self.cached: dict | None = None
        self.cached_digest: str | None = None
        self.expires = 0.0
        self.metrics = Counter()
        self.latencies: deque[float] = deque(maxlen=512)
        idl_bytes = IDL_PATH.read_bytes()
        if hashlib.sha256(idl_bytes).hexdigest() != IDL_SHA256:
            raise GatewayError(503, "IDL_HASH_MISMATCH")
        self.idl = Idl(json.loads(idl_bytes))
        if self.idl.address != PROGRAM:
            raise GatewayError(503, "IDL_PROGRAM_MISMATCH")
        self.idl.validate_marketplace_contract()

    def _identity(self, rpc: _BoundRpc, min_slot: int | None = None) -> int:
        if rpc.call("getGenesisHash", []) != GENESIS:
            self.metrics["network_mismatch"] += 1
            raise GatewayError(502, "GENESIS_MISMATCH")
        program_options = {"encoding": "base64", "commitment": "finalized"}
        if min_slot is not None:
            program_options["minContextSlot"] = min_slot
        slot, program = _account_result(rpc.call("getAccountInfo", [PROGRAM, program_options]))
        if program is None:
            raise GatewayError(503, "PROGRAM_MISSING")
        raw = _data(program, LOADER, True)
        if len(raw) < 36 or raw[:4] != b"\x02\0\0\0" or b58encode(raw[4:36]) != PROGRAM_DATA:
            raise GatewayError(502, "PROGRAM_IDENTITY_MISMATCH")
        data_slot, program_data = _account_result(rpc.call("getAccountInfo", [PROGRAM_DATA,
            {"encoding": "base64", "commitment": "finalized", "minContextSlot": slot}]))
        raw = _data(program_data, LOADER, False)
        if len(raw) < 45 or raw[:4] != b"\x03\0\0\0" or raw[12] != 1 or b58encode(raw[13:45]) != UPGRADE_AUTHORITY:
            raise GatewayError(502, "UPGRADE_AUTHORITY_MISMATCH")
        if hashlib.sha256(raw[45:]).hexdigest() != BINARY_SHA256:
            raise GatewayError(502, "PROGRAM_BINARY_MISMATCH")
        mint_slot, mint = _account_result(rpc.call("getAccountInfo", [MINT,
            {"encoding": "base64", "commitment": "finalized", "minContextSlot": data_slot}]))
        raw = _data(mint, TOKEN, False)
        if (len(raw) != 82 or raw[:4] != b"\x01\0\0\0" or b58encode(raw[4:36]) != MINT_AUTHORITY
                or raw[44:46] != b"\x06\x01" or raw[46:50] != b"\0\0\0\0"):
            raise GatewayError(502, "MINT_IDENTITY_MISMATCH")
        config_key = find_program_address([b"protocol_config"], PROGRAM)
        config_slot, config_info = _account_result(rpc.call("getAccountInfo", [config_key,
            {"encoding": "base64", "commitment": "finalized", "minContextSlot": mint_slot}]))
        try:
            config = self.idl.decode_account("ProtocolConfig", _data(config_info, PROGRAM, False))
        except (DiscoveryError, ValueError, TypeError) as exc:
            raise GatewayError(502, "PROTOCOL_CONFIG_INVALID") from exc
        if (config.get("program_id") != PROGRAM or config.get("authority") != PROTOCOL_ADMIN
                or config.get("network_id") != NETWORK_ID_HEX
                or config.get("deployment_id") != DEPLOYMENT_ID):
            raise GatewayError(502, "PROTOCOL_CONFIG_MISMATCH")
        return config_slot

    def _scan(self, provider: Provider) -> dict:
        provider.start()
        rpc = _BoundRpc(provider)
        first_slot = self._identity(rpc)
        try:
            value = discover(rpc, self.idl, "finalized")
        except (DiscoveryError, ValueError, KeyError, TypeError) as exc:
            raise GatewayError(502, "ANCHOR_ACCOUNT_INVALID") from exc
        slots = value["rpc_context_slots"]
        if any(_slot(number) < first_slot for number in slots.values()):
            raise GatewayError(502, "RPC_SLOT_REGRESSION")
        if len(value["agents"]) > MAX_ACCOUNTS or len(value["work_orders"]) > MAX_ACCOUNTS:
            raise GatewayError(502, "INDEX_LIMIT_EXCEEDED")
        if any("owner" not in row or "signing_authority" not in row for row in value["agents"]):
            raise GatewayError(502, "AGENT_AUTHORITY_MISSING")
        if any(row.get("token_mint") != MINT or row.get("token_program") != TOKEN
               for row in value["work_orders"]):
            raise GatewayError(502, "WORK_ORDER_ASSET_MISMATCH")
        last_slot = _slot(rpc.call("getSlot", [{"commitment": "finalized"}]))
        if last_slot < max(slots.values()) or self._identity(rpc, last_slot) < last_slot:
            raise GatewayError(502, "RPC_CONTEXT_CHANGED")
        now = datetime.now(timezone.utc).isoformat()
        context = {"source": "INDEXED_FROM_RPC", "network": NETWORK, "genesis_hash": GENESIS,
                   "program_id": PROGRAM, "mint": MINT, "idl_sha256": IDL_SHA256,
                   "commitment": "finalized", "slot_min": min(slots.values()),
                   "slot_max": max(slots.values()), "indexed_at": now, "last_verified_at": now,
                   "provider": provider.name, "atomic_snapshot": False, "cache_version": 1}
        return {"agents": value["agents"], "work_orders": value["work_orders"], "context": context,
                "observed_slot": last_slot}

    def snapshot(self) -> dict:
        with self.lock:
            if self.cached and self.clock() < self.expires:
                digest = hashlib.sha256(json.dumps(self.cached, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                if digest != self.cached_digest or not self._valid_context(self.cached["context"]):
                    self.cached = None
                    self.cached_digest = None
                    self.metrics["cache_poison_rejected"] += 1
                    raise GatewayError(503, "CACHE_INTEGRITY_MISMATCH")
                provider = next(p for p in self.providers if p.name == self.cached["context"]["provider"])
                try:
                    provider.start()
                    current = _slot(provider.call("getSlot", [{"commitment": "finalized"}]))
                    if current == self.cached["observed_slot"] and provider.call("getGenesisHash", []) == GENESIS:
                        self.metrics["cache_hit"] += 1
                        return {**self.cached, "context": {**self.cached["context"], "source": "CACHED_VERIFIED"}}
                except GatewayError:
                    pass
                self.cached = None
                self.cached_digest = None
            errors = []
            for index, provider in enumerate(self.providers):
                for attempt in range(2):
                    started = self.clock()
                    try:
                        result = self._scan(provider)
                        self.cached = result
                        self.cached_digest = hashlib.sha256(json.dumps(result, sort_keys=True,
                                                          separators=(",", ":")).encode()).hexdigest()
                        self.expires = self.clock() + CACHE_TTL
                        self.metrics["scan_ok"] += 1
                        self.latencies.append((self.clock() - started) * 1000)
                        return result
                    except GatewayError as exc:
                        errors.append(exc.code)
                        self.metrics["rpc_error"] += 1
                        if exc.code in {"GENESIS_MISMATCH", "PROGRAM_IDENTITY_MISMATCH",
                                        "UPGRADE_AUTHORITY_MISMATCH", "PROGRAM_BINARY_MISMATCH",
                                        "MINT_IDENTITY_MISMATCH",
                                        "ANCHOR_ACCOUNT_INVALID", "RPC_SLOT_REGRESSION", "RPC_CONTEXT_CHANGED"}:
                            break
                        if attempt == 0:
                            self.metrics["retry"] += 1
                            time.sleep(0.05 + random.random() * 0.05)
                if errors[-1] in {"GENESIS_MISMATCH", "PROGRAM_IDENTITY_MISMATCH",
                                  "UPGRADE_AUTHORITY_MISMATCH", "PROGRAM_BINARY_MISMATCH",
                                  "MINT_IDENTITY_MISMATCH",
                                  "PROTOCOL_CONFIG_MISMATCH", "PROTOCOL_CONFIG_INVALID",
                                  "ANCHOR_ACCOUNT_INVALID", "RPC_SLOT_REGRESSION", "RPC_CONTEXT_CHANGED"}:
                    break
                if index == 0 and len(self.providers) > 1:
                    self.metrics["failover"] += 1
            self.metrics["scan_failed"] += 1
            raise GatewayError(503, errors[-1] if errors else "RPC_UNAVAILABLE")

    @staticmethod
    def _valid_context(context: dict) -> bool:
        return (isinstance(context, dict) and context.get("network") == NETWORK
                and context.get("genesis_hash") == GENESIS and context.get("program_id") == PROGRAM
                and context.get("idl_sha256") == IDL_SHA256 and context.get("mint") == MINT
                and context.get("commitment") == "finalized")

    def stats(self) -> dict:
        samples = sorted(self.latencies)
        def percentile(p: float) -> float | None:
            return round(samples[min(len(samples) - 1, int((len(samples) - 1) * p))], 2) if samples else None
        return {"counters": dict(self.metrics), "scan_latency_ms": {
            "p50": percentile(.50), "p95": percentile(.95), "p99": percentile(.99)},
            "provider_mode": "SINGLE_PROVIDER_MODE" if len(self.providers) == 1 else "DUAL_PROVIDER_CONFIGURED",
            "circuit": {p.name: ("OPEN" if p.clock() < p.open_until else "CLOSED") for p in self.providers}}

    def alert_codes(self) -> list[str]:
        result = []
        if self.metrics["network_mismatch"]:
            result.append("NETWORK_MISMATCH")
        if self.metrics["scan_failed"]:
            result.append("INDEX_UNAVAILABLE")
        if any(p.clock() < p.open_until for p in self.providers):
            result.append("CIRCUIT_OPEN")
        p95 = self.stats()["scan_latency_ms"]["p95"]
        if p95 is not None and p95 > 5000:
            result.append("SCAN_P95_HIGH")
        return result


class Gateway:
    def __init__(self, index: Index, *, clock=time.monotonic):
        self.index, self.clock = index, clock
        self.clients: dict[str, deque[float]] = {}
        self.rate_lock = threading.Lock()
        self.semaphore = threading.BoundedSemaphore(8)
        self.request_times: deque[float] = deque()
        self.metrics = Counter()

    def stats(self) -> dict:
        with self.rate_lock:
            now = self.clock()
            while self.request_times and now - self.request_times[0] >= 60:
                self.request_times.popleft()
            requests_per_second = round(len(self.request_times) / 60, 3)
        scans = self.index.metrics["scan_ok"]
        hits = self.index.metrics["cache_hit"]
        return {"requests_per_second_60s": requests_per_second,
                "cache_hit_ratio": round(hits / (hits + scans), 3) if hits + scans else None,
                "gateway_counters": dict(self.metrics), "index": self.index.stats(),
                "alerts": self.index.alert_codes()}

    def _rate(self, client: str) -> None:
        with self.rate_lock:
            now = self.clock()
            if len(self.clients) > 1000:
                self.clients = {key: window for key, window in self.clients.items()
                                if window and now - window[-1] < 60}
            window = self.clients.setdefault(client, deque())
            while window and now - window[0] >= 60:
                window.popleft()
            if len(window) >= 20:
                self.metrics["rate_rejected"] += 1
                raise GatewayError(429, "RATE_LIMITED")
            window.append(now)

    def handle(self, method: str, target: str, *, origin: str | None = None,
               client: str = "local") -> tuple[int, dict, dict]:
        request_id = uuid.uuid4().hex
        headers = {"Content-Type": "application/json", "Cache-Control": "no-store",
                   "X-Content-Type-Options": "nosniff", "X-Request-ID": request_id,
                   "Vary": "Origin"}
        if origin == STAGING_ORIGIN:
            headers["Access-Control-Allow-Origin"] = STAGING_ORIGIN
        if not self.semaphore.acquire(blocking=False):
            self.metrics["concurrency_rejected"] += 1
            return 503, {"error": {"code": "CONCURRENCY_LIMITED", "request_id": request_id},
                         "provenance_status": "UNVERIFIABLE"}, headers
        try:
            with self.rate_lock:
                self.request_times.append(self.clock())
                while self.request_times and self.clock() - self.request_times[0] >= 60:
                    self.request_times.popleft()
            if origin is not None and origin != STAGING_ORIGIN:
                raise GatewayError(403, "ORIGIN_NOT_ALLOWED")
            if method != "GET":
                raise GatewayError(405, "METHOD_NOT_ALLOWED")
            if len(target) > 2048:
                raise GatewayError(414, "URI_TOO_LONG")
            parsed = urlsplit(target)
            if parsed.scheme or parsed.netloc or not parsed.path.startswith("/"):
                raise GatewayError(400, "INVALID_PATH")
            query = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True)
            if any(len(value) != 1 for value in query.values()):
                raise GatewayError(400, "INVALID_QUERY")
            if parsed.path == "/health":
                if query:
                    raise GatewayError(400, "INVALID_QUERY")
                return 200, {"status": "ok", "service": "con59-devnet-read-only"}, headers
            self._rate(client)
            if parsed.path == "/ready":
                if query:
                    raise GatewayError(400, "INVALID_QUERY")
                try:
                    snap = self.index.snapshot()
                    return 200, {"status": "ready", "genesis": GENESIS, "program_id": PROGRAM,
                                 "source": snap["context"]["source"]}, headers
                except GatewayError:
                    return 503, {"status": "unready", "reason": "RPC_UNVERIFIABLE"}, headers
            if parsed.path not in ("/v1/network", "/v1/program", "/v1/agents", "/v1/workorders") and not re.fullmatch(
                    r"/v1/(?:agents|workorders)/[1-9A-HJ-NP-Za-km-z]{32,44}", parsed.path):
                raise GatewayError(404, "ROUTE_NOT_FOUND")
            allowed = {"limit", "cursor", "status"} if parsed.path in ("/v1/agents", "/v1/workorders") else set()
            if set(query) - allowed:
                raise GatewayError(400, "INVALID_QUERY")
            snap = self.index.snapshot()
            context = snap["context"]
            if parsed.path == "/v1/network":
                data = {"network": NETWORK, "genesis_hash": GENESIS, "status": "verified"}
            elif parsed.path == "/v1/program":
                data = {"program_id": PROGRAM, "idl_sha256": IDL_SHA256, "mint": MINT,
                        "token_program": TOKEN, "token_decimals": 6}
            else:
                kind = "agents" if parsed.path.startswith("/v1/agents") else "work_orders"
                key = "agent_account" if kind == "agents" else "work_order_account"
                if parsed.path in ("/v1/agents", "/v1/workorders"):
                    status = query.get("status", [None])[0]
                    if status is not None and status not in ({"Active", "OwnerSuspended", "AdminSuspended", "Revoked"}
                                                              if kind == "agents" else {"Draft", "Open", "Claimed", "Submitted", "Verified", "Settled", "Cancelled", "Expired"}):
                        raise GatewayError(400, "INVALID_FILTER")
                    records = [row for row in snap[kind] if status is None or row["status"] == status]
                    try:
                        limit = query.get("limit", ["20"])[0]
                        if not re.fullmatch(r"[1-9][0-9]?", limit) or int(limit) > MAX_PAGE:
                            raise GatewayError(400, "INVALID_LIMIT")
                        page = paginate(records, key, limit=limit, cursor=query.get("cursor", [None])[0],
                                        scope={"network": NETWORK, "genesis": GENESIS, "program": PROGRAM,
                                               "idl": IDL_SHA256, "provider": context["provider"],
                                               "slot": context["slot_max"], "kind": kind, "status": status})
                    except CursorError as exc:
                        raise GatewayError(exc.status, exc.code) from exc
                    data = page
                else:
                    pubkey = parsed.path.rsplit("/", 1)[-1]
                    try:
                        b58decode(pubkey, 32)
                    except DiscoveryError as exc:
                        raise GatewayError(400, "INVALID_PUBKEY") from exc
                    data = next((row for row in snap[kind] if row[key] == pubkey), None)
                    if data is None:
                        raise GatewayError(404, "ACCOUNT_NOT_FOUND")
            self.metrics["requests_ok"] += 1
            return 200, {"data": data, "provenance": context,
                         "advisory_only": True, "is_financial_authority": False}, headers
        except (GatewayError, ValueError) as exc:
            code = exc.code if isinstance(exc, GatewayError) else "INVALID_QUERY"
            status = exc.status if isinstance(exc, GatewayError) else 400
            self.metrics["requests_rejected"] += 1
            return status, {"error": {"code": code, "request_id": request_id},
                            "provenance_status": "UNVERIFIABLE"}, headers
        finally:
            self.semaphore.release()


def serve(gateway: Gateway, host: str = "127.0.0.1", port: int = 8765) -> None:
    if host not in ("127.0.0.1", "::1"):
        raise ValueError("Public binding requires separately approved hosting")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            started = time.monotonic()
            origin = self.headers.get("Origin")
            status, body, headers = gateway.handle("GET", self.path, origin=origin,
                                                   client=self.client_address[0])
            encoded = json.dumps(body, separators=(",", ":")).encode()
            self.send_response(status)
            for name, value in headers.items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
            emit("INFO", "con59-gateway", "http_read", network=NETWORK, program_id=PROGRAM,
                 trace_id=headers["X-Request-ID"], status=str(status),
                 error_code=body.get("error", {}).get("code"),
                 rpc_provider=body.get("provenance", {}).get("provider"),
                 resource_type=("agents" if self.path.startswith("/v1/agents") else
                                "workorders" if self.path.startswith("/v1/workorders") else "control"),
                 slot=body.get("provenance", {}).get("slot_max"),
                 cache_hit=("HIT" if body.get("provenance", {}).get("source") == "CACHED_VERIFIED" else "MISS"),
                 duration_ms=(time.monotonic() - started) * 1000)

        def do_POST(self):
            self.send_error(405, "METHOD_NOT_ALLOWED")

    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--secondary-rpc", help="operator-approved HTTPS Devnet RPC URL")
    parser.add_argument("--secondary-host", help="exact public DNS hostname for secondary RPC")
    args = parser.parse_args()
    if bool(args.secondary_rpc) != bool(args.secondary_host):
        parser.error("secondary RPC and exact hostname must be supplied together")
    secondary = None
    if args.secondary_rpc:
        secondary = Provider("secondary-devnet", JsonRpc(args.secondary_rpc,
            approved_hosts=frozenset({args.secondary_host})))
    serve(Gateway(Index(Provider("official-devnet", JsonRpc()), secondary)))
