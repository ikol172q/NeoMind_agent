"""
Safe command execution with sandboxing and resource limits.
Provides a secure wrapper for shell command execution.
"""
import subprocess
import shlex
import os
import time
import threading
from typing import Tuple, Optional, List, Dict, Any
import signal
import sys
import tempfile
import shutil

class CommandExecutor:
    """Safe command execution with safety checks and resource limits."""

    # Dangerous command patterns (blocked)
    DANGEROUS_PATTERNS = [
        'rm -rf', 'rm -fr', 'rm -fr /', 'rm -rf /',
        'format', 'mkfs', 'dd if=', 'dd of=',
        ':(){ :|:& };:', 'forkbomb',
        'chmod 777', 'chown', 'sudo',
        '> /dev/sda', '> /dev/null',
        'wget', 'curl', 'bash -c', 'sh -c',
        'python -c', 'perl -e',
    ]

    # Allowed commands (if allowlist enabled)
    ALLOWED_COMMANDS = [
        'ls', 'pwd', 'cd', 'cat', 'head', 'tail', 'grep', 'find', 'which',
        'python', 'python3', 'pip', 'pip3', 'git', 'echo', 'mkdir', 'cp', 'mv',
        'node', 'npm', 'npx', 'docker', 'docker-compose', 'go', 'cargo',
        'rustc', 'javac', 'java', 'dotnet', 'terraform', 'kubectl',
    ]

    # Dangerous git operations
    DANGEROUS_GIT_PATTERNS = [
        'reset --hard',
        'clean -fd',
        'push --force',
        'branch -D',
        'checkout .',
        'stash drop',
    ]

    def __init__(self, allowlist_mode: bool = False, timeout: int = 30,
                 max_output_size: int = 10 * 1024 * 1024,  # 10MB
                 min_interval: float = 0.0):  # seconds, 0 = disabled
        """
        Initialize command executor.

        Args:
            allowlist_mode: If True, only commands in ALLOWED_COMMANDS are allowed.
            timeout: Default timeout in seconds.
            max_output_size: Maximum output size in bytes.
            min_interval: Minimum time between commands (rate limiting). 0 disables.
        """
        self.allowlist_mode = allowlist_mode
        self.default_timeout = timeout
        self.max_output_size = max_output_size
        self.min_interval = min_interval
        self.last_execution_time = 0
        self.sandbox_dir = None

    def _setup_sandbox(self) -> str:
        """Create a temporary sandbox directory for safe execution."""
        if self.sandbox_dir is None:
            self.sandbox_dir = tempfile.mkdtemp(prefix="cmd_sandbox_")
        return self.sandbox_dir

    def _cleanup_sandbox(self):
        """Clean up sandbox directory."""
        if self.sandbox_dir and os.path.exists(self.sandbox_dir):
            shutil.rmtree(self.sandbox_dir, ignore_errors=True)
            self.sandbox_dir = None

    def is_command_safe(self, command: str, is_git: bool = False) -> Tuple[bool, str]:
        """
        Check if command is safe to execute.
        Returns (is_safe, reason).
        """
        cmd_lower = command.lower()

        # Check dangerous patterns
        dangerous_patterns = self.DANGEROUS_PATTERNS
        if is_git:
            dangerous_patterns = dangerous_patterns + self.DANGEROUS_GIT_PATTERNS

        for pattern in dangerous_patterns:
            if pattern in cmd_lower:
                return False, f"Contains dangerous pattern: '{pattern}'"

        # Allowlist check
        if self.allowlist_mode:
            # Extract first token (command name)
            try:
                parts = shlex.split(command)
                if not parts:
                    return False, "Empty command"
                cmd_name = parts[0].lower()
                # Check if command is in allowed list
                if cmd_name not in self.ALLOWED_COMMANDS:
                    return False, f"Command '{cmd_name}' not in allowlist"
            except ValueError:
                return False, "Invalid command syntax"

        # Additional safety: prevent changing directory outside workspace
        if 'cd ' in cmd_lower and '..' in cmd_lower:
            # Could attempt to escape workspace
            return False, "Directory traversal with '..' not allowed"

        return True, "Command is safe"

    def execute(self, command: str, cwd: Optional[str] = None,
                timeout: Optional[int] = None,
                env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """
        Execute a command safely with timeout and output limits.

        Returns:
            Dictionary with keys: success, returncode, stdout, stderr,
            execution_time, error_message
        """
        start_time = time.time()

        # Safety check
        is_safe, reason = self.is_command_safe(command)
        if not is_safe:
            return {
                'success': False,
                'returncode': -1,
                'stdout': '',
                'stderr': '',
                'execution_time': 0,
                'error_message': f"Command blocked: {reason}"
            }

        # Rate limiting
        if self.min_interval > 0:
            now = time.time()
            elapsed = now - self.last_execution_time
            if elapsed < self.min_interval:
                return {
                    'success': False,
                    'returncode': -1,
                    'stdout': '',
                    'stderr': '',
                    'execution_time': 0,
                    'error_message': f"Rate limit: wait {self.min_interval - elapsed:.1f}s between commands"
                }
            self.last_execution_time = now

        # Parse command
        try:
            parts = shlex.split(command)
        except ValueError as e:
            return {
                'success': False,
                'returncode': -1,
                'stdout': '',
                'stderr': '',
                'execution_time': 0,
                'error_message': f"Invalid command syntax: {e}"
            }

        if not parts:
            return {
                'success': False,
                'returncode': -1,
                'stdout': '',
                'stderr': '',
                'execution_time': 0,
                'error_message': "Empty command"
            }

        # Set working directory
        working_dir = cwd or os.getcwd()
        if not os.path.exists(working_dir):
            return {
                'success': False,
                'returncode': -1,
                'stdout': '',
                'stderr': '',
                'execution_time': 0,
                'error_message': f"Working directory does not exist: {working_dir}"
            }

        # Set environment
        env_vars = os.environ.copy()
        if env:
            env_vars.update(env)

        # Limit environment variables for security
        safe_env = {}
        for key in ['PATH', 'HOME', 'USER', 'LANG', 'TERM', 'PYTHONPATH']:
            if key in env_vars:
                safe_env[key] = env_vars[key]

        # Execute with timeout
        timeout_val = timeout or self.default_timeout

        try:
            process = subprocess.run(
                parts,
                cwd=working_dir,
                env=safe_env,
                capture_output=True,
                text=True,
                timeout=timeout_val,
                shell=False
            )

            execution_time = time.time() - start_time

            # Check output size limits
            total_size = len(process.stdout) + len(process.stderr)
            if total_size > self.max_output_size:
                # Truncate output
                if len(process.stdout) > self.max_output_size // 2:
                    process.stdout = process.stdout[:self.max_output_size // 2] + "\n...[output truncated]"
                if len(process.stderr) > self.max_output_size // 2:
                    process.stderr = process.stderr[:self.max_output_size // 2] + "\n...[output truncated]"

            return {
                'success': True,
                'returncode': process.returncode,
                'stdout': process.stdout,
                'stderr': process.stderr,
                'execution_time': execution_time,
                'error_message': ''
            }

        except subprocess.TimeoutExpired:
            return {
                'success': False,
                'returncode': -1,
                'stdout': '',
                'stderr': '',
                'execution_time': timeout_val,
                'error_message': f"Command timed out after {timeout_val} seconds"
            }
        except FileNotFoundError:
            return {
                'success': False,
                'returncode': -1,
                'stdout': '',
                'stderr': '',
                'execution_time': time.time() - start_time,
                'error_message': f"Command not found: {parts[0]}"
            }
        except Exception as e:
            return {
                'success': False,
                'returncode': -1,
                'stdout': '',
                'stderr': '',
                'execution_time': time.time() - start_time,
                'error_message': f"Execution error: {str(e)}"
            }

    def execute_git(self, git_command: str, cwd: Optional[str] = None,
                    timeout: Optional[int] = None) -> Dict[str, Any]:
        """
        Execute a git command with additional safety checks.

        Args:
            git_command: Git subcommand and arguments (e.g., "status", "log --oneline -5")
            cwd: Working directory (should be a git repository)
            timeout: Timeout in seconds

        Returns:
            Same as execute() but with git-specific safety checks.
        """
        # Check if git is installed
        git_check = self.execute("git --version", cwd=cwd, timeout=5)
        if not git_check['success']:
            return git_check

        # Safety check for dangerous git operations
        is_safe, reason = self.is_command_safe(git_command, is_git=True)
        if not is_safe:
            return {
                'success': False,
                'returncode': -1,
                'stdout': '',
                'stderr': '',
                'execution_time': 0,
                'error_message': f"Git command blocked: {reason}"
            }

        # Execute git command
        full_command = f"git {git_command}"
        return self.execute(full_command, cwd=cwd, timeout=timeout)

    def format_result(self, result: Dict[str, Any], command: str) -> str:
        """Format execution result for display."""
        if not result['success']:
            return f"❌ Command failed: {result['error_message']}"

        output = f"🚀 Command: {command}\n"
        output += f"📁 Working directory: {os.getcwd()}\n"
        output += f"⏱️  Execution time: {result['execution_time']:.2f}s\n"
        output += f"📤 Exit code: {result['returncode']}\n"

        if result['stdout']:
            output += f"\n📤 STDOUT:\n{result['stdout'].rstrip()}\n"
        if result['stderr']:
            output += f"\n📤 STDERR:\n{result['stderr'].rstrip()}\n"

        if result['returncode'] == 0:
            output += "\n✅ Command completed successfully."
        else:
            output += "\n⚠️  Command failed (non-zero exit code)."

        return output


# Global instance for convenience
_default_executor = CommandExecutor()

def execute_safe(command: str, **kwargs) -> Dict[str, Any]:
    """Convenience function using default executor."""
    return _default_executor.execute(command, **kwargs)

def execute_git_safe(git_command: str, **kwargs) -> Dict[str, Any]:
    """Convenience function for git commands."""
    return _default_executor.execute_git(git_command, **kwargs)