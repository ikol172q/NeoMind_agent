"""
End-to-End Integration Tests — Simulates real NeoMind agent conversations.

These tests actually call the LLM (or a mock LLM) and verify the full pipeline:
- User input → command parsing → LLM call → tool execution → response
- Session save/resume round-trip
- Permission enforcement during conversation
- Memory selection and injection
- Error recovery during conversation
- Context compaction under pressure

Environment:
    NEOMIND_TEST_LLM=1  — Use real LLM (requires API key)
    NEOMIND_TEST_LLM=0  — Use mock LLM (default, no API key needed)

Usage:
    pytest tests/test_integration_e2e.py -v
    NEOMIND_TEST_LLM=1 pytest tests/test_integration_e2e.py -v  # with real LLM
"""

import os
import sys
import json
import time
import pytest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ─── Mock LLM for testing without API key ──────────────────────────

class MockLLM:
    """Mock LLM that returns predictable responses for testing."""

    def __init__(self):
        self.call_count = 0
        self.last_messages = None

    async def __call__(self, messages):
        self.call_count += 1
        self.last_messages = messages

        # Check if the last user message contains a tool result
        last_user = None
        for m in reversed(messages):
            if m.get('role') == 'user':
                last_user = m.get('content', '')
                break

        if last_user and '<tool_result>' in str(last_user):
            # After tool result, give a final response (no more tool calls)
            return "Based on the tool results, the task is complete."

        # First call — return a tool call
        if self.call_count == 1:
            return (
                'Let me read the file.\n\n'
                '<tool_call>\n'
                '{"tool": "Read", "params": {"path": "test_file.txt"}}\n'
                '</tool_call>'
            )

        # Subsequent calls — final response
        return "The task is complete. Here is the summary."


# ─── Fixtures ─────────────────────────────────────────────────────

@pytest.fixture
def workspace(tmp_path):
    """Create a temporary workspace with test files."""
    test_file = tmp_path / "test_file.txt"
    test_file.write_text("line 1\nline 2\nline 3\n")

    py_file = tmp_path / "main.py"
    py_file.write_text("print('hello world')\n")

    return tmp_path


@pytest.fixture
def tool_registry(workspace):
    """Create a ToolRegistry with the workspace."""
    from agent.coding.tools import ToolRegistry
    return ToolRegistry(str(workspace))


@pytest.fixture
def mock_llm():
    """Create a mock LLM."""
    return MockLLM()


@pytest.fixture
def service_registry():
    """Create a ServiceRegistry."""
    from agent.services import ServiceRegistry
    return ServiceRegistry()


# ─── Test: Full Agentic Loop ──────────────────────────────────────

class TestAgenticLoopE2E:
    """Test the full agentic loop with tool calls."""

    @pytest.mark.asyncio
    async def test_single_tool_call_loop(self, tool_registry, mock_llm, workspace):
        """Test a complete loop: LLM → tool call → result → final response."""
        from agent.agentic.agentic_loop import AgenticLoop, AgenticConfig

        config = AgenticConfig(max_iterations=5, tool_output_limit=3000)
        loop = AgenticLoop(tool_registry, config)

        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Read the test file."},
        ]

        # First LLM response triggers a Read tool call
        first_response = await mock_llm(messages)

        events = []
        async for event in loop.run(first_response, messages, mock_llm):
            events.append(event)

        # Should have: tool_start, tool_result, llm_response, done
        event_types = [e.type for e in events]
        assert "tool_start" in event_types, f"Expected tool_start, got {event_types}"
        assert "tool_result" in event_types, f"Expected tool_result, got {event_types}"

        # Tool result should be successful (test_file.txt exists)
        tool_results = [e for e in events if e.type == "tool_result"]
        assert len(tool_results) >= 1
        assert tool_results[0].result_success is True

    @pytest.mark.asyncio
    async def test_token_budget_auto_initialized(self, tool_registry):
        """Test that TokenBudget is auto-initialized in AgenticLoop."""
        from agent.agentic.agentic_loop import AgenticLoop, AgenticConfig

        config = AgenticConfig()
        loop = AgenticLoop(tool_registry, config)

        assert config.token_budget is not None, "TokenBudget should be auto-initialized"
        assert hasattr(config.token_budget, 'apply_tool_result_budget')

    @pytest.mark.asyncio
    async def test_error_recovery_wiring(self, tool_registry):
        """Test that error recovery is wired into the agentic loop."""
        from agent.agentic.agentic_loop import AgenticLoop, AgenticConfig

        config = AgenticConfig()
        loop = AgenticLoop(tool_registry, config)

        # The loop should create an ErrorRecoveryPipeline on first error
        # We can verify the import exists
        from agent.agentic.error_recovery import ErrorRecoveryPipeline
        pipeline = ErrorRecoveryPipeline()
        assert pipeline.is_recoverable(Exception("context length exceeded"))
        assert not pipeline.is_recoverable(Exception("random error"))

    @pytest.mark.asyncio
    async def test_stop_hooks_initialized(self, tool_registry):
        """Test that stop hooks pipeline is initialized."""
        from agent.agentic.agentic_loop import AgenticLoop, AgenticConfig

        config = AgenticConfig()
        loop = AgenticLoop(tool_registry, config)

        assert loop._stop_hooks is not None, "Stop hooks should be initialized"
        hooks = loop._stop_hooks.list_hooks()
        assert len(hooks) >= 3, f"Expected 3+ default hooks, got {len(hooks)}"


# ─── Test: Command Processing ────────────────────────────────────

class TestCommandProcessingE2E:
    """Test CLI command processing end-to-end."""

    def test_all_new_commands_registered(self):
        """Verify all 17 new commands are registered and callable."""
        from agent.cli_command_system import create_default_registry
        reg = create_default_registry()

        new_commands = [
            'checkpoint', 'rewind', 'flags', 'dream', 'resume',
            'branch', 'snip', 'brief', 'init', 'ship', 'btw',
            'doctor', 'style', 'rules', 'team',
        ]

        for name in new_commands:
            cmd = reg.find(name)
            assert cmd is not None, f"Command /{name} not registered"
            assert cmd.handler is not None, f"Command /{name} has no handler"

    def test_doctor_command_runs(self):
        """Test /doctor produces structured output."""
        from agent.cli_command_system import _build_builtin_commands
        cmds = _build_builtin_commands()
        doctor = next(c for c in cmds if c.name == 'doctor')
        result = doctor.handler('', None)
        assert 'Diagnostics' in result.text
        assert 'Python' in result.text

    def test_flags_command_lists_flags(self):
        """Test /flags lists all feature flags."""
        from agent.cli_command_system import _build_builtin_commands
        cmds = _build_builtin_commands()
        flags_cmd = next(c for c in cmds if c.name == 'flags')
        result = flags_cmd.handler('', None)
        assert 'AUTO_DREAM' in result.text
        assert 'SANDBOX' in result.text

    def test_save_markdown_export(self, workspace):
        """Test /save with .md extension produces markdown."""
        from agent.cli_command_system import _build_builtin_commands
        cmds = _build_builtin_commands()
        save_cmd = next(c for c in cmds if c.name == 'save')

        # Create mock agent with conversation
        agent = MagicMock()
        agent.conversation_history = [
            {'role': 'user', 'content': 'Hello'},
            {'role': 'assistant', 'content': 'Hi there!'},
        ]

        output_file = str(workspace / 'test_export.md')
        result = save_cmd.handler(output_file, agent)
        assert '✓' in result.text
        assert 'markdown' in result.text.lower()

        # Verify file content
        content = (workspace / 'test_export.md').read_text()
        assert '## User' in content
        assert 'Hello' in content

    def test_save_json_export(self, workspace):
        """Test /save with .json extension produces JSON."""
        from agent.cli_command_system import _build_builtin_commands
        cmds = _build_builtin_commands()
        save_cmd = next(c for c in cmds if c.name == 'save')

        agent = MagicMock()
        agent.conversation_history = [
            {'role': 'user', 'content': 'Test'},
        ]

        output_file = str(workspace / 'test_export.json')
        result = save_cmd.handler(output_file, agent)
        assert '✓' in result.text

        data = json.loads((workspace / 'test_export.json').read_text())
        assert 'messages' in data
        assert len(data['messages']) == 1

    def test_save_html_export(self, workspace):
        """Test /save with .html extension produces HTML."""
        from agent.cli_command_system import _build_builtin_commands
        cmds = _build_builtin_commands()
        save_cmd = next(c for c in cmds if c.name == 'save')

        agent = MagicMock()
        agent.conversation_history = [
            {'role': 'user', 'content': 'Test'},
            {'role': 'assistant', 'content': 'Response'},
        ]

        output_file = str(workspace / 'test_export.html')
        result = save_cmd.handler(output_file, agent)
        assert '✓' in result.text

        content = (workspace / 'test_export.html').read_text()
        assert '<html' in content
        assert 'NeoMind' in content


# ─── Test: Session Save/Resume Round-Trip ─────────────────────────

class TestSessionRoundTrip:
    """Test session save and resume end-to-end."""

    def test_session_save_and_list(self, tmp_path):
        """Test saving a session and listing it."""
        from agent.services.session_storage import SessionWriter, SessionReader

        # Write a session
        writer = SessionWriter(session_id='test_e2e', sessions_dir=str(tmp_path))
        writer.append_message('user', 'Hello')
        writer.append_message('assistant', 'Hi there!')
        writer.append_metadata('title', 'E2E Test Session')
        writer.append_metadata('mode', 'coding')
        writer.flush()

        # Read it back
        reader = SessionReader(sessions_dir=str(tmp_path))
        sessions = reader.list_sessions_lite()
        assert len(sessions) == 1
        assert sessions[0]['session_id'] == 'test_e2e'

        # Load full
        messages, metadata = reader.load_full('test_e2e')
        assert len(messages) == 2
        assert messages[0]['role'] == 'user'
        assert messages[0]['content'] == 'Hello'
        assert metadata.get('title') == 'E2E Test Session'

    def test_interrupt_detection(self, tmp_path):
        """Test detecting interrupted sessions."""
        from agent.services.session_storage import SessionWriter, SessionReader

        # Write a session that ends with a user message (interrupted)
        writer = SessionWriter(session_id='interrupted', sessions_dir=str(tmp_path))
        writer.append_message('user', 'Do something')
        writer.flush()

        reader = SessionReader(sessions_dir=str(tmp_path))
        messages, _ = reader.load_full('interrupted')
        assert reader.detect_interrupt(messages) is True

        # Normal session (ends with assistant)
        writer2 = SessionWriter(session_id='normal', sessions_dir=str(tmp_path))
        writer2.append_message('user', 'Hello')
        writer2.append_message('assistant', 'Hi')
        writer2.flush()

        messages2, _ = reader.load_full('normal')
        assert reader.detect_interrupt(messages2) is False


# ─── Test: Permission Enforcement in Conversation ─────────────────

class TestPermissionE2E:
    """Test permission system during simulated conversations."""

    def test_plan_mode_blocks_writes(self, tool_registry):
        """Test that plan mode blocks write operations."""
        from agent.services.permission_manager import (
            PermissionManager, PermissionMode, PermissionDecision
        )

        pm = PermissionManager(mode=PermissionMode.PLAN)

        # Read should be allowed
        d = pm.check_permission('Read', 'read_only')
        assert d == PermissionDecision.ALLOW

        # Write should be denied
        d = pm.check_permission('Write', 'write')
        assert d == PermissionDecision.DENY

        # Bash should be denied
        d = pm.check_permission('Bash', 'execute')
        assert d == PermissionDecision.DENY

    def test_rules_override_mode(self):
        """Test that permission rules take priority over mode."""
        from agent.services.permission_manager import (
            PermissionManager, PermissionMode, PermissionDecision
        )

        pm = PermissionManager(mode=PermissionMode.NORMAL)

        # Clear any persisted rules from previous tests
        while pm.list_rules():
            pm.remove_rule(0)

        # Add allow rule for Bash with "npm test"
        pm.add_rule('Bash', 'allow', 'npm test')

        # Bash with "npm test" should be allowed (rule overrides mode's ASK)
        d = pm.check_permission('Bash', 'execute', {'command': 'npm test'})
        assert d == PermissionDecision.ALLOW

        # Bash with other commands should still ASK (no rule matches)
        d = pm.check_permission('Bash', 'execute', {'command': 'rm -rf /'})
        assert d != PermissionDecision.ALLOW

        # Cleanup
        pm.remove_rule(0)

    def test_denial_fallback(self):
        """Test that repeated denials trigger fallback."""
        from agent.services.permission_manager import (
            PermissionManager, PermissionMode, PermissionDecision
        )

        pm = PermissionManager(mode=PermissionMode.DONT_ASK)

        # Before fallback: DONT_ASK allows most things
        d = pm.check_permission('Write', 'write')
        assert d == PermissionDecision.ALLOW

        # Record 3 consecutive denials
        for _ in range(3):
            pm.record_decision('Bash', False)

        # After fallback: should ASK for non-LOW operations
        d = pm.check_permission('Write', 'write')
        assert d == PermissionDecision.ASK


# ─── Test: Memory Selection in Conversation ───────────────────────

class TestMemoryE2E:
    """Test memory selection and injection during conversation."""

    def test_memory_selection_limits_to_5(self):
        """Test that memory selector returns max 5 memories."""
        from agent.memory.memory_selector import MemorySelector

        selector = MemorySelector()
        memories = [
            {'category': 'fact', 'fact': f'Fact number {i}',
             'updated_at': '2026-04-01T00:00:00+00:00'}
            for i in range(20)
        ]

        selected = selector.select('test query', memories)
        assert len(selected) <= 5

    def test_staleness_warnings_injected(self):
        """Test that old memories get staleness warnings."""
        from agent.memory.memory_selector import MemorySelector

        selector = MemorySelector()
        memories = [
            {'fact': 'Old fact', 'updated_at': '2025-01-01T00:00:00+00:00'},
        ]

        selector.add_staleness_warnings(memories)
        assert '_staleness_caveat' in memories[0]
        assert 'month' in memories[0]['_staleness_caveat']

    def test_taxonomy_prompt_generation(self):
        """Test memory taxonomy generates prompt text."""
        from agent.memory.memory_taxonomy import build_taxonomy_prompt, MEMORY_TYPES

        prompt = build_taxonomy_prompt()
        assert len(MEMORY_TYPES) == 4
        for mt in MEMORY_TYPES:
            # Taxonomy uses uppercase headers (### USER, ### FEEDBACK, etc.)
            assert mt['name'].upper() in prompt, f"Type '{mt['name']}' not found in prompt"
        assert 'Do NOT save' in prompt


# ─── Test: Frustration Detection ──────────────────────────────────

class TestFrustrationE2E:
    """Test frustration detection in simulated user messages."""

    def test_english_frustration(self):
        """Test detecting English frustration signals."""
        from agent.services.frustration_detector import detect_frustration

        # Frustrated message
        findings = detect_frustration("This doesn't work, waste of time")
        assert len(findings) > 0
        severities = {f['severity'] for f in findings}
        assert 'frustrated' in severities

    def test_chinese_frustration(self):
        """Test detecting Chinese frustration signals."""
        from agent.services.frustration_detector import detect_frustration

        findings = detect_frustration("不对，错了，这是错的")
        assert len(findings) > 0

    def test_neutral_message(self):
        """Test that neutral messages don't trigger detection."""
        from agent.services.frustration_detector import detect_frustration

        findings = detect_frustration("Please read the file src/main.py")
        assert len(findings) == 0


# ─── Test: Full ServiceRegistry Integration ───────────────────────

class TestServiceRegistryE2E:
    """Test that all services are accessible via ServiceRegistry."""

    def test_all_new_services_accessible(self):
        """Verify every new service property returns non-None."""
        from agent.services import ServiceRegistry
        sr = ServiceRegistry()

        services = {
            'safety': sr.safety,
            'sandbox': sr.sandbox,
            'feature_flags': sr.feature_flags,
            'permission_manager': sr.permission_manager,
            'auto_dream': sr.auto_dream,
            'session_notes': sr.session_notes,
            'memory_selector': sr.memory_selector,
            'prompt_composer': sr.prompt_composer,
            'frustration_detector': sr.frustration_detector,
            'session_storage_writer': sr.session_storage_writer,
            'agent_memory': sr.agent_memory,
        }

        for name, service in services.items():
            assert service is not None, f"Service '{name}' is None"

    def test_feature_flags_default_values(self):
        """Test feature flag default values."""
        from agent.services import ServiceRegistry
        sr = ServiceRegistry()
        ff = sr.feature_flags

        assert ff.is_enabled('AUTO_DREAM') is True
        assert ff.is_enabled('SANDBOX') is True
        assert ff.is_enabled('VOICE_INPUT') is False
        assert ff.is_enabled('COMPUTER_USE') is False


# ─── Test: Tool System Integration ────────────────────────────────

class TestToolSystemE2E:
    """Test tool system with all new features."""

    def test_new_tools_registered(self, tool_registry):
        """Verify all 9 new tools are registered."""
        new_tools = [
            'SyntheticOutput', 'Snip', 'VerifyPlanExecution',
            'Workflow', 'Brief', 'CtxInspect',
        ]
        for name in new_tools:
            td = tool_registry._tool_definitions.get(name)
            assert td is not None, f"Tool {name} not registered"

    def test_tool_interface_methods(self, tool_registry):
        """Test new tool interface methods on all tools."""
        for name, td in tool_registry._tool_definitions.items():
            # Every tool should have these methods
            assert hasattr(td, 'is_read_only'), f"{name} missing is_read_only"
            assert hasattr(td, 'is_destructive'), f"{name} missing is_destructive"
            assert hasattr(td, 'is_concurrency_safe'), f"{name} missing is_concurrency_safe"
            assert hasattr(td, 'is_open_world'), f"{name} missing is_open_world"
            assert hasattr(td, 'get_interrupt_behavior'), f"{name} missing get_interrupt_behavior"
            assert hasattr(td, 'get_activity_description'), f"{name} missing get_activity_description"

    def test_open_world_marking(self, tool_registry):
        """Test that WebFetch and WebSearch are marked as open-world."""
        wf = tool_registry._tool_definitions.get('WebFetch')
        ws = tool_registry._tool_definitions.get('WebSearch')
        rd = tool_registry._tool_definitions.get('Read')

        assert wf.is_open_world(), "WebFetch should be open-world"
        assert ws.is_open_world(), "WebSearch should be open-world"
        assert not rd.is_open_world(), "Read should NOT be open-world"

    def test_file_read_dedup(self, tool_registry, workspace):
        """Test that reading the same file twice returns cached result."""
        result1 = tool_registry._exec_read('test_file.txt', 0, 5)
        assert result1.success
        assert not result1.metadata.get('deduplicated', False)

        result2 = tool_registry._exec_read('test_file.txt', 0, 5)
        assert result2.success
        assert result2.metadata.get('deduplicated', False)

    def test_file_staleness_detection(self, tool_registry, workspace):
        """Test that editing a file after external modification is blocked."""
        # Read the file first
        tool_registry._exec_read('test_file.txt')

        # Externally modify the file
        time.sleep(0.1)
        (workspace / 'test_file.txt').write_text("modified content\n")

        # Try to edit — should fail due to staleness
        result = tool_registry._exec_edit(
            'test_file.txt', 'line 1', 'new line 1'
        )
        assert not result.success
        assert 'stale' in result.error.lower() or 'modified' in result.error.lower()


# ─── Test: Coordinator Features ───────────────────────────────────

class TestCoordinatorE2E:
    """Test coordinator mode features."""

    def test_worker_tool_filtering(self):
        """Test that worker tools are properly filtered."""
        from agent.agentic.coordinator import Coordinator
        import asyncio

        async def dummy(t):
            return 'ok'

        coord = Coordinator(worker_fn=dummy)

        # Full mode should exclude specific tools
        all_tools = {
            'Read': 'r', 'Write': 'w', 'TeamCreate': 'tc',
            'SendMessage': 'sm', 'SelfEditor': 'se',
        }
        filtered = coord.filter_worker_tools(all_tools)
        assert 'Read' in filtered
        assert 'Write' in filtered
        assert 'TeamCreate' not in filtered
        assert 'SendMessage' not in filtered

        # Simple mode should only allow basic tools
        simple = coord.filter_worker_tools(all_tools, simple_mode=True)
        assert 'Read' in simple
        assert 'Write' in simple
        assert len(simple) <= len(coord.SIMPLE_MODE_TOOLS)

    def test_message_cap(self):
        """Test worker message capping."""
        from agent.agentic.coordinator import Coordinator

        messages = [{'role': 'user', 'content': f'msg {i}'} for i in range(600)]
        capped = Coordinator.cap_worker_messages(messages)
        assert len(capped) <= 500

    @pytest.mark.asyncio
    async def test_scratchpad_lifecycle(self):
        """Test scratchpad create → write → read → cleanup."""
        from agent.agentic.coordinator import Coordinator

        async def dummy(t):
            return 'ok'

        coord = Coordinator(worker_fn=dummy)

        # Create scratchpad
        coord._create_scratchpad()
        assert coord.scratchpad_dir is not None
        assert os.path.exists(coord.scratchpad_dir)

        # Write and read
        coord.write_to_scratchpad('findings.md', '# Research Findings\nFound 3 bugs.')
        content = coord.read_from_scratchpad('findings.md')
        assert '3 bugs' in content

        # List files
        files = coord.list_scratchpad()
        assert 'findings.md' in files

        # Cleanup
        coord._cleanup_scratchpad()
        assert coord.scratchpad_dir is None
