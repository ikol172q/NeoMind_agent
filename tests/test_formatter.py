#!/usr/bin/env python3
"""
Comprehensive unit tests for Formatter.
Tests message formatting, color application, emoji usage, and convenience functions.
"""
import os
import sys
import unittest
from unittest.mock import Mock, patch, MagicMock

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.formatter import Formatter, success, error, warning, info, header, code_block, command_help


class TestFormatterInitialization(unittest.TestCase):
    """Test Formatter initialization and basic properties."""

    def test_initialization_default(self):
        """Test initialization with default parameters."""
        formatter = Formatter()

        # Should auto-detect color support
        # In test environment, sys.stdout.isatty() may be False
        # So COLORS_ENABLED may be False
        self.assertIn(formatter.COLORS_ENABLED, [True, False])

        # Verify emoji constants
        self.assertEqual(formatter.EMOJI_SUCCESS, "✅")
        self.assertEqual(formatter.EMOJI_ERROR, "❌")
        self.assertEqual(formatter.EMOJI_WARNING, "⚠️ ")
        self.assertEqual(formatter.EMOJI_INFO, "💡")

    def test_initialization_with_colors_enabled(self):
        """Test initialization with colors forced on."""
        formatter = Formatter(use_colors=True)

        self.assertTrue(formatter.COLORS_ENABLED)

    def test_initialization_with_colors_disabled(self):
        """Test initialization with colors forced off."""
        formatter = Formatter(use_colors=False)

        self.assertFalse(formatter.COLORS_ENABLED)

    def test_initialization_with_none_uses_auto_detect(self):
        """Test initialization with None uses auto-detection."""
        # Mock sys.stdout.isatty to return True
        with patch('sys.stdout.isatty', return_value=True):
            with patch.dict(os.environ, {'TERM': 'xterm-256color'}):
                formatter = Formatter(use_colors=None)

                self.assertTrue(formatter.COLORS_ENABLED)

    def test_initialization_dumb_terminal(self):
        """Test initialization with dumb terminal disables colors."""
        with patch('sys.stdout.isatty', return_value=True):
            with patch.dict(os.environ, {'TERM': 'dumb'}):
                formatter = Formatter()

                self.assertFalse(formatter.COLORS_ENABLED)


class TestColorApplication(unittest.TestCase):
    """Test color application logic."""

    def setUp(self):
        """Set up test environment."""
        self.formatter = Formatter(use_colors=True)

    def test_apply_color_when_enabled(self):
        """Test color application when colors are enabled."""
        colored_text = self.formatter._apply_color("Hello", '\033[92m')

        self.assertEqual(colored_text, '\033[92mHello\033[0m')

    def test_apply_color_when_disabled(self):
        """Test color application when colors are disabled."""
        formatter = Formatter(use_colors=False)
        colored_text = formatter._apply_color("Hello", '\033[92m')

        self.assertEqual(colored_text, "Hello")

    def test_color_constants(self):
        """Test color code constants."""
        self.assertEqual(self.formatter.COLOR_SUCCESS, '\033[92m')
        self.assertEqual(self.formatter.COLOR_ERROR, '\033[91m')
        self.assertEqual(self.formatter.COLOR_WARNING, '\033[93m')
        self.assertEqual(self.formatter.COLOR_INFO, '\033[94m')
        self.assertEqual(self.formatter.COLOR_CODE, '\033[36m')
        self.assertEqual(self.formatter.COLOR_HEADER, '\033[1m')
        self.assertEqual(self.formatter.COLOR_RESET, '\033[0m')


class TestMessageFormatting(unittest.TestCase):
    """Test message formatting methods."""

    def setUp(self):
        """Set up test environment."""
        self.formatter = Formatter(use_colors=False)  # Disable colors for predictable output

    def test_success_message(self):
        """Test success message formatting."""
        result = self.formatter.success("Operation completed")

        self.assertEqual(result, "✅ Operation completed")

    def test_error_message(self):
        """Test error message formatting."""
        result = self.formatter.error("Operation failed")

        self.assertEqual(result, "❌ Operation failed")

    def test_warning_message(self):
        """Test warning message formatting."""
        result = self.formatter.warning("Please be careful")

        self.assertEqual(result, "⚠️  Please be careful")

    def test_info_message(self):
        """Test info message formatting."""
        result = self.formatter.info("Here's some information")

        self.assertEqual(result, "💡 Here's some information")

    def test_progress_message(self):
        """Test progress message formatting."""
        result = self.formatter.progress("Processing...")

        self.assertEqual(result, "⏳ Processing...")

    def test_file_message(self):
        """Test file message formatting."""
        result = self.formatter.file("main.py")

        self.assertEqual(result, "📄 main.py")

    def test_directory_message(self):
        """Test directory message formatting."""
        result = self.formatter.directory("/path/to/dir")

        self.assertEqual(result, "📁 /path/to/dir")

    def test_code_message(self):
        """Test code message formatting."""
        result = self.formatter.code("def function():")

        # Without colors, just emoji + message
        self.assertEqual(result, "📝 def function():")

    def test_code_message_with_colors(self):
        """Test code message with colors enabled."""
        formatter = Formatter(use_colors=True)
        result = formatter.code("def function():")

        # Should include color codes
        self.assertIn('\033[36m', result)
        self.assertIn('📝', result)
        self.assertIn('def function():', result)

    def test_header_level_1(self):
        """Test level 1 header formatting."""
        result = self.formatter.header("Main Title", level=1)

        self.assertIn("Main Title", result)
        self.assertIn("=" * 60, result)

    def test_header_level_2(self):
        """Test level 2 header formatting."""
        result = self.formatter.header("Section", level=2)

        self.assertIn("Section", result)
        self.assertIn("-" * 40, result)

    def test_header_level_3(self):
        """Test level 3 header formatting."""
        result = self.formatter.header("Subsection", level=3)

        self.assertIn("Subsection", result)
        # No line, just bold text
        self.assertNotIn("=", result)
        self.assertNotIn("-", result)

    def test_header_with_colors(self):
        """Test header with colors enabled."""
        formatter = Formatter(use_colors=True)
        result = formatter.header("Title", level=1)

        self.assertIn('\033[1m', result)  # Bold color code

    def test_section_formatting(self):
        """Test section formatting."""
        result = self.formatter.section("Section Title", "Section content here.")

        self.assertIn("Section Title", result)
        self.assertIn("Section content here.", result)
        self.assertIn("-" * 40, result)  # Level 2 header line

    def test_code_block(self):
        """Test code block formatting."""
        result = self.formatter.code_block("def hello():\n    print('world')", language="python")

        self.assertIn("```python", result)
        self.assertIn("def hello():", result)
        self.assertIn("print('world')", result)
        self.assertIn("```", result)

    def test_code_block_no_language(self):
        """Test code block without language."""
        result = self.formatter.code_block("plain text")

        self.assertEqual(result, "```plain text\n```")

    def test_list_item(self):
        """Test list item formatting."""
        result = self.formatter.list_item("First item")
        self.assertEqual(result, "  • First item")

        result = self.formatter.list_item("Second item", bullet="-")
        self.assertEqual(result, "  - Second item")

    def test_key_value(self):
        """Test key-value pair formatting."""
        result = self.formatter.key_value("Name", "John Doe")
        self.assertEqual(result, "  Name: John Doe")

        result = self.formatter.key_value("Age", "30", indent=4)
        self.assertEqual(result, "    Age: 30")

    def test_command_help(self):
        """Test command help formatting."""
        result = self.formatter.command_help(
            command="/search",
            description="Search the web for information",
            usage="/search <query>",
            examples="/search latest news\n/search Python tutorials"
        )

        self.assertIn("/search", result)
        self.assertIn("Search the web for information", result)
        self.assertIn("Usage:", result)
        self.assertIn("/search <query>", result)
        self.assertIn("Examples:", result)
        self.assertIn("latest news", result)

    def test_command_help_no_examples(self):
        """Test command help without examples."""
        result = self.formatter.command_help(
            command="/help",
            description="Show help",
            usage="/help [command]"
        )

        self.assertIn("/help", result)
        self.assertNotIn("Examples:", result)


class TestTableFormatting(unittest.TestCase):
    """Test table formatting."""

    def setUp(self):
        """Set up test environment."""
        self.formatter = Formatter(use_colors=False)

    def test_empty_table(self):
        """Test table with no rows."""
        result = self.formatter.table(["Col1", "Col2"], [])

        self.assertEqual(result, "")

    def test_basic_table(self):
        """Test basic table formatting."""
        headers = ["Name", "Age", "City"]
        rows = [
            ["Alice", "30", "New York"],
            ["Bob", "25", "London"],
            ["Charlie", "35", "Paris"]
        ]

        result = self.formatter.table(headers, rows)

        # Should contain headers
        self.assertIn("Name", result)
        self.assertIn("Age", result)
        self.assertIn("City", result)

        # Should contain data
        self.assertIn("Alice", result)
        self.assertIn("Bob", result)
        self.assertIn("Charlie", result)

        # Should have separator line
        self.assertIn("-", result)

        # Should align columns
        lines = result.split("\n")
        self.assertGreaterEqual(len(lines), 5)  # headers, separator, 3 rows

    def test_table_with_missing_cells(self):
        """Test table with missing cells in some rows."""
        headers = ["A", "B", "C"]
        rows = [
            ["a1", "b1"],  # Missing C
            ["a2", "b2", "c2"]
        ]

        result = self.formatter.table(headers, rows)

        # Should not crash
        self.assertIn("a1", result)
        self.assertIn("a2", result)

    def test_table_with_long_content(self):
        """Test table with content exceeding max column width."""
        headers = ["Short", "Very Long Column Name"]
        rows = [
            ["A", "This is a very long text that should be truncated"]
        ]

        result = self.formatter.table(headers, rows, max_col_width=20)

        # Should truncate with "..."
        self.assertIn("...", result)
        # Should not contain full text
        self.assertNotIn("This is a very long text that should be truncated", result)

    def test_table_with_non_string_values(self):
        """Test table with non-string values (integers, etc.)."""
        headers = ["ID", "Score"]
        rows = [
            [1, 95.5],
            [2, 87.0]
        ]

        result = self.formatter.table(headers, rows)

        # Should convert to string
        self.assertIn("1", result)
        self.assertIn("95.5", result)
        self.assertIn("2", result)
        self.assertIn("87.0", result)


class TestConvenienceFunctions(unittest.TestCase):
    """Test global convenience functions."""

    def test_success_function(self):
        """Test global success function."""
        with patch('agent.formatter._default_formatter') as mock_formatter:
            mock_formatter.success.return_value = "✅ Success"

            result = success("Operation complete")

            mock_formatter.success.assert_called_once_with("Operation complete")
            self.assertEqual(result, "✅ Success")

    def test_error_function(self):
        """Test global error function."""
        with patch('agent.formatter._default_formatter') as mock_formatter:
            mock_formatter.error.return_value = "❌ Error"

            result = error("Something went wrong")

            mock_formatter.error.assert_called_once_with("Something went wrong")
            self.assertEqual(result, "❌ Error")

    def test_warning_function(self):
        """Test global warning function."""
        with patch('agent.formatter._default_formatter') as mock_formatter:
            mock_formatter.warning.return_value = "⚠️  Warning"

            result = warning("Be careful")

            mock_formatter.warning.assert_called_once_with("Be careful")
            self.assertEqual(result, "⚠️  Warning")

    def test_info_function(self):
        """Test global info function."""
        with patch('agent.formatter._default_formatter') as mock_formatter:
            mock_formatter.info.return_value = "💡 Info"

            result = info("Information")

            mock_formatter.info.assert_called_once_with("Information")
            self.assertEqual(result, "💡 Info")

    def test_header_function(self):
        """Test global header function."""
        with patch('agent.formatter._default_formatter') as mock_formatter:
            mock_formatter.header.return_value = "# Header"

            result = header("Title", level=2)

            mock_formatter.header.assert_called_once_with("Title", 2)
            self.assertEqual(result, "# Header")

    def test_code_block_function(self):
        """Test global code_block function."""
        with patch('agent.formatter._default_formatter') as mock_formatter:
            mock_formatter.code_block.return_value = "```code```"

            result = code_block("print('hello')", language="python")

            mock_formatter.code_block.assert_called_once_with("print('hello')", "python")
            self.assertEqual(result, "```code```")

    def test_command_help_function(self):
        """Test global command_help function."""
        with patch('agent.formatter._default_formatter') as mock_formatter:
            mock_formatter.command_help.return_value = "Help text"

            result = command_help("/cmd", "Description", "Usage", "Examples")

            mock_formatter.command_help.assert_called_once_with("/cmd", "Description", "Usage", "Examples")
            self.assertEqual(result, "Help text")


if __name__ == '__main__':
    unittest.main()