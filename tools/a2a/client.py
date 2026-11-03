"""Deny-by-default HTTPS Agent Card discovery with pinned DNS/TLS destination."""
from __future__ import annotations

from dataclasses import dataclass
import http.client
import ipaddress
import json
import socket
import ssl
import time

from .cards import (CardError, EXTENSION_URI, MAX_CARD_BYTES, _https_url, key_id,
                    identity_params, negotiate, validate_card, verify_conatus_card,
                    verify_jws)
from tools.operations.structured_logs import correlation_id, emit, new_trace_id

WELL_KNOWN = "/.well-known/agent-card.json"


@dataclass(frozen=True)
class TrustAnchor:
    domain: str
    publisher_id: str
    public_key: bytes
    expires_at: int
    revoked: bool = False


class _PinnedHttps(http.client.HTTPSConnection):
    def __init__(self, hostname: str, address: str, timeout: float):
        super().__init__(hostname, port=443, timeout=timeout,
                         context=ssl.create_default_context())
        self._address = address

    def connect(self) -> None:
        raw = socket.create_connection((self._address, 443), timeout=self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


def _resolve(host: str) -> tuple[str, ...]:
    records = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    return tuple(sorted({item[4][0] for item in records}))


def _allowed_addresses(addresses: tuple[str, ...]) -> bool:
    if not addresses:
        return False
    try:
        return all(ipaddress.ip_address(item).is_global for item in addresses)
    except ValueError:
        return False


def _fetch_https(host: str, address: str, timeout: float) -> tuple[int, str, bytes]:
    connection = _PinnedHttps(host, address, timeout)
    try:
        connection.request("GET", WELL_KNOWN,
                           headers={"Host": host, "Accept": "application/json",
                                    "User-Agent": "Conatus-A2A-Discovery/1.0"})
        response = connection.getresponse()
        size = response.getheader("Content-Length")
        if size is not None and (not size.isdigit() or int(size) > MAX_CARD_BYTES):
            raise CardError("CARD_TOO_LARGE")
        return response.status, response.getheader("Content-Type") or "", \
            response.read(MAX_CARD_BYTES + 1)
    finally:
        connection.close()


def _unique_json(data: bytes) -> dict:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise CardError("INVALID_SCHEMA")
            result[key] = value
        return result
    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=unique,
                           parse_constant=lambda _: (_ for _ in ()).throw(CardError("INVALID_SCHEMA")))
    except (UnicodeDecodeError, ValueError) as exc:
        raise CardError("INVALID_SCHEMA") from exc
    if not isinstance(value, dict):
        raise CardError("INVALID_SCHEMA")
    return value


class A2ADiscoveryClient:
    def __init__(self, anchors: dict[str, TrustAnchor], *, resolver=_resolve,
                 transport=_fetch_https, timeout: float = 5.0,
                 operational_store=None, conatus_identity_source=None):
        if not 0 < timeout <= 20:
            raise ValueError("Invalid discovery timeout")
        self.anchors = anchors
        self.resolver = resolver
        self.transport = transport
        self.timeout = timeout
        self.operational_store = operational_store
        self.conatus_identity_source = conatus_identity_source

    def _metric(self, name: str, value: int | float = 1, unit: str = "cards") -> None:
        if self.operational_store is not None:
            try:
                self.operational_store.sample(name, value, unit, "a2a")
            except Exception:
                pass

    def discover(self, domain: str, *, now: int | None = None) -> dict:
        started = time.monotonic()
        trace = new_trace_id()
        try:
            host = _https_url("https://" + domain + WELL_KNOWN)
            if host != domain.lower().rstrip(".") or host in ("localhost",) or \
                    host.endswith((".localhost", ".local", ".internal")):
                raise CardError("SSRF_BLOCKED")
            anchor = self.anchors.get(host)
            timestamp = int(time.time()) if now is None else now
            if (anchor is None or anchor.domain != host or anchor.revoked or
                    anchor.expires_at <= timestamp or
                    anchor.publisher_id != key_id(anchor.public_key)):
                raise CardError("UNTRUSTED_CARD")
            try:
                first = tuple(self.resolver(host))
                second = tuple(self.resolver(host))
            except (OSError, ValueError) as exc:
                raise CardError("DISCOVERY_ERROR") from exc
            if (not _allowed_addresses(first) or not _allowed_addresses(second) or
                    set(first) != set(second)):
                raise CardError("SSRF_BLOCKED")
            # Connect to the validated IP itself; TLS still authenticates the hostname.
            try:
                status, content_type, data = self.transport(host, first[0], self.timeout)
            except (OSError, http.client.HTTPException, TimeoutError) as exc:
                raise CardError("DISCOVERY_ERROR") from exc
            if 300 <= status < 400:
                raise CardError("REDIRECT_BLOCKED")
            if status != 200:
                raise CardError("DISCOVERY_ERROR")
            if content_type.split(";", 1)[0].strip().lower() not in (
                    "application/json", "application/a2a+json"):
                raise CardError("INVALID_CONTENT_TYPE")
            if len(data) > MAX_CARD_BYTES:
                raise CardError("CARD_TOO_LARGE")
            card = validate_card(_unique_json(data))
            verify_jws(card, anchor.public_key)
            if any(_https_url(item["url"]) != host for item in card["supportedInterfaces"]):
                raise CardError("INVALID_IDENTITY")
            if any(item.get("uri") == EXTENSION_URI for item in
                   card.get("capabilities", {}).get("extensions", [])):
                if self.conatus_identity_source is None:
                    raise CardError("UNTRUSTED_CARD")
                params = identity_params(card)
                fresh = self.conatus_identity_source(params["agentAccount"])
                if not isinstance(fresh, dict):
                    raise CardError("INVALID_IDENTITY")
                verify_conatus_card(card, fresh, now=timestamp)
            result = negotiate(card, trusted=True, now=timestamp,
                               expires_at=anchor.expires_at)
            if result["status"] != "SUPPORTED":
                if result["status"] == "UNSUPPORTED_VERSION":
                    self._metric("a2a_unsupported_versions")
                raise CardError(result["status"])
            self._metric("a2a_cards_validated")
            emit("INFO", "a2a_discovery", "discover", trace_id=trace,
                 publisher_id=anchor.publisher_id, discovery_source="external",
                 correlation_id=correlation_id(host, anchor.publisher_id),
                 duration_ms=(time.monotonic() - started) * 1000,
                 status="VERIFIED", verification_status="TRUSTED_DISCOVERY_ONLY",
                 schema_version="1.0")
            return {"card": card, "selection": result,
                    "publisher_id": anchor.publisher_id,
                    "verification_status": "TRUSTED_DISCOVERY_ONLY"}
        except CardError as exc:
            self._metric("a2a_cards_rejected")
            if exc.code == "SSRF_BLOCKED":
                self._metric("a2a_ssrf_blocked")
            if exc.code == "INVALID_SIGNATURE":
                self._metric("a2a_invalid_signatures")
            if exc.code in ("DISCOVERY_ERROR", "REDIRECT_BLOCKED"):
                self._metric("a2a_discovery_errors")
            emit("WARNING", "a2a_discovery", "discover", trace_id=trace,
                 discovery_source="external", status="REJECTED",
                 duration_ms=(time.monotonic() - started) * 1000,
                 error_category=exc.code, schema_version="1.0")
            raise
        finally:
            self._metric("a2a_resolution_ms", (time.monotonic() - started) * 1000,
                         "ms")
