#!/usr/bin/env python3
"""
Comprehensive unit tests for ContextManager.
Tests token counting, context limit checking, history compression,
and interactive management.
"""
import os
import sys
import unittest
from unittest.mock import Mock, patch, MagicMock, call

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.context_manager import ContextManager


class TestContextManagerInitialization(unittest.TestCase):
    """Test ContextManager initialization and basic properties."""

    def test_initialization_with_history(self):
        """Test initialization with conversation history."""
        history = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"}
        ]

        manager = ContextManager(history)

        self.assertEqual(manager.conversation_history, history)
        # Encoding may be None if tiktoken not available
        self.assertTrue(manager._encoding is None or hasattr(manager._encoding, 'encode'))

    def test_initialization_empty_history(self):
        """Test initialization with empty history."""
        manager = ContextManager([])
        self.assertEqual(manager.conversation_history, [])

    @patch('agent.context_manager.HAS_TIKTOKEN', True)
    @patch('agent.context_manager.tiktoken')
    def test_encoding_initialization_with_tiktoken(self, mock_tiktoken):
        """Test encoding initialization when tiktoken is available."""
        mock_encoding = Mock()
        mock_tiktoken.get_encoding.return_value = mock_encoding

        history = []
        manager = ContextManager(history)

        mock_tiktoken.get_encoding.assert_called_once_with("cl100k_base")
        self.assertEqual(manager._encoding, mock_encoding)

    @patch('agent.context_manager.HAS_TIKTOKEN', False)
    def test_encoding_initialization_without_tiktoken(self):
        """Test encoding initialization when tiktoken is not available."""
        history = []
        manager = ContextManager(history)

        self.assertIsNone(manager._encoding)

    @patch('agent.context_manager.HAS_TIKTOKEN', True)
    @patch('agent.context_manager.tiktoken')
    def test_encoding_initialization_failure(self, mock_tiktoken):
        """Test encoding initialization when tiktoken fails."""
        mock_tiktoken.get_encoding.side_effect = Exception("Failed to load")

        history = []
        manager = ContextManager(history)

        self.assertIsNone(manager._encoding)


class TestTokenCounting(unittest.TestCase):
    """Test token counting functionality."""

    def setUp(self):
        """Set up test environment."""
        self.history = [
            {"role": "user", "content": "Hello, world!"},
            {"role": "assistant", "content": "How can I help you?"}
        ]
        self.manager = ContextManager(self.history)

    def test_count_tokens_with_encoding(self):
        """Test token counting with tiktoken encoding."""
        mock_encoding = Mock()
        mock_encoding.encode.return_value = [1, 2, 3, 4, 5]  # 5 tokens
        self.manager._encoding = mock_encoding

        token_count = self.manager.count_tokens("Hello, world!")

        self.assertEqual(token_count, 5)
        mock_encoding.encode.assert_called_once_with("Hello, world!")

    def test_count_tokens_without_encoding(self):
        """Test token counting without tiktoken (fallback)."""
        self.manager._encoding = None

        # Fallback: len(text) // 4
        token_count = self.manager.count_tokens("Hello, world!")  # 13 characters

        self.assertEqual(token_count, 3)  # 13 // 4 = 3

    def test_count_tokens_empty_string(self):
        """Test token counting with empty string."""
        self.manager._encoding = None

        token_count = self.manager.count_tokens("")

        # max(1, 0 // 4) = 1
        self.assertEqual(token_count, 1)

    def test_count_message_tokens(self):
        """Test token counting for a message."""
        self.manager._encoding = None
        message = {"role": "user", "content": "Hello"}

        token_count = self.manager.count_message_tokens(message)

        # "user: Hello" = 11 characters // 4 = 2
        self.assertEqual(token_count, 2)

    def test_count_conversation_tokens(self):
        """Test token counting for entire conversation."""
        self.manager._encoding = None

        # Mock count_message_tokens to return known values
        with patch('agent.context_manager.ContextManager.count_message_tokens') as mock_count:
            mock_count.side_effect = [10, 20, 30]

            # Create history with 3 messages
            history = [
                {"role": "user", "content": "Message 1"},
                {"role": "assistant", "content": "Message 2"},
                {"role": "user", "content": "Message 3"}
            ]
            manager = ContextManager(history)

            total_tokens = manager.count_conversation_tokens()

            self.assertEqual(total_tokens, 60)
            self.assertEqual(mock_count.call_count, 3)

    def test_count_conversation_tokens_custom_messages(self):
        """Test token counting with custom message list."""
        self.manager._encoding = None

        with patch('agent.context_manager.ContextManager.count_message_tokens') as mock_count:
            mock_count.return_value = 5

            custom_messages = [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Tell me a joke."}
            ]

            total_tokens = self.manager.count_conversation_tokens(custom_messages)

            self.assertEqual(total_tokens, 10)
            self.assertEqual(mock_count.call_count, 2)


class TestContextUsage(unittest.TestCase):
    """Test context usage statistics."""

    def setUp(self):
        """Set up test environment."""
        self.history = []
        self.manager = ContextManager(self.history)

    @patch('agent.context_manager.agent_config')
    def test_get_context_usage(self, mock_config):
        """Test getting context usage statistics."""
        # Configure mock config
        mock_config.max_context_tokens = 10000
        mock_config.context_warning_threshold = 0.8  # 80%
        mock_config.context_break_threshold = 0.9    # 90%

        # Mock token counting
        with patch.object(self.manager, 'count_conversation_tokens') as mock_count:
            mock_count.return_value = 5000

            stats = self.manager.get_context_usage()

            self.assertEqual(stats["total_tokens"], 5000)
            self.assertEqual(stats["max_context_tokens"], 10000)
            self.assertEqual(stats["warning_threshold"], 0.8)
            self.assertEqual(stats["break_threshold"], 0.9)
            self.assertEqual(stats["warning_tokens"], 8000)  # 10000 * 0.8
            self.assertEqual(stats["break_tokens"], 9000)    # 10000 * 0.9
            self.assertEqual(stats["percent_used"], 0.5)     # 5000 / 10000
            self.assertFalse(stats["is_near_limit"])         # 5000 < 8000
            self.assertFalse(stats["is_over_break"])         # 5000 < 9000

    @patch('agent.context_manager.agent_config')
    def test_get_context_usage_near_limit(self, mock_config):
        """Test context usage when near limit."""
        mock_config.max_context_tokens = 10000
        mock_config.context_warning_threshold = 0.8
        mock_config.context_break_threshold = 0.9

        with patch.object(self.manager, 'count_conversation_tokens') as mock_count:
            mock_count.return_value = 8500  # Above warning threshold

            stats = self.manager.get_context_usage()

            self.assertTrue(stats["is_near_limit"])  # 8500 >= 8000
            self.assertFalse(stats["is_over_break"]) # 8500 < 9000

    @patch('agent.context_manager.agent_config')
    def test_get_context_usage_over_break(self, mock_config):
        """Test context usage when over break threshold."""
        mock_config.max_context_tokens = 10000
        mock_config.context_warning_threshold = 0.8
        mock_config.context_break_threshold = 0.9

        with patch.object(self.manager, 'count_conversation_tokens') as mock_count:
            mock_count.return_value = 9500  # Above break threshold

            stats = self.manager.get_context_usage()

            self.assertTrue(stats["is_near_limit"])  # 9500 >= 8000
            self.assertTrue(stats["is_over_break"])  # 9500 >= 9000

    @patch('agent.context_manager.agent_config')
    def test_get_context_usage_zero_max_context(self, mock_config):
        """Test context usage with zero max context tokens."""
        mock_config.max_context_tokens = 0
        mock_config.context_warning_threshold = 0.8
        mock_config.context_break_threshold = 0.9

        with patch.object(self.manager, 'count_conversation_tokens') as mock_count:
            mock_count.return_value = 100

            stats = self.manager.get_context_usage()

            self.assertEqual(stats["percent_used"], 0.0)  # division by zero protection


class TestContextLimitChecking(unittest.TestCase):
    """Test context limit checking."""

    def setUp(self):
        """Set up test environment."""
        self.history = []
        self.manager = ContextManager(self.history)

    @patch.object(ContextManager, 'get_context_usage')
    def test_check_context_limit_safe(self, mock_get_usage):
        """Test limit check when well within limits."""
        mock_get_usage.return_value = {
            "total_tokens": 5000,
            "max_context_tokens": 10000,
            "is_near_limit": False,
            "is_over_break": False,
            "warning_tokens": 8000,
            "break_tokens": 9000,
            "warning_threshold": 0.8,
            "break_threshold": 0.9,
            "percent_used": 0.5,
        }

        should_warn, stats = self.manager.check_context_limit(additional_tokens=1000)

        self.assertFalse(should_warn)
        self.assertEqual(stats["total_tokens"], 5000)
        self.assertFalse(stats.get("exceeds_max", False))

    @patch.object(ContextManager, 'get_context_usage')
    def test_check_context_limit_near_warning(self, mock_get_usage):
        """Test limit check when near warning threshold."""
        mock_get_usage.return_value = {
            "total_tokens": 8000,
            "max_context_tokens": 10000,
            "is_near_limit": True,
            "is_over_break": False,
            "warning_tokens": 8000,
            "break_tokens": 9000,
            "warning_threshold": 0.8,
            "break_threshold": 0.9,
            "percent_used": 0.8,
        }

        should_warn, stats = self.manager.check_context_limit()

        self.assertTrue(should_warn)
        self.assertFalse(stats.get("exceeds_max", False))

    @patch.object(ContextManager, 'get_context_usage')
    def test_check_context_limit_exceeds_max(self, mock_get_usage):
        """Test limit check when exceeding max context."""
        mock_get_usage.return_value = {
            "total_tokens": 9500,
            "max_context_tokens": 10000,
            "is_near_limit": True,
            "is_over_break": True,
            "warning_tokens": 8000,
            "break_tokens": 9000,
            "warning_threshold": 0.8,
            "break_threshold": 0.9,
            "percent_used": 0.95,
        }

        should_warn, stats = self.manager.check_context_limit(additional_tokens=1000)

        # total_with_additional = 9500 + 1000 = 10500 > 10000
        self.assertTrue(should_warn)
        self.assertTrue(stats.get("exceeds_max", False))

    @patch.object(ContextManager, 'get_context_usage')
    def test_check_context_limit_within_max(self, mock_get_usage):
        """Test limit check when within max after additional tokens."""
        mock_get_usage.return_value = {
            "total_tokens": 9500,
            "max_context_tokens": 10000,
            "is_near_limit": True,
            "is_over_break": True,
            "warning_tokens": 8000,
            "break_tokens": 9000,
            "warning_threshold": 0.8,
            "break_threshold": 0.9,
            "percent_used": 0.95,
        }

        should_warn, stats = self.manager.check_context_limit(additional_tokens=500)

        # total_with_additional = 9500 + 500 = 10000 <= 10000
        self.assertTrue(should_warn)  # Still warns because is_near_limit is True
        self.assertFalse(stats.get("exceeds_max", False))


class TestHistoryCompression(unittest.TestCase):
    """Test conversation history compression."""

    def setUp(self):
        """Set up test environment."""
        self.history = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Message 1"},
            {"role": "assistant", "content": "Response 1"},
            {"role": "user", "content": "Message 2"},
            {"role": "assistant", "content": "Response 2"},
            {"role": "user", "content": "Message 3"},
            {"role": "assistant", "content": "Response 3"},
        ]
        self.manager = ContextManager(self.history)

    @patch('agent.context_manager.agent_config')
    def test_compress_history_truncate_strategy(self, mock_config):
        """Test compression with truncate strategy."""
        mock_config.compression_strategy = "truncate"
        mock_config.keep_system_messages = True
        mock_config.keep_recent_messages = 2

        with patch.object(self.manager, 'count_conversation_tokens') as mock_count:
            mock_count.side_effect = [100, 40]  # original, compressed

            result = self.manager.compress_history()

            # Should keep system message and 2 most recent non-system messages
            # Recent messages: Message 3, Response 3 (but keep_recent=2 includes both)
            # Actually: keep_recent messages from other_messages (non-system)
            # other_messages: all except system (6 messages)
            # keep_recent=2 → last 2: Message 3, Response 3? Wait ordering: they are already last.
            # So compressed history should have: system, Message 3, Response 3
            compressed_history = self.manager.conversation_history
            self.assertEqual(len(compressed_history), 3)
            self.assertEqual(compressed_history[0]["role"], "system")
            self.assertEqual(compressed_history[1]["content"], "Message 3")
            self.assertEqual(compressed_history[2]["content"], "Response 3")

            self.assertEqual(result["original_messages"], 7)
            self.assertEqual(result["compressed_messages"], 3)
            self.assertEqual(result["original_tokens"], 100)
            self.assertEqual(result["compressed_tokens"], 40)
            self.assertEqual(result["token_reduction"], 60)
            self.assertEqual(result["strategy"], "truncate")

    @patch('agent.context_manager.agent_config')
    def test_compress_history_truncate_no_system(self, mock_config):
        """Test truncate compression without keeping system messages."""
        mock_config.compression_strategy = "truncate"
        mock_config.keep_system_messages = False
        mock_config.keep_recent_messages = 3

        self.manager.compress_history()

        # Should not keep system message, keep 3 most recent non-system messages
        # Non-system messages: all except first system (6 messages)
        # Last 3: Message 3, Response 3? Actually ordering: Message 2, Response 2, Message 3, Response 3 (4). Keep recent 3 → Message 2, Response 2, Message 3? Wait index.
        # Let's trust the implementation
        compressed_history = self.manager.conversation_history
        # Should have 3 messages, none should be system
        self.assertEqual(len(compressed_history), 3)
        for msg in compressed_history:
            self.assertNotEqual(msg["role"], "system")

    @patch('agent.context_manager.agent_config')
    def test_compress_history_truncate_empty_result(self, mock_config):
        """Test truncate compression that would result in empty list."""
        mock_config.compression_strategy = "truncate"
        mock_config.keep_system_messages = False
        mock_config.keep_recent_messages = 0  # Keep no recent messages

        # Create history with no system messages
        history = [
            {"role": "user", "content": "Message 1"},
            {"role": "assistant", "content": "Response 1"},
        ]
        manager = ContextManager(history)

        manager.compress_history()

        # Should keep at least the last message
        self.assertEqual(len(manager.conversation_history), 1)
        self.assertEqual(manager.conversation_history[0]["content"], "Response 1")

    @patch('agent.context_manager.agent_config')
    def test_compress_history_summarize_strategy(self, mock_config):
        """Test compression with summarize strategy (falls back to truncate)."""
        mock_config.compression_strategy = "summarize"
        mock_config.keep_system_messages = True
        mock_config.keep_recent_messages = 1

        with patch.object(self.manager, '_summarize_history') as mock_summarize:
            mock_summarize.return_value = [{"role": "system", "content": "Summarized"}]

            result = self.manager.compress_history()

            mock_summarize.assert_called_once_with(True, 1)
            self.assertEqual(self.manager.conversation_history, [{"role": "system", "content": "Summarized"}])

    @patch('agent.context_manager.agent_config')
    def test_compress_history_custom_strategy(self, mock_config):
        """Test compression with custom strategy override."""
        mock_config.compression_strategy = "truncate"  # Default
        mock_config.keep_system_messages = True
        mock_config.keep_recent_messages = 2

        # Override strategy in method call
        self.manager.compress_history(strategy="truncate")

        # Should use custom strategy
        compressed_history = self.manager.conversation_history
        self.assertGreater(len(compressed_history), 0)

    @patch('agent.context_manager.agent_config')
    def test_compress_history_invalid_strategy(self, mock_config):
        """Test compression with invalid strategy."""
        mock_config.compression_strategy = "invalid"

        with self.assertRaises(ValueError) as context:
            self.manager.compress_history()

        self.assertIn("Unknown compression strategy", str(context.exception))


class TestInteractiveContextManagement(unittest.TestCase):
    """Test interactive context management."""

    def setUp(self):
        """Set up test environment."""
        self.history = []
        self.manager = ContextManager(self.history)

    @patch.object(ContextManager, 'check_context_limit')
    def test_interactive_context_management_no_warning(self, mock_check):
        """Test when no warning is needed."""
        mock_check.return_value = (False, {"total_tokens": 5000})

        result = self.manager.interactive_context_management()

        self.assertTrue(result)
        mock_check.assert_called_once_with(0)

    @patch.object(ContextManager, 'check_context_limit')
    @patch.object(ContextManager, 'prompt_user_for_action')
    @patch('builtins.print')
    def test_interactive_continue_choice(self, mock_print, mock_prompt, mock_check):
        """Test user chooses to continue."""
        mock_check.return_value = (True, {"total_tokens": 8500})
        mock_prompt.return_value = "continue"

        result = self.manager.interactive_context_management(additional_tokens=1000)

        self.assertTrue(result)
        mock_check.assert_called_once_with(1000)
        mock_prompt.assert_called_once_with({"total_tokens": 8500})
        mock_print.assert_any_call("Continuing with current context...")

    @patch.object(ContextManager, 'check_context_limit')
    @patch.object(ContextManager, 'prompt_user_for_action')
    @patch.object(ContextManager, 'compress_history')
    @patch('builtins.print')
    def test_interactive_compress_choice(self, mock_print, mock_compress, mock_prompt, mock_check):
        """Test user chooses to compress history."""
        # First call: near limit
        mock_check.side_effect = [
            (True, {"total_tokens": 8500}),
            (False, {"total_tokens": 4000})  # After compression
        ]
        mock_prompt.return_value = "compress"
        mock_compress.return_value = {
            "original_tokens": 8500,
            "compressed_tokens": 4000,
            "token_reduction": 4500
        }

        result = self.manager.interactive_context_management()

        self.assertTrue(result)
        mock_compress.assert_called_once()
        mock_print.assert_any_call("Compressing history...")
        mock_print.assert_any_call("Compressed from 8500 to 4000 tokens (-4500).")

    @patch.object(ContextManager, 'check_context_limit')
    @patch.object(ContextManager, 'prompt_user_for_action')
    @patch('builtins.print')
    def test_interactive_clear_choice(self, mock_print, mock_prompt, mock_check):
        """Test user chooses to clear history."""
        mock_check.return_value = (True, {"total_tokens": 8500})
        mock_prompt.return_value = "clear"

        # Add some history
        self.manager.conversation_history = [
            {"role": "user", "content": "Message"},
            {"role": "assistant", "content": "Response"}
        ]

        result = self.manager.interactive_context_management()

        self.assertTrue(result)
        self.assertEqual(self.manager.conversation_history, [])
        mock_print.assert_any_call("Clearing conversation history...")

    @patch.object(ContextManager, 'check_context_limit')
    @patch.object(ContextManager, 'prompt_user_for_action')
    @patch('builtins.print')
    def test_interactive_cancel_choice(self, mock_print, mock_prompt, mock_check):
        """Test user chooses to cancel."""
        mock_check.return_value = (True, {"total_tokens": 8500})
        mock_prompt.return_value = "cancel"

        result = self.manager.interactive_context_management()

        self.assertFalse(result)
        mock_print.assert_any_call("Operation cancelled.")

    @patch.object(ContextManager, 'check_context_limit')
    @patch.object(ContextManager, 'prompt_user_for_action')
    @patch.object(ContextManager, 'compress_history')
    @patch('builtins.print')
    def test_interactive_compress_still_near_limit(self, mock_print, mock_compress, mock_prompt, mock_check):
        """Test compression still leaves us near limit (recursive call)."""
        # Simulate that after compression we're still near limit
        mock_check.side_effect = [
            (True, {"total_tokens": 8500}),
            (True, {"total_tokens": 8000}),  # Still near limit after compression
            (True, {"total_tokens": 8000})   # Recursive call check
        ]
        mock_prompt.side_effect = ["compress", "continue"]  # First compress, then continue
        mock_compress.return_value = {
            "original_tokens": 8500,
            "compressed_tokens": 8000,
            "token_reduction": 500
        }

        result = self.manager.interactive_context_management()

        self.assertTrue(result)
        self.assertEqual(mock_check.call_count, 3)
        self.assertEqual(mock_prompt.call_count, 2)
        mock_print.assert_any_call("Still near limit after compression.")


class TestPromptUserForAction(unittest.TestCase):
    """Test user prompt for action."""

    def setUp(self):
        """Set up test environment."""
        self.history = []
        self.manager = ContextManager(self.history)

    @patch('builtins.input', return_value='1')
    @patch('builtins.print')
    def test_prompt_continue(self, mock_print, mock_input):
        """Test user input for continue."""
        stats = {
            "total_tokens": 8500,
            "max_context_tokens": 10000,
            "percent_used": 0.85,
            "warning_threshold": 0.8,
            "break_threshold": 0.9,
            "warning_tokens": 8000,
            "break_tokens": 9000,
        }

        choice = self.manager.prompt_user_for_action(stats)

        self.assertEqual(choice, "continue")
        mock_input.assert_called_once_with("Enter choice (1-4): ")
        # Should print warning info
        self.assertGreater(mock_print.call_count, 0)

    @patch('builtins.input', side_effect=['5', '2'])  # Invalid, then valid
    @patch('builtins.print')
    def test_prompt_invalid_then_valid(self, mock_print, mock_input):
        """Test invalid input followed by valid input."""
        stats = {
            "total_tokens": 8500,
            "max_context_tokens": 10000,
            "percent_used": 0.85,
            "warning_threshold": 0.8,
            "break_threshold": 0.9,
            "warning_tokens": 8000,
            "break_tokens": 9000,
        }

        choice = self.manager.prompt_user_for_action(stats)

        self.assertEqual(choice, "compress")
        self.assertEqual(mock_input.call_count, 2)
        mock_print.assert_any_call("Invalid choice. Please enter 1, 2, 3, or 4.")

    @patch('builtins.input', side_effect=KeyboardInterrupt)
    @patch('builtins.print')
    def test_prompt_keyboard_interrupt(self, mock_print, mock_input):
        """Test keyboard interrupt during input."""
        stats = {
            "total_tokens": 8500,
            "max_context_tokens": 10000,
            "percent_used": 0.85,
            "warning_threshold": 0.8,
            "break_threshold": 0.9,
            "warning_tokens": 8000,
            "break_tokens": 9000,
        }

        choice = self.manager.prompt_user_for_action(stats)

        self.assertEqual(choice, "cancel")
        # Should handle KeyboardInterrupt gracefully

    def test_prompt_with_exceeds_max(self):
        """Test prompt includes exceeds max warning."""
        stats = {
            "total_tokens": 9500,
            "max_context_tokens": 10000,
            "exceeds_max": True,
            "percent_used": 0.95,
            "warning_threshold": 0.8,
            "break_threshold": 0.9,
            "warning_tokens": 8000,
            "break_tokens": 9000,
        }

        with patch('builtins.print') as mock_print:
            with patch('builtins.input', return_value='1'):
                self.manager.prompt_user_for_action(stats)

                # Should print exceeds max warning
                printed_text = ' '.join(str(call) for call in mock_print.call_args_list)
                self.assertIn("exceed", printed_text)


if __name__ == '__main__':
    unittest.main()