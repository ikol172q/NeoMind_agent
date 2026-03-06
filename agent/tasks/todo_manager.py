"""
Simple todo manager for tracking LLM progress.

Provides TodoManager class that validates and renders a todo list,
enforcing constraints like max 20 items, only one in_progress item.
"""

from typing import List, Dict, Any


class TodoManager:
    """Manages a simple todo list with validation."""

    def __init__(self):
        self.items: List[Dict[str, str]] = []

    def update(self, items: List[Dict[str, Any]]) -> str:
        """
        Update the todo list with new items.

        Args:
            items: List of todo items, each with:
                - content (str): Description of the task
                - status (str): "pending", "in_progress", or "completed"
                - activeForm (str): Present continuous description shown when in_progress

        Returns:
            Rendered todo list as string.

        Raises:
            ValueError: If validation fails.
        """
        validated = []
        in_progress_count = 0

        for i, item in enumerate(items):
            content = str(item.get("content", "")).strip()
            status = str(item.get("status", "pending")).lower()
            active_form = str(item.get("activeForm", "")).strip()

            if not content:
                raise ValueError(f"Item {i}: content required")
            if status not in ("pending", "in_progress", "completed"):
                raise ValueError(f"Item {i}: invalid status '{status}'")
            if not active_form:
                raise ValueError(f"Item {i}: activeForm required")
            if status == "in_progress":
                in_progress_count += 1

            validated.append({
                "content": content,
                "status": status,
                "activeForm": active_form
            })

        if len(validated) > 20:
            raise ValueError("Maximum 20 todo items allowed")
        if in_progress_count > 1:
            raise ValueError("Only one item can be in_progress at a time")

        self.items = validated
        return self.render()

    def render(self) -> str:
        """Render todo list as a readable string."""
        if not self.items:
            return "No todos."

        lines = []
        for item in self.items:
            marker = {
                "completed": "[x]",
                "in_progress": "[>]",
                "pending": "[ ]"
            }.get(item["status"], "[?]")

            suffix = f" <- {item['activeForm']}" if item["status"] == "in_progress" else ""
            lines.append(f"{marker} {item['content']}{suffix}")

        completed = sum(1 for item in self.items if item["status"] == "completed")
        lines.append(f"\n({completed}/{len(self.items)} completed)")

        return "\n".join(lines)

    def has_open_items(self) -> bool:
        """Check if there are any incomplete items."""
        return any(item["status"] != "completed" for item in self.items)

    def get_items(self) -> List[Dict[str, str]]:
        """Get current todo items."""
        return self.items.copy()

    def clear(self) -> None:
        """Clear all todo items."""
        self.items = []


# Global instance
TODO_MANAGER = TodoManager()