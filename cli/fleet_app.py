"""
Multi-agent tabbed terminal view for an active fleet.

This is the "fleet mode" UI that takes over the terminal when the
user runs ``/fleet start <project>`` inside the normal NeoMind CLI.
It's a **full prompt_toolkit Application** with its own layout —
not a one-shot ``print()`` into the PromptSession scrollback.

The user asked (2026-04-12) for per-agent conversation that's
preserved across focus switches, arrow-key navigation, and one
terminal window. This file delivers that. The core design is:

  1. **State-driven message source**. The message window's content
     is produced by a function that reads ``session.focus`` and
     picks either the leader's chat history or a specific sub-
     agent's ``AgentTranscript.turns`` as its data source. Switching
     focus changes the state var → ``app.invalidate()`` → layout
     re-renders. Nothing is cleared or printed into scrollback; the
     Window just redraws from whatever list is current.

  2. **Periodic refresh for live updates**. The Application has
     ``refresh_interval=0.5`` so it re-renders twice per second.
     That picks up any new turns that fleet workers appended to
     the transcripts in the background while the user was staring
     at the screen.

  3. **Keyboard navigation via Ctrl+arrows + Esc**. Ctrl+→ / Ctrl+←
     cycle focus through ``[leader, @member1, @member2, ...]``.
     Esc jumps back to the leader. Ctrl+D exits the Application
     and returns control to the outer PromptSession CLI.

  4. **Input routing by focus**. When the user presses Enter:
       - Focus on leader + ``@<name> ...``  → dispatch to that member
       - Focus on a sub-agent  → dispatch the text as a task to it
       - Focus on leader + no mention  → (MVP scope) shown as a
         hint that leader chat is handled in the main CLI

     Sub-agent dispatches happen via ``session.submit_to_member``
     which records the user turn in the transcript and schedules
     the LLM call on the same asyncio loop the Application runs on.

Clean-room notice: the architectural ideas in this file are
Python/prompt_toolkit-native. They were inspired by looking at how
Claude Code structures its multi-agent UI (single scrollable view
with a swappable message source, per-agent persistent history,
arrow-key navigation) but no code or names were copied — this
implementation uses my own class/method/state naming and my own
layout composition for prompt_toolkit.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, List, Optional, Tuple

try:
    from prompt_toolkit import Application
    from prompt_toolkit.buffer import Buffer
    from prompt_toolkit.formatted_text import FormattedText
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import HSplit, Layout, Window
    from prompt_toolkit.layout.controls import (
        BufferControl,
        FormattedTextControl,
    )
    from prompt_toolkit.styles import Style
    PT_AVAILABLE = True
except ImportError:
    PT_AVAILABLE = False

from fleet.session import FleetSession, LEADER_FOCUS
from fleet.transcripts import AgentTurn

logger = logging.getLogger(__name__)

__all__ = [
    "FleetApplication",
    "run_fleet_application",
    "FleetAppError",
]


class FleetAppError(RuntimeError):
    """Raised when the fleet application can't start (no prompt_toolkit,
    no active session, etc.)."""


# Style mapping — kept small, all tags are used inside the render
# functions via ``("class:name", text)`` tuples.
_FLEET_STYLE = Style.from_dict({
    "status":       "bg:#1a1a2e #e0e0e0",
    "statustag":    "#8080a0",
    "leadertag":    "fg:#8cf8ff bold",
    "focustag":     "fg:#ff80ff bold",
    "banner":       "fg:#888888",
    "leadbanner":   "fg:#8cf8ff bold",
    "focusbanner":  "fg:#ff80ff bold",
    "persona":      "fg:#888888",
    "user":         "fg:#ffffff bold",
    "assistant":    "fg:#88ff88",
    "system":       "fg:#888888 italic",
    "meta":         "fg:#666666",
    "hint":         "fg:#5c6a90 italic",
    "hintinput":    "fg:#e0c070 italic",
    "help":         "bg:#0d0d1a fg:#666666 italic",
    "input":        "fg:#ffffff",
    "error":        "fg:#ff6060 bold",
})


def _role_style(role: str) -> str:
    return {
        "user": "class:user",
        "assistant": "class:assistant",
        "system": "class:system",
        "meta": "class:meta",
        "tool": "class:meta",
    }.get(role, "")


class FleetApplication:
    """prompt_toolkit Application that renders a fleet multi-agent
    view and routes user input to the focused target.

    Lifecycle (typical):

        async def _launch():
            if not session.running:
                await session.start()
            app = FleetApplication(session, leader_chat=self.chat)
            reason = await app.run_async()
            # reason is one of "ctrl_d" / "user_stop"

    The caller is responsible for the session's lifecycle around the
    application — this class does NOT start or stop the fleet. It
    only drives the UI and dispatches user input to it.
    """

    def __init__(
        self,
        session: FleetSession,
        leader_chat: Optional[Any] = None,
    ):
        if not PT_AVAILABLE:
            raise FleetAppError(
                "prompt_toolkit is not installed — fleet multi-agent "
                "view requires it"
            )
        if session is None:
            raise FleetAppError("fleet application requires a FleetSession")
        self.session = session
        self.leader_chat = leader_chat
        self._exit_reason: str = "normal"

        # Single-line input buffer. The accept_handler fires on Enter
        # and routes the text based on current focus.
        self.input_buffer = Buffer(
            accept_handler=self._on_submit,
            multiline=False,
        )

        # Layout composition. prompt_toolkit's HSplit stacks children
        # vertically; each child's Window has a height= constraint or
        # auto-sizes. Order top-to-bottom:
        #
        #   1. status bar (project, uptime, tags)             height=1
        #   2. message area (leader history or agent turns)    fills
        #   3. prompt hint (what typing does here)             height=1
        #   4. input buffer (single-line, user typing)         height=1
        #   5. help bar (key reminders)                        height=1
        self.layout = Layout(HSplit([
            Window(
                FormattedTextControl(self._render_status_bar),
                height=1,
                style="class:status",
            ),
            Window(
                FormattedTextControl(self._render_message_area),
                wrap_lines=True,
            ),
            Window(
                FormattedTextControl(self._render_prompt_hint),
                height=1,
            ),
            Window(
                BufferControl(buffer=self.input_buffer),
                height=1,
                style="class:input",
            ),
            Window(
                FormattedTextControl(self._render_help_bar),
                height=1,
                style="class:help",
            ),
        ]))

        self.app = Application(
            layout=self.layout,
            key_bindings=self._build_key_bindings(),
            full_screen=True,
            mouse_support=False,
            style=_FLEET_STYLE,
            refresh_interval=0.5,
        )

    # ── Key bindings ───────────────────────────────────────────────

    def _build_key_bindings(self) -> "KeyBindings":
        kb = KeyBindings()

        @kb.add("c-right")
        def _focus_next(event):
            """Cycle focus forward through [leader, agents...]."""
            self.session.cycle_focus(+1)
            event.app.invalidate()

        @kb.add("c-left")
        def _focus_prev(event):
            """Cycle focus backward."""
            self.session.cycle_focus(-1)
            event.app.invalidate()

        @kb.add("escape")
        def _focus_leader(event):
            """Jump straight back to the leader view."""
            self.session.set_focus(LEADER_FOCUS)
            event.app.invalidate()

        @kb.add("c-d", eager=True)
        def _exit(event):
            """Exit multi-agent view and return to PromptSession CLI.

            Note: this does NOT stop the fleet — workers keep running
            in the background. User can re-enter with /fleet show or
            explicitly /fleet stop to tear down.
            """
            self._exit_reason = "ctrl_d"
            event.app.exit()

        return kb

    # ── Rendering (pure functions of session state) ────────────────

    def _render_status_bar(self) -> FormattedText:
        """Top bar: project id + uptime + focus-marked tag list.

        Implemented as a list of (style, text) tuples so the user can
        see at a glance (a) which project is active, (b) which agent
        has focus, (c) roughly how long the fleet has been running.
        """
        parts: List[Tuple[str, str]] = [
            ("class:statustag", " FLEET "),
            ("class:status", f" {self.session.project_id} "),
            ("class:statustag", f"│ uptime {int(self.session.uptime)}s "),
            ("class:statustag", "│ "),
        ]
        leader_name = self._leader_name()
        if self.session.is_focused_on_leader():
            parts.append(("class:leadertag", f"[{leader_name}]"))
        else:
            parts.append(("class:statustag", f"[{leader_name}]"))
        for name in self.session.member_names():
            focused = (self.session.focus == name)
            if focused:
                parts.append(("class:focustag", f" @{name}*"))
            else:
                parts.append(("class:statustag", f" @{name}"))
        parts.append(("class:statustag", " "))
        return FormattedText(parts)

    def _render_message_area(self) -> FormattedText:
        """Core state-driven message source switch.

        If focus is on the leader (LEADER_FOCUS sentinel), render the
        main session's chat history. Otherwise render the focused
        sub-agent's persistent AgentTranscript. Per user requirement:
        switching focus preserves each side's content because both
        are drawn from independent persistent lists, not a single
        ring buffer.
        """
        if self.session.is_focused_on_leader():
            return self._render_leader_view()
        return self._render_agent_view()

    def _render_leader_view(self) -> FormattedText:
        parts: List[Tuple[str, str]] = []
        parts.append(("class:leadbanner",
                      f"╭─ Leader · {self.session.project_id}\n"))
        parts.append(("class:banner",
                      "│  This is the main session view. Typed input in the multi-\n"))
        parts.append(("class:banner",
                      "│  agent layer supports @<agent> dispatch only — normal chat\n"))
        parts.append(("class:banner",
                      "│  with the main persona happens in the regular CLI (Ctrl+D to\n"))
        parts.append(("class:banner",
                      "│  exit this view). Fleet workers continue running underneath.\n"))
        parts.append(("class:banner", "│\n"))

        leader_history = self._leader_recent_history(limit=12)
        if not leader_history:
            parts.append(("class:system",
                          "│  (no prior chat history to display)\n"))
        else:
            for role, content in leader_history:
                parts.extend(self._format_history_row(role, content))

        parts.append(("class:banner", "│\n"))
        parts.append(("class:banner", "╰─ "))
        parts.append(("class:hint",
                      "Ctrl+→ focus next agent  •  Esc to leader  •  "
                      "Ctrl+D exit view\n"))
        return FormattedText(parts)

    def _render_agent_view(self) -> FormattedText:
        name = self.session.focused_member_name()
        if not name:
            return FormattedText([("class:error", "no focused member")])
        member = self.session.get_member(name)
        if not member:
            return FormattedText([("class:error", f"unknown member: {name}")])

        transcript = self.session.get_transcript(name)

        parts: List[Tuple[str, str]] = []
        parts.append(("class:focusbanner", f"╭─ @{name}"))
        parts.append(("class:persona",
                      f"   ({member.persona} · {member.role})  "
                      f"project={self.session.project_id}\n"))
        parts.append(("class:banner", "│\n"))

        if transcript is None or transcript.turn_count() == 0:
            parts.append(("class:system",
                          "│  (no conversation yet — type below to dispatch a task)\n"))
        else:
            # Show up to the last 50 turns. Long histories scroll off
            # the top of the window naturally via prompt_toolkit's
            # rendering (wrap_lines handles vertical overflow).
            recent = transcript.turns[-50:]
            for turn in recent:
                parts.extend(self._format_transcript_turn(turn, name))

        parts.append(("class:banner", "│\n"))
        parts.append(("class:banner", "╰─ "))
        parts.append(("class:hint",
                      f"type and Enter to dispatch to @{name}  •  "
                      "Ctrl+← / Ctrl+→ cycle  •  Esc → leader  •  Ctrl+D exit\n"))
        return FormattedText(parts)

    def _format_transcript_turn(
        self, turn: AgentTurn, agent_name: str,
    ) -> List[Tuple[str, str]]:
        """Render one AgentTurn into a sequence of style-tagged text
        tuples suitable for FormattedText."""
        if turn.role == "user":
            label = "you"
        elif turn.role == "assistant":
            label = f"@{agent_name}"
        elif turn.role == "system":
            label = "sys"
        elif turn.role == "meta":
            label = "·"
        else:
            label = turn.role
        style = _role_style(turn.role)
        prefix = ("class:banner", "│  ")
        tag = (style, f"{label}: ")
        body = (style, f"{turn.content[:800]}\n")
        return [prefix, tag, body]

    def _format_history_row(
        self, role: str, content: str,
    ) -> List[Tuple[str, str]]:
        """Render one row from the leader's chat history (NeoMindAgent
        conversation_history shape: {'role': str, 'content': str})."""
        if role == "user":
            label_style = "class:user"
            label = "you: "
        elif role == "assistant":
            label_style = "class:assistant"
            label = "assistant: "
        else:
            label_style = "class:system"
            label = f"[{role}] "
        snippet = content[:800] if isinstance(content, str) else str(content)[:800]
        return [
            ("class:banner", "│  "),
            (label_style, label),
            (label_style, f"{snippet}\n"),
        ]

    def _render_prompt_hint(self) -> FormattedText:
        if self.session.is_focused_on_leader():
            return FormattedText([
                ("class:hintinput",
                 " › leader mode · type @agent_name <message> to dispatch · "
                 "Ctrl+→ to focus an agent "),
            ])
        name = self.session.focused_member_name()
        return FormattedText([
            ("class:hintinput",
             f" › sub-agent mode · type a message and press Enter to "
             f"dispatch to @{name} "),
        ])

    def _render_help_bar(self) -> FormattedText:
        return FormattedText([
            ("class:help", " Ctrl+← / Ctrl+→ cycle focus   "),
            ("class:help", "Esc → leader   "),
            ("class:help", "Ctrl+D exit multi-agent view   "),
            ("class:help", "/exit or /fleet stop to tear down"),
        ])

    # ── Input handling ─────────────────────────────────────────────

    def _on_submit(self, buf: "Buffer") -> bool:
        """prompt_toolkit calls this when the user presses Enter."""
        text = buf.text.strip()
        buf.reset()
        if not text:
            return False  # keep the buffer open for next input

        # Inline exit commands — support both /exit and /fleet stop
        if text in ("/exit", "/fleet stop", "exit", "quit", "/quit"):
            self._exit_reason = "user_stop" if "stop" in text else "user_exit"
            self.app.exit()
            return True

        if self.session.is_focused_on_leader():
            # Leader view: only @mention dispatch is wired up in MVP
            mention = self.session.handle_leader_input(text)
            if mention is not None:
                target_name, rest = mention
                self._dispatch_in_background(target_name, rest)
            else:
                # Surface a transient note in the agent view — but
                # since we're in leader view, there's no agent buffer
                # to append to. Use the log for now; UI will refresh
                # and render a tip in the next refresh cycle.
                logger.info(
                    "leader view received non-@ input; ignored in MVP: %r",
                    text[:80],
                )
            self.app.invalidate()
            return False

        # Sub-agent focused — dispatch directly
        name = self.session.focused_member_name()
        if name:
            self._dispatch_in_background(name, text)
            self.app.invalidate()
        return False

    def _dispatch_in_background(self, target_member: str, text: str) -> None:
        """Schedule a submit_to_member on the current event loop
        without blocking input handling.

        Uses ``asyncio.get_event_loop().create_task(...)`` because the
        accept_handler runs synchronously within the Application's
        event loop. ``create_task`` schedules the coroutine and
        returns immediately so the UI stays responsive.
        """
        try:
            loop = asyncio.get_event_loop()
            loop.create_task(
                self.session.submit_to_member(target_member, text)
            )
        except Exception as exc:
            logger.error(
                "fleet dispatch background failed for @%s: %s",
                target_member, exc,
            )

    # ── Helpers ────────────────────────────────────────────────────

    def _leader_name(self) -> str:
        for m in self.session.config.members:
            if m.role == "leader":
                return m.name
        return "leader"

    def _leader_recent_history(
        self, limit: int = 12,
    ) -> List[Tuple[str, str]]:
        """Return the last N (role, content) pairs from the main
        CLI's conversation_history, filtered to user+assistant messages.

        Defensive: the NeoMindAgent may or may not have
        conversation_history at the moment this renders. Return an
        empty list on any error so the UI still renders.
        """
        if self.leader_chat is None:
            return []
        history = getattr(self.leader_chat, "conversation_history", None)
        if not history:
            return []
        out: List[Tuple[str, str]] = []
        for msg in history[-limit:]:
            if not isinstance(msg, dict):
                continue
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if role == "system":
                continue  # skip system prompt injection
            if isinstance(content, list):
                # tool-using message shape — flatten text parts
                content = " ".join(
                    c.get("text", "") for c in content
                    if isinstance(c, dict) and c.get("type") == "text"
                )
            if not isinstance(content, str):
                content = str(content)
            out.append((role, content))
        return out

    # ── Run ────────────────────────────────────────────────────────

    async def run_async(self) -> str:
        """Drive the Application until Ctrl+D or an explicit exit
        command. Returns the exit reason string."""
        await self.app.run_async()
        return self._exit_reason


async def run_fleet_application(
    session: FleetSession,
    leader_chat: Optional[Any] = None,
    *,
    start_session: bool = True,
    stop_session_on_exit: bool = False,
) -> str:
    """High-level entry point used by the CLI.

    Args:
        session: The FleetSession to render.
        leader_chat: The main NeoMindAgent, used to render leader
            view's chat history snippet. Pass None for headless use.
        start_session: If True, call ``session.start()`` before
            running the UI. If the session is already running this
            is a no-op.
        stop_session_on_exit: If True, call ``session.stop()`` after
            the Application exits. Default False — the caller can
            keep the fleet running in the background and re-enter
            the multi-agent view later via ``/fleet show``.

    Returns:
        The exit reason string from FleetApplication.run_async.
    """
    if start_session and not session.running:
        await session.start()

    app = FleetApplication(session, leader_chat=leader_chat)
    try:
        reason = await app.run_async()
    finally:
        if stop_session_on_exit and session.running:
            await session.stop()
    return reason
