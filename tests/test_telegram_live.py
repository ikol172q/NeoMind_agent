#!/usr/bin/env python3
"""
Automated Telegram Bot Integration Tests — mocks Telegram objects, calls handlers directly.

No real Telegram API calls needed. Tests the actual handler functions
with simulated Update/Message/Chat objects.

Usage:
    python -m pytest tests/test_telegram_live.py -v

Tests cover all slash commands and verify responses contain expected content.
"""

import os
import sys
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── Mock Telegram Objects ────────────────────────────────────────

def make_update(text: str, chat_id: int = 12345, chat_type: str = "private",
                user_id: int = 99999, first_name: str = "TestUser", is_bot: bool = False):
    """Create a mock Telegram Update with a message."""
    update = MagicMock()
    update.message = MagicMock()
    update.message.text = text
    update.message.chat_id = chat_id
    update.message.chat = MagicMock()
    update.message.chat.type = chat_type
    update.message.chat.send_action = AsyncMock()
    update.message.from_user = MagicMock()
    update.message.from_user.id = user_id
    update.message.from_user.first_name = first_name
    update.message.from_user.is_bot = is_bot
    update.message.reply_to_message = None

    # Capture sent replies
    update.message.reply_text = AsyncMock()

    return update


def make_context(args=None):
    """Create a mock CallbackContext with args."""
    ctx = MagicMock()
    ctx.args = args or []
    return ctx


def get_reply_text(update) -> str:
    """Extract the text from the mock reply_text call."""
    if update.message.reply_text.called:
        call_args = update.message.reply_text.call_args
        if call_args:
            return call_args[0][0] if call_args[0] else call_args[1].get("text", "")
    return ""


# ── Bot Fixture ──────────────────────────────────────────────────

@pytest.fixture
def bot(tmp_path):
    """Create a NeoMindTelegramBot instance with mock store."""
    os.environ.setdefault("DEEPSEEK_API_KEY", "test-key")
    os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123:fake")

    from agent.finance.telegram_bot import NeoMindTelegramBot, TelegramConfig
    from agent.finance.chat_store import ChatStore

    config = TelegramConfig(token="123:fake")
    components = {}

    # Patch ChatStore to use temp DB
    with patch.object(ChatStore, '__init__', lambda self, **kw: None):
        b = MagicMock(spec=NeoMindTelegramBot)

    # Create real bot with temp DB
    b = NeoMindTelegramBot.__new__(NeoMindTelegramBot)
    b.config = config
    b.components = components
    b._skill = None
    b._thinking_enabled = False
    b._app = None
    b._bot_id = 123
    b._last_response_time = {}
    b._last_compact_notice = None

    # Use temp ChatStore
    from agent.finance.chat_store import ChatStore
    b._store = ChatStore(db_path=str(tmp_path / "test.db"))

    return b


# ═══════════════════════════════════════════════════════════
# Command Tests
# ═══════════════════════════════════════════════════════════

class TestHelpCommand:
    @pytest.mark.asyncio
    async def test_help_returns_grouped_commands(self, bot):
        update = make_update("/help")
        ctx = make_context()
        await bot._cmd_help(update, ctx)
        reply = get_reply_text(update)
        assert "对话" in reply
        assert "金融" in reply
        assert "管理" in reply
        assert "/skills" in reply

    @pytest.mark.asyncio
    async def test_help_shows_current_mode(self, bot):
        update = make_update("/help", chat_id=100)
        ctx = make_context()
        await bot._cmd_help(update, ctx)
        reply = get_reply_text(update)
        assert "fin" in reply  # default mode


class TestModeCommand:
    @pytest.mark.asyncio
    async def test_mode_shows_current(self, bot):
        update = make_update("/mode", chat_id=100)
        ctx = make_context()
        await bot._cmd_mode(update, ctx)
        reply = get_reply_text(update)
        assert "fin" in reply
        assert "chat" in reply
        assert "coding" in reply

    @pytest.mark.asyncio
    async def test_mode_switch(self, bot):
        update = make_update("/mode chat", chat_id=100)
        ctx = make_context(["chat"])
        await bot._cmd_mode(update, ctx)
        reply = get_reply_text(update)
        assert "chat" in reply

        # Verify persisted
        assert bot._store.get_mode(100) == "chat"

    @pytest.mark.asyncio
    async def test_mode_invalid(self, bot):
        update = make_update("/mode xyz", chat_id=100)
        ctx = make_context(["xyz"])
        await bot._cmd_mode(update, ctx)
        reply = get_reply_text(update)
        assert "未知" in reply or "❌" in reply

    @pytest.mark.asyncio
    async def test_mode_per_chat(self, bot):
        # Set different modes for different chats
        update1 = make_update("/mode chat", chat_id=100)
        await bot._cmd_mode(update1, make_context(["chat"]))

        update2 = make_update("/mode coding", chat_id=200)
        await bot._cmd_mode(update2, make_context(["coding"]))

        assert bot._store.get_mode(100) == "chat"
        assert bot._store.get_mode(200) == "coding"


class TestThinkCommand:
    @pytest.mark.asyncio
    async def test_think_toggle(self, bot):
        assert bot._thinking_enabled is False

        update = make_update("/think")
        ctx = make_context()
        await bot._cmd_think(update, ctx)
        assert bot._thinking_enabled is True
        reply = get_reply_text(update)
        assert "ON" in reply

        update2 = make_update("/think")
        await bot._cmd_think(update2, ctx)
        assert bot._thinking_enabled is False


class TestClearCommand:
    @pytest.mark.asyncio
    async def test_clear_archives_messages(self, bot):
        # Add some messages
        bot._store.add_message(100, "user", "hello")
        bot._store.add_message(100, "assistant", "hi")
        assert bot._store.count_messages(100) == 2

        update = make_update("/clear", chat_id=100)
        await bot._cmd_clear(update, make_context())

        # Active messages gone
        assert bot._store.count_messages(100) == 0
        # But archived
        assert len(bot._store.get_archived(100)) == 2

        reply = get_reply_text(update)
        assert "归档" in reply


class TestContextCommand:
    @pytest.mark.asyncio
    async def test_context_shows_usage(self, bot):
        bot._store.add_message(100, "user", "test message")
        update = make_update("/context", chat_id=100)
        await bot._cmd_context(update, make_context())
        reply = get_reply_text(update)
        assert "Context Window" in reply
        assert "tokens" in reply.lower() or "Tokens" in reply


class TestSkillsCommand:
    @pytest.mark.asyncio
    async def test_skills_lists_for_mode(self, bot):
        update = make_update("/skills", chat_id=100)
        await bot._cmd_skills(update, make_context())
        reply = get_reply_text(update)
        assert "Skills" in reply or "skills" in reply

    @pytest.mark.asyncio
    async def test_skills_detail(self, bot):
        update = make_update("/skills browse", chat_id=100)
        await bot._cmd_skills(update, make_context(["browse"]))
        reply = get_reply_text(update)
        assert "browse" in reply.lower()


class TestCarefulCommand:
    @pytest.mark.asyncio
    async def test_careful_toggle(self, bot):
        update = make_update("/careful")
        await bot._cmd_careful(update, make_context())
        reply = get_reply_text(update)
        assert "Careful" in reply or "careful" in reply


class TestSprintCommand:
    @pytest.mark.asyncio
    async def test_sprint_new(self, bot):
        update = make_update("/sprint new 测试任务", chat_id=100)
        await bot._cmd_sprint(update, make_context(["new", "测试任务"]))
        reply = get_reply_text(update)
        assert "Sprint" in reply or "sprint" in reply
        assert "think" in reply

    @pytest.mark.asyncio
    async def test_sprint_status_after_new(self, bot):
        # Create first
        update1 = make_update("/sprint new 任务A", chat_id=100)
        await bot._cmd_sprint(update1, make_context(["new", "任务A"]))

        # Status
        update2 = make_update("/sprint status", chat_id=100)
        await bot._cmd_sprint(update2, make_context(["status"]))
        reply = get_reply_text(update2)
        assert "任务A" in reply or "Sprint" in reply

    @pytest.mark.asyncio
    async def test_sprint_next(self, bot):
        # Create
        update1 = make_update("/sprint new 任务B", chat_id=100)
        await bot._cmd_sprint(update1, make_context(["new", "任务B"]))

        # Advance
        update2 = make_update("/sprint next", chat_id=100)
        await bot._cmd_sprint(update2, make_context(["next"]))
        reply = get_reply_text(update2)
        assert "plan" in reply


class TestAdminCommand:
    @pytest.mark.asyncio
    async def test_admin_stats(self, bot):
        bot._store.add_message(100, "user", "msg")
        update = make_update("/admin stats", chat_id=100)
        await bot._cmd_admin(update, make_context(["stats"]))
        reply = get_reply_text(update)
        assert "Chat Store" in reply
        assert "messages" in reply.lower()

    @pytest.mark.asyncio
    async def test_admin_help(self, bot):
        update = make_update("/admin", chat_id=100)
        await bot._cmd_admin(update, make_context())
        reply = get_reply_text(update)
        assert "Admin Panel" in reply

    @pytest.mark.asyncio
    async def test_admin_history(self, bot):
        bot._store.add_message(100, "user", "hello world")
        bot._store.add_message(100, "assistant", "hi there")
        update = make_update("/admin history", chat_id=100)
        await bot._cmd_admin(update, make_context(["history"]))
        reply = get_reply_text(update)
        assert "hello world" in reply or "对话历史" in reply

    @pytest.mark.asyncio
    async def test_admin_purge_requires_confirm(self, bot):
        update = make_update("/admin purge", chat_id=100)
        await bot._cmd_admin(update, make_context(["purge"]))
        reply = get_reply_text(update)
        assert "confirm" in reply.lower() or "确认" in reply


class TestProviderCommand:
    @pytest.mark.asyncio
    async def test_provider_shows_chain(self, bot):
        update = make_update("/provider")
        await bot._cmd_provider(update, make_context())
        reply = get_reply_text(update)
        assert "LLM Provider" in reply or "Provider" in reply
        assert "chain" in reply.lower() or "Chain" in reply

    @pytest.mark.asyncio
    async def test_provider_switch_direct(self, bot):
        update = make_update("/provider direct")
        await bot._cmd_provider(update, make_context(["direct"]))
        reply = get_reply_text(update)
        assert "禁用" in reply or "direct" in reply.lower()


class TestHnCommand:
    @pytest.mark.asyncio
    async def test_hn_calls_fetch(self, bot):
        with patch("agent.finance.telegram_bot.NeoMindTelegramBot._send_long_message", new_callable=AsyncMock) as mock_send:
            update = make_update("/hn best 3", chat_id=100)
            await bot._cmd_hn(update, make_context(["best", "3"]))
            # Should have called send (even if HN API fails, it sends "没有找到")
            assert mock_send.called or update.message.reply_text.called


class TestEvidenceCommand:
    @pytest.mark.asyncio
    async def test_evidence_empty(self, bot):
        update = make_update("/evidence")
        await bot._cmd_evidence(update, make_context())
        reply = get_reply_text(update)
        assert "evidence" in reply.lower() or "No" in reply


class TestUnknownCommand:
    @pytest.mark.asyncio
    async def test_typo_suggestion(self, bot):
        update = make_update("/model chat")
        await bot._handle_unknown_command(update, make_context())
        reply = get_reply_text(update)
        assert "/mode" in reply
