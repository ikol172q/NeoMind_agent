"""
Safety mechanisms for file operations and system interactions.
Provides sandboxing, validation, and audit logging.
"""
import os
import sys
import shutil
import hashlib
import tempfile
import json
import time
from typing import Tuple, Optional, List, Dict, Any
from pathlib import Path
import stat

class SafetyManager:
    """Safety manager for file operations and system interactions."""

    # Dangerous file extensions (blocked for read/write)
    DANGEROUS_EXTENSIONS = {
        '.exe', '.dll', '.so', '.bin', '.sh', '.bat', '.cmd', '.ps1',
        '.pyc', '.pyo', '.pyd', '.jar', '.class', '.war', '.ear',
        '.app', '.dmg', '.iso', '.img', '.vhd', '.vmdk',
    }

    # System directories to protect (Unix and Windows)
    SYSTEM_DIRECTORIES = [
        '/', '/bin', '/sbin', '/usr', '/etc', '/var', '/lib',
        'C:\\', 'C:\\Windows', 'C:\\Program Files', 'C:\\Program Files (x86)',
        'C:\\System32', 'C:\\Windows\\System32',
    ]

    # Maximum file size for operations (10MB)
    MAX_FILE_SIZE = 10 * 1024 * 1024

    def __init__(self, workspace_root: str = None, audit_log: str = None, agent_root: str = None):
        """
        Initialize safety manager.

        Args:
            workspace_root: Root directory of allowed workspace.
            audit_log: Path to audit log file.
            agent_root: Optional additional allowed root for agent's own code.
        """
        self.workspace_root = os.path.abspath(workspace_root) if workspace_root else os.getcwd()
        self.agent_root = os.path.abspath(agent_root) if agent_root else None
        self.audit_log = audit_log or os.path.join(self.workspace_root, '.safety_audit.log')
        self._ensure_audit_log()

    def _ensure_audit_log(self):
        """Ensure audit log file exists."""
        log_dir = os.path.dirname(self.audit_log)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)
        if not os.path.exists(self.audit_log):
            with open(self.audit_log, 'w') as f:
                f.write("")

    def _log_audit(self, action: str, path: str, success: bool, details: str = ""):
        """Log an audit entry."""
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        entry = {
            'timestamp': timestamp,
            'action': action,
            'path': path,
            'success': success,
            'details': details,
            'user': os.getenv('USER', os.getenv('USERNAME', 'unknown')),
            'cwd': os.getcwd()
        }
        try:
            with open(self.audit_log, 'a') as f:
                f.write(json.dumps(entry) + '\n')
        except:
            pass  # Silently fail on audit logging errors

    def is_path_safe(self, path: str, operation: str = 'read') -> Tuple[bool, str]:
        """
        Check if a file path is safe for the given operation.

        Args:
            path: File or directory path
            operation: 'read', 'write', 'delete', 'execute'

        Returns:
            Tuple[bool, str]: (is_safe, reason)
        """
        try:
            abs_path = os.path.abspath(path)

            # Check if path is within allowed roots (workspace or agent root)
            allowed = False
            for root in [self.workspace_root, self.agent_root]:
                if root:
                    try:
                        rel_path = os.path.relpath(abs_path, root)
                        if not rel_path.startswith('..'):
                            allowed = True
                            break
                    except ValueError:
                        # Different drive on Windows - skip this root
                        continue
            if not allowed:
                return False, f"Path outside allowed roots: {abs_path}"

            # Check system directories
            for sys_dir in self.SYSTEM_DIRECTORIES:
                sys_abs = os.path.abspath(sys_dir)
                if abs_path.startswith(sys_abs + os.sep) or abs_path == sys_abs:
                    return False, f"Access to system directory blocked: {sys_dir}"

            # Check dangerous extensions (for files)
            if os.path.isfile(abs_path) or '.' in os.path.basename(abs_path):
                ext = os.path.splitext(abs_path)[1].lower()
                if ext in self.DANGEROUS_EXTENSIONS:
                    return False, f"Dangerous file extension blocked: {ext}"

            # Additional checks based on operation
            if operation == 'write':
                # Check if parent directory exists and is writable
                parent_dir = os.path.dirname(abs_path)
                if parent_dir and not os.path.exists(parent_dir):
                    # Allow creation of parent directories within workspace
                    parent_safe, reason = self.is_path_safe(parent_dir, 'write')
                    if not parent_safe:
                        return False, f"Parent directory unsafe: {reason}"
                elif parent_dir and not os.access(parent_dir, os.W_OK):
                    return False, f"No write permission to parent directory: {parent_dir}"

            elif operation == 'delete':
                # Extra caution for delete operations
                if os.path.isdir(abs_path) and not os.path.islink(abs_path):
                    # Count files in directory as a safety measure
                    try:
                        file_count = sum(1 for _ in Path(abs_path).rglob('*'))
                        if file_count > 100:
                            return False, f"Directory contains {file_count} files, delete blocked"
                    except:
                        pass

            elif operation == 'execute':
                # Check file permissions and type
                if os.path.isfile(abs_path):
                    # Check if file is executable (Unix)
                    if hasattr(os, 'access') and os.access(abs_path, os.X_OK):
                        # Could be a script or binary
                        pass
                    # Check extension
                    ext = os.path.splitext(abs_path)[1].lower()
                    if ext in {'.py', '.sh', '.bash', '.bat', '.cmd', '.ps1'}:
                        return False, f"Script execution blocked: {ext}"

            return True, "Path is safe"

        except Exception as e:
            return False, f"Path safety check error: {str(e)}"

    def validate_file_size(self, path: str, content: str = None) -> Tuple[bool, str]:
        """
        Validate file size constraints.

        Args:
            path: File path (for existing file)
            content: Content to write (for new file)

        Returns:
            Tuple[bool, str]: (is_valid, reason)
        """
        try:
            if content is not None:
                size = len(content.encode('utf-8'))
                if size > self.MAX_FILE_SIZE:
                    return False, f"Content size {size} exceeds limit {self.MAX_FILE_SIZE}"
                return True, "Content size valid"

            if os.path.exists(path):
                size = os.path.getsize(path)
                if size > self.MAX_FILE_SIZE:
                    return False, f"File size {size} exceeds limit {self.MAX_FILE_SIZE}"
                return True, "File size valid"

            return True, "File does not exist"

        except Exception as e:
            return False, f"Size validation error: {str(e)}"

    def create_backup(self, file_path: str) -> Optional[str]:
        """
        Create a backup of a file before modification.

        Returns:
            Backup file path or None if backup failed.
        """
        if not os.path.exists(file_path):
            return None

        try:
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            backup_dir = os.path.join(self.workspace_root, '.safety_backups')
            os.makedirs(backup_dir, exist_ok=True)

            base_name = os.path.basename(file_path)
            backup_name = f"{base_name}.backup_{timestamp}"
            backup_path = os.path.join(backup_dir, backup_name)

            shutil.copy2(file_path, backup_path)
            self._log_audit('backup', file_path, True, f"Backup created: {backup_path}")
            return backup_path

        except Exception as e:
            self._log_audit('backup', file_path, False, f"Backup failed: {str(e)}")
            return None

    def get_file_hash(self, file_path: str) -> str:
        """Calculate SHA256 hash of file."""
        try:
            with open(file_path, 'rb') as f:
                file_hash = hashlib.sha256(f.read()).hexdigest()
                return file_hash
        except Exception as e:
            self._log_audit('hash', file_path, False, f"Hash calculation failed: {str(e)}")
            raise

    def safe_read_file(self, file_path: str, max_lines: int = 1000) -> Tuple[bool, str, str]:
        """
        Safely read a file with safety checks.

        Returns:
            Tuple[success, message, content]
        """
        self._log_audit('read', file_path, True, "Attempting to read")

        # Path safety
        is_safe, reason = self.is_path_safe(file_path, 'read')
        if not is_safe:
            self._log_audit('read', file_path, False, f"Path unsafe: {reason}")
            return False, f"Path unsafe: {reason}", ""

        # Size validation
        if os.path.exists(file_path):
            is_valid, reason = self.validate_file_size(file_path)
            if not is_valid:
                self._log_audit('read', file_path, False, f"Size invalid: {reason}")
                return False, f"Size invalid: {reason}", ""

        # Read file
        try:
            if not os.path.exists(file_path):
                self._log_audit('read', file_path, False, "File not found")
                return False, "File not found", ""

            if not os.path.isfile(file_path):
                self._log_audit('read', file_path, False, "Not a file")
                return False, "Not a file", ""

            with open(file_path, 'r', encoding='utf-8') as f:
                lines = []
                for i, line in enumerate(f):
                    if i >= max_lines:
                        lines.append(f"... [file truncated at {max_lines} lines]")
                        break
                    lines.append(line.rstrip('\n'))

                content = '\n'.join(lines)

            self._log_audit('read', file_path, True, f"Read {len(lines)} lines")
            return True, "Success", content

        except UnicodeDecodeError:
            self._log_audit('read', file_path, False, "Binary file or encoding issue")
            return False, "Cannot read as text (binary file or encoding issue)", ""
        except Exception as e:
            self._log_audit('read', file_path, False, f"Read error: {str(e)}")
            return False, f"Read error: {str(e)}", ""

    def safe_write_file(self, file_path: str, content: str,
                       create_backup: bool = True) -> Tuple[bool, str, Optional[str]]:
        """
        Safely write content to a file with safety checks.

        Returns:
            Tuple[success, message, backup_path]
        """
        self._log_audit('write', file_path, True, f"Attempting to write {len(content)} chars")

        # Path safety
        is_safe, reason = self.is_path_safe(file_path, 'write')
        if not is_safe:
            self._log_audit('write', file_path, False, f"Path unsafe: {reason}")
            return False, f"Path unsafe: {reason}", None

        # Size validation
        is_valid, reason = self.validate_file_size(file_path, content)
        if not is_valid:
            self._log_audit('write', file_path, False, f"Size invalid: {reason}")
            return False, f"Size invalid: {reason}", None

        # Create backup if file exists
        backup_path = None
        if create_backup and os.path.exists(file_path):
            backup_path = self.create_backup(file_path)
            if backup_path is None:
                self._log_audit('write', file_path, False, "Backup creation failed")
                return False, "Backup creation failed", None

        # Write file
        try:
            # Ensure parent directory exists
            parent_dir = os.path.dirname(file_path)
            if parent_dir and not os.path.exists(parent_dir):
                os.makedirs(parent_dir, exist_ok=True)

            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)

            self._log_audit('write', file_path, True, f"Write successful, backup: {backup_path}")
            return True, f"File written successfully. Backup: {backup_path}", backup_path

        except Exception as e:
            self._log_audit('write', file_path, False, f"Write error: {str(e)}")
            return False, f"Write error: {str(e)}", backup_path

    def safe_delete_file(self, file_path: str) -> Tuple[bool, str, Optional[str]]:
        """
        Safely delete a file with safety checks.

        Returns:
            Tuple[success, message, backup_path]
        """
        self._log_audit('delete', file_path, True, "Attempting to delete")

        # Path safety
        is_safe, reason = self.is_path_safe(file_path, 'delete')
        if not is_safe:
            self._log_audit('delete', file_path, False, f"Path unsafe: {reason}")
            return False, f"Path unsafe: {reason}", None

        # Create backup
        backup_path = self.create_backup(file_path)
        if backup_path is None:
            self._log_audit('delete', file_path, False, "Backup creation failed")
            return False, "Backup creation failed", None

        # Delete file
        try:
            if os.path.isdir(file_path) and not os.path.islink(file_path):
                shutil.rmtree(file_path)
            else:
                os.remove(file_path)

            self._log_audit('delete', file_path, True, f"Delete successful, backup: {backup_path}")
            return True, f"File deleted successfully. Backup: {backup_path}", backup_path

        except Exception as e:
            self._log_audit('delete', file_path, False, f"Delete error: {str(e)}")
            return False, f"Delete error: {str(e)}", backup_path

    def cleanup_old_backups(self, max_age_days: int = 7) -> int:
        """
        Delete backup files older than max_age_days.

        Returns:
            Number of backups deleted.
        """
        backup_dir = os.path.join(self.workspace_root, '.safety_backups')
        if not os.path.exists(backup_dir):
            return 0

        cutoff = time.time() - (max_age_days * 24 * 60 * 60)
        deleted = 0

        for filename in os.listdir(backup_dir):
            filepath = os.path.join(backup_dir, filename)
            if os.path.getmtime(filepath) < cutoff:
                try:
                    os.remove(filepath)
                    deleted += 1
                except:
                    pass

        self._log_audit('cleanup', backup_dir, True, f"Deleted {deleted} old backups")
        return deleted


    def log_operation(self, action: str, target: str, success: bool, details: str = "") -> None:
        """Log any operation to audit log."""
        self._log_audit(action, target, success, details)

# Global safety manager instance (default workspace is current directory)
_default_safety = SafetyManager()

# Convenience functions
def safe_read_file(file_path: str, **kwargs) -> Tuple[bool, str, str]:
    return _default_safety.safe_read_file(file_path, **kwargs)

def safe_write_file(file_path: str, content: str, **kwargs) -> Tuple[bool, str, Optional[str]]:
    return _default_safety.safe_write_file(file_path, content, **kwargs)

def safe_delete_file(file_path: str) -> Tuple[bool, str, Optional[str]]:
    return _default_safety.safe_delete_file(file_path)

def is_path_safe(path: str, operation: str = 'read') -> Tuple[bool, str]:
    return _default_safety.is_path_safe(path, operation)

def log_operation(action: str, target: str, success: bool, details: str = "") -> None:
    """Log any operation to audit log."""
    _default_safety.log_operation(action, target, success, details)

def get_file_hash(file_path: str) -> str:
    """Calculate SHA256 hash of file."""
    return _default_safety.get_file_hash(file_path)

def create_backup(file_path: str) -> Optional[str]:
    """Create a backup of a file."""
    return _default_safety.create_backup(file_path)