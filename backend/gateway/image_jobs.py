"""Mikuchin Native's persistent *online* image task queue.

Offline drafts never call providers. Only an explicit activate/retry submits a
chargeable request. Worker execution is independent of browser connections.
The Gateway never runs provider jobs. Only the separate supervised Image
Worker claims and executes jobs; uncertain jobs are never replayed on reboot.
Local GPU/4x and gallery mutation are deliberately separate future adapters.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import secrets
import sqlite3
import threading
import time
from pathlib import Path

from PIL import Image

try:
    from . import image_providers as providers
    from . import gallery
    from . import local_images
except ImportError:  # standalone python -m unittest discover -s backend/gateway
    import image_providers as providers
    import gallery
    import local_images

JOB_ID = re.compile(r"img-[a-f0-9]{24}\Z")
CHAT_ID = re.compile(r"[a-f0-9]{32}\Z")
REF_ID = re.compile(r"[a-f0-9]{64}\Z")
SIZE = re.compile(r"\d{3,4}x\d{3,4}\Z")
MAX_PENDING = 80
FIELDS = frozenset(("prompt", "positive_prompt", "natural_prompt", "negative_prompt",
                   "size", "steps", "seed", "strata_upscale", "strata_image_profile",
                   "strata_reference_mode", "strata_reference_assets", "response_format",
                   "strata_lora_id", "strata_denoise_strength"))


class ImageJobStore:
    def __init__(self, root, *, embedded_worker=False):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "native-image-jobs.sqlite3"
        self.lock = threading.RLock()
        self.embedded_worker = embedded_worker  # unit-test-only adapter
        self.queue = None
        self.thread = None
        if embedded_worker:
            from queue import Queue
            self.queue = Queue()
        self._provider = providers.generate
        with self._db() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS jobs(
                id TEXT PRIMARY KEY,kind TEXT NOT NULL DEFAULT 'generate',
                state TEXT NOT NULL,phase TEXT NOT NULL,request_json TEXT NOT NULL,
                result_json TEXT NOT NULL DEFAULT '{}',error TEXT NOT NULL DEFAULT '',
                profile_id TEXT NOT NULL, prompt_summary TEXT NOT NULL,
                requested_size TEXT NOT NULL,created REAL NOT NULL,updated REAL NOT NULL,
                started_at REAL,finished_at REAL,source_id TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS jobs_created ON jobs(created DESC);
            -- Stable idempotency keys for explicit user-initiated chat images.
            -- A browser refresh/timeout must never trigger a second paid job.
            CREATE TABLE IF NOT EXISTS chat_image_requests(
                session_id TEXT NOT NULL, request_id TEXT NOT NULL,
                job_id TEXT NOT NULL UNIQUE, created REAL NOT NULL,
                PRIMARY KEY(session_id, request_id)
            );
            CREATE INDEX IF NOT EXISTS chat_image_session
              ON chat_image_requests(session_id, created);
            CREATE TABLE IF NOT EXISTS worker_status(
                singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                pid INTEGER NOT NULL, updated REAL NOT NULL
            );
            """)
            db.execute("PRAGMA journal_mode=WAL")

    def worker_healthy(self):
        with self._db() as db:
            row = db.execute("SELECT updated FROM worker_status WHERE singleton=1").fetchone()
        return bool(row and time.time() - row["updated"] < 4)

    def worker_pid(self):
        with self._db() as db:
            row = db.execute("SELECT pid FROM worker_status WHERE singleton=1").fetchone()
        return row["pid"] if row else None

    def worker_last_heartbeat(self):
        with self._db() as db:
            row = db.execute("SELECT updated FROM worker_status WHERE singleton=1").fetchone()
        return row["updated"] if row else 0.0

    def activity(self):
        """Cheap, privacy-safe snapshot for the Tauri/Gateway monitor."""
        with self._db() as db:
            counts = dict(db.execute(
                "SELECT state, COUNT(*) FROM jobs WHERE state IN ('running', 'draft') GROUP BY state"
            ).fetchall())
            first = db.execute(
                "SELECT phase FROM jobs WHERE state='running' ORDER BY created ASC LIMIT 1"
            ).fetchone()
        return {"running": counts.get("running", 0),
                "drafts": counts.get("draft", 0),
                "phase": first["phase"][:120] if first else ""}

    def heartbeat(self):
        import os
        with self._db() as db:
            db.execute("""INSERT INTO worker_status(singleton,pid,updated)
                VALUES(1,?,?) ON CONFLICT(singleton) DO UPDATE SET
                pid=excluded.pid,updated=excluded.updated""",(os.getpid(),time.time()))

    def worker_offline(self):
        with self._db() as db:
            db.execute("DELETE FROM worker_status WHERE singleton=1")

    def fail_uncertain_on_worker_restart(self):
        """Never auto-reissue possibly billed provider requests after a crash."""
        with self._db() as db:
            db.execute("""UPDATE jobs SET state='failed',phase='独立 Worker 已重启，未自动重试',
                          error='上次 Worker 退出时任务未完成；提供商可能已经计费，请核对后手动重试',
                          finished_at=?,updated=? WHERE state IN ('running','queued','working')""",
                       (time.time(),time.time()))

    def take_pending(self):
        """Transactional single-consumer claim, safe even if a second worker starts."""
        with self._db() as db:
            row = db.execute("""SELECT id,request_json FROM jobs WHERE state='running'
                    AND phase='排队等待执行' ORDER BY created ASC LIMIT 1""").fetchone()
            if row is None:
                return None
            cursor = db.execute("""UPDATE jobs SET phase='准备请求提供商',updated=?
                WHERE id=? AND state='running' AND phase='排队等待执行'""",
                                (time.time(),row["id"]))
            if cursor.rowcount != 1:
                return None
            return row["id"], json.loads(row["request_json"])

    def _db(self):
        class Context:
            def __init__(self, db_path):
                self.conn = sqlite3.connect(db_path, timeout=15)
                self.conn.row_factory = sqlite3.Row
                self.conn.execute("PRAGMA busy_timeout=15000")
            def __enter__(self): return self.conn
            def __exit__(self, kind, exc, tb):
                try:
                    if kind: self.conn.rollback()
                    else: self.conn.commit()
                finally: self.conn.close()
        return Context(self.path)

    @staticmethod
    def _public(row):
        result = dict(row)
        result["result"] = json.loads(result.pop("result_json"))
        result["request"] = json.loads(result.pop("request_json"))
        start, finish = result.get("started_at"),result.get("finished_at")
        result["elapsed_s"] = round(max(0,(finish or time.time()) - start),1) if start else None
        result["legacy_timer_unknown"] = start is None and result["state"] != "draft"
        return result

    @staticmethod
    def _check_id(ident):
        if not isinstance(ident,str) or not JOB_ID.fullmatch(ident):
            raise ValueError("invalid image task ID")
        return ident

    def _reference_path(self, ident):
        if not isinstance(ident,str) or not REF_ID.fullmatch(ident):
            raise ValueError("invalid image reference ID")
        file = self.root / "image-job-references" / (ident + ".bin")
        if file.is_symlink(): raise ValueError("reference symlink is not allowed")
        return file

    def reference_bytes(self, ident):
        file = self._reference_path(ident)
        if not file.is_file() or not 0 < file.stat().st_size <= 5 * 1024 * 1024:
            raise ValueError("reference image not found")
        data = file.read_bytes()
        if hashlib.sha256(data).hexdigest() != ident:
            raise ValueError("reference checksum mismatch")
        with Image.open(io.BytesIO(data)) as image:
            mime = {"PNG":"image/png","JPEG":"image/jpeg","WEBP":"image/webp"}.get(image.format)
            if mime is None: raise ValueError("invalid reference image")
        return data,mime

    def _store_ref(self, data_url):
        if not isinstance(data_url,str) or len(data_url) > 7_200_000:
            raise ValueError("reference image is too large")
        match = re.fullmatch(r"data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/=]+)",data_url)
        if not match: raise ValueError("expected base64 PNG/JPEG/WebP data URL")
        try:
            raw = base64.b64decode(match.group(2),validate=True)
            if not 0 < len(raw) <= 5 * 1024 * 1024:
                raise ValueError("reference exceeds 5 MB")
            with Image.open(io.BytesIO(raw)) as image:
                if image.format != {"jpeg":"JPEG","png":"PNG","webp":"WEBP"}[match.group(1)] \
                        or image.width * image.height > 16_000_000:
                    raise ValueError("invalid image format or dimensions")
                image.verify()
        except (ValueError,OSError,base64.binascii.Error,Image.DecompressionBombError) as exc:
            raise ValueError("invalid reference image") from exc
        ident = hashlib.sha256(raw).hexdigest()
        file = self._reference_path(ident)
        file.parent.mkdir(exist_ok=True)
        if not file.exists():
            temp = file.with_suffix("." + secrets.token_hex(6) + ".tmp")
            try:
                temp.write_bytes(raw)
                temp.replace(file)
            finally: temp.unlink(missing_ok=True)
        return ident

    def _prepare(self, request):
        if not isinstance(request,dict) or set(request) - FIELDS:
            raise ValueError("invalid image request fields")
        result = {key:val for key,val in request.items() if key in FIELDS and key != "strata_reference_assets"}
        for field,limit in (("prompt",16000),("positive_prompt",12000),
                            ("natural_prompt",6000),("negative_prompt",3000)):
            if not isinstance(result.get(field,""),str) or len(result.get(field,"")) > limit:
                raise ValueError(field + " must be short text")
        profile = result.get("strata_image_profile","default")
        if not isinstance(profile,str) or len(profile) > 64:
            raise ValueError("invalid image profile")
        result["strata_image_profile"] = profile
        mode = result.get("strata_upscale","auto")
        if mode not in ("off","auto","4x",None):
            raise ValueError("invalid native upscale mode")
        if mode == "4x" and not local_images.upscaler_ready(self):
            raise ValueError("native 4x upscaler is not configured")
        if result.get("strata_lora_id") not in (None,"","none"):
            ident = result["strata_lora_id"]
            if not isinstance(ident,str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}",ident):
                raise ValueError("invalid image LoRA id")
        if result.get("strata_denoise_strength") is not None:
            strength = result["strata_denoise_strength"]
            if type(strength) not in (int,float) or not 0.05 <= strength <= 1:
                raise ValueError("invalid image denoise strength")
        if result.get("strata_reference_mode", "none") not in ("none","single","multi"):
            raise ValueError("invalid image reference mode")
        if result.get("response_format", "url") not in ("url",):
            raise ValueError("only URL image results are supported")
        size = result.get("size","1024x1024")
        if not isinstance(size,str) or not SIZE.fullmatch(size):
            raise ValueError("invalid image size")
        if result.get("seed") is not None and (type(result["seed"]) is not int or not 0 <= result["seed"] <= 2**31-1):
            raise ValueError("invalid seed")
        if result.get("steps") is not None and (type(result["steps"]) is not int or not 1 <= result["steps"] <= 100):
            raise ValueError("invalid steps")
        refs = request.get("strata_reference_assets",[])
        if not isinstance(refs,list) or len(refs) > 8:
            raise ValueError("too many reference images")
        saved=[]
        for index,item in enumerate(refs):
            if not isinstance(item,dict): raise ValueError("invalid reference description")
            name=item.get("name",f"参考图 {index+1}")
            if not isinstance(name,str): raise ValueError("invalid reference name")
            ident = item.get("id")
            if ident is not None: self.reference_bytes(ident)
            else: ident=self._store_ref(item.get("data_url"))
            saved.append({"id":ident,"name":name[:120]})
        result["strata_reference_assets"]=saved
        if len(json.dumps(result,ensure_ascii=False)) > 44_000:
            raise ValueError("image request too large")
        return result

    def _require_provider(self, request):
        profile=request["strata_image_profile"]
        if profile.startswith("local-"):
            return local_images.validate(self, request)
        service=providers.get(self,profile)
        if not service:
            raise ValueError("native version currently supports configured online API models only")
        if not service.get("api_key"):
            raise ValueError("image provider API key not configured")
        w,h=map(int,request["size"].split("x"))
        if not providers.allowed_image_size(service["sizes"],w,h):
            raise ValueError("resolution is unavailable for the selected API model")
        if request["strata_reference_assets"] and service["reference_mode"] == "none":
            raise ValueError("this image API does not accept reference images")
        if request.get("strata_lora_id") not in (None,"","none"):
            raise ValueError("LoRA requires a local Qwen-Image model")
        if request.get("strata_upscale") == "4x":
            max_side = int(local_images._settings(self)["upscaler"].get("max_output_side",3072))
            if max(w,h)*4 > max_side:
                raise ValueError("4x output exceeds configured size limit")
        return service

    def _insert(self,db,request,state,source_id=""):
        ident="img-"+secrets.token_hex(12)
        now=time.time()
        db.execute("""INSERT INTO jobs(id,state,phase,request_json,profile_id,prompt_summary,
                    requested_size,created,updated,started_at,source_id)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                   (ident,state,"草稿已保存" if state == "draft" else "排队等待执行",
                    json.dumps(request,ensure_ascii=False),request["strata_image_profile"],
                    " ".join((request.get("prompt") or request.get("natural_prompt") or "").split())[:180],
                    request.get("size",""),now,now,None,source_id))
        return self._public(db.execute("SELECT * FROM jobs WHERE id=?",(ident,)).fetchone())

    def listing(self,ident=None,kind=None,limit=100,session_id=None):
        if kind not in (None,"generate","upscale"):
            raise ValueError("unknown image task kind")
        if session_id is not None and (not isinstance(session_id,str) or not CHAT_ID.fullmatch(session_id)):
            raise ValueError("invalid chat session ID")
        with self.lock,self._db() as db:
            if ident:
                self._check_id(ident)
                if session_id:
                    row=db.execute("""SELECT jobs.* FROM jobs JOIN chat_image_requests c
                        ON c.job_id=jobs.id WHERE jobs.id=? AND c.session_id=?""",
                        (ident,session_id)).fetchone()
                else:
                    row=db.execute("SELECT * FROM jobs WHERE id=?",(ident,)).fetchone()
                if row is not None and kind is not None and row["kind"] != kind:
                    row = None
                return self._public(row) if row else {"id":ident,"state":"unknown"}
            if session_id:
                rows=db.execute("""SELECT jobs.*, c.request_id FROM chat_image_requests c
                    JOIN jobs ON jobs.id=c.job_id WHERE c.session_id=?
                    ORDER BY c.created DESC LIMIT ?""",(session_id,min(max(limit,1),100))).fetchall()
            elif kind:
                rows=db.execute("SELECT * FROM jobs WHERE kind=? ORDER BY created DESC LIMIT ?",
                                (kind,min(max(limit,1),100))).fetchall()
            else:
                rows=db.execute("SELECT * FROM jobs ORDER BY created DESC LIMIT ?",
                                (min(max(limit,1),100),)).fetchall()
            return {"jobs":[self._public(row) for row in rows]}

    def submit_upscale(self, image_id):
        """User-triggered offline-only 4x; never invokes an image provider."""
        with self.lock,self._db() as db:
            existing=db.execute("""SELECT * FROM jobs WHERE kind='upscale' AND source_id=?
                AND state IN ('running','success') ORDER BY created DESC LIMIT 1""",
                (image_id,)).fetchone()
            if existing is not None:
                return {**self._public(existing),"already_submitted":True}
            if not self.embedded_worker and not self.worker_healthy():
                raise ValueError("独立 Image Worker 尚未就绪")
            if not local_images.upscaler_ready(self):
                raise ValueError("本地 4× 超分引擎尚未配置")
            original=gallery.upscale_source(self,image_id)
            max_side=int(local_images._settings(self)["upscaler"].get("max_output_side",3072))
            if max(original["width"],original["height"])*4 > max_side:
                raise ValueError("4× 输出尺寸超出已配置的限制")
            if db.execute("SELECT COUNT(*) FROM jobs WHERE state='running'").fetchone()[0] >= MAX_PENDING:
                raise ValueError("图像任务队列已满")
            now=time.time()
            ident="img-"+secrets.token_hex(12)
            payload={"kind":"upscale","image_id":image_id}
            db.execute("""INSERT INTO jobs(id,kind,state,phase,request_json,profile_id,
                prompt_summary,requested_size,created,updated,started_at,source_id)
                VALUES(?,'upscale','running','排队等待执行',?,?,?,?,?,?,?,?)""",
                (ident,json.dumps(payload),"native-4x","仅超分",f"{original['width']}x{original['height']}",
                 now,now,now,image_id))
            created=self._public(db.execute("SELECT * FROM jobs WHERE id=?",(ident,)).fetchone())
        if self.embedded_worker:
            self.queue.put((ident,payload))
            self._start_worker()
        return {**created,"already_submitted":False}

    def chat_submit(self, session_id, request_id, request, *, edit_previous=False):
        """One explicit button press => one paid job at most, including retries.

        The UNIQUE ledger and job record commit in one SQLite transaction. A
        crash before HTTP reply does not create an orphaned second billable job.
        Never submits automatically when reopening a conversation.
        """
        if not isinstance(session_id,str) or not CHAT_ID.fullmatch(session_id):
            raise ValueError("invalid chat session ID")
        if not isinstance(request_id,str) or not CHAT_ID.fullmatch(request_id):
            raise ValueError("invalid chat request ID")
        if type(edit_previous) is not bool:
            raise ValueError("edit_previous must be a boolean")
        with self.lock,self._db() as db:
            existing=db.execute("""SELECT job_id FROM chat_image_requests
                WHERE session_id=? AND request_id=?""",(session_id,request_id)).fetchone()
            if existing:
                row=db.execute("SELECT * FROM jobs WHERE id=?",(existing["job_id"],)).fetchone()
                if row is None:
                    return {"id":existing["job_id"],"state":"unknown","request_id":request_id,
                            "already_submitted":True}
                return {**self._public(row),"request_id":request_id,"already_submitted":True}
            if not self.embedded_worker and not self.worker_healthy():
                raise ValueError("独立 Image Worker 尚未就绪，无法提交图像任务")
            if db.execute("SELECT COUNT(*) FROM jobs WHERE state='running'").fetchone()[0] >= MAX_PENDING:
                raise ValueError("image request queue is full")
            source_id=""
            if edit_previous:
                if not isinstance(request,dict) or request.get("strata_reference_assets"):
                    raise ValueError("edit previous must use only the server-side chat image")
                candidates=db.execute("""SELECT jobs.id,jobs.result_json FROM jobs
                    JOIN chat_image_requests c ON c.job_id=jobs.id
                    WHERE c.session_id=? AND jobs.state='success'
                    ORDER BY jobs.created DESC LIMIT 30""",(session_id,)).fetchall()
                image_file=None
                for previous in candidates:
                    output=json.loads(previous["result_json"])
                    image_file=(output.get("upscale_original_id") or "")
                    if image_file:
                        image_file += ".png"
                    else:
                        image_file=output.get("image_file")
                    if isinstance(image_file,str) and re.fullmatch(r"[a-f0-9]{32}\.png",image_file):
                        source_id=previous["id"]
                        break
                if not source_id:
                    raise ValueError("本会话尚无可编辑的已生成图片")
                try:
                    raw=gallery._file(self,image_file.removesuffix(".png")).read_bytes()
                except (OSError, gallery.GalleryError) as exc:
                    raise ValueError("上张生成图已删除或不可读取，无法作为参考") from exc
                if not 0 < len(raw) <= 5*1024*1024:
                    raise ValueError("上张图片过大，不能用作图生图参考")
                reference="data:image/png;base64,"+base64.b64encode(raw).decode("ascii")
                request={**request,"strata_reference_assets":[{
                    "name":"previous-chat-image.png","data_url":reference}]}
            prepared=self._prepare(request)
            if not (prepared.get("prompt") or "").strip():
                raise ValueError("image prompt is required")
            self._require_provider(prepared)
            created=self._insert(db,prepared,"running",source_id=source_id)
            db.execute("""INSERT INTO chat_image_requests(session_id,request_id,job_id,created)
                VALUES(?,?,?,?)""",(session_id,request_id,created["id"],time.time()))
        if self.embedded_worker:
            self.queue.put((created["id"],prepared))
            self._start_worker()
        return {**created,"request_id":request_id,"already_submitted":False}

    def chat_cancel(self, session_id, request_id):
        if not isinstance(session_id,str) or not CHAT_ID.fullmatch(session_id):
            raise ValueError("invalid chat session ID")
        if not isinstance(request_id,str) or not CHAT_ID.fullmatch(request_id):
            raise ValueError("invalid chat request ID")
        with self.lock,self._db() as db:
            row=db.execute("""SELECT jobs.* FROM jobs JOIN chat_image_requests c
                ON c.job_id=jobs.id WHERE c.session_id=? AND c.request_id=?""",
                (session_id,request_id)).fetchone()
            if not row: raise ValueError("chat image request not found")
            # Never cancel in-flight provider work: it may have been billed.
            updated=db.execute("""UPDATE jobs SET state='failed',phase='用户取消排队任务',
                error='仅取消尚未执行的生图任务',updated=?,finished_at=?
                WHERE id=? AND state='running' AND phase='排队等待执行'""",
                (time.time(),time.time(),row["id"]))
            if updated.rowcount != 1:
                raise ValueError("任务已执行或结束，无法撤回本次可能收费的请求")
            return {**self._public(db.execute("SELECT * FROM jobs WHERE id=?",
                        (row["id"],)).fetchone()),"request_id":request_id}

    def submit(self,req):
        if not isinstance(req,dict): raise ValueError("expected image task object")
        action=req.get("action")
        with self.lock:
            if action in ("draft","save_draft"):
                if action == "draft" and req.get("id"):
                    ident=self._check_id(req["id"])
                    with self._db() as db:
                        row=db.execute("SELECT * FROM jobs WHERE id=? AND state='draft'",(ident,)).fetchone()
                        if not row: raise ValueError("draft not found")
                        db.execute("UPDATE jobs SET updated=? WHERE id=?",(time.time(),ident))
                        return self._public(db.execute("SELECT * FROM jobs WHERE id=?",(ident,)).fetchone())
                if action == "draft" and req.get("copy_id"):
                    source=self.listing(self._check_id(req["copy_id"]))
                    if source["state"] == "unknown": raise ValueError("source task not found")
                    original=source["request"]
                else:
                    original=req.get("request")
                prepared=self._prepare(original)
                with self._db() as db:
                    if action == "save_draft":
                        ident=self._check_id(req.get("id"))
                        update=db.execute("""UPDATE jobs SET request_json=?,profile_id=?,requested_size=?,
                             prompt_summary=?,updated=? WHERE id=? AND state='draft'""",
                             (json.dumps(prepared,ensure_ascii=False),prepared["strata_image_profile"],
                              prepared.get("size",""),prepared.get("prompt","")[:180],time.time(),ident))
                        if update.rowcount != 1: raise ValueError("draft was already submitted")
                        return self._public(db.execute("SELECT * FROM jobs WHERE id=?",(ident,)).fetchone())
                    return self._insert(db,prepared,"draft")
            if action in ("activate","retry",None):
                with self._db() as db:
                    if not self.embedded_worker and not self.worker_healthy():
                        raise ValueError("独立 Image Worker 尚未就绪，无法提交收费任务")
                    count=db.execute("SELECT COUNT(*) FROM jobs WHERE state='running'").fetchone()[0]
                    if count >= MAX_PENDING: raise ValueError("image request queue is full")
                    original_id=None
                    if action in ("activate","retry"):
                        original_id=self._check_id(req.get("id"))
                        row=db.execute("SELECT * FROM jobs WHERE id=?",(original_id,)).fetchone()
                        if not row: raise ValueError("source task not found")
                        if action == "activate" and row["state"] != "draft":
                            raise ValueError("only a draft can be activated")
                        if action == "retry" and row["state"] not in ("failed","success"):
                            raise ValueError("only completed tasks can be retried")
                        prepared=self._prepare(json.loads(row["request_json"]))
                    else:
                        prepared=self._prepare(req.get("request"))
                    if not (prepared.get("prompt") or "").strip():
                        raise ValueError("image prompt is required")
                    self._require_provider(prepared)
                    if action == "activate":
                        now=time.time()
                        db.execute("""UPDATE jobs SET state='running',phase='排队等待执行',updated=?,
                                    started_at=NULL,finished_at=NULL WHERE id=? AND state='draft'""",
                                   (now,original_id))
                        created=self._public(db.execute("SELECT * FROM jobs WHERE id=?",(original_id,)).fetchone())
                    else:
                        created=self._insert(db,prepared,"running",source_id=original_id or "")
                        if action == "retry" and row["state"] == "failed":
                            db.execute("DELETE FROM jobs WHERE id=? AND state='failed'",(original_id,))
                            created["deleted_original_id"]=original_id
                if self.embedded_worker:
                    self.queue.put((created["id"],prepared))
                    self._start_worker()
                return created
            raise ValueError("unsupported native image task action")

    def _begin_execution(self,ident,phase):
        """The clock begins only when the Worker actually calls the provider.

        The submission timestamp and the worker claim are not execution time;
        waiting for another queued job must never inflate image latency.
        """
        now=time.time()
        with self.lock,self._db() as db:
            db.execute("""UPDATE jobs SET started_at=COALESCE(started_at,?),
                updated=?,phase=? WHERE id=? AND state='running'""",
                (now,now,str(phase)[:200],ident))

    def delete(self,ident=None,clear=False):
        with self.lock,self._db() as db:
            if clear:
                cur=db.execute("DELETE FROM jobs WHERE state IN ('success','failed')")
            else:
                ident=self._check_id(ident)
                cur=db.execute("DELETE FROM jobs WHERE id=? AND state IN ('draft','success','failed')",(ident,))
            return {"deleted":cur.rowcount}

    def _start_worker(self):
        if not self.embedded_worker:
            raise RuntimeError("Gateway must not execute image provider calls")
        if self.thread is None or not self.thread.is_alive():
            self.thread=threading.Thread(target=self._work,daemon=True,name="mikuchin-native-image-worker")
            self.thread.start()

    def _work(self):
        while True:
            ident,request=self.queue.get()
            try:
                self.execute_claimed(ident,request)
            finally:
                self.queue.task_done()

    def execute_claimed(self, ident, request):
            if request.get("kind") == "upscale":
                return self._execute_upscale(ident,request)
            try:
                refs=[]
                for item in request.get("strata_reference_assets",[]):
                    raw,mime=self.reference_bytes(item["id"])
                    refs.append("data:"+mime+";base64,"+base64.b64encode(raw).decode("ascii"))
                payload={key:val for key,val in request.items() if key != "strata_reference_assets"}
                payload["strata_reference_images"]=refs
                def status(phase):
                    # Local GPU requests may wait for the shared GPU lease or
                    # LLM unload. Only start the timer at actual inference.
                    if phase in ("Local Qwen-Image inference", "Real-ESRGAN 4x upscale"):
                        self._begin_execution(ident,phase)
                    with self.lock,self._db() as db:
                        db.execute("UPDATE jobs SET phase=?,updated=? WHERE id=? AND state='running'",
                                   (str(phase)[:200],time.time(),ident))
                local = request["strata_image_profile"].startswith("local-")
                if not local:
                    self._begin_execution(ident,"调用图像 API")
                if local:
                    response=local_images.generate(self,payload,on_status=status,diagnostic_id=ident)
                else:
                    response=self._provider(self,payload,on_status=status,diagnostic_id=ident)
                extra=response.get("strata") or {}
                name=extra.get("image_file")
                if not isinstance(name,str) or not re.fullmatch(r"[a-f0-9]{32}\.png",name):
                    raise ValueError("provider image was not saved in native storage")
                result={"image_ids":[name.removesuffix(".png")],"image_file":name,
                        "model":response.get("model"),"size":response.get("size"),
                        "seconds":extra.get("seconds"),"provider":"local" if local else "api"}
                with self._db() as db:
                    chat=db.execute("""SELECT c.session_id,j.source_id FROM chat_image_requests c
                        JOIN jobs j ON j.id=c.job_id WHERE c.job_id=?""",(ident,)).fetchone()
                if chat and chat["source_id"]:
                    result["edited_previous"]=True
                try:
                    gallery.register(self,name,source="chat" if chat else "studio",
                                     session_id=chat["session_id"] if chat else "",
                                     provider=result["provider"],model=response.get("model", ""),
                                     prompt=request.get("prompt", ""))
                except Exception as exc:
                    # The provider has already returned and the PNG exists.
                    # Never label this as a failed generation and invite a
                    # potentially billable retry just because indexing failed.
                    result["gallery_warning"] = "画廊索引暂不可用，请使用画廊刷新恢复"
                    result["gallery_error_type"] = type(exc).__name__
                if local:
                    # Native Qwen already ran ESRGAN within the *same* GPU
                    # handoff and returned only the processed bytes in memory.
                    # Indexing is performed here, after the model reload; it
                    # must never cause a second unload/reload cycle.
                    enhanced = response.get("upscaled_png")
                    if enhanced is not None:
                        try:
                            cover = gallery.attach_upscaled(self, name.removesuffix(".png"), enhanced)
                            result["image_ids"] = [cover]
                            result["image_file"] = cover + ".png"
                            w, h = map(int, request["size"].split("x"))
                            result["size"] = f"{w*4}x{h*4}"
                            result["upscale_applied"] = True
                            result["upscale_original_id"] = name.removesuffix(".png")
                            result["upscale_seconds"] = response.get("upscale_seconds")
                        except Exception as exc:
                            result["upscale_applied"] = False
                            result["upscale_warning"] = type(exc).__name__
                    elif response.get("upscale_warning"):
                        result["upscale_applied"] = False
                        result["upscale_warning"] = response["upscale_warning"]
                    result["gpu_handoffs"] = 1
                elif local_images.should_upscale(self, request):
                    try:
                        status("Running Real-ESRGAN 4x")
                        original = gallery._file(self, name.removesuffix(".png")).read_bytes()
                        enhanced = local_images.upscale(self, original, on_status=status)
                        cover = gallery.attach_upscaled(self, name.removesuffix(".png"), enhanced)
                        result["image_ids"] = [cover]
                        result["image_file"] = cover + ".png"
                        result["size"] = f"{int(request['size'].split('x')[0])*4}x{int(request['size'].split('x')[1])*4}"
                        result["upscale_applied"] = True
                        result["upscale_original_id"] = name.removesuffix(".png")
                    except Exception as exc:
                        # The original can already have been charged for or
                        # generated successfully. Never suggest replaying it.
                        result["upscale_applied"] = False
                        result["upscale_warning"] = type(exc).__name__
                with self.lock,self._db() as db:
                    db.execute("""UPDATE jobs SET state='success',phase='生成完成',result_json=?,
                                  updated=?,finished_at=? WHERE id=?""",
                               (json.dumps(result),time.time(),time.time(),ident))
            except Exception as exc:
                # Provider exception details may contain URLs with API keys in
                # their query strings. Keep only a bounded, redacted diagnostic.
                detail = re.sub(r"(?:https?://|socks5h?://)[^\s'\")]+",
                                "[private endpoint]", str(exc))
                detail = re.sub(r"(?i)(?:Bearer\s+|api[_-]?key[=:]\s*)\S+",
                                "[private key]", detail)
                message=(type(exc).__name__+": "+detail)[:350]
                with self.lock,self._db() as db:
                    db.execute("""UPDATE jobs SET state='failed',phase='任务失败',error=?,
                                  updated=?,finished_at=? WHERE id=?""",
                               (message,time.time(),time.time(),ident))

    def _execute_upscale(self, ident, request):
        try:
            original=gallery.upscale_source(self,request["image_id"])
            raw=gallery._file(self,original["id"]).read_bytes()
            if not 0 < len(raw) <= 20 * 1024 * 1024:
                raise ValueError("超分原图为空或过大")
            def status(phase):
                if phase == "Real-ESRGAN 4x upscale":
                    self._begin_execution(ident,phase)
                with self.lock,self._db() as db:
                    db.execute("UPDATE jobs SET phase=?,updated=? WHERE id=? AND state='running'",
                               (str(phase)[:200],time.time(),ident))
            status("等待 GPU 空闲并释放 LLM")
            output=local_images.upscale(self,raw,on_status=status)
            cover=gallery.attach_upscaled(self,original["id"],output)
            result={"image_id":cover,"source_id":original["id"],
                    "image_file":cover+".png","upscale_applied":True}
            with self.lock,self._db() as db:
                db.execute("""UPDATE jobs SET state='success',phase='4× 超分完成',
                    result_json=?,updated=?,finished_at=? WHERE id=?""",
                    (json.dumps(result),time.time(),time.time(),ident))
        except Exception as exc:
            # Offline-only operation: never re-run the original generation.
            with self.lock,self._db() as db:
                db.execute("""UPDATE jobs SET state='failed',phase='4× 超分失败',
                    error=?,updated=?,finished_at=? WHERE id=?""",
                    (type(exc).__name__+": "+str(exc)[:160],time.time(),time.time(),ident))
