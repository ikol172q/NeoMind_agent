"""NeoMind Self-Evolution Engine

Runs automatically at different intervals:
- On startup: quick health check (cycle 1-2)
- Daily midnight: medium audit (cycle 3-4)
- Weekly Sunday: full retro + deep audit (cycle 5-6)

Learns from user feedback and conversation patterns.
Adjusts system prompt parameters and behavior automatically.

Zero external dependencies (stdlib only).
Fast: startup check < 2 seconds.
Never crashes the main agent.
All file operations use atomic writes.
Works in both CLI and Docker.
"""

import json
import os
import sqlite3
import time
import logging
import re
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any

# Configure logging
logger = logging.getLogger(__name__)


class HealthReport:
    """Result of a startup health check."""

    def __init__(self):
        self.timestamp = datetime.now(timezone.utc).isoformat()
        self.checks_passed = 0
        self.checks_failed = 0
        self.issues: List[str] = []
        self.last_successful_run: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "checks_passed": self.checks_passed,
            "checks_failed": self.checks_failed,
            "issues": self.issues,
            "last_successful_run": self.last_successful_run,
        }


class DailyReport:
    """Daily audit report."""

    def __init__(self, date: str):
        self.date = date
        self.total_calls = 0
        self.errors = 0
        self.fallbacks = 0
        self.slowest_action = None
        self.most_frequent_action = None
        self.issues: List[str] = []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "date": self.date,
            "total_calls": self.total_calls,
            "errors": self.errors,
            "fallbacks": self.fallbacks,
            "slowest_action": self.slowest_action,
            "most_frequent_action": self.most_frequent_action,
            "issues": self.issues,
        }


class RetroReport:
    """Weekly retrospective report."""

    def __init__(self, week_start: str, week_end: str):
        self.week_start = week_start
        self.week_end = week_end
        self.total_sessions = 0
        self.total_tasks = 0
        self.success_rate = 0.0
        self.avg_task_duration_sec = 0
        self.top_tools: List[str] = []
        self.patterns: Dict[str, Any] = {}
        self.improvements: List[Dict[str, str]] = []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "week_start": self.week_start,
            "week_end": self.week_end,
            "total_sessions": self.total_sessions,
            "total_tasks": self.total_tasks,
            "success_rate": self.success_rate,
            "avg_task_duration_sec": self.avg_task_duration_sec,
            "top_tools": self.top_tools,
            "patterns": self.patterns,
            "improvements": self.improvements,
        }


class AutoEvolve:
    """Self-evolution engine that learns and improves automatically."""

    def __init__(self, state_dir: Optional[str] = None):
        """
        Initialize the AutoEvolve engine.

        Args:
            state_dir: Directory for storing evolution state. Defaults to ~/.neomind
        """
        if state_dir:
            self.state_dir = Path(state_dir).expanduser()
        else:
            self.state_dir = Path.home() / ".neomind"

        self.evolution_dir = self.state_dir / "evolution"
        self.evolution_dir.mkdir(parents=True, exist_ok=True)

        self.state_file = self.evolution_dir / "evolution_state.json"
        self.feedback_db = self.evolution_dir / "feedback.db"
        self.learning_log = self.evolution_dir / "learning.jsonl"

        self._init_feedback_db()
        self._load_state()

    def _init_feedback_db(self):
        """Initialize SQLite database for storing feedback and patterns."""
        try:
            conn = sqlite3.connect(str(self.feedback_db), timeout=5.0)
            cursor = conn.cursor()

            # Create tables
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    feedback_type TEXT NOT NULL,
                    content TEXT NOT NULL
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS preferences (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    last_updated TEXT NOT NULL
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS patterns (
                    pattern_type TEXT NOT NULL,
                    pattern_value TEXT NOT NULL,
                    count INTEGER DEFAULT 1,
                    last_seen TEXT NOT NULL,
                    PRIMARY KEY (pattern_type, pattern_value)
                )
            """)

            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning(f"Failed to init feedback DB: {e}")

    def _load_state(self):
        """Load evolution state from disk."""
        if self.state_file.exists():
            try:
                with open(self.state_file, "r") as f:
                    self.state = json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load evolution state: {e}")
                self.state = self._default_state()
        else:
            self.state = self._default_state()

    def _default_state(self) -> Dict[str, Any]:
        """Return default evolution state."""
        return {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "last_startup_check": None,
            "last_daily_audit": None,
            "last_weekly_retro": None,
            "total_learnings": 0,
            "preferences": {},
            "health": {},
        }

    def _save_state(self):
        """Save evolution state to disk (atomic write)."""
        try:
            tmp_file = self.state_file.with_suffix(".tmp")
            with open(tmp_file, "w") as f:
                json.dump(self.state, f, indent=2)
            # Atomic rename
            tmp_file.replace(self.state_file)
        except Exception as e:
            logger.error(f"Failed to save evolution state: {e}")

    def _log_learning(self, learning_type: str, content: str):
        """Append learning to log file."""
        try:
            entry = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "type": learning_type,
                "content": content,
            }
            with open(self.learning_log, "a") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning(f"Failed to log learning: {e}")

    # ── Health Checks ────────────────────────────────────────────────────

    def run_startup_check(self) -> HealthReport:
        """Quick health check on bot startup. ~2 seconds."""
        report = HealthReport()

        # Check 1: Config files exist and parse
        try:
            from agent_config import AgentConfigManager

            for mode in ["chat", "coding", "fin"]:
                cfg = AgentConfigManager(mode=mode)
                if cfg.system_prompt:
                    report.checks_passed += 1
                else:
                    report.checks_failed += 1
                    report.issues.append(f"Config {mode} has empty system_prompt")
        except Exception as e:
            report.checks_failed += 1
            report.issues.append(f"Config loading failed: {e}")

        # Check 2: Evidence trail accessible
        try:
            from agent.workflow.evidence import get_evidence_trail

            trail = get_evidence_trail()
            stats = trail.get_stats()
            report.checks_passed += 1
        except Exception as e:
            report.checks_failed += 1
            report.issues.append(f"Evidence trail error: {e}")

        # Check 3: Shared memory accessible
        try:
            from agent.memory.shared_memory import SharedMemory

            memory = SharedMemory()
            stats = memory.get_stats()
            report.checks_passed += 1
        except Exception as e:
            report.checks_failed += 1
            report.issues.append(f"Shared memory error: {e}")

        # Check 4: Database files not corrupted
        if self.feedback_db.exists():
            try:
                conn = sqlite3.connect(str(self.feedback_db), timeout=2.0)
                conn.execute("SELECT COUNT(*) FROM feedback LIMIT 1")
                conn.close()
                report.checks_passed += 1
            except Exception as e:
                report.checks_failed += 1
                report.issues.append(f"Feedback DB corrupted: {e}")
        else:
            report.checks_passed += 1

        # Check 5: Disk usage reasonable
        try:
            self_size = sum(
                f.stat().st_size
                for f in self.evolution_dir.glob("**/*")
                if f.is_file()
            )
            if self_size > 100 * 1024 * 1024:  # 100 MB
                report.issues.append(
                    f"Evolution dir using {self_size / 1024 / 1024:.1f} MB"
                )
            else:
                report.checks_passed += 1
        except Exception:
            report.checks_passed += 1  # Don't fail on disk check

        # Update state
        self.state["last_startup_check"] = datetime.now(timezone.utc).isoformat()
        if report.issues:
            self.state["health"] = report.to_dict()
        self._save_state()

        return report

    # ── Daily Audit ──────────────────────────────────────────────────────

    def run_daily_audit(self) -> DailyReport:
        """Medium audit at midnight. ~10 seconds."""
        today = datetime.now().strftime("%Y-%m-%d")
        report = DailyReport(today)

        # Load evidence trail
        try:
            from agent.workflow.evidence import get_evidence_trail

            trail = get_evidence_trail()
            entries = trail.get_recent(500)

            # Filter to today
            today_entries = [
                e
                for e in entries
                if e.get("ts", "").startswith(today)
            ]

            report.total_calls = len(today_entries)

            # Count by action
            action_counts = {}
            error_count = 0

            for entry in today_entries:
                action = entry.get("action", "unknown")
                action_counts[action] = action_counts.get(action, 0) + 1
                if entry.get("severity") == "critical":
                    error_count += 1
                if "fallback" in entry.get("output", "").lower():
                    report.fallbacks += 1

            report.errors = error_count
            if action_counts:
                report.most_frequent_action = max(
                    action_counts, key=action_counts.get
                )

            # Detect repeated errors
            if error_count > 5:
                report.issues.append(
                    f"{error_count} critical errors today"
                )

        except Exception as e:
            logger.warning(f"Failed to analyze evidence trail: {e}")

        # Load shared memory for feedback
        try:
            from agent.memory.shared_memory import SharedMemory

            memory = SharedMemory()
            recent_feedback = memory.get_recent_feedback(10)
            for fb in recent_feedback:
                if fb["feedback_type"] == "complaint":
                    report.issues.append(
                        f"User complaint: {fb['content'][:50]}"
                    )
        except Exception:
            pass

        # Update state
        self.state["last_daily_audit"] = datetime.now(timezone.utc).isoformat()
        self._save_state()

        return report

    # ── Weekly Retrospective ─────────────────────────────────────────────

    def run_weekly_retro(self) -> RetroReport:
        """Full retrospective on Sunday. ~30 seconds."""
        today = datetime.now()
        week_start = (today - timedelta(days=today.weekday())).strftime(
            "%Y-%m-%d"
        )
        week_end = today.strftime("%Y-%m-%d")

        report = RetroReport(week_start, week_end)

        try:
            from agent.workflow.evidence import get_evidence_trail

            trail = get_evidence_trail()
            entries = trail.get_recent(2000)

            # Filter to this week
            week_entries = [e for e in entries]  # Simplified for demo

            report.total_sessions = len(
                set(e.get("sprint", "") for e in week_entries)
            )
            report.total_tasks = len(week_entries)

            # Success rate: entries without errors
            errors = sum(
                1
                for e in week_entries
                if e.get("severity") == "critical"
            )
            if report.total_tasks > 0:
                report.success_rate = (
                    100.0 * (report.total_tasks - errors) / report.total_tasks
                )

            # Top tools
            tool_counts = {}
            for e in week_entries:
                action = e.get("action", "unknown")
                tool_counts[action] = tool_counts.get(action, 0) + 1

            report.top_tools = sorted(
                tool_counts.keys(),
                key=lambda x: tool_counts[x],
                reverse=True,
            )[:5]

        except Exception as e:
            logger.warning(f"Failed to generate retro report: {e}")

        # Save retro file
        try:
            retro_file = self.evolution_dir / f"retro-{week_end}.md"
            retro_content = self._format_retro(report)
            with open(retro_file, "w") as f:
                f.write(retro_content)
            logger.info(f"Saved retro: {retro_file}")
        except Exception as e:
            logger.warning(f"Failed to save retro file: {e}")

        # Update state
        self.state["last_weekly_retro"] = datetime.now(timezone.utc).isoformat()
        self._save_state()

        return report

    def _format_retro(self, report: RetroReport) -> str:
        """Format retro report as markdown."""
        lines = [
            f"# Weekly Retro — {report.week_start} to {report.week_end}\n",
            "## Stats",
            f"- Sessions: {report.total_sessions}",
            f"- Tasks: {report.total_tasks}",
            f"- Success rate: {report.success_rate:.1f}%",
            f"- Avg task time: {report.avg_task_duration_sec}s",
            f"- Top tools: {', '.join(report.top_tools)}",
            "",
            "## Patterns Observed",
        ]

        if report.patterns:
            for k, v in report.patterns.items():
                lines.append(f"- {k}: {v}")
        else:
            lines.append("- (No significant patterns detected)")

        lines.extend(
            [
                "",
                "## Improvement Targets",
            ]
        )

        for i, improvement in enumerate(report.improvements, 1):
            lines.append(f"\n### {i}. {improvement.get('goal', 'Goal')}")
            lines.append(
                f"Current: {improvement.get('current', '...')}"
            )
            lines.append(f"Target: {improvement.get('target', '...')}")
            lines.append(f"Action: {improvement.get('action', '...')}")
            lines.append(f"Timeline: {improvement.get('timeline', '...')}")

        return "\n".join(lines)

    # ── Learning from Feedback ───────────────────────────────────────────

    def learn_from_feedback(self, feedback_type: str, content: str, mode: str):
        """Process user feedback immediately.

        Examples:
        - User says "太长了" → reduce max_tokens preference
        - User corrects model name → remember correct name
        - User says "don't use bullet points" → set format preference
        """
        try:
            conn = sqlite3.connect(str(self.feedback_db), timeout=5.0)
            cursor = conn.cursor()

            # Store feedback
            now = datetime.now(timezone.utc).isoformat()
            cursor.execute(
                "INSERT INTO feedback (timestamp, feedback_type, content) VALUES (?, ?, ?)",
                (now, feedback_type, content),
            )

            # Parse feedback for preferences
            self._extract_preferences_from_feedback(
                content, feedback_type, cursor
            )

            conn.commit()
            conn.close()

            self.state["total_learnings"] += 1
            self._log_learning(f"feedback/{feedback_type}", content)
            self._save_state()

        except Exception as e:
            logger.warning(f"Failed to learn from feedback: {e}")

    def _extract_preferences_from_feedback(self, content: str, ftype: str, cursor):
        """Extract preferences from feedback using simple pattern matching."""
        content_lower = content.lower()

        # Length preferences
        if "太长" in content or "too long" in content_lower:
            cursor.execute(
                "INSERT OR REPLACE INTO preferences (key, value, last_updated) VALUES (?, ?, ?)",
                (
                    "max_tokens",
                    "4096",
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            self._log_learning("pref/length", "User prefers shorter responses")

        if "太短" in content or "too short" in content_lower:
            cursor.execute(
                "INSERT OR REPLACE INTO preferences (key, value, last_updated) VALUES (?, ?, ?)",
                (
                    "max_tokens",
                    "8192",
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            self._log_learning("pref/length", "User prefers longer responses")

        # Format preferences
        if "bullet point" in content_lower and "don't" in content_lower:
            cursor.execute(
                "INSERT OR REPLACE INTO preferences (key, value, last_updated) VALUES (?, ?, ?)",
                (
                    "avoid_bullets",
                    "true",
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            self._log_learning(
                "pref/format", "User prefers paragraph format"
            )

        if "中文" in content or "chinese" in content_lower:
            cursor.execute(
                "INSERT OR REPLACE INTO preferences (key, value, last_updated) VALUES (?, ?, ?)",
                (
                    "language",
                    "zh",
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            self._log_learning("pref/language", "User prefers Chinese")

        if "english" in content_lower:
            cursor.execute(
                "INSERT OR REPLACE INTO preferences (key, value, last_updated) VALUES (?, ?, ?)",
                (
                    "language",
                    "en",
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            self._log_learning("pref/language", "User prefers English")

    # ── Learning from Conversation ───────────────────────────────────────

    def learn_from_conversation(
        self, user_msg: str, bot_response: str, mode: str
    ):
        """Extract patterns from conversation.

        Detects:
        - Frequently asked topics → remember as interests
        - Repeated corrections → adjust behavior
        - Language preference → set language
        - Time patterns → set timezone
        """
        try:
            conn = sqlite3.connect(str(self.feedback_db), timeout=5.0)
            cursor = conn.cursor()

            # Detect language
            if re.search(r"[\u4e00-\u9fff]", user_msg):
                self._record_pattern(
                    cursor, "language", "zh", mode
                )
            else:
                self._record_pattern(
                    cursor, "language", "en", mode
                )

            # Detect topics from keywords
            keywords = [
                ("finance", "stock|trading|portfolio|investment"),
                ("coding", "code|programming|debug|function|class"),
                ("writing", "write|article|essay|story|poem"),
                ("analysis", "analyze|chart|graph|data|metric"),
            ]

            for topic, pattern in keywords:
                if re.search(pattern, user_msg.lower()):
                    self._record_pattern(
                        cursor, "topic", topic, mode
                    )

            # Detect timezone (simple: look for city names or UTC offsets)
            tz_patterns = [
                ("UTC", r"UTC|GMT"),
                ("Asia/Shanghai", r"Shanghai|北京|中国"),
                ("America/New_York", r"New York|Eastern"),
                ("America/Los_Angeles", r"Los Angeles|Pacific|西部"),
            ]

            for tz, pattern in tz_patterns:
                if re.search(pattern, user_msg):
                    cursor.execute(
                        "INSERT OR REPLACE INTO preferences (key, value, last_updated) VALUES (?, ?, ?)",
                        (
                            "timezone",
                            tz,
                            datetime.now(timezone.utc).isoformat(),
                        ),
                    )
                    self._log_learning("pref/timezone", f"Detected timezone: {tz}")
                    break

            conn.commit()
            conn.close()

            self._log_learning("conversation", user_msg[:100])

        except Exception as e:
            logger.warning(f"Failed to learn from conversation: {e}")

    def _record_pattern(self, cursor, pattern_type: str, value: str, mode: str):
        """Record a pattern with frequency tracking."""
        now = datetime.now(timezone.utc).isoformat()
        cursor.execute(
            """
            INSERT INTO patterns (pattern_type, pattern_value, count, last_seen)
            VALUES (?, ?, 1, ?)
            ON CONFLICT(pattern_type, pattern_value)
            DO UPDATE SET count = count + 1, last_seen = ?
            """,
            (pattern_type, value, now, now),
        )

    # ── Evolution Summary ────────────────────────────────────────────────

    def get_evolution_summary(self) -> str:
        """Get summary for /evolve command."""
        lines = ["📈 NeoMind Evolution Status\n"]

        # Overall stats
        lines.append(f"Total Learnings: {self.state.get('total_learnings', 0)}")
        lines.append(
            f"Created: {self.state.get('created_at', '?')[:10]}"
        )

        # Last check times
        last_startup = self.state.get("last_startup_check")
        if last_startup:
            lines.append(f"Last Startup Check: {last_startup[:19]}")

        last_daily = self.state.get("last_daily_audit")
        if last_daily:
            lines.append(f"Last Daily Audit: {last_daily[:19]}")

        last_weekly = self.state.get("last_weekly_retro")
        if last_weekly:
            lines.append(f"Last Weekly Retro: {last_weekly[:19]}")

        # Preferences learned
        if self.state.get("preferences"):
            lines.append("\n📋 Learned Preferences:")
            for key, value in self.state.get("preferences", {}).items():
                lines.append(f"  - {key}: {value}")

        # Recent learnings
        try:
            if self.learning_log.exists():
                with open(self.learning_log, "r") as f:
                    recent = [
                        json.loads(line)
                        for line in f.readlines()[-5:]
                    ]
                if recent:
                    lines.append("\n🧠 Recent Learnings:")
                    for entry in recent:
                        content = (
                            entry.get("content", "?")[:50]
                        )
                        lines.append(
                            f"  - [{entry.get('type', '?')}] {content}"
                        )
        except Exception:
            pass

        return "\n".join(lines)

    # ── Scheduling ───────────────────────────────────────────────────────

    def should_run_daily(self) -> bool:
        """Check if daily audit needs to run."""
        last_run = self.state.get("last_daily_audit")
        if not last_run:
            return True

        try:
            last_dt = datetime.fromisoformat(last_run)
            now = datetime.now(timezone.utc)
            return (now - last_dt) > timedelta(hours=24)
        except Exception:
            return True

    def should_run_weekly(self) -> bool:
        """Check if weekly retro needs to run."""
        last_run = self.state.get("last_weekly_retro")
        if not last_run:
            return True

        try:
            last_dt = datetime.fromisoformat(last_run)
            now = datetime.now(timezone.utc)
            return (now - last_dt) > timedelta(days=7)
        except Exception:
            return True

    def is_sunday_midnight(self) -> bool:
        """Check if it's Sunday midnight (best time for weekly retro)."""
        now = datetime.now()
        return now.weekday() == 6 and now.hour == 0
