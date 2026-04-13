#!/usr/bin/env python3
"""Claude Code PreToolUse hook — block dangerous iTerm2 window close operations.

Background: 2026-04-12 incident — Claude wrote a script that called
iterm2.Window.async_close() in a loop with a "filter" intended to keep the
Claude Code session window. The filter heuristic failed because the prompt
banner had scrolled out of viewport, so all 9 iTerm2 windows were closed,
INCLUDING the one running the active Claude Code session. The conversation
was killed mid-task.

Memory file:
  /Users/user/.claude/projects/.../memory/feedback_never_close_iterm2_windows.md

This hook intercepts Bash tool calls (where most iTerm2 manipulation happens
via .venv/bin/python -c '...iterm2...' or similar) and rejects any command
that pattern-matches a dangerous iTerm2 close operation.

How it works (Claude Code hook contract):
- Reads JSON from stdin: {"tool_name": "Bash", "tool_input": {"command": "..."}}
- For dangerous patterns: prints reason to stderr and exits 2 (blocks the call)
- For safe patterns: exits 0 (allows the call)

Bypass for emergencies (when you GENUINELY need to close iTerm2 windows
intentionally and have manually verified): set NEOMIND_ALLOW_ITERM2_CLOSE=1
in the environment before invoking the command.
"""
from __future__ import annotations
import json
import os
import re
import sys


# Dangerous patterns — case-insensitive substring or regex match against the
# Bash command string. Order: most specific first.
DANGEROUS_PATTERNS = [
    # Direct iterm2 Python API close calls
    (r"\.async_close\b", "iterm2 Window.async_close call (the exact pattern from the 2026-04-12 incident)"),
    (r"window\.async_close", "iterm2 window.async_close call"),
    (r"for\s+\w+\s+in\s+app\.windows", "iterating app.windows — high risk of batch close"),
    (r"for\s+\w+\s+in\s+.*\.windows\(\)", "iterating windows collection"),

    # Indirect iTerm2 control via osascript
    (r"osascript.*tell\s+application\s+\"iTerm", "osascript controlling iTerm.app"),
    (r"osascript.*close.*iterm", "osascript with close + iterm"),

    # Process-level kill of iTerm — match `pkill ... iterm/iTerm/iTerm2` with any flags between
    (r"pkill\b[^|;&]*\b[Ii][Tt]erm", "pkill targeting iTerm process"),
    (r"killall\b[^|;&]*\b[Ii][Tt]erm", "killall targeting iTerm process"),
    (r"kill\s+-9\s+\$\(pgrep[^|;&]*[Ii]term", "kill -9 of iterm pgrep result"),

    # Apple System Events close
    (r"System Events.*close.*iTerm", "System Events close on iTerm"),
]


def check_command(cmd: str) -> str | None:
    """Return reason string if command is dangerous, None if safe."""
    if not cmd:
        return None
    for pattern, reason in DANGEROUS_PATTERNS:
        if re.search(pattern, cmd, re.IGNORECASE):
            return reason
    return None


def main() -> int:
    # Bypass via env var for genuinely intentional closes
    if os.environ.get("NEOMIND_ALLOW_ITERM2_CLOSE"):
        return 0

    # Read tool input from stdin
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        # Can't parse — be permissive (don't block real work)
        return 0

    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input", {}) or {}

    # Only inspect Bash tool calls (other tools don't run iterm2 code)
    if tool_name != "Bash":
        return 0

    cmd = tool_input.get("command", "") or ""
    reason = check_command(cmd)
    if reason is None:
        return 0

    # Found a dangerous pattern — block with clear explanation
    msg = (
        f"\n🚨 BLOCKED: iTerm2 window close attempt detected\n"
        f"Pattern matched: {reason}\n"
        f"\n"
        f"Memory rule: NEVER close iTerm2 windows programmatically. On 2026-04-12 "
        f"this exact pattern killed Claude Code's own session mid-task.\n"
        f"\n"
        f"What to do instead:\n"
        f"  1. Leave the windows alone — the user can ⌘W close them manually.\n"
        f"  2. If a runner created the window, let the runner's own context "
        f"manager (async with ITerm2CliTester) close ITS OWN window on exit.\n"
        f"  3. Never iterate app.windows or call .async_close on any window "
        f"you didn't create yourself in the same session.\n"
        f"\n"
        f"If you GENUINELY need to bypass (you've manually confirmed which "
        f"window is which and accept the risk), prefix the command with:\n"
        f"  NEOMIND_ALLOW_ITERM2_CLOSE=1 ...\n"
        f"\n"
        f"Command that was blocked:\n"
        f"  {cmd[:300]}{'...' if len(cmd) > 300 else ''}\n"
    )
    print(msg, file=sys.stderr)
    return 2  # Claude Code: exit 2 = block the tool call


if __name__ == "__main__":
    sys.exit(main())
