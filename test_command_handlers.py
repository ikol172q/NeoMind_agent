#!/usr/bin/env python3
"""
Unit tests for command handlers.
Mock external dependencies to test command logic in isolation.
"""
import os
import sys
import time
import unittest
from unittest.mock import Mock, patch, MagicMock, ANY

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent.core import DeepSeekStreamingChat

class TestCommandHandlers(unittest.TestCase):
    """Test command handlers with mocked dependencies."""

    def setUp(self):
        """Create agent with mocked dependencies."""
        self.agent = DeepSeekStreamingChat(api_key="dummy_key")
        # Mock external dependencies
        self.agent.code_analyzer = Mock()
        self.agent.safety_manager = Mock()
        self.agent.safety_manager.safe_read_file = Mock(return_value=(True, "", "file content"))
        self.agent.safety_manager.safe_write_file = Mock(return_value=(True, "", None))
        self.agent.formatter = Mock()
        self.agent.command_executor = Mock()
        self.agent.help_system = Mock()
        self.agent.searcher = Mock()
        self.agent.self_iteration = None
        # Set up formatter methods to return strings
        self.agent.formatter.error = Mock(return_value="ERROR")
        self.agent.formatter.success = Mock(return_value="SUCCESS")
        self.agent.formatter.warning = Mock(return_value="WARNING")
        self.agent.formatter.info = Mock(return_value="INFO")
        # Default mock for code_analyzer file operations
        self.agent.code_analyzer.read_file_safe = Mock(return_value=(True, "", "file content"))
        self.agent.code_analyzer.write_file_safe = Mock(return_value=(True, "File written"))
        # Mock code_analyzer root_path
        self.agent.code_analyzer.root_path = os.getcwd()

    def test_handle_write_command_basic(self):
        """Test /write command with content."""
        # Mock write_file_safe to succeed
        self.agent.code_analyzer.write_file_safe = Mock(return_value=(True, "File written"))
        # Call handler
        result = self.agent.handle_write_command("test.txt Hello World")
        # Verify code analyzer was called with correct arguments
        self.agent.code_analyzer.write_file_safe.assert_called_once_with("test.txt", "Hello World")
        # Verify formatter.success was called
        self.agent.formatter.success.assert_called_once_with("File written")
        # Result should be the formatted success message
        self.assertEqual(result, "SUCCESS")

    def test_handle_write_command_missing_path(self):
        """Test /write command with missing file path."""
        result = self.agent.handle_write_command("")
        # Should return help text (formatter not used)
        self.assertIsInstance(result, str)
        self.assertIn("/write", result)

    def test_handle_write_command_interactive(self):
        """Test /write --interactive reads content interactively."""
        with patch.object(self.agent, '_read_interactive_content', return_value="interactive content"):
            result = self.agent.handle_write_command("--interactive test.txt")
            # Should call write_file_safe with interactive content
            self.agent.code_analyzer.write_file_safe.assert_called_once_with("test.txt", "interactive content")
            self.agent.formatter.success.assert_called_once()
            self.assertEqual(result, "SUCCESS")

    def test_handle_read_command_local_file(self):
        """Test /read command with local file."""
        # Mock _is_likely_file_path to return True
        with patch.object(self.agent, '_is_likely_file_path', return_value=True):
            with patch.object(self.agent, '_handle_file_read') as mock_handle:
                mock_handle.return_value = "FILE CONTENT"
                result = self.agent.handle_read_command("test.txt")
                mock_handle.assert_called_once_with("test.txt", False)
                self.assertEqual(result, "FILE CONTENT")

    def test_handle_edit_command_basic(self):
        """Test /edit command with old and new code."""
        # Mock validate_proposed_change to return valid
        with patch.object(self.agent, 'validate_proposed_change', return_value=(True, "")):
            # Mock propose_code_change
            self.agent.propose_code_change = Mock(return_value="Change proposed")
            # Call handler with quoted arguments
            result = self.agent.handle_edit_command('test.py "print(\\"old\\")" "print(\\"new\\")"')
            # Should call propose_code_change
            self.agent.propose_code_change.assert_called_once()
            # Check arguments (file_path, old_code, new_code, description, line)
            call_args = self.agent.propose_code_change.call_args
            self.assertEqual(call_args[0][0], "test.py")
            self.assertEqual(call_args[0][1], 'print("old")')
            self.assertEqual(call_args[0][2], 'print("new")')
            self.assertEqual(call_args[0][3], "Manual edit via /edit command")
            self.assertIsNone(call_args[0][4])

    def test_handle_run_command_basic(self):
        """Test /run command."""
        self.agent.command_executor.execute.return_value = {
            'success': True,
            'returncode': 0,
            'stdout': 'output',
            'stderr': '',
            'execution_time': 0.5,
            'error_message': ''
        }
        result = self.agent.handle_run_command("ls -la")
        # Verify command_executor.execute called with any cwd (depends on code_analyzer.root_path)
        self.agent.command_executor.execute.assert_called_once_with("ls -la", cwd=ANY)
        # Result should contain formatted output
        self.assertIn("Command:", result)
        self.assertIn("STDOUT", result)

    def test_handle_git_command_basic(self):
        """Test /git command."""
        self.agent.command_executor.execute_git.return_value = {
            'success': True,
            'returncode': 0,
            'stdout': 'git status output',
            'stderr': '',
            'execution_time': 0.2,
            'error_message': ''
        }
        result = self.agent.handle_git_command("status")
        self.agent.command_executor.execute_git.assert_called_once_with("status", cwd=os.getcwd())
        self.assertIn("git status output", result)

    def test_handle_code_command_scan(self):
        """Test /code scan command."""
        with patch.object(self.agent, '_code_scan') as mock_scan:
            mock_scan.return_value = "Scan result"
            result = self.agent.handle_code_command("scan /some/path")
            mock_scan.assert_called_once_with("/some/path")
            self.assertEqual(result, "Scan result")

    def test_handle_code_command_changes(self):
        """Test /code changes command."""
        with patch.object(self.agent, '_code_show_changes') as mock_show:
            mock_show.return_value = "Pending changes list"
            result = self.agent.handle_code_command("changes")
            mock_show.assert_called_once()
            self.assertEqual(result, "Pending changes list")

    def test_handle_code_command_apply(self):
        """Test /code apply command."""
        with patch.object(self.agent, '_code_apply_changes') as mock_apply:
            mock_apply.return_value = "Changes applied"
            result = self.agent.handle_code_command("apply")
            mock_apply.assert_called_once()
            self.assertEqual(result, "Changes applied")

    def test_handle_diff_command_basic(self):
        """Test /diff command comparing two files."""
        # Mock read_file_safe to return dummy content
        self.agent.code_analyzer.read_file_safe = Mock(side_effect=[
            (True, "", "content1"),
            (True, "", "content2")
        ])
        result = self.agent.handle_diff_command("file1.py file2.py")
        # Should call read_file_safe twice
        self.assertEqual(self.agent.code_analyzer.read_file_safe.call_count, 2)
        # Should contain diff result (since contents differ)
        self.assertIn("Diff between", result)

    def test_handle_diff_command_git(self):
        """Test /diff --git command."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value.stdout = "git diff output"
            result = self.agent.handle_diff_command("--git file.py")
            mock_run.assert_called_once()
            self.assertIn("Git diff for", result)

    def test_handle_diff_command_backup_not_implemented(self):
        """Test /diff --backup returns not implemented."""
        result = self.agent.handle_diff_command("--backup file.py")
        self.assertIn("not yet implemented", result)

    def test_handle_diff_command_missing_args(self):
        """Test /diff with missing arguments."""
        result = self.agent.handle_diff_command("")
        self.assertIn("/diff", result)  # help text
        result2 = self.agent.handle_diff_command("single")
        # Should call formatter.error
        self.agent.formatter.error.assert_called()
        self.assertEqual(result2, "ERROR")

    def test_handle_browse_command_basic(self):
        """Test /browse command."""
        with patch('os.listdir') as mock_listdir, \
             patch('os.path.exists') as mock_exists, \
             patch('os.path.isdir') as mock_isdir, \
             patch('os.getcwd') as mock_getcwd:
            mock_getcwd.return_value = '/test/dir'
            mock_exists.return_value = True
            # First call for root path, then for each item
            def isdir_side(path):
                if path == '/test/dir':
                    return True
                return 'subdir' in path
            mock_isdir.side_effect = isdir_side
            mock_listdir.return_value = ['file1.py', 'file2.txt', 'subdir']
            result = self.agent.handle_browse_command("")
            self.assertIn("Directory:", result)
            self.assertIn("Items:", result)
            mock_listdir.assert_called_once_with('/test/dir')

    def test_handle_browse_command_with_path(self):
        """Test /browse with specific path."""
        with patch('os.listdir') as mock_listdir, \
             patch('os.path.exists') as mock_exists, \
             patch('os.path.isdir') as mock_isdir, \
             patch('os.path.isabs') as mock_isabs:
            mock_isabs.return_value = False
            mock_exists.return_value = True
            mock_isdir.return_value = True
            mock_listdir.return_value = ['file.py']
            result = self.agent.handle_browse_command("some/path")
            mock_listdir.assert_called_once()

    def test_handle_browse_command_with_filter(self):
        """Test /browse --filter .py."""
        with patch('os.listdir') as mock_listdir, \
             patch('os.path.exists') as mock_exists, \
             patch('os.path.isdir') as mock_isdir, \
             patch('os.getcwd') as mock_getcwd:
            mock_getcwd.return_value = '/test/dir'
            mock_exists.return_value = True
            def isdir_side(path):
                if path == '/test/dir':
                    return True
                # Treat items with '.' as files, else as directories
                return '.' not in os.path.basename(path)
            mock_isdir.side_effect = isdir_side
            mock_listdir.return_value = ['file.py', 'file.txt', 'script.py', 'docs']
            result = self.agent.handle_browse_command("--filter .py")
            # Should only list .py files (not .txt, not directories)
            self.assertIn("file.py", result)
            self.assertIn("script.py", result)
            self.assertNotIn("file.txt", result)
            # docs is a directory, should appear in Directories
            self.assertIn("docs", result)
            # Verify filter indicator appears
            self.assertIn("filtered: *.py", result)

    def test_handle_browse_command_nonexistent_path(self):
        """Test /browse with nonexistent path."""
        with patch('os.path.exists') as mock_exists:
            mock_exists.return_value = False
            result = self.agent.handle_browse_command("invalid/path")
            self.agent.formatter.error.assert_called_once()
            self.assertEqual(result, "ERROR")

    def test_handle_undo_command_list(self):
        """Test /undo list command."""
        mock_si = Mock()
        mock_si.get_change_history.return_value = [
            {'timestamp': 1234567890, 'file_path': '/test/file.py', 'description': 'Test change', 'backup': '/backup/file.py.backup'}
        ]
        with patch.object(self.agent, '_get_self_iteration', return_value=mock_si), \
             patch('time.strftime') as mock_strftime, \
             patch('time.localtime') as mock_localtime:
            mock_localtime.return_value = time.struct_time((2025, 1, 1, 0, 0, 0, 0, 0, 0))
            mock_strftime.return_value = '2025-01-01 00:00:00'
            result = self.agent.handle_undo_command("list")
            mock_si.get_change_history.assert_called_once_with(limit=5)
            self.assertIn("Recent Changes", result)
            self.assertIn("file.py", result)

    def test_handle_undo_command_last(self):
        """Test /undo last command."""
        mock_si = Mock()
        mock_si.get_change_history.return_value = [
            {'timestamp': 123, 'file_path': '/test/file.py', 'description': 'Test', 'backup': '/backup'}
        ]
        with patch.object(self.agent, '_get_self_iteration', return_value=mock_si), \
             patch.object(self.agent, '_revert_change') as mock_revert:
            mock_revert.return_value = "Reverted"
            result = self.agent.handle_undo_command("last")
            mock_si.get_change_history.assert_called_once_with(limit=1)
            mock_revert.assert_called_once()

    def test_handle_undo_command_by_id(self):
        """Test /undo <id> command."""
        mock_si = Mock()
        mock_si.get_change_history.return_value = [
            {'timestamp': 1, 'file_path': 'f1', 'description': 'd1', 'backup': 'b1'},
            {'timestamp': 2, 'file_path': 'f2', 'description': 'd2', 'backup': 'b2'}
        ]
        with patch.object(self.agent, '_get_self_iteration', return_value=mock_si), \
             patch.object(self.agent, '_revert_change') as mock_revert:
            mock_revert.return_value = "Reverted"
            result = self.agent.handle_undo_command("2")
            mock_si.get_change_history.assert_called_once_with(limit=12)  # change_id + 10
            mock_revert.assert_called_once()

    def test_handle_undo_command_invalid(self):
        """Test /undo with invalid command."""
        result = self.agent.handle_undo_command("invalid")
        self.agent.formatter.error.assert_called()
        self.assertEqual(result, "ERROR")

    def test_handle_undo_command_help(self):
        """Test /undo --help."""
        result = self.agent.handle_undo_command("--help")
        self.assertIn("/undo", result)

    def test_handle_test_command_basic(self):
        """Test /test basic command."""
        with patch('os.path.exists') as mock_exists, \
             patch('subprocess.run') as mock_run:
            mock_exists.return_value = True
            mock_run.return_value.stdout = "test output"
            mock_run.return_value.stderr = ""
            mock_run.return_value.returncode = 0
            result = self.agent.handle_test_command("basic")
            mock_run.assert_called_once()
            self.agent.formatter.success.assert_called()

    def test_handle_test_command_unit(self):
        """Test /test unit command."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value.stdout = "pytest output"
            mock_run.return_value.stderr = ""
            mock_run.return_value.returncode = 0
            result = self.agent.handle_test_command("unit")
            mock_run.assert_called_once()
            self.agent.formatter.success.assert_called()

    def test_handle_test_command_help(self):
        """Test /test --help."""
        result = self.agent.handle_test_command("--help")
        self.assertIn("/test", result)

    def test_handle_apply_command_basic(self):
        """Test /apply command."""
        with patch.object(self.agent, '_code_apply_changes') as mock_apply:
            mock_apply.return_value = "Changes applied"
            result = self.agent.handle_apply_command("")
            mock_apply.assert_called_once()
            self.assertEqual(result, "Changes applied")

    def test_handle_apply_command_force(self):
        """Test /apply force."""
        with patch.object(self.agent, '_code_apply_changes_confirm') as mock_confirm:
            mock_confirm.return_value = "Applied"
            result = self.agent.handle_apply_command("force")
            mock_confirm.assert_called_once_with(force=True)

    def test_handle_fix_command(self):
        """Test /fix command."""
        # /fix maps to handle_auto_fix_command, which returns None (special handling)
        result = self.agent.handle_auto_fix_command("/fix some/file.py")
        self.assertIsNone(result)

    def test_handle_analyze_command(self):
        """Test /analyze command."""
        # Same handler as fix
        result = self.agent.handle_auto_fix_command("/analyze some/file.py")
        self.assertIsNone(result)

    def test_handle_search_command(self):
        """Test /search command."""
        # /search is handled by handle_search (not handle_search_command)
        with patch.object(self.agent, 'handle_search') as mock_search:
            mock_search.return_value = "search results"
            result = self.agent.handle_search("query")
            mock_search.assert_called_once_with("query")
            self.assertEqual(result, "search results")

    def test_handle_models_command(self):
        """Test /models command."""
        with patch.object(self.agent, 'print_models') as mock_print:
            mock_print.return_value = None
            result = self.agent.handle_models_command("/models")
            mock_print.assert_called_once_with()
            self.assertIsNone(result)

    def test_handle_help_command(self):
        """Test /help command."""
        result = self.agent.handle_help_command("")
        self.assertIn("Available Commands", result)
        result2 = self.agent.handle_help_command("write")
        self.assertIn("/write", result2)

    def test_handle_code_command_reason(self):
        """Test /code reason command."""
        # Mock dependencies
        self.agent.code_analyzer.read_file_safe = Mock(return_value=(True, "", "def foo(): pass"))
        with patch.object(self.agent, 'generate_completion') as mock_gen, \
             patch.object(self.agent, 'list_models') as mock_list:
            mock_gen.return_value = "Analysis result"
            mock_list.return_value = [
                {"id": "deepseek-chat", "created": None, "owned_by": "deepseek"},
                {"id": "deepseek-reasoner", "created": None, "owned_by": "deepseek"},
                {"id": "deepseek-coder", "created": None, "owned_by": "deepseek"}
            ]
            result = self.agent.handle_code_command("reason test.py")
            # Should call read_file_safe
            self.agent.code_analyzer.read_file_safe.assert_called_once_with("test.py")
            # Should call generate_completion with appropriate messages
            mock_gen.assert_called_once()
            # Check that result contains analysis
            self.assertIn("DEEP ANALYSIS", result)
            self.assertIn("test.py", result)

    def test_with_model_switching(self):
        """Test temporary model switching with with_model."""
        # Mock list_models to return models
        with patch.object(self.agent, 'list_models') as mock_list:
            mock_list.return_value = [
                {"id": "deepseek-chat", "created": None, "owned_by": "deepseek"},
                {"id": "deepseek-reasoner", "created": None, "owned_by": "deepseek"}
            ]
            # Track model changes
            original_model = self.agent.model
            call_count = 0
            def dummy_func():
                nonlocal call_count
                call_count += 1
                # During execution, model should be switched
                self.assertEqual(self.agent.model, "deepseek-reasoner")
                return "result"

            result = self.agent.with_model("deepseek-reasoner", dummy_func)
            self.assertEqual(result, "result")
            self.assertEqual(call_count, 1)
            # Model should be restored
            self.assertEqual(self.agent.model, original_model)

    def test_with_model_invalid_model(self):
        """Test with_model raises ValueError for unavailable model."""
        with patch.object(self.agent, 'list_models') as mock_list:
            mock_list.return_value = [{"id": "deepseek-chat"}]
            with self.assertRaises(ValueError):
                self.agent.with_model("deepseek-reasoner", lambda: None)

if __name__ == '__main__':
    unittest.main()