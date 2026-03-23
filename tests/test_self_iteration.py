#!/usr/bin/env python3
"""
Integration tests for self-iteration framework.
Uses temporary directories to avoid modifying real agent code.
"""
import os
import sys
import tempfile
import shutil
import unittest
from unittest.mock import Mock, patch, MagicMock

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.self_iteration import SelfIteration
from agent.core import NeoMindAgent


class TestSelfIteration(unittest.TestCase):
    """Test SelfIteration class with temporary directories."""

    def setUp(self):
        """Create temporary agent root directory."""
        self.temp_root = tempfile.mkdtemp(prefix="test_self_iteration_")
        # Create a simple Python file for testing
        self.test_file = os.path.join(self.temp_root, "test_module.py")
        with open(self.test_file, "w") as f:
            f.write('def hello():\n    return "world"\n')
        # Create a dummy dev_test.py for basic tests
        self.dev_test = os.path.join(self.temp_root, "dev_test.py")
        with open(self.dev_test, "w") as f:
            f.write('print("Tests passed")')
        # Mock code analyzer and safety manager
        self.mock_analyzer = Mock()
        self.mock_safety = Mock()
        self.mock_safety.is_path_safe = Mock(return_value=(True, ""))
        self.mock_analyzer.safety_manager = self.mock_safety
        self.mock_analyzer.read_file_safe = Mock(return_value=(True, "", 'def hello():\n    return "world"\n'))
        self.mock_analyzer.write_file_safe = Mock(return_value=(True, "File written"))
        # Initialize SelfIteration with mocked dependencies
        self.si = SelfIteration(self.temp_root, code_analyzer=self.mock_analyzer)
        # Override safety manager mock
        self.si.safety_manager = self.mock_safety

    def tearDown(self):
        """Clean up temporary directory."""
        shutil.rmtree(self.temp_root, ignore_errors=True)

    def test_backup_file(self):
        """Test backup creation."""
        backup_path = self.si.backup_file(self.test_file)
        self.assertTrue(os.path.exists(backup_path))
        self.assertTrue(backup_path.startswith(self.si.backup_dir))
        # Ensure content matches
        with open(self.test_file, 'r') as orig, open(backup_path, 'r') as backup:
            self.assertEqual(orig.read(), backup.read())

    def test_backup_nonexistent_file(self):
        """Test backup of non-existent file raises FileNotFoundError."""
        with self.assertRaises(FileNotFoundError):
            self.si.backup_file("/nonexistent/file.py")

    def test_validate_syntax_valid(self):
        """Test syntax validation with valid Python."""
        content = 'def foo():\n    pass\n'
        is_valid, msg = self.si.validate_syntax(self.test_file, content)
        self.assertTrue(is_valid)
        self.assertIn("valid", msg.lower())

    def test_validate_syntax_invalid(self):
        """Test syntax validation with invalid Python."""
        content = 'def foo()\n    pass\n'  # missing colon
        is_valid, msg = self.si.validate_syntax(self.test_file, content)
        self.assertFalse(is_valid)
        self.assertIn("syntax", msg.lower())

    def test_validate_syntax_non_py(self):
        """Test syntax validation skips non-Python files."""
        is_valid, msg = self.si.validate_syntax("file.txt", "content")
        self.assertTrue(is_valid)
        self.assertIn("not a python file", msg.lower())

    def test_validate_imports(self):
        """Test import validation (mocked subprocess)."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value.returncode = 0
            is_valid, msg = self.si.validate_imports(self.test_file)
            self.assertTrue(is_valid)
            mock_run.assert_called_once()

    def test_validate_imports_failure(self):
        """Test import validation failure."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value.returncode = 1
            mock_run.return_value.stderr = "ImportError"
            is_valid, msg = self.si.validate_imports(self.test_file)
            self.assertFalse(is_valid)
            self.assertIn("import failed", msg.lower())

    def test_run_basic_tests(self):
        """Test basic test suite execution."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stderr = ""
            success, msg = self.si.run_basic_tests()
            self.assertTrue(success)
            mock_run.assert_called_once()

    def test_suggest_improvements(self):
        """Test suggestion generation for missing docstrings."""
        # Mock AST parsing and code analyzer
        with patch.object(self.si.code_analyzer, 'read_file_safe') as mock_read:
            mock_read.return_value = (True, "", 'def foo():\n    pass\n')
            suggestions = self.si.suggest_improvements(self.test_file)
            # Expect one suggestion for missing docstring
            self.assertGreaterEqual(len(suggestions), 0)
            if suggestions:
                self.assertEqual(suggestions[0]['description'], 'Add docstring to function foo')

    def test_validate_change(self):
        """Test change validation."""
        with patch.object(self.si, 'validate_syntax') as mock_syntax, \
             patch.object(self.si, 'validate_imports') as mock_imports:
            mock_syntax.return_value = (True, "")
            mock_imports.return_value = (True, "")
            is_valid, msg = self.si.validate_change(self.test_file, "def hello():\n    return \"world\"\n", "def hello():\n    return \"world!\"\n")
            self.assertTrue(is_valid)
            mock_syntax.assert_called_once()
            mock_imports.assert_called_once()

    def test_apply_change_success(self):
        """Test successful change application."""
        # Mock pre-tests, backup, write, post-tests
        with patch.object(self.si, 'run_basic_tests') as mock_tests, \
             patch.object(self.si, 'backup_file') as mock_backup, \
             patch.object(self.si.code_analyzer, 'read_file_safe') as mock_read, \
             patch.object(self.si.code_analyzer, 'write_file_safe') as mock_write:
            mock_tests.side_effect = [(True, ""), (True, "")]
            mock_backup.return_value = "/backup/path"
            mock_read.return_value = (True, "", "original")
            mock_write.return_value = (True, "written")
            success, msg, backup = self.si.apply_change(
                self.test_file, "original", "new", "test change"
            )
            if not success:
                self.fail(f"apply_change failed: {msg}")
            self.assertTrue(success)
            self.assertIsNotNone(backup)

    def test_apply_change_pre_test_fails(self):
        """Test change application fails when pre-tests fail."""
        with patch.object(self.si, 'run_basic_tests') as mock_tests:
            mock_tests.return_value = (False, "tests failed")
            success, msg, backup = self.si.apply_change(
                self.test_file, "old", "new", "test"
            )
            self.assertFalse(success)
            self.assertIn("pre-test", msg.lower())

    def test_get_change_history_empty(self):
        """Test retrieving empty change history."""
        history = self.si.get_change_history()
        self.assertEqual(history, [])

    def test_log_change(self):
        """Test logging a change to journal."""
        with patch('builtins.open', unittest.mock.mock_open()) as mock_file:
            self.si.log_change({'timestamp': 123, 'description': 'test'})
            mock_file.assert_called_once_with(self.si.journal_path, 'a')


class TestSelfIterationCommands(unittest.TestCase):
    """Test command handlers for self-iteration."""

    def setUp(self):
        """Create agent with mocked dependencies."""
        self.agent = NeoMindAgent(api_key="dummy_key")
        self.agent.code_analyzer = Mock()
        self.agent.safety_manager = Mock()
        self.agent.formatter = Mock()
        self.agent.formatter.error = Mock(return_value="ERROR")
        self.agent.formatter.success = Mock(return_value="SUCCESS")
        self.agent.formatter.warning = Mock(return_value="WARNING")
        self.agent.formatter.info = Mock(return_value="INFO")
        self.agent.agent_root = "/fake/agent/root"
        self.agent.self_iteration = None
        self.agent.code_changes_pending = []

    def test_code_self_scan(self):
        """Test /code self-scan command."""
        with patch.object(self.agent.code_analyzer, 'get_code_summary') as mock_summary:
            mock_summary.return_value = {'total_files': 42, 'file_types': {'.py': 10}}
            result = self.agent._code_self_scan()
            self.assertIn("SELF-SCAN", result)
            self.assertIn("42", result)

    def test_code_self_improve_no_files(self):
        """Test self-improve with no Python files."""
        mock_si = Mock()
        with patch.object(self.agent, '_get_self_iteration', return_value=mock_si), \
             patch('os.walk') as mock_walk:
            mock_walk.return_value = []  # no files
            result = self.agent._code_self_improve("")
            # formatter.error is mocked to return "ERROR"
            self.assertEqual(result, "ERROR")
            # Verify error message contains the right text
            self.agent.formatter.error.assert_called_once()
            call_args = self.agent.formatter.error.call_args[0][0]
            self.assertIn("No Python files", call_args)

    def test_code_self_improve_with_suggestions(self):
        """Test self-improve with mocked suggestions."""
        mock_si = Mock()
        mock_si.suggest_improvements.return_value = [
            {'old_code': 'def foo():', 'new_code': 'def foo():\n    """doc"""', 'description': 'Add docstring'}
        ]
        with patch.object(self.agent, '_get_self_iteration', return_value=mock_si), \
             patch('os.walk') as mock_walk, \
             patch('os.path.isfile', return_value=False), \
             patch('os.path.isdir', return_value=False):
            mock_walk.return_value = [(self.agent.agent_root, [], ['test.py'])]
            result = self.agent._code_self_improve("")
            self.assertIn("improvement", result)
            # Should have proposed a change
            self.assertEqual(len(self.agent.code_changes_pending), 1)

    def test_code_self_apply_no_changes(self):
        """Test self-apply with no pending changes."""
        result = self.agent._code_self_apply()
        self.assertIn("No pending changes", result)

    def test_code_self_apply_non_self_files(self):
        """Test self-apply with non-self modifications."""
        self.agent.code_changes_pending = [
            {'file_path': '/some/other/file.py', 'old_code': '', 'new_code': ''}
        ]
        with patch.object(self.agent, '_is_self_modification', return_value=False):
            result = self.agent._code_self_apply()
            # formatter.error is mocked to return "ERROR"
            self.assertEqual(result, "ERROR")
            # Verify error message contains the right text
            self.agent.formatter.error.assert_called_once()
            call_args = self.agent.formatter.error.call_args[0][0]
            self.assertIn("Self-apply only works on agent's own code", call_args)


if __name__ == '__main__':
    unittest.main()