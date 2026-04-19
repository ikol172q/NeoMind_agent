"""NeoMind CLI Command System — 100% Claude Code Pattern

Reimplements Claude Code's command architecture in Python:
- CommandBase type with 3 variants (prompt/local/local-ui)
- Declarative registration with lazy loading
- Slash command parsing and dispatch
- Feature gating and permission checks
- Skill/plugin command discovery

Architecture mirrors commands.ts:
    Command = CommandBase & (PromptCommand | LocalCommand | UICommand)
    CommandRegistry: register, discover, filter, dispatch
    SlashCommandParser: parse user input into (name, args)
    CommandDispatcher: route to appropriate handler

Claude Code equivalents:
    commands.ts          → CommandRegistry
    slashCommandParsing  → SlashCommandParser
    processSlashCommand  → CommandDispatcher
    Command type union   → Command dataclass variants
"""

import asyncio
import importlib
import json
import logging
import os
import re
import shlex
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import (
    Optional, Dict, List, Any, Callable, Awaitable,
    Union, Tuple, Set
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# Command Types — mirrors Claude Code's Command union type
# ─────────────────────────────────────────────────────────────────────

class CommandType(Enum):
    """Three command types, matching Claude Code exactly."""
    PROMPT = "prompt"    # Skill: expanded to text, sent to LLM
    LOCAL = "local"      # Synchronous: returns text result
    LOCAL_UI = "local-ui"  # UI: renders interactive element (replaces local-jsx)


class CommandSource(Enum):
    """Where the command was loaded from."""
    BUILTIN = "builtin"
    SKILL = "skill"
    PLUGIN = "plugin"
    MCP = "mcp"
    USER = "user"


class CommandAvailability(Enum):
    """Who can use this command."""
    ALL = "all"
    CODING = "coding"
    CHAT = "chat"
    FINANCE = "fin"
    INTERNAL = "internal"  # Like Claude Code's ANT-ONLY


@dataclass
class CommandResult:
    """Result from executing a command.

    Mirrors Claude Code's LocalCommandResult + PromptCommandResult.
    """
    text: str = ""                      # Display text
    should_query: bool = False          # Send to LLM after?
    display: str = "normal"             # "normal" | "skip" | "system"
    meta_messages: List[str] = field(default_factory=list)  # Hidden LLM messages
    next_input: str = ""                # Pre-fill next input
    submit_next: bool = False           # Auto-submit next input
    compact: bool = False               # Trigger compaction


@dataclass
class Command:
    """Single command definition — the core building block.

    Like Claude Code's Command type, this is a declarative object
    (not a class hierarchy) that binds name + metadata + handler.

    Attributes:
        name: Command name without slash (e.g., "help", "compact")
        description: One-line description for help/autocomplete
        type: CommandType (prompt/local/local-ui)
        handler: The actual function to call
        aliases: Alternative names (e.g., ["q", "quit"] for "exit")
        modes: Which modes this command is available in
        source: Where it was loaded from
        is_enabled: Dynamic gate function (like Claude Code's isEnabled())
        is_hidden: Hide from autocomplete/help
        argument_hint: Usage hint (e.g., "<file_path>")
        feature_gate: Feature flag name (command disabled if flag is off)
        allowed_tools: For prompt commands, which tools the LLM can use
        model_override: For prompt commands, use a specific model
        priority: Sort order in help listing
    """
    name: str
    description: str
    type: CommandType = CommandType.LOCAL
    handler: Optional[Callable] = None
    module_path: Optional[str] = None   # For lazy loading
    aliases: List[str] = field(default_factory=list)
    modes: List[str] = field(default_factory=lambda: ["chat", "coding", "fin"])
    source: CommandSource = CommandSource.BUILTIN
    is_enabled: Optional[Callable[[], bool]] = None
    is_hidden: bool = False
    argument_hint: str = ""
    feature_gate: Optional[str] = None
    allowed_tools: Optional[List[str]] = None
    model_override: Optional[str] = None
    priority: int = 50
    # Lazy-loaded module cache
    _loaded_module: Any = field(default=None, repr=False)

    async def load(self):
        """Lazy-load the command module if needed.

        Like Claude Code's `load: () => import('./path.js')` pattern.
        """
        if self._loaded_module is not None:
            return self._loaded_module
        if self.module_path:
            try:
                self._loaded_module = importlib.import_module(self.module_path)
                if hasattr(self._loaded_module, "handler"):
                    self.handler = self._loaded_module.handler
                return self._loaded_module
            except ImportError as e:
                logger.warning(f"Failed to load command module {self.module_path}: {e}")
        return None

    def available_in_mode(self, mode: str) -> bool:
        """Check if command is available in the given mode."""
        return mode in self.modes or "all" in [m.lower() for m in self.modes]

    def check_enabled(self) -> bool:
        """Check if the command is currently enabled.

        Combines feature gate and dynamic is_enabled check.
        """
        if self.feature_gate:
            from agent_config import agent_config
            if not agent_config.get(f"features.{self.feature_gate}", False):
                return False
        if self.is_enabled:
            return self.is_enabled()
        return True


# ─────────────────────────────────────────────────────────────────────
# Slash Command Parser — mirrors slashCommandParsing.ts
# ─────────────────────────────────────────────────────────────────────

@dataclass
class ParsedCommand:
    """Result of parsing a slash command."""
    name: str
    args: str
    raw: str


class SlashCommandParser:
    """Parse user input for slash commands.

    Like Claude Code's parseSlashCommand():
    - Detects `/` prefix
    - Extracts command name (first word after /)
    - Everything after is args
    """

    @staticmethod
    def parse(input_text: str) -> Optional[ParsedCommand]:
        """Parse a slash command from user input.

        Returns None if input is not a slash command.

        Examples:
            "/help"           → ParsedCommand("help", "")
            "/search AI news" → ParsedCommand("search", "AI news")
            "/config set temperature 0.5" → ParsedCommand("config", "set temperature 0.5")
            "hello"           → None
        """
        text = input_text.strip()
        if not text.startswith("/"):
            return None

        # Remove the leading /
        text = text[1:]

        # Split into command name and args
        parts = text.split(None, 1)
        if not parts:
            return None

        name = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        return ParsedCommand(name=name, args=args, raw=input_text)

    @staticmethod
    def is_slash_command(input_text: str) -> bool:
        """Quick check if input starts with /."""
        return input_text.strip().startswith("/")


def split_args(args: str, maxsplit: int = -1) -> List[str]:
    """Split slash-command args respecting shell-style quoting.

    If `args` contains quote characters, use shlex so that
    `"/tmp/file with spaces.md"` and `"team with space"` parse as a
    single token with the surrounding quotes stripped.

    Falls back to plain whitespace split when there are no quotes —
    this preserves the historic behavior for the (very common)
    unquoted case and avoids breaking on stray apostrophes inside
    user prose passed to prompt commands.

    `maxsplit` mirrors `str.split(None, maxsplit)` semantics: when >= 0
    the result has at most `maxsplit + 1` elements, with any remaining
    text returned untouched as the final element.
    """
    if args is None:
        return []
    text = args.strip()
    if not text:
        return []

    if '"' in text or "'" in text:
        try:
            lex = shlex.shlex(text, posix=True)
            lex.whitespace_split = True
            lex.commenters = ''
            tokens: List[str] = []
            if maxsplit is None or maxsplit < 0:
                tokens = list(lex)
            else:
                for _ in range(maxsplit):
                    tok = lex.get_token()
                    if tok is None or tok == '':
                        break
                    tokens.append(tok)
                # Remainder: collect as-is (with quotes stripped) by
                # taking whatever's left in the underlying stream.
                remainder = lex.instream.read().strip()
                if remainder:
                    # Re-parse the remainder fully so any further quotes
                    # are also stripped, then re-join with single spaces.
                    try:
                        rem_tokens = shlex.split(remainder, posix=True)
                        if rem_tokens:
                            tokens.append(' '.join(rem_tokens))
                    except ValueError:
                        tokens.append(remainder)
            return tokens
        except ValueError:
            # Unbalanced quotes — fall through to plain split
            pass

    if maxsplit is None or maxsplit < 0:
        return text.split()
    return text.split(None, maxsplit)


# ─────────────────────────────────────────────────────────────────────
# Command Registry — mirrors commands.ts COMMANDS() function
# ─────────────────────────────────────────────────────────────────────

class CommandRegistry:
    """Central registry for all commands.

    Like Claude Code's COMMANDS() memoized function + getCommands():
    - Registers built-in commands
    - Discovers skill commands from filesystem
    - Discovers plugin commands
    - Filters by mode, feature gates, permissions
    - Provides fuzzy search for autocomplete
    """

    def __init__(self):
        self._commands: Dict[str, Command] = {}
        self._alias_map: Dict[str, str] = {}  # alias → canonical name
        self._initialized = False

    def register(self, command: Command):
        """Register a single command.

        Overwrites existing command with same name (later registration wins,
        like Claude Code's skill priority over builtin).
        """
        self._commands[command.name] = command
        for alias in command.aliases:
            self._alias_map[alias] = command.name

    def register_many(self, commands: List[Command]):
        """Register multiple commands at once."""
        for cmd in commands:
            self.register(cmd)

    def unregister(self, name: str):
        """Remove a command by name."""
        if name in self._commands:
            cmd = self._commands[name]
            for alias in cmd.aliases:
                self._alias_map.pop(alias, None)
            del self._commands[name]

    def find(self, name: str) -> Optional[Command]:
        """Find a command by name or alias.

        Like Claude Code's findCommand().
        """
        # Direct match
        if name in self._commands:
            return self._commands[name]
        # Alias match
        canonical = self._alias_map.get(name)
        if canonical and canonical in self._commands:
            return self._commands[canonical]
        return None

    def get_available(self, mode: str = "chat") -> List[Command]:
        """Get all commands available in the given mode.

        Filters by:
        1. Mode availability
        2. Feature gates
        3. is_enabled() checks
        4. Not hidden
        """
        available = []
        for cmd in self._commands.values():
            if not cmd.available_in_mode(mode):
                continue
            if not cmd.check_enabled():
                continue
            available.append(cmd)

        return sorted(available, key=lambda c: (c.priority, c.name))

    def get_visible(self, mode: str = "chat") -> List[Command]:
        """Get visible commands for autocomplete/help."""
        return [c for c in self.get_available(mode) if not c.is_hidden]

    def fuzzy_search(self, query: str, mode: str = "chat", limit: int = 10) -> List[Command]:
        """Fuzzy search commands for autocomplete.

        Like Claude Code's typeahead matching.
        """
        query = query.lower()
        available = self.get_visible(mode)

        # Score each command
        scored = []
        for cmd in available:
            score = 0
            name = cmd.name.lower()

            if name == query:
                score = 100  # Exact match
            elif name.startswith(query):
                score = 80  # Prefix match
            elif query in name:
                score = 60  # Substring match
            else:
                # Check aliases
                for alias in cmd.aliases:
                    if alias.lower().startswith(query):
                        score = 70
                        break
                    elif query in alias.lower():
                        score = 50
                        break
                # Check description
                if score == 0 and query in cmd.description.lower():
                    score = 30

            if score > 0:
                scored.append((score, cmd))

        scored.sort(key=lambda x: (-x[0], x[1].name))
        return [cmd for _, cmd in scored[:limit]]

    @property
    def count(self) -> int:
        return len(self._commands)


# ─────────────────────────────────────────────────────────────────────
# Command Dispatcher — mirrors processSlashCommand.tsx
# ─────────────────────────────────────────────────────────────────────

class CommandDispatcher:
    """Execute slash commands with proper routing.

    Like Claude Code's processSlashCommand(), handles:
    - Finding the command in registry
    - Permission checks
    - Routing to prompt/local/ui handler
    - Result processing
    """

    def __init__(self, registry: CommandRegistry, context: Optional[Dict[str, Any]] = None):
        self.registry = registry
        self.context = context or {}

    async def dispatch(
        self,
        input_text: str,
        mode: str = "chat",
        agent=None,
    ) -> Optional[CommandResult]:
        """Parse and execute a slash command.

        Args:
            input_text: Raw user input (e.g., "/help", "/search AI news")
            mode: Current personality mode
            agent: NeoMindAgent instance for context

        Returns:
            CommandResult or None if not a slash command
        """
        parsed = SlashCommandParser.parse(input_text)
        if not parsed:
            return None

        cmd = self.registry.find(parsed.name)
        if not cmd:
            # Try fuzzy match for suggestions
            suggestions = self.registry.fuzzy_search(parsed.name, mode, limit=3)
            if suggestions:
                names = ", ".join(f"/{s.name}" for s in suggestions)
                return CommandResult(
                    text=f"Unknown command '/{parsed.name}'. Did you mean: {names}?",
                    display="system",
                )
            return CommandResult(
                text=f"Unknown command '/{parsed.name}'. Type /help for available commands.",
                display="system",
            )

        # Check mode availability
        if not cmd.available_in_mode(mode):
            return CommandResult(
                text=f"/{cmd.name} is not available in {mode} mode.",
                display="system",
            )

        # Check enabled
        if not cmd.check_enabled():
            gate = cmd.feature_gate or "unknown"
            return CommandResult(
                text=f"/{cmd.name} is currently disabled (feature: {gate}).",
                display="system",
            )

        # Lazy load if needed
        if cmd.handler is None and cmd.module_path:
            await cmd.load()

        if cmd.handler is None:
            return CommandResult(
                text=f"/{cmd.name} has no handler configured.",
                display="system",
            )

        # Execute based on type
        try:
            if cmd.type == CommandType.PROMPT:
                return await self._execute_prompt_command(cmd, parsed.args, agent)
            elif cmd.type == CommandType.LOCAL:
                return await self._execute_local_command(cmd, parsed.args, agent)
            elif cmd.type == CommandType.LOCAL_UI:
                return await self._execute_ui_command(cmd, parsed.args, agent)
        except Exception as e:
            logger.error(f"Command /{cmd.name} failed: {e}", exc_info=True)
            return CommandResult(
                text=f"Error executing /{cmd.name}: {e}",
                display="system",
            )

    async def _execute_prompt_command(
        self, cmd: Command, args: str, agent=None
    ) -> CommandResult:
        """Execute a prompt command — expand skill text, send to LLM.

        Like Claude Code's PromptCommand: getPromptForCommand() → content blocks.
        """
        handler = cmd.handler
        if asyncio.iscoroutinefunction(handler):
            prompt_text = await handler(args, agent=agent, context=self.context)
        else:
            prompt_text = handler(args, agent=agent, context=self.context)

        return CommandResult(
            text=prompt_text if isinstance(prompt_text, str) else str(prompt_text),
            should_query=True,  # Send expanded text to LLM
            display="skip",     # Don't show expanded text to user
        )

    async def _execute_local_command(
        self, cmd: Command, args: str, agent=None
    ) -> CommandResult:
        """Execute a local command — returns text result directly."""
        handler = cmd.handler
        if asyncio.iscoroutinefunction(handler):
            result = await handler(args, agent=agent, context=self.context)
        else:
            result = handler(args, agent=agent, context=self.context)

        if isinstance(result, CommandResult):
            return result
        elif isinstance(result, str):
            return CommandResult(text=result)
        elif result is None:
            return CommandResult(text="", display="skip")
        else:
            return CommandResult(text=str(result))

    async def _execute_ui_command(
        self, cmd: Command, args: str, agent=None
    ) -> CommandResult:
        """Execute a UI command — renders interactive element.

        In Python/prompt_toolkit, this maps to interactive dialogs
        rather than React JSX components.
        """
        # Same execution as local, but frontends may render differently
        return await self._execute_local_command(cmd, args, agent)


# ─────────────────────────────────────────────────────────────────────
# Built-in Commands — declarative registration
# ─────────────────────────────────────────────────────────────────────

def _build_builtin_commands() -> List[Command]:
    """Build the complete list of built-in commands.

    Mirrors Claude Code's COMMANDS() function.
    Each command is a declarative object with lazy-loaded handler.
    """

    # ── Shared commands (all modes) ────────────────────────────────

    def _cmd_help(args: str, agent=None, **kw) -> CommandResult:
        """Show available commands, or detailed help for a specific command."""
        from agent_config import agent_config
        mode = agent_config.mode if not agent else agent.mode
        registry = kw.get("context", {}).get("registry")

        # Per-command help: /help <command>
        target = args.strip().lstrip("/")
        if target and registry:
            cmd = registry.find(target)
            if cmd:
                lines = [f"/{cmd.name}"]
                if cmd.argument_hint:
                    lines[0] += f" {cmd.argument_hint}"
                lines.append(f"  {cmd.description}")
                lines.append(f"  Type: {cmd.type.value}")
                if cmd.aliases:
                    lines.append(f"  Aliases: {', '.join('/' + a for a in cmd.aliases)}")
                lines.append(f"  Modes: {', '.join(cmd.modes)}")
                # Try to get detailed help from HelpSystem
                if agent and hasattr(agent, 'help_system') and agent.help_system:
                    detailed = agent.help_system.help_texts.get(target)
                    if detailed:
                        lines.append(f"\n{detailed}")
                return CommandResult(text="\n".join(lines))
            else:
                return CommandResult(text=f"No help found for '/{target}'. Type /help for the full list.")

        if registry:
            cmds = registry.get_visible(mode)
            lines = [f"  /{c.name:<20} {c.description}" for c in cmds]
            text = f"Available commands ({mode} mode):\n\n" + "\n".join(lines)
            text += "\n\nTip: /help <command> for detailed help on a specific command."
        else:
            text = "Type /help to see available commands."
        return CommandResult(text=text)

    def _cmd_clear(args: str, agent=None, **kw) -> CommandResult:
        """Clear conversation history."""
        if agent:
            agent.conversation_history.clear()
            if agent_config := kw.get("context", {}).get("config"):
                if agent_config.system_prompt:
                    agent.add_to_history("system", agent_config.system_prompt)
        return CommandResult(text="Conversation cleared.", compact=True)

    def _cmd_compact(args: str, agent=None, **kw) -> CommandResult:
        """Compact conversation to save context."""
        return CommandResult(
            text="Compacting conversation context...",
            compact=True,
        )

    def _cmd_context(args: str, agent=None, **kw) -> CommandResult:
        """Show context window usage with per-section token accounting."""
        lines = ["Context Window Usage:\n"]

        # Basic message stats
        if agent and hasattr(agent, 'conversation_history'):
            history = agent.conversation_history
            total_chars = sum(len(str(m.get('content', ''))) for m in history)
            est_tokens = total_chars // 4
            user_msgs = sum(1 for m in history if m.get('role') == 'user')
            asst_msgs = sum(1 for m in history if m.get('role') == 'assistant')
            tool_msgs = sum(1 for m in history if m.get('role') == 'tool')

            lines.append(f"  Messages: {len(history)} (user: {user_msgs}, assistant: {asst_msgs}, tool: {tool_msgs})")
            lines.append(f"  Estimated tokens: ~{est_tokens:,}")
            lines.append(f"  Total characters: {total_chars:,}")

            # Context capacity bar
            max_ctx = 128000  # Default context window
            usage_pct = min(100, est_tokens * 100 // max_ctx)
            bar_len = 40
            filled = usage_pct * bar_len // 100
            bar = '█' * filled + '░' * (bar_len - filled)
            lines.append(f"\n  [{bar}] {usage_pct}% of {max_ctx:,} tokens")

        # Per-section accounting from PromptComposer
        if agent and hasattr(agent, 'services') and agent.services:
            try:
                composer = agent.services.prompt_composer
                if composer:
                    lines.append(f"\n{composer.format_token_accounting()}")
            except Exception:
                pass

        # Token budget status
        try:
            from agent.agentic.token_budget import TokenBudget
            if agent and hasattr(agent, 'services'):
                # Try to access token budget
                lines.append(f"\n  Token budget: available")
        except Exception:
            pass

        if len(lines) <= 1:
            return CommandResult(text="Context info not available.")
        return CommandResult(text="\n".join(lines))

    def _cmd_exit(args: str, agent=None, **kw) -> CommandResult:
        """Exit the agent."""
        return CommandResult(text="__EXIT__", display="skip")

    def _cmd_mode(args: str, agent=None, **kw) -> CommandResult:
        """Switch personality mode."""
        target = args.strip().lower()
        valid_modes = {"chat", "coding", "fin"}
        if target not in valid_modes:
            return CommandResult(
                text=f"Usage: /mode <{' | '.join(valid_modes)}>",
            )
        return CommandResult(
            text=f"__MODE_SWITCH__{target}",
            display="skip",
        )

    def _cmd_model(args: str, agent=None, **kw) -> CommandResult:
        """Switch or show current model. With no args, lists available
        models — pulled live from the LLM-Router (/v1/models) when
        healthy, or expanded across direct-vendor fallbacks when not.
        """
        if args.strip():
            new_model = args.strip()
            if agent:
                agent.model = new_model
            return CommandResult(text=f"Model switched to: {new_model}")

        current = agent.model if agent else "unknown"

        try:
            from agent.services.llm_provider import PROVIDERS, check_primary_healthy
        except Exception:
            return CommandResult(text=f"Current model: {current}")

        import os as _os
        try:
            import requests as _rq  # type: ignore
        except Exception:
            _rq = None  # type: ignore

        def _live_models(pconf):
            static = pconf.get("fallback_models", [])
            url = pconf.get("models_url")
            if not url or _rq is None:
                return static
            try:
                ek = pconf.get("env_key", "")
                hdrs = {}
                if ek:
                    tok = _os.getenv(ek, "")
                    if tok:
                        hdrs["Authorization"] = f"Bearer {tok}"
                r = _rq.get(url, headers=hdrs, timeout=3)
                if r.ok:
                    d = r.json()
                    live = d.get("data") if isinstance(d, dict) else d
                    if live:
                        return live
            except Exception:
                pass
            return static

        primary_ok = check_primary_healthy(timeout=2.0)
        lines = [f"Current model: {current}", ""]

        if primary_ok:
            for pname, pconf in PROVIDERS.items():
                if pconf.get("role") != "primary":
                    continue
                # Don't gate on api_key env here — check_primary_healthy
                # already confirmed the router is reachable. Model list
                # is canonical from the router regardless of how the
                # user's current chain is wired (direct vs via router).
                models = _live_models(pconf)
                if not models:
                    continue
                lines.append("router (all traffic proxied here):")
                for m in models:
                    mid = m["id"]
                    owned = m.get("owned_by", "")
                    tail = "  ← current" if mid == current else ""
                    lines.append(f"  {mid}  ({owned}){tail}")
            lines.append(
                "\nCloud + local MLX all go through LLM-Router. "
                "Direct vendor fallback kicks in if router 5xx."
            )
        else:
            lines.append("⚠ LLM-Router unreachable — direct vendor fallbacks:")
            for pname, pconf in PROVIDERS.items():
                if pconf.get("role") == "primary":
                    continue
                api_key = _os.getenv(pconf.get("env_key", ""), "")
                if not api_key:
                    continue
                models = _live_models(pconf)
                if not models:
                    continue
                lines.append(f"\n{pname} (direct):")
                for m in models:
                    mid = m["id"]
                    tail = "  ← current" if mid == current else ""
                    lines.append(f"  {mid}{tail}")

        lines.append("\nSwitch: /model <id>")
        return CommandResult(text="\n".join(lines))

    def _cmd_think(args: str, agent=None, **kw) -> CommandResult:
        """Toggle or set thinking mode. /think [on|off]"""
        if agent:
            arg_lower = args.strip().lower()
            if arg_lower in ("on", "1", "true", "yes"):
                agent.thinking_enabled = True
            elif arg_lower in ("off", "0", "false", "no"):
                agent.thinking_enabled = False
            else:
                agent.thinking_enabled = not agent.thinking_enabled
            status = "ON" if agent.thinking_enabled else "OFF"
            return CommandResult(text=f"Thinking mode: {status}")
        return CommandResult(text="Agent not available.")

    def _cmd_cost(args: str, agent=None, **kw) -> CommandResult:
        """Show session cost."""
        engine = kw.get("context", {}).get("query_engine")
        if engine:
            summary = engine.budget.get_summary()
            text = (
                f"Session cost: ${summary['total_cost_usd']:.4f}\n"
                f"This turn: ${summary['turn_cost_usd']:.4f}\n"
                f"Tokens: {summary['total_input']} in / {summary['total_output']} out\n"
                f"Context usage: {summary['usage_ratio']:.0%}"
            )
            return CommandResult(text=text)
        return CommandResult(text="Cost tracking not available.")

    def _cmd_config(args: str, agent=None, **kw) -> CommandResult:
        """View or change runtime config."""
        from agent_config import agent_config
        # shlex-aware so quoted values keep their internal spaces.
        parts = split_args(args, maxsplit=2)
        if not parts:
            # Show current config summary
            return CommandResult(text=f"Mode: {agent_config.mode}\nModel: {agent_config.model}")
        if parts[0] == "show":
            lines = [
                "Current Configuration",
                "=" * 40,
                f"  mode:         {agent_config.mode}",
                f"  model:        {agent_config.model}",
                f"  temperature:  {agent_config.temperature}",
                f"  max_tokens:   {agent_config.max_tokens}",
                f"  stream:       {agent_config.stream}",
                f"  debug:        {agent_config.debug}",
                f"  thinking:     {agent_config.thinking_enabled}",
                f"  timeout:      {agent_config.timeout}",
                f"  max_retries:  {agent_config.max_retries}",
            ]
            return CommandResult(text="\n".join(lines))
        if parts[0] == "set" and len(parts) >= 3:
            key, value = parts[1], parts[2]
            # If the value looks like JSON (list/object/bool/number/null),
            # try parsing it so /config set arr [1,2,3] stores a real list
            # instead of the literal string "[1,2,3]".
            parsed_value: Any = value
            stripped = value.strip()
            if stripped and (
                stripped[0] in '[{'
                or stripped in ('true', 'false', 'null')
            ):
                try:
                    parsed_value = json.loads(stripped)
                except (ValueError, TypeError):
                    parsed_value = value
            agent_config.set_runtime(key, parsed_value)
            return CommandResult(text=f"Config set: {key} = {parsed_value}")
        if parts[0] == "get" and len(parts) >= 2:
            key = parts[1]
            val = agent_config.get(key, "not set")
            return CommandResult(text=f"{key} = {val}")
        return CommandResult(text="Usage: /config [show | set <key> <value> | get <key>]")

    def _cmd_memory(args: str, agent=None, **kw) -> CommandResult:
        """Manage memory."""
        if not args.strip():
            return CommandResult(text="Usage: /memory [show | clear | search <query>]")
        action = args.strip().split(None, 1)
        if action[0] == "show":
            if agent and hasattr(agent, "_shared_memory") and agent._shared_memory:
                summary = agent._shared_memory.get_context_summary(
                    mode=agent.mode, max_tokens=1000
                )
                return CommandResult(text=summary or "No memories stored.")
            return CommandResult(text="Memory system not available.")
        return CommandResult(text=f"Memory action '{action[0]}' not yet implemented.")

    def _cmd_stats(args: str, agent=None, **kw) -> CommandResult:
        """Show session statistics."""
        # Try query engine first
        engine = kw.get("context", {}).get("query_engine")
        if engine:
            state = engine.get_state()
            # If query engine has real data, use it
            if state.get('turn_count', 0) > 0 or state.get('message_count', 0) > 0:
                text = (
                    f"Turns: {state['turn_count']}\n"
                    f"Messages: {state['message_count']}\n"
                    f"Compactions: {state['compact_count']}\n"
                    f"Budget: {state['budget']['usage_ratio']:.0%}"
                )
                return CommandResult(text=text)

        # Fallback: compute stats from agent's conversation_history
        if agent and hasattr(agent, 'conversation_history'):
            history = agent.conversation_history
            total_msgs = len(history)
            user_msgs = sum(1 for m in history if m.get('role') == 'user')
            asst_msgs = sum(1 for m in history if m.get('role') == 'assistant')
            tool_msgs = sum(1 for m in history if m.get('role') in ('tool', 'function'))
            total_chars = sum(len(str(m.get('content', ''))) for m in history)
            est_tokens = total_chars // 4
            text = (
                f"Turns: {user_msgs}\n"
                f"Messages: {total_msgs} (user: {user_msgs}, assistant: {asst_msgs}, tool: {tool_msgs})\n"
                f"Estimated tokens: ~{est_tokens:,}"
            )
            return CommandResult(text=text)
        return CommandResult(text="Stats not available.")

    def _cmd_debug(args: str, agent=None, **kw) -> CommandResult:
        """Toggle debug mode."""
        from agent_config import agent_config
        current = agent_config.get("debug", False)
        agent_config.set_runtime("debug", not current)
        status = "ON" if not current else "OFF"
        return CommandResult(text=f"Debug mode: {status}")

    def _cmd_careful(args: str, agent=None, **kw) -> CommandResult:
        """Toggle careful/safety guard mode.

        When enabled, dangerous commands (rm -rf, git push --force, etc.)
        will be flagged and require confirmation before execution.
        """
        from agent.workflow.guards import get_guard
        guard = get_guard()
        if guard.state.careful_enabled:
            guard.disable_careful()
            return CommandResult(text="Careful mode: OFF\nDangerous command warnings disabled.")
        else:
            guard.enable_careful()
            return CommandResult(text="Careful mode: ON\nDangerous commands will be flagged for confirmation.")

    def _cmd_history(args: str, agent=None, **kw) -> CommandResult:
        """Show conversation history summary."""
        if agent:
            count = len(agent.conversation_history)
            return CommandResult(text=f"Conversation has {count} messages.")
        return CommandResult(text="No history available.")

    def _cmd_save(args: str, agent=None, **kw) -> CommandResult:
        """Save/export conversation to file. Format auto-detected from extension.

        Supports: .md (markdown), .json, .html, .txt
        """
        # Strip shell-style quoting so paths with spaces work:
        #   /save "/tmp/file with spaces.md"  →  /tmp/file with spaces.md
        tokens = split_args(args, maxsplit=0)
        filename = tokens[0] if tokens else args.strip()
        if not filename:
            return CommandResult(text="Usage: /save <filename.md|.json|.html>")
        if not agent or not hasattr(agent, 'conversation_history'):
            return CommandResult(text="No conversation to save.")

        try:
            from agent.services.export_service import export_conversation, detect_format
            fmt = detect_format(filename)
            content = export_conversation(agent.conversation_history, fmt=fmt)
            filepath = os.path.abspath(filename)
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            return CommandResult(text=f"✓ Saved as {fmt}: {filepath} ({len(content):,} chars)")
        except Exception as e:
            return CommandResult(text=f"Save failed: {e}")

    def _cmd_skills(args: str, agent=None, **kw) -> CommandResult:
        """List available skills."""
        if agent and hasattr(agent, "_skill_loader") and agent._skill_loader:
            try:
                skills = agent._skill_loader.list_skills()
                if skills:
                    lines = [f"  {s['name']}: {s.get('description', '')}" for s in skills]
                    return CommandResult(text="Available skills:\n" + "\n".join(lines))
            except Exception:
                pass
        return CommandResult(text="No skills loaded.")

    def _cmd_permissions(args: str, agent=None, **kw) -> CommandResult:
        """Show/manage permissions. Accepts: normal | auto | auto_accept | plan.

        With no args → show current mode.
        With a recognized arg → actually switch mode via the same setter
        the legacy cli/neomind_interface.py handler uses, so `/permissions
        auto` in coding mode actually turns off the interactive gate.
        """
        from agent_config import agent_config
        if args:
            arg = args.strip().lower()
            mode_map = {
                "auto": "auto_accept", "auto_accept": "auto_accept",
                "normal": "normal", "plan": "plan",
            }
            if arg in mode_map:
                new_mode = mode_map[arg]
                try:
                    agent_config.permission_mode = new_mode
                except Exception as e:
                    return CommandResult(text=f"Failed to set mode: {e}")
                return CommandResult(
                    text=f"Permission mode: {new_mode}"
                )
            return CommandResult(
                text=f"Usage: /permissions [normal|auto|plan]"
            )
        mode = getattr(agent_config, "permission_mode", None) or \
               agent_config.get("permissions.mode", "normal")
        return CommandResult(text=f"Permission mode: {mode}")

    def _cmd_version(args: str, agent=None, **kw) -> CommandResult:
        """Show version."""
        from agent_config import agent_config
        ver = agent_config.get("identity.version", "unknown")
        return CommandResult(text=f"NeoMind v{ver}")

    # ── Coding-specific commands ──────────────────────────────────

    def _cmd_plan(args: str, agent=None, **kw) -> str:
        """Enter plan mode (prompt command → sent to LLM)."""
        return (
            "You are now in PLAN MODE. Analyze the request carefully and create "
            "a detailed implementation plan. List specific files to create/modify, "
            "the order of changes, and potential risks. Do NOT execute any tools "
            "until the user approves the plan.\n\n"
            f"Request to plan: {args}" if args else
            "Enter plan mode. Ask the user what they want to plan."
        )

    def _cmd_review(args: str, agent=None, **kw) -> str:
        """Code review (prompt command)."""
        return (
            "Review the code changes in the current context. Focus on:\n"
            "1. Correctness and potential bugs\n"
            "2. Performance issues\n"
            "3. Security vulnerabilities\n"
            "4. Code style and readability\n"
            "5. Test coverage gaps\n\n"
            f"{'Files to review: ' + args if args else 'Review all recent changes.'}"
        )

    def _cmd_diff(args: str, agent=None, **kw) -> CommandResult:
        """Show git diff."""
        import subprocess
        try:
            result = subprocess.run(
                ["git", "diff", "--stat"] + (args.split() if args else []),
                capture_output=True, text=True, timeout=10,
            )
            return CommandResult(text=result.stdout or "No changes.")
        except Exception as e:
            return CommandResult(text=f"Error: {e}")

    def _cmd_git(args: str, agent=None, **kw) -> CommandResult:
        """Run git command."""
        if not args.strip():
            return CommandResult(text="Usage: /git <command>")
        import subprocess
        try:
            result = subprocess.run(
                ["git"] + args.split(),
                capture_output=True, text=True, timeout=30,
            )
            output = result.stdout + result.stderr
            return CommandResult(text=output.strip() or "Done.")
        except Exception as e:
            return CommandResult(text=f"Error: {e}")

    def _cmd_worktree(args: str, agent=None, **kw) -> CommandResult:
        """Manage git worktrees."""
        import subprocess
        if not args.strip():
            # List worktrees
            try:
                result = subprocess.run(['git', 'worktree', 'list'], capture_output=True, text=True, timeout=10)
                return CommandResult(text=result.stdout or "No worktrees.")
            except Exception as e:
                return CommandResult(text=f"Error: {e}")
        parts = args.strip().split()
        if parts[0] == 'add':
            # git worktree add <path> [branch]
            cmd = ['git', 'worktree', 'add'] + parts[1:]
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                return CommandResult(text=result.stdout + result.stderr)
            except Exception as e:
                return CommandResult(text=f"Error: {e}")
        if parts[0] == 'remove':
            cmd = ['git', 'worktree', 'remove'] + parts[1:]
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                return CommandResult(text=result.stdout + result.stderr)
            except Exception as e:
                return CommandResult(text=f"Error: {e}")
        return CommandResult(text="Usage: /worktree [list|add <path>|remove <path>]")

    def _cmd_stash(args: str, agent=None, **kw) -> CommandResult:
        """Manage git stash."""
        import subprocess
        try:
            cmd = ['git', 'stash'] + (args.split() if args.strip() else ['list'])
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            return CommandResult(text=result.stdout + result.stderr or "Stash is empty.")
        except Exception as e:
            return CommandResult(text=f"Error: {e}")

    def _cmd_test(args: str, agent=None, **kw) -> str:
        """Run tests (prompt command)."""
        return (
            f"Run the test suite{' for ' + args if args else ''}. "
            "Execute the tests, report results, and fix any failures."
        )

    def _cmd_security_review(args: str, agent=None, **kw) -> str:
        """Security review (prompt command)."""
        return (
            "Perform a security audit of the codebase. Check for:\n"
            "1. Hardcoded secrets, API keys, credentials\n"
            "2. SQL injection, XSS, command injection vulnerabilities\n"
            "3. Insecure dependencies (known CVEs)\n"
            "4. Authentication/authorization issues\n"
            "5. Data exposure risks\n"
            "6. Path traversal vulnerabilities\n\n"
            f"{'Scope: ' + args if args else 'Review the entire project.'}"
        )

    # ── Finance-specific commands ─────────────────────────────────

    def _cmd_stock(args: str, agent=None, **kw) -> str:
        """Stock analysis (prompt command)."""
        return (
            f"Analyze the stock: {args}\n"
            "Provide: current price, key metrics (PE, EPS, market cap), "
            "recent news, technical indicators, and your assessment with "
            "confidence level. Search for real-time data."
        )

    def _cmd_portfolio(args: str, agent=None, **kw) -> str:
        """Portfolio analysis (prompt command)."""
        return (
            "Show my portfolio holdings, current allocation, total value, "
            "and today's P&L. Suggest rebalancing if needed."
        )

    def _cmd_market(args: str, agent=None, **kw) -> str:
        """Market overview (prompt command)."""
        region = args.strip() or "US"
        return (
            f"Provide a market overview for {region}. Include:\n"
            "- Major indices performance\n"
            "- Sector rotation highlights\n"
            "- Key economic data released today\n"
            "- Market sentiment indicators\n"
            "Search for current data."
        )

    def _cmd_news(args: str, agent=None, **kw) -> str:
        """Finance news digest (prompt command)."""
        topic = args.strip() or "markets"
        return (
            f"Compile a finance news digest about '{topic}'. For each item:\n"
            "- Impact score (1-10) × probability (0-1)\n"
            "- Affected sectors/stocks\n"
            "- Short/medium/long term assessment\n"
            "Search for the latest news."
        )

    def _cmd_quant(args: str, agent=None, **kw) -> str:
        """Quantitative computation (prompt command)."""
        return (
            f"Perform quantitative computation: {args}\n"
            "Show all work with formulas. Use Python for complex calculations. "
            "Never mental-math large numbers."
        )

    # ── Chat-specific commands (prompt commands) ──────────────────

    def _cmd_deep(args: str, agent=None, **kw) -> str:
        """Deep dive into a topic with structured analysis."""
        return (
            f"Deep dive: {args}\n"
            "Provide a thorough, structured analysis. Cover key concepts, "
            "nuances, open questions, and practical implications. "
            "Use clear sections and examples."
        ) if args else "What topic would you like to explore in depth?"

    def _cmd_compare(args: str, agent=None, **kw) -> str:
        """Compare items side by side."""
        return (
            f"Compare: {args}\n"
            "Create a structured comparison covering pros/cons, key differences, "
            "use cases, and a recommendation."
        ) if args else "What would you like to compare? (e.g., /compare Python vs Go)"

    def _cmd_draft(args: str, agent=None, **kw) -> str:
        """Draft content (email, article, message, etc.)."""
        return (
            f"Draft: {args}\n"
            "Create a polished draft. Match the appropriate tone and format."
        ) if args else "What would you like me to draft? (e.g., /draft email to manager about deadline)"

    def _cmd_brainstorm(args: str, agent=None, **kw) -> str:
        """Brainstorm ideas on a topic."""
        return (
            f"Brainstorm: {args}\n"
            "Generate diverse, creative ideas. Include unconventional approaches. "
            "Group by theme and rate feasibility."
        ) if args else "What topic should we brainstorm about?"

    def _cmd_tldr(args: str, agent=None, **kw) -> str:
        """Summarize content concisely."""
        return (
            f"TL;DR: {args}\n"
            "Provide a concise summary in 3-5 bullet points. "
            "Focus on the most important takeaways."
        ) if args else "What would you like summarized?"

    def _cmd_explore(args: str, agent=None, **kw) -> str:
        """Explore a question from multiple angles."""
        return (
            f"Explore: {args}\n"
            "Examine this from multiple perspectives. Consider different viewpoints, "
            "evidence, and counterarguments."
        ) if args else "What question would you like to explore?"

    # ── Session management commands ──────────────────────────────

    def _cmd_checkpoint(args: str, agent=None, **kw) -> CommandResult:
        """Save a named checkpoint of the current conversation state."""
        import json, time
        label = args.strip() or f"auto_{int(time.time())}"
        if agent and hasattr(agent, 'conversation_history'):
            checkpoint_dir = os.path.join(
                os.path.expanduser('~'), '.neomind', 'checkpoints'
            )
            os.makedirs(checkpoint_dir, exist_ok=True)
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            safe_label = "".join(c if c.isalnum() or c in '-_' else '_' for c in label)
            filepath = os.path.join(checkpoint_dir, f"{timestamp}_{safe_label}.json")
            checkpoint_data = {
                'label': label,
                'timestamp': timestamp,
                'turn_count': len([m for m in agent.conversation_history if m.get('role') == 'user']),
                'history': agent.conversation_history[:],
            }
            with open(filepath, 'w') as f:
                json.dump(checkpoint_data, f)
            return CommandResult(text=f"✓ Checkpoint saved: {label} ({filepath})")
        return CommandResult(text="No conversation to checkpoint.")

    def _cmd_rewind(args: str, agent=None, **kw) -> CommandResult:
        """Rewind to a saved checkpoint or N turns back."""
        import json, glob
        arg = args.strip()
        checkpoint_dir = os.path.join(os.path.expanduser('~'), '.neomind', 'checkpoints')

        # Bug #5 fix: warn before discarding a large number of turns. Users
        # can confirm by re-issuing the command with a trailing ``--force``.
        REWIND_WARN_THRESHOLD = 10
        force_rewind = False
        if arg.endswith(' --force'):
            force_rewind = True
            arg = arg[: -len(' --force')].strip()
        elif arg == '--force':
            arg = ''

        if not arg:
            # List available checkpoints
            if not os.path.exists(checkpoint_dir):
                return CommandResult(text="No checkpoints found.")
            files = sorted(glob.glob(os.path.join(checkpoint_dir, '*.json')), reverse=True)
            if not files:
                return CommandResult(text="No checkpoints found.")
            lines = ["Available checkpoints:"]
            for f in files[:10]:
                try:
                    with open(f) as fh:
                        data = json.load(fh)
                    lines.append(f"  {data.get('label', '?')} — {data.get('timestamp', '?')} ({data.get('turn_count', '?')} turns)")
                except Exception:
                    pass
            lines.append("\nUsage: /rewind <label> or /rewind <N> (rewind N turns)")
            return CommandResult(text="\n".join(lines))

        # Validate negative numbers early
        try:
            n_check = int(arg)
            if n_check < 0:
                return CommandResult(text=f"Invalid rewind count: {arg}. Must be a positive number.")
        except ValueError:
            pass  # Not a number — try label-based rewind below

        # Try numeric rewind (N turns back)
        if arg.isdigit():
            n = int(arg)
            if agent and hasattr(agent, 'conversation_history'):
                if n <= 0:
                    return CommandResult(text="Must rewind at least 1 turn.")
                if n >= REWIND_WARN_THRESHOLD and not force_rewind:
                    return CommandResult(
                        text=(
                            f"⚠️  /rewind {n} would discard {n} turns "
                            f"(current history: {len(agent.conversation_history)} messages).\n"
                            f"This cannot be undone. Re-run as: /rewind {n} --force"
                        )
                    )
                # Remove last N user+assistant pairs
                removed = 0
                while removed < n and len(agent.conversation_history) > 1:
                    if agent.conversation_history[-1].get('role') in ('user', 'assistant'):
                        agent.conversation_history.pop()
                        if agent.conversation_history and agent.conversation_history[-1].get('role') in ('user', 'assistant'):
                            agent.conversation_history.pop()
                        removed += 1
                    else:
                        agent.conversation_history.pop()
                return CommandResult(text=f"✓ Rewound {removed} turns. History now has {len(agent.conversation_history)} messages.")
            return CommandResult(text="No conversation to rewind.")

        # Try label-based rewind.
        # PS09 fix: also search ~/.neomind/branches/ so labels saved via /branch
        # are reachable from /rewind. Checkpoints dir takes precedence, then
        # branches dir as a fallback.
        branch_dir = os.path.join(os.path.expanduser('~'), '.neomind', 'branches')
        candidate_dirs = []
        if os.path.exists(checkpoint_dir):
            candidate_dirs.append(checkpoint_dir)
        if os.path.exists(branch_dir):
            candidate_dirs.append(branch_dir)

        files = []
        for d in candidate_dirs:
            files.extend(glob.glob(os.path.join(d, f'*_{arg}*.json')))

        if candidate_dirs:
            if files:
                latest = sorted(files, reverse=True)[0]
                with open(latest) as f:
                    data = json.load(f)
                if agent and hasattr(agent, 'conversation_history'):
                    current_len = len(agent.conversation_history)
                    new_history = data.get('history', []) or []
                    discarded = current_len - len(new_history)
                    if discarded >= REWIND_WARN_THRESHOLD and not force_rewind:
                        return CommandResult(
                            text=(
                                f"⚠️  /rewind {arg} would discard {discarded} messages "
                                f"({current_len} → {len(new_history)}).\n"
                                f"Checkpoint: {data.get('label')} "
                                f"({data.get('turn_count', '?')} turns, "
                                f"{data.get('timestamp', '?')}).\n"
                                f"This cannot be undone. Re-run as: /rewind {arg} --force"
                            )
                        )
                    agent.conversation_history.clear()
                    agent.conversation_history.extend(new_history)
                    turn_count = data.get('turn_count') or data.get('parent_turns') or '?'
                    msg = f"✓ Restored checkpoint: {data.get('label')} ({turn_count} turns)"
                    if discarded > 0:
                        msg += f" — discarded {discarded} messages"
                    return CommandResult(text=msg)

        return CommandResult(text=f"Checkpoint '{arg}' not found.")

    def _cmd_flags(args: str, agent=None, **kw) -> CommandResult:
        """Show or toggle feature flags."""
        try:
            from agent.services.feature_flags import get_feature_flags
            ff = get_feature_flags()
        except ImportError:
            return CommandResult(text="Feature flags not available.")

        arg = args.strip()
        if not arg:
            # List all flags
            flags = ff.list_flags()
            lines = ["Feature Flags:"]
            for name, info in flags.items():
                status = "✓" if info['enabled'] else "✗"
                lines.append(f"  {status} {name}: {info['description']} [{info['source']}]")
            return CommandResult(text="\n".join(lines))

        # Toggle: /flags FEATURE_NAME [on|off]  OR  /flags toggle FEATURE_NAME
        parts = arg.split()
        # Handle "/flags toggle FLAGNAME" format
        if parts[0].lower() == 'toggle' and len(parts) > 1:
            flag_name = parts[1].upper()
            value = not ff.is_enabled(flag_name)
        else:
            flag_name = parts[0].upper()
            if len(parts) > 1:
                value = parts[1].lower() in ('on', 'true', '1', 'yes')
            else:
                # Toggle current value
                value = not ff.is_enabled(flag_name)

        ff.set_flag(flag_name, value, persist=True)
        status = "enabled" if value else "disabled"
        return CommandResult(text=f"✓ {flag_name} {status}")

    def _cmd_dream(args: str, agent=None, **kw) -> CommandResult:
        """Show AutoDream status or trigger consolidation."""
        try:
            from agent.services import ServiceRegistry
            # Get from agent's services if available
            services = getattr(agent, 'services', None)
            if services is None:
                services = ServiceRegistry()
            dream = services.auto_dream
            if dream is None:
                return CommandResult(text="AutoDream not available.")

            if args.strip() == 'run':
                history = getattr(agent, 'conversation_history', [])
                if history:
                    # Force run by temporarily lowering gates
                    old_interval = dream.MIN_INTERVAL_MINUTES
                    old_turns = dream.MIN_TURNS_SINCE_LAST
                    old_idle = dream.IDLE_THRESHOLD_SECONDS
                    dream.MIN_INTERVAL_MINUTES = 0
                    dream.MIN_TURNS_SINCE_LAST = 0
                    dream.IDLE_THRESHOLD_SECONDS = 0
                    triggered = dream.maybe_consolidate(history)
                    dream.MIN_INTERVAL_MINUTES = old_interval
                    dream.MIN_TURNS_SINCE_LAST = old_turns
                    dream.IDLE_THRESHOLD_SECONDS = old_idle
                    return CommandResult(text="✓ AutoDream consolidation triggered." if triggered else "AutoDream already running.")
                return CommandResult(text="No conversation history to consolidate.")

            status = dream.status
            lines = [
                "AutoDream Status:",
                f"  Running: {status['running']}",
                f"  Turns since last: {status['turns_since_last']}",
                f"  Total consolidated: {status['total_consolidated']}",
                f"  Gates open: {status['gates_open']}",
                f"  Journal entries: {status['journal_entries']}",
            ]
            return CommandResult(text="\n".join(lines))
        except Exception as e:
            return CommandResult(text=f"AutoDream error: {e}")

    # ── Session resume ────────────────────────────────────────────

    def _cmd_resume(args: str, agent=None, **kw) -> CommandResult:
        """Resume a previous saved session."""
        import json, glob
        session_dir = os.path.join(os.path.expanduser('~'), '.neomind', 'sessions')

        if not args.strip():
            # List available sessions
            if not os.path.exists(session_dir):
                return CommandResult(text="No saved sessions found.")
            files = sorted(glob.glob(os.path.join(session_dir, '*.json')), reverse=True)
            if not files:
                return CommandResult(text="No saved sessions found.")
            lines = ["Saved sessions:"]
            for f in files[:10]:
                try:
                    with open(f) as fh:
                        data = json.load(fh)
                    name = data.get('name', os.path.basename(f))
                    mode = data.get('mode', '?')
                    turns = data.get('turn_count', '?')
                    ts = data.get('timestamp', '?')
                    lines.append(f"  {name} — {mode} mode, {turns} turns ({ts})")
                except Exception:
                    pass
            lines.append("\nUsage: /resume <session_name>")
            return CommandResult(text="\n".join(lines))

        # Load specific session
        session_file = os.path.join(session_dir, f"{args.strip()}.json")
        if not os.path.exists(session_file):
            # Try fuzzy match
            matches = glob.glob(os.path.join(session_dir, f"*{args.strip()}*.json"))
            if matches:
                session_file = sorted(matches, reverse=True)[0]
            else:
                return CommandResult(text=f"Session '{args.strip()}' not found.")

        try:
            with open(session_file) as f:
                data = json.load(f)
            if agent and hasattr(agent, 'conversation_history'):
                # Cross-project validation
                saved_cwd = data.get('cwd', '')
                current_cwd = os.getcwd()
                warnings = []
                if saved_cwd and saved_cwd != current_cwd:
                    warnings.append(f"⚠ Session was in {saved_cwd}, you're now in {current_cwd}")

                # Restore conversation history
                agent.conversation_history.clear()
                agent.conversation_history.extend(data.get('history', []))

                # Restore file read state (for read-before-edit enforcement)
                if hasattr(agent, '_files_read') or hasattr(agent, 'tools'):
                    files_read = data.get('files_read', [])
                    tools = getattr(agent, 'tools', None)
                    if tools and hasattr(tools, '_files_read'):
                        tools._files_read = set(files_read)
                    elif hasattr(agent, '_files_read'):
                        agent._files_read = set(files_read)

                # Restore personality mode
                saved_mode = data.get('mode', '')
                if saved_mode and hasattr(agent, 'mode') and agent.mode != saved_mode:
                    try:
                        from agent_config import agent_config
                        agent_config.switch_mode(saved_mode)
                        warnings.append(f"Mode switched to {saved_mode}")
                    except Exception:
                        pass

                # Restore session notes if available
                notes_path = os.path.join(
                    os.path.expanduser('~'), '.neomind', 'session_notes',
                    f"{data.get('name', '')}.md"
                )
                if os.path.exists(notes_path):
                    if hasattr(agent, 'services') and agent.services:
                        notes_svc = agent.services.session_notes
                        if notes_svc:
                            notes_svc._session_id = data.get('name', '')
                            try:
                                with open(notes_path) as nf:
                                    notes_svc._content = nf.read()
                                    notes_svc._initialized = True
                            except Exception:
                                pass

                # Show preview (last 3 messages)
                preview_lines = []
                for msg in data.get('history', [])[-3:]:
                    role = msg.get('role', '?')
                    content = str(msg.get('content', ''))[:100]
                    preview_lines.append(f"  [{role}] {content}...")

                result_lines = [
                    f"✓ Resumed session: {data.get('name', '?')} ({data.get('turn_count', '?')} turns)",
                ]
                if warnings:
                    result_lines.extend(warnings)
                if preview_lines:
                    result_lines.append("Last messages:")
                    result_lines.extend(preview_lines)

                return CommandResult(text="\n".join(result_lines))
        except Exception as e:
            return CommandResult(text=f"Failed to resume: {e}")
        return CommandResult(text="No agent available to resume into.")

    def _cmd_branch(args: str, agent=None, **kw) -> CommandResult:
        """Branch the conversation — save current state and continue from a copy."""
        import json
        label = args.strip() or f"branch_{int(time.time())}"
        if agent and hasattr(agent, 'conversation_history'):
            branch_dir = os.path.join(os.path.expanduser('~'), '.neomind', 'branches')
            os.makedirs(branch_dir, exist_ok=True)
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            safe_label = "".join(c if c.isalnum() or c in '-_' else '_' for c in label)
            filepath = os.path.join(branch_dir, f"{timestamp}_{safe_label}.json")
            branch_data = {
                'label': label,
                'timestamp': timestamp,
                'parent_turns': len([m for m in agent.conversation_history if m.get('role') == 'user']),
                'history': agent.conversation_history[:],
            }
            with open(filepath, 'w') as f:
                json.dump(branch_data, f)
            return CommandResult(text=f"✓ Branched at '{label}'. Current conversation continues. Use /rewind {safe_label} to switch.")
        return CommandResult(text="No conversation to branch.")

    def _cmd_snip(args: str, agent=None, **kw) -> CommandResult:
        """Save a snippet from the last N messages or with a label."""
        import json
        arg = args.strip()
        if not agent or not hasattr(agent, 'conversation_history'):
            return CommandResult(text="No conversation to snip from.")

        history = agent.conversation_history
        if not history:
            return CommandResult(text="Empty conversation.")

        # Extract last N messages or last exchange
        n = 4  # default: last 2 exchanges
        if arg.isdigit():
            n = int(arg)
            label = f"snip_{int(time.time())}"
        else:
            label = arg or f"snip_{int(time.time())}"

        recent = history[-n:]
        content_parts = []
        for msg in recent:
            role = msg.get('role', '?')
            content = msg.get('content', '')
            if isinstance(content, list):
                content = ' '.join(
                    b.get('text', '') for b in content
                    if isinstance(b, dict) and b.get('type') == 'text'
                )
            content_parts.append(f"**{role}**: {content[:500]}")

        snip_content = "\n\n".join(content_parts)
        snip_dir = os.path.join(os.getcwd(), '.neomind_snips')
        os.makedirs(snip_dir, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        safe = "".join(c if c.isalnum() or c in '-_' else '_' for c in label)[:50]
        filepath = os.path.join(snip_dir, f"{timestamp}_{safe}.md")
        with open(filepath, 'w') as f:
            f.write(f"---\nlabel: {label}\ntimestamp: {timestamp}\nmessages: {n}\n---\n\n{snip_content}\n")
        return CommandResult(text=f"✓ Snip saved: {os.path.basename(filepath)} ({n} messages)")

    def _cmd_brief(args: str, agent=None, **kw) -> CommandResult:
        """Toggle brief output mode."""
        if agent:
            current = getattr(agent, '_brief_mode', False)
            new_val = not current
            if args.strip().lower() in ('on', 'true', '1'):
                new_val = True
            elif args.strip().lower() in ('off', 'false', '0'):
                new_val = False
            agent._brief_mode = new_val
            return CommandResult(text=f"Brief mode {'enabled' if new_val else 'disabled'}.")
        return CommandResult(text="No agent available.")

    # ── Project onboarding & git workflow ───────────────────────────

    def _cmd_init(args: str, agent=None, **kw) -> str:
        """Initialize project configuration (prompt command — agent scans workspace)."""
        return (
            "Scan this workspace and create a project configuration file at .neomind/project.md. "
            "Detect: languages, frameworks, build/test/lint commands, project structure (monorepo?), "
            "package managers, required env vars, code style configs. "
            "If a .neomind/ directory already exists, update it. "
            "Ask me about anything you can't auto-detect. "
            "Keep the output minimal and actionable — no boilerplate."
        )

    def _cmd_ship(args: str, agent=None, **kw) -> str:
        """Full git workflow: branch → commit → push → PR (prompt command)."""
        return (
            "Execute the full shipping workflow for the current changes:\n"
            "1. Check git status and diff to understand all changes\n"
            "2. Create a feature branch if not already on one (never commit to main/master)\n"
            "3. Stage relevant files (exclude .env, credentials, large binaries)\n"
            "4. Create a commit with a conventional message based on the diff\n"
            "5. Push to remote with -u flag\n"
            "6. Create a PR with a clear title (<70 chars) and detailed body\n"
            "7. Report the PR URL\n\n"
            "Safety: never force-push, never amend, never skip hooks.\n"
            f"{('Scope: ' + args) if args.strip() else 'Ship all staged/unstaged changes.'}"
        )

    def _cmd_btw(args: str, agent=None, **kw) -> CommandResult:
        """Ask a quick side question without affecting main conversation."""
        if not args.strip():
            return CommandResult(text="Usage: /btw <question>")
        # Fork a lightweight call — don't add to main history
        if agent and hasattr(agent, 'quick_query'):
            try:
                answer = agent.quick_query(args.strip())
                return CommandResult(text=f"[btw] {answer}")
            except Exception as e:
                return CommandResult(text=f"[btw] Error: {e}")
        # Fallback: just echo the question as a prompt
        return CommandResult(text=f"[btw] Quick question noted: {args.strip()}\n(Full /btw support requires quick_query method on agent)")

    def _cmd_doctor(args: str, agent=None, **kw) -> CommandResult:
        """Run diagnostics to verify NeoMind installation and configuration."""
        import shutil
        checks = []

        # Python version
        import sys
        py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        checks.append(f"  ✓ Python {py_ver}" if sys.version_info >= (3, 8) else f"  ✗ Python {py_ver} (need 3.8+)")

        # API keys
        api_key = os.environ.get('DEEPSEEK_API_KEY') or os.environ.get('ZAI_API_KEY') or os.environ.get('OPENAI_API_KEY')
        checks.append(f"  ✓ API key configured" if api_key else "  ✗ No API key found (DEEPSEEK_API_KEY, ZAI_API_KEY, or OPENAI_API_KEY)")

        # Git
        git = shutil.which('git')
        checks.append(f"  ✓ git found: {git}" if git else "  ✗ git not found")

        # Workspace is git repo
        import subprocess
        try:
            subprocess.run(['git', 'rev-parse', '--git-dir'], capture_output=True, timeout=5)
            checks.append("  ✓ Current directory is a git repository")
        except Exception:
            checks.append("  ✗ Current directory is not a git repository")

        # Core dependencies
        for pkg in ['openai', 'yaml', 'rich', 'prompt_toolkit', 'dotenv']:
            try:
                __import__(pkg)
                checks.append(f"  ✓ {pkg} installed")
            except ImportError:
                checks.append(f"  ✗ {pkg} not installed")

        # NeoMind services
        checks.append("\n  --- Services ---")
        try:
            from agent.services import ServiceRegistry
            sr = ServiceRegistry()
            for svc_name in ['safety', 'sandbox', 'search', 'feature_flags',
                              'permission_manager', 'auto_dream', 'session_notes',
                              'memory_selector', 'llm_provider']:
                svc = getattr(sr, svc_name, None)
                checks.append(f"  ✓ {svc_name}" if svc else f"  ✗ {svc_name}")
        except Exception as e:
            checks.append(f"  ✗ ServiceRegistry error: {e}")

        # Sandbox status
        checks.append("\n  --- Sandbox ---")
        try:
            from agent.services.sandbox import SandboxManager
            sb = SandboxManager()
            checks.append(f"  {'✓' if sb.is_available else '⚠'} Sandbox: {'available' if sb.is_available else 'fallback mode'} ({sb._system})")
        except Exception:
            checks.append("  ✗ Sandbox unavailable")

        # Feature flags
        checks.append("\n  --- Feature Flags ---")
        try:
            from agent.services.feature_flags import feature_flags
            flags = feature_flags.list_flags()
            enabled = sum(1 for f in flags.values() if f['enabled'])
            checks.append(f"  ✓ {enabled}/{len(flags)} flags enabled")
        except Exception:
            checks.append("  ✗ Feature flags unavailable")

        # Memory health
        checks.append("\n  --- Memory ---")
        try:
            from agent.memory.shared_memory import SharedMemory
            mem = SharedMemory()
            facts = mem.get_all_facts()
            checks.append(f"  ✓ SharedMemory: {len(facts)} facts stored")
        except Exception:
            checks.append("  ⚠ SharedMemory unavailable")

        # AutoDream status
        try:
            dream = sr.auto_dream
            if dream:
                status = dream.status
                checks.append(f"  ✓ AutoDream: {status['total_consolidated']} consolidated, gates {'open' if status['gates_open'] else 'closed'}")
        except Exception:
            pass

        # Vault
        vault_path = os.path.expanduser('~/neomind-vault')
        checks.append(f"\n  --- Storage ---")
        checks.append(f"  {'✓' if os.path.exists(vault_path) else '⚠'} Vault: {vault_path}")

        # Migration status
        try:
            from agent.migrations import MIGRATIONS, MigrationRunner
            runner = MigrationRunner()
            applied = len(runner._applied)
            checks.append(f"  ✓ Migrations: {applied}/{len(MIGRATIONS)} applied")
        except Exception:
            pass

        # Search sources
        checks.append("\n  --- Search ---")
        search_keys = ['BRAVE_API_KEY', 'TAVILY_API_KEY', 'SERPER_API_KEY', 'NEWSAPI_KEY']
        for key in search_keys:
            has = bool(os.environ.get(key))
            checks.append(f"  {'✓' if has else '○'} {key}: {'configured' if has else 'not set'}")

        return CommandResult(text="NeoMind Doctor — Diagnostics:\n" + "\n".join(checks))

    def _cmd_style(args: str, agent=None, **kw) -> CommandResult:
        """List or load output styles from .neomind/output-styles/."""
        styles_dirs = [
            os.path.join(os.getcwd(), '.neomind', 'output-styles'),
            os.path.expanduser('~/.neomind/output-styles'),
        ]
        available = []
        for d in styles_dirs:
            if os.path.exists(d):
                for f in os.listdir(d):
                    if f.endswith('.md'):
                        name = f[:-3]
                        available.append((name, os.path.join(d, f)))

        if not args.strip():
            if not available:
                return CommandResult(text="No output styles found. Create .neomind/output-styles/<name>.md files.")
            lines = ["Available output styles:"]
            for name, path in available:
                lines.append(f"  - {name}")
            lines.append("\nUsage: /style <name>")
            return CommandResult(text="\n".join(lines))

        # Load specific style
        target = args.strip()
        for name, path in available:
            if name == target:
                try:
                    with open(path) as f:
                        content = f.read()
                    if agent:
                        agent._output_style = content
                    return CommandResult(text=f"✓ Output style '{name}' loaded.")
                except Exception as e:
                    return CommandResult(text=f"Error loading style: {e}")

        return CommandResult(text=f"Style '{target}' not found.")

    def _cmd_verbose(args: str, agent=None, **kw) -> CommandResult:
        """Toggle verbose/debug output mode."""
        from agent_config import agent_config
        current = getattr(agent_config, 'verbose', False)
        new_val = not current
        if args.strip().lower() in ('on', 'true', '1'):
            new_val = True
        elif args.strip().lower() in ('off', 'false', '0'):
            new_val = False
        agent_config.verbose = new_val
        if agent:
            agent.verbose_mode = new_val
        return CommandResult(text=f"Verbose mode: {'ON' if new_val else 'OFF'}")

    def _cmd_hooks(args: str, agent=None, **kw) -> CommandResult:
        """Show hooks information."""
        lines = ["Hooks System:"]
        try:
            from agent.agentic import AgenticConfig
            cfg = AgenticConfig()
            lines.append(f"  Hooks enabled: {cfg.hooks_enabled}")
        except ImportError:
            lines.append("  Hooks enabled: unknown (agentic module not available)")
        try:
            from agent.agentic.stop_hooks import create_default_pipeline
            pipeline = create_default_pipeline()
            hooks = pipeline.hooks if hasattr(pipeline, 'hooks') else []
            lines.append(f"  Stop hooks registered: {len(hooks)}")
            for h in hooks:
                name = getattr(h, 'name', type(h).__name__)
                lines.append(f"    - {name}")
        except (ImportError, Exception):
            lines.append("  Stop hooks: not available")
        return CommandResult(text="\n".join(lines))

    def _cmd_arch(args: str, agent=None, **kw) -> CommandResult:
        """Show architecture information."""
        import platform as _plat
        lines = [
            "Architecture Info:",
            f"  Platform: {_plat.system()} {_plat.machine()}",
            f"  Python: {_plat.python_version()}",
        ]
        try:
            from agent_config import agent_config
            lines.append(f"  Mode: {agent_config.mode}")
            lines.append(f"  Model: {getattr(agent_config, 'model', 'unknown')}")
        except Exception:
            pass
        try:
            from agent.tools import ToolRegistry
            reg = ToolRegistry.__new__(ToolRegistry)
            if hasattr(reg, '_tool_definitions'):
                lines.append(f"  Registered tools: {len(reg._tool_definitions)}")
        except Exception:
            pass
        lines.append("  Components: core, agentic_loop, tool_registry, safety, search")
        return CommandResult(text="\n".join(lines))

    def _cmd_team(args: str, agent=None, **kw) -> CommandResult:
        """Manage agent teams (swarm mode)."""
        try:
            from agent.agentic.swarm import TeamManager
            tm = TeamManager()
        except ImportError:
            return CommandResult(text="Swarm system not available.")

        arg = args.strip()
        if not arg:
            return CommandResult(text=(
                "Team Management:\n"
                "  /team create <name>  — Create a new team\n"
                "  /team list           — List teams\n"
                "  /team info <name>    — Show team details\n"
                "  /team delete <name>  — Delete a team"
            ))

        # shlex-aware split so quoted names with spaces survive intact:
        #   /team create "team with space"  →  ['create', 'team with space']
        parts = split_args(arg)
        if not parts:
            return CommandResult(text="Usage: /team [create|list|info|delete] [name]")
        action = parts[0]

        if action == 'create' and len(parts) >= 2:
            name = parts[1]
            leader = 'neomind'
            try:
                team = tm.create_team(name, leader)
            except ValueError as e:
                return CommandResult(text=f"Error: {e}")
            return CommandResult(text=f"✓ Team '{name}' created. Leader: {leader}")

        if action == 'list':
            teams_dir = os.path.expanduser('~/.neomind/teams')
            if not os.path.exists(teams_dir):
                return CommandResult(text="No teams found.")
            teams = [d for d in os.listdir(teams_dir) if os.path.isdir(os.path.join(teams_dir, d))]
            if not teams:
                return CommandResult(text="No teams found.")
            return CommandResult(text="Teams:\n" + "\n".join(f"  - {t}" for t in teams))

        if action == 'info' and len(parts) >= 2:
            team = tm.get_team(parts[1])
            if team:
                members = ", ".join(f"{m['name']} ({m['color']})" for m in team.get('members', []))
                return CommandResult(text=f"Team: {team['name']}\nMembers: {members}")
            return CommandResult(text=f"Team '{parts[1]}' not found.")

        if action == 'delete' and len(parts) >= 2:
            tm.delete_team(parts[1])
            return CommandResult(text=f"✓ Team '{parts[1]}' deleted.")

        return CommandResult(text="Usage: /team [create|list|info|delete] [name]")

    def _cmd_rules(args: str, agent=None, **kw) -> CommandResult:
        """Manage permission rules (allow/deny patterns for tools)."""
        try:
            from agent.services import ServiceRegistry
            services = getattr(agent, 'services', None) or ServiceRegistry()
            pm = services.permission_manager
            if pm is None:
                return CommandResult(text="Permission manager not available.")
        except Exception:
            return CommandResult(text="Permission manager not available.")

        arg = args.strip()
        if not arg:
            rules = pm.list_rules()
            if not rules:
                return CommandResult(text="No permission rules defined.\nUsage: /rules add <tool_pattern> allow|deny|ask [content_pattern]")
            lines = ["Permission Rules:"]
            for i, r in enumerate(rules):
                cp = f" (content: {r.get('content_pattern', '')})" if r.get('content_pattern') else ""
                lines.append(f"  [{i}] {r['tool_pattern']} → {r['behavior']}{cp}")
            return CommandResult(text="\n".join(lines))

        parts = arg.split()
        if parts[0] == 'add' and len(parts) >= 3:
            tool_pat = parts[1]
            behavior = parts[2]
            content_pat = ' '.join(parts[3:]) if len(parts) > 3 else None
            if behavior not in ('allow', 'deny', 'ask'):
                return CommandResult(text="Behavior must be: allow, deny, or ask")
            pm.add_rule(tool_pat, behavior, content_pat)
            return CommandResult(text=f"✓ Rule added: {tool_pat} → {behavior}")

        if parts[0] == 'remove' and len(parts) >= 2:
            try:
                idx = int(parts[1])
                pm.remove_rule(idx)
                return CommandResult(text=f"✓ Rule {idx} removed")
            except (ValueError, IndexError):
                return CommandResult(text="Usage: /rules remove <index>")

        return CommandResult(text="Usage: /rules [add <pattern> allow|deny|ask | remove <index>]")

    def _cmd_load(args: str, agent=None, **kw) -> CommandResult:
        """Load a saved conversation from a file produced by /save.

        Supports .json files exported by /save (export_service format).
        For .md/.html/.txt files, directs user to /resume instead.
        """
        import json as _json

        filename = args.strip()
        if not filename:
            return CommandResult(text="Usage: /load <filename.json>\n\nLoad a .json file previously created with /save.")

        filepath = os.path.abspath(filename)
        if not os.path.isfile(filepath):
            return CommandResult(text=f"File not found: {filepath}")

        ext = filepath.rsplit('.', 1)[-1].lower() if '.' in filepath else ''
        if ext != 'json':
            return CommandResult(
                text=f"Cannot load .{ext} files directly. Only .json files from /save are supported.\n"
                     f"For session recovery, try: /resume"
            )

        if not agent or not hasattr(agent, 'conversation_history'):
            return CommandResult(text="No agent available to load conversation into.")

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = _json.load(f)

            # Support export_service JSON format (format_version 1.0)
            messages = data.get('messages', [])

            # Restore into agent's conversation history
            agent.conversation_history = [
                {"role": m.get("role", "user"), "content": m.get("content", "")}
                for m in messages
            ]
            count = len(agent.conversation_history)
            return CommandResult(text=f"Loaded {count} messages from {filepath}")
        except _json.JSONDecodeError as e:
            return CommandResult(text=f"Invalid JSON file: {e}")
        except Exception as e:
            return CommandResult(text=f"Load failed: {e}")

    def _cmd_transcript(args: str, agent=None, **kw) -> CommandResult:
        """Show conversation transcript.

        Usage:
            /transcript        - show last 20 messages
            /transcript full   - show all messages
            /transcript N      - show last N messages
            /transcript last   - show last assistant response
        """
        if not agent or not hasattr(agent, 'conversation_history'):
            return CommandResult(text="No conversation history available.")

        history = agent.conversation_history
        if not history:
            return CommandResult(text="No conversation history yet.")

        arg = args.strip().lower()

        if arg == "last":
            for msg in reversed(history):
                if msg.get("role") == "assistant":
                    content = msg.get("content", "")
                    return CommandResult(text=f"[Assistant]\n{content}")
            return CommandResult(text="No assistant responses yet.")

        if arg == "full":
            limit = len(history)
        elif arg.isdigit():
            limit = int(arg)
        else:
            limit = 20

        messages = history[-limit:]
        lines = []
        for msg in messages:
            role = msg.get("role", "unknown").capitalize()
            content = str(msg.get("content", ""))
            preview = content[:200] + ("..." if len(content) > 200 else "")
            lines.append(f"[{role}] {preview}")

        return CommandResult(text="\n\n".join(lines))

    # ── Build the full command list ────────────────────────────────

    commands = [
        # === Shared (all modes) ===
        Command(name="help", description="Show available commands", handler=_cmd_help, aliases=["h", "?"], priority=1),
        Command(name="clear", description="Clear conversation history", handler=_cmd_clear, priority=5),
        Command(name="compact", description="Compact conversation to save context", handler=_cmd_compact, priority=6),
        Command(name="context", description="Show context window usage", handler=_cmd_context, priority=7),
        Command(name="cost", description="Show session cost and token usage", handler=_cmd_cost, priority=8),
        Command(name="stats", description="Show session statistics", handler=_cmd_stats, priority=9),
        Command(name="exit", description="Exit the agent", handler=_cmd_exit, aliases=["quit", "q"], priority=99),
        Command(name="mode", description="Switch personality (chat/coding/fin)", handler=_cmd_mode, argument_hint="<mode>", priority=10),
        Command(name="model", description="Switch or show model", handler=_cmd_model, aliases=["switch"], argument_hint="[model_name]", priority=11),
        Command(name="think", description="Toggle thinking mode", handler=_cmd_think, priority=12),
        Command(name="config", description="View/change config", handler=_cmd_config, argument_hint="[show | set <key> <val> | get <key>]", priority=13),
        Command(name="memory", description="Manage memory", handler=_cmd_memory, argument_hint="[show | clear | search]", priority=14),
        Command(name="debug", description="Toggle debug mode", handler=_cmd_debug, priority=15),
        Command(name="history", description="Show conversation summary", handler=_cmd_history, priority=16),
        Command(name="save", description="Save conversation", handler=_cmd_save, argument_hint="<filename>", priority=17),
        Command(name="load", description="Load a saved conversation", handler=_cmd_load, argument_hint="[name]", priority=17),
        Command(name="transcript", description="Show conversation transcript", handler=_cmd_transcript, argument_hint="[full|last|N]", priority=17),
        Command(name="skills", description="List available skills", handler=_cmd_skills, priority=18),
        Command(name="permissions", description="Show permission mode", handler=_cmd_permissions, priority=19),
        Command(name="version", description="Show version", handler=_cmd_version, aliases=["ver"], priority=20),
        Command(name="checkpoint", description="Save conversation checkpoint", handler=_cmd_checkpoint, argument_hint="[label]", priority=21),
        Command(name="rewind", description="Rewind to checkpoint or N turns back", handler=_cmd_rewind, argument_hint="[label|N]", priority=22),
        Command(name="flags", description="Show/toggle feature flags", handler=_cmd_flags, argument_hint="[FLAG on|off]", priority=23),
        Command(name="dream", description="AutoDream status or trigger", handler=_cmd_dream, argument_hint="[run]", priority=24),
        Command(name="resume", description="Resume a previous session", handler=_cmd_resume, argument_hint="[session_name]", priority=25),
        Command(name="branch", description="Branch conversation", handler=_cmd_branch, argument_hint="[label]", priority=26),
        Command(name="snip", description="Save snippet from recent messages", handler=_cmd_snip, argument_hint="[label|N]", priority=27),
        Command(name="brief", description="Toggle brief output mode", handler=_cmd_brief, argument_hint="[on|off]", priority=28),
        Command(name="doctor", description="Run installation diagnostics", handler=_cmd_doctor, priority=29),
        Command(name="btw", description="Quick side question", handler=_cmd_btw, argument_hint="<question>", priority=30),
        Command(name="style", description="List/load output styles", handler=_cmd_style, argument_hint="[name]", priority=31),
        Command(name="rules", description="Manage permission rules", handler=_cmd_rules, argument_hint="[add|remove]", priority=32),
        Command(name="careful", description="Toggle careful/safety guard mode", handler=_cmd_careful, priority=33),
        Command(name="verbose", description="Toggle verbose mode", handler=_cmd_verbose, argument_hint="[on|off]", priority=34),
        Command(name="hooks", description="Show hooks information", handler=_cmd_hooks, priority=34),
        Command(name="arch", description="Show architecture info", handler=_cmd_arch, priority=34),
        Command(name="team", description="Manage agent teams (swarm)", handler=_cmd_team, argument_hint="[create|list|info|delete]", priority=35),

        # === Chat mode ===
        Command(name="deep", description="Deep dive into a topic", type=CommandType.PROMPT, handler=_cmd_deep, modes=["chat"], argument_hint="<topic>", priority=40),
        Command(name="compare", description="Compare items side by side", type=CommandType.PROMPT, handler=_cmd_compare, modes=["chat", "fin"], argument_hint="<A vs B>", priority=41),
        Command(name="draft", description="Draft content (email, article, etc.)", type=CommandType.PROMPT, handler=_cmd_draft, modes=["chat"], argument_hint="<description>", priority=42),
        Command(name="brainstorm", description="Brainstorm ideas", type=CommandType.PROMPT, handler=_cmd_brainstorm, modes=["chat"], argument_hint="<topic>", priority=43),
        Command(name="tldr", description="Summarize concisely", type=CommandType.PROMPT, handler=_cmd_tldr, modes=["chat"], aliases=["summary"], argument_hint="<text>", priority=44),
        Command(name="explore", description="Explore a question from multiple angles", type=CommandType.PROMPT, handler=_cmd_explore, modes=["chat"], argument_hint="<question>", priority=45),

        # === Coding mode ===
        Command(name="init", description="Initialize project config", type=CommandType.PROMPT, handler=_cmd_init, modes=["coding"], priority=35),
        Command(name="ship", description="Branch → commit → push → PR", type=CommandType.PROMPT, handler=_cmd_ship, modes=["coding"], argument_hint="[scope]", priority=36),
        Command(name="plan", description="Create implementation plan", type=CommandType.PROMPT, handler=_cmd_plan, modes=["coding"], argument_hint="[task]", priority=30),
        Command(name="review", description="Code review", type=CommandType.PROMPT, handler=_cmd_review, modes=["coding"], argument_hint="[files]", priority=31),
        Command(name="diff", description="Show git diff", handler=_cmd_diff, modes=["coding"], argument_hint="[flags]", priority=32),
        Command(name="git", description="Run git command", handler=_cmd_git, modes=["coding"], argument_hint="<command>", priority=33),
        Command(name="worktree", description="Manage git worktrees", handler=_cmd_worktree, modes=["coding"], argument_hint="[list|add|remove]", priority=33),
        Command(name="stash", description="Manage git stash", handler=_cmd_stash, modes=["coding"], argument_hint="[list|pop|push|drop]", priority=33),
        Command(name="test", description="Run tests", type=CommandType.PROMPT, handler=_cmd_test, modes=["coding"], argument_hint="[scope]", priority=34),
        Command(name="security-review", description="Security audit", type=CommandType.PROMPT, handler=_cmd_security_review, modes=["coding"], aliases=["security"], priority=35),

        # === Finance mode ===
        Command(name="stock", description="Stock analysis", type=CommandType.PROMPT, handler=_cmd_stock, modes=["fin"], argument_hint="<ticker>", priority=40),
        Command(name="portfolio", description="Portfolio overview", type=CommandType.PROMPT, handler=_cmd_portfolio, modes=["fin"], priority=41),
        Command(name="market", description="Market overview", type=CommandType.PROMPT, handler=_cmd_market, modes=["fin"], argument_hint="[region]", priority=42),
        Command(name="news", description="Finance news digest", type=CommandType.PROMPT, handler=_cmd_news, modes=["fin"], argument_hint="[topic]", priority=43),
        Command(name="quant", description="Quantitative computation", type=CommandType.PROMPT, handler=_cmd_quant, modes=["fin"], argument_hint="<calculation>", priority=44),
    ]

    return commands


def create_default_registry() -> CommandRegistry:
    """Create and populate the default command registry.

    Like Claude Code's getCommands() — single entry point to get all commands.
    """
    registry = CommandRegistry()
    registry.register_many(_build_builtin_commands())
    return registry
