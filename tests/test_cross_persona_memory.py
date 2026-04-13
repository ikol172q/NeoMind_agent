"""
Tests for Phase 4 — Cross-Persona Memory with Source Tags.

Contract: contracts/persona_fleet/04_cross_persona_memory.md
"""

import os
import tempfile
import shutil
import pytest

from agent.memory.shared_memory import SharedMemory


@pytest.fixture
def tmp_db():
    """Create a temp directory for the test database."""
    d = tempfile.mkdtemp(prefix="neomind_test_mem_")
    db_path = os.path.join(d, "test_shared_memory.db")
    yield db_path
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def memory(tmp_db):
    """SharedMemory instance with isolated test database."""
    return SharedMemory(db_path=tmp_db)


class TestSchemaMigration:

    def test_migration_idempotent(self, tmp_db):
        """Contract test 1: creating SharedMemory twice runs migration twice safely."""
        mem1 = SharedMemory(db_path=tmp_db)
        mem1.remember_fact("work", "SDE", "chat")
        mem1.close()

        mem2 = SharedMemory(db_path=tmp_db)
        facts = mem2.recall_facts()
        assert len(facts) == 1
        mem2.close()

    def test_new_columns_exist(self, memory):
        """New columns source_instance and project_id exist after init."""
        conn = memory._get_conn()
        # Check facts table
        cursor = conn.execute("PRAGMA table_info(facts)")
        columns = {row["name"] for row in cursor.fetchall()}
        assert "source_instance" in columns
        assert "project_id" in columns

        # Check patterns table
        cursor = conn.execute("PRAGMA table_info(patterns)")
        columns = {row["name"] for row in cursor.fetchall()}
        assert "source_instance" in columns
        assert "project_id" in columns


class TestWriteWithInstance:

    def test_fact_with_instance(self, memory):
        """Contract test 2: remember_fact with source_instance and project_id."""
        fid = memory.remember_fact(
            "work", "SDE", "coding",
            source_instance="coder-1", project_id="proj-1"
        )
        assert fid is not None

        facts = memory.recall_facts()
        assert len(facts) == 1
        assert facts[0]["source_instance"] == "coder-1"
        assert facts[0]["project_id"] == "proj-1"

    def test_fact_without_instance(self, memory):
        """Contract test 3: remember_fact without instance → backward compat."""
        memory.remember_fact("work", "SDE", "coding")
        facts = memory.recall_facts()
        assert facts[0]["source_instance"] is None
        assert facts[0]["project_id"] is None

    def test_preference_with_instance(self, memory):
        """Contract test 10: set_preference with source_instance."""
        memory.set_preference(
            "tz", "UTC", "chat", source_instance="mgr-1"
        )
        prefs = memory.get_all_preferences()
        assert "tz" in prefs
        # Preferences table now has source_instance column
        conn = memory._get_conn()
        row = conn.execute(
            "SELECT source_instance FROM preferences WHERE key = 'tz'"
        ).fetchone()
        assert row["source_instance"] == "mgr-1"

    def test_pattern_with_instance(self, memory):
        """record_pattern with source_instance."""
        memory.record_pattern(
            "frequent_stock", "AAPL", "fin",
            source_instance="quant-1", project_id="proj-1"
        )
        patterns = memory.get_patterns()
        assert len(patterns) == 1
        assert patterns[0]["source_instance"] == "quant-1"
        assert patterns[0]["project_id"] == "proj-1"

    def test_feedback_with_instance(self, memory):
        """record_feedback with source_instance."""
        memory.record_feedback(
            "praise", "Great work", "fin",
            source_instance="quant-1", project_id="proj-1"
        )
        fb = memory.get_recent_feedback()
        assert len(fb) == 1
        # Check via raw query since get_recent_feedback may not return new cols
        conn = memory._get_conn()
        row = conn.execute(
            "SELECT source_instance, project_id FROM feedback LIMIT 1"
        ).fetchone()
        assert row["source_instance"] == "quant-1"
        assert row["project_id"] == "proj-1"


class TestFilterByPersona:

    def test_filter_facts_by_persona(self, memory):
        """Contract test 4: recall_facts with include_personas filter."""
        memory.remember_fact("work", "SDE at Google", "chat")
        memory.remember_fact("stack", "Python expert", "coding")
        memory.remember_fact("portfolio", "AAPL 100 shares", "fin")

        coding_fin = memory.recall_facts(include_personas=["coding", "fin"])
        modes = {f["source_mode"] for f in coding_fin}
        assert modes == {"coding", "fin"}
        assert len(coding_fin) == 2

    def test_filter_facts_by_project(self, memory):
        """Contract test 5: recall_facts with project_id filter."""
        memory.remember_fact("work", "task A", "coding", project_id="proj-1")
        memory.remember_fact("work", "task B", "coding", project_id="proj-2")

        proj1 = memory.recall_facts(project_id="proj-1")
        assert len(proj1) == 1
        assert proj1[0]["fact"] == "task A"

    def test_filter_patterns_by_persona(self, memory):
        """Contract test 9: get_patterns with include_personas filter."""
        memory.record_pattern("stock", "AAPL", "fin")
        memory.record_pattern("lang", "Python", "coding")
        memory.record_pattern("topic", "AI", "chat")

        fin_only = memory.get_patterns(include_personas=["fin"])
        assert len(fin_only) == 1
        assert fin_only[0]["source_mode"] == "fin"


class TestCrossPersonaContext:

    def test_envelopes_for_cross_persona(self, memory):
        """Contract test 6: cross-persona content wrapped in <from> envelopes."""
        memory.remember_fact("stack", "Python expert", "coding", source_instance="coder-1")
        memory.remember_fact("portfolio", "AAPL watcher", "fin", source_instance="quant-1")
        memory.remember_fact("preference", "likes jokes", "chat")

        context = memory.get_cross_persona_context("chat")
        assert '<from persona="coding" instance="coder-1">' in context
        assert '<from persona="fin" instance="quant-1">' in context
        assert "</from>" in context

    def test_self_not_wrapped(self, memory):
        """Contract test 7: current_mode content NOT wrapped in envelopes."""
        memory.remember_fact("preference", "likes jokes", "chat")
        memory.remember_fact("stack", "Python expert", "coding")

        context = memory.get_cross_persona_context("chat")
        # "likes jokes" should appear without envelope
        assert "likes jokes" in context
        # It should NOT be inside a <from persona="chat"> envelope
        assert '<from persona="chat">' not in context

    def test_legacy_data_loads(self, memory):
        """Contract test 8: facts without source_instance load with None."""
        # Write via raw SQL to simulate legacy data
        conn = memory._get_conn()
        conn.execute(
            "INSERT INTO facts (category, fact, source_mode, created_at) VALUES (?, ?, ?, ?)",
            ("work", "legacy fact", "chat", "2026-01-01T00:00:00")
        )
        conn.commit()

        facts = memory.recall_facts()
        assert len(facts) == 1
        assert facts[0]["source_instance"] is None
        assert facts[0]["project_id"] is None

    def test_cross_persona_with_project_filter(self, memory):
        """Cross-persona context respects project_id filter."""
        memory.remember_fact("stack", "Rust dev", "coding", project_id="proj-1")
        memory.remember_fact("stack", "Go dev", "coding", project_id="proj-2")

        context = memory.get_cross_persona_context("chat", project_id="proj-1")
        assert "Rust dev" in context
        assert "Go dev" not in context

    def test_empty_cross_persona_context(self, memory):
        """No cross-persona data → empty string."""
        context = memory.get_cross_persona_context("chat")
        assert context == ""
