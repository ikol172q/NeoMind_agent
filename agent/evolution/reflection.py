"""NeoMind Reflection Engine — Post-Task Self-Evaluation

After completing a task (or failing), the agent reflects on:
1. What went well?
2. What could be improved?
3. What hypothesis should be tested next?

This is the cognitive loop that drives deliberate improvement, not just
passive metric collection. Inspired by Reflexion (verbal reinforcement
learning) and Self-Refine, but adapted for NeoMind's multi-personality
architecture.

Reflection triggers:
- After every conversation (lightweight: did user seem satisfied?)
- After errors (medium: what went wrong, how to prevent?)
- Weekly (deep: patterns across conversations, strategic adjustments)

Outputs feed into:
- LearningsEngine (new INSIGHT/ERROR learnings)
- SkillForge (new skills from successful patterns)
- GoalTracker (new improvement goals)
- PromptTuner (tuning signals)

No external dependencies — stdlib only.
"""

import json
import logging
import sqlite3
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any, Tuple

logger = logging.getLogger(__name__)

DB_PATH = Path("/data/neomind/db/reflections.db")


class ReflectionEngine:
    """Post-task self-evaluation and improvement hypothesis generation."""

    SCHEMA = """
        CREATE TABLE IF NOT EXISTS reflections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mode TEXT NOT NULL,
            depth TEXT NOT NULL,         -- quick | medium | deep
            trigger TEXT NOT NULL,       -- conversation_end | error | weekly | manual
            went_well TEXT,             -- JSON list
            to_improve TEXT,            -- JSON list
            hypotheses TEXT,            -- JSON list of improvement hypotheses
            actions_taken TEXT,         -- JSON list of actions actually taken
            conversation_summary TEXT,  -- brief summary of what happened
            user_satisfaction REAL,     -- 0.0-1.0 estimated
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS improvement_hypotheses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hypothesis TEXT NOT NULL,
            category TEXT NOT NULL,      -- response_quality | speed | accuracy | style
            status TEXT DEFAULT 'PROPOSED', -- PROPOSED | TESTING | CONFIRMED | REJECTED
            evidence_for INTEGER DEFAULT 0,
            evidence_against INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            resolved_at TEXT
        );
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
            logger.error(f"Failed to init reflections DB: {e}")

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    # ── PreFlect: Prospective Reflection (BEFORE task) ─────

    def pre_reflect(self, task_description: str, mode: str) -> str:
        """PreFlect: Pre-execution prospective reflection.

        Based on PreFlect (2026) — 11-17% improvement over retrospective-only.
        Generates pre-task reminders by analyzing past errors for similar tasks.

        Args:
            task_description: What the user is asking for
            mode: Agent mode (chat/coding/fin)

        Returns:
            Pre-reflection text to inject before task execution.
            Empty string if no relevant history.
        """
        try:
            conn = self._conn()

            # Retrieve recent error reflections for this mode
            recent_errors = conn.execute(
                """SELECT to_improve, hypotheses FROM reflections
                WHERE mode = ? AND depth IN ('medium', 'deep')
                AND trigger = 'error'
                ORDER BY created_at DESC LIMIT 10""",
                (mode,),
            ).fetchall()

            # Retrieve active hypotheses
            active_hyp = conn.execute(
                """SELECT hypothesis, category FROM improvement_hypotheses
                WHERE status IN ('PROPOSED', 'TESTING')
                ORDER BY created_at DESC LIMIT 5""",
            ).fetchall()

            conn.close()

            if not recent_errors and not active_hyp:
                return ""

            # Build pre-reflection prompt
            reminders = []

            # Extract common error patterns
            error_patterns = {}
            for row in recent_errors:
                try:
                    improvements = json.loads(row["to_improve"] or "[]")
                    for imp in improvements:
                        key = imp[:60].lower()
                        error_patterns[key] = error_patterns.get(key, 0) + 1
                except (json.JSONDecodeError, TypeError):
                    pass

            # Top 3 most common errors
            sorted_errors = sorted(error_patterns.items(), key=lambda x: -x[1])
            for pattern, count in sorted_errors[:3]:
                if count >= 2:
                    reminders.append(f"⚠️ Common issue ({count}x): {pattern}")
                else:
                    reminders.append(f"⚠️ Past issue: {pattern}")

            # Active hypotheses as reminders
            for h in active_hyp[:3]:
                reminders.append(f"💡 Hypothesis: {h['hypothesis']}")

            if not reminders:
                return ""

            return (
                "[PreFlect — Pre-execution Reminders]\n"
                + "\n".join(reminders)
                + "\n(Apply these lessons before starting the task)"
            )

        except Exception as e:
            logger.debug(f"PreFlect failed: {e}")
            return ""

    # ── Quick Reflection (after every conversation) ────────

    def reflect_quick(self, mode: str, conversation_summary: str,
                      user_satisfaction: float = 0.5,
                      error_occurred: bool = False) -> Dict[str, Any]:
        """Lightweight post-conversation reflection.

        Doesn't use LLM — just heuristic signals.
        ~0 cost, <10ms.
        """
        went_well = []
        to_improve = []
        hypotheses = []

        # Heuristic analysis
        if user_satisfaction >= 0.8:
            went_well.append("User appeared satisfied")
        elif user_satisfaction <= 0.3:
            to_improve.append("Low user satisfaction detected")
            hypotheses.append({
                "hypothesis": f"Response quality in {mode} mode needs improvement",
                "category": "response_quality",
            })

        if error_occurred:
            to_improve.append("Error occurred during task")
            hypotheses.append({
                "hypothesis": "Error handling needs strengthening",
                "category": "accuracy",
            })

        # Detect if response was too long/short (from conversation length)
        summary_len = len(conversation_summary)
        if summary_len > 5000:
            hypotheses.append({
                "hypothesis": "Responses may be too verbose — consider concise style",
                "category": "style",
            })

        reflection = {
            "went_well": went_well,
            "to_improve": to_improve,
            "hypotheses": hypotheses,
            "user_satisfaction": user_satisfaction,
        }

        self._store_reflection(mode, "quick", "conversation_end",
                               reflection, conversation_summary,
                               user_satisfaction)

        # Store new hypotheses
        for h in hypotheses:
            self._propose_hypothesis(h["hypothesis"], h["category"])

        return reflection

    # ── Medium Reflection (after errors) ───────────────────

    def reflect_on_error(self, mode: str, error_type: str,
                          error_msg: str, context: str = "") -> Dict[str, Any]:
        """Reflect on an error — what went wrong and how to prevent it.

        Returns structured reflection including fix suggestions.
        """
        to_improve = [f"Error: {error_type} — {error_msg[:200]}"]
        hypotheses = []

        # Pattern-match common error categories
        error_lower = error_msg.lower()

        if "timeout" in error_lower or "timed out" in error_lower:
            hypotheses.append({
                "hypothesis": "API calls may need longer timeouts or retry logic",
                "category": "accuracy",
            })
            to_improve.append("Add retry with exponential backoff")

        elif "rate limit" in error_lower or "429" in error_msg:
            hypotheses.append({
                "hypothesis": "Need better rate limiting / request batching",
                "category": "speed",
            })
            to_improve.append("Implement request throttling")

        elif "memory" in error_lower or "oom" in error_lower:
            hypotheses.append({
                "hypothesis": "Memory usage is too high — need optimization",
                "category": "accuracy",
            })
            to_improve.append("Profile memory usage, reduce context window")

        elif "key" in error_lower and ("invalid" in error_lower or "expired" in error_lower):
            hypotheses.append({
                "hypothesis": "API key management needs improvement",
                "category": "accuracy",
            })

        else:
            hypotheses.append({
                "hypothesis": f"New error type '{error_type}' needs a handler",
                "category": "accuracy",
            })

        reflection = {
            "went_well": [],
            "to_improve": to_improve,
            "hypotheses": hypotheses,
            "error_type": error_type,
            "error_msg": error_msg[:500],
        }

        self._store_reflection(mode, "medium", "error",
                               reflection, context, 0.0)

        for h in hypotheses:
            self._propose_hypothesis(h["hypothesis"], h["category"])

        return reflection

    # ── Deep Reflection (weekly) ───────────────────────────

    def reflect_deep_prompt(self, mode: str) -> str:
        """Generate a prompt for LLM to do deep weekly reflection.

        Feeds in recent reflections, learnings, and metrics.
        The caller sends this to LLM and parses the result.
        """
        # Gather recent data
        recent = self._get_recent_reflections(mode, days=7)
        hypotheses = self._get_active_hypotheses()

        summary = f"Mode: {mode}\n"
        summary += f"Reflections this week: {len(recent)}\n"

        if recent:
            satisfactions = [r.get("user_satisfaction", 0.5) for r in recent]
            avg_sat = sum(satisfactions) / len(satisfactions)
            summary += f"Avg satisfaction: {avg_sat:.2f}\n"

            all_issues = []
            for r in recent:
                all_issues.extend(r.get("to_improve", []))
            if all_issues:
                summary += f"Issues this week: {', '.join(all_issues[:10])}\n"

        if hypotheses:
            summary += f"\nActive hypotheses:\n"
            for h in hypotheses[:5]:
                summary += f"  - [{h['status']}] {h['hypothesis']} (for: {h['evidence_for']}, against: {h['evidence_against']})\n"

        return f"""Perform a deep weekly reflection for NeoMind {mode} mode.

Data:
{summary}

Output a JSON reflection:
{{
  "patterns_noticed": ["pattern 1", "pattern 2"],
  "strategic_adjustments": ["adjustment 1", "adjustment 2"],
  "hypotheses_to_test": [
    {{"hypothesis": "...", "category": "response_quality|speed|accuracy|style", "test_plan": "..."}}
  ],
  "skills_to_develop": ["skill 1", "skill 2"],
  "overall_health": 0.0-1.0
}}

Be specific and actionable. JSON only:"""

    def ingest_deep_reflection(self, llm_output: str, mode: str) -> Dict:
        """Parse LLM deep reflection output and store results."""
        try:
            text = llm_output.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1]
            if text.endswith("```"):
                text = text.rsplit("\n", 1)[0]

            data = json.loads(text)

            # Store hypotheses
            for h in data.get("hypotheses_to_test", []):
                self._propose_hypothesis(
                    h.get("hypothesis", ""),
                    h.get("category", "response_quality")
                )

            # Store as reflection
            self._store_reflection(
                mode, "deep", "weekly",
                {
                    "went_well": data.get("patterns_noticed", []),
                    "to_improve": data.get("strategic_adjustments", []),
                    "hypotheses": data.get("hypotheses_to_test", []),
                    "skills_to_develop": data.get("skills_to_develop", []),
                    "overall_health": data.get("overall_health", 0.5),
                },
                json.dumps(data, ensure_ascii=False)[:2000],
                data.get("overall_health", 0.5)
            )

            return data
        except (json.JSONDecodeError, TypeError) as e:
            logger.error(f"Failed to parse deep reflection: {e}")
            return {}

    # ── Hypothesis Management ──────────────────────────────

    def update_hypothesis(self, hypothesis_id: int, confirmed: bool):
        """Add evidence for or against a hypothesis."""
        try:
            conn = self._conn()
            if confirmed:
                conn.execute(
                    "UPDATE improvement_hypotheses SET evidence_for = evidence_for + 1 WHERE id = ?",
                    (hypothesis_id,)
                )
            else:
                conn.execute(
                    "UPDATE improvement_hypotheses SET evidence_against = evidence_against + 1 WHERE id = ?",
                    (hypothesis_id,)
                )

            # Auto-resolve if enough evidence
            row = conn.execute(
                "SELECT * FROM improvement_hypotheses WHERE id = ?",
                (hypothesis_id,)
            ).fetchone()
            if row:
                total = row["evidence_for"] + row["evidence_against"]
                if total >= 5:
                    status = "CONFIRMED" if row["evidence_for"] > row["evidence_against"] else "REJECTED"
                    conn.execute(
                        "UPDATE improvement_hypotheses SET status = ?, resolved_at = ? WHERE id = ?",
                        (status, datetime.now(timezone.utc).isoformat(), hypothesis_id)
                    )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Failed to update hypothesis: {e}")

    def get_active_hypotheses(self) -> List[Dict]:
        """Get hypotheses currently being tested."""
        return self._get_active_hypotheses()

    # ── Statistics ─────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        """Return reflection statistics for dashboard."""
        try:
            conn = self._conn()
            total_reflections = conn.execute(
                "SELECT COUNT(*) FROM reflections"
            ).fetchone()[0]
            total_hypotheses = conn.execute(
                "SELECT COUNT(*) FROM improvement_hypotheses"
            ).fetchone()[0]
            confirmed = conn.execute(
                "SELECT COUNT(*) FROM improvement_hypotheses WHERE status = 'CONFIRMED'"
            ).fetchone()[0]

            # Average satisfaction trend (last 7 days)
            week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
            rows = conn.execute(
                "SELECT user_satisfaction FROM reflections WHERE created_at > ?",
                (week_ago,)
            ).fetchall()
            avg_sat = 0
            if rows:
                sats = [r["user_satisfaction"] for r in rows if r["user_satisfaction"]]
                avg_sat = sum(sats) / len(sats) if sats else 0

            conn.close()
            return {
                "total_reflections": total_reflections,
                "total_hypotheses": total_hypotheses,
                "confirmed_hypotheses": confirmed,
                "weekly_avg_satisfaction": round(avg_sat, 3),
            }
        except Exception:
            return {}

    # ── Internal ───────────────────────────────────────────

    def _store_reflection(self, mode: str, depth: str, trigger: str,
                           reflection: Dict, summary: str,
                           satisfaction: float):
        try:
            conn = self._conn()
            conn.execute(
                """INSERT INTO reflections
                   (mode, depth, trigger, went_well, to_improve,
                    hypotheses, conversation_summary, user_satisfaction, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (mode, depth, trigger,
                 json.dumps(reflection.get("went_well", []), ensure_ascii=False),
                 json.dumps(reflection.get("to_improve", []), ensure_ascii=False),
                 json.dumps(reflection.get("hypotheses", []), ensure_ascii=False),
                 summary[:2000] if summary else "",
                 satisfaction,
                 datetime.now(timezone.utc).isoformat())
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Failed to store reflection: {e}")

    def _propose_hypothesis(self, hypothesis: str, category: str):
        if not hypothesis:
            return
        try:
            conn = self._conn()
            # Dedup
            existing = conn.execute(
                "SELECT id FROM improvement_hypotheses WHERE hypothesis = ? AND status IN ('PROPOSED', 'TESTING')",
                (hypothesis,)
            ).fetchone()
            if not existing:
                conn.execute(
                    "INSERT INTO improvement_hypotheses (hypothesis, category, created_at) VALUES (?, ?, ?)",
                    (hypothesis, category, datetime.now(timezone.utc).isoformat())
                )
            conn.commit()
            conn.close()
        except Exception:
            pass

    def _get_active_hypotheses(self) -> List[Dict]:
        try:
            conn = self._conn()
            rows = conn.execute(
                "SELECT * FROM improvement_hypotheses WHERE status IN ('PROPOSED', 'TESTING') "
                "ORDER BY created_at DESC LIMIT 10"
            ).fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception:
            return []

    def _get_recent_reflections(self, mode: str, days: int = 7) -> List[Dict]:
        try:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
            conn = self._conn()
            rows = conn.execute(
                "SELECT * FROM reflections WHERE mode = ? AND created_at > ? ORDER BY created_at DESC",
                (mode, cutoff)
            ).fetchall()
            conn.close()
            results = []
            for r in rows:
                entry = dict(r)
                for field in ("went_well", "to_improve", "hypotheses"):
                    try:
                        entry[field] = json.loads(entry.get(field, "[]"))
                    except Exception:
                        entry[field] = []
                results.append(entry)
            return results
        except Exception:
            return []
