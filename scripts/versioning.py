"""Canonical Mikuchin product version synchronizer and release audit.

The manifest versions.json is authoritative. Use
  python scripts/versioning.py status [--remote]
  python scripts/versioning.py sync
  python scripts/versioning.py check

Three independent product versions; the bundled upstream PolyStrata manager
is NOT the Mikuchin launcher. Bump the manifest once and sync/check.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "versions.json"
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def manifest() -> dict:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if data.get("schema") != 1:
        raise ValueError("Unsupported versions.json schema")
    comps = data["components"]
    for part in ("main", "launcher", "android"):
        if not SEMVER.fullmatch(comps[part]["version"]):
            raise ValueError("Invalid component version: " + part)
    main = comps["main"]["version"]
    if data["release"] != f"v{main}":
        raise ValueError("Release tag must track the main component")
    code = comps["android"]["versionCode"]
    major, minor, patch = map(int, comps["android"]["version"].split("."))
    # Android's monotonically increasing code: 0.2.8 -> 208.
    expected = major * 10000 + minor * 100 + patch
    if code != expected:
        raise ValueError(f"Android versionCode must be {expected}, got {code}")
    if data["release"] == data.get("previous_release"):
        raise ValueError("Current release and previous release may not be identical")
    return data


def _text(file: str) -> str:
    return (ROOT / file).read_text(encoding="utf-8")


def _replace_once(s: str, pattern: str, replacement: str, file: str, flags: int = 0) -> str:
    out, n = re.subn(pattern, lambda match: match.expand(replacement), s, count=0, flags=flags)
    if n != 1:
        raise ValueError(f"{file}: pattern {pattern!r} matches {n}, expected 1")
    return out


def expected_files(data: dict) -> dict[str, str]:
    m = data["components"]["main"]["version"]
    l = data["components"]["launcher"]["version"]
    a = data["components"]["android"]["version"]
    c = str(data["components"]["android"]["versionCode"])
    targets: dict[str, str] = {}

    def replace(file, pat, repl, flags=0):
        s = targets.get(file, _text(file))
        targets[file] = _replace_once(s, pat, repl, file, flags=flags)

    replace("frontend/web/versions.js", r'(?m)^  main: "\d+\.\d+\.\d+",', f'  main: "{m}",')
    replace("frontend/web/versions.js", r'(?m)^  launcher: "\d+\.\d+\.\d+",', f'  launcher: "{l}",')
    replace("frontend/web/versions.js", r'(?m)^  android: "\d+\.\d+\.\d+",', f'  android: "{a}",')
    replace("frontend/web/index.html", r'web/versions\.js\?v=\d+\.\d+\.\d+', f'web/versions.js?v={m}')

    replace("frontend/launcher/package.json", r'(?m)^  "version": "\d+\.\d+\.\d+",', f'  "version": "{l}",')
    replace("frontend/launcher/package-lock.json", r'(?m)^  "version": "\d+\.\d+\.\d+",', f'  "version": "{l}",')
    replace("frontend/launcher/package-lock.json",
            r'("packages": \{\r?\n    "": \{\r?\n      "name": "mikuchin",\r?\n      "version": )"\d+\.\d+\.\d+"',
            rf'\g<1>"{l}"')
    replace("frontend/launcher/src-tauri/tauri.conf.json",
            r'(?m)^  "version": "\d+\.\d+\.\d+",', f'  "version": "{l}",')
    replace("frontend/launcher/src-tauri/Cargo.toml", r'(?m)^version = "\d+\.\d+\.\d+"$',
            f'version = "{l}"')
    replace("frontend/launcher/src-tauri/Cargo.lock",
            r'(\[\[package\]\]\r?\nname = "mikuchin"\r?\nversion = )"\d+\.\d+\.\d+"',
            rf'\g<1>"{l}"')
    replace("frontend/launcher/src/main.ts", r'(<span>v)\d+\.\d+\.\d+(</span></footer>)',
            rf'\g<1>{l}\g<2>')

    replace("frontend/android/app/build.gradle.kts", r'(?m)^        versionName = "\d+\.\d+\.\d+"',
            f'        versionName = "{a}"')
    replace("frontend/android/app/build.gradle.kts", r'(?m)^        versionCode = \d+',
            f'        versionCode = {c}')

    for file in ("README.md", "README.en-US.md", "README.ja-JP.md"):
        s = _text(file)
        # First heading and release link, not historical version references later in the file.
        s = _replace_once(s, r'(?m)^(\*\*[^\n]*?v)\d+\.\d+\.\d+(\*\*[^\n]*github\.com/zakee039/mikuchin/releases/tag/v)',
                          rf'\g<1>{m}\g<2>', file)
        s = _replace_once(s, r'(?m)^(.*github\.com/zakee039/mikuchin/releases/tag/v)\d+\.\d+\.\d+(\).*)$',
                          rf'\g<1>{m}\g<2>', file)
        if file == "README.en-US.md":
            line = (f"**Independent versions:** main app `{m}` · Windows launcher `{l}` · "
                    f"Android client `{a}` (versionCode {c}). All three artifacts were rebuilt for this release. "
                    "They remain independently versioned for future changes.")
        elif file == "README.ja-JP.md":
            line = (f"**個別バージョン：**メインアプリ `{m}` · Windows ランチャー `{l}` · "
                    f"Android クライアント `{a}`（versionCode {c}）。今回のリリースでは 3 種類を再ビルドしました。"
                    "以降のバージョンは個別に管理し、versions.json に記録します。")
        else:
            line = (f"**独立版本：**主程序 `{m}` · Windows 启动器 `{l}` · "
                    f"Android 客户端 `{a}`（versionCode {c}）。本次三个组件均重新构建；"
                    "后续仍允许独立升级，所有版本号统一记录在 versions.json。")
        s = _replace_once(s, r'(?m)^\*\*.*versionCode \d+.*$', line, file)
        s = _replace_once(s, r'(?m)^(?=[^\n]*APK)([^\n]*?v)\d+\.\d+\.\d+([^\n]*)$',
                          rf'\g<1>{a}\g<2>', file)
        targets[file] = s

    site = "docs/index.html"
    replace(site, r'(<p class="eyebrow reveal"><span class="dot"></span>.*?v)\d+\.\d+\.\d+',
            rf'\g<1>{m}')
    # Product website has one three-axis release/version line.
    replace(site, r'(主程序 v)\d+\.\d+\.\d+( · Windows 启动器 v)\d+\.\d+\.\d+( · Android v)\d+\.\d+\.\d+',
            rf'\g<1>{m}\g<2>{l}\g<3>{a}')
    return targets


def validate(data: dict, *, write: bool) -> int:
    generated = expected_files(data)
    changed = [path for path, content in generated.items() if _text(path) != content]
    if changed and write:
        for file in changed:
            (ROOT / file).write_text(generated[file], encoding="utf-8", newline="")
        print("Synchronized", len(changed), "files:")
        for path in changed:
            print("  " + path)
    elif changed:
        print("Version drift detected in:")
        for path in changed:
            print("  " + path)
        print("Fix: python scripts/versioning.py sync")
        return 1
    else:
        print("All", len(generated), "versioned sources match versions.json")

    gradle = _text("frontend/android/app/build.gradle.kts")
    if not re.search(r'(?m)^\s*versionCode\s*=\s*'+str(data["components"]["android"]["versionCode"])+r'\s*$', gradle):
        raise ValueError("Android versionCode mismatch")
    build = _text("frontend/android/build-apk.ps1")
    if "Mikuchin-v$versionName.apk" not in build:
        print("Android build-apk.ps1 must derive artifact name from Gradle versionName")
        return 1
    if not (ROOT / f'docs/RELEASE_{data["release"]}.md').is_file():
        print(f"Missing docs/RELEASE_{data['release']}.md")
        return 1
    if data["release"] not in _text("docs/VERSION_HISTORY.md"):
        print("Missing current release in version history")
        return 1
    return 0


def status(data: dict, remote: bool):
    print("Mikuchin canonical version record:", MANIFEST)
    print("Target release:", data["release"], "| previous:", data["previous_release"])
    for name, ver in data["components"].items():
        print(f"  {name:<8} {ver['version']}"
              + (f" / versionCode {ver['versionCode']}" if "versionCode" in ver else ""))
    if remote:
        result = subprocess.run(["gh", "release", "list", "--repo", "zakee039/mikuchin",
                                 "--limit", "3"], capture_output=True, text=True)
        if result.returncode:
            print("GitHub query failed:", result.stderr.strip())
            raise SystemExit(result.returncode)
        print("GitHub actual releases (not inferred from source):")
        print(result.stdout.rstrip())


def main() -> int:
    cli = argparse.ArgumentParser()
    cli.add_argument("command", choices=("status", "check", "sync"))
    cli.add_argument("--remote", action="store_true", help="check actual GitHub releases (status only)")
    args = cli.parse_args()
    data = manifest()
    if args.command == "status":
        status(data, args.remote)
        return 0
    if args.remote:
        cli.error("--remote is for status only")
    return validate(data, write=args.command == "sync")


if __name__ == "__main__":
    sys.exit(main())
