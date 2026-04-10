"""Tests for agent.state_manager — SessionState, FeatureFlags, StateManager.

Tests the Claude Code AppState.tsx pattern:
- SessionState holds all mutable session state
- FeatureFlags enable/disable features at runtime
- StateManager coordinates state with persistence and observation
"""

import pytest
import json
import os
import tempfile
from unittest.mock import MagicMock, patch

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.state_manager import (
    FeatureFlags,
    SessionState,
    StateManager,
)


# ─── FeatureFlags Tests ──────────────────────────────────────────────

class TestFeatureFlags:
    def test_default_value(self):
        flags = FeatureFlags(config_path="/nonexistent/path.json")
        assert flags.is_enabled("NONEXISTENT") is False
        assert flags.is_enabled("NONEXISTENT", default=True) is True

    def test_set_and_get(self):
        flags = FeatureFlags(config_path="/nonexistent/path.json")
        flags.set("TEST_FLAG", True)
        assert flags.is_enabled("TEST_FLAG") is True
        flags.set("TEST_FLAG", False)
        assert flags.is_enabled("TEST_FLAG") is False

    def test_get_all(self):
        flags = FeatureFlags(config_path="/nonexistent/path.json")
        flags.set("A", True)
        flags.set("B", False)
        all_flags = flags.get_all()
        assert all_flags["A"] is True
        assert all_flags["B"] is False

    def test_on_change_callback(self):
        flags = FeatureFlags(config_path="/nonexistent/path.json")
        called = []
        flags.on_change("X", lambda flag, val: called.append((flag, val)))
        flags.set("X", True)
        assert len(called) == 1
        assert called[0] == ("X", True)

    def test_no_callback_when_same_value(self):
        flags = FeatureFlags(config_path="/nonexistent/path.json")
        flags.set("X", True)
        called = []
        flags.on_change("X", lambda flag, val: called.append((flag, val)))
        flags.set("X", True)  # Same value, no change
        assert len(called) == 0

    def test_persist(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("{}")
            path = f.name
        try:
            flags = FeatureFlags(config_path=path)
            flags.set("PERSIST_ME", True, persist=True)

            # Reload and check
            flags2 = FeatureFlags(config_path=path)
            assert flags2.is_enabled("PERSIST_ME") is True
        finally:
            os.unlink(path)


# ─── SessionState Tests ──────────────────────────────────────────────

class TestSessionState:
    def test_defaults(self):
        state = SessionState()
        assert state.mode == "chat"
        assert state.model == "deepseek-chat"
        assert state.turn_count == 0
        assert state.is_active is True

    def test_custom_values(self):
        state = SessionState(mode="coding", model="kimi-k2.5")
        assert state.mode == "coding"
        assert state.model == "kimi-k2.5"

    def test_elapsed(self):
        state = SessionState()
        import time
        time.sleep(0.01)
        assert state.elapsed_seconds() > 0
        assert isinstance(state.elapsed_display(), str)

    def test_session_id_unique(self):
        s1 = SessionState()
        s2 = SessionState()
        assert s1.session_id != s2.session_id


# ─── StateManager Tests ──────────────────────────────────────────────

class TestStateManager:
    def _make_manager(self):
        mock_config = MagicMock()
        mock_config.mode = "chat"
        mock_config.model = "deepseek-chat"
        mock_config.fallback_model = None
        mock_config.thinking_enabled = True
        mock_config.thinking_mode = False
        mock_config.show_status_bar = True
        mock_config.search_enabled = True
        mock_config.auto_search_enabled = False
        mock_config.natural_language_enabled = True
        mock_config.get.side_effect = lambda k, d=None: {
            "temperature": 0.7,
            "enable_mcp_support": True,
            "compact.enabled": True,
        }.get(k, d)
        return StateManager(config=mock_config)

    def test_init(self):
        mgr = self._make_manager()
        assert mgr.session.mode == "chat"
        assert mgr.session.model == "deepseek-chat"

    def test_update(self):
        mgr = self._make_manager()
        mgr.update("mode", "coding")
        assert mgr.session.mode == "coding"

    def test_update_notifies_listeners(self):
        mgr = self._make_manager()
        changes = []
        mgr.on_change(lambda k, v: changes.append((k, v)))
        mgr.update("mode", "fin")
        assert len(changes) == 1
        assert changes[0] == ("mode", "fin")

    def test_update_unknown_key(self):
        mgr = self._make_manager()
        mgr.update("nonexistent_key", "value")  # Should not crash

    def test_snapshot(self):
        mgr = self._make_manager()
        snap = mgr.get_snapshot()
        assert "session" in snap
        assert "features" in snap
        assert snap["session"]["mode"] == "chat"

    def test_save_and_load_session(self):
        mgr = self._make_manager()
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr._sessions_dir = tmpdir
            messages = [
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "hello"},
            ]
            path = mgr.save_session(messages)
            assert os.path.exists(path)

            # Load back
            data = mgr.load_session(mgr.session.session_id)
            assert data is not None
            assert len(data["messages"]) == 2

    def test_load_nonexistent_session(self):
        mgr = self._make_manager()
        mgr._sessions_dir = "/nonexistent"
        assert mgr.load_session("fake_id") is None

    def test_list_sessions(self):
        mgr = self._make_manager()
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr._sessions_dir = tmpdir
            mgr.save_session([{"role": "user", "content": "test"}])
            sessions = mgr.list_sessions()
            assert len(sessions) >= 1
            assert "id" in sessions[0]
            assert "mode" in sessions[0]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
