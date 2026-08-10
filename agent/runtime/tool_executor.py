"""The only place a tool is executed.

Before this existed, `tool_def.execute()` was reachable from four places: the
agentic loop (guarded only if the frontend bothered to answer), the headless
loop (unguarded), a dead CLI method (unguarded), and the dead QueryEngine
(unguarded and broken). Authorization and execution were separable, so every
new surface got to re-decide whether to check.

Here they are inseparable. `execute()` performs capability filtering,
validation, policy evaluation, approval binding, the post-approval fingerprint
re-check, execution, and audit — in that order, with no way to call the tail
without the head.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Mapping, Optional, Sequence

from agent.runtime.permissions import (
    Approval,
    CapabilitySnapshot,
    Decision,
    PermissionBrokerError,
    PermissionPolicy,
    Scope,
    SessionRule,
    fingerprint,
    redact_params,
)

logger = logging.getLogger(__name__)

DEFAULT_PERMISSION_TIMEOUT = 300.0


@dataclass(frozen=True)
class ExecutionOutcome:
    """What happened. `executed` is separate from `success` on purpose.

    A denied call and a call that ran and failed are different events; collapsing
    them into one boolean is how "the tool was blocked" gets reported to the
    model as "the tool errored", which it then retries.
    """

    executed: bool
    success: bool = False
    output: str = ""
    error: str = ""
    denied_reason: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def denied(self) -> bool:
        return not self.executed


class ToolExecutor:
    """Authorize-and-execute. There is no authorize-only entry point."""

    def __init__(
        self,
        registry: Any,
        policy: Optional[PermissionPolicy] = None,
        broker: Optional[Any] = None,
        audit: Optional[Any] = None,
        working_dir: str = "",
        permission_timeout: float = DEFAULT_PERMISSION_TIMEOUT,
        risk_classifier: Optional[Callable[[str, str, Mapping[str, Any]], str]] = None,
        guards: Optional[Sequence[Callable[..., Any]]] = None,
    ) -> None:
        self.registry = registry
        self.policy = policy or PermissionPolicy()
        self.broker = broker
        self.audit = audit
        self.working_dir = working_dir
        self.permission_timeout = permission_timeout
        self._risk_classifier = risk_classifier
        # Last-mile denials that are not permission policy: read-before-edit,
        # user PreToolUse hooks, workspace rules. They live here rather than in
        # the caller so there is one place that decides the order in which a
        # call can be refused — a guard the caller runs is a guard the next
        # surface forgets to run.
        self.guards = list(guards or [])

    # ── public API ────────────────────────────────────────────────────────

    async def execute(
        self,
        tool_name: str,
        params: Mapping[str, Any],
        request_id: str = "",
        on_permission_requested: Optional[Callable[..., Awaitable[None]]] = None,
    ) -> ExecutionOutcome:
        params = dict(params or {})

        tool_def = self._lookup(tool_name)
        if tool_def is None:
            return self._deny(tool_name, params, "unknown tool")

        if not self.policy.capabilities.permits(tool_name):
            return self._deny(tool_name, params, "tool not in session capability snapshot")

        valid, validation_error = self._validate(tool_def, params)
        if not valid:
            return self._deny(tool_name, params, f"invalid params: {validation_error}")

        # Defaults are applied *before* fingerprinting so the approved call and
        # the executed call are byte-identical. Applying them afterwards would
        # mean the operator approved one thing and the tool ran another.
        try:
            effective_params = dict(tool_def.apply_defaults(params))
        except Exception as exc:  # noqa: BLE001 — a broken schema must not execute
            return self._deny(tool_name, params, f"could not apply defaults: {exc!r}")

        try:
            approved_fp = fingerprint(tool_name, effective_params, self.working_dir)
        except (TypeError, ValueError):
            return self._deny(tool_name, params, "call could not be fingerprinted")

        level = self._level_of(tool_def)
        risk = self._classify_risk(tool_name, level, effective_params)
        decision, reason = self.policy.evaluate(tool_name, level, effective_params, risk)

        if decision is Decision.DENY:
            return self._deny(tool_name, effective_params, reason, level=level, risk=risk)

        if decision is Decision.ASK:
            approval = await self._ask(
                request_id=request_id,
                tool_name=tool_name,
                tool_def=tool_def,
                params=effective_params,
                risk=risk,
                explanation=reason,
                on_permission_requested=on_permission_requested,
            )
            if approval is None:
                return self._deny(tool_name, effective_params, "not approved", level=level, risk=risk)
            if approval.fingerprint != approved_fp:
                # The answer refers to a different call than the one we hold.
                return self._deny(
                    tool_name, effective_params,
                    "approval fingerprint does not match the call", level=level, risk=risk,
                )
            if approval.scope is Scope.SESSION_PATTERN and approval.rule is not None:
                self.policy.session_rules.append(approval.rule)

        # Last line of defence: re-derive the fingerprint from the params we are
        # about to hand to the tool. Anything that mutated them between the
        # decision and this point invalidates the approval.
        try:
            final_fp = fingerprint(tool_name, effective_params, self.working_dir)
        except (TypeError, ValueError):
            return self._deny(tool_name, effective_params, "call became non-fingerprintable")

        if final_fp != approved_fp:
            logger.warning("[runtime] tool call changed after approval; blocking %s", tool_name)
            return self._deny(tool_name, effective_params, "call changed after approval")

        # Guards run after approval and immediately before execution, matching
        # the legacy order: the operator is asked first, then a hook may still
        # veto. A guard that runs before the prompt would silently drop calls
        # the user believes they are being consulted about.
        guard_denial = await self._run_guards(tool_name, effective_params)
        if guard_denial is not None:
            return self._deny(tool_name, effective_params, guard_denial, level=level, risk=risk)

        return await self._run(tool_def, tool_name, effective_params, level, risk, reason)

    async def _run_guards(self, tool_name: str, params: Mapping[str, Any]) -> Optional[str]:
        """Return a denial reason, or None to proceed.

        A guard that raises denies. Letting an exception mean "allow" would
        make a broken hook indistinguishable from an approving one.
        """
        for guard in self.guards:
            try:
                verdict = guard(tool_name, dict(params))
                if asyncio.iscoroutine(verdict):
                    verdict = await verdict
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "[runtime] guard %s raised; denying %s",
                    getattr(guard, "__name__", type(guard).__name__), tool_name,
                )
                return f"guard error: {type(exc).__name__}"
            if verdict:
                return str(verdict)
        return None

    # ── internals ─────────────────────────────────────────────────────────

    def _lookup(self, tool_name: str) -> Optional[Any]:
        getter = getattr(self.registry, "get_tool", None)
        if getter is None:
            return None
        try:
            return getter(tool_name)
        except Exception:  # noqa: BLE001 — a registry that raises denies
            logger.warning("[runtime] registry lookup failed for %s", tool_name)
            return None

    @staticmethod
    def _validate(tool_def: Any, params: Mapping[str, Any]) -> tuple:
        validator = getattr(tool_def, "validate_params", None)
        if validator is None:
            return True, ""
        try:
            return validator(dict(params))
        except Exception as exc:  # noqa: BLE001
            return False, repr(exc)

    @staticmethod
    def _level_of(tool_def: Any) -> Optional[str]:
        level = getattr(tool_def, "permission_level", None)
        # Accept both the enum and a bare string; return None for anything else
        # so the policy denies rather than guessing.
        value = getattr(level, "value", level)
        return value if isinstance(value, str) else None

    def _classify_risk(self, tool_name: str, level: Optional[str], params: Mapping[str, Any]) -> str:
        if self._risk_classifier is None:
            return ""
        try:
            return self._risk_classifier(tool_name, level or "", params) or ""
        except Exception:  # noqa: BLE001 — classifier failure must not grant access
            logger.debug("[runtime] risk classifier raised; treating as CRITICAL")
            return "CRITICAL"

    async def _ask(
        self,
        request_id: str,
        tool_name: str,
        tool_def: Any,
        params: Mapping[str, Any],
        risk: str,
        explanation: str,
        on_permission_requested: Optional[Callable[..., Awaitable[None]]],
    ) -> Optional[Approval]:
        if self.broker is None:
            return None

        preview = self._preview(tool_def, tool_name, params)
        allowed_scopes = (Scope.ONCE.value,)
        if risk.upper() != "CRITICAL":
            allowed_scopes = (Scope.ONCE.value, Scope.SESSION_PATTERN.value)

        if on_permission_requested is not None:
            try:
                await on_permission_requested(
                    request_id=request_id,
                    tool_name=tool_name,
                    risk=risk,
                    explanation=explanation,
                    preview=preview,
                    allowed_scopes=allowed_scopes,
                )
            except Exception:  # noqa: BLE001 — a renderer failure is not consent
                logger.warning("[runtime] permission notification failed; denying")
                return None

        try:
            answer = await asyncio.wait_for(
                self.broker.request(
                    request_id=request_id,
                    tool_name=tool_name,
                    preview=preview,
                    risk=risk,
                    explanation=explanation,
                    allowed_scopes=allowed_scopes,
                ),
                timeout=self.permission_timeout,
            )
        except asyncio.CancelledError:
            # Cancellation is denial, and it must still propagate so the turn
            # actually stops rather than continuing with a half-cancelled call.
            logger.info("[runtime] permission request cancelled; denying %s", tool_name)
            raise
        except (asyncio.TimeoutError, PermissionBrokerError, Exception):  # noqa: BLE001
            logger.warning("[runtime] permission broker failed/timed out; denying %s", tool_name)
            return None

        if answer is None or isinstance(answer, bool):
            # A bare True is not an approval: it names no call, so it cannot be
            # bound to one. Brokers must return an Approval.
            return None
        if not isinstance(answer, Approval):
            return None
        return answer

    @staticmethod
    def _preview(tool_def: Any, tool_name: str, params: Mapping[str, Any]) -> str:
        previewer = getattr(tool_def, "preview", None)
        if callable(previewer):
            try:
                return str(previewer(dict(params)))
            except Exception:  # noqa: BLE001
                pass
        return f"{tool_name}({redact_params(params, limit=120)})"

    async def _run(
        self,
        tool_def: Any,
        tool_name: str,
        params: Mapping[str, Any],
        level: Optional[str],
        risk: str,
        reason: str,
    ) -> ExecutionOutcome:
        fn = getattr(tool_def, "execute", None)
        if not callable(fn):
            return self._deny(tool_name, params, "tool has no executable")

        try:
            if asyncio.iscoroutinefunction(fn):
                result = await fn(**params)
            else:
                # Sync tools run off the loop so a slow shell command cannot
                # freeze a UI that is awaiting this turn.
                result = await asyncio.to_thread(fn, **params)
        except Exception as exc:  # noqa: BLE001 — tool failure is data, not a crash
            self._audit(tool_name, params, "executed", f"raised {type(exc).__name__}", level, risk)
            return ExecutionOutcome(
                executed=True, success=False, error=f"{type(exc).__name__}: {exc}",
            )

        self._audit(tool_name, params, "executed", reason, level, risk)
        return self._to_outcome(result)

    @staticmethod
    def _to_outcome(result: Any) -> ExecutionOutcome:
        # The real ToolResult exposes success/output/error/metadata. Read those
        # names — the dead QueryEngine read `.status`, which does not exist.
        success = getattr(result, "success", None)
        if success is None:
            return ExecutionOutcome(executed=True, success=True, output=str(result))
        return ExecutionOutcome(
            executed=True,
            success=bool(success),
            output=str(getattr(result, "output", "") or ""),
            error=str(getattr(result, "error", "") or ""),
            metadata=dict(getattr(result, "metadata", {}) or {}),
        )

    def _deny(
        self,
        tool_name: str,
        params: Mapping[str, Any],
        reason: str,
        level: Optional[str] = None,
        risk: str = "",
    ) -> ExecutionOutcome:
        self._audit(tool_name, params, "denied", reason, level, risk)
        return ExecutionOutcome(executed=False, success=False, denied_reason=reason)

    def _audit(
        self,
        tool_name: str,
        params: Mapping[str, Any],
        outcome: str,
        reason: str,
        level: Optional[str],
        risk: str,
    ) -> None:
        if self.audit is None:
            return
        try:
            self.audit.record({
                "tool": tool_name,
                "outcome": outcome,
                "reason": reason,
                "permission_level": level,
                "risk": risk,
                # Redacted preview, never the raw arguments.
                "params_preview": redact_params(params),
            })
        except Exception:  # noqa: BLE001 — audit failure must not change the decision
            logger.debug("[runtime] audit record failed", exc_info=False)
