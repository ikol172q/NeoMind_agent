# tests/test_shared_memory.py
"""
Comprehensive test suite for Phase 3 SharedMemory system.

Tests cover:
- CRUD operations for all data types (preferences, facts, patterns, feedback)
- Cross-mode reading (one mode writes, another reads)
- Context summary generation
- SQLite persistence across instances
- Concurrent access safety
- Edge cases and data integrity
"""

import os
import json
import sqlite3
import tempfile
import threading
import time
import pytest
from pathlib import Path

# Import the module under test
from agent.memory import SharedMemory


class TestSharedMemoryPreferences:
    """Test preference storage and retrieval."""

    def test_set_and_get_preference(self):
        """Test basic preference set/get."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = SharedMemory(db_path=os.path.join(tmpdir, "test.db"))

            mem.set_preference("timezone", "UTC", "chat")
            value = mem.get_preference("timezone")
            assert value == "UTC"

            mem.close()

    def test_set_preference_overwrites(self):
        """Test that setting a preference overwrites the previous value."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = SharedMemory(db_path=os.path.join(tmpdir, "test.db"))

            mem.set_preference("language", "en", "chat")
            assert mem.get_preference("language") == "en"

            mem.set_preference("language", "zh", "coding")
            assert mem.get_preference("language") == "zh"

            mem.close()

    def test_get_preference_default(self):
        """Test that get_preference returns default for non-existent key."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = SharedMemory(db_path=os.path.join(tmpdir, "test.db"))

            value = mem.get_preference("nonexistent", "default_value")
            assert value == "default_value"

            mem.close()

    def test_get_all_preferences(self):
        """Test retrieving all preferences with metadata."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = SharedMemory(db_path=os.path.join(tmpdir, "test.db"))

            mem.set_preference("timezone", "UTC", "chat")
            mem.set_preference("language", "en", "chat")
            mem.set_preference("name", "John", "fin")

            prefs = mem.get_all_preferences()
            assert len(prefs) == 3
            assert prefs["timezone"]["value"] == "UTC"
            assert prefs["timezone"]["source_mode"] == "chat"
            assert prefs["language"]["value"] == "en"
            assert prefs["name"]["value"] == "John"
            assert prefs["name"]["source_mode"] == "fin"

            mem.close()

    def test_preference_tracking_source_mode(self):
        """Test that preferences track which mode set them."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = SharedMemory(db_path=os.path.join(tmpdir, "test.db"))

            mem.set_preference("color", "blue", "chat")
            prefs = mem.get_all_preferences()
            assert prefs["color"]["source_mode"] == "chat"

            mem.close()


class TestSharedMemoryFacts:
    """Test fact storage and retrieval."""

    def test_remember_and_recall_fact(self):
        """Test basic fact storage and recall."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = SharedMemory(db_path=os.path.join(tmpdir, "test.db"))

            fact_id = mem.remember_fact("work", "SDE at Google", "chat")
            assert fact_id > 0

            facts = mem.recall_facts()
            assert len(facts) == 1
            assert facts[0]["fact"] == "SDE at Google"
            assert facts[0]["category"] == "work"
            assert facts[0]["source_mode"] == "chat"

            mem.close()

    def test_recall_facts_by_category(self):
        """Test filtering facts by category."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = SharedMemory(db_path=os.path.join(tmpdir, "test.db"))

            mem.remember_fact("work", "SDE at Google", "chat")
            mem.remember_fact("work", "5 years experience", "chat")
            mem.remember_fact("education", "BS Computer Science", "chat")

            work_facts = mem.recall_facts("work")
            assert len(work_facts) == 2
            for fact in work_facts:
                assert fact["category"] == "work"

            edu_facts = mem.recall_facts("education")
            assert len(edu_facts) == 1
            assert edu_facts[0]["fact"] == "BS Computer Science"

            mem.close()

    def test_recall_facts_limit(self):
        """Test that recall respects limit parameter."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = SharedMemory(db_path=os.path.join(tmpdir, "test.db"))

            for i in range(10):
                mem.remember_fact("interests", f"Interest {i}", "chat")

            facts = mem.recall_facts(limit=5)
            assert len(facts) == 5

            mem.close()

    def test_recall_facts_order(self):
        """Test that facts are returned in reverse chronological order."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = SharedMemory(db_path=os.path.join(tmpdir, "test.db"))

            ids = []
            for i in range(3):
                ids.append(mem.remember_fact("test", f"Fact {i}", "chat"))
                time.sleep(0.01)  # Ensure different timestamps

            facts = mem.recall_facts()
            # Should be in reverse order (most recent first)
            assert facts[0]["fact"] == "Fact 2"
            assert facts[1]["fact"] == "Fact 1"
            assert facts[2]["fact"] == "Fact 0"

            mem.close()

    def test_facts_cross_mode_visible(self):
        """Test that facts learned by one mode are visible to others."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem1 = SharedMemory(db_path=os.path.join(tmpdir, "test.db"))

            # Chat mode learns a fact
            mem1.remember_fact("work", "SDE at Google", "chat")
            mem1.close()

            # Coding mode reads it
            mem2 = SharedMemory(db_path=os.path.join(tmpdir, "test.db"))
            facts = mem2.recall_facts("work")
            assert len(facts) == 1
            assert facts[0]["source_mode"] == "chat"
            mem2.close()


class TestSharedMemoryPatterns:
    """Test pattern tracking and retrieval."""

    def test_record_and_get_pattern(self):
        """Test basic pattern recording."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = SharedMemory(db_path=os.path.join(tmpdir, "test.db"))

            mem.record_pattern("frequent_stock", "AAPL", "fin")
            patterns = mem.get_patterns()

            assert len(patterns) == 1
            assert patterns[0]["pattern_value"] == "AAPL"
            assert patterns[0]["count"] == 1

            mem.close()

    def test_pattern_frequency_increments(self):
        """Test that repeated patterns increment count."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = SharedMemory(db_path=os.path.join(tmpdir, "test.db"))

            mem.record_pattern("frequent_stock", "AAPL", "fin")
            mem.record_pattern("frequent_stock", "AAPL", "fin")
            mem.record_pattern("frequent_stock", "AAPL", "fin")

            patterns = mem.get_patterns("frequent_stock")
            assert len(patterns) == 1
            assert patterns[0]["count"] == 3

            mem.close()

    def test_patterns_sorted_by_frequency(self):
        """Test that patterns are returned sorted by frequency."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = SharedMemory(db_path=os.path.join(tmpdir, "test.db"))

            mem.record_pattern("stock", "AAPL", "fin")
            mem.record_pattern("stock", "AAPL", "fin")
            mem.record_pattern("stock", "MSFT", "fin")
            mem.record_pattern("stock", "MSFT", "fin")
            mem.record_pattern("stock", "MSFT", "fin")

            patterns = mem.get_patterns("stock")
            assert patterns[0]["pattern_value"] == "MSFT"  # Most frequent first
            assert patterns[0]["count"] == 3
            assert patterns[1]["pattern_value"] == "AAPL"
            assert patterns[1]["count"] == 2

            mem.close()

    def test_patterns_by_type(self):
        """Test filtering patterns by type."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = SharedMemory(db_path=os.path.join(tmpdir, "test.db"))

            mem.record_pattern("stock", "AAPL", "fin")
            mem.record_pattern("language", "Python", "coding")
            mem.record_pattern("language", "Go", "coding")

            stocks = mem.get_patterns("stock")
            assert len(stocks) == 1
            assert stocks[0]["pattern_type"] == "stock"

            langs = mem.get_patterns("language")
            assert len(langs) == 2
            for p in langs:
                assert p["pattern_type"] == "language"

            mem.close()

    def test_patterns_cross_mode(self):
        """Test patterns recorded by one mode visible to others."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem1 = SharedMemory(db_path=os.path.join(tmpdir, "test.db"))
            mem1.record_pattern("stock", "AAPL", "fin")
            mem1.close()

            mem2 = SharedMemory(db_path=os.path.join(tmpdir, "test.db"))
            patterns = mem2.get_patterns("stock")
            assert len(patterns) == 1
            assert patterns[0]["source_mode"] == "fin"
            mem2.close()


class TestSharedMemoryFeedback:
    """Test feedback storage and retrieval."""

    def test_record_and_get_feedback(self):
        """Test basic feedback recording."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = SharedMemory(db_path=os.path.join(tmpdir, "test.db"))

            fb_id = mem.record_feedback("correction", "AAPL is not APPL", "chat")
            assert fb_id > 0

            feedback = mem.get_recent_feedback()
            assert len(feedback) == 1
            assert feedback[0]["content"] == "AAPL is not APPL"
            assert feedback[0]["feedback_type"] == "correction"

            mem.close()

    def test_feedback_types(self):
        """Test different feedback types."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = SharedMemory(db_path=os.path.join(tmpdir, "test.db"))

            mem.record_feedback("correction", "Fix this", "chat")
            mem.record_feedback("praise", "Great job!", "coding")
            mem.record_feedback("complaint", "Too slow", "fin")

            feedback = mem.get_recent_feedback(limit=10)
            assert len(feedback) == 3

            types = {f["feedback_type"] for f in feedback}
            assert types == {"correction", "praise", "complaint"}

            mem.close()

    def test_feedback_limit(self):
        """Test that get_recent_feedback respects limit."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = SharedMemory(db_path=os.path.join(tmpdir, "test.db"))

            for i in range(15):
                mem.record_feedback("praise", f"Great {i}!", "chat")

            feedback = mem.get_recent_feedback(limit=5)
            assert len(feedback) == 5

            mem.close()

    def test_feedback_recency_order(self):
        """Test that feedback is returned newest first."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = SharedMemory(db_path=os.path.join(tmpdir, "test.db"))

            mem.record_feedback("praise", "First", "chat")
            time.sleep(0.01)
            mem.record_feedback("praise", "Second", "chat")
            time.sleep(0.01)
            mem.record_feedback("praise", "Third", "chat")

            feedback = mem.get_recent_feedback()
            assert feedback[0]["content"] == "Third"
            assert feedback[1]["content"] == "Second"
            assert feedback[2]["content"] == "First"

            mem.close()


class TestSharedMemoryContextSummary:
    """Test context summary generation for LLM injection."""

    def test_context_summary_includes_preferences(self):
        """Test that context summary includes preferences."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = SharedMemory(db_path=os.path.join(tmpdir, "test.db"))

            mem.set_preference("timezone", "UTC", "chat")
            mem.set_preference("language", "en", "chat")

            context = mem.get_context_summary()
            assert "timezone" in context
            assert "UTC" in context

            mem.close()

    def test_context_summary_includes_facts(self):
        """Test that context summary includes facts."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = SharedMemory(db_path=os.path.join(tmpdir, "test.db"))

            mem.remember_fact("work", "SDE at Google", "chat")
            context = mem.get_context_summary()

            assert "SDE at Google" in context

            mem.close()

    def test_context_summary_includes_patterns(self):
        """Test that context summary includes top patterns."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = SharedMemory(db_path=os.path.join(tmpdir, "test.db"))

            mem.record_pattern("stock", "AAPL", "fin")
            mem.record_pattern("stock", "AAPL", "fin")

            context = mem.get_context_summary()
            assert "AAPL" in context

            mem.close()

    def test_context_summary_mode_prioritization(self):
        """Test that context prioritizes current mode's data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = SharedMemory(db_path=os.path.join(tmpdir, "test.db"))

            mem.record_pattern("stock", "AAPL", "fin")
            mem.record_pattern("language", "Python", "coding")

            # In coding mode, should prioritize language patterns
            context_coding = mem.get_context_summary("coding")
            assert "Python" in context_coding

            # In fin mode, should prioritize stock patterns
            context_fin = mem.get_context_summary("fin")
            assert "AAPL" in context_fin

            mem.close()

    def test_context_summary_token_limit(self):
        """Test that context summary respects token limit."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = SharedMemory(db_path=os.path.join(tmpdir, "test.db"))

            # Add lots of data
            for i in range(50):
                mem.remember_fact("test", f"Very long fact number {i} with lots of content", "chat")

            context = mem.get_context_summary(max_tokens=100)
            # Should be roughly under token limit (4 chars per token)
            assert len(context) < 400 + 100  # Some buffer for headers

            mem.close()

    def test_context_summary_handles_empty_memory(self):
        """Test context summary with empty memory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = SharedMemory(db_path=os.path.join(tmpdir, "test.db"))

            context = mem.get_context_summary()
            assert isinstance(context, str)
            # Should be empty or minimal
            assert len(context) < 100

            mem.close()

    def test_context_summary_includes_corrections(self):
        """Test that context summary includes corrections."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = SharedMemory(db_path=os.path.join(tmpdir, "test.db"))

            mem.record_feedback("correction", "Use AAPL not APPL", "chat")
            context = mem.get_context_summary()

            assert "AAPL" in context or "Correction" in context

            mem.close()


class TestSharedMemoryPersistence:
    """Test SQLite persistence and cross-instance access."""

    def test_persistence_across_instances(self):
        """Test that data persists across different instances."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")

            # Instance 1: write data
            mem1 = SharedMemory(db_path=db_path)
            mem1.set_preference("color", "blue", "chat")
            mem1.remember_fact("work", "Engineer", "chat")
            mem1.close()

            # Instance 2: read same data
            mem2 = SharedMemory(db_path=db_path)
            assert mem2.get_preference("color") == "blue"
            facts = mem2.recall_facts("work")
            assert len(facts) == 1
            assert facts[0]["fact"] == "Engineer"
            mem2.close()

    def test_database_file_created(self):
        """Test that database file is created in correct location."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "custom.db")
            mem = SharedMemory(db_path=db_path)
            mem.set_preference("test", "value", "chat")
            mem.close()

            assert os.path.exists(db_path)

    def test_default_db_location(self):
        """Test default database location."""
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["NEOMIND_MEMORY_DIR"] = tmpdir
            mem = SharedMemory()
            mem.set_preference("test", "value", "chat")
            mem.close()

            expected_path = os.path.join(tmpdir, "shared_memory.db")
            assert os.path.exists(expected_path)

            del os.environ["NEOMIND_MEMORY_DIR"]

    def test_schema_created_on_init(self):
        """Test that all tables are created on initialization."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            mem = SharedMemory(db_path=db_path)

            # Check that tables exist
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            tables = cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            table_names = [t[0] for t in tables]

            assert "preferences" in table_names
            assert "facts" in table_names
            assert "patterns" in table_names
            assert "feedback" in table_names

            conn.close()
            mem.close()


class TestSharedMemoryConcurrency:
    """Test concurrent access safety."""

    def test_concurrent_writes(self):
        """Test that concurrent writes are safe."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")

            def writer(mode, count):
                mem = SharedMemory(db_path=db_path)
                for i in range(count):
                    mem.set_preference(f"key_{mode}_{i}", f"value_{i}", mode)
                mem.close()

            threads = []
            for mode in ["chat", "coding", "fin"]:
                t = threading.Thread(target=writer, args=(mode, 10))
                threads.append(t)
                t.start()

            for t in threads:
                t.join()

            # Verify all writes succeeded
            mem = SharedMemory(db_path=db_path)
            prefs = mem.get_all_preferences()
            assert len(prefs) >= 30  # 10 * 3 modes
            mem.close()

    def test_concurrent_read_write(self):
        """Test concurrent reads and writes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")

            def writer(count):
                mem = SharedMemory(db_path=db_path)
                for i in range(count):
                    mem.remember_fact("test", f"Fact {i}", "chat")
                mem.close()

            def reader():
                mem = SharedMemory(db_path=db_path)
                time.sleep(0.05)  # Let writers add some data
                facts = mem.recall_facts()
                assert len(facts) >= 0  # Just check it doesn't crash
                mem.close()

            writer_thread = threading.Thread(target=writer, args=(20,))
            reader_threads = [threading.Thread(target=reader) for _ in range(3)]

            writer_thread.start()
            for t in reader_threads:
                t.start()

            writer_thread.join()
            for t in reader_threads:
                t.join()


class TestSharedMemoryUtilities:
    """Test utility functions."""

    def test_get_stats(self):
        """Test statistics retrieval."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = SharedMemory(db_path=os.path.join(tmpdir, "test.db"))

            mem.set_preference("a", "b", "chat")
            mem.remember_fact("w", "f", "chat")
            mem.record_pattern("t", "v", "chat")
            mem.record_feedback("c", "content", "chat")

            stats = mem.get_stats()
            assert stats["preferences"] == 1
            assert stats["facts"] == 1
            assert stats["patterns"] == 1
            assert stats["feedback"] == 1

            mem.close()

    def test_export_json(self):
        """Test JSON export."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = SharedMemory(db_path=os.path.join(tmpdir, "test.db"))

            mem.set_preference("color", "blue", "chat")
            mem.remember_fact("work", "Engineer", "chat")
            mem.record_pattern("lang", "Python", "coding")

            export = mem.export_json()

            assert "preferences" in export
            assert "facts" in export
            assert "patterns" in export
            assert "feedback" in export
            assert export["preferences"]["color"]["value"] == "blue"

            mem.close()

    def test_import_json(self):
        """Test JSON import."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem1 = SharedMemory(db_path=os.path.join(tmpdir, "test1.db"))
            mem1.set_preference("color", "blue", "chat")
            mem1.remember_fact("work", "Engineer", "chat")
            export = mem1.export_json()
            mem1.close()

            # Import into fresh instance
            mem2 = SharedMemory(db_path=os.path.join(tmpdir, "test2.db"))
            mem2.import_json(export)

            assert mem2.get_preference("color") == "blue"
            facts = mem2.recall_facts("work")
            assert len(facts) == 1

            mem2.close()

    def test_clear_all(self):
        """Test clearing all data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = SharedMemory(db_path=os.path.join(tmpdir, "test.db"))

            mem.set_preference("a", "b", "chat")
            mem.remember_fact("c", "d", "chat")

            mem.clear_all()

            assert len(mem.get_all_preferences()) == 0
            assert len(mem.recall_facts()) == 0

            mem.close()


class TestSharedMemoryEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_recall_facts(self):
        """Test recall with no facts."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = SharedMemory(db_path=os.path.join(tmpdir, "test.db"))
            facts = mem.recall_facts()
            assert facts == []
            mem.close()

    def test_special_characters_in_values(self):
        """Test storing values with special characters."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = SharedMemory(db_path=os.path.join(tmpdir, "test.db"))

            special = "Hello 'world' \"quotes\" and \\ backslash"
            mem.set_preference("test", special, "chat")
            assert mem.get_preference("test") == special

            mem.close()

    def test_unicode_support(self):
        """Test Unicode in all data types."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = SharedMemory(db_path=os.path.join(tmpdir, "test.db"))

            mem.set_preference("name", "张三", "chat")
            mem.remember_fact("work", "在谷歌做工程师", "chat")
            mem.record_pattern("lang", "中文", "chat")

            assert mem.get_preference("name") == "张三"
            facts = mem.recall_facts("work")
            assert facts[0]["fact"] == "在谷歌做工程师"

            mem.close()

    def test_very_long_values(self):
        """Test storing very long text values."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = SharedMemory(db_path=os.path.join(tmpdir, "test.db"))

            long_text = "x" * 10000
            mem.set_preference("long", long_text, "chat")
            assert mem.get_preference("long") == long_text

            mem.close()

    def test_null_handling(self):
        """Test handling of None/null values."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = SharedMemory(db_path=os.path.join(tmpdir, "test.db"))

            # get_preference with None default
            result = mem.get_preference("nonexistent", None)
            assert result is None

            mem.close()

    def test_timestamps_iso8601(self):
        """Test that timestamps are ISO 8601 format."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = SharedMemory(db_path=os.path.join(tmpdir, "test.db"))

            mem.remember_fact("test", "fact", "chat")
            facts = mem.recall_facts()

            # ISO 8601 format includes T and Z or +/-
            timestamp = facts[0]["created_at"]
            assert "T" in timestamp
            assert isinstance(timestamp, str)

            mem.close()


class TestSharedMemoryIntegration:
    """Integration tests across multiple features."""

    def test_three_mode_collaboration(self):
        """Test all three modes working together."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")

            # Chat mode learns about user
            mem_chat = SharedMemory(db_path=db_path)
            mem_chat.set_preference("timezone", "UTC", "chat")
            mem_chat.remember_fact("work", "SDE at Google", "chat")
            mem_chat.close()

            # Coding mode adds patterns and reads context
            mem_coding = SharedMemory(db_path=db_path)
            mem_coding.record_pattern("language", "Python", "coding")
            context = mem_coding.get_context_summary("coding")
            assert "SDE" in context or "Google" in context
            mem_coding.close()

            # Fin mode reads everything
            mem_fin = SharedMemory(db_path=db_path)
            assert mem_fin.get_preference("timezone") == "UTC"
            facts = mem_fin.recall_facts("work")
            assert len(facts) > 0
            patterns = mem_fin.get_patterns("language")
            assert len(patterns) > 0
            mem_fin.close()

    def test_complete_user_profile_building(self):
        """Test building a complete user profile across modes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = SharedMemory(db_path=os.path.join(tmpdir, "test.db"))

            # Preferences
            mem.set_preference("timezone", "America/Los_Angeles", "chat")
            mem.set_preference("language", "en", "chat")
            mem.set_preference("name", "Alice", "chat")

            # Facts
            mem.remember_fact("work", "SDE at Google", "chat")
            mem.remember_fact("education", "BS CS from MIT", "chat")
            mem.remember_fact("interests", "Machine Learning", "chat")

            # Patterns
            mem.record_pattern("frequent_stock", "AAPL", "fin")
            mem.record_pattern("frequent_stock", "AAPL", "fin")
            mem.record_pattern("coding_language", "Python", "coding")
            mem.record_pattern("coding_language", "Python", "coding")
            mem.record_pattern("coding_language", "Python", "coding")

            # Feedback
            mem.record_feedback("praise", "Great analysis", "fin")
            mem.record_feedback("correction", "Fix the spelling", "chat")

            # Generate complete context
            context = mem.get_context_summary("coding")

            # Verify all data types are represented
            assert "America/Los_Angeles" in context or "timezone" in context
            assert "Python" in context or "coding_language" in context

            stats = mem.get_stats()
            assert stats["preferences"] >= 3
            assert stats["facts"] >= 3
            # Patterns: 2 stock + 1 language (increments on same value reduce count)
            assert stats["patterns"] >= 2
            assert stats["feedback"] >= 2

            mem.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
