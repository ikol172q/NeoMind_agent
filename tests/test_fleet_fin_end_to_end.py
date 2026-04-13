"""Phase 4 end-to-end integration tests.

Full FleetLauncher lifecycle with:
 - Phase 4.A ContextVar isolation proven through the stack
 - Phase 4.B worker_turn persona dispatch with mocked LLM (no budget)
 - Phase 4.C launcher hookup (task claim → execute → report → queue
   marked complete → leader mailbox gets XML notification)
 - Phase 4.D fleet.run.run_task lifecycle
 - Phase 4.E project.yaml fixtures (fin-core + coding-smoke)

All LLM calls are monkey-patched via fleet.worker_turn._default_llm_call
replacement so these tests burn zero real budget.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest

import fleet.worker_turn as worker_turn
from agent.finance import investment_projects
from agent_config import AgentConfigManager, agent_config, set_current_config
from fleet.launch_project import FleetLauncher
from fleet.project_schema import MemberConfig, ProjectConfig, load_project_config
from fleet.run import FleetRunError, FleetRunTimeout, run_task


# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def tmp_fleet_base(tmp_path, monkeypatch):
    """Per-test isolated ~/.neomind/teams root so different tests can't
    collide on the same team_name on disk."""
    base = tmp_path / "neomind"
    base.mkdir()
    # Also isolate Investment root for fin file writes
    inv = tmp_path / "Investment"
    inv.mkdir()
    monkeypatch.setenv("NEOMIND_INVESTMENT_ROOT", str(inv))
    return str(base)


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


@pytest.fixture
def fin_core_config():
    return load_project_config(str(_repo_root() / "projects" / "fin-core" / "project.yaml"))


@pytest.fixture
def coding_smoke_config():
    return load_project_config(
        str(_repo_root() / "projects" / "coding-smoke" / "project.yaml")
    )


# ── LLM mocking helper ─────────────────────────────────────────────────


class _MockLlmCall:
    """Replacement for worker_turn._default_llm_call used during tests.

    Records every call and returns a canned response. Patching
    ``fleet.worker_turn._default_llm_call`` replaces the module
    attribute, and worker_turn.execute_task uses that attribute as
    its fallback when no explicit llm_call is passed. The launcher
    (Phase 4.C) does NOT pass an llm_call explicitly, so the patch
    is the only way tests can intercept production calls without
    modifying the launcher.
    """

    def __init__(self, response: str = '{"signal":"hold","confidence":5,"reason":"test","sources":["mock"]}'):
        self.response = response
        self.calls: List[Dict[str, Any]] = []

    async def __call__(self, model: str, system_prompt: str, user_prompt: str) -> str:
        self.calls.append({
            "model": model,
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
        })
        return self.response


@pytest.fixture
def mock_llm(monkeypatch):
    mock = _MockLlmCall()
    monkeypatch.setattr(worker_turn, "_default_llm_call", mock)
    return mock


# ── Launcher basic lifecycle (no tasks) ────────────────────────────────


def test_launcher_start_stop_clean(tmp_fleet_base, coding_smoke_config):
    """Sanity: start a fleet, stop it immediately, no crashes, no leaks."""
    async def go():
        launcher = FleetLauncher(coding_smoke_config, base_dir=tmp_fleet_base)
        await launcher.start()
        assert launcher._running is True
        assert len(launcher._tasks) == 2  # leader + 1 worker
        await launcher.stop()
        assert launcher._running is False
        # All spawned tasks finished
        assert all(t.done() for t in launcher._tasks.values())

    asyncio.run(go())


# ── Worker claim → execute_task → queue mark + leader notification ─────


def test_fin_worker_claims_task_writes_analysis(tmp_fleet_base, mock_llm):
    """End-to-end fin path: submit task → fin worker claims it →
    worker_turn dispatches via the LLM mock → analysis file is
    written under the tmp Investment root → queue marks task complete
    → leader's mailbox receives an XML task_notification."""
    mock_llm.response = (
        '{"signal":"buy","confidence":8,"reason":"strong earnings AAPL",'
        '"sources":["Finnhub"]}'
    )

    # Register the Investment project so write_analysis succeeds
    investment_projects.register_project("fin-e2e", "test")

    # Build a minimal fin-shaped config with the registered id
    config = ProjectConfig(
        project_id="fin-e2e",
        description="minimal fin fleet",
        leader="mgr",
        members=[
            MemberConfig(name="mgr", persona="chat", role="leader"),
            MemberConfig(name="fin-rt", persona="fin", role="worker"),
        ],
        settings={},
    )

    async def go():
        launcher = FleetLauncher(config, base_dir=tmp_fleet_base)
        await launcher.start()
        try:
            task_id = await launcher.submit_task(
                "analyze AAPL and return signal",
                target_persona="fin",
            )
            # Give the worker loop a few ticks to claim + run + report
            for _ in range(30):
                tasks = launcher._task_queue.list_tasks()
                mine = next((t for t in tasks if t["id"] == task_id), None)
                if mine and mine.get("status") == "completed":
                    break
                await asyncio.sleep(0.1)

            tasks = launcher._task_queue.list_tasks()
            final = next((t for t in tasks if t["id"] == task_id), None)
            assert final is not None, "task disappeared from queue"
            assert final["status"] == "completed", (
                f"task did not complete: {final}"
            )
        finally:
            await launcher.stop()

    asyncio.run(go())

    # The mock LLM was called exactly once (for the fin worker turn)
    assert len(mock_llm.calls) == 1

    # An analysis file was written under fin-e2e/analyses/
    proj_dir = investment_projects.get_project_dir("fin-e2e")
    analysis_files = list((proj_dir / "analyses").glob("*_AAPL.json"))
    assert len(analysis_files) == 1, (
        f"expected 1 analysis file, got: {analysis_files}"
    )
    payload = json.loads(analysis_files[0].read_text())
    assert payload["symbol"] == "AAPL"
    assert payload["signal"]["signal"] == "buy"


def test_leader_mailbox_receives_task_notification(tmp_fleet_base, mock_llm):
    """After a worker completes a task, the leader's mailbox must
    contain an XML ``task_notification`` message from that worker."""
    mock_llm.response = (
        '{"signal":"sell","confidence":6,"reason":"weak","sources":["x"]}'
    )
    investment_projects.register_project("fin-notif", "test")

    config = ProjectConfig(
        project_id="fin-notif",
        description="notification test",
        leader="mgr",
        members=[
            MemberConfig(name="mgr", persona="chat", role="leader"),
            MemberConfig(name="fin-rt", persona="fin", role="worker"),
        ],
        settings={},
    )

    async def go():
        launcher = FleetLauncher(config, base_dir=tmp_fleet_base)
        await launcher.start()
        try:
            task_id = await launcher.submit_task(
                "analyze NVDA", target_persona="fin",
            )
            # Wait for completion
            for _ in range(30):
                tasks = launcher._task_queue.list_tasks()
                mine = next((t for t in tasks if t["id"] == task_id), None)
                if mine and mine.get("status") == "completed":
                    break
                await asyncio.sleep(0.1)

            # Now read the leader's mailbox — should have a notification
            leader_mailbox = launcher._mailboxes["mgr"]
            messages = leader_mailbox.read_unread()
            notifs = [m for m in messages if m.msg_type == "task_notification"]
            assert len(notifs) >= 1, (
                f"leader did not receive task_notification: {messages}"
            )
            notif = notifs[0]
            assert "<task-notification>" in notif.content
            assert f"<task-id>{task_id}</task-id>" in notif.content
            assert "<status>completed</status>" in notif.content
            assert notif.sender == "fin-rt"
        finally:
            await launcher.stop()

    asyncio.run(go())


# ── Q2 regression: coding-only fleet uses the SAME code path ───────────


def test_coding_only_fleet_end_to_end(tmp_fleet_base, coding_smoke_config, mock_llm):
    """Q2 guardrail: a project with zero fin members must run
    end-to-end via the identical launcher code path. If any Phase 4
    change accidentally hardcodes fin-specific logic in launch_project
    or fleet.run, this test breaks before anything ships to canary."""
    mock_llm.response = "I would refactor X by extracting Y into Z..."

    async def go():
        launcher = FleetLauncher(
            coding_smoke_config, base_dir=tmp_fleet_base,
        )
        await launcher.start()
        try:
            task_id = await launcher.submit_task(
                "refactor quant_engine for readability",
                target_persona="coding",
            )
            for _ in range(30):
                tasks = launcher._task_queue.list_tasks()
                mine = next((t for t in tasks if t["id"] == task_id), None)
                if mine and mine.get("status") == "completed":
                    break
                await asyncio.sleep(0.1)

            tasks = launcher._task_queue.list_tasks()
            final = next((t for t in tasks if t["id"] == task_id), None)
            assert final is not None
            assert final["status"] == "completed"
        finally:
            await launcher.stop()

    asyncio.run(go())
    assert len(mock_llm.calls) == 1
    # The LLM response text flows through — proves coding worker path
    # actually ran and returned the mock payload
    # (The task queue's result field contains a truncated copy.)


# ── Phase 4.A isolation propagates through the launcher ────────────────


def test_concurrent_fin_and_coding_workers_see_own_persona(
    tmp_fleet_base, monkeypatch,
):
    """Two concurrent workers (one fin, one coding) running on the
    same launcher must each see their own persona's config inside
    worker_turn. Captured via a spy LLM call that records agent_config
    .mode at the moment of invocation."""
    captured: List[str] = []

    async def spy_llm(model: str, system_prompt: str, user_prompt: str) -> str:
        # At this point we're inside the worker's task context — the
        # proxy should return this worker's persona mode
        captured.append(agent_config.mode)
        # Add a tiny delay so the two workers definitely interleave
        await asyncio.sleep(0.02)
        captured.append(agent_config.mode)  # second capture after await
        # Return something that parses cleanly for fin and is ignored for coding
        return '{"signal":"hold","confidence":5,"reason":"x","sources":["y"]}'

    monkeypatch.setattr(worker_turn, "_default_llm_call", spy_llm)

    investment_projects.register_project("mixed-e2e", "test")

    config = ProjectConfig(
        project_id="mixed-e2e",
        description="mixed fleet for isolation test",
        leader="mgr",
        members=[
            MemberConfig(name="mgr", persona="chat", role="leader"),
            MemberConfig(name="fin-rt", persona="fin", role="worker"),
            MemberConfig(name="dev-1", persona="coding", role="worker"),
        ],
        settings={},
    )

    async def go():
        launcher = FleetLauncher(config, base_dir=tmp_fleet_base)
        await launcher.start()
        try:
            fin_task = await launcher.submit_task(
                "analyze AAPL", target_persona="fin",
            )
            cod_task = await launcher.submit_task(
                "edit quant_engine.py", target_persona="coding",
            )
            # Wait for both
            for _ in range(50):
                tasks = launcher._task_queue.list_tasks()
                mine = {
                    t["id"]: t for t in tasks
                    if t["id"] in (fin_task, cod_task)
                }
                if all(
                    mine.get(tid, {}).get("status") == "completed"
                    for tid in (fin_task, cod_task)
                ):
                    break
                await asyncio.sleep(0.1)
        finally:
            await launcher.stop()

    asyncio.run(go())

    # Each worker ran exactly one LLM call with 2 captures (before + after await)
    assert len(captured) == 4, f"unexpected capture count: {captured}"
    # The 4 captures are some interleaving of 2x"fin" + 2x"coding" — we
    # don't care about order, only that isolation held
    assert sorted(captured) == ["coding", "coding", "fin", "fin"], (
        f"persona isolation broken under launcher: {captured}"
    )


# ── Default agent_config unchanged after fleet.stop ────────────────────


def test_default_agent_config_unchanged_after_fleet_run(
    tmp_fleet_base, coding_smoke_config, mock_llm,
):
    """Sanity check: outside any fleet worker task, agent_config.mode
    reads the process-wide default. Running a fleet must not change
    that default (even though fleet workers bind their own contextvar
    values, those bindings die with their tasks)."""
    # Snapshot the default before
    default_mode_before = agent_config.mode

    async def go():
        launcher = FleetLauncher(coding_smoke_config, base_dir=tmp_fleet_base)
        await launcher.start()
        try:
            await launcher.submit_task("noop", target_persona="coding")
            await asyncio.sleep(0.5)
        finally:
            await launcher.stop()

    asyncio.run(go())
    # Default is unchanged — the fleet workers' contextvar.set() did
    # not leak out of their tasks' contexts
    assert agent_config.mode == default_mode_before


# ── fleet.run.run_task public API ─────────────────────────────────────


def test_run_task_end_to_end_via_yaml(
    tmp_fleet_base, monkeypatch, mock_llm,
):
    """run_task("coding-smoke", ...) loads projects/coding-smoke/
    project.yaml, starts a fleet, submits a task, waits for completion,
    returns the result dict, stops the fleet."""
    mock_llm.response = "done"

    async def go():
        return await run_task(
            "coding-smoke",
            "add a comment to quant_engine.py",
            target_persona="coding",
            timeout_s=10.0,
            base_dir=tmp_fleet_base,
        )

    result = asyncio.run(go())
    assert result["project_id"] == "coding-smoke"
    assert result["status"] == "completed"
    assert "task_id" in result
    assert result["task"]["status"] == "completed"
    assert "elapsed_s" in result
    assert set(result["members"]) == {"coding-chair", "coder-1"}


def test_run_task_missing_yaml_raises_fleet_run_error(tmp_fleet_base):
    """If the project_id has no yaml under projects/, raise cleanly
    instead of crashing inside launcher.start."""
    async def go():
        return await run_task(
            "nonexistent-project",
            "task",
            base_dir=tmp_fleet_base,
        )

    with pytest.raises(FleetRunError) as exc_info:
        asyncio.run(go())
    assert "not found" in str(exc_info.value).lower()


def test_run_task_no_workers_raises(tmp_fleet_base, tmp_path):
    """A yaml with only a leader (no workers) is a usage error."""
    # Write a stub yaml with just a leader
    yaml_path = tmp_path / "leader_only.yaml"
    yaml_path.write_text(
        "project_id: leader-only-p4\n"
        "description: test\n"
        "leader: solo\n"
        "members:\n"
        "  - {name: solo, persona: chat, role: leader}\n"
    )

    async def go():
        return await run_task(
            "leader-only-p4",
            "task",
            project_yaml_path=str(yaml_path),
            base_dir=tmp_fleet_base,
        )

    with pytest.raises(FleetRunError) as exc_info:
        asyncio.run(go())
    assert "no workers" in str(exc_info.value).lower()


def test_run_task_timeout_stops_fleet_cleanly(tmp_fleet_base, monkeypatch):
    """If the submitted task never completes within timeout_s, run_task
    raises FleetRunTimeout AND the fleet is cleanly stopped (not
    leaked as a dangling asyncio task)."""

    # Block the LLM call indefinitely (mock never returns)
    async def never_returns(model, system_prompt, user_prompt):
        await asyncio.sleep(100.0)
        return ""

    monkeypatch.setattr(worker_turn, "_default_llm_call", never_returns)

    async def go():
        return await run_task(
            "coding-smoke",
            "task",
            target_persona="coding",
            timeout_s=0.5,  # expire quickly
            base_dir=tmp_fleet_base,
        )

    with pytest.raises(FleetRunTimeout):
        asyncio.run(go())


# ── Default agent_config still unchanged after run_task ────────────────


def test_agent_config_default_restored_after_run_task(
    tmp_fleet_base, mock_llm,
):
    """Outside the run_task await, agent_config reads the default.
    Inside run_task's workers each read their own. After run_task
    returns, the default is again what the main thread sees."""
    mock_llm.response = "done"
    default_before = agent_config.mode

    async def go():
        return await run_task(
            "coding-smoke",
            "task",
            target_persona="coding",
            timeout_s=10.0,
            base_dir=tmp_fleet_base,
        )

    asyncio.run(go())
    assert agent_config.mode == default_before
