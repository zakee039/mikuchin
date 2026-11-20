"""Small stdin-controlled entrypoint for the three unmodified/native services.

Only the official Python *import path* is changed here, never upstream code.
The parent's private pipe provides a graceful STOP/EOF signal without an
unauthenticated shutdown HTTP endpoint or Windows taskkill /T /F.
"""
from __future__ import annotations

import _thread
import argparse
import os
import sys
import threading
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OFFICIAL = ROOT / "backend" / "polystrata"


def watch_parent(stop):
    def watch():
        try:
            for line in sys.stdin:
                if line.strip() == "STOP":
                    break
        finally:
            # The parent crashed or requested shutdown. End unattended
            # services rather than orphaning an unprotected public endpoint.
            stop()
    thread = threading.Thread(target=watch, name="native-supervisor-pipe", daemon=True)
    thread.start()
    return thread


def main():
    parser = argparse.ArgumentParser(description="Private Mikuchin managed service")
    parser.add_argument("--role", choices=("official", "gateway", "image-worker"), required=True)
    parser.add_argument("--engine", choices=("mock", "strata"), default="mock")
    parser.add_argument("--config", default="")
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--gateway-port", type=int, default=15249)
    parser.add_argument("--upstream-port", type=int, default=15240)
    parser.add_argument("--lan-access", action="store_true")
    args = parser.parse_args()

    if args.role == "image-worker":
        from .worker import ImageWorker
        worker = ImageWorker(Path(args.data_dir) / "images")
        watch_parent(worker.stop.set)
        worker.run_forever()
        return

    # Invoked in the main thread so the official server's signal handlers and
    # normal shutdown(svc, httpd, hub) remain functional.
    watch_parent(_thread.interrupt_main)
    if args.role == "gateway":
        from . import app
        sys.argv = ["backend.gateway.app", "--host",
                    "0.0.0.0" if args.lan_access else "127.0.0.1",
                    "--port", str(args.gateway_port), "--upstream-port", str(args.upstream_port)]
        app.main()
        return

    if args.engine == "strata" and not args.config:
        parser.error("Official model config is required for the strata engine")
    if not (OFFICIAL / "serve" / "server.py").is_file():
        parser.error("Pinned official PolyStrata checkout is missing")
    sys.path.insert(0, str(OFFICIAL))
    from serve import server
    cmd = ["serve.server", "--engine", args.engine, "--host", "127.0.0.1",
           "--port", str(args.upstream_port)]
    if args.config:
        cmd.extend(("--config", args.config))
    sys.argv = cmd
    server.main()


if __name__ == "__main__":
    main()
