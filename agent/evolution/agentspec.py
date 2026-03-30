"""NeoMind AgentSpec — Declarative Safety Specification DSL

Inspired by AgentSpec (ICSE 2026, arxiv 2503.18666): a declarative language
for specifying and enforcing agent safety constraints.

Our implementation: a Python-native DSL using dataclasses and a rule engine.
Rules are defined as trigger-predicate-enforcement triples:
  - Trigger: when to check (pre_edit, post_edit, runtime, periodic)
  - Predicate: condition to evaluate (Python callable or AST pattern)
  - Enforcement: action on violation (block, warn, log, revert)

Research source: Round 1 + Round 4 safety research.

No external dependencies — stdlib only.
"""

import ast
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class TriggerPoint(Enum):
    """When a safety rule should be checked."""
    PRE_EDIT = "pre_edit"       # Before self-edit is applied
    POST_EDIT = "post_edit"     # After self-edit but before commit
    RUNTIME = "runtime"         # During normal operation
    PERIODIC = "periodic"       # On scheduled health checks
    ON_OUTPUT = "on_output"     # Before sending response to user


class Enforcement(Enum):
    """What to do when a rule is violated."""
    BLOCK = "block"     # Prevent the action entirely
    WARN = "warn"       # Allow but log warning + alert
    LOG = "log"         # Just log for monitoring
    REVERT = "revert"   # Revert to previous state


@dataclass
class SafetyRule:
    """A single safety specification rule.

    Example:
        SafetyRule(
            name="no_remove_logging",
            description="Logging statements must never be removed by self-edit",
            trigger=TriggerPoint.PRE_EDIT,
            predicate=lambda ctx: ctx.get("logging_count_after") >= ctx.get("logging_count_before"),
            enforcement=Enforcement.BLOCK,
            severity=9,
        )
    """
    name: str
    description: str
    trigger: TriggerPoint
    predicate: Callable[[Dict[str, Any]], bool]  # Returns True if SAFE
    enforcement: Enforcement
    severity: int = 5  # 1-10, higher = more critical
    tags: List[str] = field(default_factory=list)
    enabled: bool = True
    violation_count: int = 0
    last_violation: Optional[str] = None


@dataclass
class RuleViolation:
    """Record of a safety rule violation."""
    rule_name: str
    description: str
    enforcement: str
    severity: int
    context: Dict[str, Any]
    ts: str
    blocked: bool


class AgentSpec:
    """Safety specification engine — evaluates rules against context.

    Usage:
        spec = AgentSpec()
        spec.add_rule(SafetyRule(...))

        # Before self-edit
        violations = spec.check(TriggerPoint.PRE_EDIT, {
            "file": "learnings.py",
            "old_code": old_src,
            "new_code": new_src,
        })

        if any(v.blocked for v in violations):
            reject_edit()
    """

    def __init__(self):
        self._rules: List[SafetyRule] = []
        self._violations: List[RuleViolation] = []
        self._load_builtin_rules()

    def add_rule(self, rule: SafetyRule) -> None:
        """Register a safety rule."""
        # Check for duplicate names
        existing = {r.name for r in self._rules}
        if rule.name in existing:
            logger.warning(f"Overwriting existing rule: {rule.name}")
            self._rules = [r for r in self._rules if r.name != rule.name]
        self._rules.append(rule)
        logger.debug(f"Registered safety rule: {rule.name} ({rule.trigger.value})")

    def remove_rule(self, name: str) -> bool:
        """Remove a rule by name. Returns True if found and removed."""
        before = len(self._rules)
        self._rules = [r for r in self._rules if r.name != name]
        return len(self._rules) < before

    def check(self, trigger: TriggerPoint,
              context: Dict[str, Any]) -> List[RuleViolation]:
        """Evaluate all rules matching a trigger point against context.

        Args:
            trigger: Which trigger point we're at
            context: Dict of contextual data for predicate evaluation

        Returns:
            List of violations (empty if all rules pass)
        """
        violations = []
        applicable = [r for r in self._rules if r.trigger == trigger and r.enabled]

        for rule in applicable:
            try:
                is_safe = rule.predicate(context)
                if not is_safe:
                    violation = RuleViolation(
                        rule_name=rule.name,
                        description=rule.description,
                        enforcement=rule.enforcement.value,
                        severity=rule.severity,
                        context={k: str(v)[:200] for k, v in context.items()},
                        ts=datetime.now(timezone.utc).isoformat(),
                        blocked=(rule.enforcement == Enforcement.BLOCK),
                    )
                    violations.append(violation)
                    rule.violation_count += 1
                    rule.last_violation = violation.ts

                    if rule.enforcement == Enforcement.BLOCK:
                        logger.error(
                            f"SAFETY BLOCK: {rule.name} — {rule.description}"
                        )
                    elif rule.enforcement == Enforcement.WARN:
                        logger.warning(
                            f"SAFETY WARN: {rule.name} — {rule.description}"
                        )
                    else:
                        logger.info(
                            f"SAFETY LOG: {rule.name} — {rule.description}"
                        )
            except Exception as e:
                logger.error(f"Rule {rule.name} evaluation error: {e}")

        self._violations.extend(violations)
        # Keep violation history bounded
        if len(self._violations) > 1000:
            self._violations = self._violations[-500:]

        return violations

    def get_rules(self, trigger: Optional[TriggerPoint] = None) -> List[Dict]:
        """Get all rules, optionally filtered by trigger."""
        rules = self._rules if trigger is None else [
            r for r in self._rules if r.trigger == trigger
        ]
        return [
            {
                "name": r.name,
                "description": r.description,
                "trigger": r.trigger.value,
                "enforcement": r.enforcement.value,
                "severity": r.severity,
                "tags": r.tags,
                "enabled": r.enabled,
                "violation_count": r.violation_count,
            }
            for r in rules
        ]

    def get_violation_history(self, limit: int = 50) -> List[Dict]:
        """Get recent violations."""
        recent = self._violations[-limit:]
        return [
            {
                "rule": v.rule_name,
                "enforcement": v.enforcement,
                "severity": v.severity,
                "blocked": v.blocked,
                "ts": v.ts,
            }
            for v in reversed(recent)
        ]

    def get_stats(self) -> Dict[str, Any]:
        """Get safety specification statistics."""
        return {
            "total_rules": len(self._rules),
            "enabled_rules": sum(1 for r in self._rules if r.enabled),
            "total_violations": len(self._violations),
            "blocked_count": sum(1 for v in self._violations if v.blocked),
            "rules_by_trigger": {
                tp.value: sum(1 for r in self._rules if r.trigger == tp)
                for tp in TriggerPoint
            },
            "top_violated": sorted(
                [{"name": r.name, "count": r.violation_count}
                 for r in self._rules if r.violation_count > 0],
                key=lambda x: x["count"],
                reverse=True,
            )[:10],
        }

    # ── Built-in Rules ─────────────────────────────────

    def _load_builtin_rules(self) -> None:
        """Load NeoMind's constitutional safety rules as AgentSpec rules."""

        # Rule 1: No modifying safety-critical files
        self.add_rule(SafetyRule(
            name="immutable_safety_files",
            description="Safety-critical files (self_edit.py, health_monitor.py, watchdog.py, agentspec.py) cannot be modified by self-edit",
            trigger=TriggerPoint.PRE_EDIT,
            predicate=lambda ctx: ctx.get("target_file", "") not in {
                "self_edit.py", "health_monitor.py", "watchdog.py", "agentspec.py",
            },
            enforcement=Enforcement.BLOCK,
            severity=10,
            tags=["constitutional", "immutability"],
        ))

        # Rule 2: No disabling safety checks or logging
        self.add_rule(SafetyRule(
            name="no_disable_safety",
            description="Code must not disable safety checks, logging, or monitoring",
            trigger=TriggerPoint.PRE_EDIT,
            predicate=lambda ctx: not _contains_safety_disable(ctx.get("new_code", "")),
            enforcement=Enforcement.BLOCK,
            severity=10,
            tags=["constitutional", "safety"],
        ))

        # Rule 3: No reduction in safety patterns
        self.add_rule(SafetyRule(
            name="no_safety_regression",
            description="try/except, logging, assert, and if-guard counts must not decrease",
            trigger=TriggerPoint.POST_EDIT,
            predicate=lambda ctx: _check_safety_pattern_counts(
                ctx.get("old_code", ""), ctx.get("new_code", "")
            ),
            enforcement=Enforcement.BLOCK,
            severity=9,
            tags=["constitutional", "regression"],
        ))

        # Rule 4: No unauthorized network access
        self.add_rule(SafetyRule(
            name="network_allowlist",
            description="Network calls must only target allowlisted domains",
            trigger=TriggerPoint.PRE_EDIT,
            predicate=lambda ctx: _check_network_allowlist(
                ctx.get("new_code", ""),
                {"api.deepseek.com", "api.openai.com", "api.telegram.org", "finnhub.io",
                 "api.coingecko.com", "api.stlouisfed.org", "newsapi.org"}
            ),
            enforcement=Enforcement.BLOCK,
            severity=8,
            tags=["constitutional", "network"],
        ))

        # Rule 5: Memory increase limit
        self.add_rule(SafetyRule(
            name="memory_limit",
            description="Self-edit must not increase memory usage by >10MB",
            trigger=TriggerPoint.POST_EDIT,
            predicate=lambda ctx: ctx.get("memory_delta_mb", 0) <= 10,
            enforcement=Enforcement.BLOCK,
            severity=7,
            tags=["constitutional", "resources"],
        ))

        # Rule 6: Git reversibility
        self.add_rule(SafetyRule(
            name="git_reversible",
            description="Every self-edit must be reversible via git revert",
            trigger=TriggerPoint.PRE_EDIT,
            predicate=lambda ctx: ctx.get("git_tracked", True),
            enforcement=Enforcement.WARN,
            severity=6,
            tags=["constitutional", "reversibility"],
        ))

        # Rule 7: No relaxing rate limiter or compliance
        self.add_rule(SafetyRule(
            name="no_relax_compliance",
            description="Rate limiter and compliance module must not be made more permissive",
            trigger=TriggerPoint.PRE_EDIT,
            predicate=lambda ctx: ctx.get("target_file", "") not in {
                "rate_limiter.py", "compliance.py",
            } or not ctx.get("relaxes_constraints", False),
            enforcement=Enforcement.BLOCK,
            severity=9,
            tags=["constitutional", "compliance"],
        ))

        # Rule 8: Output content safety (runtime)
        self.add_rule(SafetyRule(
            name="no_sensitive_data_leak",
            description="Output must not contain API keys, passwords, or internal paths",
            trigger=TriggerPoint.ON_OUTPUT,
            predicate=lambda ctx: not _contains_sensitive_data(ctx.get("output", "")),
            enforcement=Enforcement.BLOCK,
            severity=10,
            tags=["runtime", "data_protection"],
        ))

        # Rule 9: Behavior drift monitoring (periodic)
        self.add_rule(SafetyRule(
            name="behavior_drift_check",
            description="Agent behavior metrics must stay within acceptable bounds",
            trigger=TriggerPoint.PERIODIC,
            predicate=lambda ctx: ctx.get("drift_score", 0) < 0.3,
            enforcement=Enforcement.WARN,
            severity=6,
            tags=["monitoring", "drift"],
        ))

        logger.debug(f"Loaded {len(self._rules)} built-in safety rules")


# ── Predicate Helper Functions ─────────────────────────────

def _contains_safety_disable(code: str) -> bool:
    """Check if code contains patterns that disable safety features."""
    dangerous_patterns = [
        r'logging\.disable',
        r'logger\.disabled\s*=\s*True',
        r'SAFETY.*=.*False',
        r'ENABLE_CHECKS.*=.*False',
        r'skip_safety',
        r'bypass_check',
        r'nosec',
        r'# noqa.*safety',
    ]
    for pattern in dangerous_patterns:
        if re.search(pattern, code, re.IGNORECASE):
            return True
    return False


def _check_safety_pattern_counts(old_code: str, new_code: str) -> bool:
    """Ensure safety-related AST patterns don't decrease."""
    if not old_code or not new_code:
        return True

    try:
        old_tree = ast.parse(old_code)
        new_tree = ast.parse(new_code)
    except SyntaxError:
        return False  # If new code has syntax errors, block it

    def count_patterns(tree):
        counts = {"try": 0, "assert": 0, "if": 0, "log": 0}
        for node in ast.walk(tree):
            if isinstance(node, ast.Try):
                counts["try"] += 1
            elif isinstance(node, ast.Assert):
                counts["assert"] += 1
            elif isinstance(node, ast.If):
                counts["if"] += 1
            elif isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute) and func.attr in (
                    "info", "warning", "error", "debug", "critical"
                ):
                    counts["log"] += 1
        return counts

    old_counts = count_patterns(old_tree)
    new_counts = count_patterns(new_tree)

    for key in old_counts:
        if new_counts.get(key, 0) < old_counts[key]:
            logger.warning(
                f"Safety regression: {key} count decreased "
                f"({old_counts[key]} → {new_counts[key]})"
            )
            return False
    return True


def _check_network_allowlist(code: str, allowed_domains: set) -> bool:
    """Check that any URLs in code only reference allowlisted domains."""
    url_pattern = re.compile(r'https?://([^/\s\'"]+)')
    found_domains = url_pattern.findall(code)

    for domain in found_domains:
        domain = domain.lower().rstrip('.,;:')
        if not any(domain.endswith(allowed) for allowed in allowed_domains):
            logger.warning(f"Unauthorized domain in code: {domain}")
            return False
    return True


def _contains_sensitive_data(text: str) -> bool:
    """Check if output contains sensitive data patterns."""
    patterns = [
        r'(?:sk|pk|api)[_-]?(?:live|test|key)[_-]?\w{20,}',  # API keys
        r'/data/neomind/\S+\.db',  # Internal DB paths
        r'(?:password|passwd|secret)\s*[=:]\s*\S+',  # Credentials
        r'(?:FINNHUB|ALPHA_VANTAGE|NEWSAPI|FRED)_API_KEY\s*=\s*\S+',  # Specific API keys
    ]
    for pattern in patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


# ── Singleton ──────────────────────────────────────

_spec: Optional[AgentSpec] = None


def get_agent_spec() -> AgentSpec:
    """Get or create the global AgentSpec singleton."""
    global _spec
    if _spec is None:
        _spec = AgentSpec()
    return _spec
