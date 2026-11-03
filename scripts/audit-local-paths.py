"""Verify that Mikuchin configuration cannot silently reuse an old deployment.

All non-model artifacts (engine binaries, CUDA DLLs, logs, sessions, KV,
images, characters and user-config files) must be under the product directory.
Model weights are the only allowed external data paths.
"""
from __future__ import annotations
import json
from pathlib import Path
import re
import sys

def windows_path(value: str) -> bool:
    return bool(re.match(r"^[a-zA-Z]:[\\/]", value))

def normalize(value: str) -> str:
    return value.replace("/", "\\").rstrip("\\").lower()

def check(home: Path) -> list[str]:
    home = home.resolve()
    config_file = home / "config" / "active.json"
    cfg = json.loads(config_file.read_text(encoding="utf-8-sig"))
    home_prefix = normalize(str(home)) + "\\"
    model_prefix = normalize(str(home.parent.parent / "models")) + "\\"
    issues = []
    def walk(value, key):
        if isinstance(value, dict):
            for k, v in value.items(): walk(v, key + "." + k)
        elif isinstance(value, list):
            for i, v in enumerate(value): walk(v, f"{key}[{i}]")
        elif isinstance(value, str) and windows_path(value):
            path = normalize(value)
            if path.startswith(home_prefix) or path == normalize(str(home)):
                return
            if path.startswith(model_prefix):
                return
            issues.append(f"{key} uses external non-model path {value!r}")
    walk(cfg, "config")
    expected = {
        "session_v1_dir": home / "chat",
        "session_v1_kv_dir": home / "chat" / "kv-cache",
    }
    for key, location in expected.items():
        if normalize(cfg.get(key, "")) != normalize(str(location)):
            issues.append(f"{key} must be {location}, got {cfg.get(key)!r}")
    if not normalize(cfg.get("log", "")).startswith(home_prefix + "logs\\"):
        issues.append("log must live inside Mikuchin/logs")
    if not normalize(str(cfg.get("cwd", ""))).startswith(home_prefix + "backend\\polystrata"):
        issues.append("cwd must live inside Mikuchin/backend/polystrata")
    for p in cfg.get("lib_dirs", []):
        if not Path(p).is_dir():
            issues.append(f"missing local DLL directory: {p}")
    return issues

if __name__ == "__main__":
    base = Path(__file__).resolve().parent.parent
    problems = check(base)
    for issue in problems: print("ERROR:", issue)
    if problems: sys.exit(1)
    print("PASS: runtime paths are self-contained; only model weights may be external")
