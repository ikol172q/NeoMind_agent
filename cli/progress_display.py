# cli/progress_display.py
"""Advanced progress display system similar to advanced CLI."""

import time
import threading
from typing import Dict, List, Optional, Tuple, Callable
from enum import Enum
import sys
import math


class TaskStatus(Enum):
    """Task status enum."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    WARNING = "warning"
    SKIPPED = "skipped"


class ProgressDisplay:
    """Advanced progress display system with multiple tasks and statistics."""

    # Rich status words (Chinese and English)
    STATUS_WORDS = {
        TaskStatus.IN_PROGRESS: {
            "zh": [
                "分析中", "处理中", "执行中", "探索中", "思考中",
                "等待中", "加载中", "编译中", "构建中", "测试中",
                "部署中", "优化中", "搜索中", "下载中", "上传中",
                "验证中", "同步中", "备份中", "恢复中", "扫描中",
                "计算中", "渲染中", "转换中", "加密中", "解密中"
            ],
            "en": [
                "Analyzing", "Processing", "Executing", "Exploring", "Thinking",
                "Waiting", "Loading", "Compiling", "Building", "Testing",
                "Deploying", "Optimizing", "Searching", "Downloading", "Uploading",
                "Verifying", "Syncing", "Backing up", "Restoring", "Scanning",
                "Calculating", "Rendering", "Converting", "Encrypting", "Decrypting"
            ]
        },
        TaskStatus.COMPLETED: {
            "zh": [
                "完成", "成功", "已完成", "已成功", "完毕",
                "结束", "达成", "搞定", "解决", "通过",
                "验收", "交付", "发布", "上线", "部署完成",
                "测试通过", "构建成功", "编译完成", "分析完成", "处理完成"
            ],
            "en": [
                "Done", "Success", "Completed", "Succeeded", "Finished",
                "Ended", "Achieved", "Done", "Resolved", "Passed",
                "Accepted", "Delivered", "Published", "Launched", "Deployed",
                "Tests passed", "Build succeeded", "Compiled", "Analyzed", "Processed"
            ]
        },
        TaskStatus.FAILED: {
            "zh": [
                "失败", "错误", "异常", "崩溃", "中断",
                "超时", "拒绝", "冲突", "丢失", "损坏",
                "无效", "不支持", "未找到", "已存在", "权限不足",
                "资源不足", "连接失败", "验证失败", "编译失败", "测试失败"
            ],
            "en": [
                "Failed", "Error", "Exception", "Crashed", "Interrupted",
                "Timeout", "Rejected", "Conflict", "Lost", "Corrupted",
                "Invalid", "Not supported", "Not found", "Already exists", "Permission denied",
                "Insufficient resources", "Connection failed", "Verification failed", "Compilation failed", "Tests failed"
            ]
        }
    }

    def __init__(self, language: str = "en", max_tasks: int = 5):
        """
        Initialize progress display.

        Args:
            language: Display language ('zh' or 'en')
            max_tasks: Maximum number of tasks to display simultaneously
        """
        self.language = language if language in ["zh", "en"] else "en"
        self.max_tasks = max_tasks
        # Unicode support (disable on Windows due to encoding issues)
        self.use_unicode = sys.platform != "win32"
        self.tasks: Dict[str, Dict] = {}
        self.task_order: List[str] = []
        self.lock = threading.RLock()
        self.start_time = time.time()
        self.total_tool_uses = 0
        self.total_tokens = 0

        # Display configuration
        self.show_statistics = True
        self.show_time = True
        self.compact_mode = False

    def _generate_task_id(self) -> str:
        """Generate a unique task ID."""
        with self.lock:
            return f"task_{len(self.tasks)}_{int(time.time() * 1000)}"

    def _get_status_word(self, status: TaskStatus, index: int = 0) -> str:
        """Get a status word for the given status."""
        words = self.STATUS_WORDS.get(status, {}).get(self.language, [])
        if not words:
            # Default words
            if status == TaskStatus.IN_PROGRESS:
                return "In progress" if self.language == "en" else "进行中"
            elif status == TaskStatus.COMPLETED:
                return "Done" if self.language == "en" else "完成"
            elif status == TaskStatus.FAILED:
                return "Failed" if self.language == "en" else "失败"
            else:
                return status.value

        # Use index to get different word each time
        idx = index % len(words)
        return words[idx]

    def start_task(self, title: str, description: str = "",
                   tool_uses: int = 0, tokens: int = 0) -> str:
        """
        Start a new task.

        Args:
            title: Task title
            description: Task description
            tool_uses: Initial tool uses count
            tokens: Initial token count

        Returns:
            Task ID
        """
        with self.lock:
            task_id = self._generate_task_id()

            # Create task entry
            self.tasks[task_id] = {
                "title": title,
                "description": description,
                "status": TaskStatus.IN_PROGRESS,
                "start_time": time.time(),
                "end_time": None,
                "tool_uses": tool_uses,
                "tokens": tokens,
                "status_index": 0,  # For cycling through status words
                "visible": True,
                "expanded": False
            }

            # Add to order and limit display
            self.task_order.append(task_id)
            if len(self.task_order) > self.max_tasks:
                # Remove oldest completed task
                for old_id in self.task_order[:-self.max_tasks]:
                    if self.tasks[old_id]["status"] != TaskStatus.IN_PROGRESS:
                        self.task_order.remove(old_id)
                        del self.tasks[old_id]
                        break

            # Update global statistics
            self.total_tool_uses += tool_uses
            self.total_tokens += tokens

            return task_id

    def update_task(self, task_id: str,
                    status: Optional[TaskStatus] = None,
                    tool_uses: Optional[int] = None,
                    tokens: Optional[int] = None,
                    title: Optional[str] = None,
                    description: Optional[str] = None) -> bool:
        """
        Update task progress.

        Args:
            task_id: Task ID to update
            status: New status
            tool_uses: Additional tool uses
            tokens: Additional tokens
            title: New title
            description: New description

        Returns:
            True if task was updated
        """
        with self.lock:
            if task_id not in self.tasks:
                return False

            task = self.tasks[task_id]

            if status is not None:
                task["status"] = status
                if status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED]:
                    task["end_time"] = time.time()
                elif status == TaskStatus.IN_PROGRESS:
                    task["status_index"] = (task["status_index"] + 1) % 20  # Cycle status words

            if tool_uses is not None:
                delta = tool_uses - task["tool_uses"]
                task["tool_uses"] = tool_uses
                self.total_tool_uses += delta

            if tokens is not None:
                delta = tokens - task["tokens"]
                task["tokens"] = tokens
                self.total_tokens += delta

            if title is not None:
                task["title"] = title

            if description is not None:
                task["description"] = description

            return True

    def complete_task(self, task_id: str,
                      tool_uses: Optional[int] = None,
                      tokens: Optional[int] = None) -> bool:
        """Mark task as completed."""
        return self.update_task(task_id, TaskStatus.COMPLETED, tool_uses, tokens)

    def fail_task(self, task_id: str,
                  tool_uses: Optional[int] = None,
                  tokens: Optional[int] = None) -> bool:
        """Mark task as failed."""
        return self.update_task(task_id, TaskStatus.FAILED, tool_uses, tokens)

    def _format_duration(self, seconds: float) -> str:
        """Format duration in a human-readable way."""
        if seconds < 1:
            return f"{seconds*1000:.0f}ms"
        elif seconds < 60:
            return f"{seconds:.1f}s"
        elif seconds < 3600:
            minutes = int(seconds // 60)
            secs = seconds % 60
            return f"{minutes}m {secs:.0f}s"
        else:
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            return f"{hours}h {minutes}m"

    def _format_statistics(self, task: Dict) -> str:
        """Format task statistics."""
        parts = []

        # Tool uses
        if task["tool_uses"] > 0:
            parts.append(f"{task['tool_uses']} tool uses")

        # Tokens
        if task["tokens"] > 0:
            # Format tokens with K/M suffix
            tokens = task["tokens"]
            if tokens >= 1_000_000:
                token_str = f"{tokens/1_000_000:.1f}M"
            elif tokens >= 1_000:
                token_str = f"{tokens/1_000:.1f}K"
            else:
                token_str = f"{tokens}"
            parts.append(f"{token_str} tokens")

        # Duration
        if task["start_time"]:
            end_time = task["end_time"] or time.time()
            duration = end_time - task["start_time"]
            if duration > 0.1:  # Only show if significant
                parts.append(self._format_duration(duration))

        if parts:
            separator = "·" if self.use_unicode else "|"
            return separator.join(parts)
        return ""

    def display(self, clear_previous: bool = True) -> str:
        """
        Display current tasks.

        Args:
            clear_previous: Whether to clear previous output

        Returns:
            Formatted display string
        """
        with self.lock:
            # Filter visible tasks
            visible_tasks = []
            for task_id in self.task_order:
                if task_id in self.tasks and self.tasks[task_id].get("visible", True):
                    visible_tasks.append((task_id, self.tasks[task_id]))

            if not visible_tasks:
                return ""

            lines = []

            for task_id, task in visible_tasks:
                # Determine status icon and color
                status = task["status"]

                # Select icons based on Unicode support
                if self.use_unicode:
                    if status == TaskStatus.IN_PROGRESS:
                        icon = "●"
                    elif status == TaskStatus.COMPLETED:
                        icon = "✓"
                    elif status == TaskStatus.FAILED:
                        icon = "✗"
                    elif status == TaskStatus.WARNING:
                        icon = "⚠"
                    else:
                        icon = "○"
                else:
                    # ASCII fallback icons
                    if status == TaskStatus.IN_PROGRESS:
                        icon = "*"
                    elif status == TaskStatus.COMPLETED:
                        icon = "+"
                    elif status == TaskStatus.FAILED:
                        icon = "x"
                    elif status == TaskStatus.WARNING:
                        icon = "!"
                    else:
                        icon = "o"

                # Colors
                if status == TaskStatus.IN_PROGRESS:
                    color = "\033[93m"  # Yellow
                    status_word = self._get_status_word(status, task["status_index"])
                elif status == TaskStatus.COMPLETED:
                    color = "\033[92m"  # Green
                    status_word = self._get_status_word(status, task["status_index"])
                elif status == TaskStatus.FAILED:
                    color = "\033[91m"  # Red
                    status_word = self._get_status_word(status, task["status_index"])
                elif status == TaskStatus.WARNING:
                    color = "\033[93m"  # Yellow
                    status_word = "Warning"
                else:
                    color = "\033[90m"  # Gray
                    status_word = status.value

                # Reset color
                reset = "\033[0m"
                # Prefix for status line
                prefix = "⎿" if self.use_unicode else "->"
                # Separator for statistics
                separator = "·" if self.use_unicode else "|"

                # Build title line
                title_line = f"{color}{icon} {task['title']}{reset}"

                # Add description if available and (expanded or still in progress)
                if task.get("description") and (task.get("expanded") or status == TaskStatus.IN_PROGRESS):
                    desc_lines = task["description"].split('\n')
                    for desc_line in desc_lines[:3]:  # Limit description lines
                        lines.append(f"  {desc_line}")

                # Build status line
                stats = self._format_statistics(task)
                if stats:
                    if status == TaskStatus.IN_PROGRESS:
                        status_line = f"  {color}{prefix} {status_word} {separator} {stats}{reset}"
                    else:
                        status_line = f"  {color}{prefix} {status_word} ({stats}){reset}"
                else:
                    if status == TaskStatus.IN_PROGRESS:
                        status_line = f"  {color}{prefix} {status_word}...{reset}"
                    else:
                        status_line = f"  {color}{prefix} {status_word}{reset}"

                # Add expand/collapse hint for tasks with description
                if task.get("description") and not task.get("expanded"):
                    status_line += f" {color}(ctrl+o to expand){reset}"

                # Add background run hint for long-running tasks
                if status == TaskStatus.IN_PROGRESS and task.get("start_time"):
                    duration = time.time() - task["start_time"]
                    if duration > 30:  # After 30 seconds
                        status_line += f" {color}(ctrl+b to run in background){reset}"

                lines.append(title_line)
                lines.append(status_line)
                lines.append("")  # Empty line between tasks

            # Add global statistics if enabled
            if self.show_statistics and (self.total_tool_uses > 0 or self.total_tokens > 0):
                global_stats = []
                if self.total_tool_uses > 0:
                    global_stats.append(f"{self.total_tool_uses} tool uses")
                if self.total_tokens > 0:
                    if self.total_tokens >= 1_000_000:
                        token_str = f"{self.total_tokens/1_000_000:.1f}M"
                    elif self.total_tokens >= 1_000:
                        token_str = f"{self.total_tokens/1_000:.1f}K"
                    else:
                        token_str = f"{self.total_tokens}"
                    global_stats.append(f"{token_str} tokens")
                if global_stats:
                    separator = "·" if self.use_unicode else "|"
                    lines.append(f"\033[90mGlobal: {separator.join(global_stats)}\033[0m")

            return "\n".join(lines)

    def clear_completed(self, retention_seconds: float = 0.0) -> int:
        """Clear completed tasks and return number cleared.

        Args:
            retention_seconds: How long to keep completed tasks before clearing.
                               Default 0.0 clears immediately (backward compatibility).
        """
        with self.lock:
            to_remove = []
            current_time = time.time()
            for task_id in list(self.tasks.keys()):
                task = self.tasks[task_id]
                if task["status"] in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED]:
                    # Check retention period
                    end_time = task.get("end_time")
                    if end_time and current_time - end_time >= retention_seconds:
                        to_remove.append(task_id)
                    elif not end_time:
                        # No end_time set, remove immediately
                        to_remove.append(task_id)

            for task_id in to_remove:
                if task_id in self.tasks:
                    del self.tasks[task_id]
                if task_id in self.task_order:
                    self.task_order.remove(task_id)

            return len(to_remove)

    def toggle_task_expansion(self, task_id: str = None) -> bool:
        """Toggle expansion of a task. If no task_id provided, toggles most recent task."""
        with self.lock:
            if task_id is None:
                # Find most recent task with description
                for tid in reversed(self.task_order):
                    if tid in self.tasks and self.tasks[tid].get("description"):
                        task_id = tid
                        break
            if task_id not in self.tasks:
                return False
            task = self.tasks[task_id]
            if not task.get("description"):
                return False
            task["expanded"] = not task.get("expanded", False)
            return True

    def get_task(self, task_id: str) -> Optional[Dict]:
        """Get task by ID."""
        with self.lock:
            return self.tasks.get(task_id)

    def get_active_tasks(self) -> List[Dict]:
        """Get all active (in-progress) tasks."""
        with self.lock:
            return [
                task for task in self.tasks.values()
                if task["status"] == TaskStatus.IN_PROGRESS
            ]


# Global instance for easy access
_global_progress = None

def get_global_progress(language: str = "en") -> ProgressDisplay:
    """Get or create global progress display instance."""
    global _global_progress
    if _global_progress is None:
        _global_progress = ProgressDisplay(language=language)
    return _global_progress


def format_simple_status(task_title: str, status: str = "executing") -> str:
    """Format a simple status message for copy-paste friendly display."""
    icons = {
        "executing": "->",
        "completed": "[OK]",
        "failed": "[ERROR]",
        "thinking": "[THINKING]",
        "searching": "[SEARCHING]"
    }
    icon = icons.get(status, "")
    return f"{icon} {task_title}" if icon else task_title