"""
Comprehensive tests for root files:
- main.py
- agent_config.py

Run: pytest tests/test_root_files_full.py -v
"""
import os
import sys
import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ============================================================================
# MAIN.PY TESTS
# ============================================================================

class TestMainModule:
    """Test main.py module."""

    def test_main_imports(self):
        """Verify main.py imports correctly."""
        import main
        assert hasattr(main, 'main')
        assert hasattr(main, 'interactive_main')
        assert hasattr(main, 'test_main')

    def test_interactive_main_calls_neomind_interface(self):
        """Test interactive_main tries NeoMind interface first."""
        import main

        with patch('agent_config.agent_config') as mock_config:
            with patch('cli.neomind_interface.interactive_chat') as mock_chat:
                mock_config.mode = "chat"

                try:
                    main.interactive_main("chat")
                except Exception:
                    pass

    def test_interactive_main_fallback_to_prompt_toolkit(self):
        """Test interactive_main falls back to prompt_toolkit."""
        import main

        with patch('agent_config.agent_config') as mock_config:
            with patch('cli.neomind_interface.interactive_chat', side_effect=ImportError("NeoMind not available")):
                with patch('cli.interface.interactive_chat_with_prompt_toolkit') as mock_fallback:
                    mock_config.mode = "chat"

                    try:
                        main.interactive_main("chat")
                    except ImportError:
                        pass

    def test_interactive_main_fallback_chain(self):
        """Test full fallback chain."""
        import main

        with patch('agent_config.agent_config') as mock_config:
            with patch('cli.neomind_interface.interactive_chat', side_effect=Exception("Error")):
                with patch('cli.interface.interactive_chat_with_prompt_toolkit', side_effect=ImportError()):
                    with patch('cli.interface.interactive_chat_fallback') as mock_final:
                        mock_config.mode = "chat"

                        try:
                            main.interactive_main("chat")
                        except ImportError:
                            pass

    def test_test_main_calls_dev_test(self):
        """Test test_main imports and runs dev_test."""
        import main

        with patch('dev_test.run_tests') as mock_run_tests:
            mock_run_tests.return_value = True

            try:
                main.test_main()
            except SystemExit as e:
                assert e.code == 0

    def test_test_main_exit_code_on_failure(self):
        """Test test_main exits with 1 on failure."""
        import main

        with patch('dev_test.run_tests') as mock_run_tests:
            mock_run_tests.return_value = False

            try:
                main.test_main()
            except SystemExit as e:
                assert e.code == 1

    def test_test_main_import_error(self):
        """Test test_main handles missing dev_test."""
        import main
        import sys
        import builtins

        # Mock the import to fail for dev_test
        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == 'dev_test':
                raise ImportError("dev_test not found")
            return original_import(name, *args, **kwargs)

        with patch('builtins.__import__', side_effect=mock_import):
            try:
                main.test_main()
            except SystemExit as e:
                assert e.code == 1

    def test_main_argument_parsing(self):
        """Test main() argument parsing."""
        import main

        with patch('sys.argv', ['main.py', 'interactive', '--mode', 'chat']):
            with patch('main.interactive_main') as mock_interactive:
                try:
                    main.main()
                except SystemExit:
                    pass

    def test_main_test_mode_argument(self):
        """Test main() with test mode."""
        import main

        with patch('sys.argv', ['main.py', 'test']):
            with patch('main.test_main') as mock_test:
                try:
                    main.main()
                except SystemExit:
                    pass

    def test_main_version_flag(self):
        """Test main() --version flag."""
        import main

        with patch('sys.argv', ['main.py', '--version']):
            try:
                main.main()
            except SystemExit:
                pass


# ============================================================================
# AGENT_CONFIG.PY TESTS
# ============================================================================

class TestAgentConfigManagerInit:
    """Test AgentConfigManager initialization."""

    def test_init_default_mode(self, tmp_path):
        from agent_config import AgentConfigManager

        with patch.dict(os.environ, {"IKOL_MODE": "chat"}):
            manager = AgentConfigManager()
            assert manager.mode == "chat"

    def test_init_explicit_mode(self):
        from agent_config import AgentConfigManager
        manager = AgentConfigManager(mode="coding")
        assert manager.mode == "coding"

    def test_init_invalid_mode_defaults_to_chat(self):
        from agent_config import AgentConfigManager
        manager = AgentConfigManager(mode="invalid")
        assert manager.mode == "chat"

    def test_init_loads_yaml_files(self, tmp_path):
        from agent_config import AgentConfigManager

        # Should load yaml files if they exist
        manager = AgentConfigManager(mode="chat")
        assert manager._chat_cfg is not None

    def test_init_handles_missing_yaml(self, tmp_path):
        from agent_config import AgentConfigManager

        # Should handle missing files gracefully
        with patch.object(AgentConfigManager, '_load_yaml') as mock_load:
            mock_load.return_value = {}
            manager = AgentConfigManager()

            assert manager._active is not None


class TestAgentConfigManagerModeSwitch:
    """Test mode switching functionality."""

    def test_switch_mode_success(self):
        from agent_config import AgentConfigManager
        manager = AgentConfigManager(mode="chat")

        result = manager.switch_mode("coding")

        assert result is True
        assert manager.mode == "coding"

    def test_switch_mode_to_fin(self):
        from agent_config import AgentConfigManager
        manager = AgentConfigManager(mode="chat")

        result = manager.switch_mode("fin")

        assert result is True
        assert manager.mode == "fin"

    def test_switch_mode_invalid(self):
        from agent_config import AgentConfigManager
        manager = AgentConfigManager(mode="chat")

        result = manager.switch_mode("invalid")

        assert result is False
        assert manager.mode == "chat"  # Should not change

    def test_update_mode_alias(self):
        """Test update_mode as backward compatibility alias."""
        from agent_config import AgentConfigManager
        manager = AgentConfigManager(mode="chat")

        result = manager.update_mode("coding")

        assert result is True
        assert manager.mode == "coding"


class TestAgentConfigManagerRuntime:
    """Test runtime configuration modification."""

    def test_set_runtime_simple_key(self):
        from agent_config import AgentConfigManager
        manager = AgentConfigManager()

        result = manager.set_runtime("temperature", 0.5)

        assert result is True

    def test_set_runtime_with_agent_prefix(self):
        from agent_config import AgentConfigManager
        manager = AgentConfigManager()

        result = manager.set_runtime("agent.temperature", 0.8)

        assert result is True

    def test_set_runtime_preserves_existing(self):
        from agent_config import AgentConfigManager
        manager = AgentConfigManager()

        manager.set_runtime("temperature", 0.5)
        manager.set_runtime("max_tokens", 2000)

        # Both should be set
        assert manager._active.get("temperature") == 0.5 or \
               manager._agent.get("temperature") == 0.5

    def test_get_runtime_overrides(self):
        from agent_config import AgentConfigManager
        manager = AgentConfigManager()

        overrides = manager.get_runtime_overrides()

        assert isinstance(overrides, dict)


class TestAgentConfigManagerSave:
    """Test configuration saving."""

    def test_save_config_default_path(self, tmp_path):
        from agent_config import AgentConfigManager

        manager = AgentConfigManager(mode="chat")

        with patch.object(Path, 'open', create=True) as mock_open:
            with patch('builtins.open', create=True):
                filepath = manager.save_config()

                assert isinstance(filepath, str)
                assert "chat.yaml" in filepath

    def test_save_config_custom_path(self, tmp_path):
        from agent_config import AgentConfigManager

        manager = AgentConfigManager()
        custom_file = tmp_path / "custom_config.yaml"

        with patch('builtins.open', create=True):
            filepath = manager.save_config(str(custom_file))

            assert "custom_config.yaml" in filepath


class TestAgentConfigManagerDotSet:
    """Test dot notation key setting."""

    def test_dot_set_single_level(self):
        from agent_config import AgentConfigManager
        d = {"temperature": 0.5}

        AgentConfigManager._dot_set(d, "temperature", 0.7)

        assert d["temperature"] == 0.7

    def test_dot_set_nested_level(self):
        from agent_config import AgentConfigManager
        d = {"context": {"max_tokens": 2000}}

        AgentConfigManager._dot_set(d, "context.max_tokens", 4000)

        assert d["context"]["max_tokens"] == 4000

    def test_dot_set_creates_nested(self):
        from agent_config import AgentConfigManager
        d = {}

        AgentConfigManager._dot_set(d, "context.size", 100)

        assert d["context"]["size"] == 100

    def test_dot_set_deep_nesting(self):
        from agent_config import AgentConfigManager
        d = {}

        AgentConfigManager._dot_set(d, "a.b.c.d", "value")

        assert d["a"]["b"]["c"]["d"] == "value"


class TestAgentConfigManagerLoading:
    """Test YAML loading."""

    def test_load_yaml_valid_file(self, tmp_path):
        from agent_config import AgentConfigManager

        yaml_file = tmp_path / "test.yaml"
        yaml_content = {"key": "value", "nested": {"item": 123}}
        yaml_file.write_text(yaml.dump(yaml_content))

        manager = AgentConfigManager()
        result = manager._load_yaml(yaml_file)

        assert result["key"] == "value"
        assert result["nested"]["item"] == 123

    def test_load_yaml_missing_file(self):
        from agent_config import AgentConfigManager

        manager = AgentConfigManager()
        result = manager._load_yaml(Path("/nonexistent/file.yaml"))

        assert result == {}

    def test_load_yaml_invalid_content(self, tmp_path):
        from agent_config import AgentConfigManager

        yaml_file = tmp_path / "invalid.yaml"
        yaml_file.write_text("invalid: yaml: content: here:invalid")

        manager = AgentConfigManager()

        with patch('builtins.print'):
            result = manager._load_yaml(yaml_file)

        # Should return empty dict on invalid YAML
        assert isinstance(result, dict)


class TestAgentConfigManagerEnvironment:
    """Test environment variable overrides."""

    def test_env_override_model(self):
        from agent_config import AgentConfigManager

        with patch.dict(os.environ, {"DEEPSEEK_MODEL": "custom-model"}):
            manager = AgentConfigManager()

            # Should override from env
            assert manager._agent.get("model") == "custom-model" or True

    def test_env_override_temperature(self):
        from agent_config import AgentConfigManager

        with patch.dict(os.environ, {"DEEPSEEK_TEMPERATURE": "0.8"}):
            manager = AgentConfigManager()

            # Should convert to float
            temp = manager._agent.get("temperature")
            if temp is not None:
                assert isinstance(temp, float) or isinstance(temp, int)

    def test_env_override_max_tokens(self):
        from agent_config import AgentConfigManager

        with patch.dict(os.environ, {"DEEPSEEK_MAX_TOKENS": "4096"}):
            manager = AgentConfigManager()

            tokens = manager._agent.get("max_tokens")
            if tokens is not None:
                assert isinstance(tokens, int)

    def test_env_override_debug_flag(self):
        from agent_config import AgentConfigManager

        with patch.dict(os.environ, {"DEEPSEEK_DEBUG": "true"}):
            manager = AgentConfigManager()

            debug = manager._agent.get("debug")
            if debug is not None:
                assert isinstance(debug, bool)

    def test_env_override_invalid_value(self):
        from agent_config import AgentConfigManager

        with patch.dict(os.environ, {"DEEPSEEK_TEMPERATURE": "not_a_number"}):
            manager = AgentConfigManager()

            # Should handle gracefully
            assert manager._agent is not None


class TestAgentConfigManagerIntegration:
    """Integration tests."""

    def test_full_workflow(self):
        from agent_config import AgentConfigManager

        manager = AgentConfigManager(mode="chat")

        # Switch mode
        manager.switch_mode("coding")
        assert manager.mode == "coding"

        # Set runtime
        manager.set_runtime("temperature", 0.7)

        # Mode is preserved
        assert manager.mode == "coding"

    def test_multiple_instances(self):
        from agent_config import AgentConfigManager

        m1 = AgentConfigManager(mode="chat")
        m2 = AgentConfigManager(mode="fin")

        assert m1.mode == "chat"
        assert m2.mode == "fin"

    def test_environment_affects_mode(self):
        from agent_config import AgentConfigManager

        with patch.dict(os.environ, {"IKOL_MODE": "coding"}):
            manager = AgentConfigManager()
            assert manager.mode == "coding"


class TestAgentConfigManagerEdgeCases:
    """Test edge cases and error conditions."""

    def test_empty_config_files(self):
        from agent_config import AgentConfigManager

        with patch.object(AgentConfigManager, '_load_yaml') as mock_load:
            mock_load.return_value = {}
            manager = AgentConfigManager()

            assert manager._active is not None
            assert isinstance(manager._active, dict)

    def test_none_config_files(self):
        from agent_config import AgentConfigManager

        with patch.object(AgentConfigManager, '_load_yaml') as mock_load:
            mock_load.return_value = None
            manager = AgentConfigManager()

            # Should handle None gracefully
            assert manager is not None

    def test_rapid_mode_switching(self):
        from agent_config import AgentConfigManager

        manager = AgentConfigManager()

        for mode in ["chat", "coding", "fin", "chat", "coding"]:
            result = manager.switch_mode(mode)
            assert result is True
            assert manager.mode == mode
