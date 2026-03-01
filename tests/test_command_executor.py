#!/usr/bin/env python3
"""
Comprehensive unit tests for CommandExecutor.
Tests command safety checking, execution with sandboxing, timeout handling,
git command safety, and result formatting.
"""
import os
import sys
import tempfile
import shutil
import time
import unittest
import subprocess
from unittest.mock import Mock, patch, MagicMock, call

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.command_executor import CommandExecutor, execute_safe, execute_git_safe


class TestCommandExecutorInitialization(unittest.TestCase):
    """Test CommandExecutor initialization and basic properties."""

    def test_initialization_defaults(self):
        """Test initialization with default parameters."""
        executor = CommandExecutor()

        self.assertFalse(executor.allowlist_mode)
        self.assertEqual(executor.default_timeout, 30)
        self.assertEqual(executor.max_output_size, 10 * 1024 * 1024)  # 10MB
        self.assertEqual(executor.min_interval, 0.0)
        self.assertEqual(executor.last_execution_time, 0)
        self.assertIsNone(executor.sandbox_dir)

    def test_initialization_custom_parameters(self):
        """Test initialization with custom parameters."""
        executor = CommandExecutor(
            allowlist_mode=True,
            timeout=60,
            max_output_size=5 * 1024 * 1024,  # 5MB
            min_interval=1.0
        )

        self.assertTrue(executor.allowlist_mode)
        self.assertEqual(executor.default_timeout, 60)
        self.assertEqual(executor.max_output_size, 5 * 1024 * 1024)
        self.assertEqual(executor.min_interval, 1.0)
        self.assertEqual(executor.last_execution_time, 0)

    def test_setup_sandbox(self):
        """Test sandbox directory creation."""
        executor = CommandExecutor()

        # First call should create sandbox directory
        sandbox_path = executor._setup_sandbox()
        self.assertIsNotNone(sandbox_path)
        self.assertTrue(os.path.exists(sandbox_path))
        self.assertEqual(executor.sandbox_dir, sandbox_path)

        # Second call should return same directory
        same_path = executor._setup_sandbox()
        self.assertEqual(sandbox_path, same_path)

    def test_cleanup_sandbox(self):
        """Test sandbox directory cleanup."""
        executor = CommandExecutor()
        sandbox_path = executor._setup_sandbox()

        # Directory should exist
        self.assertTrue(os.path.exists(sandbox_path))

        # Cleanup should remove directory
        executor._cleanup_sandbox()
        self.assertFalse(os.path.exists(sandbox_path))
        self.assertIsNone(executor.sandbox_dir)

    def test_cleanup_sandbox_nonexistent(self):
        """Test cleanup when sandbox doesn't exist."""
        executor = CommandExecutor()
        # No sandbox created yet
        executor._cleanup_sandbox()  # Should not raise exception
        self.assertIsNone(executor.sandbox_dir)


class TestCommandSafety(unittest.TestCase):
    """Test command safety checking."""

    def setUp(self):
        """Set up test environment."""
        self.executor = CommandExecutor()

    def test_safe_commands(self):
        """Test safe commands pass validation."""
        safe_commands = [
            "ls -la",
            "pwd",
            "cat README.md",
            "grep pattern file.txt",
            "python --version",
            "git status",
        ]

        for cmd in safe_commands:
            is_safe, reason = self.executor.is_command_safe(cmd)
            self.assertTrue(is_safe, f"Command '{cmd}' should be safe: {reason}")
            self.assertEqual(reason, "Command is safe")

    def test_dangerous_patterns(self):
        """Test dangerous command patterns are blocked."""
        dangerous_cases = [
            ("rm -rf /", "Contains dangerous pattern: 'rm -rf'"),
            ("rm -fr /home", "Contains dangerous pattern: 'rm -fr'"),
            ("format C:", "Contains dangerous pattern: 'format'"),
            ("dd if=/dev/zero of=/dev/sda", "Contains dangerous pattern: 'dd if='"),
            ("sudo apt update", "Contains dangerous pattern: 'sudo'"),
            ("chmod 777 /etc/passwd", "Contains dangerous pattern: 'chmod 777'"),
            ("wget http://evil.com", "Contains dangerous pattern: 'wget'"),
            ("curl http://evil.com", "Contains dangerous pattern: 'curl'"),
            ("bash -c 'rm -rf /'", "Contains dangerous pattern: 'rm -rf'"),
            ("python -c 'import os; os.system(\"rm -rf /\")'", "Contains dangerous pattern: 'rm -rf'"),
        ]

        for cmd, expected_reason in dangerous_cases:
            is_safe, reason = self.executor.is_command_safe(cmd)
            self.assertFalse(is_safe, f"Command '{cmd}' should be blocked")
            self.assertEqual(reason, expected_reason)

    def test_dangerous_git_patterns(self):
        """Test dangerous git operations are blocked."""
        dangerous_git_cases = [
            ("git reset --hard HEAD", "Contains dangerous pattern: 'reset --hard'"),
            ("git clean -fd", "Contains dangerous pattern: 'clean -fd'"),
            ("git push --force", "Contains dangerous pattern: 'push --force'"),
            ("git branch -D master", "Contains dangerous pattern: 'branch -D'"),
            ("git checkout .", "Contains dangerous pattern: 'checkout .'"),
            ("git stash drop", "Contains dangerous pattern: 'stash drop'"),
        ]

        for cmd, expected_reason in dangerous_git_cases:
            is_safe, reason = self.executor.is_command_safe(cmd, is_git=True)
            self.assertFalse(is_safe, f"Git command '{cmd}' should be blocked")
            self.assertEqual(reason, expected_reason)

    def test_directory_traversal(self):
        """Test directory traversal with '..' is blocked."""
        is_safe, reason = self.executor.is_command_safe("cd ..")
        self.assertFalse(is_safe)
        self.assertIn("Directory traversal", reason)

        is_safe, reason = self.executor.is_command_safe("cd ../..")
        self.assertFalse(is_safe)
        self.assertIn("Directory traversal", reason)

    def test_allowlist_mode(self):
        """Test allowlist mode restricts commands."""
        executor = CommandExecutor(allowlist_mode=True)

        # Allowed commands should pass
        allowed_cmds = ["ls -la", "pwd", "git status", "python --version"]
        for cmd in allowed_cmds:
            is_safe, reason = executor.is_command_safe(cmd)
            self.assertTrue(is_safe, f"Allowed command '{cmd}' should pass: {reason}")

        # Non-allowed commands should fail
        non_allowed = ["touch file.txt", "wc -l", "sort data.txt", "diff a b"]
        for cmd in non_allowed:
            is_safe, reason = executor.is_command_safe(cmd)
            self.assertFalse(is_safe, f"Non-allowed command '{cmd}' should fail")
            self.assertIn("not in allowlist", reason)

    def test_empty_command(self):
        """Test empty command handling."""
        # Empty string
        is_safe, reason = self.executor.is_command_safe("")
        self.assertFalse(is_safe)
        self.assertIn("Empty", reason)

        # Whitespace only
        is_safe, reason = self.executor.is_command_safe("   ")
        self.assertFalse(is_safe)
        self.assertIn("Empty", reason)

    def test_invalid_syntax(self):
        """Test invalid command syntax."""
        # Unclosed quote
        is_safe, reason = self.executor.is_command_safe("echo 'hello")
        self.assertFalse(is_safe)
        self.assertIn("Invalid command syntax", reason)


class TestCommandExecution(unittest.TestCase):
    """Test command execution with mocking."""

    def setUp(self):
        """Set up test environment."""
        self.executor = CommandExecutor()
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up after tests."""
        shutil.rmtree(self.test_dir)

    def test_execute_success(self):
        """Test successful command execution."""
        with patch('subprocess.run') as mock_run, \
             patch('time.time') as mock_time:
            # Mock time to simulate elapsed execution time
            mock_time.side_effect = [1000.0, 1000.1]  # start, end = 0.1s elapsed

            # Configure mock
            mock_process = Mock()
            mock_process.returncode = 0
            mock_process.stdout = "Hello, World!"
            mock_process.stderr = ""
            mock_run.return_value = mock_process

            result = self.executor.execute("echo Hello", cwd=self.test_dir)

            # Verify result
            self.assertTrue(result['success'])
            self.assertEqual(result['returncode'], 0)
            self.assertEqual(result['stdout'], "Hello, World!")
            self.assertEqual(result['stderr'], "")
            self.assertGreater(result['execution_time'], 0)
            self.assertEqual(result['error_message'], "")

            # Verify subprocess call
            mock_run.assert_called_once()
            args, kwargs = mock_run.call_args
            self.assertEqual(args[0], ['echo', 'Hello'])
            self.assertEqual(kwargs['cwd'], self.test_dir)
            self.assertTrue(kwargs['capture_output'])
            self.assertTrue(kwargs['text'])
            self.assertEqual(kwargs['timeout'], 30)  # default timeout

    def test_execute_with_custom_timeout(self):
        """Test execution with custom timeout."""
        with patch('subprocess.run') as mock_run:
            mock_process = Mock()
            mock_process.returncode = 0
            mock_process.stdout = "Done"
            mock_process.stderr = ""
            mock_run.return_value = mock_process

            result = self.executor.execute("sleep 1", timeout=10)

            # Verify timeout parameter
            mock_run.assert_called_once()
            _, kwargs = mock_run.call_args
            self.assertEqual(kwargs['timeout'], 10)

    def test_execute_with_environment(self):
        """Test execution with custom environment variables."""
        with patch('subprocess.run') as mock_run:
            mock_process = Mock()
            mock_process.returncode = 0
            mock_process.stdout = ""
            mock_process.stderr = ""
            mock_run.return_value = mock_process

            custom_env = {'CUSTOM_VAR': 'value', 'PATH': '/usr/bin'}
            result = self.executor.execute("echo test", env=custom_env)

            # Verify environment filtering
            mock_run.assert_called_once()
            _, kwargs = mock_run.call_args
            env = kwargs['env']

            # Should include safe variables
            self.assertIn('PATH', env)
            self.assertEqual(env['PATH'], '/usr/bin')
            # Should not include custom unsafe variables
            self.assertNotIn('CUSTOM_VAR', env)
            # Should include other safe defaults
            self.assertIn('HOME', env)

    def test_execute_timeout(self):
        """Test command timeout handling."""
        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="sleep 100", timeout=5)

            result = self.executor.execute("sleep 100", timeout=5)

            self.assertFalse(result['success'])
            self.assertEqual(result['returncode'], -1)
            self.assertIn("timed out", result['error_message'])
            self.assertEqual(result['execution_time'], 5)  # timeout value

    def test_execute_command_not_found(self):
        """Test execution when command not found."""
        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = FileNotFoundError("No such file or directory")

            result = self.executor.execute("nonexistent_command")

            self.assertFalse(result['success'])
            self.assertEqual(result['returncode'], -1)
            self.assertIn("Command not found", result['error_message'])

    def test_execute_general_exception(self):
        """Test execution with general exception."""
        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = Exception("Unexpected error")

            result = self.executor.execute("some command")

            self.assertFalse(result['success'])
            self.assertEqual(result['returncode'], -1)
            self.assertIn("Execution error", result['error_message'])

    def test_execute_unsafe_command(self):
        """Test execution blocked for unsafe command."""
        result = self.executor.execute("rm -rf /")

        self.assertFalse(result['success'])
        self.assertEqual(result['returncode'], -1)
        self.assertIn("Command blocked", result['error_message'])
        self.assertEqual(result['execution_time'], 0)

    def test_execute_rate_limiting(self):
        """Test rate limiting between commands."""
        executor = CommandExecutor(min_interval=1.0)  # 1 second between commands

        with patch('subprocess.run') as mock_run:
            mock_process = Mock()
            mock_process.returncode = 0
            mock_process.stdout = "First"
            mock_process.stderr = ""
            mock_run.return_value = mock_process

            # First command should succeed
            result1 = executor.execute("echo first")
            self.assertTrue(result1['success'])

            # Immediately try second command - should be blocked
            result2 = executor.execute("echo second")
            self.assertFalse(result2['success'])
            self.assertIn("Rate limit", result2['error_message'])

            # Wait a bit (mock time)
            with patch('time.time', return_value=time.time() + 1.5):
                # Now should succeed
                result3 = executor.execute("echo third")
                self.assertTrue(result3['success'])

    def test_execute_output_truncation(self):
        """Test output size limits and truncation."""
        executor = CommandExecutor(max_output_size=100)  # 100 byte limit

        with patch('subprocess.run') as mock_run:
            mock_process = Mock()
            mock_process.returncode = 0
            # Create output exceeding limit
            mock_process.stdout = "X" * 80  # 80 bytes
            mock_process.stderr = "Y" * 80  # 80 bytes, total 160 > 100
            mock_run.return_value = mock_process

            result = executor.execute("large_output")

            # Output should be truncated
            self.assertTrue(result['success'])
            self.assertIn("[output truncated]", result['stdout'])
            self.assertIn("[output truncated]", result['stderr'])
            self.assertLess(len(result['stdout']), 80)
            self.assertLess(len(result['stderr']), 80)

    def test_execute_empty_command(self):
        """Test execution of empty command."""
        result = self.executor.execute("")

        self.assertFalse(result['success'])
        self.assertIn("Empty command", result['error_message'])

    def test_execute_invalid_syntax(self):
        """Test execution with invalid command syntax."""
        result = self.executor.execute("echo 'unclosed quote")

        self.assertFalse(result['success'])
        self.assertIn("Invalid command syntax", result['error_message'])

    def test_execute_nonexistent_working_directory(self):
        """Test execution with non-existent working directory."""
        result = self.executor.execute("pwd", cwd="/nonexistent/directory")

        self.assertFalse(result['success'])
        self.assertIn("Working directory does not exist", result['error_message'])


class TestGitCommandExecution(unittest.TestCase):
    """Test git-specific command execution."""

    def setUp(self):
        """Set up test environment."""
        self.executor = CommandExecutor()
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up after tests."""
        shutil.rmtree(self.test_dir)

    def test_execute_git_success(self):
        """Test successful git command execution."""
        with patch.object(self.executor, 'execute') as mock_execute:
            mock_execute.return_value = {
                'success': True,
                'returncode': 0,
                'stdout': 'On branch main',
                'stderr': '',
                'execution_time': 0.1,
                'error_message': ''
            }

            result = self.executor.execute_git("status", cwd=self.test_dir)

            self.assertTrue(result['success'])
            # Should call git --version check first, then git status
            # Our mock execute returns success for both calls
            self.assertEqual(mock_execute.call_count, 2)
            first_call_args = mock_execute.call_args_list[0][0]
            self.assertEqual(first_call_args[0], "git --version")

    def test_execute_git_not_installed(self):
        """Test git command when git is not installed."""
        with patch.object(self.executor, 'execute') as mock_execute:
            mock_execute.return_value = {
                'success': False,
                'returncode': -1,
                'stdout': '',
                'stderr': '',
                'execution_time': 0,
                'error_message': 'git not found'
            }

            result = self.executor.execute_git("status")

            self.assertFalse(result['success'])
            self.assertIn('git not found', result['error_message'])
            mock_execute.assert_called_once_with("git --version", cwd=None, timeout=5)

    def test_execute_git_dangerous_operation(self):
        """Test git command with dangerous operation."""
        result = self.executor.execute_git("reset --hard HEAD", cwd=self.test_dir)

        self.assertFalse(result['success'])
        self.assertIn("Git command blocked", result['error_message'])

    def test_execute_git_with_timeout(self):
        """Test git command with custom timeout."""
        with patch.object(self.executor, 'execute') as mock_execute:
            mock_execute.return_value = {
                'success': True,
                'returncode': 0,
                'stdout': '',
                'stderr': '',
                'execution_time': 0.1,
                'error_message': ''
            }

            result = self.executor.execute_git("log --oneline -10", timeout=15)

            # Check that timeout is passed to execute
            self.assertEqual(mock_execute.call_count, 2)
            second_call_args = mock_execute.call_args_list[1]
            # second call is git log command
            self.assertEqual(second_call_args[1]['timeout'], 15)


class TestResultFormatting(unittest.TestCase):
    """Test result formatting for display."""

    def setUp(self):
        """Set up test environment."""
        self.executor = CommandExecutor()

    def test_format_success_result(self):
        """Test formatting successful execution result."""
        result = {
            'success': True,
            'returncode': 0,
            'stdout': 'Hello\nWorld',
            'stderr': '',
            'execution_time': 0.123,
            'error_message': ''
        }

        formatted = self.executor.format_result(result, "echo Hello")

        self.assertIn("🚀 Command: echo Hello", formatted)
        self.assertIn("📁 Working directory:", formatted)
        self.assertIn("⏱️  Execution time: 0.12s", formatted)
        self.assertIn("📤 Exit code: 0", formatted)
        self.assertIn("STDOUT:", formatted)
        self.assertIn("Hello", formatted)
        self.assertIn("✅ Command completed successfully", formatted)

    def test_format_failed_result(self):
        """Test formatting failed execution result."""
        result = {
            'success': False,
            'returncode': -1,
            'stdout': '',
            'stderr': '',
            'execution_time': 0,
            'error_message': 'Command blocked: dangerous'
        }

        formatted = self.executor.format_result(result, "rm -rf /")

        self.assertIn("❌ Command failed: Command blocked: dangerous", formatted)

    def test_format_result_with_stderr(self):
        """Test formatting result with stderr output."""
        result = {
            'success': True,
            'returncode': 1,
            'stdout': '',
            'stderr': 'Error: something went wrong',
            'execution_time': 0.5,
            'error_message': ''
        }

        formatted = self.executor.format_result(result, "invalid_cmd")

        self.assertIn("STDERR:", formatted)
        self.assertIn("something went wrong", formatted)
        self.assertIn("⚠️  Command failed (non-zero exit code)", formatted)

    def test_format_result_truncated_output(self):
        """Test formatting result with truncated output."""
        result = {
            'success': True,
            'returncode': 0,
            'stdout': 'X' * 100 + '\n...[output truncated]',
            'stderr': '',
            'execution_time': 0.1,
            'error_message': ''
        }

        formatted = self.executor.format_result(result, "large_output")

        self.assertIn("[output truncated]", formatted)


class TestConvenienceFunctions(unittest.TestCase):
    """Test global convenience functions."""

    def test_execute_safe(self):
        """Test global execute_safe function."""
        with patch('agent.command_executor._default_executor') as mock_executor:
            mock_executor.execute.return_value = {'success': True}

            result = execute_safe("echo test", cwd="/tmp", timeout=10)

            mock_executor.execute.assert_called_once_with(
                "echo test", cwd="/tmp", timeout=10
            )
            self.assertEqual(result, {'success': True})

    def test_execute_git_safe(self):
        """Test global execute_git_safe function."""
        with patch('agent.command_executor._default_executor') as mock_executor:
            mock_executor.execute_git.return_value = {'success': True}

            result = execute_git_safe("status", cwd="/repo", timeout=15)

            mock_executor.execute_git.assert_called_once_with(
                "status", cwd="/repo", timeout=15
            )
            self.assertEqual(result, {'success': True})


if __name__ == '__main__':
    unittest.main()