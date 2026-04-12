"""User-configurable Hooks System — PreToolUse / PostToolUse shell commands.

Reference: claudecode hooks.rs — shell-based hook execution with env vars.

Hooks are configured in ~/.neomind/settings.json under the "hooks" key:

    {
        "hooks": {
            "pre_tool_use": [
                {
                    "command": "/path/to/script.sh",
                    "tools": ["Bash", "Edit"],  // optional filter, empty = all
                    "enabled": true
                }
            ],
            "post_tool_use": [
                {
                    "command": "/path/to/logger.sh",
                    "tools": [],
                    "enabled": true
                }
            ]
        }
    }

Environment variables passed to hooks:
    PreToolUse:  HOOK_TOOL_NAME, HOOK_TOOL_INPUT (JSON)
    PostToolUse: HOOK_TOOL_NAME, HOOK_TOOL_INPUT (JSON),
                 HOOK_TOOL_OUTPUT, HOOK_TOOL_IS_ERROR ("true"/"false")

Exit codes:
    0 = allow (continue execution)
    2 = deny  (block tool execution, return denial message)
    other = warn (log warning, continue execution)

Hook stdout is captured and can be appended to tool context.
"""

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

SETTINGS_PATH = Path.home() / ".neomind" / "settings.json"


class HookResult:
    """Result of running a hook."""

    __slots__ = ("exit_code", "stdout", "stderr", "hook_name")

    def __init__(self, exit_code: int, stdout: str = "", stderr: str = "",
                 hook_name: str = ""):
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr
        self.hook_name = hook_name

    @property
    def allowed(self) -> bool:
        return self.exit_code != 2

    @property
    def is_warning(self) -> bool:
        return self.exit_code not in (0, 2)

    def __repr__(self):
        return f"HookResult(exit={self.exit_code}, allowed={self.allowed})"


class HookRunner:
    """Loads and executes user-configured shell hooks.

    Usage:
        runner = HookRunner()

        # Before tool execution:
        result = runner.run_pre_tool_use("Bash", {"command": "ls"})
        if not result.allowed:
            return "Tool blocked by hook"

        # After tool execution:
        runner.run_post_tool_use("Bash", {"command": "ls"}, "file1\\nfile2", False)
    """

    def __init__(self, settings_path: Optional[Path] = None):
        self._settings_path = settings_path or SETTINGS_PATH
        self._hooks: Dict[str, List[Dict[str, Any]]] = {
            "pre_tool_use": [],
            "post_tool_use": [],
        }
        self._load_hooks()

    def _load_hooks(self):
        """Load hook configuration from settings.json."""
        if not self._settings_path.exists():
            return

        try:
            data = json.loads(self._settings_path.read_text(encoding="utf-8"))
            hooks_cfg = data.get("hooks", {})

            for phase in ("pre_tool_use", "post_tool_use"):
                raw = hooks_cfg.get(phase, [])
                if not isinstance(raw, list):
                    continue
                for entry in raw:
                    if not isinstance(entry, dict):
                        continue
                    if not entry.get("command"):
                        continue
                    self._hooks[phase].append({
                        "command": entry["command"],
                        "tools": entry.get("tools", []),
                        "enabled": entry.get("enabled", True),
                    })

            logger.debug(
                f"Loaded hooks: pre={len(self._hooks['pre_tool_use'])}, "
                f"post={len(self._hooks['post_tool_use'])}"
            )
        except Exception as e:
            logger.warning(f"Failed to load hooks from {self._settings_path}: {e}")

    def reload(self):
        """Reload hooks from settings file."""
        self._hooks = {"pre_tool_use": [], "post_tool_use": []}
        self._load_hooks()

    def list_hooks(self, phase: str) -> List[Dict[str, Any]]:
        """List configured hooks for a phase."""
        return list(self._hooks.get(phase, []))

    def _matches_tool(self, hook: Dict[str, Any], tool_name: str) -> bool:
        """Check if a hook applies to the given tool."""
        tools_filter = hook.get("tools", [])
        if not tools_filter:
            return True  # empty = matches all tools
        return tool_name in tools_filter

    def _run_hook(self, command: str, env_vars: Dict[str, str],
                  timeout: int = 10) -> HookResult:
        """Execute a single hook command with environment variables."""
        env = os.environ.copy()
        env.update(env_vars)

        try:
            proc = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
            )
            result = HookResult(
                exit_code=proc.returncode,
                stdout=proc.stdout.strip(),
                stderr=proc.stderr.strip(),
                hook_name=command,
            )

            if result.is_warning:
                logger.warning(
                    f"Hook '{command}' exited with code {proc.returncode}: "
                    f"{result.stderr or result.stdout}"
                )

            return result

        except subprocess.TimeoutExpired:
            logger.error(f"Hook '{command}' timed out after {timeout}s")
            return HookResult(exit_code=1, stderr="Hook timed out",
                              hook_name=command)
        except Exception as e:
            logger.error(f"Hook '{command}' failed: {e}")
            return HookResult(exit_code=1, stderr=str(e), hook_name=command)

    def run_pre_tool_use(self, tool_name: str,
                         tool_input: Dict[str, Any]) -> HookResult:
        """Run all pre_tool_use hooks. Returns combined result.

        If ANY hook returns exit code 2, the tool is denied.
        Stdout from all hooks is concatenated.
        """
        combined_stdout = []
        input_json = json.dumps(tool_input, ensure_ascii=False, default=str)

        env_vars = {
            "HOOK_TOOL_NAME": tool_name,
            "HOOK_TOOL_INPUT": input_json,
        }

        for hook in self._hooks["pre_tool_use"]:
            if not hook.get("enabled", True):
                continue
            if not self._matches_tool(hook, tool_name):
                continue

            result = self._run_hook(hook["command"], env_vars)

            if result.stdout:
                combined_stdout.append(result.stdout)

            if not result.allowed:
                # Denied — return immediately
                return HookResult(
                    exit_code=2,
                    stdout="\n".join(combined_stdout),
                    stderr=result.stderr,
                    hook_name=hook["command"],
                )

        return HookResult(
            exit_code=0,
            stdout="\n".join(combined_stdout),
            hook_name="pre_tool_use",
        )

    def run_post_tool_use(self, tool_name: str, tool_input: Dict[str, Any],
                          tool_output: str, is_error: bool) -> HookResult:
        """Run all post_tool_use hooks. Returns combined result."""
        combined_stdout = []
        input_json = json.dumps(tool_input, ensure_ascii=False, default=str)

        env_vars = {
            "HOOK_TOOL_NAME": tool_name,
            "HOOK_TOOL_INPUT": input_json,
            "HOOK_TOOL_OUTPUT": tool_output[:10000],  # cap to prevent env overflow
            "HOOK_TOOL_IS_ERROR": "true" if is_error else "false",
        }

        for hook in self._hooks["post_tool_use"]:
            if not hook.get("enabled", True):
                continue
            if not self._matches_tool(hook, tool_name):
                continue

            result = self._run_hook(hook["command"], env_vars)

            if result.stdout:
                combined_stdout.append(result.stdout)

        return HookResult(
            exit_code=0,
            stdout="\n".join(combined_stdout),
            hook_name="post_tool_use",
        )
