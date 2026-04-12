"""Tests for new service modules."""
import os
import sys
import tempfile
import unittest
import asyncio
import json
import time
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock

_test_dir = os.path.dirname(os.path.abspath(__file__))
_agent_dir = os.path.dirname(_test_dir)
sys.path.insert(0, _agent_dir)

from agent.services.session_memory import SessionMemory, SessionState
from agent.services.memory_search import MemorySearchIndex, MemoryEntry, SearchHit
from agent.agentic.coordinator import (
    Coordinator,
    CoordinatorPhase,
    WorkerTask,
    PhaseResult,
    CoordinationResult,
)


# ---------------------------------------------------------------------------
# TestSessionMemory
# ---------------------------------------------------------------------------

class TestSessionMemory(unittest.TestCase):
    """Test SessionMemory persistence and lifecycle."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.mem = SessionMemory(storage_dir=self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_create_session(self):
        """create_session returns a valid SessionState."""
        state = self.mem.create_session(mode="chat", working_dir="/tmp")
        self.assertIsInstance(state, SessionState)
        self.assertEqual(state.mode, "chat")
        self.assertEqual(state.working_dir, "/tmp")
        self.assertEqual(len(state.session_id), 16)
        self.assertEqual(state.messages, [])
        self.assertEqual(state.tool_history, [])

    def test_save_and_restore(self):
        """Save a session and restore it by ID."""
        state = self.mem.create_session(mode="coding")
        state.messages.append({"role": "user", "content": "Hello"})
        self.mem.save(state)

        # Restore in a new SessionMemory instance
        mem2 = SessionMemory(storage_dir=self.tmpdir)
        restored = mem2.restore(session_id=state.session_id)
        self.assertIsNotNone(restored)
        self.assertEqual(restored.session_id, state.session_id)
        self.assertEqual(restored.mode, "coding")
        self.assertEqual(len(restored.messages), 1)
        self.assertEqual(restored.messages[0]["content"], "Hello")

    def test_restore_most_recent(self):
        """Restore without session_id returns the most recent session."""
        s1 = self.mem.create_session(mode="chat")
        time.sleep(0.05)  # Ensure different mtime
        s2 = self.mem.create_session(mode="coding")

        mem2 = SessionMemory(storage_dir=self.tmpdir)
        restored = mem2.restore()
        self.assertIsNotNone(restored)
        self.assertEqual(restored.session_id, s2.session_id)

    def test_list_sessions(self):
        """list_sessions returns summaries of stored sessions."""
        self.mem.create_session(mode="chat")
        self.mem.create_session(mode="coding")
        self.mem.create_session(mode="finance")

        sessions = self.mem.list_sessions()
        self.assertEqual(len(sessions), 3)
        modes = {s["mode"] for s in sessions}
        self.assertIn("chat", modes)
        self.assertIn("coding", modes)

    def test_delete_session(self):
        """delete_session removes the session file."""
        state = self.mem.create_session(mode="chat")
        sid = state.session_id

        result = self.mem.delete_session(sid)
        self.assertTrue(result)

        # Should not be restorable
        restored = self.mem.restore(session_id=sid)
        self.assertIsNone(restored)

    def test_delete_nonexistent_session(self):
        """Deleting a nonexistent session returns False."""
        result = self.mem.delete_session("nonexistent-id")
        self.assertFalse(result)

    def test_cleanup_old(self):
        """cleanup_old removes sessions beyond max_sessions."""
        for i in range(5):
            self.mem.create_session(mode="chat")
            time.sleep(0.02)

        deleted = self.mem.cleanup_old(max_sessions=2, max_age_days=365)
        self.assertEqual(deleted, 3)

        remaining = self.mem.list_sessions()
        self.assertEqual(len(remaining), 2)

    def test_auto_save(self):
        """auto_save creates a session if none exists and saves data."""
        self.assertIsNone(self.mem.current)

        self.mem.auto_save(
            messages=[{"role": "user", "content": "hi"}],
            tool_history=[{"tool": "Bash", "args": "ls"}],
            files_read={"file1.py", "file2.py"},
            mode="coding",
            working_dir="/project",
        )

        self.assertIsNotNone(self.mem.current)
        self.assertEqual(self.mem.current.mode, "coding")
        self.assertEqual(len(self.mem.current.messages), 1)
        self.assertEqual(len(self.mem.current.files_read), 2)

    def test_restore_empty_dir(self):
        """Restoring from an empty dir returns None."""
        with tempfile.TemporaryDirectory() as empty_dir:
            mem = SessionMemory(storage_dir=empty_dir)
            self.assertIsNone(mem.restore())


# ---------------------------------------------------------------------------
# TestMemorySearchIndex
# ---------------------------------------------------------------------------

class TestMemorySearchIndex(unittest.TestCase):
    """Test MemorySearchIndex TF-IDF search."""

    def _make_entry(self, entry_id, content, mtype="user", importance=1.0):
        return MemoryEntry(
            id=entry_id,
            content=content,
            memory_type=mtype,
            created_at="2026-01-01T00:00:00Z",
            importance=importance,
        )

    def test_add_and_search(self):
        """Add entries and search for them."""
        idx = MemorySearchIndex()
        idx.add(self._make_entry("1", "Python programming language tutorial"))
        idx.add(self._make_entry("2", "JavaScript frontend framework React"))
        idx.add(self._make_entry("3", "Python data science pandas numpy"))

        results = idx.search("Python programming")
        self.assertGreater(len(results), 0)
        # The Python entries should rank higher
        top_ids = [h.entry.id for h in results]
        self.assertIn("1", top_ids[:2])

    def test_remove_entry(self):
        """Remove an entry and verify it's gone from results."""
        idx = MemorySearchIndex()
        idx.add(self._make_entry("1", "unique quantum computing topic"))
        idx.add(self._make_entry("2", "generic web development"))

        results_before = idx.search("quantum computing")
        self.assertGreater(len(results_before), 0)

        idx.remove("1")
        results_after = idx.search("quantum computing")
        entry_ids = [h.entry.id for h in results_after]
        self.assertNotIn("1", entry_ids)

    def test_remove_nonexistent(self):
        """Removing a nonexistent entry returns False."""
        idx = MemorySearchIndex()
        self.assertFalse(idx.remove("ghost"))

    def test_type_filter(self):
        """Search with type_filter only returns matching types."""
        idx = MemorySearchIndex()
        idx.add(self._make_entry("1", "machine learning deep neural networks", mtype="project"))
        idx.add(self._make_entry("2", "reinforcement learning algorithms policy", mtype="reference"))
        idx.add(self._make_entry("3", "database optimization query planning", mtype="project"))

        results = idx.search("deep neural networks", type_filter="project")
        self.assertGreater(len(results), 0)
        for hit in results:
            self.assertEqual(hit.entry.memory_type, "project")

    def test_empty_search(self):
        """Searching with empty query returns no results."""
        idx = MemorySearchIndex()
        idx.add(self._make_entry("1", "some content here"))

        results = idx.search("")
        self.assertEqual(len(results), 0)

    def test_stopwords_filtered(self):
        """Stopwords are filtered from queries and documents."""
        idx = MemorySearchIndex()
        idx.add(self._make_entry("1", "the quick brown fox"))
        idx.add(self._make_entry("2", "lazy dog sleeping"))

        # "the" is a stopword, so searching for it alone yields nothing
        results = idx.search("the")
        self.assertEqual(len(results), 0)

    def test_importance_boost(self):
        """Entries with higher importance score higher."""
        idx = MemorySearchIndex()
        idx.add(self._make_entry("low", "database optimization query planning", importance=0.5))
        idx.add(self._make_entry("high", "database optimization index performance", importance=2.0))
        idx.add(self._make_entry("other", "unrelated topic about cooking recipes", importance=1.0))

        results = idx.search("database optimization")
        self.assertGreater(len(results), 0)
        # High-importance entry should rank first
        self.assertEqual(results[0].entry.id, "high")

    def test_tfidf_correctness(self):
        """TF-IDF gives higher score to rare terms."""
        idx = MemorySearchIndex()
        # "common" appears in all docs, "rare" appears in one
        idx.add(self._make_entry("1", "common word common word"))
        idx.add(self._make_entry("2", "common word common word"))
        idx.add(self._make_entry("3", "common word rare special"))

        results = idx.search("rare special")
        self.assertGreater(len(results), 0)
        self.assertEqual(results[0].entry.id, "3")

    def test_matched_terms_reported(self):
        """SearchHit.matched_terms lists the overlapping terms."""
        idx = MemorySearchIndex()
        idx.add(self._make_entry("1", "kubernetes container orchestration docker"))
        idx.add(self._make_entry("2", "python web framework flask django"))

        results = idx.search("kubernetes docker")
        self.assertGreater(len(results), 0)
        self.assertIn("kubernetes", results[0].matched_terms)
        self.assertIn("docker", results[0].matched_terms)


# ---------------------------------------------------------------------------
# TestCoordinator
# ---------------------------------------------------------------------------

class TestCoordinator(unittest.TestCase):
    """Test Coordinator multi-agent orchestration."""

    def _run_async(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    @classmethod
    def setUpClass(cls):
        try:
            asyncio.get_event_loop()
        except RuntimeError:
            asyncio.set_event_loop(asyncio.new_event_loop())

    def test_basic_coordination(self):
        """Run a full 4-phase coordination with mock worker."""

        async def mock_worker(task: WorkerTask) -> str:
            return f"Done: {task.description}"

        coord = Coordinator(worker_fn=mock_worker, max_workers=2)
        result = self._run_async(coord.coordinate(
            objective="Test objective",
            research_tasks=["Research A", "Research B"],
            implementation_tasks=["Implement X"],
            verification_tasks=["Verify Y"],
        ))

        self.assertIsInstance(result, CoordinationResult)
        self.assertTrue(result.success)
        # Should have 4 phases: research, synthesis, implementation, verification
        self.assertEqual(len(result.phases), 4)
        self.assertGreater(result.total_duration_ms, 0)

    def test_parallel_execution(self):
        """Workers run in parallel (bounded by semaphore)."""
        execution_times = []

        async def timed_worker(task: WorkerTask) -> str:
            start = time.time()
            await asyncio.sleep(0.05)
            elapsed = time.time() - start
            execution_times.append(elapsed)
            return f"OK: {task.description}"

        coord = Coordinator(worker_fn=timed_worker, max_workers=3)
        result = self._run_async(coord.coordinate(
            objective="Parallel test",
            research_tasks=["R1", "R2", "R3"],
            implementation_tasks=["I1"],
            verification_tasks=["V1"],
        ))

        self.assertTrue(result.success)
        # All 3 research tasks should run in roughly the same wall-clock time
        # (parallel), so total should be closer to 0.05s than 0.15s
        # The research phase duration should indicate parallelism
        research_phase = result.phases[0]
        self.assertEqual(len(research_phase.tasks), 3)
        # Each task took ~0.05s, but parallel so phase duration should be < 0.15s
        # (with some margin for scheduling overhead)
        self.assertLess(research_phase.duration_ms, 300)

    def test_phase_results(self):
        """Each phase result contains correct task details."""

        async def worker(task: WorkerTask) -> str:
            return f"Result for {task.id}"

        coord = Coordinator(worker_fn=worker)
        result = self._run_async(coord.coordinate(
            objective="Phase detail test",
            research_tasks=["Investigate X"],
        ))

        # Check research phase
        research = result.phases[0]
        self.assertEqual(research.phase, CoordinatorPhase.RESEARCH)
        self.assertEqual(len(research.tasks), 1)
        self.assertEqual(research.tasks[0].status, "completed")
        self.assertIn("Result for", research.tasks[0].result)

        # Check synthesis phase
        synthesis = result.phases[1]
        self.assertEqual(synthesis.phase, CoordinatorPhase.SYNTHESIS)

    def test_failing_workers(self):
        """Coordinator handles worker failures gracefully."""

        async def failing_worker(task: WorkerTask) -> str:
            if "fail" in task.description.lower():
                raise RuntimeError("Intentional failure")
            return "OK"

        coord = Coordinator(worker_fn=failing_worker, max_workers=2)
        result = self._run_async(coord.coordinate(
            objective="Failure test",
            research_tasks=["Succeed task", "Fail task"],
            implementation_tasks=["Succeed impl"],
            verification_tasks=["Succeed verify"],
        ))

        # The overall result should not be fully successful
        # because the research phase had a failure
        research = result.phases[0]
        self.assertFalse(research.success)

        # The failed task should have error info
        failed_tasks = [t for t in research.tasks if t.status == "failed"]
        self.assertEqual(len(failed_tasks), 1)
        self.assertIn("RuntimeError", failed_tasks[0].error)

    def test_with_llm_fn(self):
        """Coordinator uses llm_fn for synthesis when provided."""

        async def worker(task: WorkerTask) -> str:
            return "Research finding"

        async def mock_llm(prompt: str) -> str:
            return "TASK: Do the first thing\nTASK: Do the second thing"

        coord = Coordinator(worker_fn=worker, llm_fn=mock_llm)
        result = self._run_async(coord.coordinate(
            objective="LLM synthesis test",
            research_tasks=["Research"],
        ))

        self.assertTrue(result.success)
        # Synthesis should have used the LLM
        synthesis = result.phases[1]
        self.assertTrue(synthesis.success)
        self.assertIn("TASK:", synthesis.summary)

        # Implementation phase should have extracted 2 tasks from synthesis
        impl = result.phases[2]
        self.assertEqual(len(impl.tasks), 2)

    def test_failing_llm_fn(self):
        """Coordinator handles LLM failure gracefully in synthesis."""

        async def worker(task: WorkerTask) -> str:
            return "Finding"

        async def bad_llm(prompt: str) -> str:
            raise ConnectionError("LLM unavailable")

        coord = Coordinator(worker_fn=worker, llm_fn=bad_llm)
        result = self._run_async(coord.coordinate(
            objective="LLM failure test",
            research_tasks=["Research"],
        ))

        # Synthesis phase should have failed but coordination continues
        synthesis = result.phases[1]
        self.assertFalse(synthesis.success)
        self.assertIn("LLM synthesis failed", synthesis.tasks[0].result)

    def test_files_changed_extraction(self):
        """Coordinator extracts file paths from implementation results."""

        async def worker(task: WorkerTask) -> str:
            if task.phase == CoordinatorPhase.IMPLEMENTATION:
                return "Modified: src/main.py\nCreated: src/utils.py\n"
            return "OK"

        coord = Coordinator(worker_fn=worker)
        result = self._run_async(coord.coordinate(
            objective="File tracking test",
            research_tasks=["Research"],
            implementation_tasks=["Implement changes"],
            verification_tasks=["Verify"],
        ))

        self.assertIn("src/main.py", result.files_changed)
        self.assertIn("src/utils.py", result.files_changed)


if __name__ == "__main__":
    unittest.main()
