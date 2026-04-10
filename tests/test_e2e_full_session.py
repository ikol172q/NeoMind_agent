"""
End-to-End Test Suite for NeoMind Agent.

Tests full session workflows including:
- Tool pipeline: parse → validate → execute → format
- Multi-tool sequences (read then edit)
- Task management lifecycle
- Search + synthesis pipeline
- Finance trading flow
- Context compaction trigger

Created: 2026-04-02 (Phase 4 - Integration Testing)
"""

import os
import sys
import tempfile
import unittest
import asyncio
from pathlib import Path
from unittest import mock

_test_dir = os.path.dirname(os.path.abspath(__file__))
_agent_dir = os.path.dirname(_test_dir)
sys.path.insert(0, _agent_dir)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_async(coro):
    """Run an async coroutine synchronously, compatible across Python versions."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


# ===========================================================================
# 1. TestToolSequence
# ===========================================================================

class TestToolSequence(unittest.TestCase):
    """E2E: create a temp file, read it, edit it, verify edit, glob, grep."""

    def setUp(self):
        """Create a temporary directory and a ToolRegistry scoped to it."""
        self.temp_dir = tempfile.mkdtemp(prefix="neomind_e2e_")
        from agent.coding.tools import ToolRegistry
        from agent.coding.tool_parser import ToolCallParser
        self.registry = ToolRegistry(working_dir=self.temp_dir)
        self.parser = ToolCallParser()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # -- helper to run a tool through the full pipeline --
    def _run_tool(self, tool_name, params):
        """Parse → validate → apply_defaults → execute."""
        tool_def = self.registry.get_tool(tool_name)
        self.assertIsNotNone(tool_def, f"Tool '{tool_name}' not found in registry")
        valid, error = tool_def.validate_params(params)
        self.assertTrue(valid, f"Validation failed for {tool_name}: {error}")
        applied = tool_def.apply_defaults(params)
        result = tool_def.execute(**applied)
        return result

    def test_write_read_edit_glob_grep_sequence(self):
        """Full multi-tool sequence: Write → Read → Edit → Read → Glob → Grep."""

        # --- Step 1: Write a file ---
        target = os.path.join(self.temp_dir, "session_file.py")
        original_content = (
            "# session_file.py\n"
            "def greet(name):\n"
            "    return f'Hello, {name}!'\n"
        )
        result_write = self._run_tool("Write", {"path": target, "content": original_content})
        self.assertTrue(result_write.success, f"Write failed: {result_write.error}")

        # --- Step 2: Read the file back ---
        result_read = self._run_tool("Read", {"path": target})
        self.assertTrue(result_read.success, f"Read failed: {result_read.error}")
        self.assertIn("def greet(name):", result_read.output)
        self.assertIn("Hello, {name}!", result_read.output)

        # --- Step 3: Edit the file (rename function) ---
        result_edit = self._run_tool("Edit", {
            "path": target,
            "old_string": "def greet(name):",
            "new_string": "def welcome(name):",
        })
        self.assertTrue(result_edit.success, f"Edit failed: {result_edit.error}")

        # --- Step 4: Read again to confirm edit ---
        result_read2 = self._run_tool("Read", {"path": target})
        self.assertTrue(result_read2.success)
        self.assertIn("def welcome(name):", result_read2.output)
        self.assertNotIn("def greet(name):", result_read2.output)

        # --- Step 5: Glob to find the file ---
        result_glob = self._run_tool("Glob", {"pattern": "*.py", "path": self.temp_dir})
        self.assertTrue(result_glob.success, f"Glob failed: {result_glob.error}")
        self.assertIn("session_file.py", result_glob.output)

        # --- Step 6: Grep to search content ---
        result_grep = self._run_tool("Grep", {
            "pattern": "welcome",
            "path": self.temp_dir,
        })
        self.assertTrue(result_grep.success, f"Grep failed: {result_grep.error}")
        self.assertIn("welcome", result_grep.output)

    def test_edit_nonexistent_file_fails(self):
        """Editing a file that does not exist should fail gracefully."""
        result = self._run_tool("Edit", {
            "path": os.path.join(self.temp_dir, "nope.txt"),
            "old_string": "foo",
            "new_string": "bar",
        })
        self.assertFalse(result.success)

    def test_read_with_offset_and_limit(self):
        """Read respects offset/limit parameters through the full pipeline."""
        target = os.path.join(self.temp_dir, "lines.txt")
        lines = [f"line {i}\n" for i in range(1, 21)]
        with open(target, "w") as fh:
            fh.writelines(lines)

        result = self._run_tool("Read", {"path": target, "offset": 5, "limit": 3})
        self.assertTrue(result.success)
        self.assertIn("line 6", result.output)

    def test_parse_structured_tool_call(self):
        """ToolCallParser correctly parses a structured JSON tool_call tag."""
        target = os.path.join(self.temp_dir, "p.txt")
        with open(target, "w") as fh:
            fh.write("data\n")

        response = f'{{"tool": "Read", "params": {{"path": "{target}"}}}}'
        tool_call = self.parser.parse(f"<tool_call>{response}</tool_call>")

        self.assertIsNotNone(tool_call)
        self.assertEqual(tool_call.tool_name, "Read")
        self.assertEqual(tool_call.params["path"], target)


# ===========================================================================
# 2. TestTaskManagerLifecycle
# ===========================================================================

class TestTaskManagerLifecycle(unittest.TestCase):
    """E2E: task creation → listing → status transitions → stop → stats."""

    def setUp(self):
        from agent.tools.task_tools import TaskManager, TaskStatus
        self.TaskStatus = TaskStatus
        self.mgr = TaskManager()

    def test_full_lifecycle(self):
        """Create tasks, advance through statuses, stop one, verify stats."""
        TS = self.TaskStatus

        # --- Create three tasks ---
        r1 = self.mgr.create("Design API", "Design the REST endpoints")
        r2 = self.mgr.create("Implement API", "Code the endpoints")
        r3 = self.mgr.create("Write docs", "Document the API")

        self.assertTrue(r1.success)
        self.assertTrue(r2.success)
        self.assertTrue(r3.success)
        self.assertEqual(r1.task.status, TS.PENDING)

        # --- List all (should be 3) ---
        all_tasks = self.mgr.list()
        self.assertTrue(all_tasks.success)
        self.assertEqual(len(all_tasks.tasks), 3)

        # --- Move task-1 through pending → in_progress → completed ---
        up1 = self.mgr.update(r1.task.id, status=TS.IN_PROGRESS)
        self.assertTrue(up1.success)
        self.assertEqual(up1.task.status, TS.IN_PROGRESS)

        up2 = self.mgr.update(r1.task.id, status=TS.COMPLETED)
        self.assertTrue(up2.success)
        self.assertEqual(up2.task.status, TS.COMPLETED)

        # --- Invalid transition: completed → pending ---
        bad = self.mgr.update(r1.task.id, status=TS.PENDING)
        self.assertFalse(bad.success)
        self.assertIn("Cannot transition", bad.message)

        # --- Stop task-3 (pending → cancelled) ---
        stop = self.mgr.stop(r3.task.id)
        self.assertTrue(stop.success)
        self.assertEqual(stop.task.status, TS.CANCELLED)

        # --- Cannot stop an already-cancelled task ---
        stop2 = self.mgr.stop(r3.task.id)
        self.assertFalse(stop2.success)

        # --- Filter by status ---
        pending = self.mgr.list(status_filter=TS.PENDING)
        self.assertEqual(len(pending.tasks), 1)
        self.assertEqual(pending.tasks[0].id, r2.task.id)

        completed = self.mgr.list(status_filter=TS.COMPLETED)
        self.assertEqual(len(completed.tasks), 1)
        self.assertEqual(completed.tasks[0].id, r1.task.id)

        cancelled = self.mgr.list(status_filter=TS.CANCELLED)
        self.assertEqual(len(cancelled.tasks), 1)
        self.assertEqual(cancelled.tasks[0].id, r3.task.id)

        # --- Verify stats ---
        stats = self.mgr.get_stats()
        self.assertEqual(stats["total_tasks"], 3)
        self.assertEqual(stats["status_counts"]["pending"], 1)
        self.assertEqual(stats["status_counts"]["in_progress"], 0)
        self.assertEqual(stats["status_counts"]["completed"], 1)
        self.assertEqual(stats["status_counts"]["cancelled"], 1)

    def test_create_empty_subject_fails(self):
        """Creating a task with an empty subject should fail."""
        result = self.mgr.create("", "desc")
        self.assertFalse(result.success)
        self.assertEqual(result.error, "invalid_subject")

    def test_get_nonexistent_task(self):
        """Getting a task that does not exist returns an error."""
        result = self.mgr.get("task-99999")
        self.assertFalse(result.success)
        self.assertEqual(result.error, "not_found")

    def test_update_subject_and_metadata(self):
        """Updating subject and metadata works without changing status."""
        r = self.mgr.create("Original", "desc")
        updated = self.mgr.update(
            r.task.id,
            subject="Renamed",
            metadata={"priority": "high"},
        )
        self.assertTrue(updated.success)
        self.assertEqual(updated.task.subject, "Renamed")
        self.assertEqual(updated.task.metadata["priority"], "high")

    def test_auto_incremented_ids(self):
        """Task IDs are auto-incremented (task-1, task-2, ...)."""
        r1 = self.mgr.create("A", "a")
        r2 = self.mgr.create("B", "b")
        self.assertEqual(r1.task.id, "task-1")
        self.assertEqual(r2.task.id, "task-2")


# ===========================================================================
# 3. TestSearchSynthesisPipeline
# ===========================================================================

class TestSearchSynthesisPipeline(unittest.TestCase):
    """E2E: multi-source synthesis and research workflow."""

    def _make_results(self):
        """Build a list of SearchResult objects for testing."""
        from agent.search.multi_source import SearchResult
        return [
            SearchResult(
                source="DuckDuckGo",
                title="Python Concurrency Guide",
                url="https://example.com/concurrency",
                snippet="Python supports multiple concurrency models.",
                content="Python supports threads, processes, and asyncio.",
                relevance_score=0.92,
                quality_score=0.90,
            ),
            SearchResult(
                source="Google",
                title="Asyncio in Practice",
                url="https://example.com/asyncio",
                snippet="Asyncio allows cooperative multitasking in Python.",
                content="The asyncio module provides infrastructure for async IO.",
                relevance_score=0.88,
                quality_score=0.85,
            ),
            SearchResult(
                source="Bing",
                title="Thread Safety in Python",
                url="https://example.com/threads",
                snippet="The GIL limits true thread parallelism in CPython.",
                relevance_score=0.80,
                quality_score=0.75,
            ),
            # Duplicate URL to test deduplication
            SearchResult(
                source="DuckDuckGo",
                title="Python Concurrency Guide (dup)",
                url="https://example.com/concurrency",
                snippet="Duplicate entry for concurrency.",
                relevance_score=0.70,
                quality_score=0.60,
            ),
        ]

    # ── MultiSourceSynthesizer ────────────────────────────────────────

    def test_synthesize_highest_quality(self):
        """Synthesize with HIGHEST_QUALITY strategy produces correct output."""
        from agent.search.multi_source import MultiSourceSynthesizer, SynthesisStrategy

        synth = MultiSourceSynthesizer()
        results = self._make_results()

        output = synth.synthesize(
            results,
            strategy=SynthesisStrategy.HIGHEST_QUALITY,
            max_results=5,
        )

        # Should contain markdown structure
        self.assertIn("## Search Results", output)
        self.assertIn("## Summary", output)
        # First result by quality should be the highest quality_score
        self.assertIn("Python Concurrency Guide", output)

    def test_synthesize_deduplicates_urls(self):
        """Duplicate URLs are removed before synthesis."""
        from agent.search.multi_source import MultiSourceSynthesizer, SynthesisStrategy

        synth = MultiSourceSynthesizer()
        results = self._make_results()  # 4 items, 1 duplicate URL

        output = synth.synthesize(results, strategy=SynthesisStrategy.CONSENSUS)

        # The duplicate should have been removed — only 3 unique URLs
        # Count the numbered result headers [1], [2], [3]
        self.assertIn("[1]", output)
        self.assertIn("[2]", output)
        self.assertIn("[3]", output)
        # There should NOT be a [4] because the dup was removed
        self.assertNotIn("[4]", output)

    def test_synthesize_empty_results(self):
        """Synthesis with empty list returns a sentinel string."""
        from agent.search.multi_source import MultiSourceSynthesizer

        synth = MultiSourceSynthesizer()
        self.assertEqual(synth.synthesize([]), "No results found.")

    def test_generate_citations(self):
        """Citations follow the expected numbered format."""
        from agent.search.multi_source import MultiSourceSynthesizer

        synth = MultiSourceSynthesizer()
        results = self._make_results()[:2]  # take 2 unique
        citations = synth.generate_citations(results)

        self.assertEqual(len(citations), 2)
        self.assertTrue(citations[0].startswith("[1]"))
        self.assertIn("example.com/concurrency", citations[0])

    def test_synthesizer_stats(self):
        """Stats reflect registered sources and cache size."""
        from agent.search.multi_source import MultiSourceSynthesizer

        synth = MultiSourceSynthesizer()
        synth.add_source("mock_engine", object())

        stats = synth.get_stats()
        self.assertEqual(stats["sources"], 1)
        self.assertEqual(stats["cache_size"], 0)

    # ── ResearchWorkflow ──────────────────────────────────────────────

    def test_research_workflow_no_deps(self):
        """ResearchWorkflow runs all 6 phases with no external deps (heuristic mode)."""
        from agent.search.research_workflow import ResearchWorkflow

        workflow = ResearchWorkflow()  # no search_fn, no llm_fn
        result = _run_async(workflow.execute("What causes aurora borealis?"))

        self.assertEqual(result.question, "What causes aurora borealis?")
        # Clarified question should have key terms appended
        self.assertIn("aurora", result.clarified_question.lower())
        self.assertIn("borealis", result.clarified_question.lower())
        # Without search_fn, sources/facts stay empty
        self.assertEqual(len(result.sources), 0)
        self.assertEqual(len(result.facts), 0)
        self.assertGreater(result.total_duration_ms, 0)
        # All 6 phases should have run
        self.assertEqual(len(result.phase_results), 6)

    def test_research_workflow_with_mock_search_and_llm(self):
        """ResearchWorkflow with mock search_fn and llm_fn populates all fields."""
        from agent.search.research_workflow import ResearchWorkflow

        async def mock_search(query):
            return [
                {
                    "title": "Solar Wind Effects",
                    "url": "https://example.com/solar",
                    "snippet": "Solar wind particles interact with Earth magnetosphere.",
                    "source": "mock",
                    "content": "Charged particles from the sun excite atmospheric gases.",
                    "relevance_score": 0.95,
                },
                {
                    "title": "Magnetosphere Dynamics",
                    "url": "https://example.com/magneto",
                    "snippet": "The magnetosphere channels particles to the poles.",
                    "source": "mock",
                    "content": "Geomagnetic field guides solar particles toward polar regions.",
                    "relevance_score": 0.88,
                },
            ]

        call_count = {"n": 0}

        async def mock_llm(prompt):
            call_count["n"] += 1
            if "Clarify" in prompt:
                return "What physical mechanisms cause the aurora borealis (northern lights)?"
            if "Extract" in prompt:
                return (
                    "- Solar wind particles interact with Earth's magnetosphere\n"
                    "- Charged particles excite atmospheric gases\n"
                )
            if "consistency" in prompt.lower() or "Review" in prompt:
                return "1: SUPPORTED\n2: SUPPORTED\n"
            # conclusion prompt must be checked BEFORE synthesis because it
            # also contains the word "synthesis" in "research synthesis"
            if "concise conclusion" in prompt.lower():
                return (
                    "The aurora borealis results from charged solar particles colliding "
                    "with atmospheric gases.\nCONFIDENCE: 0.92"
                )
            if "research analyst" in prompt.lower():
                return "Aurora borealis is caused by solar wind particles exciting atmospheric gases."
            return "Mock LLM response"

        workflow = ResearchWorkflow(search_fn=mock_search, llm_fn=mock_llm)
        result = _run_async(workflow.execute("What causes aurora borealis?"))

        # Question clarification used LLM
        self.assertIn("physical mechanisms", result.clarified_question)
        # Sources were discovered
        self.assertEqual(len(result.sources), 2)
        # Facts were extracted
        self.assertGreater(len(result.facts), 0)
        # Validated facts have confidence boosts
        for fact in result.validated_facts:
            self.assertIn("validation_status", fact)
        # Synthesis and conclusion present
        self.assertIn("aurora", result.synthesis.lower())
        self.assertIn("aurora", result.conclusion.lower())
        self.assertAlmostEqual(result.confidence, 0.92, places=2)
        # LLM was actually called
        self.assertGreater(call_count["n"], 0)

    def test_research_workflow_search_fn_exception(self):
        """If search_fn raises, the pipeline continues with empty sources."""
        from agent.search.research_workflow import ResearchWorkflow

        async def failing_search(query):
            raise ConnectionError("Network down")

        workflow = ResearchWorkflow(search_fn=failing_search)
        result = _run_async(workflow.execute("test query"))

        # Source discovery should have failed but pipeline continues
        phase = result.phase_results.get("source_discovery")
        self.assertIsNotNone(phase)
        self.assertEqual(phase.status, "failed")
        self.assertIn("Network down", phase.notes)
        self.assertEqual(len(result.sources), 0)


# ===========================================================================
# 4. TestFinanceTradingFlow
# ===========================================================================

class TestFinanceTradingFlow(unittest.TestCase):
    """E2E: paper trading engine + performance tracker integration."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="neomind_fin_")
        from agent.finance.paper_trading import (
            PaperTradingEngine, OrderSide, OrderType, OrderStatus,
        )
        from agent.finance.performance_tracker import PerformanceTracker

        self.PaperTradingEngine = PaperTradingEngine
        self.OrderSide = OrderSide
        self.OrderType = OrderType
        self.OrderStatus = OrderStatus
        self.PerformanceTracker = PerformanceTracker

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_buy_sell_cycle_with_performance(self):
        """Buy → price rises → sell → track performance → calculate metrics."""
        engine = self.PaperTradingEngine(
            initial_capital=100_000.0,
            commission_rate=0.001,
            slippage_rate=0.0,  # disable slippage for deterministic assertions
            data_dir=Path(self.temp_dir),
        )
        tracker = self.PerformanceTracker(initial_capital=100_000.0)

        # --- Set initial price and buy ---
        engine.update_price("AAPL", 150.0)
        buy_order = engine.place_order("AAPL", self.OrderSide.BUY, 100)
        self.assertEqual(buy_order.status, self.OrderStatus.FILLED)
        self.assertAlmostEqual(buy_order.filled_price, 150.0, places=2)

        # Position should exist
        pos = engine.get_position("AAPL")
        self.assertIsNotNone(pos)
        self.assertEqual(pos.quantity, 100)

        # Record day-1 snapshot
        summary1 = engine.get_account_summary()
        tracker.record_snapshot(
            "2026-03-01",
            equity=summary1["equity"],
            cash=summary1["cash"],
            positions_value=pos.quantity * pos.current_price,
            trades_count=1,
        )

        # --- Price rises → sell ---
        engine.update_price("AAPL", 160.0)
        sell_order = engine.place_order("AAPL", self.OrderSide.SELL, 100)
        self.assertEqual(sell_order.status, self.OrderStatus.FILLED)
        self.assertAlmostEqual(sell_order.filled_price, 160.0, places=2)

        # Position should be closed
        self.assertIsNone(engine.get_position("AAPL"))

        # Realized PnL as calculated by the engine:
        # pnl = (fill_price - entry_price) * quantity - sell_commission
        # The buy commission is deducted from cash, not from realized_pnl.
        expected_pnl = (160.0 - 150.0) * 100 - sell_order.commission
        self.assertAlmostEqual(engine.account.realized_pnl, expected_pnl, places=2)

        # Record day-2 snapshot
        summary2 = engine.get_account_summary()
        tracker.record_snapshot(
            "2026-03-02",
            equity=summary2["equity"],
            cash=summary2["cash"],
            positions_value=0.0,
            trades_count=1,
        )

        # Record trades in tracker
        tracker.record_trade("AAPL", "buy", 100, 150.0, pnl=0.0)
        tracker.record_trade(
            "AAPL", "sell", 100, 160.0,
            pnl=expected_pnl, holding_period_days=1,
        )

        # --- Performance metrics ---
        metrics = tracker.calculate_metrics()
        self.assertGreater(metrics.total_return_pct, 0)
        self.assertEqual(metrics.total_trades, 2)
        self.assertEqual(metrics.winning_trades, 1)
        self.assertEqual(metrics.win_rate_pct, 50.0)  # 1 winner, 1 zero-pnl

        # --- Report should be a non-empty string ---
        report = tracker.generate_report()
        self.assertIn("PERFORMANCE REPORT", report)
        self.assertIn("Total Return", report)

    def test_market_order_rejected_without_price(self):
        """Market order for a symbol with no price set is rejected."""
        engine = self.PaperTradingEngine(
            initial_capital=50_000.0,
            data_dir=Path(self.temp_dir),
        )
        order = engine.place_order("XYZ", self.OrderSide.BUY, 10)
        self.assertEqual(order.status, self.OrderStatus.REJECTED)
        self.assertIn("No price", order.metadata.get("error", ""))

    def test_sell_without_position_rejected(self):
        """Selling a symbol we do not own is rejected."""
        engine = self.PaperTradingEngine(
            initial_capital=50_000.0,
            data_dir=Path(self.temp_dir),
        )
        engine.update_price("TSLA", 200.0)
        order = engine.place_order("TSLA", self.OrderSide.SELL, 10)
        self.assertEqual(order.status, self.OrderStatus.REJECTED)

    def test_limit_order_fills_when_price_reached(self):
        """Limit buy triggers when price drops to limit level."""
        engine = self.PaperTradingEngine(
            initial_capital=100_000.0,
            slippage_rate=0.0,
            data_dir=Path(self.temp_dir),
        )

        engine.update_price("MSFT", 300.0)
        # Place a limit buy at 290
        limit_order = engine.place_order(
            "MSFT", self.OrderSide.BUY, 50,
            order_type=self.OrderType.LIMIT, price=290.0,
        )
        self.assertEqual(limit_order.status, self.OrderStatus.PENDING)

        # Price hasn't reached limit yet
        engine.update_price("MSFT", 295.0)
        self.assertEqual(limit_order.status, self.OrderStatus.PENDING)

        # Price drops to 290 → order should fill
        engine.update_price("MSFT", 290.0)
        self.assertEqual(limit_order.status, self.OrderStatus.FILLED)
        self.assertAlmostEqual(limit_order.filled_price, 290.0, places=2)

    def test_cancel_pending_order(self):
        """A pending order can be cancelled."""
        engine = self.PaperTradingEngine(
            initial_capital=100_000.0,
            data_dir=Path(self.temp_dir),
        )
        engine.update_price("AMZN", 3000.0)
        order = engine.place_order(
            "AMZN", self.OrderSide.BUY, 10,
            order_type=self.OrderType.LIMIT, price=2900.0,
        )
        self.assertTrue(engine.cancel_order(order.id))
        self.assertEqual(order.status, self.OrderStatus.CANCELLED)
        self.assertEqual(len(engine.get_open_orders()), 0)

    def test_account_summary_values(self):
        """Account summary reflects correct aggregated values."""
        engine = self.PaperTradingEngine(
            initial_capital=100_000.0,
            slippage_rate=0.0,
            commission_rate=0.0,
            data_dir=Path(self.temp_dir),
        )
        engine.update_price("AAPL", 100.0)
        engine.place_order("AAPL", self.OrderSide.BUY, 100)

        summary = engine.get_account_summary()
        self.assertAlmostEqual(summary["cash"], 100_000.0 - 100 * 100.0, places=2)
        self.assertEqual(summary["positions"], 1)

    def test_save_and_load_state(self):
        """Engine state can be saved and restored."""
        engine = self.PaperTradingEngine(
            initial_capital=100_000.0,
            slippage_rate=0.0,
            data_dir=Path(self.temp_dir),
        )
        engine.update_price("AAPL", 150.0)
        engine.place_order("AAPL", self.OrderSide.BUY, 50)

        engine.save_state("test_state.json")

        engine2 = self.PaperTradingEngine(
            initial_capital=100_000.0, data_dir=Path(self.temp_dir),
        )
        loaded = engine2.load_state("test_state.json")
        self.assertTrue(loaded)
        self.assertIn("AAPL", engine2.account.positions)
        self.assertEqual(engine2.account.positions["AAPL"].quantity, 50)


# ===========================================================================
# 5. TestContextCompaction
# ===========================================================================

class TestContextCompaction(unittest.TestCase):
    """E2E: context compaction trigger, extractive summarisation, compression ratio."""

    def setUp(self):
        from agent.services.compact.context_compactor import (
            ContextCompactor, CompactMessage, MessageRole, PreservePolicy,
        )
        self.ContextCompactor = ContextCompactor
        self.CompactMessage = CompactMessage
        self.MessageRole = MessageRole
        self.PreservePolicy = PreservePolicy

    # -- helpers --
    def _msg(self, role, content, tokens=None, preserve=None):
        """Shortcut to build a CompactMessage."""
        MR = self.MessageRole
        PP = self.PreservePolicy
        role_enum = MR(role) if isinstance(role, str) else role
        preserve_enum = preserve if preserve is not None else PP.COMPRESSIBLE
        return self.CompactMessage(
            role=role_enum,
            content=content,
            token_count=tokens or max(1, len(content) // 4),
            preserve=preserve_enum,
        )

    def test_should_compact_threshold(self):
        """should_compact returns True when tokens exceed threshold."""
        compactor = self.ContextCompactor(
            max_tokens=1000, compact_threshold=0.8, target_ratio=0.5,
        )

        # Under threshold (800 tokens)
        small_msgs = [self._msg("user", "x" * 400, tokens=200) for _ in range(3)]
        self.assertFalse(compactor.should_compact(small_msgs))  # 600 < 800

        # Over threshold
        big_msgs = [self._msg("user", "x" * 400, tokens=300) for _ in range(3)]
        self.assertTrue(compactor.should_compact(big_msgs))  # 900 >= 800

    def test_compact_extractive_no_llm(self):
        """Compact without LLM uses extractive summarisation (first sentences)."""
        compactor = self.ContextCompactor(
            max_tokens=1000,
            compact_threshold=0.5,
            target_ratio=0.3,
            preserve_recent=1,
        )
        PP = self.PreservePolicy

        messages = [
            self._msg("system", "You are a helpful assistant.", tokens=10, preserve=PP.ALWAYS_KEEP),
            self._msg("user", "Tell me about Python.", tokens=100, preserve=PP.PREFER_KEEP),
            self._msg("assistant", "Python is a versatile language. It supports many paradigms.", tokens=200),
            self._msg("user", "What about asyncio?", tokens=100, preserve=PP.PREFER_KEEP),
            self._msg("assistant", "Asyncio provides cooperative multitasking. It is built on coroutines.", tokens=200),
            self._msg("user", "Summarize the key points.", tokens=100, preserve=PP.PREFER_KEEP),
            self._msg("assistant", "Here are the key points from our discussion.", tokens=200),
        ]

        # Should trigger compaction (total = 910 >= 1000 * 0.5 = 500)
        self.assertTrue(compactor.should_compact(messages))

        compacted, result = _run_async(compactor.compact(messages))

        # Compression happened
        self.assertLess(result.compacted_tokens, result.original_tokens)
        self.assertLess(result.compression_ratio, 1.0)
        self.assertGreater(result.compression_ratio, 0.0)

        # Fewer messages after compaction
        self.assertLess(result.messages_after, result.messages_before)

        # Summary text is non-empty and extractive (first sentences)
        self.assertTrue(len(result.summary_text) > 0)
        # Extractive summary should include first sentences of assistant replies
        self.assertIn("Python is a versatile language.", result.summary_text)

        # System message should be preserved
        system_msgs = [m for m in compacted if m.role == self.MessageRole.SYSTEM]
        self.assertGreaterEqual(len(system_msgs), 1)

    def test_compact_preserves_recent_user_messages(self):
        """Recent user messages (preserve_recent) are always kept."""
        compactor = self.ContextCompactor(
            max_tokens=500,
            compact_threshold=0.5,
            target_ratio=0.3,
            preserve_recent=2,
        )
        PP = self.PreservePolicy

        messages = [
            self._msg("user", "First question.", tokens=50, preserve=PP.PREFER_KEEP),
            self._msg("assistant", "First answer. Details follow.", tokens=100),
            self._msg("user", "Second question.", tokens=50, preserve=PP.PREFER_KEEP),
            self._msg("assistant", "Second answer. More info here.", tokens=100),
            self._msg("user", "Third question.", tokens=50, preserve=PP.PREFER_KEEP),
            self._msg("assistant", "Third answer. Conclusion reached.", tokens=100),
        ]

        compacted, result = _run_async(compactor.compact(messages))

        # Last 2 user messages and their following assistant replies should be kept
        kept_contents = {m.content for m in compacted}
        self.assertIn("Second question.", kept_contents)
        self.assertIn("Third question.", kept_contents)
        # Their assistant replies are also preserved
        self.assertIn("Second answer. More info here.", kept_contents)
        self.assertIn("Third answer. Conclusion reached.", kept_contents)

    def test_compact_nothing_compressible(self):
        """When all messages are ALWAYS_KEEP, nothing changes."""
        compactor = self.ContextCompactor(
            max_tokens=1000, compact_threshold=0.5, target_ratio=0.3,
        )
        PP = self.PreservePolicy

        messages = [
            self._msg("system", "System message.", tokens=50, preserve=PP.ALWAYS_KEEP),
            self._msg("system", "Another system message.", tokens=50, preserve=PP.ALWAYS_KEEP),
        ]

        compacted, result = _run_async(compactor.compact(messages))

        self.assertEqual(result.compression_ratio, 1.0)
        self.assertEqual(result.messages_after, result.messages_before)
        self.assertEqual(len(compacted), 2)

    def test_classify_message_roles(self):
        """classify_message assigns correct policies based on role."""
        compactor = self.ContextCompactor(
            max_tokens=1000, compact_threshold=0.8, target_ratio=0.5,
        )
        PP = self.PreservePolicy

        self.assertEqual(compactor.classify_message("system", "x"), PP.ALWAYS_KEEP)
        self.assertEqual(compactor.classify_message("user", "x"), PP.PREFER_KEEP)
        self.assertEqual(compactor.classify_message("assistant", "x"), PP.COMPRESSIBLE)
        self.assertEqual(
            compactor.classify_message("tool_result", "x", is_error=True),
            PP.PREFER_KEEP,
        )
        self.assertEqual(
            compactor.classify_message("tool_result", "x", is_error=False),
            PP.COMPRESSIBLE,
        )

    def test_invalid_parameters_raise(self):
        """Invalid compactor parameters raise ValueError."""
        with self.assertRaises(ValueError):
            self.ContextCompactor(max_tokens=1000, compact_threshold=0.0)
        with self.assertRaises(ValueError):
            self.ContextCompactor(max_tokens=1000, compact_threshold=0.5, target_ratio=0.0)
        with self.assertRaises(ValueError):
            # target_ratio >= compact_threshold is forbidden
            self.ContextCompactor(max_tokens=1000, compact_threshold=0.5, target_ratio=0.6)

    def test_compact_with_mock_llm(self):
        """Compact with a mock LLM fn produces an LLM-driven summary."""
        async def mock_llm(prompt):
            return "The user asked about Python and asyncio. Key takeaway: async IO is useful."

        compactor = self.ContextCompactor(
            max_tokens=500,
            compact_threshold=0.5,
            target_ratio=0.3,
            preserve_recent=1,
            llm_fn=mock_llm,
        )
        PP = self.PreservePolicy

        messages = [
            self._msg("user", "Explain Python.", tokens=100, preserve=PP.PREFER_KEEP),
            self._msg("assistant", "Python is great. Let me explain.", tokens=150),
            self._msg("user", "Now explain asyncio.", tokens=100, preserve=PP.PREFER_KEEP),
            self._msg("assistant", "Asyncio is for async IO. It uses coroutines.", tokens=150),
        ]

        compacted, result = _run_async(compactor.compact(messages))

        self.assertIn("asyncio", result.summary_text.lower())
        self.assertLess(result.compression_ratio, 1.0)


# ===========================================================================
# Entry point
# ===========================================================================

if __name__ == "__main__":
    unittest.main()
