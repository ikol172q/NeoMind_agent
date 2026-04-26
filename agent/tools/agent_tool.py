"""
Agent Tool for NeoMind Agent.

Provides sub-agent spawning capabilities for complex tasks.
Inspired by Claude Code's agent delegation pattern.

Created: 2026-04-02 (Phase 2 - Coding 完整功能)
"""

from __future__ import annotations

import asyncio
import uuid
from typing import List, Dict, Optional, Any, Callable, Union
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class AgentTaskStatus(Enum):
    """Status of an agent task."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"


@dataclass
class AgentTask:
    """Represents a task delegated to a sub-agent."""
    id: str
    description: str
    status: AgentTaskStatus
    result: Optional[str] = None
    error: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentResult:
    """Result from a sub-agent execution."""
    task_id: str
    success: bool
    output: str
    error: Optional[str] = None
    duration_ms: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


class AgentTool:
    """
    Spawns and manages sub-agents for complex tasks.

    Features:
    - Task delegation
    - Parallel execution
    - Timeout handling
    - Result aggregation
    """

    # Agent types
    TYPE_CODE = "code"
    TYPE_SEARCH = "search"
    TYPE_ANALYSIS = "analysis"
    TYPE_TESTING = "testing"

    def __init__(
        self,
        max_concurrent: int = 3,
        default_timeout: float = 120.0  # seconds
    ):
        """
        Initialize agent tool.

        Args:
            max_concurrent: Maximum concurrent sub-agents
            default_timeout: Default timeout for tasks
        """
        self.max_concurrent = max_concurrent
        self.default_timeout = default_timeout

        self._tasks: Dict[str, AgentTask] = {}
        self._results: Dict[str, AgentResult] = {}
        self._semaphore = asyncio.Semaphore(max_concurrent)

    def spawn(
        self,
        description: str,
        task_type: str = TYPE_CODE,
        timeout: Optional[float] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Spawn a sub-agent task.

        Args:
            description: Task description
            task_type: Type of task (code, search, analysis, testing)
            timeout: Timeout in seconds
            context: Additional context for the task

        Returns:
            Task ID
        """
        task_id = str(uuid.uuid4())[:8]

        task = AgentTask(
            id=task_id,
            description=description,
            status=AgentTaskStatus.PENDING,
            metadata={
                'type': task_type,
                'timeout': timeout or self.default_timeout,
                'context': context or {}
            }
        )

        self._tasks[task_id] = task
        return task_id

    async def execute(
        self,
        task_id: str,
        handler: Callable[[AgentTask], str]
    ) -> AgentResult:
        """
        Execute a task with a handler function.

        Args:
            task_id: Task ID
            handler: Async or sync function to execute the task

        Returns:
            AgentResult
        """
        task = self._tasks.get(task_id)
        if not task:
            return AgentResult(
                task_id=task_id,
                success=False,
                output="",
                error="Task not found"
            )

        task.status = AgentTaskStatus.RUNNING
        task.started_at = datetime.now()

        start_time = datetime.now()
        timeout = task.metadata.get('timeout', self.default_timeout)

        try:
            async with self._semaphore:
                # Handle both sync and async handlers
                if asyncio.iscoroutinefunction(handler):
                    result = await asyncio.wait_for(
                        handler(task),
                        timeout=timeout
                    )
                else:
                    result = await asyncio.get_event_loop().run_in_executor(
                        None,
                        handler,
                        task
                    )

            task.status = AgentTaskStatus.COMPLETED
            task.result = str(result)
            task.completed_at = datetime.now()

            duration = (task.completed_at - start_time).total_seconds() * 1000

            agent_result = AgentResult(
                task_id=task_id,
                success=True,
                output=str(result),
                duration_ms=duration
            )

        except asyncio.TimeoutError:
            task.status = AgentTaskStatus.TIMEOUT
            task.error = f"Task timed out after {timeout}s"
            task.completed_at = datetime.now()

            agent_result = AgentResult(
                task_id=task_id,
                success=False,
                output="",
                error=task.error,
                duration_ms=timeout * 1000
            )

        except Exception as e:
            task.status = AgentTaskStatus.FAILED
            task.error = str(e)
            task.completed_at = datetime.now()

            duration = (task.completed_at - start_time).total_seconds() * 1000

            agent_result = AgentResult(
                task_id=task_id,
                success=False,
                output="",
                error=str(e),
                duration_ms=duration
            )

        self._results[task_id] = agent_result
        return agent_result

    async def execute_batch(
        self,
        descriptions: List[str],
        handler: Callable[[AgentTask], str],
        task_type: str = TYPE_CODE
    ) -> List[AgentResult]:
        """
        Execute multiple tasks in parallel.

        Args:
            descriptions: List of task descriptions
            handler: Handler function
            task_type: Type of tasks

        Returns:
            List of AgentResult
        """
        # Spawn all tasks
        task_ids = [
            self.spawn(desc, task_type=task_type)
            for desc in descriptions
        ]

        # Execute in parallel
        results = await asyncio.gather(
            *[self.execute(tid, handler) for tid in task_ids],
            return_exceptions=True
        )

        # Convert exceptions to failed results
        final_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                final_results.append(AgentResult(
                    task_id=task_ids[i],
                    success=False,
                    output="",
                    error=str(result)
                ))
            else:
                final_results.append(result)

        return final_results

    def spawn_with_type(
        self,
        description: str,
        builtin_type,  # BuiltinAgentType from agent.agentic.builtin_agents
        timeout: Optional[float] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Spawn a task using a built-in agent type (Explore, Plan, Verify).

        The built-in type's tool allowlist, recommended model, and permission
        mode are stored in task metadata so the caller can configure the
        sub-agent session accordingly.

        Args:
            description: Task description
            builtin_type: BuiltinAgentType instance (e.g. EXPLORE_AGENT)
            timeout: Override default timeout
            context: Additional context

        Returns:
            Task ID
        """
        task_id = str(uuid.uuid4())[:8]

        task = AgentTask(
            id=task_id,
            description=description,
            status=AgentTaskStatus.PENDING,
            metadata={
                'type': builtin_type.agent_type,
                'timeout': timeout or self.default_timeout,
                'context': context or {},
                'agent_type': builtin_type.agent_type,
                'tool_allowlist': list(builtin_type.tool_allowlist),
                'recommended_model': builtin_type.recommended_model,
                'permission_mode': builtin_type.permission_mode,
                'system_prompt_addition': builtin_type.system_prompt_addition,
                'max_turns': builtin_type.max_turns,
                'is_background': builtin_type.is_background,
            }
        )

        self._tasks[task_id] = task
        return task_id

    def get_task(self, task_id: str) -> Optional[AgentTask]:
        """Get task by ID."""
        return self._tasks.get(task_id)

    def get_result(self, task_id: str) -> Optional[AgentResult]:
        """Get result by task ID."""
        return self._results.get(task_id)

    def list_tasks(self, status: Optional[AgentTaskStatus] = None) -> List[AgentTask]:
        """List tasks, optionally filtered by status."""
        tasks = list(self._tasks.values())
        if status:
            tasks = [t for t in tasks if t.status == status]
        return sorted(tasks, key=lambda t: t.created_at, reverse=True)

    def get_stats(self) -> Dict[str, Any]:
        """Get agent statistics."""
        status_counts = {}
        for status in AgentTaskStatus:
            status_counts[status.value] = sum(
                1 for t in self._tasks.values() if t.status == status
            )

        success_rate = 0.0
        if self._results:
            success_rate = sum(1 for r in self._results.values() if r.success) / len(self._results)

        return {
            'total_tasks': len(self._tasks),
            'total_results': len(self._results),
            'status_counts': status_counts,
            'success_rate': success_rate,
            'max_concurrent': self.max_concurrent,
        }


# Convenience functions
def spawn_agent(description: str, task_type: str = AgentTool.TYPE_CODE) -> str:
    """Quick spawn function."""
    tool = AgentTool()
    return tool.spawn(description, task_type)


__all__ = [
    'AgentTool',
    'AgentTask',
    'AgentResult',
    'AgentTaskStatus',
    'spawn_agent',
]


if __name__ == "__main__":
    import asyncio

    async def test_handler(task: AgentTask) -> str:
        """Test handler that simulates work."""
        await asyncio.sleep(0.1)
        return f"Completed: {task.description}"

    async def main():
        print("=== Agent Tool Test ===\n")

        tool = AgentTool(max_concurrent=2, default_timeout=5.0)

        # Test single task
        task_id = tool.spawn("Analyze code complexity")
        print(f"Spawned task: {task_id}")

        result = await tool.execute(task_id, test_handler)
        print(f"Result: {result.output}")
        print(f"Success: {result.success}")

        # Test batch execution
        print("\n--- Batch Test ---")
        descriptions = [
            "Task 1: Code review",
            "Task 2: Run tests",
            "Task 3: Generate docs",
        ]

        results = await tool.execute_batch(descriptions, test_handler)
        for r in results:
            print(f"  {r.task_id}: {r.output}")

        # Stats
        print("\n--- Stats ---")
        stats = tool.get_stats()
        print(f"  Total tasks: {stats['total_tasks']}")
        print(f"  Success rate: {stats['success_rate']:.1%}")

        print("\n✅ AgentTool test passed!")

    asyncio.run(main())
