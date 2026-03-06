"""
Enhanced task persistence with dependency graphs and file-based storage.

Provides:
- EnhancedTask: Task with dependencies, priority, estimated effort
- EnhancedTaskManager: Manages tasks with dependency resolution and persistence
- Integration with existing TaskManager for backward compatibility
"""

import os
import json
import uuid
from typing import Dict, List, Set, Optional, Any, Tuple
from datetime import datetime
from ..task_manager import Task as BaseTask, TaskManager as BaseTaskManager
from ..safety import log_operation
from .graph import TaskGraph


class EnhancedTask(BaseTask):
    """Enhanced task with dependencies, priority, and estimated effort."""

    def __init__(self, description: str, status: str = "todo", dependencies: Optional[List[str]] = None,
                 priority: int = 0, estimated_effort: int = 0, tags: Optional[List[str]] = None):
        """
        Initialize enhanced task.

        Args:
            description: Task description
            status: Task status (todo, in_progress, done)
            dependencies: List of task IDs that must complete before this task
            priority: Priority level (higher = more important)
            estimated_effort: Estimated effort in minutes (0 = unknown)
            tags: List of tags for categorization
        """
        super().__init__(description, status)
        self.dependencies = dependencies or []
        self.priority = priority
        self.estimated_effort = estimated_effort
        self.tags = tags or []
        # Note: id, created_at, updated_at are set by parent

    def to_dict(self) -> Dict[str, Any]:
        """Convert task to dictionary for JSON serialization."""
        base_dict = super().to_dict()
        base_dict.update({
            "dependencies": self.dependencies,
            "priority": self.priority,
            "estimated_effort": self.estimated_effort,
            "tags": self.tags
        })
        return base_dict

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EnhancedTask":
        """Create enhanced task from dictionary."""
        # Handle backward compatibility: old tasks may not have new fields
        description = data["description"]
        status = data.get("status", "todo")
        dependencies = data.get("dependencies", [])
        priority = data.get("priority", 0)
        estimated_effort = data.get("estimated_effort", 0)
        tags = data.get("tags", [])

        task = cls(description, status, dependencies, priority, estimated_effort, tags)
        task.id = data["id"]
        task.created_at = data["created_at"]
        task.updated_at = data["updated_at"]
        return task

    def add_dependency(self, task_id: str) -> None:
        """Add a dependency to this task."""
        if task_id not in self.dependencies:
            self.dependencies.append(task_id)
            self.updated_at = datetime.now().isoformat()

    def remove_dependency(self, task_id: str) -> bool:
        """Remove a dependency from this task."""
        if task_id in self.dependencies:
            self.dependencies.remove(task_id)
            self.updated_at = datetime.now().isoformat()
            return True
        return False

    def update_priority(self, new_priority: int) -> None:
        """Update task priority."""
        self.priority = new_priority
        self.updated_at = datetime.now().isoformat()

    def add_tag(self, tag: str) -> None:
        """Add a tag to this task."""
        if tag not in self.tags:
            self.tags.append(tag)
            self.updated_at = datetime.now().isoformat()

    def remove_tag(self, tag: str) -> bool:
        """Remove a tag from this task."""
        if tag in self.tags:
            self.tags.remove(tag)
            self.updated_at = datetime.now().isoformat()
            return True
        return False


class EnhancedTaskManager(BaseTaskManager):
    """Enhanced task manager with dependency graphs and advanced operations."""

    def __init__(self, data_dir: Optional[str] = None):
        """
        Initialize enhanced task manager.

        Args:
            data_dir: Directory to store tasks.json. Defaults to current directory.
        """
        super().__init__(data_dir)
        self.task_graph = TaskGraph()
        self._rebuild_graph()

    def _rebuild_graph(self) -> None:
        """Rebuild dependency graph from current tasks."""
        self.task_graph = TaskGraph()
        for task_id, task in self.tasks.items():
            # Convert EnhancedTask (or BaseTask) to dict with dependencies
            if isinstance(task, EnhancedTask):
                deps = task.dependencies
            else:
                # BaseTask doesn't have dependencies
                deps = []
            self.task_graph.add_task(task_id, {
                "dependencies": deps,
                "task": task
            })

    def _load_tasks(self) -> None:
        """Load tasks from JSON file, converting to EnhancedTask if needed."""
        if os.path.exists(self.tasks_file):
            try:
                with open(self.tasks_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self.tasks = {}
                for task_id, task_data in data.items():
                    try:
                        # Try to load as EnhancedTask (supports backward compatibility)
                        task = EnhancedTask.from_dict(task_data)
                    except (KeyError, ValueError) as e:
                        # Fall back to BaseTask if missing required fields
                        log_operation("task_load", self.tasks_file,
                                     f"Failed to load enhanced task {task_id}: {e}. Loading as BaseTask.")
                        task = BaseTask.from_dict(task_data)
                    self.tasks[task_id] = task
            except (json.JSONDecodeError, KeyError, ValueError) as e:
                # If file is corrupted, start fresh
                self.tasks = {}
                log_operation("task_load", self.tasks_file,
                             f"Failed to load tasks: {e}. Starting with empty task list.")
        else:
            self.tasks = {}

        self._rebuild_graph()

    def create_task(self, description: str, dependencies: Optional[List[str]] = None,
                    priority: int = 0, estimated_effort: int = 0, tags: Optional[List[str]] = None) -> EnhancedTask:
        """
        Create a new enhanced task and save to disk.

        Args:
            description: Task description
            dependencies: List of task IDs that must complete before this task
            priority: Priority level
            estimated_effort: Estimated effort in minutes
            tags: List of tags

        Returns:
            Created EnhancedTask
        """
        task = EnhancedTask(description, "todo", dependencies, priority, estimated_effort, tags)
        self.tasks[task.id] = task
        self._save_tasks()
        self._rebuild_graph()
        return task

    def update_task_dependencies(self, task_id: str, dependencies: List[str]) -> bool:
        """
        Update task dependencies.

        Args:
            task_id: Task ID
            dependencies: New list of dependency task IDs

        Returns:
            True if successful, False if task not found
        """
        task = self.get_task(task_id)
        if not task or not isinstance(task, EnhancedTask):
            return False

        # Convert to EnhancedTask if it's BaseTask
        if not isinstance(task, EnhancedTask):
            # Upgrade BaseTask to EnhancedTask
            enhanced = EnhancedTask.from_dict(task.to_dict())
            enhanced.dependencies = dependencies
            self.tasks[task_id] = enhanced
        else:
            task.dependencies = dependencies
            task.updated_at = datetime.now().isoformat()

        self._save_tasks()
        self._rebuild_graph()
        return True

    def add_dependency(self, task_id: str, dependency_id: str) -> bool:
        """Add a dependency between tasks."""
        if task_id not in self.tasks or dependency_id not in self.tasks:
            return False

        task = self.tasks[task_id]
        if not isinstance(task, EnhancedTask):
            # Upgrade
            enhanced = EnhancedTask.from_dict(task.to_dict())
            enhanced.add_dependency(dependency_id)
            self.tasks[task_id] = enhanced
        else:
            task.add_dependency(dependency_id)

        self._save_tasks()
        self._rebuild_graph()
        return True

    def remove_dependency(self, task_id: str, dependency_id: str) -> bool:
        """Remove a dependency between tasks."""
        if task_id not in self.tasks:
            return False

        task = self.tasks[task_id]
        if isinstance(task, EnhancedTask):
            success = task.remove_dependency(dependency_id)
            if success:
                self._save_tasks()
                self._rebuild_graph()
            return success
        return False

    def validate_dependencies(self) -> Tuple[bool, List[str]]:
        """
        Validate task dependencies (no cycles, missing tasks).

        Returns:
            (is_valid, list_of_error_messages)
        """
        return self.task_graph.validate()

    def get_execution_order(self) -> List[str]:
        """
        Get topological order of tasks for execution.

        Returns:
            List of task IDs in execution order (dependencies first)

        Raises:
            ValueError: If dependency cycle detected
        """
        return self.task_graph.topological_order()

    def get_parallel_groups(self) -> List[List[str]]:
        """
        Get groups of tasks that can be executed in parallel.

        Returns:
            List of groups, each group is list of task IDs that can run concurrently
        """
        return self.task_graph.parallel_groups()

    def get_ready_tasks(self, completed_tasks: Optional[Set[str]] = None) -> List[str]:
        """
        Get tasks ready for execution (all dependencies completed).

        Args:
            completed_tasks: Set of completed task IDs. If None, uses tasks with status "done"

        Returns:
            List of task IDs ready for execution
        """
        if completed_tasks is None:
            completed_tasks = {task_id for task_id, task in self.tasks.items()
                               if task.status == "done"}

        return self.task_graph.next_ready_tasks(completed_tasks)

    def get_critical_path(self) -> List[str]:
        """
        Compute critical path (longest dependency chain).

        Returns:
            List of task IDs on the critical path
        """
        return self.task_graph.critical_path()

    def get_task_dependencies(self, task_id: str, transitive: bool = False) -> List[str]:
        """
        Get dependencies for a task.

        Args:
            task_id: Task ID
            transitive: If True, return all transitive dependencies

        Returns:
            List of dependency task IDs
        """
        if task_id not in self.tasks:
            return []

        if transitive:
            return list(self.task_graph.transitive_dependencies(task_id))
        else:
            return self.task_graph.get_dependencies(task_id)

    def get_task_dependents(self, task_id: str, transitive: bool = False) -> List[str]:
        """
        Get dependents for a task (tasks that depend on this task).

        Args:
            task_id: Task ID
            transitive: If True, return all transitive dependents

        Returns:
            List of dependent task IDs
        """
        if task_id not in self.tasks:
            return []

        if transitive:
            return list(self.task_graph.transitive_dependents(task_id))
        else:
            return self.task_graph.get_dependents(task_id)

    def can_complete_task(self, task_id: str, completed_tasks: Optional[Set[str]] = None) -> bool:
        """
        Check if a task can be completed (all dependencies satisfied).

        Args:
            task_id: Task ID
            completed_tasks: Set of completed task IDs. If None, uses tasks with status "done"

        Returns:
            True if task can be completed
        """
        if task_id not in self.tasks:
            return False

        if completed_tasks is None:
            completed_tasks = {task_id for task_id, task in self.tasks.items()
                               if task.status == "done"}

        return self.task_graph.is_ready(task_id, completed_tasks)

    def plan_from_goal(self, goal: str, goal_planner, agent=None) -> Dict[str, Any]:
        """
        Create a task plan from a goal using GoalPlanner.

        Args:
            goal: Natural language goal description
            goal_planner: GoalPlanner instance

        Returns:
            Dictionary with plan_id and task_ids created
        """
        # Generate plan from goal
        plan = goal_planner.generate_plan(goal, agent=agent)

        # Convert plan steps to tasks
        task_ids = []
        for i, step in enumerate(plan.get("steps", [])):
            # Create task from step
            task = self.create_task(
                description=step.get("description", f"Step {i+1}"),
                dependencies=[task_ids[dep] for dep in step.get("dependencies", [])
                              if dep < len(task_ids)],
                priority=0,
                estimated_effort=0,
                tags=["plan", f"plan_{plan['id']}"]
            )
            task_ids.append(task.id)

        return {
            "plan_id": plan["id"],
            "task_ids": task_ids,
            "goal": goal
        }

    def export_to_dict(self) -> Dict[str, Dict[str, Any]]:
        """Export all tasks to dictionary for serialization."""
        return {task_id: task.to_dict() for task_id, task in self.tasks.items()}

    def import_from_dict(self, data: Dict[str, Dict[str, Any]]) -> None:
        """Import tasks from dictionary."""
        self.tasks = {}
        for task_id, task_data in data.items():
            try:
                task = EnhancedTask.from_dict(task_data)
                self.tasks[task_id] = task
            except (KeyError, ValueError):
                # Fall back to BaseTask
                task = BaseTask.from_dict(task_data)
                self.tasks[task_id] = task

        self._save_tasks()
        self._rebuild_graph()