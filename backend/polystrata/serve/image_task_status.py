"""Short-lived image task progress for the Mikuchin Images page.

Only holds task IDs and coarse phases, never prompts, image data or API keys.
"""
from __future__ import annotations

import re
import threading
import time

_TASKS = {}
_LOCK = threading.RLock()
_TASK_ID = re.compile(r"^img-[a-f0-9]{24}$")
_LIFETIME = 600
_MAX_TASKS = 128


def valid(task_id):
    return isinstance(task_id, str) and bool(_TASK_ID.fullmatch(task_id))


def mark(task_id, phase, *, state="working", provider="local", error=None, profile=None):
    if not valid(task_id):
        return
    with _LOCK:
        now = time.monotonic()
        for key, item in list(_TASKS.items()):
            if now - item["updated"] > _LIFETIME:
                del _TASKS[key]
        if task_id not in _TASKS and len(_TASKS) >= _MAX_TASKS:
            oldest = min(_TASKS, key=lambda key: _TASKS[key]["updated"])
            del _TASKS[oldest]
        before = _TASKS.get(task_id)
        started = before["started"] if before else now
        _TASKS[task_id] = {
            "phase": str(phase)[:90], "state": state, "provider": provider,
            "updated": now, "started": started,
            "profile": profile if profile is not None else (before.get("profile") if before else None),
            "error": str(error)[:500] if error else None
        }


def snapshot(task_id, *, gen=None, profiles=None):
    if not valid(task_id):
        return {"state": "unknown"}
    with _LOCK:
        obj = _TASKS.get(task_id)
        if not obj:
            return {"state": "unknown"}
        result = {
            "state": obj["state"], "phase": obj["phase"],
            "provider": obj["provider"],
            "elapsed_s": round(time.monotonic() - obj["started"], 1)
        }
        if obj["error"]:
            result["error"] = obj["error"]
        selected_profile = obj.get("profile")
    if selected_profile and profiles and selected_profile in profiles:
        gen = profiles[selected_profile]
    if gen is not None and result["provider"] == "local" and result["state"] == "working" and result["phase"] == "本地模型生成中":
        status = gen.status()
        if status.get("step") is not None and status.get("steps"):
            result["step"] = int(status["step"])
            result["steps"] = int(status["steps"])
    return result
