"""Serve NeoMind over pi's session protocol.

Phase 7, second adapter. pi has a terminal UI and does **not** speak ACP — a
fresh clone on 2026-08-16 contains no reference to it — so this is what it takes
to drive NeoMind from that client. Kept entirely separate from the ACP server on
purpose: pi's own `server` package describes itself as "Experimental… may change
or be removed without notice", and a protocol that may vanish must not be able
to take anything else down with it.

The protocol is nine commands over length-prefixed CBOR:

    list   create   attach   detach   prompt   steer   abort
    set_model   set_thinking

`attach`/`detach`/`list` mean several clients can watch one running session, and
`steer` is intervention mid-generation. NeoMind has no equivalent of steer, so
it is answered `not_implemented` rather than approximated — a client told a
feature exists and then given something else is worse off than one told no.

Progress maps cleanly, which is the whole reason this is small:

    TextDelta      → assistant_delta(kind="text")
    ThinkingDelta  → assistant_delta(kind="thinking")
    ToolProposed   → item_started
    ToolFinished   → item_finished

This module owns no transport. It takes decoded messages and returns messages
to send, so the entire command surface is testable without a socket.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from agent.runtime.events import (
    TextDelta,
    ThinkingDelta,
    ToolFinished,
    ToolProposed,
    ToolStarted,
    TurnFailed,
    TurnFinished,
)

#: pi's own `PROTOCOL_VERSION`. A client announcing anything else is refused at
#: hello with `version` rather than allowed to fail later on a shape mismatch.
PROTOCOL_VERSION = 1

#: pi's `SessionPhaseSchema`. There is no "busy" — a turn in flight is
#: `turn`, and inventing a phase name makes every snapshot sent afterwards
#: fail validation at the client.
PHASE_IDLE = "idle"
PHASE_TURN = "turn"

#: `ModelRefSchema` is an object, not a string. A bare model name looks
#: reasonable and is rejected by the whole snapshot, with an error that names
#: no field because the failure is in a nested union.
DEFAULT_MODEL_REF = {"provider": "neomind", "id": "unknown"}

#: pi's error codes, from `ProtocolErrorCodeSchema`.
ERROR_VERSION = "version"
ERROR_NOT_FOUND = "not_found"
ERROR_INVALID = "invalid_request"
ERROR_NOT_IMPLEMENTED = "not_implemented"

#: What a pi client may reach for. Same reasoning as the ACP surface: pi is
#: interactive, so this is wider than the unattended surfaces — but it is still
#: an allowlist, not "everything registered".
PI_TOOLS = (
    "Read", "Glob", "Grep", "LS", "WebSearch", "WebFetch",
    "Write", "Edit", "Bash",
)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _model_ref(value: Any) -> Dict[str, str]:
    """Coerce whatever a client sent into pi's `{provider, id}`.

    Accepting a bare string here rather than rejecting it: pi's own clients
    send the object, but NeoMind's config holds a plain model name, and the
    composition root should not have to know the wire shape.
    """
    if isinstance(value, dict) and value.get("id"):
        return {"provider": str(value.get("provider") or "neomind"),
                "id": str(value["id"])}
    if isinstance(value, str) and value:
        return {"provider": "neomind", "id": value}
    return dict(DEFAULT_MODEL_REF)


@dataclass
class PiSession:
    """One pi session. `revision` is pi's optimistic-concurrency counter and
    has to increase on every observable change, or a client that reconnects
    cannot tell whether it missed anything."""

    id: str
    cwd: str
    name: Optional[str] = None
    model: Dict[str, str] = field(default_factory=lambda: dict(DEFAULT_MODEL_REF))
    thinking_level: str = "off"
    phase: str = PHASE_IDLE
    attached: bool = False
    locked: bool = False
    revision: int = 0
    created_at: int = field(default_factory=_now_ms)
    updated_at: int = field(default_factory=_now_ms)
    transcript: List[Dict[str, Any]] = field(default_factory=list)
    active_turn: Optional[str] = None

    def touch(self) -> None:
        self.revision += 1
        self.updated_at = _now_ms()

    def metadata(self) -> Dict[str, Any]:
        """`SessionMetadata` — what `ServerSnapshot.sessions` carries.

        A *different* shape from `snapshot()`, and much smaller: six fields,
        with the name under `sessionName`. Treating them as one thing produced
        a server snapshot pi rejected outright for additional properties.
        """
        out: Dict[str, Any] = {"id": self.id, "createdAt": self.created_at,
                               "updatedAt": self.updated_at}
        if self.name:
            out["sessionName"] = self.name
        if self.cwd:
            out["cwd"] = self.cwd
        return out

    def snapshot(self) -> Dict[str, Any]:
        """`SessionSnapshot` — the full per-session state.

        `queuedSteer` is always empty and its count always zero: steer is the
        one command NeoMind answers `not_implemented`, so nothing can queue.
        The fields are still present because the schema requires them, and a
        client that cannot parse the snapshot cannot attach at all.
        """
        out: Dict[str, Any] = {
            "id": self.id, "cwd": self.cwd or "/",
            "createdAt": self.created_at, "updatedAt": self.updated_at,
            "phase": self.phase, "model": dict(self.model or DEFAULT_MODEL_REF),
            "thinkingLevel": self.thinking_level,
            "attached": self.attached, "locked": self.locked,
            "revision": self.revision,
            "transcript": list(self.transcript),
            "queuedSteer": [],
            "queuedSteerCount": 0,
        }
        if self.name:
            out["name"] = self.name
        return out


def error(code: str, message: str) -> Dict[str, Any]:
    return {"code": code, "message": message}


def response(request_id: str, result: Any) -> Dict[str, Any]:
    return {"type": "response", "id": request_id, "ok": True, "result": result}


def failure(request_id: str, code: str, message: str) -> Dict[str, Any]:
    return {"type": "response", "id": request_id, "ok": False, "error": error(code, message)}


def event(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {"type": "event", "event": payload}


def progress_for(session_id: str, runtime_event: Any) -> Optional[Dict[str, Any]]:
    """One runtime event → one pi `session_progress`, or None.

    pi carries deltas as strings tagged by `kind`, which is the same split the
    frozen event set already makes — that agreement is why this adapter is a
    mapping rather than a reimplementation.
    """
    if isinstance(runtime_event, TextDelta):
        inner = {
            "type": "assistant_delta",
            "messageId": runtime_event.turn_id,
            "contentIndex": 0,
            "kind": "text",
            "delta": runtime_event.text,
        }
    elif isinstance(runtime_event, ThinkingDelta):
        inner = {
            "type": "assistant_delta",
            "messageId": runtime_event.turn_id,
            "contentIndex": 0,
            "kind": "thinking",
            "delta": runtime_event.text,
        }
    elif isinstance(runtime_event, ToolProposed):
        inner = {"type": "item_started", "item": _tool_item(
            runtime_event, status="running", is_error=False, text="",
        )}
    elif isinstance(runtime_event, ToolStarted):
        inner = {"type": "item_updated", "item": _tool_item(
            runtime_event, status="running", is_error=False, text="",
        )}
    elif isinstance(runtime_event, ToolFinished):
        # pi has no "refused" status either, so the distinction goes in the
        # content — the same accommodation ACP needed, for the same reason:
        # losing it tells the user their tool crashed.
        inner = {"type": "item_finished", "item": _tool_item(
            runtime_event,
            status="complete" if runtime_event.success else "error",
            is_error=not runtime_event.success,
            text=_tool_detail(runtime_event),
        )}
    else:
        return None

    return {"type": "session_progress", "sessionId": session_id, "progress": inner}


def _tool_item(source: Any, *, status: str, is_error: bool, text: str) -> Dict[str, Any]:
    """A `ToolTranscriptItem`, in pi's actual shape.

    Read from `schemas.ts` rather than assumed: it is a transcript *item* with
    `role`, `content` and `timestamp` — not the `{type, name, status}` object
    that seemed natural. pi's own validator rejected the invented one, which is
    the only reason this is right.
    """
    return {
        "id": source.call_id,
        "role": "tool",
        "toolCallId": source.call_id,
        "toolName": source.tool_name or "tool",
        "input": {},
        "content": ([{"type": "text", "text": text}] if text else []),
        "timestamp": _now_ms(),
        "status": status,
        "isError": is_error,
    }


def _tool_detail(finished: ToolFinished) -> str:
    if finished.success:
        return (finished.preview or "")[:2000]
    if finished.denied:
        return f"Refused: {finished.error or 'not permitted in this session'}"
    return finished.error or "Tool failed."


class PiProtocolServer:
    """Decoded message in, messages out. No socket, no session construction.

    `session_factory` is injected for the same reason it is on the ACP server:
    the command surface has to be exercisable without a provider, and a wrong
    field name in a snapshot is invisible until a real client refuses it.
    """

    def __init__(
        self,
        *,
        session_factory: Optional[Callable[[PiSession], Any]] = None,
        server_id: str = "neomind",
        models: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        self.server_id = server_id
        self.revision = 0
        self.sessions: Dict[str, PiSession] = {}
        self.models = models or []
        self._agent_sessions: Dict[str, Any] = {}
        self._session_factory = session_factory
        self._counter = 0

    # ── handshake ─────────────────────────────────────────────────────────

    def hello(self, client_version: int) -> Dict[str, Any]:
        """A version mismatch is refused here, not discovered later."""
        if client_version != PROTOCOL_VERSION:
            return {
                "type": "hello_error",
                "error": error(
                    ERROR_VERSION,
                    f"server speaks protocol {PROTOCOL_VERSION}, client offered {client_version}",
                ),
            }
        return {
            "type": "hello",
            "version": PROTOCOL_VERSION,
            "connectionId": f"{self.server_id}-conn-{self.revision}",
            "snapshot": self.server_snapshot(),
        }

    def server_snapshot(self) -> Dict[str, Any]:
        return {
            "serverId": self.server_id,
            "protocolVersion": PROTOCOL_VERSION,
            "revision": self.revision,
            "sessions": [s.metadata() for s in self.sessions.values()],
            "models": list(self.models),
        }

    # ── commands ──────────────────────────────────────────────────────────

    def handle(self, message: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Route one client message. Returns everything to send back."""
        kind = message.get("type")
        if kind == "hello":
            return [self.hello(int(message.get("version", -1)))]
        if kind != "request":
            return [failure("", ERROR_INVALID, f"unexpected message type {kind!r}")]

        request_id = str(message.get("id", ""))
        request = message.get("request") or {}
        command = request.get("command")
        handler = getattr(self, f"_cmd_{command}", None)
        if handler is None:
            return [failure(request_id, ERROR_INVALID, f"unknown command {command!r}")]
        return handler(request_id, request)

    def _cmd_list(self, request_id: str, _request: Dict[str, Any]) -> List[Dict[str, Any]]:
        return [response(request_id, {"sessions": [s.metadata() for s in self.sessions.values()]})]

    def _cmd_create(self, request_id: str, request: Dict[str, Any]) -> List[Dict[str, Any]]:
        self._counter += 1
        session = PiSession(
            id=f"{self.server_id}-{self._counter}",
            cwd=request.get("cwd") or "",
            name=request.get("name"),
            model=_model_ref(request.get("model")),
            thinking_level=request.get("thinkingLevel") or "off",
        )
        self.sessions[session.id] = session
        self.revision += 1
        return [
            response(request_id, {"session": session.snapshot()}),
            event({"type": "server_snapshot", "snapshot": self.server_snapshot()}),
        ]

    def _cmd_attach(self, request_id: str, request: Dict[str, Any]) -> List[Dict[str, Any]]:
        session = self.sessions.get(str(request.get("sessionId", "")))
        if session is None:
            return [failure(request_id, ERROR_NOT_FOUND, "no such session")]
        session.attached = True
        session.touch()
        return [
            response(request_id, {"session": session.snapshot()}),
            event({"type": "session_snapshot", "snapshot": session.snapshot()}),
        ]

    def _cmd_detach(self, request_id: str, request: Dict[str, Any]) -> List[Dict[str, Any]]:
        session = self.sessions.get(str(request.get("sessionId", "")))
        if session is None:
            return [failure(request_id, ERROR_NOT_FOUND, "no such session")]
        session.attached = False
        session.touch()
        return [response(request_id, {"session": session.snapshot()})]

    def _cmd_set_model(self, request_id: str, request: Dict[str, Any]) -> List[Dict[str, Any]]:
        session = self.sessions.get(str(request.get("sessionId", "")))
        if session is None:
            return [failure(request_id, ERROR_NOT_FOUND, "no such session")]
        session.model = _model_ref(request.get("model"))
        session.touch()
        return [
            response(request_id, {"session": session.snapshot()}),
            event({"type": "session_snapshot", "snapshot": session.snapshot()}),
        ]

    def _cmd_set_thinking(self, request_id: str, request: Dict[str, Any]) -> List[Dict[str, Any]]:
        session = self.sessions.get(str(request.get("sessionId", "")))
        if session is None:
            return [failure(request_id, ERROR_NOT_FOUND, "no such session")]
        session.thinking_level = str(request.get("thinkingLevel") or "off")
        session.touch()
        return [
            response(request_id, {"session": session.snapshot()}),
            event({"type": "session_snapshot", "snapshot": session.snapshot()}),
        ]

    def _cmd_abort(self, request_id: str, request: Dict[str, Any]) -> List[Dict[str, Any]]:
        session = self.sessions.get(str(request.get("sessionId", "")))
        if session is None:
            return [failure(request_id, ERROR_NOT_FOUND, "no such session")]
        session.phase = PHASE_IDLE
        session.touch()
        return [response(request_id, {"session": session.snapshot()})]

    def _cmd_steer(self, request_id: str, _request: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Mid-generation intervention, which NeoMind does not have.

        Answered honestly rather than approximated by cancel-and-resend: a
        client told a capability exists and then handed something else behaves
        as though it worked, and the user finds out from the transcript.
        """
        return [failure(
            request_id, ERROR_NOT_IMPLEMENTED,
            "steer is not supported: NeoMind cannot intervene mid-generation",
        )]

    def _cmd_prompt(self, request_id: str, request: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Validated synchronously; the turn itself is driven by `run_turn`.

        Split deliberately: a transport can acknowledge the request and then
        stream, and a test can check every rejection without running a model.
        """
        session = self.sessions.get(str(request.get("sessionId", "")))
        if session is None:
            return [failure(request_id, ERROR_NOT_FOUND, "no such session")]
        if session.phase == PHASE_TURN:
            return [failure(request_id, "busy", "session already has a turn in flight")]
        text = request.get("text")
        if not isinstance(text, str) or not text.strip():
            return [failure(request_id, ERROR_INVALID, "prompt text is required")]
        session.phase = PHASE_TURN
        session.touch()
        return [response(request_id, {"session": session.snapshot()})]

    # ── the turn ──────────────────────────────────────────────────────────

    async def run_turn(self, session_id: str, text: str):
        """Drive one turn, yielding messages for the transport to send."""
        session = self.sessions.get(session_id)
        if session is None:
            return
        if self._session_factory is None:
            session.phase = PHASE_IDLE
            session.touch()
            yield event({
                "type": "session_progress", "sessionId": session_id,
                "progress": {"type": "item_finished", "item": {
                    "type": "error", "id": "no-factory",
                    "detail": "no session factory configured",
                }},
            })
            return

        agent_session = self._session_factory(session)
        self._agent_sessions[session_id] = agent_session
        try:
            async for runtime_event in agent_session.run_turn(text):
                session.active_turn = getattr(runtime_event, "turn_id", None)
                if isinstance(runtime_event, (TurnFinished, TurnFailed)):
                    break
                progress = progress_for(session_id, runtime_event)
                if progress is not None:
                    yield event(progress)
        finally:
            session.phase = PHASE_IDLE
            session.active_turn = None
            session.touch()
            yield event({"type": "session_snapshot", "snapshot": session.snapshot()})
