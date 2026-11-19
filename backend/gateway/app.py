"""Minimal first-stage gateway for an UNMODIFIED official PolyStrata HTTP server.

This intentionally implements only the standard inference transport. Legacy
Mikuchin session, image-tool and answer-budget semantics are explicitly refused
until their adapter is implemented; silently dropping these would corrupt chats.

No dependency outside the Python standard library is required.
"""
from __future__ import annotations

import argparse
import hmac
import http.client
import json
import logging
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

LOG = logging.getLogger("mikuchin.gateway")
MAX_BODY_BYTES = 8 * 1024 * 1024
INFERENCE_POSTS = frozenset((
    "/v1/chat/completions", "/v1/messages", "/v1/responses",
    "/v1/images/generations",
))
INFERENCE_GETS = frozenset(("/v1/models", "/models"))
UNPORTED_FIELDS = frozenset((
    "strata_session_id", "mikuchin_stateless", "strata_image_tool",
    "answer_budget_tokens",
))
IMAGE_PATH = re.compile(r"^/v1/images/files/[a-f0-9]{32}\.png$")


class GatewayServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, *, api_key: str, upstream_key: str,
                 upstream_host: str, upstream_port: int, allowed_origins=()):
        if not api_key or not upstream_key:
            raise ValueError("Both gateway and upstream API keys are required")
        if upstream_host not in ("127.0.0.1", "::1", "localhost"):
            raise ValueError("The upstream service must be bound to loopback")
        if not 1 <= upstream_port <= 65535:
            raise ValueError("Invalid upstream port")
        self.api_key = api_key
        self.upstream_key = upstream_key
        self.upstream_host = upstream_host
        self.upstream_port = upstream_port
        self.allowed_origins = frozenset(allowed_origins)
        super().__init__(address, GatewayHandler)


class GatewayHandler(BaseHTTPRequestHandler):
    server: GatewayServer
    protocol_version = "HTTP/1.1"
    server_version = "MikuchinGateway/0.1"

    def log_message(self, fmt, *args):
        # Deliberately do not log request bodies, image prompts or Authorization.
        LOG.info("client=%s %s", self.client_address[0], fmt % args)

    def _json(self, status: int, data: dict):
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(payload)

    def _send_cors_headers(self):
        origin = self.headers.get("Origin", "")
        if origin and origin in self.server.allowed_origins:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")

    def _error(self, status: int, message: str, code="gateway_error"):
        self.close_connection = True
        self._json(status, {"error": {"message": message, "type": code}})

    def _authorized(self):
        value = self.headers.get("Authorization", "")
        candidate = value[7:] if value.startswith("Bearer ") else ""
        if not candidate or not hmac.compare_digest(candidate, self.server.api_key):
            self._error(401, "Missing or invalid gateway API key", "unauthorized")
            return False
        origin = self.headers.get("Origin", "")
        if origin:
            # Requests from the gateway's own origin are normal; other origins
            # must be explicitly enabled (no wildcard CORS access).
            same_origin = (urlsplit(origin).netloc.lower() ==
                           self.headers.get("Host", "").lower())
            if not same_origin and origin not in self.server.allowed_origins:
                self._error(403, "Cross-origin request not permitted", "forbidden")
                return False
        return True

    def do_OPTIONS(self):
        origin = self.headers.get("Origin", "")
        requested = self.headers.get("Access-Control-Request-Method", "")
        if origin in self.server.allowed_origins and requested in ("GET", "POST"):
            self.send_response(204)
            self._send_cors_headers()
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
            self.send_header("Content-Length", "0")
            self.end_headers()
        else:
            self._error(403, "Cross-origin requests are disabled by default", "forbidden")

    def do_GET(self):
        if not self._authorized():
            return
        if not self.path.startswith("/") or self.path.startswith("//"):
            self._error(400, "Invalid request target")
            return
        path = urlsplit(self.path).path
        if path == "/health":
            try:
                conn = http.client.HTTPConnection(self.server.upstream_host,
                                                  self.server.upstream_port, timeout=2)
                try:
                    conn.request("GET", "/health", headers={
                        "Authorization": "Bearer " + self.server.upstream_key})
                    response = conn.getresponse()
                    reachable = response.status == 200
                    response.read()
                finally:
                    conn.close()
            except (OSError, TimeoutError, http.client.HTTPException):
                reachable = False
            self._json(200 if reachable else 503, {
                "status": "ok" if reachable else "degraded",
                "component": "mikuchin-gateway", "official_polystrata_reachable": reachable,
            })
            return
        if path not in INFERENCE_GETS and not IMAGE_PATH.fullmatch(path):
            self._error(404, "Endpoint is not yet available on the native gateway", "not_found")
            return
        self._proxy("GET")

    def do_POST(self):
        if not self._authorized():
            return
        if not self.path.startswith("/") or self.path.startswith("//"):
            self._error(400, "Invalid request target")
            return
        path = urlsplit(self.path).path
        if path not in INFERENCE_POSTS:
            self._error(404, "Endpoint is not yet available on the native gateway", "not_found")
            return
        if self.headers.get("Transfer-Encoding"):
            self._error(411, "Chunked request bodies are not supported yet")
            return
        raw_length = self.headers.get("Content-Length", "")
        try:
            size = int(raw_length)
        except ValueError:
            self._error(411, "Content-Length is required")
            return
        if size < 0 or size > MAX_BODY_BYTES:
            self._error(413, "Request body exceeds gateway limit")
            return
        body = self.rfile.read(size)
        if len(body) != size:
            self._error(400, "Incomplete request body")
            return
        try:
            request = json.loads(body)
        except (ValueError, UnicodeDecodeError):
            self._error(400, "Expected a JSON request body")
            return
        if not isinstance(request, dict):
            self._error(400, "Expected a JSON object")
            return
        unsupported = sorted(UNPORTED_FIELDS.intersection(request))
        if unsupported:
            self._error(501,
                        "Mikuchin semantics not yet ported: " + ", ".join(unsupported),
                        "feature_not_ported")
            return
        self._proxy("POST", body)

    def _proxy(self, method: str, body: bytes | None = None):
        conn = http.client.HTTPConnection(self.server.upstream_host,
                                          self.server.upstream_port, timeout=1800)
        sent_headers = False
        headers = {
            "Authorization": "Bearer " + self.server.upstream_key,
            "Accept": self.headers.get("Accept", "application/json"),
            "Accept-Encoding": "identity",
        }
        if body is not None:
            headers["Content-Type"] = "application/json"
        try:
            conn.request(method, self.path, body=body, headers=headers)
            upstream = conn.getresponse()
            # Do not buffer SSE or tool-call events. Force close framing for
            # clients; upstream's chunking is decoded by HTTPResponse.read1().
            self.send_response(upstream.status)
            for name in ("Content-Type", "Retry-After"):
                value = upstream.getheader(name)
                if value is not None:
                    self.send_header(name, value)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.send_header("X-Content-Type-Options", "nosniff")
            self._send_cors_headers()
            self.end_headers()
            sent_headers = True
            self.close_connection = True
            while True:
                data = upstream.read1(65536)
                if not data:
                    break
                self.wfile.write(data)
                self.wfile.flush()
        except (OSError, TimeoutError, http.client.HTTPException) as exc:
            # Never retry a POST automatically: upstream may have accepted it.
            LOG.warning("upstream failure class=%s method=%s", type(exc).__name__, method)
            if not sent_headers:
                self._error(502, "Official PolyStrata is unavailable", "bad_gateway")
            self.close_connection = True
        finally:
            conn.close()


def main():
    parser = argparse.ArgumentParser(description="Native PolyStrata Mikuchin development gateway")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=15249,
                        help="Isolated development port; production is planned for 15239")
    parser.add_argument("--upstream-port", type=int, default=15240)
    args = parser.parse_args()
    gateway_key = os.environ.get("MIKUCHIN_GATEWAY_API_KEY", "")
    upstream_key = os.environ.get("MIKUCHIN_UPSTREAM_API_KEY", "")
    if not gateway_key or not upstream_key:
        parser.error("Set MIKUCHIN_GATEWAY_API_KEY and MIKUCHIN_UPSTREAM_API_KEY")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    origins = tuple(x.strip() for x in os.environ.get("MIKUCHIN_ALLOWED_ORIGINS", "").split(",")
                    if x.strip())
    with GatewayServer((args.host, args.port), api_key=gateway_key,
                       upstream_key=upstream_key, upstream_host="127.0.0.1",
                       upstream_port=args.upstream_port, allowed_origins=origins) as server:
        LOG.info("Gateway on %s:%d; official PolyStrata on 127.0.0.1:%d",
                 args.host, args.port, args.upstream_port)
        try:
            server.serve_forever(poll_interval=.2)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
