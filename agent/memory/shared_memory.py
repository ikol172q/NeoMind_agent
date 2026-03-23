# agent/memory/shared_memory.py
"""
Cross-personality Shared Memory Layer — NeoMind cross-personality memory

All 3 modes (chat/coding/fin) can read and write shared user data:
- Preferences: user-level settings (language, timezone, name)
- Facts: semantic knowledge about the user (work, education, interests)
- Patterns: behavioral patterns (frequent stocks, coding languages, etc.)
- Feedback: user corrections and preferences (praise, complaints)

Storage: SQLite-backed at ~/.neomind/shared_memory.db
All entries include: source_mode (which personality mode learned this), timestamps

Architecture:
- Minimal dependencies (stdlib + sqlite3 only)
- WAL mode for safe concurrent access
- Atomic writes for data integrity
- Cross-mode visibility (any mode can read all data)
- Mode-aware ranking in context summaries
"""

import os
import json
import sqlite3
import threading
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, List, Any, Tuple


class SharedMemory:
    """Cross-personality persistent memory system.

    Stores user preferences, facts, patterns, and feedback in a shared SQLite database.
    All 3 personalities (chat, coding, finance) can read and write.

    Example usage:
        memory = SharedMemory()
        memory.set_preference('timezone', 'America/Los_Angeles', 'chat')
        memory.remember_fact('work', 'SDE at Google', 'chat')
        memory.record_pattern('frequent_stock', 'AAPL', 'fin')
        context = memory.get_context_summary('coding')
    """

    SCHEMA = {
        "preferences": """
            CREATE TABLE IF NOT EXISTS preferences (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                source_mode TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """,
        "facts": """
            CREATE TABLE IF NOT EXISTS facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                fact TEXT NOT NULL,
                source_mode TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """,
        "patterns": """
            CREATE TABLE IF NOT EXISTS patterns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pattern_type TEXT NOT NULL,
                pattern_value TEXT NOT NULL,
                count INTEGER DEFAULT 1,
                source_mode TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """,
        "feedback": """
            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                feedback_type TEXT NOT NULL,
                content TEXT NOT NULL,
                source_mode TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """,
    }

    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize SharedMemory with SQLite database.

        Args:
            db_path: Path to database file. Defaults to ~/.neomind/shared_memory.db
        """
        if db_path:
            self.db_path = Path(db_path).expanduser()
        elif os.getenv("NEOMIND_MEMORY_DIR"):
            self.db_path = Path(os.getenv("NEOMIND_MEMORY_DIR")).expanduser() / "shared_memory.db"
        elif Path("/data/neomind/db").exists():
            self.db_path = Path("/data/neomind/db") / "shared_memory.db"
        else:
            self.db_path = Path.home() / ".neomind" / "shared_memory.db"

        # Create directory with restricted permissions
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.db_path.parent, 0o700)
        except OSError:
            pass  # Windows doesn't support chmod

        # Thread-local connection for thread safety
        self._local = threading.local()

        # Initialize schema
        self._init_schema()

    def _get_conn(self) -> sqlite3.Connection:
        """Get thread-local database connection."""
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            # timeout is the first parameter to sqlite3.connect()
            self._local.conn = sqlite3.connect(str(self.db_path), timeout=5.0)
            self._local.conn.row_factory = sqlite3.Row
            # Enable WAL mode for concurrent access
            self._local.conn.execute("PRAGMA journal_mode=WAL")
        return self._local.conn

    def _close_conn(self):
        """Close thread-local connection."""
        if hasattr(self._local, 'conn') and self._local.conn:
            try:
                self._local.conn.close()
            except Exception:
                pass
            self._local.conn = None

    def _now(self) -> str:
        """Current timestamp in ISO 8601 format."""
        return datetime.now(timezone.utc).isoformat()

    def _init_schema(self):
        """Create all tables if they don't exist."""
        conn = self._get_conn()
        cursor = conn.cursor()
        for table_name, create_sql in self.SCHEMA.items():
            try:
                cursor.execute(create_sql)
            except sqlite3.OperationalError:
                pass  # Table already exists
        conn.commit()

    # ── Preferences ──────────────────────────────────────────────────────

    def set_preference(self, key: str, value: str, source_mode: str) -> None:
        """
        Store or update a user preference.

        Args:
            key: Preference key (e.g., 'timezone', 'language', 'name')
            value: Preference value
            source_mode: Which mode learned this (e.g., 'chat', 'coding', 'fin')

        Example:
            memory.set_preference('language', 'zh', 'chat')
            memory.set_preference('timezone', 'Asia/Shanghai', 'chat')
        """
        conn = self._get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO preferences (key, value, source_mode, updated_at) VALUES (?, ?, ?, ?)",
            (key, value, source_mode, self._now())
        )
        conn.commit()

    def get_preference(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """
        Get a user preference.

        Args:
            key: Preference key
            default: Default value if not found

        Returns:
            Preference value or default
        """
        conn = self._get_conn()
        row = conn.execute(
            "SELECT value FROM preferences WHERE key = ?",
            (key,)
        ).fetchone()
        return row["value"] if row else default

    def get_all_preferences(self) -> Dict[str, Any]:
        """
        Get all stored preferences.

        Returns:
            Dict mapping keys to values with metadata
            {
                'timezone': {'value': 'UTC', 'source_mode': 'chat', 'updated_at': '...'},
                ...
            }
        """
        conn = self._get_conn()
        rows = conn.execute("SELECT key, value, source_mode, updated_at FROM preferences").fetchall()
        return {
            row["key"]: {
                "value": row["value"],
                "source_mode": row["source_mode"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        }

    # ── Facts ────────────────────────────────────────────────────────────

    def remember_fact(self, category: str, fact: str, source_mode: str) -> int:
        """
        Remember a fact about the user.

        Args:
            category: Fact category (e.g., 'work', 'education', 'interests')
            fact: The fact itself (e.g., 'SDE at Google', 'BS in CS from MIT')
            source_mode: Which mode learned this

        Returns:
            ID of the stored fact

        Example:
            id = memory.remember_fact('work', 'SDE at Google', 'chat')
            id = memory.remember_fact('education', 'BS Computer Science', 'chat')
        """
        conn = self._get_conn()
        cursor = conn.execute(
            "INSERT INTO facts (category, fact, source_mode, created_at) VALUES (?, ?, ?, ?)",
            (category, fact, source_mode, self._now())
        )
        conn.commit()
        return cursor.lastrowid

    def recall_facts(self, category: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
        """
        Recall facts about the user.

        Args:
            category: Optional category filter
            limit: Max number of facts to return

        Returns:
            List of facts with metadata
            [
                {'id': 1, 'category': 'work', 'fact': 'SDE at Google', 'source_mode': 'chat', 'created_at': '...'},
                ...
            ]

        Example:
            work_facts = memory.recall_facts('work')
            all_facts = memory.recall_facts()
        """
        conn = self._get_conn()
        if category:
            rows = conn.execute(
                "SELECT id, category, fact, source_mode, created_at FROM facts WHERE category = ? ORDER BY created_at DESC LIMIT ?",
                (category, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, category, fact, source_mode, created_at FROM facts ORDER BY created_at DESC LIMIT ?",
                (limit,)
            ).fetchall()

        return [
            {
                "id": row["id"],
                "category": row["category"],
                "fact": row["fact"],
                "source_mode": row["source_mode"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    # ── Patterns ─────────────────────────────────────────────────────────

    def record_pattern(self, pattern_type: str, pattern_value: str, source_mode: str) -> None:
        """
        Record a behavioral pattern.

        Args:
            pattern_type: Type of pattern (e.g., 'frequent_stock', 'coding_language', 'tool')
            pattern_value: The pattern value (e.g., 'AAPL', 'Python', 'vim')
            source_mode: Which mode observed this

        Example:
            memory.record_pattern('frequent_stock', 'AAPL', 'fin')
            memory.record_pattern('coding_language', 'Python', 'coding')
            memory.record_pattern('tool', 'docker', 'coding')
        """
        conn = self._get_conn()
        # Try to increment count if pattern exists
        cursor = conn.execute(
            "UPDATE patterns SET count = count + 1, updated_at = ? WHERE pattern_type = ? AND pattern_value = ?",
            (self._now(), pattern_type, pattern_value)
        )

        # If no rows updated, insert new
        if cursor.rowcount == 0:
            conn.execute(
                "INSERT INTO patterns (pattern_type, pattern_value, count, source_mode, updated_at) VALUES (?, ?, ?, ?, ?)",
                (pattern_type, pattern_value, 1, source_mode, self._now())
            )

        conn.commit()

    def get_patterns(self, pattern_type: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Get recorded patterns, sorted by frequency.

        Args:
            pattern_type: Optional type filter
            limit: Max number of patterns

        Returns:
            List of patterns sorted by count (descending)
            [
                {'pattern_type': 'frequent_stock', 'pattern_value': 'AAPL', 'count': 5, 'source_mode': 'fin', 'updated_at': '...'},
                ...
            ]

        Example:
            stocks = memory.get_patterns('frequent_stock')
            all_patterns = memory.get_patterns()
        """
        conn = self._get_conn()
        if pattern_type:
            rows = conn.execute(
                "SELECT pattern_type, pattern_value, count, source_mode, updated_at FROM patterns WHERE pattern_type = ? ORDER BY count DESC LIMIT ?",
                (pattern_type, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT pattern_type, pattern_value, count, source_mode, updated_at FROM patterns ORDER BY count DESC LIMIT ?",
                (limit,)
            ).fetchall()

        return [
            {
                "pattern_type": row["pattern_type"],
                "pattern_value": row["pattern_value"],
                "count": row["count"],
                "source_mode": row["source_mode"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    # ── Feedback ─────────────────────────────────────────────────────────

    def record_feedback(self, feedback_type: str, content: str, source_mode: str) -> int:
        """
        Record user feedback.

        Args:
            feedback_type: Type of feedback ('correction', 'praise', 'complaint')
            content: The feedback content
            source_mode: Which mode received this

        Returns:
            ID of the stored feedback

        Example:
            memory.record_feedback('correction', 'AAPL is not APPL', 'chat')
            memory.record_feedback('praise', 'Great analysis!', 'fin')
            memory.record_feedback('complaint', 'Too verbose', 'coding')
        """
        conn = self._get_conn()
        cursor = conn.execute(
            "INSERT INTO feedback (feedback_type, content, source_mode, created_at) VALUES (?, ?, ?, ?)",
            (feedback_type, content, source_mode, self._now())
        )
        conn.commit()
        return cursor.lastrowid

    def get_recent_feedback(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Get recent user feedback.

        Args:
            limit: Max number of feedback entries

        Returns:
            List of recent feedback, newest first
            [
                {'id': 1, 'feedback_type': 'correction', 'content': '...', 'source_mode': 'chat', 'created_at': '...'},
                ...
            ]
        """
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT id, feedback_type, content, source_mode, created_at FROM feedback ORDER BY created_at DESC LIMIT ?",
            (limit,)
        ).fetchall()

        return [
            {
                "id": row["id"],
                "feedback_type": row["feedback_type"],
                "content": row["content"],
                "source_mode": row["source_mode"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    # ── Context for LLM ──────────────────────────────────────────────────

    def get_context_summary(self, mode: Optional[str] = None, max_tokens: int = 500) -> str:
        """
        Generate a compact summary of shared memory for LLM system prompt injection.

        Prioritizes:
        1. Preferences (all shared equally)
        2. Facts from this mode
        3. Facts from other modes
        4. Top patterns from this mode
        5. Top patterns from other modes
        6. Recent feedback

        Args:
            mode: Current mode (e.g., 'chat', 'coding', 'fin'). Used for prioritization.
            max_tokens: Approximate max tokens in output

        Returns:
            Markdown-formatted context string suitable for injection into system prompt

        Example:
            context = memory.get_context_summary('coding')
            # Use in system prompt: f"User context:\n{context}\n\nRespond accordingly..."
        """
        parts = []

        # Estimate tokens (rough: 4 chars per token)
        chars_per_token = 4
        budget = max_tokens * chars_per_token
        used = 0

        conn = self._get_conn()

        # 1. Preferences (important, usually short)
        prefs = conn.execute("SELECT key, value FROM preferences").fetchall()
        if prefs:
            pref_lines = ["**User Preferences:**"]
            for row in prefs:
                line = f"  - {row['key']}: {row['value']}"
                pref_lines.append(line)
                used += len(line)

            if used < budget:
                parts.extend(pref_lines)

        # 2. Facts (prioritize this mode, then others)
        facts = conn.execute("SELECT category, fact, source_mode FROM facts ORDER BY created_at DESC LIMIT 20").fetchall()
        if facts:
            # Group by category
            facts_by_cat = {}
            for row in facts:
                cat = row["category"]
                if cat not in facts_by_cat:
                    facts_by_cat[cat] = []
                facts_by_cat[cat].append((row["fact"], row["source_mode"]))

            if used < budget and facts_by_cat:
                parts.append("**About User:**")
                for cat in sorted(facts_by_cat.keys()):
                    for fact, source in facts_by_cat[cat][:2]:  # Top 2 per category
                        mode_hint = f" [{source}]" if source != mode else ""
                        line = f"  - {cat}: {fact}{mode_hint}"
                        if used + len(line) < budget:
                            parts.append(line)
                            used += len(line)

        # 3. Patterns (top frequency ones, this mode first)
        patterns = conn.execute("SELECT pattern_type, pattern_value, count, source_mode FROM patterns ORDER BY count DESC LIMIT 15").fetchall()
        if patterns:
            # Prioritize this mode's patterns
            this_mode_patterns = [p for p in patterns if p["source_mode"] == mode]
            other_patterns = [p for p in patterns if p["source_mode"] != mode]

            if this_mode_patterns or other_patterns:
                parts.append("**Patterns:**")
                for p in this_mode_patterns[:3] + other_patterns[:2]:
                    line = f"  - {p['pattern_type']}: {p['pattern_value']} (x{p['count']})"
                    if used + len(line) < budget:
                        parts.append(line)
                        used += len(line)

        # 4. Recent feedback (corrections most important)
        feedback = conn.execute("SELECT feedback_type, content FROM feedback ORDER BY feedback_type, created_at DESC LIMIT 10").fetchall()
        if feedback:
            corrections = [f for f in feedback if f["feedback_type"] == "correction"]
            if corrections:
                parts.append("**Recent Corrections:**")
                for f in corrections[:2]:
                    line = f"  - {f['content']}"
                    if used + len(line) < budget:
                        parts.append(line)
                        used += len(line)

        return "\n".join(parts) if parts else ""

    # ── Utilities ────────────────────────────────────────────────────────

    def clear_all(self) -> None:
        """
        Clear all data from shared memory.
        WARNING: This is irreversible. Use only for testing or explicit user request.
        """
        conn = self._get_conn()
        for table in ["preferences", "facts", "patterns", "feedback"]:
            conn.execute(f"DELETE FROM {table}")
        conn.commit()

    def get_stats(self) -> Dict[str, int]:
        """
        Get statistics about stored data.

        Returns:
            {
                'preferences': 5,
                'facts': 12,
                'patterns': 30,
                'feedback': 3,
            }
        """
        conn = self._get_conn()
        stats = {}
        for table in ["preferences", "facts", "patterns", "feedback"]:
            row = conn.execute(f"SELECT COUNT(*) as count FROM {table}").fetchone()
            stats[table] = row["count"]
        return stats

    def export_json(self) -> Dict[str, Any]:
        """
        Export all memory data as JSON (for backup/transfer).

        Returns:
            {
                'preferences': {...},
                'facts': [...],
                'patterns': [...],
                'feedback': [...],
            }
        """
        return {
            "preferences": self.get_all_preferences(),
            "facts": self.recall_facts(limit=1000),
            "patterns": self.get_patterns(limit=1000),
            "feedback": self.get_recent_feedback(limit=1000),
        }

    def import_json(self, data: Dict[str, Any]) -> None:
        """
        Import data from JSON backup.
        Merges with existing data (doesn't clear).

        Args:
            data: Dict from export_json()
        """
        conn = self._get_conn()

        # Import preferences
        for key, pref_data in data.get("preferences", {}).items():
            conn.execute(
                "INSERT OR REPLACE INTO preferences (key, value, source_mode, updated_at) VALUES (?, ?, ?, ?)",
                (key, pref_data["value"], pref_data["source_mode"], pref_data["updated_at"])
            )

        # Import facts
        for fact in data.get("facts", []):
            conn.execute(
                "INSERT INTO facts (category, fact, source_mode, created_at) VALUES (?, ?, ?, ?)",
                (fact["category"], fact["fact"], fact["source_mode"], fact["created_at"])
            )

        # Import patterns
        for pattern in data.get("patterns", []):
            conn.execute(
                "INSERT INTO patterns (pattern_type, pattern_value, count, source_mode, updated_at) VALUES (?, ?, ?, ?, ?)",
                (pattern["pattern_type"], pattern["pattern_value"], pattern["count"], pattern["source_mode"], pattern["updated_at"])
            )

        # Import feedback
        for feedback in data.get("feedback", []):
            conn.execute(
                "INSERT INTO feedback (feedback_type, content, source_mode, created_at) VALUES (?, ?, ?, ?)",
                (feedback["feedback_type"], feedback["content"], feedback["source_mode"], feedback["created_at"])
            )

        conn.commit()

    def close(self):
        """Close database connection."""
        self._close_conn()

    def __del__(self):
        """Cleanup on garbage collection."""
        try:
            self.close()
        except Exception:
            pass
