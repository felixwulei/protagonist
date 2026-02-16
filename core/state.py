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

        CREATE TABLE IF NOT EXISTS scheduled_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            description TEXT NOT NULL,
            original_text TEXT,
            trigger_date TEXT NOT NULL,
            triggered INTEGER DEFAULT 0,
            created_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_events_user ON scheduled_events(user_id);

        CREATE TABLE IF NOT EXISTS stickers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            file_id TEXT NOT NULL UNIQUE,
            emotion TEXT NOT NULL,
            source TEXT DEFAULT 'user',
            created_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_stickers_user ON stickers(user_id);

        CREATE TABLE IF NOT EXISTS shared_references (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            ref_type TEXT NOT NULL,
            keyword TEXT NOT NULL,
            context TEXT NOT NULL,
            original_quote TEXT,
            created_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_shared_refs_user ON shared_references(user_id);
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

    # --- Memory ---

    def get_user_profile(self, user_id: str) -> str:
        """Get the user's profile summary (JSON string)."""
        return self.get_meta(user_id, "user_profile", "")

    def set_user_profile(self, user_id: str, profile: str):
        self.set_meta(user_id, "user_profile", profile)

    def get_memory_summary(self, user_id: str) -> str:
        """Get the rolling conversation memory summary."""
        return self.get_meta(user_id, "memory_summary", "")

    def set_memory_summary(self, user_id: str, summary: str):
        self.set_meta(user_id, "memory_summary", summary)

    def get_relationship_narrative(self, user_id: str) -> str:
        """Get the relationship narrative — the emotional story of the friendship."""
        return self.get_meta(user_id, "relationship_narrative", "")

    def set_relationship_narrative(self, user_id: str, narrative: str):
        self.set_meta(user_id, "relationship_narrative", narrative)

    def get_mood_log(self, user_id: str) -> str:
        """Get recent mood observations (JSON string)."""
        return self.get_meta(user_id, "mood_log", "")

    def set_mood_log(self, user_id: str, log: str):
        self.set_meta(user_id, "mood_log", log)

    def get_summarized_up_to(self, user_id: str) -> int:
        """Get the message count up to which we've summarized."""
        val = self.get_meta(user_id, "summarized_up_to", "0")
        return int(val)

    def set_summarized_up_to(self, user_id: str, count: int):
        self.set_meta(user_id, "summarized_up_to", str(count))

    def get_all_messages(self, user_id: str, offset: int = 0, limit: int = 200) -> list[dict]:
        """Get messages starting from offset (by row id order)."""
        conn = self._connect()
        rows = conn.execute(
            "SELECT role, content, timestamp, type FROM messages "
            "WHERE user_id = ? ORDER BY id ASC LIMIT ? OFFSET ?",
            (user_id, limit, offset),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_last_message_time(self, user_id: str) -> float | None:
        """Get timestamp of the most recent message (any role)."""
        conn = self._connect()
        row = conn.execute(
            "SELECT timestamp FROM messages WHERE user_id = ? ORDER BY id DESC LIMIT 1",
            (user_id,),
        ).fetchone()
        conn.close()
        return row["timestamp"] if row else None

    def total_message_count(self, user_id: str) -> int:
        """Total messages (both user and friend)."""
        conn = self._connect()
        row = conn.execute(
            "SELECT COUNT(*) as c FROM messages WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        conn.close()
        return row["c"]

    # --- Chat ID (for proactive messages) ---

    def set_chat_id(self, user_id: str, chat_id: int):
        self.set_meta(user_id, "chat_id", str(chat_id))

    def get_chat_id(self, user_id: str) -> int | None:
        val = self.get_meta(user_id, "chat_id")
        return int(val) if val else None

    def get_all_chat_ids(self) -> list[tuple[str, int]]:
        """Return [(user_id, chat_id), ...] for all users with a stored chat_id."""
        conn = self._connect()
        rows = conn.execute(
            "SELECT user_id, value FROM meta WHERE key = 'chat_id'",
        ).fetchall()
        conn.close()
        return [(r["user_id"], int(r["value"])) for r in rows]

    # --- Scheduled Events ---

    def add_event(self, user_id: str, description: str, trigger_date: str, original: str = ""):
        conn = self._connect()
        # Avoid duplicates by checking description + date
        existing = conn.execute(
            "SELECT id FROM scheduled_events WHERE user_id = ? AND description = ? AND trigger_date = ?",
            (user_id, description, trigger_date),
        ).fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO scheduled_events (user_id, description, original_text, trigger_date, triggered, created_at) "
                "VALUES (?, ?, ?, ?, 0, ?)",
                (user_id, description, original, trigger_date, datetime.now().timestamp()),
            )
            conn.commit()
        conn.close()

    def get_due_events(self, user_id: str, date: str) -> list[dict]:
        """Get untriggered events due on or before the given date (YYYY-MM-DD)."""
        conn = self._connect()
        rows = conn.execute(
            "SELECT id, description, original_text, trigger_date FROM scheduled_events "
            "WHERE user_id = ? AND trigger_date <= ? AND triggered = 0 ORDER BY trigger_date",
            (user_id, date),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def mark_event_triggered(self, event_id: int):
        conn = self._connect()
        conn.execute("UPDATE scheduled_events SET triggered = 1 WHERE id = ?", (event_id,))
        conn.commit()
        conn.close()

    # --- Stickers ---

    def add_sticker(self, user_id: str, file_id: str, emotion: str, source: str = "user"):
        conn = self._connect()
        try:
            conn.execute(
                "INSERT OR IGNORE INTO stickers (user_id, file_id, emotion, source, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (user_id, file_id, emotion, source, datetime.now().timestamp()),
            )
            conn.commit()
        except Exception:
            pass
        conn.close()

    def get_stickers_by_emotion(self, user_id: str, emotion: str) -> list[dict]:
        conn = self._connect()
        rows = conn.execute(
            "SELECT file_id, emotion FROM stickers WHERE user_id = ? AND emotion = ?",
            (user_id, emotion),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_all_sticker_emotions(self, user_id: str) -> list[str]:
        conn = self._connect()
        rows = conn.execute(
            "SELECT DISTINCT emotion FROM stickers WHERE user_id = ?",
            (user_id,),
        ).fetchall()
        conn.close()
        return [r["emotion"] for r in rows]

    # --- Shared References (inside jokes, callbacks) ---

    def add_shared_reference(self, user_id: str, ref_type: str, keyword: str,
                             context: str, original_quote: str = ""):
        conn = self._connect()
        # Avoid duplicates by keyword
        existing = conn.execute(
            "SELECT id FROM shared_references WHERE user_id = ? AND keyword = ?",
            (user_id, keyword),
        ).fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO shared_references (user_id, ref_type, keyword, context, original_quote, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, ref_type, keyword, context, original_quote, datetime.now().timestamp()),
            )
            conn.commit()
        conn.close()

    def get_shared_references(self, user_id: str, limit: int = 15) -> list[dict]:
        conn = self._connect()
        rows = conn.execute(
            "SELECT ref_type, keyword, context, original_quote FROM shared_references "
            "WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
