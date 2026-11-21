"""Privacy-bounded per-request metrics for the isolated Native Gateway.

Only fixed endpoint categories, status codes, durations and response byte counts
are retained in a small in-memory ring. Never record prompts, request bodies,
messages, user/session IDs, client addresses, headers or full URLs.
"""
from __future__ import annotations

from collections import Counter, deque
from threading import Lock
import time

KINDS = frozenset(("chat", "messages", "responses", "images", "gpu_busy"))
MAX_RECENT = 30


class RequestMonitor:
    def __init__(self):
        self._lock = Lock()
        self._started_at = time.time()
        self._inflight = 0
        self._total = 0
        self._failed = 0
        self._counts = Counter()
        self._recent = deque(maxlen=MAX_RECENT)

    def begin(self, kind):
        if kind not in KINDS:
            raise ValueError("unsupported request category")
        with self._lock:
            self._inflight += 1
        return (kind, time.monotonic())

    def finish(self, ticket, *, status, response_bytes=0, outcome="completed"):
        kind, started = ticket
        if kind not in KINDS:
            raise ValueError("unsupported request category")
        if not isinstance(status, int) or not 100 <= status <= 599:
            raise ValueError("invalid HTTP status")
        if outcome not in ("completed", "upstream_error", "client_disconnect", "gpu_busy"):
            raise ValueError("invalid outcome")
        ms = min(86_400_000, round((time.monotonic() - started) * 1000))
        size = min(2**53 - 1, max(0, int(response_bytes)))
        # Fixed schema with no dynamic values from user headers, prompts or URL.
        event = {
            "kind": kind,
            "status": status,
            "outcome": outcome,
            "duration_ms": ms,
            "response_bytes": size,
            "completed_at": round(time.time()),
        }
        with self._lock:
            self._inflight = max(0, self._inflight - 1)
            self._total += 1
            self._counts[kind] += 1
            if outcome != "completed" or status >= 400:
                self._failed += 1
            self._recent.appendleft(event)

    def snapshot(self):
        with self._lock:
            return {
                "uptime_s": max(0, round(time.time() - self._started_at)),
                "total": self._total,
                "failed": self._failed,
                "active": self._inflight,
                "by_kind": {kind: self._counts[kind] for kind in sorted(KINDS)},
                "recent": [entry.copy() for entry in self._recent],
                "persistence": "memory_only",
                "token_usage": "not_available_per_request",
            }
