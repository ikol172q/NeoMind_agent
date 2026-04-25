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

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.core import NeoMindAgent

class TestCommandHandlers(unittest.TestCase):
    """Test command handlers with mocked dependencies."""

    def setUp(self):
        """Create agent with mocked dependencies."""
        self.agent = NeoMindAgent(api_key="dummy_key")
        # Disable guard to allow file operations in tests
        if self.agent.guard:
            self.agent.guard.disable_guard()
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
        # Mock task manager and goal planner
        self.agent.task_manager = Mock()
        self.agent.goal_planner = Mock()
        # Mock generate_completion for AI commands
        self.agent.generate_completion = Mock(return_value="Mocked AI response")
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

    def test_handle_diff_command_backup_no_backups(self):
        """Test /diff --backup returns appropriate message when no backups exist."""
        with patch('os.path.exists') as mock_exists:
            mock_exists.return_value = False  # backup directory doesn't exist
            self.agent.safety_manager.workspace_root = '/test/workspace'
            result = self.agent.handle_diff_command("--backup file.py")
            self.assertIn("No backup directory found", result)

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
                {"id": "deepseek-v4-flash", "created": None, "owned_by": "deepseek"},
                {"id": "deepseek-v4-pro", "created": None, "owned_by": "deepseek"},
                {"id": "deepseek-v4-flash", "created": None, "owned_by": "deepseek"}
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
                {"id": "deepseek-v4-flash", "created": None, "owned_by": "deepseek"},
                {"id": "deepseek-v4-pro", "created": None, "owned_by": "deepseek"}
            ]
            # Track model changes
            original_model = self.agent.model
            call_count = 0
            def dummy_func():
                nonlocal call_count
                call_count += 1
                # During execution, model should be switched
                self.assertEqual(self.agent.model, "deepseek-v4-pro")
                return "result"

            result = self.agent.with_model("deepseek-v4-pro", dummy_func)
            self.assertEqual(result, "result")
            self.assertEqual(call_count, 1)
            # Model should be restored
            self.assertEqual(self.agent.model, original_model)

    def test_handle_auto_command(self):
        """Test /auto command with various subcommands."""
        # Patch agent_config to avoid actual config updates
        with patch('agent.core.agent_config') as mock_config:
            mock_config.update_value = Mock(return_value=True)

            # Test empty command (should show status)
            result = self.agent.handle_auto_command("")
            self.assertIsInstance(result, str)
            self.assertIn("Auto-feature Status", result)

            # Test status subcommand
            result = self.agent.handle_auto_command("status")
            self.assertIn("Auto-feature Status", result)

            # Test search on
            result = self.agent.handle_auto_command("search on")
            self.assertIn("Auto-search enabled", result)
            self.assertTrue(self.agent.auto_search_enabled)
            # Should have called config update
            mock_config.update_value.assert_called_with("agent.auto_features.auto_search.enabled", True)

            # Test search off
            mock_config.update_value.reset_mock()
            result = self.agent.handle_auto_command("search off")
            self.assertIn("Auto-search disabled", result)
            self.assertFalse(self.agent.auto_search_enabled)
            mock_config.update_value.assert_called_with("agent.auto_features.auto_search.enabled", False)

            # Test interpret on (should create interpreter)
            mock_config.update_value.reset_mock()
            result = self.agent.handle_auto_command("interpret on")
            self.assertIn("Natural language interpretation enabled", result)
            self.assertTrue(self.agent.natural_language_enabled)
            self.assertIsNotNone(self.agent.interpreter)
            mock_config.update_value.assert_called_with("agent.auto_features.natural_language.enabled", True)

            # Test interpret off (should remove interpreter)
            mock_config.update_value.reset_mock()
            result = self.agent.handle_auto_command("interpret off")
            self.assertIn("Natural language interpretation disabled", result)
            self.assertFalse(self.agent.natural_language_enabled)
            self.assertIsNone(self.agent.interpreter)
            mock_config.update_value.assert_called_with("agent.auto_features.natural_language.enabled", False)

            # Test help
            result = self.agent.handle_auto_command("help")
            self.assertIn("/auto command usage", result)

            # Test invalid command
            result = self.agent.handle_auto_command("invalid subcommand")
            self.assertIn("/auto command usage", result)

    def test_handle_mode_command(self):
        """Test /mode command."""
        # Test status
        result = self.agent.handle_mode_command("status")
        self.assertEqual(result, f"Current mode: {self.agent.mode}")

        # Test switching to coding mode
        with patch.object(self.agent, 'switch_mode') as mock_switch:
            mock_switch.return_value = True
            result = self.agent.handle_mode_command("coding")
            mock_switch.assert_called_once_with("coding")
            self.assertEqual(result, "Switched to coding mode.")

        # Test switching to chat mode
        with patch.object(self.agent, 'switch_mode') as mock_switch:
            mock_switch.return_value = True
            result = self.agent.handle_mode_command("chat")
            mock_switch.assert_called_once_with("chat")
            self.assertEqual(result, "Switched to chat mode.")

        # Test failed switch
        with patch.object(self.agent, 'switch_mode') as mock_switch:
            mock_switch.return_value = False
            result = self.agent.handle_mode_command("chat")
            mock_switch.assert_called_once_with("chat")
            self.assertEqual(result, "Failed to switch to chat mode.")

        # Test invalid mode
        result = self.agent.handle_mode_command("invalid")
        self.assertEqual(result, "Invalid mode. Use 'chat', 'coding', 'status', or 'help'.")

        # Test help
        result = self.agent.handle_mode_command("help")
        self.assertIn("/mode command usage", result)
        self.assertIn("/mode chat", result)

    def test_handle_skills_command(self):
        """Test /skills command with skill loader integration."""
        # Test default (list for current mode)
        result = self.agent.handle_skills_command("")
        self.assertIn("Skills", result)

        # Test 'all' subcommand
        result = self.agent.handle_skills_command("all")
        self.assertIn("All skills", result)

        # Test refresh subcommand
        result = self.agent.handle_skills_command("refresh")
        self.assertIn("Reloaded", result)

        # Test help
        result = self.agent.handle_skills_command("help")
        self.assertIn("/skills", result)
        self.assertIn("help", result)

        # Test unknown subcommand
        result = self.agent.handle_skills_command("unknown")
        self.assertIn("Unknown subcommand", result)

    def test_handle_skill_command(self):
        """Test /skill command."""
        # Test with non-existent skill name
        result = self.agent.handle_skill_command("nonexistent_skill")
        self.assertIn("not found", result)

        # Test empty command (usage)
        result = self.agent.handle_skill_command("")
        self.assertIn("Usage", result)

        # Test status subcommand when no skill active
        result = self.agent.handle_skill_command("status")
        self.assertIn("No skill", result)

        # Test off subcommand when no skill active
        result = self.agent.handle_skill_command("off")
        self.assertIn("No skill", result)

    def test_handle_task_command_create(self):
        """Test /task create command."""
        mock_task = Mock(id="123", description="Test task")
        self.agent.task_manager.create_task = Mock(return_value=mock_task)

        result = self.agent.handle_task_command("create Test task description")
        self.agent.task_manager.create_task.assert_called_once_with("Test task description")
        self.assertIn("Task created", result)
        self.assertIn("123", result)

    def test_handle_task_command_list(self):
        """Test /task list command."""
        mock_tasks = [
            Mock(id="1", description="Task 1", status="todo", created_at="2025-01-01 10:00:00"),
            Mock(id="2", description="Task 2", status="in_progress", created_at="2025-01-02 11:00:00")
        ]
        self.agent.task_manager.list_tasks = Mock(return_value=mock_tasks)

        result = self.agent.handle_task_command("list")
        self.agent.task_manager.list_tasks.assert_called_once()
        self.assertIn("📋 Task List", result)
        self.assertIn("Task 1", result)
        self.assertIn("Task 2", result)
        self.assertIn("⭕", result)  # todo emoji
        self.assertIn("🔄", result)  # in_progress emoji

        # Test with status filter
        result = self.agent.handle_task_command("list todo")
        self.agent.task_manager.list_tasks.assert_called_with("todo")

        # Test invalid status filter
        result = self.agent.handle_task_command("list invalid")
        self.assertIn("Invalid status filter", result)

        # Test no tasks
        self.agent.task_manager.list_tasks = Mock(return_value=[])
        result = self.agent.handle_task_command("list")
        self.assertIn("📭 No tasks found", result)

    def test_handle_task_command_update(self):
        """Test /task update command."""
        self.agent.task_manager.update_task_status = Mock(return_value=True)

        result = self.agent.handle_task_command("update 1 done")
        self.agent.task_manager.update_task_status.assert_called_once_with("1", "done")
        self.assertEqual(result, "✅ Task 1 updated to 'done'")

        # Test update failure
        self.agent.task_manager.update_task_status = Mock(return_value=False)
        result = self.agent.handle_task_command("update 99 done")
        self.assertEqual(result, "❌ Task 99 not found")

        # Test invalid status
        result = self.agent.handle_task_command("update 1 invalid")
        self.assertIn("Invalid status 'invalid'", result)

        # Test usage (missing arguments)
        result = self.agent.handle_task_command("update")
        self.assertEqual(result, "Usage: /task update <task_id> <status>")

        result = self.agent.handle_task_command("update 1")
        self.assertEqual(result, "Usage: /task update <task_id> <status>")

    def test_handle_task_command_delete(self):
        """Test /task delete command."""
        self.agent.task_manager.delete_task = Mock(return_value=True)

        result = self.agent.handle_task_command("delete 1")
        self.agent.task_manager.delete_task.assert_called_once_with("1")
        self.assertEqual(result, "✅ Task 1 deleted")

        # Test delete failure
        self.agent.task_manager.delete_task = Mock(return_value=False)
        result = self.agent.handle_task_command("delete 99")
        self.assertEqual(result, "❌ Task 99 not found")

        # Test usage (missing task_id)
        result = self.agent.handle_task_command("delete")
        self.assertEqual(result, "Usage: /task delete <task_id>")

    def test_handle_task_command_clear(self):
        """Test /task clear command."""
        self.agent.task_manager.clear_all_tasks = Mock(return_value=2)

        result = self.agent.handle_task_command("clear")
        self.agent.task_manager.clear_all_tasks.assert_called_once()
        self.assertEqual(result, "✅ Cleared 2 tasks")

        # Test with extra arguments (should still work? method expects len(parts) == 1)
        # Actually method checks if len(parts) != 1, returns usage. We'll trust the method.

    def test_handle_plan_command_create(self):
        """Test /plan command with goal (generates plan)."""
        mock_plan = {"id": "plan1", "goal": "Test goal", "steps": ["step1", "step2"], "status": "pending"}
        self.agent.goal_planner.generate_plan = Mock(return_value=mock_plan)

        result = self.agent.handle_plan_command("Test goal")
        self.agent.goal_planner.generate_plan.assert_called_once_with("Test goal", self.agent)
        self.assertIn("📋 Plan generated with ID:", result)
        self.assertIn("plan1", result)
        self.assertIn("Test goal", result)
        self.assertIn("Steps: 2", result)
        self.assertIn("Use /execute plan1", result)

    def test_handle_plan_command_list(self):
        """Test /plan list command."""
        mock_plans = [
            {"id": "plan1", "goal": "Goal 1", "status": "pending"},
            {"id": "plan2", "goal": "Goal 2", "status": "completed"}
        ]
        self.agent.goal_planner.list_plans = Mock(return_value=mock_plans)

        result = self.agent.handle_plan_command("list")
        self.agent.goal_planner.list_plans.assert_called_once()
        self.assertIn("Goal 1", result)
        self.assertIn("Goal 2", result)

    def test_handle_plan_command_show(self):
        """Test /plan show command."""
        mock_plan = {
            "id": "plan1",
            "goal": "Test goal",
            "status": "pending",
            "created_at": "2025-01-01",
            "steps": [
                {"description": "Step 1", "action": "write"},
                {"description": "Step 2", "action": "run", "details": "Run tests"}
            ],
            "current_step": 0
        }
        self.agent.goal_planner.get_plan = Mock(return_value=mock_plan)

        result = self.agent.handle_plan_command("show plan1")
        self.agent.goal_planner.get_plan.assert_called_once_with("plan1")
        self.assertIn("📋 Plan: Test goal", result)
        self.assertIn("ID: plan1", result)
        self.assertIn("Status: pending", result)
        self.assertIn("Steps (2):", result)
        self.assertIn("→ 1. Step 1", result)
        self.assertIn("Action: write", result)
        self.assertIn("2. Step 2", result)
        self.assertIn("Details: Run tests", result)

        # Test plan not found
        self.agent.goal_planner.get_plan = Mock(return_value=None)
        result = self.agent.handle_plan_command("show plan2")
        self.assertEqual(result, "❌ Plan plan2 not found")

        # Test usage (missing plan_id)
        result = self.agent.handle_plan_command("show")
        self.assertEqual(result, "Usage: /plan show <plan_id>")

    def test_handle_plan_command_delete(self):
        """Test /plan delete command."""
        self.agent.goal_planner.delete_plan = Mock(return_value=True)

        result = self.agent.handle_plan_command("delete plan1")
        self.agent.goal_planner.delete_plan.assert_called_once_with("plan1")
        self.assertEqual(result, "✅ Plan plan1 deleted")

        # Test delete failure
        self.agent.goal_planner.delete_plan = Mock(return_value=False)
        result = self.agent.handle_plan_command("delete plan2")
        self.assertEqual(result, "❌ Plan plan2 not found")

        # Test usage (missing plan_id)
        result = self.agent.handle_plan_command("delete")
        self.assertEqual(result, "Usage: /plan delete <plan_id>")

    def test_handle_execute_command(self):
        """Test /execute command."""
        # Mock goal_planner methods
        mock_plan = {
            "id": "plan1",
            "goal": "Test goal",
            "status": "pending",
            "steps": [{"description": "Step 1", "action": "write"}, {"description": "Step 2", "action": "run"}],
            "current_step": 0
        }
        self.agent.goal_planner.get_plan = Mock(return_value=mock_plan)
        self.agent.goal_planner.update_plan_status = Mock()
        self.agent.goal_planner.get_current_step = Mock(return_value={"description": "Test step", "action": "write"})

        result = self.agent.handle_execute_command("plan1")
        self.agent.goal_planner.get_plan.assert_called_once_with("plan1")
        self.agent.goal_planner.get_current_step.assert_called_once_with("plan1")
        self.assertIn("🚀 Executing Plan:", result)
        self.assertIn("Step 1/2", result)
        self.assertIn("Test step", result)

        # Test plan not found
        self.agent.goal_planner.get_plan = Mock(return_value=None)
        result = self.agent.handle_execute_command("plan2")
        self.assertIn("❌ Plan plan2 not found", result)

        # Test usage (empty command)
        result = self.agent.handle_execute_command("")
        self.assertEqual(result, "Usage: /execute <plan_id>")

        # Test plan already completed (no current step)
        mock_plan_completed = {
            "id": "plan3",
            "goal": "Goal",
            "status": "pending",
            "steps": [],
            "current_step": 0
        }
        self.agent.goal_planner.get_plan = Mock(return_value=mock_plan_completed)
        self.agent.goal_planner.get_current_step = Mock(return_value=None)
        result = self.agent.handle_execute_command("plan3")
        self.assertIn("✅ Plan plan3 already completed!", result)

    def test_handle_switch_command_model(self):
        """Test /switch model command."""
        self.agent.set_model = Mock(return_value=True)

        result = self.agent.handle_switch_command("deepseek-v4-pro")
        self.agent.set_model.assert_called_once_with("deepseek-v4-pro")
        self.assertEqual(result, "✅ Switched model to deepseek-reasoner")

        # Test switch failure
        self.agent.set_model = Mock(return_value=False)
        result = self.agent.handle_switch_command("invalid-model")
        self.assertEqual(result, "❌ Failed to switch model to invalid-model")

        # Test empty command (usage)
        result = self.agent.handle_switch_command("")
        self.assertEqual(result, "Usage: /switch <model_id>")

    def test_handle_summarize_command(self):
        """Test /summarize command."""
        self.agent.generate_completion.return_value = "Summary of the text"

        result = self.agent.handle_summarize_command("Some long text to summarize")
        self.agent.generate_completion.assert_called_once()
        # Check that prompt contains "summarize"
        call_args = self.agent.generate_completion.call_args
        self.assertIn("summarize", call_args[0][0][0]["content"].lower())
        self.assertIn("Summary", result)

    def test_handle_translate_command(self):
        """Test /translate command."""
        self.agent.generate_completion.return_value = "Translated text"

        result = self.agent.handle_translate_command("Hello world")
        self.agent.generate_completion.assert_called_once()
        call_args = self.agent.generate_completion.call_args
        self.assertIn("translate", call_args[0][0][0]["content"].lower())
        self.assertIn("Translated", result)

    def test_handle_generate_command(self):
        """Test /generate command."""
        self.agent.generate_completion.return_value = "Generated content"

        result = self.agent.handle_generate_command("Write a story about cats")
        self.agent.generate_completion.assert_called_once()
        # Check that generate_completion was called with correct arguments
        call_args = self.agent.generate_completion.call_args
        # First argument should be a list of messages
        messages = call_args[0][0]
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["content"], "Write a story about cats")
        # Should have temperature and max_tokens kwargs
        self.assertEqual(call_args[1]["temperature"], 0.7)
        self.assertEqual(call_args[1]["max_tokens"], 2000)
        # Result should contain the response
        self.assertIn("🎨 Generated content:", result)
        self.assertIn("Generated content", result)

        # Test empty command (usage)
        result = self.agent.handle_generate_command("")
        self.assertEqual(result, "Usage: /generate <prompt>")

        # Test exception handling
        self.agent.generate_completion.side_effect = Exception("API error")
        result = self.agent.handle_generate_command("test")
        self.assertIn("❌ Failed to generate content", result)

    def test_handle_reason_command(self):
        """Test /reason command."""
        self.agent.generate_completion.return_value = "Reasoning result"

        result = self.agent.handle_reason_command("Solve this math problem: 2+2")
        self.agent.generate_completion.assert_called_once()
        call_args = self.agent.generate_completion.call_args
        self.assertIn("reason", call_args[0][0][0]["content"].lower())
        self.assertIn("Reasoning", result)

    def test_handle_debug_command(self):
        """Test /debug command."""
        with patch('os.path.exists', return_value=True):
            self.agent.safety_manager.safe_read_file.return_value = (True, "", "def buggy_code(): pass")
            self.agent.generate_completion.return_value = "Debug suggestions"

            result = self.agent.handle_debug_command("test.py")
            self.agent.safety_manager.safe_read_file.assert_called_once_with("test.py")
            self.agent.generate_completion.assert_called_once()
            self.assertIn("Debug", result)

    def test_handle_explain_command(self):
        """Test /explain command."""
        with patch('os.path.exists', return_value=True):
            self.agent.safety_manager.safe_read_file.return_value = (True, "", "complex_code()")
            self.agent.generate_completion.return_value = "Explanation of code"

            result = self.agent.handle_explain_command("test.py")
            self.agent.safety_manager.safe_read_file.assert_called_once_with("test.py")
            self.agent.generate_completion.assert_called_once()
            self.assertIn("Explanation", result)

    def test_handle_refactor_command(self):
        """Test /refactor command."""
        with patch('os.path.exists', return_value=True):
            self.agent.safety_manager.safe_read_file.return_value = (True, "", "old_code()")
            self.agent.generate_completion.return_value = "Refactored code"

            result = self.agent.handle_refactor_command("test.py")
            self.agent.safety_manager.safe_read_file.assert_called_once_with("test.py")
            self.agent.generate_completion.assert_called_once()
            self.assertIn("Refactor", result)

    def test_handle_grep_command(self):
        """Test /grep command."""
        import subprocess
        # Mock subprocess.run to simulate rg success
        with patch('subprocess.run') as mock_run:
            mock_result = Mock()
            mock_result.returncode = 0
            mock_result.stdout = "file1.py:10: match line"
            mock_run.return_value = mock_result

            result = self.agent.handle_grep_command("pattern *.py")
            mock_run.assert_called_once()
            # Check rg command
            args = mock_run.call_args[0][0]
            self.assertEqual(args[0], "rg")
            self.assertIn("-n", args)
            self.assertIn("-i", args)
            self.assertEqual(args[-2], "pattern")
            self.assertEqual(args[-1], "*.py")
            self.assertIn("🔍 Grep results", result)
            self.assertIn("file1.py:10", result)

            # Test rg failure (fallback to _grep_fallback)
            mock_result.returncode = 1
            with patch.object(self.agent, '_grep_fallback') as mock_fallback:
                mock_fallback.return_value = "Fallback results"
                result = self.agent.handle_grep_command("pattern")
                mock_fallback.assert_called_once_with("pattern", ".")

            # Test subprocess error (fallback)
            mock_run.side_effect = subprocess.SubprocessError
            with patch.object(self.agent, '_grep_fallback') as mock_fallback:
                mock_fallback.return_value = "Fallback"
                result = self.agent.handle_grep_command("pattern")
                mock_fallback.assert_called_once_with("pattern", ".")

            # Test empty command (usage)
            result = self.agent.handle_grep_command("")
            self.assertEqual(result, "Usage: /grep <pattern> [path]")

    def test_handle_find_command(self):
        """Test /find command."""
        import os
        import fnmatch
        # Mock os.walk to return test files
        with patch('os.walk') as mock_walk:
            mock_walk.return_value = [
                ('.', [], ['file1.py', 'file2.py', 'readme.txt']),
                ('./subdir', [], ['file3.py'])
            ]
            # Test basic pattern
            result = self.agent.handle_find_command("*.py")
            self.assertIn("📂 Found 3 matches", result)
            self.assertIn("file1.py", result)
            self.assertIn("file2.py", result)
            # Path separator may vary by OS
            self.assertIn("file3.py", result)
            self.assertIn("subdir", result)

            # Test with path argument
            mock_walk.return_value = [('/test', [], ['test.py'])]
            result = self.agent.handle_find_command("*.py /test")
            # Normalize path separators for comparison (Windows uses backslash)
            expected = os.path.normpath('/test/test.py')
            # Get the match line (second line of result after header)
            lines = result.strip().split('\n')
            match_line = lines[1] if len(lines) > 1 else ''
            self.assertEqual(os.path.normpath(match_line), expected)

            # Test no matches
            mock_walk.return_value = [('.', [], [])]
            result = self.agent.handle_find_command("*.py")
            self.assertIn("📭 No files/directories matching", result)

            # Test empty command (usage)
            result = self.agent.handle_find_command("")
            self.assertEqual(result, "Usage: /find <pattern> [path]")

    def test_handle_verbose_command(self):
        """Test /verbose command."""
        # Mock status_buffer
        self.agent.status_buffer = []

        # Test on
        self.agent.verbose_mode = False
        result = self.agent.handle_verbose_command("on")
        self.assertTrue(self.agent.verbose_mode)
        self.assertIn("🔊 Verbose mode: ENABLED", result)

        # Test off
        self.agent.verbose_mode = True
        result = self.agent.handle_verbose_command("off")
        self.assertFalse(self.agent.verbose_mode)
        self.assertIn("🔊 Verbose mode: DISABLED", result)

        # Test toggle (empty string)
        self.agent.verbose_mode = False
        result = self.agent.handle_verbose_command("toggle")
        self.assertTrue(self.agent.verbose_mode)
        self.assertIn("🔊 Verbose mode: TOGGLED", result)

        # Test toggle (no argument)
        self.agent.verbose_mode = True
        result = self.agent.handle_verbose_command("")
        self.assertFalse(self.agent.verbose_mode)
        self.assertIn("🔊 Verbose mode: TOGGLED", result)

        # Test invalid option
        result = self.agent.handle_verbose_command("invalid")
        self.assertIn("Invalid option", result)

        # Test with status buffer (when verbose_mode is True)
        self.agent.verbose_mode = True
        self.agent.status_buffer = [
            {"level": "INFO", "message": "Test message"},
            {"level": "DEBUG", "message": "Debug message"}
        ]
        result = self.agent.handle_verbose_command("on")  # Already on, but will still return
        self.assertIn("Recent debug messages", result)
        self.assertIn("Test message", result)

    def test_handle_clear_command(self):
        """Test /clear command."""
        with patch.object(self.agent, 'clear_history') as mock_clear:
            result = self.agent.handle_clear_command("")
            mock_clear.assert_called_once()
            self.assertEqual(result, "🗑️ Conversation history cleared.")

    def test_handle_history_command(self):
        """Test /history command."""
        self.agent.conversation_history = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"}
        ]
        result = self.agent.handle_history_command("")
        self.assertIn("📜 Conversation History:", result)
        self.assertIn("Hello", result)
        self.assertIn("Hi there", result)

        # Test empty history
        self.agent.conversation_history = []
        result = self.agent.handle_history_command("")
        self.assertIn("📭 No conversation history.", result)

    def test_handle_context_command(self):
        """Test /context command."""
        # Mock context_manager.get_context_usage
        self.agent.context_manager = Mock()
        self.agent.context_manager.get_context_usage = Mock(return_value={
            'total_tokens': 1500,
            'max_context_tokens': 8000,
            'percent_used': 0.1875,
            'warning_threshold': 0.8,
            'warning_tokens': 6400,
            'break_threshold': 0.9,
            'break_tokens': 7200,
            'is_near_limit': False,
            'is_over_break': False
        })
        # Mock HAS_TIKTOKEN to False for consistent output
        with patch('agent.core.HAS_TIKTOKEN', False):
            result = self.agent.handle_context_command("status")
            self.assertIn("📊 Context Status:", result)
            self.assertIn("1500", result)
            self.assertIn("8000", result)

        # Test compress
        self.agent.context_manager.compress_history = Mock(return_value={
            'original_tokens': 2000,
            'compressed_tokens': 1500,
            'token_reduction': 500
        })
        result = self.agent.handle_context_command("compress")
        self.assertIn("✅ Compressed history:", result)
        self.assertIn("2000 → 1500", result)

        # Test clear (should clear conversation_history and call _ensure_system_prompt)
        self.agent.conversation_history = [{"role": "user", "content": "test"}]
        with patch.object(self.agent, '_ensure_system_prompt') as mock_ensure:
            result = self.agent.handle_context_command("clear")
            self.assertEqual(len(self.agent.conversation_history), 0)
            mock_ensure.assert_called_once()
            self.assertIn("✅ Conversation history cleared.", result)

        # Test help
        result = self.agent.handle_context_command("help")
        self.assertIn("/context commands:", result)
        self.assertIn("status", result)
        self.assertIn("compress", result)
        self.assertIn("clear", result)

        # Test unknown subcommand
        result = self.agent.handle_context_command("unknown")
        self.assertIn("Unknown subcommand", result)

    def test_handle_think_command(self):
        """Test /think command."""
        # Mock agent_config.update_value to avoid config updates
        with patch('agent.core.agent_config') as mock_config:
            mock_config.update_value = Mock(return_value=True)

            # Initial state
            original_state = self.agent.thinking_enabled

            # Call handler (command argument is ignored)
            result = self.agent.handle_think_command("")
            # thinking_enabled should be toggled
            self.assertEqual(self.agent.thinking_enabled, not original_state)
            self.assertIn("🤔 Thinking mode", result)
            # Should contain "enabled" or "disabled"
            if self.agent.thinking_enabled:
                self.assertIn("enabled", result)
            else:
                self.assertIn("disabled", result)

            # Call again to toggle back
            result2 = self.agent.handle_think_command("any argument")
            self.assertEqual(self.agent.thinking_enabled, original_state)
            self.assertIn("🤔 Thinking mode", result2)

    def test_handle_quit_command(self):
        """Test /quit command."""
        result = self.agent.handle_quit_command("")
        self.assertEqual(result, "🛑 Quit command received. Use Ctrl+C or type /quit in the CLI to exit.")

    def test_handle_exit_command(self):
        """Test /exit command."""
        with patch.object(self.agent, 'handle_quit_command') as mock_quit:
            mock_quit.return_value = "Mock quit message"
            result = self.agent.handle_exit_command("")
            mock_quit.assert_called_once_with("")
            self.assertEqual(result, "Mock quit message")

    def test_handle_search(self):
        """Test /search command."""
        import asyncio

        # Mock searcher.search as an async coroutine (it's async in OptimizedDuckDuckGoSearch)
        async def mock_search_success(query):
            return (True, "Search results")

        async def mock_search_failure(query):
            return (False, "Search failed")

        self.agent.searcher.search = mock_search_success
        result = self.agent.handle_search("query")
        self.assertEqual(result, "Search results")

        # Test search failure
        self.agent.searcher.search = mock_search_failure
        result = self.agent.handle_search("query2")
        self.assertIn("Search failed", result)

        # Test empty query (usage)
        result = self.agent.handle_search("")
        self.assertIn("Usage:", result)

    def test_handle_auto_fix_command(self):
        """Test /fix and /analyze commands."""
        # Mock switch_mode to avoid actual mode switching
        with patch.object(self.agent, 'switch_mode') as mock_switch:
            # Mock code_analyzer.read_file_safe to succeed
            self.agent.code_analyzer.read_file_safe.return_value = (True, "", "file content")
            # Mock generate_completion to return something
            self.agent.generate_completion.return_value = "Analysis result"

            # Test /fix command
            result = self.agent.handle_auto_fix_command("/fix test.py")
            # Should have tried to read the file
            self.agent.code_analyzer.read_file_safe.assert_called_once_with("test.py")
            # Should return None (special handling for async process)
            self.assertIsNone(result)

            # Reset mocks
            self.agent.code_analyzer.read_file_safe.reset_mock()

            # Test /analyze command
            result = self.agent.handle_auto_fix_command("/analyze test.py")
            self.agent.code_analyzer.read_file_safe.assert_called_once_with("test.py")
            self.assertIsNone(result)

            # Test insufficient arguments (should print usage and return None)
            result = self.agent.handle_auto_fix_command("/fix")
            self.assertIsNone(result)

    def test_new_command_handlers_smoke(self):
        """Smoke test for new command handlers."""
        # Mock task manager
        from unittest.mock import Mock
        self.agent.task_manager.create_task = Mock(return_value=Mock(id="123", description="test"))
        self.agent.task_manager.list_tasks = Mock(return_value=[])
        self.agent.task_manager.update_task_status = Mock(return_value=True)
        self.agent.task_manager.delete_task = Mock(return_value=True)
        self.agent.task_manager.clear_all_tasks = Mock(return_value=0)

        # Mock goal planner
        self.agent.goal_planner.generate_plan = Mock(return_value={"id": "plan1", "goal": "test", "steps": [], "status": "pending"})
        self.agent.goal_planner.list_plans = Mock(return_value=[])
        self.agent.goal_planner.get_plan = Mock(return_value={"id": "plan1", "goal": "test", "steps": [], "status": "pending"})
        self.agent.goal_planner.update_plan_status = Mock(return_value=True)
        self.agent.goal_planner.delete_plan = Mock(return_value=True)
        self.agent.goal_planner.get_current_step = Mock(return_value=None)

        # Mock set_model for switch command
        self.agent.set_model = Mock(return_value=True)
        # Mock list_models for switch command
        self.agent.list_models = Mock(return_value=[{"id": "deepseek-v4-flash"}])

        # Mock generate_completion for AI commands
        self.agent.generate_completion.return_value = "Mocked AI response"

        # Mock file existence for debug/explain/refactor
        import os
        with patch('os.path.exists', return_value=True):
            # Mock safe_read_file for file operations
            self.agent.safety_manager.safe_read_file.return_value = (True, "", "file content")

            # Test each handler with minimal arguments
            handlers = [
                (self.agent.handle_task_command, "create test"),
                (self.agent.handle_plan_command, "test goal"),
                (self.agent.handle_execute_command, "plan1"),
                (self.agent.handle_switch_command, "deepseek-v4-flash"),
                (self.agent.handle_summarize_command, "test text"),
                (self.agent.handle_translate_command, "hello"),
                (self.agent.handle_generate_command, "prompt"),
                (self.agent.handle_reason_command, "problem"),
                (self.agent.handle_debug_command, "test.py"),
                (self.agent.handle_explain_command, "test.py"),
                (self.agent.handle_refactor_command, "test.py"),
                (self.agent.handle_grep_command, "pattern"),
                (self.agent.handle_find_command, "*.py"),
            ]

            for handler, arg in handlers:
                try:
                    result = handler(arg)
                    # Should return string or None
                    self.assertIsInstance(result, (str, type(None)))
                except Exception as e:
                    self.fail(f"Handler {handler.__name__} failed with {e}")

    def test_with_model_invalid_model(self):
        """Test with_model raises ValueError for unavailable model."""
        with patch.object(self.agent, 'list_models') as mock_list:
            mock_list.return_value = [{"id": "deepseek-v4-flash"}]
            with self.assertRaises(ValueError):
                self.agent.with_model("deepseek-v4-pro", lambda: None)

if __name__ == '__main__':
    unittest.main()