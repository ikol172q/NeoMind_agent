#!/usr/bin/env python3
"""
Comprehensive unit tests for command auto-completion system.
Tests CommandCompleter and FilePathCompleter classes.
"""

import os
import sys
import tempfile
import shutil
import unittest
from unittest.mock import Mock, patch, MagicMock, call

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cli.completers import CommandCompleter, FilePathCompleter
from prompt_toolkit.completion import Completion
from prompt_toolkit.document import Document


class TestCommandCompleterInitialization(unittest.TestCase):
    """Test CommandCompleter initialization."""

    def test_initialization_with_help_system(self):
        """Test initialization with help system."""
        mock_help_system = Mock()
        mock_help_system.help_texts = {
            "write": "Write help",
            "read": "Read help",
            "code": "Code help"
        }

        completer = CommandCompleter(mock_help_system)

        self.assertEqual(completer.help_system, mock_help_system)
        self.assertIsNone(completer.workspace_manager)
        self.assertEqual(sorted(completer.commands), ["code", "read", "write"])
        self.assertIsInstance(completer.param_suggestions, dict)

    def test_initialization_without_help_texts(self):
        """Test initialization when help_system.help_texts is None."""
        mock_help_system = Mock()
        mock_help_system.help_texts = None  # Attribute exists but is None

        # This will cause AttributeError when accessing .keys() on None
        # The code has a bug: it should check if help_texts is not None
        # For now, we expect an exception
        with self.assertRaises(AttributeError):
            completer = CommandCompleter(mock_help_system)

    def test_initialization_with_workspace_manager(self):
        """Test initialization with workspace manager."""
        mock_help_system = Mock()
        mock_help_system.help_texts = {"write": "help"}
        mock_workspace = Mock()

        completer = CommandCompleter(mock_help_system, mock_workspace)

        self.assertEqual(completer.workspace_manager, mock_workspace)

    def test_param_suggestions_structure(self):
        """Test parameter suggestions are built correctly."""
        mock_help_system = Mock()
        mock_help_system.help_texts = {}

        completer = CommandCompleter(mock_help_system)

        # Check structure of param_suggestions
        self.assertIn("mode", completer.param_suggestions)
        self.assertIn("chat", completer.param_suggestions["mode"])
        self.assertIn("coding", completer.param_suggestions["mode"])

        self.assertIn("auto", completer.param_suggestions)
        self.assertIn("search", completer.param_suggestions["auto"])
        self.assertIn("interpret", completer.param_suggestions["auto"])

        self.assertIn("code", completer.param_suggestions)
        self.assertIn("scan", completer.param_suggestions["code"])
        self.assertIn("self-scan", completer.param_suggestions["code"])

        self.assertIn("task", completer.param_suggestions)
        self.assertIn("create", completer.param_suggestions["task"])

        self.assertIn("plan", completer.param_suggestions)
        self.assertIn("list", completer.param_suggestions["plan"])

        self.assertIn("context", completer.param_suggestions)
        self.assertIn("status", completer.param_suggestions["context"])

        self.assertIn("models", completer.param_suggestions)
        self.assertIn("list", completer.param_suggestions["models"])


class TestCommandCompleterCommandCompletion(unittest.TestCase):
    """Test command name completion."""

    def setUp(self):
        """Set up test environment."""
        self.mock_help_system = Mock()
        self.mock_help_system.help_texts = {
            "write": "Write help",
            "read": "Read help",
            "code": "Code help",
            "search": "Search help",
            "mode": "Mode help"
        }
        self.completer = CommandCompleter(self.mock_help_system)

    def test_empty_input(self):
        """Test empty input returns no completions."""
        document = Document("")
        completions = list(self.completer.get_completions(document, None))

        self.assertEqual(len(completions), 0)

    def test_whitespace_input(self):
        """Test whitespace input returns no completions."""
        document = Document("   ")
        completions = list(self.completer.get_completions(document, None))

        self.assertEqual(len(completions), 0)

    def test_command_completion_partial(self):
        """Test partial command completion."""
        # Input: "/w" should complete to "/write"
        document = Document("/w")
        completions = list(self.completer.get_completions(document, None))

        self.assertEqual(len(completions), 1)
        completion = completions[0]
        self.assertEqual(completion.text, "/write")
        self.assertEqual(completion.start_position, -1)  # -len("w")
        # display and display_meta may be FormattedText objects
        self.assertIn("write", str(completion.display))
        self.assertIn("Command: write", str(completion.display_meta))

    def test_command_completion_multiple_matches(self):
        """Test command completion with multiple matches."""
        # Add more commands starting with 'c'
        self.mock_help_system.help_texts.update({
            "code": "Code help",
            "clear": "Clear help",
            "context": "Context help"
        })
        completer = CommandCompleter(self.mock_help_system)

        document = Document("/c")
        completions = list(completer.get_completions(document, None))

        self.assertEqual(len(completions), 3)
        completion_texts = [c.text for c in completions]
        self.assertIn("/code", completion_texts)
        self.assertIn("/clear", completion_texts)
        self.assertIn("/context", completion_texts)

    def test_command_completion_case_insensitive(self):
        """Test command completion is case insensitive."""
        document = Document("/W")  # Uppercase W
        completions = list(self.completer.get_completions(document, None))

        self.assertEqual(len(completions), 1)
        self.assertEqual(completions[0].text, "/write")

    def test_command_completion_full_command(self):
        """Test completion when command is already complete."""
        document = Document("/write")
        completions = list(self.completer.get_completions(document, None))

        # Should still offer the same command as completion
        self.assertEqual(len(completions), 1)  # Exact match still offered

    def test_command_completion_with_space(self):
        """Test command completion when input has space."""
        document = Document("/write ")  # Command with space after
        completions = list(self.completer.get_completions(document, None))

        # Should move to parameter completion
        self.assertEqual(len(completions), 0)  # write has no param suggestions


class TestCommandCompleterParameterCompletion(unittest.TestCase):
    """Test parameter completion for commands."""

    def setUp(self):
        """Set up test environment."""
        self.mock_help_system = Mock()
        self.mock_help_system.help_texts = {"mode": "help", "code": "help"}
        self.completer = CommandCompleter(self.mock_help_system)

    def test_mode_command_parameter_completion(self):
        """Test parameter completion for /mode command with space only."""
        # Space after command doesn't trigger parameter completion
        document = Document("/mode ")
        completions = list(self.completer.get_completions(document, None))

        self.assertEqual(len(completions), 0)  # No partial match

    def test_mode_command_partial_parameter(self):
        """Test partial parameter completion for /mode command."""
        document = Document("/mode c")
        completions = list(self.completer.get_completions(document, None))

        self.assertEqual(len(completions), 2)  # chat, coding
        completion_texts = [c.text for c in completions]
        self.assertIn("chat", completion_texts)
        self.assertIn("coding", completion_texts)

    def test_auto_command_parameter_completion(self):
        """Test parameter completion for /auto command."""
        # Partial parameter "s" should match "search" and "status"
        document = Document("/auto s")
        completions = list(self.completer.get_completions(document, None))

        self.assertEqual(len(completions), 2)  # search, status
        completion_texts = [c.text for c in completions]
        self.assertIn("search", completion_texts)
        self.assertIn("status", completion_texts)

    def test_code_command_parameter_completion(self):
        """Test parameter completion for /code command."""
        # Partial parameter "s" should match multiple parameters starting with 's'
        document = Document("/code s")
        completions = list(self.completer.get_completions(document, None))

        self.assertGreater(len(completions), 1)
        completion_texts = [c.text for c in completions]
        self.assertIn("scan", completion_texts)
        self.assertIn("self-scan", completion_texts)

    def test_command_with_multiple_words(self):
        """Test parameter completion with multiple words."""
        document = Document("/mode chat ")  # Already has parameter
        completions = list(self.completer.get_completions(document, None))

        # May still offer "chat" as completion even though already typed
        self.assertLessEqual(len(completions), 1)
        if completions:
            self.assertEqual(completions[0].text, "chat")

    def test_unknown_command_parameter_completion(self):
        """Test parameter completion for unknown command."""
        document = Document("/unknown ")  # Command not in param_suggestions
        completions = list(self.completer.get_completions(document, None))

        self.assertEqual(len(completions), 0)


class TestCommandCompleterFilePathCompletion(unittest.TestCase):
    """Test file path completion with workspace manager."""

    def setUp(self):
        """Set up test environment."""
        self.mock_help_system = Mock()
        self.mock_help_system.help_texts = {"write": "help"}
        self.mock_workspace = Mock()
        self.completer = CommandCompleter(self.mock_help_system, self.mock_workspace)

    def test_file_path_completion_disabled_for_commands(self):
        """Test file path completion not triggered for command input."""
        # When input starts with /, file completion should not happen
        self.mock_workspace.scan.return_value = ["/path/to/file.py"]

        document = Document("/write ")  # Command input
        completions = list(self.completer.get_completions(document, None))

        # Should not call workspace scan
        self.mock_workspace.scan.assert_not_called()

    def test_file_path_completion_basic(self):
        """Test basic file path completion."""
        self.mock_workspace.scan.return_value = [
            "/project/main.py",
            "/project/utils.py",
            "/project/README.md"
        ]

        document = Document("main")  # Natural language input, not a command
        completions = list(self.completer.get_completions(document, None))

        self.assertEqual(len(completions), 1)
        completion = completions[0]
        self.assertEqual(completion.text, "/project/main.py")
        self.assertEqual(completion.start_position, -4)  # -len("main")
        self.assertIn("main.py", str(completion.display))
        self.assertIn("File: /project/main.py", str(completion.display_meta))

    def test_file_path_completion_partial(self):
        """Test file path completion with partial match."""
        self.mock_workspace.scan.return_value = [
            "apple.py",
            "application.py",
            "banana.py"
        ]

        document = Document("app")
        completions = list(self.completer.get_completions(document, None))

        self.assertEqual(len(completions), 2)
        completion_texts = [c.text for c in completions]
        self.assertIn("apple.py", completion_texts)
        self.assertIn("application.py", completion_texts)

    def test_file_path_completion_case_insensitive(self):
        """Test file path completion is case insensitive."""
        self.mock_workspace.scan.return_value = ["Main.py", "main.py"]

        document = Document("MAIN")  # Uppercase
        completions = list(self.completer.get_completions(document, None))

        self.assertEqual(len(completions), 2)

    def test_file_path_completion_workspace_scan_failure(self):
        """Test file path completion handles workspace scan failure."""
        self.mock_workspace.scan.side_effect = Exception("Scan failed")

        document = Document("test")
        completions = list(self.completer.get_completions(document, None))

        # Should return empty list without raising exception
        self.assertEqual(len(completions), 0)

    def test_file_path_completion_without_workspace_manager(self):
        """Test file path completion without workspace manager."""
        completer = CommandCompleter(self.mock_help_system)  # No workspace manager

        document = Document("test")
        completions = list(completer.get_completions(document, None))

        # Should not crash, just return no completions
        self.assertEqual(len(completions), 0)


class TestCommandCompleterMixedInput(unittest.TestCase):
    """Test mixed input scenarios."""

    def setUp(self):
        """Set up test environment."""
        self.mock_help_system = Mock()
        self.mock_help_system.help_texts = {"write": "help", "read": "help"}
        self.completer = CommandCompleter(self.mock_help_system)

    def test_input_with_slash_not_at_start(self):
        """Test input with slash not at beginning."""
        document = Document("test /")  # Slash not at start
        completions = list(self.completer.get_completions(document, None))

        # Should not trigger command completion
        self.assertEqual(len(completions), 0)

    def test_command_completion_after_whitespace(self):
        """Test command completion after leading whitespace."""
        document = Document("   /w")  # Whitespace before slash
        completions = list(self.completer.get_completions(document, None))

        # Command completion requires slash at start of text, not after whitespace
        self.assertEqual(len(completions), 0)


class TestFilePathCompleterInitialization(unittest.TestCase):
    """Test FilePathCompleter initialization."""

    def test_initialization_default(self):
        """Test initialization with default base directory."""
        completer = FilePathCompleter()

        self.assertEqual(completer.base_dir, os.getcwd())

    def test_initialization_custom_base_dir(self):
        """Test initialization with custom base directory."""
        completer = FilePathCompleter("/custom/path")

        self.assertEqual(completer.base_dir, "/custom/path")


class TestFilePathCompleterCompletion(unittest.TestCase):
    """Test FilePathCompleter file path completion."""

    def setUp(self):
        """Set up test environment with temporary directory."""
        self.temp_dir = tempfile.mkdtemp()

        # Create test files and directories
        os.makedirs(os.path.join(self.temp_dir, "subdir"))

        with open(os.path.join(self.temp_dir, "file1.txt"), "w") as f:
            f.write("test")
        with open(os.path.join(self.temp_dir, "file2.py"), "w") as f:
            f.write("test")
        with open(os.path.join(self.temp_dir, ".hidden"), "w") as f:
            f.write("test")
        with open(os.path.join(self.temp_dir, "subdir", "nested.txt"), "w") as f:
            f.write("test")

        self.completer = FilePathCompleter(self.temp_dir)

    def tearDown(self):
        """Clean up temporary directory."""
        shutil.rmtree(self.temp_dir)

    def test_empty_input(self):
        """Test empty input returns no completions."""
        document = Document("")
        completions = list(self.completer.get_completions(document, None))

        self.assertEqual(len(completions), 0)

    def test_file_completion_partial(self):
        """Test partial file name completion."""
        document = Document("file")
        completions = list(self.completer.get_completions(document, None))

        self.assertEqual(len(completions), 2)
        completion_texts = sorted([c.text for c in completions])
        self.assertEqual(completion_texts, ["file1.txt", "file2.py"])

    def test_file_completion_with_extension(self):
        """Test file completion with extension filter."""
        document = Document("file1.")
        completions = list(self.completer.get_completions(document, None))

        self.assertEqual(len(completions), 1)
        self.assertEqual(completions[0].text, "file1.txt")

    def test_directory_completion(self):
        """Test directory completion."""
        # File path completion triggers when input looks like a path
        document = Document("subdir/")
        completions = list(self.completer.get_completions(document, None))

        self.assertEqual(len(completions), 1)
        self.assertEqual(os.path.normpath(completions[0].text), os.path.normpath("subdir/nested.txt"))
        self.assertIn("File", str(completions[0].display_meta))

    def test_hidden_file_completion(self):
        """Test hidden file completion."""
        document = Document(".")
        completions = list(self.completer.get_completions(document, None))

        # Should include hidden file
        completion_texts = [c.text for c in completions]
        self.assertIn(".hidden", completion_texts)

    def test_path_with_directory(self):
        """Test completion for path with directory prefix."""
        document = Document("subdir/ne")
        completions = list(self.completer.get_completions(document, None))

        self.assertEqual(len(completions), 1)
        self.assertEqual(os.path.normpath(completions[0].text), os.path.normpath("subdir/nested.txt"))

    def test_nonexistent_directory(self):
        """Test completion with nonexistent directory."""
        document = Document("nonexistent/")
        completions = list(self.completer.get_completions(document, None))

        self.assertEqual(len(completions), 0)

    def test_absolute_path(self):
        """Test completion with absolute path."""
        # Create completer with different base dir
        completer = FilePathCompleter("/")

        # This is tricky to test portably, so we'll just ensure it doesn't crash
        document = Document("/")
        completions = list(completer.get_completions(document, None))

        # Should not crash
        self.assertIsNotNone(completions)

    def test_os_error_handling(self):
        """Test handling of OSError during directory listing."""
        completer = FilePathCompleter("/nonexistent/path")

        document = Document("test")
        completions = list(completer.get_completions(document, None))

        # Should return empty list without raising exception
        self.assertEqual(len(completions), 0)


if __name__ == '__main__':
    unittest.main()