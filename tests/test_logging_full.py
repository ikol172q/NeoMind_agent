"""Comprehensive tests for agent/logging — UnifiedLogger + PIISanitizer."""

import json
import pytest
from pathlib import Path
from datetime import date, timedelta

from agent.logging.pii_sanitizer import PIISanitizer
from agent.logging.unified_logger import UnifiedLogger, get_unified_logger


# ══════════════════════════════════════════════════════════════════════
# PIISanitizer Tests
# ══════════════════════════════════════════════════════════════════════

class TestPIISanitizerInit:
    """Initialization tests."""

    def test_strict_mode(self):
        s = PIISanitizer(mode="strict")
        assert s.mode == "strict"

    def test_normal_mode(self):
        s = PIISanitizer(mode="normal")
        assert s.mode == "normal"


class TestPIISanitize:
    """Tests for sanitize() method."""

    def test_email_redacted(self):
        s = PIISanitizer(mode="strict")
        result = s.sanitize("Contact user@example.com for info")
        assert "[REDACTED_EMAIL]" in result
        assert "user@example.com" not in result

    def test_us_phone_redacted(self):
        s = PIISanitizer(mode="strict")
        result = s.sanitize("Call 555-123-4567")
        assert "[REDACTED_PHONE]" in result

    def test_cn_phone_redacted(self):
        s = PIISanitizer(mode="strict")
        result = s.sanitize("手机 13812345678")
        assert "[REDACTED_PHONE]" in result

    def test_credit_card_redacted(self):
        s = PIISanitizer(mode="strict")
        result = s.sanitize("Card: 4111111111111111")
        assert "[REDACTED_CC]" in result

    def test_ssn_redacted(self):
        s = PIISanitizer(mode="strict")
        result = s.sanitize("SSN: 123-45-6789")
        assert "[REDACTED_SSN]" in result

    def test_api_key_redacted(self):
        s = PIISanitizer(mode="strict")
        result = s.sanitize("key: sk-abc12345678")
        assert "[REDACTED_KEY]" in result

    def test_ipv4_redacted(self):
        s = PIISanitizer(mode="strict")
        result = s.sanitize("Server at 192.168.1.100")
        assert "[REDACTED_IP]" in result

    def test_normal_mode_no_redaction(self):
        s = PIISanitizer(mode="normal")
        text = "Email: user@example.com"
        assert s.sanitize(text) == text

    def test_non_string_passthrough(self):
        s = PIISanitizer(mode="strict")
        assert s.sanitize(123) == 123
        assert s.sanitize(None) is None

    def test_no_pii(self):
        s = PIISanitizer(mode="strict")
        text = "Hello world, no PII here"
        assert s.sanitize(text) == text

    def test_multiple_pii_types(self):
        s = PIISanitizer(mode="strict")
        text = "Email: a@b.com, Phone: 555-123-4567, IP: 10.0.0.1"
        result = s.sanitize(text)
        assert "[REDACTED_EMAIL]" in result
        assert "[REDACTED_IP]" in result


class TestPIISanitizeDict:
    """Tests for sanitize_dict()."""

    def test_sanitizes_string_values(self):
        s = PIISanitizer(mode="strict")
        d = {"email": "user@example.com", "count": 5}
        result = s.sanitize_dict(d)
        assert "[REDACTED_EMAIL]" in result["email"]
        assert result["count"] == 5

    def test_nested_dict(self):
        s = PIISanitizer(mode="strict")
        d = {"inner": {"email": "a@b.com"}}
        result = s.sanitize_dict(d)
        assert "[REDACTED_EMAIL]" in result["inner"]["email"]

    def test_list_values(self):
        s = PIISanitizer(mode="strict")
        d = {"emails": ["a@b.com", "c@d.com"]}
        result = s.sanitize_dict(d)
        assert all("[REDACTED_EMAIL]" in v for v in result["emails"])

    def test_non_dict_input(self):
        s = PIISanitizer(mode="strict")
        assert s.sanitize_dict("not a dict") == "not a dict"
        assert s.sanitize_dict(42) == 42


class TestPIIDetect:
    """Tests for detect() method."""

    def test_detects_email(self):
        s = PIISanitizer()
        findings = s.detect("Contact user@example.com")
        assert any(f[0] == "email" for f in findings)

    def test_detects_multiple(self):
        s = PIISanitizer()
        findings = s.detect("Email: a@b.com, SSN: 123-45-6789")
        types = [f[0] for f in findings]
        assert "email" in types

    def test_no_pii_returns_empty(self):
        s = PIISanitizer()
        assert s.detect("Hello world") == []

    def test_non_string_returns_empty(self):
        s = PIISanitizer()
        assert s.detect(123) == []


class TestPIIScanMessage:
    """Tests for scan_message() method."""

    def test_has_pii(self):
        s = PIISanitizer()
        has_pii, warnings = s.scan_message("Email: user@example.com")
        assert has_pii is True
        assert len(warnings) > 0
        assert any("email" in w for w in warnings)

    def test_no_pii(self):
        s = PIISanitizer()
        has_pii, warnings = s.scan_message("Safe text")
        assert has_pii is False
        assert warnings == []

    def test_non_string(self):
        s = PIISanitizer()
        has_pii, warnings = s.scan_message(None)
        assert has_pii is False


class TestPIIGetStats:
    """Tests for get_stats() method."""

    def test_counts_pii(self):
        s = PIISanitizer()
        stats = s.get_stats("a@b.com and c@d.com")
        assert stats.get("email", 0) >= 2

    def test_empty_text(self):
        s = PIISanitizer()
        assert s.get_stats("no pii") == {}


# ══════════════════════════════════════════════════════════════════════
# UnifiedLogger Tests
# ══════════════════════════════════════════════════════════════════════

@pytest.fixture
def logger(tmp_path):
    log_dir = str(tmp_path / "logs")
    return UnifiedLogger(log_dir=log_dir)


class TestUnifiedLoggerInit:
    """Initialization tests."""

    def test_creates_log_directory(self, tmp_path):
        log_dir = str(tmp_path / "new_logs")
        UnifiedLogger(log_dir=log_dir)
        assert Path(log_dir).exists()

    def test_has_sanitizer(self, logger):
        assert logger._sanitizer is not None
        assert isinstance(logger._sanitizer, PIISanitizer)


class TestLogGeneric:
    """Tests for log() method."""

    def test_creates_log_file(self, logger):
        logger.log("test_type", mode="chat", data="value")
        today = date.today().isoformat()
        log_file = logger.log_dir / f"{today}.jsonl"
        assert log_file.exists()

    def test_log_entry_format(self, logger):
        logger.log("test_type", mode="chat", key1="value1")
        today = date.today().isoformat()
        log_file = logger.log_dir / f"{today}.jsonl"
        lines = log_file.read_text(encoding="utf-8").strip().split("\n")
        entry = json.loads(lines[-1])
        assert entry["type"] == "test_type"
        assert entry["mode"] == "chat"
        assert entry["key1"] == "value1"
        assert "ts" in entry

    def test_sanitizes_pii(self, logger):
        logger.log("test", mode="chat", email="user@example.com")
        today = date.today().isoformat()
        log_file = logger.log_dir / f"{today}.jsonl"
        content = log_file.read_text(encoding="utf-8")
        assert "user@example.com" not in content
        assert "[REDACTED_EMAIL]" in content


class TestLogSpecialized:
    """Tests for specialized log methods."""

    def test_log_llm_call(self, logger):
        logger.log_llm_call(
            model="deepseek-chat",
            prompt_tokens=100,
            completion_tokens=50,
            latency_ms=500.0,
            mode="coding",
        )
        today = date.today().isoformat()
        log_file = logger.log_dir / f"{today}.jsonl"
        entry = json.loads(log_file.read_text(encoding="utf-8").strip().split("\n")[-1])
        assert entry["type"] == "llm_call"
        assert entry["model"] == "deepseek-chat"
        assert entry["total_tokens"] == 150

    def test_log_command(self, logger):
        logger.log_command(cmd="ls -la", exit_code=0, duration_ms=50.0, mode="coding")
        today = date.today().isoformat()
        log_file = logger.log_dir / f"{today}.jsonl"
        entry = json.loads(log_file.read_text(encoding="utf-8").strip().split("\n")[-1])
        assert entry["type"] == "command"
        assert entry["cmd"] == "ls -la"
        assert entry["success"] is True

    def test_log_file_op(self, logger):
        logger.log_file_op(operation="write", path="/tmp/test.py", mode="coding")
        today = date.today().isoformat()
        log_file = logger.log_dir / f"{today}.jsonl"
        entry = json.loads(log_file.read_text(encoding="utf-8").strip().split("\n")[-1])
        assert entry["type"] == "file_op"
        assert entry["operation"] == "write"

    def test_log_error(self, logger):
        logger.log_error(error_type="ValueError", message="bad input", severity="error")
        today = date.today().isoformat()
        log_file = logger.log_dir / f"{today}.jsonl"
        entry = json.loads(log_file.read_text(encoding="utf-8").strip().split("\n")[-1])
        assert entry["type"] == "error"
        assert entry["severity"] == "error"

    def test_log_search(self, logger):
        logger.log_search(query="AAPL price", results_count=5, source="web")
        today = date.today().isoformat()
        log_file = logger.log_dir / f"{today}.jsonl"
        entry = json.loads(log_file.read_text(encoding="utf-8").strip().split("\n")[-1])
        assert entry["type"] == "search"
        assert entry["results_count"] == 5

    def test_log_provider_switch(self, logger):
        logger.log_provider_switch(from_provider="deepseek", to_provider="glm")
        today = date.today().isoformat()
        log_file = logger.log_dir / f"{today}.jsonl"
        entry = json.loads(log_file.read_text(encoding="utf-8").strip().split("\n")[-1])
        assert entry["type"] == "provider_switch"
        assert entry["from_provider"] == "deepseek"
        assert entry["to_provider"] == "glm"


class TestQuery:
    """Tests for query() method."""

    def test_query_today(self, logger):
        logger.log("test", mode="chat")
        results = logger.query()
        assert len(results) >= 1

    def test_query_by_type(self, logger):
        logger.log("llm_call", mode="chat")
        logger.log("error", mode="chat")
        results = logger.query(log_type="llm_call")
        assert all(r["type"] == "llm_call" for r in results)

    def test_query_by_mode(self, logger):
        logger.log("test", mode="chat")
        logger.log("test", mode="coding")
        results = logger.query(mode="chat")
        assert all(r["mode"] == "chat" for r in results)

    def test_query_limit(self, logger):
        for i in range(20):
            logger.log("test", mode="chat")
        results = logger.query(limit=5)
        assert len(results) == 5

    def test_query_date_range(self, logger):
        logger.log("test", mode="chat")
        results = logger.query(date_from=date.today(), date_to=date.today())
        assert len(results) >= 1

    def test_query_empty(self, logger):
        results = logger.query(date_from=date.today() - timedelta(days=365))
        # Might be empty or have today's entries
        assert isinstance(results, list)


class TestDailyStats:
    """Tests for get_daily_stats()."""

    def test_stats_today(self, logger):
        logger.log_llm_call("model", 100, 50, 500.0, mode="chat")
        logger.log_error("ValueError", "err", mode="chat")
        logger.log_command("ls", 0, 50.0, mode="coding")
        stats = logger.get_daily_stats()
        assert stats["total_events"] == 3
        assert stats["errors"] == 1
        assert stats["total_tokens"] == 150
        assert stats["total_commands"] == 1

    def test_stats_empty_day(self, logger):
        stats = logger.get_daily_stats(date.today() - timedelta(days=365))
        assert stats["total_events"] == 0

    def test_stats_by_type(self, logger):
        logger.log("llm_call", mode="chat")
        logger.log("llm_call", mode="chat")
        logger.log("error", mode="chat")
        stats = logger.get_daily_stats()
        assert stats["by_type"]["llm_call"] == 2
        assert stats["by_type"]["error"] == 1

    def test_stats_by_mode(self, logger):
        logger.log("test", mode="chat")
        logger.log("test", mode="coding")
        logger.log("test", mode="coding")
        stats = logger.get_daily_stats()
        assert stats["by_mode"]["chat"] == 1
        assert stats["by_mode"]["coding"] == 2


class TestWeeklyStats:
    """Tests for get_weekly_stats()."""

    def test_returns_aggregate(self, logger):
        logger.log("test", mode="chat")
        stats = logger.get_weekly_stats()
        assert "total_events" in stats
        assert "by_type" in stats
        assert "by_mode" in stats
        assert "period" in stats

    def test_empty_week(self, logger):
        stats = logger.get_weekly_stats()
        assert stats["total_events"] >= 0


class TestSearch:
    """Tests for search() method."""

    def test_search_keyword(self, logger):
        logger.log("test", mode="chat", query="AAPL stock price")
        results = logger.search("AAPL")
        assert len(results) >= 1

    def test_search_case_insensitive(self, logger):
        logger.log("test", mode="chat", data="Hello World")
        results = logger.search("hello")
        assert len(results) >= 1

    def test_search_limit(self, logger):
        for i in range(20):
            logger.log("test", mode="chat", data=f"match_{i}")
        results = logger.search("match", limit=5)
        assert len(results) <= 5

    def test_search_no_results(self, logger):
        results = logger.search("nonexistent_12345")
        assert results == []


class TestCleanup:
    """Tests for cleanup_old_logs()."""

    def test_cleanup_old_files(self, logger):
        # Create an old log file
        old_date = (date.today() - timedelta(days=100)).isoformat()
        old_file = logger.log_dir / f"{old_date}.jsonl"
        old_file.write_text('{"type": "test"}\n', encoding="utf-8")
        deleted = logger.cleanup_old_logs(keep_days=90)
        assert deleted >= 1
        assert not old_file.exists()

    def test_keeps_recent_files(self, logger):
        logger.log("test", mode="chat")
        deleted = logger.cleanup_old_logs(keep_days=1)
        assert deleted == 0
        today = date.today().isoformat()
        assert (logger.log_dir / f"{today}.jsonl").exists()


class TestGetAllStats:
    """Tests for get_all_stats()."""

    def test_returns_comprehensive(self, logger):
        logger.log_llm_call("model", 100, 50, 500.0)
        logger.log_error("TypeError", "err")
        stats = logger.get_all_stats()
        assert stats["total_events"] == 2
        assert stats["total_errors"] == 1
        assert stats["total_tokens"] == 150
        assert "log_dir" in stats


class TestGetUnifiedLogger:
    """Tests for get_unified_logger() singleton."""

    def test_returns_logger(self, tmp_path):
        import agent.logging.unified_logger as mod
        mod._logger = None
        logger = get_unified_logger(str(tmp_path / "singleton_logs"))
        assert isinstance(logger, UnifiedLogger)

    def test_singleton(self, tmp_path):
        import agent.logging.unified_logger as mod
        mod._logger = None
        l1 = get_unified_logger(str(tmp_path / "singleton_logs"))
        l2 = get_unified_logger()
        assert l1 is l2
        mod._logger = None  # Cleanup
