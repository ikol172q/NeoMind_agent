"""Tests for NeoMind Evolution Engine (Phase 4).

Tests the self-evolution closed loop:
- Startup health checks
- Daily audits
- Weekly retros
- Learning from feedback
- Learning from conversations
- Pattern recognition
- State persistence
- Scheduling logic
- Safe upgrades
"""

import pytest
import json
import sqlite3
import tempfile
from pathlib import Path
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch, MagicMock

from agent.evolution.auto_evolve import (
    AutoEvolve,
    HealthReport,
    DailyReport,
    RetroReport,
)
from agent.evolution.upgrade import NeoMindUpgrade


class TestHealthReport:
    """Tests for HealthReport."""

    def test_health_report_creation(self):
        """Test creating a health report."""
        report = HealthReport()
        assert report.checks_passed == 0
        assert report.checks_failed == 0
        assert report.issues == []

    def test_health_report_to_dict(self):
        """Test converting health report to dict."""
        report = HealthReport()
        report.checks_passed = 5
        report.checks_failed = 1
        report.issues = ["Issue 1", "Issue 2"]

        d = report.to_dict()
        assert d["checks_passed"] == 5
        assert d["checks_failed"] == 1
        assert len(d["issues"]) == 2
        assert "timestamp" in d


class TestDailyReport:
    """Tests for DailyReport."""

    def test_daily_report_creation(self):
        """Test creating a daily report."""
        report = DailyReport("2026-03-22")
        assert report.date == "2026-03-22"
        assert report.total_calls == 0
        assert report.errors == 0

    def test_daily_report_to_dict(self):
        """Test converting daily report to dict."""
        report = DailyReport("2026-03-22")
        report.total_calls = 42
        report.errors = 3

        d = report.to_dict()
        assert d["date"] == "2026-03-22"
        assert d["total_calls"] == 42
        assert d["errors"] == 3


class TestRetroReport:
    """Tests for RetroReport."""

    def test_retro_report_creation(self):
        """Test creating a retro report."""
        report = RetroReport("2026-03-15", "2026-03-22")
        assert report.week_start == "2026-03-15"
        assert report.week_end == "2026-03-22"
        assert report.total_sessions == 0
        assert report.total_tasks == 0
        assert report.success_rate == 0.0

    def test_retro_report_to_dict(self):
        """Test converting retro report to dict."""
        report = RetroReport("2026-03-15", "2026-03-22")
        report.total_sessions = 10
        report.total_tasks = 50
        report.success_rate = 92.0
        report.top_tools = ["search", "edit", "read"]

        d = report.to_dict()
        assert d["total_sessions"] == 10
        assert d["total_tasks"] == 50
        assert d["success_rate"] == 92.0
        assert "search" in d["top_tools"]


class TestAutoEvolveInitialization:
    """Tests for AutoEvolve initialization."""

    def test_auto_evolve_creates_directories(self):
        """Test that AutoEvolve creates necessary directories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            evolve = AutoEvolve(state_dir=tmpdir)
            assert evolve.evolution_dir.exists()
            assert evolve.state_file is not None

    def test_auto_evolve_loads_default_state(self):
        """Test that AutoEvolve loads default state."""
        with tempfile.TemporaryDirectory() as tmpdir:
            evolve = AutoEvolve(state_dir=tmpdir)
            assert "created_at" in evolve.state
            assert "total_learnings" in evolve.state
            assert evolve.state["total_learnings"] == 0

    def test_auto_evolve_persists_state(self):
        """Test that AutoEvolve persists state to disk."""
        with tempfile.TemporaryDirectory() as tmpdir:
            evolve1 = AutoEvolve(state_dir=tmpdir)
            evolve1.state["total_learnings"] = 42
            evolve1._save_state()

            # Load again
            evolve2 = AutoEvolve(state_dir=tmpdir)
            assert evolve2.state["total_learnings"] == 42

    def test_auto_evolve_initializes_feedback_db(self):
        """Test that feedback database is initialized."""
        with tempfile.TemporaryDirectory() as tmpdir:
            evolve = AutoEvolve(state_dir=tmpdir)
            assert evolve.feedback_db.exists()

            # Verify tables exist
            conn = sqlite3.connect(str(evolve.feedback_db), timeout=5.0)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
            tables = [row[0] for row in cursor.fetchall()]
            conn.close()

            assert "feedback" in tables
            assert "preferences" in tables
            assert "patterns" in tables


class TestStartupCheck:
    """Tests for startup health checks."""

    def test_startup_check_runs_without_error(self):
        """Test that startup check completes without crashing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            evolve = AutoEvolve(state_dir=tmpdir)
            report = evolve.run_startup_check()

            assert isinstance(report, HealthReport)
            assert report.checks_passed >= 0
            assert report.checks_failed >= 0

    def test_startup_check_records_timestamp(self):
        """Test that startup check records when it ran."""
        with tempfile.TemporaryDirectory() as tmpdir:
            evolve = AutoEvolve(state_dir=tmpdir)
            report = evolve.run_startup_check()

            assert evolve.state["last_startup_check"] is not None
            assert "T" in evolve.state["last_startup_check"]

    def test_startup_check_updates_state(self):
        """Test that startup check updates evolution state."""
        with tempfile.TemporaryDirectory() as tmpdir:
            evolve = AutoEvolve(state_dir=tmpdir)
            before = evolve.state.copy()

            evolve.run_startup_check()

            assert evolve.state["last_startup_check"] != before.get(
                "last_startup_check"
            )

    def test_startup_check_detects_disk_issues(self):
        """Test that startup check can detect large disk usage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            evolve = AutoEvolve(state_dir=tmpdir)

            # Create large file
            (evolve.evolution_dir / "large_file.bin").write_bytes(
                b"x" * (101 * 1024 * 1024)
            )

            report = evolve.run_startup_check()
            # Should detect the large file
            assert any("MB" in issue for issue in report.issues)


class TestDailyAudit:
    """Tests for daily audit."""

    def test_daily_audit_runs_without_error(self):
        """Test that daily audit completes without crashing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            evolve = AutoEvolve(state_dir=tmpdir)
            report = evolve.run_daily_audit()

            assert isinstance(report, DailyReport)
            assert report.date is not None

    def test_daily_audit_records_timestamp(self):
        """Test that daily audit records when it ran."""
        with tempfile.TemporaryDirectory() as tmpdir:
            evolve = AutoEvolve(state_dir=tmpdir)
            evolve.run_daily_audit()

            assert evolve.state["last_daily_audit"] is not None

    def test_daily_audit_counts_calls(self):
        """Test that daily audit counts tool calls."""
        with tempfile.TemporaryDirectory() as tmpdir:
            evolve = AutoEvolve(state_dir=tmpdir)
            report = evolve.run_daily_audit()

            assert report.total_calls >= 0
            assert report.errors >= 0


class TestWeeklyRetro:
    """Tests for weekly retrospective."""

    def test_weekly_retro_runs_without_error(self):
        """Test that weekly retro completes without crashing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            evolve = AutoEvolve(state_dir=tmpdir)
            report = evolve.run_weekly_retro()

            assert isinstance(report, RetroReport)
            assert report.week_start is not None
            assert report.week_end is not None

    def test_weekly_retro_saves_markdown_file(self):
        """Test that weekly retro saves a markdown file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            evolve = AutoEvolve(state_dir=tmpdir)
            evolve.run_weekly_retro()

            # Check that a retro file was created
            retro_files = list(evolve.evolution_dir.glob("retro-*.md"))
            assert len(retro_files) > 0

    def test_weekly_retro_format_contains_required_sections(self):
        """Test that retro markdown contains required sections."""
        with tempfile.TemporaryDirectory() as tmpdir:
            evolve = AutoEvolve(state_dir=tmpdir)
            report = RetroReport("2026-03-15", "2026-03-22")
            markdown = evolve._format_retro(report)

            assert "Weekly Retro" in markdown
            assert "Stats" in markdown
            assert "Patterns" in markdown
            assert "Improvement Targets" in markdown

    def test_weekly_retro_records_timestamp(self):
        """Test that weekly retro records when it ran."""
        with tempfile.TemporaryDirectory() as tmpdir:
            evolve = AutoEvolve(state_dir=tmpdir)
            evolve.run_weekly_retro()

            assert evolve.state["last_weekly_retro"] is not None


class TestLearnFromFeedback:
    """Tests for learning from user feedback."""

    def test_learn_from_feedback_stores_entry(self):
        """Test that feedback is stored in database."""
        with tempfile.TemporaryDirectory() as tmpdir:
            evolve = AutoEvolve(state_dir=tmpdir)
            evolve.learn_from_feedback("praise", "Great job!", "chat")

            conn = sqlite3.connect(str(evolve.feedback_db), timeout=5.0)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM feedback")
            count = cursor.fetchone()[0]
            conn.close()

            assert count == 1

    def test_learn_from_feedback_too_long(self):
        """Test that agent detects 'too long' feedback."""
        with tempfile.TemporaryDirectory() as tmpdir:
            evolve = AutoEvolve(state_dir=tmpdir)
            evolve.learn_from_feedback(
                "complaint", "太长了，请缩短", "chat"
            )

            conn = sqlite3.connect(str(evolve.feedback_db), timeout=5.0)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT value FROM preferences WHERE key = 'max_tokens'"
            )
            pref = cursor.fetchone()
            conn.close()

            assert pref is not None
            assert pref[0] == "4096"

    def test_learn_from_feedback_english_too_long(self):
        """Test detection of English 'too long' feedback."""
        with tempfile.TemporaryDirectory() as tmpdir:
            evolve = AutoEvolve(state_dir=tmpdir)
            evolve.learn_from_feedback(
                "complaint", "Your responses are too long", "chat"
            )

            conn = sqlite3.connect(str(evolve.feedback_db), timeout=5.0)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT value FROM preferences WHERE key = 'max_tokens'"
            )
            pref = cursor.fetchone()
            conn.close()

            assert pref is not None

    def test_learn_from_feedback_language_chinese(self):
        """Test that agent detects Chinese language preference."""
        with tempfile.TemporaryDirectory() as tmpdir:
            evolve = AutoEvolve(state_dir=tmpdir)
            evolve.learn_from_feedback(
                "preference", "请用中文回答", "chat"
            )

            conn = sqlite3.connect(str(evolve.feedback_db), timeout=5.0)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT value FROM preferences WHERE key = 'language'"
            )
            pref = cursor.fetchone()
            conn.close()

            assert pref is not None
            assert pref[0] == "zh"

    def test_learn_from_feedback_language_english(self):
        """Test that agent detects English language preference."""
        with tempfile.TemporaryDirectory() as tmpdir:
            evolve = AutoEvolve(state_dir=tmpdir)
            evolve.learn_from_feedback(
                "preference", "Please respond in english only", "chat"
            )

            conn = sqlite3.connect(str(evolve.feedback_db), timeout=5.0)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT value FROM preferences WHERE key = 'language'"
            )
            pref = cursor.fetchone()
            conn.close()

            assert pref is not None
            assert pref[0] == "en"

    def test_learn_from_feedback_no_bullets(self):
        """Test that agent detects 'no bullet points' preference."""
        with tempfile.TemporaryDirectory() as tmpdir:
            evolve = AutoEvolve(state_dir=tmpdir)
            evolve.learn_from_feedback(
                "preference",
                "don't use bullet points, use paragraphs",
                "chat",
            )

            conn = sqlite3.connect(str(evolve.feedback_db), timeout=5.0)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT value FROM preferences WHERE key = 'avoid_bullets'"
            )
            pref = cursor.fetchone()
            conn.close()

            assert pref is not None
            assert pref[0] == "true"

    def test_learn_from_feedback_increments_learning_counter(self):
        """Test that learning counter is incremented."""
        with tempfile.TemporaryDirectory() as tmpdir:
            evolve = AutoEvolve(state_dir=tmpdir)
            assert evolve.state["total_learnings"] == 0

            evolve.learn_from_feedback("praise", "Good!", "chat")
            assert evolve.state["total_learnings"] == 1

            evolve.learn_from_feedback("praise", "Good!", "chat")
            assert evolve.state["total_learnings"] == 2


class TestLearnFromConversation:
    """Tests for learning from conversations."""

    def test_learn_from_conversation_detects_language_chinese(self):
        """Test that agent detects Chinese language from conversation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            evolve = AutoEvolve(state_dir=tmpdir)
            evolve.learn_from_conversation(
                "你能帮我分析这个代码吗?",
                "当然可以...",
                "coding",
            )

            conn = sqlite3.connect(str(evolve.feedback_db), timeout=5.0)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT pattern_value FROM patterns WHERE pattern_type = 'language'"
            )
            langs = [row[0] for row in cursor.fetchall()]
            conn.close()

            assert "zh" in langs

    def test_learn_from_conversation_detects_language_english(self):
        """Test that agent detects English language from conversation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            evolve = AutoEvolve(state_dir=tmpdir)
            evolve.learn_from_conversation(
                "Can you help me debug this code?",
                "Sure, let me analyze...",
                "coding",
            )

            conn = sqlite3.connect(str(evolve.feedback_db), timeout=5.0)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT pattern_value FROM patterns WHERE pattern_type = 'language'"
            )
            langs = [row[0] for row in cursor.fetchall()]
            conn.close()

            assert "en" in langs

    def test_learn_from_conversation_detects_topics(self):
        """Test that agent detects topic from conversation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            evolve = AutoEvolve(state_dir=tmpdir)

            # Finance topic
            evolve.learn_from_conversation(
                "What's your take on AAPL stock?",
                "AAPL is a strong company...",
                "fin",
            )

            conn = sqlite3.connect(str(evolve.feedback_db), timeout=5.0)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT pattern_value FROM patterns WHERE pattern_type = 'topic'"
            )
            topics = [row[0] for row in cursor.fetchall()]
            conn.close()

            assert "finance" in topics

    def test_learn_from_conversation_detects_timezone(self):
        """Test that agent detects timezone from conversation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            evolve = AutoEvolve(state_dir=tmpdir)
            evolve.learn_from_conversation(
                "I'm in Shanghai, what time is the market opening?",
                "In Shanghai (UTC+8)...",
                "fin",
            )

            conn = sqlite3.connect(str(evolve.feedback_db), timeout=5.0)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT value FROM preferences WHERE key = 'timezone'"
            )
            tz = cursor.fetchone()
            conn.close()

            assert tz is not None
            assert "Shanghai" in tz[0] or "Asia" in tz[0]

    def test_learn_from_conversation_coding_topic(self):
        """Test that agent detects coding topic."""
        with tempfile.TemporaryDirectory() as tmpdir:
            evolve = AutoEvolve(state_dir=tmpdir)
            evolve.learn_from_conversation(
                "How do I debug this Python function?",
                "You can use pdb...",
                "coding",
            )

            conn = sqlite3.connect(str(evolve.feedback_db), timeout=5.0)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT pattern_value FROM patterns WHERE pattern_type = 'topic'"
            )
            topics = [row[0] for row in cursor.fetchall()]
            conn.close()

            assert "coding" in topics


class TestScheduling:
    """Tests for scheduling logic."""

    def test_should_run_daily_first_time(self):
        """Test that daily audit should run on first call."""
        with tempfile.TemporaryDirectory() as tmpdir:
            evolve = AutoEvolve(state_dir=tmpdir)
            assert evolve.should_run_daily() is True

    def test_should_run_daily_respects_24h_interval(self):
        """Test that daily audit respects 24 hour interval."""
        with tempfile.TemporaryDirectory() as tmpdir:
            evolve = AutoEvolve(state_dir=tmpdir)

            # Set last run to 1 hour ago
            one_hour_ago = (
                datetime.now(timezone.utc) - timedelta(hours=1)
            ).isoformat()
            evolve.state["last_daily_audit"] = one_hour_ago
            evolve._save_state()

            # Should not run yet
            assert evolve.should_run_daily() is False

    def test_should_run_daily_after_24h(self):
        """Test that daily audit runs after 24 hours."""
        with tempfile.TemporaryDirectory() as tmpdir:
            evolve = AutoEvolve(state_dir=tmpdir)

            # Set last run to 25 hours ago
            long_ago = (
                datetime.now(timezone.utc) - timedelta(hours=25)
            ).isoformat()
            evolve.state["last_daily_audit"] = long_ago
            evolve._save_state()

            # Should run now
            assert evolve.should_run_daily() is True

    def test_should_run_weekly_first_time(self):
        """Test that weekly retro should run on first call."""
        with tempfile.TemporaryDirectory() as tmpdir:
            evolve = AutoEvolve(state_dir=tmpdir)
            assert evolve.should_run_weekly() is True

    def test_should_run_weekly_respects_7d_interval(self):
        """Test that weekly retro respects 7 day interval."""
        with tempfile.TemporaryDirectory() as tmpdir:
            evolve = AutoEvolve(state_dir=tmpdir)

            # Set last run to 3 days ago
            three_days_ago = (
                datetime.now(timezone.utc) - timedelta(days=3)
            ).isoformat()
            evolve.state["last_weekly_retro"] = three_days_ago
            evolve._save_state()

            # Should not run yet
            assert evolve.should_run_weekly() is False

    def test_should_run_weekly_after_7d(self):
        """Test that weekly retro runs after 7 days."""
        with tempfile.TemporaryDirectory() as tmpdir:
            evolve = AutoEvolve(state_dir=tmpdir)

            # Set last run to 8 days ago
            long_ago = (
                datetime.now(timezone.utc) - timedelta(days=8)
            ).isoformat()
            evolve.state["last_weekly_retro"] = long_ago
            evolve._save_state()

            # Should run now
            assert evolve.should_run_weekly() is True


class TestEvolutionSummary:
    """Tests for evolution summary generation."""

    def test_get_evolution_summary_returns_string(self):
        """Test that evolution summary returns formatted string."""
        with tempfile.TemporaryDirectory() as tmpdir:
            evolve = AutoEvolve(state_dir=tmpdir)
            summary = evolve.get_evolution_summary()

            assert isinstance(summary, str)
            assert len(summary) > 0
            assert "NeoMind" in summary or "Evolution" in summary

    def test_get_evolution_summary_includes_learnings_count(self):
        """Test that summary includes learning count."""
        with tempfile.TemporaryDirectory() as tmpdir:
            evolve = AutoEvolve(state_dir=tmpdir)
            evolve.state["total_learnings"] = 42
            summary = evolve.get_evolution_summary()

            assert "42" in summary

    def test_get_evolution_summary_includes_timestamps(self):
        """Test that summary includes check timestamps."""
        with tempfile.TemporaryDirectory() as tmpdir:
            evolve = AutoEvolve(state_dir=tmpdir)
            evolve.run_startup_check()
            summary = evolve.get_evolution_summary()

            assert "Startup Check" in summary


class TestNeoMindUpgrade:
    """Tests for upgrade mechanism."""

    def test_upgrade_init_finds_repo(self):
        """Test that upgrade manager initializes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            upgrade = NeoMindUpgrade(repo_dir=tmpdir)
            assert upgrade.repo_dir == Path(tmpdir)

    def test_get_current_version_handles_no_git(self):
        """Test that version check works when git is unavailable."""
        with tempfile.TemporaryDirectory() as tmpdir:
            upgrade = NeoMindUpgrade(repo_dir=tmpdir)
            version = upgrade.get_current_version()

            # Should return something even if git fails
            assert version is not None
            assert len(version) > 0

    def test_upgrade_creates_log_directory(self):
        """Test that upgrade creates log directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            upgrade = NeoMindUpgrade(repo_dir=tmpdir)
            assert upgrade.upgrade_log.exists()

    def test_check_for_updates_returns_tuple(self):
        """Test that check_for_updates returns (has_updates, version)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            upgrade = NeoMindUpgrade(repo_dir=tmpdir)
            has_updates, version = upgrade.check_for_updates()

            assert isinstance(has_updates, bool)
            # version can be None if no updates

    def test_get_changelog_diff_returns_string(self):
        """Test that get_changelog_diff returns string."""
        with tempfile.TemporaryDirectory() as tmpdir:
            upgrade = NeoMindUpgrade(repo_dir=tmpdir)
            changelog = upgrade.get_changelog_diff()

            assert isinstance(changelog, str)

    def test_get_upgrade_history_returns_list(self):
        """Test that upgrade history returns list."""
        with tempfile.TemporaryDirectory() as tmpdir:
            upgrade = NeoMindUpgrade(repo_dir=tmpdir)
            history = upgrade.get_upgrade_history()

            assert isinstance(history, list)


# ── Integration Tests ────────────────────────────────────────────────────


class TestAutoEvolveIntegration:
    """Integration tests for the full evolution loop."""

    def test_full_startup_sequence(self):
        """Test complete startup sequence."""
        with tempfile.TemporaryDirectory() as tmpdir:
            evolve = AutoEvolve(state_dir=tmpdir)

            # Run startup check
            health = evolve.run_startup_check()
            assert health is not None

            # Verify state was updated
            assert evolve.state["last_startup_check"] is not None

    def test_full_daily_sequence(self):
        """Test complete daily sequence."""
        with tempfile.TemporaryDirectory() as tmpdir:
            evolve = AutoEvolve(state_dir=tmpdir)

            # Run daily audit
            report = evolve.run_daily_audit()
            assert report is not None

            # Verify state was updated
            assert evolve.state["last_daily_audit"] is not None

    def test_full_weekly_sequence(self):
        """Test complete weekly sequence."""
        with tempfile.TemporaryDirectory() as tmpdir:
            evolve = AutoEvolve(state_dir=tmpdir)

            # Run weekly retro
            report = evolve.run_weekly_retro()
            assert report is not None

            # Verify file was created
            assert len(list(evolve.evolution_dir.glob("retro-*.md"))) > 0

            # Verify state was updated
            assert evolve.state["last_weekly_retro"] is not None

    def test_learning_persists_across_restarts(self):
        """Test that learnings persist when AutoEvolve is recreated."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # First instance: learn something
            evolve1 = AutoEvolve(state_dir=tmpdir)
            evolve1.learn_from_feedback(
                "complaint", "Response is too long", "chat"
            )

            learnings1 = evolve1.state["total_learnings"]

            # Second instance: verify learning persisted
            evolve2 = AutoEvolve(state_dir=tmpdir)
            assert evolve2.state["total_learnings"] == learnings1

            # Verify preference was stored
            conn = sqlite3.connect(
                str(evolve2.feedback_db), timeout=5.0
            )
            cursor = conn.cursor()
            cursor.execute(
                "SELECT value FROM preferences WHERE key = 'max_tokens'"
            )
            pref = cursor.fetchone()
            conn.close()

            assert pref is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
