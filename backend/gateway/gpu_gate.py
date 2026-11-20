"""Cross-process GPU turn gate for native Gateway inference and image jobs.

Every Gateway inference stream holds a shared byte-range lock. A local GPU
image/upscale operation holds the exclusive lock from engine unload through
its reload, ensuring no new Gateway inference can race it. The official engine
is reachable only through the Gateway's private API key.

Only OS-held locks are used: a crashed worker releases its lease automatically.
The file contains no secrets or application state.
"""
from __future__ import annotations

import contextlib
import json
import os
import secrets
import time
from pathlib import Path


class GPUUnavailable(RuntimeError):
    pass


_STATE_PHASES = frozenset(("unloading", "generating", "upscaling", "restoring", "idle"))


def publish_state(data_dir, phase):
    """Publish only a bounded operational phase, never prompts/paths/keys.

    The exclusive-lock owner calls this. A stale file after a crash is harmless:
    read_state probes the real OS lock instead of trusting the JSON alone.
    """
    if phase not in _STATE_PHASES:
        raise ValueError("invalid GPU phase")
    root = Path(data_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    path = root / "native-gpu-turn-status.json"
    temporary = root / ("." + path.name + "." + secrets.token_hex(6) + ".tmp")
    try:
        temporary.write_text(json.dumps({"phase": phase, "pid": os.getpid(),
                                         "updated_at": time.time()}), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def read_state(data_dir):
    """A nonblocking probe makes a crashed worker's old status report idle."""
    root = Path(data_dir).resolve()
    try:
        with gpu_turn(root, timeout=.08):
            return {"busy": False, "phase": "idle"}
    except GPUUnavailable:
        pass
    path = root / "native-gpu-turn-status.json"
    try:
        if path.stat().st_size > 1024 or path.is_symlink():
            raise ValueError("unexpected GPU status file")
        data = json.loads(path.read_text(encoding="utf-8"))
        phase = data.get("phase")
        return {"busy": True, "phase": phase if phase in _STATE_PHASES - {"idle"} else "unknown"}
    except (OSError, ValueError, TypeError, AttributeError):
        return {"busy": True, "phase": "unknown"}


@contextlib.contextmanager
def gpu_turn(data_dir, *, exclusive=False, timeout=3.0):
    root = Path(data_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    path = root / "native-gpu-turn.lock"
    deadline = time.monotonic() + timeout
    with path.open("a+b") as file:
        # Windows read locks protect byte 0 itself. Reading or writing that
        # byte from another connection *before* acquiring our lock would
        # raise PermissionError during parallel inference requests.
        if os.name == "nt":
            import msvcrt
            # CPython/MSVCRT read locks are not reliably shared between
            # distinct handles, even in one process. Instead each reader
            # takes one exclusive byte slot while the image writer locks
            # the entire 256-byte range. Readers never touch byte zero.
            size = 256 if exclusive else 1
            offset = 0
            while True:
                try:
                    if not exclusive:
                        offset = 1 + secrets.randbelow(255)
                    file.seek(offset)
                    msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, size)
                    break
                except OSError as exc:
                    if time.monotonic() >= deadline:
                        raise GPUUnavailable("GPU is busy with another native task") from exc
                    time.sleep(.08)
            try:
                yield
            finally:
                file.seek(offset)
                msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, size)
        else:
            import fcntl
            kind = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
            while True:
                try:
                    fcntl.flock(file.fileno(), kind | fcntl.LOCK_NB)
                    break
                except BlockingIOError as exc:
                    if time.monotonic() >= deadline:
                        raise GPUUnavailable("GPU is busy with another native task") from exc
                    time.sleep(.08)
            try:
                yield
            finally:
                fcntl.flock(file.fileno(), fcntl.LOCK_UN)
