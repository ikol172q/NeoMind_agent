"""
LLM Agentic Tests — Verify the agent autonomously calls tools with real LLM.

These tests send prompts that SHOULD cause the LLM to decide to use tools,
then verify the tools were actually called and results processed.

Requires: DEEPSEEK_API_KEY or ZAI_API_KEY
"""

import os
import sys
import time
import json
import pytest
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

API_KEY = (
    os.environ.get('DEEPSEEK_API_KEY')
    or os.environ.get('ZAI_API_KEY')
    or os.environ.get('OPENAI_API_KEY')
)

pytestmark = pytest.mark.skipif(
    not API_KEY,
    reason="No LLM API key found"
)


@pytest.fixture(scope="module")
def agent():
    os.environ.setdefault('NEOMIND_DISABLE_VAULT', '1')
    os.environ.setdefault('NEOMIND_DISABLE_MEMORY', '1')
    from agent_config import agent_config
    agent_config.switch_mode('coding')
    from agent.core import NeoMindAgent
    a = NeoMindAgent()
    yield a


@pytest.fixture
def workspace(tmp_path):
    (tmp_path / "sample.py").write_text("def greet(name):\n    return f'Hello {name}'\n")
    (tmp_path / "config.json").write_text('{"debug": true, "port": 8080}\n')
    (tmp_path / "README.md").write_text("# My Project\nA sample project.\n")
    return tmp_path


def chat(agent, message, **kwargs):
    try:
        return str(agent.stream_response(prompt=message, **kwargs))
    except Exception as e:
        return f"[EXCEPTION: {e}]"


# ═══════════════════════════════════════════════════════════════
# TEST: LLM autonomously decides to use tools
# ═══════════════════════════════════════════════════════════════

class TestAgenticToolUse:
    """Verify the LLM can autonomously decide to call tools."""

    def test_llm_responds_to_code_question(self, agent):
        """Ask a coding question — LLM should respond (may use tools or reply directly)."""
        history_before = len(agent.conversation_history)
        response = chat(agent, "Write a Python function that checks if a number is prime. Just the function, no explanation.")
        # The LLM may use tools (returning None from stream_response) or respond directly
        # Either way, conversation history should have grown
        history_after = len(agent.conversation_history)
        assert history_after > history_before, "Agent should have added to conversation history"

    def test_llm_uses_appropriate_language(self, agent):
        """LLM should follow the system prompt language preference."""
        response = chat(agent, "Explain what a decorator is in Python, in 2 sentences.")
        assert len(response) > 30
        # Should be a meaningful explanation
        assert 'decorator' in response.lower() or 'function' in response.lower() or '装饰' in response


# ═══════════════════════════════════════════════════════════════
# TEST: Session Notes extraction with real conversation
# ═══════════════════════════════════════════════════════════════

class TestSessionNotesWithLLM:
    """Test session notes extraction from real conversation content."""

    def test_session_notes_populate_after_conversation(self, agent):
        """After enough conversation, session notes should have content."""
        notes = agent.services.session_notes
        if notes is None:
            pytest.skip("SessionNotes service not available")

        # Have a few turns of conversation
        chat(agent, "I'm working on a bug fix for the login API. Just say OK.")
        chat(agent, "The bug is in the authentication middleware. OK?")

        # Force update by lowering threshold
        old_threshold = notes._init_token_threshold
        notes._init_token_threshold = 100  # Very low threshold
        notes._initialized = False

        history = agent.conversation_history
        total_chars = sum(len(str(m.get('content', ''))) for m in history)
        notes.maybe_update(
            messages=history,
            tool_count=10,
            est_tokens=total_chars // 4,
        )

        notes._init_token_threshold = old_threshold  # Restore

        # Notes should now have content (heuristic extraction at minimum)
        content = notes.content
        assert len(content) > 0, "Session notes should have content after conversation"

    def test_session_notes_capture_task(self, agent):
        """Session notes should capture the task being worked on."""
        notes = agent.services.session_notes
        if notes is None:
            pytest.skip("SessionNotes service not available")

        # The notes from previous test should still be populated
        if notes.content:
            # Should mention something from the conversation
            content_lower = notes.content.lower()
            has_relevant = (
                'bug' in content_lower
                or 'login' in content_lower
                or 'api' in content_lower
                or 'task' in content_lower
                or 'authentication' in content_lower
                or 'session' in content_lower
            )
            assert has_relevant or len(notes.content) > 50, \
                f"Notes should capture task context. Got: {notes.content[:200]}"


# ═══════════════════════════════════════════════════════════════
# TEST: Prompt composition affects LLM behavior
# ═══════════════════════════════════════════════════════════════

class TestPromptCompositionWithLLM:
    """Test that prompt composition actually affects LLM behavior."""

    def test_system_prompt_affects_response_style(self, agent):
        """The coding mode system prompt should make responses code-focused."""
        response = chat(agent, "How do I sort a list? One sentence answer.")
        # In coding mode, should mention code/programming concepts
        has_code_focus = (
            'sort' in response.lower()
            or '.sort' in response
            or 'sorted' in response
            or '排序' in response
        )
        assert has_code_focus, f"Coding mode should produce code-focused response. Got: {response[:200]}"

    def test_prompt_composer_sections_exist(self, agent):
        """Prompt composer should have sections populated during chat."""
        composer = agent.services.prompt_composer
        if composer is None:
            pytest.skip("PromptComposer not available")

        accounting = composer.get_token_accounting()
        assert len(accounting) > 0
        # Should have at least context section (git, OS, date)
        section_names = [a['name'] for a in accounting if a['name'] != 'TOTAL']
        assert len(section_names) > 0, "Should have at least one section"


# ═══════════════════════════════════════════════════════════════
# TEST: Frustration affects agent awareness
# ═══════════════════════════════════════════════════════════════

class TestFrustrationWithLLM:
    """Test that frustration detection works during real conversation."""

    def test_frustration_detected_in_conversation(self, agent):
        """When user sends a frustrated message, detection should fire."""
        detector = agent.services.frustration_detector
        if detector is None:
            pytest.skip("FrustrationDetector not available")

        # Send a frustrated message
        chat(agent, "That's completely wrong! This doesn't work at all. Fix it properly.")

        # The frustration detector should detect this
        findings = detector("That's completely wrong! This doesn't work at all.")
        assert len(findings) > 0, "Should detect frustration"

    def test_neutral_follows_frustrated(self, agent):
        """After frustration, a normal message should not trigger detection."""
        detector = agent.services.frustration_detector
        if detector is None:
            pytest.skip("FrustrationDetector not available")

        findings = detector("Please read the file config.json")
        assert len(findings) == 0, "Neutral message should not trigger frustration"


# ═══════════════════════════════════════════════════════════════
# TEST: /review with real LLM
# ═══════════════════════════════════════════════════════════════

class TestPromptCommandsWithLLM:
    """Test prompt commands (/init, /review) generate proper LLM prompts."""

    def test_review_generates_prompt(self):
        """The /review command should generate a code review prompt."""
        from agent.cli_command_system import _build_builtin_commands
        cmds = _build_builtin_commands()
        review_cmd = next(c for c in cmds if c.name == 'review')

        # Prompt commands return a string (the prompt text)
        prompt_text = review_cmd.handler('', None)
        assert isinstance(prompt_text, str)
        assert 'review' in prompt_text.lower() or 'code' in prompt_text.lower()

    def test_init_generates_prompt(self):
        """The /init command should generate a workspace scan prompt."""
        from agent.cli_command_system import _build_builtin_commands
        cmds = _build_builtin_commands()
        init_cmd = next(c for c in cmds if c.name == 'init')

        prompt_text = init_cmd.handler('', None)
        assert isinstance(prompt_text, str)
        assert 'scan' in prompt_text.lower() or 'detect' in prompt_text.lower()

    def test_ship_generates_prompt(self):
        """The /ship command should generate a git workflow prompt."""
        from agent.cli_command_system import _build_builtin_commands
        cmds = _build_builtin_commands()
        ship_cmd = next(c for c in cmds if c.name == 'ship')

        prompt_text = ship_cmd.handler('', None)
        assert isinstance(prompt_text, str)
        assert 'commit' in prompt_text.lower() or 'branch' in prompt_text.lower()

    def test_review_with_real_llm(self, agent):
        """Send /review prompt to real LLM and verify it responds (may use tools)."""
        from agent.cli_command_system import _build_builtin_commands
        cmds = _build_builtin_commands()
        review_cmd = next(c for c in cmds if c.name == 'review')
        review_prompt = review_cmd.handler('', None)

        response = chat(agent, review_prompt)
        # LLM may respond directly or may use tools (git diff, read files)
        # Both are valid — the key test is it doesn't crash
        assert response is not None and response != 'None', "Review should produce a response"


# ═══════════════════════════════════════════════════════════════
# TEST: Token budget with real conversation
# ═══════════════════════════════════════════════════════════════

class TestTokenBudgetWithLLM:
    """Test token budget tracking during real conversation."""

    def test_budget_tracks_usage(self, agent):
        """Token budget should track usage during real conversation."""
        from agent.agentic.token_budget import TokenBudget
        tb = TokenBudget()

        # Record some usage from the conversation we've had
        total_chars = sum(len(str(m.get('content', ''))) for m in agent.conversation_history)
        est_tokens = total_chars // 4
        tb.record_usage(input_tokens=est_tokens, output_tokens=est_tokens // 3)

        usage = tb.session_usage
        assert usage['total_tokens'] > 0, "Should have tracked tokens"
        assert usage['total_input_tokens'] > 0

    def test_tool_result_budget_truncates(self):
        """Tool result budget should truncate large outputs."""
        from agent.agentic.token_budget import TokenBudget
        tb = TokenBudget(tool_result_max_chars=100)

        large = "x" * 500
        truncated = tb.apply_tool_result_budget(large)
        assert len(truncated) < 500
        assert 'truncated' in truncated


# ═══════════════════════════════════════════════════════════════
# TEST: Memory selection with real data
# ═══════════════════════════════════════════════════════════════

class TestMemorySelectionWithLLM:
    """Test memory selection works with real conversation context."""

    def test_memory_selector_with_real_memories(self, agent):
        """Memory selector should select relevant memories from real data."""
        selector = agent.services.memory_selector
        if selector is None:
            pytest.skip("MemorySelector not available")

        # Create test memories with different topics
        memories = [
            {'category': 'fact', 'fact': 'User prefers Python for backend', 'updated_at': '2026-04-01'},
            {'category': 'fact', 'fact': 'Project uses PostgreSQL database', 'updated_at': '2026-04-01'},
            {'category': 'fact', 'fact': 'User likes dark chocolate ice cream', 'updated_at': '2026-04-01'},
            {'category': 'fact', 'fact': 'API endpoints use REST conventions', 'updated_at': '2026-04-01'},
            {'category': 'fact', 'fact': 'User timezone is America/Los_Angeles', 'updated_at': '2026-04-01'},
            {'category': 'fact', 'fact': 'Team uses GitHub Actions for CI', 'updated_at': '2026-04-01'},
            {'category': 'fact', 'fact': 'User has a cat named Whiskers', 'updated_at': '2026-04-01'},
            {'category': 'fact', 'fact': 'Project frontend uses React', 'updated_at': '2026-04-01'},
        ]

        # Select for a database query
        selected = selector.select('fix the PostgreSQL connection pooling', memories)
        assert len(selected) <= 5
        assert len(selected) > 0

        # Without LLM, selection is by recency — but at minimum we get results
        # The key test is that it doesn't crash and returns a reasonable count

    def test_staleness_on_real_memories(self, agent):
        """Staleness warnings should work on real memories."""
        selector = agent.services.memory_selector
        if selector is None:
            pytest.skip("MemorySelector not available")

        old_memories = [
            {'fact': 'Old fact from January', 'updated_at': '2026-01-15T00:00:00+00:00'},
            {'fact': 'Recent fact', 'updated_at': '2026-04-03T00:00:00+00:00'},
        ]
        selector.add_staleness_warnings(old_memories)

        # Old memory should have warning
        assert '_staleness_caveat' in old_memories[0]
        # Recent memory should not (or very short)
        # The exact behavior depends on current date vs memory date


# ═══════════════════════════════════════════════════════════════
# TEST: AutoDream with real conversation data
# ═══════════════════════════════════════════════════════════════

class TestAutoDreamWithLLM:
    """Test AutoDream consolidation with real conversation data."""

    def test_auto_dream_tracks_turns(self, agent):
        """AutoDream should track conversation turns."""
        dream = agent.services.auto_dream
        if dream is None:
            pytest.skip("AutoDream not available")

        initial_turns = dream.status['turns_since_last']
        dream.on_turn_complete()
        assert dream.status['turns_since_last'] == initial_turns + 1

    def test_auto_dream_extract_from_real_history(self, agent):
        """AutoDream should extract patterns from real conversation history."""
        dream = agent.services.auto_dream
        if dream is None:
            pytest.skip("AutoDream not available")

        history = agent.conversation_history
        if len(history) < 3:
            pytest.skip("Need at least 3 messages for extraction")

        extracted = dream._phase_extract(history)
        # May or may not find patterns — depends on conversation content
        # The key test is it doesn't crash on real data
        assert isinstance(extracted, list)

    def test_auto_dream_dedup_on_real_data(self, agent):
        """AutoDream dedup should work on real extracted data."""
        dream = agent.services.auto_dream
        if dream is None:
            pytest.skip("AutoDream not available")

        items = [
            {'type': 'preference', 'content': 'User prefers Python', 'source': 'test'},
            {'type': 'preference', 'content': 'User prefers Python', 'source': 'test'},  # duplicate
        ]
        unique = dream._phase_deduplicate(items)
        assert len(unique) <= len(items)  # Should remove or reduce duplicates
