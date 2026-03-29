# agent/core.py
import os
import sys
import json
import asyncio
import re
import html
import time
import pathlib
import fnmatch
import hashlib
import warnings
import stat
import difflib
from typing import Optional, Dict, List, Any, Set, Tuple, Callable
from urllib.parse import urlparse

import requests

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False
    BeautifulSoup = None

try:
    import chardet
    HAS_CHARDET = True
except ImportError:
    HAS_CHARDET = False
    chardet = None

try:
    from requests_html import HTMLSession
    HAS_REQUESTS_HTML = True
except ImportError:
    HAS_REQUESTS_HTML = False
    HTMLSession = None

try:
    import trafilatura
    HAS_TRAFILATURA = True
except ImportError:
    HAS_TRAFILATURA = False

try:
    import html2text
    HAS_HTML2TEXT = True
except ImportError:
    HAS_HTML2TEXT = False
    html2text = None

from .code_analyzer import CodeAnalyzer
from .self_iteration import SelfIteration
from .task_manager import TaskManager
from .formatter import Formatter, success, error, warning, info, header, code_block, command_help
from .help_system import HelpSystem, get_help
from .command_executor import CommandExecutor, execute_safe, execute_git_safe
from .safety import SafetyManager, safe_read_file, safe_write_file, safe_delete_file, is_path_safe, log_operation
from .planner import Planner, plan_changes, GoalPlanner
from .context_manager import ContextManager, HAS_TIKTOKEN
from .search_legacy import OptimizedDuckDuckGoSearch  # legacy fallback
from .search.engine import UniversalSearchEngine  # new multi-source engine
from .natural_language import NaturalLanguageInterpreter
from agent_config import agent_config

# ── Workflow modules (optional/graceful degradation) ──────────────────────────
try:
    from .workflow.sprint import SprintManager
    HAS_SPRINT = True
except ImportError:
    HAS_SPRINT = False
    SprintManager = None

try:
    from .workflow.guards import SafetyGuard
    HAS_GUARDS = True
except ImportError:
    HAS_GUARDS = False
    SafetyGuard = None

try:
    from .workflow.evidence import EvidenceTrail
    HAS_EVIDENCE = True
except ImportError:
    HAS_EVIDENCE = False
    EvidenceTrail = None

try:
    from .workflow.review import ReviewDispatcher
    HAS_REVIEW = True
except ImportError:
    HAS_REVIEW = False
    ReviewDispatcher = None

# ── Phase 4: Self-Evolution (optional/graceful degradation) ───────────────
try:
    from .evolution.auto_evolve import AutoEvolve
    from .evolution.scheduler import EvolutionScheduler
    HAS_EVOLUTION = True
except ImportError:
    HAS_EVOLUTION = False
    AutoEvolve = None
    EvolutionScheduler = None

try:
    from .evolution.upgrade import NeoMindUpgrade
    HAS_UPGRADE = True
except ImportError:
    HAS_UPGRADE = False
    NeoMindUpgrade = None

class NeoMindAgent:
    """Main AI agent with streaming, search, and model listing capabilities.

    Supports multiple providers (DeepSeek, z.ai) via OpenAI-compatible APIs.
    """

    # ── Provider & Model constants (delegated to agent.services.llm_provider) ──
    # Kept as class-level aliases for backward compatibility with tests/code
    # that reference NeoMindAgent._MODEL_SPECS, ._PROVIDERS, etc.
    from agent.services.llm_provider import (
        MODEL_SPECS as _MODEL_SPECS,
        DEFAULT_SPEC as _DEFAULT_SPEC,
        PROVIDERS as _PROVIDERS,
        get_model_spec as _get_model_spec_func,
        proxy_url as _proxy_url_func,
    )

    _TOKENSIGHT_PROXY_URL = os.getenv("TOKENSIGHT_PROXY_URL", "").rstrip("/")
    _TOKENSIGHT_ROUTES = {"deepseek": "/deepseek", "zai": "/zai", "moonshot": "/moonshot"}

    @classmethod
    def _get_model_spec(cls, model: str) -> dict:
        """Return the spec dict for a model, falling back to defaults."""
        return cls._get_model_spec_func(model)

    @classmethod
    def _proxy_url(cls, provider_name: str, path: str) -> str:
        """Build URL, routing through TokenSight proxy if configured."""
        return cls._proxy_url_func(provider_name, path)

    def _resolve_provider(self, model: str = None) -> dict:
        """Resolve which provider config to use for a given model.

        Returns a dict with keys: base_url, models_url, api_key, name.
        Implementation references PROVIDERS and proxy_url from llm_provider module.
        """
        from agent.services.llm_provider import PROVIDERS, proxy_url
        model = model or self.model
        litellm_enabled = os.getenv("LITELLM_ENABLED", "").lower() in ("true", "1", "yes")

        if litellm_enabled:
            litellm_key = os.getenv("LITELLM_API_KEY", "")
            if litellm_key:
                litellm_models = ["local", "deepseek-chat", "deepseek-reasoner", "qwen3.5", "qwen-plus"]
                if model in litellm_models or model.startswith("local") or model.startswith("qwen"):
                    base = os.getenv("LITELLM_BASE_URL", "http://localhost:4000/v1")
                    return {
                        "name": "litellm",
                        "base_url": f"{base}/chat/completions",
                        "models_url": f"{base}/models",
                        "api_key": litellm_key,
                    }

        for name, prov in PROVIDERS.items():
            if name == "litellm":
                continue
            for prefix in prov["model_prefixes"]:
                if model.startswith(prefix):
                    api_key = os.getenv(prov["env_key"], "")
                    proxy_base = proxy_url(name, "chat/completions")
                    proxy_models = proxy_url(name, "models")
                    return {
                        "name": name,
                        "base_url": proxy_base or prov["base_url"],
                        "models_url": proxy_models or prov["models_url"],
                        "api_key": api_key,
                    }

        prov = PROVIDERS["deepseek"]
        proxy_base = proxy_url("deepseek", "chat/completions")
        proxy_models = proxy_url("deepseek", "models")
        return {
            "name": "deepseek",
            "base_url": proxy_base or prov["base_url"],
            "models_url": proxy_models or prov["models_url"],
            "api_key": self.api_key,
        }

    def __init__(self, api_key: Optional[str] = None, model: str = "deepseek-chat"):
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        # CHANGED: Use agent_config instead of hardcoded values
        self.model = model if model != "deepseek-chat" else agent_config.model
        self.fallback_model = agent_config.fallback_model
        self.thinking_mode = agent_config.thinking_mode
        # Mode configuration
        self.mode = agent_config.mode  # chat or coding
        self.workspace_manager = None  # Lazy initialization for coding mode
        self.show_status_bar = agent_config.show_status_bar
        # Status display system for coding mode
        self.verbose_mode = False  # Hidden by default; toggle with /verbose or Ctrl+E
        self.status_buffer = []  # Store debug/info messages for later display
        self.current_status = ""  # Current single-line status message
        self.last_status_update = 0  # Timestamp of last status update
        self._mcp_servers_cache = None  # Cache for MCP servers
        # Provider-aware URLs (resolved dynamically per request)
        provider = self._resolve_provider(self.model)
        self.base_url = provider["base_url"]
        self.models_url = provider["models_url"]
        self.conversation_history = []
        self.context_manager = ContextManager(self.conversation_history)
        self.thinking_enabled = agent_config.thinking_enabled  # CHANGED
        # ── ServiceRegistry (owns ALL shared service creation) ────────────
        # P3-A: ServiceRegistry is the single source of truth for services.
        # core.py attributes (self.formatter, self.searcher, etc.) are backward-
        # compat aliases that point to the same objects created by ServiceRegistry.
        from agent.services import ServiceRegistry
        self.services = ServiceRegistry(config=agent_config)

        # Self-iteration setup (needed before safety_manager)
        self.agent_root = os.path.dirname(os.path.abspath(__file__))

        # ── Backward-compat aliases (all created once by ServiceRegistry) ──
        self.searcher = self.services.search
        self.formatter = self.services.formatter
        self.command_executor = self.services.command_executor
        self.safety_manager = self.services.safety
        self.help_system = self.services.help_system
        self.self_iteration = None  # Lazy initialization

        # Auto-features configuration
        self.enable_auto_search = agent_config.auto_search_enabled
        self.auto_search_enabled = agent_config.auto_search_enabled
        self.search_enabled = agent_config.search_enabled
        self.natural_language_enabled = agent_config.natural_language_enabled
        self.natural_language_confidence_threshold = agent_config.natural_language_confidence_threshold
        self.safety_confirm_file_operations = agent_config.safety_confirm_file_operations
        self.safety_confirm_code_changes = agent_config.safety_confirm_code_changes
        # Natural language interpreter (via ServiceRegistry)
        self.interpreter = self.services.nl_interpreter
        self.search_loop = None
        self._browser_loop = None  # Dedicated event loop for BrowserDaemon async calls
        self._last_links: Dict[int, str] = {}  # /links result: number → URL for follow-up
        self.available_models_cache = None  # NEW: Cache for available models
        self.available_models_cache_timestamp = 0  # NEW: Cache timestamp

        # Add system prompt from active mode config
        if agent_config.system_prompt:
            self.add_to_history("system", agent_config.system_prompt)

        # ── Vault context injection ──────────────────────────────────────
        # ServiceRegistry creates VaultReader/Writer/Watcher lazily.
        # We trigger creation here and inject context into conversation.
        self._vault_reader = None
        self._vault_writer = None
        self._vault_watcher = None
        self._response_turn_count = 0
        vault = self.services.vault  # triggers lazy init
        if vault:
            self._vault_reader = vault.get('reader')
            self._vault_writer = vault.get('writer')
            self._vault_watcher = vault.get('watcher')
            try:
                if self._vault_reader and self._vault_reader.vault_exists():
                    vault_context = self._vault_reader.get_startup_context(
                        mode=getattr(self, 'mode', 'chat')
                    )
                    if vault_context:
                        self.add_to_history("system", vault_context)
                        self._status_print("Injected vault context into system prompt", "debug")
                elif self._vault_writer:
                    self._vault_writer.ensure_structure()
                    self._status_print("Initialized vault structure (first run)", "debug")
            except Exception as e:
                self._status_print(f"Vault context injection failed (non-fatal): {e}", "debug")

        # ── Finance response validator ──────────────────────────────────
        # Now handled by FinancePersonality.on_activate(), but kept for
        # backward compat until core.py's inline validation is fully removed.
        self._finance_validator = None
        try:
            from agent.finance.response_validator import get_finance_validator
            self._finance_validator = get_finance_validator(strict=False)
            self._status_print("Finance response validator loaded", "debug")
        except Exception as e:
            self._status_print(f"Finance validator not available (non-fatal): {e}", "debug")

        # ── Shared Memory context injection ──────────────────────────────
        # ServiceRegistry creates SharedMemory lazily. We inject context here.
        self._shared_memory = self.services.memory  # triggers lazy init
        if self._shared_memory:
            try:
                mem_context = self._shared_memory.get_context_summary(
                    mode=getattr(self, 'mode', 'chat'), max_tokens=500
                )
                if mem_context:
                    self.add_to_history("system",
                        f"# User Context (from cross-personality memory)\n\n{mem_context}")
                    self._status_print("Injected shared memory context", "debug")
            except Exception as e:
                self._status_print(f"SharedMemory context injection failed (non-fatal): {e}", "debug")

        # ── Skill system ────────────────────────────────────────────────
        self._skill_loader = self.services.skills  # triggers lazy init
        self._active_skill = None
        if self._skill_loader:
            try:
                self._status_print(f"Loaded {self._skill_loader.count} skills", "debug")
            except Exception:
                pass

        # ── Unified Logger ──────────────────────────────────────────────
        self._unified_logger = self.services.logger  # triggers lazy init
        if self._unified_logger:
            self._status_print("Unified logger loaded", "debug")

        if not self.api_key:
            raise ValueError("API key is required. Set DEEPSEEK_API_KEY environment variable or pass it as argument.")
        # Initialize HTML-to-text converter if available
        if HAS_HTML2TEXT:
            self.html_converter = html2text.HTML2Text()
            self.html_converter.ignore_links = False
            self.html_converter.ignore_images = True
            self.html_converter.body_width = 0  # No width limit
        else:
            self.html_converter = None

        # Initialize optional renderer
        self.session = None
        if HAS_REQUESTS_HTML:
            try:
                self.session = HTMLSession()
            except:
                self.session = None

        # NEW: Code analyzer
        self.code_analyzer = None
        self.code_changes_pending = []  # Store proposed changes

        # ── More backward-compat aliases (via ServiceRegistry) ──────────
        self.task_manager = self.services.task_manager
        # Goal planner (not yet in ServiceRegistry — standalone)
        self.goal_planner = GoalPlanner()

        # ── Workflow modules (via ServiceRegistry lazy init) ──────────────
        self.evidence = self.services.evidence
        self.guard = self.services.guard
        self.sprint_mgr = self.services.sprint_mgr
        self.current_sprint_id = None  # Track active sprint
        self.review_dispatcher = self.services.review
        self.evolution = self.services.evolution
        self.evolution_scheduler = self.services.evolution_scheduler
        self._turn_counter = 0
        self.upgrader = self.services.upgrader

        # ── Personality system (Phase B: personalities drive command routing) ──
        # Register personalities first, then build command handlers.
        # If personality registration fails, _setup_command_handlers() falls back
        # to legacy hardcoded handlers.
        self._personalities = {}
        self._active_personality = None
        self._register_personalities()

        # Command registry for unified routing
        self.command_handlers = {}
        self._setup_command_handlers()

    def _setup_command_handlers(self) -> None:
        """Initialize command handler registry.

        Phase B: If personality system is available, builds handlers from
        shared + personality-specific. Falls back to legacy hardcoded map.
        """
        if self._active_personality:
            self._rebuild_command_handlers()
        else:
            self._setup_legacy_command_handlers()

    def _rebuild_command_handlers(self) -> None:
        """Build command handlers from personality system.

        Merges SharedCommandsMixin handlers + active personality's unique handlers.
        Personality-specific handlers override shared handlers with same prefix.
        """
        # Start with shared commands (available in ALL modes)
        self.command_handlers = dict(self._active_personality.get_shared_command_handlers())
        # Overlay personality-specific commands (may override shared ones)
        self.command_handlers.update(self._active_personality.get_command_handlers())

    def _setup_legacy_command_handlers(self) -> None:
        """Legacy command handler registry (fallback when personality system unavailable)."""
        # Mapping: prefix -> (handler, strip_prefix)
        self.command_handlers = {
            "/search": (self.handle_search, True),
            "/mode": (self.handle_mode_command, True),
            "/skills": (self.handle_skills_command, True),
            "/skill": (self.handle_skill_command, True),
            "/auto": (self.handle_auto_command, True),
            "/models": (self.handle_models_command, False),
            "/task": (self.handle_task_command, True),
            "/plan": (self.handle_plan_command, True),
            "/execute": (self.handle_execute_command, True),
            "/switch": (self.handle_switch_command, True),
            "/summarize": (self.handle_summarize_command, True),
            "/translate": (self.handle_translate_command, True),
            "/generate": (self.handle_generate_command, True),
            "/reason": (self.handle_reason_command, True),
            "/debug": (self.handle_debug_command, True),
            "/explain": (self.handle_explain_command, True),
            "/refactor": (self.handle_refactor_command, True),
            "/grep": (self.handle_grep_command, True),
            "/find": (self.handle_find_command, True),
            "/clear": (self.handle_clear_command, True),
            "/history": (self.handle_history_command, True),
            "/context": (self.handle_context_command, True),
            "/think": (self.handle_think_command, True),
            "/quit": (self.handle_quit_command, True),
            "/exit": (self.handle_exit_command, True),
            "/help": (self.handle_help_command, True),
            "/verbose": (self.handle_verbose_command, True),
            "/diff": (self.handle_diff_command, True),
            "/browse": (self.handle_browse_command, True),
            "/undo": (self.handle_undo_command, True),
            "/test": (self.handle_test_command, True),
            "/apply": (self.handle_apply_command, True),
            "/read": (self.handle_read_command, True),
            "/write": (self.handle_write_command, True),
            "/edit": (self.handle_edit_command, True),
            "/run": (self.handle_run_command, True),
            "/git": (self.handle_git_command, True),
            "/code": (self.handle_code_command, True),
            "/fix": (self.handle_auto_fix_command, False),
            "/analyze": (self.handle_auto_fix_command, False),
            "/sprint": (self.handle_sprint_command, True),
            "/careful": (self.handle_careful_command, True),
            "/freeze": (self.handle_freeze_command, True),
            "/guard": (self.handle_guard_command, True),
            "/unfreeze": (self.handle_unfreeze_command, True),
            "/evidence": (self.handle_evidence_command, True),
            "/evolve": (self.handle_evolve_command, True),
            "/dashboard": (self.handle_dashboard_command, True),
            "/upgrade": (self.handle_upgrade_command, True),
            "/links": (self.handle_links_command, True),
            "/crawl": (self.handle_crawl_command, True),
            "/webmap": (self.handle_webmap_command, True),
            "/logs": (self.handle_logs_command, True),
        }

    def _register_personalities(self) -> None:
        """Register all personality modes and wire ServiceRegistry.

        Creates a ServiceRegistry bridged to core's existing service instances,
        then instantiates personality objects that use it.
        Phase C will move real command implementations into personalities,
        accessing services via self.services.X instead of self.core.X.
        """
        try:
            from agent.services import ServiceRegistry
            from agent.modes.chat import ChatPersonality
            from agent.modes.coding import CodingPersonality
            from agent.modes.finance import FinancePersonality

            # Reuse the ServiceRegistry created in __init__ (line ~400)
            # Do NOT create a duplicate — self.services already owns service creation
            services = self.services
            if services is None:
                services = ServiceRegistry(core_ref=self, config=agent_config)
                self.services = services

            self._personalities = {
                'chat': ChatPersonality(self, services),
                'coding': CodingPersonality(self, services),
                'fin': FinancePersonality(self, services),
            }
            # Set active personality based on current mode
            self._active_personality = self._personalities.get(self.mode)
        except Exception as e:
            # Graceful degradation: if personality system fails, core.py works as before
            self._status_print(f"⚠️  Personality registration failed: {e}", "debug")
            self.services = None
            self._personalities = {}
            self._active_personality = None

    # Commands whose output should be added to conversation history
    # so the LLM can reason about tool results
    COMMANDS_FEED_TO_LLM = {
        "/run", "/grep", "/find", "/read", "/write", "/edit",
        "/git", "/code", "/analyze", "/fix", "/diff", "/test",
        "/glob", "/ls", "/search", "/browse", "/links", "/crawl", "/webmap",
    }

    # Commands that should NOT feed to LLM (UI-only)
    # /help, /clear, /think, /debug, /save, /load, /history,
    # /quit, /exit, /models, /switch, /verbose, /context, /compact

    @staticmethod
    def _truncate_middle(text: str, max_chars: int = 30000) -> str:
        """Truncate long output using middle-truncation strategy.

        Preserves the beginning and end of output (most useful parts)
        while removing the middle.
        """
        if len(text) <= max_chars:
            return text
        keep = max_chars // 2
        removed = len(text) - max_chars
        return (
            text[:keep]
            + f"\n\n... [{removed:,} chars truncated] ...\n\n"
            + text[-keep:]
        )

    def _status_print(self, message: str, level: str = "info") -> None:
        """
        Print status message with verbosity control.

        Args:
            message: Message to print
            level: Message level - "critical", "important", "info", "debug"

        Levels:
            critical  - Always shown (errors, failures)
            important - Always shown (key state changes)
            info      - Hidden unless verbose; shown as single-line status in tty
            debug     - Hidden unless verbose; silently buffered
        """
        # Store message in buffer for potential later display (/verbose dump)
        self.status_buffer.append({
            "timestamp": time.time(),
            "message": message,
            "level": level
        })
        # Keep buffer size manageable
        if len(self.status_buffer) > 100:
            self.status_buffer = self.status_buffer[-50:]

        # Verbose mode ON → print everything
        if self.verbose_mode:
            self._safe_print(message)
            return

        # Verbose mode OFF (default) → only show critical/important
        if level in ("critical", "important"):
            self._safe_print(message)
        # info/debug are silently buffered; viewable via /verbose dump

    def add_status_message(self, message: str, level: str = "info") -> None:
        """Add a status message to the buffer without printing."""
        import time
        self.status_buffer.append({
            "timestamp": time.time(),
            "message": message,
            "level": level
        })
        # Keep buffer size manageable
        if len(self.status_buffer) > 100:
            self.status_buffer = self.status_buffer[-50:]

    def get_status_messages(self, level: Optional[str] = None, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get status messages from buffer, optionally filtered by level and limited."""
        messages = self.status_buffer
        if level:
            messages = [msg for msg in messages if msg["level"] == level]
        # Reverse chronological order (most recent first)
        messages = list(reversed(messages))
        if limit:
            messages = messages[:limit]
        return messages

    def clear_status_buffer(self) -> None:
        """Clear all status messages from buffer."""
        self.status_buffer = []

    def update_current_status(self, status: str) -> None:
        """Update the current single-line status display."""
        import time
        self.current_status = status
        self.last_status_update = time.time()

    def _clear_status_line(self) -> None:
        """Clear the single-line status display if active."""
        import sys
        if self.current_status and sys.stdout.isatty():
            # Move to beginning of line, clear it
            sys.stdout.write("\r\033[K")
            sys.stdout.flush()
            self.current_status = ""

    def _safe_print(self, message: str) -> None:
        """Print message safely, handling Unicode encoding errors on Windows."""
        import sys
        # Clear any active status line before printing
        self._clear_status_line()
        try:
            print(message)
        except UnicodeEncodeError:
            # Fallback: replace common emojis with ASCII equivalents
            replacements = {
                "🔧": "[FIX]",
                "📝": "[NOTE]",
                "❌": "[ERROR]",
                "🌐": "[WEB]",
                "🚀": "[RUN]",
                "📁": "[DIR]",
                "⏱️": "[TIME]",
                "📤": "[OUT]",
                "🔍": "[SEARCH]",
                "💡": "[INFO]",
                "📄": "[FILE]",
                "📭": "[EMPTY]",
                "🔧": "[TOOL]",
                "📝": "[DOC]",
                "❌": "[FAIL]",
                "✅": "[OK]",
                "⚠️": "[WARN]",
                "⏳": "[WAIT]",
                "🔄": "[GIT]",
                "🧪": "[TEST]",
                "🤖": "[BOT]",
            }
            safe_message = message
            for emoji, ascii_repl in replacements.items():
                safe_message = safe_message.replace(emoji, ascii_repl)
            # Also strip any other non-ASCII characters
            safe_message = safe_message.encode('ascii', 'ignore').decode('ascii')
            print(safe_message)

    def switch_mode(self, mode: str, persist: bool = True) -> bool:
        """Switch between chat, coding, and fin modes.

        Args:
            mode: Target mode ('chat', 'coding', or 'fin')
            persist: Whether to save the mode change to config file (default: True)
        """
        if mode not in ("chat", "coding", "fin"):
            self._safe_print(f"❌ Invalid mode: {mode}. Use 'chat', 'coding', or 'fin'.")
            return False

        old_mode = self.mode
        self.mode = mode

        # Switch the config manager to the new mode
        agent_config.switch_mode(mode)

        # Reload settings from the now-active mode config
        new_prompt = agent_config.system_prompt
        if new_prompt:
            self.conversation_history = [msg for msg in self.conversation_history if msg["role"] != "system"]
            self.add_to_history("system", new_prompt)

        # NOTE: Vault re-injection, shared memory re-injection, and skill
        # compatibility checks are now handled by each personality's on_activate().
        # See: chat.py, coding.py, finance.py

        if self.interpreter:
            self.interpreter.confidence_threshold = agent_config.natural_language_confidence_threshold

        self.safety_confirm_file_operations = agent_config.safety_confirm_file_operations
        self.show_status_bar = agent_config.show_status_bar

        # Update model for the new mode
        self.model = agent_config.model
        self.fallback_model = agent_config.fallback_model
        self.thinking_mode = agent_config.thinking_mode
        provider = self._resolve_provider(self.model)
        self.base_url = provider["base_url"]

        # NOTE: Workspace init, finance init, and search domain sync are now
        # handled by each personality's on_activate().

        # ── Activate personality (owns mode-specific setup) ────────────
        if self._personalities and mode in self._personalities:
            old_personality = self._active_personality
            if old_personality:
                try:
                    old_personality.on_deactivate()
                except Exception:
                    pass  # Non-critical
            self._active_personality = self._personalities[mode]
            try:
                self._active_personality.on_activate()
            except Exception as e:
                # Personality activation failed — fall back to manual init
                self._status_print(f"Personality on_activate failed: {e}", "warning")
                self._fallback_mode_init(mode)
            self._rebuild_command_handlers()

        if old_mode != mode:
            self._safe_print(f"🔄 Switched from {old_mode} to {mode} mode.")

        return True

    def _fallback_mode_init(self, mode: str):
        """Fallback mode initialization if personality on_activate() fails.

        Replicates the essential setup that personalities normally handle,
        so the agent remains functional even if a personality class is broken.
        """
        # Search domain
        search_domain = {"fin": "finance", "coding": "code"}.get(mode, "general")
        if hasattr(self, 'searcher') and hasattr(self.searcher, 'set_domain'):
            self.searcher.set_domain(search_domain)

        # Workspace (coding only)
        if mode == "coding":
            self._initialize_workspace_manager()

        # Finance subsystems
        if mode == "fin":
            self._initialize_finance_subsystems()

        # Vault context
        if self._vault_reader and self._vault_reader.vault_exists():
            try:
                vault_context = self._vault_reader.get_startup_context(mode=mode)
                if vault_context:
                    self.add_to_history("system", vault_context)
            except Exception:
                pass

        # Shared memory
        if self._shared_memory:
            try:
                mem_context = self._shared_memory.get_context_summary(mode=mode, max_tokens=500)
                if mem_context:
                    self.add_to_history("system",
                        f"# User Context (from cross-personality memory)\n\n{mem_context}")
            except Exception:
                pass

        # Skill compatibility
        if self._active_skill and mode not in self._active_skill.modes:
            self._safe_print(
                f"🔴 Deactivated skill '{self._active_skill.name}' (not available in {mode} mode)")
            self._active_skill = None

    def _initialize_finance_subsystems(self):
        """Lazy-init finance components when switching to fin mode."""
        if hasattr(self, '_finance_components') and self._finance_components:
            return  # already initialized

        try:
            from agent.finance import get_finance_components
            from agent_config import agent_config as cfg
            self._finance_components = get_finance_components(cfg)
        except ImportError as e:
            self._safe_print(f"⚠️  Finance module not fully available: {e}")
            self._safe_print("   Install finance deps: pip install -e '.[finance]'")
            self._finance_components = {}
        except Exception as e:
            self._safe_print(f"⚠️  Finance init error: {e}")
            self._finance_components = {}

    def toggle_verbose_mode(self) -> bool:
        """Toggle verbose mode to show/hide detailed debug messages.
        Returns new verbose mode status."""
        self.verbose_mode = not self.verbose_mode
        return self.verbose_mode

    def get_status_info(self) -> Dict[str, any]:
        """Get current status information for status bar."""
        status = {
            "mode": self.mode,
            "token_usage": self.context_manager.count_conversation_tokens() if hasattr(self, 'context_manager') else 0,
            "pending_changes": len(self.code_changes_pending),
            "recent_files": []
        }
        if self.mode == "coding" and self.workspace_manager:
            try:
                status["recent_files"] = self.workspace_manager.get_recent_files(3)
            except:
                pass
        return status

    def _initialize_workspace_manager(self):
        """Lazy initialization of workspace manager for coding mode."""
        if self.workspace_manager is None:
            try:
                from .workspace_manager import WorkspaceManager
                self.workspace_manager = WorkspaceManager()
                self._safe_print("📁 Workspace manager initialized.")
            except ImportError:
                self._safe_print("⚠️  Workspace manager not available. Install optional dependencies.")
                self.workspace_manager = None

    # Add get_code_change_instructions method here:
    def get_code_change_instructions(self) -> str:
        """Instructions for AI to propose code changes"""
        return """
📝 HOW TO PROPOSE CODE CHANGES:

When you identify code that needs fixing, use this format:

PROPOSED CHANGE:
File: /path/to/file.py
Description: Brief description of the change
Old Code: [exact code to replace]
New Code: [replacement code]
Line: 42 (optional line number)

I will add this to pending changes and ask for user confirmation.

Available commands for the user:
• /code changes - View pending changes
• /code apply - Apply changes (with confirmation)
• /code clear - Clear pending changes
• /code scan - Scan a codebase
• /code read - Read a specific file
• /code analyze - Analyze file structure

Remember: Always ask for permission before making changes!
"""
    
    
    # NEW METHODS FOR MODEL LISTING
    def list_models(self, force_refresh: bool = False, provider: str = None) -> List[Dict[str, Any]]:
        """
        List available models from the current provider (or a specific one).

        Args:
            force_refresh: If True, force refresh the model list cache
            provider: Specific provider name (e.g. "deepseek", "zai"). If None, uses current model's provider.

        Returns:
            List of model dictionaries with id, created, and owned_by fields
        """
        # Use cache if available and not forcing refresh
        if not force_refresh and self.available_models_cache:
            return self.available_models_cache

        if provider:
            prov = self._PROVIDERS.get(provider, {})
            models_url = prov.get("models_url", self.models_url)
            api_key = os.getenv(prov.get("env_key", ""), self.api_key)
        else:
            resolved = self._resolve_provider()
            models_url = resolved["models_url"]
            api_key = resolved["api_key"] or self.api_key

        headers = {
            "Authorization": f"Bearer {api_key}"
        }

        try:
            response = requests.get(models_url, headers=headers, timeout=10)
            response.raise_for_status()

            models_data = response.json()
            if isinstance(models_data, dict) and "data" in models_data:
                self.available_models_cache = models_data["data"]
                return self.available_models_cache
            elif isinstance(models_data, list):
                self.available_models_cache = models_data
                return self.available_models_cache
            else:
                return self._get_fallback_models(provider)

        except requests.exceptions.RequestException as e:
            self._status_print(f"Error fetching models from {models_url}: {e}", "debug")
            return self._get_fallback_models(provider)

    def _get_fallback_models(self, provider: str = None) -> List[Dict[str, Any]]:
        """Return fallback models when API call fails."""
        if provider and provider in self._PROVIDERS:
            return list(self._PROVIDERS[provider]["fallback_models"])
        # Default: return current provider's fallback
        resolved = self._resolve_provider()
        prov = self._PROVIDERS.get(resolved["name"], {})
        return list(prov.get("fallback_models", []))

    def print_models(self, force_refresh: bool = False) -> None:
        """
        Print available models from ALL configured providers.
        """
        current_provider = self._resolve_provider()["name"]

        print("\n" + "="*60)
        print("AVAILABLE MODELS")
        print("="*60)

        total = 0
        for prov_name, prov_config in self._PROVIDERS.items():
            api_key = os.getenv(prov_config["env_key"], "")
            has_key = bool(api_key)
            status = "✓" if has_key else "✗ (no API key)"

            # Section header
            label = prov_name.upper()
            print(f"\n{'🟢' if has_key else '🔴'} {label} {status}")

            if has_key:
                models = self.list_models(force_refresh=force_refresh, provider=prov_name)
            else:
                models = prov_config["fallback_models"]

            for m in models:
                model_id = m.get("id", m) if isinstance(m, dict) else m
                marker = " ◀ current" if model_id == self.model else ""
                s = self._get_model_spec(model_id)
                ctx_k = s["max_context"] // 1000
                out_k = s["max_output"] // 1000
                print(f"  • {model_id:<24} {ctx_k}K ctx / {out_k}K out{marker}")
            total += len(models)

        print("\n" + "-"*60)
        spec = self._get_model_spec(self.model)
        print(f"Current: {self.model} [{current_provider}]  "
              f"(ctx {spec['max_context']//1000}K, out {spec['max_output']//1000}K, "
              f"default {spec['default_max']//1000}K)")
        print(f"Switch:  /switch <model_id>  (e.g. /switch glm-5)")
        print("="*60 + "\n")

    def set_model(self, model_id: str) -> bool:
        """
        Switch to a different model (may change provider).

        Args:
            model_id: The model ID to switch to (e.g. "deepseek-chat", "glm-5")

        Returns:
            True if model was switched successfully, False otherwise
        """
        # Resolve provider for the requested model
        new_provider = self._resolve_provider(model_id)

        # Check API key for the target provider
        if not new_provider["api_key"]:
            env_key = self._PROVIDERS.get(new_provider["name"], {}).get("env_key", "???")
            print(f"✗ No API key for provider '{new_provider['name']}'. Set {env_key} in your .env file.")
            return False

        # Check if model is in the available list (try current provider first, then all)
        models = self.list_models()
        available_ids = [m["id"] for m in models]

        # Also include fallback models from the target provider
        target_prov = self._PROVIDERS.get(new_provider["name"], {})
        fallback_ids = [m["id"] for m in target_prov.get("fallback_models", [])]
        all_known = set(available_ids) | set(fallback_ids)

        if model_id not in all_known:
            # Model not in known lists — but allow it anyway with a warning
            # (z.ai may have models not in the fallback list)
            print(f"⚠ Model '{model_id}' not in known model lists — trying anyway.")

        old_model = self.model
        old_provider_name = self._resolve_provider(old_model)["name"]
        self.model = model_id

        # Update provider URLs if provider changed
        self.base_url = new_provider["base_url"]
        self.models_url = new_provider["models_url"]

        # Clear model cache (different provider = different model list)
        if new_provider["name"] != old_provider_name:
            self.available_models_cache = None

        # Show new model specs
        spec = self._get_model_spec(model_id)
        spec_info = f"ctx {spec['max_context']//1000}K, out {spec['max_output']//1000}K"

        # Update configuration file
        try:
            from agent_config import agent_config
            success = agent_config.update_value("agent.model", model_id)
            provider_label = f" [{new_provider['name']}]" if new_provider["name"] != "deepseek" else ""
            if success:
                print(f"✓ Model switched: '{old_model}' → '{model_id}'{provider_label} ({spec_info}) (saved)")
            else:
                print(f"✓ Model switched: '{old_model}' → '{model_id}'{provider_label} ({spec_info}) (not saved)")
        except ImportError:
            print(f"✓ Model switched: '{old_model}' → '{model_id}' ({spec_info})")

        return True

    def with_model(self, model_id: str, func: Callable, *args, **kwargs):
        """
        Temporarily switch to a model, execute a function, then restore original model.
        Does NOT update configuration file.

        Args:
            model_id: Model ID to temporarily switch to
            func: Callable to execute with temporary model
            *args, **kwargs: Passed to func

        Returns:
            Result of func call
        """
        models = self.list_models()
        available_ids = [m["id"] for m in models]
        if model_id not in available_ids:
            raise ValueError(f"Model '{model_id}' not available")

        original_model = self.model
        try:
            if self.model != model_id:
                self.model = model_id
                # Optionally notify user
                print(f"[Model] Temporarily switched to '{model_id}' for this task")
            result = func(*args, **kwargs)
        finally:
            if self.model != original_model:
                self.model = original_model
                print(f"[Model] Restored model to '{original_model}'")
        return result

    def generate_completion(self, messages, temperature=0.7, max_tokens=2048):
        """Generate a completion using the current model (non-streaming)."""
        provider = self._resolve_provider()
        spec = self._get_model_spec(self.model)
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {provider['api_key'] or self.api_key}"
        }
        # Clamp max_tokens to model's hard output limit
        max_tokens = min(max_tokens, spec["max_output"])
        # Context validation using model-specific context window
        temp_context = ContextManager(messages)
        total_tokens = temp_context.count_conversation_tokens()
        max_context = spec["max_context"]
        if total_tokens + max_tokens > max_context:
            new_max = max(1, max_context - total_tokens)
            self._status_print(f"⚠️  Context limit: reducing max_tokens from {max_tokens} to {new_max}", "info")
            max_tokens = new_max
        elif total_tokens > agent_config.context_warning_threshold * max_context:
            self._status_print(f"⚠️  Context warning: {total_tokens}/{max_context} tokens used", "info")

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        # Only add thinking param for providers that support it (DeepSeek)
        if self.thinking_enabled and provider.get("name") == "deepseek":
            payload["thinking"] = {"type": "enabled"}

        try:
            import requests
            request_url = provider["base_url"]
            response = requests.post(request_url, headers=headers, json=payload, timeout=60)
            response.raise_for_status()
            result = response.json()
            if "choices" in result and result["choices"]:
                return result["choices"][0]["message"]["content"]
            else:
                raise ValueError("Unexpected response format")
        except Exception as e:
            return f"Error generating completion: {str(e)}"

    # ── Smart search routing ────────────────────────────────────────────

    # Keywords that indicate the user is talking about the local codebase
    _CODE_CONTEXT_KEYWORDS = {
        "codebase", "code base", "this repo", "this project", "this file",
        "these files", "my code", "our code", "source code", "in the code",
        "in this directory", "in this folder", "locally", "local files",
    }

    # Keywords that indicate a comprehension/exploration task (→ pass to LLM)
    _COMPREHENSION_KEYWORDS = {
        "understand", "explain", "analyze", "summarize", "overview",
        "architecture", "structure", "how does", "what does", "walk me through",
        "describe", "explore", "review", "audit", "breakdown", "break down",
    }

    def _classify_search_intent(self, query: str):
        """Classify a /search query into one of three intents.

        Returns:
            "llm"   — comprehension task, pass to LLM as regular prompt
            "grep"  — has a concrete pattern, use local grep
            "web"   — no local intent detected, do web search
        """
        q = query.lower()

        is_about_code = any(kw in q for kw in self._CODE_CONTEXT_KEYWORDS)
        is_comprehension = any(kw in q for kw in self._COMPREHENSION_KEYWORDS)

        if is_about_code:
            if is_comprehension:
                return "llm"  # "understand this codebase" → LLM task
            # Has code context but not comprehension → try to extract a grep pattern
            pattern = self._extract_grep_pattern(query)
            if pattern and len(pattern) >= 2:
                return "grep"
            # Pattern too vague → let LLM handle it
            return "llm"

        return "web"

    def _extract_grep_pattern(self, query: str) -> str:
        """Extract a grep-able pattern from a natural language query."""
        q = query.lower()
        # Strip context keywords
        for noise in sorted(self._CODE_CONTEXT_KEYWORDS, key=len, reverse=True):
            q = q.replace(noise, "")
        # Strip filler words
        for filler in ["search", "find", "look for", "in", "for", "the", "this", "my"]:
            q = q.replace(filler, "")
        return q.strip().strip("\"'")

    # ── P3-C: Extracted to general_commands.py — thin delegates for backward compat ──

    def handle_search(self, query: str) -> str:
        """Delegate to general_commands module."""
        from agent.services.general_commands import handle_search
        return handle_search(self, query)

    def handle_auto_command(self, subcommand: str) -> Optional[str]:
        """Delegate to general_commands module."""
        from agent.services.general_commands import handle_auto_command
        return handle_auto_command(self, subcommand)

    def handle_mode_command(self, command: str) -> Optional[str]:
        """Handle /mode command for switching between chat, coding, and fin modes."""
        command = command.strip().lower()
        if not command or command == "status":
            return f"Current mode: {self.mode}"
        elif command == "chat":
            success = self.switch_mode("chat")
            return "Switched to chat mode." if success else "Failed to switch to chat mode."
        elif command == "coding":
            success = self.switch_mode("coding")
            return "Switched to coding mode." if success else "Failed to switch to coding mode."
        elif command == "fin":
            success = self.switch_mode("fin")
            return "Switched to fin mode." if success else "Failed to switch to fin mode."
        elif command == "help":
            return (
                "/mode command usage:\n"
                "  /mode chat      - Switch to chat mode\n"
                "  /mode coding    - Switch to coding mode\n"
                "  /mode status    - Show current mode\n"
                "  /mode help      - Show this help"
            )
        else:
            return "Invalid mode. Use 'chat', 'coding', 'status', or 'help'."

    def handle_skills_command(self, command: str) -> Optional[str]:
        """Delegate to general_commands module."""
        from agent.services.general_commands import handle_skills_command
        return handle_skills_command(self, command)

    def handle_skill_command(self, command: str) -> Optional[str]:
        """Delegate to general_commands module."""
        from agent.services.general_commands import handle_skill_command
        return handle_skill_command(self, command)

    def discover_mcp_servers(self) -> List[Dict[str, str]]:
        """
        Discover MCP servers in standard locations.

        Returns:
            List of server info dictionaries
        """
        # Placeholder implementation
        # In a real implementation, this would scan ~/.claude/mcp-servers/
        # and ./.claude/mcp-servers/ for server configurations
        servers = []
        # Check for common MCP server locations
        import os
        import json
        from pathlib import Path

        locations = [
            Path.home() / ".claude" / "mcp-servers",
            Path.cwd() / ".claude" / "mcp-servers",
        ]

        for location in locations:
            if location.exists() and location.is_dir():
                for item in location.iterdir():
                    if item.is_file() and item.suffix == '.json':
                        try:
                            with open(item, 'r') as f:
                                config = json.load(f)
                            servers.append({
                                'name': config.get('name', item.stem),
                                'description': config.get('description', ''),
                                'path': str(item)
                            })
                        except:
                            pass

        # Add built-in skills
        builtin_skills = [
            {'name': 'code_analyzer', 'description': 'Code analysis and refactoring'},
            {'name': 'file_operations', 'description': 'File read/write/edit'},
            {'name': 'web_search', 'description': 'Web search via DuckDuckGo'},
        ]
        servers.extend(builtin_skills)

        return servers

    def handle_models_command(self, command: str) -> Optional[str]:
        """Delegate to general_commands module."""
        from agent.services.general_commands import handle_models_command
        return handle_models_command(self, command)

    def handle_task_command(self, command: str) -> Optional[str]:
        """Delegate to general_commands module."""
        from agent.services.general_commands import handle_task_command
        return handle_task_command(self, command)

    def handle_plan_command(self, command: str) -> Optional[str]:
        """Delegate to general_commands module."""
        from agent.services.general_commands import handle_plan_command
        return handle_plan_command(self, command)

    def handle_execute_command(self, command: str) -> Optional[str]:
        """Delegate to general_commands module."""
        from agent.services.general_commands import handle_execute_command
        return handle_execute_command(self, command)

    def handle_switch_command(self, command: str) -> Optional[str]:
        """Delegate to general_commands module."""
        from agent.services.general_commands import handle_switch_command
        return handle_switch_command(self, command)

    # ── LLM-analysis commands (summarize, translate, generate, reason, debug, explain, refactor)
    # Real implementations moved to SharedCommandsMixin (agent/services/shared_commands.py).
    # Thin wrappers kept for backward compat — tests call self.agent.handle_X_command().

    def handle_summarize_command(self, command: str) -> Optional[str]:
        if hasattr(self, '_active_personality') and self._active_personality:
            return self._active_personality._shared_handle_summarize_command(command)
        if not command or not command.strip():
            return "Usage: /summarize <text>"
        prompt = f"Summarize the following content concisely:\n\n{command.strip()}"
        try:
            return f"📝 Summary:\n{self.generate_completion([{'role': 'user', 'content': prompt}], temperature=0.3, max_tokens=1000)}"
        except Exception as e:
            return f"❌ Failed to generate summary: {e}"

    def handle_translate_command(self, command: str) -> Optional[str]:
        if hasattr(self, '_active_personality') and self._active_personality:
            return self._active_personality._shared_handle_translate_command(command)
        return "Usage: /translate <text> [to <language>]"

    def handle_generate_command(self, command: str) -> Optional[str]:
        if hasattr(self, '_active_personality') and self._active_personality:
            return self._active_personality._shared_handle_generate_command(command)
        return "Usage: /generate <prompt>"

    def handle_reason_command(self, command: str) -> Optional[str]:
        if hasattr(self, '_active_personality') and self._active_personality:
            return self._active_personality._shared_handle_reason_command(command)
        return "Usage: /reason <problem>"

    def handle_debug_command(self, command: str) -> Optional[str]:
        if hasattr(self, '_active_personality') and self._active_personality:
            return self._active_personality._shared_handle_debug_command(command)
        return "Usage: /debug <file_path> or /debug <code snippet>"

    def handle_explain_command(self, command: str) -> Optional[str]:
        if hasattr(self, '_active_personality') and self._active_personality:
            return self._active_personality._shared_handle_explain_command(command)
        return "Usage: /explain <file_path> or /explain <code snippet>"

    def handle_refactor_command(self, command: str) -> Optional[str]:
        if hasattr(self, '_active_personality') and self._active_personality:
            return self._active_personality._shared_handle_refactor_command(command)
        return "Usage: /refactor <file_path>"

    def handle_grep_command(self, command: str) -> Optional[str]:
        """
        Handle /grep command to search for text across files.
        Usage: /grep <pattern> [path]
        """
        if not command.strip():
            return "Usage: /grep <pattern> [path]"

        parts = command.strip().split()
        pattern = parts[0]
        path = parts[1] if len(parts) > 1 else "."

        # Use ripgrep if available, else Python regex
        try:
            import subprocess
            result = subprocess.run(
                ["rg", "-n", "-i", pattern, path],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                output = result.stdout
                if not output.strip():
                    return f"🔍 No matches for pattern '{pattern}' in {path}"
                return f"🔍 Grep results for '{pattern}' in {path}:\n{output}"
            else:
                # Fallback to Python regex
                return self._grep_fallback(pattern, path)
        except (subprocess.SubprocessError, FileNotFoundError):
            return self._grep_fallback(pattern, path)

    def _grep_fallback(self, pattern: str, path: str) -> str:
        """Fallback grep using Python regex."""
        import os
        import re
        matches = []
        pattern_re = re.compile(pattern, re.IGNORECASE)
        for root, dirs, files in os.walk(path):
            for file in files:
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        for line_num, line in enumerate(f, 1):
                            if pattern_re.search(line):
                                matches.append(f"{file_path}:{line_num}: {line.rstrip()}")
                except:
                    continue
        if not matches:
            return f"🔍 No matches for pattern '{pattern}' in {path}"
        return f"🔍 Grep results for '{pattern}' in {path} (Python fallback):\n" + "\n".join(matches[:50])  # Limit output

    def handle_find_command(self, command: str) -> Optional[str]:
        """
        Handle /find command to find files matching pattern.
        Usage: /find <pattern> [path]
        """
        if not command.strip():
            return "Usage: /find <pattern> [path]"

        parts = command.strip().split()
        pattern = parts[0]
        path = parts[1] if len(parts) > 1 else "."

        import os
        import fnmatch
        matches = []
        for root, dirs, files in os.walk(path):
            for name in files + dirs:
                if fnmatch.fnmatch(name, pattern):
                    full_path = os.path.join(root, name)
                    matches.append(full_path)
        if not matches:
            return f"📭 No files/directories matching '{pattern}' in {path}"
        return f"📂 Found {len(matches)} matches for '{pattern}' in {path}:\n" + "\n".join(matches[:50])

    def handle_verbose_command(self, command: str) -> Optional[str]:
        """
        Handle /verbose command to toggle verbose debug output.
        Usage: /verbose [on|off|toggle]
        """
        cmd = command.strip().lower()
        if cmd == "on":
            self.verbose_mode = True
            status = "ENABLED"
        elif cmd == "off":
            self.verbose_mode = False
            status = "DISABLED"
        elif cmd == "toggle" or cmd == "":
            self.toggle_verbose_mode()
            status = "TOGGLED"
        else:
            return f"❌ Invalid option: {cmd}. Use /verbose [on|off|toggle]"

        if self.verbose_mode and self.status_buffer:
            result = [f"🔊 Verbose mode: {status}", "📋 Recent debug messages:"]
            for entry in self.status_buffer[-10:]:  # Show last 10 messages
                result.append(f"  [{entry['level']}] {entry['message']}")
            return "\n".join(result)
        return f"🔊 Verbose mode: {status}"

    def handle_clear_command(self, command: str) -> Optional[str]:
        """
        Handle /clear command to clear conversation history.
        Usage: /clear
        """
        self.clear_history()
        return "🗑️ Conversation history cleared."

    def handle_history_command(self, command: str) -> Optional[str]:
        """
        Handle /history command to show conversation history.
        Usage: /history
        """
        if not self.conversation_history:
            return "📭 No conversation history."

        result = ["📜 Conversation History:"]
        for i, msg in enumerate(self.conversation_history, 1):
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            preview = content[:100] + "..." if len(content) > 100 else content
            result.append(f"{i}. [{role}] {preview}")
        return "\n".join(result)

    def handle_context_command(self, command: str) -> Optional[str]:
        """Delegate to general_commands module."""
        from agent.services.general_commands import handle_context_command
        return handle_context_command(self, command)

    def handle_think_command(self, command: str) -> Optional[str]:
        """
        Handle /think command to toggle thinking mode.
        Usage: /think
        """
        self.toggle_thinking_mode()
        status = "enabled" if self.thinking_enabled else "disabled"
        return f"🤔 Thinking mode {status}."

    def handle_quit_command(self, command: str) -> Optional[str]:
        """
        Handle /quit command to exit (signal to CLI).
        Usage: /quit or /exit
        """
        # Return special message that CLI can interpret
        return "🛑 Quit command received. Use Ctrl+C or type /quit in the CLI to exit."

    def handle_exit_command(self, command: str) -> Optional[str]:
        """
        Handle /exit command (alias for /quit).
        """
        return self.handle_quit_command(command)

    # ── Vault: session journal ──────────────────────────────────────────

    def write_session_journal(self):
        """Write a journal entry for the current session to the vault.

        Called by the CLI on normal exit (Ctrl+D, /quit) and Ctrl+C.
        Also triggers vault pattern promotion (SharedMemory → MEMORY.md).
        Gracefully no-ops if vault is disabled or unavailable.
        """
        if os.environ.get("NEOMIND_DISABLE_VAULT") or self._vault_writer is None:
            return
        try:
            # Gather lightweight stats from conversation history
            user_msgs = [m for m in self.conversation_history if m.get("role") == "user"]
            assistant_msgs = [m for m in self.conversation_history if m.get("role") == "assistant"]
            tasks = [{"description": f"Handled {len(user_msgs)} user messages", "status": "done"}]
            errors = [m.get("content", "")[:120] for m in self.conversation_history
                      if m.get("role") == "system" and "error" in m.get("content", "").lower()][:5]
            learnings = []  # Populated by future pattern extraction
            self._vault_writer.write_journal_entry(
                mode=self.mode,
                tasks=tasks,
                errors=errors,
                learnings=learnings,
                tokens_used=getattr(self, '_total_tokens_used', 0),
            )
        except Exception:
            pass  # Non-fatal — never block exit

        # ── Evolution: ensure daily audit runs before session end ──────────
        if self.evolution_scheduler:
            try:
                actions = self.evolution_scheduler.on_session_end()
                if actions:
                    for action in actions:
                        self._status_print(f"✨ {action}", "debug")
            except Exception:
                pass  # Non-fatal — never block exit

        # ── Vault Promoter: SharedMemory → MEMORY.md ─────────────────
        # Promote patterns with 3+ occurrences to long-term vault memory.
        # Runs at end of each session (lightweight — reads pattern counts, appends if needed).
        if self._shared_memory and self._vault_writer:
            try:
                from agent.vault.promoter import promote_patterns
                promoted = promote_patterns(self._shared_memory, self._vault_writer)
                if promoted > 0:
                    self._status_print(f"Promoted {promoted} patterns to MEMORY.md", "debug")
            except Exception:
                pass  # Non-fatal — never block exit

    # NEW: Webpage reading capabilities

    def read_webpage(self, url: str, max_length: int = 20000) -> str:
        """
        Read webpage content using multiple strategies for maximum compatibility
        """
        # Normalize URL
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url

        print(f"🌐 Fetching: {url}")

        # Try multiple strategies in order
        # Try multiple strategies in order
        strategies = []
        if HAS_TRAFILATURA:
            strategies.append(self._try_trafilatura)
        strategies.append(self._try_beautifulsoup)
        if HAS_HTML2TEXT:
            strategies.append(self._try_html2text)
        if HAS_REQUESTS_HTML:
            strategies.append(self._try_requests_html)
        strategies.append(self._try_playwright)
        strategies.append(self._try_fallback)
        
        best_result = None
        best_score = 0

        for strategy in strategies:
            try:
                content = strategy(url, max_length)
                if content:
                    # Score the content quality
                    score = self._score_content(content)
                    if score > best_score:
                        best_result = content
                        best_score = score

                    # If we have good content, stop trying
                    if score > 50:  # Good enough threshold
                        break
            except Exception as e:
                continue  # Try next strategy

        if best_result:
            return self._format_result(url, best_result, best_score)
        else:
            return self.formatter.error(f"Failed to extract content from {url}. All strategies failed.")

    # ── Web content extraction (delegated to agent.web.content_extraction) ──
    # Thin wrappers preserved for backward compat — all real logic is now in
    # agent/web/content_extraction.py (Tier 2C extraction).

    def _try_trafilatura(self, url: str, max_length: int) -> Optional[str]:
        from agent.web.content_extraction import try_trafilatura
        return try_trafilatura(url, max_length)

    def _try_beautifulsoup(self, url: str, max_length: int) -> Optional[str]:
        from agent.web.content_extraction import try_beautifulsoup
        return try_beautifulsoup(url, max_length)

    def _try_html2text(self, url: str, max_length: int) -> Optional[str]:
        from agent.web.content_extraction import try_html2text
        return try_html2text(url, max_length, getattr(self, 'html_converter', None))

    def _try_requests_html(self, url: str, max_length: int) -> Optional[str]:
        from agent.web.content_extraction import try_requests_html
        return try_requests_html(url, max_length, getattr(self, 'session', None))

    # ── Browser sync bridge ─────────────────────────────────────────
    def _browser_sync(self, command: str, args: List[str] = None) -> str:
        """Sync wrapper for async BrowserDaemon — mirrors search_sync() pattern."""
        if not self._browser_loop:
            self._browser_loop = asyncio.new_event_loop()

        from agent.browser.daemon import get_browser

        async def _run():
            browser = await get_browser()
            return await browser.execute(command, args or [])

        return self._browser_loop.run_until_complete(_run())

    def _try_playwright(self, url: str, max_length: int) -> Optional[str]:
        """Fallback to headless Chromium for JS-rendered pages."""
        try:
            result = self._browser_sync("goto", [url])
            if result and "Error" in result:
                return None
            text = self._browser_sync("text", [])
            if text and len(text.strip()) > 100:
                text = self._clean_text(text)
                return text[:max_length]
            return None
        except Exception:
            return None

    def _try_fallback(self, url: str, max_length: int) -> Optional[str]:
        from agent.web.content_extraction import try_fallback
        return try_fallback(url, max_length)

    def _score_content(self, content: str) -> int:
        from agent.web.content_extraction import score_content
        return score_content(content)

    def _format_result(self, url: str, content: str, score: int) -> str:
        from agent.web.content_extraction import format_result
        return format_result(url, content, score)

    def _clean_text(self, text: str) -> str:
        from agent.web.content_extraction import clean_text
        return clean_text(text)

    def handle_read_command(self, url_or_command: str) -> str:
        """
        Handle /read command for webpage reading with enhanced capabilities
        Automatically adds content to conversation history for AI awareness
        """
        if not url_or_command or url_or_command.strip() == "":
            help_text = """
    📚 /read Command Usage:
    /read <url>                     - Read webpage content and make AI aware of it
    /read <file_path>               - Read local file (supports line ranges: file.py:10-20)
    /read --debug <url>            - Show debugging info (doesn't add to AI memory)
    /read --strategy <n> <url>     - Use specific strategy (0-4)
    /read --no-ai <url|file>       - Read without adding to AI memory

    Strategies (for webpages only):
    0: trafilatura (best for articles)
    1: beautifulsoup (smart extraction)
    2: html2text (markdown conversion)
    3: requests-html (JavaScript sites)
    4: fallback (basic extraction)

    Note: By default, all content is added to AI memory so you can ask questions about it.
            """.strip()
            return help_text

        parts = url_or_command.split()

        # Parse flags
        debug = False
        strategy = None
        no_ai = False  # New flag to prevent adding to AI memory
        url = None

        # Parse flags
        i = 0
        while i < len(parts):
            if parts[i] == '--debug':
                debug = True
                parts.pop(i)
            elif parts[i] == '--strategy':
                if i + 1 < len(parts):
                    try:
                        strategy = int(parts[i + 1])
                        parts.pop(i)  # Remove --strategy
                        parts.pop(i)  # Remove the number
                    except ValueError:
                        return self.formatter.error(f"Invalid strategy number. Must be 0-4.")
                else:
                    return self.formatter.error("Missing strategy number. Use: /read --strategy <0-4> <url>")
            elif parts[i] == '--no-ai':
                no_ai = True
                parts.pop(i)
            else:
                i += 1

        # The remaining parts should form the URL
        if not parts:
            return self.formatter.error("Please provide a URL")
        
        url = ' '.join(parts)

        # ── Follow-up from /links: "/read 3" reads link #3 ──────────
        if url.isdigit() and self._last_links:
            link_num = int(url)
            if link_num in self._last_links:
                url = self._last_links[link_num]
                print(f"🔗 Following link #{link_num}: {url}")
            else:
                return self.formatter.error(
                    f"Link #{link_num} not found. Available: {min(self._last_links)}–{max(self._last_links)}"
                )

        # Check if this is a local file path
        if self._is_likely_file_path(url):
            return self._handle_file_read(url, no_ai)

        print(f"🌐 Processing: {url}")
        
        if debug:
            # Run all strategies and show results
            results = []
            strategies = []
            if HAS_TRAFILATURA:
                strategies.append(("trafilatura", self._try_trafilatura))
            strategies.append(("beautifulsoup", self._try_beautifulsoup))
            if HAS_HTML2TEXT:
                strategies.append(("html2text", self._try_html2text))
            if HAS_REQUESTS_HTML:
                strategies.append(("requests-html", self._try_requests_html))
            strategies.append(("fallback", self._try_fallback))

            best_content = None
            best_score = 0

            for name, strategy_func in strategies:
                try:
                    content = strategy_func(url, 5000)
                    if content:
                        score = self._score_content(content)
                        results.append(f"{name}: {score}/100, {len(content)} chars")
                        if score > best_score:
                            best_content = content
                            best_score = score
                except Exception as e:
                    results.append(f"{name}: ERROR - {str(e)}")

            if best_content:
                debug_info = "\n".join(results)
                final_result = self._format_result(url, best_content, best_score)
                return f"🔍 Debug Results:\n{debug_info}\n\n{final_result}"
            else:
                return self.formatter.error(f"All strategies failed for {url}")
        
        elif strategy is not None:
            # Use specific strategy
            strategies = [
                self._try_trafilatura,
                self._try_beautifulsoup,
                self._try_html2text,
                self._try_requests_html,
                self._try_fallback,
            ]

            if 0 <= strategy < len(strategies):
                content = strategies[strategy](url, 20000)
                if content:
                    score = self._score_content(content)
                    formatted_content = self._format_result(url, content, score)

                    # Add to conversation history unless --no-ai flag is set
                    if not no_ai:
                        self._add_webpage_to_memory(url, content)

                    return formatted_content
                else:
                    return self.formatter.error(f"Strategy {strategy} failed to extract content")
            else:
                return self.formatter.error(f"Invalid strategy number. Use 0-{len(strategies)-1}")

        else:
            # Normal reading with best strategy (default behavior)
            content = self.read_webpage(url)

            # Add to conversation history unless --no-ai flag is set
            if not no_ai:
                self._add_webpage_to_memory(url, content)
            
            return content

    def _read_interactive_content(self, prompt: str = "Enter content (end with EOF: Ctrl+D on Unix, Ctrl+Z on Windows):") -> str:
        """Read multiline content from stdin until EOF."""
        import sys
        lines = []
        if sys.stdin.isatty():
            print(prompt)
            print("Type your content line by line. Press Ctrl+D (Unix) or Ctrl+Z (Windows) when done.")
        try:
            for line in sys.stdin:
                lines.append(line)
        except KeyboardInterrupt:
            print("\nInput interrupted.")
            return ""
        return "".join(lines)

    def handle_write_command(self, command: str) -> str:
        """
        Handle /write command for creating or overwriting files.

        Usage:
          /write <file_path> [content]   - Write content to file (content optional)
          /write --interactive <file_path> - Enter content interactively

        If content is not provided, reads from stdin until EOF (Ctrl+D on Unix, Ctrl+Z on Windows).
        """
        if not command or command.strip() == "":
            help_text = """
📝 /write Command Usage:
  /write <file_path> [content]   - Write content to file
  /write --interactive <file_path> - Enter content interactively (end with EOF)

Examples:
  /write hello.txt "Hello World"
  /write script.py "print('hello')"
  /write --interactive notes.md
            """.strip()
            return help_text

        # Auto-switch to coding mode for write command
        if self.mode != 'coding':
            self.switch_mode('coding', persist=False)

        # Parse flags
        interactive = False
        parts = command.split()
        # Check for --interactive flag
        if parts[0] == '--interactive':
            interactive = True
            parts.pop(0)

        if not parts:
            return self.formatter.error("Please provide a file path")

        file_path = parts[0]
        content = ' '.join(parts[1:]) if len(parts) > 1 else ""

        # If interactive mode or no content provided, read from stdin
        if interactive or not content:
            content = self._read_interactive_content()
            if not content:
                return self.formatter.warning("No content provided. File not written.")

        # ── Guard check ──────────────────────────────────────────────
        is_allowed, guard_warning = self._check_file_guards(file_path)
        if not is_allowed:
            self._log_evidence("file_edit", file_path, guard_warning, severity="warning")
            return self.formatter.warning(f"🧊 FROZEN: {guard_warning}")

        # Ensure code analyzer is initialized
        if not self.code_analyzer:
            self.code_analyzer = CodeAnalyzer(os.getcwd(), safety_manager=self.safety_manager)

        # Write file
        success, message = self.code_analyzer.write_file_safe(file_path, content)
        if success:
            # Log to evidence trail
            self._log_evidence("file_edit", file_path, f"write_success, {len(content)} bytes", severity="info")
            return self.formatter.success(message)
        else:
            self._log_evidence("file_edit", file_path, f"write_failed: {message}", severity="warning")
            return self.formatter.error(message)

    def handle_edit_command(self, command: str) -> str:
        """
        Handle /edit command for editing files with code changes.

        Usage:
          /edit <file_path> "<old_code>" "<new_code>" [--description "desc"]
          /edit --help

        Examples:
          /edit test.py "print('hello')" "print('Hello World')"
        """
        import shlex
        import os
        from .code_analyzer import CodeAnalyzer
        if not command or command.strip() == "":
            help_text = """
📝 /edit Command Usage:
  /edit <file_path> "<old_code>" "<new_code>"   - Replace old code with new code
  /edit --help                                  - Show this help

Examples:
  /edit script.py "print('old')" "print('new')"
  /edit script.py "def old():" "def new():"
            """.strip()
            return help_text

        # Auto-switch to coding mode for edit command
        if self.mode != 'coding':
            self.switch_mode('coding', persist=False)

        # Parse flags
        parts = []
        try:
            parts = shlex.split(command)
        except ValueError as e:
            return self.formatter.error(f"Invalid command syntax: {e}")

        if not parts:
            return self.formatter.error("Please provide a file path")

        file_path = parts[0]
        description = "Manual edit via /edit command"
        line = None
        old_code = ""
        new_code = ""

        # Parse flags
        i = 1
        while i < len(parts):
            if parts[i] == '--description':
                if i + 1 < len(parts):
                    description = parts[i + 1]
                    i += 2
                else:
                    return self.formatter.error("Missing description after --description")
            else:
                # Treat as old_code and new_code positional arguments
                if i + 1 < len(parts):
                    old_code = parts[i]
                    new_code = parts[i + 1]
                    i += 2
                else:
                    return self.formatter.error("Need both old_code and new_code arguments")
                break  # No more flags after positional args

        # Ensure we have old_code and new_code
        if not old_code or not new_code:
            return self.formatter.error("Missing old_code or new_code")

        # Initialize code analyzer if needed
        if not self.code_analyzer:
            self.code_analyzer = CodeAnalyzer(os.getcwd(), safety_manager=self.safety_manager)

        # Validate change
        is_valid, error_msg = self.validate_proposed_change(old_code, new_code, file_path)
        if not is_valid:
            return self.formatter.error(f"Change validation failed: {error_msg}")

        # Propose change
        result = self.propose_code_change(file_path, old_code, new_code, description, line)
        return result

    def handle_run_command(self, command: str) -> str:
        """
        Handle /run command for executing shell commands safely.

        Usage:
          /run <command> [args...]

        Example:
          /run ls -la
          /run python --version
        """
        if not command or command.strip() == "":
            help_text = """
🔧 /run Command Usage:
  /run <command> [args...]   - Execute a shell command safely

Examples:
  /run ls -la
  /run python --version
  /run echo "Hello"
            """.strip()
            return help_text

        # Auto-switch to coding mode for run command
        if self.mode != 'coding':
            self.switch_mode('coding', persist=False)

        # ── Guard check ──────────────────────────────────────────────
        is_allowed, guard_warning = self._check_guards(command)
        if not is_allowed:
            self._log_evidence("command", command, guard_warning, severity="warning")
            return self.formatter.warning(f"🛑 BLOCKED by safety guard:\n{guard_warning}")

        # Determine working directory
        import os
        cwd = os.getcwd()
        if self.code_analyzer:
            cwd = self.code_analyzer.root_path

        # Execute using command executor
        result = self.command_executor.execute(command, cwd=cwd)
        # Log command execution
        log_operation('execute', command, result['success'],
                     f"cwd={cwd}, exit_code={result['returncode']}, time={result['execution_time']:.2f}s")

        # Log to evidence trail
        self._log_evidence("command", command, f"exit_code={result['returncode']}", severity="info" if result['success'] else "warning")

        # Format result using formatter
        if not result['success']:
            return self.formatter.error(result['error_message'])

        # Build formatted output
        output = f"🚀 Command: {command}\n"
        output += f"📁 Working directory: {cwd}\n"
        output += f"⏱️  Execution time: {result['execution_time']:.2f}s\n"
        output += f"📤 Exit code: {result['returncode']}\n"

        if result['stdout']:
            output += f"\n📤 STDOUT:\n{result['stdout'].rstrip()}\n"
        if result['stderr']:
            output += f"\n📤 STDERR:\n{result['stderr'].rstrip()}\n"

        if result['returncode'] == 0:
            output += f"\n{self.formatter.success('Command completed successfully.')}"
        else:
            output += f"\n{self.formatter.warning('Command failed (non-zero exit code).')}"

        return output

    def handle_git_command(self, command: str) -> str:
        """
        Handle /git command for version control operations.

        Usage:
          /git <subcommand> [args...]

        Examples:
          /git status
          /git diff
          /git log --oneline -5
          /git commit -m "message"
          /git push origin main
        """
        if not command or command.strip() == "":
            help_text = """
🔄 /git Command Usage:
  /git <subcommand> [args...]   - Execute git command safely

Common subcommands:
  status, diff, log, commit, push, pull, branch, checkout, clone, init

Examples:
  /git status
  /git diff
  /git log --oneline -5
  /git commit -m "message"
  /git push origin main
            """.strip()
            return help_text

        # Auto-switch to coding mode for git command
        if self.mode != 'coding':
            self.switch_mode('coding', persist=False)

        # Determine working directory
        import os
        cwd = os.getcwd()
        if self.code_analyzer:
            cwd = self.code_analyzer.root_path

        # Execute using command executor's git-specific method
        result = self.command_executor.execute_git(command, cwd=cwd)

        # Format result using formatter
        if not result['success']:
            return self.formatter.error(result['error_message'])

        # Build formatted output
        output = f"🔄 Git command: git {command}\n"
        output += f"📁 Working directory: {cwd}\n"
        output += f"⏱️  Execution time: {result['execution_time']:.2f}s\n"
        output += f"📤 Exit code: {result['returncode']}\n"

        if result['stdout']:
            output += f"\n📤 STDOUT:\n{result['stdout'].rstrip()}\n"
        if result['stderr']:
            output += f"\n📤 STDERR:\n{result['stderr'].rstrip()}\n"

        if result['returncode'] == 0:
            output += f"\n{self.formatter.success('Git command completed successfully.')}"
        else:
            output += f"\n{self.formatter.warning('Git command failed (non-zero exit code).')}"

        return output

    def handle_help_command(self, command: str = "") -> str:
        """
        Handle /help command.
        Usage: /help [command]
        Examples:
          /help          - Show all available commands
          /help write    - Show detailed help for /write command
        """
        help_texts = {
            "write": """
📝 /write Command:
  /write <file_path> [content]   - Write content to file
  /write --interactive <file_path> - Enter content interactively

Examples:
  /write hello.txt "Hello World"
  /write script.py "print('hello')"
""",
            "edit": """
📝 /edit Command:
  /edit <file_path> "<old_code>" "<new_code>"   - Replace old code with new code

Examples:
  /edit script.py "print('old')" "print('new')"
""",
            "read": """
📚 /read Command:
  /read <url>                     - Read webpage content
  /read <file_path>               - Read local file (supports line ranges)
  /read --debug <url>            - Show debugging info
  /read --strategy <n> <url>     - Use specific strategy (0-4)
""",
            "run": """
🔧 /run Command:
  /run <command> [args...]   - Execute a shell command safely

Examples:
  /run ls -la
  /run python --version
""",
            "git": """
🔄 /git Command:
  /git <subcommand> [args...]   - Execute git command safely

Common subcommands: status, diff, log, commit, push, pull, branch, checkout
""",
            "code": """
📁 /code Command:
  /code scan [path]              - Scan codebase
  /code summary                  - Show codebase summary
  /code find <pattern>          - Find files matching pattern
  /code read <file_path>        - Read and analyze a file
  /code analyze <file_path>     - Analyze file structure
  /code search <text>           - Search for text in code
  /code changes                 - Show pending changes
  /code apply                   - Apply pending changes
  /code clear                   - Clear pending changes
  /code self-scan              - Scan agent's own codebase
  /code self-improve <feature> - Suggest improvements
  /code self-apply             - Apply self-improvements safely
""",
            "search": """
🔍 /search Command:
  /search <query>   - Search the web using DuckDuckGo
""",
            "models": """
🤖 /models Command:
  /models list      - List available models (all providers)
  /models switch <model> - Switch to a different model
""",
            "fix": """
🔧 /fix Command:
  /fix <file_path> [description] - Automatically fix code issues
""",
            "analyze": """
🔬 /analyze Command:
  /analyze <file_path> - Analyze code for issues and suggest improvements
""",
            "diff": """
📝 /diff Command:
  /diff <file1> <file2>        - Compare two files
  /diff --git <file>           - Show git diff for file
  /diff --backup <file>        - Compare with latest backup

Examples:
  /diff old.py new.py
  /diff --git agent/core.py
""",
            "browse": """
📁 /browse Command:
  /browse [path]              - Browse directory (default: current)
  /browse --details [path]    - Show detailed listing with sizes
  /browse --filter <ext>      - Filter by extension (e.g., .py)

Examples:
  /browse
  /browse agent/
  /browse --details src/
""",
            "undo": """
↩️ /undo Command:
  /undo list [n]              - List recent changes (default: 5)
  /undo last                  - Revert last change
  /undo <change_id>           - Revert specific change by index

Examples:
  /undo list
  /undo last
  /undo 2
""",
            "test": """
🧪 /test Command:
  /test                       - Run basic development tests (dev_test.py)
  /test unit                  - Run unit tests (if available)
  /test all                   - Run all available tests

Examples:
  /test
  /test unit
""",
            "apply": """
🔧 /apply Command (alias for /code apply):
  /apply              - Apply pending changes with confirmation
  /apply force        - Apply without interactive confirmation
  /apply confirm      - Apply with confirmation (same as /apply)

Note: This is an alias for /code apply.
""",
        }

        if not command:
            # Show all commands
            result = "🤖 Available Commands:\n\n"
            for cmd in sorted(help_texts.keys()):
                # Extract first line of each help text
                first_line = help_texts[cmd].strip().split('\n')[0]
                result += f"{first_line}\n"
            result += "\n💡 Use /help <command> for detailed usage."
            return result
        else:
            cmd = command.strip().lower()
            if cmd in help_texts:
                return help_texts[cmd].strip()
            else:
                return self.formatter.error(f"No help available for '{command}'. Available commands: {', '.join(sorted(help_texts.keys()))}")

    def handle_diff_command(self, command: str) -> str:
        """Handle /diff command — delegates to file_commands module."""
        from agent.services.file_commands import handle_diff_command
        return handle_diff_command(self, command)

    def handle_browse_command(self, command: str) -> str:
        """Handle /browse command — delegates to file_commands module."""
        from agent.services.file_commands import handle_browse_command
        return handle_browse_command(self, command)

    def handle_undo_command(self, command: str) -> str:
        """Handle /undo command — delegates to file_commands module."""
        from agent.services.file_commands import handle_undo_command
        return handle_undo_command(self, command)

    def _revert_change(self, change: dict) -> str:
        """Revert a change — delegates to file_commands module."""
        from agent.services.file_commands import _revert_change
        return _revert_change(self, change)

    def handle_test_command(self, command: str) -> str:
        """Handle /test command — delegates to file_commands module."""
        from agent.services.file_commands import handle_test_command
        return handle_test_command(self, command)

    def handle_apply_command(self, command: str) -> str:
        """Handle /apply command (alias for /code apply).

        Usage:
          /apply              - Apply pending changes with confirmation
          /apply force        - Apply without interactive confirmation
          /apply confirm      - Apply with confirmation (same as /apply)
          /apply --help       - Show help
        """
        if command and command.strip().lower() in ['--help', 'help']:
            help_text = """
🔧 /apply Command (alias for /code apply):
  /apply              - Apply pending changes with confirmation
  /apply force        - Apply without interactive confirmation
  /apply confirm      - Apply with confirmation (same as /apply)
  /apply --help       - Show this help

Note: This is an alias for /code apply. See '/help code' for more details.
            """.strip()
            return help_text

        # Map to /code apply subcommand
        if command and 'force' in command.lower():
            return self._code_apply_changes_confirm(force=True)
        else:
            return self._code_apply_changes()

    # ── Workflow command handlers (delegates to agent.services.workflow_commands) ──

    def handle_sprint_command(self, command: str) -> Optional[str]:
        """Handle /sprint command — delegates to workflow_commands module."""
        from agent.services.workflow_commands import handle_sprint_command
        return handle_sprint_command(self, command)

    def handle_careful_command(self, command: str) -> Optional[str]:
        """Handle /careful command — delegates to workflow_commands module."""
        from agent.services.workflow_commands import handle_careful_command
        return handle_careful_command(self, command)

    def handle_freeze_command(self, command: str) -> Optional[str]:
        """Handle /freeze command — delegates to workflow_commands module."""
        from agent.services.workflow_commands import handle_freeze_command
        return handle_freeze_command(self, command)

    def handle_guard_command(self, command: str) -> Optional[str]:
        """Handle /guard command — delegates to workflow_commands module."""
        from agent.services.workflow_commands import handle_guard_command
        return handle_guard_command(self, command)

    def handle_unfreeze_command(self, command: str) -> Optional[str]:
        """Handle /unfreeze command — delegates to workflow_commands module."""
        from agent.services.workflow_commands import handle_unfreeze_command
        return handle_unfreeze_command(self, command)

    def handle_evidence_command(self, command: str) -> Optional[str]:
        """Handle /evidence command — delegates to workflow_commands module."""
        from agent.services.workflow_commands import handle_evidence_command
        return handle_evidence_command(self, command)

    def handle_evolve_command(self, command: str) -> Optional[str]:
        """Handle /evolve command — delegates to workflow_commands module."""
        from agent.services.workflow_commands import handle_evolve_command
        return handle_evolve_command(self, command)

    def handle_dashboard_command(self, command: str) -> Optional[str]:
        """Handle /dashboard command — delegates to workflow_commands module."""
        from agent.services.workflow_commands import handle_dashboard_command
        return handle_dashboard_command(self, command)

    def handle_upgrade_command(self, command: str) -> Optional[str]:
        """Handle /upgrade command — delegates to workflow_commands module."""
        from agent.services.workflow_commands import handle_upgrade_command
        return handle_upgrade_command(self, command)

    # ── Workflow integration helpers ────────────────────────────────────────

    def _log_evidence(self, action: str, input_data: str, output_data: str = "", severity: str = "info") -> None:
        """Helper to log evidence if available."""
        if self.evidence:
            try:
                self.evidence.log(action, input_data, output_data, mode=self.mode, sprint_id=self.current_sprint_id, severity=severity)
            except Exception:
                pass  # Gracefully ignore evidence logging failures

    def _learn_patterns_from_turn(self, user_prompt: str, response: str) -> None:
        """Extract lightweight patterns from a conversation turn and record to SharedMemory.

        Called after every LLM response in stream_response().
        Extracts: stock tickers, coding keywords, topic hints.
        Non-fatal — exceptions are silently swallowed by caller.
        """
        import re
        mode = self.mode

        # 1. Stock tickers (fin mode — record frequently discussed symbols)
        if mode == "fin":
            tickers = re.findall(r'\$([A-Z]{1,5})\b', user_prompt)
            for t in set(tickers):
                self._shared_memory.record_pattern("frequent_stock", t, mode)
            # Chinese stock codes
            cn_codes = re.findall(r'\b([036]\d{5})\b', user_prompt)
            for c in set(cn_codes):
                self._shared_memory.record_pattern("frequent_stock", c, mode)

        # 2. Coding language mentions (coding mode)
        if mode == "coding":
            lang_patterns = {
                "python": r'\bpython\b', "javascript": r'\b(?:javascript|js|typescript|ts)\b',
                "rust": r'\brust\b', "go": r'\bgolang|go\b', "java": r'\bjava\b',
                "c++": r'\bc\+\+|cpp\b', "ruby": r'\bruby\b', "swift": r'\bswift\b',
            }
            prompt_lower = user_prompt.lower()
            for lang, pat in lang_patterns.items():
                if re.search(pat, prompt_lower):
                    self._shared_memory.record_pattern("coding_language", lang, mode)

        # 3. User corrections / feedback (any mode)
        correction_triggers = ["不对", "错了", "wrong", "incorrect", "actually", "其实"]
        prompt_lower = user_prompt.lower()
        for trigger in correction_triggers:
            if trigger in prompt_lower:
                self._shared_memory.record_feedback("correction", user_prompt[:300], mode)
                break

    def _check_guards(self, cmd: str) -> Tuple[bool, str]:
        """Helper to check safety guards. Returns (is_allowed, warning_msg)."""
        if not self.guard:
            return True, ""

        try:
            blocked, warning = self.guard.check_command(cmd)
            return not blocked, warning
        except Exception:
            return True, ""  # Fail safe

    def _check_file_guards(self, filepath: str) -> Tuple[bool, str]:
        """Helper to check file edit guards. Returns (is_allowed, warning_msg)."""
        if not self.guard:
            return True, ""

        try:
            blocked, warning = self.guard.check_file_edit(filepath)
            return not blocked, warning
        except Exception:
            return True, ""  # Fail safe

    def _add_webpage_to_memory(self, url: str, content: str) -> None:
        """
        Add webpage content to conversation history for AI awareness
        """
        # Extract just the main text content (remove formatting headers)
        # Find where the actual content starts (after the "-" * 60 line)
        lines = content.split('\n')
        content_start = 0

        for i, line in enumerate(lines):
            if '-' * 60 in line or '=' * 60 in line:
                content_start = i + 1
                break

        main_content = '\n'.join(lines[content_start:])
        
        # Remove trailing separator if present
        if '-' * 60 in main_content or '=' * 60 in main_content:
            main_content = main_content[:main_content.rfind('-' * 60)]

        # Clean up whitespace
        main_content = main_content.strip()

        # Truncate to avoid token limits (adjust based on your context window)
        max_chars = 10000

        # Separate links section (if present) so it survives truncation
        links_section = ""
        links_marker = "--- Links Found ---"
        if links_marker in main_content:
            split_pos = main_content.index(links_marker)
            links_section = "\n\n" + main_content[split_pos:]
            main_content = main_content[:split_pos].rstrip()
            # Reserve space for links (cap links at 1500 chars)
            links_section = links_section[:1500]
            max_chars -= len(links_section)

        if len(main_content) > max_chars:
            # Try to find a good truncation point
            truncated = main_content[:max_chars]
            last_period = truncated.rfind('.')
            last_newline = truncated.rfind('\n')

            if last_period > max_chars * 0.8:
                main_content = truncated[:last_period + 1]
            elif last_newline > max_chars * 0.8:
                main_content = truncated[:last_newline]
            else:
                main_content = truncated + "\n\n[Content truncated for context]"

        # Re-attach links section
        main_content = main_content + links_section

        # Add to conversation history
        self.add_to_history("user", f"""I've read the following webpage:

    URL: {url}

    Content:
    {main_content}

    Please remember this content. I may ask you questions about it.""")

        print("💡 Content added to AI memory. You can now ask questions about it!")

    # ── /links command ─────────────────────────────────────────────
    # ── Web command handlers (delegates to agent.web.web_commands) ──────

    def handle_links_command(self, url_or_command: str) -> str:
        """Handle /links command — delegates to web_commands module."""
        from agent.web.web_commands import handle_links_command
        return handle_links_command(self, url_or_command)

    def _format_links_output(self, links):
        """Format links output — delegates to content_extraction module."""
        from agent.web.content_extraction import format_links_output
        return format_links_output(links)

    def handle_crawl_command(self, command: str) -> str:
        """Handle /crawl command — delegates to web_commands module."""
        from agent.web.web_commands import handle_crawl_command
        return handle_crawl_command(self, command)

    def handle_webmap_command(self, command: str) -> str:
        """Handle /webmap command — delegates to web_commands module."""
        from agent.web.web_commands import handle_webmap_command
        return handle_webmap_command(self, command)

    def _format_webmap(self, base_url, urls, source='crawl'):
        """Format webmap output — delegates to content_extraction module."""
        from agent.web.content_extraction import format_webmap
        return format_webmap(base_url, urls, source)

    def handle_logs_command(self, command: str) -> Optional[str]:
        """Handle /logs command — delegates to web_commands module."""
        from agent.web.web_commands import handle_logs_command
        return handle_logs_command(self, command)

    # ── Log formatting (delegated to agent.services.log_commands) ──────
    def _format_log_stats(self, stats, period="today"):
        from agent.services.log_commands import format_log_stats
        return format_log_stats(stats, period)

    def _format_log_weekly_stats(self, stats):
        from agent.services.log_commands import format_log_weekly_stats
        return format_log_weekly_stats(stats)

    def _format_log_search_results(self, results, keyword):
        from agent.services.log_commands import format_log_search_results
        return format_log_search_results(results, keyword)

    def _format_log_recent(self, results, limit):
        from agent.services.log_commands import format_log_recent
        return format_log_recent(results, limit)

    def _is_likely_file_path(self, path: str) -> bool:
        """
        Determine if the given string is likely a local file path rather than a URL.
        """
        # Check for URL indicators
        if '://' in path:
            return False
        if path.startswith(('http://', 'https://', 'ftp://', 'file://')):
            return False

        # Check for file path indicators
        if '/' in path or '\\' in path:
            return True
        if path.startswith(('./', '../', '~/')):
            return True
        # Check for file extension (common code/text extensions)
        import os
        ext = os.path.splitext(path)[1].lower()
        if ext in {'.py', '.js', '.txt', '.md', '.json', '.yaml', '.yml', '.html', '.css', '.java', '.cpp', '.c', '.h', '.go', '.rs', '.rb', '.php', '.swift'}:
            return True
        # Check if path exists (relative to current directory or code analyzer root)
        if os.path.exists(path):
            return True
        # Default to URL assumption (but could be a domain)
        return False

    def _get_self_iteration(self):
        """Initialize and return SelfIteration instance."""
        if self.self_iteration is None:
            self.self_iteration = SelfIteration(self.agent_root, self.code_analyzer)
        return self.self_iteration

    def _is_self_modification(self, file_path: str) -> bool:
        """Check if file is within agent's own codebase."""
        try:
            abs_path = os.path.abspath(file_path)
            return abs_path.startswith(self.agent_root)
        except:
            return False

    def _handle_file_read(self, file_path: str, no_ai: bool = False) -> str:
        """
        Read a local file and optionally add to conversation history.
        Supports line ranges: file.py:10-20
        """
        import os
        import re

        # Parse line range (e.g., file.py:10-20)
        line_range = None
        match = re.match(r'^(.+):(\d+)(?:-(\d+))?$', file_path)
        if match:
            file_path = match.group(1)
            start_line = int(match.group(2))
            end_line = int(match.group(3)) if match.group(3) else start_line
            line_range = (start_line, end_line)

        # Ensure code analyzer is initialized
        if not self.code_analyzer:
            self.code_analyzer = CodeAnalyzer(os.getcwd(), safety_manager=self.safety_manager)

        # Read file
        success, message, content = self.code_analyzer.read_file_safe(file_path)
        if not success:
            return self.formatter.error(f"Cannot read file: {message}")

        # Apply line range if specified
        if line_range:
            lines = content.split('\n')
            start, end = line_range
            if start < 1 or end > len(lines) or start > end:
                return self.formatter.error(f"Invalid line range: {start}-{end} (file has {len(lines)} lines)")
            # Convert to 0-index and slice
            content = '\n'.join(lines[start-1:end])
            line_info = f" (lines {start}-{end})"
        else:
            line_info = ""

        # Add to conversation history unless --no-ai flag is set
        if not no_ai:
            self.add_to_history("user", f"""I've read the following file:

    File: {file_path}{line_info}
    Lines: {len(content.splitlines())}

    ```python
    {content[:2000]}{'...' if len(content) > 2000 else ''}
    ```

    Please remember this code. I may ask you to analyze or fix it.

    Note: If I ask you to propose changes to this code, use the PROPOSED CHANGE format with exact Old Code and New Code.""")

        # Return formatted result
        result = f"📄 File: {file_path}{line_info}\n"
        result += f"📏 Size: {len(content)} characters, {len(content.splitlines())} lines\n"
        if len(content) > 2000:
            result += f"📝 Preview (first 2000 chars):\n```\n{content[:2000]}...\n```\n"
        else:
            result += f"📝 Content:\n```\n{content}\n```\n"
        if not no_ai:
            result += "\n💡 Content added to AI memory. You can now ask questions about it!"
        return result

    # NEW: Code analysis methods
    def handle_code_command(self, *args, **kwargs):
        """Delegate to code_commands module."""
        from agent.services.code_commands import handle_code_command
        return handle_code_command(self, *args, **kwargs)

    def _code_scan(self, *args, **kwargs):
        """Delegate to code_commands module."""
        from agent.services.code_commands import _code_scan
        return _code_scan(self, *args, **kwargs)

    def add_code_context_instructions(self, *args, **kwargs):
        """Delegate to code_commands module."""
        from agent.services.code_commands import add_code_context_instructions
        return add_code_context_instructions(self, *args, **kwargs)

    def is_code_related_query(self, *args, **kwargs):
        """Delegate to code_commands module."""
        from agent.services.code_commands import is_code_related_query
        return is_code_related_query(self, *args, **kwargs)

    def _code_show_changes(self, *args, **kwargs):
        """Delegate to code_commands module."""
        from agent.services.code_commands import _code_show_changes
        return _code_show_changes(self, *args, **kwargs)

    def _code_apply_changes(self, *args, **kwargs):
        """Delegate to code_commands module."""
        from agent.services.code_commands import _code_apply_changes
        return _code_apply_changes(self, *args, **kwargs)

    def _order_changes_by_dependencies(self, *args, **kwargs):
        """Delegate to code_commands module."""
        from agent.services.code_commands import _order_changes_by_dependencies
        return _order_changes_by_dependencies(self, *args, **kwargs)

    def _code_apply_changes_confirm(self, *args, **kwargs):
        """Delegate to code_commands module."""
        from agent.services.code_commands import _code_apply_changes_confirm
        return _code_apply_changes_confirm(self, *args, **kwargs)

    def _code_self_scan(self, *args, **kwargs):
        """Delegate to code_commands module."""
        from agent.services.code_commands import _code_self_scan
        return _code_self_scan(self, *args, **kwargs)

    def _code_self_improve(self, *args, **kwargs):
        """Delegate to code_commands module."""
        from agent.services.code_commands import _code_self_improve
        return _code_self_improve(self, *args, **kwargs)

    def _code_self_apply(self, *args, **kwargs):
        """Delegate to code_commands module."""
        from agent.services.code_commands import _code_self_apply
        return _code_self_apply(self, *args, **kwargs)

    def _code_reason(self, *args, **kwargs):
        """Delegate to code_commands module."""
        from agent.services.code_commands import _code_reason
        return _code_reason(self, *args, **kwargs)

    def propose_code_change(self, *args, **kwargs):
        """Delegate to code_commands module."""
        from agent.services.code_commands import propose_code_change
        return propose_code_change(self, *args, **kwargs)

    def search_sync(self, *args, **kwargs):
        """Delegate to code_commands module."""
        from agent.services.code_commands import search_sync
        return search_sync(self, *args, **kwargs)

    def add_to_history(self, *args, **kwargs):
        """Delegate to code_commands module."""
        from agent.services.code_commands import add_to_history
        return add_to_history(self, *args, **kwargs)

    def add_search_results_to_history(self, *args, **kwargs):
        """Delegate to code_commands module."""
        from agent.services.code_commands import add_search_results_to_history
        return add_search_results_to_history(self, *args, **kwargs)

    def clear_history(self, *args, **kwargs):
        """Delegate to code_commands module."""
        from agent.services.code_commands import clear_history
        return clear_history(self, *args, **kwargs)

    def get_conversation_summary(self, *args, **kwargs):
        """Delegate to code_commands module."""
        from agent.services.code_commands import get_conversation_summary
        return get_conversation_summary(self, *args, **kwargs)

    def get_token_count(self, *args, **kwargs):
        """Delegate to code_commands module."""
        from agent.services.code_commands import get_token_count
        return get_token_count(self, *args, **kwargs)

    def _ensure_system_prompt(self, *args, **kwargs):
        """Delegate to code_commands module."""
        from agent.services.code_commands import _ensure_system_prompt
        return _ensure_system_prompt(self, *args, **kwargs)

    def toggle_thinking_mode(self, *args, **kwargs):
        """Delegate to code_commands module."""
        from agent.services.code_commands import toggle_thinking_mode
        return toggle_thinking_mode(self, *args, **kwargs)

    def stream_response(self, *args, **kwargs):
        """Delegate to code_commands module."""
        from agent.services.code_commands import stream_response
        return stream_response(self, *args, **kwargs)

    def stream_response_async(self, *args, **kwargs):
        """Delegate to code_commands module."""
        from agent.services.code_commands import stream_response_async
        return stream_response_async(self, *args, **kwargs)

    def run_async(self, *args, **kwargs):
        """Delegate to code_commands module."""
        from agent.services.code_commands import run_async
        return run_async(self, *args, **kwargs)

    def _handle_auto_fix_confirmation(self, *args, **kwargs):
        """Delegate to code_commands module."""
        from agent.services.code_commands import _handle_auto_fix_confirmation
        return _handle_auto_fix_confirmation(self, *args, **kwargs)

    def auto_detect_and_read_file(self, *args, **kwargs):
        """Delegate to code_commands module."""
        from agent.services.code_commands import auto_detect_and_read_file
        return auto_detect_and_read_file(self, *args, **kwargs)

    def classify_and_enhance_input(self, *args, **kwargs):
        """Delegate to code_commands module."""
        from agent.services.code_commands import classify_and_enhance_input
        return classify_and_enhance_input(self, *args, **kwargs)

    def handle_auto_file_analysis(self, *args, **kwargs):
        """Delegate to code_commands module."""
        from agent.services.code_commands import handle_auto_file_analysis
        return handle_auto_file_analysis(self, *args, **kwargs)

    def handle_auto_fix_command(self, *args, **kwargs):
        """Delegate to code_commands module."""
        from agent.services.code_commands import handle_auto_fix_command
        return handle_auto_fix_command(self, *args, **kwargs)

    def _parse_ai_changes_for_file(self, *args, **kwargs):
        """Delegate to code_commands module."""
        from agent.services.code_commands import _parse_ai_changes_for_file
        return _parse_ai_changes_for_file(self, *args, **kwargs)

    def _auto_apply_changes_with_confirmation(self, *args, **kwargs):
        """Delegate to code_commands module."""
        from agent.services.code_commands import _auto_apply_changes_with_confirmation
        return _auto_apply_changes_with_confirmation(self, *args, **kwargs)

    def get_user_confirmation(self, *args, **kwargs):
        """Delegate to code_commands module."""
        from agent.services.code_commands import get_user_confirmation
        return get_user_confirmation(self, *args, **kwargs)

    def _check_file_threshold(self, *args, **kwargs):
        """Delegate to code_commands module."""
        from agent.services.code_commands import _check_file_threshold
        return _check_file_threshold(self, *args, **kwargs)

    def show_diff(self, *args, **kwargs):
        """Delegate to code_commands module."""
        from agent.services.code_commands import show_diff
        return show_diff(self, *args, **kwargs)

    def validate_proposed_change(self, *args, **kwargs):
        """Delegate to code_commands module."""
        from agent.services.code_commands import validate_proposed_change
        return validate_proposed_change(self, *args, **kwargs)

    def find_similar_code(self, *args, **kwargs):
        """Delegate to code_commands module."""
        from agent.services.code_commands import find_similar_code
        return find_similar_code(self, *args, **kwargs)
