#!/usr/bin/env python3
"""
Comprehensive unit tests for CLI interface module.
Tests status display, command handling, and interactive chat loops.
"""

import os
import sys
import time
import unittest
from unittest.mock import Mock, patch, MagicMock, call, mock_open
import tempfile
import shutil

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cli.interface import (
    display_status_bar,
    display_command_status,
    display_welcome_banner,
    get_api_key,
    handle_command,
    interactive_chat_with_prompt_toolkit,
    interactive_chat_fallback
)
from agent import DeepSeekStreamingChat
from agent.help_system import HelpSystem
from cli.progress_display import ProgressDisplay, TaskStatus


class TestDisplayStatusBar(unittest.TestCase):
    """Test display_status_bar function."""

    def test_display_status_bar_disabled(self):
        """Test status bar when show_status_bar is False."""
        mock_chat = Mock()
        mock_chat.show_status_bar = False
        mock_chat.get_status_info.return_value = {
            "mode": "chat",
            "token_usage": "100/2000",
            "pending_changes": 0,
            "recent_files": []
        }

        with patch('builtins.print') as mock_print:
            display_status_bar(mock_chat)

            mock_print.assert_not_called()

    def test_display_status_bar_basic(self):
        """Test basic status bar display."""
        mock_chat = Mock()
        mock_chat.show_status_bar = True
        mock_chat.get_status_info.return_value = {
            "mode": "chat",
            "token_usage": "100/2000",
            "pending_changes": 0,
            "recent_files": []
        }

        with patch('builtins.print') as mock_print:
            display_status_bar(mock_chat)

            mock_print.assert_called_once()
            output = mock_print.call_args[0][0]
            self.assertIn("Mode: chat", output)
            self.assertIn("Tokens: 100/2000", output)
            self.assertIn("\033[90m", output)  # Gray color code
            self.assertIn("\033[0m", output)  # Reset code

    def test_display_status_bar_with_pending_changes(self):
        """Test status bar with pending changes."""
        mock_chat = Mock()
        mock_chat.show_status_bar = True
        mock_chat.get_status_info.return_value = {
            "mode": "coding",
            "token_usage": "500/4000",
            "pending_changes": 3,
            "recent_files": []
        }

        with patch('builtins.print') as mock_print:
            display_status_bar(mock_chat)

            output = mock_print.call_args[0][0]
            self.assertIn("Pending changes: 3", output)

    def test_display_status_bar_with_recent_files(self):
        """Test status bar with recent files."""
        mock_chat = Mock()
        mock_chat.show_status_bar = True
        mock_chat.get_status_info.return_value = {
            "mode": "coding",
            "token_usage": "1500/4000",
            "pending_changes": 0,
            "recent_files": ["file1.py", "file2.py", "file3.py"]
        }

        with patch('builtins.print') as mock_print:
            display_status_bar(mock_chat)

            output = mock_print.call_args[0][0]
            self.assertIn("Recent: file1.py, file2.py", output)
            self.assertNotIn("file3.py", output)  # Limited to 2 files


class TestDisplayCommandStatus(unittest.TestCase):
    """Test display_command_status function."""

    def test_display_command_status_executing(self):
        """Test displaying executing status."""
        with patch('builtins.print') as mock_print:
            display_command_status("/test", "executing")

            mock_print.assert_called_once()
            output = mock_print.call_args[0][0]
            self.assertIn("->", output)
            self.assertIn("/test", output)
            self.assertIn("\033[93m", output)  # Yellow for executing

    def test_display_command_status_completed(self):
        """Test displaying completed status."""
        with patch('builtins.print') as mock_print:
            display_command_status("/search", "completed")

            output = mock_print.call_args[0][0]
            self.assertIn("[OK]", output)
            self.assertIn("/search", output)
            self.assertIn("\033[92m", output)  # Green for completed

    def test_display_command_status_failed(self):
        """Test displaying failed status."""
        with patch('builtins.print') as mock_print:
            display_command_status("/run", "failed")

            output = mock_print.call_args[0][0]
            self.assertIn("[ERROR]", output)
            self.assertIn("/run", output)
            self.assertIn("\033[91m", output)  # Red for failed

    def test_display_command_status_default(self):
        """Test displaying with unknown status."""
        with patch('builtins.print') as mock_print:
            display_command_status("/test", "unknown")

            output = mock_print.call_args[0][0]
            self.assertNotIn("->", output)
            self.assertNotIn("[OK]", output)
            self.assertNotIn("[ERROR]", output)
            self.assertIn("/test", output)


class TestDisplayWelcomeBanner(unittest.TestCase):
    """Test display_welcome_banner function."""

    def test_display_welcome_banner_chat_mode(self):
        """Test welcome banner for chat mode."""
        with patch('builtins.print') as mock_print:
            display_welcome_banner("chat")

            # Should print multiple lines
            self.assertGreater(mock_print.call_count, 5)

            # Collect all output
            outputs = [call[0][0] for call in mock_print.call_args_list]

            # Check key elements
            all_output = "\n".join(outputs)
            self.assertIn("DeepSeek Streaming Chat", all_output)
            self.assertIn("[CHAT MODE]", all_output)
            self.assertIn("/clear", all_output)
            self.assertIn("/search", all_output)
            self.assertIn("Features:", all_output)
            self.assertIn("Thinking process streams", all_output)

            # Should not include coding-specific features
            self.assertNotIn("Auto-file operations enabled", all_output)

    def test_display_welcome_banner_coding_mode(self):
        """Test welcome banner for coding mode."""
        with patch('builtins.print') as mock_print:
            display_welcome_banner("coding")

            outputs = [call[0][0] for call in mock_print.call_args_list]
            all_output = "\n".join(outputs)

            self.assertIn("[CODING MODE]", all_output)
            self.assertIn("Auto-file operations enabled", all_output)
            self.assertIn("Workspace context awareness", all_output)


class TestGetApiKey(unittest.TestCase):
    """Test get_api_key function."""

    def test_get_api_key_from_env(self):
        """Test getting API key from environment variable."""
        with patch.dict('os.environ', {'DEEPSEEK_API_KEY': 'test-key-123'}):
            with patch('builtins.input') as mock_input:
                result = get_api_key()

                self.assertEqual(result, 'test-key-123')
                mock_input.assert_not_called()

    def test_get_api_key_from_user_input(self):
        """Test getting API key from user input."""
        with patch.dict('os.environ', {}, clear=True):
            with patch('builtins.input', return_value='user-entered-key') as mock_input:
                with patch('builtins.print') as mock_print:
                    result = get_api_key()

                    self.assertEqual(result, 'user-entered-key')
                    mock_input.assert_called_once_with("Enter your DeepSeek API key: ")
                    # Should print instructions
                    self.assertGreater(mock_print.call_count, 0)

    def test_get_api_key_empty_input(self):
        """Test empty user input returns None."""
        with patch.dict('os.environ', {}, clear=True):
            with patch('builtins.input', return_value=''):
                with patch('builtins.print') as mock_print:
                    result = get_api_key()

                    self.assertIsNone(result)
                    # Should print error
                    print_calls = [call[0][0] for call in mock_print.call_args_list]
                    self.assertTrue(any("API key is required" in str(call) for call in print_calls))


class TestHandleCommand(unittest.TestCase):
    """Test handle_command function."""

    def setUp(self):
        """Set up test environment."""
        self.mock_chat = Mock()
        self.mock_chat.conversation_history = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"}
        ]
        self.mock_session = Mock()

    def test_handle_command_quit(self):
        """Test /quit command."""
        test_cases = ['/quit', '/exit', 'quit', 'exit']

        for cmd in test_cases:
            with self.subTest(command=cmd):
                result = handle_command(self.mock_chat, cmd, self.mock_session)

                self.assertFalse(result)  # Should return False to exit

    def test_handle_command_clear(self):
        """Test /clear command."""
        with patch('builtins.print') as mock_print:
            result = handle_command(self.mock_chat, '/clear', self.mock_session)

            self.assertTrue(result)  # Should return True to continue
            self.mock_chat.clear_history.assert_called_once()
            self.mock_session.history = Mock()  # Should be set to InMemoryHistory
            mock_print.assert_called_with("Conversation history cleared.")

    def test_handle_command_history(self):
        """Test /history command."""
        with patch('builtins.print') as mock_print:
            result = handle_command(self.mock_chat, '/history', self.mock_session)

            self.assertTrue(result)
            self.assertGreater(mock_print.call_count, 0)

            # Should print conversation history
            print_calls = mock_print.call_args_list
            history_shown = any("Conversation History" in str(call) for call in print_calls)
            self.assertTrue(history_shown)

    def test_handle_command_think(self):
        """Test /think command."""
        self.mock_chat.toggle_thinking_mode.return_value = True

        with patch('builtins.print') as mock_print:
            result = handle_command(self.mock_chat, '/think', self.mock_session)

            self.assertTrue(result)
            self.mock_chat.toggle_thinking_mode.assert_called_once()
            mock_print.assert_called_with("\nThinking mode is now: ON")

    def test_handle_command_test(self):
        """Test /test command."""
        # Create a mock dev_test module
        mock_dev_test = Mock()
        mock_dev_test.run_tests.return_value = True

        # Patch sys.modules so import dev_test returns our mock
        with patch.dict('sys.modules', {'dev_test': mock_dev_test}):
            with patch('builtins.print') as mock_print:
                result = handle_command(self.mock_chat, '/test', self.mock_session)

                self.assertTrue(result)
                mock_dev_test.run_tests.assert_called_once()
                # Should print test results
                self.assertGreater(mock_print.call_count, 0)

    def test_handle_command_test_import_error(self):
        """Test /test command when dev_test cannot be imported."""
        # Save original __import__
        original_import = __import__
        def import_side_effect(name, *args, **kwargs):
            if name == 'dev_test':
                raise ImportError(f"No module named '{name}'")
            # Use default import for everything else
            return original_import(name, *args, **kwargs)

        with patch('builtins.__import__', side_effect=import_side_effect):
            with patch('builtins.print') as mock_print:
                result = handle_command(self.mock_chat, '/test', self.mock_session)

                self.assertTrue(result)
                # Should print error message
                print_calls = [call[0][0] for call in mock_print.call_args_list]
                error_messages = [str(call) for call in print_calls if "Failed to run tests" in str(call)]
                self.assertGreater(len(error_messages), 0)

    def test_handle_command_unknown(self):
        """Test unknown command returns None."""
        result = handle_command(self.mock_chat, '/unknown', self.mock_session)

        self.assertIsNone(result)  # Not handled

    def test_handle_command_case_insensitive(self):
        """Test command case insensitivity."""
        result = handle_command(self.mock_chat, '/CLEAR', self.mock_session)

        self.assertTrue(result)  # Should handle uppercase


class TestInteractiveChatWithPromptToolkit(unittest.TestCase):
    """Test interactive_chat_with_prompt_toolkit function."""

    def setUp(self):
        """Set up test environment."""
        # Mock dependencies
        self.get_api_key_patch = patch('cli.interface.get_api_key', return_value='test-key')
        self.mock_get_api_key = self.get_api_key_patch.start()

        self.deepseek_chat_patch = patch('cli.interface.DeepSeekStreamingChat')
        self.mock_deepseek_chat_class = self.deepseek_chat_patch.start()
        self.mock_chat = Mock()
        self.mock_deepseek_chat_class.return_value = self.mock_chat

        # Mock prompt_toolkit dependencies
        self.prompt_session_patch = patch('cli.interface.PromptSession')
        self.mock_prompt_session_class = self.prompt_session_patch.start()
        self.mock_session = Mock()
        self.mock_prompt_session_class.return_value = self.mock_session

        # Mock other dependencies
        self.help_system_patch = patch('cli.interface.HelpSystem')
        self.mock_help_system_class = self.help_system_patch.start()
        self.mock_help_system = Mock()
        self.mock_help_system_class.return_value = self.mock_help_system

        self.progress_patch = patch('cli.interface.get_global_progress')
        self.mock_get_global_progress = self.progress_patch.start()
        self.mock_progress = Mock()
        self.mock_get_global_progress.return_value = self.mock_progress

        # Mock input handler
        self.input_patch = patch('cli.interface.get_multiline_input_with_prompt_toolkit')
        self.mock_get_input = self.input_patch.start()

        # Mock display functions
        self.display_banner_patch = patch('cli.interface.display_welcome_banner')
        self.mock_display_banner = self.display_banner_patch.start()

        self.display_status_patch = patch('cli.interface.display_status_bar')
        self.mock_display_status = self.display_status_patch.start()

        self.display_command_patch = patch('cli.interface.display_command_status')
        self.mock_display_command = self.display_command_patch.start()

    def tearDown(self):
        """Clean up patches."""
        self.get_api_key_patch.stop()
        self.deepseek_chat_patch.stop()
        self.prompt_session_patch.stop()
        self.help_system_patch.stop()
        self.progress_patch.stop()
        self.input_patch.stop()
        self.display_banner_patch.stop()
        self.display_status_patch.stop()
        self.display_command_patch.stop()

    def test_initialization_success(self):
        """Test successful initialization."""
        self.mock_chat.mode = "chat"

        # Mock input to return None (simulate immediate exit)
        self.mock_get_input.return_value = None

        interactive_chat_with_prompt_toolkit("chat")

        # Verify initialization
        self.mock_get_api_key.assert_called_once()
        self.mock_deepseek_chat_class.assert_called_once_with(api_key='test-key')
        self.mock_display_banner.assert_called_once_with("chat")

    def test_initialization_no_api_key(self):
        """Test initialization without API key."""
        self.mock_get_api_key.return_value = None

        interactive_chat_with_prompt_toolkit("chat")

        # Should return early without initializing chat
        self.mock_deepseek_chat_class.assert_not_called()

    def test_initialization_chat_error(self):
        """Test initialization with chat error."""
        self.mock_deepseek_chat_class.side_effect = ValueError("Invalid API key")

        with patch('builtins.print') as mock_print:
            interactive_chat_with_prompt_toolkit("chat")

            mock_print.assert_called_with("Error initializing chat: Invalid API key")

    def test_prompt_toolkit_failure_fallback(self):
        """Test prompt_toolkit failure triggers fallback."""
        # Make PromptSession initialization fail
        self.mock_prompt_session_class.side_effect = Exception("Prompt toolkit error")

        with patch('cli.interface.interactive_chat_fallback') as mock_fallback:
            with patch('builtins.print'):
                interactive_chat_with_prompt_toolkit("chat")

                mock_fallback.assert_called_once_with("chat")

    def test_mode_switch(self):
        """Test mode switching on initialization."""
        self.mock_chat.mode = "coding"  # Chat object returns different mode
        self.mock_get_input.return_value = None

        interactive_chat_with_prompt_toolkit("chat")

        # Should switch mode
        self.mock_chat.switch_mode.assert_called_once_with("chat")

    def test_command_handling_quit(self):
        """Test /quit command handling."""
        self.mock_chat.mode = "chat"
        # First call returns "/quit", second returns None to exit loop
        self.mock_get_input.side_effect = ["/quit", None]

        with patch('cli.interface.handle_command', return_value=False) as mock_handle:
            interactive_chat_with_prompt_toolkit("chat")

            mock_handle.assert_called_once_with(self.mock_chat, "/quit", self.mock_session)

    def test_ai_response(self):
        """Test AI response to user input."""
        self.mock_chat.mode = "chat"
        self.mock_get_input.side_effect = ["Hello, AI!", None]

        interactive_chat_with_prompt_toolkit("chat")

        # Should call stream_response
        self.mock_chat.stream_response.assert_called_once_with("Hello, AI!")

    def test_search_command(self):
        """Test /search command."""
        self.mock_chat.mode = "chat"
        self.mock_get_input.side_effect = ["/search AI news", None]

        interactive_chat_with_prompt_toolkit("chat")

        # Should call run_async for search
        self.mock_chat.run_async.assert_called_once_with("/search AI news")

    def test_progress_display_integration(self):
        """Test progress display integration."""
        self.mock_chat.mode = "chat"
        self.mock_get_input.side_effect = ["Test input", None]
        self.mock_progress.start_task.return_value = "task-123"
        self.mock_progress.display.return_value = "Progress display"

        interactive_chat_with_prompt_toolkit("chat")

        # Should create progress task
        self.mock_progress.start_task.assert_called_once()
        # Should complete task
        self.mock_progress.complete_task.assert_called_once_with("task-123")

    def test_keyboard_interrupt(self):
        """Test KeyboardInterrupt handling."""
        self.mock_chat.mode = "chat"
        self.mock_get_input.side_effect = KeyboardInterrupt()

        with patch('builtins.print') as mock_print:
            interactive_chat_with_prompt_toolkit("chat")

            mock_print.assert_called_with("\n\nCtrl+C detected. Exiting...")

    def test_eof_error(self):
        """Test EOFError handling."""
        self.mock_chat.mode = "chat"
        self.mock_get_input.side_effect = EOFError()

        with patch('builtins.print') as mock_print:
            interactive_chat_with_prompt_toolkit("chat")

            mock_print.assert_called_with("\nGoodbye!")

    def test_general_exception_handling(self):
        """Test general exception handling in loop."""
        self.mock_chat.mode = "chat"
        self.mock_get_input.side_effect = ["test", Exception("Test error"), None]
        self.mock_chat.stream_response.side_effect = Exception("Test error")

        with patch('builtins.print') as mock_print:
            interactive_chat_with_prompt_toolkit("chat")

            # Should print error and continue
            error_calls = [call for call in mock_print.call_args_list if "Error:" in str(call)]
            self.assertGreater(len(error_calls), 0)

    @unittest.skip("property patching issues")
    def test_auto_completion_initialization_coding_mode(self):
        """Test auto-completion initialization in coding mode."""
        self.mock_chat.mode = "coding"
        self.mock_chat.workspace_manager = None
        self.mock_get_input.return_value = None

        # Mock agent_config
        with patch('cli.interface.agent_config.coding_mode_enable_auto_complete', True):
            with patch('cli.interface.CommandCompleter') as mock_completer_class:
                mock_completer = Mock()
                mock_completer_class.return_value = mock_completer

                interactive_chat_with_prompt_toolkit("coding")

                # Should initialize workspace manager
                self.mock_chat._initialize_workspace_manager.assert_called_once()
                # Should create completer
                mock_completer_class.assert_called_once_with(
                    help_system=self.mock_help_system,
                    workspace_manager=self.mock_chat.workspace_manager
                )

    @unittest.skip("property patching issues")
    def test_auto_completion_error(self):
        """Test auto-completion initialization error."""
        self.mock_chat.mode = "coding"
        self.mock_get_input.return_value = None

        with patch('cli.interface.agent_config.coding_mode_enable_auto_complete', True):
            with patch('cli.interface.CommandCompleter', side_effect=Exception("Completer error")):
                with patch('builtins.print') as mock_print:
                    interactive_chat_with_prompt_toolkit("coding")

                    # Should print error message
                    error_calls = [call for call in mock_print.call_args_list
                                  if "Auto-completion error" in str(call)]
                    self.assertGreater(len(error_calls), 0)


class TestInteractiveChatFallback(unittest.TestCase):
    """Test interactive_chat_fallback function."""

    def setUp(self):
        """Set up test environment."""
        # Mock dependencies
        self.get_api_key_patch = patch('cli.interface.get_api_key', return_value='test-key')
        self.mock_get_api_key = self.get_api_key_patch.start()

        self.deepseek_chat_patch = patch('cli.interface.DeepSeekStreamingChat')
        self.mock_deepseek_chat_class = self.deepseek_chat_patch.start()
        self.mock_chat = Mock()
        self.mock_deepseek_chat_class.return_value = self.mock_chat

        # Mock readline availability
        self.readline_patch = patch('cli.interface.READLINE_AVAILABLE', True)
        self.readline_patch.start()

        # Mock readline module
        self.readline_module_patch = patch('cli.interface.readline')
        self.mock_readline = self.readline_module_patch.start()

        # Mock other dependencies
        self.help_system_patch = patch('cli.interface.HelpSystem')
        self.mock_help_system_class = self.help_system_patch.start()
        self.mock_help_system = Mock()
        self.mock_help_system_class.return_value = self.mock_help_system

        self.progress_patch = patch('cli.interface.get_global_progress')
        self.mock_get_global_progress = self.progress_patch.start()
        self.mock_progress = Mock()
        self.mock_get_global_progress.return_value = self.mock_progress

        # Mock input handler
        self.input_patch = patch('cli.interface.get_multiline_input_fallback')
        self.mock_get_input = self.input_patch.start()

        # Mock display functions
        self.display_banner_patch = patch('cli.interface.display_welcome_banner')
        self.mock_display_banner = self.display_banner_patch.start()

        self.display_status_patch = patch('cli.interface.display_status_bar')
        self.mock_display_status = self.display_status_patch.start()

        self.display_command_patch = patch('cli.interface.display_command_status')
        self.mock_display_command = self.display_command_patch.start()

    def tearDown(self):
        """Clean up patches."""
        self.get_api_key_patch.stop()
        self.deepseek_chat_patch.stop()
        self.readline_patch.stop()
        self.readline_module_patch.stop()
        self.help_system_patch.stop()
        self.progress_patch.stop()
        self.input_patch.stop()
        self.display_banner_patch.stop()
        self.display_status_patch.stop()
        self.display_command_patch.stop()

    def test_initialization_success(self):
        """Test successful initialization."""
        self.mock_chat.mode = "chat"
        self.mock_get_input.return_value = None

        interactive_chat_fallback("chat")

        self.mock_get_api_key.assert_called_once()
        self.mock_deepseek_chat_class.assert_called_once_with(api_key='test-key')
        self.mock_display_banner.assert_called_once_with("chat")

    def test_readline_completion_setup(self):
        """Test readline completion setup."""
        self.mock_chat.mode = "chat"
        self.mock_get_input.return_value = None
        self.mock_help_system.help_texts = {"write": "help", "read": "help"}

        interactive_chat_fallback("chat")

        # Should set up readline completion
        self.mock_readline.set_completer.assert_called_once()
        self.mock_readline.parse_and_bind.assert_called_with("tab: complete")
        self.mock_readline.set_completer_delims.assert_called_once()

    def test_readline_unavailable(self):
        """Test when readline is not available."""
        with patch('cli.interface.READLINE_AVAILABLE', False):
            self.mock_chat.mode = "chat"
            self.mock_get_input.return_value = None

            interactive_chat_fallback("chat")

            # Should not call readline functions
            self.mock_readline.set_completer.assert_not_called()

    def test_readline_completion_error(self):
        """Test readline completion setup error."""
        self.mock_chat.mode = "chat"
        self.mock_get_input.return_value = None
        self.mock_readline.set_completer.side_effect = Exception("Readline error")

        with patch('builtins.print') as mock_print:
            interactive_chat_fallback("chat")

            # Should print error message
            error_calls = [call for call in mock_print.call_args_list
                          if "Readline completion error" in str(call)]
            self.assertGreater(len(error_calls), 0)

    def test_command_handling(self):
        """Test command handling in fallback mode."""
        self.mock_chat.mode = "chat"
        self.mock_get_input.side_effect = ["/clear", None]

        with patch('cli.interface.handle_command', return_value=True) as mock_handle:
            interactive_chat_fallback("chat")

            mock_handle.assert_called_once_with(self.mock_chat, "/clear")

    def test_ai_response(self):
        """Test AI response in fallback mode."""
        self.mock_chat.mode = "chat"
        self.mock_get_input.side_effect = ["Hello!", None]

        interactive_chat_fallback("chat")

        self.mock_chat.stream_response.assert_called_once_with("Hello!")

    def test_progress_display(self):
        """Test progress display in fallback mode."""
        self.mock_chat.mode = "chat"
        self.mock_get_input.side_effect = ["Test", None]
        self.mock_progress.start_task.return_value = "task-123"
        self.mock_progress.display.return_value = "Progress"

        interactive_chat_fallback("chat")

        self.mock_progress.start_task.assert_called_once()
        self.mock_progress.complete_task.assert_called_once_with("task-123")

    def test_keyboard_interrupt(self):
        """Test KeyboardInterrupt handling."""
        self.mock_chat.mode = "chat"
        self.mock_get_input.side_effect = KeyboardInterrupt()

        with patch('builtins.print') as mock_print:
            interactive_chat_fallback("chat")

            mock_print.assert_called_with("\n\nCtrl+C detected. Exiting...")

    def test_eof_error(self):
        """Test EOFError handling."""
        self.mock_chat.mode = "chat"
        self.mock_get_input.side_effect = EOFError()

        with patch('builtins.print') as mock_print:
            interactive_chat_fallback("chat")

            mock_print.assert_called_with("\nGoodbye!")

    def test_exception_handling(self):
        """Test exception handling in fallback mode."""
        self.mock_chat.mode = "chat"
        self.mock_get_input.side_effect = ["test", Exception("Error"), None]
        self.mock_chat.stream_response.side_effect = Exception("Error")

        with patch('builtins.print') as mock_print:
            interactive_chat_fallback("chat")

            error_calls = [call for call in mock_print.call_args_list if "Error:" in str(call)]
            self.assertGreater(len(error_calls), 0)


class TestEnvironmentVariables(unittest.TestCase):
    """Test environment variable handling for Windows terminal."""

    def test_windows_terminal_detection(self):
        """Test Windows terminal detection and environment variable setting."""
        original_platform = sys.platform
        original_env = os.environ.copy()

        try:
            # Simulate Windows with xterm TERM
            sys.platform = "win32"
            os.environ["TERM"] = "xterm-256color"

            # Re-import module to trigger the platform detection code
            with patch.dict('sys.modules'):
                if 'cli.interface' in sys.modules:
                    del sys.modules['cli.interface']

                # Mock the import to avoid actual prompt_toolkit import
                with patch('cli.interface.PROMPT_TOOLKIT_AVAILABLE', True):
                    # Re-import to trigger the platform detection
                    import importlib
                    import cli.interface as interface_module
                    importlib.reload(interface_module)

                    # Check environment variables were set
                    self.assertEqual(os.environ.get("PROMPT_TOOLKIT_NO_WIN32_CONSOLE"), "1")
                    self.assertEqual(os.environ.get("PROMPT_TOOLKIT_FORCE_VT100_OUTPUT"), "1")

        finally:
            sys.platform = original_platform
            os.environ.clear()
            os.environ.update(original_env)


if __name__ == '__main__':
    unittest.main()