"""Run a fleet worker's LLM turn through `AgentSession`.

Phase 6B task 2. `fleet/worker_turn.py` reached the provider itself — a
`requests.post` wrapped in `run_in_executor` — which made fleet the last
surface with its own turn implementation, and the reason
`tests/architecture/test_fleet_worker_turn_boundary.py` freezes it as
LLM-only: an unmigrated surface that grew tools would be a second, unaudited
permission path opened after the audit concluded.

The migration is a drop-in at one seam. `worker_turn` already injects its LLM
call as `(model, system_prompt, user_prompt) -> str`, and all three persona
handlers go through it, so replacing the default migrates fin, coding and chat
at once without touching a line of persona logic.

**A fleet worker is the least supervised surface there is.** It runs unattended,
on a schedule, with nobody to answer a permission prompt — so the policy here is
the strictest of the three: `interactive=False` (an ASK resolves to DENY) and an
allowlist intersected with what still declares itself READ_ONLY. That is what
lets the freeze be lifted: a worker that requests a tool now meets the same
`ToolExecutor` as every other surface, rather than a path of its own.

The audit trail is preserved exactly. Every call still gets a `req_id`, and the
full request and response still reach the audit log — that is a zero-data-loss
requirement, not a nicety, and a migration that quietly dropped it would be a
regression no test result would show.
"""

from __future__ import annotations

import time
import traceback
from typing import Any, Dict, List, Optional, Sequence

#: What an unattended worker may reach for.
#:
#: Narrower than headless, which runs from the operator's own shell, and
#: narrower still than the terminal. Read and search are absent deliberately:
#: a scheduled worker reading arbitrary files is the shape of the problem the
#: Phase 0 freeze existed to prevent.
FLEET_READ_ONLY_TOOLS = (
    "WebSearch",
    "WebFetch",
    "finance_get_stock",
    "finance_get_crypto",
    "finance_market_overview",
    "finance_news_search",
    "finance_market_digest",
    "finance_compute",
    "finance_economic_calendar",
    "finance_risk_calc",
)

#: A worker turn is one question, not a conversation. Two rounds is enough for
#: "look something up, then answer"; more turns an unattended job into a loop
#: nobody is watching.
DEFAULT_MAX_TOOL_ROUNDS = 2

#: Reasoning models count hidden chain-of-thought against `max_tokens`. The
#: value carried over from the path this replaces, where a 2048 budget
#: truncated visible replies to a few hundred characters.
DEFAULT_MAX_TOKENS = 8192

DEFAULT_TEMPERATURE = 0.3

_ENDPOINT = "fleet.worker.session_llm_call"


def fleet_allowed_tools(registry: Any) -> List[str]:
    """Allowlist ∩ registered ∩ still READ_ONLY.

    Both halves, for the reason they matter everywhere else: the allowlist keeps
    a mislabelled side-effecting tool out even when registered, and re-checking
    the declared level drops a tool that is later tightened instead of leaving
    it silently in.
    """
    from agent.coding.tool_schema import PermissionLevel

    out: List[str] = []
    for name in FLEET_READ_ONLY_TOOLS:
        tool = None
        getter = getattr(registry, "get_tool", None)
        if callable(getter):
            try:
                tool = getter(name)
            except Exception:
                tool = None
        else:
            tool = (getattr(registry, "_tool_definitions", {}) or {}).get(name)
        if tool is None:
            continue
        if getattr(tool, "permission_level", None) is not PermissionLevel.READ_ONLY:
            continue
        out.append(name)
    return out


def build_worker_session(
    *,
    llm: Any,
    registry: Any,
    model: str,
    system_prompt: str,
    mode: str = "fin",
    max_tool_rounds: int = DEFAULT_MAX_TOOL_ROUNDS,
    working_dir: str = "",
    tool_parser: Any = None,
) -> Any:
    """Compose the session for one worker turn.

    No store: a fleet turn is one question and its answer, and the result is
    persisted by `worker_turn` as an artifact. Giving it a conversation store
    would create a second owner of history for a surface that has no
    conversation.
    """
    from agent.runtime.permissions import CapabilitySnapshot, PermissionPolicy
    from agent.runtime.session import AgentSession
    from agent.runtime.tool_executor import ToolExecutor

    executor = ToolExecutor(
        registry=registry,
        policy=PermissionPolicy(
            capabilities=CapabilitySnapshot.only(*fleet_allowed_tools(registry)),
            # Nobody is watching. An ASK would either hang a scheduled job or
            # be approved by no one.
            interactive=False,
            auto_accept=False,
        ),
        working_dir=working_dir,
    )

    if tool_parser is None:
        from agent.coding.tool_parser import ToolCallParser

        tool_parser = ToolCallParser()

    return AgentSession(
        llm=llm,
        executor=executor,
        model=model,
        mode=mode,
        history=[{"role": "system", "content": system_prompt or ""}],
        tool_parser=tool_parser,
        max_tool_rounds=max_tool_rounds,
        llm_kwargs={
            "temperature": DEFAULT_TEMPERATURE,
            "max_tokens": DEFAULT_MAX_TOKENS,
        },
    )


async def session_llm_call(
    model: str,
    system_prompt: str,
    user_prompt: str,
    *,
    registry: Any = None,
    llm: Any = None,
    mode: str = "fin",
) -> str:
    """`worker_turn`'s LLM seam, backed by `AgentSession`.

    Same signature and same return as the `requests.post` implementation it
    replaces, so persona handlers are unchanged.
    """
    from agent.runtime.headless import consume
    from agent.services import agent_audit

    if llm is None:
        from agent.runtime.providers.openai_sse import OpenAICompatibleStream
        from agent.services.llm_provider import LLMProviderService

        provider = LLMProviderService(model=model).resolve_with_fallback(model)
        llm = OpenAICompatibleStream(
            provider["base_url"], provider.get("api_key", ""), timeout=90.0,
        )

    if registry is None:
        from agent.tools import ToolRegistry

        registry = ToolRegistry(working_dir="")

    messages = [
        {"role": "system", "content": system_prompt or ""},
        {"role": "user", "content": user_prompt},
    ]

    req_id = agent_audit.new_req_id()
    agent_audit.audit_request(
        req_id=req_id,
        endpoint=_ENDPOINT,
        agent_id="fleet-worker",
        messages=messages,
        model=model,
        max_tokens=DEFAULT_MAX_TOKENS,
        temperature=DEFAULT_TEMPERATURE,
    )
    t0 = time.monotonic()

    session = build_worker_session(
        llm=llm,
        registry=registry,
        model=model,
        system_prompt=system_prompt,
        mode=mode,
    )

    try:
        result = await consume(session.run_turn(user_prompt))
    except Exception as exc:
        agent_audit.audit_error(
            req_id=req_id,
            endpoint=_ENDPOINT,
            agent_id="fleet-worker",
            error_type=type(exc).__name__,
            error_msg=str(exc),
            traceback_text=traceback.format_exc(),
            duration_ms=int((time.monotonic() - t0) * 1000),
        )
        raise

    duration_ms = int((time.monotonic() - t0) * 1000)

    if not result.ok:
        # A failed turn is an error to the caller, exactly as a non-200 was.
        # `worker_turn.execute_task` catches it and reports status=failed.
        agent_audit.audit_error(
            req_id=req_id,
            endpoint=_ENDPOINT,
            agent_id="fleet-worker",
            error_type=result.error_code or "llm_error",
            error_msg=result.error_message,
            traceback_text="",
            duration_ms=duration_ms,
        )
        from fleet.worker_turn import WorkerTurnError

        raise WorkerTurnError(
            f"fleet worker turn failed [{result.error_code}]: {result.error_message}"
        )

    agent_audit.audit_response(
        req_id=req_id,
        endpoint=_ENDPOINT,
        agent_id="fleet-worker",
        content=result.response,
        reasoning_content=None,
        finish_reason="stop",
        usage=dict(result.usage),
        duration_ms=duration_ms,
    )
    return result.response
