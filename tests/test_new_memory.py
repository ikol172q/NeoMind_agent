"""
Comprehensive unit tests for 4 memory modules:
  - agent/memory/memory_selector.py
  - agent/memory/memory_taxonomy.py
  - agent/memory/agent_memory.py
  - agent/services/session_notes.py
"""

import hashlib
import json
import os
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
import pytest

from agent.memory.memory_selector import MemorySelector, MAX_SELECTIONS
from agent.memory.memory_taxonomy import MEMORY_TYPES, build_taxonomy_prompt
from agent.memory.agent_memory import AgentMemory
from agent.services.session_notes import SessionNotes, SECTION_TEMPLATE


# ═══════════════════════════════════════════════════════════════════
# Module 1: MemorySelector
# ═══════════════════════════════════════════════════════════════════


class TestMemorySelectorCreation:
    def test_create_without_llm(self):
        sel = MemorySelector()
        assert sel._llm_fn is None
        assert sel._max_selections == MAX_SELECTIONS
        assert sel._cache == {}

    def test_create_with_llm(self):
        fn = lambda prompt: "0,1"
        sel = MemorySelector(llm_fn=fn)
        assert sel._llm_fn is fn

    def test_create_custom_max(self):
        sel = MemorySelector(max_selections=3)
        assert sel._max_selections == 3


class TestMemorySelectorSelect:
    def _make_memories(self, n):
        return [{"fact": f"memory_{i}", "category": "user"} for i in range(n)]

    def test_empty_memories(self):
        sel = MemorySelector()
        assert sel.select(query="hello", memories=[]) == []

    def test_few_memories_returns_all(self):
        sel = MemorySelector()
        mems = self._make_memories(3)
        result = sel.select(query="test", memories=mems)
        assert len(result) == 3
        assert result == mems

    def test_exactly_max_returns_all(self):
        sel = MemorySelector(max_selections=5)
        mems = self._make_memories(5)
        result = sel.select(query="test", memories=mems)
        assert len(result) == 5

    def test_more_than_max_returns_at_most_max(self):
        sel = MemorySelector(max_selections=5)
        mems = self._make_memories(10)
        result = sel.select(query="test", memories=mems)
        assert len(result) <= 5

    def test_already_surfaced_filters_out(self):
        sel = MemorySelector()
        mems = self._make_memories(3)
        surfaced_id = MemorySelector._memory_id(mems[0])
        result = sel.select(query="test", memories=mems, already_surfaced={surfaced_id})
        assert len(result) == 2
        assert mems[0] not in result

    def test_all_surfaced_returns_empty(self):
        sel = MemorySelector()
        mems = self._make_memories(2)
        ids = {MemorySelector._memory_id(m) for m in mems}
        result = sel.select(query="test", memories=mems, already_surfaced=ids)
        assert result == []

    def test_caching_same_query(self):
        sel = MemorySelector(max_selections=2)
        mems = self._make_memories(6)
        r1 = sel.select(query="fix bug", memories=mems)
        r2 = sel.select(query="fix bug", memories=mems)
        assert r1 == r2
        assert len(sel._cache) == 1

    def test_caching_different_queries(self):
        sel = MemorySelector(max_selections=2)
        mems = self._make_memories(6)
        sel.select(query="fix bug", memories=mems)
        sel.select(query="add feature", memories=mems)
        assert len(sel._cache) == 2


class TestMemorySelectorRecencyFallback:
    def test_select_by_recency_no_llm(self):
        sel = MemorySelector(max_selections=2)
        mems = [
            {"fact": "old", "created_at": "2024-01-01T00:00:00Z"},
            {"fact": "new", "created_at": "2025-06-01T00:00:00Z"},
            {"fact": "mid", "created_at": "2024-06-01T00:00:00Z"},
        ]
        result = sel._select_by_recency(mems)
        assert len(result) == 2
        # Most recent first
        assert result[0]["fact"] == "new"
        assert result[1]["fact"] == "mid"

    def test_select_by_recency_no_timestamps(self):
        sel = MemorySelector(max_selections=2)
        mems = [{"fact": "a"}, {"fact": "b"}, {"fact": "c"}]
        result = sel._select_by_recency(mems)
        assert len(result) == 2


class TestMemorySelectorStaleness:
    def test_staleness_1_day(self):
        sel = MemorySelector()
        ts = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        mems = [{"fact": "x", "updated_at": ts}]
        result = sel.add_staleness_warnings(mems)
        assert result[0]["_staleness_caveat"] == "This memory is 1 day old"

    def test_staleness_3_days(self):
        sel = MemorySelector()
        ts = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
        mems = [{"fact": "x", "updated_at": ts}]
        result = sel.add_staleness_warnings(mems)
        assert "3 days old" in result[0]["_staleness_caveat"]

    def test_staleness_7_days(self):
        sel = MemorySelector()
        ts = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        mems = [{"fact": "x", "updated_at": ts}]
        result = sel.add_staleness_warnings(mems)
        assert "1 week old" in result[0]["_staleness_caveat"]
        assert "verify" in result[0]["_staleness_caveat"]

    def test_staleness_14_days(self):
        sel = MemorySelector()
        ts = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
        mems = [{"fact": "x", "updated_at": ts}]
        result = sel.add_staleness_warnings(mems)
        assert "2 weeks old" in result[0]["_staleness_caveat"]

    def test_staleness_30_days(self):
        sel = MemorySelector()
        ts = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        mems = [{"fact": "x", "updated_at": ts}]
        result = sel.add_staleness_warnings(mems)
        assert "1 month" in result[0]["_staleness_caveat"]
        assert "outdated" in result[0]["_staleness_caveat"]

    def test_staleness_60_days(self):
        sel = MemorySelector()
        ts = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
        mems = [{"fact": "x", "updated_at": ts}]
        result = sel.add_staleness_warnings(mems)
        assert "2 months" in result[0]["_staleness_caveat"]

    def test_staleness_fresh_no_caveat(self):
        sel = MemorySelector()
        ts = datetime.now(timezone.utc).isoformat()
        mems = [{"fact": "x", "updated_at": ts}]
        result = sel.add_staleness_warnings(mems)
        assert "_staleness_caveat" not in result[0]

    def test_staleness_no_timestamp(self):
        sel = MemorySelector()
        mems = [{"fact": "x"}]
        result = sel.add_staleness_warnings(mems)
        assert "_staleness_caveat" not in result[0]


class TestMemoryId:
    def test_same_content_same_id(self):
        m1 = {"fact": "hello world"}
        m2 = {"fact": "hello world"}
        assert MemorySelector._memory_id(m1) == MemorySelector._memory_id(m2)

    def test_different_content_different_id(self):
        m1 = {"fact": "hello"}
        m2 = {"fact": "world"}
        assert MemorySelector._memory_id(m1) != MemorySelector._memory_id(m2)

    def test_uses_content_fallback(self):
        m = {"content": "some content"}
        mid = MemorySelector._memory_id(m)
        expected = hashlib.md5("some content".encode()).hexdigest()[:12]
        assert mid == expected

    def test_id_length(self):
        m = {"fact": "anything"}
        mid = MemorySelector._memory_id(m)
        assert len(mid) == 12


# ═══════════════════════════════════════════════════════════════════
# Module 2: MemoryTaxonomy
# ═══════════════════════════════════════════════════════════════════


class TestMemoryTypes:
    def test_four_types_exist(self):
        assert len(MEMORY_TYPES) == 4

    def test_type_names(self):
        names = [t["name"] for t in MEMORY_TYPES]
        assert "user" in names
        assert "feedback" in names
        assert "project" in names
        assert "reference" in names

    @pytest.mark.parametrize("field", [
        "name", "description", "when_to_save", "how_to_use",
        "body_structure", "scope", "examples",
    ])
    def test_each_type_has_required_fields(self, field):
        for mt in MEMORY_TYPES:
            assert field in mt, f"Type '{mt.get('name', '?')}' missing field '{field}'"

    def test_examples_are_lists(self):
        for mt in MEMORY_TYPES:
            assert isinstance(mt["examples"], list)
            assert len(mt["examples"]) > 0


class TestBuildTaxonomyPrompt:
    def test_contains_all_type_names(self):
        prompt = build_taxonomy_prompt()
        assert "USER" in prompt
        assert "FEEDBACK" in prompt
        assert "PROJECT" in prompt
        assert "REFERENCE" in prompt

    def test_contains_do_not_save(self):
        prompt = build_taxonomy_prompt()
        assert "Do NOT save" in prompt

    def test_contains_memory_types_header(self):
        prompt = build_taxonomy_prompt()
        assert "## Memory Types" in prompt

    def test_contains_descriptions(self):
        prompt = build_taxonomy_prompt()
        for mt in MEMORY_TYPES:
            assert mt["description"] in prompt

    def test_contains_examples(self):
        prompt = build_taxonomy_prompt()
        for mt in MEMORY_TYPES:
            for ex in mt["examples"]:
                assert ex in prompt


# ═══════════════════════════════════════════════════════════════════
# Module 3: AgentMemory
# ═══════════════════════════════════════════════════════════════════


class TestAgentMemoryCreation:
    def test_creation_with_agent_type(self, tmp_path):
        mem = AgentMemory(agent_type="researcher", project_dir=str(tmp_path))
        assert mem.agent_type == "researcher"

    def test_three_scopes_different_paths(self, tmp_path):
        mem = AgentMemory(agent_type="researcher", project_dir=str(tmp_path))
        paths = {str(mem._user_dir), str(mem._project_dir_path), str(mem._local_dir)}
        assert len(paths) == 3, "All three scope directories must be different"

    def test_user_dir_in_home(self, tmp_path):
        mem = AgentMemory(agent_type="researcher", project_dir=str(tmp_path))
        assert ".neomind/agent-memory/researcher" in str(mem._user_dir)

    def test_project_dir_in_project(self, tmp_path):
        mem = AgentMemory(agent_type="researcher", project_dir=str(tmp_path))
        assert str(tmp_path) in str(mem._project_dir_path)
        assert "agent-memory" in str(mem._project_dir_path)

    def test_local_dir_in_project(self, tmp_path):
        mem = AgentMemory(agent_type="researcher", project_dir=str(tmp_path))
        assert str(tmp_path) in str(mem._local_dir)
        assert "agent-memory-local" in str(mem._local_dir)


class TestAgentMemoryWriteRead:
    def test_write_then_read(self, tmp_path):
        mem = AgentMemory(agent_type="tester", project_dir=str(tmp_path))
        mem.write("notes.md", "# Test Notes\nHello", scope="project")
        content = mem.read("notes.md", scope="project")
        assert content == "# Test Notes\nHello"

    def test_read_nonexistent_returns_none(self, tmp_path):
        mem = AgentMemory(agent_type="tester", project_dir=str(tmp_path))
        assert mem.read("nonexistent.md", scope="project") is None

    def test_read_no_scope_searches_all(self, tmp_path):
        mem = AgentMemory(agent_type="tester", project_dir=str(tmp_path))
        mem.write("shared.md", "found it", scope="project")
        content = mem.read("shared.md")  # no scope
        assert content == "found it"

    def test_read_no_scope_prefers_local(self, tmp_path):
        mem = AgentMemory(agent_type="tester", project_dir=str(tmp_path))
        mem.write("pref.md", "from project", scope="project")
        mem.write("pref.md", "from local", scope="local")
        content = mem.read("pref.md")
        assert content == "from local"

    def test_write_different_scopes(self, tmp_path):
        mem = AgentMemory(agent_type="tester", project_dir=str(tmp_path))
        mem.write("data.md", "project data", scope="project")
        mem.write("data.md", "local data", scope="local")
        assert mem.read("data.md", scope="project") == "project data"
        assert mem.read("data.md", scope="local") == "local data"


class TestAgentMemoryListFiles:
    def test_list_empty(self, tmp_path):
        mem = AgentMemory(agent_type="tester", project_dir=str(tmp_path))
        # Ensure dirs exist but are empty
        files = mem.list_files()
        assert files == []

    def test_list_files_across_scopes(self, tmp_path):
        mem = AgentMemory(agent_type="tester", project_dir=str(tmp_path))
        mem.write("a.md", "aaa", scope="project")
        mem.write("b.md", "bbb", scope="local")
        files = mem.list_files()
        names = {f["name"] for f in files}
        assert "a.md" in names
        assert "b.md" in names
        assert len(files) == 2

    def test_list_single_scope(self, tmp_path):
        mem = AgentMemory(agent_type="tester", project_dir=str(tmp_path))
        mem.write("a.md", "aaa", scope="project")
        mem.write("b.md", "bbb", scope="local")
        files = mem.list_files(scope="project")
        assert len(files) == 1
        assert files[0]["name"] == "a.md"
        assert files[0]["scope"] == "project"

    def test_list_files_only_md(self, tmp_path):
        mem = AgentMemory(agent_type="tester", project_dir=str(tmp_path))
        mem.write("notes.md", "hello", scope="project")
        # Write a non-md file directly
        d = mem._ensure_dir("project")
        (d / "data.json").write_text("{}")
        files = mem.list_files(scope="project")
        names = [f["name"] for f in files]
        assert "notes.md" in names
        assert "data.json" not in names

    def test_list_files_has_metadata(self, tmp_path):
        mem = AgentMemory(agent_type="tester", project_dir=str(tmp_path))
        mem.write("info.md", "content here", scope="project")
        files = mem.list_files(scope="project")
        f = files[0]
        assert "name" in f
        assert "scope" in f
        assert "path" in f
        assert "size" in f
        assert "mtime" in f
        assert f["size"] > 0


class TestAgentMemoryDelete:
    def test_delete_file(self, tmp_path):
        mem = AgentMemory(agent_type="tester", project_dir=str(tmp_path))
        mem.write("doomed.md", "bye", scope="project")
        assert mem.read("doomed.md", scope="project") is not None
        mem.delete("doomed.md", scope="project")
        assert mem.read("doomed.md", scope="project") is None

    def test_delete_nonexistent_no_error(self, tmp_path):
        mem = AgentMemory(agent_type="tester", project_dir=str(tmp_path))
        mem.delete("nope.md", scope="project")  # should not raise


class TestAgentMemoryContextInjection:
    def test_context_injection_empty(self, tmp_path):
        mem = AgentMemory(agent_type="tester", project_dir=str(tmp_path))
        assert mem.get_context_injection() == ""

    def test_context_injection_with_files(self, tmp_path):
        mem = AgentMemory(agent_type="tester", project_dir=str(tmp_path))
        mem.write("notes.md", "important stuff", scope="project")
        ctx = mem.get_context_injection()
        assert "Agent Memory" in ctx
        assert "tester" in ctx
        assert "important stuff" in ctx
        assert "notes.md" in ctx


class TestAgentMemorySnapshot:
    def test_snapshot_roundtrip(self, tmp_path):
        mem = AgentMemory(agent_type="tester", project_dir=str(tmp_path))
        mem.write("alpha.md", "alpha content", scope="project")
        mem.write("beta.md", "beta content", scope="project")

        snap_dir = str(tmp_path / "snapshots")
        snap_path = mem.create_snapshot(snapshot_dir=snap_dir)
        assert Path(snap_path).exists()

        # Verify snapshot metadata
        meta_path = Path(snap_path) / ".snapshot-synced.json"
        assert meta_path.exists()
        meta = json.loads(meta_path.read_text())
        assert meta["agent_type"] == "tester"
        assert meta["file_count"] == 2

        # Create a new empty agent memory and restore
        mem2 = AgentMemory(agent_type="tester", project_dir=str(tmp_path / "new_project"))
        mem2.restore_snapshot(snap_path)

        files = mem2.list_files(scope="project")
        names = {f["name"] for f in files}
        assert "alpha.md" in names
        assert "beta.md" in names
        assert mem2.read("alpha.md", scope="project") == "alpha content"

    def test_restore_skips_if_not_empty(self, tmp_path):
        mem = AgentMemory(agent_type="tester", project_dir=str(tmp_path))
        mem.write("existing.md", "already here", scope="project")

        snap_dir = str(tmp_path / "snap")
        mem.create_snapshot(snapshot_dir=snap_dir)

        # Try restoring into same (non-empty) memory
        mem.restore_snapshot(snap_dir)
        # Should not duplicate; original still intact
        files = mem.list_files(scope="project")
        assert len(files) == 1

    def test_restore_nonexistent_dir(self, tmp_path):
        mem = AgentMemory(agent_type="tester", project_dir=str(tmp_path))
        mem.restore_snapshot("/tmp/nonexistent_snap_dir_12345")  # should not raise


# ═══════════════════════════════════════════════════════════════════
# Module 4: SessionNotes
# ═══════════════════════════════════════════════════════════════════


class TestSessionNotesCreation:
    def test_creation_defaults(self):
        notes = SessionNotes(session_id="test123")
        assert notes._session_id == "test123"
        assert notes._initialized is False
        assert notes._content == ""

    def test_creation_auto_session_id(self):
        notes = SessionNotes()
        assert notes._session_id  # not empty

    def test_creation_custom_thresholds(self):
        notes = SessionNotes(
            session_id="t1",
            update_tool_threshold=10,
            update_token_threshold=5000,
            init_token_threshold=2000,
        )
        assert notes._update_tool_threshold == 10
        assert notes._update_token_threshold == 5000
        assert notes._init_token_threshold == 2000


class TestSessionNotesMaybeUpdate:
    def test_no_update_before_init_threshold(self):
        notes = SessionNotes(session_id="t1", init_token_threshold=15000)
        messages = [{"role": "user", "content": "hello"}]
        result = notes.maybe_update(messages, tool_count=0, est_tokens=5000)
        assert result is False
        assert notes._initialized is False

    def test_triggers_at_init_threshold(self, tmp_path):
        notes = SessionNotes(session_id="t1", init_token_threshold=10000)
        # Override notes dir to tmp
        notes._notes_dir = tmp_path
        notes._notes_path = tmp_path / "t1.md"
        messages = [{"role": "user", "content": "build a widget"}]
        result = notes.maybe_update(messages, tool_count=0, est_tokens=10000)
        assert result is True
        assert notes._initialized is True

    def test_no_update_between_thresholds(self, tmp_path):
        notes = SessionNotes(
            session_id="t2",
            init_token_threshold=1000,
            update_tool_threshold=25,
            update_token_threshold=30000,
        )
        notes._notes_dir = tmp_path
        notes._notes_path = tmp_path / "t2.md"
        messages = [{"role": "user", "content": "hi"}]
        # Initialize
        notes.maybe_update(messages, tool_count=0, est_tokens=1000)
        assert notes._initialized is True
        # Subsequent call below thresholds
        result = notes.maybe_update(messages, tool_count=5, est_tokens=5000)
        assert result is False

    def test_triggers_on_tool_threshold(self, tmp_path):
        notes = SessionNotes(
            session_id="t3",
            init_token_threshold=100,
            update_tool_threshold=10,
            update_token_threshold=99999,
        )
        notes._notes_dir = tmp_path
        notes._notes_path = tmp_path / "t3.md"
        messages = [{"role": "user", "content": "work"}]
        notes.maybe_update(messages, tool_count=0, est_tokens=100)
        result = notes.maybe_update(messages, tool_count=10, est_tokens=200)
        assert result is True

    def test_triggers_on_token_threshold(self, tmp_path):
        notes = SessionNotes(
            session_id="t4",
            init_token_threshold=100,
            update_tool_threshold=99999,
            update_token_threshold=500,
        )
        notes._notes_dir = tmp_path
        notes._notes_path = tmp_path / "t4.md"
        messages = [{"role": "user", "content": "work"}]
        notes.maybe_update(messages, tool_count=0, est_tokens=100)
        result = notes.maybe_update(messages, tool_count=0, est_tokens=700)
        assert result is True


class TestSessionNotesHeuristic:
    def test_extract_with_tool_use_blocks(self, tmp_path):
        notes = SessionNotes(session_id="h1", init_token_threshold=1)
        notes._notes_dir = tmp_path
        notes._notes_path = tmp_path / "h1.md"
        messages = [
            {"role": "user", "content": "Fix the login page"},
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "name": "Read",
                        "input": {"file_path": "/src/login.py"},
                    },
                    {
                        "type": "tool_use",
                        "name": "Edit",
                        "input": {"file_path": "/src/auth.py"},
                    },
                    {
                        "type": "tool_use",
                        "name": "Bash",
                        "input": {"command": "pytest tests/"},
                    },
                ],
            },
        ]
        notes.maybe_update(messages, tool_count=0, est_tokens=1)
        content = notes._content
        assert "Fix the login page" in content
        assert "/src/login.py" in content
        assert "/src/auth.py" in content
        assert "pytest tests/" in content

    def test_extract_with_tool_result_error(self, tmp_path):
        notes = SessionNotes(session_id="h2", init_token_threshold=1)
        notes._notes_dir = tmp_path
        notes._notes_path = tmp_path / "h2.md"
        messages = [
            {"role": "user", "content": "Run tests"},
            {
                "role": "tool",
                "content": [
                    {
                        "type": "tool_result",
                        "is_error": True,
                        "content": "FileNotFoundError: missing.py",
                    },
                ],
            },
        ]
        notes.maybe_update(messages, tool_count=0, est_tokens=1)
        assert "FileNotFoundError" in notes._content

    def test_extract_with_text_blocks(self, tmp_path):
        notes = SessionNotes(session_id="h3", init_token_threshold=1)
        notes._notes_dir = tmp_path
        notes._notes_path = tmp_path / "h3.md"
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Please refactor the API"},
                ],
            },
        ]
        notes.maybe_update(messages, tool_count=0, est_tokens=1)
        assert "refactor the API" in notes._content


class TestSessionNotesContextInjection:
    def test_empty_context(self):
        notes = SessionNotes(session_id="ci1")
        assert notes.get_context_injection() == ""

    def test_populated_context(self, tmp_path):
        notes = SessionNotes(session_id="ci2", init_token_threshold=1)
        notes._notes_dir = tmp_path
        notes._notes_path = tmp_path / "ci2.md"
        messages = [{"role": "user", "content": "build feature X"}]
        notes.maybe_update(messages, tool_count=0, est_tokens=1)
        ctx = notes.get_context_injection()
        assert "Session Notes" in ctx
        assert "build feature X" in ctx


class TestSessionNotesPersistence:
    def test_save_and_load(self, tmp_path):
        notes = SessionNotes(session_id="persist1", init_token_threshold=1)
        notes._notes_dir = tmp_path
        notes._notes_path = tmp_path / "persist1.md"
        messages = [{"role": "user", "content": "do something important"}]
        notes.maybe_update(messages, tool_count=0, est_tokens=1)

        # Verify file was saved
        assert notes._notes_path.exists()
        saved = notes._notes_path.read_text()
        assert "do something important" in saved

        # Load from a fresh instance
        notes2 = SessionNotes(session_id="persist1")
        notes2._notes_dir = tmp_path
        loaded = notes2.load(session_id="persist1")
        assert loaded is not None
        assert "do something important" in loaded

    def test_load_nonexistent_returns_none(self, tmp_path):
        notes = SessionNotes(session_id="nope")
        notes._notes_dir = tmp_path
        result = notes.load(session_id="nonexistent_session")
        assert result is None

    def test_content_property(self, tmp_path):
        notes = SessionNotes(session_id="prop1", init_token_threshold=1)
        notes._notes_dir = tmp_path
        notes._notes_path = tmp_path / "prop1.md"
        assert notes.content == ""
        messages = [{"role": "user", "content": "task"}]
        notes.maybe_update(messages, tool_count=0, est_tokens=1)
        assert notes.content != ""
