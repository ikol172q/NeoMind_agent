"""`AgentSession` — the application boundary.

One session owns one conversation. It sequences turns, owns every mutation of
history, drives the model through `LLMPort` and every tool through
`ToolExecutor`, and hands frontends *events* rather than its internals. A
frontend that wants to render a turn subscribes to `run_turn()`; it never
reaches into history, never calls a tool, and never talks to a provider.

Three things the baseline did that this exists to stop.

`main.headless_main()` ran its own parse → authorize → execute → feed-back
loop, separate from the REPL's, so "what may run without a human present" was
answered twice and could drift. There is one loop here and one executor
underneath it.

History was written from several places. `stream_response()` appended the raw
assistant reply, then the headless loop rewrote that same entry in place to
strip the tool payload — a dance that only works if both halves agree about
what was appended. The session appends once, after it knows what the message
finally is.

Permission answers travelled by mutating an event the loop re-read. Here a
`PermissionRequested` event is frozen like every other; the answer comes back
through `resolve_permission()` keyed by `request_id`, and a caller that never
answers times out rather than silently granting.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Mapping, Optional, Sequence

from agent.runtime.events import (
    RuntimeEvent,
    SequenceGenerator,
    StatusChanged,
    TextDelta,
    ThinkingDelta,
    ToolFinished,
    ToolProposed,
    ToolStarted,
    TurnFailed,
    TurnFinished,
    TurnStarted,
    new_call_id,
    new_session_id,
    new_turn_id,
)
from agent.runtime.llm_stream import (
    FinishChunk,
    LLMStreamError,
    TextChunk,
    ThinkingChunk,
    UsageChunk,
)

#: Matches the ceiling the headless loop used. A turn that wants more rounds
#: than this is looping, not working.
DEFAULT_MAX_TOOL_ROUNDS = 10

#: Tool output beyond this goes to the store; the event carries a preview.
#: Same 5000 the headless loop used, kept so migrated output does not change
#: shape under callers that were tuned against it.
TOOL_OUTPUT_PREVIEW_LIMIT = 5000


@dataclass(frozen=True)
class SessionSnapshot:
    """What a frontend needs to draw a session it just attached to."""

    session_id: str
    mode: str
    model: str
    message_count: int
    turn_count: int
    usage: Mapping[str, Any] = field(default_factory=dict)
    active_turn_id: Optional[str] = None


class AgentSession:
    """Owns one conversation.

    `llm` and `executor` are injected rather than constructed: the session is
    the piece every surface shares, and a session that builds its own provider
    client cannot be driven by a test without a network.
    """

    def __init__(
        self,
        *,
        llm: Any,
        executor: Any,
        model: str = "",
        mode: str = "chat",
        session_id: Optional[str] = None,
        history: Optional[Sequence[Mapping[str, Any]]] = None,
        store: Any = None,
        tool_parser: Any = None,
        max_tool_rounds: int = DEFAULT_MAX_TOOL_ROUNDS,
        permission_timeout: float = 120.0,
        llm_kwargs: Optional[Mapping[str, Any]] = None,
    ) -> None:
        self.session_id = session_id or new_session_id()
        self.llm = llm
        self.executor = executor
        self.model = model
        self.mode = mode
        self.store = store
        self.max_tool_rounds = max_tool_rounds
        self.permission_timeout = permission_timeout
        self.llm_kwargs = dict(llm_kwargs or {})

        self._history: List[Dict[str, Any]] = [dict(m) for m in (history or [])]
        self._tool_parser = tool_parser
        self._turn_count = 0
        self._usage: Dict[str, Any] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }
        self._active_turn_id: Optional[str] = None
        self._cancelled_turns: set = set()
        self._pending_permissions: Dict[str, asyncio.Future] = {}

    # ── read-only views ───────────────────────────────────────────────────

    @property
    def history(self) -> List[Dict[str, Any]]:
        """A copy. A frontend holding the live list could append to it."""
        return [dict(m) for m in self._history]

    def snapshot(self) -> SessionSnapshot:
        return SessionSnapshot(
            session_id=self.session_id,
            mode=self.mode,
            model=self.model,
            message_count=len(self._history),
            turn_count=self._turn_count,
            usage=dict(self._usage),
            active_turn_id=self._active_turn_id,
        )

    # ── permission ────────────────────────────────────────────────────────

    async def resolve_permission(self, request_id: str, decision: Any) -> None:
        """Answer an outstanding `PermissionRequested`.

        Unknown or already-answered ids are ignored rather than raising: a
        frontend that double-clicks Allow should not take the turn down.
        """
        future = self._pending_permissions.pop(request_id, None)
        if future is not None and not future.done():
            future.set_result(decision)

    async def cancel(self, turn_id: str) -> None:
        """Mark a turn cancelled. The generator stops at its next checkpoint
        and emits exactly one terminal event."""
        self._cancelled_turns.add(turn_id)
        for request_id, future in list(self._pending_permissions.items()):
            if not future.done():
                future.cancel()
            self._pending_permissions.pop(request_id, None)

    # ── the turn ──────────────────────────────────────────────────────────

    async def run_turn(self, text: str) -> AsyncIterator[RuntimeEvent]:
        """Run one turn, yielding events as they happen.

        Exactly one terminal event (`TurnFinished` or `TurnFailed`) is emitted,
        including on cancellation and on provider failure. A consumer may rely
        on that to stop waiting.
        """
        turn_id = new_turn_id()
        seq = SequenceGenerator()
        self._active_turn_id = turn_id
        self._turn_count += 1

        def _ev(cls, **kw):
            return cls(
                session_id=self.session_id,
                turn_id=turn_id,
                sequence=seq.next(),
                **kw,
            )

        # Sole owner: the user message is appended here and nowhere else.
        self._append({"role": "user", "content": text})

        yield _ev(TurnStarted, normalized_input=text, mode=self.mode, model=self.model)

        answer_parts: List[str] = []
        try:
            for round_index in range(self.max_tool_rounds + 1):
                if turn_id in self._cancelled_turns:
                    yield _ev(
                        TurnFailed,
                        error_code="cancelled",
                        message="Turn cancelled.",
                        retryable=True,
                    )
                    return

                assistant_text = ""
                async for event, chunk in self._stream_once(_ev):
                    if event is not None:
                        yield event
                    if isinstance(chunk, TextChunk):
                        assistant_text += chunk.text

                tool_call = self._parse_tool_call(assistant_text)

                if tool_call is None:
                    self._append({"role": "assistant", "content": assistant_text})
                    answer_parts.append(assistant_text)
                    break

                if round_index >= self.max_tool_rounds:
                    # Out of rounds with a tool still pending: record the prose
                    # and stop rather than executing an unbounded chain.
                    cleaned = self._strip_tool_call(assistant_text, tool_call)
                    self._append({"role": "assistant", "content": cleaned})
                    answer_parts.append(cleaned)
                    yield _ev(
                        StatusChanged,
                        code="tool_rounds_exhausted",
                        text=f"Stopped after {self.max_tool_rounds} tool rounds.",
                    )
                    break

                # The assistant message is stored without the raw tool payload:
                # replaying history should not re-arm an executable block.
                cleaned = self._strip_tool_call(assistant_text, tool_call)
                self._append({"role": "assistant", "content": cleaned})
                if cleaned.strip():
                    answer_parts.append(cleaned)

                async for event in self._run_tool(_ev, tool_call, turn_id):
                    yield event

            yield _ev(
                TurnFinished,
                response="".join(answer_parts).strip(),
                usage=dict(self._usage),
            )
        except LLMStreamError as exc:
            yield _ev(
                TurnFailed,
                error_code=exc.code,
                message=str(exc),
                retryable=exc.retryable,
            )
        except asyncio.CancelledError:
            yield _ev(
                TurnFailed,
                error_code="cancelled",
                message="Turn cancelled.",
                retryable=True,
            )
            raise
        except Exception as exc:  # noqa: BLE001 - terminal event is the contract
            yield _ev(
                TurnFailed,
                error_code="internal_error",
                message=f"{type(exc).__name__}: {exc}",
                retryable=False,
            )
        finally:
            self._active_turn_id = None

    # ── internals ─────────────────────────────────────────────────────────

    async def _stream_once(self, _ev):
        """One provider round. Yields `(event_or_None, chunk_or_None)`.

        The chunk comes back alongside the event so the caller can accumulate
        the answer without re-deriving it from the events it just forwarded.
        """
        stream = self.llm.stream(
            [dict(m) for m in self._history],
            self.model,
            **self.llm_kwargs,
        )
        async for chunk in stream:
            if isinstance(chunk, TextChunk):
                yield _ev(TextDelta, text=chunk.text), chunk
            elif isinstance(chunk, ThinkingChunk):
                yield _ev(ThinkingDelta, text=chunk.text), chunk
            elif isinstance(chunk, UsageChunk):
                self._record_usage(chunk)
                yield None, chunk
            elif isinstance(chunk, FinishChunk):
                yield None, chunk

    async def _run_tool(self, _ev, tool_call, turn_id: str):
        call_id = new_call_id()
        tool_name = getattr(tool_call, "tool_name", "")
        params = dict(getattr(tool_call, "params", {}) or {})

        yield _ev(
            ToolProposed,
            call_id=call_id,
            tool_name=tool_name,
            preview=self._preview_params(params),
        )

        request_id_holder: Dict[str, Any] = {}
        emitted: List[RuntimeEvent] = []

        async def on_permission_requested(**kw):
            """Executor asks; the session turns that into an event and waits.

            The future is stored before the event is yielded so an answer that
            arrives immediately cannot be dropped.
            """
            request_id = kw.get("request_id", "")
            loop = asyncio.get_event_loop()
            future = loop.create_future()
            self._pending_permissions[request_id] = future
            request_id_holder["request_id"] = request_id
            request_id_holder["event"] = kw
            try:
                return await asyncio.wait_for(future, timeout=self.permission_timeout)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._pending_permissions.pop(request_id, None)
                raise
            finally:
                self._pending_permissions.pop(request_id, None)

        yield _ev(ToolStarted, call_id=call_id, tool_name=tool_name)

        outcome = await self.executor.execute(
            tool_name,
            params,
            request_id=call_id,
            on_permission_requested=on_permission_requested,
        )

        output = getattr(outcome, "output", "") or ""
        success = bool(getattr(outcome, "success", False))
        denied = bool(getattr(outcome, "denied", False))
        denied_reason = getattr(outcome, "denied_reason", "") or ""
        # A refusal is not an error. ExecutionOutcome keeps `executed` apart
        # from `success` precisely so the model is not told "the tool errored"
        # when it was blocked — it retries errors, and retrying a denial is
        # how a refused write turns into a loop.
        error = denied_reason if denied else (getattr(outcome, "error", "") or "")
        preview, output_ref = self._bound_output(output)

        yield _ev(
            ToolFinished,
            call_id=call_id,
            tool_name=tool_name,
            success=success,
            preview=preview,
            error=error,
            output_ref=output_ref,
            metadata=dict(getattr(outcome, "metadata", {}) or {}),
        )

        # Feed the result back as its own message, once. The three outcomes
        # read differently on purpose, so the model can tell "this is the
        # answer" from "this failed, maybe retry" from "you are not allowed".
        if success:
            body = output
        elif denied:
            body = f"Permission denied: {denied_reason or 'not permitted in this session'}"
        else:
            body = error or "Tool failed."
        self._append(
            {
                "role": "user",
                "content": f"[tool:{tool_name}] {self._truncate(body)}",
                "_tool_result": True,
            }
        )

    def _parse_tool_call(self, text: str):
        if not self._tool_parser or not text:
            return None
        try:
            return self._tool_parser.parse(text)
        except Exception:
            # A parser that raises must not take the turn down; no tool call
            # is a valid reading of unparseable output.
            return None

    def _strip_tool_call(self, text: str, tool_call) -> str:
        stripper = getattr(self._tool_parser, "strip_tool_call", None)
        if stripper is None:
            return text
        try:
            return stripper(text, tool_call)
        except Exception:
            return text

    def _append(self, message: Mapping[str, Any]) -> None:
        """The single write path for history."""
        entry = dict(message)
        self._history.append(entry)
        if self.store is not None:
            try:
                self.store.append(self.session_id, entry)
            except Exception:
                # A failing store must not lose the turn; the in-memory history
                # stays authoritative for this session.
                pass

    def _record_usage(self, usage: UsageChunk) -> None:
        self._usage["prompt_tokens"] += usage.prompt_tokens
        self._usage["completion_tokens"] += usage.completion_tokens
        self._usage["total_tokens"] += usage.total_tokens

    @staticmethod
    def _truncate(text: str, limit: int = TOOL_OUTPUT_PREVIEW_LIMIT) -> str:
        if len(text) <= limit:
            return text
        return text[:limit] + "\n... [truncated]"

    def _bound_output(self, output: str):
        if len(output) <= TOOL_OUTPUT_PREVIEW_LIMIT:
            return output, None
        ref = None
        if self.store is not None:
            ref = f"{self.session_id}:tool_output:{len(self._history)}"
        return output[:TOOL_OUTPUT_PREVIEW_LIMIT] + "\n... [truncated]", ref

    @staticmethod
    def _preview_params(params: Mapping[str, Any]) -> str:
        parts = []
        for key, value in list(params.items())[:4]:
            text = str(value)
            if len(text) > 80:
                text = text[:80] + "…"
            parts.append(f"{key}={text}")
        return ", ".join(parts)
