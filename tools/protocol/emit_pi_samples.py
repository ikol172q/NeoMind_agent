"""Emit one sample of every pi message shape, for schema validation.

Kept next to the validator so the two cannot drift: adding a message type
means adding it here, and the validator then checks it.
"""
import json

from agent.integration.pi_server import PiProtocolServer, progress_for
from agent.runtime.events import (
    TextDelta, ThinkingDelta, ToolFinished, ToolProposed, ToolStarted,
)


def _ev(cls, **kw):
    return cls(session_id="s", turn_id="t1", sequence=0, **kw)


def main() -> None:
    server = PiProtocolServer(server_id="neomind")
    hello = server.handle({"type": "hello", "version": 1})[0]
    created = server.handle({
        "type": "request", "id": "r1",
        "request": {"command": "create", "cwd": "/tmp", "model": "deepseek-v4-flash"},
    })
    session_id = created[0]["result"]["session"]["id"]
    # After a prompt, so the snapshot carries the in-turn phase — the value
    # that was wrong and only observable once a user had said something.
    server.handle({
        "type": "request", "id": "r2",
        "request": {"command": "prompt", "sessionId": session_id, "text": "hi"},
    })

    print(json.dumps({
        "ServerHello": hello,
        "ServerSnapshot": server.server_snapshot(),
        "SessionSnapshot": server.sessions[session_id].snapshot(),
        "TranscriptProgress_text":
            progress_for(session_id, _ev(TextDelta, text="hi"))["progress"],
        "TranscriptProgress_thinking":
            progress_for(session_id, _ev(ThinkingDelta, text="hm"))["progress"],
        "TranscriptProgress_started":
            progress_for(session_id, _ev(ToolProposed, call_id="c",
                                         tool_name="Read", preview="p"))["progress"],
        "TranscriptProgress_running":
            progress_for(session_id, _ev(ToolStarted, call_id="c",
                                         tool_name="Read"))["progress"],
        "TranscriptProgress_finished":
            progress_for(session_id, _ev(ToolFinished, call_id="c", tool_name="Read",
                                         success=False, denied=True,
                                         error="not in snapshot"))["progress"],
    }))


if __name__ == "__main__":
    main()
