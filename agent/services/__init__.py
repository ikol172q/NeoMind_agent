"""Shared Services layer — personality-agnostic infrastructure.

ServiceRegistry provides centralized, lazy access to all shared services.
Personalities access services via: self.services.search, self.services.vault, etc.

Created: 2026-03-28 (Step 1 of architecture redesign)
Updated: 2026-03-28 (Tier 2A — real service creation, replacing bridge pattern)
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    pass  # Future: type hints for service classes

# Sentinel to distinguish "not yet initialized" from "init returned None"
_UNSET = object()


class ServiceRegistry:
    """Central access point for all shared services.

    ServiceRegistry OWNS all service creation via lazy initialization.
    Properties create services on first access and cache the result.

    P3-A: core_ref bridge removed — ServiceRegistry is fully self-contained.
    core.py accesses services via self.services.X with backward-compat aliases.
    """

    def __init__(self, core_ref: Any = None, config: Any = None):
        # core_ref accepted for backward compat but no longer used for bridging
        # TODO: Remove core_ref parameter entirely once all callers are updated

        # ── Configuration ────────────────────────────────────────────
        if config is None:
            from agent_config import agent_config
            self.config = agent_config
        else:
            self.config = config

        # ── All services start as _UNSET (lazy init on first access) ──
        # Eager (lightweight)
        self._formatter = _UNSET
        self._help_system = _UNSET
        self._command_executor = _UNSET
        self._task_manager = _UNSET
        self._safety = _UNSET

        # Feature flags, Sandbox, Permissions
        self._feature_flags = _UNSET
        self._sandbox = _UNSET
        self._permission_manager = _UNSET

        # Lazy (heavier)
        self._search = _UNSET
        self._vault = _UNSET
        self._memory = _UNSET
        self._logger = _UNSET
        self._skills = _UNSET
        self._nl_interpreter = _UNSET
        self._context = _UNSET
        self._llm_provider = _UNSET

        # AutoDream, Session Notes, Memory Selector, Prompt Composer, Swarm, etc.
        self._auto_dream = _UNSET
        self._session_notes = _UNSET
        self._memory_selector = _UNSET
        self._prompt_composer = _UNSET
        self._frustration_detector = _UNSET
        self._session_storage = _UNSET
        self._agent_memory = _UNSET

        # Hooks & Plugins
        self._hook_runner = _UNSET
        self._plugin_loader = _UNSET

        # Workflow & Evolution
        self._evidence = _UNSET
        self._guard = _UNSET
        self._sprint_mgr = _UNSET
        self._review = _UNSET
        self._evolution = _UNSET
        self._evolution_scheduler = _UNSET
        self._upgrader = _UNSET

    # ── Eager Service Properties (lightweight, always needed) ─────────

    @property
    def formatter(self):
        """Formatter for terminal output."""
        if self._formatter is _UNSET:
            try:
                from agent.services.formatter import Formatter
                self._formatter = Formatter()
            except Exception:
                self._formatter = None
        return self._formatter

    @property
    def help_system(self):
        """Help text and command documentation."""
        if self._help_system is _UNSET:
            try:
                from agent.services.help_system import HelpSystem
                self._help_system = HelpSystem()
            except Exception:
                self._help_system = None
        return self._help_system

    @property
    def command_executor(self):
        """Shell command execution with safety guards."""
        if self._command_executor is _UNSET:
            try:
                from agent.services.command_executor import CommandExecutor
                self._command_executor = CommandExecutor()
            except Exception:
                self._command_executor = None
        return self._command_executor

    @property
    def task_manager(self):
        """Task/todo management."""
        if self._task_manager is _UNSET:
            try:
                from agent.services.task_manager import TaskManager
                self._task_manager = TaskManager()
            except Exception:
                self._task_manager = None
        return self._task_manager

    @property
    def safety(self):
        """SafetyManager for file operation guards."""
        if self._safety is _UNSET:
            try:
                from agent.services.safety_service import SafetyManager
                agent_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                self._safety = SafetyManager(os.getcwd(), agent_root=agent_root)
            except Exception:
                self._safety = None
        return self._safety

    @property
    def permission_manager(self):
        """PermissionManager for tool access control."""
        if self._permission_manager is _UNSET:
            try:
                from agent.services.permission_manager import PermissionManager, PermissionMode
                mode_str = self.config.get("permissions.mode", "normal") if hasattr(self.config, 'get') else "normal"
                mode_map = {
                    'normal': PermissionMode.NORMAL,
                    'auto_accept': PermissionMode.AUTO_ACCEPT,
                    'accept_edits': PermissionMode.ACCEPT_EDITS,
                    'dont_ask': PermissionMode.DONT_ASK,
                    'plan': PermissionMode.PLAN,
                    'bypass': PermissionMode.BYPASS,
                }
                mode = mode_map.get(mode_str, PermissionMode.NORMAL)
                self._permission_manager = PermissionManager(mode=mode)
            except Exception:
                self._permission_manager = None
        return self._permission_manager

    @property
    def feature_flags(self):
        """FeatureFlagService for runtime feature gating."""
        if self._feature_flags is _UNSET:
            try:
                from agent.services.feature_flags import get_feature_flags
                self._feature_flags = get_feature_flags()
            except Exception:
                self._feature_flags = None
        return self._feature_flags

    @property
    def sandbox(self):
        """SandboxManager for isolated command execution."""
        if self._sandbox is _UNSET:
            try:
                from agent.services.sandbox import SandboxManager
                self._sandbox = SandboxManager(workspace_root=os.getcwd())
            except Exception:
                self._sandbox = None
        return self._sandbox

    # ── Lazy Service Properties (heavier, on-demand) ──────────────────

    @property
    def search(self):
        """UniversalSearchEngine."""
        if self._search is _UNSET:
            try:
                from agent.search.engine import UniversalSearchEngine
                domain = "finance" if getattr(self.config, 'mode', 'chat') == "fin" else "general"
                self._search = UniversalSearchEngine(
                    domain=domain,
                    triggers=self.config.auto_search_triggers,
                )
            except Exception:
                try:
                    from agent.services.search_legacy import OptimizedDuckDuckGoSearch
                    self._search = OptimizedDuckDuckGoSearch(
                        triggers=self.config.auto_search_triggers
                    )
                except Exception:
                    self._search = None
        return self._search

    @property
    def vault(self):
        """Vault dict: {reader, writer, watcher}. Lazy init."""
        if self._vault is _UNSET:
            if os.environ.get("NEOMIND_DISABLE_VAULT"):
                self._vault = None
            else:
                try:
                    from agent.vault.reader import VaultReader
                    from agent.vault.writer import VaultWriter
                    reader = VaultReader()
                    writer = VaultWriter()
                    # Watcher is optional
                    watcher = None
                    try:
                        from agent.vault.watcher import VaultWatcher
                        watcher = VaultWatcher()
                    except Exception:
                        pass
                    self._vault = {'reader': reader, 'writer': writer, 'watcher': watcher}
                except Exception:
                    self._vault = None
        return self._vault

    @property
    def memory(self):
        """SharedMemory — cross-personality learning."""
        if self._memory is _UNSET:
            if os.environ.get("NEOMIND_DISABLE_MEMORY"):
                self._memory = None
            else:
                try:
                    from agent.memory.shared_memory import SharedMemory
                    self._memory = SharedMemory()
                except Exception:
                    self._memory = None
        return self._memory

    @property
    def logger(self):
        """UnifiedLogger with PII sanitization."""
        if self._logger is _UNSET:
            try:
                from agent.logging import get_unified_logger
                self._logger = get_unified_logger()
            except Exception:
                self._logger = None
        return self._logger

    @property
    def skills(self):
        """SkillLoader for SKILL.md files."""
        if self._skills is _UNSET:
            try:
                from agent.skills.loader import get_skill_loader
                self._skills = get_skill_loader()
            except Exception:
                self._skills = None
        return self._skills

    @property
    def nl_interpreter(self):
        """Natural language command interpreter."""
        if self._nl_interpreter is _UNSET:
            if getattr(self.config, 'natural_language_enabled', False):
                try:
                    from agent.services.nl_interpreter import NaturalLanguageInterpreter
                    threshold = getattr(self.config, 'natural_language_confidence_threshold', 0.6)
                    self._nl_interpreter = NaturalLanguageInterpreter(
                        confidence_threshold=threshold
                    )
                except Exception:
                    self._nl_interpreter = None
            else:
                self._nl_interpreter = None
        return self._nl_interpreter

    @property
    def context(self):
        """ContextManager for conversation history ops."""
        # Context manager needs conversation_history from core — bridge only
        if self._context is _UNSET:
            self._context = None  # Mark as attempted
        return self._context

    @property
    def llm_provider(self):
        """LLMProviderService — model specs, provider routing, model management."""
        if self._llm_provider is _UNSET:
            try:
                from agent.services.llm_provider import LLMProviderService
                api_key = os.getenv("DEEPSEEK_API_KEY", "")
                model = getattr(self.config, 'model', 'deepseek-chat')
                self._llm_provider = LLMProviderService(
                    api_key=api_key,
                    model=model,
                    config=self.config,
                )
            except Exception:
                self._llm_provider = None
        return self._llm_provider

    @property
    def auto_dream(self):
        """AutoDream — background memory consolidation."""
        if self._auto_dream is _UNSET:
            try:
                from agent.evolution.auto_dream import AutoDream
                self._auto_dream = AutoDream(
                    shared_memory=self.memory,
                    vault=self.vault,
                )
            except Exception:
                self._auto_dream = None
        return self._auto_dream

    @property
    def prompt_composer(self):
        """PromptComposer — modular system prompt construction."""
        if self._prompt_composer is _UNSET:
            try:
                from agent.prompts.composer import PromptComposer, collect_system_context
                self._prompt_composer = PromptComposer()
                # Auto-inject system context
                git_status, os_info, date_str = collect_system_context()
                self._prompt_composer.set_context(git_status, os_info, date_str)
                # Auto-discover NEOMIND.md / project.md guidance
                self._prompt_composer.inject_project_guidance(
                    workspace_root=os.getcwd()
                )
            except Exception:
                self._prompt_composer = None
        return self._prompt_composer

    @property
    def memory_selector(self):
        """MemorySelector — LLM-based memory relevance selection."""
        if self._memory_selector is _UNSET:
            try:
                from agent.memory.memory_selector import MemorySelector
                self._memory_selector = MemorySelector()
            except Exception:
                self._memory_selector = None
        return self._memory_selector

    @property
    def frustration_detector(self):
        """FrustrationDetector — detect negative user signals."""
        if self._frustration_detector is _UNSET:
            try:
                from agent.services.frustration_detector import detect_frustration
                self._frustration_detector = detect_frustration
            except Exception:
                self._frustration_detector = None
        return self._frustration_detector

    @property
    def session_storage_writer(self):
        """SessionWriter — JSONL append-only session persistence."""
        if self._session_storage is _UNSET:
            try:
                from agent.services.session_storage import SessionWriter
                self._session_storage = SessionWriter()
            except Exception:
                self._session_storage = None
        return self._session_storage

    @property
    def agent_memory(self):
        """AgentMemory — per-agent persistent knowledge."""
        if self._agent_memory is _UNSET:
            try:
                from agent.memory.agent_memory import AgentMemory
                self._agent_memory = AgentMemory(agent_type='default')
            except Exception:
                self._agent_memory = None
        return self._agent_memory

    @property
    def session_notes(self):
        """SessionNotes — auto-maintained session context notes."""
        if self._session_notes is _UNSET:
            try:
                from agent.services.session_notes import SessionNotes
                self._session_notes = SessionNotes()
            except Exception:
                self._session_notes = None
        return self._session_notes

    # ── Hooks & Plugins ───────────────────────────────────────────────

    @property
    def hook_runner(self):
        """HookRunner — user-configurable PreToolUse/PostToolUse shell hooks."""
        if self._hook_runner is _UNSET:
            try:
                from agent.services.hooks import HookRunner
                self._hook_runner = HookRunner()
            except Exception:
                self._hook_runner = None
        return self._hook_runner

    @property
    def plugin_loader(self):
        """PluginLoader — user plugins from ~/.neomind/plugins/."""
        if self._plugin_loader is _UNSET:
            try:
                from agent.services.plugin_loader import PluginLoader
                self._plugin_loader = PluginLoader()
                # Auto-load all discovered plugins on first access.
                # tool_registry is optional; plugins that don't need it
                # will still load and register their capabilities.
                self._plugin_loader.load_all()
            except Exception:
                self._plugin_loader = None
        return self._plugin_loader

    # ── Workflow & Evolution ──────────────────────────────────────────
    # These are fully decoupled singletons. Try own init first,
    # bridge to core as fallback during migration.

    @property
    def evidence(self):
        if self._evidence is _UNSET:
            try:
                from agent.workflow.evidence import EvidenceTrail
                self._evidence = EvidenceTrail()
            except Exception:
                self._evidence = None
        return self._evidence

    @property
    def guard(self):
        if self._guard is _UNSET:
            try:
                from agent.workflow.guards import SafetyGuard
                self._guard = SafetyGuard()
            except Exception:
                self._guard = None
        return self._guard

    @property
    def sprint_mgr(self):
        if self._sprint_mgr is _UNSET:
            try:
                from agent.workflow.sprint import SprintManager
                self._sprint_mgr = SprintManager()
            except Exception:
                self._sprint_mgr = None
        return self._sprint_mgr

    @property
    def review(self):
        if self._review is _UNSET:
            try:
                from agent.workflow.review import ReviewDispatcher
                self._review = ReviewDispatcher()
            except Exception:
                self._review = None
        return self._review

    @property
    def evolution(self):
        if self._evolution is _UNSET:
            try:
                from agent.evolution.auto_evolve import AutoEvolve
                self._evolution = AutoEvolve()
                self._evolution.run_startup_check()
            except Exception:
                self._evolution = None
        return self._evolution

    @property
    def evolution_scheduler(self):
        if self._evolution_scheduler is _UNSET:
            try:
                from agent.evolution.scheduler import EvolutionScheduler
                evo = self.evolution
                if evo is not None:
                    self._evolution_scheduler = EvolutionScheduler(evo)
                    self._evolution_scheduler.on_session_start()
                else:
                    self._evolution_scheduler = None
            except Exception:
                self._evolution_scheduler = None
        return self._evolution_scheduler

    @property
    def upgrader(self):
        if self._upgrader is _UNSET:
            try:
                from agent.evolution.upgrade import NeoMindUpgrade
                self._upgrader = NeoMindUpgrade()
            except Exception:
                self._upgrader = None
        return self._upgrader

    # ── Lifecycle Hooks (called by core.py) ──────────────────────────

    def on_turn_complete(self, turn_count: int, conversation_history: list = None) -> None:
        """Called after each response. Triggers scheduled evolution tasks and AutoDream."""
        sched = self.evolution_scheduler
        if sched is not None:
            try:
                sched.on_turn_complete(turn_count)
            except Exception:
                pass

        # AutoDream: notify turn complete and attempt consolidation
        dream = self.auto_dream
        if dream is not None:
            try:
                dream.on_turn_complete()
                if conversation_history:
                    dream.maybe_consolidate(conversation_history)
            except Exception:
                pass

    def on_session_end(self) -> None:
        """Called on exit. Flushes evidence, runs evolution checks."""
        sched = self.evolution_scheduler
        if sched is not None:
            try:
                sched.on_session_end()
            except Exception:
                pass

        ev = self._evidence
        if ev is not _UNSET and ev is not None:
            try:
                ev.flush()
            except Exception:
                pass
