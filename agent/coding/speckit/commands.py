"""
Slash command handlers for spec-kit integration.

Each handler is a callable (core, arg) -> str that:
1. Parses arguments
2. Instantiates PhaseRunner with available services
3. Calls the appropriate phase
4. Returns formatted output
"""

from __future__ import annotations

import asyncio
from typing import Any


def _get_phase_runner(core: Any) -> "PhaseRunner":
    """Build a PhaseRunner from the core agent's available services."""
    from agent.coding.speckit.spec_manager import SpecManager
    from agent.coding.speckit.phase_runner import PhaseRunner

    ws_mgr = getattr(core, 'workspace_manager', None)
    project_root = getattr(ws_mgr, 'project_root', None) if ws_mgr is not None else None
    if project_root is None:
        import os as _os
        project_root = _os.getcwd()
    ws_root = str(project_root)
    spec_mgr = SpecManager(ws_root)

    sprint_mgr = getattr(core, 'sprint_mgr', None)
    task_mgr = getattr(core, 'task_mgr', None)
    plan_mode_mgr = getattr(core, 'plan_mode_manager', None)

    # Coordinator integration
    coordinator = getattr(core, 'coordinator', None)
    worker_fn = getattr(core, '_run_worker_task', None)

    # LLM function: prefer an async completion if core exposes one, else
    # wrap the sync `generate_completion` in a thread so PhaseRunner's
    # async path stays non-blocking. Core has only `generate_completion`
    # (sync) at agent/core.py:1105 — `generate_completion_async` does
    # not exist, so the previous hasattr check silently disabled all
    # LLM enrichment in real usage.
    llm_fn = None
    if hasattr(core, 'generate_completion_async'):
        async def _llm_fn(system_prompt: str, user_prompt: str) -> str:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
            return await core.generate_completion_async(
                messages, temperature=0.7, max_tokens=8000,
            )
        llm_fn = _llm_fn
    elif hasattr(core, 'generate_completion'):
        async def _llm_fn(system_prompt: str, user_prompt: str) -> str:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
            # max_tokens=8000: plans/tasks with 10+ steps routinely
            # overflow 3000 and truncate mid-section (verified via
            # E2E dogfood — see /tmp/speckit_e2e_dumps).
            # core.generate_completion clamps to the model's max_output
            # spec automatically (agent/core.py:1124), so an overly
            # generous value is safe.
            return await asyncio.to_thread(
                core.generate_completion, messages, 0.7, 8000,
            )
        llm_fn = _llm_fn

    return PhaseRunner(
        spec_manager=spec_mgr,
        llm_fn=llm_fn,
        sprint_manager=sprint_mgr,
        task_manager=task_mgr,
        coordinator=coordinator,
        worker_fn=worker_fn,
        plan_mode_manager=plan_mode_mgr,
    )


def _run_async(coro):
    """Run an async coroutine from a sync handler.

    Slash-command handlers are dispatched synchronously from
    code_commands.stream_response (sync function), so normally there is
    no running loop and ``asyncio.run`` works. The two corner cases are
    (a) Python 3.9 policy state after a prior ``asyncio.run`` —
    ``get_event_loop`` raises and ``asyncio.run`` succeeds; (b) a future
    caller invoking us from inside a running loop — ``asyncio.run``
    raises and we fall back to a fresh loop.

    Mirrors the pattern at neomind_interface.py:2944-2955 to stay
    consistent with the rest of the codebase. Avoids nest_asyncio so we
    don't add an optional-dependency footgun.
    """
    try:
        return asyncio.run(coro)
    except RuntimeError:
        # Already inside a running loop, or get_event_loop state is poisoned.
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()


# ── Command handlers ──────────────────────────────────────────────

def handle_constitution(core, arg: str) -> str:
    """Handle /speckit.constitution [project-name]"""
    project_name = arg.strip() or "My Project"
    runner = _get_phase_runner(core)
    result = _run_async(runner.run_constitution(project_name))
    return _fmt(result)


def handle_specify(core, arg: str) -> str:
    """Handle /speckit.specify <feature-name> [description]"""
    parts = arg.strip().split(maxsplit=1)
    if not parts:
        return "Usage: /speckit.specify <feature-name> [description]"
    feature_name = parts[0]
    description = parts[1] if len(parts) > 1 else ""
    runner = _get_phase_runner(core)
    result = _run_async(runner.run_specify(feature_name, description))
    return _fmt(result)


def handle_clarify(core, arg: str) -> str:
    """Handle /speckit.clarify <feature-slug>"""
    slug = arg.strip()
    if not slug:
        return "Usage: /speckit.clarify <feature-slug>"
    runner = _get_phase_runner(core)
    result = _run_async(runner.run_clarify(slug))
    if result.success and result.data.get("questions"):
        lines = [_fmt(result), "", "Questions to resolve:"]
        for i, q in enumerate(result.data["questions"], 1):
            lines.append(f"  {i}. {q}")
            if result.data.get("suggestions", {}).get(q):
                lines.append(f"     Suggestion: {result.data['suggestions'][q]}")
        return "\n".join(lines)
    return _fmt(result)


def handle_plan(core, arg: str) -> str:
    """Handle /speckit.plan <feature-slug>"""
    slug = arg.strip()
    if not slug:
        return "Usage: /speckit.plan <feature-slug>"
    runner = _get_phase_runner(core)
    result = _run_async(runner.run_plan(slug))
    return _fmt(result)


def handle_tasks(core, arg: str) -> str:
    """Handle /speckit.tasks <feature-slug>"""
    slug = arg.strip()
    if not slug:
        return "Usage: /speckit.tasks <feature-slug>"
    runner = _get_phase_runner(core)
    result = _run_async(runner.run_tasks(slug))
    return _fmt(result)


def handle_analyze(core, arg: str) -> str:
    """Handle /speckit.analyze <feature-slug>"""
    slug = arg.strip()
    if not slug:
        return "Usage: /speckit.analyze <feature-slug>"
    runner = _get_phase_runner(core)
    result = _run_async(runner.run_analyze(slug))
    lines = [_fmt(result)]
    if result.data.get("violations"):
        lines.append("\nViolations:")
        for v in result.data["violations"]:
            lines.append(f"  - {v}")
    return "\n".join(lines)


def handle_implement(core, arg: str) -> str:
    """Handle /speckit.implement <feature-slug>"""
    slug = arg.strip()
    if not slug:
        return "Usage: /speckit.implement <feature-slug>"
    runner = _get_phase_runner(core)
    result = _run_async(runner.run_implement(slug))
    return _fmt(result)


def handle_checklist(core, arg: str) -> str:
    """Handle /speckit.checklist <feature-slug>"""
    slug = arg.strip()
    if not slug:
        return "Usage: /speckit.checklist <feature-slug>"
    runner = _get_phase_runner(core)
    result = _run_async(runner.run_checklist(slug))
    return _fmt(result)


def handle_status(core, arg: str) -> str:
    """Handle /speckit.status [feature-slug]"""
    slug = arg.strip() or None
    runner = _get_phase_runner(core)
    result = _run_async(runner.run_status(slug))
    return _fmt(result)


# ── Formatting ────────────────────────────────────────────────────

def _fmt(result) -> str:
    from agent.coding.speckit.phase_runner import PhaseResult
    icon = "✅" if result.success else "❌"
    return f"{icon} [{result.phase}] {result.message}"
