"""Permission policy and approval binding.

The invariants here are the ones the baseline audit found violated, restated so
they are checkable rather than aspirational:

1. No valid approval means no execution. Silence is denial.
2. ASK with no interactive broker resolves to DENY — a non-interactive surface
   cannot "fall through" to running the tool.
3. An approval is bound to a fingerprint of the exact call. Approving `Read
   a.txt` never authorizes `Read ../../.ssh/id_rsa`.
4. A session rule names a tool and a target pattern. There is no global
   "auto-approved" flag; the CLI's old one approved every later write in the
   session after a single "always".
5. Destructive and CRITICAL-risk calls stay interactive even under auto-accept,
   unless the operator selected a separately named bypass.
6. A broker that raises, disconnects, times out, or is cancelled denies.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Mapping, Optional, Tuple

logger = logging.getLogger(__name__)


class Decision(Enum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


class Scope(Enum):
    """How far an approval reaches.

    ONCE is the only scope that needs no pattern. SESSION_PATTERN must name a
    tool and a target glob, which is what keeps "always allow" from becoming
    "allow everything for the rest of the session".
    """

    ONCE = "once"
    SESSION_PATTERN = "session_pattern"


def fingerprint(tool_name: str, params: Mapping[str, Any], working_dir: str = "") -> str:
    """Stable hash of the exact call being authorized.

    Sorted keys and a canonical separator so that equal calls hash equal
    regardless of dict ordering. Raises on non-serializable params rather than
    silently hashing a repr — an un-fingerprintable call must fail closed at
    the caller, not be approved against an unstable string.
    """
    payload = json.dumps(
        {"tool": tool_name, "params": params, "cwd": working_dir},
        sort_keys=True,
        separators=(",", ":"),
        default=None,
    )
    if "null" in payload and params and any(
        not _json_safe(v) for v in params.values()
    ):
        raise TypeError("tool params are not canonically serializable")
    return hashlib.sha256(payload.encode()).hexdigest()


def _json_safe(value: Any) -> bool:
    try:
        json.dumps(value)
        return True
    except (TypeError, ValueError):
        return False


@dataclass(frozen=True)
class SessionRule:
    """An operator-granted standing approval, always scoped."""

    tool_name: str
    target_pattern: str = "*"

    def matches(self, tool_name: str, params: Mapping[str, Any]) -> bool:
        if tool_name != self.tool_name:
            return False
        if self.target_pattern == "*":
            return True
        target = _primary_target(params)
        return bool(target) and fnmatch.fnmatch(str(target), self.target_pattern)


def _primary_target(params: Mapping[str, Any]) -> Optional[str]:
    """The parameter a rule is scoped against.

    Kept explicit rather than "first string param" so a rule for a path cannot
    silently start matching a command string when a tool's schema changes.
    """
    for key in ("path", "file_path", "filename", "command", "pattern", "url"):
        if key in params and isinstance(params[key], str):
            return params[key]
    return None


@dataclass(frozen=True)
class CapabilitySnapshot:
    """The tools a session may use — for prompting AND for execution.

    One snapshot feeds both so they cannot drift. When they drift, the model is
    offered tools the executor will refuse, and it burns turns retrying.

    `allowed` of None means "every registered tool"; an explicit empty set means
    no tools, which is what a non-interactive remote surface should start from.
    """

    allowed: Optional[frozenset] = None

    def permits(self, tool_name: str) -> bool:
        return self.allowed is None or tool_name in self.allowed

    @classmethod
    def unrestricted(cls) -> "CapabilitySnapshot":
        return cls(allowed=None)

    @classmethod
    def only(cls, *tool_names: str) -> "CapabilitySnapshot":
        return cls(allowed=frozenset(tool_names))


@dataclass
class PermissionPolicy:
    """Turns a proposed call into ALLOW / ASK / DENY.

    `interactive` is a property of the surface, not a preference: headless,
    Telegram and cron have no one to ask, so ASK must resolve to DENY there.
    """

    capabilities: CapabilitySnapshot = field(default_factory=CapabilitySnapshot.unrestricted)
    interactive: bool = False
    auto_approve_reads: bool = True
    auto_accept: bool = False
    allow_destructive_bypass: bool = False
    session_rules: list = field(default_factory=list)

    def evaluate(
        self,
        tool_name: str,
        permission_level: Optional[str],
        params: Mapping[str, Any],
        risk: Optional[str] = None,
    ) -> Tuple[Decision, str]:
        """Return (decision, reason). Reason is for audit and display."""

        if not self.capabilities.permits(tool_name):
            return Decision.DENY, "tool not in session capability snapshot"

        # Unknown or missing classification is treated as dangerous. The
        # baseline denied only known-bad levels, so a tool whose level was
        # missing or a plain string sailed through.
        level = (permission_level or "").strip().lower()
        if level not in _KNOWN_LEVELS:
            return Decision.DENY, f"unclassified permission level: {permission_level!r}"

        normalized_risk = (risk or "").strip().upper()
        is_critical = normalized_risk == "CRITICAL" or level == "destructive"

        if level == "read_only":
            if self.auto_approve_reads:
                return Decision.ALLOW, "read-only"
            return self._ask_or_deny("read-only, auto-approve disabled")

        # Order matters: the standing rule is checked before auto_accept so a
        # narrowly scoped grant is what the audit records, not a blanket one.
        for rule in self.session_rules:
            if rule.matches(tool_name, params):
                if is_critical and not self.allow_destructive_bypass:
                    return self._ask_or_deny("critical action; session rule does not cover it")
                return Decision.ALLOW, f"session rule {rule.tool_name}:{rule.target_pattern}"

        if is_critical and not self.allow_destructive_bypass:
            # Critical stays interactive even under auto-accept. The CLI used to
            # return ALLOW here before risk was ever classified.
            return self._ask_or_deny("critical action requires explicit confirmation")

        if self.auto_accept:
            return Decision.ALLOW, "auto-accept mode"

        return self._ask_or_deny(f"{level} requires confirmation")

    def _ask_or_deny(self, reason: str) -> Tuple[Decision, str]:
        if self.interactive:
            return Decision.ASK, reason
        return Decision.DENY, f"{reason}; no interactive broker"


_KNOWN_LEVELS = frozenset({"read_only", "write", "execute", "destructive"})


@dataclass(frozen=True)
class Approval:
    """A granted decision, bound to one exact call."""

    request_id: str
    fingerprint: str
    scope: Scope = Scope.ONCE
    rule: Optional[SessionRule] = None


class PermissionBrokerError(Exception):
    """Raised when a broker fails. Callers must treat this as denial."""


def redact_params(params: Mapping[str, Any], limit: int = 200) -> str:
    """Bounded, secret-free preview for the audit trail.

    The existing permission audit stored `str(params)[:200]`, which happily
    persisted whatever credential was passed as an argument. Audit records must
    survive being read by someone who should not see the secrets.
    """
    from agent.logging.secret_redaction import redact_secrets

    try:
        rendered = json.dumps(params, sort_keys=True, default=repr)
    except (TypeError, ValueError):
        rendered = repr(params)
    return redact_secrets(rendered)[:limit]
