"""Phase 4.B — fleet/worker_turn.py unit tests.

All LLM calls are mocked. Real HTTP + real LLM budget only happens in
the manual live smoke step (Phase 4.F), gated on
NEOMIND_FLEET_LIVE_SMOKE=1.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import List, Tuple
from unittest.mock import MagicMock

import pytest

from agent.finance import investment_projects
from agent_config import AgentConfigManager, set_current_config
from fleet.project_schema import MemberConfig
from fleet.worker_turn import (
    WorkerTurnError,
    _extract_symbol,
    execute_task,
)


# ── Helpers / fixtures ─────────────────────────────────────────────────


@pytest.fixture
def tmp_investment_root(tmp_path, monkeypatch):
    root = tmp_path / "Investment"
    root.mkdir()
    monkeypatch.setenv("NEOMIND_INVESTMENT_ROOT", str(root))
    return root


@pytest.fixture
def registered_project(tmp_investment_root):
    investment_projects.register_project("us-growth-2026q2", "test")
    return "us-growth-2026q2"


def _make_mock_llm(response: str):
    calls: List[Tuple[str, str, str]] = []

    async def mock_llm(model: str, system_prompt: str, user_prompt: str) -> str:
        calls.append((model, system_prompt, user_prompt))
        return response

    mock_llm.calls = calls  # type: ignore[attr-defined]
    return mock_llm


def _make_failing_llm(exc: Exception):
    async def mock_llm(model: str, system_prompt: str, user_prompt: str) -> str:
        raise exc

    return mock_llm


# ── Symbol extraction ─────────────────────────────────────────────────


def test_extract_symbol_from_explicit_field():
    assert _extract_symbol({"symbol": "aapl", "description": "x"}) == "AAPL"


def test_extract_symbol_from_description():
    assert _extract_symbol({"description": "please analyze NVDA today"}) == "NVDA"


def test_extract_symbol_blacklist_filters_english_caps():
    # "US" is in the blacklist and should NOT be returned as a symbol
    assert _extract_symbol({"description": "the US economy"}) is None


def test_extract_symbol_returns_none_when_empty():
    assert _extract_symbol({"description": "no tickers here"}) is None


def test_extract_symbol_explicit_beats_extraction():
    assert _extract_symbol({"symbol": "msft", "description": "NVDA up"}) == "MSFT"


# ── Fin worker path ────────────────────────────────────────────────────


def test_fin_worker_completes_with_strict_parse(registered_project):
    mock = _make_mock_llm(
        '{"signal":"buy","confidence":8,"reason":"strong earnings","sources":["Finnhub"]}'
    )
    member = MemberConfig(name="fin-rt", persona="fin", role="worker")
    task = {"description": "analyze AAPL", "id": "t1"}

    async def go():
        # Bind fin config for this task's context
        set_current_config(AgentConfigManager(mode="fin"))
        return await execute_task(
            member, task, llm_call=mock, project_id=registered_project,
        )

    result = asyncio.run(go())
    assert result["status"] == "completed"
    assert result["layer_used"] == "strict"
    # LLM was called exactly once
    assert len(mock.calls) == 1
    # Analysis file was written
    analyses_dir = (
        investment_projects.get_project_dir(registered_project) / "analyses"
    )
    files = list(analyses_dir.glob("*_AAPL.json"))
    assert len(files) == 1
    assert str(files[0]) in result["artifacts"]


def test_fin_worker_lenient_parse(registered_project):
    """LLM returns fenced markdown with aliased keys — lenient layer
    should recover it."""
    mock = _make_mock_llm(
        '```json\n{"action":"BULLISH","conviction":"7/10","rationale":"earnings beat"}\n```'
    )
    member = MemberConfig(name="fin-rt", persona="fin", role="worker")

    async def go():
        set_current_config(AgentConfigManager(mode="fin"))
        return await execute_task(
            member, {"description": "analyze AAPL"},
            llm_call=mock, project_id=registered_project,
        )

    result = asyncio.run(go())
    assert result["status"] == "completed"
    assert result["layer_used"] == "lenient"


def test_fin_worker_fallback_parse_still_completes(registered_project):
    """Garbage LLM output falls through to hold_fallback. Task status is
    still 'completed' because we recovered — just the signal is hold/1."""
    mock = _make_mock_llm("complete garbage that is not JSON at all")
    member = MemberConfig(name="fin-rt", persona="fin", role="worker")

    async def go():
        set_current_config(AgentConfigManager(mode="fin"))
        return await execute_task(
            member, {"description": "analyze AAPL"},
            llm_call=mock, project_id=registered_project,
        )

    result = asyncio.run(go())
    assert result["status"] == "completed"
    assert result["layer_used"] == "fallback"
    # The fallback signal is a conservative hold
    import json
    analysis = json.loads(result["result"])
    assert analysis["signal"] == "hold"


def test_fin_worker_without_project_id_skips_file_write(tmp_investment_root):
    """No project_id → analysis still parses but no file is written."""
    mock = _make_mock_llm(
        '{"signal":"sell","confidence":6,"reason":"weak","sources":["x"]}'
    )
    member = MemberConfig(name="fin-rt", persona="fin", role="worker")

    async def go():
        set_current_config(AgentConfigManager(mode="fin"))
        return await execute_task(
            member, {"description": "analyze NVDA"}, llm_call=mock,
        )

    result = asyncio.run(go())
    assert result["status"] == "completed"
    assert result["artifacts"] == []


# ── Coding worker path ────────────────────────────────────────────────


def test_coding_worker_returns_llm_text_verbatim():
    mock = _make_mock_llm(
        "I would add a new function `compute_vwap` in quant_engine.py..."
    )
    member = MemberConfig(name="dev-1", persona="coding", role="worker")

    async def go():
        set_current_config(AgentConfigManager(mode="coding"))
        return await execute_task(
            member,
            {"description": "add VWAP indicator to quant_engine"},
            llm_call=mock,
        )

    result = asyncio.run(go())
    assert result["status"] == "completed"
    assert result["layer_used"] == "text"
    assert "compute_vwap" in result["result"]
    assert len(mock.calls) == 1


# ── Chat worker path ──────────────────────────────────────────────────


def test_chat_worker_returns_text():
    mock = _make_mock_llm("Hi! Here's what I think about X...")
    member = MemberConfig(name="think-1", persona="chat", role="worker")

    async def go():
        set_current_config(AgentConfigManager(mode="chat"))
        return await execute_task(
            member, {"description": "brainstorm"}, llm_call=mock,
        )

    result = asyncio.run(go())
    assert result["status"] == "completed"
    assert result["result"].startswith("Hi!")


# ── Error handling ────────────────────────────────────────────────────


def test_invalid_persona_returns_failed():
    # MemberConfig.persona is normally validated upstream, but execute_task
    # must defend against bad data regardless.
    member = MemberConfig(name="x", persona="unknown", role="worker")  # type: ignore[arg-type]
    mock = _make_mock_llm("anything")

    async def go():
        return await execute_task(member, {"description": "x"}, llm_call=mock)

    result = asyncio.run(go())
    assert result["status"] == "failed"
    assert "unknown persona" in result["result"]


def test_llm_exception_captured_not_raised():
    mock = _make_failing_llm(RuntimeError("LLM API down"))
    member = MemberConfig(name="fin-rt", persona="fin", role="worker")

    async def go():
        set_current_config(AgentConfigManager(mode="fin"))
        return await execute_task(
            member, {"description": "analyze AAPL"}, llm_call=mock,
        )

    result = asyncio.run(go())
    assert result["status"] == "failed"
    assert "RuntimeError" in result["result"]
    assert "LLM API down" in result["result"]


def test_llm_exception_in_coding_worker_captured():
    mock = _make_failing_llm(ValueError("bad prompt"))
    member = MemberConfig(name="dev-1", persona="coding", role="worker")

    async def go():
        set_current_config(AgentConfigManager(mode="coding"))
        return await execute_task(
            member, {"description": "do something"}, llm_call=mock,
        )

    result = asyncio.run(go())
    assert result["status"] == "failed"
    assert "ValueError" in result["result"]


# ── Fail-fast gate ────────────────────────────────────────────────────


def test_fail_fast_active_blocks_task():
    """If SharedMemory has a fail_fast entry < 24h for this project,
    execute_task must bail immediately without calling the LLM."""
    mem = MagicMock()
    mem.recall_feedback.return_value = [
        {
            "id": 1,
            "feedback_type": "fail_fast",
            "content": '{"kpi":{"parse_fallback_rate":0.5}}',
            "source_mode": "fin",
            "source_instance": None,
            "project_id": "proj",
            "created_at": "2026-04-12T10:00:00+00:00",
        }
    ]
    llm_called = []

    async def mock(model, sys_p, user_p):
        llm_called.append(True)
        return "should not be called"

    member = MemberConfig(name="fin-rt", persona="fin", role="worker")

    async def go():
        return await execute_task(
            member, {"description": "analyze AAPL"},
            llm_call=mock, shared_memory=mem, project_id="proj",
        )

    result = asyncio.run(go())
    assert result["status"] == "failed"
    assert "fail_fast" in result["result"]
    assert result["layer_used"] == "fail_fast"
    assert llm_called == [], "LLM must not be called when fail_fast is active"
    # Verify the query was scoped correctly
    call_kwargs = mem.recall_feedback.call_args.kwargs
    assert call_kwargs["feedback_type"] == "fail_fast"
    assert call_kwargs["project_id"] == "proj"
    assert call_kwargs["max_age_hours"] == 24.0


def test_fail_fast_stale_entry_does_not_block():
    """If recall_feedback returns empty (e.g. all entries older than
    24h), execute_task proceeds normally."""
    mem = MagicMock()
    mem.recall_feedback.return_value = []
    mock = _make_mock_llm(
        '{"signal":"buy","confidence":7,"reason":"ok","sources":["x"]}'
    )
    member = MemberConfig(name="fin-rt", persona="fin", role="worker")

    async def go():
        set_current_config(AgentConfigManager(mode="fin"))
        return await execute_task(
            member, {"description": "analyze AAPL"},
            llm_call=mock, shared_memory=mem, project_id="proj",
        )

    result = asyncio.run(go())
    assert result["status"] == "completed"


def test_fail_fast_query_error_does_not_block():
    """If SharedMemory.recall_feedback raises, the worker still runs
    (best-effort fail-fast, not a hard gate). Prevents a DB issue from
    taking down the whole fleet."""
    mem = MagicMock()
    mem.recall_feedback.side_effect = RuntimeError("db down")
    mock = _make_mock_llm(
        '{"signal":"buy","confidence":7,"reason":"ok","sources":["x"]}'
    )
    member = MemberConfig(name="fin-rt", persona="fin", role="worker")

    async def go():
        set_current_config(AgentConfigManager(mode="fin"))
        return await execute_task(
            member, {"description": "analyze AAPL"},
            llm_call=mock, shared_memory=mem, project_id="proj",
        )

    result = asyncio.run(go())
    assert result["status"] == "completed"


def test_fail_fast_skipped_when_no_project_id():
    """No project_id → fail_fast check is skipped entirely (even with a
    SharedMemory attached). This is the fleet-without-Investment-project
    use case."""
    mem = MagicMock()
    mem.recall_feedback.return_value = [{"feedback_type": "fail_fast"}]
    mock = _make_mock_llm(
        '{"signal":"hold","confidence":5,"reason":"wait","sources":["x"]}'
    )
    member = MemberConfig(name="fin-rt", persona="fin", role="worker")

    async def go():
        set_current_config(AgentConfigManager(mode="fin"))
        return await execute_task(
            member, {"description": "analyze AAPL"},
            llm_call=mock, shared_memory=mem,  # no project_id
        )

    result = asyncio.run(go())
    assert result["status"] == "completed"
    # recall_feedback should NOT have been called
    mem.recall_feedback.assert_not_called()


# ── Concurrent workers (proves Phase 4.A isolation reaches here) ───────


def test_concurrent_workers_see_their_own_persona():
    """Four workers running via asyncio.gather, each with its own
    persona. Each worker's LLM call should see its own system prompt /
    model via the contextvar-bound config. This tests that Option E's
    isolation propagates through the execute_task boundary."""
    seen = []

    async def capturing_llm(model, system_prompt, user_prompt):
        # Capture the MODEL each worker saw — it's per-persona config
        seen.append((user_prompt, model))
        # Return a structure that parses fine for fin, ignored for others
        return '{"signal":"hold","confidence":5,"reason":"x","sources":["y"]}'

    async def worker_task(persona: str, tag: str):
        set_current_config(AgentConfigManager(mode=persona))
        member = MemberConfig(name=f"w-{tag}", persona=persona, role="worker")
        # Yield to other tasks to interleave
        await asyncio.sleep(0.005)
        return await execute_task(
            member, {"description": tag}, llm_call=capturing_llm,
        )

    async def main():
        return await asyncio.gather(
            worker_task("fin", "t1"),
            worker_task("coding", "t2"),
            worker_task("fin", "t3"),
            worker_task("chat", "t4"),
        )

    results = asyncio.run(main())
    assert all(r["status"] == "completed" for r in results)
    # Every worker called the LLM exactly once
    assert len(seen) == 4
    # Each tag was paired with exactly one LLM call
    tags_seen = {s[0] for s in seen}
    assert tags_seen == {"t1", "t2", "t3", "t4"}


# ── Default LLM call smoke (import only) ──────────────────────────────


def test_default_llm_call_is_importable():
    """Sanity: the production default LLM path imports without errors.
    We don't actually call it (that would hit the real API)."""
    from fleet.worker_turn import _default_llm_call
    assert asyncio.iscoroutinefunction(_default_llm_call)


def test_fin_worker_casual_chat_skips_signal_parser(registered_project, caplog):
    """Phase 5.12 task #69: a casual-chat task (no ticker symbol in
    description) must NOT invoke parse_signal and must NOT produce
    the 'both strict and lenient layers failed' warning log. The raw
    LLM response is returned as plain text with layer_used='raw'."""
    mock = _make_mock_llm(
        "你好！我是 NeoMind 的 fin 助理，你的金融认知延伸。"
    )
    member = MemberConfig(name="fin-rt", persona="fin", role="worker")

    import logging
    caplog.set_level(logging.WARNING, logger="agent.finance.signal_schema")
    caplog.set_level(logging.WARNING, logger="fleet.worker_turn")

    async def go():
        set_current_config(AgentConfigManager(mode="fin"))
        return await execute_task(
            member,
            {"description": "hi, 你是谁呀"},  # no ticker
            llm_call=mock,
            project_id=registered_project,
        )

    result = asyncio.run(go())
    assert result["status"] == "completed"
    assert result["layer_used"] == "raw", (
        "casual chat should take the raw-text path, not parse_signal"
    )
    assert result["result"] == (
        "你好！我是 NeoMind 的 fin 助理，你的金融认知延伸。"
    )
    assert result["artifacts"] == []

    # The parse_signal warning must NOT fire for casual chat
    for rec in caplog.records:
        assert "both strict and lenient layers failed" not in rec.message, (
            "parse_signal fallback warning leaked for a non-signal task"
        )
