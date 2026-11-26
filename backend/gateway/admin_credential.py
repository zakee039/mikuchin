"""Dedicated per-Supervisor management credential for the current Windows user.

No existing Gateway/provider keys are accessed. Only the local administrative
listener accepts this credential. DPAPI is the same-user security boundary.
"""
from __future__ import annotations
import os
import secrets
from pathlib import Path
from .chat_providers import _protect

NAME = "native-admin-credential.dpapi"

def _binding(root, pid, port):
    return f"mikuchin-admin-v1|{Path(root).resolve()}|{pid}|{port}"

def issue(root, pid, port):
    if os.name != "nt":
        return None
    token = secrets.token_urlsafe(48)
    path = Path(root) / NAME
    temp = path.with_name(path.name + "." + secrets.token_hex(6) + ".tmp")
    try:
        protected = _protect(token, _binding(root, pid, port))
        with temp.open("x", encoding="ascii") as f:
            f.write(protected)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)
    return token

def load(root, pid, port):
    if os.name != "nt":
        return None
    path = Path(root) / NAME
    if not path.is_file():
        return None
    with path.open(encoding="ascii") as f:
        protected = f.read(8193)
    if len(protected) > 8192:
        raise ValueError("Invalid local management credential")
    return _protect(protected, _binding(root, pid, port), True)
