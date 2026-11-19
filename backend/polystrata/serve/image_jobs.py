"""Desktop-owned image jobs: browser clients submit and then disconnect freely.

A single daemon worker per session store executes jobs without using the request
handler, its socket, or its client-disconnect cancellation event. Durable task
metadata may include completed chat-image prompts; credentials and image bytes
remain outside the task database.
"""
from __future__ import annotations

import json
import queue
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager

from serve import gallery as gallery_api
from serve import image_api_services as api_images
from serve import image_task_status
from serve import images as images_api

_LOCK = threading.RLock()
_WORKERS = {}
_MAX_PENDING = 12


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
            tool_call_id TEXT NOT NULL DEFAULT ''
        )""")
        columns = {row[1] for row in conn.execute("PRAGMA table_info(jobs)")}
        if "tool_call_id" not in columns:
            conn.execute("ALTER TABLE jobs ADD COLUMN tool_call_id TEXT NOT NULL DEFAULT ''")
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
            db.execute("UPDATE jobs SET state='interrupted', phase='服务已重启，任务未完成', "
                       "error='桌面服务已重启；请重新提交任务' "
                       "WHERE state IN ('queued', 'working')")
            _WORKERS[key] = {"queue": queue.Queue(), "thread": None, "service": svc}


def _public(row):
    result = dict(row)
    result["result"] = json.loads(result.get("result") or "{}")
    result["elapsed_s"] = round(max(0.0, result["updated"] - result["created"]), 1)
    return result


def snapshot(svc, job_id=None, limit=40, session_id=None):
    _initialize(svc)
    with _LOCK, _db(svc) as db:
        if job_id:
            if not image_task_status.valid(job_id):
                raise ValueError("invalid image job ID")
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                return {"state": "unknown", "id": job_id}
            obj = _public(row)
            if obj["state"] == "working":
                extra = image_task_status.snapshot(job_id, gen=svc.images, profiles=svc.image_profiles)
                for key in ("step", "steps"):
                    if key in extra:
                        obj[key] = extra[key]
            return obj
        if not isinstance(limit, int) or not 1 <= limit <= 40:
            raise ValueError("invalid job list limit")
        if session_id is not None:
            from serve.session_v1 import valid_id
            valid_id(session_id)
            rows = db.execute("SELECT * FROM jobs WHERE kind='chat' AND source_id=? "
                              "ORDER BY created DESC LIMIT ?", (session_id, limit)).fetchall()
        else:
            rows = db.execute("SELECT * FROM jobs ORDER BY created DESC LIMIT ?", (limit,)).fetchall()
    return {"jobs": [_public(row) for row in rows]}


def _mark(svc, job_id, phase, state="working", result=None, error=None, provider="local"):
    now = time.time()
    with _LOCK, _db(svc) as db:
        db.execute("UPDATE jobs SET phase=?, state=?, result=COALESCE(?,result), "
                   "error=COALESCE(?,error), updated=? WHERE id=?",
                   (str(phase)[:100], state,
                    json.dumps(result, ensure_ascii=False) if result is not None else None,
                    str(error)[:500] if error else None, now, job_id))
    image_task_status.mark(job_id, phase, state=state, error=error, provider=provider)


def _generate(svc, req, job_id):
    profile_id = req.get("strata_image_profile", "default")
    if isinstance(profile_id, str) and profile_id.startswith("api-"):
        _mark(svc, job_id, "正在请求 API", provider="api")
        out = api_images.generate(svc, req, ident=profile_id,
            on_status=lambda phase: _mark(svc, job_id, phase, provider="api"))
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
        _mark(svc, job_id, "本地模型生成中")
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
        _mark(svc, job_id, "正在执行 4x 超分")
        png, secs = _upscale_one(original, cfg)
    _mark(svc, job_id, "正在保存 4x 图片")
    cover = gallery_api.attach_upscaled(svc, source_id, png)
    return {"image_ids": [cover], "original_id": source_id,
            "upscaled_id": cover, "seconds": secs}


def _work(svc, jobs):
    while True:
        job_id, kind, payload = jobs.get()
        try:
            if kind == "chat":
                hub, arguments, call_id = payload
                _mark(svc, job_id, "正在执行聊天生图")
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
        finally:
            jobs.task_done()


def submit(svc, req):
    if not isinstance(req, dict):
        raise ValueError("expected JSON object")
    kind = req.get("kind")
    if kind == "generate":
        payload = req.get("request")
        if not isinstance(payload, dict) or not isinstance(payload.get("prompt"), str) or not payload["prompt"].strip():
            raise ValueError("image prompt is required")
        if len(payload["prompt"]) > 16000:
            raise ValueError("image prompt too long")
        profile = payload.get("strata_image_profile", "default")
        if not isinstance(profile, str) or len(profile) > 64:
            raise ValueError("invalid image profile")
        # Protect background workers from oversized arbitrary responses.
        payload = dict(payload)
        payload["response_format"] = "url"
        source_id = ""
    elif kind == "upscale":
        source_id = req.get("image_id")
        gallery_api.upscale_source(svc, source_id)
        payload = source_id
    else:
        raise ValueError("unsupported image job kind")
    _initialize(svc)
    key = str(_db_path(svc))
    with _LOCK, _db(svc) as db:
        pending = db.execute("SELECT COUNT(*) FROM jobs WHERE state IN ('queued', 'working')").fetchone()[0]
        if pending >= _MAX_PENDING:
            raise ValueError("图像任务队列已满，请稍后再试")
        if kind == "upscale":
            row = db.execute("SELECT * FROM jobs WHERE kind='upscale' AND source_id=? "
                             "AND state IN ('queued','working') ORDER BY created DESC LIMIT 1",
                             (source_id,)).fetchone()
            if row:
                return _public(row)
        job_id = "img-" + secrets.token_hex(12)
        now = time.time()
        db.execute("INSERT INTO jobs(id,kind,source_id,state,phase,created,updated) "
                   "VALUES(?,?,?,?,?,?,?)",
                   (job_id, kind, source_id, "queued", "等待桌面端处理", now, now))
        state = _WORKERS[key]
        if state["thread"] is None or not state["thread"].is_alive():
            state["thread"] = threading.Thread(target=_work, args=(svc, state["queue"]),
                name="mikuchin-image-worker", daemon=True)
            state["thread"].start()
        state["queue"].put((job_id, kind, payload))
        row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return _public(row)


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
