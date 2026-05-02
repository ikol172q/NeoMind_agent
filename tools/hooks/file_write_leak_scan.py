#!/usr/bin/env python3
"""Claude Code PreToolUse hook — block Edit/Write/MultiEdit if the
content about to be written contains a secret or known PII pattern.

Why this exists in addition to leak_scan_hook.py:
- leak_scan_hook only fires on `git commit` / `git push` Bash calls.
- Anything written via the Edit / Write / MultiEdit tools and never
  committed (working-tree experiments, debug dumps, .playwright-mcp
  snapshots, prompt files) was previously invisible to the scan.
- This hook closes that gap by piping the candidate content through
  `gitleaks detect --no-git --pipe` BEFORE the file is written.

Behavior:
- Edit       → scan tool_input.new_string
- Write      → scan tool_input.content
- MultiEdit  → scan each edit's new_string concatenated
- gitleaks finds something → exit 2 (block)
- Bypass: NEOMIND_ALLOW_LEAKS=1 (same env var as leak_scan_hook)

Fail-closed: if gitleaks isn't installed, block and tell the user how
to install it. Personal-data safety > convenience.
"""
from __future__ import annotations
import json
import os
import re
import shutil
import subprocess
import sys


GITLEAKS_CONFIG = os.path.join(
    os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()),
    ".gitleaks.toml",
)


def have_gitleaks() -> bool:
    return shutil.which("gitleaks") is not None


_LEAKS_FOUND_RE = re.compile(r"leaks found:\s*(\d+)", re.IGNORECASE)


def scan_content(content: str) -> tuple[bool, str]:
    """Pipe content through `gitleaks detect --pipe`. Returns
    (clean?, finding_message).

    NOTE on exit code: gitleaks --pipe always exits 0 even when leaks
    are found (known behavior in current gitleaks versions). We parse
    stderr for the `leaks found: N` summary line and treat N>0 as
    fail. Without this, every clean file would still report `exit 0`
    just like a leaked one — silent bypass.
    """
    if not content:
        return True, ""
    args = ["gitleaks", "detect", "--pipe", "--no-banner", "--redact"]
    if os.path.exists(GITLEAKS_CONFIG):
        args.extend(["--config", GITLEAKS_CONFIG])
    try:
        p = subprocess.run(
            args, input=content, capture_output=True, text=True, timeout=30,
        )
    except subprocess.TimeoutExpired:
        return True, ""  # don't block on hung scanner
    except FileNotFoundError:
        return False, "gitleaks not installed"
    combined = (p.stdout or "") + (p.stderr or "")
    m = _LEAKS_FOUND_RE.search(p.stderr or "")
    n_leaks = int(m.group(1)) if m else 0
    if n_leaks > 0:
        return False, combined[:2000]
    return True, ""


def emit_block(reason: str, details: str, file_path: str) -> int:
    msg = (
        f"\nBLOCKED: pre-{reason} content scan failed\n"
        f"\n"
        f"file: {file_path}\n"
        f"\n"
        f"{details}\n"
        f"\n"
        f"This hook fires on Edit/Write/MultiEdit before the file is\n"
        f"written, closing the gap that leak_scan_hook (commit/push only)\n"
        f"left open.\n"
        f"\n"
        f"Bypass (only after manual verification):\n"
        f"  NEOMIND_ALLOW_LEAKS=1 ...\n"
        f"\n"
        f"If a finding is a known false positive, add it to .gitleaks.toml's\n"
        f"[allowlist] section instead of bypassing.\n"
    )
    print(msg, file=sys.stderr)
    return 2


def main() -> int:
    if os.environ.get("NEOMIND_ALLOW_LEAKS"):
        return 0

    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    tool = payload.get("tool_name")
    tool_input = payload.get("tool_input") or {}

    if tool == "Edit":
        content = tool_input.get("new_string", "") or ""
    elif tool == "Write":
        content = tool_input.get("content", "") or ""
    elif tool == "MultiEdit":
        edits = tool_input.get("edits") or []
        parts = [e.get("new_string", "") or "" for e in edits if isinstance(e, dict)]
        content = "\n".join(parts)
    elif tool == "NotebookEdit":
        content = tool_input.get("new_source", "") or ""
    else:
        return 0  # not a write tool; nothing to do

    if not have_gitleaks():
        return emit_block(
            "Edit/Write",
            "gitleaks not installed. Run:\n  brew install gitleaks\nThen retry.",
            tool_input.get("file_path", "<unknown>"),
        )

    clean, finding = scan_content(content)
    if not clean:
        return emit_block(
            "Edit/Write",
            finding,
            tool_input.get("file_path", "<unknown>"),
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
