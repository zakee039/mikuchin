"""Disposable browser E2E fixture for Native Gateway P0 chat compatibility.

No real GPU, paid image calls, production ports, user data, or credentials.
Start with: python -u -B scripts/smoke-native-chat-browser.py
Prints a JSON port, then runs until the printed stop-file is created.
"""
from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.gateway import app as gateway_app
from backend.gateway.app import GatewayServer
from backend.gateway.characters import CharacterStore
from backend.gateway.conversations import ConversationStore
from backend.gateway.image_jobs import ImageJobStore

TEST_KEY = "native-p0-browser-test-key"
OFFICIAL_KEY = "native-p0-browser-upstream-test-key"


class FakeChatEngine(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    recorded = None

    def log_message(self, *_args):
        pass

    def send_json(self, value):
        raw = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.headers.get("Authorization") != "Bearer " + OFFICIAL_KEY:
            self.send_error(401)
            return
        if self.path == "/health":
            self.send_json({"status": "ok", "model": "browser-e2e-mock",
                            "loaded": True, "images": False})
        elif self.path == "/api/models":
            self.send_json({"models": [{"id": "browser-e2e-mock", "current": True}]})
        elif self.path == "/v1/models":
            self.send_json({"data": [{"id": "browser-e2e-mock"}]})
        elif self.path == "/metrics":
            self.send_json({"live":{"state":"idle"},"totals":{},"hardware":{}})
        else:
            self.send_error(404)

    def do_POST(self):
        if self.headers.get("Authorization") != "Bearer " + OFFICIAL_KEY:
            self.send_error(401)
            return
        count = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(count))
        record = {"fields":sorted(body), "messages":body.get("messages", []),
                  "image_tool":body.get("strata_image_tool", "absent"),
                  "budget":body.get("answer_budget_tokens", "absent")}
        with self.recorded.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        if body.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            for data in [
                {"choices":[{"delta":{"content":"P0_BROWSER_OK"},"finish_reason":None}]},
                {"choices":[{"delta":{},"finish_reason":"stop"}],
                 "usage":{"prompt_tokens":14,"completion_tokens":3}},
            ]:
                self.wfile.write(b"data: " + json.dumps(data).encode() + b"\n\n")
                self.wfile.flush()
            self.wfile.write(b"data: [DONE]\n\n")
        else:
            self.send_json({"choices":[{"message":{"role":"assistant","content":"P0_BROWSER_OK"},
                                        "finish_reason":"stop"}]})


def main():
    # All state is disposable. Fixture is explicitly stopped by creating the
    # reported control file so Windows processes and ports can be verified free.
    with tempfile.TemporaryDirectory(prefix="mikuchin-p0-browser-") as root:
        directory = Path(root)
        stop_file = directory / "STOP"
        recorded = directory / "forwarded.jsonl"
        FakeChatEngine.recorded = recorded
        official = ThreadingHTTPServer(("127.0.0.1", 0), FakeChatEngine)
        # Preserve the same capability mismatch as a real local Qwen model:
        # Image Studio is available, but the in-chat tool is NOT.
        original_catalog = gateway_app.local_images.catalog
        gateway_app.local_images.catalog = lambda _jobs: ([{"id":"local-mock","available":True}], [])
        gateway = GatewayServer(("127.0.0.1", 0), api_key=TEST_KEY, upstream_key=OFFICIAL_KEY,
                                upstream_host="127.0.0.1", upstream_port=official.server_address[1],
                                conversations=ConversationStore(directory),
                                characters=CharacterStore(directory / "character"),
                                image_jobs=ImageJobStore(directory / "images"))
        threads = [threading.Thread(target=x.serve_forever,daemon=True)
                   for x in (official,gateway)]
        for thread in threads:
            thread.start()
        print(json.dumps({"gateway_port":gateway.server_address[1],
                          "stop_file":str(stop_file), "forwarded_file":str(recorded),
                          "key":TEST_KEY}),flush=True)
        try:
            while not stop_file.exists():
                time.sleep(.2)
        finally:
            gateway_app.local_images.catalog = original_catalog
            for server in (gateway, official):
                server.shutdown()
                server.server_close()
            for thread in threads:
                thread.join(timeout=3)
            # Report only synthetic-test flags, never user credentials.
            if recorded.exists():
                lines = recorded.read_text(encoding="utf-8").splitlines()
                print("forwarded_requests=" + str(len(lines)), flush=True)


if __name__ == "__main__":
    main()
