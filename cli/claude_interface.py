"""
Claude CLI-like interface for user agent.

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

from agent.core import DeepSeekStreamingChat
from agent.help_system import HelpSystem
from agent_config import agent_config


# ──────────────────────────────────────────────────────────────────────────────
# Slash Command Completer
# ──────────────────────────────────────────────────────────────────────────────

class SlashCommandCompleter(Completer):
    """Mode-aware slash command completer with descriptions."""

    # All known command descriptions (superset)
    ALL_DESCRIPTIONS = {
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
        "quit": "Exit the agent",
        "exit": "Exit the agent",
        # Chat-only
        "search": "Search the web",
        "browse": "Read a webpage",
        "summarize": "Summarize text or code",
        "translate": "Translate text",
        "generate": "Generate content",
        "reason": "Chain-of-thought reasoning",
        # Coding-only (Claude CLI tools)
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
    }

    def __init__(self, mode: str = "chat", help_system: Optional[HelpSystem] = None):
        self.help_system = help_system
        self.mode = mode
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
    """Save / load conversations to ~/.user/conversations/."""

    def __init__(self):
        self.base_dir = Path.home() / ".user" / "conversations"
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def save(self, chat: DeepSeekStreamingChat, name: Optional[str] = None) -> str:
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
# ClaudeInterface
# ──────────────────────────────────────────────────────────────────────────────

class ClaudeInterface:
    """Claude-like terminal chat interface."""

    def __init__(self, chat: DeepSeekStreamingChat):
        self.chat = chat
        self.console = Console(highlight=False) if RICH_AVAILABLE else None
        self.conv_mgr = ConversationManager()
        self.help_system = HelpSystem()
        self.running = True
        self._interrupt = False

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
                    f"[bold cyan]user[/bold cyan]  "
                    f"[dim]coding mode[/dim]"
                )
                self.console.print(
                    f"[dim]Model:[/dim] [green]{model_name}[/green]  "
                    f"[dim]Think:[/dim] [yellow]{think_icon}[/yellow]"
                )
                self.console.print(
                    f"[dim]Workspace:[/dim] [blue]{cwd}[/blue]"
                )
                self.console.print(
                    "[dim]Tools: Bash, Read, Write, Edit, Glob, Grep, LS[/dim]"
                )
                self.console.print(
                    "[dim]  / commands  |  Ctrl+O think  |  Ctrl+E expand  |  /debug logs  |  Ctrl+D exit[/dim]"
                )
            else:
                self.console.print(
                    f"[bold cyan]user[/bold cyan]  "
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
            print(f"\nuser — {mode} mode")
            print(f"Model: {model_name}  Think: {think_icon}")
            if mode == "coding":
                print(f"Workspace: {os.getcwd()}")
                print("Tools: Bash, Read, Write, Edit, Glob, Grep, LS")
            print("  / commands | Ctrl+O think | Ctrl+D exit\n")

    # ── Status bar (prompt_toolkit bottom_toolbar) ────────────────────────
    def _bottom_toolbar(self):
        model = self.chat.model
        mode = self.chat.mode
        think = "on" if self.chat.thinking_enabled else "off"
        tokens = 0
        max_ctx = 128000
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
                max_ctx = agent_config.max_context_tokens or 128000
        pct = (tokens / max_ctx * 100) if max_ctx > 0 else 0
        if pct >= 80:
            pct_color = "ansired"
        elif pct >= 50:
            pct_color = "ansiyellow"
        else:
            pct_color = "ansigreen"
        max_label = f"{max_ctx // 1000}k"

        if mode == "coding":
            # Coding mode: show permission mode + cwd
            perm = agent_config.permission_mode
            cwd = os.path.basename(os.getcwd()) or "~"
            return HTML(
                f" <b>{model}</b> | coding | {perm} | think:{think} "
                f"| <{pct_color}>{pct:.0f}% {tokens:,}/{max_label}</{pct_color}> {msg_count}msg "
                f"| {cwd} "
                f"  <i>Ctrl+O</i> think  <i>/</i> cmds  <i>Ctrl+D</i> exit"
            )
        else:
            # Chat mode: simpler bar
            return HTML(
                f" <b>{model}</b> | chat | think:{think} "
                f"| <{pct_color}>{pct:.0f}% {tokens:,}/{max_label}</{pct_color}> {msg_count}msg "
                f"  <i>Ctrl+O</i> think  <i>/</i> cmds  <i>Ctrl+D</i> exit"
            )

    # ── Command handling ──────────────────────────────────────────────────
    def _handle_local_command(self, user_input: str) -> Optional[bool]:
        """Handle commands that this interface owns. Returns:
        - False  → quit
        - True   → command handled, continue loop
        - None   → not a local command, pass to agent core
        """
        parts = user_input.split(maxsplit=1)
        cmd = parts[0][1:].lower() if parts[0].startswith("/") else ""
        args = parts[1].strip() if len(parts) > 1 else ""

        # Check if command is allowed in current mode
        allowed = agent_config.available_commands
        if allowed and cmd not in allowed and cmd not in ("quit", "exit", "help"):
            self._print(f"[yellow]/{cmd}[/yellow] is not available in [bold]{self.chat.mode}[/bold] mode")
            if self.chat.mode == "chat":
                self._print("[dim]Hint: start with --mode coding for file and code operations[/dim]")
            return True

        if cmd in ("quit", "exit"):
            self._print("[dim]Goodbye![/dim]")
            return False

        if cmd == "clear":
            self.chat.clear_history()
            self._print("[green]✓[/green] Conversation cleared")
            return True

        if cmd == "think":
            self.chat.thinking_enabled = not self.chat.thinking_enabled
            status = "[green]on[/green]" if self.chat.thinking_enabled else "[red]off[/red]"
            self._print(f"Thinking mode: {status}")
            return True

        if cmd == "debug":
            if args == "dump":
                # Show buffered debug messages from recent requests
                if self.chat.status_buffer:
                    self._print("[dim]── Debug log ──[/dim]")
                    for entry in self.chat.status_buffer[-30:]:
                        lvl = entry.get("level", "info")
                        msg = entry["message"]
                        self._print(f"[dim]  [{lvl}] {msg}[/dim]")
                    self._print(f"[dim]── {len(self.chat.status_buffer)} entries total ──[/dim]")
                else:
                    self._print("[dim]No debug messages yet[/dim]")
            elif args == "clear":
                self.chat.status_buffer = []
                self._print("[green]✓[/green] Debug log cleared")
            else:
                # Toggle verbose mode
                self.chat.verbose_mode = not self.chat.verbose_mode
                if self.chat.verbose_mode:
                    self._print("[yellow]Debug mode: on[/yellow] — all status messages will be shown")
                else:
                    self._print("[yellow]Debug mode: off[/yellow] — clean output")
            return True

        if cmd == "history":
            for i, msg in enumerate(self.chat.conversation_history, 1):
                role = msg["role"].capitalize()
                preview = msg["content"][:120].replace("\n", " ")
                if len(msg["content"]) > 120:
                    preview += "…"
                self._print(f"  {i}. [{role}] {preview}")
            return True

        if cmd == "save":
            try:
                fp = self.conv_mgr.save(self.chat, args or None)
                self._print(f"[green]✓[/green] Saved → {fp}")
            except Exception as e:
                self._print(f"[red]✗[/red] Save failed: {e}")
            return True

        if cmd == "load":
            if not args:
                convs = self.conv_mgr.list_all()
                if convs:
                    self._print("[bold]Saved conversations:[/bold]")
                    for c in convs[:20]:
                        self._print(f"  • {c}")
                else:
                    self._print("[dim]No saved conversations[/dim]")
            else:
                data = self.conv_mgr.load(args)
                if data:
                    self.chat.conversation_history = data.get("history", [])
                    self._print(f"[green]✓[/green] Loaded: {args}")
                else:
                    self._print(f"[red]✗[/red] Not found: {args}")
            return True

        if cmd == "help" and not args:
            mode_label = self.chat.mode
            self._print(f"[bold]Commands ({mode_label} mode):[/bold]")
            allowed = agent_config.available_commands
            for c in sorted(allowed):
                desc = SlashCommandCompleter.ALL_DESCRIPTIONS.get(c, "")
                self._print(f"  /{c:<14} {desc}")
            return True

        if cmd == "transcript":
            self._show_transcript(args)
            return True

        if cmd == "expand":
            self._show_expand(args)
            return True

        if cmd == "permissions":
            current = agent_config.permission_mode
            if not args:
                # Toggle between normal and auto_accept
                new_mode = "auto_accept" if current == "normal" else "normal"
                agent_config.permission_mode = new_mode
            elif args in ("normal", "auto_accept", "auto", "plan"):
                new_mode = "auto_accept" if args == "auto" else args
                agent_config.permission_mode = new_mode
            else:
                self._print(f"[yellow]Usage:[/yellow] /permissions [normal|auto|plan]")
                self._print(f"  [dim]Current: {current}[/dim]")
                return True
            mode_display = {
                "normal": "[cyan]normal[/cyan] — ask before each command",
                "auto_accept": "[green]auto_accept[/green] — run all commands automatically",
                "plan": "[yellow]plan[/yellow] — read-only, no execution",
            }
            self._print(f"Permissions: {mode_display[agent_config.permission_mode]}")
            return True

        # Not a local command
        return None

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
        - Python code fences: ```python (DeepSeek fallback)
        - Structured tool calls: <tool_call>...</tool_call>
        """

        _OPEN_RE = re.compile(r'```(?:bash|shell|sh|console|python)[ \t]*\n')
        _TOOL_CALL_OPEN_RE = re.compile(r'<tool_call>\s*')
        _TOOL_CALL_CLOSE = '</tool_call>'

        def __init__(self):
            self._buf = ""
            self._suppressing = False
            self._suppress_type = None  # "fence" or "tool_call"

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
                    elif self._suppress_type == "tool_call":
                        idx = self._buf.find(self._TOOL_CALL_CLOSE)
                        if idx == -1:
                            # Keep tail for partial match
                            close_len = len(self._TOOL_CALL_CLOSE)
                            if len(self._buf) > close_len:
                                self._buf = self._buf[-close_len:]
                            break
                        # Found closing tag — skip past it
                        self._suppressing = False
                        self._suppress_type = None
                        rest = self._buf[idx + len(self._TOOL_CALL_CLOSE):]
                        if rest.startswith('\n'):
                            rest = rest[1:]
                        self._buf = rest
                        continue
                else:
                    # Check for <tool_call> first (higher priority)
                    m_tc = self._TOOL_CALL_OPEN_RE.search(self._buf)
                    m_fence = self._OPEN_RE.search(self._buf)

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

                    if match:
                        # Strip trailing newlines before the suppressed block
                        output += self._buf[:match.start()].rstrip('\n')
                        self._suppressing = True
                        self._suppress_type = match_type
                        self._buf = self._buf[match.end():]
                        continue

                    # Keep a small tail in case a tag straddles two chunks
                    if len(self._buf) > 15:
                        safe = self._buf[:-15]
                        self._buf = self._buf[-15:]
                        output += safe
                    break

            return output

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
            self._tool_registry = ToolRegistry(working_dir=os.getcwd())
        return self._tool_registry

    def _execute_tool_call(self, tool_call) -> 'ToolResult':
        """Execute a parsed ToolCall through the registry.

        For structured tool calls (Read, Edit, Grep, etc.), dispatches to
        the registered tool definition's execute function with validated params.
        For legacy bash blocks, falls back to Bash tool.

        Returns a ToolResult.
        """
        registry = self._get_tool_registry()
        tool_def = registry.get_tool(tool_call.tool_name)

        if tool_def is None:
            # Unknown tool — try Bash as fallback for legacy compatibility
            from agent.tools import ToolResult
            return ToolResult(False, error=f"Unknown tool: {tool_call.tool_name}")

        # Validate params
        valid, error = tool_def.validate_params(tool_call.params)
        if not valid:
            from agent.tools import ToolResult
            return ToolResult(False, error=f"Invalid params: {error}")

        # Apply defaults and execute
        params = tool_def.apply_defaults(tool_call.params)
        return tool_def.execute(**params)

    def _check_permission(self, tool_call, auto_approved: bool) -> tuple:
        """Check permission for a tool call.

        Returns (approved: bool, new_auto_approved: bool).
        Uses per-tool permission levels when a structured tool is found.
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

        # Plan mode: only READ_ONLY tools run
        if perm_mode == "plan":
            if level == PermissionLevel.READ_ONLY:
                return True, auto_approved
            preview = tool_call.preview()
            self._print(f"[dim]  Would run: {preview}[/dim]")
            self._print("[dim]  (permission mode is 'plan' — skipping)[/dim]")
            return False, auto_approved

        # Auto-accept mode or already auto-approved this turn
        if perm_mode == "auto_accept" or auto_approved:
            return True, auto_approved

        # Normal mode: READ_ONLY tools auto-approve (no prompt)
        if level == PermissionLevel.READ_ONLY:
            return True, auto_approved

        # Ask user for WRITE/EXECUTE/DESTRUCTIVE tools
        preview = tool_call.preview()
        if tool_call.tool_name == "Bash":
            self._print(f"  [dim]│[/dim] [cyan]$[/cyan] [dim]{preview}[/dim]")
        else:
            self._print(f"  [dim]│[/dim] [cyan]{tool_call.tool_name}[/cyan] [dim]{preview}[/dim]")
        try:
            choice = input("  │ Run? [y/n/a]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            self._print("[dim]  │ Skipped[/dim]")
            return False, auto_approved

        if choice in ("n", "no"):
            return False, auto_approved
        if choice in ("a", "all"):
            return True, True
        return choice in ("y", "yes", ""), auto_approved

    # How many tool calls before we tell the model to wrap up
    _AGENTIC_SOFT_LIMIT = 8
    _AGENTIC_HARD_LIMIT = 15

    def _run_agentic_loop(self, max_iterations: int = None):
        """After an LLM response, parse tool calls, execute, feed back, repeat.

        This implements the structured agentic loop:
        1. Parse the FIRST tool call from the LLM response (structured or legacy)
        2. Check per-tool permissions (READ_ONLY auto-approves)
        3. Validate parameters against the tool's schema
        4. Execute under spinner (no verbose output)
        5. Feed structured result back to conversation
        6. Re-prompt the LLM
        7. Repeat until no more tool calls or max iterations

        After _AGENTIC_SOFT_LIMIT iterations, the re-prompt instructs the model
        to stop making tool calls and provide a final summary.
        """
        if self.chat.mode != "coding":
            return  # Only in coding mode

        if max_iterations is None:
            max_iterations = self._AGENTIC_HARD_LIMIT

        parser = self._get_tool_parser()
        auto_approved = False  # Track if user said "all" this turn

        for iteration in range(max_iterations):
            # Get the last assistant message
            history = self.chat.conversation_history
            if not history:
                return
            last_msg = history[-1]
            if last_msg["role"] != "assistant":
                return

            response_text = last_msg["content"]

            # Parse the first tool call
            tool_call = parser.parse(response_text)
            if not tool_call:
                return  # No tool calls found — done

            # Check permission
            approved, auto_approved = self._check_permission(tool_call, auto_approved)
            if not approved:
                return

            # Start spinner — tool execution + re-prompt happen under it
            preview = tool_call.preview()
            stop = self._start_spinner("Thinking…")
            self._update_spinner(stop, f"Thinking… {preview}")

            # Execute the tool call (structured dispatch or bash)
            result = self._execute_tool_call(tool_call)

            # Update spinner with brief tool result status
            if result.success:
                brief = (result.output or "").split('\n')[0][:50]
                if brief:
                    self._update_spinner(stop, f"Thinking… {brief}")
                else:
                    self._update_spinner(stop, "Thinking…")
            else:
                brief = (result.error or "").split('\n')[0][:50]
                if brief:
                    self._update_spinner(stop, f"Thinking… {brief}")
                else:
                    self._update_spinner(stop, "Thinking… (error)")

            # Feed structured result + continuation prompt as ONE user message
            from agent.tool_parser import format_tool_result
            feedback = format_tool_result(tool_call, result)

            # After soft limit, tell the model to wrap up instead of making more calls
            if iteration >= self._AGENTIC_SOFT_LIMIT - 1:
                continuation = (
                    "You have used many tool calls. Now STOP making tool calls "
                    "and provide your final analysis/summary based on everything "
                    "you've gathered so far. Do NOT include any more code blocks."
                )
            else:
                continuation = "Continue based on the tool results above."

            combined = feedback + "\n\n" + continuation
            self.chat.add_to_history("user", combined)

            # Re-prompt the LLM — spinner stays running until first content token
            self._stream_and_render_inner(stop_event=stop, skip_user_add=True)

        self._print("[dim](Agent loop: max iterations reached)[/dim]")

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
        self.chat._content_filter = self._CodeFenceFilter()

        try:
            if skip_user_add:
                # Caller already added user message — tell stream_response to skip
                self.chat._skip_next_user_add = True
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
    def _stream_and_render(self, prompt: str):
        """Send prompt to agent core's stream_response with spinner UX."""
        self._interrupt = False

        # Start a lightweight ANSI spinner (writes to stderr, avoids Rich proxy)
        stop = self._start_spinner("Thinking…")
        self.chat._ui_on_first_token = lambda: stop.set()

        # In coding mode, install content filter to suppress code fences
        if self.chat.mode == "coding":
            self.chat._content_filter = self._CodeFenceFilter()

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

        # Fallback: if nothing was ever displayed to the user, show the raw response
        if not getattr(self.chat, '_last_content_was_displayed', True):
            history = self.chat.conversation_history
            if history and history[-1]["role"] == "assistant":
                raw = history[-1]["content"].strip()
                if raw:
                    # Strip any tool_call blocks for display
                    import re
                    cleaned = re.sub(
                        r'<tool_call>.*?</tool_call>',
                        '', raw, flags=re.DOTALL
                    ).strip()
                    cleaned = re.sub(
                        r'```(?:bash|shell|sh|console)\s*\n.*?```',
                        '', cleaned, flags=re.DOTALL
                    ).strip()
                    if cleaned:
                        self._print(cleaned)
                    else:
                        self._print("[dim](Agent executed tools but produced no visible summary)[/dim]")

    # ── Main loop ─────────────────────────────────────────────────────────
    def run(self):
        self.display_welcome()

        if not PROMPT_TOOLKIT_AVAILABLE:
            self._run_fallback()
            return

        # --- Setup prompt_toolkit session ---
        history_path = Path.home() / ".user" / "history"
        history_path.parent.mkdir(parents=True, exist_ok=True)

        bindings = KeyBindings()

        @bindings.add("c-o")
        def _toggle_think(event):
            self.chat.thinking_enabled = not self.chat.thinking_enabled
            status = "on" if self.chat.thinking_enabled else "off"
            event.app.current_buffer.insert_text("")  # noop to refresh toolbar

        @bindings.add("escape", eager=True)
        def _clear_input(event):
            buf = event.current_buffer
            # If completion menu is showing, dismiss it first
            if buf.complete_state:
                buf.cancel_completion()
            else:
                buf.reset()

        @bindings.add("c-l")
        def _clear_screen(event):
            event.app.renderer.clear()

        @bindings.add("c-e")
        def _expand_thinking(event):
            """Ctrl+E: open /expand to view thinking turns."""
            event.app.exit(result="/expand")

        # Shift+Enter for newline continuation
        @bindings.add("escape", "enter")
        def _newline(event):
            event.current_buffer.insert_text("\n")

        completer = SlashCommandCompleter(mode=self.chat.mode, help_system=self.help_system)

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
                completer=completer,
                complete_while_typing=True,
                complete_in_thread=True,
                bottom_toolbar=self._bottom_toolbar,
                style=style,
                multiline=False,
                enable_history_search=True,
            )
        except Exception as e:
            self._print(f"[dim]prompt_toolkit init failed ({e}), using fallback[/dim]")
            self._run_fallback()
            return

        while self.running:
            try:
                prompt_str = "> " if self.chat.mode == "coding" else f"[{self.chat.mode}] > "
                user_input = session.prompt(prompt_str)

                if user_input is None:
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
                self._print("")
                continue
            except EOFError:
                # Ctrl+D
                self._print("[dim]Goodbye![/dim]")
                break
            except Exception as e:
                self._print(f"[red]Error: {e}[/red]")
                continue

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
                prompt_str = "> " if self.chat.mode == "coding" else f"[{self.chat.mode}] > "
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
                print()
                continue
            except EOFError:
                print("\nGoodbye!")
                break
            except Exception as e:
                print(f"Error: {e}")

        try:
            if len(self.chat.conversation_history) > 1:
                self.conv_mgr.save(self.chat)
        except Exception:
            pass


# ──────────────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────────────

def interactive_chat_claude_interface(mode: str = "chat"):
    """Launch the Claude-like interface."""
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        print("DEEPSEEK_API_KEY not found in environment.")
        print("Please set it in your .env file or enter it now.")
        api_key = input("Enter your DeepSeek API key: ").strip()
        if not api_key:
            print("API key is required!")
            return

    try:
        chat = DeepSeekStreamingChat(api_key=api_key)
    except ValueError as e:
        print(f"Error initializing chat: {e}")
        return

    if chat.mode != mode:
        chat.switch_mode(mode, persist=False)

    interface = ClaudeInterface(chat)
    interface.run()
