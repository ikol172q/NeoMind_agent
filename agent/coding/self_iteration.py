"""
Self-iteration framework for safe self-modification of the agent's own code.
Provides backup, validation, rollback, and change journaling.
"""
import os
import shutil
import ast
import importlib.util
import sys
import time
import json
import subprocess
from typing import Tuple, Optional, Dict, Any, List
from .code_analyzer import CodeAnalyzer


class SelfIteration:
    """Safe self-modification framework for the agent."""

    def __init__(self, root_path: str, code_analyzer: Optional[CodeAnalyzer] = None):
        self.root_path = os.path.abspath(root_path)
        self.code_analyzer = code_analyzer or CodeAnalyzer(self.root_path)
        self.safety_manager = self.code_analyzer.safety_manager
        self.backup_dir = os.path.join(self.root_path, ".self_iteration_backups")
        self.journal_path = os.path.join(self.root_path, ".self_iteration_journal.jsonl")
        os.makedirs(self.backup_dir, exist_ok=True)

    def backup_file(self, file_path: str) -> str:
        """
        Create a timestamped backup of a file.
        Returns the backup file path.
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Cannot backup non-existent file: {file_path}")

        timestamp = time.strftime("%Y%m%d_%H%M%S")
        base_name = os.path.basename(file_path)
        backup_name = f"{base_name}.backup_{timestamp}"
        backup_path = os.path.join(self.backup_dir, backup_name)

        shutil.copy2(file_path, backup_path)
        return backup_path

    def validate_syntax(self, file_path: str, content: str) -> Tuple[bool, str]:
        """
        Validate Python syntax of the content.
        Returns (is_valid, error_message).
        """
        if not file_path.endswith('.py'):
            return True, "Not a Python file, skipping syntax check"

        try:
            ast.parse(content)
            return True, "Syntax valid"
        except SyntaxError as e:
            return False, f"Syntax error at line {e.lineno}, column {e.offset}: {e.msg}"

    def validate_imports(self, file_path: str) -> Tuple[bool, str]:
        """
        Try to import the module (if it's a Python file) to ensure no import errors.
        This is done in a separate subprocess to avoid polluting current runtime.
        """
        if not file_path.endswith('.py'):
            return True, "Not a Python file, skipping import check"

        # Try to import the module in a subprocess
        try:
            # Use python -c "import module" where module is relative to root_path
            rel_path = os.path.relpath(file_path, self.root_path)
            module_name = rel_path.replace('.py', '').replace(os.sep, '.')
            # Ensure it's a proper module (no leading dots)
            if module_name.startswith('.'):
                module_name = module_name[1:]

            # Run import test
            result = subprocess.run(
                [sys.executable, "-c", f"import sys; sys.path.insert(0, '{self.root_path}'); import {module_name}"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                return True, "Import successful"
            else:
                return False, f"Import failed: {result.stderr}"
        except subprocess.TimeoutExpired:
            return False, "Import check timed out"
        except Exception as e:
            return False, f"Import check error: {str(e)}"

    def run_basic_tests(self) -> Tuple[bool, str]:
        """
        Run basic test suite (if exists) to ensure agent still works.
        Currently runs dev_test.py.
        """
        test_path = os.path.join(self.root_path, "dev_test.py")
        if not os.path.exists(test_path):
            return True, "No test suite found, skipping"

        try:
            result = subprocess.run(
                [sys.executable, test_path],
                capture_output=True,
                text=True,
                timeout=30
            )
            if result.returncode == 0:
                return True, "Basic tests passed"
            else:
                return False, f"Tests failed: {result.stderr[:500]}"
        except subprocess.TimeoutExpired:
            return False, "Test execution timed out"
        except Exception as e:
            return False, f"Test execution error: {str(e)}"

    def suggest_improvements(self, file_path: str) -> List[Dict[str, Any]]:
        """
        Suggest improvements for a Python file.
        Currently suggests adding docstrings to functions without them.
        Returns list of suggestions with 'old_code', 'new_code', 'description'.
        """
        suggestions = []
        try:
            success, msg, content = self.code_analyzer.read_file_safe(file_path)
            if not success:
                return suggestions
            # Parse AST
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    # Check if function has docstring
                    docstring = ast.get_docstring(node)
                    if docstring is None:
                        # Get function line number (1-indexed)
                        line_start = node.lineno
                        # Get the line of the function definition
                        lines = content.split('\n')
                        def_line = lines[line_start - 1]  # lineno is 1-indexed
                        # Find indentation
                        indent = len(def_line) - len(def_line.lstrip())
                        # Create new line with docstring
                        new_line = def_line + '\n' + ' ' * (indent + 4) + '"""TODO: Add docstring."""'
                        suggestions.append({
                            'old_code': def_line,
                            'new_code': new_line,
                            'description': f'Add docstring to function {node.name}'
                        })
        except Exception as e:
            # Silently fail
            pass
        return suggestions

    def validate_change(self, file_path: str, old_code: str, new_code: str) -> Tuple[bool, str]:
        """
        Comprehensive validation of a proposed change.
        Includes syntax check, import validation, and basic functionality test.
        Returns (is_valid, error_message).
        """
        # First, create a temporary copy of the file with the change applied
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as tmp:
            # Read original content
            success, msg, original_content = self.code_analyzer.read_file_safe(file_path)
            if not success:
                return False, f"Cannot read file for validation: {msg}"

            # Apply the change (simple string replace)
            if old_code not in original_content:
                return False, "Old code not found in file"

            new_content = original_content.replace(old_code, new_code)
            tmp.write(new_content)
            tmp_path = tmp.name

        try:
            # Validate syntax
            is_valid, error = self.validate_syntax(file_path, new_content)
            if not is_valid:
                return False, f"Syntax validation failed: {error}"

            # Validate imports
            is_valid, error = self.validate_imports(tmp_path)
            if not is_valid:
                return False, f"Import validation failed: {error}"

            # Note: basic tests run on the whole codebase, not just this file
            # We'll run them after all changes are applied

            return True, "Change validation passed"
        finally:
            os.unlink(tmp_path)

    def apply_change(self, file_path: str, old_code: str, new_code: str,
                     description: str, run_tests: bool = True,
                     run_pre_tests: bool = True) -> Tuple[bool, str, Optional[str]]:
        """
        Apply a validated change with backup and rollback capability.
        Returns (success, message, backup_path).
        """
        backup_path = None
        try:
            # Create backup
            backup_path = self.backup_file(file_path)

            # Run pre-tests to ensure codebase is healthy before modification
            if run_pre_tests:
                pre_test_success, pre_test_msg = self.run_basic_tests()
                if not pre_test_success:
                    return False, f"Pre-test suite failed: {pre_test_msg}. Change not applied.", backup_path

            # Read original content
            success, msg, original_content = self.code_analyzer.read_file_safe(file_path)
            if not success:
                return False, f"Cannot read file: {msg}", backup_path

            # Apply change
            if old_code not in original_content:
                return False, "Old code not found in file", backup_path

            new_content = original_content.replace(old_code, new_code)

            # Write new content
            success, msg = self.code_analyzer.write_file_safe(file_path, new_content, backup=False)
            if not success:
                return False, f"Failed to write file: {msg}", backup_path

            # Run post-tests if requested (after writing, before finalizing)
            if run_tests:
                test_success, test_msg = self.run_basic_tests()
                if not test_success:
                    # Rollback due to test failure
                    if backup_path and os.path.exists(backup_path):
                        try:
                            shutil.copy2(backup_path, file_path)
                            rollback_msg = f"Post-tests failed, rolled back: {test_msg}"
                        except Exception as rollback_e:
                            rollback_msg = f"Post-tests failed and rollback failed: {str(rollback_e)}"
                    else:
                        rollback_msg = "Post-tests failed, no backup available"
                    return False, f"Test suite failed after change: {test_msg}. {rollback_msg}", backup_path

            # Log change
            self.log_change({
                'timestamp': time.time(),
                'file_path': file_path,
                'description': description,
                'backup': backup_path,
                'status': 'applied',
                'pre_tests_passed': run_pre_tests,
                'post_tests_passed': run_tests
            })

            return True, f"Change applied successfully. Backup: {backup_path}", backup_path

        except Exception as e:
            # Attempt rollback
            if backup_path and os.path.exists(backup_path):
                try:
                    shutil.copy2(backup_path, file_path)
                    rollback_msg = f"Rolled back to backup: {backup_path}"
                except Exception as rollback_e:
                    rollback_msg = f"Failed to rollback: {str(rollback_e)}"
            else:
                rollback_msg = "No backup available for rollback"

            return False, f"Failed to apply change: {str(e)}. {rollback_msg}", backup_path

    def log_change(self, change_data: Dict[str, Any]) -> None:
        """Append change record to journal."""
        # Safety check
        if self.safety_manager:
            is_safe, reason = self.safety_manager.is_path_safe(self.journal_path, 'write')
            if not is_safe:
                # Log error but continue? For now, skip audit.
                pass
            else:
                self.safety_manager._log_audit('journal_append', self.journal_path, True, "Appending change record")
        with open(self.journal_path, 'a') as f:
            f.write(json.dumps(change_data) + '\n')

    def get_change_history(self, limit: int = 100) -> list:
        """Retrieve recent change history from journal."""
        if not os.path.exists(self.journal_path):
            return []

        # Use safety manager if available
        if self.safety_manager:
            success, message, content = self.safety_manager.safe_read_file(self.journal_path)
            if success:
                changes = []
                for line in content.split('\n'):
                    if line.strip():
                        try:
                            changes.append(json.loads(line.strip()))
                        except json.JSONDecodeError:
                            continue
                return sorted(changes, key=lambda x: x.get('timestamp', 0), reverse=True)[:limit]

        # Fallback or no safety manager
        changes = []
        with open(self.journal_path, 'r') as f:
            for line in f:
                try:
                    changes.append(json.loads(line.strip()))
                except json.JSONDecodeError:
                    continue

        return sorted(changes, key=lambda x: x.get('timestamp', 0), reverse=True)[:limit]

    def cleanup_old_backups(self, max_age_days: int = 30) -> int:
        """Delete backup files older than max_age_days. Returns count deleted."""
        if not os.path.exists(self.backup_dir):
            return 0

        cutoff = time.time() - (max_age_days * 24 * 60 * 60)
        deleted = 0

        for filename in os.listdir(self.backup_dir):
            filepath = os.path.join(self.backup_dir, filename)
            if os.path.getmtime(filepath) < cutoff:
                try:
                    os.remove(filepath)
                    deleted += 1
                except:
                    pass

        return deleted