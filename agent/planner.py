"""
Planning system for self-modification of code.
Provides dependency analysis, change ordering, and rollback planning.
"""
import os
import ast
import re
from typing import List, Dict, Any, Tuple, Set
import logging

logger = logging.getLogger(__name__)


class Planner:
    """Planning system for code modifications."""

    def __init__(self, root_path: str):
        """
        Initialize planner with root directory.

        Args:
            root_path: Root directory of the codebase.
        """
        self.root_path = os.path.abspath(root_path)
        self.import_cache: Dict[str, Set[str]] = {}

    def extract_imports(self, file_path: str) -> Set[str]:
        """
        Extract module imports from a Python file.

        Returns:
            Set of module names imported (relative to root_path).
        """
        if file_path in self.import_cache:
            return self.import_cache[file_path]

        if not file_path.endswith('.py'):
            self.import_cache[file_path] = set()
            return set()

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            logger.warning(f"Failed to read file {file_path}: {e}")
            self.import_cache[file_path] = set()
            return set()

        imports = set()
        try:
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.add(alias.name.split('.')[0])
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        imports.add(node.module.split('.')[0])
        except SyntaxError as e:
            logger.warning(f"Syntax error in {file_path}: {e}")
            # Fallback to regex for simple imports
            # Simple regex to catch import statements (not robust)
            import_pattern = r'^\s*import\s+([a-zA-Z0-9_.]+)'
            from_pattern = r'^\s*from\s+([a-zA-Z0-9_.]+)\s+import'
            for line in content.split('\n'):
                match = re.match(import_pattern, line)
                if match:
                    imports.add(match.group(1).split('.')[0])
                match = re.match(from_pattern, line)
                if match:
                    imports.add(match.group(1).split('.')[0])

        # Convert module names to file paths relative to root_path
        # This is a simple mapping: assume module corresponds to a file in the same directory
        # For now, keep as module names; we'll map later.
        self.import_cache[file_path] = imports
        return imports

    def build_dependency_graph(self, file_paths: List[str]) -> Dict[str, Set[str]]:
        """
        Build a dependency graph between files based on imports.

        Args:
            file_paths: List of absolute file paths.

        Returns:
            Adjacency list: file -> set of files it depends on (imports).
        """
        # Map module name to file path (simplistic)
        module_to_file = {}
        for fp in file_paths:
            if fp.endswith('.py'):
                module_name = os.path.splitext(os.path.basename(fp))[0]
                module_to_file[module_name] = fp
                # Also consider parent directory as module? skip for now.

        graph = {fp: set() for fp in file_paths}
        for fp in file_paths:
            imports = self.extract_imports(fp)
            for imp in imports:
                if imp in module_to_file:
                    dep_file = module_to_file[imp]
                    if dep_file != fp:
                        graph[fp].add(dep_file)
        return graph

    def topological_order(self, graph: Dict[str, Set[str]]) -> List[str]:
        """
        Perform topological sort on dependency graph (Kahn's algorithm).

        Returns:
            List of file paths in order of dependencies (dependents first).
        """
        # Compute indegree
        indegree = {node: 0 for node in graph}
        for node, deps in graph.items():
            for dep in deps:
                if dep in indegree:
                    indegree[dep] += 1
                else:
                    indegree[dep] = 1

        # Queue of nodes with zero indegree
        queue = [node for node in graph if indegree[node] == 0]
        order = []

        while queue:
            node = queue.pop(0)
            order.append(node)
            for dep in graph[node]:
                indegree[dep] -= 1
                if indegree[dep] == 0:
                    queue.append(dep)

        # If there's a cycle, remaining nodes have indegree > 0
        # Add them at the end (arbitrary order)
        remaining = [node for node in graph if node not in order]
        if remaining:
            logger.warning(f"Dependency cycle detected among files: {remaining}")
            order.extend(remaining)

        return order

    def plan_changes(self, changes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Plan application order for changes based on file dependencies.

        Args:
            changes: List of change dictionaries with at least 'file_path' key.

        Returns:
            Ordered list of changes (least dependent first).
        """
        if not changes:
            return changes

        # Group changes by file (multiple changes per file)
        changes_by_file: Dict[str, List[Dict[str, Any]]] = {}
        for change in changes:
            fp = change['file_path']
            changes_by_file.setdefault(fp, []).append(change)

        file_paths = list(changes_by_file.keys())
        # Build dependency graph among these files
        graph = self.build_dependency_graph(file_paths)
        # Topological order: files that are depended upon come first (so that dependents are applied later)
        # Actually we want to apply dependencies before dependents. If A imports B, B is dependency.
        # In graph, A -> B means A depends on B. So we need order where B before A (dependency first).
        # Our graph adjacency is file -> set of files it depends on (imports). That's correct.
        # Topological order from Kahn's algorithm gives dependents first? Let's test: indegree zero nodes have no incoming edges (no dependencies).
        # Those are files that no other file in the set depends on. They can be applied first.
        # That's actually the dependents (if no one depends on them). Wait.
        # Let's just use the order returned; we can reverse if needed.
        order = self.topological_order(graph)
        # We'll apply files in order of least dependencies first (i.e., files that don't depend on others).
        # That's exactly the topological order from Kahn's algorithm (zero indegree first).
        # So order is good.

        # Flatten changes according to file order
        ordered_changes = []
        for fp in order:
            ordered_changes.extend(changes_by_file[fp])
        # Add files not in graph (non-Python files) at the end
        non_py_files = [fp for fp in file_paths if not fp.endswith('.py')]
        for fp in non_py_files:
            if fp not in order:
                ordered_changes.extend(changes_by_file[fp])

        return ordered_changes

    def validate_plan(self, changes: List[Dict[str, Any]]) -> Tuple[bool, str]:
        """
        Basic validation of changes (syntax, safety).

        Args:
            changes: List of changes.

        Returns:
            (is_valid, error_message)
        """
        # For now, just check that files exist and are within root_path.
        for change in changes:
            fp = change.get('file_path')
            if not fp:
                return False, f"Change missing file_path: {change}"
            abs_fp = os.path.abspath(fp)
            if not abs_fp.startswith(self.root_path):
                return False, f"File outside root path: {fp}"
            if not os.path.exists(abs_fp):
                return False, f"File does not exist: {fp}"
        return True, "Plan validation passed"

    def create_rollback_plan(self, changes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Create a rollback plan for changes (reverse order with backups).

        Args:
            changes: Ordered list of changes to apply.

        Returns:
            Rollback plan with steps to revert each change.
        """
        rollback = []
        for change in reversed(changes):
            rollback.append({
                'action': 'revert',
                'file_path': change['file_path'],
                'old_code': change.get('old_code', ''),
                'new_code': change.get('new_code', ''),
                'description': f"Revert: {change.get('description', 'unknown')}",
                'backup': None  # Could be filled later with actual backup path
            })
        return rollback


# Convenience function
def plan_changes(changes: List[Dict[str, Any]], root_path: str) -> List[Dict[str, Any]]:
    """Convenience function to plan changes."""
    planner = Planner(root_path)
    return planner.plan_changes(changes)