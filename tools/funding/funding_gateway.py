#!/usr/bin/env python3
"""AeroSettle Funding Gateway: local, read-only."""

import argparse
import json
import re

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

from funding_preflight import audit

BASE58 = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")


def parse_request(path, config):
    url = urlsplit(path)

    if url.path != "/preflight":
        raise ValueError("Ruta desconocida")

    values = parse_qs(url.query, keep_blank_values=True)

    if set(values) - {"wallet", "work_order"}:
        raise ValueError("Parámetro no permitido")

    if any(len(v) != 1 for v in values.values()):
        raise ValueError("Parámetros duplicados")

    wallet = values.get("wallet", [""])[0]
    order = values.get("work_order", [None])[0]

    if not BASE58.fullmatch(wallet):
        raise ValueError("Wallet inválida")

    if order is not None and not BASE58.fullmatch(order):
        raise ValueError("WorkOrder inválida")

    return SimpleNamespace(
        wallet=wallet,
        work_order=order,
        rpc_url=config.rpc_url,
        idl=config.idl,
    )


def create_handler(config):
    class Handler(BaseHTTPRequestHandler):

        def send_json(self, status, payload):
            body = json.dumps(
                payload, ensure_ascii=False
            ).encode("utf-8")

            self.send_response(status)
            self.send_header(
                "Content-Type", "application/json"
            )
            self.send_header("Cache-Control", "no-store")
            self.send_header(
                "X-Content-Type-Options", "nosniff"
            )
            self.send_header(
                "Content-Length", str(len(body))
            )
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            route = urlsplit(self.path).path

            if route == "/health":
                self.send_json(200, {
                    "status": "ok",
                    "service": "aerosettle-funding-gateway",
                    "mode": "read-only",
                    "network": "Localnet",
                })
                return

            if route != "/preflight":
                self.send_json(404, {
                    "error": "Not found"
                })
                return

            try:
                request = parse_request(
                    self.path, config
                )

                report, ready = audit(request)

                self.send_json(200, {
                    "ready": ready,
                    "report": report,
                })

            except ValueError as error:
                self.send_json(400, {
                    "error": str(error)
                })

            except Exception as error:
                self.send_json(409, {
                    "error": (
                        "Preflight bloqueado: "
                        + str(error)
                    )
                })

        def do_POST(self):
            self.send_json(405, {
                "error": "Servicio de sólo lectura"
            })

        def log_message(self, fmt, *args):
            print(
                "[funding-gateway] request processed",
                flush=True
            )

    return Handler


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--port", type=int, default=8788
    )
    parser.add_argument(
        "--rpc-url",
        default="http://127.0.0.1:8899",
    )
    parser.add_argument(
        "--idl",
        default="target/idl/aerosettle.discovery.json",
    )

    config = parser.parse_args()

    server = ThreadingHTTPServer(
        ("127.0.0.1", config.port),
        create_handler(config),
    )

    print("✅ AeroSettle Funding Gateway")
    print(f"✅ http://127.0.0.1:{config.port}")
    print("✅ GET /health")
    print("✅ GET /preflight")
    print("✅ READ-ONLY")

    server.serve_forever()


if __name__ == "__main__":
    main()
