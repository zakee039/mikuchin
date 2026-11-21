"""Durable, session-scoped image-tool turns. No provider calls in this module.

One turn id maps to one deterministic image request id. A crash between the
ImageJobStore commit and the turn link is resolved by READ-ONLY lookup; no
ambiguous POST replay is permitted.
"""
from __future__ import annotations
import hashlib
import json
import re
import secrets
import sqlite3
import threading
import time
from pathlib import Path

ID = re.compile(r"[0-9a-f]{32}\Z")
PENDING = ("queued", "running", "image_done", "vision_running")
FINISHED = ("text_done", "decision_error", "tool_rejected", "unavailable",
            "cancelled", "image_failed", "vision_done", "vision_failed")
VALID_STATES = frozenset(PENDING + FINISHED + ("deciding", "awaiting_approval"))
IMAGE_FIELDS = ("image_file", "image_original_file", "upscale_original_id",
                "upscale_applied", "upscale_fallback", "edited_previous",
                "image_prompt", "image_model", "model", "text", "source_id")


class TurnForbidden(ValueError):
    pass


class ChatTurnStore:
    def __init__(self, directory):
        root = Path(directory).resolve()
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / "native-chat-turns.sqlite3"
        self.lock = threading.RLock()
        with self._db() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS turns (
                turn_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                state TEXT NOT NULL,
                request_json TEXT NOT NULL,
                decision_json TEXT NOT NULL DEFAULT '{}',
                image_request_json TEXT NOT NULL DEFAULT '{}',
                profile_id TEXT NOT NULL DEFAULT '',
                online INTEGER NOT NULL DEFAULT 0,
                approval_hash TEXT NOT NULL DEFAULT '',
                approval_expires REAL NOT NULL DEFAULT 0,
                job_id TEXT NOT NULL DEFAULT '',
                text TEXT NOT NULL DEFAULT '',
                reasoning_text TEXT NOT NULL DEFAULT '',
                error TEXT NOT NULL DEFAULT '',
                created REAL NOT NULL,
                updated REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS turns_session ON turns(session_id,created DESC);
            CREATE INDEX IF NOT EXISTS turns_pending ON turns(state,updated);
            """)
            # Existing production Turn databases predate streamed reasoning.
            # A single additive migration preserves all settled image jobs.
            columns={r["name"] for r in db.execute("PRAGMA table_info(turns)")}
            if "reasoning_text" not in columns:
                db.execute("ALTER TABLE turns ADD COLUMN reasoning_text TEXT NOT NULL DEFAULT ''")
            db.execute("PRAGMA journal_mode=WAL")
            # Deciding was interrupted at service stop: NEVER automatically repeat.
            db.execute("""UPDATE turns SET state='decision_error',
                error='模型决策在服务重启前中断，请显式发起新请求',updated=?
                WHERE state='deciding'""", (time.time(),))
            # The vision tail is nonchargeable but is not replayed after crash.
            db.execute("""UPDATE turns SET state='vision_failed',
                error='视觉尾部在服务重启前中断，图片生成结果仍保留',updated=?
                WHERE state='vision_running'""", (time.time(),))

    class _DB:
        def __init__(self, path): self.path = path
        def __enter__(self):
            self.conn = sqlite3.connect(self.path, timeout=15)
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA busy_timeout=15000")
            return self.conn
        def __exit__(self, kind, exc, tb):
            try:
                if kind: self.conn.rollback()
                else: self.conn.commit()
            finally: self.conn.close()
    def _db(self): return self._DB(self.path)

    @staticmethod
    def validate_id(ident):
        if not isinstance(ident, str) or not ID.fullmatch(ident):
            raise ValueError("Expected 32 lowercase hex identifier")
        return ident

    def get(self, session_id, turn_id):
        self.validate_id(session_id)
        self.validate_id(turn_id)
        with self._db() as db:
            row = db.execute("SELECT * FROM turns WHERE turn_id=?", (turn_id,)).fetchone()
        if row and row["session_id"] != session_id:
            raise TurnForbidden("Turn belongs to another session")
        return dict(row) if row else None

    def create(self, session_id, turn_id, request):
        self.validate_id(session_id)
        self.validate_id(turn_id)
        raw = json.dumps(request, ensure_ascii=False, allow_nan=False)
        if len(raw.encode("utf-8")) > 7 * 1024 * 1024:
            raise ValueError("Turn history too large")
        with self.lock, self._db() as db:
            found = db.execute("SELECT session_id FROM turns WHERE turn_id=?", (turn_id,)).fetchone()
            if found:
                if found["session_id"] != session_id:
                    raise TurnForbidden("Turn belongs to another session")
                return False
            now = time.time()
            db.execute("""INSERT INTO turns(turn_id,session_id,state,request_json,created,updated)
                       VALUES(?,?,'deciding',?,?,?)""", (turn_id,session_id,raw,now,now))
        return True

    def transition(self, session_id, turn_id, from_states, state, **columns):
        if state not in VALID_STATES:
            raise ValueError("Invalid target turn state")
        if isinstance(from_states, str): from_states = (from_states,)
        if not from_states or set(from_states) - VALID_STATES:
            raise ValueError("Invalid source state")
        allowed = {"decision_json","image_request_json","profile_id","online",
                   "approval_hash","approval_expires","job_id","text","reasoning_text","error"}
        if set(columns) - allowed:
            raise ValueError("Disallowed transition fields")
        # Update in one transactional compare-and-swap.
        with self.lock, self._db() as db:
            found = db.execute("SELECT state,session_id FROM turns WHERE turn_id=?", (turn_id,)).fetchone()
            if not found or found["session_id"] != session_id:
                raise TurnForbidden("Unknown turn in this session")
            if found["state"] not in from_states: return False
            cols = ["state=?", "updated=?"] + [k+"=?" for k in columns]
            vals = [state,time.time(),*columns.values(),turn_id]
            db.execute("UPDATE turns SET "+",".join(cols)+" WHERE turn_id=?", vals)
        return True

    def decision_text(self, session_id, turn_id, text, reasoning=""):
        return self.transition(session_id, turn_id, "deciding", "text_done",
                               text=text,reasoning_text=reasoning[:140000])

    def decision_tool(self, session_id, turn_id, tool, image_request, profile,reasoning=""):
        """Freeze executable choices, produce one-time approval only if paid."""
        public_tool = {k:tool[k] for k in ("name","tool_call_id","arguments")}
        decision = json.dumps(public_tool, ensure_ascii=False, allow_nan=False)
        request = json.dumps(image_request, ensure_ascii=False, allow_nan=False)
        online = bool(profile["online"])
        require_approval = online and profile.get("require_approval",False) is True
        token = secrets.token_urlsafe(32) if require_approval else None
        succeeded = self.transition(session_id,turn_id,"deciding",
            "awaiting_approval" if require_approval else "queued",
            decision_json=decision,image_request_json=request,
            profile_id=profile["profile"],online=int(online),
            reasoning_text=reasoning[:140000],
            approval_hash=hashlib.sha256(token.encode()).hexdigest() if token else "",
            approval_expires=time.time()+600 if token else 0)
        return token if succeeded else None

    def accept_approval(self, session_id, turn_id, token):
        if not isinstance(token,str) or not 30 <= len(token) <= 200:
            raise ValueError("One-time approval token is required")
        with self.lock, self._db() as db:
            row = db.execute("SELECT * FROM turns WHERE turn_id=?", (turn_id,)).fetchone()
            if row is None or row["session_id"] != session_id:
                raise TurnForbidden("Unknown turn")
            if row["state"] != "awaiting_approval":
                raise ValueError("Turn is not awaiting approval")
            digest=hashlib.sha256(token.encode()).hexdigest()
            if not row["online"] or time.time() >= row["approval_expires"] or not secrets.compare_digest(digest,row["approval_hash"]):
                raise ValueError("Approval expired or does not match the original paid request")
            db.execute("""UPDATE turns SET state='queued',approval_hash='',approval_expires=0,updated=?
                WHERE turn_id=?""",(time.time(),turn_id))
        return True

    def cancel_approval(self, session_id, turn_id):
        return self.transition(session_id,turn_id,"awaiting_approval","cancelled",
                               approval_hash="",approval_expires=0,
                               text="已取消在线付费生图，未创建任何图像任务")

    def job_for(self, row, jobs):
        if jobs is None: return None
        # Indexed, read-only lookup survives long chats and ambiguous POST
        # acknowledgements without ever resubmitting billable requests.
        if hasattr(jobs, "chat_lookup"):
            return jobs.chat_lookup(row["session_id"],row["turn_id"])
        entries = jobs.listing(None,session_id=row["session_id"],limit=100).get("jobs",[])
        for entry in entries:
            if entry.get("request_id")==row["turn_id"]:
                return entry
        return None

    def public(self, session_id, turn_id, jobs=None):
        row=self.get(session_id,turn_id)
        if row is None: return None
        decision=json.loads(row["decision_json"])
        result={"session_id":row["session_id"],"turn_id":row["turn_id"],
                "state":row["state"],"text":row["text"],
                "reasoning":row["reasoning_text"],"error":row["error"][:200],
                "tool":decision if decision else None,
                "request_id":row["turn_id"] if decision else None,
                "job_id":row["job_id"] or None,"profile_id":row["profile_id"],
                "online":bool(row["online"]),"created":row["created"],
                "updated":row["updated"]}
        if decision:
            frozen=json.loads(row["image_request_json"] or "{}")
            # API work never occupies the local LLM GPU. The concurrent
            # local mode likewise keeps the engine loaded during Qwen-Image.
            result["background"]=bool(row["online"] or
                                      frozen.get("_chat_runtime_mode")=="concurrent")
        # Completed image/vision turns must still expose their owned picture
        # after a refresh; only the safe, small result fields cross the wire.
        if decision and row["state"] not in ("awaiting_approval", "cancelled"):
            job = self.job_for(row,jobs)
            if job:
                value=job.get("result") or {}
                picture={k:value[k] for k in IMAGE_FIELDS if k in value and
                         isinstance(value[k],(str,bool,int,float))}
                result["job"]={"id":job["id"],"state":job.get("state"),
                               "phase":str(job.get("phase") or "")[:120],
                               "started_at":job.get("started_at"),
                               "finished_at":job.get("finished_at"),
                               "elapsed_s":job.get("elapsed_s"),
                               "result":picture}
                result["job_id"]=job["id"]
        return result

    def pending(self):
        with self._db() as db:
            rows=db.execute("""SELECT session_id,turn_id,state FROM turns
                WHERE state IN ('queued','running','image_done')
                ORDER BY updated ASC LIMIT 100""").fetchall()
        return [dict(r) for r in rows]
