"""Serve NeoMind over the Agent Client Protocol.

Phase 7. The operator's decision was to stop building interfaces and be
drivable by existing ones: DeepSeek Harness drives external agents over ACP
(`subagent-acp`), Zed speaks it natively, and anything else that implements the
standard gets NeoMind for free.

This is a composition root, the same kind of thing as
`agent/integration/telegram_session.py` and `fleet/worker_session.py`: it picks
a provider, a registry, a capability policy and a permission mode, then hands
`AgentSession` the pieces. It draws nothing and owns no turn logic.

**ACP is the first remote surface that can actually ask.** Telegram and fleet
are `interactive=False` because nobody is there to answer a permission prompt —
an ASK there can only resolve to DENY. An ACP client implements
`request_permission`, so this surface is interactive, and the broker port from
Phase 4 finally has a second consumer. That is why the tool policy here is
wider than Telegram's: the user is present, through their client.

One session per ACP session id, each with its own forked config, so two clients
setting different modes do not overwrite each other — the property Phase 6A
established and the one this surface would have broken first.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional

import acp
from acp import schema

from agent.runtime.events import TurnFailed, TurnFinished

from .acp_translate import _tag, stop_reason_for, translate, turn_usage

#: The protocol revision this server implements. Echoed back in `initialize`;
#: a client that speaks something else sees the mismatch immediately rather
#: than after a malformed update.
PROTOCOL_VERSION = 1

#: Modes a client may switch between, matching the CLI's personalities.
SESSION_MODES = ("chat", "coding", "fin")

#: What a client is shown in a mode picker. The ids are the same strings
#: `set_session_mode` validates, so a client can round-trip what it was given
#: without knowing anything about NeoMind.
SESSION_MODE_DESCRIPTIONS = {
    "chat": ("Chat", "General conversation."),
    "coding": ("Coding", "Reads and edits code in the workspace."),
    "fin": ("Finance", "Markets, filings, and portfolio analysis."),
}

#: What an ACP client may reach for.
#:
#: Wider than Telegram's and fleet's because those cannot ask and this can —
#: but still an allowlist rather than "everything registered", so a mislabelled
#: destructive tool cannot walk in. Writes and execution are present because a
#: client can refuse them; they still go through the same ToolExecutor, and an
#: unanswered request still ends as DENY.
ACP_TOOLS = (
    "Read", "Glob", "Grep", "LS", "WebSearch", "WebFetch",
    "Write", "Edit", "Bash",
)


@dataclass
class _Session:
    """One ACP session: its agent session, its config, its cwd.

    `config` holds the manager itself rather than a contextvar token. The token
    was useless: `set_current_config` binds only the calling task, the SDK runs
    every request in its own task, so the binding made in `session/new` was
    already gone by the time `session/prompt` arrived — and nothing ever read
    the token back. Holding the object lets the turn bind it for real.
    """

    session_id: str
    cwd: str
    mode: str = "coding"
    config: Any = None
    history: List[Dict[str, Any]] = field(default_factory=list)
    active_turn: Optional[str] = None
    cancelled: bool = False


class NeoMindACPAgent(acp.Agent):
    """NeoMind, as an ACP agent.

    `session_factory` is injected so the whole class is testable without a
    provider: the tests drive real ACP models through a fake session, which is
    the only way to catch a wrong field name before a client does.
    """

    def __init__(
        self,
        *,
        session_factory: Optional[Any] = None,
        default_mode: str = "coding",
    ) -> None:
        self._sessions: Dict[str, _Session] = {}
        self._agent_sessions: Dict[str, Any] = {}
        self._client: Optional[acp.Client] = None
        self._session_factory = session_factory or self._build_agent_session
        self._default_mode = default_mode
        self._counter = 0

    # ── lifecycle ─────────────────────────────────────────────────────────

    def on_connect(self, conn: acp.Client) -> None:
        """The client half arrives here; the permission broker needs it."""
        self._client = conn

    async def initialize(
        self,
        protocol_version: int,
        client_capabilities: Any = None,
        client_info: Any = None,
        **kwargs: Any,
    ) -> Any:
        return schema.InitializeResponse(
            protocol_version=PROTOCOL_VERSION,
            agent_capabilities=schema.AgentCapabilities(
                load_session=False,
                # `close_session` has always been implemented and never
                # advertised, so no client called it and `_sessions` only ever
                # grew — harmless for a per-run stdio process, a leak for a
                # server that stays up. Only `close` is claimed: listing,
                # deletion, forking and resuming are not implemented, and
                # advertising them would invite calls that fail.
                # Presence is the claim — the field takes a capability object,
                # not a bool, and pydantic drops a bool without complaining, so
                # `close=True` reads back as `None` and advertises nothing.
                session_capabilities=schema.SessionCapabilities(
                    close=schema.SessionCloseCapabilities(),
                ),
            ),
        )

    async def new_session(self, cwd: str, **kwargs: Any) -> Any:
        from agent_config import fork_current_config

        self._counter += 1
        session_id = f"neomind-{self._counter}"

        # Each ACP session gets its own config. Without this, a second client
        # setting a different mode would silently change the first client's —
        # the process-wide default that Phase 6A moved into the session.
        #
        # The fork is kept, not bound: binding here would die with this
        # request's task. `prompt` binds it around the turn instead.
        config = fork_current_config()
        # Only switch when the mode actually differs. `switch_mode` rebuilds the
        # active config from YAML, which discards a system prompt someone set at
        # runtime — the very loss `fork_current_config` exists to avoid — so an
        # unconditional call would quietly undo a `--system-prompt` override.
        if getattr(config, "mode", None) != self._default_mode:
            config.switch_mode(self._default_mode)

        self._sessions[session_id] = _Session(
            session_id=session_id, cwd=cwd, mode=self._default_mode,
            config=config,
        )
        # Without this the modes are unreachable from outside: `set_session_mode`
        # worked, but nothing told a client the ids existed, so a client with a
        # mode picker had nothing to put in it and one without could only guess.
        return schema.NewSessionResponse(
            session_id=session_id,
            modes=self._mode_state(self._default_mode),
        )

    @staticmethod
    def _mode_state(current: str) -> Any:
        return schema.SessionModeState(
            current_mode_id=current,
            available_modes=[
                schema.SessionMode(
                    id=mode_id,
                    name=SESSION_MODE_DESCRIPTIONS[mode_id][0],
                    description=SESSION_MODE_DESCRIPTIONS[mode_id][1],
                )
                for mode_id in SESSION_MODES
            ],
        )

    async def close_session(self, session_id: str, **kwargs: Any) -> Any:
        self._sessions.pop(session_id, None)
        self._agent_sessions.pop(session_id, None)
        return None

    async def set_session_mode(self, session_id: str, mode_id: str, **kwargs: Any) -> Any:
        session = self._require(session_id)
        if mode_id not in SESSION_MODES:
            raise ValueError(f"unknown mode {mode_id!r}; expected one of {SESSION_MODES}")
        session.mode = mode_id
        # The mode has to reach the config too, not just the session record:
        # the personality, the model and the system prompt all read from the
        # active mode, so setting only `session.mode` renamed the mode without
        # changing the agent.
        if session.config is not None:
            session.config.switch_mode(mode_id)
        # A fresh agent session is built per turn, so the next one picks this
        # up; nothing cached needs invalidating.
        self._agent_sessions.pop(session_id, None)
        # A client that did not initiate the switch — a second one attached to
        # the same session, or the same one after a reconnect — has no other way
        # to learn the mode changed.
        if self._client is not None:
            await self._client.session_update(
                session_id,
                schema.CurrentModeUpdate(
                    session_update=_tag(schema.CurrentModeUpdate),
                    current_mode_id=mode_id,
                ),
            )
        return None

    # ── the turn ──────────────────────────────────────────────────────────

    async def prompt(self, session_id: str, prompt: List[Any], **kwargs: Any) -> Any:
        session = self._require(session_id)
        session.cancelled = False
        text = self._prompt_text(prompt)

        # Bind the session's config for the whole turn. Everything downstream
        # reads `agent_config` through the contextvar proxy — the model, the
        # personality, the permission mode — and this request runs in its own
        # task, so without binding here it would all come from the process-wide
        # default and the session's mode would be decoration.
        token = self._bind_config(session)
        try:
            # Seeded here rather than inside the composition root so that every
            # session the turn can run against gets the briefing — including an
            # injected one. Needs the config bound above, because which prompt
            # applies depends on the session's mode.
            session.history = self._seeded_history(session)
            return await self._run_turn(session, text)
        finally:
            self._unbind_config(token)

    async def _run_turn(self, session: "_Session", text: str) -> Any:
        session_id = session.session_id
        agent_session = self._session_factory(session)
        self._agent_sessions[session_id] = agent_session
        terminal: Any = None

        async for event in agent_session.run_turn(text):
            session.active_turn = getattr(event, "turn_id", None)
            if isinstance(event, (TurnFinished, TurnFailed)):
                terminal = event
                break
            update = translate(event)
            if update is not None and self._client is not None:
                await self._client.session_update(session_id, update)

        session.active_turn = None
        usage = getattr(terminal, "usage", None) if terminal else None
        return schema.PromptResponse(
            stop_reason=stop_reason_for(terminal),
            usage=turn_usage(usage),
        )

    async def cancel(self, session_id: str, **kwargs: Any) -> None:
        """ACP's cancel is a notification, not a request — it returns nothing
        and must not raise for an unknown session."""
        session = self._sessions.get(session_id)
        if session is None:
            return
        session.cancelled = True
        agent_session = self._agent_sessions.get(session_id)
        if agent_session is not None and session.active_turn:
            await agent_session.cancel(session.active_turn)

    class _HistoryStore:
        """Writes the turn's messages back into the ACP session.

        Without it the session had no memory. `session.history` was read to
        seed each turn and never written, so turn two started from the same
        list as turn one: a client that asked a follow-up got an agent which
        had forgotten the question it had just answered. Every other surface
        writes back — the CLI into `chat.conversation_history`, Telegram into
        its store — and this one only looked like it did.

        Underscore-prefixed keys are dropped, same as the CLI's store: they are
        the runtime's own bookkeeping and do not belong in a message sent back
        to a provider.
        """

        def __init__(self, session: "_Session") -> None:
            self.session = session

        def append(self, session_id: str, message: Mapping[str, Any]) -> None:
            entry = {k: v for k, v in dict(message).items() if not k.startswith("_")}
            self.session.history.append(entry)

        def load(self, session_id: str) -> List[Dict[str, Any]]:
            return list(self.session.history)

    # ── config binding ────────────────────────────────────────────────────

    @staticmethod
    def _bind_config(session: "_Session") -> Any:
        """Make the session's config current, returning a token to undo it.

        Returns None when the session has no config of its own — the injected
        test factories construct `_Session` directly — so the caller can treat
        "nothing to unbind" the same as a successful unbind.
        """
        if session.config is None:
            return None
        from agent_config import set_current_config

        return set_current_config(session.config)

    @staticmethod
    def _unbind_config(token: Any) -> None:
        if token is None:
            return
        from agent_config import reset_current_config

        reset_current_config(token)

    # ── composition ───────────────────────────────────────────────────────

    def _build_agent_session(self, session: _Session) -> Any:
        """The real wiring. Mirrors the other surfaces' composition roots."""
        from agent.coding.tool_parser import ToolCallParser
        from agent.runtime.permissions import CapabilitySnapshot, PermissionPolicy
        from agent.runtime.providers.openai_sse import OpenAICompatibleStream
        from agent.runtime.session import AgentSession
        from agent.runtime.tool_executor import ToolExecutor
        from agent.services.llm_provider import LLMProviderService
        from agent.tools import ToolRegistry
        from agent_config import agent_config

        model = getattr(agent_config, "model", "") or ""
        provider = LLMProviderService(model=model).resolve_with_fallback(model)
        llm = OpenAICompatibleStream(
            provider["base_url"], provider.get("api_key", ""), timeout=180.0,
        )

        registry = ToolRegistry(working_dir=session.cwd)
        allowed = self._allowed_tools(registry)

        executor = ToolExecutor(
            registry=registry,
            policy=PermissionPolicy(
                capabilities=CapabilitySnapshot.only(*allowed),
                # The client can answer. That is the whole difference between
                # this surface and Telegram or fleet.
                interactive=True,
                auto_accept=False,
            ),
            broker=self._permission_broker(session),
            working_dir=session.cwd,
        )

        return AgentSession(
            llm=llm,
            executor=executor,
            model=model,
            mode=session.mode,
            session_id=session.session_id,
            history=list(session.history),
            store=self._HistoryStore(session),
            tool_parser=ToolCallParser(),
        )

    @staticmethod
    def _seeded_history(session: "_Session") -> List[Dict[str, Any]]:
        """The session's history with the mode's system prompt at its head.

        Every other surface does this — the CLI through
        `core._ensure_system_prompt`, a fleet worker by passing one in — but
        this one shipped without it, so an ACP client got a model with no
        briefing: no personality, no working directory, no notion that it had
        tools. It answered a question about the repository it was running
        inside by asking for a link to it.

        Idempotent against a history that already carries the prompt, so
        resuming a session does not stack duplicates.
        """
        from agent_config import agent_config

        history = list(session.history)
        prompt = getattr(agent_config, "system_prompt", "") or ""
        if not prompt:
            return history
        if any(
            msg.get("role") == "system" and msg.get("content") == prompt
            for msg in history
        ):
            return history
        return [{"role": "system", "content": prompt}, *history]

    @staticmethod
    def _allowed_tools(registry: Any) -> List[str]:
        """Allowlist ∩ registered. The level is *not* re-checked here, unlike
        the unattended surfaces: a client can be asked about a write, so the
        gate is the permission answer rather than the declared level."""
        out = []
        for name in ACP_TOOLS:
            getter = getattr(registry, "get_tool", None)
            try:
                if callable(getter) and getter(name) is not None:
                    out.append(name)
            except Exception:
                continue
        return out

    def _permission_broker(self, session: _Session) -> Any:
        """Bridge the executor's broker port onto `client.request_permission`.

        The Phase 4 port asked for `params` for exactly this reason: a dialog
        that cannot show what it is approving is the failure this layer exists
        to prevent, and ACP's `tool_call` field is where that goes.
        """
        client = self._client

        class _Broker:
            async def request(
                self,
                request_id: str,
                tool_name: str,
                preview: str = "",
                risk: str = "",
                explanation: str = "",
                allowed_scopes: Any = None,
                params: Any = None,
                **_ignored: Any,
            ) -> Any:
                """Ask the ACP client, and return an `Approval` or None.

                An `Approval`, not a bool and not a `Decision`. The executor
                refuses anything else — "a bare True names no call, so it
                cannot be bound to one" — and returning the wrong type silently
                denied every tool for a whole phase of the REPL migration.

                The fingerprint is derived from the same params the executor is
                about to run, so an approval cannot be replayed onto a
                different call.
                """
                from agent.runtime.permissions import Approval, Scope, fingerprint

                if client is None:
                    # No client attached means nobody can answer, and the
                    # executor treats an unanswered request as a denial.
                    return None

                options = [
                    schema.PermissionOption(
                        option_id="allow", name="Allow", kind="allow_once",
                    ),
                    schema.PermissionOption(
                        option_id="allow_always", name="Always allow", kind="allow_always",
                    ),
                    schema.PermissionOption(
                        option_id="reject", name="Reject", kind="reject_once",
                    ),
                ]
                answer = await client.request_permission(
                    session.session_id,
                    schema.ToolCallUpdate(
                        tool_call_id=request_id,
                        title=tool_name,
                        # What is being approved, not just its name. A dialog
                        # that cannot show this is the failure this layer
                        # exists to prevent.
                        raw_input=dict(params or {}) or None,
                    ),
                    options,
                )
                # `outcome` is a discriminated union: AllowedOutcome carries
                # the chosen option_id, DeniedOutcome carries only
                # outcome="cancelled" and has no option_id at all. Reading
                # `.option_id` and comparing would *work* — by accident,
                # because a denial yields None — but it would be right for the
                # wrong reason, and the REPL already shipped one permission
                # bridge that was wrong for a reason nobody could see.
                outcome = getattr(answer, "outcome", None)
                if getattr(outcome, "outcome", None) != "selected":
                    return None
                chosen = getattr(outcome, "option_id", None)
                if chosen not in ("allow", "allow_always"):
                    return None
                return Approval(
                    request_id=request_id,
                    fingerprint=fingerprint(
                        tool_name, dict(params or {}), session.cwd
                    ),
                    scope=Scope.SESSION_PATTERN if chosen == "allow_always" else Scope.ONCE,
                )

        return _Broker()

    # ── helpers ───────────────────────────────────────────────────────────

    def _require(self, session_id: str) -> _Session:
        session = self._sessions.get(session_id)
        if session is None:
            raise ValueError(f"unknown session {session_id!r}")
        return session

    @staticmethod
    def _prompt_text(prompt: List[Any]) -> str:
        """ACP sends a list of content blocks; NeoMind's turn takes a string.

        Non-text blocks are named rather than dropped silently — a user who
        attached an image should not watch it vanish with no explanation.
        """
        parts: List[str] = []
        for block in prompt or []:
            text = getattr(block, "text", None)
            if text:
                parts.append(text)
                continue
            kind = getattr(block, "type", None) or type(block).__name__
            parts.append(f"[unsupported content: {kind}]")
        return "\n".join(parts).strip()
