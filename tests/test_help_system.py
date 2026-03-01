#!/usr/bin/env python3
"""
Comprehensive unit tests for HelpSystem.
Tests help text building, command lookup, and convenience functions.
"""
import os
import sys
import unittest
from unittest.mock import Mock, patch, MagicMock, call

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.help_system import HelpSystem, get_help


class TestHelpSystemInitialization(unittest.TestCase):
    """Test HelpSystem initialization and basic properties."""

    def test_initialization_with_default_formatter(self):
        """Test initialization with default formatter."""
        help_system = HelpSystem()

        self.assertIsNotNone(help_system.formatter)
        self.assertIsInstance(help_system.help_texts, dict)
        self.assertGreater(len(help_system.help_texts), 0)

    def test_initialization_with_custom_formatter(self):
        """Test initialization with custom formatter."""
        mock_formatter = Mock()
        help_system = HelpSystem(formatter=mock_formatter)

        self.assertEqual(help_system.formatter, mock_formatter)
        # Should call formatter.command_help during _build_help_texts
        # But since we mocked it, we can verify it was called
        # Actually mock_formatter.command_help is not called because we mocked the formatter
        # The _build_help_texts uses self.formatter.command_help, which is the mock

    def test_build_help_texts_structure(self):
        """Test that help texts dictionary is built correctly."""
        mock_formatter = Mock()
        mock_formatter.command_help.return_value = "Formatted help"
        mock_formatter.header.return_value = "# Header"
        mock_formatter.info.return_value = "💡 Info"

        help_system = HelpSystem(formatter=mock_formatter)

        # Should have many commands
        expected_commands = [
            "write", "edit", "read", "run", "git", "code", "search", "models",
            "mode", "fix", "analyze", "diff", "browse", "undo", "test", "apply",
            "auto", "task", "plan", "execute", "switch", "summarize", "translate",
            "generate", "reason", "debug", "explain", "refactor", "grep", "find",
            "clear", "history", "context", "think", "quit", "exit"
        ]

        for cmd in expected_commands:
            self.assertIn(cmd, help_system.help_texts)

        # Each entry should be the result of command_help
        self.assertEqual(help_system.help_texts["write"], "Formatted help")
        # Verify command_help was called with correct arguments for at least one command
        mock_formatter.command_help.assert_called()


class TestGetHelp(unittest.TestCase):
    """Test getting help for commands."""

    def setUp(self):
        """Set up test environment."""
        self.mock_formatter = Mock()
        self.help_system = HelpSystem(formatter=self.mock_formatter)

        # Set up mock help texts
        self.help_system.help_texts = {
            "write": "📝 /write - Write content to a file",
            "read": "📖 /read - Read file or URL",
            "code": "💻 /code - Code analysis commands",
        }

    def test_get_help_specific_command(self):
        """Test getting help for a specific command."""
        result = self.help_system.get_help("write")

        self.assertEqual(result, "📝 /write - Write content to a file")

    def test_get_help_command_case_insensitive(self):
        """Test command name case insensitivity."""
        result = self.help_system.get_help("WRITE")

        self.assertEqual(result, "📝 /write - Write content to a file")

    def test_get_help_command_with_whitespace(self):
        """Test command name with whitespace."""
        result = self.help_system.get_help("  write  ")

        self.assertEqual(result, "📝 /write - Write content to a file")

    def test_get_help_nonexistent_command(self):
        """Test getting help for nonexistent command."""
        self.mock_formatter.error.return_value = "❌ Error"

        result = self.help_system.get_help("nonexistent")

        self.mock_formatter.error.assert_called_once()
        error_call = self.mock_formatter.error.call_args[0][0]
        self.assertIn("No help available", error_call)
        self.assertIn("write", error_call)  # Should list available commands

    def test_get_help_empty_command_shows_all(self):
        """Test getting help with empty string shows all commands."""
        # Mock header and info methods
        self.mock_formatter.header.return_value = "# Available Commands"
        self.mock_formatter.info.return_value = "💡 Info"

        result = self.help_system.get_help("")

        # Should call header
        self.mock_formatter.header.assert_called_once_with("Available Commands", level=2)
        # Should call info
        self.mock_formatter.info.assert_called_once_with("Use /help <command> for detailed usage.")

        # Should include command headers
        self.assertIn("# Available Commands", result)
        self.assertIn("📝 /write", result)
        self.assertIn("📖 /read", result)
        self.assertIn("💡 Info", result)

    def test_get_help_all_commands_sorted(self):
        """Test that all commands are shown in sorted order."""
        # Create help system with many commands in unsorted order
        help_texts = {
            "zebra": "Zebra command",
            "apple": "Apple command",
            "banana": "Banana command",
        }
        self.help_system.help_texts = help_texts
        self.mock_formatter.header.return_value = "# Header"
        self.mock_formatter.info.return_value = "Info"

        result = self.help_system.get_help("")

        # Commands should appear in alphabetical order
        # Since we can't guarantee exact format, check that result contains each
        self.assertIn("Apple command", result)
        self.assertIn("Banana command", result)
        self.assertIn("Zebra command", result)

        # Find positions
        pos_apple = result.find("Apple command")
        pos_banana = result.find("Banana command")
        pos_zebra = result.find("Zebra command")

        # Should be in alphabetical order: apple, banana, zebra
        self.assertLess(pos_apple, pos_banana)
        self.assertLess(pos_banana, pos_zebra)


class TestHelpSystemIntegration(unittest.TestCase):
    """Test HelpSystem integration with formatter."""

    def test_build_help_texts_calls_formatter(self):
        """Test that _build_help_texts calls formatter.command_help for each command."""
        mock_formatter = Mock()
        mock_formatter.command_help.return_value = "Help text"

        help_system = HelpSystem(formatter=mock_formatter)

        # Verify command_help was called multiple times
        self.assertGreater(mock_formatter.command_help.call_count, 10)

        # Check some specific calls
        calls = mock_formatter.command_help.call_args_list

        # Find call for "write" command
        write_call = None
        for call in calls:
            args, kwargs = call
            if kwargs.get('command') == "/write":
                write_call = call
                break

        self.assertIsNotNone(write_call)
        args, kwargs = write_call
        self.assertEqual(kwargs.get('command'), "/write")
        self.assertIn("Write content to a file", kwargs.get('description', ''))

    def test_get_help_with_formatter_error(self):
        """Test error formatting with formatter."""
        mock_formatter = Mock()
        mock_formatter.error.return_value = "❌ Custom error"
        help_system = HelpSystem(formatter=mock_formatter)
        help_system.help_texts = {"write": "Help for write"}

        result = help_system.get_help("nonexistent")

        self.assertEqual(result, "❌ Custom error")
        mock_formatter.error.assert_called_once()

    def test_get_help_all_commands_uses_formatter(self):
        """Test that getAll commands uses formatter.header and formatter.info."""
        mock_formatter = Mock()
        mock_formatter.header.return_value = "# HEADER"
        mock_formatter.info.return_value = "ℹ️ INFO"
        mock_formatter.command_help.return_value = "Command: /write\nDescription"

        help_system = HelpSystem(formatter=mock_formatter)
        help_system.help_texts = {"write": "Command: /write\nDescription"}

        result = help_system.get_help("")

        mock_formatter.header.assert_called_once_with("Available Commands", level=2)
        mock_formatter.info.assert_called_once_with("Use /help <command> for detailed usage.")
        self.assertIn("# HEADER", result)
        self.assertIn("ℹ️ INFO", result)


class TestGlobalConvenienceFunctions(unittest.TestCase):
    """Test global convenience functions."""

    def test_get_help_function(self):
        """Test global get_help function."""
        with patch('agent.help_system._default_help_system') as mock_help_system:
            mock_help_system.get_help.return_value = "Help text"

            result = get_help("write")

            mock_help_system.get_help.assert_called_once_with("write")
            self.assertEqual(result, "Help text")

    def test_get_help_function_empty(self):
        """Test global get_help function with empty string."""
        with patch('agent.help_system._default_help_system') as mock_help_system:
            mock_help_system.get_help.return_value = "All commands"

            result = get_help("")

            mock_help_system.get_help.assert_called_once_with("")
            self.assertEqual(result, "All commands")


class TestHelpContentCompleteness(unittest.TestCase):
    """Test that help content is complete and well-formed."""

    def test_all_commands_have_help(self):
        """Test that all expected commands have help entries."""
        help_system = HelpSystem()

        # List of commands that should definitely have help
        essential_commands = [
            "write", "edit", "read", "run", "git", "code", "search", "models",
            "mode", "fix", "analyze", "diff", "browse", "undo", "test", "apply",
            "auto", "clear", "history", "context", "think", "quit", "exit"
        ]

        for cmd in essential_commands:
            self.assertIn(cmd, help_system.help_texts, f"Missing help for command: {cmd}")

    def test_help_texts_not_empty(self):
        """Test that help texts are not empty strings."""
        help_system = HelpSystem()

        for cmd, text in help_system.help_texts.items():
            self.assertIsInstance(text, str)
            self.assertGreater(len(text.strip()), 0, f"Empty help text for command: {cmd}")

    def test_help_texts_contain_command_name(self):
        """Test that help texts contain the command name."""
        help_system = HelpSystem()

        for cmd, text in help_system.help_texts.items():
            # Most help texts should contain the command name (with slash)
            self.assertIn(f"/{cmd}", text, f"Help text for '{cmd}' should contain '/{cmd}'")


if __name__ == '__main__':
    unittest.main()