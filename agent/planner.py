"""
Planning system for self-modification of code.
Provides dependency analysis, change ordering, and rollback planning.
"""
import os
import ast
import re
import json
import logging
from typing import List, Dict, Any, Tuple, Set, Optional
from datetime import datetime

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
        # Separate Python files for dependency analysis
        py_files = [fp for fp in file_paths if fp.endswith('.py')]
        # Build dependency graph among Python files
        graph = self.build_dependency_graph(py_files)
        # Topological order returns dependents first (zero indegree nodes are files with no incoming dependencies).
        order = self.topological_order(graph)
        # We need dependencies first, so reverse the order.
        order.reverse()
        # Now order has dependencies first (files that others depend on) before dependents.

        # Flatten changes according to file order
        ordered_changes = []
        for fp in order:
            ordered_changes.extend(changes_by_file[fp])
        # Add non-Python files at the end
        non_py_files = [fp for fp in file_paths if not fp.endswith('.py')]
        for fp in non_py_files:
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


class GoalPlanner:
    """Generates and manages plans from natural language goals."""

    def __init__(self, data_dir: Optional[str] = None):
        self.data_dir = data_dir or os.getcwd()
        self.plans_file = os.path.join(self.data_dir, ".plans.json")
        self.plans: Dict[str, Dict] = {}
        self._load_plans()

    def _load_plans(self) -> None:
        """Load plans from JSON file."""
        if os.path.exists(self.plans_file):
            try:
                with open(self.plans_file, 'r', encoding='utf-8') as f:
                    self.plans = json.load(f)
            except (json.JSONDecodeError, IOError):
                self.plans = {}
        else:
            self.plans = {}

    def _save_plans(self) -> bool:
        """Save plans to JSON file."""
        try:
            with open(self.plans_file, 'w', encoding='utf-8') as f:
                json.dump(self.plans, f, indent=2)
            return True
        except (IOError, TypeError):
            return False

    def generate_plan(self, goal: str, agent: Any) -> Dict[str, Any]:
        """
        Generate a step-by-step plan from a goal using AI.

        Args:
            goal: Natural language goal description
            agent: DeepSeekStreamingChat instance for AI completion

        Returns:
            Plan dictionary with id, goal, steps, status
        """
        import uuid
        from datetime import datetime

        prompt = f"""Create a step-by-step plan to achieve this goal: "{goal}"

The plan should be a sequence of actionable steps. Each step should:
1. Be clear and specific
2. Have a single actionable task
3. Include expected outcome or success criteria
4. Be numbered sequentially

Format the response as a JSON array of step objects, each with:
- "description": string describing the step
- "action": string suggesting the action (e.g., "write code", "run test", "create file")
- "details": string with additional details or commands to execute
- "dependencies": array of step indices that must complete before this step (empty if none)

Example:
[
  {{
    "description": "Set up project structure",
    "action": "create directory",
    "details": "Create src/ and tests/ directories",
    "dependencies": []
  }},
  {{
    "description": "Implement core functionality",
    "action": "write code",
    "details": "Write main.py with basic functionality",
    "dependencies": [0]
  }}
]

Now generate the plan for: "{goal}"
"""
        try:
            # Use AI to generate plan
            messages = [{"role": "user", "content": prompt}]
            response = agent.generate_completion(messages, temperature=0.7, max_tokens=2000)

            # Parse JSON from response
            import re
            json_match = re.search(r'\[\s*\{.*\}\s*\]', response, re.DOTALL)
            if json_match:
                steps_json = json_match.group(0)
                steps = json.loads(steps_json)
            else:
                # Fallback: treat each line as a step
                steps = []
                for line in response.strip().split('\n'):
                    line = line.strip()
                    if line and line[0].isdigit() and '.' in line:
                        desc = line.split('.', 1)[1].strip()
                        steps.append({
                            "description": desc,
                            "action": "execute",
                            "details": "",
                            "dependencies": []
                        })

            # Create plan object
            plan_id = str(uuid.uuid4())[:8]
            plan = {
                "id": plan_id,
                "goal": goal,
                "steps": steps,
                "status": "pending",
                "current_step": 0,
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat()
            }

            self.plans[plan_id] = plan
            self._save_plans()
            return plan

        except Exception as e:
            # Fallback plan
            import uuid
            from datetime import datetime
            plan_id = str(uuid.uuid4())[:8]
            plan = {
                "id": plan_id,
                "goal": goal,
                "steps": [
                    {
                        "description": f"Analyze the goal: {goal}",
                        "action": "analyze",
                        "details": f"Understand what needs to be done to achieve: {goal}",
                        "dependencies": []
                    },
                    {
                        "description": "Implement the solution",
                        "action": "execute",
                        "details": "Carry out the necessary actions",
                        "dependencies": [0]
                    }
                ],
                "status": "pending",
                "current_step": 0,
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat()
            }
            self.plans[plan_id] = plan
            self._save_plans()
            return plan

    def get_plan(self, plan_id: str) -> Optional[Dict[str, Any]]:
        """Get plan by ID."""
        return self.plans.get(plan_id)

    def list_plans(self, status_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        """List all plans, optionally filtered by status."""
        plans = list(self.plans.values())
        if status_filter:
            plans = [plan for plan in plans if plan.get("status") == status_filter]
        return sorted(plans, key=lambda p: p.get("created_at", ""), reverse=True)

    def update_plan_status(self, plan_id: str, status: str) -> bool:
        """Update plan status."""
        plan = self.get_plan(plan_id)
        if not plan:
            return False
        valid_statuses = {"pending", "in_progress", "completed", "failed"}
        if status not in valid_statuses:
            return False
        plan["status"] = status
        plan["updated_at"] = datetime.now().isoformat()
        self._save_plans()
        return True

    def advance_step(self, plan_id: str) -> bool:
        """Advance to next step in plan."""
        plan = self.get_plan(plan_id)
        if not plan:
            return False
        if plan["current_step"] >= len(plan["steps"]) - 1:
            return False
        plan["current_step"] += 1
        plan["updated_at"] = datetime.now().isoformat()
        self._save_plans()
        return True

    def get_current_step(self, plan_id: str) -> Optional[Dict[str, Any]]:
        """Get current step for plan."""
        plan = self.get_plan(plan_id)
        if not plan:
            return None
        steps = plan.get("steps", [])
        current_idx = plan.get("current_step", 0)
        if current_idx < len(steps):
            return steps[current_idx]
        return None

    def delete_plan(self, plan_id: str) -> bool:
        """Delete plan by ID."""
        if plan_id in self.plans:
            del self.plans[plan_id]
            self._save_plans()
            return True
        return False


# Convenience function
def plan_changes(changes: List[Dict[str, Any]], root_path: str) -> List[Dict[str, Any]]:
    """Convenience function to plan changes."""
    planner = Planner(root_path)
    return planner.plan_changes(changes)