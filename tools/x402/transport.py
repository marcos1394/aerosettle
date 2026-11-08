"""Bounded loopback HTTP transport for the x402 V2 offline demo."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPRedirectHandler, ProxyHandler

from .common import MAX_BODY, SandboxError, local_url


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise SandboxError("REDIRECT_FORBIDDEN", 403)


def call(url: str, *, method: str = "GET", headers: dict | None = None,
         body: dict | None = None, timeout: float = 3) -> tuple[int, dict, bytes]:
    local_url(url)
    if method not in {"GET", "POST"}:
        raise SandboxError("METHOD_NOT_ALLOWED")
    data = json.dumps(body, separators=(",", ":")).encode() if body is not None else None
    if data is not None and len(data) > MAX_BODY:
        raise SandboxError("REQUEST_TOO_LARGE")
    request = Request(url, data=data, method=method, headers={
        **(headers or {}), **({"Content-Type": "application/json"} if data is not None else {})})
    opener = build_opener(ProxyHandler({}), _NoRedirect)
    try:
        response = opener.open(request, timeout=timeout)
    except HTTPError as exc:
        response = exc
    except (URLError, TimeoutError, OSError) as exc:
        raise SandboxError("FACILITATOR_UNAVAILABLE", 503) from exc
    with response:
        length = response.headers.get("Content-Length")
        if length is not None and int(length) > MAX_BODY:
            raise SandboxError("RESPONSE_TOO_LARGE", 502)
        content = response.read(MAX_BODY + 1)
        if len(content) > MAX_BODY:
            raise SandboxError("RESPONSE_TOO_LARGE", 502)
        return response.status, dict(response.headers), content


def _handler(service):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def _respond(self, status: int, headers: dict, content: dict):
            body = json.dumps(content, separators=(",", ":")).encode()
            self.send_response(status)
            for key, value in headers.items():
                self.send_header(key, value)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _dispatch(self, method: str):
            try:
                if self.path not in service.paths or method not in service.paths[self.path]:
                    raise SandboxError("NOT_FOUND", 404)
                size = int(self.headers.get("Content-Length", "0"))
                if size < 0 or size > MAX_BODY:
                    raise SandboxError("REQUEST_TOO_LARGE", 413)
                data = json.loads(self.rfile.read(size)) if size else None
                status, headers, content = service.dispatch(method, self.path, dict(self.headers), data)
            except SandboxError as exc:
                status, headers, content = exc.status, {}, {"error": exc.code}
            except Exception:
                status, headers, content = 503, {}, {"error": "SERVICE_UNAVAILABLE"}
            self._respond(status, headers, content)

        def do_GET(self): self._dispatch("GET")
        def do_POST(self): self._dispatch("POST")

    return Handler


class LocalHTTP:
    def __init__(self, service, port: int = 0):
        self.server = ThreadingHTTPServer(("127.0.0.1", port), _handler(service))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def start(self):
        self.thread.start()
        return self

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)

    def __enter__(self): return self.start()
    def __exit__(self, *_): self.close()
