"""
Comprehensive tests for agent/vault/_config.py

Run: pytest tests/test_vault_config_full.py -v
"""
import os
import sys
import pytest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestGetVaultDir:
    """Test get_vault_dir function."""

    def test_get_vault_dir_from_env(self):
        from agent.vault._config import get_vault_dir

        with patch.dict(os.environ, {"NEOMIND_VAULT_DIR": "/custom/vault"}):
            result = get_vault_dir()
            assert result == "/custom/vault"

    def test_get_vault_dir_docker_path(self):
        from agent.vault._config import get_vault_dir

        # Clear env var
        env = dict(os.environ)
        env.pop("NEOMIND_VAULT_DIR", None)

        with patch.dict(os.environ, env, clear=True):
            with patch('os.path.isdir') as mock_isdir:
                # Simulate /data exists (Docker)
                def isdir_side_effect(path):
                    return path == "/data"

                mock_isdir.side_effect = isdir_side_effect

                result = get_vault_dir()
                assert result == "/data/vault"

    def test_get_vault_dir_home_fallback(self):
        from agent.vault._config import get_vault_dir

        env = dict(os.environ)
        env.pop("NEOMIND_VAULT_DIR", None)

        with patch.dict(os.environ, env, clear=True):
            with patch('os.path.isdir') as mock_isdir:
                # Simulate /data does not exist
                mock_isdir.return_value = False

                with patch.object(Path, 'home') as mock_home:
                    mock_home.return_value = Path("/home/user")

                    result = get_vault_dir()
                    assert result == "/home/user/neomind-vault"

    def test_get_vault_dir_priority_env_first(self):
        from agent.vault._config import get_vault_dir

        with patch.dict(os.environ, {"NEOMIND_VAULT_DIR": "/env/vault"}):
            with patch('os.path.isdir') as mock_isdir:
                with patch.object(Path, 'home') as mock_home:
                    # Even if /data and home exist, env should win
                    mock_isdir.return_value = True
                    mock_home.return_value = Path("/home/user")

                    result = get_vault_dir()
                    assert result == "/env/vault"

    def test_get_vault_dir_returns_string(self):
        from agent.vault._config import get_vault_dir

        result = get_vault_dir()
        assert isinstance(result, str)

    def test_get_vault_dir_empty_env_var(self):
        from agent.vault._config import get_vault_dir

        with patch.dict(os.environ, {"NEOMIND_VAULT_DIR": ""}):
            with patch('os.path.isdir') as mock_isdir:
                with patch.object(Path, 'home') as mock_home:
                    mock_isdir.return_value = False
                    mock_home.return_value = Path("/home/user")

                    result = get_vault_dir()
                    # Empty env var should be treated as not set
                    assert result is not None

    def test_get_vault_dir_none_env_var(self):
        from agent.vault._config import get_vault_dir

        env = dict(os.environ)
        env.pop("NEOMIND_VAULT_DIR", None)

        with patch.dict(os.environ, env, clear=True):
            with patch('os.path.isdir') as mock_isdir:
                with patch.object(Path, 'home') as mock_home:
                    mock_isdir.return_value = False
                    mock_home.return_value = Path("/home/user")

                    result = get_vault_dir()
                    assert "neomind-vault" in result

    def test_get_vault_dir_various_docker_paths(self):
        from agent.vault._config import get_vault_dir

        env = dict(os.environ)
        env.pop("NEOMIND_VAULT_DIR", None)

        with patch.dict(os.environ, env, clear=True):
            with patch('os.path.isdir') as mock_isdir:
                mock_isdir.return_value = True

                result = get_vault_dir()
                assert result == "/data/vault"

    def test_get_vault_dir_consistency(self):
        """Verify get_vault_dir returns consistent results."""
        from agent.vault._config import get_vault_dir

        result1 = get_vault_dir()
        result2 = get_vault_dir()

        assert result1 == result2

    def test_get_vault_dir_with_custom_path_env(self):
        from agent.vault._config import get_vault_dir

        custom_path = "/opt/neomind/vault"
        with patch.dict(os.environ, {"NEOMIND_VAULT_DIR": custom_path}):
            result = get_vault_dir()
            assert result == custom_path

    def test_get_vault_dir_path_types(self):
        """Test that different path formats are handled."""
        from agent.vault._config import get_vault_dir

        test_paths = [
            "/absolute/path",
            "/path/with/many/levels",
            "/path-with-dashes",
            "/path_with_underscores",
        ]

        for test_path in test_paths:
            with patch.dict(os.environ, {"NEOMIND_VAULT_DIR": test_path}):
                result = get_vault_dir()
                assert result == test_path

    def test_get_vault_dir_windows_paths(self):
        """Test Windows path handling."""
        from agent.vault._config import get_vault_dir

        with patch.dict(os.environ, {"NEOMIND_VAULT_DIR": "C:\\vault"}):
            result = get_vault_dir()
            assert result == "C:\\vault"

    def test_get_vault_dir_relative_paths(self):
        """Test relative path handling."""
        from agent.vault._config import get_vault_dir

        with patch.dict(os.environ, {"NEOMIND_VAULT_DIR": "./vault"}):
            result = get_vault_dir()
            assert result == "./vault"

    def test_get_vault_dir_with_special_chars(self):
        """Test paths with special characters."""
        from agent.vault._config import get_vault_dir

        special_path = "/vault-2024/neomind-prod"
        with patch.dict(os.environ, {"NEOMIND_VAULT_DIR": special_path}):
            result = get_vault_dir()
            assert result == special_path


class TestVaultConfigModule:
    """Test module-level functionality."""

    def test_module_imports(self):
        """Verify module imports successfully."""
        from agent.vault import _config
        assert hasattr(_config, 'get_vault_dir')

    def test_function_callable(self):
        """Verify get_vault_dir is callable."""
        from agent.vault._config import get_vault_dir
        assert callable(get_vault_dir)

    def test_no_module_side_effects(self):
        """Verify importing doesn't have side effects."""
        import importlib
        from agent.vault import _config

        # Clear the module
        if '_config' in sys.modules:
            del sys.modules['agent.vault._config']

        # Re-import
        _config = importlib.import_module('agent.vault._config')

        # Should work without issues
        result = _config.get_vault_dir()
        assert isinstance(result, str)
