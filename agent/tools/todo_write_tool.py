"""
TodoWrite tool for tracking LLM progress.

Provides a simple todo list that the LLM can update to track its progress
on complex tasks, with validation and rendering.
"""

from typing import List, Dict, Any

from .base import Tool, ToolMetadata
from ..tasks.todo_manager import TODO_MANAGER


class TodoWriteTool(Tool):
    """Tool for updating and rendering a simple todo list."""

    def _default_metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="todo_write",
            description="Update a simple todo list to track LLM progress. Enforces constraints: max 20 items, only one in_progress item. Each item must have content, status (pending/in_progress/completed), and activeForm (present continuous description).",
            parameters={
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "description": "List of todo items",
                        "items": {
                            "type": "object",
                            "properties": {
                                "content": {
                                    "type": "string",
                                    "description": "Description of the task"
                                },
                                "status": {
                                    "type": "string",
                                    "description": "Status of the task",
                                    "enum": ["pending", "in_progress", "completed"]
                                },
                                "activeForm": {
                                    "type": "string",
                                    "description": "Present continuous description shown when status is in_progress (e.g., 'Writing tests')"
                                }
                            },
                            "required": ["content", "status", "activeForm"]
                        }
                    }
                },
                "required": ["items"]
            },
            returns={
                "type": "string",
                "description": "Rendered todo list with status markers"
            },
            categories=["productivity", "system"],
            dangerous=False
        )

    def execute(self, **kwargs) -> Any:
        """
        Update the todo list with new items and return rendered list.

        Args:
            items: List of todo items (see parameters).

        Returns:
            Rendered todo list as string.
        """
        items = kwargs["items"]
        try:
            return TODO_MANAGER.update(items)
        except ValueError as e:
            return f"Validation error: {e}"
        except Exception as e:
            return f"Error updating todo list: {e}"


def create_todo_write_tool() -> TodoWriteTool:
    """Create and return a TodoWriteTool instance."""
    return TodoWriteTool()