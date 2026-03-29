"""Abstract base class for all NeoMind personality modes.

Each personality (Chat, Coding, Finance) subclasses BasePersonality
and implements mode-specific behavior while inheriting shared infrastructure
from SharedCommandsMixin and accessing services via ServiceRegistry.

Created: 2026-03-28 (Step 1 of architecture redesign)
"""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Dict, Optional, Set

from agent_config import agent_config

if TYPE_CHECKING:
    from agent.core import NeoMindAgent  # Will become NeoMindCore later


class BasePersonality(ABC):
    """Abstract base for all NeoMind personality modes.

    Lifecycle:
        1. __init__(core, services) — called once at registration time
        2. on_activate()            — called each time this mode becomes active
        3. (user interactions)      — command handlers, enhance_response, etc.
        4. on_deactivate()          — called when switching away to another mode
    """

    def __init__(self, core: 'NeoMindAgent', services: 'ServiceRegistry'):
        self.core = core          # Slim core reference (LLM calls, history, streaming)
        self.services = services  # Shared services registry

    # ── Abstract Properties ──────────────────────────────────────────

    @property
    @abstractmethod
    def name(self) -> str:
        """Mode identifier: 'chat', 'coding', or 'fin'.

        Must match the key used in agent_config.switch_mode().
        """

    @property
    @abstractmethod
    def display_name(self) -> str:
        """Human-readable name shown in prompts, e.g. 'Chat 类人'."""

    # ── Abstract Methods ─────────────────────────────────────────────

    @abstractmethod
    def get_command_handlers(self) -> Dict[str, tuple]:
        """Return command → (handler, strip_prefix) mapping UNIQUE to this mode.

        Shared commands are provided by SharedCommandsMixin (inherited by
        concrete personality classes). This method only returns commands
        that are exclusive to this personality.

        Returns:
            Dict mapping command string (e.g. '/code') to a tuple of
            (handler_callable, bool_strip_prefix).
        """

    @abstractmethod
    def on_activate(self) -> None:
        """Called when switching TO this mode.

        Concrete implementations should call super().on_activate() first,
        then add mode-specific initialization.

        Responsibilities (12 steps):
        1.  agent_config.switch_mode(self.name)    — reload YAML config
        2.  Update core.model, core.fallback_model  — from agent_config
        3.  Re-resolve provider (core._resolve_provider)
        4.  Update search domain (core.searcher.set_domain)
        5.  Update NL interpreter threshold
        6.  Update safety settings
        7.  Reload system prompt → inject into conversation_history
        8.  Re-inject vault + shared memory context
        9.  Deactivate incompatible active skill
        10. Clear stale available_models_cache (provider may change across modes)
        11. Close stale event loops (search_loop, _browser_loop)
        12. Init mode-specific subsystems (workspace, finance, etc.)

        See core.py switch_mode() lines 786-861 for the current logic
        that this method will eventually replace.
        """

    @abstractmethod
    def on_deactivate(self) -> None:
        """Called when switching AWAY from this mode.

        Override to perform cleanup: close connections, flush caches,
        save state, etc. Default behavior (from base) is a no-op.
        """

    # ── Default Implementations (override as needed) ─────────────────

    def get_system_prompt(self) -> str:
        """Return the personality-specific system prompt.

        Default: reads from agent_config after switch_mode() has been
        called in on_activate(). Override for custom prompt construction.
        """
        return agent_config.system_prompt or ""

    def get_commands_feed_to_llm(self) -> Set[str]:
        """Commands whose output should be fed back to the LLM.

        These are tool-like commands where the LLM benefits from seeing
        the command's output to formulate a follow-up response.

        Default set (from core.py L644-648). Override in personality
        subclasses to add/remove commands.
        """
        return {
            "/run", "/grep", "/find", "/read", "/write", "/edit",
            "/git", "/code", "/analyze", "/fix", "/diff", "/test",
            "/search", "/browse", "/links", "/crawl", "/webmap",
        }

    def enhance_response(self, response: str, tool_results: Optional[list] = None) -> str:
        """Post-process LLM response before displaying to user.

        Override in FinancePersonality to run response_validator.
        Default: passthrough (no modification).

        Args:
            response: The raw LLM response text.
            tool_results: Any tool call results from this turn.

        Returns:
            The (possibly modified) response text.
        """
        return response

    def get_search_domain(self) -> str:
        """Search domain hint for UniversalSearchEngine.

        Override: 'finance' for fin mode, 'code' for coding mode.
        Default: 'general'.
        """
        return "general"

    def get_nl_patterns(self) -> Optional[dict]:
        """Return mode-specific natural language patterns for NL interpreter.

        Default: None (use general patterns only).
        Override in CodingPersonality to add code-specific patterns.
        Override in FinancePersonality to add finance-specific patterns.
        """
        return None
