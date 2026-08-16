"""
NeoMind interface for neomind agent.

Features:
- Key bindings: Ctrl+O (thinking toggle), Ctrl+C (cancel/interrupt), Escape (clear), Ctrl+L (clear screen), Ctrl+D (exit)
- Bottom status bar with model, mode, thinking status, tokens, and key hints
- Slash command menu with fuzzy matching and descriptions
- Rich markdown rendering for AI responses
- Compact welcome screen
- Conversation persistence (save/load)
"""

import os
import sys
import json
import time
import re
import threading
import itertools
import subprocess
import shutil
from pathlib import Path
from typing import Optional, Dict, List, Any
from datetime import datetime

# --- prompt_toolkit imports ---
try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import FileHistory, InMemoryHistory
    from prompt_toolkit.completion import Completer, Completion, CompleteEvent
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.formatted_text import HTML, ANSI
    from prompt_toolkit.styles import Style as PTStyle
    from prompt_toolkit.patch_stdout import patch_stdout
    PROMPT_TOOLKIT_AVAILABLE = True
except ImportError:
    PROMPT_TOOLKIT_AVAILABLE = False

# --- rich imports ---
try:
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.text import Text
    from rich.live import Live
    from rich.spinner import Spinner
    from rich.status import Status
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

from agent.core import NeoMindAgent
from agent.help_system import HelpSystem
from agent_config import agent_config, bind_session_config

# --- pygments imports (code block syntax highlighting) ---
try:
    from pygments import highlight as _pygments_highlight
    from pygments.lexers import get_lexer_by_name, TextLexer
    from pygments.formatters import TerminalFormatter
    PYGMENTS_AVAILABLE = True
except ImportError:
    PYGMENTS_AVAILABLE = False

_CODE_BLOCK_RE = re.compile(r'```(\w+)?\s*\n(.*?)```', re.DOTALL)


def highlight_code_block(code: str, language: str = '') -> str:
    """Highlight a code block using pygments. Graceful fallback if unavailable."""
    if not PYGMENTS_AVAILABLE or not language:
        return code
    try:
        lexer = get_lexer_by_name(language, stripall=True)
    except Exception:
        lexer = TextLexer()
    try:
        return _pygments_highlight(code, lexer, TerminalFormatter())
    except Exception:
        return code


def highlight_code_blocks_in_text(text: str) -> str:
    """Find ```lang ... ``` blocks in text and apply syntax highlighting."""
    if not PYGMENTS_AVAILABLE:
        return text

    def _replace(m):
        lang = m.group(1) or ''
        code = m.group(2)
        highlighted = highlight_code_block(code, lang)
        # Return highlighted code without the fences (the highlight adds its own formatting)
        return highlighted.rstrip('\n') + '\n'

    return _CODE_BLOCK_RE.sub(_replace, text)


# ──────────────────────────────────────────────────────────────────────────────
# Slash Command Completer
# ──────────────────────────────────────────────────────────────────────────────

def _registry_descriptions() -> dict:
    """Command descriptions read straight from the command registry.

    ALL_DESCRIPTIONS below used to be a second, hand-maintained copy of the
    same information, so every command added to the registry since it was
    written had no description here — 34 of them across chat/coding/fin, which
    is what test_all_descriptions_covers_all_commands catches. Reading the
    registry keeps the two from drifting apart again.

    Guarded: the completer must still work if the registry cannot be built.
    """
    try:
        from agent.cli_command_system import create_default_registry

        registry = create_default_registry()
        commands = getattr(registry, "commands", None) or getattr(registry, "_commands", {})
        return {
            name: getattr(cmd, "description", "") or ""
            for name, cmd in commands.items()
        }
    except Exception:
        return {}


# Commands that live outside the registry and so have to be named here.
# Sourced from their own docstrings, not invented:
#   speckit.*  — agent/coding/speckit/__init__.py module docstring
#   links/crawl/webmap — the _shared_handle_*_command docstrings in
#                        agent/services/shared_commands.py
_EXTRA_DESCRIPTIONS = {
    "links": "Extract links from a URL",
    "crawl": "Crawl a website starting from a URL",
    "webmap": "Generate a site map from a URL",
    "speckit.constitution": "Scaffold project constitution",
    "speckit.specify": "Create feature specification",
    "speckit.clarify": "Resolve [NEEDS CLARIFICATION] markers",
    "speckit.plan": "Generate implementation plan",
    "speckit.tasks": "Break plan into tasks",
    "speckit.analyze": "Cross-artifact consistency check",
    "speckit.implement": "Execute implementation",
    "speckit.checklist": "Generate quality checklist",
    "speckit.status": "Show spec-kit state",
}


class SlashCommandCompleter(Completer):
    """Mode-aware slash command completer with descriptions."""

    # All known command descriptions (superset). Hand-written entries below win
    # over the registry so curated wording is preserved; see _build_descriptions.
    _CURATED_DESCRIPTIONS = {
        # Shared
        "help": "Show available commands",
        "clear": "Clear conversation history",
        "think": "Toggle thinking mode on/off",
        "debug": "Toggle debug logs / dump recent logs",
        "models": "List and switch models",
        "switch": "Switch model",
        "history": "Show conversation history",
        "save": "Save conversation to file",
        "load": "Load previous conversation",
        "context": "Show context window usage",
        "compact": "Compact conversation to save context",
        "transcript": "View full conversation transcript",
        "expand": "Expand a turn's thinking in a pager (Ctrl+E)",
        "mode": "Switch personality (chat / coding / fin)",
        "config": "View or change runtime config (/config set temperature 0.5)",
        "skills": "List available skills for current mode",
        "careful": "Enable safety warnings for destructive operations",
        "freeze": "Restrict edits to one directory (/freeze src/)",
        "unfreeze": "Remove edit restriction",
        "guard": "Enable careful + freeze together",
        "sprint": "Structured task workflow (new/status/next/skip)",
        "evidence": "View audit trail of operations",
        "quit": "Exit the agent",
        "exit": "Exit the agent",
        # Chat-only
        "search": "Search the web",
        "browse": "Read a webpage",
        "summarize": "Summarize text or code",
        "translate": "Translate text",
        "generate": "Generate content",
        "reason": "Chain-of-thought reasoning",
        "remember": "Save user facts and preferences to shared memory",
        "recall": "Retrieve user facts and preferences from memory",
        "preferences": "View or set user preferences",
        # Coding-only (NeoMind tools)
        "read": "Read file with line numbers",
        "write": "Create or overwrite a file",
        "edit": "Edit specific sections of a file",
        "ls": "List directory contents",
        "glob": "Find files by pattern",
        "grep": "Search file contents with regex",
        "find": "Find files by name pattern",
        "run": "Execute a shell command",
        "git": "Execute git commands",
        "code": "Code analysis and refactoring",
        "fix": "Auto-fix code issues",
        "analyze": "Analyze code for issues",
        "explain": "Explain code",
        "refactor": "Suggest refactorings",
        "test": "Run tests",
        "diff": "Compare files or show changes",
        "undo": "Revert recent changes",
        "apply": "Apply pending code changes",
        "task": "Manage tasks",
        "plan": "Generate plans from goals",
        "execute": "Execute a plan",
        "todo": "Track task progress",
        "permissions": "Toggle permission mode (normal / auto_accept / plan)",
        "perf": "Analyze performance bottlenecks",
        "deploy": "Prepare deployment",
        "ship": "Finalize and push to production",
        "remember": "Save coding patterns to shared memory",
        "recall": "Retrieve user context from memory",
        # Finance-only (fin mode)
        "stock": "Look up stock price, fundamentals, and analysis",
        "crypto": "Cryptocurrency price, market cap, and trends",
        "news": "Multi-source financial news search (EN + ZH)",
        "portfolio": "View and manage tracked portfolio",
        "alert": "Set or manage price / event alerts",
        "digest": "Generate or view daily market digest",
        "memory": "Query secure local financial memory",
        "predict": "Log a prediction with confidence and timeframe",
        "compare": "Compare assets, sectors, or strategies",
        "chart": "Generate mermaid diagrams (causal, flow, pie)",
        "compute": "Run financial math (compound, DCF, Black-Scholes)",
        "sources": "View source trust scores and rankings",
        "sync": "Manage mobile sync (pair, status, push)",
        "watchlist": "Manage tracked assets watchlist",
        "risk": "Assess portfolio risk (VaR, Sharpe, position sizing)",
        "calendar": "View upcoming financial events and earnings",
    }

    # Registry first, then the out-of-registry extras, then the curated text —
    # so a command always has *some* description and the hand-written wording
    # still wins where it exists.
    ALL_DESCRIPTIONS = {
        **_registry_descriptions(),
        **_EXTRA_DESCRIPTIONS,
        **_CURATED_DESCRIPTIONS,
    }

    def __init__(self, mode: str = "chat", help_system: Optional[HelpSystem] = None, command_registry=None):
        self.help_system = help_system
        self.mode = mode
        self._new_registry = command_registry  # Claude Code CommandRegistry
        # Load commands from config for the active mode
        self.commands = list(agent_config.get_mode_config(mode).get("commands", []))
        # Fallback if config has no commands list
        if not self.commands:
            self.commands = list(self.ALL_DESCRIPTIONS.keys())

    def set_mode(self, mode: str):
        """Update completer for a new mode."""
        self.mode = mode
        self.commands = list(agent_config.get_mode_config(mode).get("commands", []))
        if not self.commands:
            self.commands = list(self.ALL_DESCRIPTIONS.keys())

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if not text.startswith("/"):
            return

        # Don't complete if there's a space (user is typing args, not a command)
        if " " in text:
            return

        partial = text[1:].lower()

        # Try new CommandRegistry first (Claude Code fuzzy search)
        if self._new_registry:
            results = self._new_registry.fuzzy_search(partial, self.mode, limit=15)
            for cmd in results:
                yield Completion(
                    f"/{cmd.name}",
                    start_position=-(len(partial) + 1),
                    display=f"/{cmd.name}",
                    display_meta=cmd.description,
                )
            return

        # Legacy fallback
        for cmd in sorted(self.commands):
            if cmd.lower().startswith(partial):
                desc = self.ALL_DESCRIPTIONS.get(cmd, "")
                yield Completion(
                    f"/{cmd}",
                    start_position=-(len(partial) + 1),
                    display=f"/{cmd}",
                    display_meta=desc,
                )


# ──────────────────────────────────────────────────────────────────────────────
# Conversation Persistence
# ──────────────────────────────────────────────────────────────────────────────

class ConversationManager:
    """Save / load conversations to ~/.neomind/conversations/."""

    def __init__(self):
        self.base_dir = Path.home() / ".neomind" / "conversations"
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def save(self, chat: NeoMindAgent, name: Optional[str] = None) -> str:
        name = name or f"conv_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        fp = self.base_dir / f"{name}.json"
        data = {
            "timestamp": datetime.now().isoformat(),
            "model": chat.model,
            "mode": chat.mode,
            "thinking": chat.thinking_enabled,
            "history": chat.conversation_history,
        }
        fp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        return str(fp)

    def load(self, name: str) -> Optional[Dict]:
        fp = self.base_dir / f"{name}.json"
        if not fp.exists():
            # try without .json
            fp = self.base_dir / name
        if not fp.exists():
            return None
        return json.loads(fp.read_text())

    def list_all(self) -> List[str]:
        return sorted(
            [p.stem for p in self.base_dir.glob("*.json")],
            reverse=True,
        )


# ──────────────────────────────────────────────────────────────────────────────
# NeoMindInterface
# ──────────────────────────────────────────────────────────────────────────────


def _tp_open_pattern() -> str:
    from agent.coding.tool_parser import _OPEN_DELIM_RE
    return _OPEN_DELIM_RE.pattern


def _tp_close_pattern() -> str:
    from agent.coding.tool_parser import _CLOSE_DELIM_RE
    return _CLOSE_DELIM_RE.pattern


#: This family requires a real marker — the DSML word, or a fullwidth U+FF5C
#: bar — before it will suppress anything. Matching a bare `<|tool_calls|>`
#: swallowed prose that merely mentions the tag, which
#: test_pipe_like_normal_text_passes_through has asserted since before this
#: work: eating a user's sentence is worse than letting one payload through,
#: and every payload observed in the wild carried the marker.
_DSML_MARK = r'(?:\uff5c+\s*(?:DSML)?\s*\uff5c*|\|*\s*DSML\s*\|*)'


def _tp_dsml_open(tag: str) -> str:
    return rf'<\s*{_DSML_MARK}\s*{tag}\b[^>]*>'


def _tp_dsml_close(tag: str) -> str:
    return rf'<\s*/\s*{_DSML_MARK}\s*{tag}\s*>' 


class NeoMindInterface:
    """NeoMind terminal chat interface."""

    def __init__(self, chat: NeoMindAgent):
        self.chat = chat
        self.console = Console(highlight=False) if RICH_AVAILABLE else None
        self.conv_mgr = ConversationManager()
        self.help_system = HelpSystem()
        self.running = True
        self._interrupt = False
        self._auto_approved = False  # Persists "always allow" across turns

        # ── One command registry (Phase 6A task 2) ──────────────────
        # The registry is the only place that defines what commands exist.
        # The terminal's own commands are declared into it here, so
        # autocomplete, /help and the mode-availability check all read one
        # list. It is `NeoMindAgent`'s per-instance registry, so these
        # declarations are scoped to this session and never reach Telegram's.
        self._new_command_dispatcher = getattr(chat, '_command_dispatcher', None)
        self._new_command_registry = getattr(chat, '_command_registry', None)
        from cli.ui_commands import register_ui_commands

        self._ui_command_names = register_ui_commands(
            self, self._new_command_registry
        )

        # ── Phase 5: Fleet multi-agent monitor (2026-04-12) ─────────
        # In-session FleetSession wrapper; None when no fleet active.
        # Populated by /fleet start, cleared by /fleet stop. The UX is
        # entirely inline within the existing PromptSession — no full-
        # screen Application, no alt-screen takeover, no Ctrl+arrow
        # shortcuts (user directive 2026-04-12). Visual focus switching
        # happens via a two-line bottom toolbar (mode info + tag row)
        # and conditional arrow-key bindings that only activate when
        # the input buffer is empty AND a fleet is running, so the
        # default prompt_toolkit behavior (history recall, cursor
        # movement) is preserved otherwise.
        self._fleet_session: Optional[Any] = None
        # When True, arrow keys in the input field navigate the fleet
        # tag row at the bottom instead of their default behavior.
        # Toggled by pressing Up from an empty buffer, cleared by
        # pressing Enter/Escape on a tag.
        self._fleet_tag_nav_active: bool = False
        # Index into [LEADER_FOCUS, *member_names()] while in tag nav.
        self._fleet_tag_cursor: int = 0
        # Per-focus input buffer drafts: when the user switches focus
        # with half-typed text in the input, we stash it here keyed by
        # the *previous* focus target and restore whatever draft that
        # the *new* focus target had previously (or empty string).
        # Keys: LEADER_FOCUS sentinel or member name.
        self._fleet_draft_buffers: dict = {}
        # Phase 5.12 task #67: tracks which sub-agents have unread
        # completed replies (task_completed events that arrived while
        # the user was focused on a DIFFERENT target). Cleared for a
        # member when the user next switches to it. The toolbar
        # rendering uses this set to show a bright green "●" badge.
        self._fleet_unread_completion: set = set()

    # ── Welcome ───────────────────────────────────────────────────────────
    def display_welcome(self):
        model_name = self.chat.model
        mode = self.chat.mode
        think_icon = "on" if self.chat.thinking_enabled else "off"

        if self.console:
            self.console.print()
            if mode == "coding":
                cwd = os.getcwd()
                self.console.print(
                    f"[bold cyan]neomind[/bold cyan]  "
                    f"[dim]coding mode[/dim]"
                )
                self.console.print(
                    f"[dim]Model:[/dim] [green]{model_name}[/green]  "
                    f"[dim]Think:[/dim] [yellow]{think_icon}[/yellow]"
                )
                self.console.print(
                    f"[dim]Workspace:[/dim] [blue]{cwd}[/blue]"
                )
                # Show tool count from registry if available
                try:
                    registry = self._get_tool_registry()
                    tool_names = sorted([t.name for t in registry.get_all_tools()]) if registry else []
                    tool_count = len(tool_names)
                    if tool_count > 0:
                        # Show first few tools + count
                        shown = ", ".join(tool_names[:7])
                        if tool_count > 7:
                            self.console.print(
                                f"[dim]Tools ({tool_count}): {shown}, ... (+{tool_count - 7} more)[/dim]"
                            )
                        else:
                            self.console.print(
                                f"[dim]Tools ({tool_count}): {shown}[/dim]"
                            )
                    else:
                        self.console.print(
                            "[dim]Tools: Bash, Read, Write, Edit, Glob, Grep, LS[/dim]"
                        )
                except Exception:
                    self.console.print(
                        "[dim]Tools: Bash, Read, Write, Edit, Glob, Grep, LS[/dim]"
                    )
                self.console.print(
                    "[dim]  / commands  |  Ctrl+O think  |  Ctrl+E expand  |  /debug logs  |  Ctrl+D exit[/dim]"
                )
            elif mode == "fin":
                self.console.print(
                    f"[bold green]neomind[/bold green]  "
                    f"[dim]finance mode[/dim]"
                )
                self.console.print(
                    f"[dim]Model:[/dim] [green]{model_name}[/green]  "
                    f"[dim]Think:[/dim] [yellow]{think_icon}[/yellow]"
                )
                self.console.print(
                    "[dim]Sources: Finnhub, yfinance, AKShare, CoinGecko, DuckDuckGo, RSS[/dim]"
                )
                self.console.print(
                    "[dim]Tools: /stock  /crypto  /news  /compute  /digest  /chart  /risk[/dim]"
                )
                self.console.print(
                    "[dim]  / commands  |  Ctrl+O think  |  /sources trust  |  Ctrl+D exit[/dim]"
                )
            else:
                self.console.print(
                    f"[bold cyan]neomind[/bold cyan]  "
                    f"[dim]chat mode[/dim]"
                )
                self.console.print(
                    f"[dim]Model:[/dim] [green]{model_name}[/green]  "
                    f"[dim]Think:[/dim] [yellow]{think_icon}[/yellow]"
                )
                self.console.print(
                    "[dim]  / commands  |  Ctrl+O think  |  /debug logs  |  Ctrl+C cancel  |  Ctrl+D exit[/dim]"
                )
            self.console.print()
        else:
            print(f"\nneomind — {mode} mode")
            print(f"Model: {model_name}  Think: {think_icon}")
            if mode == "coding":
                print(f"Workspace: {os.getcwd()}")
                print("Tools: Bash, Read, Write, Edit, Glob, Grep, LS")
            elif mode == "fin":
                print("Sources: Finnhub, yfinance, AKShare, CoinGecko, DuckDuckGo, RSS")
                print("Tools: /stock  /crypto  /news  /compute  /digest  /chart  /risk")
            print("  / commands | Ctrl+O think | Ctrl+D exit\n")

    # ── Status bar (prompt_toolkit bottom_toolbar) ────────────────────────
    def _fleet_toolbar_line(self) -> str:
        """Return a standalone HTML line for the fleet tag row, or
        empty string when no fleet is active.

        Rendered as a second line below the main status line. Contains
        the leader slot followed by one tag per non-leader member:

            [mgr-1]  @fin-rt  @fin-rsrch  @dev-1  @dev-2

        Visual state reflects THREE orthogonal things:
          1. ``session.focus`` — which target is currently active (bold
             magenta for sub-agent, bold cyan for leader).
          2. ``self._fleet_tag_nav_active`` + ``self._fleet_tag_cursor``
             — if the user has pressed Up from an empty buffer and is
             navigating the tag row, the tag at the cursor gets a
             reverse-video highlight (like vim's visual selection).
          3. Last event kind per member — color-coded background for
             running / completed / failed states so the user can see
             at-a-glance which agents are busy.
        """
        from html import escape as _esc

        session = self._fleet_session
        if session is None:
            return ""
        from fleet.session import LEADER_FOCUS

        # Build the sequence the tag cursor navigates over.
        seq = [LEADER_FOCUS] + session.member_names()
        cursor_idx = self._fleet_tag_cursor if self._fleet_tag_nav_active else -1
        # Clamp cursor to valid range
        if cursor_idx >= len(seq):
            cursor_idx = len(seq) - 1

        leader_name = None
        for m in session.config.members:
            if m.role == "leader":
                leader_name = m.name
                break
        leader_label = leader_name or "leader"

        parts = [" "]

        # Minimal palette:
        #   - cursor (tag-nav selection): yellow background, black fg
        #   - active (currently-focused target): bold white, underlined
        #   - running (llm call in flight): dim yellow foreground only
        #   - failed: dim red foreground only
        #   - idle: dim gray
        # No background colors except the cursor itself — that's the
        # whole point of the bar, so it should be the only thing with
        # a background.
        CURSOR_OPEN = '<style bg="ansiyellow" fg="ansiblack"><b>'
        CURSOR_CLOSE = '</b></style>'

        def _fmt_leader() -> str:
            txt = f"[{_esc(leader_label)}]"
            is_cursor = (seq[0] == LEADER_FOCUS and cursor_idx == 0)
            is_active = (session.focus == LEADER_FOCUS)
            if is_cursor:
                return f"{CURSOR_OPEN} {txt} {CURSOR_CLOSE}"
            if is_active:
                return f"<b><u>{txt}</u></b>"
            return f"<ansibrightblack>{txt}</ansibrightblack>"

        unread = getattr(self, "_fleet_unread_completion", set())

        def _fmt_tag(name: str, idx: int) -> str:
            # Phase 5.12 task #67: bright-green ● badge on any worker
            # that completed a task while the user was focused
            # elsewhere. Cleared when the user switches to this tag.
            badge = (
                '<style fg="ansibrightgreen"><b>●</b></style>'
                if name in unread else ""
            )
            txt = f"@{_esc(name)}"
            is_cursor = (idx == cursor_idx)
            is_active = (session.focus == name)
            # Status-based foreground only (no backgrounds)
            fg = "ansibrightblack"
            events = session.recent_events(name, limit=1)
            if events:
                last_kind = events[-1].kind
                if last_kind == "task_failed":
                    fg = "ansired"
                elif last_kind in ("llm_call_start", "task_received"):
                    fg = "ansiyellow"
                # task_completed/llm_call_end → revert to neutral gray
                # so the bar doesn't stay green forever.
            if is_cursor:
                return f"{CURSOR_OPEN} {txt} {CURSOR_CLOSE}{badge}"
            if is_active:
                return f"<b><u>{txt}</u></b>{badge}"
            return f"<{fg}>{txt}</{fg}>{badge}"

        parts.append(_fmt_leader())
        for i, name in enumerate(session.member_names(), start=1):
            parts.append("  ")
            parts.append(_fmt_tag(name, i))

        # Contextual hint tail
        if self._fleet_tag_nav_active:
            parts.append(
                "   <ansibrightblack>"
                "← → move   Enter select   Esc cancel"
                "</ansibrightblack>"
            )
        else:
            parts.append(
                "   <ansibrightblack>"
                "↓ to navigate tags"
                "</ansibrightblack>"
            )
        return "".join(parts)

    def _bottom_toolbar(self):
        model = self.chat.model
        mode = self.chat.mode
        think = "on" if self.chat.thinking_enabled else "off"
        tokens = 0
        # Default ctx ceiling derived from currently-active model's MODEL_SPECS
        # so the toolbar % stays meaningful when the user `/model`-switches.
        from agent.constants.models import get_active_max_context
        max_ctx = get_active_max_context()
        msg_count = len(self.chat.conversation_history)
        if hasattr(self.chat, "context_manager") and self.chat.context_manager:
            try:
                tokens = self.chat.context_manager.count_conversation_tokens()
            except Exception:
                pass
            try:
                # Use model-specific context limit instead of static config
                spec = self.chat._get_model_spec(self.chat.model)
                max_ctx = spec["max_context"]
            except Exception:
                max_ctx = agent_config.max_context_tokens or get_active_max_context()
        pct = (tokens / max_ctx * 100) if max_ctx > 0 else 0
        if pct >= 80:
            pct_color = "ansired"
        elif pct >= 50:
            pct_color = "ansiyellow"
        else:
            pct_color = "ansigreen"
        max_label = f"{max_ctx // 1000}k"

        fleet_line = self._fleet_toolbar_line()
        # Two-row bottom toolbar: main status on line 1, fleet tags on
        # line 2 (only when fleet is running). One row when no fleet.
        fleet_suffix = f"\n{fleet_line}" if fleet_line else ""

        if mode == "coding":
            # Coding mode: show permission mode + cwd
            perm = agent_config.permission_mode
            cwd = os.path.basename(os.getcwd()) or "~"
            return HTML(
                f" <b>{model}</b> | coding | {perm} | think:{think} "
                f"| <{pct_color}>{pct:.0f}% {tokens:,}/{max_label}</{pct_color}> {msg_count}msg "
                f"| {cwd}"
                f"  <i>Ctrl+O</i> think  <i>/</i> cmds  <i>Ctrl+D</i> exit"
                f"{fleet_suffix}"
            )
        elif mode == "fin":
            # Finance mode: show source count + encrypted memory status
            return HTML(
                f" <b>{model}</b> | <ansigreen>fin</ansigreen> | think:{think} "
                f"| <{pct_color}>{pct:.0f}% {tokens:,}/{max_label}</{pct_color}> {msg_count}msg"
                f"  <i>Ctrl+O</i> think  <i>/</i> cmds  <i>Ctrl+D</i> exit"
                f"{fleet_suffix}"
            )
        else:
            # Chat mode: simpler bar
            return HTML(
                f" <b>{model}</b> | chat | think:{think} "
                f"| <{pct_color}>{pct:.0f}% {tokens:,}/{max_label}</{pct_color}> {msg_count}msg"
                f"  <i>Ctrl+O</i> think  <i>/</i> cmds  <i>Ctrl+D</i> exit"
                f"{fleet_suffix}"
            )

    # ── Fleet multi-agent monitor (Phase 5) ───────────────────────────────

    # Background asyncio loop for fleet operations. Lazy-created on first
    # /fleet start and kept alive until the interpreter exits (daemon
    # thread). This is load-bearing for Phase 5: a synchronous REPL can't
    # pump a long-lived asyncio fleet via the `get_event_loop().run_until_
    # complete()` pattern — that pattern only drives the loop during the
    # brief window of each call, so fleet workers would freeze between
    # user inputs AND cross-call task references would fail with
    # "future belongs to a different loop" errors (caught by Phase 5.10
    # iTerm2 live smoke 2026-04-12). Using a dedicated thread + persistent
    # loop fixes both problems in one move.
    _fleet_bg_loop = None  # type: ignore
    _fleet_bg_thread = None  # type: ignore

    def _fleet_async_run(self, coro):
        """Run an async coroutine on the dedicated background loop.

        Submits the coroutine via asyncio.run_coroutine_threadsafe and
        blocks the CLI thread until it completes (or raises). Short
        operations (start, stop, submit, status) complete in
        milliseconds. Long operations should not be run through this
        helper — the fleet's own background workers run on the same
        loop and make progress independently of the CLI thread.
        """
        import asyncio
        import threading
        import time

        # Lazy-create the background loop + thread on first call
        cls = type(self)
        if cls._fleet_bg_loop is None:
            loop_ready = threading.Event()

            def _run_loop():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                cls._fleet_bg_loop = loop
                loop_ready.set()
                try:
                    loop.run_forever()
                finally:
                    # Cancel any remaining tasks on teardown
                    try:
                        pending = asyncio.all_tasks(loop)
                        for t in pending:
                            t.cancel()
                        if pending:
                            loop.run_until_complete(
                                asyncio.gather(*pending, return_exceptions=True)
                            )
                    except Exception:
                        pass
                    loop.close()

            cls._fleet_bg_thread = threading.Thread(
                target=_run_loop, name="neomind-fleet-loop", daemon=True,
            )
            cls._fleet_bg_thread.start()
            loop_ready.wait(timeout=5.0)
            if cls._fleet_bg_loop is None:
                raise RuntimeError("fleet background loop failed to start")

        # Submit the coroutine to the background loop and wait for it
        future = asyncio.run_coroutine_threadsafe(coro, cls._fleet_bg_loop)
        return future.result()

    def _print_fleet_focus_banner(self) -> None:
        """Print a focus-change banner plus the last N turns of the
        newly-focused target into the terminal scrollback.

        Called from the main loop after a tag-navigation Enter selects
        a new focus target. The goal is to give the user a quick
        "here's where you are, here's what's been said" view without
        taking over the screen — the banner lands in normal terminal
        scrollback so the user can scroll up to see it later.
        """
        session = self._fleet_session
        if session is None:
            return
        from fleet.session import LEADER_FOCUS

        # Clear the terminal (screen + scrollback) so the user only
        # sees the focused agent's conversation, not the accumulated
        # transcripts of every other agent they visited.
        # \x1b[2J  — clear visible screen
        # \x1b[3J  — clear scrollback buffer (xterm + iTerm2)
        # \x1b[H   — home cursor
        import sys as _sys
        _sys.stdout.write("\x1b[2J\x1b[3J\x1b[H")
        _sys.stdout.flush()

        if session.is_focused_on_leader():
            self._print(
                f"[bold cyan]── ↩ leader[/bold cyan] "
                f"[dim](main {self.chat.mode} session, project={session.project_id})[/dim]"
            )
            history = getattr(self.chat, "conversation_history", None) or []
            visible = [
                h for h in history
                if isinstance(h, dict) and h.get("role") in ("user", "assistant")
            ][-8:]
            if not visible:
                self._print(
                    "[dim]  (no conversation yet — type below to talk to "
                    "the main persona, or [bold]@agent-name[/bold] to "
                    "dispatch a sub-agent)[/dim]"
                )
            else:
                for h in visible:
                    role = h.get("role")
                    body = str(h.get("content") or "")[:400]
                    if role == "user":
                        self._print(f"[white bold]  you:[/white bold] {body}")
                    else:
                        self._print(f"[cyan bold]  leader:[/cyan bold] {body}")
            self._print(
                "[dim]  ─── type below to talk to the main persona, "
                "[bold]↓[/bold] to navigate tags[/dim]"
            )
            return

        name = session.focused_member_name()
        member = session.get_member(name) if name else None
        if not member:
            return

        transcript = session.get_transcript(name)
        self._print(
            f"[bold magenta]── ➜ @{name}[/bold magenta] "
            f"[dim]({member.persona} · {member.role}, "
            f"project={session.project_id})[/dim]"
        )

        if transcript is None or transcript.turn_count() == 0:
            self._print(
                "[dim]  (no conversation yet — type a message below to "
                "send this agent its first task)[/dim]"
            )
        else:
            recent = transcript.turns[-8:]
            for turn in recent:
                if turn.role == "user":
                    label = "[white bold]  you:[/white bold]"
                elif turn.role == "assistant":
                    label = f"[green bold]  @{name}:[/green bold]"
                elif turn.role == "system":
                    label = "[dim italic]  [sys][/dim italic]"
                elif turn.role == "meta":
                    continue  # skip internal meta turns
                else:
                    label = f"[dim]  [{turn.role}][/dim]"
                body = turn.content[:400]
                if turn.role in ("user", "assistant"):
                    self._print(f"{label} {body}")
                else:
                    self._print(f"{label} [dim]{body}[/dim]")
        self._print(
            "[dim]  ─── type below to send a new task to this agent, "
            "[bold]↓[/bold] to navigate tags again[/dim]"
        )

    def _wait_and_print_agent_reply(
        self, member_name: str, task_id: str, timeout: float = 120.0,
    ) -> None:
        """Spawn a background daemon thread that polls the member's
        transcript for new assistant / thinking turns tied to
        ``task_id`` and prints them above the active prompt via
        ``patch_stdout``. Returns immediately so the user can keep
        navigating / typing / switching focus while the sub-agent
        thinks. Multiple agents can stream concurrently — their
        replies will interleave above the prompt as they arrive."""
        import threading
        import time as _time

        session = self._fleet_session
        if session is None:
            return
        transcript = session.get_transcript(member_name)
        if transcript is None:
            return
        baseline = transcript.turn_count()

        # Only show the "thinking" hint if the user is currently
        # focused on THIS agent. If they dispatched and then switched
        # away, the hint would leak into the other agent's view.
        if session.focus == member_name:
            self._print(
                f"[dim]  ⠋ @{member_name} thinking…[/dim]"
            )

        def _worker():
            nonlocal baseline
            deadline = _time.monotonic() + timeout
            while _time.monotonic() < deadline:
                _time.sleep(0.4)
                try:
                    count = transcript.turn_count()
                    if count > baseline:
                        new = transcript.turns[baseline:count]
                        # Only stream live if the user is STILL focused
                        # on this agent. Otherwise the turns remain in
                        # the transcript and will be replayed when the
                        # user navigates back to this agent.
                        currently_focused = (
                            self._fleet_session is not None
                            and self._fleet_session.focus == member_name
                        )
                        if currently_focused:
                            for turn in new:
                                if turn.role == "assistant":
                                    self._print(
                                        f"[green bold]  @{member_name}:"
                                        f"[/green bold] {turn.content}"
                                    )
                                elif turn.role == "thinking":
                                    self._print(
                                        f"[dim italic]  @{member_name} "
                                        f"(think): {turn.content[:400]}"
                                        f"[/dim italic]"
                                    )
                        baseline = count
                        evs = session.recent_events(member_name, limit=8)
                        if any(
                            e.metadata.get("task_id") == task_id
                            and e.kind in ("task_completed", "task_failed")
                            for e in evs
                        ):
                            # Task done. If the user wasn't watching
                            # when the reply streamed in, mark this
                            # agent as having an unread completion so
                            # the toolbar shows a ● badge.
                            if not currently_focused:
                                self._fleet_unread_completion.add(
                                    member_name
                                )
                            return
                except Exception:
                    return

        t = threading.Thread(target=_worker, daemon=True)
        t.start()

    @staticmethod
    def _fleet_event_color(kind: str) -> str:
        return {
            "spawned": "dim",
            "task_received": "cyan",
            "llm_call_start": "yellow",
            "llm_call_end": "green",
            "task_completed": "bold green",
            "task_failed": "bold red",
            "system": "dim",
        }.get(kind, "white")

    def _handle_fleet_command(self, args: str) -> bool:
        """Handle /fleet subcommands. Always returns True — fleet
        commands are local-handled, never delegated to the LLM.

        Subcommands:
          /fleet                      — show subcommand list
          /fleet start <project_id>   — load projects/<id>/project.yaml
                                        and spawn FleetSession
          /fleet status               — show team snapshot
          /fleet list                 — list members (same as status -v)
          /fleet submit <task>        — submit to shared queue
          /fleet submit --to <name> <task>
          /fleet submit --persona <p> <task>
          /fleet focus <name>|leader  — set focus without arrow keys
          /fleet stop                 — graceful shutdown
        """
        parts = args.split(maxsplit=1) if args else []
        sub = parts[0].lower() if parts else ""
        sub_args = parts[1].strip() if len(parts) > 1 else ""

        if not sub or sub == "help":
            self._print_fleet_help()
            return True

        if sub == "start":
            self._fleet_cmd_start(sub_args)
            return True
        if sub == "stop":
            self._fleet_cmd_stop()
            return True
        if sub == "status":
            self._fleet_cmd_status()
            return True
        if sub == "list":
            self._fleet_cmd_list()
            return True
        if sub == "submit":
            self._fleet_cmd_submit(sub_args)
            return True
        if sub == "focus":
            self._fleet_cmd_focus(sub_args)
            return True

        self._print(f"[yellow]Unknown /fleet subcommand:[/yellow] {sub}")
        self._print_fleet_help()
        return True

    def _print_fleet_help(self) -> None:
        self._print("[bold]Fleet commands[/bold]")
        self._print("  [cyan]/fleet start <project_id>[/cyan]  — spawn a fleet from projects/<id>/project.yaml")
        self._print("  [cyan]/fleet submit <task>[/cyan]       — submit task to any idle worker")
        self._print("  [cyan]/fleet submit --to <name> <task>[/cyan]    — target a specific member")
        self._print("  [cyan]/fleet submit --persona <p> <task>[/cyan]  — target any idle member of a persona")
        self._print("  [cyan]/fleet focus <name>|leader[/cyan]  — set focus (alternative to Ctrl+→/←)")
        self._print("  [cyan]/fleet status[/cyan]               — team snapshot + task counts")
        self._print("  [cyan]/fleet list[/cyan]                 — list members")
        self._print("  [cyan]/fleet stop[/cyan]                 — graceful shutdown")
        self._print("")
        self._print("[dim]Once a fleet is running:[/dim]")
        self._print("[dim]  • The bottom toolbar shows a second line with agent tags[/dim]")
        self._print("[dim]  • Press [bold]Down[/bold] from an empty input to move the cursor onto the tag row[/dim]")
        self._print("[dim]  • [bold]← →[/bold] move between tags, [bold]Enter[/bold] selects (enters that agent), [bold]Esc[/bold] cancels[/dim]")
        self._print("[dim]  • While an agent is focused, typing + Enter dispatches the message as a task[/dim]")
        self._print("[dim]  • In leader view, prefix input with [bold]@agent-name[/bold] to dispatch inline[/dim]")

    def _fleet_cmd_start(self, project_id: str) -> None:
        """Start a fleet in the background and stay in the current CLI.

        The fleet runs inline via the existing PromptSession — no
        full-screen takeover, no alt-screen, no Ctrl+arrow shortcuts.
        After start, the bottom toolbar shows tags for every sub-agent
        and the user can navigate them with plain arrow keys (Up from
        an empty buffer enters tag-nav, Left/Right/Enter select).
        """
        if not project_id:
            self._print("[yellow]Usage:[/yellow] /fleet start <project_id>")
            return
        if self._fleet_session is not None:
            self._print(
                f"[yellow]Fleet already running:[/yellow] "
                f"{self._fleet_session.project_id}"
            )
            self._print("[dim]Use /fleet stop first[/dim]")
            return

        project_id = project_id.strip()
        from pathlib import Path
        yaml_path = Path(__file__).resolve().parent.parent / "projects" / project_id / "project.yaml"
        if not yaml_path.exists():
            self._print(f"[red]Project yaml not found:[/red] {yaml_path}")
            return

        try:
            from fleet.project_schema import load_project_config
            from fleet.session import FleetSession
            config = load_project_config(str(yaml_path))
            session = FleetSession(config)
            self._fleet_async_run(session.start())
        except Exception as exc:
            self._print(f"[red]Failed to start fleet:[/red] {exc}")
            return

        self._fleet_session = session
        self._fleet_tag_nav_active = False
        self._fleet_tag_cursor = 0
        non_leader = session.member_names()
        self._print(
            f"[green]✓[/green] Fleet [bold]{session.project_id}[/bold] started "
            f"with {len(non_leader)} worker(s): "
            + " ".join(f"[magenta]@{n}[/magenta]" for n in non_leader)
        )
        self._print(
            "[dim]Press [bold]Down[/bold] from an empty input to navigate agent tags; "
            "[bold]← →[/bold] move, [bold]Enter[/bold] to select, [bold]Esc[/bold] to cancel. "
            "While an agent is focused, typing sends a task to it. "
            "Prefix with [bold]@agent[/bold] to dispatch inline from the leader view. "
            "[bold]/fleet stop[/bold] to tear down.[/dim]"
        )

    def _fleet_cmd_stop(self) -> None:
        if self._fleet_session is None:
            self._print("[yellow]No fleet running[/yellow]")
            return
        try:
            self._fleet_async_run(self._fleet_session.stop())
        except Exception as exc:
            self._print(f"[red]Error during fleet stop:[/red] {exc}")
        self._fleet_session = None
        self._print("[green]✓[/green] Fleet stopped")

    def _fleet_cmd_status(self) -> None:
        if self._fleet_session is None:
            self._print("[yellow]No fleet running[/yellow]")
            return
        snap = self._fleet_session.status_snapshot()
        self._print(f"[bold]Fleet[/bold]: {snap['project_id']}  "
                    f"[dim]uptime: {snap['uptime_s']:.0f}s[/dim]")
        self._print(f"[bold]Focus[/bold]: {snap['focus']}")
        if "supervisor" in snap:
            sup = snap["supervisor"]
            tasks = sup.get("tasks", {})
            self._print(
                f"[bold]Tasks[/bold]: available={tasks.get('available', 0)}  "
                f"claimed={tasks.get('claimed', 0)}  "
                f"completed={tasks.get('completed', 0)}  "
                f"failed={tasks.get('failed', 0)}"
            )
        self._print("[bold]Members[/bold]:")
        for m in snap["members"]:
            self._print(
                f"  [magenta]@{m['name']}[/magenta] "
                f"[dim]({m['persona']}, {m['role']}, {m['events']} events)[/dim]"
            )

    def _fleet_cmd_list(self) -> None:
        if self._fleet_session is None:
            self._print("[yellow]No fleet running[/yellow]")
            return
        for m in self._fleet_session.config.members:
            marker = "[bold cyan](leader)[/bold cyan]" if m.role == "leader" else ""
            self._print(f"  [magenta]@{m.name}[/magenta] [dim]{m.persona}[/dim] {marker}")

    def _fleet_cmd_submit(self, args: str) -> None:
        if self._fleet_session is None:
            self._print("[yellow]No fleet running[/yellow] — /fleet start first")
            return
        if not args:
            self._print("[yellow]Usage:[/yellow] /fleet submit <task> | --to <name> <task> | --persona <p> <task>")
            return

        target_member: Optional[str] = None
        target_persona: Optional[str] = None
        task_desc: str = args

        # Parse --to / --persona flags (simple left-to-right)
        tokens = args.split(maxsplit=2)
        if tokens and tokens[0] == "--to" and len(tokens) >= 3:
            target_member = tokens[1]
            task_desc = tokens[2]
        elif tokens and tokens[0] == "--persona" and len(tokens) >= 3:
            target_persona = tokens[1]
            task_desc = tokens[2]

        try:
            if target_member:
                task_id = self._fleet_async_run(
                    self._fleet_session.submit_to_member(target_member, task_desc)
                )
                self._print(
                    f"[green]✓[/green] Dispatched task [dim]{task_id}[/dim] "
                    f"to [magenta]@{target_member}[/magenta]"
                )
            elif target_persona:
                task_id = self._fleet_async_run(
                    self._fleet_session.submit_to_persona(target_persona, task_desc)
                )
                self._print(
                    f"[green]✓[/green] Dispatched task [dim]{task_id}[/dim] "
                    f"to persona [cyan]{target_persona}[/cyan]"
                )
            else:
                task_id = self._fleet_async_run(
                    self._fleet_session.submit_to_queue(task_desc)
                )
                self._print(
                    f"[green]✓[/green] Enqueued task [dim]{task_id}[/dim] "
                    f"for any idle worker"
                )
        except Exception as exc:
            self._print(f"[red]Dispatch failed:[/red] {exc}")

    def _compute_prompt_str(self) -> str:
        """Compute the prompt string.

        When a fleet is running AND focus is on a sub-agent, the
        prompt reflects that so the user knows where their typed
        input will be routed (e.g. ``[@fin-rt fin] > ``). Otherwise
        the prompt reflects the main chat/coding/fin mode as before.
        """
        if (
            self._fleet_session is not None
            and not self._fleet_session.is_focused_on_leader()
        ):
            name = self._fleet_session.focused_member_name()
            member = self._fleet_session.get_member(name) if name else None
            persona = member.persona if member else ""
            return f"[@{name} {persona}] > "
        if self.chat.mode == "coding":
            return "> "
        if self.chat.mode == "fin":
            return "[fin] > "
        return f"[{self.chat.mode}] > "

    def _fleet_cmd_focus(self, target: str) -> None:
        """Set the focused member on the FleetSession state.

        In PromptSession mode this is just a state setter — the visual
        focused view lives in the fleet_app.FleetApplication mode
        (entered via /fleet start). Calling /fleet focus here preps
        the state so when the user next enters the multi-agent view
        it starts on the chosen target.
        """
        if self._fleet_session is None:
            self._print("[yellow]No fleet running[/yellow]")
            return
        from fleet.session import LEADER_FOCUS
        target = target.strip()
        if not target or target == "leader" or target == "main":
            if self._fleet_session.set_focus(LEADER_FOCUS):
                self._print(
                    "[green]✓[/green] Focus set to leader (main session)"
                )
            return
        if self._fleet_session.set_focus(target):
            self._print(
                f"[green]✓[/green] Focus set to [magenta]@{target}[/magenta] "
                f"[dim](enter multi-agent view with /fleet show to see it)[/dim]"
            )
        else:
            self._print(
                f"[yellow]Cannot focus on[/yellow] {target!r} "
                f"[dim](unknown member or already focused)[/dim]"
            )

    # ── Command handling ──────────────────────────────────────────────────
    #: Commands that work in every mode regardless of the personality's list.
    #: `fleet` is here because a multi-agent monitor is not a property of the
    #: personality you happen to be in.
    _MODE_AGNOSTIC_COMMANDS = frozenset({
        "quit", "exit", "help", "mode", "config", "skills", "careful",
        "freeze", "unfreeze", "guard", "sprint", "evidence", "fleet",
    })

    def _mode_gate_message(self, user_input: str) -> Optional[str]:
        """Why this command is unavailable here, or None if it is available."""
        if not user_input.lstrip().startswith("/"):
            return None
        cmd = user_input.lstrip().split(maxsplit=1)[0][1:].lower()
        if not cmd or cmd in self._MODE_AGNOSTIC_COMMANDS:
            return None
        allowed = agent_config.available_commands
        if not allowed or cmd in allowed:
            return None
        # Declared by the frontend or the registry → available regardless of
        # the personality's command list, which predates both.
        registry = getattr(self, "_new_command_registry", None)
        if registry is not None and registry.find(cmd) is not None:
            return None

        hint = {
            "chat": "[dim]Hint: start with --mode coding for file and code operations[/dim]",
            "fin": "[dim]Hint: use /stock, /crypto, /news, /compute for finance tools[/dim]",
        }.get(self.chat.mode, "")
        message = (
            f"[yellow]/{cmd}[/yellow] is not available in "
            f"[bold]{self.chat.mode}[/bold] mode"
        )
        return f"{message}\n{hint}" if hint else message

    def _command_dispatch_failed(self, user_input: str, exc: Exception) -> Optional[bool]:
        """A dispatcher that raised is a fault to report, not a verdict.

        This used to set `result = None`, which means "not a command" — so a
        crash inside `/permissions` handed the literal text `/permissions` to
        the model as though the user had typed prose. The user saw a chat
        reply about permissions and no indication anything had failed. Prose
        is still passed through, because a bare `/` in a sentence should not
        become an error.
        """
        if not user_input.lstrip().startswith("/"):
            return None
        self._print(f"[red]Command failed:[/red] {exc}")
        return True

    def _handle_local_command(self, user_input: str) -> Optional[bool]:
        """Handle commands that this interface owns. Returns:
        - False  → quit
        - True   → command handled, continue loop
        - None   → not a local command, pass to agent core

        Phase 1: Tries the new Claude Code-style CommandDispatcher first.
        Falls through to legacy handler if the new system doesn't handle it.
        """
        from agent.cli_command_system import ExitRequested, ModeSwitchRequested

        # Mode gating, which used to live in the removed legacy chain. Without
        # it a personality command typed in the wrong mode falls through to the
        # model as prose, and the user gets a chat reply about `/run` instead
        # of being told it is a coding-mode command.
        gated = self._mode_gate_message(user_input)
        if gated:
            self._print(gated)
            return True

        # ── Try new command system first (Claude Code pattern) ──────
        if self._new_command_dispatcher:
            try:
                import asyncio
                result = asyncio.get_event_loop().run_until_complete(
                    self._new_command_dispatcher.dispatch(
                        user_input,
                        mode=self.chat.mode,
                        agent=self.chat,
                    )
                )
            except RuntimeError:
                # No event loop running — create one
                try:
                    result = asyncio.run(
                        self._new_command_dispatcher.dispatch(
                            user_input,
                            mode=self.chat.mode,
                            agent=self.chat,
                        )
                    )
                except Exception as exc:
                    return self._command_dispatch_failed(user_input, exc)
            except Exception as exc:
                return self._command_dispatch_failed(user_input, exc)

            if result is not None:
                # Fall through to legacy handler for "Unknown command" —
                # these may be personality-specific commands (e.g. /code,
                # /test, /run, /grep, /find) registered on core.command_handlers.
                if result.display == "system" and "Unknown command" in result.text:
                    result = None  # Let legacy handler try

            if result is not None:
                # Control signals arrive as typed effects rather than sentinel
                # values inside `text` — a command whose ordinary output
                # happened to read "__EXIT__" used to quit the application,
                # and a second frontend had to know every sentinel's spelling.
                if result.effect(ExitRequested):
                    self._print("[dim]Goodbye![/dim]")
                    return False
                mode_switch = result.effect(ModeSwitchRequested)
                if mode_switch:
                    target = mode_switch.target
                    ok = self.chat.switch_mode(target)
                    if ok and hasattr(self, '_completer') and self._completer:
                        self._completer.set_mode(target)
                        self.display_welcome()
                    return True
                if result.compact:
                    # Extract key user facts before clearing history
                    facts_summary = self._extract_user_facts(self.chat.conversation_history)
                    self.chat.clear_history()
                    if agent_config.system_prompt:
                        self.chat.add_to_history("system", agent_config.system_prompt)
                    # Re-inject preserved facts so the agent remembers the user
                    if facts_summary:
                        self.chat.add_to_history("system",
                            f"# Preserved context from previous conversation\n\n{facts_summary}")
                    # Use the command's own message if provided
                    msg = result.text if result.text else "Conversation compacted"
                    self._print(f"[green]✓[/green] {msg}")
                    return True
                if result.should_query:
                    # Prompt command: feed expanded text to LLM
                    self._stream_and_render(result.text)
                    return True
                if result.display != "skip" and result.text:
                    self._print(result.text)
                return True

        # One registry defines the commands. There is no second chain.
        #
        # There used to be: 21 `if cmd == ...` branches here, of which 14 were
        # already shadowed — the dispatcher above answers and returns, so those
        # bodies could not run, while still looking like the place to edit
        # `/clear`. They were only reachable when the registry failed to build,
        # and silently serving a *different* implementation of a command is
        # worse than saying the registry is broken. The remaining seven are
        # genuinely frontend-owned and are now declared in the same registry by
        # `cli/ui_commands.py`.
        if self._new_command_dispatcher is None:
            self._print(
                "[red]Command registry unavailable[/red] — slash commands are "
                "disabled for this session. Start with [bold]/debug[/bold] logs "
                "to see why it failed to build."
            )
            return True

        # Not a local command
        return None

    # ── Frontend-owned commands ──────────────────────────────────────────
    #
    # Declared in the one registry by `cli/ui_commands.py` and executed here.
    # They draw, they read interface state, and they mean nothing to a chat
    # surface — but "what commands exist" still has to have a single answer,
    # or autocomplete, /help and the mode-availability check each learn a
    # different list.

    def _ui_cmd_freeze(self, args: str) -> None:
        from agent.workflow.guards import get_guard
        guard = get_guard()
        directory = args or os.getcwd()
        guard.enable_freeze(directory)
        self._print(f"[cyan]🧊[/cyan] Freeze: edits restricted to [bold]{directory}[/bold]")

    def _ui_cmd_unfreeze(self, args: str) -> None:
        from agent.workflow.guards import get_guard
        get_guard().disable_freeze()
        self._print("[green]✓[/green] Freeze removed — edits unrestricted")

    def _ui_cmd_guard(self, args: str) -> None:
        from agent.workflow.guards import get_guard
        guard = get_guard()
        directory = args or os.getcwd()
        guard.enable_guard(directory)
        self._print(f"[green]✓[/green] Guard mode: careful + freeze to [bold]{directory}[/bold]")

    def _ui_cmd_sprint(self, args: str) -> None:
        from agent.workflow.sprint import SprintManager
        mgr = SprintManager()
        if args.startswith("new "):
            goal = args[4:].strip()
            sprint = mgr.create(goal, mode=self.chat.mode)
            self._print(f"[green]✓[/green] Sprint created: {sprint.id}")
            self._print(mgr.format_status(sprint.id))
        elif args == "status":
            for sid, s in mgr._active_sprints.items():
                self._print(mgr.format_status(sid))
        elif args == "next":
            for sid in list(mgr._active_sprints.keys()):
                phase = mgr.advance(sid)
                if phase:
                    self._print(f"[green]▶️[/green] Now: {phase.name}")
                else:
                    self._print("[green]✓[/green] Sprint completed!")
                break
        elif args == "skip":
            for sid in list(mgr._active_sprints.keys()):
                phase = mgr.skip_phase(sid)
                if phase:
                    self._print(f"[yellow]⏭️[/yellow] Skipped → {phase.name}")
                break
        else:
            self._print("Usage: /sprint new <goal> | /sprint status | /sprint next | /sprint skip")

    def _ui_cmd_evidence(self, args: str) -> None:
        from agent.workflow.evidence import get_evidence_trail
        trail = get_evidence_trail()
        if args == "stats":
            stats = trail.get_stats()
            self._print(f"Evidence: {stats.get('total', 0)} entries, {stats.get('log_size_kb', 0)} KB")
        else:
            self._print(trail.format_recent(10))

    # ── Fact extraction for /compact ──────────────────────────────────────
    @staticmethod
    def _extract_user_facts(history: list) -> str:
        """Extract key user facts from conversation history before compaction.

        Scans user and assistant messages for identity signals (name, location,
        preferences, project context) so they survive /compact.

        Returns a short bullet-point summary, or empty string if nothing found.
        """
        import re as _re

        facts = []
        # Patterns that typically carry user identity/facts
        _NAME_PATTERNS = [
            _re.compile(r"(?:my name is|i'm|i am|call me)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)", _re.I),
        ]
        _FACT_PATTERNS = [
            _re.compile(r"(?:i (?:work|am working) (?:on|at|in|with))\s+(.{5,80})", _re.I),
            _re.compile(r"(?:i (?:prefer|like|use|need))\s+(.{5,80})", _re.I),
            _re.compile(r"(?:i live in|i'm from|i'm based in)\s+(.{3,60})", _re.I),
            _re.compile(r"(?:my (?:project|repo|codebase|app|company) is)\s+(.{3,80})", _re.I),
        ]

        seen = set()
        for msg in history:
            role = msg.get("role", "")
            content = str(msg.get("content", ""))
            if role == "user":
                for pat in _NAME_PATTERNS:
                    m = pat.search(content)
                    if m:
                        name = m.group(1).strip()
                        key = f"name:{name.lower()}"
                        if key not in seen:
                            facts.append(f"- User's name: {name}")
                            seen.add(key)
                for pat in _FACT_PATTERNS:
                    m = pat.search(content)
                    if m:
                        fact = m.group(0).strip().rstrip(".,;")
                        key = fact.lower()[:40]
                        if key not in seen:
                            facts.append(f"- User said: \"{fact}\"")
                            seen.add(key)
            elif role == "assistant":
                # Capture when the assistant confirms user identity
                for pat in [_re.compile(r"(?:your name is|you(?:'re| are)|Hi,?)\s+([A-Z][a-z]+)", _re.I)]:
                    m = pat.search(content[:500])
                    if m:
                        name = m.group(1).strip()
                        key = f"name:{name.lower()}"
                        if key not in seen:
                            facts.append(f"- User's name: {name}")
                            seen.add(key)

        return "\n".join(facts[:10])  # Cap at 10 facts

    # ── Transcript viewer ───────────────────────────────────────────────
    def _show_transcript(self, args: str = ""):
        """Show full conversation transcript.

        Usage:
            /transcript        — show all messages (truncated to last 20)
            /transcript full   — show all messages untruncated
            /transcript N      — show last N messages
            /transcript last   — show the last assistant response in full
        """
        history = self.chat.conversation_history
        if not history:
            self._print("[dim]No conversation history yet.[/dim]")
            return

        args = args.strip().lower()

        if args == "last":
            # Show the last assistant response in full
            for msg in reversed(history):
                if msg["role"] == "assistant":
                    self._print(f"\n[bold green]Assistant:[/bold green]")
                    if self.console and RICH_AVAILABLE:
                        self.console.print(Markdown(msg["content"]))
                    else:
                        print(msg["content"])
                    return
            self._print("[dim]No assistant responses yet.[/dim]")
            return

        if args == "full":
            limit = len(history)
        elif args.isdigit():
            limit = int(args)
        else:
            limit = 20  # default: last 20

        msgs = history[-limit:] if limit < len(history) else history
        skipped = len(history) - len(msgs)

        if skipped > 0:
            self._print(f"[dim]({skipped} earlier messages omitted — use /transcript full to see all)[/dim]\n")

        for i, msg in enumerate(msgs):
            role = msg["role"]
            content = msg["content"]

            if role == "system":
                self._print(f"[dim]━━━ System ━━━[/dim]")
                preview = content[:200] + ("…" if len(content) > 200 else "")
                self._print(f"[dim]{preview}[/dim]")
            elif role == "user":
                self._print(f"\n[bold blue]You:[/bold blue]")
                # Show full user message (usually short)
                if len(content) > 500:
                    self._print(content[:500] + "…")
                else:
                    self._print(content)
            elif role == "assistant":
                self._print(f"\n[bold green]Assistant:[/bold green]")
                if args == "full" or len(content) <= 1000:
                    if self.console and RICH_AVAILABLE:
                        self.console.print(Markdown(content))
                    else:
                        print(content)
                else:
                    # Truncate long responses in default view
                    self._print(content[:500])
                    self._print(f"[dim]… ({len(content)} chars total — use /transcript last to see full)[/dim]")

            if i < len(msgs) - 1:
                self._print("[dim]─[/dim]")

        self._print(f"\n[dim]({len(history)} total messages)[/dim]")

    # ── Turn expansion viewer (Ctrl+E or /expand) ────────────────────────
    def _show_expand(self, args: str = ""):
        """Show full thinking content for a turn, opened in a pager.

        Usage:
            /expand        — list turns with thinking, pick one to expand
            /expand N      — expand turn N directly
            /expand last   — expand the most recent thinking turn
            /expand all    — expand all turns with thinking
        """
        thinking_history = getattr(self.chat, '_thinking_history', [])
        if not thinking_history:
            self._print("[dim]No thinking turns recorded yet.[/dim]")
            return

        args = args.strip().lower()

        if args == "last":
            self._expand_turn_in_pager(thinking_history[-1])
            return

        if args == "all":
            full_text = ""
            for i, turn in enumerate(thinking_history):
                full_text += f"{'='*60}\n"
                full_text += f"Turn {i+1} — Thought for {turn['duration']:.1f}s\n"
                full_text += f"{'='*60}\n\n"
                full_text += f"THINKING:\n{turn['thinking']}\n\n"
                if turn.get('response_preview'):
                    full_text += f"RESPONSE (preview):\n{turn['response_preview']}…\n\n"
            self._open_in_pager(full_text)
            return

        if args.isdigit():
            idx = int(args) - 1
            if 0 <= idx < len(thinking_history):
                self._expand_turn_in_pager(thinking_history[idx])
            else:
                self._print(f"[red]Turn {args} not found. Valid: 1-{len(thinking_history)}[/red]")
            return

        # Default: list turns and prompt for selection
        self._print(f"[bold]Thinking turns ({len(thinking_history)} total):[/bold]")
        for i, turn in enumerate(thinking_history):
            duration = turn.get('duration', 0)
            preview = turn.get('response_preview', '')[:60]
            self._print(f"  [cyan]{i+1}.[/cyan] Thought {duration:.1f}s — {preview}…")

        self._print(f"\n[dim]Usage: /expand N, /expand last, /expand all[/dim]")

        # Prompt for selection
        try:
            choice = input("  Expand turn #: ").strip()
            if choice.isdigit():
                idx = int(choice) - 1
                if 0 <= idx < len(thinking_history):
                    self._expand_turn_in_pager(thinking_history[idx])
                else:
                    self._print("[dim]Invalid turn number[/dim]")
            elif choice.lower() == "all":
                self._show_expand("all")
        except (EOFError, KeyboardInterrupt):
            pass

    def _expand_turn_in_pager(self, turn: dict):
        """Open a single turn's thinking content in a pager."""
        duration = turn.get('duration', 0)
        text = f"{'='*60}\n"
        text += f"Thinking ({duration:.1f}s)\n"
        text += f"{'='*60}\n\n"
        text += turn.get('thinking', '(empty)')
        text += f"\n\n{'='*60}\n"
        text += f"Response (preview):\n"
        text += turn.get('response_preview', '(empty)')
        text += "…\n"
        self._open_in_pager(text)

    def _open_in_pager(self, text: str):
        """Open text in less/more pager. Falls back to printing if unavailable."""
        pager = shutil.which("less") or shutil.which("more")
        if pager:
            try:
                proc = subprocess.Popen(
                    [pager, "-R"],  # -R for ANSI color passthrough
                    stdin=subprocess.PIPE,
                    encoding="utf-8",
                )
                proc.communicate(input=text)
                return
            except Exception:
                pass
        # Fallback: just print
        print(text)

    # ── Helper: print via rich or plain ────────────────────────────────────
    def _print(self, msg: str):
        if self.console:
            self.console.print(msg)
        else:
            # Strip rich markup for plain output
            clean = re.sub(r'\[/?[^\]]+\]', '', msg)
            print(clean)

    # ── ANSI Spinner (writes to stderr to avoid Rich stdout proxy conflict) ──

    _SPINNER_FRAMES = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']

    def _start_spinner(self, label: str = "Thinking…") -> threading.Event:
        """Start a lightweight ANSI spinner on stderr. Returns a stop event.

        The label can be updated dynamically via stop_event._label_ref[0].
        """
        stop_event = threading.Event()
        label_ref = [label]
        stop_event._label_ref = label_ref  # Expose for dynamic updates
        frames = itertools.cycle(self._SPINNER_FRAMES)

        def _spin():
            start = time.time()
            while not stop_event.is_set():
                frame = next(frames)
                elapsed = time.time() - start
                current_label = label_ref[0]
                if elapsed > 2:
                    msg = f"\r\033[K\033[36m{frame}\033[0m {current_label} \033[2m({elapsed:.0f}s)\033[0m"
                else:
                    msg = f"\r\033[K\033[36m{frame}\033[0m {current_label}"
                sys.stderr.write(msg)
                sys.stderr.flush()
                stop_event.wait(0.08)
            # Clear spinner line
            sys.stderr.write("\r\033[K")
            sys.stderr.flush()

        t = threading.Thread(target=_spin, daemon=True)
        t.start()
        return stop_event

    def _update_spinner(self, stop_event: threading.Event, new_label: str):
        """Update the spinner label (thread-safe via _label_ref)."""
        if hasattr(stop_event, '_label_ref'):
            stop_event._label_ref[0] = new_label

    # ── Code fence filter (suppresses bash blocks from streaming output) ──

    class _CodeFenceFilter:
        """Suppress tool calls and bash code fences from streaming stdout.

        Installed on ``chat._content_filter`` before calling ``stream_response``.
        ``stream_response`` calls ``filter.write(chunk)`` for each content chunk
        and prints only the returned text.

        Suppresses:
        - Bash code fences: ```bash, ```shell, ```sh, ```console
        - Python code fences: ```python (LLM fallback)
        - Structured tool calls using either ``<tool_call>`` or DeepSeek's
          pipe-delimited ``<|tool_call|>`` protocol tags
        """

        _OPEN_RE = re.compile(r'```(?:bash|shell|sh|console|python)[ \t]*\n')
        # A fourth copy of the delimiter list lived here, knowing only the
        # ASCII spellings — so DeepSeek's fullwidth `<｜｜DSML｜｜tool_calls>`
        # and its `invoke` form streamed to the screen in fragments
        # ("</｜｜DSML｜｜tool_ca" … "lls>") while parse() and strip_tool_call()
        # handled them fine. Built from the parser's own patterns instead, so
        # a spelling the parser learns is a spelling this suppresses.
        _TOOL_CALL_OPEN_RE = re.compile(
            r'(?:<tool_call>|<\|tool_call(?:_begin)?\|>'
            + r'|' + _tp_open_pattern()
            + r')\s*'
        )

        #: The XML-shaped family is tracked separately because it nests:
        #: `invoke` sits inside `tool_calls`, so accepting `</invoke>` as the
        #: end of the block released suppression early and left the outer
        #: `</｜｜DSML｜｜tool_calls>` on screen.
        #: `invoke` nests inside `tool_calls`, so the tag that opened the block
        #: is the only one allowed to close it. Accepting either — as the first
        #: version did — let `</invoke>` end the outer block and leave
        #: `</｜｜DSML｜｜tool_calls>` on screen.
        _DSML_OPENERS = (
            ("tool_calls", re.compile(_tp_dsml_open("tool_calls"), re.IGNORECASE)),
            ("invoke", re.compile(_tp_dsml_open("invoke"), re.IGNORECASE)),
        )
        _DSML_CLOSERS = {
            "tool_calls": re.compile(_tp_dsml_close("tool_calls"), re.IGNORECASE),
            "invoke": re.compile(_tp_dsml_close("invoke"), re.IGNORECASE),
        }
        # LLM sometimes hallucinates closing tags: </tool_result>, </tool_report>,
        # or truncated </tool_re, </tool_r, etc. Match all with one regex.
        _TOOL_CALL_CLOSE_RE = re.compile(
            r'(?:</tool_(?:call|result|report|re)\s*>'
            r'|<\|(?:/tool_call(?:_end)?|tool_call_end)\|>'
            + r'|' + _tp_close_pattern()
            + r')'
        )
        # Orphan closing tags that may leak without a matching opener
        _ORPHAN_CLOSE_RE = re.compile(
            r'\s*(?:</tool_(?:call|result|report|re)\s*>'
            r'|<\|(?:/tool_call(?:_end)?|tool_call_end)\|>)\s*'
        )
        # Retain enough undecided input to recognize the longest protocol tag
        # when it is split across streaming chunks.
        _OPEN_TAIL_LEN = max(
            len('<tool_call>'),
            len('<|tool_call|>'),
            len('<|tool_call_begin|>'),
            len('```console\n'),
        )
        # Sized for the longest closing tag, since a shorter retention cuts a
        # tag that straddles two chunks in half and prints the remainder. This
        # was 18, computed before the DSML forms existed; `</｜｜DSML｜｜tool_calls>`
        # is 21, so three characters survived as "lls>" on screen after an
        # otherwise correctly suppressed block.
        _CLOSE_TAIL_LEN = max(
            len('</tool_report>'),
            len('<|/tool_call|>'),
            len('<|tool_call_end|>'),
            len('<|/tool_call_end|>'),
            len('</｜｜DSML｜｜tool_calls>'),
            len('</｜｜DSML｜｜tool_call>'),
            len('</｜｜DSML｜｜invoke>'),
        )

        def __init__(self):
            self._buf = ""
            self._suppressing = False
            self._suppress_type = None  # "fence" | "tool_call" | "dsml_block"
            self._dsml_tag = "tool_calls"
            self._after_tool_result = False

        def write(self, text: str) -> str:
            """Feed a streaming chunk. Returns text safe to print."""
            self._buf += text
            output = ""

            while True:
                if self._suppressing:
                    if self._suppress_type == "fence":
                        idx = self._buf.find('```')
                        if idx == -1:
                            # Keep last 2 chars (partial backtick sequence)
                            if len(self._buf) > 2:
                                self._buf = self._buf[-2:]
                            break
                        # Found closing fence — skip past it
                        self._suppressing = False
                        self._suppress_type = None
                        rest = self._buf[idx + 3:]
                        if rest.startswith('\n'):
                            rest = rest[1:]
                        self._buf = rest
                        continue
                    elif self._suppress_type == "dsml_block":
                        m_close = self._DSML_CLOSERS[
                            getattr(self, "_dsml_tag", "tool_calls")
                        ].search(self._buf)
                        if not m_close:
                            if len(self._buf) > self._CLOSE_TAIL_LEN:
                                self._buf = self._buf[-self._CLOSE_TAIL_LEN:]
                            break
                        self._suppressing = False
                        self._suppress_type = None
                        rest = self._buf[m_close.end():]
                        if rest.startswith('\n'):
                            rest = rest[1:]
                        self._buf = rest
                        continue
                    elif self._suppress_type == "tool_call":
                        # Check all LLM-hallucinated closing tag variants
                        m_close = self._TOOL_CALL_CLOSE_RE.search(self._buf)
                        if not m_close:
                            # Keep tail for a closing tag split across chunks.
                            if len(self._buf) > self._CLOSE_TAIL_LEN:
                                self._buf = self._buf[-self._CLOSE_TAIL_LEN:]
                            break
                        # Found closing tag — skip past it
                        self._suppressing = False
                        self._suppress_type = None
                        rest = self._buf[m_close.end():]
                        if rest.startswith('\n'):
                            rest = rest[1:]
                        self._buf = rest
                        continue
                else:
                    # Check for <tool_call> first (higher priority)
                    m_tc = self._TOOL_CALL_OPEN_RE.search(self._buf)
                    # After a tool result, don't suppress code fences —
                    # they likely contain actual tool output, not LLM commands.
                    m_fence = None if self._after_tool_result else self._OPEN_RE.search(self._buf)

                    # Pick the earliest match
                    match = None
                    match_type = None
                    if m_tc and m_fence:
                        if m_tc.start() <= m_fence.start():
                            match, match_type = m_tc, "tool_call"
                        else:
                            match, match_type = m_fence, "fence"
                    elif m_tc:
                        match, match_type = m_tc, "tool_call"
                    elif m_fence:
                        match, match_type = m_fence, "fence"

                    for _tag, _open_re in self._DSML_OPENERS:
                        m_dsml = _open_re.search(self._buf)
                        if m_dsml and (match is None or m_dsml.start() < match.start()):
                            match, match_type = m_dsml, "dsml_block"
                            self._dsml_tag = _tag
                            break

                    if match:
                        # Strip trailing newlines before the suppressed block
                        output += self._buf[:match.start()].rstrip('\n')
                        self._suppressing = True
                        self._suppress_type = match_type
                        self._buf = self._buf[match.end():]
                        continue

                    # Check for orphan closing tags (</tool_call> without opener)
                    m_orphan = self._ORPHAN_CLOSE_RE.search(self._buf)
                    if m_orphan:
                        output += self._buf[:m_orphan.start()]
                        self._buf = self._buf[m_orphan.end():]
                        continue

                    # Keep a small tail in case a tag straddles two chunks
                    if len(self._buf) > self._OPEN_TAIL_LEN:
                        safe = self._buf[:-self._OPEN_TAIL_LEN]
                        self._buf = self._buf[-self._OPEN_TAIL_LEN:]
                        output += safe
                    break

            return output

        def notify_tool_result(self):
            """Signal that a tool result was just received.

            After a tool result, code fences in the LLM response likely
            contain the actual tool output, so we stop suppressing them.
            """
            self._after_tool_result = True

        def flush(self) -> str:
            """Flush remaining buffer (call after stream ends).

            If still in suppress mode (stream ended mid-suppression),
            discard the suppressed content instead of leaking it to display.
            """
            if self._suppressing:
                # Stream ended while suppressing a tool call or code fence.
                # Discard the buffer — it contains suppressed content.
                self._buf = ""
                self._suppressing = False
                self._suppress_type = None
                return ""
            # Strip any orphan closing tags from remaining buffer
            out = self._ORPHAN_CLOSE_RE.sub('', self._buf)
            self._buf = ""
            return out

    class _SyntaxHighlightFilter:
        """Post-processing filter that highlights code blocks in streaming output.

        Wraps around the content display path. Buffers text when inside a code
        block, applies pygments highlighting on close, and passes through
        non-code text immediately.
        """

        _OPEN_RE = re.compile(r'```(\w+)?\s*\n?$')

        def __init__(self):
            self._buf = ""
            self._in_block = False
            self._language = ""

        def write(self, text: str) -> str:
            """Feed a chunk. Returns text safe to print (may be highlighted)."""
            self._buf += text
            output = ""

            while True:
                if self._in_block:
                    # Look for closing ```
                    idx = self._buf.find('```')
                    if idx == -1:
                        # Keep buffering — don't emit code until block closes
                        break
                    # Found closing fence — highlight the block
                    code = self._buf[:idx]
                    highlighted = highlight_code_block(code, self._language)
                    output += highlighted
                    rest = self._buf[idx + 3:]
                    if rest.startswith('\n'):
                        rest = rest[1:]
                    self._buf = rest
                    self._in_block = False
                    self._language = ""
                    continue
                else:
                    # Look for opening ```lang
                    m = self._OPEN_RE.search(self._buf)
                    if m:
                        # Emit text before the fence
                        output += self._buf[:m.start()]
                        self._language = m.group(1) or ''
                        self._in_block = True
                        self._buf = self._buf[m.end():]
                        continue
                    # No complete fence opener — check for partial at end
                    # Keep last few chars in case ``` straddles chunks
                    if len(self._buf) > 4:
                        safe = self._buf[:-4]
                        self._buf = self._buf[-4:]
                        output += safe
                    break

            return output

        def flush(self) -> str:
            """Flush remaining buffer at end of stream."""
            if self._in_block:
                # Unclosed code block — highlight what we have
                code = self._buf
                self._buf = ""
                self._in_block = False
                return highlight_code_block(code, self._language)
            out = self._buf
            self._buf = ""
            return out

    # ── Tool execution from LLM response (agentic loop) ─────────────────

    def _get_tool_parser(self):
        """Lazily create the ToolCallParser."""
        if not hasattr(self, '_tool_parser') or self._tool_parser is None:
            from agent.tool_parser import ToolCallParser
            self._tool_parser = ToolCallParser()
        return self._tool_parser

    def _get_tool_registry(self):
        """Lazily create the ToolRegistry."""
        from agent.tools import ToolRegistry
        if not hasattr(self, '_tool_registry') or self._tool_registry is None:
            try:
                self._tool_registry = ToolRegistry(working_dir=os.getcwd())
            except Exception as e:
                self._print(f"[red]Failed to initialize ToolRegistry: {e}[/red]")
                self._tool_registry = None
        return self._tool_registry

    def _check_permission(self, tool_call, auto_approved: bool) -> tuple:
        """Interactive permission dialog for tool execution.

        Shows tool preview and asks yes/no for WRITE/EXECUTE/DESTRUCTIVE tools.
        Returns (approved: bool, new_auto_approved: bool).
        """
        from agent.tool_schema import PermissionLevel

        perm_mode = agent_config.permission_mode
        registry = self._get_tool_registry()
        tool_def = registry.get_tool(tool_call.tool_name)

        # Determine permission level (default to EXECUTE for unknown tools)
        if tool_def:
            level = tool_def.permission_level
        else:
            level = PermissionLevel.EXECUTE

        tool_name = tool_call.tool_name if hasattr(tool_call, 'tool_name') else str(tool_call)
        params = tool_call.params if hasattr(tool_call, 'params') else {}

        # Classify dynamic risk before any mode/session shortcut.  In particular,
        # auto_accept and the per-session "always" choice must not bypass a
        # CRITICAL command or path.
        risk_label = ""
        explanation = ""
        pm = None
        try:
            from agent.services.permission_manager import PermissionManager
            pm = PermissionManager()
            risk = pm.classify_risk(tool_name, level.value, params)
            risk_label = risk.value.upper()
        except Exception:
            # If dynamic classification is unavailable, fail closed for every
            # non-read action rather than letting an auto-approval shortcut run.
            risk_label = "LOW" if level == PermissionLevel.READ_ONLY else "CRITICAL"

        # Plan mode: only READ_ONLY tools run
        if perm_mode == "plan":
            if level == PermissionLevel.READ_ONLY:
                return True, auto_approved
            self._print("[dim]  \u2298 Blocked (plan mode)[/dim]")
            return False, auto_approved

        # The explicitly named bypass mode is the sole CRITICAL shortcut.
        if perm_mode == "bypass":
            return True, auto_approved

        # READ_ONLY tools and noncritical auto-approved calls need no prompt.
        if level == PermissionLevel.READ_ONLY:
            return True, auto_approved
        if risk_label != "CRITICAL" and (perm_mode == "auto_accept" or auto_approved):
            return True, auto_approved if perm_mode != "auto_accept" else True

        # Show interactive permission dialog for WRITE/EXECUTE/DESTRUCTIVE tools
        level_colors = {
            PermissionLevel.WRITE: "yellow",
            PermissionLevel.EXECUTE: "orange1",
            PermissionLevel.DESTRUCTIVE: "red",
        }
        color = level_colors.get(level, "yellow")

        if pm is not None:
            try:
                explanation = pm.explain_permission(tool_name, level.value, params)
            except Exception:
                pass

        # Build permission panel with tool preview
        preview_lines = [f"[bold]{tool_name}[/bold] ({level.value})"]
        if risk_label:
            risk_color = {"LOW": "green", "MEDIUM": "yellow", "HIGH": "orange1", "CRITICAL": "red"}.get(risk_label, "yellow")
            preview_lines.append(f"  Risk: [{risk_color}]{risk_label}[/{risk_color}]")
        if explanation:
            preview_lines.append(f"  [dim]{explanation}[/dim]")
        if params:
            for k, v in params.items():
                val_str = str(v)[:100]
                preview_lines.append(f"  {k}: {val_str}")
        else:
            # Fallback to preview() if no structured params
            preview = tool_call.preview() if hasattr(tool_call, 'preview') else ""
            if preview:
                preview_lines.append(f"  {preview}")

        if self.console:
            self.console.print(Panel(
                "\n".join(preview_lines),
                title=f"[{color}]\u26a0 Permission Required[/{color}]",
                border_style=color,
                width=min(80, self.console.width),
            ))
        else:
            self._print(f"  [{color}]\u26a0 Permission Required[/{color}]")
            for line in preview_lines:
                self._print(f"  {line}")

        # Ask for approval
        try:
            response = input("  Allow? [y]es / [n]o / [a]lways: ").strip().lower()
            if response in ('y', 'yes', ''):
                return True, auto_approved
            elif response in ('a', 'always'):
                return True, True  # auto_approved for rest of session
            else:
                self._print("[dim]  \u2298 Denied[/dim]")
                return False, auto_approved
        except (EOFError, KeyboardInterrupt):
            self._print("[dim]  \u2298 Denied[/dim]")
            return False, auto_approved

    # How many tool calls before we tell the model to wrap up
    _AGENTIC_SOFT_LIMIT = 8
    _AGENTIC_HARD_LIMIT = 15

    def _run_agentic_loop(self, max_iterations: int = None):
        """After an LLM response, parse tool calls, execute, feed back, repeat.

        Uses the canonical AgenticLoop from agent.agentic, delegating all loop logic
        and tool execution to it. The CLI remains responsible for:
        - Permission checking via _check_permission
        - Spinner/UX rendering for tool execution
        - Streaming LLM responses back to the user

        Tool result feedback and continuation prompts are automatically handled
        by the canonical loop.

        The canonical AgenticLoop.run() is async, so we bridge from the sync
        CLI world via asyncio.run().
        """
        if self.chat.mode not in ("coding", "fin"):
            return  # Only in coding and finance modes

        if max_iterations is None:
            # Check for CLI --max-turns override
            cli_max = getattr(self.chat, '_cli_max_turns', None)
            max_iterations = cli_max if cli_max is not None else self._AGENTIC_HARD_LIMIT

        import asyncio
        from agent.agentic import AgenticLoop, AgenticConfig

        # Sync LLM caller (runs in thread pool, called by the async loop)
        def _sync_llm_caller(messages):
            """Wrapper around self.chat.stream_response for the agentic loop."""
            self.chat._skip_next_user_add = True
            # Install content filter to suppress <tool_call> tags from display.
            # Without this, tool_call blocks leak to the terminal during
            # agentic loop iterations (the initial filter was cleared after
            # the first _stream_and_render call).
            self.chat._content_filter = self._CodeFenceFilter()
            response_text = self.chat.stream_response("[Continue based on the tool results above.]")
            self.chat._content_filter = None
            return response_text

        # Async LLM caller — wraps the sync one via to_thread
        async def llm_caller(messages):
            return await asyncio.to_thread(_sync_llm_caller, messages)

        # Configure the agentic loop
        config = AgenticConfig(
            max_iterations=max_iterations,
            soft_limit=self._AGENTIC_SOFT_LIMIT,
            auto_approve_reads=True,
            tool_output_limit=3000,
            continuation_prompt="Continue based on the tool results above.",
            wrapup_prompt=(
                "You have used many tool calls. Now STOP making tool calls "
                "and provide your final analysis/summary based on everything "
                "you've gathered so far."
            ),
            hooks_enabled=True,
            skill_forge=None,
        )

        # Get the tool registry and create the loop
        registry = self._get_tool_registry()
        if registry is None:
            return

        loop = AgenticLoop(registry, config)

        # Get the current LLM response from the last assistant message
        history = self.chat.conversation_history
        if not history or history[-1]["role"] != "assistant":
            return

        last_response = history[-1]["content"]

        # Use instance-level auto_approved so "always allow" persists across turns
        stop_event = None

        # Inner async function to consume the async generator
        async def _async_event_loop():
            nonlocal stop_event
            async for event in loop.run(last_response, history, llm_caller):
                if event.type == "tool_start":
                    # Stop any existing spinner before starting a new one
                    if stop_event:
                        stop_event.set()
                        time.sleep(0.1)  # Let spinner thread finish
                        sys.stderr.write("\r\033[K")  # Clear spinner line
                        sys.stderr.flush()
                        stop_event = None

                    # Check permission before execution
                    class _ToolCallProxy:
                        def __init__(self, tool_name, params, preview_text):
                            self.tool_name = tool_name
                            self.params = params or {}
                            self._preview = preview_text
                        def preview(self):
                            return self._preview

                    tool_call = _ToolCallProxy(event.tool_name, event.tool_params, event.tool_preview or "")

                    # Use existing permission logic (persists across turns)
                    approved, self._auto_approved = self._check_permission(tool_call, self._auto_approved)
                    event.approved = approved

                    if approved:
                        # Show tool name + status on a dedicated line (don't mix with LLM text)
                        tool_preview = event.tool_preview or ""
                        # Truncate preview for display
                        if len(tool_preview) > 60:
                            tool_preview = tool_preview[:57] + "..."
                        sys.stderr.write(f"\r\033[K\U0001f527 {event.tool_name}({tool_preview}) ...")
                        sys.stderr.flush()
                        # Also run spinner
                        preview = event.tool_preview or event.tool_name
                        stop_event = self._start_spinner(f"\U0001f527 {event.tool_name}({tool_preview}) ...")
                    # else: loop will stop after this iteration

                elif event.type == "tool_result":
                    # STOP spinner before printing tool result
                    if stop_event:
                        stop_event.set()
                        time.sleep(0.1)  # Let spinner thread finish
                        sys.stderr.flush()
                        stop_event = None

                    # Show tool status on dedicated line, then clear
                    tool_name = getattr(event, 'tool_name', '') or ''
                    success = event.result_success
                    status_icon = '\u2713' if success else '\u2717'
                    sys.stderr.write(f"\r\033[K\U0001f527 {tool_name} {status_icon}\n")
                    sys.stderr.flush()

                    # Show tool result details (collapsible)
                    if success:
                        output = event.result_output or ""
                        preview = output[:200]
                        if len(output) > 200:
                            self._print(f"  [green]\u2713[/green] [dim]{preview}... ({len(output)} chars, /expand to see full)[/dim]")
                        elif preview:
                            self._print(f"  [green]\u2713[/green] [dim]{preview}[/dim]")
                    else:
                        self._print(f"  [red]\u2717[/red] {event.result_error or 'Unknown error'}")

                    # Visual separator between tool results
                    self._print("")

                elif event.type == "llm_response":
                    # LLM response already streamed by llm_caller's stream_response
                    if stop_event:
                        stop_event.set()
                        time.sleep(0.1)  # Let spinner thread finish
                        sys.stderr.write("\r\033[K")  # Clear spinner line
                        sys.stderr.flush()
                        stop_event = None

                elif event.type == "skill_match":
                    # Briefly show matched skills (optional)
                    if event.matched_skills:
                        skill_names = ", ".join(s.get("name", "?") for s in event.matched_skills[:2])
                        self._print(f"[dim](Matched skills: {skill_names})[/dim]")

                elif event.type == "skill_record":
                    # Skill usage was recorded (non-critical, skip display)
                    pass

                elif event.type == "done":
                    # Loop finished naturally
                    if stop_event:
                        stop_event.set()
                        time.sleep(0.1)
                        sys.stderr.write("\r\033[K")
                        sys.stderr.flush()
                        stop_event = None
                    break

                elif event.type == "error":
                    # An error occurred in the loop
                    if stop_event:
                        stop_event.set()
                        time.sleep(0.1)
                        sys.stderr.write("\r\033[K")
                        sys.stderr.flush()
                        stop_event = None
                    self._print(f"[red]Agent error: {event.error_message}[/red]")
                    break

        # Run the async event loop from sync context
        try:
            asyncio.run(_async_event_loop())
        except KeyboardInterrupt:
            if stop_event:
                stop_event.set()
            self._print("\n[dim][Agent loop interrupted][/dim]")
        except Exception as e:
            if stop_event:
                stop_event.set()
            self._print(f"[dim]Agent loop error: {e}[/dim]")

    def _stream_and_render_inner(self, stop_event=None, skip_user_add=False):
        """Inner streaming call (no agentic loop — prevents recursion).

        If *stop_event* is given the caller already owns a running spinner;
        we re-use it instead of starting a new one.

        If *skip_user_add* is True, the caller already added the user message
        to history (e.g. the combined tool_result + continuation prompt), so
        we tell stream_response not to add another one.
        """
        own_spinner = stop_event is None
        if own_spinner:
            stop_event = self._start_spinner("Thinking…")

        self.chat._ui_on_first_token = lambda: stop_event.set()
        # Install content filter to suppress code fences from display
        content_filter = self._CodeFenceFilter()
        # If this is a continuation after tool execution, notify the filter
        # so it preserves code fences that contain actual tool output.
        if skip_user_add:
            content_filter.notify_tool_result()
        self.chat._content_filter = content_filter

        try:
            if skip_user_add:
                # Caller already added user message — tell stream_response to skip
                self.chat._skip_next_user_add = True
                # Use empty prompt since message is already in history
                self.chat.stream_response("")
            else:
                self.chat.stream_response("[Continue based on the tool results above.]")
        except KeyboardInterrupt:
            self._print("\n[dim][Interrupted][/dim]")
        except Exception as e:
            self._print(f"[red]Error: {e}[/red]")
        finally:
            stop_event.set()
            self.chat._content_filter = None
            self.chat._skip_next_user_add = False

    # ── Render AI streaming response ──────────────────────────────────────
    def _print_fleet_stream_header(self) -> None:
        """Print a one-line fleet status header above the leader's
        streaming reply so the user can still see which sub-agents
        are busy / idle / done while the main persona is talking.

        Rationale (Phase 5.12 task #65): during leader streaming,
        prompt_toolkit's bottom_toolbar disappears because
        session.prompt() has already returned and there is no running
        Application to host the toolbar. Printing a plain header line
        into the streamed scrollback is the cheapest way to preserve
        fleet visibility without moving the whole REPL into a
        long-lived Application (the expensive refactor)."""
        session = self._fleet_session
        if session is None:
            return
        from fleet.session import LEADER_FOCUS

        parts = []
        for name in session.member_names():
            evs = session.recent_events(name, limit=1)
            mark = "·"
            if evs:
                kind = evs[-1].kind
                if kind in ("llm_call_start", "task_received"):
                    mark = "⠋"  # busy
                elif kind == "task_completed":
                    mark = "✓"
                elif kind == "task_failed":
                    mark = "✗"
            parts.append(f"{mark}@{name}")
        status = "  ".join(parts)
        self._print(
            f"[dim]⬢ fleet:[/dim] [dim]{session.project_id}[/dim] "
            f"[dim]·[/dim] {status}  "
            f"[dim](leader replying…)[/dim]"
        )

    # ── Phase 4: session-backed turn ──────────────────────────────────────

    class _HistoryStore:
        """Writes the session's messages straight into the agent's history.

        The REPL's other machinery — /history, /transcript, /compact, token
        accounting — all read `chat.conversation_history`, so that list stays
        authoritative. The session is the only writer during a turn; it just
        writes through here instead of keeping a second copy that would drift
        the moment /compact rewrote one of them.
        """

        def __init__(self, chat):
            self.chat = chat

        def append(self, session_id, message):
            entry = {k: v for k, v in dict(message).items() if not k.startswith("_")}
            self.chat.conversation_history.append(entry)

        def load(self, session_id):
            return list(self.chat.conversation_history)

    def _build_turn_session(self):
        """A fresh AgentSession seeded from the agent's current history.

        Per turn rather than per session, deliberately. A long-lived session
        would hold its own copy of the conversation, and /compact, /clear and
        resume all rewrite the agent's list underneath it — the two would
        disagree silently and the model would be prompted with a history the
        user could no longer see.
        """
        import os as _os

        from agent.coding.tool_parser import ToolCallParser
        from agent.runtime.permissions import CapabilitySnapshot, PermissionPolicy
        from agent.runtime.providers.openai_sse import OpenAICompatibleStream
        from agent.runtime.session import AgentSession
        from agent.runtime.tool_executor import ToolExecutor
        from agent.tools import ToolRegistry

        provider = self.chat._resolve_provider()
        llm = OpenAICompatibleStream(
            provider["base_url"],
            provider["api_key"] or self.chat.api_key,
            timeout=180.0,
        )

        registry = ToolRegistry(working_dir=_os.getcwd())
        # Interactive: every registered tool is offered, and the executor asks
        # before anything that needs asking. That is the difference from
        # headless, which starts from an explicit read-only allowlist because
        # there is nobody to answer.
        # interactive=True is not decoration. PermissionPolicy defaults it to
        # False, and with it False every ASK collapses straight to DENY —
        # "execute requires confirmation; no interactive broker" — so a real
        # terminal session could not run Bash at all even though a broker was
        # attached. auto_accept has to be threaded through the same way, or
        # NEOMIND_AUTO_ACCEPT stops working the moment the REPL moves onto
        # this path. Read from agent_config so there is one source of truth
        # about permission mode rather than a second copy here.
        perm_mode = agent_config.permission_mode
        executor = ToolExecutor(
            registry=registry,
            policy=PermissionPolicy(
                capabilities=CapabilitySnapshot.unrestricted(),
                interactive=True,
                auto_accept=(perm_mode == "auto_accept"),
            ),
            broker=self._session_permission_broker(),
            working_dir=_os.getcwd(),
        )

        llm_kwargs = {}
        if getattr(self.chat, "thinking_enabled", False) and provider.get("name") == "deepseek":
            llm_kwargs["thinking"] = {"type": "enabled"}

        max_rounds = getattr(self.chat, "_cli_max_turns", None) or self._AGENTIC_HARD_LIMIT

        return AgentSession(
            llm=llm,
            executor=executor,
            model=self.chat.model,
            mode=self.chat.mode,
            history=list(self.chat.conversation_history),
            store=self._HistoryStore(self.chat),
            tool_parser=ToolCallParser(),
            max_tool_rounds=max_rounds,
            llm_kwargs=llm_kwargs,
        )

    def _session_permission_broker(self):
        """Bridge the executor's permission question to the REPL's prompt.

        Reuses `_check_permission` rather than drawing a second dialog, so the
        panel, the risk wording and the [y]es/[n]o/[a]lways keys stay exactly
        as they are today.

        `_check_permission(tool_call, auto_approved) -> (approved,
        new_auto_approved)` — it wants an object with `.tool_name` and
        `.params`, not the executor's keyword arguments, and the second half of
        its return value is how "[a]lways" persists for the rest of the
        session. Dropping it would make "always" mean "once".

        The prompt blocks on stdin, so it runs in an executor thread; calling
        it directly would freeze the event loop the stream is running on.
        """
        interface = self

        class _Call:
            __slots__ = ("tool_name", "params")

            def __init__(self, tool_name, params):
                self.tool_name = tool_name
                self.params = params

        class _Broker:
            def __init__(self):
                self.auto_approved = False

            async def request(self, request_id, tool_name, preview, risk,
                              explanation, allowed_scopes, params=None, **_ignored):
                import asyncio as _asyncio
                import os as _os

                from agent.runtime.permissions import Approval, Scope, fingerprint

                call = _Call(tool_name, dict(params or {}))

                def _ask():
                    return interface._check_permission(call, self.auto_approved)

                approved, new_auto = await _asyncio.get_event_loop().run_in_executor(
                    None, _ask
                )
                self.auto_approved = new_auto
                if not approved:
                    return None

                # An Approval, not a Decision. The executor rejects anything
                # else outright — "a bare True is not an approval: it names no
                # call, so it cannot be bound to one" — and returning a
                # Decision silently denied every tool in the session path.
                #
                # The fingerprint has to be derived from the same params the
                # executor is about to run, which is why the broker contract
                # carries them: it re-derives it after approval and refuses a
                # mismatch, so an approval cannot be replayed onto a different
                # call.
                return Approval(
                    request_id=request_id,
                    fingerprint=fingerprint(tool_name, dict(params or {}), _os.getcwd()),
                    scope=Scope.ONCE,
                )

        return _Broker()

    def _interpret_as_command(self, text: str):
        """Map prose onto a slash command, or None.

        Mirrors what stream_response() does before calling the provider: the
        same interpreter, the same confidence threshold, and the same silence
        when nothing is confident enough.
        """
        if text.startswith("/"):
            return None
        interpreter = getattr(self.chat, "interpreter", None)
        if not interpreter or not getattr(self.chat, "natural_language_enabled", False):
            return None
        try:
            command, confidence = interpreter.interpret(text, self.chat.mode)
        except Exception:
            return None
        if not command:
            return None
        threshold = getattr(interpreter, "confidence_threshold", 0.8)
        return command if confidence >= threshold else None

    def _stream_and_render_session(self, prompt: str):
        """The session-backed replacement for _stream_and_render().

        Behind NEOMIND_REPL=session_v1 until the real-terminal gate has run —
        this is the surface people use every day, and a green test suite is
        not the same as a turn that still looks right.
        """
        import asyncio as _asyncio

        from cli.session_renderer import SessionRenderer

        # Natural-language command interpretation lives inside
        # stream_response(), which this path does not call — so on session_v1
        # "换成 fin" reached the model as prose and it replied "已切换到 fin
        # 模式" while the status bar still read coding. It claimed to have done
        # something it has no way to do.
        #
        # Interpreted here instead, and dispatched as the command it maps to,
        # using the same interpreter and threshold rather than a second copy.
        interpreted = self._interpret_as_command(prompt)
        if interpreted:
            self._handle_local_command(interpreted)
            return None

        self._interrupt = False
        if self._fleet_session is not None:
            self._print_fleet_stream_header()

        stop = self._start_spinner("Thinking…")

        if self.chat.mode == "coding":
            content_filter = self._CodeFenceFilter()
        elif PYGMENTS_AVAILABLE:
            content_filter = self._SyntaxHighlightFilter()
        else:
            content_filter = None

        cleared = [False]

        def _stop_spinner_and_clear():
            """Stop the spinner and wipe its line — once.

            The spinner runs on stderr while the answer goes to stdout, so its
            final frame can land after the first characters of the reply and
            overwrite them: a resumed session answered "SUME_MARKER_KIWI_42",
            two characters short of the token it had correctly recalled. The
            legacy path clears the line for the same reason.

            Only on the first call. The renderer also stops the spinner when
            the turn ends, and by then the buffered answer has just been
            flushed onto that line — clearing again erased it, and the reply
            vanished completely.
            """
            stop.set()
            if cleared[0]:
                return
            cleared[0] = True
            try:
                sys.stderr.write("\r\033[K")
                sys.stderr.flush()
            except Exception:
                pass

        renderer = SessionRenderer(
            write=lambda text: (sys.stdout.write(text), sys.stdout.flush()),
            write_markup=self._print,
            stop_spinner=_stop_spinner_and_clear,
            content_filter=content_filter,
        )

        session = self._build_turn_session()
        try:
            outcome = _asyncio.run(renderer.render(session.run_turn(prompt)))
        except KeyboardInterrupt:
            self._print("\n[dim][Interrupted][/dim]")
            outcome = None
        finally:
            stop.set()

        # Same safety net the legacy path has: if a turn finished but nothing
        # reached the screen, show the answer rather than leaving a blank. Two
        # separate filter bugs during this migration produced exactly that —
        # a "Thought for 0.5s" line, then the prompt again, with the reply
        # nowhere. A wrong-looking answer is recoverable; a silent empty turn
        # tells the user nothing at all.
        if outcome is not None and outcome.ok and outcome.chars_written == 0:
            text = (outcome.response or "").strip()
            if text:
                self._print(highlight_code_blocks_in_text(text))
            elif outcome.tools_run:
                self._print("[dim](Agent ran tools but produced no visible summary)[/dim]")

        self._warn_on_context_usage()
        return outcome

    def _warn_on_context_usage(self):
        """Unchanged from the legacy path — extracted so both can call it."""
        try:
            if hasattr(self.chat, 'context_manager') and self.chat.context_manager:
                tokens = self.chat.context_manager.count_conversation_tokens()
                from agent.constants.models import get_active_max_context as _gmax
                max_ctx = getattr(self.chat, 'max_context', 0) or _gmax()
                usage = tokens / max_ctx if max_ctx > 0 else 0
                if usage > 0.95:
                    self._print(f"\n[red]⚠ Context {usage:.0%} full! Auto-compacting...[/red]")
                    self.chat.handle_command("/compact", "")
                elif usage > 0.85:
                    self._print(f"\n[yellow]⚠ Context {usage:.0%} full. Run /compact to free space.[/yellow]")
        except Exception:
            pass

    def _stream_and_render(self, prompt: str):
        """Send prompt to agent core's stream_response with spinner UX.

        Phase 4 rollback switch (D8). The turn runs through AgentSession by
        default now: the REPL no longer owns the LLM call or the tool loop, so
        there is one authorization path instead of two.

        The gate that had to pass before this default flipped, all in real
        iTerm2 windows: streaming, tool results, /help, /think, natural-language
        mode switching, permission allow *and* deny in coding and in fin, chat
        shown to run no tool loop at all, Ctrl+C leaving the session able to
        take the next turn, and --resume recalling a token from before a
        restart.

        `NEOMIND_REPL=legacy` returns to the old path. It stays until Phase 8
        retires the compatibility paths, because the first day a new default is
        live is the worst possible day to have no way back.
        """
        if os.environ.get("NEOMIND_REPL", "").strip() != "legacy":
            return self._stream_and_render_session(prompt)

        self._interrupt = False

        # Phase 5.12 task #65: preserve fleet visibility during leader
        # streaming. The bottom_toolbar doesn't render between
        # session.prompt() calls, so print a one-line header instead.
        if self._fleet_session is not None:
            self._print_fleet_stream_header()

        # Start a lightweight ANSI spinner (writes to stderr, avoids Rich proxy)
        stop = self._start_spinner("Thinking…")
        self.chat._ui_on_first_token = lambda: stop.set()

        # In coding mode, install content filter to suppress code fences
        # In other modes, install syntax highlight filter for code blocks
        if self.chat.mode == "coding":
            self.chat._content_filter = self._CodeFenceFilter()
        elif PYGMENTS_AVAILABLE:
            self.chat._content_filter = self._SyntaxHighlightFilter()

        try:
            self.chat.stream_response(prompt)
        except KeyboardInterrupt:
            self._print("\n[dim][Interrupted][/dim]")
        except Exception as e:
            self._print(f"[red]Error: {e}[/red]")
        finally:
            stop.set()
            self.chat._content_filter = None

        # Agentic loop: auto-execute tool blocks from the response
        try:
            self._run_agentic_loop()
        except KeyboardInterrupt:
            self._print("\n[dim][Agent loop interrupted][/dim]")
        except Exception as e:
            self._print(f"[dim]Agent loop error: {e}[/dim]")

        # Check context usage and warn
        try:
            if hasattr(self.chat, 'context_manager') and self.chat.context_manager:
                tokens = self.chat.context_manager.count_conversation_tokens()
                from agent.constants.models import get_active_max_context as _gmax
                max_ctx = getattr(self.chat, 'max_context', 0) or _gmax()
                usage = tokens / max_ctx if max_ctx > 0 else 0
                if usage > 0.95:
                    self._print(f"\n[red]\u26a0 Context {usage:.0%} full! Auto-compacting...[/red]")
                    self.chat.handle_command("/compact", "")
                elif usage > 0.85:
                    self._print(f"\n[yellow]\u26a0 Context {usage:.0%} full. Run /compact to free space.[/yellow]")
        except Exception:
            pass

        # Fallback: if nothing was ever displayed to the user, show the raw response
        if not getattr(self.chat, '_last_content_was_displayed', True):
            history = self.chat.conversation_history
            if history and history[-1]["role"] == "assistant":
                raw = history[-1]["content"].strip()
                if raw:
                    # Strip any tool_call blocks and orphan closing tags for display
                    import re
                    cleaned = re.sub(
                        r'<tool_call>.*?</tool_(?:call|result)>',
                        '', raw, flags=re.DOTALL
                    ).strip()
                    # Strip orphan closing tags (</tool_call> or </tool_result> without opener)
                    cleaned = re.sub(
                        r'\s*</tool_(?:call|result)>\s*',
                        '', cleaned
                    ).strip()
                    cleaned = re.sub(
                        r'```(?:bash|shell|sh|console)\s*\n.*?```',
                        '', cleaned, flags=re.DOTALL
                    ).strip()
                    if cleaned:
                        self._print(highlight_code_blocks_in_text(cleaned))
                    else:
                        self._print("[dim](Agent executed tools but produced no visible summary)[/dim]")

    # ── Main loop ─────────────────────────────────────────────────────────
    def run(self):
        # This session's configuration is its own from here on. The mechanism
        # already existed for fleet workers; interactive surfaces never bound
        # anything, so `/permissions auto` wrote to the process-wide default
        # and a second session — the whole point of extracting a frontend
        # contract — would silently inherit it.
        #
        # Bound here rather than in __init__ because main.py configures the
        # process (mode, custom system prompt) before calling run(), and the
        # fork has to happen after that or the session starts from a
        # configuration nobody chose.
        self._config_token = bind_session_config()

        self.display_welcome()

        if not PROMPT_TOOLKIT_AVAILABLE:
            self._run_fallback()
            return

        # Use plain fallback when running in test/automation mode
        # (prompt_toolkit ANSI escapes break pexpect prompt detection)
        if os.environ.get('NEOMIND_DISABLE_VAULT') and os.environ.get('NEOMIND_DISABLE_MEMORY'):
            self._run_fallback()
            return

        # --- Setup prompt_toolkit session ---
        history_path = Path.home() / ".neomind" / "history"
        history_path.parent.mkdir(parents=True, exist_ok=True)

        bindings = KeyBindings()

        @bindings.add("c-o")
        def _toggle_think(event):
            self.chat.thinking_enabled = not self.chat.thinking_enabled
            status = "on" if self.chat.thinking_enabled else "off"
            event.app.current_buffer.insert_text("")  # noop to refresh toolbar

        # NOTE: Bind multi-key sequence (escape, enter) BEFORE the lone-escape
        # binding so prompt_toolkit's key matcher prefers the longer sequence.
        # Also do NOT use eager=True on the lone-escape binding — eager would
        # fire the moment Escape is seen, preventing the (escape, enter) chord
        # from ever matching.
        @bindings.add("escape", "enter")
        def _newline(event):
            """Esc+Enter (Meta+Enter / Alt+Enter): insert literal newline."""
            event.current_buffer.insert_text("\n")

        @bindings.add("escape")
        def _clear_input(event):
            buf = event.current_buffer
            # If completion menu is showing, dismiss it first
            if buf.complete_state:
                buf.cancel_completion()
            else:
                buf.reset()

        @bindings.add("c-l")
        def _clear_screen(event):
            # prompt_toolkit's renderer.clear() does not always wipe the
            # scrollback / full screen on every terminal emulator. Pair it
            # with a direct ANSI clear so behavior is consistent everywhere.
            try:
                sys.stdout.write("\x1b[2J\x1b[H")
                sys.stdout.flush()
            except Exception:
                pass
            event.app.renderer.clear()

        @bindings.add("c-e")
        def _expand_thinking(event):
            """Ctrl+E: open /expand to view thinking turns."""
            event.app.exit(result="/expand")

        # ── Phase 5.12: Fleet tag row navigation (plain arrow keys) ──
        #
        # These bindings only fire when a fleet is active AND the
        # conditions in their filters match, so they NEVER steal
        # default arrow-key behavior (history recall, cursor movement)
        # from users who don't have a fleet running. Inside the filters
        # I read self._fleet_session, self._fleet_tag_nav_active,
        # etc. directly — prompt_toolkit re-evaluates Conditions on
        # every key press.
        from prompt_toolkit.filters import Condition

        def _fleet_active():
            return self._fleet_session is not None

        def _tag_nav():
            return self._fleet_session is not None and self._fleet_tag_nav_active

        def _buffer_empty(event_or_app=None):
            # Evaluated via Condition — has access to the current app
            # through prompt_toolkit's implicit context. We use a
            # simple approach: read app.current_buffer via get_app.
            from prompt_toolkit.application.current import get_app
            try:
                return get_app().current_buffer.text == ""
            except Exception:
                return False

        _fleet_active_cond = Condition(_fleet_active)
        _tag_nav_cond = Condition(_tag_nav)
        # Down enters tag-nav whenever a fleet is active and we aren't
        # already in nav mode — regardless of whether the input has
        # text. Any half-typed draft is stashed per-focus and restored
        # when the user comes back to that target.
        _can_enter_tag_nav = Condition(
            lambda: _fleet_active() and not _tag_nav()
        )

        @bindings.add("down", filter=_can_enter_tag_nav)
        def _enter_tag_nav(event):
            """Pressing Down while a fleet is running enters
            tag-navigation mode. Down is the natural direction because
            the fleet tag row renders BELOW the input field in the
            bottom toolbar. If the user had half-typed text in the
            buffer, stash it under the current focus so it's restored
            when they come back here."""
            # Stash current draft for the focus we're leaving
            current_focus = self._fleet_session.focus
            current_text = event.app.current_buffer.text
            if current_text:
                self._fleet_draft_buffers[current_focus] = current_text
            else:
                self._fleet_draft_buffers.pop(current_focus, None)
            self._fleet_tag_nav_active = True
            from fleet.session import LEADER_FOCUS
            seq = [LEADER_FOCUS] + self._fleet_session.member_names()
            try:
                self._fleet_tag_cursor = seq.index(self._fleet_session.focus)
            except ValueError:
                self._fleet_tag_cursor = 0
            event.app.invalidate()

        @bindings.add("left", filter=_tag_nav_cond)
        def _tag_nav_left(event):
            from fleet.session import LEADER_FOCUS
            seq = [LEADER_FOCUS] + self._fleet_session.member_names()
            self._fleet_tag_cursor = (self._fleet_tag_cursor - 1) % len(seq)
            event.app.invalidate()

        @bindings.add("right", filter=_tag_nav_cond)
        def _tag_nav_right(event):
            from fleet.session import LEADER_FOCUS
            seq = [LEADER_FOCUS] + self._fleet_session.member_names()
            self._fleet_tag_cursor = (self._fleet_tag_cursor + 1) % len(seq)
            event.app.invalidate()

        @bindings.add("enter", filter=_tag_nav_cond)
        def _tag_nav_confirm(event):
            """Confirm the selected tag, exit the prompt with a
            sentinel so the main loop can print a focus banner."""
            from fleet.session import LEADER_FOCUS
            seq = [LEADER_FOCUS] + self._fleet_session.member_names()
            target = seq[self._fleet_tag_cursor]
            self._fleet_session.set_focus(target)
            self._fleet_tag_nav_active = False
            event.app.exit(result="__fleet_tag_selected__")

        @bindings.add("escape", filter=_tag_nav_cond)
        def _tag_nav_cancel(event):
            self._fleet_tag_nav_active = False
            event.app.invalidate()

        @bindings.add("up", filter=_tag_nav_cond)
        def _tag_nav_up_cancel(event):
            """Up arrow returns focus from the tag row back to the
            input field (natural inverse of Down-to-enter)."""
            self._fleet_tag_nav_active = False
            event.app.invalidate()

        self._completer = SlashCommandCompleter(
            mode=self.chat.mode,
            help_system=self.help_system,
            command_registry=self._new_command_registry,
        )

        style = PTStyle.from_dict({
            "bottom-toolbar":                "bg:#1a1a2e #e0e0e0",
            "bottom-toolbar.text":           "#e0e0e0",
            # Completion menu styling
            "completion-menu":               "bg:#1a1a2e #c0c0c0",
            "completion-menu.completion":     "bg:#1a1a2e #a0a0a0",
            "completion-menu.completion.current": "bg:#3a3a5e #ffffff bold",
            "completion-menu.meta.completion":     "bg:#1a1a2e #666666 italic",
            "completion-menu.meta.completion.current": "bg:#3a3a5e #aaaaaa italic",
        })

        try:
            session = PromptSession(
                history=FileHistory(str(history_path)),
                key_bindings=bindings,
                completer=self._completer,
                complete_while_typing=True,
                complete_in_thread=True,
                bottom_toolbar=self._bottom_toolbar,
                style=style,
                multiline=False,
                enable_history_search=True,
                # TY12 fix: disable mouse support so pasted ANSI escape sequences
                # aren't misinterpreted as mouse events (which caused a crash in
                # prompt_toolkit/key_binding/bindings/mouse.py: "not enough values
                # to unpack (expected 3, got 1)").
                mouse_support=False,
            )
        except Exception as e:
            self._print(f"[dim]prompt_toolkit init failed ({e}), using fallback[/dim]")
            self._run_fallback()
            return

        # patch_stdout lets background daemon threads (e.g. sub-agent
        # reply poller spawned by _wait_and_print_agent_reply) safely
        # print above the active prompt line while the user types.
        pending_draft = ""
        self._stdout_patch = patch_stdout(raw=True)
        self._stdout_patch.__enter__()
        while self.running:
            try:
                prompt_str = self._compute_prompt_str()
                user_input = session.prompt(prompt_str, default=pending_draft)
                pending_draft = ""

                if user_input is None:
                    continue

                # ── Phase 5.12: tag-nav select sentinel ────────────
                # When the user presses Enter while the fleet tag row
                # is focused, one of the KeyBindings calls
                # event.app.exit(result="__fleet_tag_selected__").
                # session.prompt returns that sentinel; the focus was
                # already updated on FleetSession inside the binding.
                # Print the banner and re-prompt without dispatching.
                if user_input == "__fleet_tag_selected__":
                    self._print_fleet_focus_banner()
                    # Restore whatever draft was previously stashed for
                    # the NEW focus target (or empty if none).
                    if self._fleet_session is not None:
                        new_focus = self._fleet_session.focus
                        pending_draft = self._fleet_draft_buffers.pop(
                            new_focus, ""
                        )
                        # Phase 5.12 task #67: clear the unread-badge
                        # for the agent we just switched to. The user
                        # has acknowledged the completion by navigating
                        # here.
                        self._fleet_unread_completion.discard(new_focus)
                    continue

                user_input = user_input.strip()
                if not user_input:
                    continue

                # Handle continuation lines (backslash)
                while user_input.endswith("\\"):
                    user_input = user_input[:-1]
                    cont = session.prompt("... ")
                    if cont is not None:
                        user_input += "\n" + cont

                # ── Phase 5.12: focus-aware input routing ─────────
                # When a fleet is running AND focus is on a sub-
                # agent, non-slash input is dispatched as a task to
                # that sub-agent via submit_to_member. Slash commands
                # always fall through to _handle_local_command so
                # /fleet stop etc. keep working in sub-agent mode.
                if (
                    self._fleet_session is not None
                    and not self._fleet_session.is_focused_on_leader()
                    and not user_input.startswith("/")
                ):
                    name = self._fleet_session.focused_member_name()
                    if name:
                        self._print(f"[white bold]  you:[/white bold] {user_input}")
                        try:
                            task_id = self._fleet_async_run(
                                self._fleet_session.submit_to_member(
                                    name, user_input,
                                )
                            )
                            self._wait_and_print_agent_reply(name, task_id)
                        except Exception as exc:
                            self._print(
                                f"[red]Dispatch failed:[/red] {exc}"
                            )
                    continue

                # ── Phase 5.12: leader-view @mention inline dispatch ─
                # When focus is on leader AND input begins with
                # @<member-name>, dispatch the rest as a task to that
                # member without requiring the user to navigate the
                # tag row. Unknown mentions fall through to normal
                # LLM handling so typos don't block the user.
                if (
                    self._fleet_session is not None
                    and self._fleet_session.is_focused_on_leader()
                    and not user_input.startswith("/")
                ):
                    mention = self._fleet_session.handle_leader_input(
                        user_input,
                    )
                    if mention is not None:
                        target_name, rest = mention
                        try:
                            self._print(
                                f"[white bold]  you → @{target_name}:"
                                f"[/white bold] {rest}"
                            )
                            task_id = self._fleet_async_run(
                                self._fleet_session.submit_to_member(
                                    target_name, rest,
                                )
                            )
                            self._wait_and_print_agent_reply(
                                target_name, task_id,
                            )
                        except Exception as exc:
                            self._print(
                                f"[red]Mention dispatch failed:[/red] {exc}"
                            )
                        continue

                # Try local commands first
                if user_input.startswith("/"):
                    result = self._handle_local_command(user_input)
                    if result is False:
                        break
                    if result is True:
                        continue
                    # result is None → pass to agent core

                # Send to agent core (which handles /search, /code, etc. and regular chat)
                self._stream_and_render(user_input)

            except KeyboardInterrupt:
                # Ctrl+C during input just cancels current line
                # Wrap recovery emit so a third rapid Ctrl+C doesn't kill the process
                try:
                    self._print("")
                except KeyboardInterrupt:
                    pass
                continue
            except EOFError:
                # Ctrl+D
                self._print("[dim]Goodbye![/dim]")
                break
            except Exception as e:
                self._print(f"[red]Error: {e}[/red]")
                continue

        # Close patch_stdout context
        try:
            if getattr(self, "_stdout_patch", None) is not None:
                self._stdout_patch.__exit__(None, None, None)
                self._stdout_patch = None
        except Exception:
            pass

        # Write session journal to vault before saving
        try:
            self.chat.write_session_journal()
        except Exception:
            pass

        # Auto-save on exit
        try:
            if len(self.chat.conversation_history) > 1:
                self.conv_mgr.save(self.chat)
        except Exception:
            pass

    def _run_fallback(self):
        """Fallback loop without prompt_toolkit."""
        while self.running:
            try:
                prompt_str = "> " if self.chat.mode == "coding" else ("[fin] > " if self.chat.mode == "fin" else f"[{self.chat.mode}] > ")
                user_input = input(prompt_str).strip()
                if not user_input:
                    continue

                if user_input.startswith("/"):
                    result = self._handle_local_command(user_input)
                    if result is False:
                        break
                    if result is True:
                        continue

                self._stream_and_render(user_input)

            except KeyboardInterrupt:
                try:
                    print()
                except KeyboardInterrupt:
                    pass
                continue
            except EOFError:
                print("\nGoodbye!")
                break
            except Exception as e:
                print(f"Error: {e}")

        # Write session journal to vault before saving
        try:
            self.chat.write_session_journal()
        except Exception:
            pass

        try:
            if len(self.chat.conversation_history) > 1:
                self.conv_mgr.save(self.chat)
        except Exception:
            pass


# ──────────────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────────────

def interactive_chat(mode: str = "chat", resume_session: str = None,
                     system_prompt: str = None, verbose: bool = False,
                     max_turns: int = None):
    """Launch the NeoMind interface.

    Args:
        mode: Session mode (chat, coding, fin)
        resume_session: Session name/id to resume
        system_prompt: Custom system prompt override
        verbose: Enable verbose/debug mode
        max_turns: Max agentic loop iterations
    """
    # Accept any of the supported authentication paths (mirrors the
    # docker-entrypoint.sh fix in commit 3cf92ae):
    #   - LLM_ROUTER_API_KEY: local LiteLLM proxy (current default)
    #   - DEEPSEEK_API_KEY:   direct DeepSeek fallback
    #   - ZAI_API_KEY:        direct z.ai fallback
    # NeoMindAgent routes via the provider chain so any of these is enough.
    api_key = (
        os.environ.get("DEEPSEEK_API_KEY")
        or os.environ.get("LLM_ROUTER_API_KEY")
        or os.environ.get("ZAI_API_KEY")
    )
    if not api_key:
        print("No API key found in environment.")
        print("Set LLM_ROUTER_API_KEY (recommended), DEEPSEEK_API_KEY,")
        print("or ZAI_API_KEY in your .env file, or enter a key now.")
        try:
            import getpass
            api_key = getpass.getpass("Enter your API key (hidden): ").strip()
        except Exception:
            api_key = input("Enter your API key: ").strip()
        if not api_key:
            print("API key is required!")
            return

    try:
        chat = NeoMindAgent(api_key=api_key)
    except ValueError as e:
        print(f"Error initializing chat: {e}")
        return

    if chat.mode != mode:
        chat.switch_mode(mode, persist=False)

    # Apply CLI overrides
    if verbose:
        chat.verbose_mode = True
    if system_prompt:
        chat.system_prompt = system_prompt
    if max_turns is not None:
        # Store max_turns so the interface can use it for agentic loop limits
        chat._cli_max_turns = max_turns

    interface = NeoMindInterface(chat)

    # Resume session if requested
    if resume_session:
        try:
            from agent.cli_command_system import CommandDispatcher
            dispatcher = getattr(chat, '_command_dispatcher', None)
            if dispatcher:
                # CommandDispatcher.dispatch is async — await it via asyncio.run
                # so the resume-from-crash path doesn't get a coroutine back.
                import asyncio
                try:
                    result = asyncio.run(
                        dispatcher.dispatch(f"/resume {resume_session}", agent=chat)
                    )
                except RuntimeError:
                    # Already inside an event loop — fall back to a fresh loop
                    loop = asyncio.new_event_loop()
                    try:
                        result = loop.run_until_complete(
                            dispatcher.dispatch(f"/resume {resume_session}", agent=chat)
                        )
                    finally:
                        loop.close()
                if result and getattr(result, 'text', None):
                    print(result.text)
            else:
                # Fallback: load session directly via state manager
                if hasattr(chat, 'state_manager') and chat.state_manager:
                    data = chat.state_manager.load_session(resume_session)
                    if data and 'messages' in data:
                        chat.conversation_history = data['messages']
                        print(f"Resumed session: {resume_session} ({len(data['messages'])} messages)")
                    else:
                        print(f"Session not found: {resume_session}")
        except Exception as e:
            print(f"Warning: Could not resume session: {e}")

    interface.run()
