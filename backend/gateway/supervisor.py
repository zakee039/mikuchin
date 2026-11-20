"""Isolated Mikuchin Native three-process supervisor (development entrypoint).

Starts the *official* engine, then an independent Image Worker, then the
Mikuchin Gateway. Each child receives a write-only stdin control pipe and
never requires changes to upstream source. No entrypoint opens production
port 15239. Crash restarts are bounded; paid tasks are never auto-replayed.
"""
from __future__ import annotations

import argparse
import http.client
import json
import logging
import os
import secrets
import socket
import subprocess
import sys
import threading
import time
from collections import defaultdict, deque
from pathlib import Path

from .image_jobs import ImageJobStore
from .worker import singleton_lock
from .gpu_gate import read_state


LOG = logging.getLogger("mikuchin.supervisor")
ROOT = Path(__file__).resolve().parents[2]
STABLE_PORT = 15239


def _is_available(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            # On Windows, SO_REUSEADDR can steal a port from a running service.
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
        return True


def _health(port, key):
    # http.client never uses the user's HTTP(S) proxy settings. An internal
    # health check must never send a private Bearer key to a proxy.
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=1.2)
    try:
        conn.request("GET", "/health", headers={"Authorization": "Bearer " + key})
        response = conn.getresponse()
        if response.status != 200:
            return None
        return json.loads(response.read(32768))
    except (OSError, ValueError, http.client.HTTPException):
        return None
    finally:
        conn.close()


class NativeSupervisor:
    roles = ("official", "image-worker", "gateway")

    def __init__(self, *, data_dir, engine="mock", config=None, gateway_port=15249,
                 upstream_port=15240, api_key=None, python=None, startup_timeout=120,
                 control_stdin=False, lan_access=False):
        if not isinstance(gateway_port, int) or not isinstance(upstream_port, int) or \
           not all(1024 <= port <= 65535 for port in (gateway_port, upstream_port)) or \
           gateway_port == upstream_port or STABLE_PORT in (gateway_port, upstream_port):
            raise ValueError("Use separate unprivileged ports; stable 15239 is reserved")
        self.data_dir = Path(data_dir).expanduser().resolve()
        stable = (ROOT.parent / "mikuchin").resolve()
        if self.data_dir == stable or stable in self.data_dir.parents:
            raise ValueError("Native runtime must not use the stable Mikuchin data directory")
        if engine not in ("mock", "strata"):
            raise ValueError("Unknown official engine")
        self.config = Path(config).resolve() if config else None
        if engine == "strata" and (not self.config or not self.config.is_file()):
            raise ValueError("A valid official model JSON config is required")
        self.engine = engine
        self.python = str(Path(python or sys.executable).resolve())
        self.gateway_port, self.upstream_port = gateway_port, upstream_port
        self.lan_access = bool(lan_access)
        self.api_key = api_key or os.environ.get("MIKUCHIN_GATEWAY_API_KEY", "")
        if len(self.api_key) < 12:
            raise ValueError("Provide MIKUCHIN_GATEWAY_API_KEY (at least 12 characters)")
        self.upstream_key = secrets.token_urlsafe(42)
        self.startup_timeout = startup_timeout
        self.control_stdin = control_stdin
        self.stop = threading.Event()
        self.children = {}
        self.child_logs = {}
        self.launch_times = {}
        self.restarts = defaultdict(deque)
        self.child_restarts = defaultdict(int)
        self.last_recovery = None
        self.start_time = time.time()
        self.image_store = None
        self.status_file = self.data_dir / "supervisor-status.json"

    def _watch_stdin(self):
        """A parent Launcher or test harness can request STOP without signals."""
        def monitor():
            try:
                for line in sys.stdin:
                    if line.strip() == "STOP":
                        break
            finally:
                self.stop.set()
        threading.Thread(target=monitor, name="native-supervisor-stdin", daemon=True).start()

    def _environment(self):
        env = dict(os.environ)
        env["MIKUCHIN_GATEWAY_API_KEY"] = self.api_key
        env["MIKUCHIN_UPSTREAM_API_KEY"] = self.upstream_key
        env["STRATA_API_KEY"] = self.upstream_key
        env["MIKUCHIN_NATIVE_DATA_DIR"] = str(self.data_dir)
        env["MIKUCHIN_NATIVE_OFFICIAL_PORT"] = str(self.upstream_port)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        if self.config:
            model = json.loads(self.config.read_text(encoding="utf-8-sig"))
            dirs = model.get("lib_dirs") or []
            if not isinstance(dirs, list) or not all(isinstance(d, str) for d in dirs):
                raise ValueError("Official config lib_dirs must be a list of paths")
            env["PATH"] = os.pathsep.join(dirs) + os.pathsep + env.get("PATH", "")
        return env

    def _args(self, role):
        command = [self.python, "-u", "-B", "-m", "backend.gateway.managed_child",
                   "--role", role, "--data-dir", str(self.data_dir),
                   "--gateway-port", str(self.gateway_port),
                   "--upstream-port", str(self.upstream_port), "--engine", self.engine]
        if self.config:
            command += ["--config", str(self.config)]
        if role == "gateway" and self.lan_access:
            command.append("--lan-access")
        return command

    def _launch(self, role):
        logs = self.data_dir / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        # A single append-only log per component keeps only local diagnostics.
        handle = (logs / (role + ".log")).open("a", encoding="utf-8")
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        try:
            child = subprocess.Popen(self._args(role), cwd=str(ROOT), env=self._environment(),
                                     stdin=subprocess.PIPE, stdout=handle,
                                     stderr=subprocess.STDOUT, text=True,
                                     creationflags=creationflags)
        except Exception:
            handle.close()
            raise
        self.children[role] = child
        self.child_logs[role] = handle
        self.launch_times[role] = time.time()
        LOG.info("Started %s PID=%d", role, child.pid)
        self._write_status("starting")

    def _write_status(self, phase):
        public = {"phase": phase, "engine": self.engine,
                  "supervisor_pid": os.getpid(), "started_at": self.start_time,
                  "gateway_port": self.gateway_port,
                  "lan_access": self.lan_access,
                  "official_port": self.upstream_port,
                  "children": {role: child.pid for role, child in self.children.items()
                               if child.poll() is None},
                  "child_restarts": dict(self.child_restarts),
                  "last_recovery": self.last_recovery}
        self.data_dir.mkdir(parents=True, exist_ok=True)
        temp = self.status_file.with_suffix(".tmp")
        temp.write_text(json.dumps(public, indent=2) + "\n", encoding="utf-8")
        os.replace(temp, self.status_file)

    def _wait(self, role, predicate, timeout):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not self.stop.is_set():
            child = self.children[role]
            if child.poll() is not None:
                raise RuntimeError(f"{role} exited with code {child.returncode}; check its local log")
            if predicate():
                return
            self.stop.wait(.25)
        raise RuntimeError(f"{role} did not become healthy within {timeout}s")

    def _wait_role(self, role):
        if role == "official":
            self._wait(role, lambda: bool((s := _health(self.upstream_port, self.upstream_key))
                                          and s.get("status") == "ok" and
                                          (self.engine == "mock" or s.get("loaded") is True)),
                       self.startup_timeout)
        elif role == "image-worker":
            self._wait(role, lambda: self.image_store.worker_healthy() and
                       self.image_store.worker_last_heartbeat() >=
                       self.launch_times[role], 16)
        else:
            self._wait(role, lambda: bool((s := _health(self.gateway_port, self.api_key))
                                          and s.get("status") == "ok" and
                                          s.get("official_polystrata_reachable") and
                                          s.get("image_worker_ready")), 20)

    def _start_role(self, role):
        self._launch(role)
        self._wait_role(role)
        LOG.info("%s is healthy", role)

    def _watch(self):
        while not self.stop.wait(.5):
            for role in self.roles:
                child = self.children[role]
                if child.poll() is None:
                    continue
                LOG.warning("%s exited unexpectedly (code %s)", role, child.returncode)
                now = time.monotonic()
                failures = self.restarts[role]
                while failures and now - failures[0] > 60:
                    failures.popleft()
                failures.append(now)
                if len(failures) > 3:
                    raise RuntimeError(f"{role} crashed more than three times in 60 seconds")
                old_log = self.child_logs.pop(role, None)
                if old_log is not None:
                    old_log.close()
                self.stop.wait(min(len(failures) * .5, 2.0))
                if self.stop.is_set():
                    break
                if role == "official":
                    # A local image owns the GPU exclusively between model
                    # unload and reload. Never re-launch the crashed LLM
                    # into an image job that still owns that GPU lease.
                    if read_state(self.data_dir)["busy"]:
                        self._write_status("waiting-for-gpu")
                    while not self.stop.is_set() and read_state(self.data_dir)["busy"]:
                        self.stop.wait(.25)
                    if self.stop.is_set():
                        break
                self._start_role(role)
                self.child_restarts[role] += 1
                self.last_recovery = {"role": role, "at": time.time()}
                self._write_status("running")

    def _stop_role(self, role, grace):
        child = self.children.get(role)
        if child is None:
            return
        if child.poll() is None:
            try:
                if child.stdin and not child.stdin.closed:
                    child.stdin.write("STOP\n")
                    child.stdin.flush()
            except (BrokenPipeError, OSError):
                pass
            try:
                child.wait(timeout=grace)
            except subprocess.TimeoutExpired:
                if role == "image-worker":
                    # Provider calls may have been accepted and charged. The
                    # worker keeps its private pipe alive until it finishes;
                    # never terminate/replay the billing-sensitive operation.
                    LOG.error("Image Worker is still executing; leaving it running to finish safely")
                else:
                    LOG.error("%s did not stop gracefully; refusing to kill its process tree", role)
        if child.stdin is not None and child.poll() is not None:
            child.stdin.close()
        handle = self.child_logs.pop(role, None)
        if handle is not None:
            handle.close()

    def run(self):
        if not _is_available(self.upstream_port) or not _is_available(self.gateway_port):
            raise RuntimeError("Development service port already in use; existing service untouched")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        with singleton_lock(self.data_dir / "native-supervisor.lock"):
            self.image_store = ImageJobStore(self.data_dir / "images")
            if self.control_stdin:
                self._watch_stdin()
            try:
                for role in self.roles:
                    self._start_role(role)
                self._write_status("running")
                LOG.info("Native stack ready at http://127.0.0.1:%d", self.gateway_port)
                self._watch()
            finally:
                self.stop.set()
                self._write_status("stopping")
                for role, seconds in (("gateway", 12), ("image-worker", 300), ("official", 30)):
                    self._stop_role(role, seconds)
                leftovers = [role for role, child in self.children.items() if child.poll() is None]
                if leftovers:
                    # A paid provider request can outlive the normal shutdown grace.
                    # Keep the controlling parent and its private pipes alive until
                    # the worker finishes: never orphan a charged request or claim
                    # a clean STOP before the actual child has exited.
                    LOG.warning("Waiting for active native jobs to finish: %s", leftovers)
                    self._write_status("waiting-for-active-jobs")
                    while leftovers:
                        time.sleep(0.5)
                        leftovers = [role for role, child in self.children.items()
                                     if child.poll() is None]
                self._write_status("stopped")


def main():
    ap = argparse.ArgumentParser(description="Mikuchin Native isolated process supervisor")
    ap.add_argument("--engine", choices=("mock", "strata"), default="mock")
    ap.add_argument("--config", help="Pinned official engine model JSON (for --engine strata)")
    ap.add_argument("--data-dir", required=True, help="Fresh Native storage; never stable Mikuchin chat")
    ap.add_argument("--gateway-port", type=int, default=15249)
    ap.add_argument("--upstream-port", type=int, default=15240)
    ap.add_argument("--startup-timeout", type=int, default=120)
    ap.add_argument("--control-stdin", action="store_true",
                    help="Enable private STOP/EOF pipe; for a parent launcher")
    ap.add_argument("--lan-access", action="store_true",
                    help="Explicitly allow remote access to authenticated Gateway only")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        supervisor = NativeSupervisor(data_dir=args.data_dir, engine=args.engine,
                                      config=args.config, gateway_port=args.gateway_port,
                                      upstream_port=args.upstream_port,
                                      startup_timeout=args.startup_timeout,
                                      control_stdin=args.control_stdin,
                                      lan_access=args.lan_access)
        supervisor.run()
    except KeyboardInterrupt:
        pass
    except (ValueError, RuntimeError, OSError) as exc:
        LOG.error("Native supervisor stopped: %s", str(exc))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
