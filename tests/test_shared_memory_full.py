"""Comprehensive tests for agent/memory/shared_memory.py."""

import os
import json
import pytest
from pathlib import Path
from agent.memory.shared_memory import SharedMemory


@pytest.fixture
def memory(tmp_path):
    """Create a SharedMemory with tmp db."""
    db = str(tmp_path / "test_shared_memory.db")
    m = SharedMemory(db_path=db)
    yield m
    m.close()


class TestSharedMemoryInit:
    """Initialization tests."""

    def test_creates_db_file(self, tmp_path):
        db = str(tmp_path / "init_test.db")
        m = SharedMemory(db_path=db)
        assert Path(db).exists()
        m.close()

    def test_creates_parent_directory(self, tmp_path):
        db = str(tmp_path / "subdir" / "test.db")
        m = SharedMemory(db_path=db)
        assert Path(db).parent.exists()
        m.close()

    def test_schema_created(self, memory):
        conn = memory._get_conn()
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = {t["name"] for t in tables}
        assert "preferences" in table_names
        assert "facts" in table_names
        assert "patterns" in table_names
        assert "feedback" in table_names

    def test_wal_mode(self, memory):
        conn = memory._get_conn()
        result = conn.execute("PRAGMA journal_mode").fetchone()
        assert result[0] == "wal"


class TestPreferences:
    """Tests for preference operations."""

    def test_set_and_get(self, memory):
        memory.set_preference("lang", "zh", "chat")
        assert memory.get_preference("lang") == "zh"

    def test_get_default(self, memory):
        assert memory.get_preference("missing", "default") == "default"

    def test_get_none_default(self, memory):
        assert memory.get_preference("missing") is None

    def test_overwrite(self, memory):
        memory.set_preference("lang", "en", "chat")
        memory.set_preference("lang", "zh", "coding")
        assert memory.get_preference("lang") == "zh"

    def test_get_all_preferences(self, memory):
        memory.set_preference("lang", "zh", "chat")
        memory.set_preference("tz", "UTC", "coding")
        prefs = memory.get_all_preferences()
        assert "lang" in prefs
        assert prefs["lang"]["value"] == "zh"
        assert prefs["lang"]["source_mode"] == "chat"
        assert "tz" in prefs

    def test_empty_preferences(self, memory):
        assert memory.get_all_preferences() == {}


class TestFacts:
    """Tests for fact operations."""

    def test_remember_and_recall(self, memory):
        fid = memory.remember_fact("work", "SDE at Google", "chat")
        assert fid > 0
        facts = memory.recall_facts("work")
        assert len(facts) == 1
        assert facts[0]["fact"] == "SDE at Google"
        assert facts[0]["source_mode"] == "chat"

    def test_recall_all(self, memory):
        memory.remember_fact("work", "SDE", "chat")
        memory.remember_fact("edu", "MIT", "coding")
        facts = memory.recall_facts()
        assert len(facts) == 2

    def test_recall_by_category(self, memory):
        memory.remember_fact("work", "SDE", "chat")
        memory.remember_fact("edu", "MIT", "coding")
        work_facts = memory.recall_facts("work")
        assert len(work_facts) == 1

    def test_recall_limit(self, memory):
        for i in range(10):
            memory.remember_fact("cat", f"fact {i}", "chat")
        facts = memory.recall_facts(limit=3)
        assert len(facts) == 3

    def test_recall_order(self, memory):
        memory.remember_fact("cat", "first", "chat")
        memory.remember_fact("cat", "second", "chat")
        facts = memory.recall_facts("cat")
        assert facts[0]["fact"] == "second"  # newest first


class TestPatterns:
    """Tests for pattern operations."""

    def test_record_new_pattern(self, memory):
        memory.record_pattern("frequent_stock", "AAPL", "fin")
        patterns = memory.get_patterns("frequent_stock")
        assert len(patterns) == 1
        assert patterns[0]["count"] == 1

    def test_increment_pattern(self, memory):
        memory.record_pattern("frequent_stock", "AAPL", "fin")
        memory.record_pattern("frequent_stock", "AAPL", "fin")
        memory.record_pattern("frequent_stock", "AAPL", "fin")
        patterns = memory.get_patterns("frequent_stock")
        assert patterns[0]["count"] == 3

    def test_different_patterns(self, memory):
        memory.record_pattern("frequent_stock", "AAPL", "fin")
        memory.record_pattern("frequent_stock", "TSLA", "fin")
        patterns = memory.get_patterns("frequent_stock")
        assert len(patterns) == 2

    def test_pattern_sorted_by_count(self, memory):
        memory.record_pattern("tool", "vim", "coding")
        for _ in range(5):
            memory.record_pattern("tool", "docker", "coding")
        patterns = memory.get_patterns("tool")
        assert patterns[0]["pattern_value"] == "docker"

    def test_get_all_patterns(self, memory):
        memory.record_pattern("stock", "AAPL", "fin")
        memory.record_pattern("tool", "git", "coding")
        all_p = memory.get_all_patterns()
        assert len(all_p) == 2

    def test_get_patterns_limit(self, memory):
        for i in range(20):
            memory.record_pattern("type", f"val{i}", "chat")
        patterns = memory.get_patterns(limit=5)
        assert len(patterns) == 5


class TestFeedback:
    """Tests for feedback operations."""

    def test_record_and_get(self, memory):
        fid = memory.record_feedback("correction", "AAPL not APPL", "chat")
        assert fid > 0
        fb = memory.get_recent_feedback()
        assert len(fb) == 1
        assert fb[0]["content"] == "AAPL not APPL"

    def test_feedback_types(self, memory):
        memory.record_feedback("correction", "fix1", "chat")
        memory.record_feedback("praise", "great!", "fin")
        memory.record_feedback("complaint", "too slow", "coding")
        fb = memory.get_recent_feedback()
        assert len(fb) == 3

    def test_feedback_limit(self, memory):
        for i in range(20):
            memory.record_feedback("correction", f"fb {i}", "chat")
        fb = memory.get_recent_feedback(limit=5)
        assert len(fb) == 5


class TestContextSummary:
    """Tests for get_context_summary()."""

    def test_empty_memory(self, memory):
        summary = memory.get_context_summary("chat")
        assert summary == ""

    def test_includes_preferences(self, memory):
        memory.set_preference("language", "zh", "chat")
        summary = memory.get_context_summary("chat")
        assert "language" in summary
        assert "zh" in summary

    def test_includes_facts(self, memory):
        memory.remember_fact("work", "SDE at Google", "chat")
        summary = memory.get_context_summary("chat")
        assert "SDE at Google" in summary

    def test_includes_patterns(self, memory):
        for _ in range(5):
            memory.record_pattern("frequent_stock", "AAPL", "fin")
        summary = memory.get_context_summary("fin")
        assert "AAPL" in summary

    def test_includes_corrections(self, memory):
        memory.record_feedback("correction", "AAPL not APPL", "chat")
        summary = memory.get_context_summary("chat")
        assert "AAPL not APPL" in summary

    def test_mode_priority(self, memory):
        memory.remember_fact("work", "SDE", "coding")
        summary = memory.get_context_summary("chat")
        # Facts from other modes should have mode hint
        assert "[coding]" in summary

    def test_respects_budget(self, memory):
        # Fill with lots of data
        for i in range(100):
            memory.remember_fact("cat", f"Long fact string number {i} " * 10, "chat")
        summary = memory.get_context_summary("chat", max_tokens=50)
        # Should be limited (rough estimate: 50 tokens * 4 chars = 200 chars)
        # But won't be exact — just verify it doesn't return everything
        assert len(summary) < 10000


class TestUtilities:
    """Tests for utility methods."""

    def test_clear_all(self, memory):
        memory.set_preference("k", "v", "chat")
        memory.remember_fact("cat", "fact", "chat")
        memory.record_pattern("type", "val", "chat")
        memory.record_feedback("type", "content", "chat")
        memory.clear_all()
        stats = memory.get_stats()
        assert all(v == 0 for v in stats.values())

    def test_get_stats(self, memory):
        memory.set_preference("k", "v", "chat")
        memory.remember_fact("cat", "fact", "chat")
        stats = memory.get_stats()
        assert stats["preferences"] == 1
        assert stats["facts"] == 1
        assert stats["patterns"] == 0
        assert stats["feedback"] == 0

    def test_export_json(self, memory):
        memory.set_preference("lang", "zh", "chat")
        memory.remember_fact("work", "SDE", "chat")
        data = memory.export_json()
        assert "preferences" in data
        assert "facts" in data
        assert "patterns" in data
        assert "feedback" in data

    def test_import_json(self, memory, tmp_path):
        # Export from one instance
        memory.set_preference("lang", "zh", "chat")
        memory.remember_fact("work", "SDE", "chat")
        data = memory.export_json()

        # Import to another instance
        db2 = str(tmp_path / "import_test.db")
        m2 = SharedMemory(db_path=db2)
        m2.import_json(data)
        assert m2.get_preference("lang") == "zh"
        facts = m2.recall_facts("work")
        assert len(facts) >= 1
        m2.close()

    def test_close(self, tmp_path):
        db = str(tmp_path / "close_test.db")
        m = SharedMemory(db_path=db)
        m.set_preference("k", "v", "chat")
        m.close()
        # Should not crash on double close
        m.close()


class TestTimestamp:
    """Tests for _now() method."""

    def test_returns_iso_string(self, memory):
        ts = memory._now()
        assert "T" in ts
        assert "+" in ts or "Z" in ts  # Has timezone info


class TestThreadSafety:
    """Tests for thread-local connection."""

    def test_get_conn_returns_connection(self, memory):
        conn = memory._get_conn()
        assert conn is not None

    def test_close_conn(self, memory):
        memory._get_conn()
        memory._close_conn()
        # Should work without error
        assert not hasattr(memory._local, 'conn') or memory._local.conn is None
