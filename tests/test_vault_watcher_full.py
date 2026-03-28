"""Comprehensive tests for agent/vault/watcher.py — VaultWatcher."""

import os
import time
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from agent.vault.watcher import VaultWatcher


@pytest.fixture
def vault_dir(tmp_path):
    """Create a minimal vault directory."""
    d = tmp_path / "vault"
    d.mkdir()
    return d


@pytest.fixture
def populated_vault(vault_dir):
    """Vault with all 3 watched files."""
    (vault_dir / "MEMORY.md").write_text("---\ntype: memory\n---\n# Memory\n## About\nsome data\n", encoding="utf-8")
    (vault_dir / "current-goals.md").write_text("---\ntype: goals\n---\n# Goals\ngoal 1\n", encoding="utf-8")
    (vault_dir / "SOUL.md").write_text("---\ntype: soul\n---\n# Soul\nI am NeoMind.\n", encoding="utf-8")
    return vault_dir


class TestWatcherInit:
    """Initialization tests."""

    def test_init_with_vault_dir(self, vault_dir):
        w = VaultWatcher(vault_dir=str(vault_dir))
        assert w.vault_dir == vault_dir

    def test_init_stores_mtimes(self, populated_vault):
        w = VaultWatcher(vault_dir=str(populated_vault))
        assert "MEMORY.md" in w._stored_mtimes
        assert "current-goals.md" in w._stored_mtimes
        assert "SOUL.md" in w._stored_mtimes

    def test_init_nonexistent_files(self, vault_dir):
        w = VaultWatcher(vault_dir=str(vault_dir))
        assert w._stored_mtimes.get("MEMORY.md") is None
        assert w._stored_mtimes.get("SOUL.md") is None

    def test_watched_files_constant(self):
        assert "MEMORY.md" in VaultWatcher.WATCHED_FILES
        assert "current-goals.md" in VaultWatcher.WATCHED_FILES
        assert "SOUL.md" in VaultWatcher.WATCHED_FILES


class TestCheckForChanges:
    """Tests for check_for_changes()."""

    def test_no_changes_returns_none(self, populated_vault):
        w = VaultWatcher(vault_dir=str(populated_vault))
        assert w.check_for_changes() is None

    def test_detects_file_modification(self, populated_vault):
        w = VaultWatcher(vault_dir=str(populated_vault))
        # Modify a file (ensure mtime changes)
        time.sleep(0.05)
        (populated_vault / "MEMORY.md").write_text("# Updated Memory\nNew content\n", encoding="utf-8")
        changed = w.check_for_changes()
        assert changed is not None
        assert "MEMORY.md" in changed
        assert "Updated Memory" in changed["MEMORY.md"]

    def test_detects_new_file(self, vault_dir):
        w = VaultWatcher(vault_dir=str(vault_dir))
        # Create a watched file that didn't exist before
        (vault_dir / "MEMORY.md").write_text("# New Memory\n", encoding="utf-8")
        changed = w.check_for_changes()
        assert changed is not None
        assert "MEMORY.md" in changed

    def test_detects_file_deletion(self, populated_vault):
        w = VaultWatcher(vault_dir=str(populated_vault))
        # Delete a file
        (populated_vault / "SOUL.md").unlink()
        changed = w.check_for_changes()
        assert changed is not None
        assert "SOUL.md" in changed
        assert changed["SOUL.md"] is None  # Marked as deleted

    def test_multiple_changes(self, populated_vault):
        w = VaultWatcher(vault_dir=str(populated_vault))
        time.sleep(0.05)
        (populated_vault / "MEMORY.md").write_text("# Changed 1\n", encoding="utf-8")
        (populated_vault / "SOUL.md").write_text("# Changed 2\n", encoding="utf-8")
        changed = w.check_for_changes()
        assert changed is not None
        assert "MEMORY.md" in changed
        assert "SOUL.md" in changed

    def test_error_handling(self, populated_vault):
        w = VaultWatcher(vault_dir=str(populated_vault))
        # Make file unreadable via mocking
        with patch("os.path.getmtime", side_effect=OSError("Permission denied")):
            result = w.check_for_changes()
            # Should not crash, returns None or empty
            assert result is None or result == {}


class TestGetChangedContext:
    """Tests for get_changed_context()."""

    def test_no_changes_returns_none(self, populated_vault):
        w = VaultWatcher(vault_dir=str(populated_vault))
        assert w.get_changed_context("chat") is None

    def test_returns_formatted_context(self, populated_vault):
        w = VaultWatcher(vault_dir=str(populated_vault))
        time.sleep(0.05)
        (populated_vault / "MEMORY.md").write_text("---\ntype: memory\n---\n# Memory\nUpdated data\n", encoding="utf-8")
        context = w.get_changed_context("chat")
        assert context is not None
        assert "Updated Vault Context" in context
        assert "Long-Term Memory" in context
        assert "Updated data" in context

    def test_strips_yaml_frontmatter(self, populated_vault):
        w = VaultWatcher(vault_dir=str(populated_vault))
        time.sleep(0.05)
        (populated_vault / "MEMORY.md").write_text("---\ntype: memory\nlast_updated: 2024-01-01\n---\n# Real Content\n", encoding="utf-8")
        context = w.get_changed_context("chat")
        assert "type: memory" not in context
        assert "Real Content" in context

    def test_section_titles(self, populated_vault):
        w = VaultWatcher(vault_dir=str(populated_vault))
        time.sleep(0.05)
        (populated_vault / "MEMORY.md").write_text("---\n---\nMemory content\n", encoding="utf-8")
        (populated_vault / "current-goals.md").write_text("---\n---\nGoals content\n", encoding="utf-8")
        (populated_vault / "SOUL.md").write_text("---\n---\nSoul content\n", encoding="utf-8")
        context = w.get_changed_context("chat")
        assert "Long-Term Memory" in context
        assert "Current Improvement Targets" in context
        assert "Identity and Personality" in context

    def test_skips_deleted_files(self, populated_vault):
        w = VaultWatcher(vault_dir=str(populated_vault))
        (populated_vault / "SOUL.md").unlink()
        time.sleep(0.05)
        (populated_vault / "MEMORY.md").write_text("---\n---\nNew Memory\n", encoding="utf-8")
        context = w.get_changed_context("chat")
        # Should have Memory but not crash on deleted SOUL
        assert context is not None
        assert "New Memory" in context

    def test_all_files_deleted_returns_none(self, populated_vault):
        w = VaultWatcher(vault_dir=str(populated_vault))
        for f in VaultWatcher.WATCHED_FILES:
            (populated_vault / f).unlink()
        context = w.get_changed_context("chat")
        assert context is None


class TestMarkSeen:
    """Tests for mark_seen()."""

    def test_mark_seen_clears_changes(self, populated_vault):
        w = VaultWatcher(vault_dir=str(populated_vault))
        time.sleep(0.05)
        (populated_vault / "MEMORY.md").write_text("# Changed\n", encoding="utf-8")
        assert w.check_for_changes() is not None
        w.mark_seen()
        assert w.check_for_changes() is None

    def test_mark_seen_updates_mtimes(self, populated_vault):
        w = VaultWatcher(vault_dir=str(populated_vault))
        old_mtimes = dict(w._stored_mtimes)
        time.sleep(0.05)
        (populated_vault / "MEMORY.md").write_text("# Changed\n", encoding="utf-8")
        w.mark_seen()
        assert w._stored_mtimes["MEMORY.md"] != old_mtimes["MEMORY.md"]


class TestUpdateStoredMtimes:
    """Tests for _update_stored_mtimes()."""

    def test_updates_existing_file_mtime(self, populated_vault):
        w = VaultWatcher(vault_dir=str(populated_vault))
        initial_mtime = w._stored_mtimes["MEMORY.md"]
        time.sleep(0.05)
        (populated_vault / "MEMORY.md").write_text("# Updated\n", encoding="utf-8")
        w._update_stored_mtimes()
        assert w._stored_mtimes["MEMORY.md"] != initial_mtime

    def test_sets_none_for_missing_file(self, vault_dir):
        w = VaultWatcher(vault_dir=str(vault_dir))
        assert w._stored_mtimes.get("MEMORY.md") is None

    def test_handles_permission_error(self, populated_vault):
        w = VaultWatcher(vault_dir=str(populated_vault))
        with patch("os.path.getmtime", side_effect=OSError("Permission denied")):
            w._update_stored_mtimes()
            # Should set to None, not crash
            assert w._stored_mtimes["MEMORY.md"] is None
