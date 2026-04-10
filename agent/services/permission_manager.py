"""
Permission Manager — Enhanced permission system with risk classification.

Modes:
  - normal: Ask user for write/execute, auto-approve reads
  - auto_accept: Auto-approve writes and executes, ask for destructive
  - accept_edits: Auto-approve file edits specifically, ask for other writes
  - plan: Read-only mode, block all writes/executes
  - bypass: Allow everything (dangerous, for testing only)

Risk Classification:
  - LOW: Read-only operations, info queries → always auto-approve
  - MEDIUM: File writes, code edits → mode-dependent
  - HIGH: Shell execution, git operations → ask in most modes
  - CRITICAL: Destructive operations → always ask (except bypass)

Decision Tracking:
  - Audit trail of all permission decisions
  - Session memory for "allow once" → "allow for session" escalation
"""

import os
import json
import time
import logging
from enum import Enum
from typing import Dict, Optional, Tuple, List, Any
from pathlib import Path

logger = logging.getLogger(__name__)


class PermissionMode(Enum):
    """Permission modes controlling tool approval behavior."""
    NORMAL = "normal"
    AUTO_ACCEPT = "auto_accept"
    ACCEPT_EDITS = "accept_edits"
    DONT_ASK = "dont_ask"       # Auto-approve everything except CRITICAL
    PLAN = "plan"
    BYPASS = "bypass"


class RiskLevel(Enum):
    """Three-tier risk classification for tool actions."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class PermissionDecision(Enum):
    """Result of a permission check."""
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"
    PASSTHROUGH = "passthrough"     # Allow and pass to next handler unchanged


# Map PermissionLevel → RiskLevel
_PERMISSION_TO_RISK = {
    'read_only': RiskLevel.LOW,
    'write': RiskLevel.MEDIUM,
    'execute': RiskLevel.HIGH,
    'destructive': RiskLevel.CRITICAL,
}


class PermissionManager:
    """Manages tool permission decisions with mode-based policies.

    Usage:
        pm = PermissionManager(mode=PermissionMode.NORMAL)
        decision = pm.check_permission('Bash', 'execute', {'command': 'ls'})
        if decision == PermissionDecision.ASK:
            # prompt user
            pm.record_decision('Bash', user_allowed=True)
    """

    def __init__(self, mode: PermissionMode = PermissionMode.NORMAL):
        self._mode = mode
        self._session_decisions: Dict[str, bool] = {}  # tool_name → allowed
        self._decision_log: List[Dict[str, Any]] = []
        self._audit_path = Path(os.path.expanduser('~/.neomind/permission_audit.jsonl'))

        # Permission rules — per-tool allow/deny/ask patterns
        self._rules: List[Dict[str, Any]] = []  # [{tool_pattern, behavior, content_pattern?}]
        self._load_rules()

        # Denial tracking with fallback
        self._consecutive_denials: int = 0
        self._total_denials: int = 0
        self.CONSECUTIVE_DENIAL_LIMIT = 3
        self.TOTAL_DENIAL_LIMIT = 20
        self._denial_fallback_active = False

    @property
    def mode(self) -> PermissionMode:
        return self._mode

    @mode.setter
    def mode(self, value: PermissionMode):
        self._mode = value
        # Clear session decisions on mode change
        self._session_decisions.clear()

    # ── Permission Rules ──────────────────────────────────────────

    def _load_rules(self):
        """Load permission rules from config file."""
        rules_path = Path(os.path.expanduser('~/.neomind/permission_rules.json'))
        try:
            if rules_path.exists():
                with open(rules_path) as f:
                    self._rules = json.load(f)
        except Exception:
            self._rules = []

    def _save_rules(self):
        """Persist rules to config file."""
        rules_path = Path(os.path.expanduser('~/.neomind/permission_rules.json'))
        try:
            rules_path.parent.mkdir(parents=True, exist_ok=True)
            with open(rules_path, 'w') as f:
                json.dump(self._rules, f, indent=2)
        except Exception:
            pass

    def add_rule(self, tool_pattern: str, behavior: str,
                 content_pattern: str = None):
        """Add a permission rule.

        Args:
            tool_pattern: Glob-style tool name pattern (e.g., 'Bash', 'mcp__*')
            behavior: 'allow', 'deny', or 'ask'
            content_pattern: Optional content match (e.g., 'npm test')
        """
        rule = {'tool_pattern': tool_pattern, 'behavior': behavior}
        if content_pattern:
            rule['content_pattern'] = content_pattern
        self._rules.append(rule)
        self._save_rules()

    def remove_rule(self, index: int):
        """Remove a rule by index."""
        if 0 <= index < len(self._rules):
            self._rules.pop(index)
            self._save_rules()

    def list_rules(self) -> List[Dict[str, Any]]:
        """Return all permission rules."""
        return list(self._rules)

    def _match_rule(self, tool_name: str, params: Dict[str, Any] = None) -> Optional[str]:
        """Check if any rule matches the tool name and return behavior.

        Rules are checked in order; first match wins.
        """
        import fnmatch
        for rule in self._rules:
            pattern = rule.get('tool_pattern', '')
            if fnmatch.fnmatch(tool_name, pattern):
                # Check content pattern if specified
                content_pattern = rule.get('content_pattern')
                if content_pattern and params:
                    # Check command or path parameters
                    cmd = params.get('command', params.get('path', ''))
                    if content_pattern not in cmd:
                        continue
                return rule['behavior']
        return None

    def classify_risk(self, tool_name: str, permission_level: str,
                      params: Dict[str, Any] = None) -> RiskLevel:
        """Classify the risk level of a tool action.

        Goes beyond static permission_level by examining tool parameters.
        For example, ``echo hello`` should be LOW risk while ``rm -rf /``
        should be CRITICAL, even though both are Bash/execute.
        """
        base_risk = _PERMISSION_TO_RISK.get(permission_level, RiskLevel.MEDIUM)

        # Refine risk based on specific patterns
        if params:
            command = params.get('command', '')
            path = params.get('path', '')

            # Bash commands with dangerous patterns → CRITICAL
            if tool_name in ('Bash', 'PowerShell') and command:
                dangerous_patterns = [
                    'rm -rf', 'rm -fr', 'git push --force', 'git reset --hard',
                    'drop table', 'drop database', 'sudo ', 'chmod 777',
                    'dd if=', 'mkfs', '> /dev/',
                ]
                cmd_lower = command.lower().strip()
                if any(p in cmd_lower for p in dangerous_patterns):
                    return RiskLevel.CRITICAL

                # Safe read-only / informational commands → LOW
                safe_prefixes = [
                    'echo ', 'echo\t', 'printf ', 'cat ', 'head ', 'tail ',
                    'ls', 'pwd', 'date', 'whoami', 'uname', 'hostname',
                    'which ', 'type ', 'file ', 'wc ', 'du ', 'df ',
                    'env', 'printenv', 'id', 'uptime', 'free ',
                    'git status', 'git log', 'git diff', 'git branch',
                    'git show', 'git remote', 'git tag',
                    'python --version', 'python3 --version', 'node --version',
                    'npm --version', 'pip --version', 'pip3 --version',
                    'cargo --version', 'rustc --version', 'go version',
                    'java -version', 'javac -version',
                ]
                # Exact-match safe commands (no arguments)
                safe_exact = [
                    'ls', 'pwd', 'date', 'whoami', 'uname', 'hostname',
                    'env', 'printenv', 'id', 'uptime',
                ]
                if cmd_lower in safe_exact or any(cmd_lower.startswith(p) for p in safe_prefixes):
                    # But not if piped to something dangerous
                    if '|' not in command and ';' not in command and '&&' not in command:
                        return RiskLevel.LOW

                # Moderate commands (build/test, non-destructive writes) → MEDIUM
                moderate_prefixes = [
                    'python ', 'python3 ', 'node ', 'npm ', 'pip ',
                    'pytest', 'cargo ', 'go ', 'make', 'grep ', 'find ',
                    'sed ', 'awk ', 'sort ', 'uniq ', 'cut ', 'tr ',
                    'git add', 'git commit', 'git checkout',
                    'mkdir ', 'touch ', 'cp ', 'mv ',
                ]
                if any(cmd_lower.startswith(p) for p in moderate_prefixes):
                    if '|' not in command and ';' not in command:
                        return RiskLevel.MEDIUM

            # Writing to sensitive paths → CRITICAL
            if path and tool_name in ('Write', 'Edit'):
                sensitive = ['.env', '.ssh', '.gitconfig', '.bashrc', '.zshrc']
                if any(s in path for s in sensitive):
                    return RiskLevel.CRITICAL

        return base_risk

    def check_permission(self, tool_name: str, permission_level: str,
                         params: Dict[str, Any] = None) -> PermissionDecision:
        """Check if a tool action should be allowed, asked, or denied.

        Args:
            tool_name: Name of the tool
            permission_level: The tool's static permission level
            params: Tool parameters for risk analysis

        Returns:
            PermissionDecision
        """
        risk = self.classify_risk(tool_name, permission_level, params)

        # Check permission rules first (user-defined overrides)
        rule_behavior = self._match_rule(tool_name, params)
        if rule_behavior:
            rule_decision = {
                'allow': PermissionDecision.ALLOW,
                'deny': PermissionDecision.DENY,
                'ask': PermissionDecision.ASK,
            }.get(rule_behavior)
            if rule_decision:
                self._log_decision(tool_name, permission_level, risk, rule_decision, params)
                return rule_decision

        # Denial fallback: if too many denials, force ASK for everything
        if self._denial_fallback_active and risk != RiskLevel.LOW:
            decision = PermissionDecision.ASK
            self._log_decision(tool_name, permission_level, risk, decision, params)
            return decision

        # Mode-based decision matrix
        if self._mode == PermissionMode.BYPASS:
            decision = PermissionDecision.ALLOW

        elif self._mode == PermissionMode.PLAN:
            if risk == RiskLevel.LOW:
                decision = PermissionDecision.ALLOW
            else:
                decision = PermissionDecision.DENY

        elif self._mode == PermissionMode.DONT_ASK:
            if risk == RiskLevel.CRITICAL:
                decision = PermissionDecision.ASK
            else:
                decision = PermissionDecision.ALLOW

        elif self._mode == PermissionMode.AUTO_ACCEPT:
            if risk == RiskLevel.CRITICAL:
                decision = PermissionDecision.ASK
            else:
                decision = PermissionDecision.ALLOW

        elif self._mode == PermissionMode.ACCEPT_EDITS:
            if risk == RiskLevel.LOW:
                decision = PermissionDecision.ALLOW
            elif tool_name in ('Edit', 'Write', 'NotebookEdit'):
                decision = PermissionDecision.ALLOW
            elif risk == RiskLevel.CRITICAL:
                decision = PermissionDecision.ASK
            else:
                decision = PermissionDecision.ASK

        else:  # NORMAL
            if risk == RiskLevel.LOW:
                decision = PermissionDecision.ALLOW
            elif tool_name in self._session_decisions:
                decision = (PermissionDecision.ALLOW
                            if self._session_decisions[tool_name]
                            else PermissionDecision.DENY)
            else:
                decision = PermissionDecision.ASK

        # Log the decision
        self._log_decision(tool_name, permission_level, risk, decision, params)

        return decision

    def explain_permission(self, tool_name: str, permission_level: str,
                           params: Dict[str, Any] = None) -> str:
        """Generate a human-readable explanation of why permission is needed.

        Returns a short explanation suitable for showing to the user when
        they are prompted for permission.
        """
        risk = self.classify_risk(tool_name, permission_level, params)

        # Build explanation based on tool + risk
        explanations = {
            'Bash': 'execute a shell command on your system',
            'PowerShell': 'execute a PowerShell command on your system',
            'Write': 'create or overwrite a file',
            'Edit': 'modify an existing file',
            'NotebookEdit': 'modify a Jupyter notebook',
            'SelfEditor': 'modify the agent\'s own source code',
            'TaskStop': 'stop a running background task',
            'Workflow': 'execute a workflow script',
            'CronCreate': 'create a scheduled task',
            'CronDelete': 'delete a scheduled task',
            'RemoteTrigger': 'fire a remote webhook trigger',
            'Snip': 'save a snippet to disk',
            'GitCommit': 'create a git commit',
            'GitPR': 'create or interact with a pull request',
        }

        action = explanations.get(tool_name, f'use the {tool_name} tool')

        # Risk-specific warnings
        risk_warnings = {
            RiskLevel.LOW: '',
            RiskLevel.MEDIUM: ' This modifies files in your workspace.',
            RiskLevel.HIGH: ' This executes code on your system.',
            RiskLevel.CRITICAL: ' ⚠️ This is a potentially destructive operation.',
        }
        warning = risk_warnings.get(risk, '')

        # Parameter-specific detail
        detail = ''
        if params:
            if 'command' in params:
                cmd = params['command'][:80]
                detail = f'\n  Command: {cmd}'
            elif 'path' in params:
                detail = f'\n  File: {params["path"]}'
            elif 'name' in params and tool_name in ('CronCreate', 'CronDelete', 'Workflow'):
                detail = f'\n  Name: {params["name"]}'

        return f"Permission needed to {action}.{warning}{detail}\nRisk level: {risk.value.upper()}"

    def record_decision(self, tool_name: str, user_allowed: bool,
                        remember_for_session: bool = False):
        """Record a user's permission decision with denial tracking.

        After CONSECUTIVE_DENIAL_LIMIT consecutive denials or TOTAL_DENIAL_LIMIT
        total denials, the system falls back to always-prompt mode to prevent
        the agent from being stuck in a denial loop.

        Args:
            tool_name: Tool that was asked about
            user_allowed: Whether the user allowed it
            remember_for_session: If True, apply to all future calls of this tool
        """
        if remember_for_session:
            self._session_decisions[tool_name] = user_allowed

        # Track denials for fallback mechanism
        if user_allowed:
            self._consecutive_denials = 0  # Reset on success
        else:
            self._consecutive_denials += 1
            self._total_denials += 1

            # Check if denial limits exceeded
            if (self._consecutive_denials >= self.CONSECUTIVE_DENIAL_LIMIT or
                    self._total_denials >= self.TOTAL_DENIAL_LIMIT):
                self._denial_fallback_active = True
                logger.warning(
                    f"Permission denial fallback activated: "
                    f"{self._consecutive_denials} consecutive, "
                    f"{self._total_denials} total"
                )

    def _log_decision(self, tool_name: str, permission_level: str,
                      risk: RiskLevel, decision: PermissionDecision,
                      params: Dict[str, Any] = None):
        """Log a permission decision to the audit trail."""
        entry = {
            'timestamp': time.time(),
            'tool': tool_name,
            'permission_level': permission_level,
            'risk': risk.value,
            'decision': decision.value,
            'mode': self._mode.value,
            'params_summary': str(params)[:200] if params else None,
        }
        self._decision_log.append(entry)

        # Persist to file (non-blocking)
        try:
            self._audit_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._audit_path, 'a') as f:
                f.write(json.dumps(entry) + '\n')
        except Exception:
            pass

    @property
    def decision_log(self) -> List[Dict[str, Any]]:
        """Return the session's permission decision log."""
        return list(self._decision_log)

    def get_stats(self) -> Dict[str, int]:
        """Return permission decision statistics for the session."""
        stats = {'allow': 0, 'ask': 0, 'deny': 0}
        for entry in self._decision_log:
            d = entry.get('decision', '')
            if d in stats:
                stats[d] += 1
        return stats
