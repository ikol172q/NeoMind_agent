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
        self._migrate_schema()

    def _migrate_schema(self):
        """Add source_instance and project_id columns (Phase 4 migration).

        Idempotent: safe to run multiple times. Existing rows get NULL.
        """
        conn = self._get_conn()
        tables = ["preferences", "facts", "patterns", "feedback"]
        new_cols = ["source_instance", "project_id"]
        for table in tables:
            for col in new_cols:
                try:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} TEXT")
                except sqlite3.OperationalError:
                    pass  # Column already exists
        conn.commit()

    # ── Preferences ──────────────────────────────────────────────────────

    def set_preference(self, key: str, value: str, source_mode: str,
                       source_instance: Optional[str] = None,
                       project_id: Optional[str] = None) -> None:
        """
        Store or update a user preference.

        Args:
            key: Preference key (e.g., 'timezone', 'language', 'name')
            value: Preference value
            source_mode: Which mode learned this (e.g., 'chat', 'coding', 'fin')
            source_instance: Which agent instance wrote this (e.g., 'coder-1')
            project_id: Which project context (e.g., 'build-trading-bot')

        Example:
            memory.set_preference('language', 'zh', 'chat')
            memory.set_preference('timezone', 'Asia/Shanghai', 'chat', source_instance='mgr-1')
        """
        conn = self._get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO preferences (key, value, source_mode, updated_at, source_instance, project_id) VALUES (?, ?, ?, ?, ?, ?)",
            (key, value, source_mode, self._now(), source_instance, project_id)
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

    def remember_fact(self, category: str, fact: str, source_mode: str,
                      source_instance: Optional[str] = None,
                      project_id: Optional[str] = None) -> int:
        """
        Remember a fact about the user.

        Args:
            category: Fact category (e.g., 'work', 'education', 'interests')
            fact: The fact itself (e.g., 'SDE at Google', 'BS in CS from MIT')
            source_mode: Which mode learned this
            source_instance: Which agent instance wrote this
            project_id: Which project context

        Returns:
            ID of the stored fact

        Example:
            id = memory.remember_fact('work', 'SDE at Google', 'chat')
            id = memory.remember_fact('education', 'BS CS', 'chat', source_instance='mgr-1')
        """
        conn = self._get_conn()
        cursor = conn.execute(
            "INSERT INTO facts (category, fact, source_mode, created_at, source_instance, project_id) VALUES (?, ?, ?, ?, ?, ?)",
            (category, fact, source_mode, self._now(), source_instance, project_id)
        )
        conn.commit()
        return cursor.lastrowid

    def recall_facts(self, category: Optional[str] = None, limit: int = 20,
                     include_personas: Optional[List[str]] = None,
                     project_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Recall facts about the user.

        Args:
            category: Optional category filter
            limit: Max number of facts to return
            include_personas: If provided, only return facts from these source_modes
            project_id: If provided, only return facts from this project

        Returns:
            List of facts with metadata

        Example:
            work_facts = memory.recall_facts('work')
            coding_facts = memory.recall_facts(include_personas=['coding', 'fin'])
        """
        conn = self._get_conn()
        conditions = []
        params: list = []

        if category:
            conditions.append("category = ?")
            params.append(category)

        if include_personas:
            placeholders = ",".join("?" for _ in include_personas)
            conditions.append(f"source_mode IN ({placeholders})")
            params.extend(include_personas)

        if project_id:
            conditions.append("project_id = ?")
            params.append(project_id)

        where = ""
        if conditions:
            where = " WHERE " + " AND ".join(conditions)

        params.append(limit)
        rows = conn.execute(
            f"SELECT id, category, fact, source_mode, created_at, source_instance, project_id FROM facts{where} ORDER BY created_at DESC LIMIT ?",
            params
        ).fetchall()

        return [
            {
                "id": row["id"],
                "category": row["category"],
                "fact": row["fact"],
                "source_mode": row["source_mode"],
                "created_at": row["created_at"],
                "source_instance": row["source_instance"],
                "project_id": row["project_id"],
            }
            for row in rows
        ]

    # ── Patterns ─────────────────────────────────────────────────────────

    def record_pattern(self, pattern_type: str, pattern_value: str, source_mode: str,
                       source_instance: Optional[str] = None,
                       project_id: Optional[str] = None) -> None:
        """
        Record a behavioral pattern.

        Args:
            pattern_type: Type of pattern (e.g., 'frequent_stock', 'coding_language', 'tool')
            pattern_value: The pattern value (e.g., 'AAPL', 'Python', 'vim')
            source_mode: Which mode observed this
            source_instance: Which agent instance observed this
            project_id: Which project context

        Example:
            memory.record_pattern('frequent_stock', 'AAPL', 'fin')
            memory.record_pattern('coding_language', 'Python', 'coding', source_instance='coder-1')
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
                "INSERT INTO patterns (pattern_type, pattern_value, count, source_mode, updated_at, source_instance, project_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (pattern_type, pattern_value, 1, source_mode, self._now(), source_instance, project_id)
            )

        conn.commit()

    def get_patterns(self, pattern_type: Optional[str] = None, limit: int = 50,
                     include_personas: Optional[List[str]] = None,
                     project_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get recorded patterns, sorted by frequency.

        Args:
            pattern_type: Optional type filter
            limit: Max number of patterns
            include_personas: If provided, only return patterns from these source_modes
            project_id: If provided, only return patterns from this project

        Returns:
            List of patterns sorted by count (descending)

        Example:
            stocks = memory.get_patterns('frequent_stock')
            fin_patterns = memory.get_patterns(include_personas=['fin'])
        """
        conn = self._get_conn()
        conditions = []
        params: list = []

        if pattern_type:
            conditions.append("pattern_type = ?")
            params.append(pattern_type)

        if include_personas:
            placeholders = ",".join("?" for _ in include_personas)
            conditions.append(f"source_mode IN ({placeholders})")
            params.extend(include_personas)

        if project_id:
            conditions.append("project_id = ?")
            params.append(project_id)

        where = ""
        if conditions:
            where = " WHERE " + " AND ".join(conditions)

        params.append(limit)
        rows = conn.execute(
            f"SELECT pattern_type, pattern_value, count, source_mode, updated_at, source_instance, project_id FROM patterns{where} ORDER BY count DESC LIMIT ?",
            params
        ).fetchall()

        return [
            {
                "pattern_type": row["pattern_type"],
                "pattern_value": row["pattern_value"],
                "count": row["count"],
                "source_mode": row["source_mode"],
                "updated_at": row["updated_at"],
                "source_instance": row["source_instance"],
                "project_id": row["project_id"],
            }
            for row in rows
        ]

    def get_all_patterns(self, limit: int = 200) -> List[Dict[str, Any]]:
        """Alias for get_patterns() — returns all patterns (used by vault promoter)."""
        return self.get_patterns(pattern_type=None, limit=limit)

    # ── Feedback ─────────────────────────────────────────────────────────

    def record_feedback(self, feedback_type: str, content: str, source_mode: str,
                        source_instance: Optional[str] = None,
                        project_id: Optional[str] = None) -> int:
        """
        Record user feedback.

        Args:
            feedback_type: Type of feedback ('correction', 'praise', 'complaint')
            content: The feedback content
            source_mode: Which mode received this
            source_instance: Which agent instance received this
            project_id: Which project context

        Returns:
            ID of the stored feedback

        Example:
            memory.record_feedback('correction', 'AAPL is not APPL', 'chat')
            memory.record_feedback('praise', 'Great analysis!', 'fin', source_instance='quant-1')
        """
        conn = self._get_conn()
        cursor = conn.execute(
            "INSERT INTO feedback (feedback_type, content, source_mode, created_at, source_instance, project_id) VALUES (?, ?, ?, ?, ?, ?)",
            (feedback_type, content, source_mode, self._now(), source_instance, project_id)
        )
        conn.commit()
        return cursor.lastrowid

    def recall_feedback(
        self,
        feedback_type: Optional[str] = None,
        project_id: Optional[str] = None,
        max_age_hours: Optional[float] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        Recall feedback with filters. Richer than get_recent_feedback —
        supports type/project/age filtering and returns the Phase 4
        cross-persona fields (source_instance, project_id).

        Added in Phase 4.B (2026-04-12) to support the fleet worker's
        fail_fast check on task entry.

        Args:
            feedback_type: Optional filter (e.g. "fail_fast", "correction").
            project_id: Optional filter to limit results to one project.
            max_age_hours: If provided, drop entries older than this many
                hours (compared against ISO created_at timestamps).
            limit: Max rows.

        Returns:
            List of feedback dicts newest first, each with id,
            feedback_type, content, source_mode, source_instance,
            project_id, created_at.
        """
        conn = self._get_conn()
        conditions = []
        params: list = []
        if feedback_type:
            conditions.append("feedback_type = ?")
            params.append(feedback_type)
        if project_id:
            conditions.append("project_id = ?")
            params.append(project_id)
        if max_age_hours is not None and max_age_hours > 0:
            from datetime import datetime, timedelta, timezone
            cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
            conditions.append("created_at >= ?")
            params.append(cutoff.isoformat())

        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
        params.append(limit)
        rows = conn.execute(
            "SELECT id, feedback_type, content, source_mode, source_instance, "
            f"project_id, created_at FROM feedback{where} "
            "ORDER BY created_at DESC LIMIT ?",
            params,
        ).fetchall()
        return [
            {
                "id": row["id"],
                "feedback_type": row["feedback_type"],
                "content": row["content"],
                "source_mode": row["source_mode"],
                "source_instance": row["source_instance"],
                "project_id": row["project_id"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

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

    # ── Cross-persona context ──────────────────────────────────────────

    def get_cross_persona_context(self, current_mode: str,
                                   project_id: Optional[str] = None,
                                   max_tokens: int = 300) -> str:
        """Generate LLM context showing cross-persona knowledge with source attribution.

        Returns content wrapped in source envelopes:
            <from persona="coding" instance="coder-1">
            User prefers Python 3.12, uses pytest for testing.
            </from>

        Content from current_mode is NOT wrapped (native knowledge).
        Only cross-persona content gets envelopes.

        Args:
            current_mode: The requesting persona's mode
            project_id: Optional project filter
            max_tokens: Approximate token budget

        Returns:
            Formatted context string with source envelopes
        """
        chars_per_token = 4
        budget = max_tokens * chars_per_token
        used = 0
        parts: List[str] = []

        conn = self._get_conn()

        # Collect facts grouped by source_mode
        query = "SELECT category, fact, source_mode, source_instance FROM facts"
        params: list = []
        if project_id:
            query += " WHERE project_id = ?"
            params.append(project_id)
        query += " ORDER BY created_at DESC LIMIT 50"

        rows = conn.execute(query, params).fetchall()

        # Group by (source_mode, source_instance)
        groups: Dict[tuple, List[str]] = {}
        for row in rows:
            key = (row["source_mode"] or "unknown", row["source_instance"])
            if key not in groups:
                groups[key] = []
            groups[key].append(f"{row['category']}: {row['fact']}")

        # Native knowledge (from current_mode) — no envelope
        for key, facts in groups.items():
            mode, instance = key
            if mode == current_mode:
                for fact in facts[:3]:
                    if used + len(fact) < budget:
                        parts.append(fact)
                        used += len(fact)

        # Cross-persona knowledge — with envelopes
        for key, facts in groups.items():
            mode, instance = key
            if mode != current_mode:
                inst_attr = f' instance="{instance}"' if instance else ""
                envelope_open = f'<from persona="{mode}"{inst_attr}>'
                envelope_close = "</from>"
                inner_lines = []
                for fact in facts[:3]:
                    if used + len(fact) + len(envelope_open) + len(envelope_close) < budget:
                        inner_lines.append(fact)
                        used += len(fact)
                if inner_lines:
                    parts.append(envelope_open)
                    parts.extend(inner_lines)
                    parts.append(envelope_close)

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
