"""Compose an `AgentSession` for a Telegram conversation.

The composition root for the Telegram surface, the counterpart to
`main._build_headless_session` and `NeoMindInterface._build_turn_session`.
It lives outside `telegram_bot.py` so it can be tested without importing
`telegram`, and outside `agent/runtime/` because the runtime must not know
which registry or provider a surface picked (`test_import_boundary.py`).

**Telegram is a remote, non-interactive surface.** Nobody is at a terminal to
answer a permission prompt, and in a group chat the person talking to the bot
is not necessarily the person who owns the machine it runs on. So the capability
snapshot is an allowlist rather than "everything registered", and the policy is
built with `interactive=False` so an ASK resolves to DENY instead of hanging.

That matches what the bot already does, but by construction rather than by
accident. Today the agentic loop simply never sets `event.approved`, so only
READ_ONLY tools run and anything else quietly ends the turn — the user gets no
answer and no reason. Here the same call is refused explicitly and the refusal
is rendered as ⊘.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

#: What a Telegram conversation may reach for.
#:
#: Deliberately narrower than the headless allowlist: no `Read`, `Glob`, `Grep`
#: or `LS`. Headless runs on the operator's own machine from their own shell,
#: where reading a file is what they asked for. The bot runs in a container with
#: the source tree bind-mounted, and a message from a group chat asking it to
#: read `.env` should not be one mislabelled tool away from working.
#:
#: Web and finance lookups are what this surface is actually for.
TELEGRAM_READ_ONLY_TOOLS = (
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
    "finance_portfolio_show",
    "finance_watchlist_show",
    "finance_persona_debate",
    "finance_rag_query",
)

#: Telegram cuts the agentic loop shorter than the CLI. A chat window shows one
#: message being edited, so a long tool chain reads as a frozen bot, and the
#: existing loop already capped itself at 3.
DEFAULT_MAX_TOOL_ROUNDS = 3


def telegram_allowed_tools(registry: Any) -> List[str]:
    """Intersect the allowlist with what is registered and still READ_ONLY.

    Both halves matter, for the same reason they do in headless: the allowlist
    keeps a mislabelled side-effecting tool out even when it is registered, and
    re-checking the declared level means a tool that is later tightened drops
    out of the snapshot instead of silently staying in.
    """
    from agent.coding.tool_schema import PermissionLevel

    out: List[str] = []
    for name in TELEGRAM_READ_ONLY_TOOLS:
        tool = _lookup(registry, name)
        if tool is None:
            continue
        if getattr(tool, "permission_level", None) is not PermissionLevel.READ_ONLY:
            continue
        out.append(name)
    return out


def _lookup(registry: Any, name: str) -> Any:
    getter = getattr(registry, "get_tool", None)
    if callable(getter):
        try:
            return getter(name)
        except Exception:
            return None
    return (getattr(registry, "_tool_definitions", {}) or {}).get(name)


class TelegramHistoryStore:
    """Writes the session's messages into the bot's `ChatStore`.

    The session is the only writer during a turn; this is where those writes
    land so that `/history`, `/clear`, auto-compaction and the next turn all
    see one conversation rather than two copies of it.

    Tool results are deliberately *not* persisted. They are transcript, not
    conversation: replaying yesterday's search results into today's prompt
    wastes context on stale data, and the existing store has never held them.
    """

    def __init__(self, store: Any, chat_id: int, chat_type: str = "private") -> None:
        self._store = store
        self._chat_id = chat_id
        self._chat_type = chat_type

    def append(self, session_id: str, message: Mapping[str, Any]) -> None:
        if message.get("_tool_result"):
            return
        role = message.get("role", "")
        content = message.get("content", "")
        if not role or not content:
            return
        self._store.add_message(self._chat_id, role, content, self._chat_type)

    def load(self, session_id: str) -> List[Dict[str, Any]]:
        return list(self._store.get_recent_history(self._chat_id, limit=20))


def build_telegram_session(
    *,
    links: Sequence[Any],
    registry: Any,
    history: Sequence[Mapping[str, Any]],
    store: Any = None,
    model: str = "",
    mode: str = "chat",
    session_id: Optional[str] = None,
    llm_kwargs: Optional[Mapping[str, Any]] = None,
    max_tool_rounds: int = DEFAULT_MAX_TOOL_ROUNDS,
    working_dir: str = "/app",
    on_selected: Any = None,
    on_failure: Any = None,
    tool_parser: Any = None,
) -> Any:
    """Build the session for one Telegram turn.

    `links` is the provider chain the bot resolved, already ordered. It is
    wrapped in a `FallbackChain` so the session sees a single `LLMPort` and
    does not have to know that failover exists.
    """
    from agent.runtime.permissions import CapabilitySnapshot, PermissionPolicy
    from agent.runtime.providers.fallback import FallbackChain
    from agent.runtime.session import AgentSession
    from agent.runtime.tool_executor import ToolExecutor

    llm = FallbackChain(
        list(links), on_selected=on_selected, on_failure=on_failure
    )

    allowed = telegram_allowed_tools(registry)
    executor = ToolExecutor(
        registry=registry,
        policy=PermissionPolicy(
            capabilities=CapabilitySnapshot.only(*allowed),
            # No terminal, no prompt. An ASK here would either hang the turn or
            # be silently approved; DENY is the only honest answer.
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
        session_id=session_id,
        history=history,
        store=store,
        tool_parser=tool_parser,
        max_tool_rounds=max_tool_rounds,
        llm_kwargs=dict(llm_kwargs or {}),
    )
