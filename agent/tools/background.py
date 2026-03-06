"""
Background task system for async execution of long-running tools.

Provides:
- BackgroundTask: Represents an async task with status tracking
- BackgroundTaskQueue: Manages queuing and execution of background tasks
- TaskMonitor: Monitors task progress and provides status updates
- AsyncExecutor: Executes async tools with timeouts and cancellation
"""

import asyncio
import threading
import time
import uuid
from typing import Dict, List, Any, Optional, Callable, Union, Tuple
from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime
import traceback
import queue

from .base import AsyncTool, Tool, ToolError, ToolExecutionError
from ..safety import log_operation


class TaskStatus(Enum):
    """Status of a background task."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


@dataclass
class BackgroundTask:
    """Represents a background task."""

    task_id: str
    tool_name: str
    tool_instance: Any
    parameters: Dict[str, Any]
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None
    error: Optional[str] = None
    progress: float = 0.0  # 0.0 to 1.0
    progress_message: Optional[str] = None
    timeout: Optional[float] = None  # seconds
    max_retries: int = 0
    retry_count: int = 0
    cancellation_requested: bool = False
    tags: List[str] = field(default_factory=list)

    def update_progress(self, progress: float, message: Optional[str] = None) -> None:
        """Update task progress."""
        self.progress = max(0.0, min(1.0, progress))
        if message:
            self.progress_message = message

    def start(self) -> None:
        """Mark task as started."""
        self.started_at = datetime.now()
        self.status = TaskStatus.RUNNING

    def complete(self, result: Any) -> None:
        """Mark task as completed successfully."""
        self.completed_at = datetime.now()
        self.status = TaskStatus.COMPLETED
        self.result = result
        self.progress = 1.0

    def fail(self, error: str) -> None:
        """Mark task as failed."""
        self.completed_at = datetime.now()
        self.status = TaskStatus.FAILED
        self.error = error

    def cancel(self) -> None:
        """Mark task as cancelled."""
        self.completed_at = datetime.now()
        self.status = TaskStatus.CANCELLED
        self.cancellation_requested = True

    def timeout_expired(self) -> None:
        """Mark task as timed out."""
        self.completed_at = datetime.now()
        self.status = TaskStatus.TIMEOUT
        self.error = "Task timeout expired"

    def is_finished(self) -> bool:
        """Check if task is in a finished state."""
        return self.status in (TaskStatus.COMPLETED, TaskStatus.FAILED,
                              TaskStatus.CANCELLED, TaskStatus.TIMEOUT)

    def execution_time(self) -> Optional[float]:
        """Get execution time in seconds, or None if not started/finished."""
        if not self.started_at:
            return None
        end_time = self.completed_at or datetime.now()
        return (end_time - self.started_at).total_seconds()

    def to_dict(self) -> Dict[str, Any]:
        """Convert task to dictionary for serialization."""
        return {
            "task_id": self.task_id,
            "tool_name": self.tool_name,
            "parameters": self.parameters,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "status": self.status.value,
            "progress": self.progress,
            "progress_message": self.progress_message,
            "result": str(self.result) if self.result else None,
            "error": self.error,
            "execution_time": self.execution_time(),
            "cancellation_requested": self.cancellation_requested,
            "tags": self.tags
        }


class BackgroundTaskQueue:
    """
    Manages queuing and execution of background tasks.

    Uses threading to run async tasks in background without blocking main loop.
    """

    def __init__(self, max_concurrent_tasks: int = 3, max_queue_size: int = 100):
        """
        Initialize task queue.

        Args:
            max_concurrent_tasks: Maximum number of tasks to run concurrently
            max_queue_size: Maximum number of pending tasks
        """
        self.max_concurrent_tasks = max_concurrent_tasks
        self.max_queue_size = max_queue_size
        self.tasks: Dict[str, BackgroundTask] = {}
        self.task_queue: queue.Queue = queue.Queue(maxsize=max_queue_size)
        self.running_tasks: Dict[str, asyncio.Task] = {}
        self._lock = threading.RLock()
        self._shutdown = False
        self._worker_threads: List[threading.Thread] = []

        # Start worker threads
        self._start_workers()

        log_operation("background_queue_init", "BackgroundTaskQueue",
                     f"Initialized with {max_concurrent_tasks} concurrent workers")

    def _start_workers(self) -> None:
        """Start worker threads."""
        for i in range(self.max_concurrent_tasks):
            thread = threading.Thread(
                target=self._worker_loop,
                name=f"BackgroundWorker-{i}",
                daemon=True
            )
            thread.start()
            self._worker_threads.append(thread)

    def _worker_loop(self) -> None:
        """Worker thread main loop."""
        while not self._shutdown:
            try:
                # Get task from queue with timeout
                task = self.task_queue.get(timeout=1.0)
                if task is None:  # Shutdown signal
                    break

                self._execute_task(task)

            except queue.Empty:
                continue  # Timeout, check shutdown flag
            except Exception as e:
                log_operation("background_worker_error", "BackgroundTaskQueue",
                             f"Worker error: {e}")
                time.sleep(1)  # Avoid tight loop on errors

    def _execute_task(self, task: BackgroundTask) -> None:
        """Execute a single task."""
        try:
            task.start()

            # Check if tool is async
            if isinstance(task.tool_instance, AsyncTool):
                # Run async tool in event loop
                result = asyncio.run(self._execute_async_tool(task))
            else:
                # Run sync tool
                result = task.tool_instance.execute(**task.parameters)

            task.complete(result)

        except asyncio.TimeoutError:
            task.timeout_expired()
            log_operation("background_task_timeout", task.task_id,
                         f"Task timeout after {task.timeout}s")
        except Exception as e:
            task.fail(str(e))
            log_operation("background_task_failed", task.task_id,
                         f"Task failed: {e}")
        finally:
            # Clean up
            with self._lock:
                if task.task_id in self.running_tasks:
                    del self.running_tasks[task.task_id]

    async def _execute_async_tool(self, task: BackgroundTask) -> Any:
        """Execute async tool with timeout."""
        if task.timeout:
            async with asyncio.timeout(task.timeout):
                return await task.tool_instance.execute_async(**task.parameters)
        else:
            return await task.tool_instance.execute_async(**task.parameters)

    def submit(
        self,
        tool_instance: Union[Tool, AsyncTool],
        parameters: Dict[str, Any],
        timeout: Optional[float] = None,
        max_retries: int = 0,
        tags: Optional[List[str]] = None
    ) -> str:
        """
        Submit a task for background execution.

        Args:
            tool_instance: Tool instance to execute
            parameters: Tool parameters
            timeout: Timeout in seconds (None for no timeout)
            max_retries: Maximum number of retries on failure
            tags: List of tags for categorization

        Returns:
            Task ID
        """
        with self._lock:
            if self._shutdown:
                raise RuntimeError("Task queue is shutting down")

            if self.task_queue.full():
                raise RuntimeError(f"Task queue full (max: {self.max_queue_size})")

            task_id = str(uuid.uuid4())[:8]
            task = BackgroundTask(
                task_id=task_id,
                tool_name=tool_instance.metadata.name,
                tool_instance=tool_instance,
                parameters=parameters,
                created_at=datetime.now(),
                timeout=timeout,
                max_retries=max_retries,
                tags=tags or []
            )

            self.tasks[task_id] = task
            self.task_queue.put(task)

            log_operation("background_task_submitted", task_id,
                         f"Submitted {tool_instance.metadata.name} task")

            return task_id

    def get_task(self, task_id: str) -> Optional[BackgroundTask]:
        """Get task by ID."""
        with self._lock:
            return self.tasks.get(task_id)

    def list_tasks(
        self,
        status_filter: Optional[TaskStatus] = None,
        tool_filter: Optional[str] = None,
        tag_filter: Optional[str] = None
    ) -> List[BackgroundTask]:
        """List tasks with optional filtering."""
        with self._lock:
            tasks = list(self.tasks.values())

            if status_filter:
                tasks = [t for t in tasks if t.status == status_filter]

            if tool_filter:
                tasks = [t for t in tasks if t.tool_name == tool_filter]

            if tag_filter:
                tasks = [t for t in tasks if tag_filter in t.tags]

            return sorted(tasks, key=lambda t: t.created_at, reverse=True)

    def cancel_task(self, task_id: str) -> bool:
        """Cancel a running task."""
        with self._lock:
            task = self.tasks.get(task_id)
            if not task:
                return False

            if task.is_finished():
                return False  # Already finished

            task.cancellation_requested = True

            # Try to cancel asyncio task if running
            if task_id in self.running_tasks:
                self.running_tasks[task_id].cancel()

            log_operation("background_task_cancelled", task_id,
                         f"Cancelled task {task.tool_name}")
            return True

    def wait_for_task(
        self,
        task_id: str,
        timeout: Optional[float] = None,
        poll_interval: float = 0.1
    ) -> Optional[BackgroundTask]:
        """
        Wait for task to complete.

        Args:
            task_id: Task ID to wait for
            timeout: Maximum time to wait in seconds
            poll_interval: Time between status checks

        Returns:
            Completed task or None if timeout
        """
        start_time = time.time()

        while True:
            with self._lock:
                task = self.tasks.get(task_id)
                if not task:
                    return None

                if task.is_finished():
                    return task

            # Check timeout
            if timeout and (time.time() - start_time) > timeout:
                return None

            # Wait before checking again
            time.sleep(poll_interval)

    def cleanup_old_tasks(self, max_age_hours: float = 24.0) -> int:
        """
        Remove old completed tasks to free memory.

        Args:
            max_age_hours: Maximum age of tasks to keep

        Returns:
            Number of tasks removed
        """
        with self._lock:
            now = datetime.now()
            to_remove = []

            for task_id, task in self.tasks.items():
                if not task.is_finished():
                    continue

                if task.completed_at:
                    age_hours = (now - task.completed_at).total_seconds() / 3600
                    if age_hours > max_age_hours:
                        to_remove.append(task_id)

            for task_id in to_remove:
                del self.tasks[task_id]

            if to_remove:
                log_operation("background_tasks_cleaned", "BackgroundTaskQueue",
                             f"Removed {len(to_remove)} old tasks")

            return len(to_remove)

    def shutdown(self, wait: bool = True, timeout: float = 30.0) -> None:
        """Shutdown task queue and workers."""
        with self._lock:
            if self._shutdown:
                return

            self._shutdown = True

            # Send shutdown signals to workers
            for _ in range(self.max_concurrent_tasks):
                try:
                    self.task_queue.put(None, timeout=1.0)
                except queue.Full:
                    pass

            if wait:
                # Wait for workers to finish
                for thread in self._worker_threads:
                    thread.join(timeout=timeout / len(self._worker_threads))

            log_operation("background_queue_shutdown", "BackgroundTaskQueue",
                         "Task queue shutdown complete")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.shutdown(wait=True)


class TaskMonitor:
    """Monitors background tasks and provides status updates."""

    def __init__(self, task_queue: BackgroundTaskQueue):
        self.task_queue = task_queue

    def get_status_summary(self) -> Dict[str, Any]:
        """Get summary of task queue status."""
        tasks = self.task_queue.list_tasks()

        status_counts = {status.value: 0 for status in TaskStatus}
        for task in tasks:
            status_counts[task.status.value] += 1

        running_tasks = [t for t in tasks if t.status == TaskStatus.RUNNING]
        avg_progress = (
            sum(t.progress for t in running_tasks) / len(running_tasks)
            if running_tasks else 0.0
        )

        return {
            "total_tasks": len(tasks),
            "status_counts": status_counts,
            "queue_size": self.task_queue.task_queue.qsize(),
            "running_tasks": len(running_tasks),
            "average_progress": avg_progress,
            "max_concurrent": self.task_queue.max_concurrent_tasks,
            "queue_capacity": self.task_queue.max_queue_size
        }

    def get_detailed_status(self) -> List[Dict[str, Any]]:
        """Get detailed status of all tasks."""
        tasks = self.task_queue.list_tasks()
        return [task.to_dict() for task in tasks]

    def format_status_table(self) -> str:
        """Format task status as a text table."""
        tasks = self.task_queue.list_tasks()
        if not tasks:
            return "No background tasks."

        # Create table
        lines = ["Background Task Status", "=" * 60]
        lines.append(f"{'ID':<8} {'Tool':<15} {'Status':<12} {'Progress':<8} {'Time':<8}")
        lines.append("-" * 60)

        for task in tasks:
            status_symbol = {
                TaskStatus.PENDING: "⭕",
                TaskStatus.RUNNING: "▶",
                TaskStatus.COMPLETED: "✓",
                TaskStatus.FAILED: "✗",
                TaskStatus.CANCELLED: "⭕",
                TaskStatus.TIMEOUT: "⌛"
            }.get(task.status, "?")

            progress_str = f"{task.progress:.1%}"
            time_str = f"{task.execution_time():.1f}s" if task.execution_time() else "-"

            lines.append(
                f"{task.task_id:<8} "
                f"{task.tool_name[:14]:<15} "
                f"{status_symbol} {task.status.value[:10]:<12} "
                f"{progress_str:<8} "
                f"{time_str:<8}"
            )

        # Add summary
        summary = self.get_status_summary()
        lines.append("-" * 60)
        lines.append(f"Total: {summary['total_tasks']} | "
                    f"Pending: {summary['status_counts']['pending']} | "
                    f"Running: {summary['running_tasks']} | "
                    f"Completed: {summary['status_counts']['completed']} | "
                    f"Failed: {summary['status_counts']['failed']}")

        return "\n".join(lines)

    def watch_progress(
        self,
        task_id: str,
        update_callback: Optional[Callable[[BackgroundTask], None]] = None,
        poll_interval: float = 0.5
    ) -> BackgroundTask:
        """
        Watch task progress until completion.

        Args:
            task_id: Task ID to watch
            update_callback: Called on each progress update
            poll_interval: Time between checks

        Returns:
            Completed task
        """
        last_progress = -1.0

        while True:
            task = self.task_queue.get_task(task_id)
            if not task:
                raise ValueError(f"Task {task_id} not found")

            # Call callback if progress changed
            if update_callback and task.progress != last_progress:
                update_callback(task)
                last_progress = task.progress

            # Check if finished
            if task.is_finished():
                if update_callback:
                    update_callback(task)
                return task

            # Wait before checking again
            time.sleep(poll_interval)


class AsyncExecutor:
    """Executes async tools with proper error handling and timeouts."""

    def __init__(self, max_workers: int = 10):
        self.max_workers = max_workers
        self._semaphore = asyncio.Semaphore(max_workers)

    async def execute_with_progress(
        self,
        tool: AsyncTool,
        parameters: Dict[str, Any],
        timeout: Optional[float] = None,
        progress_callback: Optional[Callable[[float, Optional[str]], None]] = None
    ) -> Any:
        """
        Execute async tool with progress reporting.

        Args:
            tool: AsyncTool instance
            parameters: Tool parameters
            timeout: Execution timeout in seconds
            progress_callback: Callback for progress updates (progress, message)

        Returns:
            Tool execution result
        """
        async with self._semaphore:
            try:
                # Set up timeout if specified
                if timeout:
                    async with asyncio.timeout(timeout):
                        return await tool.execute_async(**parameters)
                else:
                    return await tool.execute_async(**parameters)

            except asyncio.TimeoutError:
                if progress_callback:
                    progress_callback(1.0, "Timeout")
                raise ToolExecutionError(f"Tool execution timeout after {timeout}s")
            except Exception as e:
                if progress_callback:
                    progress_callback(1.0, f"Error: {e}")
                raise

    async def execute_batch(
        self,
        tasks: List[Tuple[AsyncTool, Dict[str, Any]]],
        max_concurrent: Optional[int] = None,
        timeout_per_task: Optional[float] = None
    ) -> List[Any]:
        """
        Execute multiple async tools concurrently.

        Args:
            tasks: List of (tool, parameters) tuples
            max_concurrent: Maximum concurrent executions (defaults to max_workers)
            timeout_per_task: Timeout per individual task

        Returns:
            List of results in same order as input
        """
        if max_concurrent is None:
            max_concurrent = self.max_workers

        # Create semaphore for this batch
        batch_semaphore = asyncio.Semaphore(max_concurrent)

        async def execute_single(tool: AsyncTool, params: Dict[str, Any]) -> Any:
            async with batch_semaphore:
                if timeout_per_task:
                    async with asyncio.timeout(timeout_per_task):
                        return await tool.execute_async(**params)
                else:
                    return await tool.execute_async(**params)

        # Run all tasks concurrently
        return await asyncio.gather(
            *[execute_single(tool, params) for tool, params in tasks],
            return_exceptions=True
        )


# Global background task queue (singleton)
_global_task_queue: Optional[BackgroundTaskQueue] = None
_global_task_monitor: Optional[TaskMonitor] = None

def get_global_task_queue() -> BackgroundTaskQueue:
    """Get or create global background task queue."""
    global _global_task_queue
    if _global_task_queue is None:
        _global_task_queue = BackgroundTaskQueue()
    return _global_task_queue

def get_global_task_monitor() -> TaskMonitor:
    """Get or create global task monitor."""
    global _global_task_monitor
    if _global_task_monitor is None:
        _global_task_monitor = TaskMonitor(get_global_task_queue())
    return _global_task_monitor

def shutdown_global_task_queue(wait: bool = True) -> None:
    """Shutdown global background task queue."""
    global _global_task_queue
    if _global_task_queue:
        _global_task_queue.shutdown(wait=wait)
        _global_task_queue = None
        _global_task_monitor = None