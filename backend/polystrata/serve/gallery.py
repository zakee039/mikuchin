"""Unified, indexed gallery for Mikuchin-generated images only.

Gallery only indexes 32-hex PNGs under SessionV1/generated-images. No
user uploads, character references, KV images or arbitrary filesystem paths.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from PIL import Image, ImageOps

IMAGE_ID = re.compile(r"^[a-f0-9]{32}$")
_MAX_BATCH = 150
_LOCK = threading.RLock()
_INITIALIZED = set()

class GalleryError(ValueError):
    pass

def _root(svc):
    sessions = getattr(svc, "session_v1", None)
    if sessions is None:
        raise GalleryError("gallery requires persistent chat storage")
    return sessions.root

def _file(svc, image_id):
    if not isinstance(image_id, str) or not IMAGE_ID.fullmatch(image_id):
        raise GalleryError("invalid image ID")
    root = _root(svc) / "generated-images"
    result = root / (image_id + ".png")
    if result.is_symlink():
        raise GalleryError("image symlinks are not supported")
    return result

@contextmanager
def _db(svc):
    p = _root(svc) / "gallery-index.sqlite3"
    c = sqlite3.connect(p, timeout=15)
    c.row_factory = sqlite3.Row
    try:
        c.execute("""CREATE TABLE IF NOT EXISTS images (
            id TEXT PRIMARY KEY,
            created REAL NOT NULL,
            source TEXT NOT NULL,
            provider TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL DEFAULT '',
            prompt TEXT NOT NULL DEFAULT '',
            session_id TEXT NOT NULL DEFAULT '',
            width INTEGER NOT NULL DEFAULT 0,
            height INTEGER NOT NULL DEFAULT 0,
            nsfw INTEGER NOT NULL DEFAULT 0,
            parent_id TEXT NOT NULL DEFAULT ''
        )""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_gallery_time ON images(created DESC, id)")
        c.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        with c:
            yield c
    finally:
        c.close()

def _size(path):
    try:
        with Image.open(path) as image:
            if image.format != "PNG" or image.width * image.height > 100_000_000:
                return None
            return image.width, image.height
    except (OSError, ValueError, Image.DecompressionBombError):
        return None

def _chat_history(svc):
    """Recover source/metadata for old chat tool images (including swipe variants)."""
    records = {}
    sessions = svc.session_v1
    with sessions.lock, sessions._db() as c:
        rows = c.execute("SELECT id, web_messages FROM conversations").fetchall()
        latest = c.execute("SELECT session_id,image_file,original_file "
                           "FROM recent_generated_images").fetchall()
    for row in rows:
        try:
            messages = json.loads(row["web_messages"])
        except (TypeError, ValueError):
            continue
        for message in messages if isinstance(messages, list) else []:
            if not isinstance(message, dict) or message.get("role") != "assistant":
                continue
            variants = [message] + ([v for v in message.get("swipes", [])
                                      if isinstance(v, dict)]
                                     if isinstance(message.get("swipes"), list) else [])
            for variant in variants:
                for tool in variant.get("tools", []) if isinstance(variant.get("tools"), list) else []:
                    if not isinstance(tool, dict) or tool.get("name") != "polystrata__generate_image":
                        continue
                    for key in ("image_file", "image_original_file"):
                        name = tool.get(key)
                        if isinstance(name, str) and name.endswith(".png") and IMAGE_ID.fullmatch(name[:-4]):
                            records[name[:-4]] = {
                                "source":"chat", "model": str(tool.get("image_model") or "")[:120],
                                "prompt":str(tool.get("image_prompt") or "")[:6000],
                                "session_id":row["id"],
                                "parent_id":(tool.get("image_file") or "")[:-4] if key == "image_original_file" else ""
                            }
    for row in latest:
        for name in (row["image_file"], row["original_file"]):
            if name and IMAGE_ID.fullmatch(name[:-4]) and name.endswith(".png"):
                records.setdefault(name[:-4], {"source":"chat","session_id":row["session_id"]})
    return records

def _insert(c, item):
    c.execute("""INSERT OR IGNORE INTO images
              (id,created,source,provider,model,prompt,session_id,width,height,nsfw,parent_id)
              VALUES (:id,:created,:source,:provider,:model,:prompt,:session_id,
                      :width,:height,:nsfw,:parent_id)""", item)

def _rebuild(svc, c):
    history = _chat_history(svc)
    root = _root(svc) / "generated-images"
    imported = 0
    for p in root.glob("*.png"):
        ident = p.stem
        if not IMAGE_ID.fullmatch(ident) or p.is_symlink():
            continue
        if c.execute("SELECT 1 FROM images WHERE id=?", (ident,)).fetchone():
            continue
        size = _size(p)
        if size is None:
            continue
        entry = history.get(ident, {})
        model = entry.get("model","")
        item = {
            "id":ident, "created":p.stat().st_mtime,
            "source":entry.get("source","studio"),
            "provider":entry.get("provider",""),
            "model":model, "prompt":entry.get("prompt",""),
            "session_id":entry.get("session_id",""),
            "width":size[0], "height":size[1],
            "nsfw":int("uncensored" in model.lower()),
            "parent_id":entry.get("parent_id","") if IMAGE_ID.fullmatch(entry.get("parent_id","")) else "",
        }
        _insert(c, item)
        imported += 1
    return imported

def _sync_missing(svc,c):
    # Lightweight integrity check of indexed names, not a full disk rescan.
    gone = [row["id"] for row in c.execute("SELECT id FROM images")
            if not _file(svc,row["id"]).is_file()]
    for ident in gone:
        c.execute("DELETE FROM images WHERE id=?", (ident,))
        try:
            (_root(svc) / "gallery-thumbnails" / (ident + ".jpg")).unlink(missing_ok=True)
        except OSError:
            pass
    return len(gone)

def ensure(svc):
    path = str(_root(svc))
    with _LOCK, _db(svc) as c:
        if path not in _INITIALIZED:
            mark = c.execute("SELECT value FROM meta WHERE key='history_backfill_v1'").fetchone()
            if not mark:
                count = _rebuild(svc,c)
                c.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('history_backfill_v1',?)",
                          (str(int(time.time())),))
            _INITIALIZED.add(path)
        # Only stat indexed paths; this does not re-scan the generated-images directory.
        # Chat deletion may remove a PNG between gallery visits.
        _sync_missing(svc,c)

def register(svc, name, *, source="studio", provider="local", model="",
             prompt="", session_id="", parent_id=""):
    """Idempotent success-path insert; re-register updates metadata without clearing NSFW."""
    if getattr(svc,"session_v1",None) is None:
        return
    ident = name[:-4] if isinstance(name,str) and name.endswith(".png") else name
    path = _file(svc,ident)
    if not path.is_file():
        raise FileNotFoundError("generated image is absent: " + str(ident))
    if source not in ("studio","chat"):
        raise GalleryError("invalid gallery source")
    size = _size(path)
    if size is None:
        raise GalleryError("generated file is not a valid PNG")
    if not isinstance(parent_id,str) or (parent_id and not IMAGE_ID.fullmatch(parent_id)):
        parent_id = ""
    model = str(model or "")[:120]
    item = {
        "id":ident,"created":path.stat().st_mtime,"source":source,
        "provider":str(provider or "local")[:20], "model":model,
        "prompt":str(prompt or "")[:6000],"session_id":str(session_id or "")[:64],
        "width":size[0],"height":size[1],
        "nsfw":int("uncensored" in model.lower()),"parent_id":parent_id,
    }
    with _LOCK, _db(svc) as c:
        c.execute("""INSERT INTO images
            (id,created,source,provider,model,prompt,session_id,width,height,nsfw,parent_id)
            VALUES (:id,:created,:source,:provider,:model,:prompt,:session_id,
                    :width,:height,:nsfw,:parent_id)
            ON CONFLICT(id) DO UPDATE SET
                source=excluded.source,provider=excluded.provider,
                model=excluded.model,prompt=excluded.prompt,
                session_id=excluded.session_id,
                width=excluded.width,height=excluded.height,
                parent_id=excluded.parent_id""", item)
    return ident

def _view(row):
    out = dict(row)
    out["nsfw"] = bool(out["nsfw"])
    return out

def _main_id(c, ident):
    """Resolve either the upscale image or its source image to one group."""
    row = c.execute("SELECT id,parent_id FROM images WHERE id=?", (ident,)).fetchone()
    if row is None:
        return None
    if row["parent_id"] and c.execute(
            "SELECT 1 FROM images WHERE id=?", (row["parent_id"],)).fetchone():
        return row["parent_id"]
    return ident


def _members(c, main_id):
    rows = c.execute(
        "SELECT id FROM images WHERE id=? OR parent_id=? ORDER BY id",
        (main_id, main_id)).fetchall()
    return [r["id"] for r in rows]


def _unlink_indexed(svc, c, ident):
    """Never accept paths: only delete an indexed, validated generated image ID."""
    path = _file(svc, ident)
    path.unlink(missing_ok=True)
    c.execute("DELETE FROM images WHERE id=?", (ident,))
    thumb = _root(svc) / "gallery-thumbnails" / (ident + ".jpg")
    try:
        thumb.unlink(missing_ok=True)
    except OSError:
        pass


def listing(svc, *, limit=60, offset=0, source="all", order="newest"):
    if type(limit) is not int or not 1 <= limit <= 120:
        raise GalleryError("limit must be 1-120")
    if type(offset) is not int or not 0 <= offset <= 2000000:
        raise GalleryError("offset out of range")
    if source not in ("all","studio","chat","local","api"):
        raise GalleryError("invalid gallery filter")
    if order not in ("newest","oldest"):
        raise GalleryError("invalid gallery sort")
    ensure(svc)
    where = {"all":"1=1","studio":"source='studio'","chat":"source='chat'",
             "local":"provider='local'","api":"provider='api'"}[source]
    sorting = "DESC" if order == "newest" else "ASC"
    # Pagination is by *artwork group*, not by physical PNG. A 4x image
    # is the cover and its original child is shown via a small count badge.
    main_filter = "(i.parent_id='' OR NOT EXISTS(SELECT 1 FROM images p WHERE p.id=i.parent_id))"
    where = where.replace("source=", "i.source=").replace("provider=", "i.provider=")
    combined = main_filter + " AND (" + where + ")"
    with _LOCK, _db(svc) as c:
        total = c.execute(f"SELECT COUNT(*) FROM images i WHERE {combined}").fetchone()[0]
        cover_rows = c.execute(
            f"SELECT i.* FROM images i WHERE {combined} "
            f"ORDER BY i.created {sorting},i.id {sorting} LIMIT ? OFFSET ?",
            (limit, offset)).fetchall()
        items = [_view(r) for r in cover_rows]
        if items:
            names = [item["id"] for item in items]
            placeholders = ",".join("?" for _ in names)
            children = c.execute(
                f"SELECT id,parent_id,nsfw,width,height FROM images "
                f"WHERE parent_id IN ({placeholders}) ORDER BY width*height, id", names).fetchall()
            child_map = {}
            for child in children:
                child_map.setdefault(child["parent_id"], []).append(child)
            for item in items:
                attached = child_map.get(item["id"], [])
                item["variant_count"] = 1 + len(attached)
                item["variants"] = (
                    {"upscaled": item["id"], "original": attached[0]["id"]}
                    if attached else {"upscaled": None, "original": None})
                item["nsfw"] = item["nsfw"] or any(bool(ch["nsfw"]) for ch in attached)
    return {"items":items,"total":total,"limit":limit,"offset":offset}


def upscale_source(svc, ident):
    """Resolve a singleton indexed artwork eligible for an on-demand 4x job."""
    ensure(svc)
    path = _file(svc, ident)
    with _LOCK, _db(svc) as c:
        row = c.execute("SELECT * FROM images WHERE id=?", (ident,)).fetchone()
        if row is None or not path.is_file():
            raise GalleryError("original image no longer exists")
        if row["parent_id"] or c.execute(
                "SELECT 1 FROM images WHERE parent_id=? LIMIT 1", (ident,)).fetchone():
            raise GalleryError("this artwork already has an original/4x pair")
        if row["width"] <= 0 or row["height"] <= 0:
            raise GalleryError("invalid original image size")
        return _view(row)


def detail(svc, ident):
    """Return an artwork group by either the original or its 4x image ID."""
    ensure(svc)
    _file(svc, ident)  # validate opaque image ID, not arbitrary paths
    with _LOCK, _db(svc) as c:
        main = _main_id(c, ident)
        if main is None:
            raise GalleryError("gallery image not found")
        cover = c.execute("SELECT * FROM images WHERE id=?", (main,)).fetchone()
        children = c.execute(
            "SELECT id FROM images WHERE parent_id=? ORDER BY width*height,id", (main,)).fetchall()
        item = _view(cover)
        item["variant_count"] = 1 + len(children)
        item["variants"] = ({"upscaled": main, "original": children[0]["id"]} if children
                            else {"upscaled": None, "original": None})
        return item


def attach_upscaled(svc, original_id, png):
    """Atomically promote an existing original into a 4x artwork group.

    The newly generated 4x becomes the cover; the original remains its child.
    A deleted or already paired original never gets silently overwritten.
    """
    if not isinstance(png, bytes):
        raise GalleryError("upscaled image must be PNG bytes")
    original = upscale_source(svc, original_id)
    image_id = secrets.token_hex(16)
    dest = _file(svc, image_id)
    try:
        dest.write_bytes(png)
        dimensions = _size(dest)
        if dimensions != (original["width"] * 4, original["height"] * 4):
            raise GalleryError("4x image dimensions do not match the original")
        with _LOCK, _db(svc) as c:
            current = c.execute("SELECT * FROM images WHERE id=?", (original_id,)).fetchone()
            if current is None or current["parent_id"] or c.execute(
                    "SELECT 1 FROM images WHERE parent_id=? LIMIT 1", (original_id,)).fetchone():
                raise GalleryError("original image was deleted or already upscaled")
            _insert(c, {"id": image_id, "created": current["created"],
                        "source": current["source"], "provider": current["provider"],
                        "model": current["model"], "prompt": current["prompt"],
                        "session_id": current["session_id"], "width": dimensions[0],
                        "height": dimensions[1], "nsfw": current["nsfw"], "parent_id": ""})
            c.execute("UPDATE images SET parent_id=? WHERE id=?", (image_id, original_id))
        return image_id
    except BaseException:
        dest.unlink(missing_ok=True)
        raise

def set_nsfw_many(svc, ids, nsfw):
    """One manual NSFW setting applies to both original and 4x versions."""
    if type(nsfw) is not bool:
        raise GalleryError("nsfw must be boolean")
    if not isinstance(ids, list) or not 1 <= len(ids) <= _MAX_BATCH:
        raise GalleryError("select 1-150 artworks")
    if any(not isinstance(i,str) or not IMAGE_ID.fullmatch(i) for i in ids):
        raise GalleryError("invalid image IDs")
    ensure(svc)
    with _LOCK, _db(svc) as c:
        mains = list(dict.fromkeys(_main_id(c,i) for i in ids))
        if None in mains:
            raise GalleryError("image not found")
        for main in mains:
            members = _members(c,main)
            c.executemany("UPDATE images SET nsfw=? WHERE id=?",
                          [(int(nsfw), i) for i in members])
    return {"updated":mains, "nsfw":nsfw}


def set_nsfw(svc,ident,nsfw):
    result = set_nsfw_many(svc,[ident],nsfw)
    return {"id":result["updated"][0],"nsfw":nsfw}

def delete_many(svc,ids):
    """Normal and multi-select delete entire artworks, including their 4x originals."""
    if not isinstance(ids,list) or not 1 <= len(ids) <= _MAX_BATCH:
        raise GalleryError("select 1-150 artworks")
    if any(not isinstance(x,str) or not IMAGE_ID.fullmatch(x) for x in ids):
        raise GalleryError("invalid image IDs")
    ensure(svc)
    deleted, failed, complete_groups = [], [], 0
    with _LOCK, _db(svc) as c:
        mains = list(dict.fromkeys(_main_id(c,i) for i in ids))
        for main in mains:
            if main is None:
                failed.append({"error":"image not found"})
                continue
            members = _members(c,main)
            good = True
            for ident in members:
                try:
                    _unlink_indexed(svc,c,ident)
                    deleted.append(ident)
                except OSError:
                    good = False
                    failed.append({"id":ident,"error":"cannot delete image file"})
            if good:
                complete_groups += 1
    return {"deleted":deleted,"deleted_groups":complete_groups,"failed":failed}


def delete_variant(svc, ident, variant):
    """Delete only one variant in a paired artwork.

    Removing 4x promotes the original into a standalone gallery cover;
    removing the original leaves the 4x picture as a standalone cover.
    """
    if variant not in ("original","upscaled"):
        raise GalleryError("variant must be original or upscaled")
    ensure(svc)
    _file(svc,ident)
    with _LOCK, _db(svc) as c:
        main = _main_id(c,ident)
        if main is None:
            raise GalleryError("image not found")
        children = c.execute("SELECT id FROM images WHERE parent_id=? ORDER BY width*height,id",
                             (main,)).fetchall()
        if not children:
            raise GalleryError("this image has no original/4x pair")
        if variant == "original":
            removed = [r["id"] for r in children]
            for original in removed:
                _unlink_indexed(svc,c,original)
            remaining = main
        else:
            removed = [main]
            # Promote one surviving original and keep metadata and NSFW selection.
            cover = c.execute("SELECT nsfw,model,prompt,source,provider,session_id FROM images WHERE id=?",
                              (main,)).fetchone()
            promoted = children[0]["id"]
            _unlink_indexed(svc,c,main)
            c.execute("""UPDATE images SET parent_id='',nsfw=?,model=CASE WHEN model='' THEN ? ELSE model END,
                      prompt=CASE WHEN prompt='' THEN ? ELSE prompt END,
                      source=?,provider=?,session_id=? WHERE id=?""",
                      (cover["nsfw"],cover["model"],cover["prompt"],cover["source"],
                       cover["provider"],cover["session_id"],promoted))
            c.execute("UPDATE images SET parent_id=? WHERE parent_id=?",
                      (promoted,main))
            remaining = promoted
    return {"deleted":removed,"remaining":remaining,"variant":variant}

def repair(svc):
    ensure(svc)
    with _LOCK, _db(svc) as c:
        removed = _sync_missing(svc,c)
        added = _rebuild(svc,c)
    return {"added":added,"removed":removed}

def thumbnail(svc,ident):
    """Only serve indexed, opaque generated IDs, never arbitrary filesystem files."""
    path = _file(svc,ident)
    ensure(svc)
    with _LOCK, _db(svc) as c:
        if not c.execute("SELECT 1 FROM images WHERE id=?", (ident,)).fetchone():
            return None
    if not path.is_file():
        return None
    cached = _root(svc) / "gallery-thumbnails" / (ident + ".jpg")
    if cached.is_file() and cached.stat().st_mtime >= path.stat().st_mtime:
        return cached.read_bytes()
    with _LOCK:
        cached.parent.mkdir(exist_ok=True)
        tmp = cached.with_name("." + ident + "." + secrets.token_hex(4) + ".tmp")
        try:
            with Image.open(path) as src:
                if src.width * src.height > 100_000_000:
                    return None
                img = ImageOps.exif_transpose(src).convert("RGB")
                img.thumbnail((420,420),Image.Resampling.LANCZOS)
                img.save(tmp, format="JPEG",quality=76,optimize=True)
            os.replace(tmp,cached)
            return cached.read_bytes()
        except (OSError,ValueError,Image.DecompressionBombError):
            return None
        finally:
            tmp.unlink(missing_ok=True)
