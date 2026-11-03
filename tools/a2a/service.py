"""Read-only HTTP surface for signed A2A cards and the searchable catalog."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from urllib.parse import parse_qs, urlsplit

from .catalog import CardCatalog
from .cards import CardError

FILTERS = frozenset({"skill", "category", "modality", "capability", "version",
                     "agent_id", "organization_id"})


def route(path: str, host: str, catalog: CardCatalog, *, now: int | None = None) -> tuple[int, dict]:
    parsed = urlsplit(path)
    if parsed.fragment:
        return 400, {"error": "INVALID_QUERY"}
    if parsed.path == "/.well-known/agent-card.json":
        if parsed.query or ":" in host or not host:
            return 400, {"error": "INVALID_HOST"}
        card = catalog.by_domain(host.lower(), now=now)
        return (200, card) if card else (404, {"error": "CARD_NOT_FOUND"})
    if parsed.path == "/a2a/cards":
        query = parse_qs(parsed.query, keep_blank_values=True, max_num_fields=8)
        if any(key not in FILTERS or len(values) != 1 or not values[0] or
               len(values[0]) > 128 for key, values in query.items()):
            return 400, {"error": "INVALID_QUERY"}
        return 200, {"cards": catalog.search(now=now,
            **{key: values[0] for key, values in query.items()}),
            "is_executable": False}
    parts = parsed.path.split("/")
    if len(parts) in (4, 5) and parts[:3] == ["", "a2a", "cards"] and \
            parts[3] and not parsed.query:
        if len(parts) == 5 and parts[4] == "verify":
            try:
                return 200, catalog.verify(parts[3], now=now)
            except CardError:
                return 404, {"error": "CARD_NOT_FOUND"}
        if len(parts) == 4:
            card = catalog.get(parts[3], now=now)
            return (200, card) if card else (404, {"error": "CARD_NOT_FOUND"})
    return 404, {"error": "NOT_FOUND"}


def handler_for(catalog: CardCatalog):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            status, body = route(self.path, self.headers.get("Host", ""), catalog)
            encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(encoded)

        def do_POST(self):
            self.send_response(405)
            self.send_header("Allow", "GET")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *_):
            pass

    return Handler


def serve(catalog: CardCatalog, address: str = "127.0.0.1", port: int = 8089):
    httpd = ThreadingHTTPServer((address, port), handler_for(catalog))
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()
