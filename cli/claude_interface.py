"""
Claude CLI-like interface for ikol1729 agent.

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
    """Fuzzy-matching slash command completer with descriptions."""

    COMMAND_DESCRIPTIONS = {
        "clear": "Clear conversation history",
        "think": "Toggle thinking mode on/off",
        "history": "Show conversation history",
        "mode": "Switch chat / coding mode",
        "search": "Search the web",
        "write": "Write content to a file",
        "edit": "Edit file content",
        "read": "Read file or webpage",
        "run": "Execute a shell command",
        "git": "Execute git commands",
        "code": "Code analysis and refactoring",
        "models": "List and switch models",
        "save": "Save conversation to file",
        "load": "Load previous conversation",
        "context": "Manage context window",
        "verbose": "Toggle verbose output",
        "task": "Manage tasks",
        "plan": "Generate plans from goals",
        "execute": "Execute a plan",
        "diff": "Compare files or versions",
        "browse": "Browse directory tree",
        "undo": "Revert recent changes",
        "test": "Run tests",
        "apply": "Apply pending code changes",
        "fix": "Auto-fix code issues",
        "analyze": "Analyze code for issues",
        "debug": "Toggle debug logs / dump recent logs",
        "explain": "Explain code",
        "refactor": "Suggest refactorings",
        "grep": "Search text across files",
        "find": "Find files by pattern",
        "summarize": "Summarize text or code",
        "translate": "Translate text",
        "generate": "Generate content",
        "reason": "Chain-of-thought reasoning",
        "switch": "Switch model",
        "quit": "Exit the agent",
        "exit": "Exit the agent",
        "help": "Show help",
        "auto": "Control auto-features",
    }

    def __init__(self, help_system: Optional[HelpSystem] = None):
        self.help_system = help_system
        if help_system and hasattr(help_system, "help_texts"):
            self.commands = list(help_system.help_texts.keys())
        else:
            self.commands = list(self.COMMAND_DESCRIPTIONS.keys())
        # Add commands that may not be in help_system
        for cmd in ("save", "load", "debug"):
            if cmd not in self.commands:
                self.commands.append(cmd)

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if not text.startswith("/"):
            return

        # Don't complete if there's a space (user is typing args, not a command)
        if " " in text:
            return

        partial = text[1:].lower()

        for cmd in sorted(self.commands):
            # Prefix match first, then fuzzy substring fallback
            if cmd.lower().startswith(partial):
                desc = self.COMMAND_DESCRIPTIONS.get(cmd, "")
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
    """Save / load conversations to ~/.ikol1729/conversations/."""

    def __init__(self):
        self.base_dir = Path.home() / ".ikol1729" / "conversations"
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
        if self.console:
            model_name = self.chat.model
            mode = self.chat.mode
            think_icon = "on" if self.chat.thinking_enabled else "off"
            self.console.print()
            self.console.print(
                f"[bold cyan]ikol1729 agent[/bold cyan]  "
                f"[dim]v0.1.0[/dim]"
            )
            self.console.print(
                f"[dim]Model:[/dim] [green]{model_name}[/green]  "
                f"[dim]Mode:[/dim] [green]{mode}[/green]  "
                f"[dim]Think:[/dim] [yellow]{think_icon}[/yellow]"
            )
            self.console.print(
                "[dim]  / commands  |  Ctrl+O think  |  /debug logs  |  Ctrl+C cancel  |  Ctrl+D exit[/dim]"
            )
            self.console.print()
        else:
            print(f"\nikol1729 agent v0.1.0")
            print(f"Model: {self.chat.model}  Mode: {self.chat.mode}")
            print("  / commands | Ctrl+O think | Ctrl+C cancel | Ctrl+D exit\n")

    # ── Status bar (prompt_toolkit bottom_toolbar) ────────────────────────
    def _bottom_toolbar(self):
        model = self.chat.model
        mode = self.chat.mode
        think = "on" if self.chat.thinking_enabled else "off"
        tokens = 0
        max_ctx = 128000  # DeepSeek context window
        msg_count = len(self.chat.conversation_history)
        if hasattr(self.chat, "context_manager") and self.chat.context_manager:
            try:
                tokens = self.chat.context_manager.count_conversation_tokens()
            except Exception:
                pass
            try:
                from agent_config import agent_config
                max_ctx = agent_config.max_context_tokens or 128000
            except Exception:
                pass
        pct = (tokens / max_ctx * 100) if max_ctx > 0 else 0
        if pct >= 80:
            pct_color = "ansired"
        elif pct >= 50:
            pct_color = "ansiyellow"
        else:
            pct_color = "ansigreen"
        max_label = f"{max_ctx // 1000}k"
        return HTML(
            f" <b>{model}</b> | {mode} | think:{think} "
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
            self._print("[bold]Commands:[/bold]")
            for c in sorted(SlashCommandCompleter.COMMAND_DESCRIPTIONS):
                desc = SlashCommandCompleter.COMMAND_DESCRIPTIONS[c]
                self._print(f"  /{c:<14} {desc}")
            return True

        # Not a local command
        return None

    # ── Helper: print via rich or plain ────────────────────────────────────
    def _print(self, msg: str):
        if self.console:
            self.console.print(msg)
        else:
            # Strip rich markup for plain output
            clean = re.sub(r'\[/?[^\]]+\]', '', msg)
            print(clean)

    # ── Render AI streaming response ──────────────────────────────────────
    def _stream_and_render(self, prompt: str):
        """Send prompt to agent core's stream_response and let it handle output."""
        self._interrupt = False
        try:
            self.chat.stream_response(prompt)
        except KeyboardInterrupt:
            self._print("\n[dim][Interrupted][/dim]")
        except Exception as e:
            self._print(f"[red]Error: {e}[/red]")

    # ── Main loop ─────────────────────────────────────────────────────────
    def run(self):
        self.display_welcome()

        if not PROMPT_TOOLKIT_AVAILABLE:
            self._run_fallback()
            return

        # --- Setup prompt_toolkit session ---
        history_path = Path.home() / ".ikol1729" / "history"
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

        # Shift+Enter for newline continuation
        @bindings.add("escape", "enter")
        def _newline(event):
            event.current_buffer.insert_text("\n")

        completer = SlashCommandCompleter(self.help_system)

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
