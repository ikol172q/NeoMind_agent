"""
Task Management Tools for NeoMind Agent.

Provides session-level task tracking for organizing complex work.

Created: 2026-04-02 (Phase 2 - Coding 完整功能)
"""

from __future__ import annotations

from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class TaskStatus(Enum):
    """Status of a managed task."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


# Valid status transitions
_VALID_TRANSITIONS: Dict[TaskStatus, List[TaskStatus]] = {
    TaskStatus.PENDING: [TaskStatus.IN_PROGRESS, TaskStatus.CANCELLED],
    TaskStatus.IN_PROGRESS: [TaskStatus.COMPLETED, TaskStatus.CANCELLED],
    TaskStatus.COMPLETED: [],
    TaskStatus.CANCELLED: [],
}


@dataclass
class Task:
    """Represents a tracked task within a session."""
    id: str
    subject: str
    description: str
    status: TaskStatus = TaskStatus.PENDING
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskResult:
    """Result from a task management operation."""
    success: bool
    message: str
    task: Optional[Task] = None
    tasks: Optional[List[Task]] = None
    error: Optional[str] = None


class TaskManager:
    """
    Session-level task tracker for organizing complex work.

    Features:
    - Create, read, update, and cancel tasks
    - Status-based filtering
    - Enforced status transitions
    - Auto-incremented task IDs
    """

    def __init__(self):
        """Initialize task manager with empty state."""
        self._tasks: Dict[str, Task] = {}
        self._next_id: int = 1

    def _generate_id(self) -> str:
        """Generate the next task ID."""
        task_id = f"task-{self._next_id}"
        self._next_id += 1
        return task_id

    def create(
        self,
        subject: str,
        description: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> TaskResult:
        """
        Create a new task.

        Args:
            subject: Short task subject/title
            description: Detailed task description
            metadata: Optional metadata dict

        Returns:
            TaskResult with the created task
        """
        if not subject or not subject.strip():
            return TaskResult(
                success=False,
                message="Task subject cannot be empty",
                error="invalid_subject"
            )

        task_id = self._generate_id()
        now = datetime.now()

        task = Task(
            id=task_id,
            subject=subject.strip(),
            description=description.strip() if description else "",
            status=TaskStatus.PENDING,
            created_at=now,
            updated_at=now,
            metadata=metadata or {}
        )

        self._tasks[task_id] = task

        return TaskResult(
            success=True,
            message=f"Task {task_id} created",
            task=task
        )

    def get(self, task_id: str) -> TaskResult:
        """
        Get a task by ID.

        Args:
            task_id: Task ID

        Returns:
            TaskResult with the task if found
        """
        task = self._tasks.get(task_id)
        if not task:
            return TaskResult(
                success=False,
                message=f"Task {task_id} not found",
                error="not_found"
            )

        return TaskResult(
            success=True,
            message=f"Task {task_id} retrieved",
            task=task
        )

    def list(self, status_filter: Optional[TaskStatus] = None) -> TaskResult:
        """
        List all tasks, optionally filtered by status.

        Args:
            status_filter: Optional status to filter by

        Returns:
            TaskResult with list of matching tasks
        """
        tasks = list(self._tasks.values())

        if status_filter is not None:
            tasks = [t for t in tasks if t.status == status_filter]

        tasks = sorted(tasks, key=lambda t: t.created_at, reverse=True)

        return TaskResult(
            success=True,
            message=f"Found {len(tasks)} task(s)",
            tasks=tasks
        )

    def update(
        self,
        task_id: str,
        status: Optional[TaskStatus] = None,
        subject: Optional[str] = None,
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> TaskResult:
        """
        Update a task's fields.

        Status transitions are enforced:
        - pending -> in_progress, cancelled
        - in_progress -> completed, cancelled
        - completed -> (terminal)
        - cancelled -> (terminal)

        Args:
            task_id: Task ID
            status: New status (optional)
            subject: New subject (optional)
            description: New description (optional)
            metadata: Metadata to merge (optional)

        Returns:
            TaskResult with the updated task
        """
        task = self._tasks.get(task_id)
        if not task:
            return TaskResult(
                success=False,
                message=f"Task {task_id} not found",
                error="not_found"
            )

        # Validate status transition
        if status is not None and status != task.status:
            allowed = _VALID_TRANSITIONS.get(task.status, [])
            if status not in allowed:
                return TaskResult(
                    success=False,
                    message=f"Cannot transition from {task.status.value} to {status.value}",
                    error="invalid_transition",
                    task=task
                )
            task.status = status

        if subject is not None:
            if not subject.strip():
                return TaskResult(
                    success=False,
                    message="Task subject cannot be empty",
                    error="invalid_subject",
                    task=task
                )
            task.subject = subject.strip()

        if description is not None:
            task.description = description.strip()

        if metadata is not None:
            task.metadata.update(metadata)

        task.updated_at = datetime.now()

        return TaskResult(
            success=True,
            message=f"Task {task_id} updated",
            task=task
        )

    def stop(self, task_id: str) -> TaskResult:
        """
        Cancel/stop a task. Sets status to cancelled.

        Only pending or in_progress tasks can be stopped.

        Args:
            task_id: Task ID

        Returns:
            TaskResult with the cancelled task
        """
        task = self._tasks.get(task_id)
        if not task:
            return TaskResult(
                success=False,
                message=f"Task {task_id} not found",
                error="not_found"
            )

        if task.status in (TaskStatus.COMPLETED, TaskStatus.CANCELLED):
            return TaskResult(
                success=False,
                message=f"Task {task_id} is already {task.status.value}",
                error="invalid_transition",
                task=task
            )

        task.status = TaskStatus.CANCELLED
        task.updated_at = datetime.now()

        return TaskResult(
            success=True,
            message=f"Task {task_id} cancelled",
            task=task
        )

    def get_stats(self) -> Dict[str, Any]:
        """Get summary statistics for all tasks."""
        status_counts = {}
        for status in TaskStatus:
            status_counts[status.value] = sum(
                1 for t in self._tasks.values() if t.status == status
            )

        return {
            'total_tasks': len(self._tasks),
            'status_counts': status_counts,
        }


__all__ = [
    'TaskManager',
    'Task',
    'TaskResult',
    'TaskStatus',
]


if __name__ == "__main__":
    print("=== TaskManager Test ===\n")

    mgr = TaskManager()

    # Create tasks
    r1 = mgr.create("Refactor auth module", "Split auth into separate services")
    print(f"Created: {r1.task.id} - {r1.task.subject}")

    r2 = mgr.create("Write unit tests", "Cover edge cases in parser", metadata={"priority": "high"})
    print(f"Created: {r2.task.id} - {r2.task.subject}")

    r3 = mgr.create("Update docs", "Refresh API documentation")
    print(f"Created: {r3.task.id} - {r3.task.subject}")

    # Update status
    mgr.update(r1.task.id, status=TaskStatus.IN_PROGRESS)
    mgr.update(r1.task.id, status=TaskStatus.COMPLETED)
    print(f"\n{r1.task.id} status: {r1.task.status.value}")

    # Invalid transition
    bad = mgr.update(r1.task.id, status=TaskStatus.PENDING)
    print(f"Invalid transition: {bad.message}")

    # List by status
    pending = mgr.list(status_filter=TaskStatus.PENDING)
    print(f"\nPending tasks: {len(pending.tasks)}")
    for t in pending.tasks:
        print(f"  {t.id}: {t.subject}")

    # Stop a task
    stop_result = mgr.stop(r3.task.id)
    print(f"\nStopped: {stop_result.task.id} -> {stop_result.task.status.value}")

    # Stats
    stats = mgr.get_stats()
    print(f"\nStats: {stats}")

    print("\nTaskManager test passed!")
