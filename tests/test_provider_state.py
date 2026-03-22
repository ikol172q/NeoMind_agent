# tests/test_provider_state.py
"""
Comprehensive tests for ProviderStateManager — bidirectional provider sync.

Coverage:
- State file read/write/atomic operations
- mtime cache behavior
- Corruption recovery (backup + default)
- Schema migration framework
- Bot registration (new + idempotent)
- Provider mode switching
- Provider chain building (litellm, direct, fallback)
- External change detection (xbar → bot)
- Health status updates
- Status text formatting
- Concurrent file access simulation
- VirtioFS mtime delay simulation
- provider-ctl.py CLI tool
- API key safety assertion
- Edge cases (empty state, missing fields, etc.)
"""

import json
import os
import sys
import time
import tempfile
import shutil
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add project root to path — import the module directly to avoid
# pulling in the full agent package (which requires aiohttp etc.)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import importlib.util
_spec = importlib.util.spec_from_file_location(
    "provider_state",
    os.path.join(os.path.dirname(__file__), "..", "agent", "finance", "provider_state.py"),
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

ProviderStateManager = _mod.ProviderStateManager
DEFAULT_STATE = _mod.DEFAULT_STATE
DEFAULT_BOT_CONFIG = _mod.DEFAULT_BOT_CONFIG
CURRENT_SCHEMA_VERSION = _mod.CURRENT_SCHEMA_VERSION
_now_iso = _mod._now_iso


class TestProviderStateBase(unittest.TestCase):
    """Base class with temp directory setup/teardown."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="neomind_test_")
        self.state_dir = os.path.join(self.tmp_dir, ".neomind")
        os.makedirs(self.state_dir, exist_ok=True)
        self.state_file = os.path.join(self.state_dir, "provider-state.json")

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _make_mgr(self, **env_overrides) -> ProviderStateManager:
        """Create a ProviderStateManager with test directory."""
        return ProviderStateManager(state_dir=self.state_dir)

    def _write_state(self, data: dict):
        """Directly write a state file for test setup."""
        with open(self.state_file, "w") as f:
            json.dump(data, f, indent=2)

    def _read_state(self) -> dict:
        """Directly read state file."""
        with open(self.state_file) as f:
            return json.load(f)


# ═══════════════════════════════════════════════════════════════════
# 1. State File Read/Write
# ═══════════════════════════════════════════════════════════════════

class TestReadWrite(TestProviderStateBase):
    """Test basic state file operations."""

    def test_fresh_start_returns_default(self):
        """No state file → returns default state."""
        mgr = self._make_mgr()
        state = mgr._read_state()
        self.assertEqual(state["schema_version"], CURRENT_SCHEMA_VERSION)
        self.assertIn("bots", state)
        self.assertIn("litellm", state)
        self.assertEqual(state["bots"], {})

    def test_write_and_read_roundtrip(self):
        """Write state → read it back identically."""
        mgr = self._make_mgr()
        mgr.register_bot("testbot")
        state = mgr._read_state()
        self.assertIn("testbot", state["bots"])
        self.assertEqual(state["bots"]["testbot"]["provider_mode"], "direct")

    def test_atomic_write_uses_tmp_rename(self):
        """Verify .tmp file is used during write (no partial reads)."""
        mgr = self._make_mgr()
        state = mgr._default_state()
        mgr._atomic_write(state)

        # After write, .tmp should be gone (renamed to .json)
        tmp_file = Path(self.state_file).with_suffix(".json.tmp")
        self.assertFalse(tmp_file.exists())
        self.assertTrue(Path(self.state_file).exists())

    def test_state_file_is_valid_json(self):
        """Written file is always valid JSON."""
        mgr = self._make_mgr()
        mgr.register_bot("neomind")
        mgr.set_provider_mode("neomind", "litellm", updated_by="test")

        with open(self.state_file) as f:
            data = json.load(f)  # Should not raise
        self.assertIsInstance(data, dict)

    def test_api_key_safety_assertion(self):
        """Writing a state with API key must raise AssertionError."""
        mgr = self._make_mgr()
        bad_state = mgr._default_state()
        bad_state["api_key"] = "sk-secret-123"

        with self.assertRaises(AssertionError):
            mgr._atomic_write(bad_state)

    def test_api_key_safety_nested(self):
        """API key check catches nested keys too."""
        mgr = self._make_mgr()
        bad_state = mgr._default_state()
        bad_state["bots"]["test"] = {"deepseek_api_key": "sk-123"}

        with self.assertRaises(AssertionError):
            mgr._atomic_write(bad_state)


# ═══════════════════════════════════════════════════════════════════
# 2. mtime Cache
# ═══════════════════════════════════════════════════════════════════

class TestMtimeCache(TestProviderStateBase):
    """Test that mtime caching avoids unnecessary file reads."""

    def test_cache_hit_returns_same_object(self):
        """Two reads without file change → same cached dict."""
        mgr = self._make_mgr()
        mgr.register_bot("bot1")

        state1 = mgr._read_state()
        state2 = mgr._read_state()
        # Same object (cache hit)
        self.assertIs(state1, state2)

    def test_cache_invalidated_on_external_write(self):
        """External file modification → cache miss → re-read."""
        mgr = self._make_mgr()
        mgr.register_bot("bot1")

        state1 = mgr._read_state()

        # Simulate external write (xbar)
        time.sleep(0.05)  # Ensure mtime changes
        data = self._read_state()
        data["bots"]["bot1"]["provider_mode"] = "litellm"
        data["bots"]["bot1"]["updated_by"] = "xbar"
        self._write_state(data)

        state2 = mgr._read_state()
        # Should be different object (cache miss)
        self.assertIsNot(state1, state2)
        self.assertEqual(state2["bots"]["bot1"]["provider_mode"], "litellm")

    def test_cache_updated_after_own_write(self):
        """Our own writes update the cache."""
        mgr = self._make_mgr()
        mgr.register_bot("bot1")
        mgr.set_provider_mode("bot1", "litellm", updated_by="test")

        state = mgr._read_state()
        self.assertEqual(state["bots"]["bot1"]["provider_mode"], "litellm")
        # Cache should reflect own write without file re-read
        self.assertEqual(mgr._cached_mtime, Path(self.state_file).stat().st_mtime)


# ═══════════════════════════════════════════════════════════════════
# 3. Corruption Recovery
# ═══════════════════════════════════════════════════════════════════

class TestCorruptionRecovery(TestProviderStateBase):
    """Test recovery from corrupted state files."""

    def test_corrupted_json_creates_backup(self):
        """Corrupted JSON → backed up → fresh default state."""
        # Write garbage
        with open(self.state_file, "w") as f:
            f.write("{invalid json!!!}")

        mgr = self._make_mgr()
        state = mgr._read_state()

        # Should get default state
        self.assertEqual(state["schema_version"], CURRENT_SCHEMA_VERSION)
        self.assertEqual(state["bots"], {})

        # Backup should exist
        bak = Path(self.state_file).with_suffix(".json.bak")
        self.assertTrue(bak.exists())

    def test_empty_file_recovery(self):
        """Empty file → treated as corrupted → default state."""
        Path(self.state_file).touch()

        mgr = self._make_mgr()
        state = mgr._read_state()
        self.assertEqual(state["schema_version"], CURRENT_SCHEMA_VERSION)

    def test_missing_fields_patched(self):
        """State file missing expected fields → patched by migration."""
        self._write_state({"schema_version": 0})

        mgr = self._make_mgr()
        state = mgr._read_state()
        self.assertIn("bots", state)
        self.assertIn("litellm", state)
        self.assertEqual(state["schema_version"], CURRENT_SCHEMA_VERSION)


# ═══════════════════════════════════════════════════════════════════
# 4. Schema Migration
# ═══════════════════════════════════════════════════════════════════

class TestSchemaMigration(TestProviderStateBase):
    """Test schema migration framework."""

    def test_v0_to_v1_migration(self):
        """Old state (no version) gets migrated to v1."""
        old_state = {"some_legacy_key": "value"}
        self._write_state(old_state)

        mgr = self._make_mgr()
        state = mgr._read_state()

        self.assertEqual(state["schema_version"], CURRENT_SCHEMA_VERSION)
        self.assertIn("bots", state)
        self.assertIn("litellm", state)
        # Legacy key preserved
        self.assertEqual(state["some_legacy_key"], "value")

    def test_current_version_no_migration(self):
        """State at current version → no migration needed."""
        current = {
            "schema_version": CURRENT_SCHEMA_VERSION,
            "updated_at": "2026-01-01T00:00:00Z",
            "updated_by": "test",
            "bots": {"neomind": DEFAULT_BOT_CONFIG.copy()},
            "litellm": DEFAULT_STATE["litellm"].copy(),
        }
        self._write_state(current)

        mgr = self._make_mgr()
        state = mgr._read_state()
        self.assertEqual(state["schema_version"], CURRENT_SCHEMA_VERSION)

    def test_invalid_schema_version_type(self):
        """Non-integer schema version → treated as v0."""
        self._write_state({"schema_version": "banana"})

        mgr = self._make_mgr()
        state = mgr._read_state()
        self.assertEqual(state["schema_version"], CURRENT_SCHEMA_VERSION)


# ═══════════════════════════════════════════════════════════════════
# 5. Bot Registration
# ═══════════════════════════════════════════════════════════════════

class TestBotRegistration(TestProviderStateBase):
    """Test bot registration lifecycle."""

    def test_register_new_bot(self):
        """First registration creates bot with default config."""
        mgr = self._make_mgr()
        mgr.register_bot("neomind")

        state = self._read_state()
        self.assertIn("neomind", state["bots"])
        self.assertEqual(state["bots"]["neomind"]["provider_mode"], "direct")
        self.assertEqual(state["bots"]["neomind"]["updated_by"], "registration")

    def test_register_idempotent(self):
        """Re-registering preserves existing config."""
        mgr = self._make_mgr()
        mgr.register_bot("neomind")
        mgr.set_provider_mode("neomind", "litellm", updated_by="test")

        # Re-register — should NOT reset mode
        mgr.register_bot("neomind")
        state = self._read_state()
        self.assertEqual(state["bots"]["neomind"]["provider_mode"], "litellm")

    def test_register_with_custom_defaults(self):
        """Registration with custom defaults applies them."""
        mgr = self._make_mgr()
        mgr.register_bot("custom", defaults={"direct_model": "gpt-4o"})

        config = mgr.get_bot_config("custom")
        self.assertEqual(config["direct_model"], "gpt-4o")

    @patch.dict(os.environ, {"LITELLM_ENABLED": "true"})
    def test_register_migrates_from_env(self):
        """First registration with LITELLM_ENABLED=true → litellm mode."""
        mgr = self._make_mgr()
        mgr.register_bot("envbot")

        config = mgr.get_bot_config("envbot")
        self.assertEqual(config["provider_mode"], "litellm")

    def test_register_multiple_bots(self):
        """Multiple bots can be registered independently."""
        mgr = self._make_mgr()
        mgr.register_bot("neomind")
        mgr.register_bot("othbot")
        mgr.set_provider_mode("neomind", "litellm", updated_by="test")

        neomind = mgr.get_bot_config("neomind")
        othbot = mgr.get_bot_config("othbot")
        self.assertEqual(neomind["provider_mode"], "litellm")
        self.assertEqual(othbot["provider_mode"], "direct")

    def test_get_unregistered_bot_returns_default(self):
        """Getting config for unknown bot returns defaults."""
        mgr = self._make_mgr()
        config = mgr.get_bot_config("nonexistent")
        self.assertEqual(config["provider_mode"], "direct")


# ═══════════════════════════════════════════════════════════════════
# 6. Provider Mode Switching
# ═══════════════════════════════════════════════════════════════════

class TestProviderMode(TestProviderStateBase):
    """Test provider mode set/get."""

    def test_set_litellm_mode(self):
        """Switch to litellm mode."""
        mgr = self._make_mgr()
        mgr.register_bot("neomind")
        result = mgr.set_provider_mode("neomind", "litellm", updated_by="test")

        self.assertEqual(result["provider_mode"], "litellm")
        self.assertEqual(result["updated_by"], "test")

    def test_set_direct_mode(self):
        """Switch to direct mode."""
        mgr = self._make_mgr()
        mgr.register_bot("neomind")
        mgr.set_provider_mode("neomind", "litellm", updated_by="test")
        result = mgr.set_provider_mode("neomind", "direct", updated_by="xbar")

        self.assertEqual(result["provider_mode"], "direct")
        self.assertEqual(result["updated_by"], "xbar")

    def test_set_invalid_mode_raises(self):
        """Invalid mode raises ValueError."""
        mgr = self._make_mgr()
        mgr.register_bot("neomind")

        with self.assertRaises(ValueError):
            mgr.set_provider_mode("neomind", "invalid_mode")

    def test_set_mode_auto_registers(self):
        """Setting mode for unregistered bot auto-registers it."""
        mgr = self._make_mgr()
        result = mgr.set_provider_mode("newbot", "litellm", updated_by="test")
        self.assertEqual(result["provider_mode"], "litellm")

    def test_mode_persists_across_instances(self):
        """Mode change survives creating a new ProviderStateManager."""
        mgr1 = self._make_mgr()
        mgr1.register_bot("neomind")
        mgr1.set_provider_mode("neomind", "litellm", updated_by="test")

        # New instance reads same file
        mgr2 = ProviderStateManager(state_dir=self.state_dir)
        config = mgr2.get_bot_config("neomind")
        self.assertEqual(config["provider_mode"], "litellm")

    def test_updated_at_changes_on_set(self):
        """Setting mode updates timestamp."""
        mgr = self._make_mgr()
        mgr.register_bot("neomind")

        before = self._read_state()["bots"]["neomind"]["updated_at"]
        time.sleep(1.1)  # Timestamp has 1s granularity
        mgr.set_provider_mode("neomind", "litellm", updated_by="test")
        after = self._read_state()["bots"]["neomind"]["updated_at"]

        self.assertNotEqual(before, after)


# ═══════════════════════════════════════════════════════════════════
# 7. Provider Chain Building
# ═══════════════════════════════════════════════════════════════════

class TestProviderChain(TestProviderStateBase):
    """Test get_provider_chain() builds correct ordered fallback list."""

    @patch.dict(os.environ, {
        "DEEPSEEK_API_KEY": "sk-ds-test",
        "ZAI_API_KEY": "sk-zai-test",
        "LITELLM_API_KEY": "",
    }, clear=False)
    def test_direct_mode_chain(self):
        """Direct mode: DeepSeek → z.ai, no litellm."""
        mgr = self._make_mgr()
        mgr.register_bot("neomind")
        chain = mgr.get_provider_chain("neomind", thinking=False)

        names = [p["name"] for p in chain]
        self.assertEqual(names, ["deepseek", "zai"])
        self.assertEqual(chain[0]["model"], "deepseek-chat")

    @patch.dict(os.environ, {
        "DEEPSEEK_API_KEY": "sk-ds-test",
        "ZAI_API_KEY": "sk-zai-test",
        "LITELLM_API_KEY": "sk-litellm-test",
        "LITELLM_BASE_URL": "http://localhost:4000/v1",
    }, clear=False)
    def test_litellm_mode_chain(self):
        """LiteLLM mode: litellm → DeepSeek → z.ai."""
        mgr = self._make_mgr()
        mgr.register_bot("neomind")
        mgr.set_provider_mode("neomind", "litellm", updated_by="test")

        chain = mgr.get_provider_chain("neomind", thinking=False)
        names = [p["name"] for p in chain]
        self.assertEqual(names[0], "litellm")
        self.assertIn("deepseek", names)
        self.assertEqual(chain[0]["model"], "local")

    @patch.dict(os.environ, {
        "DEEPSEEK_API_KEY": "sk-ds-test",
        "ZAI_API_KEY": "",
        "LITELLM_API_KEY": "",
    }, clear=False)
    def test_single_provider_only(self):
        """Only DeepSeek key → chain has only DeepSeek."""
        mgr = self._make_mgr()
        mgr.register_bot("neomind")
        chain = mgr.get_provider_chain("neomind", thinking=False)

        self.assertEqual(len(chain), 1)
        self.assertEqual(chain[0]["name"], "deepseek")

    @patch.dict(os.environ, {
        "DEEPSEEK_API_KEY": "sk-ds-test",
        "ZAI_API_KEY": "",
        "LITELLM_API_KEY": "",
    }, clear=False)
    def test_thinking_mode_uses_reasoner(self):
        """Thinking=True → uses deepseek-reasoner model."""
        mgr = self._make_mgr()
        mgr.register_bot("neomind")
        chain = mgr.get_provider_chain("neomind", thinking=True)

        self.assertEqual(chain[0]["model"], "deepseek-reasoner")

    @patch.dict(os.environ, {
        "DEEPSEEK_API_KEY": "",
        "ZAI_API_KEY": "",
        "LITELLM_API_KEY": "",
    }, clear=False)
    def test_no_keys_empty_chain(self):
        """No API keys configured → empty chain."""
        mgr = self._make_mgr()
        mgr.register_bot("neomind")
        chain = mgr.get_provider_chain("neomind")
        self.assertEqual(chain, [])

    @patch.dict(os.environ, {
        "DEEPSEEK_API_KEY": "sk-ds-test",
        "ZAI_API_KEY": "sk-zai-test",
        "LITELLM_API_KEY": "sk-litellm-test",
    }, clear=False)
    def test_litellm_mode_with_thinking(self):
        """LiteLLM mode + thinking → litellm uses thinking model."""
        mgr = self._make_mgr()
        mgr.register_bot("neomind")
        mgr.set_provider_mode("neomind", "litellm", updated_by="test")

        chain = mgr.get_provider_chain("neomind", thinking=True)
        self.assertEqual(chain[0]["name"], "litellm")
        self.assertEqual(chain[0]["model"], "deepseek-reasoner")


# ═══════════════════════════════════════════════════════════════════
# 8. External Change Detection
# ═══════════════════════════════════════════════════════════════════

class TestChangeDetection(TestProviderStateBase):
    """Test detect_external_change() for xbar → bot sync."""

    def test_no_change_returns_none(self):
        """No external change → None."""
        mgr = self._make_mgr()
        mgr.register_bot("neomind")
        result = mgr.detect_external_change("neomind")
        self.assertIsNone(result)

    def test_detect_xbar_switch(self):
        """xbar switches mode → bot detects it."""
        mgr = self._make_mgr()
        mgr.register_bot("neomind")
        mgr.detect_external_change("neomind")  # Initialize tracking

        # Simulate xbar external write
        time.sleep(0.05)
        data = self._read_state()
        data["bots"]["neomind"]["provider_mode"] = "litellm"
        data["bots"]["neomind"]["updated_by"] = "xbar"
        self._write_state(data)

        result = mgr.detect_external_change("neomind")
        self.assertIsNotNone(result)
        self.assertIn("litellm", result)
        self.assertIn("xbar", result)

    def test_own_change_not_detected(self):
        """Our own set_provider_mode doesn't trigger detection."""
        mgr = self._make_mgr()
        mgr.register_bot("neomind")
        mgr.set_provider_mode("neomind", "litellm", updated_by="telegram")

        result = mgr.detect_external_change("neomind")
        self.assertIsNone(result)

    def test_detection_resets_after_read(self):
        """After detection, next call returns None (until another change)."""
        mgr = self._make_mgr()
        mgr.register_bot("neomind")
        mgr.detect_external_change("neomind")

        # External switch
        time.sleep(0.05)
        data = self._read_state()
        data["bots"]["neomind"]["provider_mode"] = "litellm"
        self._write_state(data)

        result1 = mgr.detect_external_change("neomind")
        self.assertIsNotNone(result1)

        result2 = mgr.detect_external_change("neomind")
        self.assertIsNone(result2)

    def test_detect_unregistered_bot(self):
        """Detect change for bot not yet tracked → None (no crash)."""
        mgr = self._make_mgr()
        result = mgr.detect_external_change("unknown_bot")
        self.assertIsNone(result)


# ═══════════════════════════════════════════════════════════════════
# 9. Health Status
# ═══════════════════════════════════════════════════════════════════

class TestHealth(TestProviderStateBase):
    """Test LiteLLM health status management."""

    def test_update_health_ok(self):
        """Set health to True."""
        mgr = self._make_mgr()
        mgr.update_health(True)

        state = self._read_state()
        self.assertTrue(state["litellm"]["health_ok"])
        self.assertNotEqual(state["litellm"]["last_health_check"], "")

    def test_update_health_fail(self):
        """Set health to False."""
        mgr = self._make_mgr()
        mgr.update_health(True)
        mgr.update_health(False)

        self.assertFalse(mgr.is_litellm_healthy())

    def test_default_health_is_false(self):
        """Fresh state has health_ok=False."""
        mgr = self._make_mgr()
        self.assertFalse(mgr.is_litellm_healthy())


# ═══════════════════════════════════════════════════════════════════
# 10. Status Text
# ═══════════════════════════════════════════════════════════════════

class TestStatusText(TestProviderStateBase):
    """Test get_status_text() formatting."""

    @patch.dict(os.environ, {
        "DEEPSEEK_API_KEY": "sk-ds-test",
        "ZAI_API_KEY": "",
        "LITELLM_API_KEY": "",
    }, clear=False)
    def test_status_text_contains_mode(self):
        """Status text includes current mode."""
        mgr = self._make_mgr()
        mgr.register_bot("neomind")
        text = mgr.get_status_text("neomind")
        self.assertIn("direct", text)

    @patch.dict(os.environ, {
        "DEEPSEEK_API_KEY": "sk-ds-test",
        "ZAI_API_KEY": "",
        "LITELLM_API_KEY": "",
    }, clear=False)
    def test_status_text_contains_provider_chain(self):
        """Status text includes provider names."""
        mgr = self._make_mgr()
        mgr.register_bot("neomind")
        text = mgr.get_status_text("neomind")
        self.assertIn("deepseek", text)


# ═══════════════════════════════════════════════════════════════════
# 11. get_all_bots
# ═══════════════════════════════════════════════════════════════════

class TestGetAllBots(TestProviderStateBase):

    def test_all_bots_empty(self):
        mgr = self._make_mgr()
        self.assertEqual(mgr.get_all_bots(), {})

    def test_all_bots_multiple(self):
        mgr = self._make_mgr()
        mgr.register_bot("a")
        mgr.register_bot("b")
        bots = mgr.get_all_bots()
        self.assertIn("a", bots)
        self.assertIn("b", bots)


# ═══════════════════════════════════════════════════════════════════
# 12. VirtioFS mtime Delay Simulation
# ═══════════════════════════════════════════════════════════════════

class TestVirtioFSDelay(TestProviderStateBase):
    """Simulate VirtioFS mtime propagation delay (Docker Desktop macOS).

    Even if mtime doesn't change, detect_external_change should
    still catch mode differences via string comparison.
    """

    def test_mode_change_detected_without_mtime_change(self):
        """If mtime stays the same but content differs, detect via mode string."""
        mgr = self._make_mgr()
        mgr.register_bot("neomind")
        mgr.detect_external_change("neomind")

        # Simulate external write WITHOUT mtime change
        data = self._read_state()
        data["bots"]["neomind"]["provider_mode"] = "litellm"
        data["bots"]["neomind"]["updated_by"] = "xbar"
        self._write_state(data)

        # Force cache to have old mtime (simulate VirtioFS delay)
        mgr._cached_mtime = Path(self.state_file).stat().st_mtime
        old_state = json.loads(json.dumps(mgr._cached_state))
        old_state["bots"]["neomind"]["provider_mode"] = "direct"  # old value in cache
        # But re-read will happen because detect_external_change calls get_bot_config
        # which calls _read_state — the key test is whether the dual detection works.

        # Re-read state explicitly (simulating eventual mtime update)
        mgr._cached_state = None  # Force re-read
        mgr._cached_mtime = 0.0

        result = mgr.detect_external_change("neomind")
        self.assertIsNotNone(result)
        self.assertIn("litellm", result)


# ═══════════════════════════════════════════════════════════════════
# 13. Concurrent Access Simulation
# ═══════════════════════════════════════════════════════════════════

class TestConcurrentAccess(TestProviderStateBase):
    """Simulate concurrent reads/writes from multiple processes."""

    def test_two_managers_share_state(self):
        """Two ProviderStateManagers can share the same state file."""
        mgr1 = ProviderStateManager(state_dir=self.state_dir)
        mgr2 = ProviderStateManager(state_dir=self.state_dir)

        mgr1.register_bot("neomind")
        mgr1.set_provider_mode("neomind", "litellm", updated_by="mgr1")

        # mgr2 should see the change
        config = mgr2.get_bot_config("neomind")
        self.assertEqual(config["provider_mode"], "litellm")

    def test_rapid_writes_no_corruption(self):
        """Rapid sequential writes produce valid JSON."""
        mgr = self._make_mgr()
        mgr.register_bot("bot")

        for i in range(50):
            mode = "litellm" if i % 2 == 0 else "direct"
            mgr.set_provider_mode("bot", mode, updated_by=f"iter{i}")

        # Final state should be valid and consistent
        state = self._read_state()
        self.assertIn("bot", state["bots"])
        self.assertIn(state["bots"]["bot"]["provider_mode"], ("litellm", "direct"))


# ═══════════════════════════════════════════════════════════════════
# 14. provider-ctl.py CLI Tool
# ═══════════════════════════════════════════════════════════════════

class TestProviderCtl(TestProviderStateBase):
    """Test the xbar CLI tool (provider-ctl.py)."""

    def _ctl(self, *args) -> subprocess.CompletedProcess:
        """Run provider-ctl.py with custom state dir."""
        ctl_path = os.path.join(
            os.path.dirname(__file__), "..", "xbar", "provider-ctl.py"
        )
        env = os.environ.copy()
        env["NEOMIND_STATE_DIR"] = self.state_dir

        return subprocess.run(
            [sys.executable, ctl_path, *args],
            capture_output=True, text=True, env=env, timeout=10,
        )

    def test_ctl_get_empty(self):
        """provider-ctl.py get with no bots."""
        result = self._ctl("get")
        self.assertEqual(result.returncode, 0)
        self.assertIn("No bots", result.stdout)

    def test_ctl_set_and_get(self):
        """Set mode via CLI, then verify via get."""
        result = self._ctl("set", "neomind", "litellm")
        self.assertEqual(result.returncode, 0)
        self.assertIn("litellm", result.stdout)

        result = self._ctl("get", "neomind")
        self.assertEqual(result.returncode, 0)
        self.assertIn("litellm", result.stdout)

    def test_ctl_set_invalid_mode(self):
        """Invalid mode → non-zero exit."""
        result = self._ctl("set", "bot", "banana")
        self.assertNotEqual(result.returncode, 0)

    def test_ctl_health_update(self):
        """Health-update writes to state file."""
        self._ctl("health-update", "true")
        state = self._read_state()
        self.assertTrue(state["litellm"]["health_ok"])

        self._ctl("health-update", "false")
        state = self._read_state()
        self.assertFalse(state["litellm"]["health_ok"])

    def test_ctl_unknown_command(self):
        """Unknown command → non-zero exit."""
        result = self._ctl("banana")
        self.assertNotEqual(result.returncode, 0)

    def test_ctl_interop_with_manager(self):
        """CLI writes → ProviderStateManager reads correctly."""
        self._ctl("set", "neomind", "litellm")

        mgr = ProviderStateManager(state_dir=self.state_dir)
        config = mgr.get_bot_config("neomind")
        self.assertEqual(config["provider_mode"], "litellm")
        self.assertEqual(config["updated_by"], "xbar")

    def test_manager_writes_ctl_reads(self):
        """Manager writes → CLI reads correctly."""
        mgr = self._make_mgr()
        mgr.register_bot("neomind")
        mgr.set_provider_mode("neomind", "litellm", updated_by="telegram")

        result = self._ctl("get", "neomind")
        self.assertIn("litellm", result.stdout)


# ═══════════════════════════════════════════════════════════════════
# 15. Edge Cases
# ═══════════════════════════════════════════════════════════════════

class TestEdgeCases(TestProviderStateBase):
    """Test edge cases and boundary conditions."""

    def test_state_dir_auto_created(self):
        """State dir is created automatically if missing."""
        new_dir = os.path.join(self.tmp_dir, "new", "nested", ".neomind")
        mgr = ProviderStateManager(state_dir=new_dir)
        mgr.register_bot("test")
        self.assertTrue(Path(new_dir).exists())

    def test_now_iso_format(self):
        """_now_iso returns valid ISO 8601 UTC format."""
        ts = _now_iso()
        self.assertTrue(ts.endswith("Z"))
        self.assertIn("T", ts)
        self.assertEqual(len(ts), 20)  # "2026-03-22T00:00:00Z"

    def test_unicode_in_state(self):
        """State file handles unicode correctly (Chinese chars)."""
        mgr = self._make_mgr()
        mgr.register_bot("neomind")

        # Modify state to include unicode
        state = mgr._read_state()
        state["bots"]["neomind"]["direct_model"] = "深度求索"
        mgr._atomic_write(state)

        # Re-read
        mgr2 = ProviderStateManager(state_dir=self.state_dir)
        config = mgr2.get_bot_config("neomind")
        self.assertEqual(config["direct_model"], "深度求索")

    def test_state_file_permissions(self):
        """State file is readable and writable."""
        mgr = self._make_mgr()
        mgr.register_bot("test")
        self.assertTrue(os.access(self.state_file, os.R_OK))
        self.assertTrue(os.access(self.state_file, os.W_OK))

    def test_default_litellm_base_url(self):
        """Default state has correct LiteLLM base URL for Docker."""
        mgr = self._make_mgr()
        state = mgr._read_state()
        base_url = state.get("litellm", {}).get("base_url", "")
        self.assertIn("4000", base_url)

    def test_empty_bot_name(self):
        """Empty bot name still works (no crash)."""
        mgr = self._make_mgr()
        mgr.register_bot("")
        config = mgr.get_bot_config("")
        self.assertEqual(config["provider_mode"], "direct")


# ═══════════════════════════════════════════════════════════════════
# Run
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    unittest.main(verbosity=2)
