"""
Token Budget System for NeoMind Agent.

Manages token budget per conversation to prevent context overflow.
Inspired by Claude Code's token budget architecture.

Created: 2026-04-01
Phase: 0 - Infrastructure
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
from datetime import datetime
import threading
import json


@dataclass
class TokenUsage:
    """Token usage record."""
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    tool_result_tokens: int = 0
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)


class TokenBudget:
    """
    Token预算管理器。

    负责追踪和管理对话中的token使用量，
    在超出预算时触发压缩或警告。

    Inspired by Claude Code's token budget system.
    """

    # 默认配置
    DEFAULT_MAX_TOKENS = 100000  # 100K tokens
    WARNING_THRESHOLD = 0.8   # 80% 时警告
    COMPACT_THRESHOLD = 0.9  # 90% 时触发压缩
    MAX_TOOL_RESULT_SIZE = 100 * 1024  # 100KB

    def __init__(self, max_tokens: int = DEFAULT_MAX_TOKENS):
        """
        初始化Token预算管理器。

        Args:
            max_tokens: 最大token数量 (默认100K)
        """
        self.max_tokens = max_tokens
        self._used = 0
        self._reserved = 0
        self._lock = threading.Lock()

        # 使用历史
        self._usage_history: List[TokenUsage] = []
        self._tool_result_storage: Dict[str, str] = {}
        self._compaction_count = 0
        self._last_compaction_time: Optional[datetime] = None

    @property
    def used(self) -> int:
        """已使用的token数量。"""
        return self._used

    @property
    def reserved(self) -> int:
        """已预留的token数量。"""
        return self._reserved

    def remaining(self) -> int:
        """
        剩余可用token数量。

        Returns:
            剩余token数量，不会小于0
        """
        with self._lock:
            return max(0, self.max_tokens - self._used - self._reserved)

    def usage_ratio(self) -> float:
        """
        当前使用比率。

        Returns:
            使用量占最大值的比例 (0.0 - 1.0+)
        """
        with self._lock:
            return (self._used + self._reserved) / self.max_tokens

    def can_proceed(self, estimated_tokens: int) -> bool:
        """
        检查是否有足够预算执行操作。

        Args:
            estimated_tokens: 预估需要的token数量

        Returns:
            True 如果有足够预算
        """
        with self._lock:
            return (self._used + self._reserved + estimated_tokens) < self.max_tokens

    def reserve(self, tokens: int) -> bool:
        """
        预留token预算。

        用于在执行前预留预算，防止并发操作超出限制。

        Args:
            tokens: 需要预留的token数量

        Returns:
            True 如果预留成功，False 如果预算不足
        """
        with self._lock:
            if not self.can_proceed(tokens):
                return False
            self._reserved += tokens
            return True

    def consume(self, tokens: int, input_tokens: int = 0, output_tokens: int = 0,
                cached_tokens: int = 0, metadata: Optional[Dict] = None) -> None:
        """
        消耗token预算并记录使用情况。

        Args:
            tokens: 总消耗token数量
            input_tokens: 输入token数量
            output_tokens: 输出token数量
            cached_tokens: 缓存token数量
            metadata: 额外元数据
        """
        with self._lock:
            self._used += tokens
            self._reserved = max(0, self._reserved - tokens)

            # 记录使用历史
            usage = TokenUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cached_tokens=cached_tokens,
                tool_result_tokens=tokens - input_tokens - output_tokens - cached_tokens if tokens > input_tokens + output_tokens + cached_tokens else 0,
                metadata=metadata or {}
            )
            self._usage_history.append(usage)

    def release(self, tokens: int) -> None:
        """
        释放预留的token。

        用于操作失败时释放之前预留的预算。

        Args:
            tokens: 要释放的token数量
        """
        with self._lock:
            self._reserved = max(0, self._reserved - tokens)

    def should_warn(self) -> bool:
        """
        检查是否应该发出警告。

        Returns:
            True 如果使用量超过警告阈值
        """
        return self.usage_ratio() >= self.WARNING_THRESHOLD

    def should_compact(self) -> bool:
        """
        检查是否需要压缩上下文。

        Returns:
            True 如果使用量超过压缩阈值
        """
        return self.usage_ratio() >= self.COMPACT_THRESHOLD

    def needs_compaction(self) -> bool:
        """Alias for should_compact()."""
        return self.should_compact()

    def record_compaction(self, tokens_saved: int) -> None:
        """
        记录压缩事件。

        Args:
            tokens_saved: 压缩节省的token数量
        """
        with self._lock:
            self._used = max(0, self._used - tokens_saved)
            self._compaction_count += 1
            self._last_compaction_time = datetime.now()

    def store_tool_result(self, result_id: str, content: str) -> str:
        """
        存储大型工具结果到磁盘。

        当工具结果超过100KB时，将内容持久化到磁盘，
        只保留预览和文件路径在内存中。

        Args:
            result_id: 结果唯一标识
            content: 工具结果内容

        Returns:
            如果内容过大，返回带文件路径的预览；否则返回原内容
        """
        if len(content) <= self.MAX_TOOL_RESULT_SIZE:
            return content

        # 存储到磁盘
        import os
        import tempfile

        storage_dir = Path(tempfile.gettempdir()) / "neomind_tool_results"
        storage_dir.mkdir(parents=True, exist_ok=True)

        file_path = storage_dir / f"{result_id}.json"

        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump({
                "content": content,
                "size": len(content),
                "timestamp": datetime.now().isoformat()
            }, f)

        self._tool_result_storage[result_id] = str(file_path)

        # 返回预览
        preview = content[:2000]
        return f"{preview}\n\n[Full output ({len(content):,} bytes) saved to {file_path}]"

    def get_stored_result(self, result_id: str) -> Optional[str]:
        """
        获取存储的工具结果。

        Args:
            result_id: 结果唯一标识

        Returns:
            存储的内容，如果不存在返回None
        """
        if result_id in self._tool_result_storage:
            file_path = Path(self._tool_result_storage[result_id])
            if file_path.exists():
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data.get("content")
        return None

    def clear_stored_results(self) -> int:
        """
        清除所有存储的工具结果。

        Returns:
            清除的文件数量
        """
        count = 0
        for result_id, file_path in list(self._tool_result_storage.items()):
            try:
                Path(file_path).unlink()
                count += 1
            except Exception:
                pass
        self._tool_result_storage.clear()
        return count

    def get_stats(self) -> Dict[str, Any]:
        """
        获取token使用统计。

        Returns:
            包含使用统计的字典
        """
        with self._lock:
            total_input = sum(u.input_tokens for u in self._usage_history)
            total_output = sum(u.output_tokens for u in self._usage_history)
            total_cached = sum(u.cached_tokens for u in self._usage_history)

            return {
                "max_tokens": self.max_tokens,
                "used": self._used,
                "reserved": self._reserved,
                "remaining": self.remaining(),
                "usage_ratio": self.usage_ratio(),
                "should_warn": self.should_warn(),
                "should_compact": self.should_compact(),
                "compaction_count": self._compaction_count,
                "last_compaction": self._last_compaction_time.isoformat() if self._last_compaction_time else None,
                "usage_history_count": len(self._usage_history),
                "total_input_tokens": total_input,
                "total_output_tokens": total_output,
                "total_cached_tokens": total_cached,
                "stored_results_count": len(self._tool_result_storage),
            }

    def reset(self) -> None:
        """
        重置预算管理器。

        清除所有使用记录和存储的结果。
        """
        with self._lock:
            self._used = 0
            self._reserved = 0
            self._usage_history.clear()
            self.clear_stored_results()
            self._compaction_count = 0
            self._last_compaction_time = None

    def adjust_max_tokens(self, new_max: int) -> None:
        """
        调整最大token数量。

        Args:
            new_max: 新的最大token数量
        """
        with self._lock:
            self.max_tokens = new_max


# 导出
__all__ = ['TokenBudget', 'TokenUsage']


if __name__ == "__main__":
    # 简单测试
    budget = TokenBudget(100000)

    print(f"Initial remaining: {budget.remaining()}")

    budget.consume(10000, input_tokens=8000, output_tokens=2000)
    print(f"After consume: {budget.remaining()}")
    print(f"Usage ratio: {budget.usage_ratio():.2%}")

    print(f"Should warn: {budget.should_warn()}")

    budget.reserve(50000)
    print(f"After reserve: {budget.remaining()}")

    budget.consume(30000)
    print(f"Should compact: {budget.should_compact()}")

    print(f"\nStats: {budget.get_stats()}")
