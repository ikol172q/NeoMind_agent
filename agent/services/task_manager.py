"""
Task management system for neomind.
Provides persistent task tracking with CRUD operations.
"""
import os
import json
import uuid
from typing import List, Dict, Any, Optional
from datetime import datetime
from agent.services.safety_service import log_operation


class Task:
    """A task with unique ID, description, status, and timestamps."""

    def __init__(self, description: str, status: str = "todo"):
        self.id = str(uuid.uuid4())[:8]  # Short ID
        self.description = description
        self.status = status  # todo, in_progress, done
        self.created_at = datetime.now().isoformat()
        self.updated_at = self.created_at

    def to_dict(self) -> Dict[str, str]:
        """Convert task to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "description": self.description,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at
        }

    @classmethod
    def from_dict(cls, data: Dict[str, str]) -> "Task":
        """Create task from dictionary."""
        task = cls(data["description"], data["status"])
        task.id = data["id"]
        task.created_at = data["created_at"]
        task.updated_at = data["updated_at"]
        return task

    def update_status(self, new_status: str) -> None:
        """Update task status and timestamp."""
        valid_statuses = {"todo", "in_progress", "done"}
        if new_status not in valid_statuses:
            raise ValueError(f"Invalid status '{new_status}'. Must be one of: {valid_statuses}")
        self.status = new_status
        self.updated_at = datetime.now().isoformat()


class TaskManager:
    """Manages persistent storage of tasks."""

    def __init__(self, data_dir: Optional[str] = None):
        """
        Initialize task manager.

        Args:
            data_dir: Directory to store tasks.json. Defaults to current directory.
        """
        self.data_dir = data_dir or os.getcwd()
        self.tasks_file = os.path.join(self.data_dir, ".tasks.json")
        self.tasks: Dict[str, Task] = {}
        self._load_tasks()

    def _load_tasks(self) -> None:
        """Load tasks from JSON file."""
        if os.path.exists(self.tasks_file):
            try:
                with open(self.tasks_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self.tasks = {task_id: Task.from_dict(task_data)
                             for task_id, task_data in data.items()}
            except (json.JSONDecodeError, KeyError, ValueError, PermissionError, IOError) as e:
                # If file is corrupted or inaccessible, start fresh
                self.tasks = {}
                log_operation("task_load", self.tasks_file,
                             f"Failed to load tasks: {e}. Starting with empty task list.")
        else:
            self.tasks = {}

    def _save_tasks(self) -> bool:
        """Save tasks to JSON file."""
        try:
            data = {task_id: task.to_dict() for task_id, task in self.tasks.items()}
            with open(self.tasks_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            log_operation("task_save", self.tasks_file, f"Saved {len(self.tasks)} tasks.")
            return True
        except (IOError, TypeError) as e:
            log_operation("task_save_error", self.tasks_file, f"Failed to save tasks: {e}")
            return False

    def create_task(self, description: str) -> Task:
        """Create a new task and save to disk."""
        task = Task(description)
        self.tasks[task.id] = task
        self._save_tasks()
        return task

    def get_task(self, task_id: str) -> Optional[Task]:
        """Get task by ID."""
        return self.tasks.get(task_id)

    def list_tasks(self, status_filter: Optional[str] = None) -> List[Task]:
        """List all tasks, optionally filtered by status."""
        tasks = list(self.tasks.values())
        if status_filter:
            tasks = [task for task in tasks if task.status == status_filter]
        return sorted(tasks, key=lambda t: t.created_at, reverse=True)

    def update_task_status(self, task_id: str, new_status: str) -> bool:
        """Update task status and save to disk."""
        task = self.get_task(task_id)
        if not task:
            return False
        try:
            task.update_status(new_status)
            self._save_tasks()
            return True
        except ValueError:
            return False

    def delete_task(self, task_id: str) -> bool:
        """Delete task by ID."""
        if task_id in self.tasks:
            del self.tasks[task_id]
            self._save_tasks()
            return True
        return False

    def clear_all_tasks(self) -> int:
        """Delete all tasks and return count deleted."""
        count = len(self.tasks)
        self.tasks.clear()
        self._save_tasks()
        return count