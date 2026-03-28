"""
Comprehensive unit tests for agent/finance/config_editor.py
Tests config loading, saving, merging, and override management.
"""

import pytest
import yaml
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

import sys
sys.path.insert(0, '/sessions/hopeful-magical-rubin/mnt/NeoMind_agent')

from agent.finance.config_editor import ConfigEditor


class TestConfigEditorInit:
    """Tests for ConfigEditor initialization."""

    def test_init_custom_path(self, tmp_path):
        """Test initialization with custom path."""
        config_path = tmp_path / "config.yaml"
        editor = ConfigEditor(overrides_path=config_path)

        assert editor.path == config_path

    def test_init_default_path(self):
        """Test initialization with default path."""
        editor = ConfigEditor()
        assert editor.path is not None


class TestConfigLoad:
    """Tests for loading config."""

    def test_load_nonexistent_file(self, tmp_path):
        """Test loading from nonexistent file."""
        config_path = tmp_path / "nonexistent.yaml"
        editor = ConfigEditor(overrides_path=config_path)

        data = editor.load()
        assert data == {}

    def test_load_empty_file(self, tmp_path):
        """Test loading from empty file."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text("")

        editor = ConfigEditor(overrides_path=config_path)
        data = editor.load()
        assert data == {}

    def test_load_valid_yaml(self, tmp_path):
        """Test loading valid YAML."""
        config_path = tmp_path / "config.yaml"
        config_data = {
            "fin": {
                "extra_system_prompt": "test prompt",
                "search_triggers": ["stock", "price"]
            }
        }
        config_path.write_text(yaml.dump(config_data))

        editor = ConfigEditor(overrides_path=config_path)
        data = editor.load()

        assert data["fin"]["extra_system_prompt"] == "test prompt"
        assert "stock" in data["fin"]["search_triggers"]

    def test_load_caching(self, tmp_path):
        """Test that load() caches data."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text("fin:\n  test: value")

        editor = ConfigEditor(overrides_path=config_path)
        data1 = editor.load()
        data2 = editor.load()

        assert data1 is data2  # Same object due to caching

    def test_load_invalid_yaml(self, tmp_path):
        """Test loading invalid YAML."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text("{ invalid yaml ][")

        editor = ConfigEditor(overrides_path=config_path)
        data = editor.load()
        assert data == {}


class TestGetModeOverrides:
    """Tests for getting mode-specific overrides."""

    def test_get_mode_overrides_exists(self, tmp_path):
        """Test getting overrides for existing mode."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({
            "fin": {"prompt": "test"}
        }))

        editor = ConfigEditor(overrides_path=config_path)
        overrides = editor.get_mode_overrides("fin")

        assert overrides["prompt"] == "test"

    def test_get_mode_overrides_nonexistent(self, tmp_path):
        """Test getting overrides for nonexistent mode."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({"fin": {}}))

        editor = ConfigEditor(overrides_path=config_path)
        overrides = editor.get_mode_overrides("chat")

        assert overrides == {}

    def test_get_mode_overrides_empty_config(self, tmp_path):
        """Test getting overrides from empty config."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text("")

        editor = ConfigEditor(overrides_path=config_path)
        overrides = editor.get_mode_overrides("fin")

        assert overrides == {}


class TestGetExtraPrompt:
    """Tests for getting extra system prompt."""

    def test_get_extra_prompt_exists(self, tmp_path):
        """Test getting existing extra prompt."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({
            "fin": {"extra_system_prompt": "test prompt"}
        }))

        editor = ConfigEditor(overrides_path=config_path)
        prompt = editor.get_extra_prompt("fin")

        assert prompt == "test prompt"

    def test_get_extra_prompt_nonexistent(self, tmp_path):
        """Test getting nonexistent extra prompt."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({"fin": {}}))

        editor = ConfigEditor(overrides_path=config_path)
        prompt = editor.get_extra_prompt("fin")

        assert prompt == ""

    def test_get_extra_prompt_multiline(self, tmp_path):
        """Test getting multiline extra prompt."""
        config_path = tmp_path / "config.yaml"
        prompt_text = "Line 1\nLine 2\nLine 3"
        config_path.write_text(yaml.dump({
            "fin": {"extra_system_prompt": prompt_text}
        }))

        editor = ConfigEditor(overrides_path=config_path)
        prompt = editor.get_extra_prompt("fin")

        assert prompt == prompt_text


class TestGetSearchTriggers:
    """Tests for getting search triggers."""

    def test_get_search_triggers_single_mode(self, tmp_path):
        """Test getting triggers for single mode."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({
            "fin": {"search_triggers": ["stock", "price", "earnings"]}
        }))

        editor = ConfigEditor(overrides_path=config_path)
        triggers = editor.get_extra_search_triggers("fin")

        assert "stock" in triggers
        assert "price" in triggers

    def test_get_search_triggers_all_modes(self, tmp_path):
        """Test getting triggers from all modes."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({
            "fin": {"search_triggers": ["stock", "price"]},
            "chat": {"search_triggers": ["hello", "world"]}
        }))

        editor = ConfigEditor(overrides_path=config_path)
        triggers = editor.get_extra_search_triggers("")

        assert "stock" in triggers
        assert "hello" in triggers
        assert len(triggers) == 4

    def test_get_search_triggers_nonexistent(self, tmp_path):
        """Test getting nonexistent triggers."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({"fin": {}}))

        editor = ConfigEditor(overrides_path=config_path)
        triggers = editor.get_extra_search_triggers("fin")

        assert triggers == []


class TestGetSetting:
    """Tests for getting arbitrary settings."""

    def test_get_setting_exists(self, tmp_path):
        """Test getting existing setting."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({
            "fin": {"custom_setting": "value"}
        }))

        editor = ConfigEditor(overrides_path=config_path)
        value = editor.get_setting("fin", "custom_setting")

        assert value == "value"

    def test_get_setting_with_default(self, tmp_path):
        """Test getting setting with default."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({"fin": {}}))

        editor = ConfigEditor(overrides_path=config_path)
        value = editor.get_setting("fin", "nonexistent", default="default_val")

        assert value == "default_val"

    def test_get_setting_none_default(self, tmp_path):
        """Test getting setting with None default."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({"fin": {}}))

        editor = ConfigEditor(overrides_path=config_path)
        value = editor.get_setting("fin", "nonexistent")

        assert value is None


class TestSave:
    """Tests for saving config."""

    def test_save_basic(self, tmp_path):
        """Test saving basic config."""
        config_path = tmp_path / "config.yaml"
        editor = ConfigEditor(overrides_path=config_path)

        data = {"fin": {"prompt": "test"}}
        editor.save(data)

        assert config_path.exists()
        loaded = yaml.safe_load(config_path.read_text())
        assert loaded["fin"]["prompt"] == "test"

    def test_save_creates_parent_dirs(self, tmp_path):
        """Test that save creates parent directories."""
        config_path = tmp_path / "subdir" / "deeper" / "config.yaml"
        editor = ConfigEditor(overrides_path=config_path)

        editor.save({"fin": {}})

        assert config_path.exists()

    def test_save_overwrites(self, tmp_path):
        """Test that save overwrites existing file."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text("old: data")

        editor = ConfigEditor(overrides_path=config_path)
        editor.save({"fin": {"new": "data"}})

        loaded = yaml.safe_load(config_path.read_text())
        assert "old" not in loaded
        assert loaded["fin"]["new"] == "data"

    def test_save_preserves_unicode(self, tmp_path):
        """Test that save preserves Unicode."""
        config_path = tmp_path / "config.yaml"
        editor = ConfigEditor(overrides_path=config_path)

        data = {"fin": {"prompt": "你好世界"}}
        editor.save(data)

        loaded = yaml.safe_load(config_path.read_text())
        assert loaded["fin"]["prompt"] == "你好世界"

    def test_save_creates_backup(self, tmp_path):
        """Test that save creates history backup."""
        config_path = tmp_path / "config.yaml"
        history_dir = tmp_path / "history"

        editor = ConfigEditor(overrides_path=config_path)
        editor.history_dir = history_dir

        # First save
        config_path.write_text("initial")
        editor.save({"fin": {"v1": 1}})

        # Verify backup was created
        backups = list(history_dir.glob("*.yaml"))
        assert len(backups) == 1


class TestUpdateMode:
    """Tests for updating mode config."""

    def test_update_mode_new(self, tmp_path):
        """Test updating new mode."""
        config_path = tmp_path / "config.yaml"
        editor = ConfigEditor(overrides_path=config_path)

        editor.update_mode("fin", {"setting": "value"})

        loaded = editor.load()
        assert loaded["fin"]["setting"] == "value"

    def test_update_mode_merge(self, tmp_path):
        """Test that update merges into existing mode."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({
            "fin": {"old_setting": "old"}
        }))

        editor = ConfigEditor(overrides_path=config_path)
        editor.update_mode("fin", {"new_setting": "new"})

        loaded = editor.load()
        assert loaded["fin"]["old_setting"] == "old"
        assert loaded["fin"]["new_setting"] == "new"


class TestSetExtraPrompt:
    """Tests for setting extra prompt."""

    def test_set_extra_prompt_new(self, tmp_path):
        """Test setting new extra prompt."""
        config_path = tmp_path / "config.yaml"
        editor = ConfigEditor(overrides_path=config_path)

        editor.set_extra_prompt("fin", "new prompt")

        assert editor.get_extra_prompt("fin") == "new prompt"

    def test_set_extra_prompt_replace(self, tmp_path):
        """Test replacing existing prompt."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({
            "fin": {"extra_system_prompt": "old prompt"}
        }))

        editor = ConfigEditor(overrides_path=config_path)
        editor.set_extra_prompt("fin", "new prompt")

        assert editor.get_extra_prompt("fin") == "new prompt"


class TestAppendToPrompt:
    """Tests for appending to prompt."""

    def test_append_to_prompt_empty(self, tmp_path):
        """Test appending to empty prompt."""
        config_path = tmp_path / "config.yaml"
        editor = ConfigEditor(overrides_path=config_path)

        editor.append_to_prompt("fin", "text1")

        assert editor.get_extra_prompt("fin") == "text1"

    def test_append_to_prompt_existing(self, tmp_path):
        """Test appending to existing prompt."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({
            "fin": {"extra_system_prompt": "line1"}
        }))

        editor = ConfigEditor(overrides_path=config_path)
        editor.append_to_prompt("fin", "line2")

        prompt = editor.get_extra_prompt("fin")
        assert "line1" in prompt
        assert "line2" in prompt

    def test_append_to_prompt_multiline(self, tmp_path):
        """Test appending multiline text."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({
            "fin": {"extra_system_prompt": "existing"}
        }))

        editor = ConfigEditor(overrides_path=config_path)
        editor.append_to_prompt("fin", "new\nlines")

        prompt = editor.get_extra_prompt("fin")
        assert "new" in prompt and "lines" in prompt


class TestSearchTriggers:
    """Tests for managing search triggers."""

    def test_add_search_triggers_new(self, tmp_path):
        """Test adding new triggers."""
        config_path = tmp_path / "config.yaml"
        editor = ConfigEditor(overrides_path=config_path)

        editor.add_search_triggers(["trigger1", "trigger2"], mode="fin")

        triggers = editor.get_extra_search_triggers("fin")
        assert "trigger1" in triggers
        assert "trigger2" in triggers

    def test_add_search_triggers_merge(self, tmp_path):
        """Test adding triggers merges with existing."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({
            "fin": {"search_triggers": ["old"]}
        }))

        editor = ConfigEditor(overrides_path=config_path)
        editor.add_search_triggers(["new"], mode="fin")

        triggers = editor.get_extra_search_triggers("fin")
        assert "old" in triggers
        assert "new" in triggers

    def test_add_search_triggers_dedup(self, tmp_path):
        """Test that adding duplicates deduplicates."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({
            "fin": {"search_triggers": ["trigger"]}
        }))

        editor = ConfigEditor(overrides_path=config_path)
        editor.add_search_triggers(["trigger", "new"], mode="fin")

        triggers = editor.get_extra_search_triggers("fin")
        assert triggers.count("trigger") == 1

    def test_remove_search_triggers(self, tmp_path):
        """Test removing triggers."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({
            "fin": {"search_triggers": ["trigger1", "trigger2", "trigger3"]}
        }))

        editor = ConfigEditor(overrides_path=config_path)
        editor.remove_search_triggers(["trigger2"], mode="fin")

        triggers = editor.get_extra_search_triggers("fin")
        assert "trigger2" not in triggers
        assert "trigger1" in triggers

    def test_remove_search_triggers_nonexistent(self, tmp_path):
        """Test removing nonexistent trigger."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({
            "fin": {"search_triggers": ["trigger1"]}
        }))

        editor = ConfigEditor(overrides_path=config_path)
        # Should not raise
        editor.remove_search_triggers(["nonexistent"], mode="fin")

        triggers = editor.get_extra_search_triggers("fin")
        assert "trigger1" in triggers


class TestSetSetting:
    """Tests for setting arbitrary settings."""

    def test_set_setting_new(self, tmp_path):
        """Test setting new arbitrary setting."""
        config_path = tmp_path / "config.yaml"
        editor = ConfigEditor(overrides_path=config_path)

        editor.set_setting("fin", "custom_key", "custom_value")

        value = editor.get_setting("fin", "custom_key")
        assert value == "custom_value"

    def test_set_setting_replace(self, tmp_path):
        """Test replacing setting."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({
            "fin": {"key": "old"}
        }))

        editor = ConfigEditor(overrides_path=config_path)
        editor.set_setting("fin", "key", "new")

        assert editor.get_setting("fin", "key") == "new"


class TestReset:
    """Tests for reset operations."""

    def test_reset_mode(self, tmp_path):
        """Test resetting single mode."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({
            "fin": {"setting": "value"},
            "chat": {"setting": "value"}
        }))

        editor = ConfigEditor(overrides_path=config_path)
        editor.reset_mode("fin")

        loaded = editor.load()
        assert "fin" not in loaded
        assert "chat" in loaded

    def test_reset_all(self, tmp_path):
        """Test resetting all config."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({
            "fin": {"setting": "value"},
            "chat": {"setting": "value"}
        }))

        editor = ConfigEditor(overrides_path=config_path)
        editor.reset_all()

        loaded = editor.load()
        assert loaded == {}


class TestFormatStatus:
    """Tests for status formatting."""

    def test_format_status_empty(self, tmp_path):
        """Test formatting status when empty."""
        config_path = tmp_path / "config.yaml"
        editor = ConfigEditor(overrides_path=config_path)

        status = editor.format_status()
        assert "No custom overrides" in status or status == "📋 No custom overrides — using all defaults."

    def test_format_status_with_config(self, tmp_path):
        """Test formatting status with config."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({
            "fin": {
                "extra_system_prompt": "test prompt",
                "search_triggers": ["trigger1", "trigger2"]
            }
        }))

        editor = ConfigEditor(overrides_path=config_path)
        status = editor.format_status()

        assert "fin" in status
        assert "test prompt" in status or "Prompt" in status

    def test_format_status_long_prompt(self, tmp_path):
        """Test formatting status truncates long prompts."""
        config_path = tmp_path / "config.yaml"
        long_prompt = "x" * 500
        config_path.write_text(yaml.dump({
            "fin": {"extra_system_prompt": long_prompt}
        }))

        editor = ConfigEditor(overrides_path=config_path)
        status = editor.format_status()

        # Should truncate
        assert len(status) < len(long_prompt)


class TestIntegration:
    """Integration tests."""

    def test_full_workflow(self, tmp_path):
        """Test complete workflow."""
        config_path = tmp_path / "config.yaml"
        editor = ConfigEditor(overrides_path=config_path)

        # 1. Set initial config
        editor.set_extra_prompt("fin", "Initial prompt")
        editor.add_search_triggers(["stock", "price"], "fin")

        # 2. Load and verify
        data = editor.load()
        assert data["fin"]["extra_system_prompt"] == "Initial prompt"

        # 3. Append to prompt
        editor.append_to_prompt("fin", "\nAdditional line")
        prompt = editor.get_extra_prompt("fin")
        assert "Initial prompt" in prompt
        assert "Additional line" in prompt

        # 4. Add more triggers
        editor.add_search_triggers(["earnings"], "fin")
        triggers = editor.get_extra_search_triggers("fin")
        assert len(triggers) == 3

        # 5. Reset
        editor.reset_mode("fin")
        assert editor.get_mode_overrides("fin") == {}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
