"""Immutable runtime events.

Every event is frozen. This is the direct fix for the defect the baseline audit
found: `AgenticEvent.approved` defaulted to True and the loop re-read the same
object after yielding it, so a frontend granted permission by saying nothing and
could change what it had approved. Events here cannot be written to at all —
permission answers travel back through `AgentSession.resolve_permission()`
keyed by `request_id`, never by mutating an event the runtime will read again.

Every event carries `session_id, turn_id, sequence, timestamp, type`. Sequence
numbers increase monotonically within a turn so a renderer can detect dropped or
reordered events — Telegram message edits, terminal repaint, and record/replay
tests all depend on that ordering being checkable rather than assumed.
"""

from __future__ import annotations

import itertools
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Tuple


def new_session_id() -> str:
    return f"ses_{uuid.uuid4().hex[:16]}"


def new_turn_id() -> str:
    return f"trn_{uuid.uuid4().hex[:16]}"


def new_call_id() -> str:
    return f"cal_{uuid.uuid4().hex[:16]}"


def new_request_id() -> str:
    return f"req_{uuid.uuid4().hex[:16]}"


class SequenceGenerator:
    """Monotonic per-turn sequence source.

    Deliberately per-turn rather than global: a consumer checking for gaps
    should not have to reason about interleaving from other turns or sessions.
    """

    def __init__(self) -> None:
        self._counter = itertools.count()

    def next(self) -> int:
        return next(self._counter)


@dataclass(frozen=True)
class RuntimeEvent:
    """Base envelope. Subclasses add payload; none of them add mutability."""

    session_id: str
    turn_id: str
    sequence: int
    timestamp: float = field(default_factory=time.time)

    @property
    def type(self) -> str:
        """Stable wire name — the class name is an implementation detail."""
        return _EVENT_TYPES.get(type(self), type(self).__name__)


# ── Turn lifecycle ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TurnStarted(RuntimeEvent):
    normalized_input: str = ""
    mode: str = ""
    model: str = ""


@dataclass(frozen=True)
class StatusChanged(RuntimeEvent):
    """Structured code plus display text.

    The code is what tests and non-terminal surfaces branch on; the text is for
    humans. Surfaces that branch on prose break the moment the prose is
    reworded or translated.
    """

    code: str = ""
    text: str = ""


@dataclass(frozen=True)
class ThinkingDelta(RuntimeEvent):
    text: str = ""


@dataclass(frozen=True)
class TextDelta(RuntimeEvent):
    text: str = ""


@dataclass(frozen=True)
class ContextWarning(RuntimeEvent):
    used_tokens: int = 0
    limit_tokens: int = 0


@dataclass(frozen=True)
class ContextCompacted(RuntimeEvent):
    tokens_before: int = 0
    tokens_after: int = 0
    messages_removed: int = 0


@dataclass(frozen=True)
class TurnFinished(RuntimeEvent):
    response: str = ""
    usage: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TurnFailed(RuntimeEvent):
    error_code: str = ""
    message: str = ""
    retryable: bool = False


# ── Tools and permission ──────────────────────────────────────────────────


@dataclass(frozen=True)
class ToolProposed(RuntimeEvent):
    """The model asked for a tool. Nothing has been authorized yet."""

    call_id: str = ""
    tool_name: str = ""
    preview: str = ""


@dataclass(frozen=True)
class PermissionRequested(RuntimeEvent):
    """A decision is needed before this call can run.

    `allowed_scopes` tells the surface which answers the runtime will accept, so
    a UI cannot offer "always allow" where policy does not permit it. There is
    no session-wide allow: a scope always names a tool and a target pattern.
    """

    request_id: str = ""
    call_id: str = ""
    tool_name: str = ""
    risk: str = ""
    explanation: str = ""
    preview: str = ""
    allowed_scopes: Tuple[str, ...] = ()


@dataclass(frozen=True)
class ToolStarted(RuntimeEvent):
    call_id: str = ""
    tool_name: str = ""


@dataclass(frozen=True)
class ToolOutputDelta(RuntimeEvent):
    call_id: str = ""
    text: str = ""


@dataclass(frozen=True)
class ToolFinished(RuntimeEvent):
    """Bounded preview only.

    Large output stays in the store and is referenced by `output_ref`; a
    renderer that receives megabytes inline will stall the surface it draws.
    """

    call_id: str = ""
    tool_name: str = ""
    success: bool = False
    #: A refusal is not a failure, and a renderer must not have to recover the
    #: difference by matching on the wording of `error`. It carried
    #: `denied_reason` verbatim — "tool not in session capability snapshot" —
    #: which no prefix check was ever going to recognise, so every denial on
    #: every surface drew as a crash.
    denied: bool = False
    preview: str = ""
    error: str = ""
    output_ref: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


_EVENT_TYPES: Dict[type, str] = {
    TurnStarted: "turn_started",
    StatusChanged: "status_changed",
    ThinkingDelta: "thinking_delta",
    TextDelta: "text_delta",
    ContextWarning: "context_warning",
    ContextCompacted: "context_compacted",
    TurnFinished: "turn_finished",
    TurnFailed: "turn_failed",
    ToolProposed: "tool_proposed",
    PermissionRequested: "permission_requested",
    ToolStarted: "tool_started",
    ToolOutputDelta: "tool_output_delta",
    ToolFinished: "tool_finished",
}

TERMINAL_EVENT_TYPES = frozenset({"turn_finished", "turn_failed"})
