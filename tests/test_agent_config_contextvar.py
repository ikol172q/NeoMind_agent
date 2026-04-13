"""Phase 4.A — Option E isolation property tests.

Proves that agent_config.py's ContextVar + _AgentConfigProxy give us
per-asyncio-task isolation for the AgentConfigManager view, without
locks and without refactoring the seven files that do
``from agent_config import agent_config``.

This is the **single most load-bearing test file** for Phase 4. If it
regresses, the entire fleet's parallelism story is broken and every
downstream worker could silently see the wrong persona's config. The
grep audit in ``test_grep_audit_no_isinstance_checks`` is the
insurance policy against a future caller adding an ``isinstance``
check that would expose the proxy.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

import agent_config as ac_module
from agent_config import (
    AgentConfigManager,
    _AgentConfigProxy,
    _default_manager,
    agent_config,
    get_current_config,
    reset_current_config,
    set_current_config,
)


# ── Defaults + single-task basics ──────────────────────────────────────


def test_proxy_is_not_a_config_manager():
    """Deliberate: the proxy is NOT an AgentConfigManager subclass."""
    assert not isinstance(agent_config, AgentConfigManager)
    assert isinstance(agent_config, _AgentConfigProxy)


def test_default_config_returned_when_no_override():
    """Outside any fleet worker task, reads land on the default manager."""
    assert get_current_config() is _default_manager
    # And proxy reads match what the default instance would return
    assert agent_config.mode == _default_manager.mode
    assert agent_config.model == _default_manager.model


def test_set_current_config_binds_in_task():
    """set_current_config in a task changes what the proxy reads."""

    async def worker():
        cfg = AgentConfigManager(mode="fin")
        set_current_config(cfg)
        # Proxy now reads from the task-local binding
        assert agent_config.mode == "fin"
        assert get_current_config() is cfg

    asyncio.run(worker())
    # After the task exits, the default is restored at the proxy level
    # (because the contextvar snapshot of that task is dropped).
    assert agent_config.mode == _default_manager.mode


def test_reset_current_config_restores_previous():
    """The Token API lets callers manually restore mid-task if needed."""

    async def worker():
        tok = set_current_config(AgentConfigManager(mode="coding"))
        assert agent_config.mode == "coding"
        reset_current_config(tok)
        # Back to whatever was bound before (which is the default here)
        assert agent_config.mode == _default_manager.mode

    asyncio.run(worker())


# ── THE critical property: sibling task isolation ──────────────────────


def test_sibling_tasks_isolated_across_asyncio_gather():
    """4 concurrent workers, each with its own persona, reading the
    proxy across multiple await points — each must see ONLY its own
    mode, with zero cross-contamination. This is the proof of Option E.
    """

    async def worker(persona: str, iterations: int = 20):
        cfg = AgentConfigManager(mode=persona)
        set_current_config(cfg)
        reads = []
        for _ in range(iterations):
            # Interleave with the scheduler so sibling coroutines run
            await asyncio.sleep(0.001)
            reads.append(agent_config.mode)
        return reads

    async def main():
        return await asyncio.gather(
            worker("fin"),
            worker("coding"),
            worker("chat"),
            worker("fin"),       # a second fin worker — still isolated
            worker("coding"),    # a second coding worker — still isolated
        )

    results = asyncio.run(main())
    assert set(results[0]) == {"fin"}, f"fin-1 contaminated: {set(results[0])}"
    assert set(results[1]) == {"coding"}, f"coding-1 contaminated: {set(results[1])}"
    assert set(results[2]) == {"chat"}, f"chat contaminated: {set(results[2])}"
    assert set(results[3]) == {"fin"}, f"fin-2 contaminated: {set(results[3])}"
    assert set(results[4]) == {"coding"}, f"coding-2 contaminated: {set(results[4])}"


def test_sibling_tasks_isolated_across_asyncio_create_task():
    """Same isolation property but via explicit create_task instead of gather."""

    captured = {}

    async def worker(persona: str):
        set_current_config(AgentConfigManager(mode=persona))
        await asyncio.sleep(0.005)
        captured[persona] = agent_config.mode

    async def main():
        tasks = [
            asyncio.create_task(worker("fin")),
            asyncio.create_task(worker("coding")),
            asyncio.create_task(worker("chat")),
        ]
        await asyncio.gather(*tasks)

    asyncio.run(main())
    assert captured == {"fin": "fin", "coding": "coding", "chat": "chat"}


def test_parent_context_unaffected_by_child_task():
    """A parent task sets one persona, spawns a child with a different
    persona, waits for the child, and still sees its own persona."""

    async def child():
        set_current_config(AgentConfigManager(mode="coding"))
        assert agent_config.mode == "coding"

    async def parent():
        set_current_config(AgentConfigManager(mode="fin"))
        assert agent_config.mode == "fin"
        await asyncio.create_task(child())
        # Child's contextvar set() does not leak into parent
        assert agent_config.mode == "fin"

    asyncio.run(parent())


def test_child_inherits_parent_config_by_default():
    """If a child task does NOT call set_current_config, it inherits
    the parent's current binding (via context copy at task creation)."""

    captured = []

    async def child():
        captured.append(agent_config.mode)

    async def parent():
        set_current_config(AgentConfigManager(mode="fin"))
        await asyncio.create_task(child())

    asyncio.run(parent())
    assert captured == ["fin"]


# ── Exception safety ───────────────────────────────────────────────────


def test_exception_in_worker_does_not_corrupt_siblings():
    """If one worker raises mid-turn, sibling workers must still hold
    their own views correctly and the default must come back."""

    survivor_reads = []

    async def failing_worker():
        set_current_config(AgentConfigManager(mode="fin"))
        await asyncio.sleep(0.005)
        raise RuntimeError("boom")

    async def survivor_worker():
        set_current_config(AgentConfigManager(mode="coding"))
        await asyncio.sleep(0.01)
        survivor_reads.append(agent_config.mode)
        await asyncio.sleep(0.01)
        survivor_reads.append(agent_config.mode)
        return "survived"

    async def main():
        results = await asyncio.gather(
            failing_worker(),
            survivor_worker(),
            return_exceptions=True,
        )
        return results

    results = asyncio.run(main())
    assert isinstance(results[0], RuntimeError)
    assert results[1] == "survived"
    assert set(survivor_reads) == {"coding"}
    # Default is unchanged after the whole gather completes
    assert get_current_config() is _default_manager


# ── Legacy-caller compat ───────────────────────────────────────────────


def test_legacy_caller_reads_default_outside_worker():
    """A synchronous legacy path (CLI init at module load time) that
    captures agent_config.model at construction time must see the
    default instance's value, NOT a worker's."""

    class FakeLegacyAgent:
        def __init__(self):
            self.captured_model = agent_config.model
            self.captured_mode = agent_config.mode

    # No worker context — we're in the main thread/task
    legacy = FakeLegacyAgent()
    assert legacy.captured_model == _default_manager.model
    assert legacy.captured_mode == _default_manager.mode


def test_property_setter_forwards_through_proxy():
    """agent_config.system_prompt = "..." must call the property
    setter on the underlying AgentConfigManager instance, not create
    an attribute on the proxy."""

    async def worker():
        cfg = AgentConfigManager(mode="fin")
        set_current_config(cfg)
        agent_config.system_prompt = "phase-4 test prompt"
        # Reads through the proxy AND directly on the instance both
        # return the new value
        assert agent_config.system_prompt == "phase-4 test prompt"
        assert cfg.system_prompt == "phase-4 test prompt"

    asyncio.run(worker())


def test_proxy_dir_exposes_manager_attributes():
    """dir(agent_config) should include AgentConfigManager attributes
    for debug tooling / IDE autocomplete."""
    attrs = set(dir(agent_config))
    # Sanity check a few known properties
    assert "mode" in attrs
    assert "model" in attrs
    assert "system_prompt" in attrs
    assert "switch_mode" in attrs


def test_proxy_repr_includes_underlying_target():
    """repr(agent_config) should help debugging by showing which
    instance is currently bound."""
    r = repr(agent_config)
    assert "AgentConfigProxy" in r
    assert "AgentConfigManager" in r


# ── Regression: no isinstance checks anywhere in the repo ──────────────


def test_grep_audit_no_isinstance_checks_on_agent_config_manager():
    """A meta-test: if a future caller adds
    ``isinstance(agent_config, AgentConfigManager)``, the proxy would
    fail that check (proxy is deliberately not a subclass). Fail loudly
    so the future commit knows to either remove the isinstance check
    or promote the proxy to a subclass.
    """
    repo_root = Path(__file__).resolve().parent.parent
    result = subprocess.run(
        [
            "grep", "-rn",
            "--include=*.py",
            "-E",
            r"isinstance\s*\([^,]+,\s*AgentConfigManager\b",
            str(repo_root),
        ],
        capture_output=True,
        text=True,
    )
    # Filter out:
    #  - this test file (contains a literal assertion about the pattern)
    #  - agent_config.py itself (mentions the pattern in comments as
    #    documentation — no real isinstance check because the file
    #    defines the class locally and has no reason to check it)
    #  - Lines that are pure comments (start with optional whitespace
    #    then '#') — matches text-in-docstring mentions too
    hits = []
    for line in result.stdout.splitlines():
        if "test_agent_config_contextvar.py" in line:
            continue
        if line.endswith("agent_config.py") or "/agent_config.py:" in line:
            continue
        # path:lineno:content — extract the content after the second colon
        parts = line.split(":", 2)
        if len(parts) == 3:
            content = parts[2].lstrip()
            if content.startswith("#"):
                continue
        hits.append(line)
    assert not hits, (
        "Found isinstance(..., AgentConfigManager) checks that would "
        "break the _AgentConfigProxy pattern:\n" + "\n".join(hits)
    )
