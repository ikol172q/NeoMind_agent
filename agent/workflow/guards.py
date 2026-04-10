# agent/workflow/guards.py
"""
Safety Guards — /careful, /freeze, /guard commands.

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


# ── Extended Bash Security Validation (23 checks from Claude Code analysis) ──

BASH_SECURITY_CHECKS = {
    "incomplete_command": {
        "pattern": r"[|&;]\s*$",
        "description": "Incomplete command (trailing pipe/operator)",
        "severity": "medium",
    },
    "jq_system": {
        "pattern": r"\bjq\b.*\bsystem\s*\(",
        "description": "jq system() function call — can execute arbitrary commands",
        "severity": "critical",
    },
    "obfuscated_flags": {
        "pattern": r"\\x[0-9a-fA-F]{2}|\\[0-7]{3}|\\u[0-9a-fA-F]{4}",
        "description": "Obfuscated flag characters (hex/octal/unicode escapes)",
        "severity": "high",
    },
    "shell_metacharacters": {
        "pattern": r"[`]|;\s*\||&&\s*rm|;\s*cat\s+/etc/",
        "description": "Suspicious shell metacharacter combination",
        "severity": "high",
    },
    "dangerous_variables": {
        "pattern": r"\$\{?IFS\}?|\$\{?BASH_COMMAND\}?|\$\{?BASH_ENV\}?|\$\{?ENV\}?|\$\{?SHELLOPTS\}?|\$\{?BASHOPTS\}?",
        "description": "Dangerous shell variable access",
        "severity": "critical",
    },
    "command_substitution_nested": {
        "pattern": r"\$\(\s*\$\(|\$\(\s*`|`\s*\$\(",
        "description": "Nested command substitution",
        "severity": "high",
    },
    "process_substitution": {
        "pattern": r"<\(|>\(",
        "description": "Process substitution (potential data exfiltration)",
        "severity": "medium",
    },
    "ifs_injection": {
        "pattern": r"\bIFS\s*=",
        "description": "IFS variable injection",
        "severity": "critical",
    },
    "proc_environ": {
        "pattern": r"/proc/(self|[0-9]+)/(environ|cmdline|maps|fd)",
        "description": "Process environment/memory access",
        "severity": "critical",
    },
    "brace_expansion_attack": {
        "pattern": r"\{[0-9]+\.\.[0-9]+\}|\{[a-z]\.\.[a-z]\}",
        "description": "Brace expansion (potential DoS via large ranges)",
        "severity": "medium",
    },
    "control_characters": {
        "pattern": r"[\x00-\x08\x0e-\x1f\x7f]",
        "description": "Control characters in command",
        "severity": "high",
    },
    "unicode_whitespace": {
        "pattern": r"[\u00a0\u2000-\u200f\u2028\u2029\u202f\u205f\u3000\ufeff]",
        "description": "Unicode whitespace trick (invisible characters)",
        "severity": "high",
    },
    "comment_desync": {
        "pattern": r"#.*['\"]|['\"].*#",
        "description": "Quote/comment boundary mismatch (potential desync)",
        "severity": "medium",
    },
    "escaped_operators": {
        "pattern": r"\\;|\\&|\\[|]",
        "description": "Escaped shell operators (bypass attempt)",
        "severity": "medium",
    },
    "eval_exec": {
        "pattern": r"\beval\s+|exec\s+[0-9]|exec\s+-",
        "description": "Shell eval/exec command",
        "severity": "critical",
    },
    "xargs_exec": {
        "pattern": r"\bxargs\b.*(-I|--replace|sh\s+-c|bash\s+-c)",
        "description": "xargs with command execution",
        "severity": "high",
    },
    "curl_pipe": {
        "pattern": r"\bcurl\b.*\|\s*(bash|sh|python|perl|ruby)",
        "description": "curl piped to shell interpreter",
        "severity": "critical",
    },
    "wget_pipe": {
        "pattern": r"\bwget\b.*-O\s*-.*\|\s*(bash|sh|python)",
        "description": "wget piped to shell interpreter",
        "severity": "critical",
    },
    "env_override": {
        "pattern": r"\benv\b\s+\w+=.*\s+(bash|sh|python|perl|ruby|node)",
        "description": "Environment override with shell execution",
        "severity": "high",
    },
    "dd_raw_write": {
        "pattern": r"\bdd\b.*of=/dev/",
        "description": "Raw device write via dd",
        "severity": "critical",
    },
    "mkfs_format": {
        "pattern": r"\bmkfs\b|\bmke2fs\b|\bnewfs\b",
        "description": "Filesystem formatting command",
        "severity": "critical",
    },
    "crontab_modify": {
        "pattern": r"\bcrontab\s+(-e|-r|-l\s*>)",
        "description": "Crontab modification or export",
        "severity": "high",
    },
    "ssh_forward": {
        "pattern": r"\bssh\b.*(-L|-R|-D)\s+[0-9]",
        "description": "SSH port forwarding",
        "severity": "medium",
    },
}


SENSITIVE_SYSTEM_FILES = [
    '/etc/passwd', '/etc/shadow', '/etc/master.passwd', '/etc/sudoers',
    '/etc/security/passwd', '/etc/gshadow', '/etc/group',
]


def _check_protected_file_access(command: str) -> List[Tuple[str, str, str]]:
    """Detect bash commands that read/write protected credential/config files.

    Checks two categories:
    1. User credential files from SafetyManager.PROTECTED_FILES (relative to ~)
    2. Sensitive system files (absolute paths like /etc/passwd, /etc/shadow)

    Returns:
        List of (check_name, description, severity) for each match.
    """
    from agent.services.safety_service import SafetyManager

    findings = []
    home = os.path.expanduser('~')

    # --- Check user credential/config files (relative to $HOME) ---
    for pf in SafetyManager.PROTECTED_FILES:
        # Build variants: ~/.ssh/id_rsa, $HOME/.ssh/id_rsa, /Users/x/.ssh/id_rsa
        tilde_path = os.path.join('~', pf)
        home_var_path = os.path.join('$HOME', pf)
        abs_path = os.path.join(home, pf)

        for variant in (tilde_path, home_var_path, abs_path):
            # Escape for regex — match the literal path as a token boundary
            escaped = re.escape(variant)
            # Match if the path appears as a standalone token (not as substring of a longer path)
            if re.search(r'(?:^|\s|[;|&`"\'])' + escaped + r'(?:\s|$|[;|&`"\'])', command):
                findings.append((
                    'protected_file_access',
                    f'Access to protected file blocked: {pf}',
                    'critical',
                ))
                break  # Don't report same file multiple times

    # --- Check sensitive system files (absolute paths) ---
    for sf in SENSITIVE_SYSTEM_FILES:
        escaped = re.escape(sf)
        if re.search(r'(?:^|\s|[;|&`"\'])' + escaped + r'(?:\s|$|[;|&`"\'])', command):
            findings.append((
                'protected_file_access',
                f'Access to sensitive system file blocked: {sf}',
                'critical',
            ))

    return findings


def validate_bash_security(command: str) -> List[Tuple[str, str, str]]:
    """Run extended bash security checks against a command.

    Uses both regex pattern matching and shlex-based command chain analysis.

    Returns:
        List of (check_name, description, severity) for each match.
    """
    findings = []

    # Phase 0: Protected file access checks
    findings.extend(_check_protected_file_access(command))

    # Phase 1: Regex pattern checks
    for name, check in BASH_SECURITY_CHECKS.items():
        if re.search(check["pattern"], command):
            findings.append((name, check["description"], check["severity"]))

    # Phase 2: shlex-based command chain analysis
    try:
        import shlex
        import signal

        # Timeout protection (50ms) to prevent hangs on adversarial input
        def _timeout_handler(signum, frame):
            raise TimeoutError("Bash parsing timeout")

        old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
        signal.setitimer(signal.ITIMER_REAL, 0.05)  # 50ms

        try:
            # Split on command chain operators
            chain_ops = [';', '&&', '||']
            segments = [command]
            for op in chain_ops:
                new_segments = []
                for seg in segments:
                    new_segments.extend(seg.split(op))
                segments = new_segments

            # Check each command segment
            for seg in segments:
                seg = seg.strip()
                if not seg:
                    continue
                # Handle pipes
                pipe_parts = seg.split('|')
                for part in pipe_parts:
                    part = part.strip()
                    if not part:
                        continue
                    try:
                        tokens = shlex.split(part)
                        if tokens:
                            cmd = tokens[0]
                            # Check for code execution via interpreters
                            if cmd in ('python', 'python3', 'node', 'ruby', 'perl', 'php') and '-c' in tokens:
                                findings.append(('inline_code_exec', f'{cmd} -c inline execution', 'high'))
                    except ValueError:
                        # Unmatched quotes — could be injection attempt
                        findings.append(('unmatched_quotes', 'Unmatched quotes in command', 'medium'))
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)  # Cancel timer
            signal.signal(signal.SIGALRM, old_handler)

    except (TimeoutError, AttributeError):
        # SIGALRM not available on Windows, or parsing timed out
        pass
    except Exception:
        pass  # Non-fatal — regex checks already ran

    return findings


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
        """Check a shell command for dangerous patterns and security issues.

        Runs both DANGEROUS_PATTERNS (destructive ops) and
        BASH_SECURITY_CHECKS (injection/evasion attacks).

        Returns (is_blocked, warning_message).
        is_blocked is True if the command should NOT proceed without confirmation.
        """
        warnings = []

        # Always run extended bash security checks (regardless of careful mode)
        security_findings = validate_bash_security(command)
        for name, desc, severity in security_findings:
            if severity in ("critical", "high"):
                icon = {"critical": "🛑", "high": "⚠️"}.get(severity, "⚠️")
                warnings.append(f"{icon} [SECURITY-{severity.upper()}] {desc}")

        # Dangerous pattern checks only in careful mode
        if self.state.careful_enabled:
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
