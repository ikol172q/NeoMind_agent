"""
Tool system for user_agent.

This package implements a tool-calling system similar to advanced CLI tool architecture.
Tools are callable functions that the LLM can invoke to perform actions.
"""

from .base import Tool, AsyncTool, CommandTool
from .registry import ToolRegistry
from .exceptions import ToolError, ToolValidationError, ToolExecutionError
from .background import (
    BackgroundTaskQueue, TaskMonitor, TaskStatus, BackgroundTask,
    get_global_task_queue, get_global_task_monitor, shutdown_global_task_queue
)
from .background_tool import (
    BackgroundSubmitTool, BackgroundMonitorTool, BackgroundWrapper,
    background_tool, submit_background_task, get_background_task_status,
    wait_for_background_task
)

__all__ = [
    "Tool",
    "AsyncTool",
    "CommandTool",
    "ToolRegistry",
    "ToolError",
    "ToolValidationError",
    "ToolExecutionError",
    "BackgroundTaskQueue",
    "TaskMonitor",
    "TaskStatus",
    "BackgroundTask",
    "get_global_task_queue",
    "get_global_task_monitor",
    "shutdown_global_task_queue",
    "BackgroundSubmitTool",
    "BackgroundMonitorTool",
    "BackgroundWrapper",
    "background_tool",
    "submit_background_task",
    "get_background_task_status",
    "wait_for_background_task",
]