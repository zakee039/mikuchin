"""Disposable end-to-end LAN smoke test for Native Gateway.

Starts only official MOCK Engine, image worker, Gateway on random ports.
Never reads/updates user preferences, production port 15239, tunnel tokens,
model weights, or an existing process. No paid calls.
"""
from __future__ import annotations

import http.client
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def spare_port():
    with socket.socket(socket.AF_INET) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def request(port, path="/health", key=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    try:
        conn.request("GET", path, headers={"Authorization": "Bearer " + key} if key else {})
        response = conn.getresponse()
        payload = response.read(10000)
        return response.status, json.loads(payload)
    finally:
        conn.close()


def main():
    with tempfile.TemporaryDirectory(prefix="mikuchin-native-lan-smoke-") as tmp:
        gateway, official = spare_port(), spare_port()
        while gateway in (official, 15239) or official == 15239:
            gateway, official = spare_port(), spare_port()
        key = "mock-native-lan-isolation-key"
        env = dict(os.environ, MIKUCHIN_GATEWAY_API_KEY=key)
        log_file = Path(tmp) / "supervisor.log"
        with log_file.open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                [sys.executable, "-u", "-B", "-m", "backend.gateway.supervisor",
                 "--engine", "mock", "--data-dir", tmp, "--gateway-port", str(gateway),
                 "--upstream-port", str(official), "--startup-timeout", "30",
                 "--control-stdin", "--lan-access"],
                cwd=ROOT, env=env, stdin=subprocess.PIPE,
                stdout=log, stderr=subprocess.STDOUT, text=True)
            try:
                deadline = time.monotonic() + 40
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise RuntimeError("Supervisor exited prematurely")
                    try:
                        status, body = request(gateway, key=key)
                        if status == 200 and body.get("status") == "ok":
                            break
                    except OSError:
                        pass
                    time.sleep(.3)
                else:
                    raise TimeoutError("Gateway did not become healthy")
                status, body = request(gateway)
                assert status == 401, (status, body)
                assert body["error"]["type"] == "unauthorized"
                status, body = request(gateway, key=key)
                assert status == 200 and body["official_polystrata_reachable"]
                status_info = json.loads((Path(tmp) / "supervisor-status.json").read_text())
                assert status_info["lan_access"] is True
                # Windows netstat identifies the actual bind, not just the
                # supervisor's requested flag. This checks the socket itself.
                lines = subprocess.run(["netstat", "-an", "-p", "TCP"],
                    capture_output=True, text=True, timeout=8).stdout.splitlines()
                assert any("0.0.0.0:" + str(gateway) in line and "LISTEN" in line.upper()
                           for line in lines), "Gateway did not bind all IPv4 interfaces"
                assert not any("0.0.0.0:" + str(official) in line and "LISTEN" in line.upper()
                               for line in lines), "Private engine must never bind LAN"
                print(json.dumps({"passed": True, "gateway_lan_bind": "0.0.0.0",
                                  "gateway_port": gateway, "upstream_loopback": official,
                                  "unauthorized_health": 401, "authenticated_health": 200}))
            finally:
                if process.poll() is None:
                    process.stdin.write("STOP\n")
                    process.stdin.flush()
                    process.wait(timeout=40)
                assert process.returncode == 0, log_file.read_text(errors="replace")[-2000:]


if __name__ == "__main__":
    main()
