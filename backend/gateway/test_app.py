"""Network contract tests against a fake official PolyStrata (no models/paid calls).

Run from the repository root: python -m unittest discover -s backend/gateway -v
"""
from __future__ import annotations

import http.client
import json
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:
    from .app import GatewayServer
except ImportError:
    from app import GatewayServer


class FakeOfficial(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    seen = []
    lock = threading.Lock()
    hold_second_event = False
    release_second_event = threading.Event()
    second_event_sent = threading.Event()
    def log_message(self, *_args):
        pass

    def send_bytes(self, status, payload, content_type="application/json"):
        self.send_response(status)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Content-Type", content_type)
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.headers.get("Authorization") != "Bearer official-test-secret":
            self.send_bytes(401, b'{"error":"wrong upstream key"}')
            return
        if self.path == "/health":
            self.send_bytes(200, b'{"status":"ok"}')
        elif self.path == "/v1/models":
            self.send_bytes(200, b'{"data":[{"id":"official-model"}]}')
        else:
            self.send_bytes(404, b'{"error":"not found"}')

    def do_POST(self):
        size = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(size))
        with self.lock:
            self.seen.append((self.path, payload, self.headers.get("Authorization")))
        if self.headers.get("Authorization") != "Bearer official-test-secret":
            self.send_bytes(401, b'{"error":"wrong upstream key"}')
            return
        if payload.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            self.wfile.write(b'data: {"delta":"first"}\n\n')
            self.wfile.flush()
            if FakeOfficial.hold_second_event:
                FakeOfficial.release_second_event.wait(timeout=3)
            else:
                time.sleep(.22)
            self.wfile.write(b'data: {"delta":"second"}\n\n')
            self.wfile.flush()
            FakeOfficial.second_event_sent.set()
        else:
            self.send_bytes(200, json.dumps({"reply":payload.get("messages",[]),
                                              "upstream":"unmodified"}).encode())


class GatewayContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.upstream = ThreadingHTTPServer(("127.0.0.1", 0), FakeOfficial)
        cls.upstream.daemon_threads = True
        cls.gateway = GatewayServer(("127.0.0.1", 0), api_key="client-test-secret",
                                    upstream_key="official-test-secret",
                                    upstream_host="127.0.0.1",
                                    upstream_port=cls.upstream.server_address[1])
        cls.threads = []
        for server in (cls.upstream, cls.gateway):
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            cls.threads.append(thread)

    @classmethod
    def tearDownClass(cls):
        for server in (cls.gateway, cls.upstream):
            server.shutdown()
            server.server_close()
        for thread in cls.threads:
            thread.join(timeout=2)

    def request(self, method, path, *, payload=None, key="client-test-secret", origin=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.gateway.server_address[1], timeout=5)
        headers = {"Authorization": "Bearer " + key} if key else {}
        if origin is not None:
            headers["Origin"] = origin
        body = None
        if payload is not None:
            body = json.dumps(payload).encode()
            headers["Content-Type"] = "application/json"
        conn.request(method, path, body=body, headers=headers)
        response = conn.getresponse()
        result = response.status, response.read()
        conn.close()
        return result

    def test_health_and_native_models_endpoint(self):
        status, data = self.request("GET", "/health")
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(data)["official_polystrata_reachable"])
        status, data = self.request("GET", "/v1/models")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(data)["data"][0]["id"], "official-model")

    def test_unauthorized_and_foreign_origin(self):
        self.assertEqual(self.request("GET", "/v1/models", key=None)[0], 401)
        self.assertEqual(self.request("GET", "/v1/models", key="wrong")[0], 401)
        self.assertEqual(self.request("GET", "/v1/models", origin="https://evil.example")[0], 403)
        local_origin = f"http://127.0.0.1:{self.gateway.server_address[1]}"
        self.assertEqual(self.request("GET", "/v1/models", origin=local_origin)[0], 200)

    def test_private_routes_not_forwarded(self):
        for path in ("/slots/0?action=restore", "/v1/mikuchin/image-jobs",
                     "/config", "/v1/strata/sessions"):
            self.assertEqual(self.request("GET", path)[0], 404, path)
        self.assertEqual(self.request("POST", "/unload", payload={})[0], 404)

    def test_unported_mikuchin_semantics_fail_explicitly(self):
        for key in ("strata_session_id", "mikuchin_stateless",
                    "strata_image_tool", "answer_budget_tokens"):
            status, result = self.request("POST", "/v1/chat/completions",
                                          payload={"messages":[], key: "x"})
            self.assertEqual(status, 501, key)
            self.assertIn(key.encode(), result)

    def test_standard_chat_and_upstream_key_isolation(self):
        before = len(FakeOfficial.seen)
        messages = [{"role":"user","content":"only native backend"}]
        status, data = self.request("POST", "/v1/chat/completions",
                                    payload={"model":"official-model", "messages":messages})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(data)["reply"], messages)
        self.assertEqual(len(FakeOfficial.seen), before + 1)
        self.assertEqual(FakeOfficial.seen[-1][2], "Bearer official-test-secret")

    def test_parallel_requests_stay_isolated(self):
        def one(n):
            status, data = self.request("POST", "/v1/chat/completions",
                                        payload={"messages":[{"role":"user","content":str(n)}]})
            return status, json.loads(data)["reply"][0]["content"]
        with ThreadPoolExecutor(max_workers=6) as executor:
            outcome = list(executor.map(one, range(12)))
        self.assertEqual(outcome, [(200,str(n)) for n in range(12)])

    def test_sse_first_event_is_not_buffered_until_last_event(self):
        FakeOfficial.hold_second_event = True
        FakeOfficial.release_second_event.clear()
        FakeOfficial.second_event_sent.clear()
        conn = http.client.HTTPConnection("127.0.0.1", self.gateway.server_address[1], timeout=5)
        try:
            body = json.dumps({"messages":[], "stream":True}).encode()
            conn.request("POST", "/v1/chat/completions", body=body,
                         headers={"Authorization":"Bearer client-test-secret", "Content-Type":"application/json"})
            response = conn.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(response.getheader("Content-Type"), "text/event-stream")
            chunk = response.read1(65536)
            self.assertIn(b'first', chunk)
            self.assertFalse(FakeOfficial.second_event_sent.is_set(),
                             "Gateway must forward first SSE event before the upstream sends another")
            FakeOfficial.release_second_event.set()
            rest = response.read()
            self.assertIn(b'second', rest)
        finally:
            FakeOfficial.release_second_event.set()
            FakeOfficial.hold_second_event = False
            conn.close()

    def test_no_default_auth_secrets(self):
        with self.assertRaises(ValueError):
            GatewayServer(("127.0.0.1",0), api_key="", upstream_key="secret",
                          upstream_host="127.0.0.1", upstream_port=15240)
        with self.assertRaises(ValueError):
            GatewayServer(("127.0.0.1",0), api_key="valid", upstream_key="secret",
                          upstream_host="192.168.0.10", upstream_port=15240)

    def test_explicit_origin_allows_preflight_and_forwards_model_list(self):
        server = GatewayServer(("127.0.0.1", 0), api_key="client-test-secret",
                               upstream_key="official-test-secret", upstream_host="127.0.0.1",
                               upstream_port=self.upstream.server_address[1],
                               allowed_origins=("https://trusted.example",))
        runner = threading.Thread(target=server.serve_forever, daemon=True)
        runner.start()
        try:
            conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=4)
            conn.request("OPTIONS", "/v1/models", headers={
                "Origin":"https://trusted.example", "Access-Control-Request-Method":"GET"})
            res = conn.getresponse()
            self.assertEqual(res.status, 204)
            self.assertEqual(res.getheader("Access-Control-Allow-Origin"), "https://trusted.example")
            res.read()
            conn.request("GET", "/v1/models", headers={
                "Authorization":"Bearer client-test-secret", "Origin":"https://trusted.example"})
            res = conn.getresponse()
            self.assertEqual(res.status, 200)
            self.assertEqual(res.getheader("Access-Control-Allow-Origin"), "https://trusted.example")
            res.read()
            conn.close()
        finally:
            server.shutdown()
            server.server_close()
            runner.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
