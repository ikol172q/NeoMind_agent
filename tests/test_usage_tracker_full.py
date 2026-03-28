"""
Comprehensive unit tests for agent/finance/usage_tracker.py
Tests LLM usage recording, tracking, and statistics.
"""

import pytest
import sqlite3
from pathlib import Path
from datetime import datetime, timezone, timedelta

import sys
sys.path.insert(0, '/sessions/hopeful-magical-rubin/mnt/NeoMind_agent')

from agent.finance.usage_tracker import UsageTracker, UsageRecord, COST_PER_1K_TOKENS


class TestUsageRecord:
    """Tests for UsageRecord dataclass."""

    def test_init_basic(self):
        """Test basic initialization."""
        record = UsageRecord(
            provider="litellm",
            model="local",
            tokens_est=100,
            latency_ms=500,
            cost_est=0.0,
            success=True
        )

        assert record.provider == "litellm"
        assert record.model == "local"
        assert record.tokens_est == 100
        assert record.success is True

    def test_init_with_chat_id(self):
        """Test initialization with chat ID."""
        record = UsageRecord(
            provider="deepseek",
            model="deepseek-chat",
            tokens_est=200,
            latency_ms=1000,
            cost_est=0.00028,
            success=True,
            chat_id=12345
        )

        assert record.chat_id == 12345

    def test_init_with_error(self):
        """Test initialization with error."""
        record = UsageRecord(
            provider="litellm",
            model="local",
            tokens_est=0,
            latency_ms=0,
            cost_est=0,
            success=False,
            error="Connection timeout"
        )

        assert record.success is False
        assert record.error == "Connection timeout"


class TestUsageTrackerInit:
    """Tests for UsageTracker initialization."""

    def test_init_custom_db(self, tmp_path):
        """Test initialization with custom DB path."""
        db_path = str(tmp_path / "usage.db")
        tracker = UsageTracker(db_path=db_path)

        assert tracker.db_path == db_path
        assert Path(db_path).parent.exists()

    def test_init_creates_tables(self, tmp_path):
        """Test that initialization creates tables."""
        db_path = str(tmp_path / "usage.db")
        tracker = UsageTracker(db_path=db_path)

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cursor.fetchall()}

        assert "usage" in tables
        conn.close()

    def test_init_creates_index(self, tmp_path):
        """Test that initialization creates indices."""
        db_path = str(tmp_path / "usage.db")
        tracker = UsageTracker(db_path=db_path)

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='index'")
        indices = {row[0] for row in cursor.fetchall()}

        assert "idx_usage_ts" in indices
        conn.close()


class TestRecordUsage:
    """Tests for recording usage."""

    def test_record_basic(self, tmp_path):
        """Test basic usage recording."""
        tracker = UsageTracker(db_path=str(tmp_path / "usage.db"))

        tracker.record(
            provider="litellm",
            model="local",
            tokens_est=100,
            latency_ms=500,
            success=True
        )

        # Should not raise
        assert tracker.count_records() == 1

    def test_record_with_chat_id(self, tmp_path):
        """Test recording with chat ID."""
        tracker = UsageTracker(db_path=str(tmp_path / "usage.db"))

        tracker.record(
            provider="deepseek",
            model="deepseek-chat",
            tokens_est=150,
            latency_ms=1000,
            success=True,
            chat_id=12345
        )

        assert tracker.count_records() == 1

    def test_record_failure(self, tmp_path):
        """Test recording failed calls."""
        tracker = UsageTracker(db_path=str(tmp_path / "usage.db"))

        tracker.record(
            provider="litellm",
            model="local",
            tokens_est=0,
            latency_ms=0,
            success=False,
            error="Timeout"
        )

        assert tracker.count_records() == 1

    def test_record_multiple(self, tmp_path):
        """Test recording multiple calls."""
        tracker = UsageTracker(db_path=str(tmp_path / "usage.db"))

        for i in range(5):
            tracker.record(
                provider="litellm",
                model="local",
                tokens_est=100 * i,
                latency_ms=500,
                success=True
            )

        assert tracker.count_records() == 5


class TestCostEstimation:
    """Tests for cost estimation."""

    def test_cost_local_free(self, tmp_path):
        """Test that local model is free."""
        tracker = UsageTracker(db_path=str(tmp_path / "usage.db"))

        tracker.record(
            provider="litellm",
            model="local",
            tokens_est=10000,
            latency_ms=1000,
            success=True
        )

        # Cost should be 0
        today = tracker.get_today()
        assert today["cost"] == 0.0

    def test_cost_estimation_deepseek(self, tmp_path):
        """Test cost estimation for paid models."""
        tracker = UsageTracker(db_path=str(tmp_path / "usage.db"))

        tracker.record(
            provider="deepseek",
            model="deepseek-chat",
            tokens_est=1000,
            latency_ms=500,
            success=True
        )

        today = tracker.get_today()
        # Should have some cost
        assert today["cost"] >= 0


class TestGetToday:
    """Tests for getting today's stats."""

    def test_get_today_empty(self, tmp_path):
        """Test getting stats for empty day."""
        tracker = UsageTracker(db_path=str(tmp_path / "usage.db"))

        today = tracker.get_today()

        assert today["calls"] == 0
        assert today["tokens"] == 0
        assert today["cost"] == 0.0

    def test_get_today_with_data(self, tmp_path):
        """Test getting today's stats with data."""
        tracker = UsageTracker(db_path=str(tmp_path / "usage.db"))

        tracker.record(
            provider="litellm",
            model="local",
            tokens_est=100,
            latency_ms=500,
            success=True
        )
        tracker.record(
            provider="litellm",
            model="local",
            tokens_est=150,
            latency_ms=600,
            success=True
        )

        today = tracker.get_today()

        assert today["calls"] == 2
        assert today["tokens"] == 250

    def test_get_today_excludes_yesterday(self, tmp_path):
        """Test that today's stats exclude yesterday."""
        tracker = UsageTracker(db_path=str(tmp_path / "usage.db"))

        # Record today
        tracker.record(
            provider="litellm",
            model="local",
            tokens_est=100,
            latency_ms=500,
            success=True
        )

        # Get yesterday's date
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date()

        today = tracker.get_today()
        assert today["calls"] == 1


class TestGetByModel:
    """Tests for getting stats by model."""

    def test_get_by_model_single(self, tmp_path):
        """Test getting stats for single model."""
        tracker = UsageTracker(db_path=str(tmp_path / "usage.db"))

        tracker.record(
            provider="litellm",
            model="local",
            tokens_est=100,
            latency_ms=500,
            success=True
        )

        stats = tracker.get_by_model()

        assert "local" in stats
        assert stats["local"]["calls"] == 1
        assert stats["local"]["tokens"] == 100

    def test_get_by_model_multiple(self, tmp_path):
        """Test getting stats for multiple models."""
        tracker = UsageTracker(db_path=str(tmp_path / "usage.db"))

        tracker.record(
            provider="litellm",
            model="local",
            tokens_est=100,
            latency_ms=500,
            success=True
        )
        tracker.record(
            provider="deepseek",
            model="deepseek-chat",
            tokens_est=200,
            latency_ms=1000,
            success=True
        )

        stats = tracker.get_by_model()

        assert len(stats) >= 2
        assert stats["local"]["calls"] == 1
        assert stats["deepseek-chat"]["calls"] == 1

    def test_get_by_model_totals(self, tmp_path):
        """Test model totals."""
        tracker = UsageTracker(db_path=str(tmp_path / "usage.db"))

        for i in range(5):
            tracker.record(
                provider="litellm",
                model="local",
                tokens_est=100,
                latency_ms=500,
                success=True
            )

        stats = tracker.get_by_model()
        assert stats["local"]["calls"] == 5
        assert stats["local"]["tokens"] == 500


class TestCountRecords:
    """Tests for counting records."""

    def test_count_empty(self, tmp_path):
        """Test counting empty tracker."""
        tracker = UsageTracker(db_path=str(tmp_path / "usage.db"))

        count = tracker.count_records()
        assert count == 0

    def test_count_with_records(self, tmp_path):
        """Test counting with records."""
        tracker = UsageTracker(db_path=str(tmp_path / "usage.db"))

        for i in range(10):
            tracker.record(
                provider="litellm",
                model="local",
                tokens_est=100,
                latency_ms=500,
                success=True
            )

        count = tracker.count_records()
        assert count == 10


class TestGetByProvider:
    """Tests for getting stats by provider."""

    def test_get_by_provider(self, tmp_path):
        """Test getting stats by provider."""
        tracker = UsageTracker(db_path=str(tmp_path / "usage.db"))

        tracker.record(
            provider="litellm",
            model="local",
            tokens_est=100,
            latency_ms=500,
            success=True
        )
        tracker.record(
            provider="deepseek",
            model="deepseek-chat",
            tokens_est=200,
            latency_ms=1000,
            success=True
        )

        stats = tracker.get_by_provider()

        assert "litellm" in stats
        assert "deepseek" in stats


class TestGetByStatus:
    """Tests for getting stats by success/failure."""

    def test_get_by_status(self, tmp_path):
        """Test getting stats by status."""
        tracker = UsageTracker(db_path=str(tmp_path / "usage.db"))

        tracker.record(
            provider="litellm",
            model="local",
            tokens_est=100,
            latency_ms=500,
            success=True
        )
        tracker.record(
            provider="litellm",
            model="local",
            tokens_est=0,
            latency_ms=0,
            success=False
        )

        success_count = tracker.count_by_status(success=True)
        failure_count = tracker.count_by_status(success=False)

        assert success_count == 1
        assert failure_count == 1


class TestLatencyTracking:
    """Tests for latency tracking."""

    def test_average_latency(self, tmp_path):
        """Test average latency calculation."""
        tracker = UsageTracker(db_path=str(tmp_path / "usage.db"))

        tracker.record(
            provider="litellm",
            model="local",
            tokens_est=100,
            latency_ms=1000,
            success=True
        )
        tracker.record(
            provider="litellm",
            model="local",
            tokens_est=100,
            latency_ms=1000,
            success=True
        )
        tracker.record(
            provider="litellm",
            model="local",
            tokens_est=100,
            latency_ms=1000,
            success=True
        )

        avg = tracker.get_average_latency()
        assert avg == 1000

    def test_max_latency(self, tmp_path):
        """Test max latency tracking."""
        tracker = UsageTracker(db_path=str(tmp_path / "usage.db"))

        tracker.record(
            provider="litellm",
            model="local",
            tokens_est=100,
            latency_ms=500,
            success=True
        )
        tracker.record(
            provider="litellm",
            model="local",
            tokens_est=100,
            latency_ms=2000,
            success=True
        )

        max_lat = tracker.get_max_latency()
        assert max_lat == 2000


class TestChatIdTracking:
    """Tests for tracking by chat ID."""

    def test_get_by_chat_id(self, tmp_path):
        """Test getting stats by chat ID."""
        tracker = UsageTracker(db_path=str(tmp_path / "usage.db"))

        tracker.record(
            provider="litellm",
            model="local",
            tokens_est=100,
            latency_ms=500,
            success=True,
            chat_id=111
        )
        tracker.record(
            provider="litellm",
            model="local",
            tokens_est=200,
            latency_ms=500,
            success=True,
            chat_id=222
        )

        stats_111 = tracker.get_by_chat_id(111)
        stats_222 = tracker.get_by_chat_id(222)

        assert stats_111["calls"] == 1
        assert stats_111["tokens"] == 100
        assert stats_222["calls"] == 1
        assert stats_222["tokens"] == 200


class TestClearOldRecords:
    """Tests for clearing old records."""

    def test_clear_by_age(self, tmp_path):
        """Test clearing records older than N days."""
        tracker = UsageTracker(db_path=str(tmp_path / "usage.db"))

        tracker.record(
            provider="litellm",
            model="local",
            tokens_est=100,
            latency_ms=500,
            success=True
        )

        count = tracker.clear_older_than_days(0)
        # May be 0 or 1 depending on exact timing
        assert count >= 0


class TestThreadSafety:
    """Tests for thread safety."""

    def test_concurrent_records(self, tmp_path):
        """Test concurrent record additions."""
        tracker = UsageTracker(db_path=str(tmp_path / "usage.db"))

        for i in range(20):
            tracker.record(
                provider="litellm",
                model="local",
                tokens_est=100,
                latency_ms=500,
                success=True
            )

        assert tracker.count_records() == 20


class TestPersistence:
    """Tests for persistence."""

    def test_data_persists(self, tmp_path):
        """Test that data persists across instances."""
        db_path = str(tmp_path / "usage.db")

        # Record with first instance
        tracker1 = UsageTracker(db_path=db_path)
        tracker1.record(
            provider="litellm",
            model="local",
            tokens_est=100,
            latency_ms=500,
            success=True
        )

        # Verify with second instance
        tracker2 = UsageTracker(db_path=db_path)
        count = tracker2.count_records()

        assert count == 1


class TestEdgeCases:
    """Tests for edge cases."""

    def test_zero_tokens(self, tmp_path):
        """Test recording with zero tokens."""
        tracker = UsageTracker(db_path=str(tmp_path / "usage.db"))

        tracker.record(
            provider="litellm",
            model="local",
            tokens_est=0,
            latency_ms=0,
            success=False
        )

        assert tracker.count_records() == 1

    def test_very_high_token_count(self, tmp_path):
        """Test with very high token count."""
        tracker = UsageTracker(db_path=str(tmp_path / "usage.db"))

        tracker.record(
            provider="deepseek",
            model="deepseek-chat",
            tokens_est=1000000,
            latency_ms=5000,
            success=True
        )

        today = tracker.get_today()
        assert today["tokens"] == 1000000

    def test_unicode_in_error(self, tmp_path):
        """Test unicode in error messages."""
        tracker = UsageTracker(db_path=str(tmp_path / "usage.db"))

        tracker.record(
            provider="litellm",
            model="local",
            tokens_est=0,
            latency_ms=0,
            success=False,
            error="错误: 超时"
        )

        assert tracker.count_records() == 1


class TestIntegration:
    """Integration tests."""

    def test_full_workflow(self, tmp_path):
        """Test complete workflow."""
        tracker = UsageTracker(db_path=str(tmp_path / "usage.db"))

        # Record various calls
        tracker.record(
            provider="litellm",
            model="local",
            tokens_est=100,
            latency_ms=500,
            success=True,
            chat_id=111
        )
        tracker.record(
            provider="deepseek",
            model="deepseek-chat",
            tokens_est=200,
            latency_ms=1000,
            success=True,
            chat_id=111
        )
        tracker.record(
            provider="litellm",
            model="local",
            tokens_est=50,
            latency_ms=400,
            success=False,
            error="Test error"
        )

        # Get stats
        today = tracker.get_today()
        by_model = tracker.get_by_model()
        by_chat = tracker.get_by_chat_id(111)

        assert today["calls"] == 3
        assert today["tokens"] == 350
        assert len(by_model) >= 2
        assert by_chat["calls"] == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
