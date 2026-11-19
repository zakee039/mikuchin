"""Mikuchin-owned conversation persistence; no PolyStrata state/KV dependency.

Only *new* Mikuchin Native sessions live here. Old SessionV1 databases and
POLYKV1 snapshots are neither imported nor opened. SQLite is WAL-backed so
simultaneous browser clients can read while another request saves a turn.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

_ID = re.compile(r"[0-9a-f]{32}\Z")
_MAX_MESSAGES = 2000
_MAX_CHAT_JSON = 7 * 1024 * 1024
_SAMPLING_KEYS = frozenset(("thinking", "budget", "temperature", "top_p",
                            "top_k", "max", "seed", "show", "esp", "mcp"))


class MissingConversation(LookupError):
    """Session not present in the new native store."""


def valid_id(value):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError("conversation ID must be 32 lowercase hexadecimal characters")
    return value


def _json(value):
    result = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    if len(result.encode("utf-8")) > _MAX_CHAT_JSON:
        raise ValueError("conversation exceeds 7 MiB storage limit")
    return result


def valid_sampling(data):
    if not isinstance(data, dict) or set(data) - _SAMPLING_KEYS:
        raise ValueError("invalid sampling settings")
    for key, value in data.items():
        if key == "thinking":
            if value not in ("none", "low", "medium", "high"):
                raise ValueError("invalid thinking level")
        elif key in ("show", "esp", "mcp"):
            if type(value) is not bool:
                raise ValueError(f"sampling {key} must be boolean")
        elif key in ("budget", "top_k", "max", "seed"):
            if value == "" and key in ("max", "seed"):
                continue
            if type(value) is not int or value < 0 or value > 2 ** 31 - 1:
                raise ValueError(f"sampling {key} must be a non-negative integer")
            if key == "budget" and value > 262144:
                raise ValueError("thinking budget exceeds 262144")
            if key == "top_k" and not 1 <= value <= 128:
                raise ValueError("top_k must be between 1 and 128")
        elif key in ("temperature", "top_p"):
            if type(value) not in (int, float):
                raise ValueError(f"sampling {key} must be a number")
            if key == "temperature" and not 0 <= value <= 3:
                raise ValueError("temperature must be between 0 and 3")
            if key == "top_p" and not 0 < value <= 1:
                raise ValueError("top_p must be greater than 0 and at most 1")
    _json(data)  # reject NaN / infinity and unbounded values
    return data


def _title_from_messages(messages):
    for message in messages:
        if message.get("role") != "user":
            continue
        value = message.get("text") or message.get("content") or ""
        if isinstance(value, str):
            title = " ".join(value.split()).strip()
            if title:
                return title[:80]
    return "New chat"


class ConversationStore:
    def __init__(self, root: str | os.PathLike):
        self.root = Path(root).resolve()
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path = self.root / "native-conversations.sqlite3"
        with self._db() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise ValueError("unsupported native conversation schema version")
            db.executescript("""
            CREATE TABLE IF NOT EXISTS conversations(
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                pinned INTEGER NOT NULL DEFAULT 0,
                sampling TEXT NOT NULL DEFAULT '{}',
                web_messages TEXT NOT NULL DEFAULT '[]',
                created REAL NOT NULL,
                updated REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS global_settings(
                key TEXT PRIMARY KEY,
                json_value TEXT NOT NULL
            );
            """)
            if version == 0:
                db.execute("PRAGMA user_version=1")
            db.execute("PRAGMA journal_mode=WAL")

    @staticmethod
    def default_root():
        if os.name == "nt":
            return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "MikuchinNative"
        return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "mikuchin-native"

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=10000")
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _record(row, full=False):
        result = {
            "id": row["id"], "title": row["title"], "pinned": bool(row["pinned"]),
            "created": row["created"], "updated": row["updated"],
        }
        if full:
            result["sampling"] = json.loads(row["sampling"])
            result["web_messages"] = json.loads(row["web_messages"])
        return result

    def listing(self):
        with self._db() as db:
            rows = db.execute("""SELECT id,title,pinned,created,updated FROM conversations
                                ORDER BY pinned DESC,updated DESC LIMIT 2000""").fetchall()
            return [self._record(row) for row in rows]

    def get(self, ident):
        valid_id(ident)
        with self._db() as db:
            row = db.execute("SELECT * FROM conversations WHERE id=?", (ident,)).fetchone()
            if row is None:
                raise MissingConversation("conversation not found")
            return self._record(row, full=True)

    def has_messages(self, ident):
        """An uncreated fresh session is empty; existing chats cannot change role."""
        valid_id(ident)
        with self._db() as db:
            row = db.execute("SELECT web_messages FROM conversations WHERE id=?", (ident,)).fetchone()
            return bool(row and json.loads(row["web_messages"]))

    def save_messages(self, ident, messages):
        valid_id(ident)
        if not isinstance(messages, list) or len(messages) > _MAX_MESSAGES or not all(
                isinstance(item, dict) and item.get("role") in ("user", "assistant", "system", "tool")
                for item in messages):
            raise ValueError("web_messages must be an array of up to 2000 valid messages")
        serialized = _json(messages)
        title = _title_from_messages(messages)
        now = time.time()
        with self._db() as db:
            db.execute("""INSERT INTO conversations(id,title,web_messages,created,updated)
                          VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                          title=CASE WHEN conversations.title='New chat'
                                     AND conversations.web_messages='[]' THEN excluded.title
                                     ELSE conversations.title END,
                          web_messages=excluded.web_messages,updated=excluded.updated""",
                       (ident, title, serialized, now, now))
        return {"id": ident, "saved": True}

    def change(self, ident, action, request):
        valid_id(ident)
        if action == "lock_kv":
            raise ValueError("Manual KV locking is intentionally retired in Mikuchin Native")
        if action == "rename":
            title = request.get("title")
            if not isinstance(title, str) or not (title := " ".join(title.split())) or len(title) > 100:
                raise ValueError("conversation title must be 1-100 characters")
            field, value = "title", title
        elif action == "pin":
            value = request.get("pinned")
            if type(value) is not bool:
                raise ValueError("pinned must be boolean")
            field, value = "pinned", int(value)
        elif action == "sampling":
            field, value = "sampling", _json(valid_sampling(request.get("sampling")))
        else:
            raise ValueError("unknown conversation action")
        now = time.time()
        with self._db() as db:
            if action == "sampling":
                db.execute("""INSERT OR IGNORE INTO conversations(id,title,created,updated)
                              VALUES(?,?,?,?)""", (ident, "New chat", now, now))
            cursor = db.execute(f"UPDATE conversations SET {field}=?,updated=? WHERE id=?",
                                (value, now, ident))
            if cursor.rowcount != 1:
                raise MissingConversation("conversation not found")
        return self.get(ident)

    def delete(self, ident):
        valid_id(ident)
        with self._db() as db:
            cursor = db.execute("DELETE FROM conversations WHERE id=?", (ident,))
            if cursor.rowcount != 1:
                raise MissingConversation("conversation not found")
        return {"id": ident, "deleted": True}

    def default_sampling(self):
        with self._db() as db:
            row = db.execute("SELECT json_value FROM global_settings WHERE key='sampling'").fetchone()
            return json.loads(row["json_value"]) if row else {}

    def save_default_sampling(self, value):
        serialized = _json(valid_sampling(value))
        with self._db() as db:
            db.execute("""INSERT INTO global_settings(key,json_value) VALUES('sampling',?)
                          ON CONFLICT(key) DO UPDATE SET json_value=excluded.json_value""",
                       (serialized,))
        return {"sampling": value}
