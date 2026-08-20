"""Headless consumer — turns a turn's events into `-p` output.

This is the first surface that renders nothing while a turn is running and
still produces correct output, which is the point of Phase 3: if a second
frontend can be written against the event stream alone, the contract holds.

It replaces `main.headless_main()`'s own parse → authorize → execute →
feed-back loop. That loop was a second answer to "what may run with no human
present", kept in step with the REPL's answer by hand; it also redirected
`sys.stdout` into a `StringIO` for the duration of a turn to suppress the
streaming prints the runtime should never have been making.

Capability, not vigilance, is what makes this safe now: the session is built
with a read-only capability snapshot, so a write tool is refused by the
executor rather than by a check remembered here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Mapping, Optional

from agent.runtime.events import (
    RuntimeEvent,
    ToolFinished,
    ToolStarted,
    TurnFailed,
    TurnFinished,
)


@dataclass
class HeadlessResult:
    """Everything `-p` needs, with no rendering decisions baked in."""

    response: str = ""
    ok: bool = True
    error_code: str = ""
    error_message: str = ""
    retryable: bool = False
    usage: Mapping[str, Any] = field(default_factory=dict)
    tools: List[Dict[str, Any]] = field(default_factory=list)

    def to_text(self) -> str:
        if self.ok:
            return self.response or "(no response)"
        return f"Error [{self.error_code}]: {self.error_message}"

    def to_json(self) -> str:
        """New fields, old keys kept.

        The legacy `-p --output-format json` shape was
        `{"response": ..., "tokens": len(response)//4}`. Automation reading
        those two keys keeps working: `response` is unchanged and `tokens` is
        still present, now carrying the provider's real completion count when
        there is one instead of a character estimate. Everything else is
        additive.
        """
        usage = dict(self.usage)
        payload: Dict[str, Any] = {
            "response": self.response,
            "tokens": usage.get("completion_tokens") or (len(self.response) // 4),
            "ok": self.ok,
            "usage": usage,
            "tools": self.tools,
        }
        if not self.ok:
            payload["error"] = {
                "code": self.error_code,
                "message": self.error_message,
                "retryable": self.retryable,
            }
        return json.dumps(payload, ensure_ascii=False, indent=2)


async def consume(events: AsyncIterator[RuntimeEvent]) -> HeadlessResult:
    """Fold a turn's events into one result.

    Reads only the terminal event for the answer. Accumulating `TextDelta`
    instead would double-count the prose that precedes a tool call, since the
    session already folds those into `TurnFinished.response`.
    """
    result = HeadlessResult()
    saw_terminal = False
    started: Dict[str, str] = {}

    async for event in events:
        if isinstance(event, ToolStarted):
            started[event.call_id] = event.tool_name
        elif isinstance(event, ToolFinished):
            result.tools.append(
                {
                    "tool": event.tool_name or started.get(event.call_id, ""),
                    "success": event.success,
                    "error": event.error,
                }
            )
        elif isinstance(event, TurnFinished):
            result.response = event.response
            result.usage = dict(event.usage)
            result.ok = True
            saw_terminal = True
        elif isinstance(event, TurnFailed):
            result.ok = False
            result.error_code = event.error_code
            result.error_message = event.message
            result.retryable = event.retryable
            saw_terminal = True

    if not saw_terminal:
        # The session contracts to emit exactly one terminal event. Reaching
        # here means it did not, and reporting success would hide that.
        result.ok = False
        result.error_code = "no_terminal_event"
        result.error_message = "the turn ended without a terminal event"
    return result


def render(result: HeadlessResult, output_format: str = "text") -> str:
    return result.to_json() if output_format == "json" else result.to_text()
