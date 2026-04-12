"""
Performance Test Suite for NeoMind Agent.

Benchmarks critical paths to catch performance regressions:
- Tool execution latency
- Search indexing throughput
- Context compaction speed
- Token budget operations
- File operations at scale

Created: 2026-04-02 (Phase 4 - Integration Testing)
"""

import os
import sys
import time
import tempfile
import unittest
import threading
import shutil
import asyncio
from pathlib import Path

_test_dir = os.path.dirname(os.path.abspath(__file__))
_agent_dir = os.path.dirname(_test_dir)
sys.path.insert(0, _agent_dir)


class TestToolExecutionPerformance(unittest.TestCase):
    """Benchmark ToolRegistry operations (Read, Write, Glob, Grep)."""

    @classmethod
    def setUpClass(cls):
        """Create a temp directory with realistic file content for benchmarks."""
        cls._tmpdir = tempfile.mkdtemp(prefix="neomind_perf_tools_")

        # Create a 10K-line file for Read benchmarks
        cls._big_file = os.path.join(cls._tmpdir, "big_file.py")
        with open(cls._big_file, "w") as f:
            for i in range(10_000):
                f.write(f"# line {i}: x = {i * 3} + some padding text here\n")

        # Create 1000+ small Python files for Glob benchmarks
        cls._files_dir = os.path.join(cls._tmpdir, "many_files")
        os.makedirs(cls._files_dir, exist_ok=True)
        for i in range(1_050):
            fpath = os.path.join(cls._files_dir, f"module_{i:04d}.py")
            with open(fpath, "w") as f:
                f.write(f"# module {i}\ndef func_{i}():\n    return {i}\n")

        # Create 100 files with searchable content for Grep benchmarks
        cls._grep_dir = os.path.join(cls._tmpdir, "grep_files")
        os.makedirs(cls._grep_dir, exist_ok=True)
        for i in range(100):
            fpath = os.path.join(cls._grep_dir, f"search_{i:03d}.py")
            with open(fpath, "w") as f:
                for j in range(50):
                    if j % 10 == 0:
                        f.write(f"# TODO: fix issue {i}-{j}\n")
                    else:
                        f.write(f"value_{j} = {j * i}\n")

    @classmethod
    def tearDownClass(cls):
        """Remove temp directory."""
        shutil.rmtree(cls._tmpdir, ignore_errors=True)

    def _get_registry(self):
        """Create a fresh ToolRegistry pointing at our temp dir."""
        from agent.coding.tools import ToolRegistry
        return ToolRegistry(working_dir=self._tmpdir)

    def test_read_10k_line_file_under_500ms(self):
        """Reading a 10K line file should complete in <500ms."""
        registry = self._get_registry()

        start = time.time()
        result = registry.read_file(self._big_file)
        elapsed = time.time() - start

        print(f"  Read 10K-line file: {elapsed*1000:.1f}ms")
        self.assertTrue(result.success, f"Read failed: {result.error}")
        self.assertLess(elapsed, 0.5, f"Read took {elapsed:.3f}s (limit: 0.5s)")

    def test_glob_1000_files_under_2s(self):
        """Globbing 1000+ files should complete in <2s."""
        registry = self._get_registry()

        start = time.time()
        result = registry.glob_files("**/*.py", path=self._files_dir)
        elapsed = time.time() - start

        print(f"  Glob 1000+ files: {elapsed*1000:.1f}ms")
        self.assertTrue(result.success, f"Glob failed: {result.error}")
        self.assertLess(elapsed, 2.0, f"Glob took {elapsed:.3f}s (limit: 2.0s)")

    def test_grep_100_files_under_2s(self):
        """Searching across 100 files should complete in <2s."""
        registry = self._get_registry()

        start = time.time()
        result = registry.grep_files("TODO", path=self._grep_dir)
        elapsed = time.time() - start

        print(f"  Grep 100 files: {elapsed*1000:.1f}ms")
        self.assertTrue(result.success, f"Grep failed: {result.error}")
        self.assertLess(elapsed, 2.0, f"Grep took {elapsed:.3f}s (limit: 2.0s)")

    def test_write_1mb_file_under_1s(self):
        """Writing a 1MB file should complete in <1s."""
        registry = self._get_registry()
        content = "x" * (1024 * 1024)  # 1MB of data
        out_path = os.path.join(self._tmpdir, "large_output.txt")

        start = time.time()
        result = registry.write_file(out_path, content)
        elapsed = time.time() - start

        print(f"  Write 1MB file: {elapsed*1000:.1f}ms")
        self.assertTrue(result.success, f"Write failed: {result.error}")
        self.assertLess(elapsed, 1.0, f"Write took {elapsed:.3f}s (limit: 1.0s)")
        # Verify the file was actually written
        self.assertTrue(os.path.exists(out_path))
        self.assertGreaterEqual(os.path.getsize(out_path), 1024 * 1024)


class TestTokenBudgetPerformance(unittest.TestCase):
    """Benchmark TokenBudget consume and thread-safety."""

    def test_10k_consume_ops_under_100ms(self):
        """10K sequential consume operations should complete in <100ms."""
        from agent.token_budget import TokenBudget

        budget = TokenBudget(max_tokens=10_000_000)

        start = time.time()
        for i in range(10_000):
            budget.consume(1)
        elapsed = time.time() - start

        print(f"  10K consume ops: {elapsed*1000:.1f}ms")
        self.assertEqual(budget.used, 10_000)
        self.assertLess(elapsed, 0.1, f"10K consumes took {elapsed:.3f}s (limit: 0.1s)")

    def test_thread_safety_10_threads_1k_ops_under_500ms(self):
        """10 concurrent threads each doing 1K consume ops should finish in <500ms."""
        from agent.token_budget import TokenBudget

        budget = TokenBudget(max_tokens=100_000_000)
        errors = []

        def worker():
            try:
                for _ in range(1_000):
                    budget.consume(1)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(10)]

        start = time.time()
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        elapsed = time.time() - start

        print(f"  10 threads x 1K ops: {elapsed*1000:.1f}ms")
        self.assertEqual(len(errors), 0, f"Thread errors: {errors}")
        self.assertEqual(budget.used, 10_000)
        self.assertLess(elapsed, 0.5, f"Threaded ops took {elapsed:.3f}s (limit: 0.5s)")


class TestContextCompactorPerformance(unittest.TestCase):
    """Benchmark ContextCompactor extractive compaction and classification."""

    def _make_messages(self, count):
        """Generate a list of CompactMessage objects for testing."""
        from agent.services.compact import CompactMessage, MessageRole, PreservePolicy

        messages = []
        roles = [MessageRole.USER, MessageRole.ASSISTANT, MessageRole.TOOL_RESULT]
        for i in range(count):
            role = roles[i % len(roles)]
            content = f"Message {i}: " + ("Some detailed content. " * 10)
            preserve = (
                PreservePolicy.ALWAYS_KEEP
                if role == MessageRole.SYSTEM
                else PreservePolicy.COMPRESSIBLE
            )
            messages.append(CompactMessage(
                role=role,
                content=content,
                token_count=len(content) // 4,
                preserve=preserve,
            ))
        return messages

    def test_compact_100_messages_extractive_under_200ms(self):
        """Extractive compaction of 100 messages should take <200ms."""
        from agent.services.compact import ContextCompactor

        # Use extractive mode (no LLM function)
        compactor = ContextCompactor(
            max_tokens=500_000,
            compact_threshold=0.01,  # Low threshold to force compaction
            target_ratio=0.005,
        )

        messages = self._make_messages(100)

        loop = asyncio.new_event_loop()
        try:
            start = time.time()
            compacted, result = loop.run_until_complete(compactor.compact(messages))
            elapsed = time.time() - start
        finally:
            loop.close()

        print(f"  Compact 100 messages (extractive): {elapsed*1000:.1f}ms")
        print(f"    {result.messages_before} -> {result.messages_after} messages, "
              f"ratio={result.compression_ratio:.3f}")
        self.assertLess(elapsed, 0.2, f"Compaction took {elapsed:.3f}s (limit: 0.2s)")

    def test_classify_1000_messages_under_50ms(self):
        """Classifying 1000 messages should take <50ms."""
        from agent.services.compact import ContextCompactor

        compactor = ContextCompactor(max_tokens=100_000)

        roles = ["user", "assistant", "system", "tool_call", "tool_result"]
        test_cases = [
            (roles[i % len(roles)], f"Content for message {i}", i % 7 == 0)
            for i in range(1_000)
        ]

        start = time.time()
        results = []
        for role, content, is_error in test_cases:
            results.append(compactor.classify_message(role, content, is_error=is_error))
        elapsed = time.time() - start

        print(f"  classify_message x1000: {elapsed*1000:.1f}ms")
        self.assertEqual(len(results), 1_000)
        self.assertLess(elapsed, 0.05, f"Classification took {elapsed:.3f}s (limit: 0.05s)")


class TestSearchPerformance(unittest.TestCase):
    """Benchmark SemanticSearchTool indexing (without real embeddings)."""

    def test_index_100_files_under_5s(self):
        """Indexing 100 Python files (TF-IDF fallback) should take <5s."""
        from agent.tools.semantic_search import SemanticSearchTool

        # Use a temp dir for the index
        with tempfile.TemporaryDirectory(prefix="neomind_perf_search_") as tmpdir:
            tool = SemanticSearchTool(index_path=Path(tmpdir))

            # Generate 100 realistic Python files
            files = []
            for i in range(100):
                content_lines = [
                    f'"""Module {i} - auto-generated for performance testing."""',
                    f"import os",
                    f"import sys",
                    f"",
                    f"class Handler{i}:",
                    f'    """Handler for operation {i}."""',
                    f"",
                    f"    def __init__(self):",
                    f"        self.value = {i}",
                    f"        self.name = 'handler_{i}'",
                    f"",
                    f"    def process(self, data):",
                    f"        result = data * self.value",
                    f"        return result",
                    f"",
                ]
                # Pad to ~50 lines for realistic chunk sizes
                for j in range(35):
                    content_lines.append(
                        f"    def method_{j}(self, x): return x + {j}"
                    )
                content = "\n".join(content_lines)
                files.append((f"src/module_{i:03d}.py", content))

            start = time.time()
            stats = tool.index_files(files)
            elapsed = time.time() - start

            print(f"  Index 100 files: {elapsed*1000:.1f}ms")
            print(f"    files_indexed={stats['files_indexed']}, "
                  f"chunks_created={stats['chunks_created']}, "
                  f"errors={len(stats['errors'])}")
            self.assertEqual(stats['files_indexed'], 100)
            self.assertEqual(len(stats['errors']), 0)
            self.assertLess(elapsed, 5.0, f"Indexing took {elapsed:.3f}s (limit: 5.0s)")


class TestFinancePerformance(unittest.TestCase):
    """Benchmark PerformanceTracker snapshot recording and metric calculation."""

    def test_record_10k_snapshots_under_500ms(self):
        """Recording 10K daily snapshots should complete in <500ms."""
        from agent.finance.performance_tracker import PerformanceTracker

        tracker = PerformanceTracker(initial_capital=100_000.0)
        base_equity = 100_000.0

        start = time.time()
        for i in range(10_000):
            # Simulate small daily changes
            equity = base_equity + (i % 100) * 10 - 500
            tracker.record_snapshot(
                date=f"2025-{(i // 30) % 12 + 1:02d}-{(i % 28) + 1:02d}",
                equity=equity,
                cash=equity * 0.3,
                positions_value=equity * 0.7,
                trades_count=i % 5,
            )
        elapsed = time.time() - start

        print(f"  Record 10K snapshots: {elapsed*1000:.1f}ms")
        self.assertLess(elapsed, 0.5, f"Recording took {elapsed:.3f}s (limit: 0.5s)")

    def test_calculate_metrics_1k_snapshots_under_200ms(self):
        """Calculating metrics with 1K snapshots should complete in <200ms."""
        from agent.finance.performance_tracker import PerformanceTracker

        tracker = PerformanceTracker(initial_capital=100_000.0)

        # Build up 1K snapshots with realistic daily returns
        equity = 100_000.0
        import random
        rng = random.Random(42)  # Deterministic seed
        for i in range(1_000):
            daily_return = rng.gauss(0.0005, 0.015)  # ~12% annualized, ~15% vol
            equity *= (1 + daily_return)
            tracker.record_snapshot(
                date=f"2024-{(i // 30) % 12 + 1:02d}-{(i % 28) + 1:02d}",
                equity=equity,
                cash=equity * 0.2,
                positions_value=equity * 0.8,
                trades_count=rng.randint(0, 3),
            )
            # Record some trades for trade-level metrics
            if i % 5 == 0:
                pnl = rng.gauss(50, 200)
                tracker.record_trade(
                    symbol=f"SYM{i % 10}",
                    side="buy" if pnl > 0 else "sell",
                    quantity=rng.randint(1, 100),
                    price=rng.uniform(10, 500),
                    pnl=pnl,
                )

        start = time.time()
        metrics = tracker.calculate_metrics()
        elapsed = time.time() - start

        print(f"  Calculate metrics (1K snapshots): {elapsed*1000:.1f}ms")
        print(f"    total_return={metrics.total_return_pct:.2f}%, "
              f"sharpe={metrics.sharpe_ratio:.2f}, "
              f"max_dd={metrics.max_drawdown_pct:.2f}%")
        self.assertLess(elapsed, 0.2, f"Metrics took {elapsed:.3f}s (limit: 0.2s)")
        # Sanity checks on metrics
        self.assertEqual(metrics.total_trades, 200)
        self.assertGreater(metrics.win_rate_pct, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
