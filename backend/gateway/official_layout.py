"""Resolve the unmodified official engine's serving layout.

0.2.x moved the server and Python helpers below terminal/. Keep legacy
layout detection so a v0.5.2 source/config rollback stays straightforward.
"""
from pathlib import Path


def serving_root(checkout: Path) -> Path:
    checkout = Path(checkout).resolve()
    for candidate in (checkout / "terminal", checkout):
        if (candidate / "serve" / "server.py").is_file():
            return candidate
    raise FileNotFoundError("Pinned official PolyStrata checkout is missing its server")
