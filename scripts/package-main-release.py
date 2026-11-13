"""Package Mikuchin's complete tracked source, including its bundled backend.

No Git submodule or secondary repository is required. Only files tracked in
the Mikuchin repository enter the archive: never package generated images,
conversations, credentials, local model files, runtimes or virtual environments.

Usage: python scripts/package-main-release.py
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import re
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist/release"


def git(*args: str, cwd: Path = ROOT) -> bytes:
    return subprocess.check_output(["git", *args], cwd=cwd)


def tracked_files():
    for name in git("ls-files", "-z").decode("utf-8").split("\0"):
        if name:
            file = ROOT / name
            if file.is_file():
                yield file


def main() -> int:
    versions = (ROOT / "frontend/web/versions.js").read_text(encoding="utf-8")
    match = re.search(r'\bmain:\s*"([0-9]+\.[0-9]+\.[0-9]+)"', versions)
    if not match:
        raise ValueError("Cannot read main-program version from web/versions.js")
    version = match.group(1)
    if git("status", "--porcelain").strip():
        raise ValueError(f"Refusing to archive dirty worktree: {ROOT}")
    if (ROOT / ".gitmodules").exists():
        raise ValueError("This release must not depend on Git submodules")
    if not (ROOT / "backend/polystrata/LICENSE").is_file():
        raise ValueError("Missing bundled engine source or license")

    out = DIST / f"Mikuchin-Main-v{version}-source.zip"
    DIST.mkdir(parents=True, exist_ok=True)
    prefix = f"Mikuchin-Main-v{version}/"
    count = 0
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6,
                         allowZip64=True) as archive:
        for file in tracked_files():
            archive.write(file, prefix + file.relative_to(ROOT).as_posix())
            count += 1

    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    (DIST / f"{out.name}.sha256").write_text(f"{digest}  {out.name}\n", encoding="ascii")
    print(f"Main version: {version}; tracked files: {count}; size: {out.stat().st_size:,} bytes")
    print(f"Archive: {out}")
    print(f"SHA256: {digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
