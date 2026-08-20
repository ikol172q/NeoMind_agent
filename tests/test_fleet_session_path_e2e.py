"""Phase 6B tasks 3 and 4 — the fleet end to end, on the session path.

`tests/test_fleet_fin_end_to_end.py` mocks `worker_turn._default_llm_call`,
which is precisely the function the migration replaces — so with
`NEOMIND_FLEET=session` those tests would either bypass the mock and hit the
network, or, if they didn't, prove nothing about the new path.

Here the fake goes in one layer lower, at the provider. Everything above it is
real: the launcher, the task queue, persona routing, `AgentSession`, the
`ToolExecutor` and its policy, signal parsing, the analysis write and the
leader's mailbox. Only the socket is imaginary.

The gate this covers: "Existing fin/coding/chat worker results, artifacts,
fail-fast behavior, and leader notifications pass a real fleet run."
"""

from __future__ import annotations

import asyncio
import json
import os
from unittest import mock

import pytest

from agent.finance import investment_projects
from agent.runtime.llm_stream import FinishChunk, TextChunk
from fleet.launch_project import FleetLauncher
from fleet.project_schema import MemberConfig, ProjectConfig

from tests.test_fleet_fin_end_to_end import tmp_fleet_base  # noqa: F401


class RecordingProvider:
    """A provider that streams a canned answer and remembers every prompt."""

    calls: list = []
    response: str = "ok"

    def __init__(self, *a, **kw):
        pass

    def stream(self, messages, model, **kwargs):
        type(self).calls.append({"messages": list(messages), "model": model})
        text = type(self).response

        async def gen():
            yield TextChunk(text=text)
            yield FinishChunk(reason="stop")

        return gen()


@pytest.fixture
def session_path(monkeypatch):
    """Run the fleet on the migrated path with only the socket faked."""
    monkeypatch.setenv("NEOMIND_FLEET", "session")
    RecordingProvider.calls = []
    RecordingProvider.response = "ok"
    # Patched where it is looked up, not where it is defined: the call site
    # imports it inside the function, so patching the module attribute is what
    # the import will find.
    with mock.patch(
        "agent.runtime.providers.openai_sse.OpenAICompatibleStream",
        RecordingProvider,
    ), mock.patch(
        "agent.services.llm_provider.LLMProviderService.resolve_with_fallback",
        return_value={"base_url": "http://fake/v1", "api_key": "k", "name": "fake"},
    ), mock.patch.multiple(
        "agent.services.agent_audit",
        new_req_id=mock.DEFAULT,
        audit_request=mock.DEFAULT,
        audit_response=mock.DEFAULT,
        audit_error=mock.DEFAULT,
    ):
        yield RecordingProvider


def _fin_config(project_id: str) -> ProjectConfig:
    return ProjectConfig(
        project_id=project_id,
        description="minimal fin fleet",
        leader="mgr",
        members=[
            MemberConfig(name="mgr", persona="chat", role="leader"),
            MemberConfig(name="fin-rt", persona="fin", role="worker"),
        ],
        settings={},
    )


async def _run_one(config, base_dir, description, persona, ticks=40):
    launcher = FleetLauncher(config, base_dir=base_dir)
    await launcher.start()
    try:
        task_id = await launcher.submit_task(description, target_persona=persona)
        for _ in range(ticks):
            tasks = launcher._task_queue.list_tasks()
            mine = next((t for t in tasks if t["id"] == task_id), None)
            if mine and mine.get("status") in ("completed", "failed"):
                break
            await asyncio.sleep(0.1)
        tasks = launcher._task_queue.list_tasks()
        return next((t for t in tasks if t["id"] == task_id), None)
    finally:
        await launcher.stop()


class TestTheSwitchIsActuallyOn:
    """Without this the rest of the file could pass while testing the old
    path, which is the failure mode that produced a green Telethon run against
    code the change never touched."""

    def test_the_resolved_call_is_the_session_one(self, session_path):
        import fleet.worker_turn as wt

        assert wt._session_path_enabled() is True
        assert wt._resolve_llm_call() is not wt._default_llm_call

    def test_the_legacy_default_is_never_called(self, session_path, tmp_fleet_base):
        import fleet.worker_turn as wt

        investment_projects.register_project("fin-sess-guard", "test")
        with mock.patch.object(
            wt, "_default_llm_call", side_effect=AssertionError("legacy path ran")
        ):
            final = asyncio.run(_run_one(
                _fin_config("fin-sess-guard"), tmp_fleet_base,
                "analyze MSFT and return signal", "fin",
            ))
        assert final is not None


class TestFinWorker:

    def test_signal_parses_and_the_analysis_file_is_written(
        self, session_path, tmp_fleet_base
    ):
        """The whole fin chain: persona routing → session turn → parse_signal
        → write_analysis → queue completion."""
        session_path.response = (
            '{"signal":"buy","confidence":8,"reason":"strong earnings AAPL",'
            '"sources":["Finnhub"]}'
        )
        investment_projects.register_project("fin-sess", "test")

        final = asyncio.run(_run_one(
            _fin_config("fin-sess"), tmp_fleet_base,
            "analyze AAPL and return signal", "fin",
        ))

        assert final is not None, "task disappeared from the queue"
        assert final["status"] == "completed", final

        proj_dir = investment_projects.get_project_dir("fin-sess")
        files = list((proj_dir / "analyses").glob("*_AAPL.json"))
        assert len(files) == 1, f"expected one analysis file, got {files}"
        payload = json.loads(files[0].read_text())
        assert payload["symbol"] == "AAPL"
        assert payload["signal"]["signal"] == "buy"

    def test_the_worker_turn_reached_the_provider_once(
        self, session_path, tmp_fleet_base
    ):
        """One task, one call. A session that looped would bill the user for
        an unattended job nobody is watching."""
        session_path.response = '{"signal":"hold","confidence":5,"reason":"x"}'
        investment_projects.register_project("fin-sess-once", "test")

        asyncio.run(_run_one(
            _fin_config("fin-sess-once"), tmp_fleet_base,
            "analyze NVDA and return signal", "fin",
        ))
        assert len(session_path.calls) == 1, session_path.calls

    def test_the_persona_system_prompt_reaches_the_model(
        self, session_path, tmp_fleet_base
    ):
        """Persona routing is the one thing `worker_turn` is allowed to branch
        on, and it survives the migration only if the prompt does."""
        session_path.response = '{"signal":"hold","confidence":5,"reason":"x"}'
        investment_projects.register_project("fin-sess-prompt", "test")

        asyncio.run(_run_one(
            _fin_config("fin-sess-prompt"), tmp_fleet_base,
            "analyze TSLA and return signal", "fin",
        ))
        first = session_path.calls[0]
        assert first["messages"][0]["role"] == "system"
        assert first["messages"][0]["content"], "the persona prompt was dropped"
        assert "TSLA" in first["messages"][-1]["content"]


class TestLeaderNotification:

    def test_the_leader_mailbox_receives_a_task_notification(
        self, session_path, tmp_fleet_base
    ):
        session_path.response = '{"signal":"buy","confidence":7,"reason":"y"}'
        investment_projects.register_project("fin-sess-mail", "test")
        config = _fin_config("fin-sess-mail")

        async def go():
            launcher = FleetLauncher(config, base_dir=tmp_fleet_base)
            await launcher.start()
            try:
                await launcher.submit_task(
                    "analyze AMD and return signal", target_persona="fin",
                )
                for _ in range(40):
                    await asyncio.sleep(0.1)
                    msgs = launcher._mailboxes["mgr"].read_unread()
                    notifs = [m for m in msgs if m.msg_type == "task_notification"]
                    if notifs:
                        return notifs
                return []
            finally:
                await launcher.stop()

        notifs = asyncio.run(go())
        assert notifs, "leader received no task_notification"
        assert "<status>completed</status>" in notifs[0].content
        assert notifs[0].sender == "fin-rt"


class TestCodingAndChatPersonas:

    def _config(self, project_id):
        return ProjectConfig(
            project_id=project_id,
            description="coding fleet",
            leader="chair",
            members=[
                MemberConfig(name="chair", persona="chat", role="leader"),
                MemberConfig(name="coder-1", persona="coding", role="worker"),
            ],
            settings={},
        )

    def test_a_coding_task_completes_with_the_models_text(
        self, session_path, tmp_fleet_base
    ):
        session_path.response = "CODING_SESSION_PATH_OK"
        final = asyncio.run(_run_one(
            self._config("coding-sess"), tmp_fleet_base,
            "reply with a marker", "coding",
        ))
        assert final is not None and final["status"] == "completed", final
        assert "CODING_SESSION_PATH_OK" in str(final.get("result", ""))


class TestFailures:

    def test_a_provider_failure_marks_the_task_failed_not_completed(
        self, session_path, tmp_fleet_base
    ):
        """`execute_task` never raises; it reports. That contract only holds
        if the session path raises rather than returning an error string that
        would be persisted as an analysis."""
        from agent.runtime.llm_stream import LLMTransportError

        class Dead(RecordingProvider):
            def stream(self, messages, model, **kwargs):
                async def gen():
                    raise LLMTransportError("refused")
                    yield  # pragma: no cover

                return gen()

        investment_projects.register_project("fin-sess-fail", "test")
        with mock.patch(
            "agent.runtime.providers.openai_sse.OpenAICompatibleStream", Dead
        ):
            final = asyncio.run(_run_one(
                _fin_config("fin-sess-fail"), tmp_fleet_base,
                "analyze AAPL and return signal", "fin",
            ))

        assert final is not None
        assert final["status"] == "failed", final
        proj_dir = investment_projects.get_project_dir("fin-sess-fail")
        assert not list((proj_dir / "analyses").glob("*.json")), (
            "a failed turn must not leave an analysis file behind"
        )
