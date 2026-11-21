"""One-way, additive migration from preserved old-mixed to Native.

Never touches the source; every destination SQLite DB is backed up first.
Only import complete successful gallery images, role cards, assignments and
conversation web messages. Legacy KV snapshots/jobs are NOT transferable.
Migration is idempotent and refuses conflicting image content or card data.
No image prompts, chat messages, secret values or session IDs are logged.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.gateway.conversations import valid_id, valid_sampling, _json
from backend.gateway.characters import valid_card

ID = re.compile(r"[a-f0-9]{32}\Z")


def safe_database_backup(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True) as original:
        with sqlite3.connect(target) as copy:
            original.backup(copy)


def json_payload(value):
    return json.loads(value) if isinstance(value, str) else value


def source_rows(db_file: Path, table: str):
    with sqlite3.connect(f"file:{db_file.as_posix()}?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        return [dict(row) for row in db.execute(f"SELECT * FROM {table}")]


def digest(path: Path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.digest()


def import_data(old: Path, native: Path, backup: Path, dry_run=False):
    old = old.resolve()
    native = native.resolve()
    backup = backup.resolve()
    if old == native or native.is_relative_to(old) or old.is_relative_to(native):
        raise ValueError("source, destination and backup must be separate")
    if backup.is_relative_to(old) or backup.is_relative_to(native):
        raise ValueError("backup directory must be outside the source and destination")
    role_db = old / "character/character_cards.sqlite3"
    chat_db = old / "chat/conversations.sqlite3"
    gallery_db = old / "chat/gallery-index.sqlite3"
    native_role = native / "character/character_cards.sqlite3"
    native_chat = native / "native-conversations.sqlite3"
    native_gallery = native / "images/gallery-index.sqlite3"
    all_files = [role_db, chat_db, gallery_db, native_role, native_chat, native_gallery]
    if any(not p.is_file() for p in all_files):
        raise FileNotFoundError("a source/destination database is missing")
    cards = source_rows(role_db, "cards")
    options = source_rows(role_db, "options")
    assignments = source_rows(role_db, "assignments")
    sessions = source_rows(chat_db, "conversations")
    images = source_rows(gallery_db, "images")
    native_cards = {r["id"]: r["data"] for r in source_rows(native_role, "cards")}
    native_sessions = {r["id"] for r in source_rows(native_chat, "conversations")}
    native_images = {r["id"]: r for r in source_rows(native_gallery, "images")}
    for c in cards:
        valid_card(json_payload(c["data"]))
        if c["id"] in native_cards and json_payload(native_cards[c["id"]]) != json_payload(c["data"]):
            raise ValueError("existing native card conflicts; abort instead of overwriting")
    for s in sessions:
        valid_id(s["id"])
        if s["id"] in native_sessions:
            continue  # preserve any conversation already created or edited in Native
        messages = json_payload(s["web_messages"])
        if (not isinstance(messages, list) or len(messages) > 2000 or
            any(not isinstance(m, dict) or m.get("role") not in
                ("user", "assistant", "system", "tool") for m in messages)):
            raise ValueError("invalid legacy chat messages; no partial import")
        if len(s["title"] or "") > 100:
            raise ValueError("legacy title exceeds Native limit")
        _json(messages)
        valid_sampling(json_payload(s["sampling_json"] or "{}"))
    total_bytes = 0
    copies = []
    for img in images:
        ident = img["id"]
        if not isinstance(ident, str) or not ID.fullmatch(ident):
            raise ValueError("invalid legacy gallery ID")
        source = old / "chat/generated-images" / (ident + ".png")
        destination = native / "images/generated-images" / (ident + ".png")
        if not source.is_file() or source.is_symlink() or source.stat().st_size < 8:
            raise FileNotFoundError("legacy gallery has missing or unsafe image")
        with source.open("rb") as fh:
            if fh.read(8) != b"\x89PNG\r\n\x1a\n":
                raise ValueError("invalid legacy PNG header")
        if destination.exists():
            if destination.is_symlink() or digest(source) != digest(destination):
                raise ValueError("existing Native image hash differs; abort instead of replacing")
        else:
            copies.append((source, destination))
            total_bytes += source.stat().st_size
    role_files = []
    # Preserve user-maintained character folders as well as database cards:
    # a role workflow directory (for example character/miku/) may not have
    # an entry in cards, yet is still part of the old character setup.
    for directory in (p for p in (old / "character").iterdir() if p.is_dir()):
        if directory.is_symlink():
            raise ValueError("role directory symlinks are forbidden")
        for item in directory.rglob("*"):
            if not item.is_file():
                continue
            if item.is_symlink():
                raise ValueError("role file symlinks are forbidden")
            rel = item.relative_to(old / "character")
            target = native / "character" / rel
            if target.exists():
                if target.is_symlink() or digest(target) != digest(item):
                    raise ValueError("existing role reference/worldbook conflicts")
            else:
                role_files.append((item, target))
                total_bytes += item.stat().st_size
    summary = {
        "legacy_cards": len(cards), "legacy_assignments": len(assignments),
        "legacy_sessions": len(sessions), "legacy_gallery_images": len(images),
        "new_conversations": len([r for r in sessions if r["id"] not in native_sessions]),
        "new_gallery_records": len([r for r in images if r["id"] not in native_images]),
        "new_files": len(copies) + len(role_files), "new_file_bytes": total_bytes,
        "dry_run": dry_run,
    }
    if dry_run:
        return summary
    if backup.exists():
        raise FileExistsError("backup directory already exists; never reuse a prior backup")
    backup.mkdir(parents=True)
    try:
        for label, path in (("native-characters", native_role),
                            ("native-sessions", native_chat),
                            ("native-gallery", native_gallery),
                            ("old-characters", role_db),
                            ("old-sessions", chat_db),
                            ("old-gallery", gallery_db)):
            safe_database_backup(path, backup / f"{label}.sqlite3")
        for source, destination in copies + role_files:
            destination.parent.mkdir(parents=True, exist_ok=True)
            # No replacement of existing images or reference files.
            with source.open("rb") as src, destination.open("xb") as dest:
                shutil.copyfileobj(src, dest, 1024 * 1024)
            if destination.stat().st_size != source.stat().st_size or digest(source) != digest(destination):
                raise IOError("migrated file verification failed")
        with sqlite3.connect(native_role, timeout=20) as db:
            with db:
                db.executemany("INSERT OR IGNORE INTO cards(id,data) VALUES(?,?)",
                               [(x["id"], x["data"]) for x in cards])
                db.executemany("INSERT OR IGNORE INTO options(key,value) VALUES(?,?)",
                               [(x["key"], x["value"]) for x in options])
                db.executemany("INSERT OR IGNORE INTO assignments(session_id,card_id) VALUES(?,?)",
                               [(x["session_id"], x["card_id"]) for x in assignments])
                for x in source_rows(role_db, "workflow_sessions"):
                    db.execute("INSERT OR IGNORE INTO workflow_sessions "
                               "(session_id,card_id,snapshot,initialized) VALUES(?,?,?,?)",
                               (x["session_id"], x["card_id"], x["snapshot"], x["initialized"]))
        with sqlite3.connect(native_chat, timeout=20) as db:
            with db:
                db.executemany("INSERT OR IGNORE INTO conversations "
                               "(id,title,pinned,sampling,web_messages,created,updated) "
                               "VALUES(?,?,?,?,?,?,?)",
                               [(x["id"], x["title"], x["pinned"],
                                 x["sampling_json"] or "{}", x["web_messages"],
                                 x["created"], x["updated"]) for x in sessions])
        with sqlite3.connect(native_gallery, timeout=20) as db:
            with db:
                db.executemany("INSERT OR IGNORE INTO images "
                               "(id,created,source,provider,model,prompt,session_id,"
                               "width,height,nsfw,parent_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                               [tuple(x[k] for k in (
                                "id", "created", "source", "provider", "model",
                                "prompt", "session_id", "width", "height",
                                "nsfw", "parent_id")) for x in images])
    except Exception:
        # Original data and backup untouched; do not silently delete any
        # successfully copied files, because users may have started using them.
        raise
    summary["dry_run"] = False
    summary["backup_folder"] = str(backup)
    return summary


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--legacy", type=Path, required=True)
    p.add_argument("--native-data", type=Path, required=True)
    p.add_argument("--backup", type=Path, required=True)
    p.add_argument("--apply", action="store_true")
    a = p.parse_args()
    result = import_data(a.legacy, a.native_data, a.backup, dry_run=not a.apply)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
