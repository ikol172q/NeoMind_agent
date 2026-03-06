"""
Dependency graph for tasks with topological ordering and cycle detection.

Provides:
- TaskGraph: Builds dependency graph from tasks with dependencies
- Topological ordering for task execution
- Cycle detection and validation
- Parallel execution group identification
"""

from typing import Dict, List, Set, Tuple, Optional
from collections import defaultdict, deque


class TaskGraph:
    """Dependency graph for tasks with topological ordering."""

    def __init__(self):
        """Initialize empty graph."""
        self.graph: Dict[str, Set[str]] = defaultdict(set)  # task_id -> set of dependents (edges: task_id depends on dependent?)
        self.reverse_graph: Dict[str, Set[str]] = defaultdict(set)  # task_id -> set of dependencies
        self.tasks: Dict[str, dict] = {}  # task_id -> task data (must have 'dependencies' list)

    def add_task(self, task_id: str, task_data: dict) -> None:
        """
        Add a task to the graph.

        Args:
            task_id: Unique task identifier
            task_data: Task dictionary with 'dependencies' list (list of task IDs)
        """
        self.tasks[task_id] = task_data
        dependencies = task_data.get('dependencies', [])

        # Validate dependencies exist (can be added later)
        for dep_id in dependencies:
            self.graph[dep_id].add(task_id)  # dep_id -> task_id edge means task_id depends on dep_id
            self.reverse_graph[task_id].add(dep_id)

    def build_from_tasks(self, tasks: Dict[str, dict]) -> None:
        """
        Build graph from dictionary of tasks.

        Args:
            tasks: {task_id: task_data} where task_data has 'dependencies' list
        """
        self.tasks = {}
        self.graph = defaultdict(set)
        self.reverse_graph = defaultdict(set)

        for task_id, task_data in tasks.items():
            self.add_task(task_id, task_data)

    def validate(self) -> Tuple[bool, List[str]]:
        """
        Validate graph for cycles and self-dependencies.

        Returns:
            (is_valid, list_of_error_messages)
        """
        errors = []

        # Check for self-dependencies
        for task_id in self.tasks:
            if task_id in self.reverse_graph.get(task_id, set()):
                errors.append(f"Task '{task_id}' depends on itself")

        # Check for missing dependencies
        for task_id, deps in self.reverse_graph.items():
            for dep_id in deps:
                if dep_id not in self.tasks:
                    errors.append(f"Task '{task_id}' depends on missing task '{dep_id}'")

        # Check for cycles
        try:
            self.topological_order()
        except ValueError as e:
            errors.append(f"Dependency cycle detected: {e}")

        return len(errors) == 0, errors

    def topological_order(self) -> List[str]:
        """
        Perform topological sort (Kahn's algorithm).

        Returns:
            List of task IDs in execution order (dependencies first).

        Raises:
            ValueError: If cycle detected.
        """
        # Compute indegree (number of dependencies for each task)
        indegree = {task_id: 0 for task_id in self.tasks}
        for task_id in self.tasks:
            indegree[task_id] = len(self.reverse_graph.get(task_id, set()))

        # Queue of tasks with zero indegree
        queue = deque([task_id for task_id, deg in indegree.items() if deg == 0])
        order = []

        while queue:
            task_id = queue.popleft()
            order.append(task_id)

            # Reduce indegree of dependents
            for dependent in self.graph.get(task_id, set()):
                indegree[dependent] -= 1
                if indegree[dependent] == 0:
                    queue.append(dependent)

        # Check for cycles
        if len(order) != len(self.tasks):
            # Find remaining tasks with positive indegree (cycle members)
            remaining = [task_id for task_id in self.tasks if task_id not in order]
            raise ValueError(f"Cycle involving tasks: {remaining}")

        return order

    def parallel_groups(self) -> List[List[str]]:
        """
        Group tasks that can be executed in parallel.

        Returns:
            List of groups, where each group is a list of task IDs that can run
            concurrently (no dependencies within group).
        """
        order = self.topological_order()

        # Build level assignment using BFS
        levels: Dict[str, int] = {}
        for task_id in order:
            deps = self.reverse_graph.get(task_id, set())
            if not deps:
                levels[task_id] = 0
            else:
                levels[task_id] = max(levels[dep] for dep in deps) + 1

        # Group by level
        groups_dict: Dict[int, List[str]] = defaultdict(list)
        for task_id, level in levels.items():
            groups_dict[level].append(task_id)

        # Convert to list sorted by level
        sorted_levels = sorted(groups_dict.keys())
        return [groups_dict[level] for level in sorted_levels]

    def get_dependencies(self, task_id: str) -> List[str]:
        """Get direct dependencies for a task."""
        return list(self.reverse_graph.get(task_id, set()))

    def get_dependents(self, task_id: str) -> List[str]:
        """Get direct dependents (tasks that depend on this task)."""
        return list(self.graph.get(task_id, set()))

    def transitive_dependencies(self, task_id: str) -> Set[str]:
        """Get all transitive dependencies (recursive)."""
        visited: Set[str] = set()
        stack = [task_id]

        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            for dep in self.reverse_graph.get(current, set()):
                if dep not in visited:
                    stack.append(dep)

        visited.remove(task_id)  # Exclude self
        return visited

    def transitive_dependents(self, task_id: str) -> Set[str]:
        """Get all transitive dependents (recursive)."""
        visited: Set[str] = set()
        stack = [task_id]

        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            for dep in self.graph.get(current, set()):
                if dep not in visited:
                    stack.append(dep)

        visited.remove(task_id)  # Exclude self
        return visited

    def is_ready(self, task_id: str, completed_tasks: Set[str]) -> bool:
        """
        Check if a task is ready to execute (all dependencies completed).

        Args:
            task_id: Task to check
            completed_tasks: Set of completed task IDs

        Returns:
            True if all dependencies are completed
        """
        deps = self.reverse_graph.get(task_id, set())
        return all(dep in completed_tasks for dep in deps)

    def next_ready_tasks(self, completed_tasks: Set[str]) -> List[str]:
        """
        Get list of tasks ready to execute (dependencies completed).

        Args:
            completed_tasks: Set of completed task IDs

        Returns:
            List of task IDs ready for execution
        """
        ready = []
        for task_id in self.tasks:
            if task_id not in completed_tasks and self.is_ready(task_id, completed_tasks):
                ready.append(task_id)
        return ready

    def critical_path(self) -> List[str]:
        """
        Compute critical path (longest path) in the dependency graph.
        Assumes each task has equal weight.

        Returns:
            List of task IDs on the critical path
        """
        # For simplicity, we compute longest path in DAG using topological order
        order = self.topological_order()

        # Distance and predecessor arrays
        dist = {task_id: 0 for task_id in order}
        pred = {task_id: None for task_id in order}

        for task_id in order:
            for dependent in self.graph.get(task_id, set()):
                if dist[dependent] < dist[task_id] + 1:
                    dist[dependent] = dist[task_id] + 1
                    pred[dependent] = task_id

        # Find task with maximum distance
        if not order:
            return []

        max_task = max(dist.items(), key=lambda x: x[1])[0]

        # Reconstruct path
        path = []
        current = max_task
        while current is not None:
            path.append(current)
            current = pred[current]

        return list(reversed(path))