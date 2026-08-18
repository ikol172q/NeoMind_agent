"""Translate NeoMind runtime events into ACP session updates.

Phase 7. The Agent Client Protocol is what DeepSeek Harness drives external
agents with (`subagent-acp`) and what Zed speaks natively, so an ACP server is
the one adapter that makes NeoMind usable from clients we did not write.

This module is the whole translation, and it is deliberately pure: events in,
ACP models out, no transport and no session. That is what makes it testable
without a client, a socket or a model — and the mapping is where an adapter
silently goes wrong, because a wrong field name still type-checks.

The mapping exists at all because Phases 1–6 froze an event set:

    TextDelta      → AgentMessageChunk
    ThinkingDelta  → AgentThoughtChunk
    ToolProposed   → ToolCallStart      (status: pending)
    ToolStarted    → ToolCallProgress   (status: in_progress)
    ToolFinished   → ToolCallProgress   (status: completed | failed)
    UsageChunk     → UsageUpdate

ACP's status enum is only `pending | in_progress | completed | failed` — it has
**no** state for "refused", so a denial has to arrive as `failed` plus text
saying so. `ToolFinished.denied` is what makes that text reliable: without it
the only way to know a refusal happened would be matching on the wording of
`error`, which is the bug that had every denial rendering as a crash on the CLI
and Telegram for an entire phase.
"""

from __future__ import annotations

from typing import Any, Iterable, List, Optional

from acp import schema

from agent.runtime.events import (
    RuntimeEvent,
    StatusChanged,
    TextDelta,
    ThinkingDelta,
    ToolFinished,
    ToolProposed,
    ToolStarted,
    TurnFailed,
    TurnFinished,
)

#: The `session_update` discriminator is never written by hand here. Each model
#: declares it as a `Literal` with a default, so pydantic fills it in — and one
#: hand-typed value was already wrong ("usage" where the schema says
#: "usage_update"), which only surfaced when a real object was constructed.
#:
#: How much of a tool's output travels to the client. ACP has no bound of its
#: own, and a client rendering megabytes inline stalls — the same reason
#: `ToolFinished` carries a preview and an `output_ref` rather than the output.
TOOL_CONTENT_LIMIT = 2000


def _tag(model: Any) -> str:
    """The `session_update` discriminator a model requires, read from its own
    schema.

    Required, so it cannot be omitted — and hand-typing it is how one of these
    ended up as "usage" where the schema says "usage_update", a mistake no type
    checker catches and only a constructed object reveals. Reading the Literal
    means the value cannot drift from the model it labels.
    """
    import typing

    ann = model.model_fields["session_update"].annotation
    args = typing.get_args(ann)
    if not args:
        raise TypeError(f"{model.__name__}.session_update is not a Literal")
    return args[0]


def _text_block(text: str) -> Any:
    """ACP content blocks are tagged; text is the only kind we produce."""
    return schema.TextContentBlock(type="text", text=text)


def _tool_content(text: str) -> List[Any]:
    if not text:
        return []
    clipped = text[:TOOL_CONTENT_LIMIT]
    if len(text) > TOOL_CONTENT_LIMIT:
        clipped += f"\n… ({len(text) - TOOL_CONTENT_LIMIT} more characters)"
    return [schema.ContentToolCallContent(type="content", content=_text_block(clipped))]


def tool_status_for(event: ToolFinished) -> str:
    """ACP has two outcomes where the runtime has three.

    `completed` and `failed` are all the protocol offers, so a refusal maps to
    `failed` — and `describe_outcome` carries the distinction in the text,
    because losing it entirely would tell the user their tool crashed when it
    was declined.
    """
    return "completed" if event.success else "failed"


def describe_outcome(event: ToolFinished) -> str:
    """The text a client shows for a finished tool.

    Refusal is stated as refusal even though the status field cannot hold it.
    """
    if event.success:
        return event.preview or ""
    if event.denied:
        return f"Refused: {event.error or 'not permitted in this session'}"
    return event.error or "Tool failed."


def translate(event: RuntimeEvent) -> Optional[Any]:
    """One runtime event → one ACP session update, or None if it has no
    counterpart.

    Returning None rather than inventing an update matters: `TurnStarted` and
    `TurnFinished` are turn lifecycle, which ACP expresses by the `prompt` call
    returning, not by a session update. Emitting something for them would make
    a client render a phantom message.
    """
    if isinstance(event, TextDelta):
        return schema.AgentMessageChunk(
            session_update=_tag(schema.AgentMessageChunk),
            content=_text_block(event.text),
        )

    if isinstance(event, ThinkingDelta):
        return schema.AgentThoughtChunk(
            session_update=_tag(schema.AgentThoughtChunk),
            content=_text_block(event.text),
        )

    if isinstance(event, ToolProposed):
        return schema.ToolCallStart(
            session_update=_tag(schema.ToolCallStart),
            tool_call_id=event.call_id,
            title=event.tool_name or "tool",
            status="pending",
            # `preview` is a rendered string, not the parameter dict — the
            # event deliberately carries a bounded preview rather than raw
            # params, so there is nothing structured to put in `raw_input`.
            content=_tool_content(event.preview or ""),
        )

    if isinstance(event, ToolStarted):
        return schema.ToolCallProgress(
            session_update=_tag(schema.ToolCallProgress),
            tool_call_id=event.call_id,
            status="in_progress",
        )

    if isinstance(event, ToolFinished):
        return schema.ToolCallProgress(
            session_update=_tag(schema.ToolCallProgress),
            tool_call_id=event.call_id,
            status=tool_status_for(event),
            content=_tool_content(describe_outcome(event)),
        )

    if isinstance(event, StatusChanged):
        # Surfaced as an agent message rather than dropped: "stopped after 3
        # tool rounds" is something the user has to see, and ACP has no
        # dedicated status update.
        return schema.AgentMessageChunk(
            session_update=_tag(schema.AgentMessageChunk),
            content=_text_block(f"[{event.text}]"),
        ) if event.text else None

    return None


def translate_all(events: Iterable[RuntimeEvent]) -> List[Any]:
    """Convenience for tests and for replaying a recorded trace."""
    return [u for u in (translate(e) for e in events) if u is not None]


def usage_update(usage: Any) -> Optional[Any]:
    """`UsageChunk` → `UsageUpdate`.

    Separate from `translate` because usage arrives on the provider stream
    rather than as a runtime event; the session folds it into `TurnFinished`.
    """
    total = getattr(usage, "total_tokens", None)
    if total is None and isinstance(usage, dict):
        total = usage.get("total_tokens")
    if not total:
        return None
    return schema.UsageUpdate(
        session_update=_tag(schema.UsageUpdate),
        used=int(total),
        size=int(total),
    )


def turn_usage(usage: Any) -> Optional[Any]:
    """`TurnFinished.usage` → `schema.Usage`, for the `prompt` response.

    A *different* type from `usage_update`, which is a session update pushed
    mid-turn. Passing the wrong one is silent: pydantic drops a field it cannot
    validate rather than raising, so the response simply arrives with no usage
    and the client reports nothing spent.
    """
    if not usage:
        return None
    get = usage.get if isinstance(usage, dict) else lambda k, d=0: getattr(usage, k, d)
    total = int(get("total_tokens", 0) or 0)
    prompt_tokens = int(get("prompt_tokens", 0) or 0)
    completion = int(get("completion_tokens", 0) or 0)
    if not (total or prompt_tokens or completion):
        return None
    return schema.Usage(
        total_tokens=total or (prompt_tokens + completion),
        input_tokens=prompt_tokens,
        output_tokens=completion,
    )


def stop_reason_for(event: Any) -> str:
    """What ACP should be told a turn ended as.

    `cancelled` is not an error — the runtime keeps them apart and so does
    ACP, and a client that shows a user's own Ctrl-C as a failure is lying to
    them.

    Every other `TurnFailed` maps to `max_turn_requests`, **not** `refusal`.
    `TurnFailed` is only ever a technical failure — a provider error, a
    timeout, an unexpected exception — and the runtime has no way to express
    "the model declined", so nothing here can legitimately produce a refusal.

    Mapping them to `refusal` was wrong in a way only a real client showed:
    DeepSeek Harness took it at its word and reported "subagent declined the
    task", sending its model off to rephrase the prompt twice. A transport
    failure dressed as a refusal makes the caller debug the wrong thing.
    """
    if isinstance(event, TurnFinished):
        return "end_turn"
    if isinstance(event, TurnFailed):
        if event.error_code == "cancelled":
            return "cancelled"
        # ACP's remaining options are end_turn | max_tokens |
        # max_turn_requests | refusal. Of those, only max_turn_requests reads
        # as "the run stopped without finishing" rather than a deliberate act.
        return "max_turn_requests"
    return "end_turn"
