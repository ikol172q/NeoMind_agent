"""Tests for agent.cli_command_system — Registry, Parser, Dispatcher, Commands.

Tests the Claude Code-style CLI command system:
- SlashCommandParser correctly parses /commands
- CommandRegistry registers, finds, filters, fuzzy-searches
- CommandDispatcher routes to handlers and returns results
- Built-in commands return expected results
"""

import asyncio
import pytest
from unittest.mock import MagicMock, patch

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.cli_command_system import (
    Command,
    CommandType,
    CommandSource,
    CommandResult,
    CommandRegistry,
    SlashCommandParser,
    CommandDispatcher,
    ParsedCommand,
    create_default_registry,
)


# ─── SlashCommandParser Tests ────────────────────────────────────────

class TestSlashCommandParser:
    def test_parse_simple_command(self):
        result = SlashCommandParser.parse("/help")
        assert result is not None
        assert result.name == "help"
        assert result.args == ""

    def test_parse_command_with_args(self):
        result = SlashCommandParser.parse("/search AI news today")
        assert result.name == "search"
        assert result.args == "AI news today"

    def test_parse_command_with_spaces(self):
        result = SlashCommandParser.parse("  /config set temperature 0.5  ")
        assert result.name == "config"
        assert result.args == "set temperature 0.5"

    def test_parse_not_a_command(self):
        assert SlashCommandParser.parse("hello world") is None
        assert SlashCommandParser.parse("") is None
        assert SlashCommandParser.parse("   ") is None

    def test_parse_just_slash(self):
        assert SlashCommandParser.parse("/") is None

    def test_is_slash_command(self):
        assert SlashCommandParser.is_slash_command("/help") is True
        assert SlashCommandParser.is_slash_command("  /help") is True
        assert SlashCommandParser.is_slash_command("hello") is False
        assert SlashCommandParser.is_slash_command("") is False

    def test_parse_case_insensitive(self):
        result = SlashCommandParser.parse("/HELP")
        assert result.name == "help"

    def test_parse_preserves_args_case(self):
        result = SlashCommandParser.parse("/search CaseSensitive")
        assert result.args == "CaseSensitive"


# ─── CommandRegistry Tests ────────────────────────────────────────────

class TestCommandRegistry:
    def setup_method(self):
        self.registry = CommandRegistry()

    def test_register_and_find(self):
        cmd = Command(name="test", description="A test command")
        self.registry.register(cmd)
        found = self.registry.find("test")
        assert found is not None
        assert found.name == "test"

    def test_find_by_alias(self):
        cmd = Command(name="exit", description="Exit", aliases=["quit", "q"])
        self.registry.register(cmd)
        assert self.registry.find("quit") is not None
        assert self.registry.find("q") is not None
        assert self.registry.find("q").name == "exit"

    def test_find_nonexistent(self):
        assert self.registry.find("nonexistent") is None

    def test_register_overwrites(self):
        cmd1 = Command(name="test", description="Old")
        cmd2 = Command(name="test", description="New")
        self.registry.register(cmd1)
        self.registry.register(cmd2)
        found = self.registry.find("test")
        assert found.description == "New"

    def test_unregister(self):
        cmd = Command(name="test", description="Test", aliases=["t"])
        self.registry.register(cmd)
        self.registry.unregister("test")
        assert self.registry.find("test") is None
        assert self.registry.find("t") is None

    def test_get_available_filters_by_mode(self):
        self.registry.register(Command(name="all_cmd", description="All", modes=["chat", "coding", "fin"]))
        self.registry.register(Command(name="coding_only", description="Coding", modes=["coding"]))
        self.registry.register(Command(name="fin_only", description="Fin", modes=["fin"]))

        chat_cmds = self.registry.get_available("chat")
        assert any(c.name == "all_cmd" for c in chat_cmds)
        assert not any(c.name == "coding_only" for c in chat_cmds)
        assert not any(c.name == "fin_only" for c in chat_cmds)

        coding_cmds = self.registry.get_available("coding")
        assert any(c.name == "coding_only" for c in coding_cmds)

    def test_get_available_respects_feature_gate(self):
        cmd = Command(
            name="gated",
            description="Gated command",
            feature_gate="TEST_FEATURE",
        )
        self.registry.register(cmd)
        with patch("agent_config.agent_config") as mock_config:
            mock_config.get.return_value = False
            available = self.registry.get_available("chat")
            assert not any(c.name == "gated" for c in available)

    def test_get_visible_hides_hidden(self):
        self.registry.register(Command(name="visible", description="V"))
        self.registry.register(Command(name="hidden", description="H", is_hidden=True))
        visible = self.registry.get_visible("chat")
        assert any(c.name == "visible" for c in visible)
        assert not any(c.name == "hidden" for c in visible)

    def test_fuzzy_search_exact(self):
        self.registry.register(Command(name="help", description="Show help"))
        results = self.registry.fuzzy_search("help")
        assert len(results) >= 1
        assert results[0].name == "help"

    def test_fuzzy_search_prefix(self):
        self.registry.register(Command(name="compact", description="Compact"))
        self.registry.register(Command(name="config", description="Config"))
        self.registry.register(Command(name="cost", description="Cost"))
        results = self.registry.fuzzy_search("co")
        names = [r.name for r in results]
        assert "compact" in names
        assert "config" in names
        assert "cost" in names

    def test_fuzzy_search_description(self):
        self.registry.register(Command(name="abc", description="Show available commands"))
        results = self.registry.fuzzy_search("available")
        assert len(results) >= 1

    def test_count(self):
        self.registry.register(Command(name="a", description="A"))
        self.registry.register(Command(name="b", description="B"))
        assert self.registry.count == 2


# ─── CommandDispatcher Tests ──────────────────────────────────────────

class TestCommandDispatcher:
    def setup_method(self):
        self.registry = CommandRegistry()
        self.dispatcher = CommandDispatcher(
            self.registry,
            context={"registry": self.registry},
        )

    @pytest.mark.asyncio
    async def test_dispatch_unknown_command(self):
        result = await self.dispatcher.dispatch("/nonexistent")
        assert result is not None
        assert "Unknown command" in result.text

    @pytest.mark.asyncio
    async def test_dispatch_unknown_with_suggestion(self):
        self.registry.register(Command(name="help", description="Help"))
        result = await self.dispatcher.dispatch("/hel")
        assert result is not None
        assert "help" in result.text.lower()

    @pytest.mark.asyncio
    async def test_dispatch_not_a_command(self):
        result = await self.dispatcher.dispatch("hello world")
        assert result is None

    @pytest.mark.asyncio
    async def test_dispatch_local_command(self):
        def handler(args, **kw):
            return CommandResult(text=f"Got: {args}")
        self.registry.register(Command(
            name="echo", description="Echo", handler=handler,
        ))
        result = await self.dispatcher.dispatch("/echo hello")
        assert result.text == "Got: hello"

    @pytest.mark.asyncio
    async def test_dispatch_prompt_command(self):
        def handler(args, **kw):
            return f"Prompt for: {args}"
        self.registry.register(Command(
            name="plan", description="Plan",
            type=CommandType.PROMPT, handler=handler,
            modes=["coding"],
        ))
        result = await self.dispatcher.dispatch("/plan build feature", mode="coding")
        assert result.should_query is True
        assert "build feature" in result.text

    @pytest.mark.asyncio
    async def test_dispatch_mode_restriction(self):
        self.registry.register(Command(
            name="stock", description="Stock",
            modes=["fin"],
        ))
        result = await self.dispatcher.dispatch("/stock AAPL", mode="chat")
        assert "not available" in result.text

    @pytest.mark.asyncio
    async def test_dispatch_async_handler(self):
        async def async_handler(args, **kw):
            return CommandResult(text=f"Async: {args}")
        self.registry.register(Command(
            name="async_cmd", description="Async",
            handler=async_handler,
        ))
        result = await self.dispatcher.dispatch("/async_cmd test")
        assert result.text == "Async: test"


# ─── Built-in Commands Tests ─────────────────────────────────────────

class TestBuiltinCommands:
    def setup_method(self):
        self.registry = create_default_registry()
        self.dispatcher = CommandDispatcher(
            self.registry,
            context={"registry": self.registry},
        )

    def test_default_registry_has_commands(self):
        assert self.registry.count > 20

    def test_has_core_commands(self):
        core_names = ["help", "clear", "compact", "context", "exit",
                      "mode", "model", "think", "config", "memory",
                      "stats", "debug", "history", "skills", "version"]
        for name in core_names:
            cmd = self.registry.find(name)
            assert cmd is not None, f"Missing command: /{name}"

    def test_has_coding_commands(self):
        for name in ["plan", "review", "diff", "git", "test", "security-review"]:
            cmd = self.registry.find(name)
            assert cmd is not None, f"Missing coding command: /{name}"
            assert "coding" in cmd.modes

    def test_has_finance_commands(self):
        for name in ["stock", "portfolio", "market", "news", "quant"]:
            cmd = self.registry.find(name)
            assert cmd is not None, f"Missing finance command: /{name}"
            assert "fin" in cmd.modes

    def test_aliases_work(self):
        assert self.registry.find("quit") is not None
        assert self.registry.find("q") is not None
        assert self.registry.find("?") is not None
        assert self.registry.find("switch") is not None
        assert self.registry.find("ver") is not None
        assert self.registry.find("security") is not None

    @pytest.mark.asyncio
    async def test_help_command(self):
        result = await self.dispatcher.dispatch("/help", mode="chat")
        assert result is not None
        assert "commands" in result.text.lower() or "Available" in result.text

    @pytest.mark.asyncio
    async def test_version_command(self):
        with patch("agent_config.agent_config") as mock_config:
            mock_config.get.return_value = "0.3.0"
            result = await self.dispatcher.dispatch("/version")
            assert "NeoMind" in result.text

    @pytest.mark.asyncio
    async def test_exit_command(self):
        result = await self.dispatcher.dispatch("/exit")
        assert result.text == "__EXIT__"

    @pytest.mark.asyncio
    async def test_mode_command_valid(self):
        result = await self.dispatcher.dispatch("/mode coding")
        assert "__MODE_SWITCH__coding" in result.text

    @pytest.mark.asyncio
    async def test_mode_command_invalid(self):
        result = await self.dispatcher.dispatch("/mode invalid")
        assert "Usage" in result.text


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
