"""
Utility Commands — grep, find, verbose, clear, history, think, quit, exit, mode.

Extracted from core.py (Tier 2I). Each function takes the core agent reference
and command string, returning formatted output.

Created: 2026-04-01 (Phase 0 - Infrastructure Refactoring)
"""

from __future__ import annotations

import os
import re
import fnmatch
import subprocess
from typing import TYPE_CHECKING, Optional, List

if TYPE_CHECKING:
    from agent.core import NeoMindAgent


def handle_mode_command(core: "NeoMindAgent", command: str) -> Optional[str]:
    """
    Handle /mode command for switching between chat, coding, and fin modes.

    Args:
        core: NeoMind agent instance
        command: Mode name or subcommand

    Returns:
        Status message
    """
    command = command.strip().lower()
    if not command or command == "status":
        return f"Current mode: {core.mode}"
    elif command == "chat":
        success = core.switch_mode("chat")
        return "Switched to chat mode." if success else "Failed to switch to chat mode."
    elif command == "coding":
        success = core.switch_mode("coding")
        return "Switched to coding mode." if success else "Failed to switch to coding mode."
    elif command == "fin":
        success = core.switch_mode("fin")
        return "Switched to fin mode." if success else "Failed to switch to fin mode."
    elif command == "help":
        return (
            "/mode command usage:\n"
            "  /mode chat      - Switch to chat mode\n"
            "  /mode coding    - Switch to coding mode\n"
            "  /mode fin       - Switch to finance mode\n"
            "  /mode status    - Show current mode\n"
            "  /mode help      - Show this help"
        )
    else:
        return "Invalid mode. Use 'chat', 'coding', 'fin', 'status', or 'help'."


def handle_grep_command(core: "NeoMindAgent", command: str) -> Optional[str]:
    """
    Handle /grep command to search for text across files.

    Args:
        core: NeoMind agent instance
        command: Pattern and optional path

    Returns:
        Search results
    """
    if not command.strip():
        return "Usage: /grep <pattern> [path]"

    parts = command.strip().split()
    pattern = parts[0]
    path = parts[1] if len(parts) > 1 else "."

    # Use ripgrep if available, else Python regex
    try:
        result = subprocess.run(
            ["rg", "-n", "-i", pattern, path],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            output = result.stdout
            if not output.strip():
                return f"🔍 No matches for pattern '{pattern}' in {path}"
            return f"🔍 Grep results for '{pattern}' in {path}:\n{output}"
        else:
            # Fallback to Python regex
            return _grep_fallback(pattern, path)
    except (subprocess.SubprocessError, FileNotFoundError):
        return _grep_fallback(pattern, path)


def _grep_fallback(pattern: str, path: str) -> str:
    """Fallback grep using Python regex."""
    matches = []
    pattern_re = re.compile(pattern, re.IGNORECASE)
    for root, dirs, files in os.walk(path):
        for file in files:
            file_path = os.path.join(root, file)
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    for line_num, line in enumerate(f, 1):
                        if pattern_re.search(line):
                            matches.append(f"{file_path}:{line_num}: {line.rstrip()}")
            except Exception:
                continue
    if not matches:
        return f"🔍 No matches for pattern '{pattern}' in {path}"
    return f"🔍 Grep results for '{pattern}' in {path} (Python fallback):\n" + "\n".join(matches[:50])


def handle_find_command(core: "NeoMindAgent", command: str) -> Optional[str]:
    """
    Handle /find command to find files matching pattern.

    Args:
        core: NeoMind agent instance
        command: Pattern and optional path

    Returns:
        Matching files
    """
    if not command.strip():
        return "Usage: /find <pattern> [path]"

    parts = command.strip().split()
    pattern = parts[0]
    path = parts[1] if len(parts) > 1 else "."

    matches = []
    for root, dirs, files in os.walk(path):
        for name in files + dirs:
            if fnmatch.fnmatch(name, pattern):
                full_path = os.path.join(root, name)
                matches.append(full_path)
    if not matches:
        return f"📭 No files/directories matching '{pattern}' in {path}"
    return f"📂 Found {len(matches)} matches for '{pattern}' in {path}:\n" + "\n".join(matches[:50])


def handle_verbose_command(core: "NeoMindAgent", command: str) -> Optional[str]:
    """
    Handle /verbose command to toggle verbose debug output.

    Args:
        core: NeoMind agent instance
        command: on/off/toggle

    Returns:
        Status message
    """
    cmd = command.strip().lower()
    if cmd == "on":
        core.verbose_mode = True
        status = "ENABLED"
    elif cmd == "off":
        core.verbose_mode = False
        status = "DISABLED"
    elif cmd == "toggle" or cmd == "":
        core.toggle_verbose_mode()
        status = "TOGGLED"
    else:
        return f"❌ Invalid option: {cmd}. Use /verbose [on|off|toggle]"

    if core.verbose_mode and hasattr(core, 'status_buffer') and core.status_buffer:
        result = [f"🔊 Verbose mode: {status}", "📋 Recent debug messages:"]
        for entry in core.status_buffer[-10:]:
            result.append(f"  [{entry['level']}] {entry['message']}")
        return "\n".join(result)
    return f"🔊 Verbose mode: {status}"


def handle_clear_command(core: "NeoMindAgent", command: str) -> Optional[str]:
    """
    Handle /clear command to clear conversation history.

    Args:
        core: NeoMind agent instance
        command: (unused)

    Returns:
        Status message
    """
    core.clear_history()
    return "🗑️ Conversation history cleared."


def handle_history_command(core: "NeoMindAgent", command: str) -> Optional[str]:
    """
    Handle /history command to show conversation history.

    Args:
        core: NeoMind agent instance
        command: (unused)

    Returns:
        Conversation history
    """
    if not hasattr(core, 'conversation_history') or not core.conversation_history:
        return "📭 No conversation history."

    result = ["📜 Conversation History:"]
    for i, msg in enumerate(core.conversation_history, 1):
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        preview = content[:100] + "..." if len(content) > 100 else content
        result.append(f"{i}. [{role}] {preview}")
    return "\n".join(result)


def handle_think_command(core: "NeoMindAgent", command: str) -> Optional[str]:
    """
    Handle /think command to toggle thinking mode.

    Args:
        core: NeoMind agent instance
        command: (unused)

    Returns:
        Status message
    """
    core.toggle_thinking_mode()
    status = "enabled" if getattr(core, 'thinking_enabled', False) else "disabled"
    return f"🤔 Thinking mode {status}."


def handle_quit_command(core: "NeoMindAgent", command: str) -> Optional[str]:
    """
    Handle /quit command to exit (signal to CLI).

    Args:
        core: NeoMind agent instance
        command: (unused)

    Returns:
        Quit message
    """
    return "🛑 Quit command received. Use Ctrl+C or type /quit in the CLI to exit."


def handle_exit_command(core: "NeoMindAgent", command: str) -> Optional[str]:
    """
    Handle /exit command (alias for /quit).

    Args:
        core: NeoMind agent instance
        command: (unused)

    Returns:
        Exit message
    """
    return handle_quit_command(core, command)


def handle_apply_command(core: "NeoMindAgent", command: str) -> Optional[str]:
    """
    Handle /apply command for applying pending changes.

    Args:
        core: NeoMind agent instance
        command: Optional flags

    Returns:
        Result of apply operation
    """
    # Check for force flag
    force = command.strip().lower() == "force"

    if hasattr(core, 'code_analyzer') and core.code_analyzer:
        pending = getattr(core.code_analyzer, 'pending_changes', [])
        if not pending:
            return "📭 No pending changes to apply."

        if force:
            # Apply without confirmation
            results = core.code_analyzer.apply_all_changes()
            return f"✅ Applied {len(results)} changes without confirmation."
        else:
            # Apply with confirmation
            return core._auto_apply_changes_with_confirmation()
    else:
        return "❌ Code analyzer not available."


# ── LLM Analysis Commands ──────────────────────────────────────────────────

def handle_summarize_command(core: "NeoMindAgent", command: str) -> Optional[str]:
    """Handle /summarize command."""
    if hasattr(core, '_active_personality') and core._active_personality:
        return core._active_personality._shared_handle_summarize_command(command)
    if not command or not command.strip():
        return "Usage: /summarize <text>"
    prompt = f"Summarize the following content concisely:\n\n{command.strip()}"
    try:
        return f"📝 Summary:\n{core.generate_completion([{'role': 'user', 'content': prompt}], temperature=0.3, max_tokens=1000)}"
    except Exception as e:
        return f"❌ Failed to generate summary: {e}"


def handle_translate_command(core: "NeoMindAgent", command: str) -> Optional[str]:
    """Handle /translate command."""
    if hasattr(core, '_active_personality') and core._active_personality:
        return core._active_personality._shared_handle_translate_command(command)
    return "Usage: /translate <text> [to <language>]"


def handle_generate_command(core: "NeoMindAgent", command: str) -> Optional[str]:
    """Handle /generate command."""
    if hasattr(core, '_active_personality') and core._active_personality:
        return core._active_personality._shared_handle_generate_command(command)
    return "Usage: /generate <prompt>"


def handle_reason_command(core: "NeoMindAgent", command: str) -> Optional[str]:
    """Handle /reason command."""
    if hasattr(core, '_active_personality') and core._active_personality:
        return core._active_personality._shared_handle_reason_command(command)
    return "Usage: /reason <problem>"


def handle_debug_command(core: "NeoMindAgent", command: str) -> Optional[str]:
    """Handle /debug command."""
    if hasattr(core, '_active_personality') and core._active_personality:
        return core._active_personality._shared_handle_debug_command(command)
    return "Usage: /debug <file_path> or /debug <code snippet>"


def handle_explain_command(core: "NeoMindAgent", command: str) -> Optional[str]:
    """Handle /explain command."""
    if hasattr(core, '_active_personality') and core._active_personality:
        return core._active_personality._shared_handle_explain_command(command)
    return "Usage: /explain <file_path> or /explain <code snippet>"


def handle_refactor_command(core: "NeoMindAgent", command: str) -> Optional[str]:
    """Handle /refactor command."""
    if hasattr(core, '_active_personality') and core._active_personality:
        return core._active_personality._shared_handle_refactor_command(command)
    return "Usage: /refactor <file_path>"


__all__ = [
    'handle_mode_command',
    'handle_grep_command',
    'handle_find_command',
    'handle_verbose_command',
    'handle_clear_command',
    'handle_history_command',
    'handle_think_command',
    'handle_quit_command',
    'handle_exit_command',
    'handle_apply_command',
    'handle_summarize_command',
    'handle_translate_command',
    'handle_generate_command',
    'handle_reason_command',
    'handle_debug_command',
    'handle_explain_command',
    'handle_refactor_command',
]
