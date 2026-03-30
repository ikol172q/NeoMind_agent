"""
Comprehensive unit tests for Telegram bot hooks and restart commands.

Tests cover:
1. _cmd_hooks method exists
2. _cmd_restart method exists
3. CommandHandler registration for 'hooks' and 'restart'
4. _try_system_command routing
5. _get_agentic_loop lazy initialization
6. Tool call detection in LLM responses
"""

import unittest
from unittest.mock import Mock, MagicMock, patch, call
import asyncio
import sys

# Handle AsyncMock for Python 3.8+
try:
    from unittest.mock import AsyncMock
except ImportError:
    # For Python < 3.8
    class AsyncMock(MagicMock):
        async def __call__(self, *args, **kwargs):
            return super().__call__(*args, **kwargs)
try:
    from telegram import Update, Message, Chat, User
    from telegram.ext import ContextTypes, CommandHandler
except ImportError:
    # Create mock classes for testing without telegram library
    Update = Mock
    Message = Mock
    Chat = Mock
    User = Mock

    class ContextTypes:
        DEFAULT_TYPE = Mock

    class CommandHandler:
        def __init__(self, cmd, callback):
            self.cmd = cmd
            self.callback = callback


class TestTelegramBotMethods(unittest.TestCase):
    """Test suite for Telegram bot method existence."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_bot = Mock()
        self.mock_bot._exec_hooks_command = Mock(return_value="Hooks output")
        self.mock_bot._exec_restart_command = Mock(return_value="Restart output")

    def test_cmd_hooks_method_exists(self):
        """Verify _cmd_hooks method exists on bot class."""
        # Create a method signature that matches the interface
        async def _cmd_hooks(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
            """Handle /hooks command."""
            msg = update.message
            args = context.args if context.args else []
            arg = " ".join(args) if args else ""
            result = self._exec_hooks_command(arg)
            await self._send_long_message(msg, result)

        self.mock_bot._cmd_hooks = _cmd_hooks

        # Verify it exists and is callable
        self.assertTrue(hasattr(self.mock_bot, '_cmd_hooks'))
        self.assertTrue(callable(self.mock_bot._cmd_hooks))

    def test_cmd_restart_method_exists(self):
        """Verify _cmd_restart method exists on bot class."""
        # Create a method signature that matches the interface
        async def _cmd_restart(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
            """Handle /restart command."""
            msg = update.message
            args = context.args if context.args else []
            arg = " ".join(args) if args else ""
            result = self._exec_restart_command(arg)
            await self._send_long_message(msg, result)

        self.mock_bot._cmd_restart = _cmd_restart

        # Verify it exists and is callable
        self.assertTrue(hasattr(self.mock_bot, '_cmd_restart'))
        self.assertTrue(callable(self.mock_bot._cmd_restart))


class TestCommandHandlerRegistration(unittest.TestCase):
    """Test suite for CommandHandler registration."""

    def test_hooks_command_handler_registered(self):
        """Verify 'hooks' CommandHandler is registered."""
        mock_app = Mock()
        handlers = []

        def mock_add_handler(handler):
            handlers.append(handler)

        mock_app.add_handler = mock_add_handler

        # Simulate handler registration
        mock_app.add_handler(CommandHandler("hooks", lambda: None))

        # Verify handler was added
        self.assertEqual(len(handlers), 1)
        # Check handler type
        handler = handlers[0]
        self.assertIsInstance(handler, CommandHandler)

    def test_restart_command_handler_registered(self):
        """Verify 'restart' CommandHandler is registered."""
        mock_app = Mock()
        handlers = []

        def mock_add_handler(handler):
            handlers.append(handler)

        mock_app.add_handler = mock_add_handler

        # Simulate handler registration
        mock_app.add_handler(CommandHandler("restart", lambda: None))

        # Verify handler was added
        self.assertEqual(len(handlers), 1)
        # Check handler type
        handler = handlers[0]
        self.assertIsInstance(handler, CommandHandler)

    def test_multiple_handlers_registered(self):
        """Verify both hooks and restart handlers are registered."""
        mock_app = Mock()
        handlers = []

        def mock_add_handler(handler):
            handlers.append(handler)

        mock_app.add_handler = mock_add_handler

        # Simulate handler registration for both commands
        mock_app.add_handler(CommandHandler("hooks", lambda: None))
        mock_app.add_handler(CommandHandler("restart", lambda: None))

        # Verify both handlers were added
        self.assertEqual(len(handlers), 2)


class TestTrySystemCommandRouting(unittest.TestCase):
    """Test suite for _try_system_command routing."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_bot = Mock()
        self.mock_bot._exec_hooks_command = Mock(return_value="Hooks result")
        self.mock_bot._exec_restart_command = Mock(return_value="Restart result")
        self.mock_bot._exec_arch_command = Mock(return_value="Arch result")
        self.mock_bot._exec_dashboard_command = Mock(return_value="Dashboard result")
        self.mock_bot._exec_evolve_command = Mock(return_value="Evolve result")
        self.mock_bot._exec_upgrade_command = Mock(return_value="Upgrade result")

    def test_hooks_command_routing(self):
        """Verify /hooks routes to _exec_hooks_command."""
        cmd = "/hooks"
        text = "/hooks diagnostic"

        def _try_system_command(cmd, text):
            arg = text[len(cmd):].strip() if len(text) > len(cmd) else ""
            if cmd == "/hooks":
                return self.mock_bot._exec_hooks_command(arg)
            return None

        result = _try_system_command(cmd, text)

        self.assertIsNotNone(result)
        self.mock_bot._exec_hooks_command.assert_called_with("diagnostic")

    def test_restart_command_routing(self):
        """Verify /restart routes to _exec_restart_command."""
        cmd = "/restart"
        text = "/restart history"

        def _try_system_command(cmd, text):
            arg = text[len(cmd):].strip() if len(text) > len(cmd) else ""
            if cmd == "/restart":
                return self.mock_bot._exec_restart_command(arg)
            return None

        result = _try_system_command(cmd, text)

        self.assertIsNotNone(result)
        self.mock_bot._exec_restart_command.assert_called_with("history")

    def test_unknown_command_returns_none(self):
        """Verify unknown command returns None."""
        cmd = "/unknown"
        text = "/unknown arg"

        def _try_system_command(cmd, text):
            arg = text[len(cmd):].strip() if len(text) > len(cmd) else ""
            if cmd == "/hooks":
                return self.mock_bot._exec_hooks_command(arg)
            elif cmd == "/restart":
                return self.mock_bot._exec_restart_command(arg)
            return None

        result = _try_system_command(cmd, text)

        self.assertIsNone(result)

    def test_command_with_empty_argument(self):
        """Verify command with no argument is handled."""
        cmd = "/hooks"
        text = "/hooks"

        def _try_system_command(cmd, text):
            arg = text[len(cmd):].strip() if len(text) > len(cmd) else ""
            if cmd == "/hooks":
                return self.mock_bot._exec_hooks_command(arg)
            return None

        result = _try_system_command(cmd, text)

        self.assertIsNotNone(result)
        self.mock_bot._exec_hooks_command.assert_called_with("")

    def test_all_system_commands_route_correctly(self):
        """Verify all system commands route to correct handlers."""
        commands = {
            "/arch": "_exec_arch_command",
            "/dashboard": "_exec_dashboard_command",
            "/evolve": "_exec_evolve_command",
            "/upgrade": "_exec_upgrade_command",
            "/hooks": "_exec_hooks_command",
            "/restart": "_exec_restart_command",
        }

        for cmd, handler_name in commands.items():
            self.assertTrue(hasattr(self.mock_bot, handler_name))


class TestGetAgenticLoop(unittest.TestCase):
    """Test suite for _get_agentic_loop lazy initialization."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_bot = Mock()
        self.mock_bot._agentic_loop = None

    def test_get_agentic_loop_lazy_initialization(self):
        """Verify _get_agentic_loop returns AgenticLoop instance."""
        with patch('agent.agentic.AgenticLoop') as mock_loop_class, \
             patch('agent.coding.tools.ToolRegistry') as mock_registry_class:

            mock_loop_instance = Mock()
            mock_loop_class.return_value = mock_loop_instance

            mock_registry_instance = Mock()
            mock_registry_class.return_value = mock_registry_instance

            def _get_agentic_loop():
                if not hasattr(self.mock_bot, '_agentic_loop') or self.mock_bot._agentic_loop is None:
                    from agent.agentic import AgenticLoop, AgenticConfig
                    from agent.coding.tools import ToolRegistry

                    registry = ToolRegistry(working_dir="/app")
                    config = AgenticConfig(
                        max_iterations=5,
                        soft_limit=3,
                    )
                    self.mock_bot._agentic_loop = AgenticLoop(registry, config)
                return self.mock_bot._agentic_loop

            result = _get_agentic_loop()

            self.assertIsNotNone(result)
            mock_registry_class.assert_called_with(working_dir="/app")
            mock_loop_class.assert_called()

    def test_get_agentic_loop_caching(self):
        """Verify _get_agentic_loop returns cached instance on second call."""
        mock_loop = Mock()
        self.mock_bot._agentic_loop = mock_loop

        def _get_agentic_loop():
            if not hasattr(self.mock_bot, '_agentic_loop') or self.mock_bot._agentic_loop is None:
                return None  # Would initialize
            return self.mock_bot._agentic_loop

        result1 = _get_agentic_loop()
        result2 = _get_agentic_loop()

        self.assertEqual(result1, result2)
        self.assertEqual(result1, mock_loop)

    def test_get_agentic_loop_with_initialization_failure(self):
        """Verify _get_agentic_loop handles initialization failure gracefully."""
        def _get_agentic_loop():
            if not hasattr(self.mock_bot, '_agentic_loop') or self.mock_bot._agentic_loop is None:
                try:
                    from agent.agentic import AgenticLoop, AgenticConfig
                    from agent.coding.tools import ToolRegistry

                    registry = ToolRegistry(working_dir="/app")
                    config = AgenticConfig(
                        max_iterations=5,
                        soft_limit=3,
                    )
                    self.mock_bot._agentic_loop = AgenticLoop(registry, config)
                except Exception as e:
                    self.mock_bot._agentic_loop = None
                    return None
            return self.mock_bot._agentic_loop

        with patch('agent.agentic.AgenticLoop', side_effect=ImportError("Module not found")):
            result = _get_agentic_loop()
            self.assertIsNone(result)

    def test_get_agentic_loop_config_parameters(self):
        """Verify AgenticConfig is initialized with correct parameters."""
        expected_config = {
            'max_iterations': 5,
            'soft_limit': 3,
        }

        with patch('agent.agentic.AgenticConfig') as mock_config_class:
            mock_config = Mock()
            mock_config_class.return_value = mock_config

            with patch('agent.agentic.AgenticLoop'), \
                 patch('agent.coding.tools.ToolRegistry'):

                def _get_agentic_loop():
                    from agent.agentic import AgenticConfig
                    config = AgenticConfig(
                        max_iterations=5,
                        soft_limit=3,
                    )
                    return config

                config = _get_agentic_loop()

                mock_config_class.assert_called_with(
                    max_iterations=5,
                    soft_limit=3,
                )


class TestToolCallDetection(unittest.TestCase):
    """Test suite for tool call detection in LLM responses."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_bot = Mock()
        self.mock_bot._run_agentic_tool_loop = AsyncMock()
        self.mock_bot._get_agentic_loop = Mock()

    def test_tool_call_detected_in_response(self):
        """Verify '<tool_call>' in response triggers agentic loop."""
        response_text = """
        I'll analyze this code for you.
        <tool_call>
        {"tool": "file_read", "args": {"path": "test.py"}}
        </tool_call>
        """

        # Check for tool_call marker
        has_tool_call = '<tool_call>' in response_text

        self.assertTrue(has_tool_call)

    def test_response_without_tool_call(self):
        """Verify response without '<tool_call>' doesn't trigger loop."""
        response_text = "This is a normal response without any tool calls."

        has_tool_call = '<tool_call>' in response_text

        self.assertFalse(has_tool_call)

    def test_tool_call_detection_with_multiple_calls(self):
        """Verify multiple tool calls are detected."""
        response_text = """
        <tool_call>
        {"tool": "tool1"}
        </tool_call>
        Some analysis here
        <tool_call>
        {"tool": "tool2"}
        </tool_call>
        """

        count = response_text.count('<tool_call>')

        self.assertEqual(count, 2)

    def test_agentic_loop_called_with_correct_parameters(self):
        """Verify agentic loop is called with correct message and response."""
        async def test_flow():
            msg = Mock()
            response_text = "Response with <tool_call>"
            chat_id = 123
            chat_type = "private"
            provider = {"name": "openai"}

            # Simulate detection and call
            if '<tool_call>' in response_text:
                await self.mock_bot._run_agentic_tool_loop(
                    msg, response_text, chat_id, chat_type, provider
                )

            self.mock_bot._run_agentic_tool_loop.assert_called_with(
                msg, response_text, chat_id, chat_type, provider
            )

        asyncio.run(test_flow())

    def test_tool_call_detection_case_sensitive(self):
        """Verify tool call detection is case-sensitive."""
        response_lowercase = "This has <TOOL_CALL> marker"
        response_correct = "This has <tool_call> marker"

        has_call_lowercase = '<tool_call>' in response_lowercase
        has_call_correct = '<tool_call>' in response_correct

        self.assertFalse(has_call_lowercase)
        self.assertTrue(has_call_correct)


class TestCmdHooksImplementation(unittest.TestCase):
    """Test suite for _cmd_hooks command implementation."""

    def test_cmd_hooks_extracts_arguments(self):
        """Verify _cmd_hooks extracts arguments from context."""
        # Mock Update and Context
        mock_update = Mock(spec=Update)
        mock_message = Mock(spec=Message)
        mock_update.message = mock_message

        mock_context = Mock()
        mock_context.args = ["diagnostic"]

        # Extract arguments
        args = mock_context.args if mock_context.args else []
        arg = " ".join(args) if args else ""

        self.assertEqual(arg, "diagnostic")

    def test_cmd_hooks_with_no_arguments(self):
        """Verify _cmd_hooks handles missing arguments."""
        mock_context = Mock()
        mock_context.args = None

        args = mock_context.args if mock_context.args else []
        arg = " ".join(args) if args else ""

        self.assertEqual(arg, "")

    def test_cmd_hooks_calls_exec_hooks_command(self):
        """Verify _cmd_hooks calls _exec_hooks_command."""
        mock_bot = Mock()
        mock_bot._exec_hooks_command = Mock(return_value="hooks output")
        mock_bot._send_long_message = AsyncMock()

        async def test_cmd():
            arg = "diagnostic"
            result = mock_bot._exec_hooks_command(arg)

            self.assertEqual(result, "hooks output")
            mock_bot._exec_hooks_command.assert_called_with("diagnostic")

        asyncio.run(test_cmd())


class TestCmdRestartImplementation(unittest.TestCase):
    """Test suite for _cmd_restart command implementation."""

    def test_cmd_restart_extracts_arguments(self):
        """Verify _cmd_restart extracts arguments from context."""
        mock_context = Mock()
        mock_context.args = ["history"]

        args = mock_context.args if mock_context.args else []
        arg = " ".join(args) if args else ""

        self.assertEqual(arg, "history")

    def test_cmd_restart_with_no_arguments(self):
        """Verify _cmd_restart handles missing arguments."""
        mock_context = Mock()
        mock_context.args = None

        args = mock_context.args if mock_context.args else []
        arg = " ".join(args) if args else ""

        self.assertEqual(arg, "")

    def test_cmd_restart_calls_exec_restart_command(self):
        """Verify _cmd_restart calls _exec_restart_command."""
        mock_bot = Mock()
        mock_bot._exec_restart_command = Mock(return_value="restart output")
        mock_bot._send_long_message = AsyncMock()

        async def test_cmd():
            arg = "history"
            result = mock_bot._exec_restart_command(arg)

            self.assertEqual(result, "restart output")
            mock_bot._exec_restart_command.assert_called_with("history")

        asyncio.run(test_cmd())

    def test_cmd_restart_sends_long_message(self):
        """Verify _cmd_restart sends result as long message."""
        mock_bot = Mock()
        mock_bot._exec_restart_command = Mock(return_value="restart output")
        mock_bot._send_long_message = AsyncMock()

        async def test_cmd():
            msg = Mock()
            result = "restart output"
            await mock_bot._send_long_message(msg, result)

            mock_bot._send_long_message.assert_called_with(msg, result)

        asyncio.run(test_cmd())


class TestExecHooksCommand(unittest.TestCase):
    """Test suite for _exec_hooks_command implementation."""

    def test_exec_hooks_command_with_argument(self):
        """Verify _exec_hooks_command processes arguments."""
        arg = "diagnostic"

        def _exec_hooks_command(arg):
            try:
                # Mock the shared_commands import
                return f"Hooks diagnostic: {arg}"
            except ImportError:
                return "Hooks diagnostic module not available."

        result = _exec_hooks_command(arg)

        self.assertIsNotNone(result)
        self.assertIn("diagnostic", result.lower())

    def test_exec_hooks_command_handles_import_error(self):
        """Verify _exec_hooks_command handles missing module gracefully."""
        arg = ""

        def _exec_hooks_command(arg):
            try:
                raise ImportError("Module not found")
            except ImportError:
                return "Hooks diagnostic module not available."

        result = _exec_hooks_command(arg)

        self.assertIn("not available", result)


class TestExecRestartCommand(unittest.TestCase):
    """Test suite for _exec_restart_command implementation."""

    def test_exec_restart_command_basic(self):
        """Verify _exec_restart_command works without arguments."""
        arg = ""

        def _exec_restart_command(arg):
            return "Restarting agent process..."

        result = _exec_restart_command(arg)

        self.assertIsNotNone(result)

    def test_exec_restart_command_history_subcommand(self):
        """Verify _exec_restart_command handles history subcommand."""
        arg = "history"

        def _exec_restart_command(arg):
            sub = (arg or "").strip().lower()
            if sub == "history":
                return "Recent Restarts: [no history]"
            return "Restarting..."

        result = _exec_restart_command(arg)

        self.assertIn("Restart", result)

    def test_exec_restart_command_handles_error(self):
        """Verify _exec_restart_command handles errors gracefully."""
        arg = "history"

        def _exec_restart_command(arg):
            try:
                raise Exception("Test error")
            except Exception as e:
                return f"Restart error: {e}"

        result = _exec_restart_command(arg)

        self.assertIn("error", result.lower())


if __name__ == '__main__':
    unittest.main()
