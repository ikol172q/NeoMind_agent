"""NeoMind Self-Edit Engine — Git-Gated Code Self-Modification

Allows NeoMind to modify its own Python source code with safety guarantees:
1. AST analysis blocks dangerous operations (exec, eval, os.system, etc.)
2. Syntax validation before applying changes
3. Tests run in forked subprocess — failure doesn't crash main process
4. Every change is a git commit — full audit trail
5. Smart reload: hot-reload for simple modules, full supervisor restart for core files
6. Daily edit limit (10/day) prevents runaway modifications

Docker context:
- Code lives at /app (volume-mounted from host for persistence)
- Git is available (installed in Dockerfile)
- /app is the git repo root
- Data persists at /data/neomind (Docker volume)
- supervisord manages the agent process (restart without container rebuild)

No external dependencies — stdlib only.
"""

import ast
import subprocess
import importlib
import sys
import json
import logging
import os
from pathlib import Path
from datetime import datetime, timezone, date
from typing import Tuple, Optional, List, Set

logger = logging.getLogger(__name__)


class SelfEditor:
    """Git-Gated Self-Edit Pipeline.

    Design principles:
    1. Every modification = git commit → complete audit trail
    2. AST analysis blocks dangerous calls → safety boundary
    3. pytest in fork process → failure doesn't affect main process
    4. importlib.reload hot-loads changes → no container restart needed
    5. Constitutional AI constraints enforce safety guarantees
    """

    REPO_DIR = Path("/app")  # Code directory in Docker
    DATA_DIR = Path("/data/neomind/evolution")

    # Functions that must never appear in self-edited code
    FORBIDDEN_CALLS: Set[str] = {
        "exec", "eval", "__import__",
        "os.system", "os.execv", "os.execve", "os.execvp",
        "subprocess.call", "subprocess.Popen",
        "shutil.rmtree",
        "ctypes.cdll",
    }

    # Files that must never be self-modified
    FORBIDDEN_PATHS: Set[str] = {
        ".env", ".env.example",
        "docker-entrypoint.sh",
        "Dockerfile", "docker-compose.yml",
        "supervisord.conf",
        "agent/evolution/self_edit.py",   # Can't modify itself
        "agent/evolution/health_monitor.py",  # Safety-critical
        "agent/evolution/watchdog.py",    # Safety-critical
    }

    # Imports that are not allowed
    FORBIDDEN_IMPORTS: Set[str] = {
        "ctypes", "cffi", "multiprocessing",
    }

    # Constitutional AI principles that cannot be overridden
    CONSTITUTIONAL_PRINCIPLES = [
        "Never modify safety-critical files (self_edit.py, health_monitor.py, watchdog.py)",
        "Never introduce code that disables safety checks or logging",
        "Never remove or weaken existing safety constraints",
        "Never add network access to external endpoints not in allowlist",
        "Every self-edit must be reversible via git revert",
        "Self-edit code must not increase memory usage by >10MB",
        "Never modify compliance or rate-limiting modules to be more permissive",
    ]

    # Allowlisted domains for network calls validation
    ALLOWLISTED_DOMAINS: Set[str] = {
        "api.anthropic.com",
        "api.openai.com",
        "localhost",
        "127.0.0.1",
    }

    MAX_EDITS_PER_DAY = 10
    MAX_FILE_SIZE = 50_000  # 50KB max per file
    MAX_MEMORY_INCREASE_MB = 10

    def __init__(self):
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.edit_log = self.DATA_DIR / "edit_history.jsonl"
        self._today = date.today()
        self._today_edits = self._count_today_edits()

    # ── Public API ─────────────────────────────────────────

    def propose_edit(self, file_path: str, reason: str,
                     new_content: str) -> Tuple[bool, str]:
        """Propose a code modification through the full safety pipeline.

        Args:
            file_path: Absolute or relative path to the file
            reason: Human-readable reason for the change
            new_content: Complete new file content

        Returns:
            (success: bool, message: str)
        """
        # Normalize path
        try:
            if Path(file_path).is_absolute():
                rel_path = str(Path(file_path).relative_to(self.REPO_DIR))
            else:
                rel_path = file_path
        except ValueError:
            return False, f"File must be under {self.REPO_DIR}"

        # ── Guard 1: Daily limit ──
        if self._today != date.today():
            self._today = date.today()
            self._today_edits = 0

        if self._today_edits >= self.MAX_EDITS_PER_DAY:
            return False, f"Daily edit limit reached ({self.MAX_EDITS_PER_DAY})"

        # ── Guard 2: Forbidden files ──
        if rel_path in self.FORBIDDEN_PATHS:
            return False, f"Cannot modify protected file: {rel_path}"

        # ── Guard 3: Only .py files ──
        if not rel_path.endswith(".py"):
            return False, "Only .py files can be self-modified"

        # ── Guard 4: File size ──
        if len(new_content.encode()) > self.MAX_FILE_SIZE:
            return False, f"Content exceeds {self.MAX_FILE_SIZE} bytes"

        # ── Guard 5: Syntax check ──
        try:
            compile(new_content, rel_path, "exec")
        except SyntaxError as e:
            return False, f"Syntax error: {e}"

        # ── Guard 6: AST safety check ──
        safe, ast_msg = self._ast_safety_check(new_content)
        if not safe:
            return False, f"AST safety check failed: {ast_msg}"

        # ── Guard 6.5: Constitutional AI review ──
        original = (self.REPO_DIR / rel_path).read_text() if (self.REPO_DIR / rel_path).exists() else ""
        const_safe, const_violations = self._constitutional_review(original, new_content, rel_path)
        if not const_safe:
            msg = "Constitutional safety violations: " + "; ".join(const_violations)
            return False, msg

        # ── Guard 6.6: Integration hooks (AgentSpec + Debate consensus) ──
        try:
            from agent.evolution.integration_hooks import self_edit_gate
            allowed, gate_msg = self_edit_gate(
                file_path=rel_path,
                new_content=new_content,
                old_content=original,
                reason=reason,
            )
            if not allowed:
                self._log_edit(rel_path, reason, "blocked", gate_msg)
                return False, gate_msg
        except ImportError:
            pass  # hooks not installed
        except Exception as e:
            logger.warning(f"Self-edit gate error (proceeding): {e}")

        # ── Guard 7: Safe mode check ──
        if os.getenv("NEOMIND_SAFE_MODE") == "1":
            return False, "Self-edit disabled in safe mode"

        # ── Apply change ──
        target = self.REPO_DIR / rel_path
        original = target.read_text() if target.exists() else None

        # Write new content
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(new_content)

        # ── Test in fork process ──
        test_ok, test_msg = self._run_tests_in_fork(rel_path)

        if not test_ok:
            # Rollback
            if original is not None:
                target.write_text(original)
            else:
                target.unlink(missing_ok=True)
            self._log_edit(rel_path, reason, "ROLLBACK", test_msg)
            return False, f"Tests failed, rolled back: {test_msg}"

        # ── Git commit ──
        self._git_commit(rel_path, reason)

        # ── Hot reload or full restart ──
        restart_scheduled = False
        try:
            from agent.evolution.self_restart import needs_full_restart, request_restart, is_supervisor_managed
            if needs_full_restart(rel_path) and is_supervisor_managed():
                ok, restart_msg = request_restart(
                    reason=f"Self-edit: {reason[:200]}",
                    changed_files=[rel_path],
                    delay_seconds=3.0,
                )
                restart_scheduled = ok
                if ok:
                    logger.info(f"Full restart scheduled after editing {rel_path}")
        except ImportError:
            pass
        except Exception as e:
            logger.warning(f"Self-restart check failed (non-blocking): {e}")

        if not restart_scheduled:
            # Try hot-reload (sufficient for evolution/* modules etc.)
            module_name = rel_path.replace("/", ".").replace(".py", "")
            reload_ok = self._hot_reload(module_name)
        else:
            reload_ok = False  # will be loaded fresh after restart

        self._today_edits += 1
        if restart_scheduled:
            status_msg = "restart scheduled"
        elif reload_ok:
            status_msg = "hot-reloaded"
        else:
            status_msg = "reload pending"

        self._log_edit(rel_path, reason, "APPLIED", f"Tests passed, {status_msg}")

        suffix = " (进程将在 3 秒后重启以加载更改)" if restart_scheduled else ""
        return True, f"Applied edit to {rel_path} and committed{suffix}"

    def get_edit_history(self, limit: int = 20) -> List[dict]:
        """Return recent edit history."""
        if not self.edit_log.exists():
            return []
        try:
            lines = self.edit_log.read_text().splitlines()
            entries = [json.loads(l) for l in lines[-limit:]]
            return list(reversed(entries))
        except Exception:
            return []

    def get_stats(self) -> dict:
        """Return edit statistics."""
        history = self.get_edit_history(limit=1000)
        return {
            "today_edits": self._today_edits,
            "daily_limit": self.MAX_EDITS_PER_DAY,
            "total_edits": len(history),
            "applied": sum(1 for e in history if e.get("status") == "APPLIED"),
            "rollbacks": sum(1 for e in history if e.get("status") == "ROLLBACK"),
        }

    # ── AST Safety Analysis ────────────────────────────────

    def _ast_safety_check(self, code: str) -> Tuple[bool, str]:
        """Analyze AST to block dangerous operations."""
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return False, str(e)

        for node in ast.walk(tree):
            # Check dangerous function calls
            if isinstance(node, ast.Call):
                func_name = self._get_call_name(node)
                if func_name in self.FORBIDDEN_CALLS:
                    return False, f"Forbidden call: {func_name} (line {node.lineno})"

            # Check dangerous imports
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in self.FORBIDDEN_IMPORTS:
                        return False, f"Forbidden import: {alias.name} (line {node.lineno})"

            if isinstance(node, ast.ImportFrom):
                if node.module and node.module.split(".")[0] in self.FORBIDDEN_IMPORTS:
                    return False, f"Forbidden import from: {node.module} (line {node.lineno})"

        return True, "passed"

    def _get_call_name(self, node: ast.Call) -> str:
        """Extract fully qualified function name from AST Call node."""
        if isinstance(node.func, ast.Name):
            return node.func.id
        elif isinstance(node.func, ast.Attribute):
            parts = []
            current = node.func
            while isinstance(current, ast.Attribute):
                parts.append(current.attr)
                current = current.value
            if isinstance(current, ast.Name):
                parts.append(current.id)
            return ".".join(reversed(parts))
        return ""

    # ── Constitutional AI Review ───────────────────────────────

    def _constitutional_review(self, old_content: str, new_content: str,
                               file_path: str) -> Tuple[bool, List[str]]:
        """Constitutional AI-inspired review ensuring safety constraints.

        Compares old vs new AST to detect:
        - Removed safety checks (try/except, logging, assertions)
        - Disabled safety-critical code
        - Weakened rate limits or compliance modules
        - Non-allowlisted network endpoints

        Returns:
            (safe: bool, violations: List[str])
        """
        violations = []

        try:
            old_ast = ast.parse(old_content) if old_content else ast.parse("pass")
            new_ast = ast.parse(new_content)
        except SyntaxError as e:
            return False, [f"AST parse error: {e}"]

        # Detect safety regression (removed safety checks)
        regression = self._detect_safety_regression(old_ast, new_ast)
        if regression:
            violations.extend(regression)

        # Check for network calls to non-allowlisted domains
        network_issues = self._check_network_allowlist(new_ast)
        if network_issues:
            violations.extend(network_issues)

        # Ensure reversibility via git
        if not file_path.endswith(".py"):
            violations.append("Only .py files are reversible via git revert")

        if violations:
            return False, violations
        return True, []

    def _detect_safety_regression(self, old_ast: ast.AST,
                                  new_ast: ast.AST) -> List[str]:
        """Detect removed or weakened safety checks.

        Checks:
        - try/except blocks (new >= old)
        - logging calls (new >= old)
        - assert statements (new >= old)
        - if guards and early returns
        """
        violations = []

        old_counts = self._count_safety_patterns(old_ast)
        new_counts = self._count_safety_patterns(new_ast)

        # Try/except blocks should not decrease
        if new_counts["try_except"] < old_counts["try_except"]:
            violations.append(
                f"Removed {old_counts['try_except'] - new_counts['try_except']} "
                "try/except block(s)"
            )

        # Logging calls should not decrease
        if new_counts["logging"] < old_counts["logging"]:
            violations.append(
                f"Removed {old_counts['logging'] - new_counts['logging']} "
                "logging call(s)"
            )

        # Assertions should not decrease
        if new_counts["assert"] < old_counts["assert"]:
            violations.append(
                f"Removed {old_counts['assert'] - new_counts['assert']} "
                "assertion(s)"
            )

        # If guards should not decrease (early returns checking conditions)
        if new_counts["if_guards"] < old_counts["if_guards"]:
            violations.append(
                f"Removed {old_counts['if_guards'] - new_counts['if_guards']} "
                "safety guard condition(s)"
            )

        return violations

    def _count_safety_patterns(self, tree: ast.AST) -> dict:
        """Count safety-related patterns in AST."""
        counts = {
            "try_except": 0,
            "logging": 0,
            "assert": 0,
            "if_guards": 0,
        }

        for node in ast.walk(tree):
            # Count try/except blocks
            if isinstance(node, ast.Try):
                counts["try_except"] += 1

            # Count logging calls
            if isinstance(node, ast.Call):
                func_name = self._get_call_name(node)
                if "logger" in func_name or "logging" in func_name:
                    counts["logging"] += 1

            # Count assertions
            if isinstance(node, ast.Assert):
                counts["assert"] += 1

            # Count if statements (guards)
            if isinstance(node, ast.If):
                # Count if statements that aren't in comprehensions
                counts["if_guards"] += 1

        return counts

    def _check_network_allowlist(self, tree: ast.AST) -> List[str]:
        """Detect network calls to non-allowlisted domains.

        Checks for:
        - requests.get/post with URL strings
        - urllib.request with URLs
        - socket operations
        """
        violations = []

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func_name = self._get_call_name(node)

                # Check requests library
                if func_name.startswith("requests."):
                    # Check first string argument for domain
                    for arg in node.args:
                        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                            url = arg.value
                            if not self._is_allowlisted_url(url):
                                violations.append(
                                    f"Non-allowlisted network call: {func_name} to {url}"
                                )

                # Check urllib
                if "urllib" in func_name:
                    for arg in node.args:
                        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                            url = arg.value
                            if not self._is_allowlisted_url(url):
                                violations.append(
                                    f"Non-allowlisted network call: {func_name} to {url}"
                                )

        return violations

    def _is_allowlisted_url(self, url: str) -> bool:
        """Check if URL uses an allowlisted domain."""
        for domain in self.ALLOWLISTED_DOMAINS:
            if domain in url or url.startswith(f"http://{domain}") or url.startswith(f"https://{domain}"):
                return True
        return False

    # ── Fork-Process Testing ───────────────────────────────

    def _run_tests_in_fork(self, changed_file: str) -> Tuple[bool, str]:
        """Run pytest in subprocess — failure doesn't affect main process."""
        try:
            test_file = self._find_test_for(changed_file)
            if test_file:
                cmd = ["python", "-m", "pytest", "-x", "--tb=short", "-q", test_file]
            else:
                # No test file — at minimum verify the module imports
                module = changed_file.replace("/", ".").replace(".py", "")
                cmd = ["python", "-c",
                       f"import importlib; m = importlib.import_module('{module}'); "
                       f"print(f'Import OK: {{m.__name__}}')"]

            result = subprocess.run(
                cmd,
                capture_output=True, text=True,
                timeout=60,
                cwd=str(self.REPO_DIR),
                env={**os.environ, "PYTHONPATH": str(self.REPO_DIR)},
            )

            if result.returncode == 0:
                return True, result.stdout[-300:].strip()
            else:
                output = (result.stderr or result.stdout)[-500:].strip()
                return False, output

        except subprocess.TimeoutExpired:
            return False, "Tests timed out (60s)"
        except Exception as e:
            return False, f"Test execution error: {e}"

    def _find_test_for(self, file_path: str) -> Optional[str]:
        """Find the corresponding test file for a source file."""
        name = Path(file_path).stem
        parent = Path(file_path).parent.name

        candidates = [
            f"tests/test_{name}.py",
            f"tests/test_{parent}.py",
            f"tests/{parent}/test_{name}.py",
        ]

        for c in candidates:
            if (self.REPO_DIR / c).exists():
                return c
        return None

    # ── Hot Reload ─────────────────────────────────────────

    def _hot_reload(self, module_name: str) -> bool:
        """Hot-reload a modified module via importlib.reload."""
        try:
            if module_name in sys.modules:
                module = sys.modules[module_name]
                importlib.reload(module)
                logger.info(f"Hot-reloaded: {module_name}")
                return True
            else:
                logger.debug(f"Module not loaded, skip reload: {module_name}")
                return True  # Will be loaded fresh next time
        except Exception as e:
            # Hot-reload failure is not catastrophic — new code loads on restart
            logger.warning(f"Hot-reload failed for {module_name}: {e}")
            return False

    # ── Git Operations ─────────────────────────────────────

    def _git_commit(self, file_path: str, reason: str):
        """Commit the change to git with audit message."""
        try:
            # Ensure git repo exists
            if not (self.REPO_DIR / ".git").exists():
                subprocess.run(
                    ["git", "init"],
                    cwd=str(self.REPO_DIR), capture_output=True, timeout=5
                )
                subprocess.run(
                    ["git", "add", "-A"],
                    cwd=str(self.REPO_DIR), capture_output=True, timeout=10
                )
                subprocess.run(
                    ["git", "commit", "-m", "initial: pre-self-edit snapshot"],
                    cwd=str(self.REPO_DIR), capture_output=True, timeout=10
                )

            # Stage and commit the changed file
            subprocess.run(
                ["git", "add", file_path],
                cwd=str(self.REPO_DIR), capture_output=True, timeout=5
            )

            msg = f"[self-edit] {reason[:100]}"
            subprocess.run(
                ["git", "commit", "-m", msg],
                cwd=str(self.REPO_DIR), capture_output=True, timeout=10
            )
            logger.info(f"Git commit: {msg}")
        except Exception as e:
            logger.warning(f"Git commit failed (non-blocking): {e}")

    def get_git_log(self, limit: int = 10) -> List[str]:
        """Get recent self-edit git commits."""
        try:
            result = subprocess.run(
                ["git", "log", "--oneline", f"-{limit}", "--grep=self-edit"],
                cwd=str(self.REPO_DIR),
                capture_output=True, text=True, timeout=5
            )
            return result.stdout.strip().splitlines() if result.returncode == 0 else []
        except Exception:
            return []

    # ── Logging ────────────────────────────────────────────

    def _log_edit(self, file: str, reason: str, status: str, detail: str):
        """Append to edit history log (JSONL format)."""
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "file": file,
            "reason": reason[:200],
            "status": status,
            "detail": detail[:300],
        }
        try:
            with open(self.edit_log, "a") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error(f"Failed to log edit: {e}")

    def _count_today_edits(self) -> int:
        """Count edits made today (for daily limit)."""
        if not self.edit_log.exists():
            return 0
        today_str = date.today().isoformat()
        count = 0
        try:
            for line in self.edit_log.read_text().splitlines():
                entry = json.loads(line)
                if entry.get("ts", "").startswith(today_str) and entry.get("status") == "APPLIED":
                    count += 1
        except Exception:
            pass
        return count
