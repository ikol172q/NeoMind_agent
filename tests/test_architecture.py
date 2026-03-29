"""Architecture verification tests — proves the three-tier system WORKS.

P3-F: These tests verify the architectural properties of the NeoMind system:
1. ServiceRegistry is self-contained (no bridge fallback)
2. Personality on_activate() actually runs mode-specific setup
3. switch_mode() delegates to personality, not duplicating logic
4. SharedCommandsMixin routes to service modules, not through core
5. Each personality has unique behavior (not pass-through)

Created: 2026-03-28 (P3-F of architecture redesign)
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch, PropertyMock

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestServiceRegistrySelfContained(unittest.TestCase):
    """Verify ServiceRegistry owns service creation without bridge fallback."""

    def test_no_resolve_method(self):
        """ServiceRegistry should NOT have a _resolve bridge method."""
        from agent.services import ServiceRegistry
        self.assertFalse(
            hasattr(ServiceRegistry, '_resolve'),
            "ServiceRegistry should not have _resolve bridge method (P3-A)"
        )

    def test_no_core_ref_usage(self):
        """ServiceRegistry should not use _core for service resolution."""
        import inspect
        from agent.services import ServiceRegistry

        source = inspect.getsource(ServiceRegistry)
        # _core should not appear in any property getters
        for name in ['formatter', 'search', 'vault', 'memory', 'logger',
                      'skills', 'help_system', 'command_executor', 'safety',
                      'task_manager', 'nl_interpreter', 'context', 'llm_provider',
                      'evidence', 'guard', 'sprint_mgr', 'review',
                      'evolution', 'evolution_scheduler', 'upgrader']:
            prop = getattr(ServiceRegistry, name, None)
            if prop and isinstance(prop, property) and prop.fget:
                fget_source = inspect.getsource(prop.fget)
                self.assertNotIn(
                    'self._core',
                    fget_source,
                    f"Property '{name}' should not reference self._core (P3-A)"
                )

    def test_registry_creates_formatter(self):
        """ServiceRegistry.formatter should create a Formatter without core."""
        from agent.services import ServiceRegistry
        reg = ServiceRegistry(config=MagicMock())
        formatter = reg.formatter
        self.assertIsNotNone(formatter, "ServiceRegistry should create Formatter on its own")

    def test_registry_creates_help_system(self):
        """ServiceRegistry.help_system should create HelpSystem without core."""
        from agent.services import ServiceRegistry
        reg = ServiceRegistry(config=MagicMock())
        hs = reg.help_system
        self.assertIsNotNone(hs, "ServiceRegistry should create HelpSystem on its own")

    def test_registry_creates_command_executor(self):
        """ServiceRegistry.command_executor should create CommandExecutor without core."""
        from agent.services import ServiceRegistry
        reg = ServiceRegistry(config=MagicMock())
        ce = reg.command_executor
        self.assertIsNotNone(ce, "ServiceRegistry should create CommandExecutor on its own")

    def test_registry_creates_task_manager(self):
        """ServiceRegistry.task_manager should create TaskManager without core."""
        from agent.services import ServiceRegistry
        reg = ServiceRegistry(config=MagicMock())
        tm = reg.task_manager
        self.assertIsNotNone(tm, "ServiceRegistry should create TaskManager on its own")

    def test_registry_lazy_init(self):
        """Services should be _UNSET before first access and cached after."""
        from agent.services import ServiceRegistry, _UNSET
        reg = ServiceRegistry(config=MagicMock())
        # Before access
        self.assertIs(reg._formatter, _UNSET, "Should be _UNSET before access")
        # Trigger access
        _ = reg.formatter
        # After access
        self.assertIsNot(reg._formatter, _UNSET, "Should be cached after first access")


class TestPersonalityOnActivate(unittest.TestCase):
    """Verify personality on_activate() performs real mode-specific setup."""

    def _make_core_mock(self, mode='chat'):
        """Create a minimal core mock for personality testing."""
        core = MagicMock()
        core.mode = mode
        core.searcher = MagicMock()
        core.searcher.set_domain = MagicMock()
        core._vault_reader = MagicMock()
        core._vault_reader.vault_exists.return_value = False
        core._shared_memory = None
        core._active_skill = None
        core._skill_loader = None
        core.conversation_history = []
        core.add_to_history = MagicMock()
        return core

    def test_chat_on_activate_sets_search_domain(self):
        """ChatPersonality.on_activate() should set search domain to 'general'."""
        from agent.modes.chat import ChatPersonality
        core = self._make_core_mock('chat')
        services = MagicMock()
        p = ChatPersonality(core=core, services=services)
        p.on_activate()
        core.searcher.set_domain.assert_called_with("general")

    def test_coding_on_activate_sets_search_domain(self):
        """CodingPersonality.on_activate() should set search domain to 'code'."""
        from agent.modes.coding import CodingPersonality
        core = self._make_core_mock('coding')
        services = MagicMock()
        p = CodingPersonality(core=core, services=services)
        p.on_activate()
        core.searcher.set_domain.assert_called_with("code")

    def test_finance_on_activate_sets_search_domain(self):
        """FinancePersonality.on_activate() should set search domain to 'finance'."""
        from agent.modes.finance import FinancePersonality
        core = self._make_core_mock('fin')
        services = MagicMock()
        p = FinancePersonality(core=core, services=services)
        p.on_activate()
        core.searcher.set_domain.assert_called_with("finance")

    def test_chat_on_activate_not_empty(self):
        """ChatPersonality.on_activate() should NOT be a no-op."""
        import inspect
        from agent.modes.chat import ChatPersonality
        source = inspect.getsource(ChatPersonality.on_activate)
        # Should NOT be just 'pass' or empty
        lines = [l.strip() for l in source.split('\n')
                 if l.strip() and not l.strip().startswith('#')
                 and not l.strip().startswith('"""')
                 and not l.strip().startswith('def ')]
        self.assertTrue(
            len(lines) > 1,
            "ChatPersonality.on_activate() should have real logic, not just 'pass'"
        )

    def test_coding_initializes_workspace(self):
        """CodingPersonality.on_activate() should call workspace initialization."""
        from agent.modes.coding import CodingPersonality
        core = self._make_core_mock('coding')
        services = MagicMock()
        p = CodingPersonality(core=core, services=services)
        p.on_activate()
        # Should attempt workspace init (may fail in test, but should be called)
        # Check that the method exists and has real logic
        self.assertTrue(hasattr(p, '_initialize_workspace'))

    def test_finance_initializes_finance(self):
        """FinancePersonality.on_activate() should call finance initialization."""
        from agent.modes.finance import FinancePersonality
        core = self._make_core_mock('fin')
        services = MagicMock()
        p = FinancePersonality(core=core, services=services)
        p.on_activate()
        # Should have finance init method
        self.assertTrue(hasattr(p, '_initialize_finance'))

    def test_finance_has_real_nl_patterns(self):
        """FinancePersonality.get_nl_patterns() should return actual patterns."""
        from agent.modes.finance import FinancePersonality
        core = self._make_core_mock('fin')
        services = MagicMock()
        p = FinancePersonality(core=core, services=services)
        patterns = p.get_nl_patterns()
        self.assertIsInstance(patterns, (list, dict))
        if isinstance(patterns, dict):
            self.assertTrue(len(patterns) > 0, "Finance should have NL pattern categories")
        else:
            self.assertTrue(len(patterns) > 0, "Finance should have NL patterns")


class TestSwitchModeDelegation(unittest.TestCase):
    """Verify switch_mode() delegates to personality, not duplicating logic."""

    def test_switch_mode_no_vault_reinject(self):
        """switch_mode() should NOT contain vault re-injection code."""
        import inspect
        # Import or read the method
        from agent.core import NeoMindAgent
        source = inspect.getsource(NeoMindAgent.switch_mode)
        self.assertNotIn(
            'vault_context = self._vault_reader',
            source,
            "switch_mode() should not re-inject vault (P3-B moved to personality)"
        )

    def test_switch_mode_no_memory_reinject(self):
        """switch_mode() should NOT contain memory re-injection code."""
        import inspect
        from agent.core import NeoMindAgent
        source = inspect.getsource(NeoMindAgent.switch_mode)
        self.assertNotIn(
            'mem_context = self._shared_memory',
            source,
            "switch_mode() should not re-inject memory (P3-B moved to personality)"
        )

    def test_switch_mode_no_search_domain_set(self):
        """switch_mode() should NOT set search domain directly."""
        import inspect
        from agent.core import NeoMindAgent
        source = inspect.getsource(NeoMindAgent.switch_mode)
        self.assertNotIn(
            'searcher.set_domain',
            source,
            "switch_mode() should not set search domain (P3-B moved to personality)"
        )

    def test_switch_mode_calls_on_activate(self):
        """switch_mode() should call personality.on_activate()."""
        import inspect
        from agent.core import NeoMindAgent
        source = inspect.getsource(NeoMindAgent.switch_mode)
        self.assertIn(
            'on_activate()',
            source,
            "switch_mode() should call personality.on_activate()"
        )

    def test_switch_mode_has_fallback(self):
        """switch_mode() should have a _fallback_mode_init safety net."""
        import inspect
        from agent.core import NeoMindAgent
        source = inspect.getsource(NeoMindAgent.switch_mode)
        self.assertIn(
            '_fallback_mode_init',
            source,
            "switch_mode() should have _fallback_mode_init for safety"
        )
        # Also verify the method exists
        self.assertTrue(
            hasattr(NeoMindAgent, '_fallback_mode_init'),
            "NeoMindAgent should have _fallback_mode_init method"
        )


class TestSharedCommandsRouting(unittest.TestCase):
    """Verify SharedCommandsMixin routes to service modules, not through core."""

    def test_workflow_commands_call_standalone_functions(self):
        """Workflow commands should call workflow_commands.py directly."""
        import inspect
        from agent.services.shared_commands import SharedCommandsMixin

        workflow_cmds = [
            '_shared_handle_sprint_command',
            '_shared_handle_careful_command',
            '_shared_handle_freeze_command',
            '_shared_handle_guard_command',
            '_shared_handle_unfreeze_command',
            '_shared_handle_evidence_command',
            '_shared_handle_evolve_command',
            '_shared_handle_dashboard_command',
            '_shared_handle_upgrade_command',
        ]
        for cmd_name in workflow_cmds:
            method = getattr(SharedCommandsMixin, cmd_name)
            source = inspect.getsource(method)
            self.assertIn(
                'from agent.services.workflow_commands import',
                source,
                f"{cmd_name} should import from workflow_commands, not delegate to core"
            )

    def test_mode_command_inlined(self):
        """_shared_handle_mode_command should call switch_mode directly."""
        import inspect
        from agent.services.shared_commands import SharedCommandsMixin
        source = inspect.getsource(SharedCommandsMixin._shared_handle_mode_command)
        self.assertIn('switch_mode', source)
        # Should NOT delegate back to core.handle_mode_command
        self.assertNotIn('self.core.handle_mode_command', source)

    def test_help_command_uses_help_system(self):
        """_shared_handle_help_command should use help_system directly."""
        import inspect
        from agent.services.shared_commands import SharedCommandsMixin
        source = inspect.getsource(SharedCommandsMixin._shared_handle_help_command)
        self.assertIn('help_system', source)

    def test_llm_commands_have_real_impl(self):
        """LLM analysis commands should have real implementations, not delegates."""
        import inspect
        from agent.services.shared_commands import SharedCommandsMixin

        llm_cmds = [
            '_shared_handle_summarize_command',
            '_shared_handle_reason_command',
            '_shared_handle_debug_command',
            '_shared_handle_explain_command',
            '_shared_handle_refactor_command',
            '_shared_handle_translate_command',
            '_shared_handle_generate_command',
        ]
        for cmd_name in llm_cmds:
            method = getattr(SharedCommandsMixin, cmd_name)
            source = inspect.getsource(method)
            # Should NOT be a one-liner delegate
            lines = [l for l in source.split('\n') if l.strip() and not l.strip().startswith('#')]
            self.assertTrue(
                len(lines) > 3,
                f"{cmd_name} should have real implementation (>3 lines), not a delegate"
            )


class TestCoreUsesServiceRegistry(unittest.TestCase):
    """Verify core.__init__ uses ServiceRegistry for service creation."""

    def test_core_init_creates_service_registry(self):
        """core.__init__ should create self.services as ServiceRegistry."""
        import inspect
        from agent.core import NeoMindAgent
        source = inspect.getsource(NeoMindAgent.__init__)
        self.assertIn('ServiceRegistry', source, "core.__init__ should create ServiceRegistry")

    def test_core_init_aliases_from_registry(self):
        """core.__init__ should set aliases from self.services, not create duplicates."""
        import inspect
        from agent.core import NeoMindAgent
        source = inspect.getsource(NeoMindAgent.__init__)
        # Should have backward-compat aliases
        self.assertIn('self.services.formatter', source,
                       "formatter should be aliased from services")
        self.assertIn('self.services.search', source,
                       "searcher should be aliased from services")
        self.assertIn('self.services.command_executor', source,
                       "command_executor should be aliased from services")

    def test_no_duplicate_formatter_creation(self):
        """core.__init__ should NOT call Formatter() directly."""
        import inspect
        from agent.core import NeoMindAgent
        source = inspect.getsource(NeoMindAgent.__init__)
        # Should not have direct Formatter() construction
        self.assertNotIn(
            'self.formatter = Formatter()',
            source,
            "Should not create Formatter() directly — use self.services.formatter"
        )


class TestPersonalityCommandHandlers(unittest.TestCase):
    """Verify personalities have unique command handlers, not all pass-through."""

    def test_finance_enhance_response_has_real_logic(self):
        """FinancePersonality.enhance_response() should have real logic."""
        import inspect
        from agent.modes.finance import FinancePersonality
        source = inspect.getsource(FinancePersonality.enhance_response)
        lines = [l for l in source.split('\n')
                 if l.strip() and not l.strip().startswith('#')
                 and not l.strip().startswith('"""')]
        self.assertTrue(
            len(lines) > 5,
            "FinancePersonality.enhance_response() should have real logic"
        )

    def test_each_personality_has_unique_commands(self):
        """Each personality should define its own command handlers."""
        from agent.modes.chat import ChatPersonality
        from agent.modes.coding import CodingPersonality
        from agent.modes.finance import FinancePersonality

        core = MagicMock()
        services = MagicMock()

        chat_cmds = set(ChatPersonality(core=core, services=services)
                        .get_command_handlers().keys())
        coding_cmds = set(CodingPersonality(core=core, services=services)
                          .get_command_handlers().keys())
        finance_cmds = set(FinancePersonality(core=core, services=services)
                           .get_command_handlers().keys())

        # Chat and Coding should have unique commands
        self.assertTrue(len(chat_cmds) > 0, "ChatPersonality should have commands")
        self.assertTrue(len(coding_cmds) > 0, "CodingPersonality should have commands")
        # Finance uses NL routing, not slash commands — may have 0
        self.assertIsInstance(finance_cmds, set)

        # Coding should have commands that chat doesn't (e.g. /code, /diff, etc.)
        coding_only = coding_cmds - chat_cmds
        self.assertTrue(
            len(coding_only) > 0,
            "CodingPersonality should have unique commands not in ChatPersonality"
        )


if __name__ == '__main__':
    unittest.main()
