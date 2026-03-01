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
import hydra
from omegaconf import OmegaConf


class TestAgentConfigManagerBasics(unittest.TestCase):
    """Test basic AgentConfigManager functionality."""

    def setUp(self):
        """Set up test environment."""
        # Create a temporary directory for test config files
        self.test_dir = tempfile.mkdtemp()
        self.original_cwd = os.getcwd()
        os.chdir(self.test_dir)

        # Create a minimal test config structure
        self.config_dir = os.path.join(self.test_dir, "agent")
        os.makedirs(self.config_dir, exist_ok=True)

        # Create a test config.yaml
        self.test_config = {
            "agent": {
                "model": "deepseek-chat",
                "temperature": 0.7,
                "max_tokens": 8192,
                "debug": False,
                "thinking_enabled": False,
                "system_prompt": "",
                "mode": "chat",
                "context": {
                    "max_context_tokens": 131072,
                    "warning_threshold": 0.8,
                    "break_threshold": 0.6,
                    "compression_strategy": "truncate",
                    "keep_system_messages": True,
                    "keep_recent_messages": 5
                },
                "auto_features": {
                    "enabled": True,
                    "auto_search": {
                        "enabled": True,
                        "triggers": ["today", "news", "weather", "latest", "current"]
                    },
                    "natural_language": {
                        "enabled": True,
                        "confidence_threshold": 0.8
                    },
                    "safety": {
                        "confirm_file_operations": True,
                        "confirm_code_changes": True
                    }
                },
                "coding_mode": {
                    "auto_file_operations": True,
                    "workspace_scan": True,
                    "system_prompt": "",
                    "natural_language_confidence_threshold": 0.7,
                    "safety_confirm_file_operations": False,
                    "auto_read_files": True,
                    "auto_analyze_references": True,
                    "show_status_bar": True,
                    "enable_auto_complete": True,
                    "enable_mcp_support": True
                }
            }
        }

        self.config_path = os.path.join(self.config_dir, "config.yaml")
        with open(self.config_path, 'w') as f:
            yaml.dump(self.test_config, f)

    def tearDown(self):
        """Clean up after tests."""
        os.chdir(self.original_cwd)
        shutil.rmtree(self.test_dir)

    def test_initialization_with_default_config(self):
        """Test AgentConfigManager initialization with default config."""
        # Mock hydra to use our test config directory
        with patch('agent_config.hydra') as mock_hydra:
            with patch('agent_config.GlobalHydra') as mock_global_hydra:
                with patch('agent_config.Path') as mock_path:
                    with patch('agent_config.OmegaConf') as mock_omegaconf:
                        # Set up mocks
                        mock_instance = Mock()
                        mock_instance.is_initialized.return_value = False
                        mock_global_hydra.instance.return_value = mock_instance

                        mock_path_instance = Mock()
                        mock_path.return_value.parent = Mock(return_value=Mock())
                        mock_path.return_value.parent.return_value = Mock()
                        mock_path.return_value.parent.return_value.__truediv__ = Mock(return_value=self.config_dir)

                        # Mock OmegaConf.to_container to avoid real call
                        mock_cfg = Mock()
                        mock_cfg.get.return_value = {}
                        mock_hydra.compose.return_value = mock_cfg
                        mock_omegaconf.to_container.return_value = {}

                        # Create config manager
                        config_manager = AgentConfigManager(config_name="config")

                        # Verify hydra was initialized with correct path
                        mock_hydra.initialize.assert_called_once_with(
                            config_path="agent", version_base="1.3"
                        )

    def test_config_path_property(self):
        """Test config_path property returns correct path."""
        with patch('agent_config.hydra') as mock_hydra:
            with patch('agent_config.GlobalHydra') as mock_global_hydra:
                with patch('agent_config.OmegaConf') as mock_omegaconf:
                    # Set up mocks
                    mock_instance = Mock()
                    mock_instance.is_initialized.return_value = False
                    mock_global_hydra.instance.return_value = mock_instance

                    mock_cfg = Mock()
                    mock_cfg.get.return_value = {}
                    mock_omegaconf.to_container.return_value = {}
                    mock_hydra.compose.return_value = mock_cfg

                    # Create config manager
                    config_manager = AgentConfigManager(config_name="config")
                    # Override base_dir to point to test directory
                    config_manager.base_dir = Path(self.test_dir)

                    path = config_manager.config_path

                    # Should return path to config.yaml in agent directory relative to test dir
                    expected = Path(self.test_dir) / "agent" / "config.yaml"
                    self.assertEqual(path, expected)

    def test_get_method_with_dot_notation(self):
        """Test get method with dot notation for nested keys."""
        # Create a simple config manager with mocked config
        config_manager = AgentConfigManager(config_name="config")

        # Mock the internal config
        config_manager._agent_config = {
            "model": "deepseek-chat",
            "temperature": 0.7,
            "context": {
                "max_context_tokens": 131072,
                "warning_threshold": 0.8
            }
        }

        # Test top-level key
        model = config_manager.get("model")
        self.assertEqual(model, "deepseek-chat")

        # Test nested key with dot notation
        max_tokens = config_manager.get("context.max_context_tokens")
        self.assertEqual(max_tokens, 131072)

        # Test with default value for missing key
        missing = config_manager.get("missing.key", "default_value")
        self.assertEqual(missing, "default_value")

        # Test with "agent." prefix (should be stripped)
        model_with_prefix = config_manager.get("agent.model")
        self.assertEqual(model_with_prefix, "deepseek-chat")

    def test_property_accessors(self):
        """Test property accessors return correct values."""
        # Create config manager with mocked config
        config_manager = AgentConfigManager(config_name="config")

        # Mock the internal config
        config_manager._agent_config = {
            "model": "deepseek-reasoner",
            "temperature": 0.5,
            "max_tokens": 4096,
            "debug": True,
            "thinking_enabled": True,
            "mode": "coding",
            "context": {
                "max_context_tokens": 65536,
                "warning_threshold": 0.7,
                "break_threshold": 0.5,
                "compression_strategy": "summarize",
                "keep_system_messages": False,
                "keep_recent_messages": 3
            }
        }

        # Test properties
        self.assertEqual(config_manager.model, "deepseek-reasoner")
        self.assertEqual(config_manager.temperature, 0.5)
        self.assertEqual(config_manager.max_tokens, 4096)
        self.assertTrue(config_manager.debug)
        self.assertTrue(config_manager.thinking_enabled)
        self.assertEqual(config_manager.mode, "coding")
        self.assertEqual(config_manager.max_context_tokens, 65536)
        self.assertEqual(config_manager.context_warning_threshold, 0.7)
        self.assertEqual(config_manager.context_break_threshold, 0.5)
        self.assertEqual(config_manager.compression_strategy, "summarize")
        self.assertFalse(config_manager.keep_system_messages)
        self.assertEqual(config_manager.keep_recent_messages, 3)

    def test_property_default_values(self):
        """Test properties return default values when keys are missing."""
        # Create config manager with empty config
        config_manager = AgentConfigManager(config_name="config")
        config_manager._agent_config = {}

        # Test default values
        self.assertEqual(config_manager.model, "deepseek-chat")
        self.assertEqual(config_manager.temperature, 0.7)
        self.assertEqual(config_manager.max_tokens, 8192)
        self.assertFalse(config_manager.debug)
        self.assertFalse(config_manager.thinking_enabled)
        self.assertEqual(config_manager.mode, "chat")
        self.assertEqual(config_manager.max_context_tokens, 131072)
        self.assertEqual(config_manager.context_warning_threshold, 0.8)
        self.assertEqual(config_manager.context_break_threshold, 0.6)
        self.assertEqual(config_manager.compression_strategy, "truncate")
        self.assertTrue(config_manager.keep_system_messages)
        self.assertEqual(config_manager.keep_recent_messages, 5)


class TestEnvironmentOverrides(unittest.TestCase):
    """Test environment variable overrides."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = tempfile.mkdtemp()
        self.original_cwd = os.getcwd()
        os.chdir(self.test_dir)

        # Create a minimal test config structure
        self.config_dir = os.path.join(self.test_dir, "agent")
        os.makedirs(self.config_dir, exist_ok=True)

        # Create a test config.yaml
        self.test_config = {
            "agent": {
                "model": "deepseek-chat",
                "temperature": 0.7,
                "debug": False
            }
        }

        self.config_path = os.path.join(self.config_dir, "config.yaml")
        with open(self.config_path, 'w') as f:
            yaml.dump(self.test_config, f)

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
            # Mock hydra and OmegaConf to track updates
            with patch('agent_config.hydra') as mock_hydra:
                with patch('agent_config.GlobalHydra') as mock_global_hydra:
                    with patch('agent_config.Path') as mock_path:
                        with patch('agent_config.OmegaConf') as mock_omegaconf:
                            # Set up mocks
                            mock_instance = Mock()
                            mock_instance.is_initialized.return_value = False
                            mock_global_hydra.instance.return_value = mock_instance

                            # Mock OmegaConf.update to track calls
                            update_calls = []
                            def mock_update(cfg, key, value):
                                update_calls.append((key, value))
                            mock_omegaconf.update.side_effect = mock_update

                            # Mock the config object
                            mock_cfg = Mock()
                            mock_cfg.get.return_value = {}
                            mock_omegaconf.to_container.return_value = {}
                            mock_hydra.compose.return_value = mock_cfg

                            # Create config manager
                            config_manager = AgentConfigManager(config_name="config")

                            # Verify OmegaConf.update was called for each env var
                            self.assertGreater(len(update_calls), 0)

                            # Check specific updates (order may vary)
                            updates_dict = dict(update_calls)
                            self.assertEqual(updates_dict.get("agent.model"), "deepseek-reasoner")
                            self.assertEqual(updates_dict.get("agent.temperature"), 0.5)
                            self.assertEqual(updates_dict.get("agent.max_tokens"), 4096)
                            self.assertEqual(updates_dict.get("agent.debug"), True)

    def test_environment_variable_type_conversions(self):
        """Test environment variable value type conversions."""
        # Test cases: (env_var, env_value, expected_converted_value)
        test_cases = [
            ("DEEPSEEK_TEMPERATURE", "0.3", 0.3),  # float
            ("DEEPSEEK_MAX_TOKENS", "2048", 2048),  # int
            ("DEEPSEEK_MAX_CONTEXT_TOKENS", "65536", 65536),  # int
            ("DEEPSEEK_KEEP_RECENT_MESSAGES", "10", 10),  # int
            ("DEEPSEEK_CONTEXT_WARNING_THRESHOLD", "0.75", 0.75),  # float
            ("DEEPSEEK_CONTEXT_BREAK_THRESHOLD", "0.55", 0.55),  # float
            ("DEEPSEEK_KEEP_SYSTEM_MESSAGES", "true", True),  # bool true
            ("DEEPSEEK_KEEP_SYSTEM_MESSAGES", "1", True),  # bool true
            ("DEEPSEEK_KEEP_SYSTEM_MESSAGES", "false", False),  # bool false
            ("DEEPSEEK_KEEP_SYSTEM_MESSAGES", "0", False),  # bool false
            ("DEEPSEEK_DEBUG", "true", True),  # bool true
            ("DEEPSEEK_DEBUG", "1", True),  # bool true
            ("DEEPSEEK_DEBUG", "false", False),  # bool false
            ("DEEPSEEK_DEBUG", "0", False),  # bool false
            ("DEEPSEEK_COMPRESSION_STRATEGY", "summarize", "summarize"),  # string
        ]

        for env_var, env_value, expected_value in test_cases:
            with self.subTest(env_var=env_var, env_value=env_value):
                with patch.dict(os.environ, {env_var: env_value}):
                    # Mock hydra and OmegaConf
                    with patch('agent_config.hydra'):
                        with patch('agent_config.GlobalHydra'):
                            with patch('agent_config.Path'):
                                with patch('agent_config.OmegaConf') as mock_omegaconf:
                                    # Track OmegaConf.update calls
                                    update_calls = []
                                    def mock_update(cfg, key, value):
                                        update_calls.append((key, value))
                                    mock_omegaconf.update.side_effect = mock_update

                                    # Mock config
                                    mock_cfg = Mock()
                                    mock_cfg.get.return_value = {}
                                    mock_omegaconf.to_container.return_value = {}
                                    mock_hydra = Mock()
                                    mock_hydra.compose.return_value = mock_cfg

                                    with patch('agent_config.hydra', mock_hydra):
                                        config_manager = AgentConfigManager(config_name="config")

                                    # Find the update for this env var
                                    config_path = None
                                    for key, value in update_calls:
                                        if "agent." in key:
                                            config_path = key
                                            actual_value = value
                                            break

                                    if config_path:
                                        # Verify value was converted correctly
                                        self.assertEqual(actual_value, expected_value)


class TestConfigUpdates(unittest.TestCase):
    """Test configuration updates and saving."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = tempfile.mkdtemp()
        self.original_cwd = os.getcwd()
        os.chdir(self.test_dir)

        # Create a minimal test config structure
        self.config_dir = os.path.join(self.test_dir, "agent")
        os.makedirs(self.config_dir, exist_ok=True)

        # Create a test config.yaml
        self.test_config = {
            "agent": {
                "model": "deepseek-chat",
                "temperature": 0.7
            }
        }

        self.config_path = os.path.join(self.config_dir, "config.yaml")
        with open(self.config_path, 'w') as f:
            yaml.dump(self.test_config, f)

    def tearDown(self):
        """Clean up after tests."""
        os.chdir(self.original_cwd)
        shutil.rmtree(self.test_dir)

    def test_update_value_success(self):
        """Test successful update of configuration value."""
        # Create config manager
        with patch('agent_config.hydra'):
            with patch('agent_config.GlobalHydra'):
                with patch('agent_config.Path'):
                    with patch('agent_config.OmegaConf') as mock_omegaconf:
                        # Mock OmegaConf methods
                        mock_cfg = Mock()
                        mock_omegaconf.to_container.return_value = {"model": "deepseek-chat", "temperature": 0.7}

                        # Mock save_config to track calls
                        config_manager = AgentConfigManager(config_name="config")
                        config_manager._cfg = mock_cfg
                        config_manager._agent_config = {"model": "deepseek-chat", "temperature": 0.7}
                        config_manager.save_config = Mock(return_value=True)

                        # Update a value
                        success = config_manager.update_value("agent.model", "deepseek-reasoner")

                        # Should succeed
                        self.assertTrue(success)
                        # OmegaConf.update should have been called
                        mock_omegaconf.update.assert_called_once_with(mock_cfg, "agent.model", "deepseek-reasoner")
                        # Internal config should be updated
                        self.assertEqual(config_manager._agent_config["model"], "deepseek-reasoner")
                        # save_config should have been called
                        config_manager.save_config.assert_called_once()

    def test_update_value_failure(self):
        """Test update_value failure handling."""
        # Create config manager
        with patch('agent_config.hydra'):
            with patch('agent_config.GlobalHydra'):
                with patch('agent_config.Path'):
                    with patch('agent_config.OmegaConf') as mock_omegaconf:
                        # Mock OmegaConf.update to raise exception
                        mock_omegaconf.update.side_effect = Exception("Update failed")

                        # Mock config
                        mock_cfg = Mock()
                        mock_omegaconf.to_container.return_value = {"model": "deepseek-chat"}

                        config_manager = AgentConfigManager(config_name="config")
                        config_manager._cfg = mock_cfg
                        config_manager._agent_config = {"model": "deepseek-chat"}

                        # Update should fail
                        success = config_manager.update_value("agent.model", "deepseek-reasoner")

                        # Should return False
                        self.assertFalse(success)

    def test_save_config_success(self):
        """Test successful save of configuration."""
        # Create config manager
        with patch('agent_config.hydra'):
            with patch('agent_config.GlobalHydra'):
                with patch('agent_config.Path'):
                    with patch('agent_config.OmegaConf') as mock_omegaconf:
                        # Mock OmegaConf.save
                        mock_omegaconf.save = Mock()

                        # Mock config
                        mock_cfg = Mock()
                        mock_omegaconf.to_container.return_value = {}

                        config_manager = AgentConfigManager(config_name="config")
                        config_manager._cfg = mock_cfg
                        config_manager.base_dir = Path(self.test_dir)

                        # Save config
                        success = config_manager.save_config()

                        # Should succeed
                        self.assertTrue(success)
                        # OmegaConf.save should have been called
                        mock_omegaconf.save.assert_called_once_with(mock_cfg, Path(self.config_path))

    def test_save_config_failure(self):
        """Test save_config failure handling."""
        # Create config manager
        with patch('agent_config.hydra'):
            with patch('agent_config.GlobalHydra'):
                with patch('agent_config.Path'):
                    with patch('agent_config.OmegaConf') as mock_omegaconf:
                        # Mock OmegaConf.save to raise exception
                        mock_omegaconf.save.side_effect = Exception("Save failed")

                        # Mock config
                        mock_cfg = Mock()
                        mock_omegaconf.to_container.return_value = {}

                        config_manager = AgentConfigManager(config_name="config")
                        config_manager._cfg = mock_cfg
                        config_manager.base_dir = Path(self.test_dir)

                        # Save should fail
                        success = config_manager.save_config()

                        # Should return False
                        self.assertFalse(success)

    def test_update_mode_success(self):
        """Test successful mode update."""
        # Create config manager
        with patch('agent_config.hydra'):
            with patch('agent_config.GlobalHydra'):
                with patch('agent_config.Path'):
                    with patch('agent_config.OmegaConf') as mock_omegaconf:
                        # Mock update_value to succeed
                        config_manager = AgentConfigManager(config_name="config")
                        config_manager.update_value = Mock(return_value=True)

                        # Update mode to coding
                        success = config_manager.update_mode("coding")

                        # Should succeed
                        self.assertTrue(success)
                        # update_value should have been called with correct key
                        config_manager.update_value.assert_called_once_with("agent.mode", "coding")

    def test_update_mode_invalid(self):
        """Test mode update with invalid mode."""
        # Create config manager
        with patch('agent_config.hydra'):
            with patch('agent_config.GlobalHydra'):
                with patch('agent_config.Path'):
                    with patch('agent_config.OmegaConf'):
                        config_manager = AgentConfigManager(config_name="config")

                        # Try to update to invalid mode
                        success = config_manager.update_mode("invalid_mode")

                        # Should fail
                        self.assertFalse(success)

    def test_update_mode_failure(self):
        """Test mode update when update_value fails."""
        # Create config manager
        with patch('agent_config.hydra'):
            with patch('agent_config.GlobalHydra'):
                with patch('agent_config.Path'):
                    with patch('agent_config.OmegaConf'):
                        # Mock update_value to fail
                        config_manager = AgentConfigManager(config_name="config")
                        config_manager.update_value = Mock(return_value=False)

                        # Update mode
                        success = config_manager.update_mode("coding")

                        # Should fail
                        self.assertFalse(success)


class TestAutoFeaturesProperties(unittest.TestCase):
    """Test auto-features related properties."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = tempfile.mkdtemp()
        self.original_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        """Clean up after tests."""
        os.chdir(self.original_cwd)
        shutil.rmtree(self.test_dir)

    def test_auto_features_properties(self):
        """Test auto-features properties."""
        # Create config manager with mocked config
        with patch('agent_config.hydra') as mock_hydra:
            with patch('agent_config.GlobalHydra') as mock_global_hydra:
                with patch('agent_config.Path'):
                    with patch('agent_config.OmegaConf') as mock_omegaconf:
                        # Set up mocks
                        mock_instance = Mock()
                        mock_instance.is_initialized.return_value = False
                        mock_global_hydra.instance.return_value = mock_instance

                        mock_cfg = Mock()
                        mock_cfg.get.return_value = {}
                        mock_omegaconf.to_container.return_value = {}
                        mock_hydra.compose.return_value = mock_cfg

                        config_manager = AgentConfigManager(config_name="config")

                        # Mock config with auto-features
                        config_manager._agent_config = {
                            "auto_features": {
                                "enabled": True,
                                "auto_search": {
                                    "enabled": True,
                                    "triggers": ["news", "weather"]
                                },
                                "natural_language": {
                                    "enabled": True,
                                    "confidence_threshold": 0.9
                                },
                                "safety": {
                                    "confirm_file_operations": False,
                                    "confirm_code_changes": False
                                }
                            },
                            "coding_mode": {
                                "auto_file_operations": False,
                                "workspace_scan": False,
                                "system_prompt": "Code assistant",
                                "natural_language_confidence_threshold": 0.8,
                                "safety_confirm_file_operations": True,
                                "auto_read_files": False,
                                "auto_analyze_references": False,
                                "show_status_bar": False,
                                "enable_auto_complete": False,
                                "enable_mcp_support": False
                            }
                        }

                        # Test auto-features properties
                        self.assertTrue(config_manager.auto_features_enabled)
                        self.assertTrue(config_manager.auto_search_enabled)
                        self.assertEqual(config_manager.auto_search_triggers, ["news", "weather"])
                        self.assertTrue(config_manager.natural_language_enabled)
                        self.assertEqual(config_manager.natural_language_confidence_threshold, 0.9)
                        self.assertFalse(config_manager.safety_confirm_file_operations)
                        self.assertFalse(config_manager.safety_confirm_code_changes)

                        # Test coding mode properties
                        self.assertFalse(config_manager.coding_mode_auto_file_operations)
                        self.assertFalse(config_manager.coding_mode_workspace_scan)
                        self.assertEqual(config_manager.coding_mode_system_prompt, "Code assistant")
                        self.assertEqual(config_manager.coding_mode_natural_language_confidence_threshold, 0.8)
                        self.assertTrue(config_manager.coding_mode_safety_confirm_file_operations)
                        self.assertFalse(config_manager.coding_mode_auto_read_files)
                        self.assertFalse(config_manager.coding_mode_auto_analyze_references)
                        self.assertFalse(config_manager.coding_mode_show_status_bar)
                        self.assertFalse(config_manager.coding_mode_enable_auto_complete)
                        self.assertFalse(config_manager.coding_mode_enable_mcp_support)

    def test_auto_features_defaults(self):
        """Test auto-features default values."""
        # Create config manager with empty config
        with patch('agent_config.hydra') as mock_hydra:
            with patch('agent_config.GlobalHydra') as mock_global_hydra:
                with patch('agent_config.Path'):
                    with patch('agent_config.OmegaConf') as mock_omegaconf:
                        # Set up mocks
                        mock_instance = Mock()
                        mock_instance.is_initialized.return_value = False
                        mock_global_hydra.instance.return_value = mock_instance

                        mock_cfg = Mock()
                        mock_cfg.get.return_value = {}
                        mock_omegaconf.to_container.return_value = {}
                        mock_hydra.compose.return_value = mock_cfg

                        config_manager = AgentConfigManager(config_name="config")
                        config_manager._agent_config = {}

                        # Test default values
                        self.assertTrue(config_manager.auto_features_enabled)
                        self.assertTrue(config_manager.auto_search_enabled)
                        self.assertEqual(config_manager.auto_search_triggers, ["today", "news", "weather", "latest", "current"])
                        self.assertTrue(config_manager.natural_language_enabled)
                        self.assertEqual(config_manager.natural_language_confidence_threshold, 0.8)
                        self.assertTrue(config_manager.safety_confirm_file_operations)
                        self.assertTrue(config_manager.safety_confirm_code_changes)

                        # Test coding mode defaults
                        self.assertTrue(config_manager.coding_mode_auto_file_operations)
                        self.assertTrue(config_manager.coding_mode_workspace_scan)
                        self.assertEqual(config_manager.coding_mode_system_prompt, "")
                        self.assertEqual(config_manager.coding_mode_natural_language_confidence_threshold, 0.7)
                        self.assertFalse(config_manager.coding_mode_safety_confirm_file_operations)
                        self.assertTrue(config_manager.coding_mode_auto_read_files)
                        self.assertTrue(config_manager.coding_mode_auto_analyze_references)
                        self.assertTrue(config_manager.coding_mode_show_status_bar)
                        self.assertTrue(config_manager.coding_mode_enable_auto_complete)
                        self.assertTrue(config_manager.coding_mode_enable_mcp_support)


if __name__ == '__main__':
    unittest.main()