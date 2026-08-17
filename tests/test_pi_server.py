"""Phase 7 — NeoMind over pi's session protocol.

These assert what we believe the protocol requires. What pi *actually*
requires is checked separately by `tools/protocol/validate_pi_messages.mjs`
against its own TypeBox schemas, and on the first run the two disagreed on
five points — every one of which would have reached a real client. The most
telling: `phase: "busy"` is not a legal value, and it only appears after a
prompt, so a session would have looked fine until the user said something.

Where a shape is pinned here, it is pinned because pi's validator confirmed it.
"""

from __future__ import annotations

import asyncio

import pytest

from agent.integration.pi_server import (
    DEFAULT_MODEL_REF,
    ERROR_NOT_FOUND,
    ERROR_NOT_IMPLEMENTED,
    ERROR_VERSION,
    PHASE_IDLE,
    PHASE_TURN,
    PI_TOOLS,
    PROTOCOL_VERSION,
    PiProtocolServer,
    progress_for,
)
from agent.runtime.events import (
    TextDelta, ThinkingDelta, ToolFinished, ToolProposed, ToolStarted,
    TurnFailed, TurnFinished,
)


def ev(cls, **kw):
    return cls(session_id="s", turn_id="t1", sequence=0, **kw)


@pytest.fixture
def server():
    return PiProtocolServer(server_id="neomind")


def create(server, **overrides):
    request = {"command": "create", "cwd": "/tmp", "model": "m"}
    request.update(overrides)
    out = server.handle({"type": "request", "id": "r", "request": request})
    return out[0]["result"]["session"]["id"]


class TestHandshake:

    def test_a_matching_version_gets_a_hello_with_a_snapshot(self, server):
        reply = server.handle({"type": "hello", "version": PROTOCOL_VERSION})[0]
        assert reply["type"] == "hello"
        assert reply["snapshot"]["protocolVersion"] == PROTOCOL_VERSION

    def test_a_mismatched_version_is_refused_at_the_handshake(self, server):
        """Refused here rather than discovered later on a shape mismatch,
        where the error would name a field instead of the real cause."""
        reply = server.handle({"type": "hello", "version": 99})[0]
        assert reply["type"] == "hello_error"
        assert reply["error"]["code"] == ERROR_VERSION

    def test_an_unexpected_message_type_is_rejected(self, server):
        reply = server.handle({"type": "nonsense"})[0]
        assert reply["ok"] is False


class TestSessions:

    def test_create_returns_a_snapshot_and_announces_it(self, server):
        out = server.handle({
            "type": "request", "id": "r1",
            "request": {"command": "create", "cwd": "/tmp"},
        })
        assert out[0]["ok"] is True
        assert out[1]["event"]["type"] == "server_snapshot"

    def test_metadata_and_snapshot_are_different_shapes(self, server):
        """pi has two: `SessionMetadata` for the server snapshot's list, and
        `SessionSnapshot` for the session itself. Serving one for both makes
        the server snapshot fail validation for additional properties."""
        sid = create(server)
        session = server.sessions[sid]
        assert set(session.metadata()) < set(session.snapshot())
        assert "transcript" not in session.metadata()
        assert "name" not in session.metadata(), "the metadata field is sessionName"

    def test_a_snapshot_carries_the_steer_queue_fields(self, server):
        """Required by the schema. Without them a client cannot attach at
        all — not a degraded experience, no session."""
        snapshot = server.sessions[create(server)].snapshot()
        assert snapshot["queuedSteer"] == []
        assert snapshot["queuedSteerCount"] == 0

    def test_the_model_is_an_object_not_a_name(self, server):
        snapshot = server.sessions[create(server, model="deepseek-v4-flash")].snapshot()
        assert snapshot["model"] == {"provider": "neomind", "id": "deepseek-v4-flash"}

    def test_a_model_object_is_passed_through(self, server):
        sid = create(server, model={"provider": "anthropic", "id": "x"})
        assert server.sessions[sid].snapshot()["model"]["provider"] == "anthropic"

    def test_a_missing_model_falls_back_rather_than_emitting_an_invalid_ref(self, server):
        sid = create(server, model=None)
        assert server.sessions[sid].snapshot()["model"] == DEFAULT_MODEL_REF

    def test_attach_and_detach_flip_the_flag_and_bump_the_revision(self, server):
        sid = create(server)
        before = server.sessions[sid].revision
        server.handle({"type": "request", "id": "a",
                       "request": {"command": "attach", "sessionId": sid}})
        assert server.sessions[sid].attached is True
        assert server.sessions[sid].revision > before, (
            "a client that reconnects uses the revision to tell what it missed"
        )
        server.handle({"type": "request", "id": "d",
                       "request": {"command": "detach", "sessionId": sid}})
        assert server.sessions[sid].attached is False

    def test_list_reports_every_session(self, server):
        create(server)
        create(server)
        out = server.handle({"type": "request", "id": "l", "request": {"command": "list"}})
        assert len(out[0]["result"]["sessions"]) == 2

    @pytest.mark.parametrize("command", [
        "attach", "detach", "abort", "set_model", "set_thinking", "prompt",
    ])
    def test_an_unknown_session_is_not_found(self, server, command):
        out = server.handle({
            "type": "request", "id": "x",
            "request": {"command": command, "sessionId": "nope", "text": "hi",
                        "model": "m", "thinkingLevel": "off"},
        })
        assert out[0]["error"]["code"] == ERROR_NOT_FOUND

    def test_an_unknown_command_is_rejected(self, server):
        out = server.handle({"type": "request", "id": "x",
                             "request": {"command": "teleport"}})
        assert out[0]["ok"] is False


class TestPhases:
    """`busy` is not a phase pi knows. The legal set is idle | turn |
    compaction | branch_summary | retry, and the wrong value only reaches a
    client after a prompt — so the session looks healthy until the user
    speaks."""

    def test_a_new_session_is_idle(self, server):
        assert server.sessions[create(server)].phase == PHASE_IDLE

    def test_a_prompt_moves_it_to_turn_not_busy(self, server):
        sid = create(server)
        server.handle({"type": "request", "id": "p",
                       "request": {"command": "prompt", "sessionId": sid, "text": "hi"}})
        assert server.sessions[sid].phase == PHASE_TURN
        assert server.sessions[sid].phase != "busy"

    def test_a_second_prompt_while_one_is_in_flight_is_refused(self, server):
        sid = create(server)
        req = {"command": "prompt", "sessionId": sid, "text": "hi"}
        server.handle({"type": "request", "id": "p1", "request": req})
        out = server.handle({"type": "request", "id": "p2", "request": req})
        assert out[0]["ok"] is False

    def test_abort_returns_it_to_idle(self, server):
        sid = create(server)
        server.handle({"type": "request", "id": "p",
                       "request": {"command": "prompt", "sessionId": sid, "text": "hi"}})
        server.handle({"type": "request", "id": "a",
                       "request": {"command": "abort", "sessionId": sid}})
        assert server.sessions[sid].phase == PHASE_IDLE

    def test_empty_prompt_text_is_refused(self, server):
        sid = create(server)
        out = server.handle({"type": "request", "id": "p",
                             "request": {"command": "prompt", "sessionId": sid, "text": "   "}})
        assert out[0]["ok"] is False
        assert server.sessions[sid].phase == PHASE_IDLE, "a refused prompt must not lock the session"


class TestSteerIsAnsweredHonestly:

    def test_steer_reports_not_implemented(self, server):
        """NeoMind cannot intervene mid-generation. Approximating it with
        cancel-and-resend would behave as though it had worked, and the user
        would find out from the transcript."""
        sid = create(server)
        out = server.handle({"type": "request", "id": "s",
                             "request": {"command": "steer", "sessionId": sid, "text": "no"}})
        assert out[0]["error"]["code"] == ERROR_NOT_IMPLEMENTED


class TestProgressMapping:

    def test_text_and_thinking_are_tagged_deltas(self):
        text = progress_for("s1", ev(TextDelta, text="hi"))["progress"]
        think = progress_for("s1", ev(ThinkingDelta, text="hm"))["progress"]
        assert text["kind"] == "text" and text["delta"] == "hi"
        assert think["kind"] == "thinking"

    def test_a_tool_becomes_a_transcript_item_not_an_invented_shape(self):
        """pi wants a transcript item — role, toolCallId, content, timestamp,
        isError — not the {type, name, status} object that reads naturally."""
        item = progress_for("s1", ev(ToolProposed, call_id="c1",
                                     tool_name="Read", preview="p"))["progress"]["item"]
        assert item["role"] == "tool"
        assert item["toolCallId"] == "c1"
        assert item["toolName"] == "Read"
        assert isinstance(item["content"], list)
        assert item["isError"] is False
        assert "timestamp" in item

    def test_a_started_tool_updates_rather_than_starts_again(self):
        assert progress_for("s1", ev(ToolStarted, call_id="c", tool_name="Read"))[
            "progress"]["type"] == "item_updated"

    def test_a_successful_tool_finishes_without_error(self):
        item = progress_for("s1", ev(ToolFinished, call_id="c", tool_name="Read",
                                     success=True, preview="data"))["progress"]["item"]
        assert item["status"] == "complete" and item["isError"] is False

    def test_a_refusal_says_so_even_though_the_status_cannot(self):
        """pi has no refused status either, so it goes in the content — the
        same accommodation ACP needed, for the same reason."""
        item = progress_for("s1", ev(ToolFinished, call_id="c", tool_name="Bash",
                                     success=False, denied=True,
                                     error="not in snapshot"))["progress"]["item"]
        assert item["isError"] is True
        assert "Refused" in item["content"][0]["text"]

    def test_a_genuine_failure_does_not_claim_refusal(self):
        item = progress_for("s1", ev(ToolFinished, call_id="c", tool_name="Read",
                                     success=False, error="No such file"))["progress"]["item"]
        assert "Refused" not in item["content"][0]["text"]

    def test_lifecycle_events_produce_no_progress(self):
        assert progress_for("s1", ev(TurnFinished, response="x")) is None
        assert progress_for("s1", ev(TurnFailed, error_code="e", message="m",
                                     retryable=False)) is None


class TestTurn:

    def test_a_turn_streams_progress_and_returns_to_idle(self, server):
        class FakeSession:
            def run_turn(self, text):
                async def gen():
                    yield ev(TextDelta, text="hello")
                    yield ev(TurnFinished, response="hello")
                return gen()

        server._session_factory = lambda s: FakeSession()
        sid = create(server)
        server.handle({"type": "request", "id": "p",
                       "request": {"command": "prompt", "sessionId": sid, "text": "hi"}})

        async def go():
            return [m async for m in server.run_turn(sid, "hi")]

        messages = asyncio.run(go())
        kinds = [m["event"]["type"] for m in messages]
        assert "session_progress" in kinds
        assert kinds[-1] == "session_snapshot"
        assert server.sessions[sid].phase == PHASE_IDLE

    def test_a_failing_turn_still_releases_the_session(self, server):
        """Left in `turn`, the session would refuse every later prompt."""
        class Exploding:
            def run_turn(self, text):
                async def gen():
                    yield ev(TextDelta, text="partial")
                    raise RuntimeError("provider died")
                return gen()

        server._session_factory = lambda s: Exploding()
        sid = create(server)

        async def go():
            return [m async for m in server.run_turn(sid, "hi")]

        with pytest.raises(RuntimeError):
            asyncio.run(go())
        assert server.sessions[sid].phase == PHASE_IDLE


class TestCapabilityPolicy:

    def test_the_tool_list_is_an_allowlist(self):
        assert len(PI_TOOLS) < 20
        for name in ("TeamDelete", "SendMessage", "CronCreate"):
            assert name not in PI_TOOLS
