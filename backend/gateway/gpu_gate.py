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
import os
import secrets
import time
from pathlib import Path


class GPUUnavailable(RuntimeError):
    pass


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
