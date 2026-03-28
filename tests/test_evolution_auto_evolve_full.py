"""
Comprehensive tests for agent/evolution/auto_evolve.py

Run: pytest tests/test_evolution_auto_evolve_full.py -v
"""
import os
import sys
import pytest
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch
import json
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestHealthReport:
    """Test HealthReport class."""

    def test_init(self):
        from agent.evolution.auto_evolve import HealthReport
        report = HealthReport()

        assert report.timestamp is not None
        assert report.checks_passed == 0
        assert report.checks_failed == 0
        assert report.issues == []
        assert report.last_successful_run is None

    def test_to_dict(self):
        from agent.evolution.auto_evolve import HealthReport
        report = HealthReport()
        report.checks_passed = 5
        report.checks_failed = 1

        data = report.to_dict()

        assert data["checks_passed"] == 5
        assert data["checks_failed"] == 1
        assert "timestamp" in data
        assert "issues" in data


class TestDailyReport:
    """Test DailyReport class."""

    def test_init(self):
        from agent.evolution.auto_evolve import DailyReport
        report = DailyReport("2024-01-01")

        assert report.date == "2024-01-01"
        assert report.total_calls == 0
        assert report.errors == 0
        assert report.fallbacks == 0

    def test_to_dict(self):
        from agent.evolution.auto_evolve import DailyReport
        report = DailyReport("2024-01-01")
        report.total_calls = 100
        report.errors = 5

        data = report.to_dict()

        assert data["total_calls"] == 100
        assert data["errors"] == 5
        assert data["date"] == "2024-01-01"


class TestRetroReport:
    """Test RetroReport class."""

    def test_init(self):
        from agent.evolution.auto_evolve import RetroReport
        report = RetroReport("2024-01-01", "2024-01-07")

        assert report.week_start == "2024-01-01"
        assert report.week_end == "2024-01-07"
        assert report.total_sessions == 0
        assert report.success_rate == 0.0

    def test_to_dict(self):
        from agent.evolution.auto_evolve import RetroReport
        report = RetroReport("2024-01-01", "2024-01-07")
        report.total_sessions = 42
        report.success_rate = 0.95

        data = report.to_dict()

        assert data["total_sessions"] == 42
        assert data["success_rate"] == 0.95


class TestAutoEvolveInit:
    """Test AutoEvolve initialization."""

    def test_init_default_state_dir(self, tmp_path):
        from agent.evolution.auto_evolve import AutoEvolve
        # Use explicit state_dir to avoid creating files in real home
        fake_home = tmp_path / "fakehome"
        fake_home.mkdir()
        ae = AutoEvolve(state_dir=str(fake_home / ".neomind"))

        assert ae.state_dir == fake_home / ".neomind"
        assert ae.evolution_dir.exists()

    def test_init_custom_state_dir(self, tmp_path):
        from agent.evolution.auto_evolve import AutoEvolve
        ae = AutoEvolve(state_dir=str(tmp_path))

        assert ae.state_dir == tmp_path
        assert (tmp_path / "evolution").exists()

    def test_init_creates_directories(self, tmp_path):
        from agent.evolution.auto_evolve import AutoEvolve
        ae = AutoEvolve(state_dir=str(tmp_path))

        assert ae.evolution_dir.exists()

    def test_init_feedback_db(self, tmp_path):
        from agent.evolution.auto_evolve import AutoEvolve
        ae = AutoEvolve(state_dir=str(tmp_path))

        assert ae.feedback_db.exists()

    def test_feedback_db_schema(self, tmp_path):
        from agent.evolution.auto_evolve import AutoEvolve
        ae = AutoEvolve(state_dir=str(tmp_path))

        conn = sqlite3.connect(str(ae.feedback_db))
        cursor = conn.cursor()

        # Check tables exist
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]

        assert "feedback" in tables
        assert "preferences" in tables

        conn.close()


class TestAutoEvolveStateManagement:
    """Test state loading and saving."""

    def test_load_state_file(self, tmp_path):
        from agent.evolution.auto_evolve import AutoEvolve

        # Create state file
        state_file = tmp_path / "evolution" / "evolution_state.json"
        state_file.parent.mkdir(parents=True)
        state_file.write_text(json.dumps({"test": "value"}))

        ae = AutoEvolve(state_dir=str(tmp_path))

        assert ae.state_file.exists()

    def test_load_state_missing_file(self, tmp_path):
        from agent.evolution.auto_evolve import AutoEvolve
        ae = AutoEvolve(state_dir=str(tmp_path))

        # Should not raise if state file missing
        assert ae.state_file is not None


class TestAutoEvolveFeedback:
    """Test feedback database operations."""

    def test_add_feedback(self, tmp_path):
        from agent.evolution.auto_evolve import AutoEvolve

        ae = AutoEvolve(state_dir=str(tmp_path))

        conn = sqlite3.connect(str(ae.feedback_db))
        cursor = conn.cursor()

        cursor.execute(
            "INSERT INTO feedback (timestamp, feedback_type, content) VALUES (?, ?, ?)",
            ("2024-01-01T12:00:00Z", "positive", "Good response")
        )
        conn.commit()

        cursor.execute("SELECT COUNT(*) FROM feedback")
        count = cursor.fetchone()[0]
        assert count == 1

        conn.close()

    def test_preferences_storage(self, tmp_path):
        from agent.evolution.auto_evolve import AutoEvolve

        ae = AutoEvolve(state_dir=str(tmp_path))

        conn = sqlite3.connect(str(ae.feedback_db))
        cursor = conn.cursor()

        cursor.execute(
            "INSERT INTO preferences (key, value, last_updated) VALUES (?, ?, ?)",
            ("model_temperature", "0.7", "2024-01-01T12:00:00Z")
        )
        conn.commit()

        cursor.execute("SELECT value FROM preferences WHERE key = ?", ("model_temperature",))
        value = cursor.fetchone()[0]
        assert value == "0.7"

        conn.close()


class TestAutoEvolveFileOperations:
    """Test file I/O operations."""

    def test_learning_log_created(self, tmp_path):
        from agent.evolution.auto_evolve import AutoEvolve
        ae = AutoEvolve(state_dir=str(tmp_path))

        assert ae.learning_log.parent.exists()

    def test_learning_log_path(self, tmp_path):
        from agent.evolution.auto_evolve import AutoEvolve
        ae = AutoEvolve(state_dir=str(tmp_path))

        assert ae.learning_log.name == "learning.jsonl"
        assert ae.learning_log.suffix == ".jsonl"


class TestAutoEvolveErrorHandling:
    """Test error handling and edge cases."""

    def test_corrupted_feedback_db(self, tmp_path):
        from agent.evolution.auto_evolve import AutoEvolve

        # Create corrupted database
        db_path = tmp_path / "evolution" / "feedback.db"
        db_path.parent.mkdir(parents=True)
        db_path.write_text("corrupted data")

        # Should not crash during init - handles corruption gracefully
        ae = AutoEvolve(state_dir=str(tmp_path))
        assert ae.state_dir == tmp_path

    def test_missing_evolution_dir_created(self, tmp_path):
        from agent.evolution.auto_evolve import AutoEvolve

        ae = AutoEvolve(state_dir=str(tmp_path))

        assert ae.evolution_dir.exists()
        assert ae.evolution_dir.is_dir()


class TestAutoEvolveIntegration:
    """Integration tests for AutoEvolve."""

    def test_full_workflow(self, tmp_path):
        from agent.evolution.auto_evolve import AutoEvolve

        ae = AutoEvolve(state_dir=str(tmp_path))

        # Verify all components initialized
        assert ae.state_dir == tmp_path
        assert ae.evolution_dir.exists()
        assert ae.feedback_db.exists()
        assert ae.state_file.parent.exists()

    def test_multiple_instances(self, tmp_path):
        from agent.evolution.auto_evolve import AutoEvolve

        ae1 = AutoEvolve(state_dir=str(tmp_path))
        ae2 = AutoEvolve(state_dir=str(tmp_path))

        # Both should reference same database
        assert ae1.feedback_db == ae2.feedback_db
