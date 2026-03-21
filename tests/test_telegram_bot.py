"""
Comprehensive tests for the Telegram bot subsystem.

Covers:
  1. ChatStore — SQLite persistence, per-chat isolation, archive, purge, compact, thinking
  2. MessageRouter — should_respond logic for private/group/mention/auto-detect
  3. Auto-compact — token estimation, threshold triggers, DB-backed compact
  4. AgentCollaborator — domain classification, response decisions
  5. History persistence — simulates container restart (close + reopen DB)

Run: pytest tests/test_telegram_bot.py -v
"""

import os
import sys
import tempfile
import pytest

# Ensure project root is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ═══════════════════════════════════════════════════════════
# 1. ChatStore Tests
# ═══════════════════════════════════════════════════════════

class TestChatStore:
    """Test SQLite chat history store."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        from agent.finance.chat_store import ChatStore
        self.db_path = str(tmp_path / "test_chat.db")
        self.store = ChatStore(db_path=self.db_path)

    def test_add_and_get_messages(self):
        self.store.add_message(100, "user", "hello")
        self.store.add_message(100, "assistant", "hi there!")
        history = self.store.get_history(100)
        assert len(history) == 2
        assert history[0]["role"] == "user"
        assert history[0]["content"] == "hello"
        assert history[1]["role"] == "assistant"
        assert history[1]["content"] == "hi there!"

    def test_per_chat_isolation(self):
        """Different chat_ids should have completely separate histories."""
        self.store.add_message(111, "user", "chat A msg")
        self.store.add_message(222, "user", "chat B msg")
        self.store.add_message(111, "assistant", "reply A")
        self.store.add_message(222, "assistant", "reply B")

        h1 = self.store.get_history(111)
        h2 = self.store.get_history(222)
        assert len(h1) == 2
        assert len(h2) == 2
        assert h1[0]["content"] == "chat A msg"
        assert h2[0]["content"] == "chat B msg"
        # No cross-contamination
        assert all("chat B" not in m["content"] for m in h1)
        assert all("chat A" not in m["content"] for m in h2)

    def test_recent_history_limit(self):
        """get_recent_history should return only the last N messages."""
        for i in range(50):
            self.store.add_message(100, "user", f"msg {i}")
        recent = self.store.get_recent_history(100, limit=5)
        assert len(recent) == 5
        # Should be the LAST 5, in chronological order
        assert recent[0]["content"] == "msg 45"
        assert recent[-1]["content"] == "msg 49"

    def test_thinking_content_stored(self):
        """Thinking (reasoning) content should be stored and retrievable."""
        self.store.add_message(100, "user", "what is BTC?")
        self.store.add_message(
            100, "assistant", "BTC is Bitcoin.",
            thinking="The user asks about BTC. I should explain cryptocurrency basics."
        )

        # Normal history does NOT include thinking
        history = self.store.get_history(100, include_thinking=False)
        assert len(history) == 2
        assert "thinking" not in history[1]

        # With include_thinking=True
        history_full = self.store.get_history(100, include_thinking=True)
        assert history_full[1]["thinking"] == "The user asks about BTC. I should explain cryptocurrency basics."

        # LLM context history never includes thinking
        recent = self.store.get_recent_history(100)
        assert all("thinking" not in m for m in recent)

    def test_clear_archives_not_deletes(self):
        """/clear should archive messages, not delete them."""
        self.store.add_message(100, "user", "msg 1")
        self.store.add_message(100, "assistant", "reply 1")
        self.store.add_message(100, "user", "msg 2")

        count = self.store.clear_active(100)
        assert count == 3

        # Active history is empty
        assert self.store.get_history(100) == []

        # But archived messages still exist
        archived = self.store.get_archived(100)
        assert len(archived) == 3
        assert archived[0]["content"] == "msg 1"

    def test_archive_and_unarchive(self):
        self.store.add_message(100, "user", "before archive")
        self.store.archive(100)
        assert self.store.get_history(100) == []

        self.store.unarchive(100)
        h = self.store.get_history(100)
        assert len(h) == 1
        assert h[0]["content"] == "before archive"

    def test_purge_permanently_deletes(self):
        """/purge should permanently delete, including archived."""
        self.store.add_message(100, "user", "msg")
        self.store.archive(100)
        # Archived exists
        assert len(self.store.get_archived(100)) == 1

        self.store.purge(100)
        # Everything gone
        assert self.store.get_archived(100) == []
        assert self.store.get_history(100) == []
        assert self.store.count_messages(100, include_archived=True) == 0

    def test_purge_all(self):
        self.store.add_message(111, "user", "a")
        self.store.add_message(222, "user", "b")
        count = self.store.purge_all()
        assert count == 2
        assert self.store.get_stats()["total_messages"] == 0

    def test_compact_keeps_recent(self):
        """Compact should archive old messages, keeping only the most recent N."""
        for i in range(20):
            self.store.add_message(100, "user", f"msg {i}")
            self.store.add_message(100, "assistant", f"reply {i}")

        assert self.store.count_messages(100) == 40

        archived_count, remaining = self.store.compact(100, keep_recent=4)
        assert remaining == 4
        assert archived_count == 36

        # The remaining messages should be the most recent
        history = self.store.get_history(100)
        assert len(history) == 4
        assert history[-1]["content"] == "reply 19"

        # Archived messages still in DB
        archived = self.store.get_archived(100)
        assert len(archived) == 36

    def test_persistence_across_reopen(self):
        """Simulates container restart: close DB, reopen, data should survive."""
        self.store.add_message(100, "user", "before restart")
        self.store.add_message(100, "assistant", "ok!", thinking="thinking content")
        self.store.close()

        # Reopen same DB file (simulates container restart)
        from agent.finance.chat_store import ChatStore
        store2 = ChatStore(db_path=self.db_path)
        history = store2.get_history(100, include_thinking=True)
        assert len(history) == 2
        assert history[0]["content"] == "before restart"
        assert history[1]["thinking"] == "thinking content"
        store2.close()

    def test_migration_adds_thinking_column(self):
        """If DB was created without thinking column, migration should add it."""
        import sqlite3
        # Create a DB without thinking column
        old_db = str(self.db_path) + ".old"
        conn = sqlite3.connect(old_db)
        conn.executescript("""
            CREATE TABLE chats (
                chat_id INTEGER PRIMARY KEY,
                chat_type TEXT DEFAULT 'private',
                title TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                archived INTEGER DEFAULT 0
            );
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                archived INTEGER DEFAULT 0
            );
            INSERT INTO chats VALUES (100, 'private', '', '2024-01-01', '2024-01-01', 0);
            INSERT INTO messages (chat_id, role, content, created_at) VALUES (100, 'user', 'old msg', '2024-01-01');
        """)
        conn.commit()
        conn.close()

        # Open with ChatStore — should auto-migrate
        from agent.finance.chat_store import ChatStore
        store = ChatStore(db_path=old_db)
        history = store.get_history(100)
        assert len(history) == 1
        assert history[0]["content"] == "old msg"

        # Should be able to add messages with thinking now
        store.add_message(100, "assistant", "new reply", thinking="some thinking")
        h = store.get_history(100, include_thinking=True)
        assert h[1].get("thinking") == "some thinking"
        store.close()

    def test_stats(self):
        self.store.add_message(100, "user", "a")
        self.store.add_message(100, "assistant", "b")
        self.store.add_message(200, "user", "c")
        self.store.archive(200)

        stats = self.store.get_stats()
        assert stats["total_chats"] == 2
        assert stats["active_chats"] == 1
        assert stats["total_messages"] == 3
        assert stats["active_messages"] == 2
        assert stats["archived_messages"] == 1
        assert stats["db_size_kb"] > 0

    def test_list_chats(self):
        self.store.add_message(100, "user", "a", "private")
        self.store.add_message(200, "user", "b", "group")
        chats = self.store.list_chats()
        assert len(chats) == 2

        # Archive one
        self.store.archive(200)
        active_chats = self.store.list_chats(include_archived=False)
        all_chats = self.store.list_chats(include_archived=True)
        assert len(active_chats) == 1
        assert len(all_chats) == 2

    # -- Per-chat mode --

    def test_per_chat_mode_default(self):
        """New chats should default to 'fin' mode."""
        assert self.store.get_mode(999) == "fin"

    def test_per_chat_mode_set_and_get(self):
        """Each chat has its own independent mode."""
        self.store.set_mode(100, "chat")
        self.store.set_mode(200, "coding")
        self.store.set_mode(300, "fin")

        assert self.store.get_mode(100) == "chat"
        assert self.store.get_mode(200) == "coding"
        assert self.store.get_mode(300) == "fin"

    def test_per_chat_mode_independent(self):
        """Changing one chat's mode doesn't affect others."""
        self.store.set_mode(100, "fin")
        self.store.set_mode(200, "fin")

        self.store.set_mode(100, "chat")
        assert self.store.get_mode(100) == "chat"
        assert self.store.get_mode(200) == "fin"  # unchanged

    def test_per_chat_mode_persists(self):
        """Mode survives DB reopen (container restart)."""
        self.store.set_mode(100, "coding")
        self.store.close()

        from agent.finance.chat_store import ChatStore
        store2 = ChatStore(db_path=self.db_path)
        assert store2.get_mode(100) == "coding"
        store2.close()

    def test_per_chat_mode_rejects_invalid(self):
        assert self.store.set_mode(100, "invalid") is False
        assert self.store.get_mode(100) == "fin"  # unchanged


# ═══════════════════════════════════════════════════════════
# 2. MessageRouter Tests
# ═══════════════════════════════════════════════════════════

class TestMessageRouter:
    """Test Telegram message routing logic."""

    @pytest.fixture(autouse=True)
    def setup(self):
        from agent.finance.telegram_bot import MessageRouter, TelegramConfig
        config = TelegramConfig(auto_finance_detect=True)
        self.router = MessageRouter("neomind_fin_bot", config)

    # -- Direct commands --

    def test_neo_prefix_commands(self):
        assert self.router.should_respond("/neo_stock AAPL", False)[0] is True
        assert self.router.should_respond("/neo news Fed", False)[0] is True
        assert self.router.should_respond("/neo_digest", False)[0] is True

    def test_finance_slash_commands(self):
        for cmd in ["/stock", "/crypto", "/news", "/digest", "/compute",
                    "/portfolio", "/predict", "/alert", "/compare",
                    "/watchlist", "/risk", "/sources", "/chart"]:
            result, reason = self.router.should_respond(f"{cmd} AAPL", False)
            assert result is True, f"{cmd} should trigger response"
            assert reason == "fin_command"

    # -- @mention --

    def test_mention_triggers(self):
        assert self.router.should_respond("@neomind_fin_bot what is AAPL?", False)[0] is True
        assert self.router.should_respond("Hey @neomind_fin_bot 帮我看看A股", False)[0] is True

    def test_mention_case_insensitive(self):
        assert self.router.should_respond("@NEOMIND_FIN_BOT test", False)[0] is True

    # -- Reply to bot --

    def test_reply_to_bot(self):
        result, reason = self.router.should_respond("tell me more", True)
        assert result is True
        assert reason == "reply"

    # -- Private chat --

    def test_private_chat_always_responds(self):
        """In private chat, bot should respond to everything."""
        result, reason = self.router.should_respond("你好", False, is_private=True)
        assert result is True
        assert reason in ("private_chat", "private_finance")

    def test_private_chat_finance_tagged(self):
        """Finance queries in private chat get tagged as private_finance."""
        result, reason = self.router.should_respond("AAPL stock price", False, is_private=True)
        assert result is True
        assert reason == "private_finance"

    # -- Auto-detect in group --

    def test_group_finance_auto_detect(self):
        for query in ["Tesla stock price?", "bitcoin 今天行情怎么样", "$NVDA is pumping"]:
            result, reason = self.router.should_respond(query, False, is_private=False)
            assert result is True, f"Should detect finance in: {query}"
            assert reason == "auto_detect"

    def test_group_non_finance_ignored(self):
        """Non-finance messages in group should NOT trigger response."""
        for query in ["hello everyone", "帮我写个Python脚本", "what is the weather",
                      "好的", "明天见"]:
            result, reason = self.router.should_respond(query, False, is_private=False)
            assert result is False, f"Should NOT respond to: {query}"

    # -- Query extraction --

    def test_extract_neo_prefix(self):
        assert self.router.extract_query("/neo_stock AAPL", "command") == "/stock AAPL"
        assert self.router.extract_query("/neo news Fed rate", "command") == "/news Fed rate"

    def test_extract_mention(self):
        result = self.router.extract_query("@neomind_fin_bot AAPL price?", "mention")
        assert result == "AAPL price?"

    # -- Delegation --

    def test_openclaw_delegation_detected(self):
        assert self.router.should_delegate_to_openclaw("ask @openclaw about weather") is not None
        assert self.router.should_delegate_to_openclaw("叫openclaw帮忙查一下") is not None

    def test_no_delegation_for_normal_queries(self):
        assert self.router.should_delegate_to_openclaw("What is AAPL?") is None
        assert self.router.should_delegate_to_openclaw("hello") is None


# ═══════════════════════════════════════════════════════════
# 3. Token Estimation & Auto-Compact Tests
# ═══════════════════════════════════════════════════════════

class TestAutoCompact:
    """Test token estimation and auto-compact logic."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        from agent.finance.chat_store import ChatStore
        from agent.finance.telegram_bot import NeoMindTelegramBot
        self.db_path = str(tmp_path / "test_compact.db")
        self.store = ChatStore(db_path=self.db_path)

        # We need a bot instance for the estimation methods
        # Create a minimal mock
        class MinimalBot:
            _MODEL_CONTEXT = {"test-model": 1000}
            _store = self.store

            @staticmethod
            def _estimate_tokens(text):
                cn_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
                en_words = len(__import__('re').findall(r'[a-zA-Z]+', text))
                return int(cn_chars * 1.5 + en_words * 0.75 + len(text) * 0.1)

            def _estimate_history_tokens(self, history):
                return sum(self._estimate_tokens(m.get("content", "")) + 4 for m in history)

            def _auto_compact_if_needed_db(self, chat_id, model):
                max_ctx = self._MODEL_CONTEXT.get(model, 128000)
                history = self._store.get_recent_history(chat_id, limit=100)
                used = self._estimate_history_tokens(history)
                pct = used / max_ctx

                if pct >= 0.9 and self._store.count_messages(chat_id) > 4:
                    target_tokens = int(max_ctx * 0.3)
                    keep = max(2, len(history))
                    running = 0
                    for i in range(len(history) - 1, -1, -1):
                        running += self._estimate_tokens(history[i].get("content", "")) + 4
                        if running > target_tokens:
                            keep = len(history) - i - 1
                            break
                    keep = max(keep, 2)
                    archived, remaining = self._store.compact(chat_id, keep_recent=keep)
                    if archived > 0:
                        return f"📦 compacted {archived} msgs"
                    return None

                if pct >= 0.6:
                    return f"⚠️ Context: {pct:.0%}"
                return None

        self.bot = MinimalBot()

    def test_token_estimation_english(self):
        tokens = self.bot._estimate_tokens("Hello world this is a test")
        assert tokens > 0
        assert tokens < 20

    def test_token_estimation_chinese(self):
        tokens = self.bot._estimate_tokens("你好世界这是一个测试")
        assert tokens > 0
        # Chinese should estimate more tokens per char
        en_tokens = self.bot._estimate_tokens("Hello world")
        zh_tokens = self.bot._estimate_tokens("你好世界")
        assert zh_tokens > en_tokens * 0.5  # Chinese is denser

    def test_no_compact_under_60pct(self):
        """Under 60%: no warning, no compact."""
        self.store.add_message(100, "user", "short msg")
        result = self.bot._auto_compact_if_needed_db(100, "test-model")
        assert result is None

    def test_warning_at_60pct(self):
        """Between 60-90%: warning but no compact."""
        # Fill up to ~70% of 1000 tokens
        for i in range(15):
            self.store.add_message(100, "user", f"Message number {i} with some content here " * 2)
        result = self.bot._auto_compact_if_needed_db(100, "test-model")
        if result:
            assert "⚠️" in result or "📦" in result

    def test_compact_at_90pct(self):
        """Over 90%: auto-compact triggered."""
        # Fill well over 90% of 1000 tokens
        for i in range(30):
            self.store.add_message(100, "user", f"A fairly long message number {i} " * 3)
            self.store.add_message(100, "assistant", f"A long reply for message {i} " * 3)

        before_count = self.store.count_messages(100)
        assert before_count == 60

        result = self.bot._auto_compact_if_needed_db(100, "test-model")
        after_count = self.store.count_messages(100)

        # Should have compacted
        assert result is not None
        assert "📦" in result
        assert after_count < before_count

    def test_compact_via_store_directly(self):
        """ChatStore.compact() should keep only the most recent N messages."""
        for i in range(40):
            self.store.add_message(100, "user", f"Message {i} " * 5)

        before = self.store.count_messages(100)
        assert before == 40

        archived, remaining = self.store.compact(100, keep_recent=4)
        assert remaining == 4
        assert archived == 36

        # Remaining should be the most recent
        history = self.store.get_history(100)
        assert len(history) == 4
        assert "Message 39" in history[-1]["content"]

    def test_force_compact_halves(self):
        """Force compact should halve message count."""
        for i in range(20):
            self.store.add_message(100, "user", f"msg {i}")
        assert self.store.count_messages(100) == 20

        # Compact keeping half
        target = 20 // 2
        archived, remaining = self.store.compact(100, keep_recent=target)
        assert remaining == 10
        assert archived == 10

        # Remaining should be the most recent 10
        history = self.store.get_history(100)
        assert history[0]["content"] == "msg 10"
        assert history[-1]["content"] == "msg 19"

    def test_force_compact_refuses_below_minimum(self):
        """Compact with keep_recent=2 should always keep at least 2."""
        self.store.add_message(100, "user", "only one")
        archived, remaining = self.store.compact(100, keep_recent=2)
        # Nothing to archive — only 1 message
        assert archived == 0
        assert remaining == 1


# ═══════════════════════════════════════════════════════════
# 4. AgentCollaborator Tests
# ═══════════════════════════════════════════════════════════

class TestAgentCollaborator:
    """Test inter-agent domain routing."""

    @pytest.fixture(autouse=True)
    def setup(self):
        from agent.finance.agent_collab import AgentCollaborator
        self.collab = AgentCollaborator("neomind_fin_bot")
        self.collab.register_openclaw("openclaw_bot")

    def test_classify_finance_domain(self):
        finance_queries = [
            "What is AAPL stock price?",
            "$BTC is pumping",
            "央行降息了",
            "inflation data today",
            "portfolio rebalancing",
        ]
        for q in finance_queries:
            assert self.collab.classify_domain(q) == "finance", f"Should be finance: {q}"

    def test_classify_general_domain(self):
        general_queries = [
            "help me write python code",
            "check my email",
            "what is the weather",
            "schedule a meeting",
            "代码有bug帮我看看",
        ]
        for q in general_queries:
            assert self.collab.classify_domain(q) == "general", f"Should be general: {q}"

    def test_classify_ambiguous(self):
        assert self.collab.classify_domain("hello") == "ambiguous"
        assert self.collab.classify_domain("thanks") == "ambiguous"

    def test_neomind_responds_to_finance(self):
        result, reason = self.collab.should_i_respond("AAPL stock price?", False, False)
        assert result is True
        assert reason == "finance_domain"

    def test_neomind_silent_for_general(self):
        result, reason = self.collab.should_i_respond("write me a script", False, False)
        assert result is False
        assert reason == "general_domain"

    def test_neomind_responds_to_direct_mention(self):
        result, reason = self.collab.should_i_respond("@neomind hi", True, False)
        assert result is True
        assert reason == "direct"

    def test_handoff_formatting(self):
        msg = self.collab.format_handoff("openclaw_bot", "check the weather")
        assert "@openclaw_bot" in msg
        assert "weather" in msg

    def test_incoming_handoff_parsing(self):
        result = self.collab.parse_incoming_handoff("@neomind_fin_bot /stock AAPL")
        assert result is not None
        assert "/stock AAPL" in result["query"]


# ═══════════════════════════════════════════════════════════
# 5. Container Restart Simulation
# ═══════════════════════════════════════════════════════════

class TestPersistenceAcrossRestart:
    """Simulate container restart: verify all data survives."""

    def test_full_lifecycle(self, tmp_path):
        from agent.finance.chat_store import ChatStore

        db_path = str(tmp_path / "lifecycle.db")

        # === Phase 1: Normal operation ===
        store = ChatStore(db_path=db_path)
        store.add_message(100, "user", "what is BTC?", "private")
        store.add_message(100, "assistant", "BTC is Bitcoin.",
                          thinking="User asks about crypto. Explain basics.")
        store.add_message(100, "user", "and ETH?")
        store.add_message(100, "assistant", "ETH is Ethereum.",
                          thinking="Follow-up about Ethereum.")
        store.add_message(200, "user", "hello", "group")
        store.add_message(200, "assistant", "hi!")

        # Archive chat 200
        store.archive(200)

        stats_before = store.get_stats()
        store.close()

        # === Phase 2: "Container restart" — reopen DB ===
        store2 = ChatStore(db_path=db_path)

        # Active history for chat 100 survives
        h100 = store2.get_history(100, include_thinking=True)
        assert len(h100) == 4
        assert h100[0]["content"] == "what is BTC?"
        assert h100[1]["thinking"] == "User asks about crypto. Explain basics."

        # Chat 200 is still archived
        h200_active = store2.get_history(200)
        assert len(h200_active) == 0  # archived, not visible
        h200_archived = store2.get_archived(200)
        assert len(h200_archived) == 2  # but still in DB

        # Stats match
        stats_after = store2.get_stats()
        assert stats_after["total_messages"] == stats_before["total_messages"]
        assert stats_after["active_messages"] == stats_before["active_messages"]

        # LLM context history works
        recent = store2.get_recent_history(100, limit=2)
        assert len(recent) == 2
        assert recent[-1]["content"] == "ETH is Ethereum."
        # No thinking in LLM context
        assert "thinking" not in recent[-1]

        # Can still add new messages after restart
        store2.add_message(100, "user", "what about SOL?")
        h100_new = store2.get_history(100)
        assert len(h100_new) == 5

        store2.close()

        # === Phase 3: Another restart — purge ===
        store3 = ChatStore(db_path=db_path)
        store3.purge(200)
        assert store3.count_messages(200, include_archived=True) == 0
        # Chat 100 unaffected
        assert store3.count_messages(100) == 5
        store3.close()
