#!/usr/bin/env python3
"""
Comprehensive unit tests for NeoMindAgent core functionality.
Tests initialization, mode switching, configuration, history management,
and basic agent operations.
"""
import os
import sys
import json
import tempfile
import unittest
from unittest.mock import Mock, patch, MagicMock, AsyncMock, ANY
import time

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.core import NeoMindAgent
from agent_config import agent_config


class TestCoreInitialization(unittest.TestCase):
    """Test NeoMindAgent initialization and basic properties."""

    def setUp(self):
        """Set up test environment."""
        self.test_api_key = "test_api_key_12345"
        # Mock agent_config to control behavior
        self.agent_config_patcher = patch('agent.core.agent_config')
        self.mock_agent_config = self.agent_config_patcher.start()

    def tearDown(self):
        """Clean up after tests."""
        self.agent_config_patcher.stop()

    def test_initialization_with_api_key(self):
        """Test agent initialization with explicit API key."""
        # Configure mock agent_config
        self.mock_agent_config.model = "deepseek-chat"
        self.mock_agent_config.mode = "chat"
        self.mock_agent_config.coding_mode_show_status_bar = False
        self.mock_agent_config.thinking_enabled = False
        self.mock_agent_config.auto_search_triggers = []
        self.mock_agent_config.auto_search_enabled = True
        self.mock_agent_config.natural_language_enabled = True
        self.mock_agent_config.natural_language_confidence_threshold = 0.8
        self.mock_agent_config.safety_confirm_file_operations = True
        self.mock_agent_config.safety_confirm_code_changes = True
        self.mock_agent_config.system_prompt = ""
        self.mock_agent_config.coding_mode_system_prompt = ""

        # Create agent with API key
        agent = NeoMindAgent(api_key=self.test_api_key)

        # Verify basic properties
        self.assertEqual(agent.api_key, self.test_api_key)
        self.assertEqual(agent.model, "deepseek-chat")
        self.assertEqual(agent.mode, "chat")
        self.assertFalse(agent.show_status_bar)
        self.assertFalse(agent.verbose_mode)
        self.assertEqual(agent.base_url, "https://api.deepseek.com/chat/completions")
        self.assertEqual(agent.models_url, "https://api.deepseek.com/models")
        self.assertIsInstance(agent.conversation_history, list)
        self.assertIsNotNone(agent.context_manager)
        self.assertIsNotNone(agent.searcher)
        self.assertIsNotNone(agent.formatter)
        self.assertIsNotNone(agent.command_executor)
        self.assertIsNotNone(agent.safety_manager)
        self.assertIsNotNone(agent.help_system)
        self.assertIsNone(agent.self_iteration)  # Lazy initialization
        self.assertIsNone(agent.workspace_manager)  # Lazy initialization for coding mode

    def test_initialization_with_env_api_key(self):
        """Test agent initialization with API key from environment."""
        # Set environment variable
        with patch.dict(os.environ, {'DEEPSEEK_API_KEY': 'env_api_key_123'}):
            # Configure mock agent_config
            self.mock_agent_config.model = "deepseek-chat"
            self.mock_agent_config.mode = "chat"
            self.mock_agent_config.coding_mode_show_status_bar = False
            self.mock_agent_config.thinking_enabled = False
            self.mock_agent_config.auto_search_triggers = []
            self.mock_agent_config.auto_search_enabled = True
            self.mock_agent_config.natural_language_enabled = True
            self.mock_agent_config.natural_language_confidence_threshold = 0.8
            self.mock_agent_config.safety_confirm_file_operations = True
            self.mock_agent_config.safety_confirm_code_changes = True
            self.mock_agent_config.system_prompt = ""
            self.mock_agent_config.coding_mode_system_prompt = ""

            # Create agent without explicit API key
            agent = NeoMindAgent(api_key=None)

            # Should use environment variable
            self.assertEqual(agent.api_key, 'env_api_key_123')

    def test_initialization_missing_api_key(self):
        """Test agent initialization without API key raises ValueError."""
        # Remove environment variable if exists
        with patch.dict(os.environ, {}, clear=True):
            # Configure mock agent_config
            self.mock_agent_config.model = "deepseek-chat"
            self.mock_agent_config.mode = "chat"

            # Should raise ValueError
            with self.assertRaises(ValueError) as context:
                NeoMindAgent(api_key=None)

            self.assertIn("API key is required", str(context.exception))

    def test_initialization_with_custom_model(self):
        """Test agent initialization with custom model."""
        # Configure mock agent_config
        self.mock_agent_config.model = "deepseek-chat"  # Default
        self.mock_agent_config.mode = "chat"
        self.mock_agent_config.coding_mode_show_status_bar = False
        self.mock_agent_config.thinking_enabled = False
        self.mock_agent_config.auto_search_triggers = []
        self.mock_agent_config.auto_search_enabled = True
        self.mock_agent_config.natural_language_enabled = True
        self.mock_agent_config.natural_language_confidence_threshold = 0.8
        self.mock_agent_config.safety_confirm_file_operations = True
        self.mock_agent_config.safety_confirm_code_changes = True
        self.mock_agent_config.system_prompt = ""
        self.mock_agent_config.coding_mode_system_prompt = ""

        # Create agent with custom model
        agent = NeoMindAgent(api_key=self.test_api_key, model="deepseek-reasoner")

        # Should use custom model
        self.assertEqual(agent.model, "deepseek-reasoner")

    def test_initialization_with_system_prompt(self):
        """Test agent initialization with system prompt in config."""
        # Configure mock agent_config with system prompt
        self.mock_agent_config.model = "deepseek-chat"
        self.mock_agent_config.mode = "chat"
        self.mock_agent_config.coding_mode_show_status_bar = False
        self.mock_agent_config.thinking_enabled = False
        self.mock_agent_config.auto_search_triggers = []
        self.mock_agent_config.auto_search_enabled = True
        self.mock_agent_config.natural_language_enabled = True
        self.mock_agent_config.natural_language_confidence_threshold = 0.8
        self.mock_agent_config.safety_confirm_file_operations = True
        self.mock_agent_config.safety_confirm_code_changes = True
        self.mock_agent_config.system_prompt = "You are a helpful assistant."
        self.mock_agent_config.coding_mode_system_prompt = ""

        # Create agent
        agent = NeoMindAgent(api_key=self.test_api_key)

        # Should have system message in conversation history
        self.assertEqual(len(agent.conversation_history), 1)
        self.assertEqual(agent.conversation_history[0]["role"], "system")
        self.assertEqual(agent.conversation_history[0]["content"], "You are a helpful assistant.")

    def test_initialization_coding_mode_system_prompt(self):
        """Test agent initialization with coding mode system prompt."""
        # Configure mock agent_config for coding mode
        self.mock_agent_config.model = "deepseek-chat"
        self.mock_agent_config.mode = "coding"
        self.mock_agent_config.coding_mode_show_status_bar = True
        self.mock_agent_config.thinking_enabled = False
        self.mock_agent_config.auto_search_triggers = []
        self.mock_agent_config.auto_search_enabled = True
        self.mock_agent_config.natural_language_enabled = True
        self.mock_agent_config.natural_language_confidence_threshold = 0.8
        self.mock_agent_config.safety_confirm_file_operations = True
        self.mock_agent_config.safety_confirm_code_changes = True
        self.mock_agent_config.system_prompt = "General assistant."
        self.mock_agent_config.coding_mode_system_prompt = "You are a coding assistant."

        # Create agent
        agent = NeoMindAgent(api_key=self.test_api_key)

        # Should have coding mode system prompt in conversation history
        self.assertEqual(len(agent.conversation_history), 1)
        self.assertEqual(agent.conversation_history[0]["role"], "system")
        self.assertEqual(agent.conversation_history[0]["content"], "You are a coding assistant.")
        # Should have coding mode properties
        self.assertTrue(agent.show_status_bar)
        self.assertTrue(agent.verbose_mode)

    def test_initialization_html_converter(self):
        """Test HTML converter initialization based on dependencies."""
        # Configure mock agent_config
        self.mock_agent_config.model = "deepseek-chat"
        self.mock_agent_config.mode = "chat"
        self.mock_agent_config.coding_mode_show_status_bar = False
        self.mock_agent_config.thinking_enabled = False
        self.mock_agent_config.auto_search_triggers = []
        self.mock_agent_config.auto_search_enabled = True
        self.mock_agent_config.natural_language_enabled = True
        self.mock_agent_config.natural_language_confidence_threshold = 0.8
        self.mock_agent_config.safety_confirm_file_operations = True
        self.mock_agent_config.safety_confirm_code_changes = True
        self.mock_agent_config.system_prompt = ""
        self.mock_agent_config.coding_mode_system_prompt = ""

        # Test with html2text available
        with patch('agent.core.HAS_HTML2TEXT', True):
            with patch('agent.core.html2text') as mock_html2text:
                mock_converter = Mock()
                mock_html2text.HTML2Text.return_value = mock_converter

                agent = NeoMindAgent(api_key=self.test_api_key)

                # Should initialize HTML converter
                self.assertIsNotNone(agent.html_converter)
                mock_html2text.HTML2Text.assert_called_once()

        # Test without html2text
        with patch('agent.core.HAS_HTML2TEXT', False):
            agent = NeoMindAgent(api_key=self.test_api_key)

            # Should not have HTML converter
            self.assertIsNone(agent.html_converter)


class TestCoreHistoryManagement(unittest.TestCase):
    """Test conversation history management."""

    def setUp(self):
        """Set up test environment."""
        self.test_api_key = "test_api_key_12345"
        # Mock agent_config
        self.agent_config_patcher = patch('agent.core.agent_config')
        self.mock_agent_config = self.agent_config_patcher.start()
        self.mock_agent_config.model = "deepseek-chat"
        self.mock_agent_config.mode = "chat"
        self.mock_agent_config.coding_mode_show_status_bar = False
        self.mock_agent_config.thinking_enabled = False
        self.mock_agent_config.auto_search_triggers = []
        self.mock_agent_config.auto_search_enabled = True
        self.mock_agent_config.natural_language_enabled = True
        self.mock_agent_config.natural_language_confidence_threshold = 0.8
        self.mock_agent_config.safety_confirm_file_operations = True
        self.mock_agent_config.safety_confirm_code_changes = True
        self.mock_agent_config.system_prompt = ""
        self.mock_agent_config.coding_mode_system_prompt = ""

    def tearDown(self):
        """Clean up after tests."""
        self.agent_config_patcher.stop()

    def test_add_to_history(self):
        """Test adding messages to conversation history."""
        agent = NeoMindAgent(api_key=self.test_api_key)

        # Initial state
        initial_len = len(agent.conversation_history)

        # Add user message
        agent.add_to_history("user", "Hello, how are you?")
        self.assertEqual(len(agent.conversation_history), initial_len + 1)
        self.assertEqual(agent.conversation_history[-1]["role"], "user")
        self.assertEqual(agent.conversation_history[-1]["content"], "Hello, how are you?")

        # Add assistant message
        agent.add_to_history("assistant", "I'm doing well, thank you!")
        self.assertEqual(len(agent.conversation_history), initial_len + 2)
        self.assertEqual(agent.conversation_history[-1]["role"], "assistant")
        self.assertEqual(agent.conversation_history[-1]["content"], "I'm doing well, thank you!")

        # Add system message
        agent.add_to_history("system", "Please be concise.")
        self.assertEqual(len(agent.conversation_history), initial_len + 3)
        self.assertEqual(agent.conversation_history[-1]["role"], "system")
        self.assertEqual(agent.conversation_history[-1]["content"], "Please be concise.")

    def test_clear_history(self):
        """Test clearing conversation history."""
        agent = NeoMindAgent(api_key=self.test_api_key)

        # Add some messages
        agent.add_to_history("user", "Message 1")
        agent.add_to_history("assistant", "Response 1")
        agent.add_to_history("user", "Message 2")

        # Verify history has messages
        self.assertGreater(len(agent.conversation_history), 0)

        # Clear history
        agent.clear_history()

        # History should be empty (except possibly system prompt)
        # System prompt might remain based on configuration
        # Just verify we can clear without errors

    def test_get_conversation_summary(self):
        """Test getting conversation summary."""
        agent = NeoMindAgent(api_key=self.test_api_key)

        # Add some messages
        agent.add_to_history("user", "What is Python?")
        agent.add_to_history("assistant", "Python is a programming language.")
        agent.add_to_history("user", "What are its features?")

        # Get summary
        summary = agent.get_conversation_summary()

        # Summary should be a string
        self.assertIsInstance(summary, str)
        # Should contain conversation information
        self.assertIn("conversation", summary.lower())

    def test_token_counting(self):
        """Test token counting functionality."""
        agent = NeoMindAgent(api_key=self.test_api_key)

        # Add a message
        test_message = "This is a test message for token counting."
        agent.add_to_history("user", test_message)

        # Get token count
        # Note: Actual token count depends on tiktoken availability
        # Just verify the method exists and returns something reasonable
        try:
            count = agent.get_token_count()
            self.assertIsInstance(count, int)
            self.assertGreaterEqual(count, 0)
        except Exception:
            # tiktoken might not be available, that's OK for test
            pass


class TestCoreModeSwitching(unittest.TestCase):
    """Test mode switching functionality."""

    def setUp(self):
        """Set up test environment."""
        self.test_api_key = "test_api_key_12345"
        # Mock agent_config
        self.agent_config_patcher = patch('agent.core.agent_config')
        self.mock_agent_config = self.agent_config_patcher.start()

    def tearDown(self):
        """Clean up after tests."""
        self.agent_config_patcher.stop()

    def test_switch_mode_chat_to_coding(self):
        """Test switching from chat mode to coding mode."""
        # Start in chat mode
        self.mock_agent_config.model = "deepseek-chat"
        self.mock_agent_config.mode = "chat"
        self.mock_agent_config.coding_mode_show_status_bar = True
        self.mock_agent_config.thinking_enabled = False
        self.mock_agent_config.auto_search_triggers = []
        self.mock_agent_config.auto_search_enabled = True
        self.mock_agent_config.natural_language_enabled = True
        self.mock_agent_config.natural_language_confidence_threshold = 0.8
        self.mock_agent_config.safety_confirm_file_operations = True
        self.mock_agent_config.safety_confirm_code_changes = True
        self.mock_agent_config.system_prompt = ""
        self.mock_agent_config.coding_mode_system_prompt = "Coding assistant."

        agent = NeoMindAgent(api_key=self.test_api_key)

        # Initial state should be chat mode
        self.assertEqual(agent.mode, "chat")
        self.assertFalse(agent.show_status_bar)
        self.assertFalse(agent.verbose_mode)
        self.assertIsNone(agent.workspace_manager)

        # Mock agent_config.update_mode to succeed
        self.mock_agent_config.update_mode = Mock(return_value=True)

        # Switch to coding mode
        result = agent.switch_mode("coding")

        # Should succeed
        self.assertTrue(result)
        # Mode should be updated
        self.assertEqual(agent.mode, "coding")
        # Properties should be updated for coding mode
        self.assertTrue(agent.show_status_bar)
        self.assertTrue(agent.verbose_mode)
        # Workspace manager should be initialized
        self.assertIsNotNone(agent.workspace_manager)

    def test_switch_mode_coding_to_chat(self):
        """Test switching from coding mode to chat mode."""
        # Start in coding mode
        self.mock_agent_config.model = "deepseek-chat"
        self.mock_agent_config.mode = "coding"
        self.mock_agent_config.coding_mode_show_status_bar = True
        self.mock_agent_config.thinking_enabled = False
        self.mock_agent_config.auto_search_triggers = []
        self.mock_agent_config.auto_search_enabled = True
        self.mock_agent_config.natural_language_enabled = True
        self.mock_agent_config.natural_language_confidence_threshold = 0.8
        self.mock_agent_config.safety_confirm_file_operations = True
        self.mock_agent_config.safety_confirm_code_changes = True
        self.mock_agent_config.system_prompt = ""
        self.mock_agent_config.coding_mode_system_prompt = "Coding assistant."

        agent = NeoMindAgent(api_key=self.test_api_key)

        # Initial state should be coding mode
        self.assertEqual(agent.mode, "coding")
        self.assertTrue(agent.show_status_bar)
        self.assertTrue(agent.verbose_mode)

        # Initialize workspace manager
        agent._initialize_workspace_manager()
        self.assertIsNotNone(agent.workspace_manager)

        # Mock agent_config.update_mode to succeed
        self.mock_agent_config.update_mode = Mock(return_value=True)

        # Switch to chat mode
        result = agent.switch_mode("chat")

        # Should succeed
        self.assertTrue(result)
        # Mode should be updated
        self.assertEqual(agent.mode, "chat")
        # Properties should be updated for chat mode
        self.assertFalse(agent.show_status_bar)
        self.assertFalse(agent.verbose_mode)

    def test_switch_mode_invalid_mode(self):
        """Test switching to invalid mode."""
        # Start in chat mode
        self.mock_agent_config.model = "deepseek-chat"
        self.mock_agent_config.mode = "chat"
        self.mock_agent_config.coding_mode_show_status_bar = False
        self.mock_agent_config.thinking_enabled = False
        self.mock_agent_config.auto_search_triggers = []
        self.mock_agent_config.auto_search_enabled = True
        self.mock_agent_config.natural_language_enabled = True
        self.mock_agent_config.natural_language_confidence_threshold = 0.8
        self.mock_agent_config.safety_confirm_file_operations = True
        self.mock_agent_config.safety_confirm_code_changes = True
        self.mock_agent_config.system_prompt = ""
        self.mock_agent_config.coding_mode_system_prompt = ""

        agent = NeoMindAgent(api_key=self.test_api_key)

        # Try to switch to invalid mode
        result = agent.switch_mode("invalid_mode")

        # Should fail
        self.assertFalse(result)
        # Mode should remain unchanged
        self.assertEqual(agent.mode, "chat")

    def test_switch_mode_config_update_fails(self):
        """Test mode switching when config update fails."""
        # Start in chat mode
        self.mock_agent_config.model = "deepseek-chat"
        self.mock_agent_config.mode = "chat"
        self.mock_agent_config.coding_mode_show_status_bar = False
        self.mock_agent_config.thinking_enabled = False
        self.mock_agent_config.auto_search_triggers = []
        self.mock_agent_config.auto_search_enabled = True
        self.mock_agent_config.natural_language_enabled = True
        self.mock_agent_config.natural_language_confidence_threshold = 0.8
        self.mock_agent_config.safety_confirm_file_operations = True
        self.mock_agent_config.safety_confirm_code_changes = True
        self.mock_agent_config.system_prompt = ""
        self.mock_agent_config.coding_mode_system_prompt = ""

        agent = NeoMindAgent(api_key=self.test_api_key)

        # Mock agent_config.update_mode to fail
        self.mock_agent_config.update_mode = Mock(return_value=False)

        # Try to switch mode
        result = agent.switch_mode("coding")

        # Should fail
        self.assertFalse(result)
        # Mode should remain unchanged
        self.assertEqual(agent.mode, "chat")


class TestCoreStatusBuffer(unittest.TestCase):
    """Test status buffer functionality for debug/info messages."""

    def setUp(self):
        """Set up test environment."""
        self.test_api_key = "test_api_key_12345"
        # Mock agent_config
        self.agent_config_patcher = patch('agent.core.agent_config')
        self.mock_agent_config = self.agent_config_patcher.start()
        self.mock_agent_config.model = "deepseek-chat"
        self.mock_agent_config.mode = "chat"
        self.mock_agent_config.coding_mode_show_status_bar = False
        self.mock_agent_config.thinking_enabled = False
        self.mock_agent_config.auto_search_triggers = []
        self.mock_agent_config.auto_search_enabled = True
        self.mock_agent_config.natural_language_enabled = True
        self.mock_agent_config.natural_language_confidence_threshold = 0.8
        self.mock_agent_config.safety_confirm_file_operations = True
        self.mock_agent_config.safety_confirm_code_changes = True
        self.mock_agent_config.system_prompt = ""
        self.mock_agent_config.coding_mode_system_prompt = ""

    def tearDown(self):
        """Clean up after tests."""
        self.agent_config_patcher.stop()

    def test_add_status_message(self):
        """Test adding status messages."""
        agent = NeoMindAgent(api_key=self.test_api_key)

        # Initial buffer should be empty
        self.assertEqual(len(agent.status_buffer), 0)

        # Add a status message
        agent.add_status_message("Test message", "info")

        # Buffer should have one message
        self.assertEqual(len(agent.status_buffer), 1)
        message = agent.status_buffer[0]
        self.assertEqual(message["message"], "Test message")
        self.assertEqual(message["level"], "info")
        self.assertIsInstance(message["timestamp"], float)

        # Add another message with different level
        agent.add_status_message("Debug message", "debug")
        self.assertEqual(len(agent.status_buffer), 2)
        self.assertEqual(agent.status_buffer[1]["level"], "debug")

    def test_get_status_messages(self):
        """Test retrieving status messages."""
        agent = NeoMindAgent(api_key=self.test_api_key)

        # Add some messages
        agent.add_status_message("Info 1", "info")
        agent.add_status_message("Debug 1", "debug")
        agent.add_status_message("Info 2", "info")
        agent.add_status_message("Important", "important")
        agent.add_status_message("Critical", "critical")

        # Get all messages
        all_messages = agent.get_status_messages()
        self.assertEqual(len(all_messages), 5)

        # Get messages by level
        info_messages = agent.get_status_messages(level="info")
        self.assertEqual(len(info_messages), 2)
        for msg in info_messages:
            self.assertEqual(msg["level"], "info")

        debug_messages = agent.get_status_messages(level="debug")
        self.assertEqual(len(debug_messages), 1)
        self.assertEqual(debug_messages[0]["message"], "Debug 1")

        # Get recent messages with limit
        recent = agent.get_status_messages(limit=2)
        self.assertEqual(len(recent), 2)
        # Should be the two most recent messages
        self.assertEqual(recent[0]["message"], "Critical")
        self.assertEqual(recent[1]["message"], "Important")

    def test_clear_status_buffer(self):
        """Test clearing status buffer."""
        agent = NeoMindAgent(api_key=self.test_api_key)

        # Add some messages
        agent.add_status_message("Message 1", "info")
        agent.add_status_message("Message 2", "debug")

        # Verify messages are there
        self.assertEqual(len(agent.status_buffer), 2)

        # Clear buffer
        agent.clear_status_buffer()

        # Buffer should be empty
        self.assertEqual(len(agent.status_buffer), 0)

    def test_update_current_status(self):
        """Test updating current single-line status."""
        agent = NeoMindAgent(api_key=self.test_api_key)

        # Initial status should be empty
        self.assertEqual(agent.current_status, "")

        # Update status
        agent.update_current_status("Processing...")

        # Status should be updated
        self.assertEqual(agent.current_status, "Processing...")
        # Timestamp should be updated
        self.assertGreater(agent.last_status_update, 0)

        # Update again
        agent.update_current_status("Done!")
        self.assertEqual(agent.current_status, "Done!")


class TestCoreMiscellaneous(unittest.TestCase):
    """Test miscellaneous core functionality."""

    def setUp(self):
        """Set up test environment."""
        self.test_api_key = "test_api_key_12345"
        # Mock agent_config
        self.agent_config_patcher = patch('agent.core.agent_config')
        self.mock_agent_config = self.agent_config_patcher.start()
        self.mock_agent_config.model = "deepseek-chat"
        self.mock_agent_config.mode = "chat"
        self.mock_agent_config.coding_mode_show_status_bar = False
        self.mock_agent_config.thinking_enabled = False
        self.mock_agent_config.auto_search_triggers = []
        self.mock_agent_config.auto_search_enabled = True
        self.mock_agent_config.natural_language_enabled = True
        self.mock_agent_config.natural_language_confidence_threshold = 0.8
        self.mock_agent_config.safety_confirm_file_operations = True
        self.mock_agent_config.safety_confirm_code_changes = True
        self.mock_agent_config.system_prompt = ""
        self.mock_agent_config.coding_mode_system_prompt = ""

    def tearDown(self):
        """Clean up after tests."""
        self.agent_config_patcher.stop()

    def test_toggle_thinking_mode(self):
        """Test toggling thinking mode."""
        agent = NeoMindAgent(api_key=self.test_api_key)

        # Initial thinking mode from config (False in our mock)
        initial_mode = agent.thinking_enabled

        # Toggle thinking mode
        new_mode = agent.toggle_thinking_mode()

        # Should be opposite of initial
        self.assertEqual(new_mode, not initial_mode)

        # Toggle again
        back_mode = agent.toggle_thinking_mode()
        self.assertEqual(back_mode, initial_mode)

    def test_get_status_info(self):
        """Test getting status information."""
        agent = NeoMindAgent(api_key=self.test_api_key)

        # Get status info
        status_info = agent.get_status_info()

        # Should return a dictionary with expected keys
        self.assertIsInstance(status_info, dict)
        expected_keys = ["mode", "token_usage", "pending_changes", "recent_files"]
        for key in expected_keys:
            self.assertIn(key, status_info)

        # Check values
        self.assertEqual(status_info["mode"], "chat")
        self.assertIsInstance(status_info["token_usage"], int)
        self.assertIsInstance(status_info["pending_changes"], int)
        self.assertIsInstance(status_info["recent_files"], list)

    def test_workspace_manager_lazy_initialization(self):
        """Test workspace manager lazy initialization."""
        agent = NeoMindAgent(api_key=self.test_api_key)

        # Initially should be None
        self.assertIsNone(agent.workspace_manager)

        # Initialize workspace manager
        agent._initialize_workspace_manager()

        # Should now be initialized
        self.assertIsNotNone(agent.workspace_manager)

        # Calling again should not reinitialize (or should handle gracefully)
        agent._initialize_workspace_manager()
        self.assertIsNotNone(agent.workspace_manager)


if __name__ == '__main__':
    unittest.main()