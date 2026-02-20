# agent/code_analyzer.py
import os
import pathlib
import fnmatch
import hashlib
import stat
import shutil
import datetime
import time
from typing import Set, Tuple, List, Dict, Any
import warnings
import re
import html


class CodeAnalyzer:
    """Analyze and understand codebases, suggest fixes with permission"""

    def __init__(self, root_path: str = None, safety_manager=None):
        self.root_path = root_path or os.getcwd()
        self.safety_manager = safety_manager
        self.file_cache = {}  # Cache for file contents: {path: content}
        self.file_metadata = {}  # {path: {'size': size, 'ext': ext, 'lines': lines}}
        self.ignore_patterns = [
            '__pycache__', '.git', '.env', 'venv', 'env', 'node_modules',
            '.idea', '.vscode', 'dist', 'build', '*.pyc', '*.pyo',
            '.DS_Store', '*.so', '*.dll', '*.exe', '*.bin'
        ]
        self.max_files_before_warning = 500
        self.read_files_count = 0
        self.permission_errors = []
        
    def should_ignore(self, path: str) -> bool:
        """Check if file/directory should be ignored"""
        name = os.path.basename(path)

        # Check patterns
        for pattern in self.ignore_patterns:
            if fnmatch.fnmatch(name, pattern) or pattern in path:
                return True

        # Check if binary file by extension
        binary_exts = {'.pyc', '.pyo', '.so', '.dll', '.exe', '.bin', 
                      '.jpg', '.png', '.gif', '.pdf', '.zip', '.tar'}
        ext = os.path.splitext(name)[1].lower()
        if ext in binary_exts:
            return True

        return False

    def count_files(self, path: str = None) -> Tuple[int, int]:
        """Count total files and directories in a path"""
        total_files = 0
        total_dirs = 0
        path = path or self.root_path

        try:
            for root, dirs, files in os.walk(path):
                # Filter ignored directories
                dirs[:] = [d for d in dirs if not self.should_ignore(os.path.join(root, d))]

                total_dirs += len(dirs)

                # Filter and count files
                for file in files:
                    file_path = os.path.join(root, file)
                    if not self.should_ignore(file_path):
                        total_files += 1
        except PermissionError:
            pass

        return total_files, total_dirs

    def find_code_files(self, pattern: str = None, limit: int = 100) -> List[str]:
        """Find code files matching pattern or all code files"""
        code_files = []

        try:
            for root, dirs, files in os.walk(self.root_path):
                # Filter ignored directories
                dirs[:] = [d for d in dirs if not self.should_ignore(os.path.join(root, d))]

                for file in files:
                    file_path = os.path.join(root, file)

                    if self.should_ignore(file_path):
                        continue

                    # Check if it's a text/code file
                    ext = os.path.splitext(file)[1].lower()
                    code_exts = {'.py', '.js', '.ts', '.java', '.cpp', '.c', '.h', 
                                '.hpp', '.cs', '.go', '.rs', '.rb', '.php', '.swift',
                                '.kt', '.scala', '.m', '.mm', '.sh', '.bash', '.zsh',
                                '.json', '.yaml', '.yml', '.toml', '.ini', '.cfg',
                                '.txt', '.md', '.rst', '.html', '.css', '.scss',
                                '.sql', '.graphql', '.proto', '.thrift', '.xml'}

                    if ext in code_exts or (pattern and fnmatch.fnmatch(file, pattern)):
                        code_files.append(file_path)

                        if limit and len(code_files) >= limit:
                            return code_files
        except PermissionError as e:
            self.permission_errors.append(str(e))

        return code_files

    def smart_find_files(self, search_term: str, max_results: int = 20, search_limit: int = 500) -> List[Dict[str, Any]]:
        """Intelligently find files based on search term"""
        results = []
        search_term_lower = search_term.lower()

        # Try different strategies
        strategies = [
            # Strategy 1: Exact filename match
            lambda f: os.path.basename(f).lower() == search_term_lower,
            # Strategy 2: Filename contains search term
            lambda f: search_term_lower in os.path.basename(f).lower(),
            # Strategy 3: Path contains search term
            lambda f: search_term_lower in f.lower(),
        ]
        
        all_files = self.find_code_files(limit=search_limit)  # Quick scan

        for strategy in strategies:
            if len(results) >= max_results:
                break

            for file_path in all_files:
                if strategy(file_path) and file_path not in [r['path'] for r in results]:
                    try:
                        size = os.path.getsize(file_path)
                        results.append({
                            'path': file_path,
                            'name': os.path.basename(file_path),
                            'size': size,
                            'relative': os.path.relpath(file_path, self.root_path),
                            'score': 100 - len(results)  # Higher score for earlier matches
                        })
                    except:
                        pass

                if len(results) >= max_results:
                    break

        return sorted(results, key=lambda x: x['score'], reverse=True)

    def read_file_safe(self, file_path: str) -> Tuple[bool, str, str]:
        """Safely read a file with permission handling"""
        # Use safety manager if available
        if self.safety_manager:
            success, message, content = self.safety_manager.safe_read_file(file_path, max_lines=1000000)
            if success:
                # Cache the content
                self.file_cache[file_path] = content
                # Store metadata
                lines = content.count('\n') + 1
                ext = os.path.splitext(file_path)[1]
                self.file_metadata[file_path] = {
                    'size': len(content.encode('utf-8')),
                    'lines': lines,
                    'ext': ext,
                    'last_read': os.path.getmtime(file_path) if os.path.exists(file_path) else time.time()
                }
            return success, message, content

        # Fallback to original implementation
        try:
            # Check if file exists
            if not os.path.exists(file_path):
                return False, "File not found", ""

            # Check if it's a file (not directory)
            if not os.path.isfile(file_path):
                return False, "Not a file", ""

            # Check permissions
            if not os.access(file_path, os.R_OK):
                return False, "No read permission", ""

            # Check file size (skip very large files)
            size = os.path.getsize(file_path)
            if size > 10 * 1024 * 1024:  # 10MB
                return False, f"File too large ({size/1024/1024:.1f}MB)", ""

            # Try to read as text
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
            except UnicodeDecodeError:
                # Try different encodings
                for encoding in ['latin-1', 'cp1252', 'iso-8859-1']:
                    try:
                        with open(file_path, 'r', encoding=encoding) as f:
                            content = f.read()
                        break
                    except:
                        continue
                else:
                    return False, "Cannot decode as text (binary file?)", ""

            # Cache the content
            self.file_cache[file_path] = content

            # Store metadata
            lines = content.count('\n') + 1
            ext = os.path.splitext(file_path)[1]
            self.file_metadata[file_path] = {
                'size': size,
                'lines': lines,
                'ext': ext,
                'last_read': os.path.getmtime(file_path)
            }

            return True, "Success", content

        except PermissionError:
            return False, "Permission denied", ""
        except Exception as e:
            return False, f"Error: {str(e)}", ""
    
    def analyze_file(self, file_path: str) -> Dict[str, Any]:
        """Analyze a single file"""
        success, message, content = self.read_file_safe(file_path)

        if not success:
            return {'success': False, 'error': message}

        # Basic analysis
        lines = content.split('\n')

        # Count imports, functions, classes, etc. (Python-specific for now)
        imports = []
        functions = []
        classes = []

        for i, line in enumerate(lines):
            line_stripped = line.strip()

            # Python-specific analysis
            if line_stripped.startswith('import ') or line_stripped.startswith('from '):
                imports.append({'line': i + 1, 'content': line_stripped})
            elif line_stripped.startswith('def '):
                functions.append({'line': i + 1, 'name': line_stripped[4:].split('(')[0]})
            elif line_stripped.startswith('class '):
                classes.append({'line': i + 1, 'name': line_stripped[6:].split(':')[0]})

        return {
            'success': True,
            'path': file_path,
            'size': len(content),
            'lines': len(lines),
            'imports': imports,
            'functions': functions,
            'classes': classes,
            'content_preview': '\n'.join(lines[:50]) if len(lines) > 50 else content,
            'has_more_lines': len(lines) > 50
        }

    def get_code_summary(self) -> Dict[str, Any]:
        """Get summary of the codebase"""
        all_files = self.find_code_files(limit=1000)

        if len(all_files) > self.max_files_before_warning:
            return {
                'total_files': len(all_files),
                'warning': f"Large codebase detected: {len(all_files)} files",
                'suggestion': "Use specific search to find files"
            }
        
        # Analyze file types
        file_types = {}
        total_lines = 0
        total_size = 0

        for file_path in all_files[:100]:  # Sample first 100 files
            ext = os.path.splitext(file_path)[1].lower()
            file_types[ext] = file_types.get(ext, 0) + 1

            try:
                size = os.path.getsize(file_path)
                total_size += size

                # Count lines for text files
                if ext in {'.py', '.js', '.java', '.cpp', '.c', '.h', '.txt', '.md'}:
                    success, msg, content = self.read_file_safe(file_path)
                    if success:
                        total_lines += content.count('\n') + 1
            except:
                pass

        return {
            'total_files': len(all_files),
            'file_types': dict(sorted(file_types.items(), key=lambda x: x[1], reverse=True)),
            'total_lines': total_lines,
            'total_size': f"{total_size/1024/1024:.2f} MB",
            'root_path': self.root_path
        }

    def write_file_safe(self, file_path: str, content: str, backup: bool = True) -> Tuple[bool, str]:
        """
        Safely write content to a file with validation and optional backup.

        Args:
            file_path: Path to the file
            content: Content to write
            backup: Whether to create a backup before writing

        Returns:
            Tuple[bool, str]: (success, message)
        """
        # Use safety manager if available
        if self.safety_manager:
            success, message, backup_path = self.safety_manager.safe_write_file(
                file_path, content, create_backup=backup
            )
            if success:
                # Update cache
                self.file_cache[file_path] = content
                lines = content.count('\n') + 1
                self.file_metadata[file_path] = {
                    'size': len(content.encode('utf-8')),
                    'lines': lines,
                    'ext': os.path.splitext(file_path)[1],
                    'last_read': os.path.getmtime(file_path) if os.path.exists(file_path) else time.time()
                }
            return success, message

        # Fallback to original implementation
        try:
            # Normalize path
            file_path = os.path.abspath(file_path)

            # Check if file already exists
            file_exists = os.path.exists(file_path)

            # Safety: prevent writing to system directories or outside workspace
            # Ensure file is within the codebase root (or subdirectory)
            if self.root_path:
                try:
                    relative = os.path.relpath(file_path, self.root_path)
                    if relative.startswith('..'):
                        return False, f"File path is outside codebase root: {file_path}"
                except ValueError:
                    # Could not compute relative path (different drives on Windows)
                    pass

            # Check write permission
            if file_exists:
                if not os.access(file_path, os.W_OK):
                    return False, "No write permission"
            else:
                # Check if parent directory is writable
                parent_dir = os.path.dirname(file_path)
                if parent_dir and not os.path.exists(parent_dir):
                    # Create parent directories
                    try:
                        os.makedirs(parent_dir, exist_ok=True)
                    except Exception as e:
                        return False, f"Cannot create parent directories: {e}"
                if parent_dir and not os.access(parent_dir, os.W_OK):
                    return False, f"No write permission to parent directory: {parent_dir}"

            # Limit content size (10MB)
            if len(content.encode('utf-8')) > 10 * 1024 * 1024:
                return False, "Content exceeds 10MB limit"

            # Create backup if requested and file exists
            backup_path = None
            if backup and file_exists:
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_path = file_path + f".backup_{timestamp}"
                try:
                    shutil.copy2(file_path, backup_path)
                except Exception as e:
                    return False, f"Failed to create backup: {e}"

            # Write content
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)

            # Update cache
            self.file_cache[file_path] = content
            lines = content.count('\n') + 1
            self.file_metadata[file_path] = {
                'size': len(content.encode('utf-8')),
                'lines': lines,
                'ext': os.path.splitext(file_path)[1],
                'last_read': os.path.getmtime(file_path) if file_exists else time.time()
            }

            message = f"File written successfully: {file_path}"
            if backup_path:
                message += f" (backup: {backup_path})"
            return True, message

        except Exception as e:
            return False, f"Error writing file: {str(e)}"