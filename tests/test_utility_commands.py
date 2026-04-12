"""
Unit tests for utility_commands module.

Phase 0 - Infrastructure
"""

import pytest
from unittest.mock import MagicMock, patch
from agent.services.utility_commands import (
    handle_mode_command,
    handle_grep_command,
    handle_find_command,
    handle_verbose_command,
    handle_clear_command,
    handle_history_command,
    handle_think_command,
    handle_quit_command,
    handle_exit_command,
    handle_apply_command,
)


class TestHandleModeCommand:
    """Tests for handle_mode_command."""

    def test_show_current_mode(self):
        """Test showing current mode."""
        core = MagicMock()
        core.mode = 'chat'

        result = handle_mode_command(core, 'status')
        assert result == "Current mode: chat"

    def test_switch_to_chat(self):
        """Test switching to chat mode."""
        core = MagicMock()
        core.switch_mode.return_value = True

        result = handle_mode_command(core, 'chat')
        assert "chat mode" in result.lower()
        core.switch_mode.assert_called_once_with('chat')

    def test_switch_to_coding(self):
        """Test switching to coding mode."""
        core = MagicMock()
        core.switch_mode.return_value = True

        result = handle_mode_command(core, 'coding')
        assert "coding mode" in result.lower()
        core.switch_mode.assert_called_once_with('coding')

    def test_show_help(self):
        """Test showing help."""
        core = MagicMock()

        result = handle_mode_command(core, 'help')
        assert '/mode' in result

    def test_invalid_mode(self):
        """Test invalid mode."""
        core = MagicMock()

        result = handle_mode_command(core, 'invalid')
        assert 'Invalid' in result


class TestHandleGrepCommand:
    """Tests for handle_grep_command."""

    def test_no_pattern(self):
        """Test with no pattern provided."""
        core = MagicMock()

        result = handle_grep_command(core, '')
        assert 'Usage' in result

    def test_no_matches(self):
        """Test with no matches."""
        core = MagicMock()

        with patch('agent.services.utility_commands.subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout='')
            result = handle_grep_command(core, 'nonexistent_pattern .')
            assert 'No matches' in result or 'fallback' in result.lower()


class TestHandleFindCommand:
    """Tests for handle_find_command."""

    def test_no_pattern(self):
        """Test with no pattern provided."""
        core = MagicMock()

        result = handle_find_command(core, '')
        assert 'Usage' in result

    def test_find_files(self):
        """Test finding files."""
        core = MagicMock()

        with patch('agent.services.utility_commands.os.walk') as mock_walk:
            mock_walk.return_value = [('/root', [], ['test.py', 'main.py'])]
            result = handle_find_command(core, '*.py .')
            assert 'test.py' in result or 'main.py' in result


class TestHandleVerboseCommand:
    """Tests for handle_verbose_command."""

    def test_verbose_on(self):
        """Test turning verbose on."""
        core = MagicMock()
        core.verbose_mode = False
        core.status_buffer = []

        result = handle_verbose_command(core, 'on')
        assert 'ENABLED' in result

    def test_verbose_off(self):
        """Test turning verbose off."""
        core = MagicMock()
        core.verbose_mode = True
        core.status_buffer = []

        result = handle_verbose_command(core, 'off')
        assert 'DISABLED' in result

    def test_verbose_toggle(self):
        """Test toggling verbose."""
        core = MagicMock()
        core.verbose_mode = False
        core.status_buffer = []

        result = handle_verbose_command(core, 'toggle')
        core.toggle_verbose_mode.assert_called_once()


class TestHandleClearCommand:
    """Tests for handle_clear_command."""

    def test_clear_history(self):
        """Test clearing history."""
        core = MagicMock()

        result = handle_clear_command(core, '')
        assert 'cleared' in result.lower()
        core.clear_history.assert_called_once()


class TestHandleHistoryCommand:
    """Tests for handle_history_command."""

    def test_no_history(self):
        """Test with no history."""
        core = MagicMock()
        core.conversation_history = []

        result = handle_history_command(core, '')
        assert 'No conversation history' in result

    def test_show_history(self):
        """Test showing history."""
        core = MagicMock()
        core.conversation_history = [
            {'role': 'user', 'content': 'Hello'},
            {'role': 'assistant', 'content': 'Hi there!'}
        ]

        result = handle_history_command(core, '')
        assert 'Hello' in result
        assert 'Hi there' in result


class TestHandleThinkCommand:
    """Tests for handle_think_command."""

    def test_toggle_thinking(self):
        """Test toggling thinking mode."""
        core = MagicMock()
        core.thinking_enabled = False

        result = handle_think_command(core, '')
        core.toggle_thinking_mode.assert_called_once()
        assert 'Thinking mode' in result


class TestHandleQuitCommand:
    """Tests for handle_quit_command."""

    def test_quit_message(self):
        """Test quit message."""
        core = MagicMock()

        result = handle_quit_command(core, '')
        assert 'Quit' in result


class TestHandleExitCommand:
    """Tests for handle_exit_command."""

    def test_exit_message(self):
        """Test exit message."""
        core = MagicMock()

        result = handle_exit_command(core, '')
        assert 'Quit' in result  # Should delegate to quit


class TestHandleApplyCommand:
    """Tests for handle_apply_command."""

    def test_apply_with_confirmation(self):
        """Test apply with confirmation."""
        core = MagicMock()
        core._code_changes = [{'file': 'test.py', 'changes': []}]

        result = handle_apply_command(core, '')
        # Should return confirmation prompt or apply result
        assert result is not None

    def test_apply_no_changes(self):
        """Test apply with no pending changes."""
        core = MagicMock()
        core._code_changes = []

        result = handle_apply_command(core, '')
        assert 'No pending' in result or 'no changes' in result.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
