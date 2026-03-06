"""
Background tool for submitting and monitoring async tasks.

Provides:
- BackgroundSubmitTool: Submit tools for background execution
- BackgroundMonitorTool: Monitor and manage background tasks
- BackgroundWrapper: Wraps any tool to run in background
"""

import asyncio
import time
from typing import Dict, Any, Optional, List, Union, Callable
from enum import Enum

from .base import Tool, AsyncTool, ToolMetadata, ToolError, ToolExecutionError
from .background import (
    BackgroundTaskQueue, TaskMonitor, TaskStatus, BackgroundTask,
    get_global_task_queue, get_global_task_monitor
)


class BackgroundSubmitTool(Tool):
    """Tool for submitting other tools to run in the background."""

    def __init__(self, tool_registry=None):
        """
        Initialize background submit tool.

        Args:
            tool_registry: ToolRegistry instance for looking up tools
        """
        super().__init__()
        self.tool_registry = tool_registry
        self.task_queue = get_global_task_queue()
        self.task_monitor = get_global_task_monitor()

    @classmethod
    def _default_metadata(cls) -> ToolMetadata:
        return ToolMetadata(
            name="background_submit",
            description="Submit a tool to run in the background and return immediately with task ID",
            parameters={
                "type": "object",
                "properties": {
                    "tool_name": {
                        "type": "string",
                        "description": "Name of the tool to execute in background"
                    },
                    "parameters": {
                        "type": "object",
                        "description": "Parameters for the tool",
                        "additionalProperties": True
                    },
                    "timeout": {
                        "type": "number",
                        "description": "Timeout in seconds (optional)",
                        "minimum": 1
                    },
                    "tags": {
                        "type": "array",
                        "description": "Tags for categorizing the task",
                        "items": {"type": "string"}
                    }
                },
                "required": ["tool_name", "parameters"]
            },
            returns={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "status": {"type": "string"},
                    "message": {"type": "string"}
                }
            },
            categories=["background", "execution"],
            dangerous=False
        )

    def execute(self, **kwargs) -> Dict[str, Any]:
        """
        Submit a tool for background execution.

        Args:
            tool_name: Name of tool to execute
            parameters: Tool parameters
            timeout: Timeout in seconds (optional)
            tags: List of tags (optional)

        Returns:
            Dict with task_id and status
        """
        self.validate_input(**kwargs)

        tool_name = kwargs["tool_name"]
        parameters = kwargs["parameters"]
        timeout = kwargs.get("timeout")
        tags = kwargs.get("tags", [])

        # Get tool from registry
        if self.tool_registry is None:
            raise ToolExecutionError("Tool registry not available")

        tool = self.tool_registry.get_tool(tool_name)
        if not tool:
            raise ToolExecutionError(f"Tool '{tool_name}' not found")

        # Submit to background queue
        try:
            task_id = self.task_queue.submit(
                tool_instance=tool,
                parameters=parameters,
                timeout=timeout,
                tags=tags
            )

            return {
                "task_id": task_id,
                "status": "submitted",
                "message": f"Tool '{tool_name}' submitted as background task {task_id}"
            }
        except Exception as e:
            raise ToolExecutionError(f"Failed to submit background task: {e}")


class BackgroundMonitorTool(Tool):
    """Tool for monitoring and managing background tasks."""

    def __init__(self):
        super().__init__()
        self.task_queue = get_global_task_queue()
        self.task_monitor = get_global_task_monitor()

    @classmethod
    def _default_metadata(cls) -> ToolMetadata:
        return ToolMetadata(
            name="background_monitor",
            description="Monitor and manage background tasks",
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "Action to perform",
                        "enum": ["list", "status", "cancel", "wait", "summary", "cleanup"]
                    },
                    "task_id": {
                        "type": "string",
                        "description": "Task ID (required for status, cancel, wait)"
                    },
                    "status_filter": {
                        "type": "string",
                        "description": "Filter tasks by status (pending, running, completed, failed, cancelled, timeout)",
                        "enum": ["pending", "running", "completed", "failed", "cancelled", "timeout"]
                    },
                    "tool_filter": {
                        "type": "string",
                        "description": "Filter tasks by tool name"
                    },
                    "max_age_hours": {
                        "type": "number",
                        "description": "Maximum age in hours for cleanup (default: 24)",
                        "minimum": 0.1
                    },
                    "wait_timeout": {
                        "type": "number",
                        "description": "Timeout in seconds for wait action",
                        "minimum": 1
                    }
                },
                "required": ["action"]
            },
            returns={
                "type": "object",
                "properties": {
                    "success": {"type": "boolean"},
                    "result": {"type": "object"},
                    "message": {"type": "string"}
                }
            },
            categories=["background", "monitoring"],
            dangerous=False
        )

    def execute(self, **kwargs) -> Dict[str, Any]:
        """
        Monitor and manage background tasks.

        Args:
            action: Action to perform
            task_id: Task ID for specific actions
            status_filter: Filter tasks by status
            tool_filter: Filter tasks by tool name
            max_age_hours: Max age for cleanup
            wait_timeout: Timeout for wait action

        Returns:
            Action result
        """
        self.validate_input(**kwargs)

        action = kwargs["action"]

        if action == "list":
            return self._handle_list(
                status_filter=kwargs.get("status_filter"),
                tool_filter=kwargs.get("tool_filter")
            )
        elif action == "status":
            return self._handle_status(kwargs["task_id"])
        elif action == "cancel":
            return self._handle_cancel(kwargs["task_id"])
        elif action == "wait":
            return self._handle_wait(
                kwargs["task_id"],
                kwargs.get("wait_timeout")
            )
        elif action == "summary":
            return self._handle_summary()
        elif action == "cleanup":
            return self._handle_cleanup(kwargs.get("max_age_hours", 24.0))
        else:
            raise ToolExecutionError(f"Unknown action: {action}")

    def _handle_list(
        self,
        status_filter: Optional[str] = None,
        tool_filter: Optional[str] = None
    ) -> Dict[str, Any]:
        """List background tasks."""
        # Convert status filter string to enum
        status_enum = None
        if status_filter:
            try:
                status_enum = TaskStatus(status_filter)
            except ValueError:
                raise ToolExecutionError(f"Invalid status filter: {status_filter}")

        tasks = self.task_queue.list_tasks(
            status_filter=status_enum,
            tool_filter=tool_filter
        )

        return {
            "success": True,
            "result": {
                "tasks": [task.to_dict() for task in tasks],
                "count": len(tasks)
            },
            "message": f"Found {len(tasks)} background tasks"
        }

    def _handle_status(self, task_id: str) -> Dict[str, Any]:
        """Get status of a specific task."""
        task = self.task_queue.get_task(task_id)
        if not task:
            return {
                "success": False,
                "result": None,
                "message": f"Task {task_id} not found"
            }

        return {
            "success": True,
            "result": task.to_dict(),
            "message": f"Task {task_id} status: {task.status.value}"
        }

    def _handle_cancel(self, task_id: str) -> Dict[str, Any]:
        """Cancel a background task."""
        success = self.task_queue.cancel_task(task_id)
        return {
            "success": success,
            "result": {"cancelled": success, "task_id": task_id},
            "message": (
                f"Task {task_id} cancelled" if success
                else f"Task {task_id} not found or already finished"
            )
        }

    def _handle_wait(
        self,
        task_id: str,
        timeout: Optional[float] = None
    ) -> Dict[str, Any]:
        """Wait for a task to complete."""
        task = self.task_queue.wait_for_task(task_id, timeout)
        if not task:
            return {
                "success": False,
                "result": None,
                "message": f"Task {task_id} not found or wait timeout"
            }

        return {
            "success": True,
            "result": task.to_dict(),
            "message": f"Task {task_id} completed with status: {task.status.value}"
        }

    def _handle_summary(self) -> Dict[str, Any]:
        """Get summary of background task queue."""
        summary = self.task_monitor.get_status_summary()
        return {
            "success": True,
            "result": summary,
            "message": "Background task queue summary"
        }

    def _handle_cleanup(self, max_age_hours: float) -> Dict[str, Any]:
        """Clean up old completed tasks."""
        removed = self.task_queue.cleanup_old_tasks(max_age_hours)
        return {
            "success": True,
            "result": {"removed_count": removed, "max_age_hours": max_age_hours},
            "message": f"Removed {removed} old background tasks"
        }


class BackgroundWrapper(AsyncTool):
    """
    Wraps any tool to run asynchronously in the background.

    This allows synchronous tools to be used with async execution patterns.
    """

    def __init__(self, wrapped_tool: Tool, run_in_background: bool = True):
        """
        Initialize wrapper.

        Args:
            wrapped_tool: Tool to wrap
            run_in_background: If True, runs in background thread
        """
        super().__init__()
        self.wrapped_tool = wrapped_tool
        self.run_in_background = run_in_background
        self.task_queue = get_global_task_queue() if run_in_background else None

        # Use wrapped tool's metadata
        self.metadata = wrapped_tool.metadata

    async def execute_async(self, **kwargs) -> Any:
        """
        Execute wrapped tool asynchronously.

        If run_in_background is True, submits to background queue and waits.
        Otherwise, runs in current thread using asyncio.to_thread.
        """
        if self.run_in_background:
            # Submit to background queue and wait
            task_id = self.task_queue.submit(
                tool_instance=self.wrapped_tool,
                parameters=kwargs
            )

            # Wait for completion
            task = self.task_queue.wait_for_task(task_id)
            if not task:
                raise ToolExecutionError(f"Background task {task_id} failed")

            if task.status == TaskStatus.COMPLETED:
                return task.result
            elif task.error:
                raise ToolExecutionError(f"Background task failed: {task.error}")
            else:
                raise ToolExecutionError(
                    f"Background task failed with status: {task.status.value}"
                )
        else:
            # Run sync tool in thread pool
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                None,
                lambda: self.wrapped_tool.execute(**kwargs)
            )

    def execute(self, **kwargs) -> Any:
        """Sync execution (blocks)."""
        if self.run_in_background:
            # For sync execution, we still use background but wait immediately
            task_id = self.task_queue.submit(
                tool_instance=self.wrapped_tool,
                parameters=kwargs
            )
            task = self.task_queue.wait_for_task(task_id)
            if task and task.status == TaskStatus.COMPLETED:
                return task.result
            elif task and task.error:
                raise ToolExecutionError(f"Background task failed: {task.error}")
            else:
                raise ToolExecutionError("Background task failed")
        else:
            # Direct sync execution
            return self.wrapped_tool.execute(**kwargs)


def background_tool(
    tool_instance: Optional[Tool] = None,
    run_in_background: bool = True,
    **kwargs
):
    """
    Decorator to make a tool run in the background.

    Can be used as:
        @background_tool
        class MyTool(Tool):
            ...

    or:
        @background_tool(run_in_background=False)
        class MyTool(Tool):
            ...
    """
    def decorator(tool_cls_or_instance):
        if isinstance(tool_cls_or_instance, type):
            # It's a class, create wrapper class
            class BackgroundWrappedTool(AsyncTool):
                def __init__(self, *args, **init_kwargs):
                    super().__init__()
                    self.wrapped = tool_cls_or_instance(*args, **init_kwargs)
                    self.metadata = self.wrapped.metadata
                    self.run_in_background = run_in_background
                    self.task_queue = get_global_task_queue() if run_in_background else None

                async def execute_async(self, **exec_kwargs) -> Any:
                    if self.run_in_background:
                        task_id = self.task_queue.submit(
                            tool_instance=self.wrapped,
                            parameters=exec_kwargs
                        )
                        task = self.task_queue.wait_for_task(task_id)
                        if task and task.status == TaskStatus.COMPLETED:
                            return task.result
                        elif task and task.error:
                            raise ToolExecutionError(f"Background task failed: {task.error}")
                        else:
                            raise ToolExecutionError("Background task failed")
                    else:
                        loop = asyncio.get_event_loop()
                        return await loop.run_in_executor(
                            None,
                            lambda: self.wrapped.execute(**exec_kwargs)
                        )

                def execute(self, **exec_kwargs) -> Any:
                    return self.wrapped.execute(**exec_kwargs)

            # Copy class attributes
            BackgroundWrappedTool.__name__ = f"Background{tool_cls_or_instance.__name__}"
            BackgroundWrappedTool.__doc__ = tool_cls_or_instance.__doc__
            return BackgroundWrappedTool

        else:
            # It's an instance, wrap it
            return BackgroundWrapper(tool_cls_or_instance, run_in_background)

    # Handle both @background_tool and @background_tool(...) syntax
    if tool_instance is None:
        # Called with parentheses: @background_tool(...)
        return decorator
    else:
        # Called without parentheses: @background_tool
        return decorator(tool_instance)


# Convenience functions
def submit_background_task(
    tool_instance: Tool,
    parameters: Dict[str, Any],
    timeout: Optional[float] = None,
    tags: Optional[List[str]] = None
) -> str:
    """Submit a tool to run in background and return task ID."""
    task_queue = get_global_task_queue()
    return task_queue.submit(tool_instance, parameters, timeout, tags)


def get_background_task_status(task_id: str) -> Optional[BackgroundTask]:
    """Get status of a background task."""
    task_queue = get_global_task_queue()
    return task_queue.get_task(task_id)


def wait_for_background_task(
    task_id: str,
    timeout: Optional[float] = None
) -> Optional[BackgroundTask]:
    """Wait for a background task to complete."""
    task_queue = get_global_task_queue()
    return task_queue.wait_for_task(task_id, timeout)