"""Real, isolated Native model smoke: official CUDA LLM -> local Vulkan Qwen -> LLM.

Never uses stable 15239, never calls a paid provider, and owns exactly one
temporary supervisor process tree. The Native launcher's own data is untouched.
Run from the repository root with the Native runtime's Python.
"""
from __future__ import annotations

import argparse
import http.client
import json
import os
import secrets
import shutil
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT.parent / "mikuchin-native-runtime"


def request(key, method, path, payload=None, timeout=10):
    conn = http.client.HTTPConnection("127.0.0.1", 15249, timeout=timeout)
    try:
        body = json.dumps(payload).encode() if payload is not None else None
        conn.request(method, path, body=body, headers={
            "Authorization": "Bearer " + key,
            **({"Content-Type": "application/json"} if body else {})})
        response = conn.getresponse()
        data = response.read(500_000)
        result = json.loads(data)
        if response.status >= 300:
            raise RuntimeError(f"{method} {path} failed HTTP {response.status}: {result}")
        return result
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default="local-qwen-official")
    parser.add_argument("--upscale", action="store_true")
    parser.add_argument("--lora", default="none")
    parser.add_argument("--data-dir", default=str(RUNTIME / "native-real-image-smoke-20261120"))
    args = parser.parse_args()
    source = RUNTIME / "launcher-user-data" / "images" / "config" / "native-local-images.json"
    target_dir = Path(args.data_dir).resolve()
    if target_dir == RUNTIME / "launcher-user-data":
        parser.error("smoke test must not use the Native launcher's main data directory")
    target = target_dir / "images" / "config" / "native-local-images.json"
    if not source.is_file():
        parser.error("configure isolated local images first")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    key = secrets.token_urlsafe(40)
    env = dict(os.environ)
    env["MIKUCHIN_GATEWAY_API_KEY"] = key
    config = RUNTIME / "config" / "official-sm86-model-test.json"
    cmd = [sys.executable, "-u", "-B", "-m", "backend.gateway.supervisor",
           "--engine", "strata", "--config", str(config),
           "--data-dir", str(target_dir), "--gateway-port", "15249",
           "--upstream-port", "15240", "--control-stdin",
           "--startup-timeout", "180"]
    log = target_dir / "native-real-smoke-supervisor.log"
    result = None
    with log.open("a", encoding="utf-8") as output:
        proc = subprocess.Popen(cmd, cwd=ROOT, env=env, stdin=subprocess.PIPE,
                                stdout=output, stderr=subprocess.STDOUT, text=True)
        try:
            print("native supervisor PID:", proc.pid, flush=True)
            ready = False
            deadline = time.monotonic() + 220
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    raise RuntimeError("supervisor exited before ready; consult " + str(log))
                try:
                    info = request(key, "GET", "/health")
                    if info["image_worker_ready"] and info["official_polystrata_reachable"]:
                        ready = True
                        print("Native CUDA LLM + Gateway + Worker ready", flush=True)
                        break
                except (ConnectionError, OSError, ValueError, RuntimeError):
                    pass
                time.sleep(1)
            if not ready:
                raise TimeoutError("native supervisor did not become healthy")
            models = request(key, "GET", "/v1/mikuchin/image-models")
            names = [item["id"] for item in models["models"] if item["available"]]
            if args.profile not in names:
                raise RuntimeError("local model not offered in catalog: " + str(names))
            print("available image profiles:", names, flush=True)
            payload = {"prompt":"minimal anime illustration of a small blue cat, clean simple lines",
                       "size":"384x384", "strata_image_profile":args.profile,
                       "strata_upscale":"4x" if args.upscale else "off",
                       "strata_lora_id":args.lora, "response_format":"url"}
            job = request(key, "POST", "/v1/mikuchin/image-jobs", {"request":payload})
            ident = job["id"]
            print("Local image accepted:", ident, flush=True)
            deadline = time.monotonic() + 1500
            phase = None
            while time.monotonic() < deadline:
                item = request(key, "GET", "/v1/mikuchin/image-jobs?id=" + ident)
                if item["phase"] != phase:
                    phase = item["phase"]
                    print("phase:", phase, flush=True)
                if item["state"] in ("success", "failed"):
                    result = item
                    print("result:", json.dumps({
                        "state": item["state"], "error":item["error"][:230],
                        "provider": item["result"].get("provider"),
                        "upscaled": item["result"].get("upscale_applied"),
                        "size": item["result"].get("size"),
                        "image_ids": item["result"].get("image_ids"),
                        "seconds": item["result"].get("seconds")},
                        ensure_ascii=False), flush=True)
                    break
                if proc.poll() is not None:
                    raise RuntimeError("supervisor exited while task was running")
                time.sleep(2)
            if result is None:
                raise TimeoutError("local image generation did not complete before test deadline")
            if result["state"] != "success":
                return 2
            info = request(key, "GET", "/health")
            print("Gateway after local GPU handoff:", info["status"],flush=True)
            return 0
        finally:
            if proc.poll() is None:
                try:
                    proc.stdin.write("STOP\n")
                    proc.stdin.flush()
                    proc.wait(timeout=320)
                except (BrokenPipeError, OSError, subprocess.TimeoutExpired):
                    # Do not forcibly kill billable or long-running tasks;
                    # parent and private pipes stay alive for safe completion.
                    print("supervisor is still stopping; inspect", log,flush=True)
                print("Supervisor exit code:",proc.poll(),flush=True)


if __name__ == "__main__":
    sys.exit(main())
