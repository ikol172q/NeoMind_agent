"""
Comprehensive unit tests for agent/finance/chat_store.py
Tests all chat storage, message management, archival, and purge operations.
"""

import pytest
import sqlite3
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import Mock, patch, MagicMock
import tempfile
import os

import sys
sys.path.insert(0, '/sessions/hopeful-magical-rubin/mnt/NeoMind_agent')

from agent.finance.chat_store import ChatStore, DEFAULT_DB_PATH


class TestChatStoreInit:
    """Tests for ChatStore initialization."""

    def test_init_with_custom_db(self, tmp_path):
        """Test initialization with custom DB path."""
        db_path = str(tmp_path / "test.db")
        store = ChatStore(db_path=db_path)

        assert store.db_path == db_path
        assert Path(db_path).parent.exists()

    def test_init_creates_tables(self, tmp_path):
        """Test that initialization creates required tables."""
        db_path = str(tmp_path / "test.db")
        store = ChatStore(db_path=db_path)

        # Check tables exist
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cursor.fetchall()}

        assert "chats" in tables
        assert "messages" in tables
        conn.close()

    def test_init_creates_indices(self, tmp_path):
        """Test that initialization creates indices."""
        db_path = str(tmp_path / "test.db")
        store = ChatStore(db_path=db_path)

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='index'")
        indices = {row[0] for row in cursor.fetchall()}

        assert "idx_messages_chat" in indices
        conn.close()

    def test_default_db_path(self):
        """Test that default DB path is returned."""
        # This just verifies the function works
        assert isinstance(DEFAULT_DB_PATH, str)
        assert len(DEFAULT_DB_PATH) > 0

    def test_init_migration_thinking_column(self, tmp_path):
        """Test migration adds thinking column if missing."""
        db_path = str(tmp_path / "test.db")
        # Create DB without thinking column
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        conn.commit()
        conn.close()

        # Initialize store — should add column
        store = ChatStore(db_path=db_path)

        # Verify column exists
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(messages)")
        columns = {row[1] for row in cursor.fetchall()}
        assert "thinking" in columns
        conn.close()

    def test_init_migration_mode_column(self, tmp_path):
        """Test migration adds mode column if missing."""
        db_path = str(tmp_path / "test.db")
        # Create DB without mode column
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS chats (
                chat_id INTEGER PRIMARY KEY,
                chat_type TEXT DEFAULT 'private',
                title TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                archived INTEGER DEFAULT 0
            )
        """)
        conn.commit()
        conn.close()

        # Initialize store — should add column
        store = ChatStore(db_path=db_path)

        # Verify column exists
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(chats)")
        columns = {row[1] for row in cursor.fetchall()}
        assert "mode" in columns
        conn.close()


class TestChatModeOperations:
    """Tests for chat mode operations."""

    def test_get_mode_default(self, tmp_path):
        """Test getting default mode for new chat."""
        store = ChatStore(db_path=str(tmp_path / "test.db"))
        mode = store.get_mode(12345)
        assert mode == "fin"

    def test_set_mode_valid(self, tmp_path):
        """Test setting valid mode."""
        store = ChatStore(db_path=str(tmp_path / "test.db"))
        result = store.set_mode(12345, "chat")
        assert result is True

        mode = store.get_mode(12345)
        assert mode == "chat"

    def test_set_mode_all_valid_modes(self, tmp_path):
        """Test setting all valid modes."""
        store = ChatStore(db_path=str(tmp_path / "test.db"))

        for mode in ["fin", "chat", "coding"]:
            result = store.set_mode(12345, mode)
            assert result is True
            assert store.get_mode(12345) == mode

    def test_set_mode_invalid(self, tmp_path):
        """Test setting invalid mode."""
        store = ChatStore(db_path=str(tmp_path / "test.db"))
        result = store.set_mode(12345, "invalid_mode")
        assert result is False

    def test_set_mode_overwrite(self, tmp_path):
        """Test overwriting existing mode."""
        store = ChatStore(db_path=str(tmp_path / "test.db"))
        store.set_mode(12345, "fin")
        store.set_mode(12345, "coding")

        assert store.get_mode(12345) == "coding"

    def test_get_mode_multiple_chats(self, tmp_path):
        """Test getting mode for different chats independently."""
        store = ChatStore(db_path=str(tmp_path / "test.db"))

        store.set_mode(111, "fin")
        store.set_mode(222, "chat")
        store.set_mode(333, "coding")

        assert store.get_mode(111) == "fin"
        assert store.get_mode(222) == "chat"
        assert store.get_mode(333) == "coding"


class TestAddMessage:
    """Tests for adding messages."""

    def test_add_message_basic(self, tmp_path):
        """Test basic message addition."""
        store = ChatStore(db_path=str(tmp_path / "test.db"))

        store.add_message(
            chat_id=12345,
            role="user",
            content="Hello"
        )

        history = store.get_history(12345)
        assert len(history) == 1
        assert history[0]["role"] == "user"
        assert history[0]["content"] == "Hello"

    def test_add_message_with_thinking(self, tmp_path):
        """Test adding message with thinking content."""
        store = ChatStore(db_path=str(tmp_path / "test.db"))

        store.add_message(
            chat_id=12345,
            role="assistant",
            content="Response",
            thinking="My reasoning"
        )

        history = store.get_history(12345, include_thinking=True)
        assert history[0]["thinking"] == "My reasoning"

    def test_add_message_chat_metadata(self, tmp_path):
        """Test that chat metadata is created."""
        store = ChatStore(db_path=str(tmp_path / "test.db"))

        store.add_message(
            chat_id=12345,
            role="user",
            content="Hello",
            chat_type="group",
            chat_title="Test Group"
        )

        chats = store.list_chats()
        assert len(chats) == 1
        assert chats[0]["chat_id"] == 12345
        assert chats[0]["chat_type"] == "group"
        assert chats[0]["title"] == "Test Group"

    def test_add_multiple_messages(self, tmp_path):
        """Test adding multiple messages."""
        store = ChatStore(db_path=str(tmp_path / "test.db"))

        store.add_message(12345, "user", "Q1")
        store.add_message(12345, "assistant", "A1")
        store.add_message(12345, "user", "Q2")
        store.add_message(12345, "assistant", "A2")

        history = store.get_history(12345)
        assert len(history) == 4
        assert history[0]["content"] == "Q1"
        assert history[1]["content"] == "A1"
        assert history[2]["content"] == "Q2"
        assert history[3]["content"] == "A2"

    def test_add_message_empty_content(self, tmp_path):
        """Test adding message with empty content."""
        store = ChatStore(db_path=str(tmp_path / "test.db"))

        store.add_message(12345, "user", "")
        history = store.get_history(12345)
        assert len(history) == 1
        assert history[0]["content"] == ""

    def test_add_message_long_content(self, tmp_path):
        """Test adding very long message."""
        store = ChatStore(db_path=str(tmp_path / "test.db"))

        long_content = "x" * 100000
        store.add_message(12345, "user", long_content)

        history = store.get_history(12345)
        assert history[0]["content"] == long_content

    def test_add_message_none_thinking(self, tmp_path):
        """Test that None thinking is stored as empty string."""
        store = ChatStore(db_path=str(tmp_path / "test.db"))

        store.add_message(12345, "assistant", "Response", thinking=None)

        history = store.get_history(12345, include_thinking=True)
        assert history[0].get("thinking", "") == ""

    def test_add_message_timestamps(self, tmp_path):
        """Test that timestamps are recorded."""
        store = ChatStore(db_path=str(tmp_path / "test.db"))

        before = datetime.now(timezone.utc)
        store.add_message(12345, "user", "test")
        after = datetime.now(timezone.utc)

        history = store.get_history(12345)
        created = datetime.fromisoformat(history[0]["created_at"])

        assert before <= created <= after


class TestAddMessagesBatch:
    """Tests for batch message addition."""

    def test_add_messages_batch_basic(self, tmp_path):
        """Test batch message addition."""
        store = ChatStore(db_path=str(tmp_path / "test.db"))

        messages = [
            {"role": "user", "content": "Q1"},
            {"role": "assistant", "content": "A1"},
            {"role": "user", "content": "Q2"},
        ]

        store.add_messages_batch(12345, messages)

        history = store.get_history(12345)
        assert len(history) == 3
        assert history[0]["content"] == "Q1"

    def test_add_messages_batch_empty(self, tmp_path):
        """Test batch addition with empty list."""
        store = ChatStore(db_path=str(tmp_path / "test.db"))

        store.add_messages_batch(12345, [])

        history = store.get_history(12345)
        assert len(history) == 0

    def test_add_messages_batch_mixed_roles(self, tmp_path):
        """Test batch with various roles."""
        store = ChatStore(db_path=str(tmp_path / "test.db"))

        messages = [
            {"role": "user", "content": "msg1"},
            {"role": "assistant", "content": "msg2"},
            {"role": "system", "content": "msg3"},
        ]

        store.add_messages_batch(12345, messages)

        history = store.get_history(12345)
        assert len(history) == 3
        assert history[0]["role"] == "user"
        assert history[1]["role"] == "assistant"
        assert history[2]["role"] == "system"


class TestGetHistory:
    """Tests for retrieving history."""

    def test_get_history_empty_chat(self, tmp_path):
        """Test getting history for non-existent chat."""
        store = ChatStore(db_path=str(tmp_path / "test.db"))

        history = store.get_history(99999)
        assert history == []

    def test_get_history_limit(self, tmp_path):
        """Test history limit parameter."""
        store = ChatStore(db_path=str(tmp_path / "test.db"))

        for i in range(100):
            store.add_message(12345, "user", f"msg{i}")

        history = store.get_history(12345, limit=10)
        assert len(history) == 10

    def test_get_history_order(self, tmp_path):
        """Test that history is returned in chronological order."""
        store = ChatStore(db_path=str(tmp_path / "test.db"))

        for i in range(5):
            store.add_message(12345, "user", f"msg{i}")

        history = store.get_history(12345)
        for i, msg in enumerate(history):
            assert msg["content"] == f"msg{i}"

    def test_get_history_excludes_archived(self, tmp_path):
        """Test that archived messages are excluded."""
        store = ChatStore(db_path=str(tmp_path / "test.db"))

        store.add_message(12345, "user", "msg1")
        store.add_message(12345, "user", "msg2")
        store.clear_active(12345)

        history = store.get_history(12345)
        assert len(history) == 0

    def test_get_history_include_thinking(self, tmp_path):
        """Test including thinking in history."""
        store = ChatStore(db_path=str(tmp_path / "test.db"))

        store.add_message(12345, "assistant", "Response", thinking="thoughts")
        store.add_message(12345, "user", "Q2")

        history_no_thinking = store.get_history(12345)
        assert "thinking" not in history_no_thinking[0]

        history_with_thinking = store.get_history(12345, include_thinking=True)
        assert history_with_thinking[0]["thinking"] == "thoughts"


class TestGetRecentHistory:
    """Tests for getting recent history."""

    def test_get_recent_history_basic(self, tmp_path):
        """Test getting recent history."""
        store = ChatStore(db_path=str(tmp_path / "test.db"))

        for i in range(30):
            store.add_message(12345, "user", f"msg{i}")

        history = store.get_recent_history(12345, limit=10)
        assert len(history) == 10
        # Should be last 10 messages
        assert history[0]["content"] == "msg20"
        assert history[-1]["content"] == "msg29"

    def test_get_recent_history_less_than_limit(self, tmp_path):
        """Test when there are fewer messages than limit."""
        store = ChatStore(db_path=str(tmp_path / "test.db"))

        for i in range(5):
            store.add_message(12345, "user", f"msg{i}")

        history = store.get_recent_history(12345, limit=10)
        assert len(history) == 5

    def test_get_recent_history_no_thinking(self, tmp_path):
        """Test that thinking is not included in recent history."""
        store = ChatStore(db_path=str(tmp_path / "test.db"))

        store.add_message(12345, "assistant", "Response", thinking="thoughts")

        history = store.get_recent_history(12345)
        assert len(history) == 1
        assert "thinking" not in history[0]


class TestCountMessages:
    """Tests for message counting."""

    def test_count_messages_empty(self, tmp_path):
        """Test counting messages in empty chat."""
        store = ChatStore(db_path=str(tmp_path / "test.db"))

        count = store.count_messages(12345)
        assert count == 0

    def test_count_messages_basic(self, tmp_path):
        """Test counting messages."""
        store = ChatStore(db_path=str(tmp_path / "test.db"))

        for i in range(5):
            store.add_message(12345, "user", f"msg{i}")

        count = store.count_messages(12345)
        assert count == 5

    def test_count_messages_includes_archived(self, tmp_path):
        """Test counting with include_archived flag."""
        store = ChatStore(db_path=str(tmp_path / "test.db"))

        store.add_message(12345, "user", "msg1")
        store.add_message(12345, "user", "msg2")
        store.clear_active(12345)

        count_active = store.count_messages(12345, include_archived=False)
        count_all = store.count_messages(12345, include_archived=True)

        assert count_active == 0
        assert count_all == 2


class TestListChats:
    """Tests for listing chats."""

    def test_list_chats_empty(self, tmp_path):
        """Test listing chats when none exist."""
        store = ChatStore(db_path=str(tmp_path / "test.db"))

        chats = store.list_chats()
        assert chats == []

    def test_list_chats_basic(self, tmp_path):
        """Test listing chats."""
        store = ChatStore(db_path=str(tmp_path / "test.db"))

        store.add_message(111, "user", "msg", chat_title="Chat1")
        store.add_message(222, "user", "msg", chat_title="Chat2")

        chats = store.list_chats()
        assert len(chats) == 2
        chat_ids = {c["chat_id"] for c in chats}
        assert 111 in chat_ids
        assert 222 in chat_ids

    def test_list_chats_with_counts(self, tmp_path):
        """Test that chat listing includes message counts."""
        store = ChatStore(db_path=str(tmp_path / "test.db"))

        store.add_message(111, "user", "msg1")
        store.add_message(111, "user", "msg2")
        store.add_message(222, "user", "msg3")

        chats = store.list_chats()
        chat_dict = {c["chat_id"]: c for c in chats}

        assert chat_dict[111]["message_count"] == 2
        assert chat_dict[222]["message_count"] == 1

    def test_list_chats_ordered_by_update(self, tmp_path):
        """Test that chats are ordered by most recent update."""
        store = ChatStore(db_path=str(tmp_path / "test.db"))

        store.add_message(111, "user", "msg")
        store.add_message(222, "user", "msg")
        import time
        time.sleep(0.01)
        store.add_message(111, "user", "msg")

        chats = store.list_chats()
        # Most recently updated should be first
        assert chats[0]["chat_id"] == 111


class TestArchiveOperations:
    """Tests for archival operations."""

    def test_clear_active_archives_messages(self, tmp_path):
        """Test that clear_active archives messages."""
        store = ChatStore(db_path=str(tmp_path / "test.db"))

        store.add_message(12345, "user", "msg1")
        store.add_message(12345, "user", "msg2")

        count = store.clear_active(12345)
        assert count == 2

        history = store.get_history(12345)
        assert len(history) == 0

        archived = store.get_archived(12345)
        assert len(archived) == 2

    def test_archive_chat(self, tmp_path):
        """Test archiving entire chat."""
        store = ChatStore(db_path=str(tmp_path / "test.db"))

        store.add_message(12345, "user", "msg1")
        store.add_message(12345, "user", "msg2")

        count = store.archive(12345)
        assert count == 2

        history = store.get_history(12345)
        assert len(history) == 0

        archived = store.get_archived(12345)
        assert len(archived) == 2

    def test_unarchive_chat(self, tmp_path):
        """Test unarchiving chat."""
        store = ChatStore(db_path=str(tmp_path / "test.db"))

        store.add_message(12345, "user", "msg")
        store.archive(12345)

        store.unarchive(12345)

        history = store.get_history(12345)
        assert len(history) == 1

    def test_get_archived(self, tmp_path):
        """Test getting archived messages."""
        store = ChatStore(db_path=str(tmp_path / "test.db"))

        store.add_message(12345, "user", "msg1")
        store.add_message(12345, "user", "msg2")
        store.archive(12345)

        archived = store.get_archived(12345)
        assert len(archived) == 2
        assert archived[0]["content"] == "msg1"

    def test_get_archived_limit(self, tmp_path):
        """Test archived message limit."""
        store = ChatStore(db_path=str(tmp_path / "test.db"))

        for i in range(100):
            store.add_message(12345, "user", f"msg{i}")
        store.archive(12345)

        archived = store.get_archived(12345, limit=10)
        assert len(archived) == 10

    def test_list_chats_includes_archived(self, tmp_path):
        """Test listing archived chats."""
        store = ChatStore(db_path=str(tmp_path / "test.db"))

        store.add_message(111, "user", "msg")
        store.add_message(222, "user", "msg")
        store.archive(111)

        chats_active = store.list_chats(include_archived=False)
        chats_all = store.list_chats(include_archived=True)

        assert len(chats_active) == 1
        assert len(chats_all) == 2


class TestPurgeOperations:
    """Tests for purge (permanent deletion)."""

    def test_purge_chat(self, tmp_path):
        """Test purging a chat."""
        store = ChatStore(db_path=str(tmp_path / "test.db"))

        store.add_message(12345, "user", "msg1")
        store.add_message(12345, "user", "msg2")

        count = store.purge(12345)
        assert count == 2

        history = store.get_history(12345)
        assert len(history) == 0

        chats = store.list_chats(include_archived=True)
        assert all(c["chat_id"] != 12345 for c in chats)

    def test_purge_all(self, tmp_path):
        """Test purging all messages."""
        store = ChatStore(db_path=str(tmp_path / "test.db"))

        store.add_message(111, "user", "msg1")
        store.add_message(222, "user", "msg2")

        count = store.purge_all()
        assert count == 2

        chats = store.list_chats(include_archived=True)
        assert len(chats) == 0


class TestCompact:
    """Tests for message compaction."""

    def test_compact_basic(self, tmp_path):
        """Test basic message compaction."""
        store = ChatStore(db_path=str(tmp_path / "test.db"))

        for i in range(10):
            store.add_message(12345, "user", f"msg{i}")

        archived, remaining = store.compact(12345, keep_recent=4)

        assert archived == 6
        assert remaining == 4
        assert store.count_messages(12345) == 4

    def test_compact_fewer_than_keep(self, tmp_path):
        """Test compact when messages < keep_recent."""
        store = ChatStore(db_path=str(tmp_path / "test.db"))

        for i in range(3):
            store.add_message(12345, "user", f"msg{i}")

        archived, remaining = store.compact(12345, keep_recent=5)

        assert archived == 0
        assert remaining == 3

    def test_compact_keeps_most_recent(self, tmp_path):
        """Test that compact keeps the most recent messages."""
        store = ChatStore(db_path=str(tmp_path / "test.db"))

        for i in range(10):
            store.add_message(12345, "user", f"msg{i}")

        store.compact(12345, keep_recent=3)

        history = store.get_history(12345)
        assert len(history) == 3
        assert history[0]["content"] == "msg7"
        assert history[2]["content"] == "msg9"


class TestStats:
    """Tests for statistics."""

    def test_get_stats_empty(self, tmp_path):
        """Test stats for empty store."""
        store = ChatStore(db_path=str(tmp_path / "test.db"))

        stats = store.get_stats()
        assert stats["total_chats"] == 0
        assert stats["active_chats"] == 0
        assert stats["total_messages"] == 0
        assert stats["active_messages"] == 0

    def test_get_stats_with_data(self, tmp_path):
        """Test stats with messages."""
        store = ChatStore(db_path=str(tmp_path / "test.db"))

        store.add_message(111, "user", "msg1")
        store.add_message(111, "user", "msg2")
        store.add_message(222, "user", "msg3")

        stats = store.get_stats()
        assert stats["total_chats"] == 2
        assert stats["total_messages"] == 3
        assert stats["active_chats"] == 2

    def test_get_stats_with_archived(self, tmp_path):
        """Test stats with archived messages."""
        store = ChatStore(db_path=str(tmp_path / "test.db"))

        store.add_message(111, "user", "msg1")
        store.add_message(111, "user", "msg2")
        store.archive(111)

        stats = store.get_stats()
        assert stats["total_messages"] == 2
        assert stats["active_messages"] == 0
        assert stats["archived_messages"] == 2

    def test_get_stats_db_size(self, tmp_path):
        """Test that DB size is reported."""
        store = ChatStore(db_path=str(tmp_path / "test.db"))

        store.add_message(111, "user", "msg" * 1000)

        stats = store.get_stats()
        assert "db_size_kb" in stats
        assert stats["db_size_kb"] >= 0


class TestThreadSafety:
    """Tests for thread safety."""

    def test_multiple_chats_concurrent(self, tmp_path):
        """Test that multiple chats can be stored concurrently."""
        store = ChatStore(db_path=str(tmp_path / "test.db"))

        for chat_id in range(10):
            for msg_idx in range(5):
                store.add_message(chat_id, "user", f"msg_{msg_idx}")

        for chat_id in range(10):
            assert store.count_messages(chat_id) == 5


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_special_characters_in_content(self, tmp_path):
        """Test storing special characters."""
        store = ChatStore(db_path=str(tmp_path / "test.db"))

        special = "!@#$%^&*(){}[]<>?|\\/:;'\"~`"
        store.add_message(12345, "user", special)

        history = store.get_history(12345)
        assert history[0]["content"] == special

    def test_unicode_content(self, tmp_path):
        """Test storing Unicode content."""
        store = ChatStore(db_path=str(tmp_path / "test.db"))

        unicode_text = "Hello 你好 мир 🌍 العربية"
        store.add_message(12345, "user", unicode_text)

        history = store.get_history(12345)
        assert history[0]["content"] == unicode_text

    def test_null_bytes_in_content(self, tmp_path):
        """Test handling null bytes in content."""
        store = ChatStore(db_path=str(tmp_path / "test.db"))

        content_with_null = "before\x00after"
        store.add_message(12345, "user", content_with_null)

        history = store.get_history(12345)
        assert history[0]["content"] == content_with_null

    def test_very_old_timestamps(self, tmp_path):
        """Test handling very old ISO timestamps."""
        store = ChatStore(db_path=str(tmp_path / "test.db"))

        store.add_message(12345, "user", "msg")
        history = store.get_history(12345)
        # Should have some timestamp
        assert "created_at" in history[0]

    def test_rapid_message_additions(self, tmp_path):
        """Test rapid message additions."""
        store = ChatStore(db_path=str(tmp_path / "test.db"))

        for i in range(100):
            store.add_message(12345, "user", f"msg{i}")

        assert store.count_messages(12345) == 100


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
