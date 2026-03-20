# agent/finance/chat_store.py
"""
Persistent Chat History Store — SQLite-backed, per-chat isolation.

Survives container restarts (stored on Docker volume at /data/neomind/).
Supports two deletion modes:
  - purge:   permanently delete all messages (unrecoverable)
  - archive: hide from active view, but keep in DB for admin access

Schema:
  chats       — one row per Telegram chat (private or group)
  messages    — all messages, with chat_id FK and archived flag
"""

import os
import sqlite3
import json
import threading
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from pathlib import Path


# Default DB path — inside Docker volume for persistence
DEFAULT_DB_PATH = os.getenv(
    "NEOMIND_CHAT_DB",
    str(Path(os.getenv("HOME", "/data")) / ".neomind" / "chat_history.db")
)


class ChatStore:
    """SQLite-backed persistent chat history.

    Thread-safe. Each Telegram chat_id gets isolated history.
    Messages survive container restarts.

    Usage:
        store = ChatStore()
        store.add_message(chat_id=12345, role="user", content="hello")
        store.add_message(chat_id=12345, role="assistant", content="hi!")
        history = store.get_history(chat_id=12345)
        # → [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi!"}]
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or DEFAULT_DB_PATH
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_db()

    @property
    def _conn(self) -> sqlite3.Connection:
        """Thread-local connection."""
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            self._local.conn = sqlite3.connect(self.db_path)
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA foreign_keys=ON")
        return self._local.conn

    def _init_db(self):
        """Create tables if they don't exist."""
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS chats (
                chat_id     INTEGER PRIMARY KEY,
                chat_type   TEXT DEFAULT 'private',
                title       TEXT DEFAULT '',
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL,
                archived    INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS messages (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id     INTEGER NOT NULL,
                role        TEXT NOT NULL,
                content     TEXT NOT NULL,
                thinking    TEXT DEFAULT '',
                created_at  TEXT NOT NULL,
                archived    INTEGER DEFAULT 0,
                FOREIGN KEY (chat_id) REFERENCES chats(chat_id)
            );

            CREATE INDEX IF NOT EXISTS idx_messages_chat
                ON messages(chat_id, archived, id);
        """)
        self._conn.commit()

        # Migration: add thinking column to existing DBs
        try:
            self._conn.execute("SELECT thinking FROM messages LIMIT 1")
        except sqlite3.OperationalError:
            self._conn.execute("ALTER TABLE messages ADD COLUMN thinking TEXT DEFAULT ''")
            self._conn.commit()

    # ── Write Operations ─────────────────────────────────────────

    def add_message(self, chat_id: int, role: str, content: str,
                    chat_type: str = "private", chat_title: str = "",
                    thinking: str = ""):
        """Add a message to a chat's history.

        Args:
            thinking: LLM reasoning/thinking content (from deepseek-reasoner).
                      Only meaningful for role="assistant".
        """
        now = datetime.now(timezone.utc).isoformat()

        # Ensure chat exists
        self._conn.execute("""
            INSERT INTO chats (chat_id, chat_type, title, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET updated_at=?, title=COALESCE(NULLIF(?, ''), title)
        """, (chat_id, chat_type, chat_title, now, now, now, chat_title))

        # Insert message
        self._conn.execute("""
            INSERT INTO messages (chat_id, role, content, thinking, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (chat_id, role, content, thinking or "", now))

        self._conn.commit()

    def add_messages_batch(self, chat_id: int, messages: List[Dict],
                           chat_type: str = "private"):
        """Add multiple messages at once (for migration from in-memory)."""
        now = datetime.now(timezone.utc).isoformat()

        self._conn.execute("""
            INSERT INTO chats (chat_id, chat_type, title, created_at, updated_at)
            VALUES (?, ?, '', ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET updated_at=?
        """, (chat_id, chat_type, now, now, now))

        for msg in messages:
            self._conn.execute("""
                INSERT INTO messages (chat_id, role, content, created_at)
                VALUES (?, ?, ?, ?)
            """, (chat_id, msg["role"], msg["content"], now))

        self._conn.commit()

    # ── Read Operations ──────────────────────────────────────────

    def get_history(self, chat_id: int, limit: int = 50,
                    include_thinking: bool = False) -> List[Dict]:
        """Get active (non-archived) message history for a chat.

        Returns list of {"role": ..., "content": ..., "thinking"?: ...} dicts, oldest first.
        """
        rows = self._conn.execute("""
            SELECT role, content, thinking, created_at FROM messages
            WHERE chat_id = ? AND archived = 0
            ORDER BY id ASC
            LIMIT ?
        """, (chat_id, limit)).fetchall()

        result = []
        for r in rows:
            msg = {"role": r["role"], "content": r["content"], "created_at": r["created_at"]}
            if include_thinking and r["thinking"]:
                msg["thinking"] = r["thinking"]
            result.append(msg)
        return result

    def get_recent_history(self, chat_id: int, limit: int = 20) -> List[Dict]:
        """Get the most recent N messages (for LLM context window).

        Returns oldest-first order. Only role+content (no thinking — that's for display only).
        """
        rows = self._conn.execute("""
            SELECT role, content FROM (
                SELECT role, content, id FROM messages
                WHERE chat_id = ? AND archived = 0
                ORDER BY id DESC
                LIMIT ?
            ) sub ORDER BY id ASC
        """, (chat_id, limit)).fetchall()

        return [{"role": r["role"], "content": r["content"]} for r in rows]

    def count_messages(self, chat_id: int, include_archived: bool = False) -> int:
        """Count messages in a chat."""
        if include_archived:
            row = self._conn.execute(
                "SELECT COUNT(*) as cnt FROM messages WHERE chat_id = ?",
                (chat_id,)
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT COUNT(*) as cnt FROM messages WHERE chat_id = ? AND archived = 0",
                (chat_id,)
            ).fetchone()
        return row["cnt"]

    def list_chats(self, include_archived: bool = False) -> List[Dict]:
        """List all chats with message counts."""
        if include_archived:
            rows = self._conn.execute("""
                SELECT c.chat_id, c.chat_type, c.title, c.created_at, c.updated_at, c.archived,
                       COUNT(m.id) as message_count
                FROM chats c LEFT JOIN messages m ON c.chat_id = m.chat_id
                GROUP BY c.chat_id
                ORDER BY c.updated_at DESC
            """).fetchall()
        else:
            rows = self._conn.execute("""
                SELECT c.chat_id, c.chat_type, c.title, c.created_at, c.updated_at, c.archived,
                       COUNT(m.id) as message_count
                FROM chats c LEFT JOIN messages m ON c.chat_id = m.chat_id AND m.archived = 0
                WHERE c.archived = 0
                GROUP BY c.chat_id
                ORDER BY c.updated_at DESC
            """).fetchall()

        return [dict(r) for r in rows]

    # ── Clear: remove active messages from LLM context ───────────

    def clear_active(self, chat_id: int) -> int:
        """Clear active messages (same as /clear — removes from LLM context).

        Messages are archived, not deleted. Use purge() for permanent deletion.
        Returns number of messages archived.
        """
        cursor = self._conn.execute("""
            UPDATE messages SET archived = 1
            WHERE chat_id = ? AND archived = 0
        """, (chat_id,))
        self._conn.commit()
        return cursor.rowcount

    # ── Archive: hide from active view, keep in DB ───────────────

    def archive(self, chat_id: int) -> int:
        """Archive a chat — messages hidden from active view but still in DB.

        Admin can still query archived messages via get_archived().
        Returns number of messages archived.
        """
        now = datetime.now(timezone.utc).isoformat()

        # Archive all messages
        cursor = self._conn.execute("""
            UPDATE messages SET archived = 1
            WHERE chat_id = ? AND archived = 0
        """, (chat_id,))
        count = cursor.rowcount

        # Mark chat as archived
        self._conn.execute("""
            UPDATE chats SET archived = 1, updated_at = ?
            WHERE chat_id = ?
        """, (now, chat_id))

        self._conn.commit()
        return count

    def unarchive(self, chat_id: int) -> int:
        """Restore an archived chat — makes messages visible again."""
        now = datetime.now(timezone.utc).isoformat()

        cursor = self._conn.execute("""
            UPDATE messages SET archived = 0
            WHERE chat_id = ?
        """, (chat_id,))
        count = cursor.rowcount

        self._conn.execute("""
            UPDATE chats SET archived = 0, updated_at = ?
            WHERE chat_id = ?
        """, (now, chat_id))

        self._conn.commit()
        return count

    def get_archived(self, chat_id: int, limit: int = 100) -> List[Dict]:
        """Admin: get archived messages (not visible to normal /history)."""
        rows = self._conn.execute("""
            SELECT role, content, thinking, created_at FROM messages
            WHERE chat_id = ? AND archived = 1
            ORDER BY id ASC
            LIMIT ?
        """, (chat_id, limit)).fetchall()

        result = []
        for r in rows:
            msg = {"role": r["role"], "content": r["content"], "created_at": r["created_at"]}
            if r["thinking"]:
                msg["thinking"] = r["thinking"]
            result.append(msg)
        return result

    # ── Purge: permanent deletion ────────────────────────────────

    def purge(self, chat_id: int) -> int:
        """Permanently delete ALL messages for a chat (including archived).

        This is unrecoverable. Use archive() for soft-delete.
        Returns number of messages deleted.
        """
        cursor = self._conn.execute(
            "DELETE FROM messages WHERE chat_id = ?", (chat_id,)
        )
        count = cursor.rowcount

        self._conn.execute(
            "DELETE FROM chats WHERE chat_id = ?", (chat_id,)
        )

        self._conn.commit()
        return count

    def purge_all(self) -> int:
        """Permanently delete ALL messages across ALL chats.

        Nuclear option. Returns total messages deleted.
        """
        cursor = self._conn.execute("DELETE FROM messages")
        count = cursor.rowcount
        self._conn.execute("DELETE FROM chats")
        self._conn.commit()
        return count

    # ── Compact: drop oldest messages to stay under token limit ──

    def compact(self, chat_id: int, keep_recent: int = 4) -> Tuple[int, int]:
        """Archive old messages, keeping only the most recent N.

        Returns (archived_count, remaining_count).
        """
        # Find the ID threshold: keep messages with ID >= this
        row = self._conn.execute("""
            SELECT id FROM messages
            WHERE chat_id = ? AND archived = 0
            ORDER BY id DESC
            LIMIT 1 OFFSET ?
        """, (chat_id, keep_recent - 1)).fetchone()

        if not row:
            return 0, self.count_messages(chat_id)

        threshold_id = row["id"]

        cursor = self._conn.execute("""
            UPDATE messages SET archived = 1
            WHERE chat_id = ? AND archived = 0 AND id < ?
        """, (chat_id, threshold_id))

        self._conn.commit()
        remaining = self.count_messages(chat_id)
        return cursor.rowcount, remaining

    # ── Stats ────────────────────────────────────────────────────

    def get_stats(self) -> Dict:
        """Get overall store statistics."""
        total_chats = self._conn.execute("SELECT COUNT(*) as cnt FROM chats").fetchone()["cnt"]
        active_chats = self._conn.execute(
            "SELECT COUNT(*) as cnt FROM chats WHERE archived = 0"
        ).fetchone()["cnt"]
        total_messages = self._conn.execute("SELECT COUNT(*) as cnt FROM messages").fetchone()["cnt"]
        active_messages = self._conn.execute(
            "SELECT COUNT(*) as cnt FROM messages WHERE archived = 0"
        ).fetchone()["cnt"]
        archived_messages = total_messages - active_messages

        # DB file size
        try:
            db_size = os.path.getsize(self.db_path)
        except OSError:
            db_size = 0

        return {
            "total_chats": total_chats,
            "active_chats": active_chats,
            "total_messages": total_messages,
            "active_messages": active_messages,
            "archived_messages": archived_messages,
            "db_path": self.db_path,
            "db_size_kb": round(db_size / 1024, 1),
        }

    def close(self):
        """Close the database connection."""
        if hasattr(self._local, 'conn') and self._local.conn:
            self._local.conn.close()
            self._local.conn = None
