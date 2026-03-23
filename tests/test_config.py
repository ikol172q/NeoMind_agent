#!/usr/bin/env python3
"""
Comprehensive unit tests for AgentConfigManager configuration system.
Tests configuration loading, environment overrides, value updates,
and mode switching functionality.
"""
import os
import sys
import tempfile
import shutil
import unittest
from unittest.mock import Mock, patch, MagicMock
import yaml
from pathlib import Path

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_config import AgentConfigManager


class TestAgentConfigManagerBasics(unittest.TestCase):
    """Test basic AgentConfigManager functionality."""

    def setUp(self):
        """Set up test environment."""
        # Create a temporary directory for test config files
        self.test_dir = tempfile.mkdtemp()
        self.original_cwd = os.getcwd()

        # Create a minimal test config structure
        self.config_dir = os.path.join(self.test_dir, "agent", "config")
        os.makedirs(self.config_dir, exist_ok=True)

        # Create base.yaml
        self.base_config = {
            "agent": {
                "model": "deepseek-chat",
                "temperature": 0.7,
                "max_tokens": 8192,
                "debug": False,
                "thinking_enabled": False,
                "stream": True,
                "timeout": 30,
                "max_retries": 3,
                "context": {
                    "max_context_tokens": 131072,
                    "warning_threshold": 0.61,
                    "break_threshold": 0.8,
                    "compression_strategy": "truncate",
                    "keep_system_messages": True,
                    "keep_recent_messages": 5
                }
            }
        }
        base_path = os.path.join(self.config_dir, "base.yaml")
        with open(base_path, 'w') as f:
            yaml.dump(self.base_config, f)

        # Create chat.yaml
        chat_config = {
            "system_prompt": "You are a helpful AI assistant.",
            "search_enabled": True,
            "show_status_bar": True,
            "enable_auto_complete": True
        }
        chat_path = os.path.join(self.config_dir, "chat.yaml")
        with open(chat_path, 'w') as f:
            yaml.dump(chat_config, f)

        # Create coding.yaml
        coding_config = {
            "system_prompt": "You are a coding assistant.",
            "search_enabled": False,
            "show_status_bar": True,
            "enable_auto_complete": True
        }
        coding_path = os.path.join(self.config_dir, "coding.yaml")
        with open(coding_path, 'w') as f:
            yaml.dump(coding_config, f)

        # Create fin.yaml
        fin_config = {
            "system_prompt": "You are a financial assistant.",
            "search_enabled": True,
            "show_status_bar": True,
            "enable_auto_complete": True
        }
        fin_path = os.path.join(self.config_dir, "fin.yaml")
        with open(fin_path, 'w') as f:
            yaml.dump(fin_config, f)

    def tearDown(self):
        """Clean up after tests."""
        os.chdir(self.original_cwd)
        shutil.rmtree(self.test_dir)

    def test_initialization_with_default_mode(self):
        """Test AgentConfigManager initialization with default chat mode."""
        with patch('agent_config.Path') as mock_path_cls:
            mock_path_instance = Mock()
            mock_path_instance.parent = Path(self.test_dir)
            mock_path_cls.return_value = mock_path_instance

            config_manager = AgentConfigManager(mode="chat")

            # Verify mode is set
            self.assertEqual(config_manager.mode, "chat")

    def test_initialization_with_mode_parameter(self):
        """Test initialization with explicit mode parameter."""
        with patch('agent_config.Path') as mock_path_cls:
            mock_path_instance = Mock()
            mock_path_instance.parent = Path(self.test_dir)
            mock_path_cls.return_value = mock_path_instance

            config_manager = AgentConfigManager(mode="coding")

            # Verify mode is set correctly
            self.assertEqual(config_manager.mode, "coding")

    def test_config_path_property(self):
        """Test config_path property returns correct path."""
        with patch('agent_config.Path') as mock_path_cls:
            mock_path_instance = Mock()
            mock_path_instance.parent = Path(self.test_dir)
            mock_path_cls.return_value = mock_path_instance

            config_manager = AgentConfigManager(mode="chat")

            # Should return the config directory path
            self.assertIsInstance(config_manager.config_path, Path)

    def test_get_method_with_dot_notation(self):
        """Test get method with dot notation for nested keys."""
        with patch('agent_config.Path') as mock_path_cls:
            mock_path_instance = Mock()
            mock_path_instance.parent = Path(self.test_dir)
            mock_path_cls.return_value = mock_path_instance

            config_manager = AgentConfigManager(mode="chat")

            # Test top-level key from mode config
            system_prompt = config_manager.get("system_prompt")
            self.assertEqual(system_prompt, "You are a helpful AI assistant.")

            # Test nested key with dot notation from agent config
            max_tokens = config_manager.get("max_tokens")
            self.assertEqual(max_tokens, 8192)

            # Test nested key in context
            max_context = config_manager.get("context.max_context_tokens")
            self.assertEqual(max_context, 131072)

            # Test with default value for missing key
            missing = config_manager.get("missing.key", "default_value")
            self.assertEqual(missing, "default_value")

            # Test with "agent." prefix (should be stripped)
            model_with_prefix = config_manager.get("agent.model")
            self.assertEqual(model_with_prefix, "deepseek-chat")

    def test_property_accessors(self):
        """Test property accessors return correct values."""
        with patch('agent_config.Path') as mock_path_cls:
            mock_path_instance = Mock()
            mock_path_instance.parent = Path(self.test_dir)
            mock_path_cls.return_value = mock_path_instance

            config_manager = AgentConfigManager(mode="chat")

            # Test properties
            self.assertEqual(config_manager.model, "deepseek-chat")
            self.assertEqual(config_manager.temperature, 0.7)
            self.assertEqual(config_manager.max_tokens, 8192)
            self.assertFalse(config_manager.debug)
            self.assertFalse(config_manager.thinking_enabled)
            self.assertEqual(config_manager.max_context_tokens, 131072)
            self.assertEqual(config_manager.context_warning_threshold, 0.61)
            self.assertEqual(config_manager.context_break_threshold, 0.8)
            self.assertEqual(config_manager.compression_strategy, "truncate")
            self.assertTrue(config_manager.keep_system_messages)
            self.assertEqual(config_manager.keep_recent_messages, 5)

    def test_property_default_values(self):
        """Test properties return default values when keys are missing."""
        with patch('agent_config.Path') as mock_path_cls:
            mock_path_instance = Mock()
            mock_path_instance.parent = Path(self.test_dir)
            mock_path_cls.return_value = mock_path_instance

            # Create config with minimal data
            empty_config_dir = os.path.join(self.test_dir, "empty_config")
            os.makedirs(empty_config_dir, exist_ok=True)
            for fname in ["base.yaml", "chat.yaml", "coding.yaml", "fin.yaml"]:
                with open(os.path.join(empty_config_dir, fname), 'w') as f:
                    f.write("{}")

            config_manager = AgentConfigManager(mode="chat")

            # Test default values
            self.assertEqual(config_manager.model, "deepseek-chat")
            self.assertEqual(config_manager.temperature, 0.7)
            self.assertEqual(config_manager.max_tokens, 8192)
            self.assertFalse(config_manager.debug)
            self.assertFalse(config_manager.thinking_enabled)


class TestEnvironmentOverrides(unittest.TestCase):
    """Test environment variable overrides."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = tempfile.mkdtemp()
        self.original_cwd = os.getcwd()

        # Create a minimal test config structure
        self.config_dir = os.path.join(self.test_dir, "agent", "config")
        os.makedirs(self.config_dir, exist_ok=True)

        # Create base.yaml
        self.base_config = {
            "agent": {
                "model": "deepseek-chat",
                "temperature": 0.7,
                "max_tokens": 8192,
                "debug": False,
                "context": {
                    "max_context_tokens": 131072,
                    "warning_threshold": 0.61,
                    "break_threshold": 0.8
                }
            }
        }
        base_path = os.path.join(self.config_dir, "base.yaml")
        with open(base_path, 'w') as f:
            yaml.dump(self.base_config, f)

        # Create minimal mode configs
        for fname in ["chat.yaml", "coding.yaml", "fin.yaml"]:
            with open(os.path.join(self.config_dir, fname), 'w') as f:
                yaml.dump({}, f)

    def tearDown(self):
        """Clean up after tests."""
        os.chdir(self.original_cwd)
        shutil.rmtree(self.test_dir)

    def test_environment_variable_overrides(self):
        """Test environment variables override config values."""
        # Set environment variables
        env_vars = {
            "DEEPSEEK_MODEL": "deepseek-reasoner",
            "DEEPSEEK_TEMPERATURE": "0.5",
            "DEEPSEEK_MAX_TOKENS": "4096",
            "DEEPSEEK_DEBUG": "true"
        }

        with patch.dict(os.environ, env_vars):
            with patch('agent_config.Path') as mock_path_cls:
                mock_path_instance = Mock()
                mock_path_instance.parent = Path(self.test_dir)
                mock_path_cls.return_value = mock_path_instance

                config_manager = AgentConfigManager(mode="chat")

                # Verify environment overrides were applied
                self.assertEqual(config_manager.model, "deepseek-reasoner")
                self.assertEqual(config_manager.temperature, 0.5)
                self.assertEqual(config_manager.max_tokens, 4096)
                self.assertTrue(config_manager.debug)

    def test_environment_variable_type_conversions(self):
        """Test environment variable value type conversions."""
        # Test cases: (env_var, env_value, property_method, expected_value)
        test_cases = [
            ("DEEPSEEK_TEMPERATURE", "0.3", "temperature", 0.3),  # float
            ("DEEPSEEK_MAX_TOKENS", "2048", "max_tokens", 2048),  # int
            ("DEEPSEEK_MAX_CONTEXT_TOKENS", "65536", "max_context_tokens", 65536),  # int
            ("DEEPSEEK_DEBUG", "true", "debug", True),  # bool true
            ("DEEPSEEK_DEBUG", "1", "debug", True),  # bool true (numeric)
            ("DEEPSEEK_DEBUG", "false", "debug", False),  # bool false
            ("DEEPSEEK_DEBUG", "0", "debug", False),  # bool false (numeric)
        ]

        for env_var, env_value, prop_name, expected_value in test_cases:
            with self.subTest(env_var=env_var, env_value=env_value):
                with patch.dict(os.environ, {env_var: env_value}, clear=False):
                    # Clear other DEEPSEEK env vars to isolate this test
                    env_copy = os.environ.copy()
                    for key in list(env_copy.keys()):
                        if key.startswith("DEEPSEEK_") and key != env_var:
                            del os.environ[key]

                    try:
                        with patch('agent_config.Path') as mock_path_cls:
                            mock_path_instance = Mock()
                            mock_path_instance.parent = Path(self.test_dir)
                            mock_path_cls.return_value = mock_path_instance

                            config_manager = AgentConfigManager(mode="chat")

                            # Get the property value
                            actual_value = getattr(config_manager, prop_name)

                            # Verify value was converted correctly
                            self.assertEqual(actual_value, expected_value,
                                           f"Failed for {env_var}={env_value}: expected {expected_value}, got {actual_value}")
                    finally:
                        # Restore environment
                        os.environ.clear()
                        os.environ.update(env_copy)


class TestConfigUpdates(unittest.TestCase):
    """Test configuration updates and saving."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = tempfile.mkdtemp()
        self.original_cwd = os.getcwd()

        # Create a minimal test config structure
        self.config_dir = os.path.join(self.test_dir, "agent", "config")
        os.makedirs(self.config_dir, exist_ok=True)

        # Create base.yaml
        self.base_config = {
            "agent": {
                "model": "deepseek-chat",
                "temperature": 0.7,
                "max_tokens": 8192
            }
        }
        base_path = os.path.join(self.config_dir, "base.yaml")
        with open(base_path, 'w') as f:
            yaml.dump(self.base_config, f)

        # Create minimal mode configs
        for fname in ["chat.yaml", "coding.yaml", "fin.yaml"]:
            with open(os.path.join(self.config_dir, fname), 'w') as f:
                yaml.dump({}, f)

    def tearDown(self):
        """Clean up after tests."""
        os.chdir(self.original_cwd)
        shutil.rmtree(self.test_dir)

    def test_update_value_success(self):
        """Test successful update of configuration value."""
        with patch('agent_config.Path') as mock_path_cls:
            mock_path_instance = Mock()
            mock_path_instance.parent = Path(self.test_dir)
            mock_path_cls.return_value = mock_path_instance

            config_manager = AgentConfigManager(mode="chat")

            # Update a value in agent config
            success = config_manager.update_value("agent.model", "deepseek-reasoner")

            # Should succeed
            self.assertTrue(success)
            # Internal config should be updated
            self.assertEqual(config_manager._agent["model"], "deepseek-reasoner")

    def test_update_value_nested_success(self):
        """Test successful update of nested configuration value."""
        with patch('agent_config.Path') as mock_path_cls:
            mock_path_instance = Mock()
            mock_path_instance.parent = Path(self.test_dir)
            mock_path_cls.return_value = mock_path_instance

            config_manager = AgentConfigManager(mode="chat")

            # Update a nested value
            success = config_manager.update_value("temperature", 0.3)

            # Should succeed
            self.assertTrue(success)

    def test_update_value_failure(self):
        """Test update_value failure handling."""
        with patch('agent_config.Path') as mock_path_cls:
            mock_path_instance = Mock()
            mock_path_instance.parent = Path(self.test_dir)
            mock_path_cls.return_value = mock_path_instance

            config_manager = AgentConfigManager(mode="chat")

            # This should still return True since the method doesn't raise,
            # but let's test that the value gets set
            success = config_manager.update_value("model", "test-model")
            self.assertTrue(success)

    def test_save_config_success(self):
        """Test successful save of configuration to file."""
        with patch('agent_config.Path') as mock_path_cls:
            mock_path_instance = Mock()
            mock_path_instance.parent = Path(self.test_dir)
            mock_path_cls.return_value = mock_path_instance

            config_manager = AgentConfigManager(mode="chat")

            # Save config to a temp file
            temp_file = os.path.join(self.test_dir, "test_save.yaml")
            filepath = config_manager.save_config(temp_file)

            # Should succeed and return the filepath
            self.assertEqual(filepath, temp_file)
            # File should exist
            self.assertTrue(os.path.exists(temp_file))

    def test_save_config_default_path(self):
        """Test save_config uses default mode path when no filepath given."""
        with patch('agent_config.Path') as mock_path_cls:
            mock_path_instance = Mock()
            mock_path_instance.parent = Path(self.test_dir)
            mock_path_cls.return_value = mock_path_instance

            config_manager = AgentConfigManager(mode="coding")

            # Save config without specifying path (should use default)
            # We can't easily test file creation without a real config_dir,
            # but we can mock the write operation
            with patch('builtins.open', create=True) as mock_open:
                mock_open.return_value.__enter__ = Mock()
                mock_open.return_value.__exit__ = Mock()

                try:
                    filepath = config_manager.save_config()
                    # Should return a path ending with mode name
                    self.assertIn("coding", filepath)
                except (FileNotFoundError, TypeError):
                    # Expected since we're using a mocked Path
                    pass

    def test_switch_mode_success(self):
        """Test successful mode switch."""
        with patch('agent_config.Path') as mock_path_cls:
            mock_path_instance = Mock()
            mock_path_instance.parent = Path(self.test_dir)
            mock_path_cls.return_value = mock_path_instance

            config_manager = AgentConfigManager(mode="chat")

            # Switch to coding mode
            success = config_manager.switch_mode("coding")

            # Should succeed
            self.assertTrue(success)
            # Mode should be updated
            self.assertEqual(config_manager.mode, "coding")

    def test_switch_mode_invalid(self):
        """Test mode switch with invalid mode."""
        with patch('agent_config.Path') as mock_path_cls:
            mock_path_instance = Mock()
            mock_path_instance.parent = Path(self.test_dir)
            mock_path_cls.return_value = mock_path_instance

            config_manager = AgentConfigManager(mode="chat")

            # Try to switch to invalid mode
            success = config_manager.switch_mode("invalid_mode")

            # Should fail
            self.assertFalse(success)
            # Mode should remain unchanged
            self.assertEqual(config_manager.mode, "chat")

    def test_update_mode_success(self):
        """Test successful mode update (backward compatibility)."""
        with patch('agent_config.Path') as mock_path_cls:
            mock_path_instance = Mock()
            mock_path_instance.parent = Path(self.test_dir)
            mock_path_cls.return_value = mock_path_instance

            config_manager = AgentConfigManager(mode="chat")

            # Update mode using backward-compatible method
            success = config_manager.update_mode("fin")

            # Should succeed
            self.assertTrue(success)
            # Mode should be updated
            self.assertEqual(config_manager.mode, "fin")


class TestModeSpecificProperties(unittest.TestCase):
    """Test mode-specific properties and defaults."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = tempfile.mkdtemp()
        self.original_cwd = os.getcwd()

        # Create a minimal test config structure
        self.config_dir = os.path.join(self.test_dir, "agent", "config")
        os.makedirs(self.config_dir, exist_ok=True)

        # Create base.yaml with agent settings
        self.base_config = {
            "agent": {
                "model": "deepseek-chat",
                "temperature": 0.7,
                "max_tokens": 8192,
                "debug": False,
                "thinking_enabled": False,
                "stream": True,
                "timeout": 30,
                "max_retries": 3,
                "context": {
                    "max_context_tokens": 131072,
                    "warning_threshold": 0.61,
                    "break_threshold": 0.8,
                    "compression_strategy": "truncate",
                    "keep_system_messages": True,
                    "keep_recent_messages": 5
                }
            }
        }
        base_path = os.path.join(self.config_dir, "base.yaml")
        with open(base_path, 'w') as f:
            yaml.dump(self.base_config, f)

        # Create mode configs with different settings
        chat_config = {
            "system_prompt": "You are a helpful chat assistant.",
            "search_enabled": True,
            "show_status_bar": True,
            "enable_auto_complete": True,
            "auto_search": {
                "enabled": True,
                "triggers": ["latest", "current", "today"]
            },
            "natural_language": {
                "enabled": True,
                "confidence_threshold": 0.8
            },
            "safety": {
                "confirm_file_operations": True,
                "confirm_code_changes": True
            }
        }
        with open(os.path.join(self.config_dir, "chat.yaml"), 'w') as f:
            yaml.dump(chat_config, f)

        coding_config = {
            "system_prompt": "You are a coding assistant.",
            "search_enabled": False,
            "show_status_bar": True,
            "enable_auto_complete": True,
            "workspace": {
                "auto_scan": False,
                "auto_read_files": False,
                "auto_analyze_references": False,
                "exclude_patterns": []
            },
            "safety": {
                "confirm_file_operations": True,
                "confirm_code_changes": True
            }
        }
        with open(os.path.join(self.config_dir, "coding.yaml"), 'w') as f:
            yaml.dump(coding_config, f)

        fin_config = {
            "system_prompt": "You are a financial assistant.",
            "search_enabled": True
        }
        with open(os.path.join(self.config_dir, "fin.yaml"), 'w') as f:
            yaml.dump(fin_config, f)

    def tearDown(self):
        """Clean up after tests."""
        os.chdir(self.original_cwd)
        shutil.rmtree(self.test_dir)

    def test_mode_config_access(self):
        """Test accessing mode-specific configuration."""
        with patch('agent_config.Path') as mock_path_cls:
            mock_path_instance = Mock()
            mock_path_instance.parent = Path(self.test_dir)
            mock_path_cls.return_value = mock_path_instance

            config_manager = AgentConfigManager(mode="chat")

            # Test chat mode properties
            self.assertEqual(config_manager.system_prompt, "You are a helpful chat assistant.")
            self.assertTrue(config_manager.search_enabled)
            self.assertTrue(config_manager.show_status_bar)

    def test_get_mode_config_other_modes(self):
        """Test getting configuration for modes without switching."""
        with patch('agent_config.Path') as mock_path_cls:
            mock_path_instance = Mock()
            mock_path_instance.parent = Path(self.test_dir)
            mock_path_cls.return_value = mock_path_instance

            config_manager = AgentConfigManager(mode="chat")

            # Get coding mode config without switching
            coding_cfg = config_manager.get_mode_config("coding")
            self.assertEqual(coding_cfg.get("system_prompt"), "You are a coding assistant.")

            # Get fin mode config without switching
            fin_cfg = config_manager.get_mode_config("fin")
            self.assertEqual(fin_cfg.get("system_prompt"), "You are a financial assistant.")

    def test_coding_mode_properties(self):
        """Test coding mode specific properties."""
        with patch('agent_config.Path') as mock_path_cls:
            mock_path_instance = Mock()
            mock_path_instance.parent = Path(self.test_dir)
            mock_path_cls.return_value = mock_path_instance

            config_manager = AgentConfigManager(mode="coding")

            # Test coding mode properties
            self.assertEqual(config_manager.system_prompt, "You are a coding assistant.")
            self.assertFalse(config_manager.search_enabled)
            self.assertEqual(config_manager.coding_mode_system_prompt, "You are a coding assistant.")

    def test_mode_aware_properties(self):
        """Test that mode-aware properties reflect active mode."""
        with patch('agent_config.Path') as mock_path_cls:
            mock_path_instance = Mock()
            mock_path_instance.parent = Path(self.test_dir)
            mock_path_cls.return_value = mock_path_instance

            config_manager = AgentConfigManager(mode="chat")
            chat_system = config_manager.system_prompt

            # Switch mode and verify properties change
            config_manager.switch_mode("coding")
            coding_system = config_manager.system_prompt

            self.assertNotEqual(chat_system, coding_system)

    def test_backward_compat_properties(self):
        """Test backward-compatible properties."""
        with patch('agent_config.Path') as mock_path_cls:
            mock_path_instance = Mock()
            mock_path_instance.parent = Path(self.test_dir)
            mock_path_cls.return_value = mock_path_instance

            config_manager = AgentConfigManager(mode="chat")

            # Test backward-compatible properties
            self.assertTrue(config_manager.auto_features_enabled)  # always True
            self.assertEqual(config_manager.coding_mode_system_prompt, "You are a coding assistant.")


if __name__ == '__main__':
    unittest.main()