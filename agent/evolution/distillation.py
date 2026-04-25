"""NeoMind Model Distillation — Cheap Model Knowledge Transfer

Implements knowledge distillation from expensive to cheap models:
1. When deepseek-v4-pro produces high-quality output, save as exemplar
2. When similar task arrives, try deepseek-v4-flash first with exemplar as context
3. If cheap model succeeds (quality above threshold), use it → save cost
4. If cheap model fails, fall back to expensive model

This creates a "fallback chain": cheap+exemplar → expensive → error

Expected impact: 80-90% quality at 10-30% cost for recurring task types.

Research: Round 3 — model distillation for agent cost optimization.
No external dependencies — stdlib only.
"""

import json
import hashlib
import logging
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger(__name__)

DB_PATH = Path("/data/neomind/db/cost_tracking.db")

# Quality threshold: below this, cheap model answer is rejected
QUALITY_THRESHOLD = 0.7

# Maximum exemplars to store per task type
MAX_EXEMPLARS_PER_TYPE = 20

# Maximum age for exemplars (days)
EXEMPLAR_MAX_AGE_DAYS = 90


class DistillationExemplar:
    """A high-quality response from an expensive model, stored for distillation."""

    def __init__(self, task_type: str, prompt_summary: str,
                 response: str, model: str, quality_score: float,
                 mode: str = "all"):
        self.task_type = task_type
        self.prompt_summary = prompt_summary
        self.response = response
        self.model = model
        self.quality_score = quality_score
        self.mode = mode


class DistillationEngine:
    """Manages knowledge distillation from expensive to cheap models.

    Usage:
        engine = DistillationEngine()

        # After getting a good answer from expensive model
        engine.store_exemplar(
            task_type="financial_analysis",
            prompt_summary="Analyze AAPL earnings impact",
            response="Based on the earnings report...",
            model="deepseek-v4-pro",
            quality_score=0.92,
        )

        # Before calling expensive model, check for distillation
        exemplar = engine.get_best_exemplar("financial_analysis", "Analyze MSFT earnings")
        if exemplar:
            # Try cheap model with exemplar context
            cheap_prompt = engine.build_distilled_prompt(
                original_prompt="Analyze MSFT earnings impact",
                exemplar=exemplar,
            )
            # If cheap model output quality >= threshold, use it

        # Track distillation success rate
        engine.record_attempt(task_type, model_used, quality, cost)
    """

    SCHEMA = """
        CREATE TABLE IF NOT EXISTS distillation_exemplars (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_type TEXT NOT NULL,
            prompt_summary TEXT NOT NULL,
            prompt_hash TEXT NOT NULL,
            response TEXT NOT NULL,
            model TEXT NOT NULL,
            quality_score REAL NOT NULL,
            mode TEXT DEFAULT 'all',
            use_count INTEGER DEFAULT 0,
            success_count INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            last_used_at TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_exemplar_type ON distillation_exemplars(task_type);
        CREATE INDEX IF NOT EXISTS idx_exemplar_quality ON distillation_exemplars(quality_score DESC);

        CREATE TABLE IF NOT EXISTS distillation_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_type TEXT NOT NULL,
            model_used TEXT NOT NULL,
            was_distilled INTEGER DEFAULT 0,
            quality_score REAL,
            cost_usd REAL DEFAULT 0,
            tokens_used INTEGER DEFAULT 0,
            exemplar_id INTEGER,
            ts TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_attempt_ts ON distillation_attempts(ts);
        CREATE INDEX IF NOT EXISTS idx_attempt_type ON distillation_attempts(task_type);
    """

    # Task types that benefit from distillation
    DISTILLABLE_TASKS = {
        "financial_analysis",
        "sentiment_analysis",
        "market_briefing",
        "code_review",
        "learning_extraction",
        "reflection",
        "goal_evaluation",
    }

    def __init__(self, db_path: Optional[Path] = None):
        if isinstance(db_path, str):
            db_path = Path(db_path) if db_path != ":memory:" else db_path
        self.db_path = db_path or DB_PATH
        if isinstance(self.db_path, Path):
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.executescript(self.SCHEMA)
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Failed to init distillation DB: {e}")

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    @staticmethod
    def _hash_prompt(text: str) -> str:
        """Create a hash for similarity comparison."""
        normalized = text.lower().strip()[:500]
        return hashlib.sha256(normalized.encode()).hexdigest()[:16]

    # ── Exemplar Management ─────────────────────────────

    def store_exemplar(self, task_type: str, prompt_summary: str,
                       response: str, model: str,
                       quality_score: float, mode: str = "all") -> Optional[int]:
        """Store a high-quality response as a distillation exemplar.

        Only stores if quality exceeds threshold and task type is distillable.

        Args:
            task_type: Category of task
            prompt_summary: Summary of the prompt (for matching)
            response: The high-quality response
            model: Model that generated it
            quality_score: Quality assessment (0-1)
            mode: Agent mode

        Returns:
            Exemplar ID, or None
        """
        if quality_score < QUALITY_THRESHOLD:
            return None

        if task_type not in self.DISTILLABLE_TASKS:
            logger.debug(f"Task type {task_type} not distillable")
            return None

        prompt_hash = self._hash_prompt(prompt_summary)
        now = datetime.now(timezone.utc).isoformat()

        try:
            conn = self._conn()

            # Check for existing exemplar with same hash
            existing = conn.execute(
                "SELECT id, quality_score FROM distillation_exemplars WHERE prompt_hash=?",
                (prompt_hash,)
            ).fetchone()

            if existing and existing["quality_score"] >= quality_score:
                conn.close()
                return existing["id"]  # Existing exemplar is better

            if existing:
                # Replace with better quality
                conn.execute("DELETE FROM distillation_exemplars WHERE id=?", (existing["id"],))

            cursor = conn.execute(
                """INSERT INTO distillation_exemplars
                   (task_type, prompt_summary, prompt_hash, response, model,
                    quality_score, mode, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (task_type, prompt_summary[:500], prompt_hash,
                 response[:5000], model, quality_score, mode, now)
            )
            exemplar_id = cursor.lastrowid

            # Cleanup: keep only top N per task type
            conn.execute(
                """DELETE FROM distillation_exemplars
                   WHERE task_type=? AND id NOT IN (
                       SELECT id FROM distillation_exemplars
                       WHERE task_type=?
                       ORDER BY quality_score DESC
                       LIMIT ?
                   )""",
                (task_type, task_type, MAX_EXEMPLARS_PER_TYPE)
            )

            conn.commit()
            conn.close()
            logger.info(
                f"Stored exemplar #{exemplar_id}: {task_type} "
                f"(quality={quality_score:.2f}, model={model})"
            )
            return exemplar_id
        except Exception as e:
            logger.error(f"Failed to store exemplar: {e}")
            return None

    def get_best_exemplar(self, task_type: str,
                           prompt: Optional[str] = None) -> Optional[Dict]:
        """Get the best exemplar for a task type.

        If prompt is provided, tries to find a matching exemplar first.
        Falls back to highest quality exemplar for the task type.

        Args:
            task_type: Task category
            prompt: Optional current prompt for similarity matching

        Returns:
            Exemplar dict, or None
        """
        try:
            conn = self._conn()

            # Try exact match first
            if prompt:
                prompt_hash = self._hash_prompt(prompt)
                row = conn.execute(
                    "SELECT * FROM distillation_exemplars WHERE prompt_hash=?",
                    (prompt_hash,)
                ).fetchone()
                if row:
                    conn.close()
                    return dict(row)

            # Fall back to best quality exemplar for this task type
            row = conn.execute(
                """SELECT * FROM distillation_exemplars
                   WHERE task_type=?
                   ORDER BY quality_score DESC, success_count DESC
                   LIMIT 1""",
                (task_type,)
            ).fetchone()

            conn.close()
            return dict(row) if row else None
        except Exception:
            return None

    def build_distilled_prompt(self, original_prompt: str,
                                exemplar: Dict) -> str:
        """Build a prompt that includes exemplar context for the cheap model.

        Wraps the exemplar as a demonstration to guide the cheap model
        toward producing similar quality output.

        Args:
            original_prompt: The original task prompt
            exemplar: The exemplar dict (from get_best_exemplar)

        Returns:
            Enhanced prompt with exemplar context
        """
        return f"""Here is an example of a high-quality response for a similar task:

--- Example ---
Task: {exemplar.get('prompt_summary', '')}
Response: {exemplar.get('response', '')[:2000]}
--- End Example ---

Now, following the same quality and structure as the example above, complete this task:

{original_prompt}"""

    # ── Attempt Tracking ─────────────────────────────────

    def record_attempt(self, task_type: str, model_used: str,
                       quality_score: float, cost_usd: float = 0,
                       tokens_used: int = 0, was_distilled: bool = False,
                       exemplar_id: Optional[int] = None) -> None:
        """Record a distillation attempt (whether it used distilled or direct).

        Args:
            task_type: Task category
            model_used: Which model was actually used
            quality_score: Quality of the output
            cost_usd: Cost of the call
            tokens_used: Tokens consumed
            was_distilled: Whether this used a distilled prompt
            exemplar_id: Which exemplar was used (if distilled)
        """
        now = datetime.now(timezone.utc).isoformat()
        try:
            conn = self._conn()
            conn.execute(
                """INSERT INTO distillation_attempts
                   (task_type, model_used, was_distilled, quality_score,
                    cost_usd, tokens_used, exemplar_id, ts)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (task_type, model_used, int(was_distilled),
                 quality_score, cost_usd, tokens_used, exemplar_id, now)
            )

            # Update exemplar use stats
            if exemplar_id and was_distilled:
                success = 1 if quality_score >= QUALITY_THRESHOLD else 0
                conn.execute(
                    """UPDATE distillation_exemplars
                       SET use_count = use_count + 1,
                           success_count = success_count + ?,
                           last_used_at = ?
                       WHERE id = ?""",
                    (success, now, exemplar_id)
                )

            conn.commit()
            conn.close()
        except Exception as e:
            logger.debug(f"Failed to record distillation attempt: {e}")

    def should_try_distillation(self, task_type: str) -> bool:
        """Decide whether to try distillation for a task.

        Based on historical success rate for this task type.
        If we don't have enough data, be optimistic and try.

        Returns:
            True if distillation is worth trying
        """
        if task_type not in self.DISTILLABLE_TASKS:
            return False

        try:
            conn = self._conn()

            # Check if we have any exemplars
            exemplar_count = conn.execute(
                "SELECT COUNT(*) FROM distillation_exemplars WHERE task_type=?",
                (task_type,)
            ).fetchone()[0]

            if exemplar_count == 0:
                conn.close()
                return False

            # Check historical success rate
            row = conn.execute(
                """SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN was_distilled=1 AND quality_score >= ? THEN 1 ELSE 0 END) as successes
                FROM distillation_attempts
                WHERE task_type=? AND was_distilled=1""",
                (QUALITY_THRESHOLD, task_type)
            ).fetchone()

            conn.close()

            if not row or row["total"] < 3:
                return True  # Not enough data, try anyway

            success_rate = row["successes"] / row["total"]
            return success_rate >= 0.5  # At least 50% success rate
        except Exception:
            return False

    # ── Analytics ──────────────────────────────────────

    def get_savings_report(self, days: int = 30) -> Dict[str, Any]:
        """Calculate cost savings from distillation.

        Returns:
            Dict with savings by task type, total savings, success rates
        """
        try:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
            conn = self._conn()

            # Get distilled vs direct stats
            rows = conn.execute(
                """SELECT
                    task_type,
                    was_distilled,
                    COUNT(*) as count,
                    AVG(quality_score) as avg_quality,
                    SUM(cost_usd) as total_cost,
                    SUM(tokens_used) as total_tokens
                FROM distillation_attempts
                WHERE ts > ?
                GROUP BY task_type, was_distilled""",
                (cutoff,)
            ).fetchall()

            conn.close()

            by_task = {}
            for row in rows:
                task = row["task_type"]
                if task not in by_task:
                    by_task[task] = {"distilled": {}, "direct": {}}

                key = "distilled" if row["was_distilled"] else "direct"
                by_task[task][key] = {
                    "count": row["count"],
                    "avg_quality": round(row["avg_quality"], 3),
                    "total_cost": round(row["total_cost"], 4),
                    "total_tokens": row["total_tokens"],
                }

            # Calculate savings
            total_saved = 0
            for task, data in by_task.items():
                if data["distilled"].get("count", 0) > 0 and data["direct"].get("count", 0) > 0:
                    distilled_cost_per = data["distilled"]["total_cost"] / data["distilled"]["count"]
                    direct_cost_per = data["direct"]["total_cost"] / data["direct"]["count"]
                    saved_per_call = direct_cost_per - distilled_cost_per
                    total_saved += saved_per_call * data["distilled"]["count"]

            return {
                "period_days": days,
                "by_task": by_task,
                "total_saved_usd": round(total_saved, 4),
                "total_exemplars": self._count_exemplars(),
            }
        except Exception as e:
            logger.error(f"Failed to generate savings report: {e}")
            return {"period_days": days, "total_saved_usd": 0}

    def _count_exemplars(self) -> int:
        try:
            conn = self._conn()
            count = conn.execute(
                "SELECT COUNT(*) FROM distillation_exemplars"
            ).fetchone()[0]
            conn.close()
            return count
        except Exception:
            return 0

    def get_stats(self) -> Dict[str, Any]:
        """Get distillation engine statistics."""
        try:
            conn = self._conn()

            exemplars = conn.execute(
                "SELECT COUNT(*) FROM distillation_exemplars"
            ).fetchone()[0]

            attempts = conn.execute(
                "SELECT COUNT(*) FROM distillation_attempts"
            ).fetchone()[0]

            distilled = conn.execute(
                "SELECT COUNT(*) FROM distillation_attempts WHERE was_distilled=1"
            ).fetchone()[0]

            avg_quality = conn.execute(
                "SELECT AVG(quality_score) FROM distillation_attempts WHERE was_distilled=1"
            ).fetchone()[0] or 0

            by_type = {}
            for row in conn.execute(
                "SELECT task_type, COUNT(*) as c FROM distillation_exemplars GROUP BY task_type"
            ):
                by_type[row["task_type"]] = row["c"]

            conn.close()

            return {
                "total_exemplars": exemplars,
                "total_attempts": attempts,
                "distilled_attempts": distilled,
                "distillation_rate": round(distilled / max(1, attempts), 3),
                "avg_distilled_quality": round(avg_quality, 3),
                "exemplars_by_type": by_type,
            }
        except Exception:
            return {"total_exemplars": 0, "total_attempts": 0}

    def cleanup_old_exemplars(self, max_age_days: int = EXEMPLAR_MAX_AGE_DAYS) -> int:
        """Remove old exemplars that haven't been used recently."""
        try:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).isoformat()
            conn = self._conn()
            result = conn.execute(
                """DELETE FROM distillation_exemplars
                   WHERE created_at < ? AND (last_used_at IS NULL OR last_used_at < ?)
                   AND use_count < 3""",
                (cutoff, cutoff)
            )
            deleted = result.rowcount
            conn.commit()
            conn.close()
            if deleted:
                logger.info(f"Cleaned {deleted} old distillation exemplars")
            return deleted
        except Exception:
            return 0


# ── Singleton ──────────────────────────────────────

_engine: Optional[DistillationEngine] = None


def get_distillation_engine() -> DistillationEngine:
    """Get or create the global DistillationEngine singleton."""
    global _engine
    if _engine is None:
        _engine = DistillationEngine()
    return _engine
