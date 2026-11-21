"""Package Mikuchin Native source and its exact pinned official PolyStrata.

Only Git-tracked source files enter the ZIP. No generated images, conversations,
credentials, runtime, model weights or virtual environments are included.
For the Native main Gitlink, include the CLEAN pinned upstream checkout's
tracked source in the archive, without any .git internals or custom patches.

Usage: python scripts/package-main-release.py
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess
import sys
import zipfile
import versioning

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist/release"


def git(*args: str, cwd: Path = ROOT) -> bytes:
    return subprocess.check_output(["git", *args], cwd=cwd)


def tracked_files():
    for name in git("ls-files", "-z").decode("utf-8").split("\0"):
        if name:
            file = ROOT / name
            if file.is_file() and not file.is_symlink():
                yield file


def upstream_files():
    upstream=ROOT / "backend/polystrata"
    if not (ROOT/".gitmodules").is_file():
        return []
    pointer=git("ls-tree","HEAD","backend/polystrata").decode("utf-8","replace").strip()
    if not pointer.startswith("160000 commit "):
        raise ValueError("Native PolyStrata must remain a pinned Gitlink")
    expected=pointer.split()[2].split("\t")[0]
    actual=git("rev-parse","HEAD",cwd=upstream).decode("ascii").strip()
    if expected!=actual:
        raise ValueError("Official PolyStrata checkout differs from pinned SHA")
    if git("status","--porcelain",cwd=upstream).strip():
        raise ValueError("Refusing to ship a modified official PolyStrata checkout")
    origin=git("remote","get-url","origin",cwd=upstream).decode("utf-8").strip()
    if origin!="https://github.com/simplexai-labs/PolyStrata.git":
        raise ValueError("Unexpected official PolyStrata remote")
    result=[]
    for name in git("ls-files","-z",cwd=upstream).decode("utf-8").split("\0"):
        if not name:continue
        file=upstream/name
        if file.is_file() and not file.is_symlink():
            result.append(file)
    if not any(file.name=="LICENSE" for file in result):
        raise ValueError("Official PolyStrata license absent from source bundle")
    return result


def main() -> int:
    manifest = versioning.manifest()
    if versioning.validate(manifest, write=False):
        raise ValueError("Version drift: run python scripts/versioning.py sync")
    version = manifest["components"]["main"]["version"]
    if git("status", "--porcelain").strip():
        raise ValueError(f"Refusing to archive dirty worktree: {ROOT}")
    if not (ROOT / "backend/polystrata/LICENSE").is_file():
        raise ValueError("Official engine source or license is unavailable")

    out = DIST / f"Mikuchin-Main-v{version}-source.zip"
    DIST.mkdir(parents=True, exist_ok=True)
    prefix = f"Mikuchin-Main-v{version}/"
    count = 0
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6,
                         allowZip64=True) as archive:
        source_files=list(tracked_files())+upstream_files()
        for file in source_files:
            archive.write(file, prefix + file.relative_to(ROOT).as_posix())
            count += 1
        # Useful without fetching another Git repository and independently
        # auditable against .gitmodules and the public upstream commit.
        archive.writestr(prefix+"OFFICIAL_POLYSTRATA_PIN.txt",
            "Official unmodified PolyStrata submodule:\n"
            "https://github.com/simplexai-labs/PolyStrata.git\n"
            +git("rev-parse","HEAD",cwd=ROOT/"backend/polystrata").decode("ascii"))

    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    (DIST / f"{out.name}.sha256").write_text(f"{digest}  {out.name}\n", encoding="ascii")
    print(f"Main version: {version}; tracked files: {count}; size: {out.stat().st_size:,} bytes")
    print(f"Archive: {out}")
    print(f"SHA256: {digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
