# agent/workspace_manager.py
import os
import fnmatch
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import time


class WorkspaceManager:
    """Manages workspace context for coding mode."""

    def __init__(self, project_root: Optional[str] = None):
        """
        Initialize workspace manager.

        Args:
            project_root: Root directory of the project (defaults to current working directory)
        """
        self.project_root = Path(project_root or os.getcwd()).resolve()
        self.files_cache = []  # List of file paths relative to project_root
        self.file_metadata = {}  # path -> {size, mtime, type, etc.}
        self.recently_accessed = []  # List of recently accessed files (path, timestamp)
        self.scan_time = 0
        self._exclude_patterns = [
            '.git', '__pycache__', '.pytest_cache', '.venv', 'venv',
            'node_modules', '.idea', '.vscode', '.vs', '*.pyc', '*.pyo',
            '*.so', '*.dll', '*.exe', '*.bin', '*.class', '*.jar'
        ]
        self._include_extensions = [
            '.py', '.js', '.ts', '.jsx', '.tsx', '.java', '.c', '.cpp', '.h',
            '.hpp', '.go', '.rs', '.rb', '.php', '.swift', '.kt', '.scala',
            '.html', '.css', '.scss', '.less', '.json', '.yaml', '.yml',
            '.xml', '.toml', '.ini', '.cfg', '.conf', '.md', '.txt', '.rst',
            '.sql', '.sh', '.bash', '.zsh', '.ps1', '.bat', '.csv', '.tsv'
        ]

    def scan(self, force_refresh: bool = False) -> List[str]:
        """
        Scan project directory for files.

        Args:
            force_refresh: If True, force rescan even if cache is recent

        Returns:
            List of file paths relative to project_root
        """
        # If cache is fresh (less than 5 minutes) and not forcing refresh
        if not force_refresh and time.time() - self.scan_time < 300 and self.files_cache:
            return self.files_cache

        self.files_cache = []
        self.file_metadata = {}

        for root, dirs, files in os.walk(self.project_root, topdown=True):
            # Filter directories using exclude patterns
            dirs[:] = [d for d in dirs if not self._should_exclude(d, is_dir=True)]

            for file in files:
                if self._should_exclude(file, is_dir=False):
                    continue
                file_path = Path(root) / file
                try:
                    rel_path = file_path.relative_to(self.project_root)
                    stat = file_path.stat()
                    self.files_cache.append(str(rel_path))
                    self.file_metadata[str(rel_path)] = {
                        'size': stat.st_size,
                        'mtime': stat.st_mtime,
                        'absolute_path': str(file_path),
                        'extension': file_path.suffix.lower()
                    }
                except (ValueError, OSError):
                    # Skip files outside project root or inaccessible
                    continue

        self.scan_time = time.time()
        return self.files_cache

    def _should_exclude(self, name: str, is_dir: bool) -> bool:
        """Check if a file/directory should be excluded."""
        for pattern in self._exclude_patterns:
            if fnmatch.fnmatch(name, pattern):
                return True
            if is_dir and pattern == name:
                return True
        return False

    def get_files(self) -> List[Dict[str, any]]:
        """
        Get list of files with metadata.

        Returns:
            List of dictionaries with file metadata
        """
        self.scan()  # Ensure cache is fresh
        return [
            {'path': path, **self.file_metadata.get(path, {})}
            for path in self.files_cache
        ]

    def track_file_access(self, file_path: str) -> None:
        """
        Record that a file was accessed.

        Args:
            file_path: Path to file (relative or absolute)
        """
        # Normalize path
        try:
            path_obj = Path(file_path)
            if path_obj.is_absolute():
                rel_path = path_obj.relative_to(self.project_root)
            else:
                rel_path = Path(file_path)
            rel_str = str(rel_path)
            # Add to recently accessed (with timestamp)
            self.recently_accessed.append((rel_str, time.time()))
            # Keep only last 20
            self.recently_accessed = self.recently_accessed[-20:]
        except (ValueError, OSError):
            # File not in project or invalid path
            pass

    def find_file(self, pattern: str) -> List[str]:
        """
        Find files matching pattern (supports glob patterns).

        Args:
            pattern: Glob pattern to match (e.g., "*.py", "**/test_*.py")

        Returns:
            List of matching file paths (relative to project_root)
        """
        self.scan()
        matches = []
        for file_path in self.files_cache:
            if fnmatch.fnmatch(file_path, pattern):
                matches.append(file_path)
            elif pattern.lower() in file_path.lower():
                # Also do substring match if no glob characters
                if '*' not in pattern and '?' not in pattern and '[' not in pattern:
                    matches.append(file_path)
        return matches

    def get_file_context(self, file_path: str, max_lines: int = 100) -> Optional[str]:
        """
        Read file with surrounding context.

        Args:
            file_path: Path to file (relative or absolute)
            max_lines: Maximum number of lines to read

        Returns:
            File content (or None if file cannot be read)
        """
        try:
            path_obj = Path(file_path)
            if not path_obj.is_absolute():
                path_obj = self.project_root / file_path

            if not path_obj.exists() or not path_obj.is_file():
                return None

            # Read file
            with open(path_obj, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()

            # Track access
            self.track_file_access(file_path)

            if len(lines) <= max_lines:
                return ''.join(lines)

            # Return first max_lines lines with note
            return ''.join(lines[:max_lines]) + f'\n... (truncated, total {len(lines)} lines)'

        except (OSError, UnicodeDecodeError, ValueError) as e:
            return None

    def get_project_structure(self, max_depth: int = 3) -> str:
        """
        Generate a tree representation of project structure.

        Args:
            max_depth: Maximum depth to display

        Returns:
            String representation of project tree
        """
        self.scan()
        if not self.files_cache:
            return "No files found in project."

        # Build tree structure
        tree = {}
        for file_path in sorted(self.files_cache):
            parts = Path(file_path).parts
            if len(parts) > max_depth:
                # Truncate deep paths
                parts = parts[:max_depth] + ('...',)
            current = tree
            for part in parts[:-1]:
                current = current.setdefault(part, {})
            current[parts[-1]] = None  # File marker

        def format_tree(node, prefix="", is_last=True):
            lines = []
            keys = sorted(node.keys())
            for i, key in enumerate(keys):
                is_last_item = i == len(keys) - 1
                connector = "└── " if is_last_item else "├── "
                lines.append(f"{prefix}{connector}{key}")
                if node[key] is not None:  # Directory
                    extension = "    " if is_last_item else "│   "
                    lines.extend(format_tree(node[key], prefix + extension, is_last_item))
            return lines

        tree_lines = format_tree(tree)
        return "\n".join(tree_lines)

    def get_recent_files(self, count: int = 10) -> List[str]:
        """
        Get list of recently accessed files.

        Args:
            count: Number of recent files to return

        Returns:
            List of file paths (most recent first)
        """
        # Clean up old entries (older than 24 hours)
        cutoff = time.time() - 86400
        self.recently_accessed = [(path, ts) for path, ts in self.recently_accessed if ts > cutoff]
        # Return paths
        return [path for path, _ in sorted(self.recently_accessed, key=lambda x: x[1], reverse=True)[:count]]


# Optional: Integration with existing CodeAnalyzer
if __name__ == "__main__":
    # Simple test
    wm = WorkspaceManager()
    print(f"Project root: {wm.project_root}")
    files = wm.scan()
    print(f"Found {len(files)} files")
    if files:
        print(f"First 5 files: {files[:5]}")
        print("\nProject structure:")
        print(wm.get_project_structure())