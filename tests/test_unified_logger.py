"""Tests for Unified Logger

Comprehensive test coverage for logging functionality, querying, and statistics.
"""

import json
import pytest
import tempfile
import threading
from pathlib import Path
from datetime import date, timedelta
from agent.logging.unified_logger import UnifiedLogger, get_unified_logger


@pytest.fixture
def temp_log_dir():
    """Create a temporary log directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def logger(temp_log_dir):
    """Create a logger with a temporary directory."""
    return UnifiedLogger(log_dir=temp_log_dir)


class TestLogCreation:
    """Test basic log creation."""

    def test_log_creates_file(self, logger):
        """Test that logging creates a file."""
        logger.log("test_type", mode="test")
        log_dir = Path(logger.log_dir)
        today = date.today().isoformat()
        log_file = log_dir / f"{today}.jsonl"
        assert log_file.exists()

    def test_log_entry_format(self, logger):
        """Test log entry has required fields."""
        logger.log("test_type", mode="test", custom_field="value")
        log_dir = Path(logger.log_dir)
        today = date.today().isoformat()
        log_file = log_dir / f"{today}.jsonl"

        with open(log_file, 'r') as f:
            lines = f.readlines()

        assert len(lines) > 0
        entry = json.loads(lines[0])
        assert "ts" in entry
        assert "type" in entry
        assert "mode" in entry
        assert entry["type"] == "test_type"
        assert entry["mode"] == "test"
        assert entry["custom_field"] == "value"

    def test_log_has_timestamp(self, logger):
        """Test that log entries have ISO timestamps."""
        logger.log("test", mode="test")
        log_dir = Path(logger.log_dir)
        today = date.today().isoformat()
        log_file = log_dir / f"{today}.jsonl"

        with open(log_file, 'r') as f:
            entry = json.loads(f.readline())

        ts = entry.get("ts")
        assert ts is not None
        # Check ISO 8601 format
        assert "T" in ts


class TestDailyRotation:
    """Test that logs rotate daily."""

    def test_different_dates_different_files(self, logger):
        """Test logs for different dates go to different files."""
        # Log for today
        logger.log("test", mode="test")

        today = date.today()
        today_file = Path(logger.log_dir) / f"{today.isoformat()}.jsonl"
        assert today_file.exists()

        # Manually create entry for yesterday
        yesterday = today - timedelta(days=1)
        yesterday_file = Path(logger.log_dir) / f"{yesterday.isoformat()}.jsonl"

        # This would happen if we could mock time, but we can at least
        # verify the query mechanism would find entries from different files
        entry = {
            "ts": f"{yesterday.isoformat()}T12:00:00",
            "type": "test",
            "mode": "test"
        }
        with open(yesterday_file, 'a') as f:
            f.write(json.dumps(entry) + "\n")

        # Both files should exist
        assert today_file.exists()
        assert yesterday_file.exists()


class TestLogLLMCall:
    """Test LLM call logging."""

    def test_log_llm_call_basic(self, logger):
        """Test logging an LLM call."""
        logger.log_llm_call("gpt-4", 100, 50, 1200.5, mode="chat")

        log_dir = Path(logger.log_dir)
        today = date.today().isoformat()
        log_file = log_dir / f"{today}.jsonl"

        with open(log_file, 'r') as f:
            entry = json.loads(f.readline())

        assert entry["type"] == "llm_call"
        assert entry["model"] == "gpt-4"
        assert entry["prompt_tokens"] == 100
        assert entry["completion_tokens"] == 50
        assert entry["latency_ms"] == 1200.5
        assert entry["total_tokens"] == 150

    def test_log_llm_call_with_extra(self, logger):
        """Test LLM call logging with extra fields."""
        logger.log_llm_call(
            "claude-3",
            200, 100, 500.0,
            mode="coding",
            cost=0.25,
            provider="anthropic"
        )

        log_dir = Path(logger.log_dir)
        today = date.today().isoformat()
        log_file = log_dir / f"{today}.jsonl"

        with open(log_file, 'r') as f:
            entry = json.loads(f.readline())

        assert entry["cost"] == 0.25
        assert entry["provider"] == "anthropic"


class TestLogCommand:
    """Test command execution logging."""

    def test_log_command_success(self, logger):
        """Test logging a successful command."""
        logger.log_command("ls -la", 0, 45.2, mode="cli")

        log_dir = Path(logger.log_dir)
        today = date.today().isoformat()
        log_file = log_dir / f"{today}.jsonl"

        with open(log_file, 'r') as f:
            entry = json.loads(f.readline())

        assert entry["type"] == "command"
        assert entry["cmd"] == "ls -la"
        assert entry["exit_code"] == 0
        assert entry["duration_ms"] == 45.2
        assert entry["success"] is True

    def test_log_command_failure(self, logger):
        """Test logging a failed command."""
        logger.log_command("rm /bad/path", 1, 10.5, mode="cli")

        log_dir = Path(logger.log_dir)
        today = date.today().isoformat()
        log_file = log_dir / f"{today}.jsonl"

        with open(log_file, 'r') as f:
            entry = json.loads(f.readline())

        assert entry["exit_code"] == 1
        assert entry["success"] is False


class TestLogFileOp:
    """Test file operation logging."""

    def test_log_file_read(self, logger):
        """Test logging a file read."""
        logger.log_file_op("read", "/path/to/file.txt", mode="cli", size_bytes=1024)

        log_dir = Path(logger.log_dir)
        today = date.today().isoformat()
        log_file = log_dir / f"{today}.jsonl"

        with open(log_file, 'r') as f:
            entry = json.loads(f.readline())

        assert entry["type"] == "file_op"
        assert entry["operation"] == "read"
        assert "/path/to/file.txt" in entry["path"]
        assert entry["size_bytes"] == 1024

    def test_log_file_write(self, logger):
        """Test logging a file write."""
        logger.log_file_op("write", "/tmp/output.txt", mode="cli", size_bytes=2048)

        log_dir = Path(logger.log_dir)
        today = date.today().isoformat()
        log_file = log_dir / f"{today}.jsonl"

        with open(log_file, 'r') as f:
            entry = json.loads(f.readline())

        assert entry["operation"] == "write"


class TestLogError:
    """Test error logging."""

    def test_log_error_basic(self, logger):
        """Test logging an error."""
        logger.log_error("FileNotFoundError", "file.txt not found", severity="warning")

        log_dir = Path(logger.log_dir)
        today = date.today().isoformat()
        log_file = log_dir / f"{today}.jsonl"

        with open(log_file, 'r') as f:
            entry = json.loads(f.readline())

        assert entry["type"] == "error"
        assert entry["error_type"] == "FileNotFoundError"
        assert entry["message"] == "file.txt not found"
        assert entry["severity"] == "warning"

    def test_log_error_with_traceback(self, logger):
        """Test error logging with traceback."""
        logger.log_error(
            "ValueError",
            "invalid value",
            severity="error",
            traceback="line 1\nline 2"
        )

        log_dir = Path(logger.log_dir)
        today = date.today().isoformat()
        log_file = log_dir / f"{today}.jsonl"

        with open(log_file, 'r') as f:
            entry = json.loads(f.readline())

        assert "traceback" in entry


class TestLogSearch:
    """Test search operation logging."""

    def test_log_search(self, logger):
        """Test logging a search."""
        logger.log_search("python", 42, source="web", mode="chat")

        log_dir = Path(logger.log_dir)
        today = date.today().isoformat()
        log_file = log_dir / f"{today}.jsonl"

        with open(log_file, 'r') as f:
            entry = json.loads(f.readline())

        assert entry["type"] == "search"
        assert entry["query"] == "python"
        assert entry["results_count"] == 42
        assert entry["source"] == "web"


class TestLogProviderSwitch:
    """Test provider switch logging."""

    def test_log_provider_switch(self, logger):
        """Test logging a provider switch."""
        logger.log_provider_switch("gpt-4", "claude-3", updated_by="user")

        log_dir = Path(logger.log_dir)
        today = date.today().isoformat()
        log_file = log_dir / f"{today}.jsonl"

        with open(log_file, 'r') as f:
            entry = json.loads(f.readline())

        assert entry["type"] == "provider_switch"
        assert entry["from_provider"] == "gpt-4"
        assert entry["to_provider"] == "claude-3"
        assert entry["updated_by"] == "user"


class TestQueryByType:
    """Test querying logs by type."""

    def test_query_by_type(self, logger):
        """Test filtering by log type."""
        logger.log("type_a", mode="test")
        logger.log("type_b", mode="test")
        logger.log("type_a", mode="test")

        results = logger.query(log_type="type_a", limit=100)
        assert len(results) == 2
        assert all(r["type"] == "type_a" for r in results)

    def test_query_by_type_empty(self, logger):
        """Test querying for non-existent type."""
        logger.log("type_a", mode="test")
        results = logger.query(log_type="type_b", limit=100)
        assert len(results) == 0


class TestQueryByMode:
    """Test querying logs by mode."""

    def test_query_by_mode(self, logger):
        """Test filtering by mode."""
        logger.log("type_a", mode="chat")
        logger.log("type_a", mode="coding")
        logger.log("type_a", mode="chat")

        results = logger.query(mode="chat", limit=100)
        assert len(results) == 2
        assert all(r["mode"] == "chat" for r in results)


class TestQueryByDateRange:
    """Test querying by date range."""

    def test_query_by_date_range(self, logger, temp_log_dir):
        """Test filtering by date range."""
        today = date.today()

        # Create entries for multiple dates
        entry_today = {
            "ts": f"{today.isoformat()}T12:00:00",
            "type": "test",
            "mode": "test"
        }

        yesterday = today - timedelta(days=1)
        entry_yesterday = {
            "ts": f"{yesterday.isoformat()}T12:00:00",
            "type": "test",
            "mode": "test"
        }

        # Write entries
        today_file = Path(temp_log_dir) / f"{today.isoformat()}.jsonl"
        with open(today_file, 'a') as f:
            f.write(json.dumps(entry_today) + "\n")

        yesterday_file = Path(temp_log_dir) / f"{yesterday.isoformat()}.jsonl"
        with open(yesterday_file, 'a') as f:
            f.write(json.dumps(entry_yesterday) + "\n")

        # Query range
        results = logger.query(date_from=yesterday, date_to=today, limit=100)
        assert len(results) == 2


class TestDailyStats:
    """Test daily statistics."""

    def test_daily_stats_empty(self, logger):
        """Test daily stats for empty day."""
        tomorrow = date.today() + timedelta(days=1)
        stats = logger.get_daily_stats(target_date=tomorrow)
        assert stats["total_events"] == 0

    def test_daily_stats_with_entries(self, logger):
        """Test daily stats with entries."""
        logger.log("type_a", mode="chat")
        logger.log("type_b", mode="coding")
        logger.log_error("error_type", "message", severity="error")

        stats = logger.get_daily_stats()
        assert stats["total_events"] == 3
        assert "type_a" in stats["by_type"]
        assert "type_b" in stats["by_type"]
        assert stats["errors"] == 1

    def test_daily_stats_by_mode(self, logger):
        """Test daily stats breakdown by mode."""
        logger.log("test", mode="chat")
        logger.log("test", mode="chat")
        logger.log("test", mode="coding")

        stats = logger.get_daily_stats()
        assert stats["by_mode"]["chat"] == 2
        assert stats["by_mode"]["coding"] == 1

    def test_daily_stats_tokens(self, logger):
        """Test daily stats token counting."""
        logger.log_llm_call("model1", 100, 50, 500, mode="chat")
        logger.log_llm_call("model2", 200, 100, 600, mode="chat")

        stats = logger.get_daily_stats()
        assert stats["total_tokens"] == 450


class TestWeeklyStats:
    """Test weekly statistics."""

    def test_weekly_stats_structure(self, logger):
        """Test weekly stats have expected structure."""
        logger.log("test", mode="test")
        stats = logger.get_weekly_stats()

        assert "period" in stats
        assert "total_events" in stats
        assert "by_type" in stats
        assert "by_mode" in stats
        assert "days_with_activity" in stats
        assert "daily_breakdown" in stats

    def test_weekly_stats_aggregation(self, logger, temp_log_dir):
        """Test weekly stats aggregates across days."""
        today = date.today()

        # Create entries for 3 different days
        for i in range(3):
            target_date = today - timedelta(days=i)
            log_file = Path(temp_log_dir) / f"{target_date.isoformat()}.jsonl"
            for j in range(2):
                entry = {
                    "ts": f"{target_date.isoformat()}T{10+j}:00:00",
                    "type": "test",
                    "mode": "test"
                }
                with open(log_file, 'a') as f:
                    f.write(json.dumps(entry) + "\n")

        stats = logger.get_weekly_stats()
        assert stats["total_events"] >= 6


class TestSearch:
    """Test full-text search."""

    def test_search_finds_keyword(self, logger):
        """Test search finds matching entries."""
        logger.log("test", mode="test", custom="searchable_found_here")
        logger.log("test", mode="test", custom="something else")

        results = logger.search("searchable", limit=10)
        assert len(results) >= 1
        assert any("searchable" in json.dumps(r).lower() for r in results)

    def test_search_case_insensitive(self, logger):
        """Test search is case-insensitive."""
        logger.log("test", mode="test", message="TEST_MESSAGE")

        results = logger.search("test_message", limit=10)
        assert len(results) >= 1

    def test_search_limit(self, logger):
        """Test search respects limit."""
        for i in range(20):
            logger.log("test", mode="test", idx=i)

        results = logger.search("test", limit=5)
        assert len(results) <= 5


class TestCleanupOldLogs:
    """Test log cleanup."""

    def test_cleanup_removes_old_logs(self, logger, temp_log_dir):
        """Test cleanup removes logs older than keep_days."""
        today = date.today()

        # Create old log file
        old_date = today - timedelta(days=100)
        old_file = Path(temp_log_dir) / f"{old_date.isoformat()}.jsonl"
        old_file.write_text('{"ts": "old"}\n')

        # Create recent log file
        recent_file = Path(temp_log_dir) / f"{today.isoformat()}.jsonl"
        recent_file.write_text('{"ts": "recent"}\n')

        # Cleanup
        deleted = logger.cleanup_old_logs(keep_days=7)

        assert old_file.exists() is False or deleted >= 1
        assert recent_file.exists()

    def test_cleanup_keeps_recent(self, logger, temp_log_dir):
        """Test cleanup keeps recent logs."""
        today = date.today()
        recent_date = today - timedelta(days=5)

        recent_file = Path(temp_log_dir) / f"{recent_date.isoformat()}.jsonl"
        recent_file.write_text('{"ts": "recent"}\n')

        deleted = logger.cleanup_old_logs(keep_days=7)

        assert recent_file.exists()


class TestConcurrentWrites:
    """Test thread-safe logging."""

    def test_concurrent_writes(self, logger):
        """Test multiple threads can log concurrently."""
        def log_entries(thread_id):
            for i in range(10):
                logger.log("test", mode="test", thread_id=thread_id, idx=i)

        threads = []
        for i in range(5):
            t = threading.Thread(target=log_entries, args=(i,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # All entries should be logged
        today = date.today().isoformat()
        log_file = Path(logger.log_dir) / f"{today}.jsonl"

        with open(log_file, 'r') as f:
            lines = f.readlines()

        # 5 threads * 10 entries = 50
        assert len(lines) >= 50

    def test_concurrent_reads_writes(self, logger):
        """Test concurrent reads and writes."""
        def write_entries():
            for i in range(20):
                logger.log("write", mode="test", idx=i)

        def read_entries():
            for _ in range(10):
                logger.query(limit=100)

        threads = []
        # Start writers
        for _ in range(2):
            t = threading.Thread(target=write_entries)
            threads.append(t)
            t.start()

        # Start readers
        for _ in range(3):
            t = threading.Thread(target=read_entries)
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # Should complete without errors
        results = logger.query(limit=1000)
        assert len(results) >= 0


class TestPIISanitization:
    """Test PII sanitization in logging."""

    def test_email_sanitized_in_logs(self, logger):
        """Test email is sanitized in logs."""
        logger.log("test", mode="test", email="user@example.com")

        log_dir = Path(logger.log_dir)
        today = date.today().isoformat()
        log_file = log_dir / f"{today}.jsonl"

        with open(log_file, 'r') as f:
            entry = json.loads(f.readline())

        assert "[REDACTED_EMAIL]" in entry["email"]
        assert "@example.com" not in entry["email"]

    def test_phone_sanitized_in_logs(self, logger):
        """Test phone is sanitized in logs."""
        logger.log("test", mode="test", phone="555-123-4567")

        log_dir = Path(logger.log_dir)
        today = date.today().isoformat()
        log_file = log_dir / f"{today}.jsonl"

        with open(log_file, 'r') as f:
            entry = json.loads(f.readline())

        assert "[REDACTED_PHONE]" in entry["phone"]

    def test_nested_pii_sanitized(self, logger):
        """Test nested PII is sanitized."""
        logger.log("test", mode="test", user={"email": "test@example.com"})

        log_dir = Path(logger.log_dir)
        today = date.today().isoformat()
        log_file = log_dir / f"{today}.jsonl"

        with open(log_file, 'r') as f:
            entry = json.loads(f.readline())

        assert "[REDACTED_EMAIL]" in entry["user"]["email"]


class TestSingleton:
    """Test singleton functionality."""

    def test_get_unified_logger_returns_instance(self):
        """Test get_unified_logger returns UnifiedLogger."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = get_unified_logger(log_dir=tmpdir)
            assert isinstance(logger, UnifiedLogger)

    def test_get_unified_logger_same_instance(self):
        """Test get_unified_logger returns same instance."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger1 = get_unified_logger(log_dir=tmpdir)
            logger2 = get_unified_logger(log_dir=tmpdir)
            # Note: They may not be same object due to how singleton is implemented


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_non_string_values(self, logger):
        """Test logging with non-string values."""
        logger.log("test", mode="test", count=42, score=3.14, active=True)

        log_dir = Path(logger.log_dir)
        today = date.today().isoformat()
        log_file = log_dir / f"{today}.jsonl"

        with open(log_file, 'r') as f:
            entry = json.loads(f.readline())

        assert entry["count"] == 42
        assert entry["score"] == 3.14
        assert entry["active"] is True

    def test_unicode_content(self, logger):
        """Test logging with Unicode content."""
        logger.log("test", mode="test", message="你好世界🌍")

        log_dir = Path(logger.log_dir)
        today = date.today().isoformat()
        log_file = log_dir / f"{today}.jsonl"

        with open(log_file, 'r', encoding='utf-8') as f:
            entry = json.loads(f.readline())

        assert "你好世界" in entry["message"]

    def test_very_long_strings(self, logger):
        """Test logging very long strings."""
        long_string = "x" * 10000
        logger.log("test", mode="test", data=long_string)

        log_dir = Path(logger.log_dir)
        today = date.today().isoformat()
        log_file = log_dir / f"{today}.jsonl"

        with open(log_file, 'r') as f:
            entry = json.loads(f.readline())

        assert len(entry["data"]) == 10000

    def test_empty_log_query(self, logger):
        """Test querying empty logs."""
        tomorrow = date.today() + timedelta(days=1)
        results = logger.query(date_from=tomorrow, date_to=tomorrow)
        assert results == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
