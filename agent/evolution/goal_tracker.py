"""NeoMind Goal Tracker — Autonomous Self-Improvement Goals

The agent sets its own improvement goals and tracks progress:
1. Auto-generated goals from reflections and metrics
2. Manual goals from user directives
3. Progress tracked via measurable metrics
4. Goals auto-close on achievement or auto-expire after deadline

This is what makes NeoMind truly self-directed rather than just reactive.
Without goals, evolution is random drift. With goals, it's deliberate growth.

Goal types:
  - METRIC: Achieve a specific metric target (e.g., "reduce retry rate to <10%")
  - CAPABILITY: Acquire a new capability (e.g., "learn to handle PDF parsing")
  - HABIT: Establish a behavioral pattern (e.g., "always ask clarifying questions")
  - EXPERIMENT: Test a hypothesis (e.g., "try deeper reasoning for coding tasks")

No external dependencies — stdlib only.
"""

import json
import sqlite3
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional, Any

logger = logging.getLogger(__name__)

DB_PATH = Path("/data/neomind/db/goals.db")

# Auto-expire goals after this many days without progress
GOAL_EXPIRY_DAYS = 30
MAX_ACTIVE_GOALS = 10


class GoalTracker:
    """Autonomous self-improvement goal management."""

    SCHEMA = """
        CREATE TABLE IF NOT EXISTS goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            goal_type TEXT NOT NULL,      -- METRIC | CAPABILITY | HABIT | EXPERIMENT
            mode TEXT NOT NULL,           -- chat | coding | fin | all
            status TEXT DEFAULT 'ACTIVE', -- ACTIVE | ACHIEVED | FAILED | EXPIRED | PAUSED
            target_metric TEXT,          -- JSON: what to measure
            current_value REAL DEFAULT 0,
            target_value REAL DEFAULT 1.0,
            priority REAL DEFAULT 0.5,   -- 0.0-1.0
            source TEXT,                 -- reflection | user | metric_analysis | auto
            created_at TEXT NOT NULL,
            deadline TEXT,               -- optional deadline
            achieved_at TEXT,
            last_progress_at TEXT,
            progress_log TEXT DEFAULT '[]' -- JSON array of progress entries
        );

        CREATE INDEX IF NOT EXISTS idx_goals_status ON goals(status);
        CREATE INDEX IF NOT EXISTS idx_goals_mode ON goals(mode);
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(self.SCHEMA)
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Failed to init goals DB: {e}")

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    # ── Create Goals ───────────────────────────────────────

    def set_goal(self, title: str, mode: str, goal_type: str,
                 description: str = "", target_value: float = 1.0,
                 target_metric: Optional[Dict] = None,
                 priority: float = 0.5,
                 deadline_days: Optional[int] = None,
                 source: str = "auto") -> Optional[int]:
        """Set a new improvement goal.

        Args:
            title: Short goal title (e.g., "Reduce coding retry rate")
            mode: Personality mode this applies to
            goal_type: METRIC | CAPABILITY | HABIT | EXPERIMENT
            description: Detailed description
            target_value: Numeric target (1.0 = 100% for binary goals)
            target_metric: What to measure (JSON dict)
            priority: 0.0-1.0
            deadline_days: Days until deadline (None = no deadline)
            source: What generated this goal

        Returns:
            Goal ID, or None if limit reached
        """
        # Check active goal limit
        active = self._count_active(mode)
        if active >= MAX_ACTIVE_GOALS:
            logger.info(f"Active goal limit reached for {mode} ({active})")
            return None

        # Dedup
        if self._find_similar_goal(title, mode):
            logger.debug(f"Similar goal already exists: {title}")
            return None

        now = datetime.now(timezone.utc)
        deadline = None
        if deadline_days:
            deadline = (now + timedelta(days=deadline_days)).isoformat()

        try:
            conn = self._conn()
            cursor = conn.execute(
                """INSERT INTO goals
                   (title, description, goal_type, mode, target_metric,
                    target_value, priority, source, created_at, deadline)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (title, description, goal_type, mode,
                 json.dumps(target_metric or {}),
                 target_value, priority, source,
                 now.isoformat(), deadline)
            )
            goal_id = cursor.lastrowid
            conn.commit()
            conn.close()
            logger.info(f"New goal #{goal_id}: {title} ({goal_type}, {mode})")
            return goal_id
        except Exception as e:
            logger.error(f"Failed to set goal: {e}")
            return None

    def set_metric_goal(self, mode: str, metric_name: str,
                         target: float, current: float = 0,
                         deadline_days: int = 14) -> Optional[int]:
        """Convenience: set a metric-based goal."""
        return self.set_goal(
            title=f"Improve {metric_name} to {target}",
            mode=mode, goal_type="METRIC",
            description=f"Current: {current}, Target: {target}",
            target_value=target,
            target_metric={"name": metric_name, "baseline": current},
            deadline_days=deadline_days,
            source="metric_analysis",
        )

    def set_experiment_goal(self, mode: str, hypothesis: str,
                             test_plan: str = "",
                             deadline_days: int = 7) -> Optional[int]:
        """Convenience: set an experiment goal from a hypothesis."""
        return self.set_goal(
            title=f"Test: {hypothesis[:80]}",
            mode=mode, goal_type="EXPERIMENT",
            description=f"Hypothesis: {hypothesis}\nPlan: {test_plan}",
            target_value=1.0,
            deadline_days=deadline_days,
            source="reflection",
        )

    # ── Track Progress ─────────────────────────────────────

    def record_progress(self, goal_id: int, value: float,
                         note: str = "") -> bool:
        """Record progress toward a goal.

        For METRIC goals: value is the current metric value
        For binary goals: value is 0.0-1.0 representing % complete
        """
        try:
            now = datetime.now(timezone.utc).isoformat()
            conn = self._conn()
            row = conn.execute("SELECT * FROM goals WHERE id = ?", (goal_id,)).fetchone()
            if not row or row["status"] != "ACTIVE":
                conn.close()
                return False

            # Append to progress log
            progress_log = json.loads(row["progress_log"] or "[]")
            progress_log.append({
                "ts": now, "value": value, "note": note
            })
            # Keep last 50 entries
            progress_log = progress_log[-50:]

            conn.execute(
                """UPDATE goals SET
                   current_value = ?,
                   last_progress_at = ?,
                   progress_log = ?
                   WHERE id = ?""",
                (value, now, json.dumps(progress_log), goal_id)
            )

            # Check if goal is achieved
            if value >= row["target_value"]:
                conn.execute(
                    "UPDATE goals SET status = 'ACHIEVED', achieved_at = ? WHERE id = ?",
                    (now, goal_id)
                )
                logger.info(f"Goal #{goal_id} ACHIEVED: {row['title']}")

            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Failed to record progress: {e}")
            return False

    # ── Auto-Generate Goals ────────────────────────────────

    def auto_generate_goals(self, mode: str, metrics: Dict[str, float],
                             reflection_data: Optional[Dict] = None) -> List[int]:
        """Automatically generate improvement goals from metrics and reflections.

        Called by scheduler during daily/weekly cycles.
        """
        new_goals = []

        # From metrics: set goals for underperforming areas
        if metrics.get("retry_rate", 0) > 0.2:
            gid = self.set_metric_goal(
                mode, "retry_rate", target=0.1,
                current=metrics["retry_rate"], deadline_days=14
            )
            if gid:
                new_goals.append(gid)

        if metrics.get("user_satisfaction", 1) < 0.7:
            gid = self.set_metric_goal(
                mode, "user_satisfaction", target=0.8,
                current=metrics["user_satisfaction"], deadline_days=14
            )
            if gid:
                new_goals.append(gid)

        if metrics.get("task_completion", 1) < 0.8:
            gid = self.set_metric_goal(
                mode, "task_completion", target=0.9,
                current=metrics["task_completion"], deadline_days=14
            )
            if gid:
                new_goals.append(gid)

        if metrics.get("error_rate", 0) > 0.1:
            gid = self.set_metric_goal(
                mode, "error_rate", target=0.05,
                current=metrics["error_rate"], deadline_days=14
            )
            if gid:
                new_goals.append(gid)

        # From reflection hypotheses: create experiment goals
        if reflection_data:
            for h in reflection_data.get("hypotheses_to_test", [])[:2]:
                gid = self.set_experiment_goal(
                    mode, h.get("hypothesis", ""),
                    h.get("test_plan", ""),
                    deadline_days=7
                )
                if gid:
                    new_goals.append(gid)

        return new_goals

    # ── Maintenance ────────────────────────────────────────

    def expire_stale_goals(self) -> int:
        """Expire goals past deadline or without progress for 30 days."""
        try:
            now = datetime.now(timezone.utc)
            conn = self._conn()
            expired = 0

            rows = conn.execute(
                "SELECT * FROM goals WHERE status = 'ACTIVE'"
            ).fetchall()

            for row in rows:
                should_expire = False

                # Past deadline
                if row["deadline"]:
                    deadline = datetime.fromisoformat(row["deadline"])
                    if now > deadline:
                        should_expire = True

                # No progress for 30 days
                last_progress = row["last_progress_at"] or row["created_at"]
                age = (now - datetime.fromisoformat(last_progress)).days
                if age > GOAL_EXPIRY_DAYS:
                    should_expire = True

                if should_expire:
                    conn.execute(
                        "UPDATE goals SET status = 'EXPIRED' WHERE id = ?",
                        (row["id"],)
                    )
                    expired += 1

            conn.commit()
            conn.close()
            if expired:
                logger.info(f"Expired {expired} stale goals")
            return expired
        except Exception as e:
            logger.error(f"Goal expiry failed: {e}")
            return 0

    # ── Query ──────────────────────────────────────────────

    def get_active_goals(self, mode: Optional[str] = None) -> List[Dict]:
        """Get all active goals, optionally filtered by mode."""
        try:
            conn = self._conn()
            if mode:
                rows = conn.execute(
                    "SELECT * FROM goals WHERE status = 'ACTIVE' AND mode IN (?, 'all') ORDER BY priority DESC",
                    (mode,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM goals WHERE status = 'ACTIVE' ORDER BY priority DESC"
                ).fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception:
            return []

    def get_goal_summary(self, mode: Optional[str] = None) -> str:
        """Human-readable summary of current goals (for system prompt)."""
        goals = self.get_active_goals(mode)
        if not goals:
            return ""

        lines = ["[NeoMind Active Improvement Goals]"]
        for g in goals[:5]:
            progress = g["current_value"] / max(0.001, g["target_value"]) * 100
            lines.append(
                f"- [{g['goal_type']}] {g['title']} "
                f"({progress:.0f}% → target {g['target_value']})"
            )
        return "\n".join(lines)

    def get_stats(self) -> Dict[str, Any]:
        """Return goal statistics for dashboard."""
        try:
            conn = self._conn()
            total = conn.execute("SELECT COUNT(*) FROM goals").fetchone()[0]
            by_status = {}
            for row in conn.execute("SELECT status, COUNT(*) as c FROM goals GROUP BY status"):
                by_status[row["status"]] = row["c"]
            achieved = by_status.get("ACHIEVED", 0)
            conn.close()
            return {
                "total": total,
                "by_status": by_status,
                "achievement_rate": achieved / max(1, total),
            }
        except Exception:
            return {"total": 0}

    # ── Internal ───────────────────────────────────────────

    def _count_active(self, mode: str) -> int:
        try:
            conn = self._conn()
            count = conn.execute(
                "SELECT COUNT(*) FROM goals WHERE status = 'ACTIVE' AND mode IN (?, 'all')",
                (mode,)
            ).fetchone()[0]
            conn.close()
            return count
        except Exception:
            return 0

    def _find_similar_goal(self, title: str, mode: str) -> bool:
        try:
            conn = self._conn()
            row = conn.execute(
                "SELECT id FROM goals WHERE title = ? AND mode = ? AND status = 'ACTIVE'",
                (title, mode)
            ).fetchone()
            conn.close()
            return row is not None
        except Exception:
            return False
