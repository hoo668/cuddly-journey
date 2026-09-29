#!/usr/bin/env python3
"""Serve normalized IP lookup results as a small JSON HTTP API."""

from __future__ import annotations

import argparse
import hmac
import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

from lookup import lookup


class LookupHandler(BaseHTTPRequestHandler):
    lookup_timeout = 10.0
    api_key: str | None = None

    def send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        request = urlsplit(self.path)
        if request.path == "/health":
            self.send_json(HTTPStatus.OK, {"status": "ok"})
            return
        if request.path != "/api/v1/ip":
            self.send_json(HTTPStatus.NOT_FOUND, {"schema_version": "1.0", "error": "not_found"})
            return

        if self.api_key is not None:
            expected = f"Bearer {self.api_key}"
            if not hmac.compare_digest(self.headers.get("Authorization", ""), expected):
                self.send_json(HTTPStatus.UNAUTHORIZED, {"schema_version": "1.0", "error": "unauthorized"})
                return

        parameters = parse_qs(request.query, keep_blank_values=True)
        if set(parameters) - {"ip"} or len(parameters.get("ip", [])) > 1:
            self.send_json(HTTPStatus.BAD_REQUEST, {"schema_version": "1.0", "error": "invalid_query"})
            return
        if "ip" in parameters and not parameters["ip"][0]:
            self.send_json(HTTPStatus.BAD_REQUEST, {"schema_version": "1.0", "error": "ip_must_not_be_empty"})
            return

        target_ip = parameters.get("ip", [None])[0]
        try:
            result = lookup(target_ip, self.lookup_timeout)
        except ValueError:
            self.send_json(HTTPStatus.BAD_REQUEST, {"schema_version": "1.0", "error": "invalid_ip"})
            return

        status = HTTPStatus.OK if result["ip"] else HTTPStatus.BAD_GATEWAY
        if status == HTTPStatus.BAD_GATEWAY:
            result["error"] = "no_ip_available"
        self.send_json(status, result)

    def log_message(self, format: str, *args: Any) -> None:
        return


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve the IP lookup JSON API.")
    parser.add_argument("--host", default="127.0.0.1", help="Listen address; public binds require IP_LOOKUP_API_KEY")
    parser.add_argument("--port", type=int, default=8080, help="Listen port")
    parser.add_argument("--timeout", type=float, default=10.0, help="Per-source timeout in seconds")
    args = parser.parse_args()

    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    if args.timeout <= 0:
        parser.error("--timeout must be greater than zero")

    api_key = os.environ.get("IP_LOOKUP_API_KEY")
    if args.host not in {"127.0.0.1", "localhost", "::1"} and not api_key:
        parser.error("set IP_LOOKUP_API_KEY before listening on a non-local address")

    LookupHandler.lookup_timeout = args.timeout
    LookupHandler.api_key = api_key
    server = ThreadingHTTPServer((args.host, args.port), LookupHandler)
    print(f"IP lookup API listening on http://{args.host}:{args.port}")
    print("GET /api/v1/ip?ip=1.1.1.1  |  GET /health")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nAPI stopped.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())