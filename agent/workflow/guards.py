# agent/workflow/guards.py
"""
Safety Guards — /careful, /freeze, /guard (from gstack pattern).

Protects all 3 personalities from destructive operations:
- /careful: warn before dangerous commands
- /freeze <dir>: restrict edits to one directory
- /guard: both at once
- /unfreeze: remove restrictions

Thread-safe, state persisted to JSON.
"""

import os
import re
import json
from pathlib import Path
from typing import Optional, List, Tuple
from datetime import datetime, timezone


# ── Dangerous Command Patterns ───────────────────────────────────

DANGEROUS_PATTERNS = {
    # File system
    "rm_recursive": {
        "pattern": r"\brm\s+(-[a-zA-Z]*[rf][a-zA-Z]*\s+|--force\s+|--recursive\s+)",
        "description": "Recursive/forced file deletion",
        "severity": "critical",
    },
    "chmod_wide": {
        "pattern": r"\bchmod\s+(-R\s+)?(777|666|a\+[rwx])",
        "description": "Wide permission change",
        "severity": "high",
    },
    "overwrite_redirect": {
        "pattern": r">\s*/etc/|>\s*/usr/|>\s*/sys/",
        "description": "Overwriting system file",
        "severity": "critical",
    },

    # Git
    "force_push": {
        "pattern": r"\bgit\s+push\s+(-[a-zA-Z]*f|--force)",
        "description": "Force push (may lose remote commits)",
        "severity": "critical",
    },
    "hard_reset": {
        "pattern": r"\bgit\s+reset\s+--hard",
        "description": "Hard reset (discards uncommitted changes)",
        "severity": "high",
    },
    "git_clean": {
        "pattern": r"\bgit\s+clean\s+-[a-zA-Z]*f",
        "description": "Force clean (deletes untracked files)",
        "severity": "high",
    },
    "branch_force_delete": {
        "pattern": r"\bgit\s+branch\s+-D",
        "description": "Force delete branch",
        "severity": "medium",
    },

    # Database
    "drop_table": {
        "pattern": r"\bDROP\s+(TABLE|DATABASE)\b",
        "description": "Drop table/database",
        "severity": "critical",
    },
    "delete_no_where": {
        "pattern": r"\bDELETE\s+FROM\s+\w+\s*;",
        "description": "DELETE without WHERE clause",
        "severity": "critical",
    },
    "truncate": {
        "pattern": r"\bTRUNCATE\s+TABLE\b",
        "description": "Truncate table",
        "severity": "high",
    },

    # System
    "sudo": {
        "pattern": r"\bsudo\s+",
        "description": "Elevated privileges",
        "severity": "medium",
    },
    "pip_system": {
        "pattern": r"\bpip\s+install\b(?!.*--user|.*venv|.*-e\s)",
        "description": "pip install outside virtualenv",
        "severity": "low",
    },

    # Financial (fin mode)
    "trade_execute": {
        "pattern": r"\b(execute_trade|submit_order|place_order|market_buy|market_sell)\b",
        "description": "Executing real-money trade",
        "severity": "critical",
    },
}


# ── Guard State ──────────────────────────────────────────────────

class GuardState:
    """Persisted guard state."""

    def __init__(self):
        self.careful_enabled: bool = False
        self.freeze_enabled: bool = False
        self.freeze_directory: str = ""
        self._state_path = Path(os.getenv("HOME", "/data")) / ".neomind" / "guard_state.json"

    def load(self):
        try:
            if self._state_path.exists():
                data = json.loads(self._state_path.read_text())
                self.careful_enabled = data.get("careful", False)
                self.freeze_enabled = data.get("freeze", False)
                self.freeze_directory = data.get("freeze_dir", "")
        except Exception:
            pass

    def save(self):
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            self._state_path.write_text(json.dumps({
                "careful": self.careful_enabled,
                "freeze": self.freeze_enabled,
                "freeze_dir": self.freeze_directory,
            }))
        except Exception:
            pass


# ── Safety Guard ─────────────────────────────────────────────────

class SafetyGuard:
    """Checks commands against safety rules.

    Usage:
        guard = SafetyGuard()
        guard.enable_careful()

        # Before executing a command:
        blocked, warning = guard.check("rm -rf /tmp/data")
        if blocked:
            print(f"🛑 BLOCKED: {warning}")
            # Ask user for confirmation before proceeding
    """

    def __init__(self):
        self.state = GuardState()
        self.state.load()

    # ── Mode toggles ─────────────────────────────────────────

    def enable_careful(self):
        self.state.careful_enabled = True
        self.state.save()

    def disable_careful(self):
        self.state.careful_enabled = False
        self.state.save()

    def enable_freeze(self, directory: str):
        self.state.freeze_enabled = True
        self.state.freeze_directory = os.path.abspath(directory)
        self.state.save()

    def disable_freeze(self):
        self.state.freeze_enabled = False
        self.state.freeze_directory = ""
        self.state.save()

    def enable_guard(self, directory: str = ""):
        """Enable both careful + freeze."""
        self.enable_careful()
        if directory:
            self.enable_freeze(directory)

    def disable_guard(self):
        self.disable_careful()
        self.disable_freeze()

    # ── Check commands ───────────────────────────────────────

    def check_command(self, command: str) -> Tuple[bool, str]:
        """Check a shell command for dangerous patterns.

        Returns (is_blocked, warning_message).
        is_blocked is True if the command should NOT proceed without confirmation.
        """
        if not self.state.careful_enabled:
            return False, ""

        warnings = []
        for name, rule in DANGEROUS_PATTERNS.items():
            if re.search(rule["pattern"], command, re.IGNORECASE):
                severity = rule["severity"]
                icon = {"critical": "🛑", "high": "⚠️", "medium": "🟡", "low": "ℹ️"}.get(severity, "⚠️")
                warnings.append(f"{icon} [{severity.upper()}] {rule['description']}")

        if warnings:
            return True, "\n".join(warnings)
        return False, ""

    def check_file_edit(self, filepath: str) -> Tuple[bool, str]:
        """Check if a file edit is allowed (freeze mode).

        Returns (is_blocked, warning_message).
        """
        if not self.state.freeze_enabled or not self.state.freeze_directory:
            return False, ""

        abs_path = os.path.abspath(filepath)
        freeze_dir = self.state.freeze_directory

        if not abs_path.startswith(freeze_dir):
            return True, (
                f"🧊 FROZEN: Edit blocked outside freeze directory.\n"
                f"  Attempted: {abs_path}\n"
                f"  Allowed: {freeze_dir}/\n"
                f"  Use /unfreeze to remove restriction."
            )
        return False, ""

    def get_status(self) -> str:
        lines = ["Safety Guard Status", "=" * 40]
        lines.append(f"  /careful: {'🟢 ON' if self.state.careful_enabled else '⚪ OFF'}")
        lines.append(f"  /freeze:  {'🧊 ON' if self.state.freeze_enabled else '⚪ OFF'}")
        if self.state.freeze_enabled:
            lines.append(f"  Frozen to: {self.state.freeze_directory}")
        return "\n".join(lines)


# ── Singleton ────────────────────────────────────────────────────

_guard: Optional[SafetyGuard] = None


def get_guard() -> SafetyGuard:
    global _guard
    if _guard is None:
        _guard = SafetyGuard()
    return _guard
