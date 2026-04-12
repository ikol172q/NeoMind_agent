"""
Comprehensive unit tests for 6 infrastructure modules:
  1. agent/services/feature_flags.py
  2. agent/services/frustration_detector.py
  3. agent/services/session_storage.py
  4. agent/evolution/auto_dream.py
  5. agent/prompts/composer.py
  6. agent/migrations/__init__.py
"""

import json
import os
import time
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Module 1: FeatureFlagService
# ---------------------------------------------------------------------------

class TestFeatureFlagService:
    """Tests for agent.services.feature_flags.FeatureFlagService."""

    def _make_service(self, tmp_path):
        from agent.services.feature_flags import FeatureFlagService
        config_path = str(tmp_path / "flags.json")
        return FeatureFlagService(config_path=config_path)

    def test_creation(self, tmp_path):
        svc = self._make_service(tmp_path)
        assert svc is not None
        assert isinstance(svc._runtime_overrides, dict)
        assert isinstance(svc._file_flags, dict)

    def test_is_enabled_auto_dream_default_true(self, tmp_path):
        svc = self._make_service(tmp_path)
        assert svc.is_enabled("AUTO_DREAM") is True

    def test_is_enabled_voice_input_default_false(self, tmp_path):
        svc = self._make_service(tmp_path)
        assert svc.is_enabled("VOICE_INPUT") is False

    def test_get_value_resolution_chain_default(self, tmp_path):
        """Default flags are returned when nothing else overrides."""
        svc = self._make_service(tmp_path)
        assert svc.get_value("AUTO_DREAM") is True
        assert svc.get_value("VOICE_INPUT") is False

    def test_get_value_resolution_chain_config_file(self, tmp_path):
        """Config file overrides default."""
        config_path = tmp_path / "flags.json"
        config_path.write_text(json.dumps({"VOICE_INPUT": True}))
        from agent.services.feature_flags import FeatureFlagService
        svc = FeatureFlagService(config_path=str(config_path))
        assert svc.get_value("VOICE_INPUT") is True

    def test_get_value_resolution_chain_runtime_over_config(self, tmp_path):
        """Runtime override beats config file."""
        config_path = tmp_path / "flags.json"
        config_path.write_text(json.dumps({"VOICE_INPUT": True}))
        from agent.services.feature_flags import FeatureFlagService
        svc = FeatureFlagService(config_path=str(config_path))
        svc.set_flag("VOICE_INPUT", False)
        assert svc.get_value("VOICE_INPUT") is False

    def test_get_value_resolution_chain_env_over_runtime(self, tmp_path, monkeypatch):
        """Environment variable beats runtime override."""
        svc = self._make_service(tmp_path)
        svc.set_flag("VOICE_INPUT", False)
        monkeypatch.setenv("NEOMIND_FLAG_VOICE_INPUT", "1")
        assert svc.get_value("VOICE_INPUT") is True

    def test_get_value_unknown_flag_returns_default_param(self, tmp_path):
        svc = self._make_service(tmp_path)
        assert svc.get_value("NONEXISTENT", default=42) == 42

    def test_set_flag_runtime_override(self, tmp_path):
        svc = self._make_service(tmp_path)
        svc.set_flag("AUTO_DREAM", False)
        assert svc.is_enabled("AUTO_DREAM") is False

    def test_set_flag_persist_writes_file(self, tmp_path):
        config_path = tmp_path / "flags.json"
        from agent.services.feature_flags import FeatureFlagService
        svc = FeatureFlagService(config_path=str(config_path))
        svc.set_flag("MY_FLAG", "hello", persist=True)
        assert config_path.exists()
        data = json.loads(config_path.read_text())
        assert data["MY_FLAG"] == "hello"

    def test_clear_override(self, tmp_path):
        svc = self._make_service(tmp_path)
        svc.set_flag("AUTO_DREAM", False)
        assert svc.is_enabled("AUTO_DREAM") is False
        svc.clear_override("AUTO_DREAM")
        # Falls back to default (True)
        assert svc.is_enabled("AUTO_DREAM") is True

    def test_list_flags_returns_all(self, tmp_path):
        svc = self._make_service(tmp_path)
        flags = svc.list_flags()
        assert "AUTO_DREAM" in flags
        assert "VOICE_INPUT" in flags
        entry = flags["AUTO_DREAM"]
        assert "enabled" in entry
        assert "value" in entry
        assert "source" in entry
        assert "description" in entry
        assert entry["source"] == "default"

    def test_list_flags_source_runtime(self, tmp_path):
        svc = self._make_service(tmp_path)
        svc.set_flag("AUTO_DREAM", False)
        flags = svc.list_flags()
        assert flags["AUTO_DREAM"]["source"] == "runtime"

    def test_env_override_is_enabled(self, tmp_path, monkeypatch):
        """NEOMIND_FLAG_TEST=1 makes is_enabled return True."""
        svc = self._make_service(tmp_path)
        monkeypatch.setenv("NEOMIND_FLAG_TEST", "1")
        assert svc.is_enabled("TEST") is True

    def test_env_override_false(self, tmp_path, monkeypatch):
        svc = self._make_service(tmp_path)
        monkeypatch.setenv("NEOMIND_FLAG_AUTO_DREAM", "0")
        assert svc.is_enabled("AUTO_DREAM") is False


# ---------------------------------------------------------------------------
# Module 2: Frustration Detector
# ---------------------------------------------------------------------------

class TestFrustrationDetector:
    """Tests for agent.services.frustration_detector."""

    def test_detect_english_correction_thats_wrong(self):
        from agent.services.frustration_detector import detect_frustration
        findings = detect_frustration("that's wrong, do it differently")
        assert len(findings) > 0
        severities = {f["severity"] for f in findings}
        assert "correction" in severities

    def test_detect_english_frustration_doesnt_work(self):
        from agent.services.frustration_detector import detect_frustration
        findings = detect_frustration("this doesn't work at all")
        assert len(findings) > 0
        severities = {f["severity"] for f in findings}
        assert "frustrated" in severities

    def test_detect_english_frustration_waste_of_time(self):
        from agent.services.frustration_detector import detect_frustration
        findings = detect_frustration("this is a waste of time")
        assert len(findings) > 0
        assert any(f["severity"] == "frustrated" for f in findings)

    def test_detect_english_repetition(self):
        from agent.services.frustration_detector import detect_frustration
        findings = detect_frustration("I already told you the answer")
        assert len(findings) > 0
        assert any(f["severity"] == "repetition" for f in findings)

    def test_detect_chinese_budui(self):
        from agent.services.frustration_detector import detect_frustration
        findings = detect_frustration("不对，重新来")
        assert len(findings) > 0
        assert any(f["severity"] == "correction" for f in findings)

    def test_detect_chinese_cuole(self):
        from agent.services.frustration_detector import detect_frustration
        findings = detect_frustration("你说错了")
        assert len(findings) > 0
        assert any(f["severity"] == "correction" for f in findings)

    def test_detect_chinese_meiyong(self):
        from agent.services.frustration_detector import detect_frustration
        findings = detect_frustration("这个没用")
        assert len(findings) > 0
        assert any(f["severity"] == "frustrated" for f in findings)

    def test_neutral_message_empty(self):
        from agent.services.frustration_detector import detect_frustration
        findings = detect_frustration("Please help me write a function")
        assert findings == []

    def test_empty_message(self):
        from agent.services.frustration_detector import detect_frustration
        assert detect_frustration("") == []

    def test_guidance_with_correction(self):
        from agent.services.frustration_detector import get_frustration_guidance
        findings = [{"category": "explicit_correction", "severity": "correction",
                     "signal": "User is correcting an error"}]
        guidance = get_frustration_guidance(findings)
        assert len(guidance) > 0
        assert "correction" in guidance.lower() or "correct" in guidance.lower()

    def test_guidance_with_frustration(self):
        from agent.services.frustration_detector import get_frustration_guidance
        findings = [{"category": "frustration", "severity": "frustrated",
                     "signal": "User is expressing frustration"}]
        guidance = get_frustration_guidance(findings)
        assert "frustrated" in guidance.lower() or "careful" in guidance.lower()

    def test_guidance_empty_findings(self):
        from agent.services.frustration_detector import get_frustration_guidance
        assert get_frustration_guidance([]) == ""


# ---------------------------------------------------------------------------
# Module 3: Session Storage
# ---------------------------------------------------------------------------

class TestSessionWriter:
    """Tests for agent.services.session_storage.SessionWriter."""

    def test_append_message_and_flush(self, tmp_path):
        from agent.services.session_storage import SessionWriter
        writer = SessionWriter(session_id="test01", sessions_dir=str(tmp_path))
        writer.append_message("user", "Hello world")
        writer.flush()
        filepath = Path(writer.filepath)
        assert filepath.exists()
        lines = filepath.read_text().strip().split("\n")
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["type"] == "message"
        assert entry["role"] == "user"
        assert entry["content"] == "Hello world"

    def test_uuid_deduplication(self, tmp_path):
        from agent.services.session_storage import SessionWriter
        writer = SessionWriter(session_id="test02", sessions_dir=str(tmp_path))
        writer.append_message("user", "msg1", msg_uuid="dup-uuid")
        writer.append_message("user", "msg2", msg_uuid="dup-uuid")
        writer.flush()
        lines = Path(writer.filepath).read_text().strip().split("\n")
        assert len(lines) == 1  # Second was deduplicated

    def test_append_metadata(self, tmp_path):
        from agent.services.session_storage import SessionWriter
        writer = SessionWriter(session_id="test03", sessions_dir=str(tmp_path))
        writer.append_metadata("title", "Test Session")
        writer.flush()
        lines = Path(writer.filepath).read_text().strip().split("\n")
        entry = json.loads(lines[0])
        assert entry["type"] == "metadata"
        assert entry["key"] == "title"
        assert entry["value"] == "Test Session"


class TestSessionReader:
    """Tests for agent.services.session_storage.SessionReader."""

    def _create_session_file(self, tmp_path, session_id, entries):
        filepath = tmp_path / f"{session_id}.jsonl"
        with open(filepath, "w") as f:
            for entry in entries:
                f.write(json.dumps(entry) + "\n")
        return filepath

    def test_list_sessions_lite(self, tmp_path):
        from agent.services.session_storage import SessionReader
        self._create_session_file(tmp_path, "sess1", [
            {"type": "message", "role": "user", "content": "Hello",
             "timestamp": time.time(), "uuid": "u1"},
            {"type": "metadata", "key": "title", "value": "My Session",
             "timestamp": time.time()},
        ])
        reader = SessionReader(sessions_dir=str(tmp_path))
        sessions = reader.list_sessions_lite()
        assert len(sessions) >= 1
        s = sessions[0]
        assert s["session_id"] == "sess1"
        assert "title" in s
        assert s["title"] == "My Session"

    def test_load_full(self, tmp_path):
        from agent.services.session_storage import SessionReader
        self._create_session_file(tmp_path, "sess2", [
            {"type": "message", "role": "user", "content": "Hi",
             "timestamp": time.time(), "uuid": "u1"},
            {"type": "message", "role": "assistant", "content": "Hello!",
             "timestamp": time.time(), "uuid": "u2"},
            {"type": "metadata", "key": "mode", "value": "chat",
             "timestamp": time.time()},
        ])
        reader = SessionReader(sessions_dir=str(tmp_path))
        messages, metadata = reader.load_full("sess2")
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[1]["role"] == "assistant"
        assert metadata["mode"] == "chat"

    def test_detect_interrupt_last_user(self, tmp_path):
        from agent.services.session_storage import SessionReader
        reader = SessionReader(sessions_dir=str(tmp_path))
        messages = [
            {"role": "user", "content": "Do something"},
        ]
        assert reader.detect_interrupt(messages) is True

    def test_detect_interrupt_last_assistant(self, tmp_path):
        from agent.services.session_storage import SessionReader
        reader = SessionReader(sessions_dir=str(tmp_path))
        messages = [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello!"},
        ]
        assert reader.detect_interrupt(messages) is False

    def test_detect_interrupt_empty(self, tmp_path):
        from agent.services.session_storage import SessionReader
        reader = SessionReader(sessions_dir=str(tmp_path))
        assert reader.detect_interrupt([]) is False

    def test_detect_interrupt_tool_use_incomplete(self, tmp_path):
        from agent.services.session_storage import SessionReader
        reader = SessionReader(sessions_dir=str(tmp_path))
        messages = [
            {"role": "user", "content": "Read file"},
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "t1", "name": "Read", "input": {}}
            ]},
        ]
        assert reader.detect_interrupt(messages) is True


class TestSubagentSidechain:
    """Tests for agent.services.session_storage.SubagentSidechain."""

    def test_append_and_load_roundtrip(self, tmp_path):
        from agent.services.session_storage import SubagentSidechain
        sc = SubagentSidechain(
            session_id="main_sess",
            agent_id="worker1",
            sessions_dir=str(tmp_path),
        )
        sc.append("user", "Task: summarize")
        sc.append("assistant", "Here is the summary.")
        sc.flush()

        messages = sc.load()
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "Task: summarize"
        assert messages[1]["role"] == "assistant"
        assert messages[1]["content"] == "Here is the summary."


# ---------------------------------------------------------------------------
# Module 4: AutoDream
# ---------------------------------------------------------------------------

class TestAutoDream:
    """Tests for agent.evolution.auto_dream.AutoDream."""

    def _make_dream(self, tmp_path):
        from agent.evolution.auto_dream import AutoDream
        with patch.object(AutoDream, '_load_state'):
            dream = AutoDream()
            dream._state_path = tmp_path / "dream_state.json"
            dream._last_consolidation_time = 0.0
            dream._consolidated_count = 0
            dream._turns_since_last = 0
            dream._last_activity_time = time.time()
            dream._running = False
            dream._dream_journal = []
        return dream

    def test_creation(self, tmp_path):
        dream = self._make_dream(tmp_path)
        assert dream is not None
        assert dream._turns_since_last == 0

    def test_on_turn_complete_increments(self, tmp_path):
        dream = self._make_dream(tmp_path)
        assert dream._turns_since_last == 0
        dream.on_turn_complete()
        assert dream._turns_since_last == 1
        dream.on_turn_complete()
        assert dream._turns_since_last == 2

    def test_check_gates_closed_initially(self, tmp_path):
        """Gates should be closed because turns < MIN_TURNS_SINCE_LAST
        and idle time < IDLE_THRESHOLD_SECONDS."""
        dream = self._make_dream(tmp_path)
        # _last_consolidation_time=0 means time gate passes, but
        # turns gate (0 < 10) should fail
        assert dream._check_gates() is False

    def test_check_gates_all_open(self, tmp_path):
        dream = self._make_dream(tmp_path)
        dream._last_consolidation_time = 0.0  # Long ago
        dream._turns_since_last = 100  # Plenty of turns
        dream._last_activity_time = time.time() - 120  # Idle for 2 min
        assert dream._check_gates() is True

    def test_status_property(self, tmp_path):
        dream = self._make_dream(tmp_path)
        status = dream.status
        assert "running" in status
        assert "last_consolidation" in status
        assert "turns_since_last" in status
        assert "total_consolidated" in status
        assert "gates_open" in status
        assert "journal_entries" in status
        assert status["running"] is False

    def test_phase_extract_preferences(self, tmp_path):
        dream = self._make_dream(tmp_path)
        history = [
            {"role": "user", "content": "remember that I prefer Python 3.12"},
            {"role": "assistant", "content": "Noted!"},
        ]
        extracted = dream._phase_extract(history)
        assert len(extracted) > 0
        assert any(e["type"] == "preference" for e in extracted)

    def test_phase_extract_corrections(self, tmp_path):
        dream = self._make_dream(tmp_path)
        history = [
            {"role": "user", "content": "that's wrong, the file is main.py"},
        ]
        extracted = dream._phase_extract(history)
        assert len(extracted) > 0
        assert any(e["type"] == "correction" for e in extracted)

    def test_phase_extract_no_match(self, tmp_path):
        dream = self._make_dream(tmp_path)
        history = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        extracted = dream._phase_extract(history)
        assert extracted == []

    def test_phase_deduplicate_removes_known(self, tmp_path):
        dream = self._make_dream(tmp_path)
        dream._shared_memory = None  # No shared memory to check
        items = [
            {"type": "preference", "content": "I prefer dark mode", "source": "user"},
            {"type": "preference", "content": "I prefer dark mode", "source": "user"},
            {"type": "correction", "content": "Use tabs not spaces", "source": "user"},
        ]
        unique = dream._phase_deduplicate(items)
        # Should remove the duplicate
        assert len(unique) == 2

    def test_phase_synthesize_groups_by_type(self, tmp_path):
        dream = self._make_dream(tmp_path)
        items = [
            {"type": "preference", "content": "pref1", "source": "u"},
            {"type": "preference", "content": "pref2", "source": "u"},
            {"type": "correction", "content": "corr1", "source": "u"},
        ]
        synthesized = dream._phase_synthesize(items)
        types = {s["type"] for s in synthesized}
        assert "preference" in types
        assert "correction" in types

    def test_phase_synthesize_merges_large_groups(self, tmp_path):
        dream = self._make_dream(tmp_path)
        items = [
            {"type": "pattern", "content": f"file{i}", "source": "tool"}
            for i in range(5)
        ]
        synthesized = dream._phase_synthesize(items)
        # 5 items of same type (>3) should be merged into 1 consolidated entry
        assert len(synthesized) == 1
        assert "[Consolidated" in synthesized[0]["content"]


# ---------------------------------------------------------------------------
# Module 5: PromptComposer
# ---------------------------------------------------------------------------

class TestPromptComposer:
    """Tests for agent.prompts.composer.PromptComposer."""

    def test_creation(self):
        from agent.prompts.composer import PromptComposer
        composer = PromptComposer()
        assert composer is not None
        assert composer._sections == {}

    def test_set_base_prompt_priority_10(self):
        from agent.prompts.composer import PromptComposer
        composer = PromptComposer()
        composer.set_base_prompt("You are NeoMind.")
        assert "base" in composer._sections
        assert composer._sections["base"].priority == 10

    def test_build_contains_base_content(self):
        from agent.prompts.composer import PromptComposer
        composer = PromptComposer()
        composer.set_base_prompt("You are NeoMind, an AI assistant.")
        output = composer.build()
        assert "You are NeoMind, an AI assistant." in output

    def test_build_contains_dynamic_boundary(self):
        from agent.prompts.composer import PromptComposer, DYNAMIC_BOUNDARY
        composer = PromptComposer()
        composer.set_base_prompt("Base prompt")
        output = composer.build()
        assert "SYSTEM_PROMPT_DYNAMIC_BOUNDARY" in output

    def test_override_takes_precedence(self):
        from agent.prompts.composer import PromptComposer
        composer = PromptComposer()
        composer.set_base_prompt("Base prompt text")
        composer.set_override_prompt("Override prompt text")
        output = composer.build()
        assert "Override prompt text" in output
        assert "Base prompt text" not in output

    def test_append_prompt_always_appended(self):
        from agent.prompts.composer import PromptComposer
        composer = PromptComposer()
        composer.set_override_prompt("Override here")
        composer.set_append_prompt("Always appended text")
        output = composer.build()
        assert "Override here" in output
        assert "Always appended text" in output

    def test_append_prompt_with_sections(self):
        from agent.prompts.composer import PromptComposer
        composer = PromptComposer()
        composer.set_base_prompt("Base")
        composer.set_append_prompt("Appended")
        output = composer.build()
        assert "Base" in output
        assert "Appended" in output

    def test_get_token_accounting_has_total(self):
        from agent.prompts.composer import PromptComposer
        composer = PromptComposer()
        composer.set_base_prompt("Some base prompt content here")
        accounting = composer.get_token_accounting()
        assert isinstance(accounting, list)
        assert len(accounting) >= 1
        names = [e["name"] for e in accounting]
        assert "TOTAL" in names
        total_entry = [e for e in accounting if e["name"] == "TOTAL"][0]
        assert total_entry["tokens"] > 0

    def test_format_token_accounting_string(self):
        from agent.prompts.composer import PromptComposer
        composer = PromptComposer()
        composer.set_base_prompt("Some content")
        formatted = composer.format_token_accounting()
        assert isinstance(formatted, str)
        assert "TOTAL" in formatted
        assert "tokens" in formatted

    def test_collect_system_context_returns_3_tuple(self):
        from agent.prompts.composer import collect_system_context
        result = collect_system_context()
        assert isinstance(result, tuple)
        assert len(result) == 3
        git_status, os_info, date_str = result
        assert isinstance(git_status, str)
        assert isinstance(os_info, str)
        assert isinstance(date_str, str)
        # date_str should look like YYYY-MM-DD
        assert len(date_str) == 10
        assert date_str[4] == "-"

    def test_priority_chain_coordinator_over_agent(self):
        from agent.prompts.composer import PromptComposer
        composer = PromptComposer()
        composer.set_base_prompt("Base")
        composer.set_agent_prompt("Agent prompt")
        composer.set_coordinator_prompt("Coordinator prompt")
        output = composer.build()
        assert "Coordinator prompt" in output
        assert "Agent prompt" not in output

    def test_custom_prompt_over_sections(self):
        from agent.prompts.composer import PromptComposer
        composer = PromptComposer()
        composer.set_base_prompt("Base")
        composer.set_custom_prompt("Custom prompt text")
        output = composer.build()
        assert "Custom prompt text" in output
        # base is only used if no custom/agent/coordinator/override is set
        assert "<!-- section: base -->" not in output


# ---------------------------------------------------------------------------
# Module 6: Migrations
# ---------------------------------------------------------------------------

class TestMigrations:
    """Tests for agent.migrations."""

    def test_migration_runner_creation(self, tmp_path, monkeypatch):
        from agent.migrations import MigrationRunner, MIGRATION_STATE_PATH
        # Point state path to tmp
        monkeypatch.setattr(
            "agent.migrations.MIGRATION_STATE_PATH",
            tmp_path / "migration_state.json",
        )
        runner = MigrationRunner()
        assert runner is not None
        assert isinstance(runner._applied, list)

    def test_run_pending_in_order(self, tmp_path, monkeypatch):
        """Verify migrations run in order."""
        state_path = tmp_path / "migration_state.json"
        monkeypatch.setattr("agent.migrations.MIGRATION_STATE_PATH", state_path)

        execution_order = []

        def make_fn(name):
            def fn():
                execution_order.append(name)
            return fn

        test_migrations = [
            ("m_001", make_fn("m_001")),
            ("m_002", make_fn("m_002")),
            ("m_003", make_fn("m_003")),
        ]
        monkeypatch.setattr("agent.migrations.MIGRATIONS", test_migrations)

        from agent.migrations import MigrationRunner
        runner = MigrationRunner()
        runner.run_pending()

        assert execution_order == ["m_001", "m_002", "m_003"]
        # Verify state file records all as applied
        data = json.loads(state_path.read_text())
        assert data["applied"] == ["m_001", "m_002", "m_003"]

    def test_run_pending_skips_already_applied(self, tmp_path, monkeypatch):
        """Already applied migrations are not re-run."""
        state_path = tmp_path / "migration_state.json"
        state_path.write_text(json.dumps({"applied": ["m_001", "m_002"]}))
        monkeypatch.setattr("agent.migrations.MIGRATION_STATE_PATH", state_path)

        execution_order = []

        def make_fn(name):
            def fn():
                execution_order.append(name)
            return fn

        test_migrations = [
            ("m_001", make_fn("m_001")),
            ("m_002", make_fn("m_002")),
            ("m_003", make_fn("m_003")),
        ]
        monkeypatch.setattr("agent.migrations.MIGRATIONS", test_migrations)

        from agent.migrations import MigrationRunner
        runner = MigrationRunner()
        runner.run_pending()

        # Only m_003 should run
        assert execution_order == ["m_003"]

    def test_migrations_list_has_at_least_7(self):
        from agent.migrations import MIGRATIONS
        assert len(MIGRATIONS) >= 7

    def test_each_migration_is_callable(self):
        from agent.migrations import MIGRATIONS
        for name, fn in MIGRATIONS:
            assert callable(fn), f"Migration {name} is not callable"
            assert isinstance(name, str), f"Migration name should be str, got {type(name)}"
