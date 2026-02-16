"""Per-user persistent state — conversation history, promises, milestones."""
from __future__ import annotations

import sqlite3
import os
from datetime import datetime


class UserState:
    """Multi-user SQLite state. Each user gets their own namespace."""

    def __init__(self, db_path: str = None):
        if db_path is None:
            try:
                from app.config import DB_PATH
                db_path = DB_PATH
            except ImportError:
                db_path = os.path.join(os.path.dirname(__file__), "..", "protagonist.db")
        self.db_path = os.path.abspath(db_path)
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp REAL NOT NULL,
            type TEXT DEFAULT 'text'
        );
        CREATE INDEX IF NOT EXISTS idx_messages_user ON messages(user_id);

        CREATE TABLE IF NOT EXISTS promises (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            thing TEXT NOT NULL,
            original TEXT,
            created_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_promises_user ON promises(user_id);

        CREATE TABLE IF NOT EXISTS meta (
            user_id TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT,
            PRIMARY KEY (user_id, key)
        );
        """)
        conn.commit()
        conn.close()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    # --- Messages ---

    def add_message(self, user_id: str, role: str, content: str, msg_type: str = "text"):
        conn = self._connect()
        conn.execute(
            "INSERT INTO messages (user_id, role, content, timestamp, type) VALUES (?, ?, ?, ?, ?)",
            (user_id, role, content, datetime.now().timestamp(), msg_type),
        )
        conn.commit()
        conn.close()

    def get_history(self, user_id: str, limit: int = 50) -> list[dict]:
        conn = self._connect()
        rows = conn.execute(
            "SELECT role, content, timestamp, type FROM messages WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
        conn.close()
        return [dict(r) for r in reversed(rows)]

    def message_count(self, user_id: str) -> int:
        conn = self._connect()
        row = conn.execute(
            "SELECT COUNT(*) as c FROM messages WHERE user_id = ? AND role = 'user'",
            (user_id,),
        ).fetchone()
        conn.close()
        return row["c"]

    # --- Promises ---

    def add_promise(self, user_id: str, thing: str, original: str = ""):
        conn = self._connect()
        existing = conn.execute(
            "SELECT id FROM promises WHERE user_id = ? AND thing = ?",
            (user_id, thing),
        ).fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO promises (user_id, thing, original, created_at) VALUES (?, ?, ?, ?)",
                (user_id, thing, original, datetime.now().timestamp()),
            )
            conn.commit()
        conn.close()

    def get_promises(self, user_id: str) -> list[dict]:
        conn = self._connect()
        rows = conn.execute(
            "SELECT thing, original FROM promises WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    # --- Meta ---

    def get_meta(self, user_id: str, key: str, default: str = None) -> str | None:
        conn = self._connect()
        row = conn.execute(
            "SELECT value FROM meta WHERE user_id = ? AND key = ?",
            (user_id, key),
        ).fetchone()
        conn.close()
        return row["value"] if row else default

    def set_meta(self, user_id: str, key: str, value: str):
        conn = self._connect()
        conn.execute(
            "INSERT OR REPLACE INTO meta (user_id, key, value) VALUES (?, ?, ?)",
            (user_id, key, value),
        )
        conn.commit()
        conn.close()

    def first_message_time(self, user_id: str) -> float | None:
        val = self.get_meta(user_id, "first_message_time")
        return float(val) if val else None

    def milestones_sent(self, user_id: str) -> set[int]:
        val = self.get_meta(user_id, "milestones_sent", "")
        if not val:
            return set()
        return set(int(x) for x in val.split(",") if x)

    def mark_milestone(self, user_id: str, count: int):
        sent = self.milestones_sent(user_id)
        sent.add(count)
        self.set_meta(user_id, "milestones_sent", ",".join(str(x) for x in sent))
