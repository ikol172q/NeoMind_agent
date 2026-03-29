"""CodingPersonality — engineer mode with strongest development capability.

Personality core: 工程师 (engineer)
Strongest capability: code analysis, generation, refactoring, testing,
    project management, git workflows, automated fixing.

Design principle: Coding is LASER-FOCUSED on building software.
  Every command is a development tool. When in doubt, write code.
  WorkspaceManager provides persistent project context.
  Web commands (/read, /crawl, etc.) are available via shared layer
  for reading documentation, but the emphasis is on CODE.

Created: 2026-03-28 (Step 6 of architecture redesign)
Updated: 2026-03-28 (P4 — clearer differentiation)
"""

from typing import Dict, Optional, Set

from agent.base_personality import BasePersonality
from agent.services.shared_commands import SharedCommandsMixin
from agent_config import agent_config


class CodingPersonality(BasePersonality, SharedCommandsMixin):
    """Coding mode — engineer with full development toolkit."""

    @property
    def name(self) -> str:
        return "coding"

    @property
    def display_name(self) -> str:
        return "Coding 工程师"

    def get_command_handlers(self) -> Dict[str, tuple]:
        """Coding-UNIQUE commands. Shared commands via SharedCommandsMixin."""
        return {
            "/code": (self._coding_handle_code_command, True),
            "/write": (self._coding_handle_write_command, True),
            "/edit": (self._coding_handle_edit_command, True),
            "/run": (self._coding_handle_run_command, True),
            "/git": (self._coding_handle_git_command, True),
            "/diff": (self._coding_handle_diff_command, True),
            "/browse": (self._coding_handle_browse_command, True),
            "/undo": (self._coding_handle_undo_command, True),
            "/test": (self._coding_handle_test_command, True),
            "/apply": (self._coding_handle_apply_command, True),
            "/grep": (self._coding_handle_grep_command, True),
            "/find": (self._coding_handle_find_command, True),
            "/fix": (self._coding_handle_auto_fix_command, False),
            "/analyze": (self._coding_handle_auto_fix_command, False),
        }

    def on_activate(self) -> None:
        """Activate coding mode — init workspace, set search domain."""
        # Set search domain for code-oriented results
        if hasattr(self.core, 'searcher') and hasattr(self.core.searcher, 'set_domain'):
            self.core.searcher.set_domain("code")

        # Initialize workspace manager (coding-specific)
        self._initialize_workspace()

        # Re-inject vault context for coding mode
        self._inject_vault_context()

        # Re-inject shared memory context
        self._inject_memory_context()

        # Deactivate incompatible skills
        self._check_skill_compatibility()

    def on_deactivate(self) -> None:
        """Deactivate coding mode."""
        # Future: close persistent bash session, save workspace state
        pass

    def get_search_domain(self) -> str:
        return "code"

    def get_system_prompt(self) -> str:
        return agent_config.system_prompt or ""

    def get_commands_feed_to_llm(self) -> Set[str]:
        """Coding mode feeds more commands to LLM for reasoning."""
        base = super().get_commands_feed_to_llm()
        return base

    # ── Activation helpers ──────────────────────────────────────────

    def _initialize_workspace(self):
        """Init WorkspaceManager for coding mode (coding-specific)."""
        if getattr(self.core, 'workspace_manager', None) is None:
            try:
                from agent.workspace_manager import WorkspaceManager
                self.core.workspace_manager = WorkspaceManager()
                self.core._safe_print("📁 Workspace manager initialized.")
            except ImportError:
                self.core._safe_print("⚠️  Workspace manager not available.")
                self.core.workspace_manager = None

    def _inject_vault_context(self):
        """Re-inject vault context for this mode."""
        vault_reader = getattr(self.core, '_vault_reader', None)
        if vault_reader and vault_reader.vault_exists():
            try:
                vault_context = vault_reader.get_startup_context(mode=self.name)
                if vault_context:
                    self.core.add_to_history("system", vault_context)
            except Exception:
                pass

    def _inject_memory_context(self):
        """Re-inject shared memory context for this mode."""
        memory = getattr(self.core, '_shared_memory', None)
        if memory:
            try:
                mem_context = memory.get_context_summary(mode=self.name, max_tokens=500)
                if mem_context:
                    self.core.add_to_history("system",
                        f"# User Context (from cross-personality memory)\n\n{mem_context}")
            except Exception:
                pass

    def _check_skill_compatibility(self):
        """Deactivate skills not available in this mode."""
        active_skill = getattr(self.core, '_active_skill', None)
        if active_skill and self.name not in active_skill.modes:
            self.core._safe_print(
                f"🔴 Deactivated skill '{active_skill.name}' (not available in {self.name} mode)")
            self.core._active_skill = None

    # ── Coding-unique command handlers ───────────────────────────────

    def _coding_handle_code_command(self, arg):
        return self.core.handle_code_command(arg)

    def _coding_handle_write_command(self, arg):
        return self.core.handle_write_command(arg)

    def _coding_handle_edit_command(self, arg):
        return self.core.handle_edit_command(arg)

    def _coding_handle_run_command(self, arg):
        return self.core.handle_run_command(arg)

    def _coding_handle_git_command(self, arg):
        return self.core.handle_git_command(arg)

    def _coding_handle_diff_command(self, arg):
        return self.core.handle_diff_command(arg)

    def _coding_handle_browse_command(self, arg):
        return self.core.handle_browse_command(arg)

    def _coding_handle_undo_command(self, arg):
        return self.core.handle_undo_command(arg)

    def _coding_handle_test_command(self, arg):
        return self.core.handle_test_command(arg)

    def _coding_handle_apply_command(self, arg):
        return self.core.handle_apply_command(arg)

    def _coding_handle_grep_command(self, arg):
        return self.core.handle_grep_command(arg)

    def _coding_handle_find_command(self, arg):
        return self.core.handle_find_command(arg)

    def _coding_handle_auto_fix_command(self, arg):
        return self.core.handle_auto_fix_command(arg)
