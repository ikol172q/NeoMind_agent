"""
Fleet worker turn — the persona-dispatch layer for fleet tasks.

**This is the ONE place in the fleet code where it is legitimate to
branch on ``member.persona``.** ``fleet/launch_project.py`` and
``fleet/run.py`` must stay persona-agnostic (grep-audited in commit
diff). When a fleet worker claims a task, the launcher calls
``execute_task(member, task, ...)`` here and we dispatch to the
correct per-persona handler.

Assumes the caller has already called ``set_current_config(
AgentConfigManager(mode=member.persona))`` at the top of the worker's
asyncio task, so that ``agent_config.mode / .model / .system_prompt``
inside this module reach through the proxy to the member's per-task
config view. This is the Phase 4.A contract.

LLM calls are injected via the ``llm_call`` parameter so tests can
mock them. The default implementation wraps ``requests.post`` inside
``asyncio.run_in_executor`` — the default thread pool has enough
slots (min(32, cpu+4)) to run ≤5 fleet workers in parallel without
serialization. Each concurrent worker's thread-pool call progresses
independently.

Contract: plans/2026-04-12_phase4_fleet_llm_loop.md §4.B.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any, Awaitable, Callable, Dict, Optional

from agent_config import agent_config
from fleet.project_schema import MemberConfig

logger = logging.getLogger(__name__)

__all__ = [
    "execute_task",
    "LlmCallable",
    "EventSink",
    "WorkerTurnError",
]


# Signature: (model, system_prompt, user_prompt) -> str
LlmCallable = Callable[[str, str, str], Awaitable[str]]

# Signature: (member_name, event_dict) -> None
# event_dict must contain at least {"kind": str}; common keys include
# "content", "model", "duration_s", "task_id", "layer_used", "error".
EventSink = Callable[[str, Dict[str, Any]], None]


def _emit(
    sink: Optional[EventSink], member_name: str, kind: str, content: str = "",
    **metadata: Any,
) -> None:
    """Safely publish an event — never crashes the caller."""
    if sink is None:
        return
    try:
        sink(member_name, {"kind": kind, "content": content, **metadata})
    except Exception as exc:
        logger.debug("event_sink raised (ignored): %s", exc)


class WorkerTurnError(Exception):
    """Raised internally; always caught by execute_task and reported
    as status=failed. Never propagates to the launcher."""


# ── Default LLM call (production path) ─────────────────────────────────


async def _default_llm_call(
    model: str, system_prompt: str, user_prompt: str
) -> str:
    """Make a single LLM call via the existing router.

    Uses the same payload shape as ``agent/core.py::NeoMindAgent.
    generate_completion`` (lines 1102-1148) so prod behavior stays
    consistent. Wraps the synchronous ``requests.post`` in
    ``run_in_executor`` so multiple concurrent fleet workers each get
    their own thread from the default pool — achieving real parallelism
    without reimplementing the HTTP layer.
    """
    import requests
    from agent.services.llm_provider import LLMProviderService

    provider_svc = LLMProviderService(model=model)
    provider = provider_svc.resolve_with_fallback(model)

    messages = [
        {"role": "system", "content": system_prompt or ""},
        {"role": "user", "content": user_prompt},
    ]
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "temperature": 0.3,
        "max_tokens": 2048,
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {provider.get('api_key', '')}",
    }
    url = provider["base_url"]

    def _sync_post() -> str:
        resp = requests.post(url, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("choices"):
            raise WorkerTurnError(f"unexpected LLM response shape: {data!r}")
        return data["choices"][0]["message"]["content"]

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _sync_post)


# ── Fail-fast check on entry ───────────────────────────────────────────


def _check_fail_fast(
    shared_memory: Any, project_id: str, max_age_hours: float = 24.0
) -> Optional[Dict[str, Any]]:
    """Return the most recent fail_fast feedback entry for ``project_id``
    within the window, or None if no active signal exists."""
    if shared_memory is None or project_id is None:
        return None
    try:
        rows = shared_memory.recall_feedback(
            feedback_type="fail_fast",
            project_id=project_id,
            max_age_hours=max_age_hours,
            limit=1,
        )
    except Exception as exc:
        logger.debug("fail_fast check failed (ignored): %s", exc)
        return None
    return rows[0] if rows else None


# ── Symbol extraction (best effort) ────────────────────────────────────


_SYMBOL_RE = re.compile(r"\b([A-Z]{1,5})\b")


def _extract_symbol(task: Dict[str, Any]) -> Optional[str]:
    """Try to find a ticker-style symbol in the task. Explicit
    ``task['symbol']`` beats regex extraction from the description."""
    sym = task.get("symbol")
    if isinstance(sym, str) and sym.strip():
        return sym.strip().upper()
    desc = task.get("description", "")
    if not isinstance(desc, str):
        return None
    matches = _SYMBOL_RE.findall(desc)
    # Filter out common English stop-words that match the regex
    blacklist = {"AI", "US", "AM", "PM", "JSON", "API", "ETF", "SEC", "IRS", "EPS",
                 "PE", "YOY", "QOQ", "GDP", "CPI", "FED", "OK"}
    for m in matches:
        if m not in blacklist:
            return m
    return None


# ── Per-persona handlers ───────────────────────────────────────────────


async def _execute_fin(
    task: Dict[str, Any],
    llm_call: LlmCallable,
    project_id: Optional[str],
    event_sink: Optional[EventSink] = None,
    member_name: str = "",
) -> Dict[str, Any]:
    """Fin persona: parse signal, write analysis record, return summary."""
    from agent.finance.signal_schema import parse_signal

    # Read per-persona context through the proxy (contextvar-bound to fin)
    system_prompt = agent_config.system_prompt or ""
    model = agent_config.model

    user_prompt = task.get("description", "")
    _emit(event_sink, member_name, "llm_call_start",
          content=f"{model}", model=model, prompt_len=len(user_prompt))
    t0 = time.monotonic()
    raw_response = await llm_call(model, system_prompt, user_prompt)
    elapsed = time.monotonic() - t0
    _emit(event_sink, member_name, "llm_call_end",
          content=f"{elapsed:.2f}s, {len(raw_response)} chars",
          duration_s=elapsed, response_len=len(raw_response),
          preview=raw_response[:200])

    analysis, layer = parse_signal(raw_response)

    artifacts: list = []
    symbol = _extract_symbol(task)
    if project_id and symbol:
        try:
            from agent.finance import investment_projects

            path = investment_projects.write_analysis(
                project_id, symbol, analysis.model_dump()
            )
            artifacts.append(str(path))
        except Exception as exc:
            logger.warning(
                "fin worker: write_analysis failed for %s/%s: %s",
                project_id, symbol, exc,
            )

    return {
        "status": "completed",
        "result": json.dumps(analysis.model_dump(), ensure_ascii=False),
        "layer_used": layer,
        "artifacts": artifacts,
    }


async def _execute_coding(
    task: Dict[str, Any], llm_call: LlmCallable,
    event_sink: Optional[EventSink] = None,
    member_name: str = "",
) -> Dict[str, Any]:
    """Coding persona: minimal LLM-only path for Phase 4. Full agentic
    loop integration (tool calls, Edit/Bash dispatch, iterative
    reasoning) is deferred to a follow-up. This ships the persona
    correctness property; feature completeness is a separate lift."""
    system_prompt = agent_config.system_prompt or ""
    model = agent_config.model
    user_prompt = task.get("description", "")

    _emit(event_sink, member_name, "llm_call_start",
          content=f"{model}", model=model, prompt_len=len(user_prompt))
    t0 = time.monotonic()
    response = await llm_call(model, system_prompt, user_prompt)
    elapsed = time.monotonic() - t0
    _emit(event_sink, member_name, "llm_call_end",
          content=f"{elapsed:.2f}s, {len(response)} chars",
          duration_s=elapsed, response_len=len(response),
          preview=response[:200])

    return {
        "status": "completed",
        "result": response,
        "layer_used": "text",
        "artifacts": [],
    }


async def _execute_chat(
    task: Dict[str, Any], llm_call: LlmCallable,
    event_sink: Optional[EventSink] = None,
    member_name: str = "",
) -> Dict[str, Any]:
    """Chat persona-as-worker: minimal text return. Main use of chat
    in fleet is as a leader (see ChatSupervisor), not a worker. This
    path exists for edge cases like 'think about X' projects."""
    system_prompt = agent_config.system_prompt or ""
    model = agent_config.model
    user_prompt = task.get("description", "")

    _emit(event_sink, member_name, "llm_call_start",
          content=f"{model}", model=model, prompt_len=len(user_prompt))
    t0 = time.monotonic()
    response = await llm_call(model, system_prompt, user_prompt)
    elapsed = time.monotonic() - t0
    _emit(event_sink, member_name, "llm_call_end",
          content=f"{elapsed:.2f}s, {len(response)} chars",
          duration_s=elapsed, response_len=len(response),
          preview=response[:200])

    return {
        "status": "completed",
        "result": response,
        "layer_used": "text",
        "artifacts": [],
    }


# ── Public entry point ────────────────────────────────────────────────


async def execute_task(
    member: MemberConfig,
    task: Dict[str, Any],
    *,
    llm_call: Optional[LlmCallable] = None,
    shared_memory: Optional[Any] = None,
    project_id: Optional[str] = None,
    event_sink: Optional[EventSink] = None,
) -> Dict[str, Any]:
    """Execute one claimed task for the given fleet member.

    Args:
        member: The fleet member who claimed the task. Persona routing
            uses ``member.persona``.
        task: Task dict with at minimum ``description``; optionally
            ``id``, ``symbol``, ``metadata``.
        llm_call: Async callable ``(model, system_prompt, user_prompt)
            -> str``. Defaults to ``_default_llm_call`` which hits the
            existing LLM router via run_in_executor. Tests inject mocks
            to stay hermetic.
        shared_memory: Optional ``SharedMemory`` instance for the
            fail_fast check. When None, the check is skipped.
        project_id: Project context. Required for fin analysis writes
            and fail_fast lookup. When None, fin workers still run but
            don't persist analysis files.

    Returns:
        Dict with keys:
          - ``status`` — "completed" or "failed"
          - ``result`` — the LLM response, JSON-serialized analysis, or
            an error message
          - ``layer_used`` — for fin: "strict" / "lenient" / "fallback"
            from parse_signal; for coding/chat: "text"
          - ``artifacts`` — list of file paths written (fin writes one
            analysis file per task when project_id + symbol known)

    This function NEVER raises — any exception is caught and reported
    as ``status=failed`` with the error captured in ``result``. The
    caller (the fleet launcher) can then mark the task in its queue
    and continue without propagation.
    """
    call = llm_call or _default_llm_call

    _emit(event_sink, member.name, "task_received",
          content=task.get("description", "")[:200],
          task_id=task.get("id"))

    # Fail-fast gate (Phase 3 integration — honors kpi_snapshot's
    # fail_fast feedback writes).
    fail_fast_hit = _check_fail_fast(shared_memory, project_id, max_age_hours=24.0)
    if fail_fast_hit is not None:
        logger.warning(
            "worker %s: fail_fast active for project %s, bailing: %s",
            member.name, project_id, fail_fast_hit.get("content", "")[:80],
        )
        _emit(event_sink, member.name, "task_failed",
              content="fail_fast signal active", task_id=task.get("id"))
        return {
            "status": "failed",
            "result": (
                f"fail_fast: project {project_id!r} has an active fail_fast "
                f"signal less than 24h old — downgrading to rules-only"
            ),
            "layer_used": "fail_fast",
            "artifacts": [],
        }

    # Persona dispatch — the ONE legitimate persona branch in fleet code
    try:
        if member.persona == "fin":
            result = await _execute_fin(
                task, call, project_id,
                event_sink=event_sink, member_name=member.name,
            )
        elif member.persona == "coding":
            result = await _execute_coding(
                task, call, event_sink=event_sink, member_name=member.name,
            )
        elif member.persona == "chat":
            result = await _execute_chat(
                task, call, event_sink=event_sink, member_name=member.name,
            )
        else:
            raise WorkerTurnError(
                f"unknown persona {member.persona!r} for member {member.name!r}"
            )
        _emit(event_sink, member.name, "task_completed",
              content=f"layer={result.get('layer_used', 'text')}, "
                      f"artifacts={len(result.get('artifacts', []))}",
              task_id=task.get("id"),
              layer_used=result.get("layer_used"))
        return result
    except Exception as exc:
        logger.exception(
            "execute_task failed for member %s (persona=%s)",
            member.name, member.persona,
        )
        _emit(event_sink, member.name, "task_failed",
              content=f"{type(exc).__name__}: {exc}",
              task_id=task.get("id"),
              error=str(exc))
        return {
            "status": "failed",
            "result": f"exception: {type(exc).__name__}: {exc}",
            "layer_used": None,
            "artifacts": [],
        }
