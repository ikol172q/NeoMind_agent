"""
Enhanced task system with dependency graphs and persistence.

This module provides:
- TaskGraph: Dependency graph with topological ordering
- TaskPersistence: File-based storage with versioning
- TaskVisualization: ASCII and text-based graph visualization
"""

from .graph import TaskGraph
from .persistence import EnhancedTaskManager
from .visualization import TaskVisualizer

__all__ = ["TaskGraph", "EnhancedTaskManager", "TaskVisualizer"]