"""
Sandbox system for isolated command execution.

Provides OS-level sandboxing for bash commands:
- macOS: sandbox-exec with Seatbelt profiles
- Linux: Firejail (if available)
- Fallback: No sandboxing with warning

Features:
- Filesystem restrictions (read-only outside workspace)
- Network domain allowlisting
- Process isolation
"""

import os
import logging
import platform
import subprocess
import tempfile
import shutil
from typing import Optional, List, Tuple

logger = logging.getLogger(__name__)


class SandboxManager:
    """Manages sandboxed command execution."""

    # Network domains allowed by default
    DEFAULT_ALLOWED_DOMAINS = [
        'github.com', 'api.github.com',
        'pypi.org', 'files.pythonhosted.org',
        'npmjs.org', 'registry.npmjs.org',
        'rubygems.org',
        'crates.io',
    ]

    # Paths always readable
    DEFAULT_READABLE_PATHS = [
        '/usr', '/bin', '/sbin', '/lib', '/etc/ssl', '/etc/resolv.conf',
        '/tmp', '/var/tmp',
        '/System', '/Library', '/Applications',
    ]

    # Writable paths (besides workspace) - additional dirs the sandbox allows writing to
    DEFAULT_WRITABLE_PATHS = [
        '/tmp', '/var/tmp',
    ]

    # Paths that should NEVER be writable from sandbox (even if in workspace)
    BLOCKED_WRITE_PATHS = [
        '/.ssh', '/.gnupg', '/.gitconfig', '/.bashrc', '/.zshrc',
        '/.profile', '/.env',
    ]

    def __init__(self, workspace_root: str = None,
                 allowed_domains: List[str] = None,
                 extra_readable: List[str] = None,
                 extra_writable: List[str] = None,
                 network_enabled: bool = True,
                 enabled: bool = True):
        self.workspace_root = os.path.abspath(workspace_root) if workspace_root else os.getcwd()
        self.allowed_domains = allowed_domains or self.DEFAULT_ALLOWED_DOMAINS
        self.extra_readable = extra_readable or []
        self.extra_writable = extra_writable or []
        self.network_enabled = network_enabled
        self.enabled = enabled
        self._system = platform.system()
        self._sandbox_available = self._detect_sandbox()

    def _detect_sandbox(self) -> bool:
        """Detect if sandbox tooling is available."""
        if not self.enabled:
            return False
        if self._system == 'Darwin':
            return shutil.which('sandbox-exec') is not None
        elif self._system == 'Linux':
            return shutil.which('firejail') is not None
        return False

    @property
    def is_available(self) -> bool:
        return self._sandbox_available

    def _generate_seatbelt_profile(self) -> str:
        """Generate macOS Seatbelt profile for sandboxed execution."""
        readable_paths = self.DEFAULT_READABLE_PATHS + [
            os.path.expanduser('~/.gitconfig'),
            os.path.expanduser('~/.ssh'),
        ]

        home = os.path.expanduser('~')
        profile = f"""(version 1)
(deny default)

;; Allow basic process operations
(allow process*)
(allow signal)
(allow sysctl-read)
(allow mach*)
(allow ipc*)
(allow iokit*)

;; Allow reading system and common paths
(allow file-read*
    (subpath "/usr")
    (subpath "/bin")
    (subpath "/sbin")
    (subpath "/lib")
    (subpath "/etc")
    (subpath "/tmp")
    (subpath "/var")
    (subpath "/System")
    (subpath "/Library")
    (subpath "/Applications")
    (subpath "/dev")
    (subpath "/private/tmp")
    (subpath "/private/var")
    (subpath "/private/etc")
    (subpath "{home}")
)

;; Full access to workspace
(allow file-read* (subpath "{self.workspace_root}"))
(allow file-write* (subpath "{self.workspace_root}"))

;; Allow writing to temp
(allow file-write* (subpath "/tmp"))
(allow file-write* (subpath "/private/tmp"))
(allow file-write* (subpath "/private/var/tmp"))

;; Block writing to protected home config files
(deny file-write* (literal "{home}/.bashrc"))
(deny file-write* (literal "{home}/.zshrc"))
(deny file-write* (literal "{home}/.profile"))
(deny file-write* (literal "{home}/.bash_profile"))
(deny file-write* (literal "{home}/.gitconfig"))
(deny file-write* (subpath "{home}/.ssh"))
(deny file-write* (subpath "{home}/.gnupg"))
(deny file-write* (literal "{home}/.env"))
(deny file-write* (literal "{home}/.netrc"))
(deny file-write* (literal "{home}/.npmrc"))
"""
        # Extra readable paths
        for rp in self.extra_readable:
            if os.path.exists(rp):
                profile += f'\n(allow file-read* (subpath "{rp}"))\n'

        # Extra writable paths
        for wp in self.extra_writable + self.DEFAULT_WRITABLE_PATHS:
            if os.path.exists(wp):
                profile += f'(allow file-write* (subpath "{wp}"))\n'

        # Network control
        if self.network_enabled:
            profile += '\n;; Allow network access\n(allow network*)\n'
        else:
            profile += '\n;; Network disabled\n(deny network*)\n'
        return profile

    def _build_firejail_args(self, command: str) -> List[str]:
        """Build Firejail command arguments for Linux sandboxing."""
        args = [
            'firejail',
            '--quiet',
            f'--whitelist={self.workspace_root}',
            '--read-only=/usr',
            '--read-only=/bin',
            '--read-only=/sbin',
            '--read-only=/lib',
            '--read-only=/etc',
            '--noroot',
            '--nosound',
            '--no3d',
            '--nodvd',
        ]

        # Network control
        if not self.network_enabled:
            args.append('--net=none')

        args.extend(['--', 'bash', '-c', command])
        return args

    def execute_sandboxed(self, command: str, timeout: int = 120,
                          cwd: str = None) -> Tuple[int, str, str]:
        """Execute a command in a sandbox.

        Args:
            command: Shell command to execute
            timeout: Timeout in seconds
            cwd: Working directory

        Returns:
            Tuple[exit_code, stdout, stderr]
        """
        working_dir = cwd or self.workspace_root

        if not self._sandbox_available:
            return self._execute_unsandboxed(command, timeout, working_dir)

        if self._system == 'Darwin':
            code, stdout, stderr = self._execute_seatbelt(command, timeout, working_dir)
            # Fallback if sandbox-exec fails (common on modern macOS with SIP)
            if code < 0 or (code != 0 and 'sandbox' in stderr.lower()):
                return self._execute_unsandboxed(command, timeout, working_dir)
            return code, stdout, stderr
        elif self._system == 'Linux':
            code, stdout, stderr = self._execute_firejail(command, timeout, working_dir)
            if code != 0 and 'firejail' in stderr.lower():
                return self._execute_unsandboxed(command, timeout, working_dir)
            return code, stdout, stderr
        else:
            return self._execute_unsandboxed(command, timeout, working_dir)

    def _execute_unsandboxed(self, command: str, timeout: int,
                              cwd: str) -> Tuple[int, str, str]:
        """Execute command without sandbox (fallback)."""
        try:
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True,
                timeout=timeout, cwd=cwd
            )
            return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return 124, '', f'Command timed out after {timeout}s'
        except Exception as e:
            return 1, '', str(e)

    def _execute_seatbelt(self, command: str, timeout: int,
                          cwd: str) -> Tuple[int, str, str]:
        """Execute command in macOS sandbox-exec."""
        profile = self._generate_seatbelt_profile()

        # Write profile to temp file
        profile_fd, profile_path = tempfile.mkstemp(suffix='.sb', prefix='neomind_')
        try:
            with os.fdopen(profile_fd, 'w') as f:
                f.write(profile)

            result = subprocess.run(
                ['sandbox-exec', '-f', profile_path, 'bash', '-c', command],
                capture_output=True, text=True, timeout=timeout, cwd=cwd
            )
            return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return 124, '', f'Command timed out after {timeout}s'
        except Exception as e:
            return 1, '', f'Sandbox execution error: {e}'
        finally:
            try:
                os.unlink(profile_path)
            except OSError:
                pass

    def _execute_firejail(self, command: str, timeout: int,
                          cwd: str) -> Tuple[int, str, str]:
        """Execute command in Linux Firejail."""
        args = self._build_firejail_args(command)
        try:
            result = subprocess.run(
                args, capture_output=True, text=True, timeout=timeout, cwd=cwd
            )
            return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return 124, '', f'Command timed out after {timeout}s'
        except Exception as e:
            return 1, '', f'Firejail execution error: {e}'

    # Auto-allow setting: if sandbox is active, auto-approve Bash commands
    auto_allow_if_sandboxed: bool = False

    def cleanup_after_command(self, cwd: str = None):
        """Post-execution cleanup — scrub dangerous artifacts.

        Removes git bare repo files that could be planted to escape sandbox
        when Claude's unsandboxed git runs later.
        """
        working_dir = cwd or self.workspace_root
        dangerous_git_files = ['HEAD', 'config', 'hooks']
        for fname in dangerous_git_files:
            fpath = os.path.join(working_dir, fname)
            # Only remove if it looks like a planted bare repo file
            if os.path.isfile(fpath):
                try:
                    with open(fpath, 'r') as f:
                        content = f.read(100)
                    if 'ref:' in content or '[core]' in content:
                        os.unlink(fpath)
                        logger.info(f"Scrubbed planted git file: {fpath}")
                except Exception:
                    pass

        # Remove bare repo directories
        for dname in ['objects', 'refs']:
            dpath = os.path.join(working_dir, dname)
            if os.path.isdir(dpath) and not os.path.exists(os.path.join(working_dir, '.git')):
                try:
                    shutil.rmtree(dpath)
                    logger.info(f"Scrubbed planted git directory: {dpath}")
                except Exception:
                    pass

    def should_auto_allow(self, command: str) -> bool:
        """Check if a command should be auto-allowed because sandbox is active.

        Only returns True when:
        1. Sandbox is enabled and available
        2. auto_allow_if_sandboxed is True
        3. Command will actually be sandboxed (not in excludedCommands)
        """
        if not self.auto_allow_if_sandboxed:
            return False
        if not self._sandbox_available:
            return False
        return True

    def refresh_config(self, workspace_root: str = None,
                       allowed_domains: List[str] = None,
                       enabled: bool = None):
        """Update sandbox configuration."""
        if workspace_root is not None:
            self.workspace_root = os.path.abspath(workspace_root)
        if allowed_domains is not None:
            self.allowed_domains = allowed_domains
        if enabled is not None:
            self.enabled = enabled
            self._sandbox_available = self._detect_sandbox()
