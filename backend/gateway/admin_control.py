"""Loopback-only supervisor control, separate from the public Gateway."""
from __future__ import annotations

import hmac
import logging
import os
import json
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from . import admin_credential

RELOAD = "/admin/reload-image-api-stack"
OPERATIONS = "/admin/operations/"


class ControlServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, supervisor):
        self.supervisor = supervisor
        self.lock = threading.Lock()
        self.operation = None
        self.last_request = 0.0
        super().__init__(("127.0.0.1", 0), ControlHandler)
        self.local_token = None
        try:
            self.local_token = admin_credential.issue(supervisor.data_dir, os.getpid(), self.server_port)
        except (OSError, ValueError, RuntimeError):
            logging.getLogger(__name__).warning("Local management credential unavailable; explicit authentication required")

    def server_close(self):
        try:
            if self.local_token:
                (self.supervisor.data_dir / admin_credential.NAME).unlink(missing_ok=True)
        except OSError:
            pass  # stale credential cannot authenticate a new Supervisor
        finally:
            self.local_token = None
            super().server_close()

    def submit(self):
        with self.lock:
            if self.operation and self.operation["phase"] in ("queued", "checking", "reloading"):
                return 409, {"accepted": False, "reason": "operation-active"}
            if time.monotonic() - self.last_request < 10:
                return 429, {"accepted": False, "reason": "reload-rate-limited"}
            self.last_request = time.monotonic()
            self.operation = {"id": uuid.uuid4().hex, "phase": "queued", "done": False}
            return 202, {"accepted": True, "operation_id": self.operation["id"], "phase": "queued"}

    def claim(self):
        with self.lock:
            if self.operation and self.operation["phase"] == "queued":
                self.operation["phase"] = "checking"
                return True
            return False

    def update(self, phase, reason=""):
        with self.lock:
            self.operation.update(phase=phase, reason=reason, done=phase in ("done", "blocked", "failed"))

    def lookup(self, ident):
        with self.lock:
            if self.operation and self.operation["id"] == ident:
                return dict(self.operation)
            return None


class ControlHandler(BaseHTTPRequestHandler):
    def setup(self):
        self.request.settimeout(3)
        super().setup()

    def log_message(self, *args):
        pass

    def reply(self, status, data):
        raw = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def authorized(self):
        if (self.client_address[0] != "127.0.0.1" or
                self.headers.get("Host") != f"127.0.0.1:{self.server.server_port}" or
                any(self.headers.get(h) for h in ("Origin", "Forwarded", "X-Forwarded-For", "X-Forwarded-Host", "X-Real-IP", "CF-Connecting-IP", "CF-Ray"))):
            self.reply(403, {"error": "local operator only"})
            return False
        auth = self.headers.get("Authorization", "").encode("utf-8")
        normal = hmac.compare_digest(auth, ("Bearer " + self.server.supervisor.api_key).encode("utf-8"))
        local = self.server.local_token
        dedicated = bool(local) and hmac.compare_digest(auth, ("Bearer " + local).encode("utf-8"))
        if not normal and not dedicated:
            self.reply(401, {"error": "unauthorized"})
            return False
        return True

    def do_GET(self):
        if not self.authorized():
            return
        if self.path == RELOAD + "/eligibility":
            allowed, reason = self.server.supervisor._manual_eligibility()
            self.reply(200, {"allowed": allowed, "reason": reason})
        elif self.path.startswith(OPERATIONS):
            found = self.server.lookup(self.path[len(OPERATIONS):])
            self.reply(200 if found else 404, found or {"error": "unknown operation"})
        else:
            self.reply(404, {"error": "unknown endpoint"})

    def do_POST(self):
        if not self.authorized():
            return
        if self.path != RELOAD:
            self.reply(404, {"error": "unknown endpoint"})
            return
        if self.headers.get("Transfer-Encoding") or self.headers.get("Content-Length", "0") != "0":
            self.reply(400, {"error": "empty body required; force is not supported"})
            return
        status, data = self.server.submit()
        self.reply(status, data)
