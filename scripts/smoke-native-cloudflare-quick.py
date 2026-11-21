"""Disposable public Cloudflare Quick Tunnel smoke with a MOCK Native stack.

Creates a random Key, ephemeral data directory, and mock official engine. The
REAL launcher, model files, user gallery, production 15239 and any stable/Native
named-Tunnel token are never read or changed. Only GET /health and GET / are
checked remotely, without Authorization. The Quick Tunnel is terminated.
This validates public HTTPS plumbing, NOT any permanent hostname or Android.
"""
from __future__ import annotations

import argparse
import http.client
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QUICK_URL = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com", re.I)


def spare_port():
    with socket.socket(socket.AF_INET) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def local_health(port, key):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
    try:
        conn.request("GET", "/health", headers={"Authorization": "Bearer " + key})
        reply = conn.getresponse()
        body = json.loads(reply.read(2048))
        return reply.status == 200 and body.get("component") == "mikuchin-gateway"
    finally:
        conn.close()


def public_get(base_url, path):
    # No Authorization or cookies cross this public network check.
    request = urllib.request.Request(base_url + path, headers={
        "User-Agent": "Mikuchin-Native-P3-ReadOnly-Smoke"})
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            return response.status, response.read(4096)
    except urllib.error.HTTPError as err:
        return err.code, err.read(4096)


def smoke(exe, wait_seconds):
    with tempfile.TemporaryDirectory(prefix="mikuchin-native-quick-tunnel-") as temp:
        temp_path = Path(temp)
        gateway, upstream, metrics = spare_port(), spare_port(), spare_port()
        while len({gateway, upstream, metrics, 15239, 15240, 15249, 23189}) < 7:
            gateway, upstream, metrics = spare_port(), spare_port(), spare_port()
        key = "native-smoke-" + secrets.token_urlsafe(28)
        log = (temp_path / "supervisor.log").open("w", encoding="utf-8")
        env = dict(os.environ, MIKUCHIN_GATEWAY_API_KEY=key,
                   PYTHONDONTWRITEBYTECODE="1")
        supervisor = subprocess.Popen([
            sys.executable, "-u", "-B", "-m", "backend.gateway.supervisor",
            "--engine", "mock", "--data-dir", str(temp_path),
            "--gateway-port", str(gateway),
            "--upstream-port", str(upstream),
            "--startup-timeout", "25", "--control-stdin",
        ], cwd=ROOT, env=env, stdin=subprocess.PIPE,
            stdout=log, stderr=subprocess.STDOUT, text=True)
        tunnel = None
        try:
            deadline = time.monotonic() + 35
            while time.monotonic() < deadline:
                if supervisor.poll() is not None:
                    raise RuntimeError("mock Native supervisor exited")
                try:
                    if local_health(gateway, key):
                        break
                except (OSError, ValueError, json.JSONDecodeError):
                    pass
                time.sleep(.4)
            else:
                raise TimeoutError("isolated Native Gateway never became healthy")

            tunnel_log = temp_path / "cloudflared.log"
            output = tunnel_log.open("w", encoding="utf-8")
            try:
                tunnel = subprocess.Popen([
                    str(exe), "tunnel", "--no-autoupdate", "--metrics",
                    f"127.0.0.1:{metrics}", "--url", f"http://127.0.0.1:{gateway}",
                ], cwd=temp_path, env={**os.environ, "TUNNEL_TOKEN": ""},
                    stdin=subprocess.DEVNULL, stdout=output,
                    stderr=subprocess.STDOUT)
            finally:
                output.close()

            deadline = time.monotonic() + wait_seconds
            url = None
            verified = False
            last_status = None
            while time.monotonic() < deadline:
                if tunnel.poll() is not None:
                    raise RuntimeError("Quick Tunnel connector exited unexpectedly")
                logs = tunnel_log.read_text(encoding="utf-8", errors="replace")
                match = QUICK_URL.search(logs)
                if match:
                    url = match.group(0)
                    try:
                        status, data = public_get(url, "/health")
                        last_status = status
                        if status == 401 and b"Missing or invalid gateway API key" in data:
                            landing_status, landing = public_get(url, "/")
                            verified = landing_status == 200 and b"Mikuchin" in landing
                            if verified:
                                break
                    except (OSError, TimeoutError, urllib.error.URLError):
                        pass
                time.sleep(3)
            if not verified:
                raise RuntimeError(f"Public HTTPS probe failed (url_generated={bool(url)}, http={last_status})")
            print(json.dumps({
                "passed": True, "public_https": True, "temporary_quick_tunnel": True,
                "native_401_challenge": 401, "public_static_page": 200,
                "original_model": "mock", "paid_api_calls": 0,
                "live_real_gateway_exposed": False,
                "permanent_named_tunnel_verified": False,
            }))
        finally:
            if tunnel is not None and tunnel.poll() is None:
                tunnel.terminate()
                try:
                    tunnel.wait(timeout=12)
                except subprocess.TimeoutExpired:
                    tunnel.kill()
                    tunnel.wait(timeout=10)
            if supervisor.poll() is None:
                try:
                    assert supervisor.stdin is not None
                    supervisor.stdin.write("STOP\n")
                    supervisor.stdin.flush()
                    supervisor.wait(timeout=35)
                except (OSError, subprocess.TimeoutExpired):
                    supervisor.kill()
                    supervisor.wait(timeout=10)
            log.close()
            if supervisor.returncode not in (0, None):
                print("Mock supervisor returned", supervisor.returncode, file=sys.stderr)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cloudflared", type=Path, required=True)
    parser.add_argument("--wait-seconds", type=int, default=85)
    args = parser.parse_args()
    if not args.cloudflared.is_file() or not 15 <= args.wait_seconds <= 150:
        parser.error("valid cloudflared binary and 15..150 wait seconds required")
    smoke(args.cloudflared, args.wait_seconds)


if __name__ == "__main__":
    main()
