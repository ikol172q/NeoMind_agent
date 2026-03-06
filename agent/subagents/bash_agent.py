"""
Bash subagent for system operations.

Specializes in executing shell commands safely, managing processes,
and handling system-level operations.
"""

import os
import subprocess
import shlex
import time
import signal
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path

from .base import Subagent, SubagentMetadata
from ..safety import is_path_safe, log_operation


class BashAgent(Subagent):
    """Subagent for system operations and command execution."""

    @classmethod
    def _default_metadata(cls) -> SubagentMetadata:
        return SubagentMetadata(
            name="bash",
            description="Execute shell commands safely, manage processes, and handle system-level operations.",
            capabilities=[
                "command_execution",
                "process_management",
                "file_operations",
                "system_monitoring",
                "package_management",
                "network_operations"
            ],
            input_schema={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Shell command to execute"
                    },
                    "working_directory": {
                        "type": "string",
                        "description": "Working directory for command execution"
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Timeout in seconds (0 = no timeout)",
                        "minimum": 0,
                        "maximum": 3600,
                        "default": 30
                    },
                    "capture_output": {
                        "type": "boolean",
                        "description": "Capture command output",
                        "default": True
                    },
                    "environment": {
                        "type": "object",
                        "description": "Environment variables to set",
                        "additionalProperties": {"type": "string"}
                    },
                    "shell": {
                        "type": "boolean",
                        "description": "Use shell execution (less safe)",
                        "default": False
                    }
                },
                "required": ["command"]
            },
            output_schema={
                "type": "object",
                "properties": {
                    "success": {"type": "boolean"},
                    "exit_code": {"type": "integer"},
                    "stdout": {"type": "string"},
                    "stderr": {"type": "string"},
                    "execution_time": {"type": "number"},
                    "command": {"type": "string"},
                    "warnings": {"type": "array"}
                },
                "required": ["success", "exit_code"]
            },
            categories=["system", "operations"],
            max_execution_time=300,
            requires_isolation=True
        )

    def __init__(self, metadata: Optional[SubagentMetadata] = None):
        super().__init__(metadata)
        self.safety_manager = None

    def set_safety_manager(self, safety_manager):
        """Set safety manager for command validation."""
        self.safety_manager = safety_manager

    def execute(self, task_description: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute shell command.

        Args:
            task_description: Description of the system task.
            parameters: Command parameters.

        Returns:
            Command execution results.
        """
        import time
        start_time = time.time()

        try:
            self.validate_input(parameters)

            command = parameters.get("command", "")
            working_dir = parameters.get("working_directory", os.getcwd())
            timeout = parameters.get("timeout", 30)
            capture_output = parameters.get("capture_output", True)
            environment = parameters.get("environment", {})
            use_shell = parameters.get("shell", False)

            # Safety checks
            warnings = self._validate_command_safety(command, working_dir)

            # Execute command
            result = self._execute_command(
                command, working_dir, timeout, capture_output,
                environment, use_shell
            )

            result["warnings"] = warnings
            result["execution_time"] = time.time() - start_time
            result["command"] = command

            # Log operation
            log_operation(
                "bash_agent_execution",
                command,
                result["success"],
                f"exit_code={result['exit_code']}, time={result['execution_time']:.2f}s"
            )

            return result

        except Exception as e:
            return {
                "success": False,
                "exit_code": -1,
                "stdout": "",
                "stderr": str(e),
                "execution_time": time.time() - start_time,
                "command": parameters.get("command", ""),
                "warnings": []
            }

    def _validate_command_safety(self, command: str, working_dir: str) -> List[str]:
        """Validate command for safety and return warnings."""
        warnings = []

        # Check working directory safety
        if self.safety_manager:
            is_safe, reason = self.safety_manager.is_path_safe(working_dir, 'execute')
            if not is_safe:
                warnings.append(f"Working directory may not be safe: {reason}")

        # Check for dangerous commands
        dangerous_patterns = [
            (r'rm\s+-rf', 'Recursive force delete (rm -rf)'),
            (r'chmod\s+[0-7]{3,4}\s+.*', 'Permission changes (chmod)'),
            (r'chown\s+.*', 'Ownership changes (chown)'),
            (r'dd\s+.*', 'Disk operations (dd)'),
            (r'mkfs\.', 'Filesystem creation'),
            (r'fdisk', 'Disk partitioning'),
            (r'format', 'Format commands'),
            (r'poweroff', 'Shutdown commands'),
            (r'reboot', 'Reboot commands'),
            (r'init\s+[06]', 'System halt/reboot'),
            (r'shutdown', 'Shutdown commands'),
        ]

        command_lower = command.lower()
        for pattern, description in dangerous_patterns:
            if re.search(pattern, command_lower):
                warnings.append(f"Potentially dangerous command: {description}")

        # Check for network operations that might be intensive
        network_intensive = [
            'wget', 'curl', 'scp', 'rsync', 'ssh', 'ping', 'traceroute',
            'nmap', 'netcat', 'telnet'
        ]
        for cmd in network_intensive:
            if command_lower.startswith(cmd + ' ') or command_lower == cmd:
                warnings.append(f"Network operation detected: {cmd}")
                break

        return warnings

    def _execute_command(self, command: str, working_dir: str,
                        timeout: int, capture_output: bool,
                        env_vars: Dict[str, str], use_shell: bool) -> Dict[str, Any]:
        """Execute shell command with proper error handling."""
        # Prepare environment
        env = os.environ.copy()
        env.update(env_vars)

        # Prepare working directory
        if not os.path.exists(working_dir):
            return {
                "success": False,
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Working directory does not exist: {working_dir}",
            }

        try:
            if use_shell:
                # Shell execution (less safe but supports shell features)
                process = subprocess.Popen(
                    command,
                    shell=True,
                    cwd=working_dir,
                    env=env,
                    stdout=subprocess.PIPE if capture_output else None,
                    stderr=subprocess.PIPE if capture_output else None,
                    text=True,
                    preexec_fn=os.setsid if hasattr(os, 'setsid') else None
                )
            else:
                # Safe execution without shell
                args = shlex.split(command)
                process = subprocess.Popen(
                    args,
                    shell=False,
                    cwd=working_dir,
                    env=env,
                    stdout=subprocess.PIPE if capture_output else None,
                    stderr=subprocess.PIPE if capture_output else None,
                    text=True
                )

            # Wait with timeout
            try:
                stdout, stderr = process.communicate(timeout=timeout if timeout > 0 else None)
                exit_code = process.returncode
            except subprocess.TimeoutExpired:
                # Kill the process group if using shell
                if use_shell and hasattr(os, 'killpg'):
                    os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                else:
                    process.terminate()
                    process.wait(timeout=5)

                return {
                    "success": False,
                    "exit_code": -2,
                    "stdout": stdout if 'stdout' in locals() else "",
                    "stderr": stderr if 'stderr' in locals() else "Command timed out",
                }

            success = exit_code == 0

            return {
                "success": success,
                "exit_code": exit_code,
                "stdout": stdout if capture_output else "",
                "stderr": stderr if capture_output else "",
            }

        except FileNotFoundError as e:
            return {
                "success": False,
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Command not found: {e}",
            }
        except PermissionError as e:
            return {
                "success": False,
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Permission denied: {e}",
            }
        except Exception as e:
            return {
                "success": False,
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Execution error: {e}",
            }

    # Additional utility methods for system operations

    def list_processes(self, filter_pattern: str = "") -> Dict[str, Any]:
        """List running processes."""
        import psutil

        try:
            processes = []
            for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
                try:
                    info = proc.info
                    if filter_pattern and filter_pattern.lower() not in info['name'].lower():
                        continue
                    processes.append(info)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            return {
                "success": True,
                "processes": processes[:100],  # Limit output
                "count": len(processes),
                "summary": f"Found {len(processes)} processes"
            }
        except ImportError:
            return {
                "success": False,
                "error": "psutil not installed. Install with: pip install psutil"
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    def disk_usage(self, path: str = "/") -> Dict[str, Any]:
        """Check disk usage."""
        try:
            import shutil
            usage = shutil.disk_usage(path)

            return {
                "success": True,
                "path": path,
                "total_gb": usage.total / (1024**3),
                "used_gb": usage.used / (1024**3),
                "free_gb": usage.free / (1024**3),
                "percent_used": (usage.used / usage.total) * 100,
                "summary": f"Disk usage at {path}: {usage.used/(1024**3):.1f}GB used of {usage.total/(1024**3):.1f}GB total ({usage.used/usage.total*100:.1f}%)"
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    def network_info(self) -> Dict[str, Any]:
        """Get network information."""
        try:
            import socket
            import netifaces

            info = {
                "hostname": socket.gethostname(),
                "interfaces": {}
            }

            for interface in netifaces.interfaces():
                addrs = netifaces.ifaddresses(interface)
                if netifaces.AF_INET in addrs:
                    ipv4_info = addrs[netifaces.AF_INET][0]
                    info["interfaces"][interface] = {
                        "ipv4": ipv4_info.get('addr'),
                        "netmask": ipv4_info.get('netmask')
                    }

            return {
                "success": True,
                "network_info": info,
                "summary": f"Hostname: {info['hostname']}, {len(info['interfaces'])} active interfaces"
            }
        except ImportError:
            # Fallback to basic info
            try:
                import socket
                return {
                    "success": True,
                    "hostname": socket.gethostname(),
                    "summary": "Basic network info (install netifaces for details)"
                }
            except Exception as e:
                return {
                    "success": False,
                    "error": f"Cannot get network info: {e}"
                }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    def system_info(self) -> Dict[str, Any]:
        """Get system information."""
        import platform
        import sys

        info = {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "python_version": sys.version,
            "python_implementation": platform.python_implementation(),
        }

        # Try to get more detailed info
        try:
            import psutil
            info.update({
                "cpu_count": psutil.cpu_count(),
                "total_memory_gb": psutil.virtual_memory().total / (1024**3),
                "available_memory_gb": psutil.virtual_memory().available / (1024**3),
            })
            summary = f"{info['system']} {info['release']} ({info['machine']}), {info['cpu_count']} CPUs, {info['total_memory_gb']:.1f}GB RAM"
        except ImportError:
            summary = f"{info['system']} {info['release']} ({info['machine']})"

        return {
            "success": True,
            "system_info": info,
            "summary": summary
        }