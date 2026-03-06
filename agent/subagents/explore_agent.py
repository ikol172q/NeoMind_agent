"""
Explore subagent for codebase exploration and analysis.

Specializes in exploring codebases, searching for files, analyzing
code structure, and answering questions about code organization.
"""

import os
import re
import json
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path

from .base import Subagent, SubagentMetadata


class ExploreAgent(Subagent):
    """Subagent for code exploration and analysis."""

    @classmethod
    def _default_metadata(cls) -> SubagentMetadata:
        return SubagentMetadata(
            name="explore",
            description="Explore codebases, search for files, analyze code structure, and answer questions about code organization.",
            capabilities=[
                "file_search",
                "code_analysis",
                "directory_structure",
                "pattern_matching",
                "dependency_analysis",
                "code_summarization"
            ],
            input_schema={
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "description": "Type of exploration operation",
                        "enum": ["search", "analyze", "structure", "find", "dependencies", "summary"],
                        "default": "search"
                    },
                    "query": {
                        "type": "string",
                        "description": "Search query or file pattern"
                    },
                    "path": {
                        "type": "string",
                        "description": "Path to explore (default: current directory)"
                    },
                    "max_depth": {
                        "type": "integer",
                        "description": "Maximum directory depth to explore",
                        "minimum": 1,
                        "maximum": 10,
                        "default": 3
                    },
                    "file_types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "File extensions to include (e.g., ['.py', '.js', '.md'])"
                    },
                    "pattern": {
                        "type": "string",
                        "description": "Regex pattern for content search"
                    }
                },
                "required": ["operation"]
            },
            output_schema={
                "type": "object",
                "properties": {
                    "success": {"type": "boolean"},
                    "results": {"type": "array"},
                    "summary": {"type": "string"},
                    "file_count": {"type": "integer"},
                    "directory_count": {"type": "integer"},
                    "execution_time": {"type": "number"}
                },
                "required": ["success"]
            },
            categories=["code", "exploration"],
            max_execution_time=60,
            requires_isolation=False
        )

    def __init__(self, metadata: Optional[SubagentMetadata] = None):
        super().__init__(metadata)

    def execute(self, task_description: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute exploration task.

        Args:
            task_description: Description of the exploration task.
            parameters: Exploration parameters.

        Returns:
            Exploration results.
        """
        import time
        start_time = time.time()

        try:
            self.validate_input(parameters)
            operation = parameters.get("operation", "search")
            path = parameters.get("path", os.getcwd())
            max_depth = parameters.get("max_depth", 3)

            # Ensure path exists
            if not os.path.exists(path):
                return {
                    "success": False,
                    "error": f"Path does not exist: {path}",
                    "execution_time": time.time() - start_time
                }

            result = None
            if operation == "search":
                result = self._search_files(parameters, path, max_depth)
            elif operation == "analyze":
                result = self._analyze_codebase(parameters, path, max_depth)
            elif operation == "structure":
                result = self._get_directory_structure(parameters, path, max_depth)
            elif operation == "find":
                result = self._find_content(parameters, path, max_depth)
            elif operation == "dependencies":
                result = self._analyze_dependencies(parameters, path)
            elif operation == "summary":
                result = self._generate_summary(parameters, path, max_depth)
            else:
                result = {
                    "success": False,
                    "error": f"Unknown operation: {operation}"
                }

            result["execution_time"] = time.time() - start_time
            return result

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "execution_time": time.time() - start_time
            }

    def _search_files(self, params: Dict[str, Any], root_path: str,
                     max_depth: int) -> Dict[str, Any]:
        """Search for files matching criteria."""
        query = params.get("query", "")
        file_types = params.get("file_types", [])
        pattern = params.get("pattern", "")

        results = []
        file_count = 0
        dir_count = 0

        for root, dirs, files in os.walk(root_path):
            # Calculate current depth
            current_depth = root[len(root_path):].count(os.sep)
            if current_depth >= max_depth:
                # Don't go deeper
                dirs.clear()

            dir_count += 1

            for file in files:
                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, root_path)

                # Apply filters
                matches = True

                # File type filter
                if file_types:
                    ext = os.path.splitext(file)[1].lower()
                    if ext not in file_types:
                        matches = False

                # Query filter (in filename)
                if query and query.lower() not in file.lower():
                    matches = False

                # Pattern filter (regex in filename)
                if pattern and not re.search(pattern, file, re.IGNORECASE):
                    matches = False

                if matches:
                    file_count += 1
                    file_info = {
                        "path": rel_path,
                        "full_path": file_path,
                        "size": os.path.getsize(file_path),
                        "modified": os.path.getmtime(file_path)
                    }
                    results.append(file_info)

                # Limit results
                if len(results) >= 100:
                    break

        return {
            "success": True,
            "results": results[:50],  # Limit output
            "file_count": file_count,
            "directory_count": dir_count,
            "summary": f"Found {file_count} files matching criteria in {dir_count} directories"
        }

    def _analyze_codebase(self, params: Dict[str, Any], root_path: str,
                         max_depth: int) -> Dict[str, Any]:
        """Analyze codebase structure and statistics."""
        analysis = {
            "total_files": 0,
            "total_size": 0,
            "file_types": {},
            "largest_files": [],
            "recent_files": []
        }

        file_info_list = []

        for root, dirs, files in os.walk(root_path):
            current_depth = root[len(root_path):].count(os.sep)
            if current_depth >= max_depth:
                dirs.clear()

            for file in files:
                file_path = os.path.join(root, file)
                try:
                    size = os.path.getsize(file_path)
                    modified = os.path.getmtime(file_path)
                    ext = os.path.splitext(file)[1].lower()

                    analysis["total_files"] += 1
                    analysis["total_size"] += size

                    # File type statistics
                    analysis["file_types"][ext] = analysis["file_types"].get(ext, 0) + 1

                    file_info = {
                        "path": os.path.relpath(file_path, root_path),
                        "size": size,
                        "modified": modified,
                        "extension": ext
                    }
                    file_info_list.append(file_info)

                except (OSError, IOError):
                    continue

        # Find largest files
        file_info_list.sort(key=lambda x: x["size"], reverse=True)
        analysis["largest_files"] = [
            {"path": f["path"], "size": f["size"]}
            for f in file_info_list[:10]
        ]

        # Find most recent files
        file_info_list.sort(key=lambda x: x["modified"], reverse=True)
        analysis["recent_files"] = [
            {"path": f["path"], "modified": f["modified"]}
            for f in file_info_list[:10]
        ]

        # Format summary
        total_mb = analysis["total_size"] / (1024 * 1024)
        file_type_summary = ", ".join(
            f"{ext}: {count}" for ext, count in
            sorted(analysis["file_types"].items(), key=lambda x: x[1], reverse=True)[:5]
        )

        summary = f"""Codebase Analysis:
• Total files: {analysis['total_files']}
• Total size: {total_mb:.2f} MB
• File types: {file_type_summary}
• Largest file: {analysis['largest_files'][0]['path'] if analysis['largest_files'] else 'N/A'} ({analysis['largest_files'][0]['size'] / 1024:.1f} KB)
• Most recent: {analysis['recent_files'][0]['path'] if analysis['recent_files'] else 'N/A'}"""

        return {
            "success": True,
            "analysis": analysis,
            "summary": summary,
            "file_count": analysis["total_files"]
        }

    def _get_directory_structure(self, params: Dict[str, Any], root_path: str,
                                max_depth: int) -> Dict[str, Any]:
        """Get directory structure as tree."""
        from pathlib import Path

        def build_tree(path: Path, current_depth: int, max_depth: int):
            if current_depth >= max_depth:
                return {"name": path.name, "type": "directory", "children": []}

            tree = {"name": path.name, "type": "directory", "children": []}

            try:
                # Add files
                for item in sorted(path.iterdir()):
                    if item.is_file():
                        tree["children"].append({
                            "name": item.name,
                            "type": "file",
                            "size": item.stat().st_size
                        })
                    elif item.is_dir():
                        # Skip hidden directories
                        if not item.name.startswith('.'):
                            subtree = build_tree(item, current_depth + 1, max_depth)
                            tree["children"].append(subtree)
            except (PermissionError, OSError):
                pass

            return tree

        root = Path(root_path)
        tree = build_tree(root, 0, max_depth)

        return {
            "success": True,
            "tree": tree,
            "summary": f"Directory structure of {root_path} up to depth {max_depth}"
        }

    def _find_content(self, params: Dict[str, Any], root_path: str,
                     max_depth: int) -> Dict[str, Any]:
        """Find content in files."""
        pattern = params.get("pattern", "")
        query = params.get("query", "")
        file_types = params.get("file_types", [])

        if not pattern and not query:
            return {
                "success": False,
                "error": "Either pattern or query must be provided"
            }

        # Use query as simple text search if no regex pattern
        search_pattern = pattern if pattern else re.escape(query)
        regex = re.compile(search_pattern, re.IGNORECASE)

        results = []
        files_searched = 0

        for root, dirs, files in os.walk(root_path):
            current_depth = root[len(root_path):].count(os.sep)
            if current_depth >= max_depth:
                dirs.clear()

            for file in files:
                # File type filter
                if file_types:
                    ext = os.path.splitext(file)[1].lower()
                    if ext not in file_types:
                        continue

                file_path = os.path.join(root, file)
                files_searched += 1

                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                        matches = list(regex.finditer(content))
                        if matches:
                            results.append({
                                "path": os.path.relpath(file_path, root_path),
                                "match_count": len(matches),
                                "sample_matches": [
                                    m.group(0)[:100] for m in matches[:3]
                                ]
                            })
                except (UnicodeDecodeError, IOError, OSError):
                    # Skip binary files or permission errors
                    continue

                # Limit results
                if len(results) >= 50:
                    break

        return {
            "success": True,
            "results": results,
            "files_searched": files_searched,
            "summary": f"Found {len(results)} files containing '{pattern or query}'"
        }

    def _analyze_dependencies(self, params: Dict[str, Any], root_path: str) -> Dict[str, Any]:
        """Analyze dependencies in Python code."""
        # Simplified dependency analysis
        import_count = 0
        imports = set()
        modules = []

        for root, dirs, files in os.walk(root_path):
            for file in files:
                if file.endswith('.py'):
                    file_path = os.path.join(root, file)
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            content = f.read()

                            # Simple import detection
                            import_lines = re.findall(
                                r'^\s*(import|from)\s+([a-zA-Z0-9_.]+)',
                                content,
                                re.MULTILINE
                            )
                            for _, module in import_lines:
                                imports.add(module.split('.')[0])
                                import_count += 1

                        modules.append({
                            "name": os.path.relpath(file_path, root_path),
                            "import_count": len(import_lines)
                        })
                    except (IOError, UnicodeDecodeError):
                        continue

        # Categorize imports
        stdlib_imports = []
        third_party_imports = []
        local_imports = []

        # Simple classification (in reality would need stdlib list)
        for imp in imports:
            if '.' in imp or '/' in imp:
                local_imports.append(imp)
            elif len(imp) < 10:  # Very naive heuristic
                stdlib_imports.append(imp)
            else:
                third_party_imports.append(imp)

        summary = f"""Dependency Analysis:
• Total imports: {import_count}
• Unique modules: {len(imports)}
• Standard library: {len(stdlib_imports)}
• Third-party: {len(third_party_imports)}
• Local: {len(local_imports)}
• Python files: {len(modules)}"""

        return {
            "success": True,
            "imports": list(imports),
            "import_count": import_count,
            "modules": modules[:20],  # Limit
            "summary": summary
        }

    def _generate_summary(self, params: Dict[str, Any], root_path: str,
                         max_depth: int) -> Dict[str, Any]:
        """Generate comprehensive codebase summary."""
        # Combine multiple analyses
        analysis = self._analyze_codebase(params, root_path, max_depth)
        deps = self._analyze_dependencies(params, root_path)
        structure = self._get_directory_structure(params, root_path, 2)  # Shallow structure

        # Extract key insights
        total_files = analysis.get("analysis", {}).get("total_files", 0)
        total_size_mb = analysis.get("analysis", {}).get("total_size", 0) / (1024 * 1024)
        file_types = analysis.get("analysis", {}).get("file_types", {})
        main_file_type = max(file_types.items(), key=lambda x: x[1]) if file_types else (".txt", 0)

        summary = f"""📁 **Codebase Summary: {os.path.basename(root_path)}**

**Statistics:**
• Total files: {total_files}
• Total size: {total_size_mb:.1f} MB
• Main file type: {main_file_type[0]} ({main_file_type[1]} files)

**Structure:**
• Top-level directories: {len(structure.get('tree', {}).get('children', [])) if structure.get('tree') else 0}

**Dependencies:**
• Unique imports: {len(deps.get('imports', []))}
• Python modules: {len(deps.get('modules', []))}

**Key Insights:**
1. This appears to be a {self._classify_project(file_types)} project.
2. {self._get_size_classification(total_size_mb)}
3. {self._get_complexity_insight(total_files, deps.get('import_count', 0))}
"""

        return {
            "success": True,
            "summary": summary,
            "detailed_analysis": {
                "statistics": analysis.get("analysis", {}),
                "dependencies": deps,
                "structure": structure.get("tree", {})
            }
        }

    def _classify_project(self, file_types: Dict[str, int]) -> str:
        """Classify project type based on file extensions."""
        priorities = [
            (['.py', '.pyc', '.pyo'], "Python"),
            (['.js', '.jsx', '.ts', '.tsx'], "JavaScript/TypeScript"),
            (['.java', '.class', '.jar'], "Java"),
            (['.cpp', '.c', '.h', '.hpp'], "C/C++"),
            (['.go'], "Go"),
            (['.rs'], "Rust"),
            (['.rb'], "Ruby"),
            (['.php'], "PHP"),
            (['.html', '.css', '.scss'], "Web"),
        ]

        for extensions, language in priorities:
            if any(ext in file_types for ext in extensions):
                return language

        return "mixed-technology"

    def _get_size_classification(self, size_mb: float) -> str:
        """Classify project size."""
        if size_mb < 1:
            return "Small project (<1 MB)"
        elif size_mb < 10:
            return "Medium project (1-10 MB)"
        elif size_mb < 100:
            return "Large project (10-100 MB)"
        else:
            return "Very large project (>100 MB)"

    def _get_complexity_insight(self, file_count: int, import_count: int) -> str:
        """Provide complexity insight."""
        if file_count == 0:
            return "Empty or non-code project."
        elif file_count < 10:
            return "Simple project with few files."
        elif import_count > file_count * 2:
            return "High dependency complexity relative to code size."
        elif import_count > 20:
            return "Moderate dependency usage."
        else:
            return "Minimal external dependencies."