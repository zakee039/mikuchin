"""Desktop-owned image jobs: browser clients submit and then disconnect freely.

A single daemon worker per session store executes jobs without using the request
handler, its socket, or its client-disconnect cancellation event. Durable task
metadata may include completed chat-image prompts; credentials and image bytes
remain outside the task database.
"""
from __future__ import annotations

import json
import base64
import hashlib
import io
import os
import queue
import re
from collections import deque
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from PIL import Image

from serve import gallery as gallery_api
from serve import image_api_services as api_images
from serve import image_task_status
from serve import images as images_api

_LOCK = threading.RLock()
_WORKERS = {}
# Must not be smaller than a provider's 20 concurrent requests. Leave room for
# other providers, local jobs, and queued work; this remains a safety limit.
_MAX_PENDING = 80
_MAX_STUDIO_RECORDS = 100
_REF_ID = re.compile(r"^[a-f0-9]{64}$")
_DATA_URL = re.compile(r"^data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/=]+)$")
_REF_LIMIT = 5 * 1024 * 1024
_MAX_REFS = 8
_REQUEST_FIELDS = frozenset({"prompt", "positive_prompt", "natural_prompt", "negative_prompt", "steps",
    "seed", "size", "response_format", "strata_upscale", "strata_image_profile",
    "strata_lora_id", "strata_denoise_strength", "strata_reference_assets", "strata_reference_mode"})


def _db_path(svc):
    sessions = getattr(svc, "session_v1", None)
    if sessions is None:
        raise ValueError("persistent image storage is unavailable")
    return sessions.root / "image-jobs.sqlite3"


@contextmanager
def _db(svc):
    conn = sqlite3.connect(_db_path(svc), timeout=15)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("""CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY, kind TEXT NOT NULL, source_id TEXT NOT NULL DEFAULT '',
            state TEXT NOT NULL, phase TEXT NOT NULL, result TEXT NOT NULL DEFAULT '{}',
            error TEXT NOT NULL DEFAULT '', created REAL NOT NULL, updated REAL NOT NULL,
            tool_call_id TEXT NOT NULL DEFAULT '', profile_id TEXT NOT NULL DEFAULT '',
            prompt_summary TEXT NOT NULL DEFAULT '', requested_size TEXT NOT NULL DEFAULT '',
            request_json TEXT NOT NULL DEFAULT '{}',
            started_at REAL, finished_at REAL
        )""")
        columns = {row[1] for row in conn.execute("PRAGMA table_info(jobs)")}
        if "tool_call_id" not in columns:
            conn.execute("ALTER TABLE jobs ADD COLUMN tool_call_id TEXT NOT NULL DEFAULT ''")
        for col in ("profile_id", "prompt_summary", "requested_size", "request_json"):
            if col not in columns:
                conn.execute(f"ALTER TABLE jobs ADD COLUMN {col} TEXT NOT NULL DEFAULT ''")
        for col in ("started_at", "finished_at"):
            if col not in columns:
                conn.execute(f"ALTER TABLE jobs ADD COLUMN {col} REAL")
        # Previously released studio jobs have no full request: keep their
        # results/history, but never claim they can be faithfully replayed.
        conn.execute("UPDATE jobs SET request_json='{}' WHERE request_json='' OR request_json IS NULL")
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def _initialize(svc):
    with _LOCK, _db(svc) as db:
        key = str(_db_path(svc))
        if key not in _WORKERS:
            # An interrupted server process cannot leave a false "running" task.
            db.execute("UPDATE jobs SET state='success' WHERE kind='generate' AND state='done'")
            db.execute("UPDATE jobs SET state='failed' WHERE kind='generate' AND state IN ('error','interrupted')")
            db.execute("UPDATE jobs SET state='failed', finished_at=COALESCE(finished_at, ?), "
                       "phase='服务已重启，任务未完成', "
                       "error='桌面服务已重启；原请求未完成，请决定是否重新生成' "
                       "WHERE kind='generate' AND state IN ('queued','working','running')",
                       (time.time(),))
            db.execute("UPDATE jobs SET state='interrupted', phase='服务已重启，任务未完成', "
                       "error='桌面服务已重启；请重新提交任务' WHERE kind!='generate' "
                       "AND state IN ('queued','working')")
            _WORKERS[key] = {"queue": queue.Queue(), "thread": None,
                             "api_queue": queue.Queue(), "api_thread": None,
                             "api_active": {}, "service": svc}


def _public(row):
    result = dict(row)
    result["result"] = json.loads(result.get("result") or "{}")
    result["request"] = json.loads(result.pop("request_json", None) or "{}")
    start = result.get("started_at")
    finish = result.get("finished_at")
    if result["kind"] == "generate":
        result["elapsed_s"] = round(max(0.0,
            (finish if finish is not None else time.time()) - start), 1) if start is not None else None
        result["legacy_timer_unknown"] = start is None and result["state"] != "draft"
    else:
        result["elapsed_s"] = round(max(0.0, result["updated"] - result["created"]), 1)
    return result


def _reference_file(svc, asset_id):
    if not isinstance(asset_id, str) or not _REF_ID.fullmatch(asset_id):
        raise ValueError("invalid reference asset ID")
    folder = svc.session_v1.root / "image-job-references"
    path = folder / (asset_id + ".bin")
    if path.is_symlink():
        raise ValueError("reference symlinks are not allowed")
    return path


def reference_bytes(svc, asset_id):
    """Private server asset; GET route must authenticate before calling."""
    p = _reference_file(svc, asset_id)
    if not p.is_file() or p.stat().st_size > _REF_LIMIT:
        raise ValueError("reference image not found")
    raw = p.read_bytes()
    if hashlib.sha256(raw).hexdigest() != asset_id:
        raise ValueError("reference asset checksum mismatch")
    with Image.open(io.BytesIO(raw)) as image:
        if image.format not in ("PNG", "JPEG", "WEBP"):
            raise ValueError("invalid stored reference image")
        mime = {"PNG":"image/png", "JPEG":"image/jpeg", "WEBP":"image/webp"}[image.format]
    return raw, mime


def _store_reference(svc, data_url):
    if not isinstance(data_url, str) or len(data_url) > (_REF_LIMIT * 4 // 3 + 128):
        raise ValueError("reference must be a PNG/JPEG/WebP image of at most 5 MB")
    match = _DATA_URL.fullmatch(data_url)
    if not match:
        raise ValueError("reference image must be a PNG/JPEG/WebP data URL")
    try:
        raw = base64.b64decode(match.group(2), validate=True)
        if not 0 < len(raw) <= _REF_LIMIT:
            raise ValueError("reference image exceeds 5 MB")
        with Image.open(io.BytesIO(raw)) as image:
            if image.format.lower() != match.group(1).replace("jpeg", "jpeg") or \
                    image.width * image.height > 16_000_000:
                raise ValueError("unsupported reference image dimensions or format")
            image.verify()
    except (OSError, ValueError, base64.binascii.Error, Image.DecompressionBombError) as exc:
        raise ValueError("invalid or oversized reference image") from exc
    ident = hashlib.sha256(raw).hexdigest()
    p = _reference_file(svc, ident)
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.is_file():
        tmp = p.with_suffix("." + secrets.token_hex(8) + ".tmp")
        try:
            tmp.write_bytes(raw)
            os.replace(tmp, p)
        finally:
            tmp.unlink(missing_ok=True)
    return ident


def _prepare_request(svc, request):
    """Validate and snapshot all supported form fields, storing images outside SQLite."""
    if not isinstance(request, dict):
        raise ValueError("image request must be an object")
    if any(k not in _REQUEST_FIELDS | {"strata_reference_images", "strata_reference_image"}
           for k in request):
        raise ValueError("unknown image generation parameter")
    result = {k: v for k, v in request.items() if k in _REQUEST_FIELDS and k != "strata_reference_assets"}
    for field, limit in (("prompt",16000),("positive_prompt",12000),
                         ("natural_prompt",6000),("negative_prompt",3000)):
        if not isinstance(result.get(field,""), str) or len(result.get(field,"")) > limit:
            raise ValueError(field + " is invalid")
    profile = result.get("strata_image_profile", "default")
    if not isinstance(profile,str) or len(profile) > 64:
        raise ValueError("invalid image profile")
    result["strata_image_profile"] = profile
    if len(json.dumps(result,ensure_ascii=False)) > 44000:
        raise ValueError("image parameters are too large")
    refs = request.get("strata_reference_assets", [])
    if not isinstance(refs,list):
        raise ValueError("reference assets must be a list")
    legacy_refs = request.get("strata_reference_images")
    if legacy_refs is not None:
        if refs or not isinstance(legacy_refs,list):
            raise ValueError("invalid reference list")
        refs = [{"data_url":u, "name":f"参考图 {i+1}"} for i,u in enumerate(legacy_refs)]
    elif request.get("strata_reference_image") is not None:
        if refs:
            raise ValueError("duplicate reference images")
        refs = [{"data_url":request["strata_reference_image"], "name":"参考图 1"}]
    if len(refs) > _MAX_REFS:
        raise ValueError("at most 8 reference images per task")
    prepared = []
    for index, item in enumerate(refs):
        if not isinstance(item,dict):
            raise ValueError("invalid reference description")
        name = item.get("name", f"参考图 {index+1}")
        if not isinstance(name,str):
            raise ValueError("reference name must be text")
        name = name.strip()[:120] or f"参考图 {index+1}"
        ident = item.get("id")
        if ident is None:
            ident = _store_reference(svc, item.get("data_url"))
        else:
            path = _reference_file(svc, ident)
            # Already-validated immutable content-addressed images do not need
            # 5 MB reads and image decoding on every debounced keystroke.
            if not path.is_file() or not 0 < path.stat().st_size <= _REF_LIMIT:
                raise ValueError("reference image not found")
        prepared.append({"id":ident, "name":name})
    result["strata_reference_assets"] = prepared
    result["response_format"] = "url"
    return result


def _expand_request(svc, request):
    """Load reference bytes only for the generation worker, never in job JSON."""
    expanded = {k:v for k,v in request.items() if k != "strata_reference_assets"}
    refs = request.get("strata_reference_assets") or []
    profile = request.get("strata_image_profile", "default")
    if profile.startswith("api-"):
        service = api_images.get(svc, profile)
        mode = (service or {}).get("reference_mode", "none")
        selected = refs if mode == "multi" else refs[:1] if mode == "single" else []
        if selected:
            expanded["strata_reference_images"] = [
                f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"
                for raw,mime in (reference_bytes(svc,ref["id"]) for ref in selected)]
    else:
        if refs and request.get("strata_reference_mode") in ("single", "img2img", "qwen_edit"):
            raw,mime = reference_bytes(svc, refs[0]["id"])
            expanded["strata_reference_image"] = f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"
            expanded.setdefault("strata_denoise_strength", 0.65)
    return expanded


def _trim_studio(svc, db, protected_ids=()):
    count = db.execute("SELECT COUNT(*) FROM jobs WHERE kind='generate'").fetchone()[0]
    if count < _MAX_STUDIO_RECORDS:
        return
    remove = count - _MAX_STUDIO_RECORDS + 1
    rows = db.execute("SELECT id FROM jobs WHERE kind='generate' AND state IN ('success','failed') "
                      "ORDER BY updated ASC, created ASC").fetchall()
    rows = [row for row in rows if row["id"] not in protected_ids][:remove]
    if len(rows) < remove:
        raise ValueError("已保存 100 条任务且草稿/进行中无法自动清理，请先删除不需要的草稿")
    db.executemany("DELETE FROM jobs WHERE id=?", [(row["id"],) for row in rows])


def _gc_references(svc):
    """Only delete assets unreferenced by every surviving task."""
    with _LOCK, _db(svc) as db:
        rows = db.execute("SELECT request_json FROM jobs WHERE kind='generate'").fetchall()
        keep = set()
        for row in rows:
            try:
                for ref in json.loads(row["request_json"] or "{}").get("strata_reference_assets",[]):
                    if _REF_ID.fullmatch(ref.get("id", "")):
                        keep.add(ref["id"])
            except (TypeError,ValueError,AttributeError):
                continue
        folder = svc.session_v1.root / "image-job-references"
        if folder.exists():
            for p in folder.glob("*.bin"):
                if _REF_ID.fullmatch(p.stem) and p.stem not in keep and not p.is_symlink():
                    p.unlink(missing_ok=True)


def snapshot(svc, job_id=None, limit=100, session_id=None, kind=None):
    _initialize(svc)
    with _LOCK, _db(svc) as db:
        if job_id:
            if not image_task_status.valid(job_id):
                raise ValueError("invalid image job ID")
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                return {"state": "unknown", "id": job_id}
            obj = _public(row)
            if obj["state"] in ("working", "running"):
                extra = image_task_status.snapshot(job_id, gen=svc.images, profiles=svc.image_profiles)
                for key in ("step", "steps"):
                    if key in extra:
                        obj[key] = extra[key]
            return obj
        if not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("invalid job list limit")
        if kind is not None and kind not in ("generate", "chat", "upscale"):
            raise ValueError("invalid image job kind")
        if session_id is not None:
            from serve.session_v1 import valid_id
            valid_id(session_id)
            rows = db.execute("SELECT * FROM jobs WHERE kind='chat' AND source_id=? "
                              "ORDER BY updated DESC, created DESC LIMIT ?", (session_id, limit)).fetchall()
        elif kind:
            rows = db.execute("SELECT * FROM jobs WHERE kind=? "
                              "ORDER BY updated DESC, created DESC LIMIT ?", (kind, limit)).fetchall()
            if kind == "generate":
                # Active tasks must stay visible even if 40 newer completed
                # requests exist (e.g. 20-way API concurrency + queue).
                active_rows = db.execute("SELECT * FROM jobs WHERE kind='generate' "
                    "AND state='running' ORDER BY updated DESC").fetchall()
                unique = {row["id"]: row for row in [*rows, *active_rows]}
                rows = sorted(unique.values(), key=lambda row: (row["updated"],row["created"]), reverse=True)
        else:
            rows = db.execute("SELECT * FROM jobs ORDER BY updated DESC LIMIT ?", (limit,)).fetchall()
    jobs = [_public(row) for row in rows]
    for obj in jobs:
        if obj["state"] in ("working", "running"):
            extra = image_task_status.snapshot(obj["id"], gen=svc.images, profiles=svc.image_profiles)
            for name in ("step", "steps"):
                if name in extra:
                    obj[name] = extra[name]
    return {"jobs": jobs}


def delete_records(svc, *, job_id=None, clear_completed=False):
    """Discard terminal studio task metadata; never delete generated images.

    Active jobs are immutable in this operation so the worker cannot update a
    record that was removed while it was generating or delivering a result.
    """
    if (clear_completed is not True and job_id is None):
        raise ValueError("select a task to delete")
    if job_id is not None and not image_task_status.valid(job_id):
        raise ValueError("invalid image job ID")
    _initialize(svc)
    with _LOCK, _db(svc) as db:
        if clear_completed is True:
            cursor = db.execute("DELETE FROM jobs WHERE kind='generate' "
                                "AND state IN ('success', 'failed')")
        else:
            cursor = db.execute("DELETE FROM jobs WHERE id=? AND kind='generate' "
                                "AND state IN ('draft','success','failed')", (job_id,))
        count = cursor.rowcount
    if count:
        _gc_references(svc)
    return {"deleted": count}


def _mark(svc, job_id, phase, state="working", result=None, error=None, provider="local", start=False):
    now = time.time()
    with _LOCK, _db(svc) as db:
        row = db.execute("SELECT kind FROM jobs WHERE id=?", (job_id,)).fetchone()
        db_state = ({"working":"running","done":"success","error":"failed"}.get(state,state)
                    if row and row["kind"] == "generate" else state)
        terminal = row is not None and row["kind"] == "generate" and db_state in ("success", "failed")
        db.execute("UPDATE jobs SET phase=?, state=?, result=COALESCE(?,result), "
                   "error=COALESCE(?,error), updated=?, "
                   "started_at=CASE WHEN ? AND started_at IS NULL THEN ? ELSE started_at END, "
                   "finished_at=CASE WHEN ? AND finished_at IS NULL THEN ? ELSE finished_at END WHERE id=?",
                   (str(phase)[:100], db_state,
                    json.dumps(result, ensure_ascii=False) if result is not None else None,
                    str(error)[:500] if error else None, now, start, now, terminal, now, job_id))
    image_task_status.mark(job_id, phase, state=state, error=error, provider=provider)


def _generate(svc, req, job_id):
    req = _expand_request(svc, req)
    profile_id = req.get("strata_image_profile", "default")
    if isinstance(profile_id, str) and profile_id.startswith("api-"):
        _mark(svc, job_id, "正在请求 API", provider="api", start=True)
        out = api_images.generate(svc, req, ident=profile_id,
            on_status=lambda phase: _mark(svc, job_id, phase, provider="api"),
            diagnostic_id=job_id)
        meta = out.get("strata") or {}
        primary = gallery_api.register(svc, meta.get("image_file"), source="studio",
            provider="api", model=out.get("model"), prompt=req.get("prompt"))
        for original in meta.get("upscale_original_files") or []:
            if original:
                gallery_api.register(svc, original, source="studio", provider="api",
                    model=out.get("model"), prompt=req.get("prompt"), parent_id=primary)
        return {"image_ids": [primary], "upscale_applied": bool(meta.get("upscale_applied")),
                "upscale_error": meta.get("upscale_error"), "model": out.get("model"),
                "size": out.get("size")}
    gen = svc.images
    if gen is None:
        raise ValueError("本地生图尚未配置")
    if profile_id not in ("default", gen.cfg.get("profile_id") or "default"):
        gen = svc.image_profiles.get(profile_id)
        if gen is None:
            raise ValueError("image model not found")
    missing = gen.missing()
    if missing:
        raise ValueError("selected image model is unavailable")
    job = images_api.parse_request({**req, "response_format": "url"}, gen.cfg)
    if svc.session_v1:
        gen.dir = svc.session_v1.root / "generated-images"
        gen.dir.mkdir(parents=True, exist_ok=True)
        gen.keep_files = 2**31 - 1
    _mark(svc, job_id, "等待本地生成任务")
    with images_api.gpu_turn(svc, gen, job) as _policy:
        _mark(svc, job_id, "本地模型生成中", start=True)
        generated, figures = gen.run(job)  # no browser cancellation event
        _mark(svc, job_id, "正在执行本地超分")
        generated, upscale = images_api.postprocess(gen, generated, job)
        figures.update(upscale)
    _mark(svc, job_id, "正在保存图片")
    out = gen.response(generated, job, figures, "http://127.0.0.1")
    ids = []
    for datum in out.get("data", []):
        name = str(datum.get("url", "")).rsplit("/", 1)[-1]
        ids.append(gallery_api.register(svc, name, source="studio", provider="local",
            model=gen.model, prompt=job.get("prompt")))
    for index, original in enumerate(figures.get("upscale_original_files") or []):
        if original and index < len(ids):
            gallery_api.register(svc, original, source="studio", provider="local",
                model=gen.model, prompt=job.get("prompt"), parent_id=ids[index])
    return {"image_ids": ids, "model": gen.model,
            "size": out.get("size"), "upscale_applied": bool(upscale.get("upscale_applied")),
            "upscale_error": upscale.get("upscale_error")}


def _upscale(svc, source_id, job_id):
    from serve.upscale import _upscale_one
    source = gallery_api.upscale_source(svc, source_id)
    gen = svc.images
    cfg = (getattr(gen, "cfg", {}) or {}).get("upscaler") or {}
    if gen is None or not cfg.get("enabled"):
        raise ValueError("桌面端尚未配置可用的 4x 超分组件")
    path = gallery_api._file(svc, source_id)
    original = path.read_bytes()
    w, h = source["width"], source["height"]
    if max(w, h) * 4 > 6144:
        raise ValueError("超分后最长边不能超过 6144 像素")
    _mark(svc, job_id, "等待超分 GPU 任务")
    with images_api.gpu_turn(svc, gen, {"width": w, "height": h}) as _policy:
        _mark(svc, job_id, "正在执行 4x 超分", start=True)
        png, secs = _upscale_one(original, cfg)
    _mark(svc, job_id, "正在保存 4x 图片")
    cover = gallery_api.attach_upscaled(svc, source_id, png)
    return {"image_ids": [cover], "original_id": source_id,
            "upscaled_id": cover, "seconds": secs}


def _run_one(svc, job_id, kind, payload):
    try:
        if kind == "chat":
            hub, arguments, call_id = payload
            _mark(svc, job_id, "正在执行聊天生图", start=True)
            output = hub._execute_image("polystrata__generate_image", arguments)
            if not output.get("ok"):
                raise RuntimeError(output.get("text") or "聊天生图失败")
            result = {key: output[key] for key in (
                "image_file", "image_original_file", "image_prompt", "image_model",
                "edited_previous", "upscale_applied", "upscale_fallback", "text")
                if key in output}
            result["tool_call_id"] = call_id
            followup = getattr(hub, "visual_followup", None)
            if callable(followup):
                try:
                    _mark(svc, job_id, "正在理解已生成图片")
                    reply = []
                    for event_type, event in followup(call_id, arguments, output) or ():
                        if event_type == "event" and event.kind == "content" and event.text:
                            reply.append(event.text)
                    result["reply_text"] = "".join(reply).strip()[:1500] or "图片已生成。"
                except Exception as followup_error:
                    print(f"[mikuchin] image visual follow-up skipped: {followup_error}", flush=True)
                    result["reply_text"] = "图片已生成。"
        else:
            result = (_generate(svc, payload, job_id) if kind == "generate" else
                      _upscale(svc, payload, job_id))
        _mark(svc, job_id, "已完成", state="done", result=result)
        if kind == "chat" and hub.delivery_session_id:
            try:
                svc.session_v1.complete_image_tool_job(
                    hub.delivery_session_id, job_id, call_id, result)
            except Exception as write_exc:
                print(f"[mikuchin] chat image result persistence: {write_exc}", flush=True)
    except Exception as exc:
        _mark(svc, job_id, "任务失败", state="error",
              error=f"{type(exc).__name__}: {exc}")
        if kind == "chat" and hub.delivery_session_id:
            try:
                svc.session_v1.complete_image_tool_job(
                    hub.delivery_session_id, job_id, call_id,
                    {"error": f"{type(exc).__name__}: {exc}"[:500]})
            except Exception as write_exc:
                print(f"[mikuchin] chat image failure persistence: {write_exc}", flush=True)
        print(f"[mikuchin] detached image job {job_id} failed: {type(exc).__name__}: {exc}",
              flush=True)


def _work(svc, jobs):
    """Local GPU work and chat tasks stay serialized."""
    while True:
        job_id, kind, payload = jobs.get()
        try:
            _run_one(svc, job_id, kind, payload)
        finally:
            jobs.task_done()


def _dispatch_api(svc, state):
    """API jobs use a separate pool with a live per-provider concurrency cap.

    Decreasing a cap drains already-running jobs, but starts no new jobs for
    that provider until it is back below the new limit. No GPU worker is used.
    """
    jobs = state["api_queue"]
    waiting = deque()
    while True:
        try:
            waiting.append(jobs.get(timeout=.10))
        except queue.Empty:
            pass
        remaining = deque()
        while waiting:
            job_id, kind, payload = waiting.popleft()
            profile_id = payload["strata_image_profile"]
            try:
                service = api_images.get(svc, profile_id)
                limit = (service or {}).get("concurrency", 1)
            except Exception:
                limit = 1
            with _LOCK:
                active = state["api_active"].get(profile_id, 0)
                allowed = active < limit
                if allowed:
                    state["api_active"][profile_id] = active + 1
            if not allowed:
                remaining.append((job_id, kind, payload))
                continue
            print(f"[mikuchin:image-pool] job={job_id} profile={profile_id} "
                  f"active={active+1}/{limit}", flush=True)

            def run(job_id=job_id, kind=kind, payload=payload, profile_id=profile_id):
                try:
                    _run_one(svc, job_id, kind, payload)
                finally:
                    with _LOCK:
                        count = state["api_active"].get(profile_id, 1) - 1
                        if count:
                            state["api_active"][profile_id] = count
                        else:
                            state["api_active"].pop(profile_id, None)
                    jobs.task_done()

            threading.Thread(target=run, name="mikuchin-api-image-" + profile_id,
                             daemon=True).start()
        waiting = remaining


def _pending_count(db):
    return db.execute("SELECT COUNT(*) FROM jobs WHERE state IN ('queued','working','running')").fetchone()[0]


def _enqueue(svc, ident, kind, payload):
    state = _WORKERS[str(_db_path(svc))]
    profile = payload.get("strata_image_profile", "default") if kind == "generate" else ""
    if kind == "generate" and profile.startswith("api-"):
        if state["api_thread"] is None or not state["api_thread"].is_alive():
            state["api_thread"] = threading.Thread(target=_dispatch_api, args=(svc,state),
                name="mikuchin-api-image-dispatcher", daemon=True)
            state["api_thread"].start()
        state["api_queue"].put((ident,kind,payload))
    else:
        if state["thread"] is None or not state["thread"].is_alive():
            state["thread"] = threading.Thread(target=_work, args=(svc,state["queue"]),
                name="mikuchin-image-worker", daemon=True)
            state["thread"].start()
        state["queue"].put((ident,kind,payload))


def _insert_studio(db, request, state="draft"):
    job_id = "img-" + secrets.token_hex(12)
    now = time.time()
    db.execute("INSERT INTO jobs(id,kind,source_id,state,phase,created,updated,"
               "profile_id,prompt_summary,requested_size,request_json,started_at) "
               "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (
               job_id, "generate", "", state,
               "草稿已保存" if state == "draft" else "排队等待执行", now, now,
               request.get("strata_image_profile", "default"),
               " ".join((request.get("prompt") or request.get("natural_prompt") or "").split())[:180],
               str(request.get("size") or "")[:40], json.dumps(request,ensure_ascii=False),
               None))
    return job_id


def _original_request(row):
    original = json.loads(row["request_json"] or "{}")
    if original:
        return original
    # Older tasks only had a short summary. These can be copied into a draft
    # with a clear warning, but NOT retried as if the original request existed.
    return {"prompt":row["prompt_summary"],
            "strata_image_profile":row["profile_id"] or "default",
            "size":row["requested_size"] or "768x768", "legacy_incomplete":True}


def submit(svc, req):
    if not isinstance(req, dict):
        raise ValueError("expected JSON object")
    action = req.get("action")
    kind = req.get("kind", "generate")
    if action not in (None, "draft", "save_draft", "activate", "retry"):
        raise ValueError("unknown image task action")
    if action is None and kind not in ("generate", "upscale"):
        raise ValueError("unsupported image job kind")
    _initialize(svc)
    with _LOCK:
        if action == "save_draft":
            ident = req.get("id")
            if not image_task_status.valid(ident):
                raise ValueError("invalid draft ID")
            with _db(svc) as db:
                row = db.execute("SELECT * FROM jobs WHERE id=? AND kind='generate' AND state='draft'",(ident,)).fetchone()
                if row is None:
                    raise ValueError("draft no longer exists or has already been submitted")
            request = _prepare_request(svc, req.get("request"))
            with _db(svc) as db:
                cursor = db.execute("UPDATE jobs SET updated=?,request_json=?,prompt_summary=?,"
                    "profile_id=?,requested_size=?,phase='草稿已保存' WHERE id=? AND kind='generate' AND state='draft'",
                    (time.time(), json.dumps(request,ensure_ascii=False),
                     " ".join((request.get("prompt") or request.get("natural_prompt") or "").split())[:180],
                     request.get("strata_image_profile", "default"), str(request.get("size") or "")[:40], ident))
                if cursor.rowcount != 1:
                    raise ValueError("draft was submitted while editing")
                response = _public(db.execute("SELECT * FROM jobs WHERE id=?",(ident,)).fetchone())
            _gc_references(svc)
            return response

        if action == "draft":
            touch_id = req.get("id")
            copy_id = req.get("copy_id")
            if touch_id is not None:
                if not image_task_status.valid(touch_id):
                    raise ValueError("invalid draft ID")
                with _db(svc) as db:
                    cursor = db.execute("UPDATE jobs SET updated=? WHERE id=? AND kind='generate' AND state='draft'",
                                        (time.time(), touch_id))
                    if cursor.rowcount != 1:
                        raise ValueError("draft not found; do not overwrite a completed task")
                    return _public(db.execute("SELECT * FROM jobs WHERE id=?", (touch_id,)).fetchone())
            if copy_id is not None:
                if not image_task_status.valid(copy_id):
                    raise ValueError("invalid source task ID")
                with _db(svc) as db:
                    row = db.execute("SELECT * FROM jobs WHERE id=? AND kind='generate'", (copy_id,)).fetchone()
                    if not row:
                        raise ValueError("source task not found")
                    original = _original_request(row)
                legacy = original.pop("legacy_incomplete", False)
                request = _prepare_request(svc, original)
            else:
                legacy = False
                request = _prepare_request(svc, req.get("request"))
            with _db(svc) as db:
                _trim_studio(svc,db,protected_ids=(copy_id,) if copy_id else ())
                ident = _insert_studio(db,request)
                response = _public(db.execute("SELECT * FROM jobs WHERE id=?",(ident,)).fetchone())
            response["legacy_incomplete"] = legacy
            _gc_references(svc)
            return response

        if action == "activate":
            ident = req.get("id")
            if not image_task_status.valid(ident):
                raise ValueError("invalid draft ID")
            with _db(svc) as db:
                if _pending_count(db) >= _MAX_PENDING:
                    raise ValueError("图像任务队列已满")
                row = db.execute("SELECT * FROM jobs WHERE id=? AND kind='generate' AND state='draft'",(ident,)).fetchone()
                if row is None:
                    raise ValueError("draft already submitted or does not exist")
                payload = json.loads(row["request_json"] or "{}")
                if not (payload.get("prompt") or "").strip():
                    raise ValueError("image prompt is required")
                db.execute("UPDATE jobs SET state='running',phase='排队等待执行',updated=?,"
                           "started_at=NULL,finished_at=NULL WHERE id=?",
                           (time.time(), ident))
                response = _public(db.execute("SELECT * FROM jobs WHERE id=?",(ident,)).fetchone())
            _enqueue(svc,ident,"generate",payload)
            return response

        if action == "retry":
            original_id = req.get("id")
            if not image_task_status.valid(original_id):
                raise ValueError("invalid task ID")
            with _db(svc) as db:
                row = db.execute("SELECT * FROM jobs WHERE id=? AND kind='generate'",(original_id,)).fetchone()
                if not row or row["state"] not in ("success","failed"):
                    raise ValueError("only successful or failed image tasks can be retried")
                original = json.loads(row["request_json"] or "{}")
                if not original:
                    raise ValueError("该历史任务没有保存完整参数和参考图，无法原样重试；可点击编辑新建草稿")
                if _pending_count(db) >= _MAX_PENDING:
                    raise ValueError("图像任务队列已满")
            request = _prepare_request(svc, original)
            if not (request.get("prompt") or "").strip():
                raise ValueError("image prompt is required")
            with _db(svc) as db:
                # Replace failed tasks in one database transaction. Never erase
                # the failed request before validating and creating the retry;
                # success records still remain as independent history entries.
                source = db.execute("SELECT state FROM jobs WHERE id=? AND kind='generate'",
                                    (original_id,)).fetchone()
                if not source or source["state"] not in ("success", "failed"):
                    raise ValueError("source task is no longer retryable")
                failed_source = source["state"] == "failed"
                if not failed_source:
                    _trim_studio(svc,db,protected_ids=(original_id,))
                ident = _insert_studio(db, request, "running")
                if failed_source:
                    db.execute("DELETE FROM jobs WHERE id=? AND kind='generate' AND state='failed'",
                               (original_id,))
                response = _public(db.execute("SELECT * FROM jobs WHERE id=?",(ident,)).fetchone())
                if failed_source:
                    response["deleted_original_id"] = original_id
            _enqueue(svc,ident,"generate",request)
            _gc_references(svc)
            return response

        if kind == "generate":
            request = _prepare_request(svc, req.get("request"))
            if not (request.get("prompt") or "").strip():
                raise ValueError("image prompt is required")
            with _db(svc) as db:
                if _pending_count(db) >= _MAX_PENDING:
                    raise ValueError("图像任务队列已满")
                _trim_studio(svc,db)
                ident = _insert_studio(db, request, "running")
                response = _public(db.execute("SELECT * FROM jobs WHERE id=?",(ident,)).fetchone())
            _enqueue(svc,ident,"generate",request)
            _gc_references(svc)
            return response

        source_id = req.get("image_id")
        gallery_api.upscale_source(svc,source_id)
        with _db(svc) as db:
            if _pending_count(db) >= _MAX_PENDING:
                raise ValueError("图像任务队列已满")
            row = db.execute("SELECT * FROM jobs WHERE kind='upscale' AND source_id=? "
                "AND state IN ('queued','working') ORDER BY created DESC LIMIT 1",(source_id,)).fetchone()
            if row:
                return _public(row)
            ident = "img-" + secrets.token_hex(12)
            now = time.time()
            db.execute("INSERT INTO jobs(id,kind,source_id,state,phase,created,updated) VALUES(?,?,?,?,?,?,?)",
                (ident,"upscale",source_id,"queued","等待桌面端处理",now,now))
            response = _public(db.execute("SELECT * FROM jobs WHERE id=?",(ident,)).fetchone())
        _enqueue(svc,ident,"upscale",source_id)
        return response


def submit_chat(svc, hub, arguments, tool_call_id):
    """Enqueue a chat image with its server-owned reference context.

    Only the opaque job ID and session/tool binding are persisted; prompts,
    reference images, and credentials stay in service memory, not the task DB.
    """
    if not isinstance(arguments, dict) or not isinstance(arguments.get("prompt"), str) \
            or not arguments["prompt"].strip() or len(arguments["prompt"]) > 16000:
        raise ValueError("invalid chat image prompt")
    if not isinstance(tool_call_id, str) or not 1 <= len(tool_call_id) <= 128:
        raise ValueError("invalid tool call ID")
    from serve.session_v1 import valid_id
    session_id = valid_id(hub.delivery_session_id)
    _initialize(svc)
    key = str(_db_path(svc))
    with _LOCK, _db(svc) as db:
        existing = db.execute(
            "SELECT * FROM jobs WHERE kind='chat' AND source_id=? AND tool_call_id=? "
            "ORDER BY created DESC LIMIT 1", (session_id, tool_call_id)).fetchone()
        if existing:
            return _public(existing)
        pending = db.execute(
            "SELECT COUNT(*) FROM jobs WHERE state IN ('queued','working')").fetchone()[0]
        if pending >= _MAX_PENDING:
            raise ValueError("image job queue is full")
        job_id = "img-" + secrets.token_hex(12)
        now = time.time()
        db.execute("INSERT INTO jobs(id,kind,source_id,state,phase,created,updated,tool_call_id) "
                   "VALUES(?,?,?,?,?,?,?,?)",
                   (job_id, "chat", session_id, "queued", "等待桌面端生成", now, now, tool_call_id))
        state = _WORKERS[key]
        if state["thread"] is None or not state["thread"].is_alive():
            state["thread"] = threading.Thread(target=_work, args=(svc, state["queue"]),
                name="mikuchin-image-worker", daemon=True)
            state["thread"].start()
        state["queue"].put((job_id, "chat", (hub, dict(arguments), tool_call_id)))
        accepted = _public(db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())
    # Commit the task before updating chat history, so closed tabs can recover
    # even if they never received the tool-result SSE event.
    try:
        svc.session_v1.complete_image_tool_job(session_id, job_id, tool_call_id, {})
    except Exception as exc:
        print(f"[mikuchin] chat image queued-state persistence: {exc}", flush=True)
    return accepted
