"""Generate or verify Mikuchin release-asset integrity manifest.

Requires REAL binaries: source ZIP, Windows portable and NSIS, release-signed APK.
Never renames old builds to a new version; caller must verify APK metadata and
signing certificate before executing this command.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import versioning

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist/release"


def digest(file: Path) -> str:
    sha = hashlib.sha256()
    with file.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def assets_of(m: dict) -> list[str]:
    main = m["components"]["main"]["version"]
    launcher = m["components"]["launcher"]["version"]
    android = m["components"]["android"]["version"]
    paths = [
        f"Mikuchin-Main-v{main}-source.zip",
        f"Mikuchin-Main-v{main}-source.zip.sha256",
        f"Mikuchin-Launcher-v{launcher}.exe",
        f"Mikuchin-Launcher-v{launcher}-Setup.exe",
        f"Mikuchin-Android-v{android}.apk",
    ]
    native = DIST / f"Mikuchin-Engine-v{main}-Windows-CUDA13.2-SM86.exe"
    if native.exists():
        paths.append(native.name)
    return paths


def build(m: dict) -> int:
    if versioning.validate(m, write=False):
        raise ValueError("Sources are not synchronized with versions.json")
    sources = assets_of(m)
    for name in sources:
        file = DIST / name
        if not file.is_file() or file.stat().st_size < 40:
            raise ValueError("Missing or empty release artifact " + str(file))
    zip_file = DIST / sources[0]
    sha_file = DIST / sources[1]
    expected = sha_file.read_text(encoding="ascii").strip().split()[0]
    if expected.lower() != digest(zip_file):
        raise ValueError("Main ZIP SHA256 sidecar mismatch")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    result = {
        "schema": 1,
        "tag": m["release"],
        "commit": head,
        "components": m["components"],
        "notes": "Android internal version and signer checked separately; native Windows CUDA13.2 SM86 optional.",
        "assets": [
            {"filename": name, "bytes": (DIST / name).stat().st_size,
             "sha256": digest(DIST / name)}
            for name in sources
        ],
    }
    out = DIST / f"Mikuchin-{m['release']}-release-manifest.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Built release manifest for", result["tag"], "at commit", head)
    for item in result["assets"]:
        print(f"  {item['filename']}: {item['bytes']:,} bytes {item['sha256']}")
    return 0


def verify(m: dict) -> int:
    path = DIST / f"Mikuchin-{m['release']}-release-manifest.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("tag") != m["release"] or data.get("components") != m["components"]:
        raise ValueError("Release manifest component versions diverged")
    expected_names = set(assets_of(m))
    actual_names = {asset["filename"] for asset in data["assets"]}
    if expected_names != actual_names:
        raise ValueError("Manifest asset names differ from present release files")
    for asset in data["assets"]:
        file = DIST / asset["filename"]
        if not file.is_file() or file.stat().st_size != asset["bytes"] or digest(file) != asset["sha256"]:
            raise ValueError("Release manifest integrity verification failed for " + str(file))
    print(f"Verified {len(data['assets'])} release assets for {m['release']}")
    return 0


def main() -> int:
    cli = argparse.ArgumentParser()
    cli.add_argument("command", choices=["build", "verify"])
    args = cli.parse_args()
    m = versioning.manifest()
    return build(m) if args.command == "build" else verify(m)


if __name__ == "__main__":
    sys.exit(main())
