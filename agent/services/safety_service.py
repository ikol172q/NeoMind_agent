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
import re
import unicodedata
import platform
from typing import Tuple, Optional, List, Dict, Any
from pathlib import Path
import stat

class SafetyManager:
    """Safety manager for file operations and system interactions."""

    # Dangerous file extensions (blocked for read/write)
    DANGEROUS_EXTENSIONS = {
        # FZ02: removed '.bin' — too generic (commonly used for data/firmware
        # dumps); content-based binary detection handles these safely.
        '.exe', '.dll', '.so', '.sh', '.bat', '.cmd', '.ps1',
        '.pyc', '.pyo', '.pyd', '.jar', '.class', '.war', '.ear',
        '.app', '.dmg', '.iso', '.img', '.vhd', '.vmdk',
    }

    # System directories to protect (Unix and Windows)
    SYSTEM_DIRECTORIES = [
        '/', '/bin', '/sbin', '/usr', '/etc', '/var/run', '/var/log',
        '/var/spool', '/var/mail', '/var/cache', '/lib',
        'C:\\', 'C:\\Windows', 'C:\\Program Files', 'C:\\Program Files (x86)',
        'C:\\System32', 'C:\\Windows\\System32',
    ]

    # Protected config/credential files (blocked for write/delete)
    PROTECTED_FILES = {
        # Shell configs
        '.gitconfig', '.bashrc', '.zshrc', '.profile', '.bash_profile',
        # SSH & GPG
        '.ssh/id_rsa', '.ssh/id_ed25519', '.ssh/authorized_keys', '.ssh/config',
        '.gnupg/secring.gpg', '.gnupg/trustdb.gpg',
        # Environment files
        '.env', '.env.local', '.env.production', '.env.staging',
        '.env.development', '.env.test',
        # Agent configs
        '.mcp.json', '.claude.json', '.claude/settings.json',
        '.neomind/config.json', '.neomind/secrets.json',
        # Credentials
        'credentials.json', 'service-account.json',
        '.netrc', '.npmrc', '.pypirc',
        # Cloud provider credentials
        '.aws/credentials', '.aws/config',
        '.config/gcloud/credentials.db', '.config/gcloud/application_default_credentials.json',
        '.kube/config',
        '.docker/config.json',
        '.helm/repositories.yaml',
        # Browser data
        '.config/google-chrome/Default/Login Data',
        '.config/google-chrome/Default/Cookies',
    }

    # Safe temp directories (allowed for read even outside workspace)
    SAFE_TEMP_DIRS = ['/var/folders', '/var/tmp', '/tmp']

    # Device paths (Unix) - never access
    DEVICE_PATHS = {'/dev', '/proc', '/sys'}

    # Maximum file size for operations (10MB)
    MAX_FILE_SIZE = 10 * 1024 * 1024

    # API & file processing limits
    IMAGE_MAX_SIZE = 5 * 1024 * 1024       # 5MB
    PDF_MAX_PAGES = 100
    PDF_MAX_SIZE = 20 * 1024 * 1024        # 20MB
    MAX_MEDIA_PER_REQUEST = 100
    DEFAULT_MAX_TOKENS = 32000
    COMPACT_THRESHOLD = 0.90
    MAX_LINES_PER_READ = 5000
    MAX_TOOL_OUTPUT_CHARS = 30000

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

    # ── Path Traversal Prevention ─────────────────────────────────────

    def _check_device_paths(self, path: str) -> Tuple[bool, str]:
        """Block access to device/proc/sys paths.

        On macOS/Windows (case-insensitive FS), also checks lowercase.
        Prevents bypass via /ETC/PASSWD, /Dev/Zero, etc.
        """
        normalized = os.path.normpath(path)
        # Case-insensitive check on macOS/Windows
        check_lower = platform.system() in ('Darwin', 'Windows')
        norm_lower = normalized.lower() if check_lower else normalized
        for dev in self.DEVICE_PATHS:
            dev_lower = dev.lower() if check_lower else dev
            if norm_lower == dev_lower or norm_lower.startswith(dev_lower + os.sep):
                return False, f"Access to device path blocked: {normalized}"

        # Also block /etc, /var/run, and other sensitive system dirs on case-insensitive FS
        if check_lower:
            sensitive_dirs = ['/etc', '/var/run', '/private/etc']
            for sd in sensitive_dirs:
                if norm_lower == sd or norm_lower.startswith(sd + '/'):
                    return False, f"Access to system directory blocked: {normalized}"

        return True, ""

    def _check_unc_paths(self, path: str) -> Tuple[bool, str]:
        """Block UNC paths to prevent NTLM credential theft (Windows)."""
        if path.startswith('\\\\') or path.startswith('//'):
            return False, f"UNC path blocked (NTLM protection): {path}"
        return True, ""

    def _check_symlink(self, path: str) -> Tuple[bool, str]:
        """Resolve symlinks and ensure target is within workspace."""
        try:
            if os.path.islink(path):
                real = os.path.realpath(path)
                allowed = False
                for root in [self.workspace_root, self.agent_root]:
                    if root:
                        try:
                            rel = os.path.relpath(real, root)
                            if not rel.startswith('..'):
                                allowed = True
                                break
                        except ValueError:
                            continue
                if not allowed:
                    return False, f"Symlink target outside workspace: {path} -> {real}"
        except Exception:
            pass
        return True, ""

    def _check_url_encoded_traversal(self, path: str) -> Tuple[bool, str]:
        """Detect URL-encoded path traversal sequences."""
        suspicious = ['%2e%2e', '%2e%2e%2f', '%2e%2e/', '..%2f', '%2e%2e%5c',
                       '..%5c', '%252e%252e', '%c0%ae', '%c1%9c']
        path_lower = path.lower()
        for pattern in suspicious:
            if pattern in path_lower:
                return False, f"URL-encoded path traversal detected: {pattern}"
        return True, ""

    def _check_unicode_normalization(self, path: str) -> Tuple[bool, str]:
        """Detect Unicode normalization attacks (e.g. fullwidth dots)."""
        nfkc = unicodedata.normalize('NFKC', path)
        if nfkc != path:
            # Check if normalization changes path semantics
            if '..' in nfkc and '..' not in path:
                return False, f"Unicode normalization attack detected in path"
        # Block fullwidth characters in path components
        for ch in path:
            if unicodedata.category(ch).startswith('Cf'):  # format chars
                return False, f"Invisible Unicode character in path"
            # Fullwidth period (U+FF0E) etc.
            if ch in ('\uff0e', '\uff0f', '\uff3c'):
                return False, f"Fullwidth Unicode character in path: U+{ord(ch):04X}"
        return True, ""

    def _check_backslash_injection(self, path: str) -> Tuple[bool, str]:
        """Block backslash injection on non-Windows."""
        if platform.system() != 'Windows':
            if '\\' in path:
                return False, f"Backslash in path on non-Windows system: {path}"
        return True, ""

    def _check_case_insensitive_traversal(self, path: str) -> Tuple[bool, str]:
        """Detect case manipulation attacks on case-insensitive filesystems."""
        if platform.system() == 'Darwin' or platform.system() == 'Windows':
            normalized = os.path.normpath(path)
            if normalized.lower() != normalized and '..' in normalized.lower():
                return False, f"Case-insensitive path manipulation detected"
        return True, ""

    def _check_glob_pattern(self, pattern: str) -> Tuple[bool, str]:
        """Validate glob patterns for safety."""
        dangerous = ['/**/../', '/../', '/..\\', '\\..\\']
        for d in dangerous:
            if d in pattern:
                return False, f"Dangerous glob pattern detected: {d}"
        # Block globbing into parent directories
        if pattern.startswith('..') or '/..' in pattern:
            return False, f"Glob pattern escapes workspace: {pattern}"
        return True, ""

    def _check_tilde_variants(self, path: str) -> Tuple[bool, str]:
        """Block tilde variants that resolve to other users' directories."""
        if re.match(r'~[a-zA-Z0-9_]', path):
            return False, f"Tilde-user path blocked (resolves to another user's home): {path}"
        if re.match(r'~[+\-0-9]', path):
            return False, f"Tilde variant blocked (directory stack reference): {path}"
        return True, ""

    # Credential/secret files that should be blocked for ALL operations (including read)
    READ_BLOCKED_FILES = {
        '.ssh/id_rsa', '.ssh/id_ed25519', '.ssh/authorized_keys',
        '.gnupg/secring.gpg', '.gnupg/trustdb.gpg',
        '.env', '.env.local', '.env.production', '.env.staging',
        '.env.development', '.env.test',
        '.neomind/secrets.json',
        'credentials.json', 'service-account.json',
        '.netrc', '.npmrc', '.pypirc',
        '.aws/credentials',
        '.config/gcloud/credentials.db',
        '.config/gcloud/application_default_credentials.json',
        '.docker/config.json',
        '.config/google-chrome/Default/Login Data',
        '.config/google-chrome/Default/Cookies',
    }

    def _check_protected_file(self, path: str, operation: str) -> Tuple[bool, str]:
        """Check if path targets a protected config/credential file.

        - Credential/secret files are blocked for ALL operations (read/write/delete).
        - Other protected config files are blocked for write/delete only.
        """
        abs_path = os.path.abspath(os.path.expanduser(path))
        home = os.path.expanduser('~')

        for pf in self.PROTECTED_FILES:
            protected_abs = os.path.normpath(os.path.join(home, pf))
            if os.path.normpath(abs_path) == protected_abs:
                # Credential files: block ALL operations (including read)
                if pf in self.READ_BLOCKED_FILES:
                    return False, f"Protected credential file blocked for {operation}: {pf}"
                # Non-credential config files: block write/delete only
                if operation in ('write', 'delete'):
                    return False, f"Protected file blocked for {operation}: {pf}"

        # For .env files outside the home-directory PROTECTED_FILES set:
        # block write/delete but allow read (workspace .env files are readable)
        basename = os.path.basename(abs_path)
        if basename.startswith('.env') and operation in ('write', 'delete'):
            return False, f"Environment file blocked for {operation}: {basename}"
        return True, ""

    # Magic bytes for common binary formats
    MAGIC_SIGNATURES = {
        b'\x89PNG': 'PNG image',
        b'\xff\xd8\xff': 'JPEG image',
        b'GIF87a': 'GIF image',
        b'GIF89a': 'GIF image',
        b'%PDF': 'PDF document',
        b'PK\x03\x04': 'ZIP/DOCX/XLSX archive',
        b'PK\x05\x06': 'ZIP archive (empty)',
        b'\x7fELF': 'ELF executable',
        b'\xfe\xed\xfa': 'Mach-O executable',
        b'\xcf\xfa\xed\xfe': 'Mach-O executable (64-bit)',
        b'\xca\xfe\xba\xbe': 'Mach-O universal binary',
        b'MZ': 'Windows PE executable',
        b'\x1f\x8b': 'GZIP compressed',
        b'BZh': 'BZIP2 compressed',
        b'\xfd7zXZ': 'XZ compressed',
        b'Rar!\x1a\x07': 'RAR archive',
        b'\x00\x00\x01\x00': 'ICO image',
        b'RIFF': 'RIFF container (WAV/AVI)',
        b'\x1a\x45\xdf\xa3': 'WebM/MKV video',
        b'\x00\x00\x00\x1c\x66\x74\x79\x70': 'MP4 video',
        b'\x00\x00\x00\x20\x66\x74\x79\x70': 'MP4 video',
        b'OggS': 'OGG audio/video',
        b'fLaC': 'FLAC audio',
        b'ID3': 'MP3 audio (ID3 tag)',
        b'\xff\xfb': 'MP3 audio',
        b'\xff\xf3': 'MP3 audio',
        b'SQLite format 3': 'SQLite database',
        b'\xd0\xcf\x11\xe0': 'MS Office (OLE2)',
    }

    def _check_magic_bytes(self, chunk: bytes) -> Optional[str]:
        """Check file header against known binary format signatures."""
        for magic, desc in self.MAGIC_SIGNATURES.items():
            if chunk[:len(magic)] == magic:
                return desc
        return None

    def check_binary_content(self, file_path: str) -> Tuple[bool, str]:
        """Detect binary files via magic bytes, null bytes, and non-printable ratio."""
        try:
            with open(file_path, 'rb') as f:
                chunk = f.read(8192)
            if not chunk:
                return True, "Empty file"

            # Magic byte / content sniffing
            detected = self._check_magic_bytes(chunk)
            if detected:
                return False, f"Binary file detected: {detected}"

            # Null byte detection
            if b'\x00' in chunk:
                return False, "Binary file detected (null bytes)"

            # Non-printable ratio check (>10% = binary)
            non_printable = sum(
                1 for b in chunk
                if b < 32 and b not in (9, 10, 13)  # tab, LF, CR are OK
            )
            ratio = non_printable / len(chunk)
            if ratio > 0.10:
                return False, f"Binary file detected ({ratio:.0%} non-printable)"

            return True, "Text file"
        except Exception as e:
            return False, f"Binary detection error: {e}"

    def validate_path_traversal(self, path: str, operation: str = 'read') -> Tuple[bool, str]:
        """Run all path traversal prevention checks.

        Returns:
            Tuple[bool, str]: (is_safe, reason)
        """
        checks = [
            self._check_device_paths(path),
            self._check_unc_paths(path),
            self._check_tilde_variants(path),
            self._check_url_encoded_traversal(path),
            self._check_unicode_normalization(path),
            self._check_backslash_injection(path),
            self._check_case_insensitive_traversal(path),
            self._check_protected_file(path, operation),
        ]
        for ok, reason in checks:
            if not ok:
                self._log_audit('path_traversal_blocked', path, False, reason)
                return False, reason

        # Symlink check only for existing paths
        if os.path.lexists(path):
            ok, reason = self._check_symlink(path)
            if not ok:
                self._log_audit('path_traversal_blocked', path, False, reason)
                return False, reason

        return True, "Path traversal checks passed"

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
            # Run path traversal prevention checks first
            traversal_ok, traversal_reason = self.validate_path_traversal(path, operation)
            if not traversal_ok:
                return False, traversal_reason

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
            # Allow access to safe temp directories (e.g. macOS /var/folders)
            if not allowed:
                for temp_dir in self.SAFE_TEMP_DIRS:
                    temp_abs = os.path.abspath(temp_dir)
                    if abs_path.startswith(temp_abs + os.sep):
                        allowed = True
                        break
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