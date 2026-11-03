"""Package the *complete tracked source* including the PolyStrata submodule.

GitHub's automatic source archives do not include Git submodule contents, so
this main-program archive includes both committed trees. The archive NEVER
contains generated images, conversations, credentials, models, or virtualenvs.

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
SUBMODULE = ROOT / "backend/polystrata"
DIST = ROOT / "dist/release"


def git(*args: str, cwd: Path = ROOT) -> bytes:
    return subprocess.check_output(["git", *args], cwd=cwd)


def tracked_files(path: Path):
    for name in git("ls-files", "-z", cwd=path).decode("utf-8").split("\0"):
        if name:
            file = path / name
            if file.is_file():
                yield file


def main() -> int:
    versions = (ROOT / "frontend/web/versions.js").read_text(encoding="utf-8")
    match = re.search(r'\bmain:\s*"([0-9]+\.[0-9]+\.[0-9]+)"', versions)
    if not match:
        raise ValueError("Cannot read main-program version from web/versions.js")
    version = match.group(1)
    for cwd in (ROOT, SUBMODULE):
        if git("status", "--porcelain", cwd=cwd).strip():
            raise ValueError(f"Refusing to archive dirty worktree: {cwd}")
    sub_head = git("rev-parse", "HEAD", cwd=SUBMODULE).decode().strip()
    expected_sub = git("rev-parse", "HEAD:backend/polystrata").decode().strip()
    if sub_head != expected_sub:
        raise ValueError("Submodule checkout does not match pinned main-program commit")

    out = DIST / f"Mikuchin-Main-v{version}-source.zip"
    DIST.mkdir(parents=True, exist_ok=True)
    prefix = f"Mikuchin-Main-v{version}/"
    count = 0
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6,
                         allowZip64=True) as archive:
        for directory in (ROOT, SUBMODULE):
            for file in tracked_files(directory):
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
