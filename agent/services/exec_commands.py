"""
Execution Commands — run, git, shell operations.

Extracted from core.py (Tier 2H). Each function takes the core agent reference
and command string, returning formatted output.

Created: 2026-04-01 (Phase 0 - Infrastructure Refactoring)
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.core import NeoMindAgent


def handle_run_command(core: "NeoMindAgent", command: str) -> str:
    """
    Handle /run command for safe shell command execution.

    Args:
        core: NeoMind agent instance
        command: Command string to execute

    Returns:
        Formatted output or error message
    """
    if not command or command.strip() == "":
        help_text = """
🔧 /run Command Usage:
  /run <command> [args...]   - Execute a shell command safely

Examples:
  /run ls -la
  /run python --version
  /run npm install
  /run echo "Hello"
        """.strip()
        return help_text

    # Auto-switch to coding mode for run command
    if core.mode != 'coding':
        core.switch_mode('coding', persist=False)

    # Guard check
    is_allowed, guard_warning = core._check_guards(command)
    if not is_allowed:
        core._log_evidence("command", command, guard_warning, severity="warning")
        return core.formatter.warning(f"🛑 BLOCKED by safety guard:\n{guard_warning}")

    # Determine working directory
    cwd = os.getcwd()
    if core.code_analyzer:
        cwd = core.code_analyzer.root_path

    # Execute using command executor
    result = core.command_executor.execute(command, cwd=cwd)

    # Log command execution
    from agent.safety import log_operation
    log_operation('execute', command, result['success'],
                  f"cwd={cwd}, exit_code={result['returncode']}, time={result['execution_time']:.2f}s")

    # Log to evidence trail
    core._log_evidence("command", command, f"exit_code={result['returncode']}",
                       severity="info" if result['success'] else "warning")

    # Format result
    if not result['success']:
        return core.formatter.error(result['error_message'])

    # Build formatted output
    output = f"🚀 Command: {command}\n"
    output += f"📁 Working directory: {cwd}\n"
    output += f"⏱️  Execution time: {result['execution_time']:.2f}s\n"
    output += f"📤 Exit code: {result['returncode']}\n"

    if result['stdout']:
        output += f"\n📤 STDOUT:\n{result['stdout'].rstrip()}\n"
    if result['stderr']:
        output += f"\n📤 STDERR:\n{result['stderr'].rstrip()}\n"

    if result['returncode'] == 0:
        output += f"\n{core.formatter.success('Command completed successfully.')}"
    else:
        output += f"\n{core.formatter.warning('Command failed (non-zero exit code).')}"

    return output


def handle_git_command(core: "NeoMindAgent", command: str) -> str:
    """
    Handle /git command for version control operations.

    Args:
        core: NeoMind agent instance
        command: Git command string

    Returns:
        Formatted output or error message
    """
    if not command or command.strip() == "":
        help_text = """
🔄 /git Command Usage:
  /git <subcommand> [args...]   - Execute git command safely

Common subcommands:
  status, diff, log, commit, push, pull, branch, checkout, clone, init

Examples:
  /git status
  /git diff
  /git log --oneline -5
  /git commit -m "message"
  /git push origin main
        """.strip()
        return help_text

    # Auto-switch to coding mode for git command
    if core.mode != 'coding':
        core.switch_mode('coding', persist=False)

    # Determine working directory
    cwd = os.getcwd()
    if core.code_analyzer:
        cwd = core.code_analyzer.root_path

    # Execute using command executor's git-specific method
    result = core.command_executor.execute_git(command, cwd=cwd)

    # Format result
    if not result['success']:
        return core.formatter.error(result['error_message'])

    # Build formatted output
    output = f"🔄 Git command: git {command}\n"
    output += f"📁 Working directory: {cwd}\n"
    output += f"⏱️  Execution time: {result['execution_time']:.2f}s\n"
    output += f"📤 Exit code: {result['returncode']}\n"

    if result['stdout']:
        output += f"\n📤 STDOUT:\n{result['stdout'].rstrip()}\n"
    if result['stderr']:
        output += f"\n📤 STDERR:\n{result['stderr'].rstrip()}\n"

    if result['returncode'] == 0:
        output += f"\n{core.formatter.success('Git command completed successfully.')}"
    else:
        output += f"\n{core.formatter.warning('Git command failed (non-zero exit code).')}"

    return output


__all__ = [
    'handle_run_command',
    'handle_git_command',
]
