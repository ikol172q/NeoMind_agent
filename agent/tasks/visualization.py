"""
Task visualization utilities for dependency graphs.

Provides:
- TaskVisualizer: ASCII and text-based graph visualization
- DOT export for Graphviz
- Progress tracking visualization
"""

from typing import Dict, List, Set, Optional, Any
from datetime import datetime
from .graph import TaskGraph


class TaskVisualizer:
    """Visualize task dependency graphs in various formats."""

    def __init__(self, task_manager):
        """
        Initialize visualizer with task manager.

        Args:
            task_manager: EnhancedTaskManager instance
        """
        self.task_manager = task_manager
        self.task_graph = task_manager.task_graph

    def ascii_tree(self, root_task_id: Optional[str] = None, max_depth: int = 10) -> str:
        """
        Generate ASCII tree representation of task dependencies.

        Args:
            root_task_id: Root task ID (if None, show all tasks as forest)
            max_depth: Maximum depth to render

        Returns:
            ASCII tree string
        """
        if root_task_id:
            return self._build_subtree(root_task_id, max_depth)
        else:
            # Show forest of tasks with no dependencies (roots)
            roots = [task_id for task_id in self.task_graph.tasks
                     if not self.task_graph.get_dependencies(task_id)]
            if not roots:
                # No roots, pick first task
                roots = list(self.task_graph.tasks.keys())[:1]

            trees = []
            for root in roots:
                trees.append(self._build_subtree(root, max_depth))

            return "\n\n".join(trees)

    def _build_subtree(self, task_id: str, max_depth: int, depth: int = 0,
                       prefix: str = "", is_last: bool = True) -> str:
        """Recursively build ASCII subtree."""
        if depth > max_depth:
            return ""

        task = self.task_manager.get_task(task_id)
        if not task:
            return ""

        # Current node
        branch = "└── " if is_last else "├── "
        line = prefix + branch + self._format_task(task_id, task)

        # Update prefix for children
        child_prefix = prefix + ("    " if is_last else "│   ")

        # Get dependents (tasks that depend on this task)
        dependents = self.task_graph.get_dependents(task_id)
        if not dependents:
            return line

        # Sort dependents for consistent output
        dependents = sorted(dependents)

        # Recursively build child subtrees
        child_lines = []
        for i, child_id in enumerate(dependents):
            child_is_last = (i == len(dependents) - 1)
            child_lines.append(self._build_subtree(child_id, max_depth, depth + 1,
                                                   child_prefix, child_is_last))

        return line + "\n" + "\n".join(child_lines)

    def _format_task(self, task_id: str, task) -> str:
        """Format task for display."""
        status_symbols = {
            "todo": "○",
            "in_progress": "▶",
            "done": "✓"
        }
        symbol = status_symbols.get(task.status, "?")

        # Priority indicator
        priority_str = ""
        if hasattr(task, 'priority') and task.priority > 0:
            priority_str = f" P{task.priority}"

        # Estimated effort
        effort_str = ""
        if hasattr(task, 'estimated_effort') and task.estimated_effort > 0:
            effort_str = f" ({task.estimated_effort}m)"

        return f"{symbol} {task_id}: {task.description[:50]}{'...' if len(task.description) > 50 else ''}{priority_str}{effort_str}"

    def dependency_matrix(self) -> str:
        """
        Generate dependency matrix (tasks × dependencies).

        Returns:
            Matrix as formatted string
        """
        task_ids = sorted(self.task_graph.tasks.keys())
        if not task_ids:
            return "No tasks"

        # Build matrix
        matrix = []
        header = "Task".ljust(10) + " │ " + " ".join([tid.ljust(8) for tid in task_ids])
        matrix.append(header)
        matrix.append("─" * len(header))

        for task_id in task_ids:
            row = task_id.ljust(10) + " │ "
            deps = self.task_graph.get_dependencies(task_id)
            for other_id in task_ids:
                if other_id in deps:
                    row += "X".ljust(8)
                else:
                    row += ".".ljust(8) if task_id != other_id else "-".ljust(8)
            matrix.append(row)

        return "\n".join(matrix)

    def execution_timeline(self) -> str:
        """
        Generate timeline showing parallel execution groups.

        Returns:
            Timeline as formatted string
        """
        try:
            groups = self.task_graph.parallel_groups()
        except ValueError:
            return "Cannot generate timeline: dependency cycle detected"

        if not groups:
            return "No tasks"

        timeline = []
        timeline.append("Execution Timeline (parallel groups):")
        timeline.append("=" * 50)

        for i, group in enumerate(groups):
            timeline.append(f"\nGroup {i + 1} (can run in parallel):")
            for task_id in sorted(group):
                task = self.task_manager.get_task(task_id)
                if task:
                    status = task.status
                    desc = task.description[:40] + "..." if len(task.description) > 40 else task.description
                    timeline.append(f"  • {task_id}: {desc} [{status}]")

        return "\n".join(timeline)

    def critical_path_chart(self) -> str:
        """
        Generate chart showing critical path.

        Returns:
            Critical path chart as string
        """
        try:
            path = self.task_graph.critical_path()
        except ValueError:
            return "Cannot compute critical path: dependency cycle detected"

        if not path:
            return "No critical path (empty graph)"

        chart = []
        chart.append("Critical Path (longest dependency chain):")
        chart.append("=" * 50)

        for i, task_id in enumerate(path):
            task = self.task_manager.get_task(task_id)
            if task:
                arrow = "→" if i < len(path) - 1 else "✓"
                chart.append(f"{task_id}: {task.description[:50]} {arrow}")

        chart.append(f"\nTotal tasks on critical path: {len(path)}")
        chart.append(f"Estimated effort: {self._sum_estimated_effort(path)} minutes")

        return "\n".join(chart)

    def _sum_estimated_effort(self, task_ids: List[str]) -> int:
        """Sum estimated effort for given task IDs."""
        total = 0
        for task_id in task_ids:
            task = self.task_manager.get_task(task_id)
            if hasattr(task, 'estimated_effort'):
                total += task.estimated_effort
        return total

    def progress_summary(self) -> str:
        """
        Generate progress summary with statistics.

        Returns:
            Progress summary as string
        """
        tasks = list(self.task_manager.tasks.values())
        if not tasks:
            return "No tasks"

        total = len(tasks)
        todo = sum(1 for t in tasks if t.status == "todo")
        in_progress = sum(1 for t in tasks if t.status == "in_progress")
        done = sum(1 for t in tasks if t.status == "done")

        # Calculate progress percentage
        progress_pct = (done / total) * 100 if total > 0 else 0

        # Count blocked tasks
        blocked = 0
        completed_ids = {task_id for task_id, task in self.task_manager.tasks.items()
                         if task.status == "done"}
        for task_id, task in self.task_manager.tasks.items():
            if task.status != "done":
                deps = self.task_graph.get_dependencies(task_id)
                if deps and not all(dep in completed_ids for dep in deps):
                    blocked += 1

        summary = []
        summary.append("Task Progress Summary")
        summary.append("=" * 50)
        summary.append(f"Total tasks: {total}")
        summary.append(f"To do: {todo} | In progress: {in_progress} | Done: {done}")
        summary.append(f"Progress: {progress_pct:.1f}%")
        summary.append(f"Blocked tasks: {blocked}")

        # Show ready tasks
        ready = self.task_manager.get_ready_tasks(completed_ids)
        if ready:
            summary.append(f"\nReady to execute ({len(ready)}):")
            for task_id in ready[:5]:  # Limit to 5
                task = self.task_manager.get_task(task_id)
                summary.append(f"  • {task_id}: {task.description[:50]}")
            if len(ready) > 5:
                summary.append(f"  ... and {len(ready) - 5} more")

        return "\n".join(summary)

    def to_dot(self, filename: Optional[str] = None) -> str:
        """
        Generate Graphviz DOT representation of task graph.

        Args:
            filename: If provided, write DOT to file

        Returns:
            DOT string
        """
        dot_lines = []
        dot_lines.append("digraph TaskGraph {")
        dot_lines.append("  rankdir=TB;")
        dot_lines.append("  node [shape=box, style=filled];")

        # Define nodes with status-based colors
        for task_id, task in self.task_manager.tasks.items():
            color = {
                "todo": "lightgray",
                "in_progress": "lightblue",
                "done": "lightgreen"
            }.get(task.status, "white")

            label = f"{task_id}\\n{task.description[:30]}"
            if hasattr(task, 'priority') and task.priority > 0:
                label += f"\\nP{task.priority}"
            dot_lines.append(f'  "{task_id}" [label="{label}", fillcolor="{color}"];')

        # Add edges
        for task_id, task in self.task_manager.tasks.items():
            deps = self.task_graph.get_dependencies(task_id)
            for dep_id in deps:
                dot_lines.append(f'  "{dep_id}" -> "{task_id}";')

        dot_lines.append("}")

        dot_string = "\n".join(dot_lines)

        if filename:
            with open(filename, 'w') as f:
                f.write(dot_string)

        return dot_string

    def print_all_views(self) -> None:
        """Print all visualization views."""
        views = [
            ("Progress Summary", self.progress_summary),
            ("Execution Timeline", self.execution_timeline),
            ("Critical Path", self.critical_path_chart),
            ("Dependency Matrix", self.dependency_matrix),
            ("ASCII Tree", lambda: self.ascii_tree(max_depth=5))
        ]

        for title, view_func in views:
            print(f"\n{'='*60}")
            print(f"{title}")
            print(f"{'='*60}")
            print(view_func())