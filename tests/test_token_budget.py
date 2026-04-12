"""
Unit tests for TokenBudget system.

Phase 0 - Infrastructure
"""

import pytest
import threading
import time
from datetime import datetime
from agent.token_budget import TokenBudget, TokenUsage


class TestTokenBudget:
    """Token预算管理器单元测试。"""

    # ── Fixtures ─────────────────────────────────────

    @pytest.fixture
    def budget(self):
        """创建默认预算管理器。"""
        return TokenBudget(100000)

    @pytest.fixture
    def small_budget(self):
        """创建小容量预算管理器。"""
        return TokenBudget(1000)

    # ── 基础功能测试 ─────────────────────────────────

    def test_initial_budget_is_max(self, budget):
        """测试初始预算等于最大值。"""
        assert budget.remaining() == 100000
        assert budget.used == 0
        assert budget.reserved == 0

    def test_consume_reduces_remaining(self, budget):
        """测试消耗预算后剩余量减少。"""
        budget.consume(10000)
        assert budget.remaining() == 90000
        assert budget.used == 10000

    def test_reserve_blocks_tokens(self, budget):
        """测试预留预算会锁定token。"""
        assert budget.reserve(5000) is True
        assert budget.remaining() == 95000
        assert budget.reserved == 5000

    def test_reserve_fails_when_insufficient(self, small_budget):
        """测试预算不足时预留失败。"""
        small_budget.consume(950)
        assert small_budget.reserve(100) is False
        assert small_budget.reserved == 0

    def test_can_proceed_checks_availability(self, budget):
        """测试can_proceed正确检查可用性。"""
        assert budget.can_proceed(50000) is True
        budget.consume(80000)
        assert budget.can_proceed(50000) is False

    # ── 警告和压缩阈值测试 ─────────────────────────────

    def test_should_warn_at_threshold(self, budget):
        """测试在警告阈值时触发警告。"""
        assert budget.should_warn() is False
        budget.consume(80000)
        assert budget.should_warn() is True

    def test_should_compact_at_threshold(self, budget):
        """测试在压缩阈值时触发压缩。"""
        assert budget.should_compact() is False
        budget.consume(90000)
        assert budget.should_compact() is True

    def test_needs_compaction_alias(self, budget):
        """测试needs_compaction是should_compact的别名。"""
        budget.consume(90000)
        assert budget.needs_compaction() == budget.should_compact()

    # ── 释放和重置测试 ─────────────────────────────────

    def test_release_frees_reserved(self, budget):
        """测试释放预留的预算。"""
        budget.reserve(5000)
        budget.release(3000)
        assert budget.reserved == 2000

    def test_release_never_negative(self, budget):
        """测试释放不会导致预留量为负。"""
        budget.reserve(5000)
        budget.release(10000)  # 释放比预留更多
        assert budget.reserved == 0

    def test_reset_clears_all(self, budget):
        """测试重置清除所有状态。"""
        budget.consume(50000)
        budget.reserve(10000)
        budget.reset()
        assert budget.remaining() == 100000
        assert budget.used == 0
        assert budget.reserved == 0

    # ── 边界条件测试 ─────────────────────────────────

    def test_remaining_never_negative(self, budget):
        """测试剩余量永远不会为负。"""
        budget.consume(150000)  # 超过最大值
        assert budget.remaining() == 0

    def test_consume_with_detailed_tokens(self, budget):
        """测试带详细token信息的消耗。"""
        budget.consume(
            tokens=15000,
            input_tokens=10000,
            output_tokens=4000,
            cached_tokens=1000,
            metadata={"model": "test"}
        )
        assert budget.used == 15000
        assert len(budget._usage_history) == 1
        usage = budget._usage_history[0]
        assert usage.input_tokens == 10000
        assert usage.output_tokens == 4000
        assert usage.cached_tokens == 1000

    def test_usage_ratio(self, budget):
        """测试使用比率计算。"""
        assert budget.usage_ratio() == 0.0
        budget.consume(50000)
        assert budget.usage_ratio() == 0.5
        budget.consume(50000)
        assert budget.usage_ratio() == 1.0

    # ── 并发安全测试 ─────────────────────────────────

    def test_concurrent_access_thread_safety(self, budget):
        """测试并发访问线程安全。"""
        errors = []

        def consume_task():
            try:
                for _ in range(100):
                budget.consume(1)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=consume_task) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0  # 允许一个可能的竞争条件
        assert budget.used == 1000

    def test_concurrent_reserve(self, budget):
        """测试并发预留。"""
        success_count = [0]

        def reserve_task():
            if budget.reserve(10000):
                success_count[0] += 1

        threads = [threading.Thread(target=reserve_task) for _ in range(15)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 最多只有10个能成功预留
        assert success_count[0] <= 10

    # ── 工具结果存储测试 ───────────────────────────────

    def test_store_tool_result_small(self, budget):
        """测试小型工具结果不存储。"""
        small_content = "x" * 1000  # 1KB
        result = budget.store_tool_result("test_id", small_content)
        assert result == small_content
        assert "test_id" not in budget._tool_result_storage

    def test_store_tool_result_large(self, budget):
        """测试大型工具结果被存储。"""
        large_content = "x" * (150 * 1024)  # 150KB
        result = budget.store_tool_result("large_id", large_content)

        assert "[Full output" in result
        assert "saved to" in result
        assert "large_id" in budget._tool_result_storage

    def test_get_stored_result(self, budget):
        """测试获取存储的结果。"""
        large_content = "x" * (150 * 1024)
        budget.store_tool_result("test_id", large_content)

        retrieved = budget.get_stored_result("test_id")
        assert retrieved == large_content

    def test_get_stored_result_not_found(self, budget):
        """测试获取不存在的结果。"""
        result = budget.get_stored_result("nonexistent")
        assert result is None

    def test_clear_stored_results(self, budget):
        """测试清除存储的结果。"""
        large_content = "x" * (150 * 1024)
        budget.store_tool_result("id1", large_content)
        budget.store_tool_result("id2", large_content)

        count = budget.clear_stored_results()
        assert count == 2
        assert len(budget._tool_result_storage) == 0

    # ── 压缩记录测试 ─────────────────────────────────

    def test_record_compaction(self, budget):
        """测试记录压缩事件。"""
        budget.consume(50000)
        budget.record_compaction(30000)

        assert budget.used == 20000
        assert budget._compaction_count == 1
        assert budget._last_compaction_time is not None

    # ── 统计信息测试 ─────────────────────────────────

    def test_get_stats(self, budget):
        """测试获取统计信息。"""
        budget.consume(50000, input_tokens=30000, output_tokens=20000)
        stats = budget.get_stats()

        assert stats["max_tokens"] == 100000
        assert stats["used"] == 50000
        assert stats["remaining"] == 50000
        assert stats["usage_ratio"] == 0.5
        assert stats["total_input_tokens"] == 30000
        assert stats["total_output_tokens"] == 20000
        assert stats["usage_history_count"] == 1

    def test_get_stats_after_compaction(self, budget):
        """测试压缩后的统计信息。"""
        budget.consume(90000)
        budget.record_compaction(50000)
        stats = budget.get_stats()

        assert stats["compaction_count"] == 1
        assert stats["last_compaction"] is not None

    # ── 调整最大值测试 ─────────────────────────────────

    def test_adjust_max_tokens(self, budget):
        """测试调整最大token数量。"""
        budget.consume(50000)
        budget.adjust_max_tokens(200000)

        assert budget.max_tokens == 200000
        assert budget.remaining() == 150000

    # ── 压力测试 ─────────────────────────────────

    def test_many_operations(self, budget):
        """测试大量操作的性能。"""
        start_time = time.time()

        for i in range(1000):
            budget.consume(10)
            if i % 100 == 0:
                budget.reserve(5)
                budget.release(5)

        elapsed = time.time() - start_time
        assert elapsed < 1.0  # 应该在1秒内完成
        assert budget.used == 10000


class TestTokenUsage:
    """TokenUsage数据类测试。"""

    def test_default_values(self):
        """测试默认值。"""
        usage = TokenUsage()
        assert usage.input_tokens == 0
        assert usage.output_tokens == 0
        assert usage.cached_tokens == 0
        assert usage.metadata == {}

    def test_custom_values(self):
        """测试自定义值。"""
        metadata = {"model": "test", "provider": "deepseek"}
        usage = TokenUsage(
            input_tokens=1000,
            output_tokens=500,
            cached_tokens=200,
            metadata=metadata
        )
        assert usage.input_tokens == 1000
        assert usage.output_tokens == 500
        assert usage.cached_tokens == 200
        assert usage.metadata == metadata


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
