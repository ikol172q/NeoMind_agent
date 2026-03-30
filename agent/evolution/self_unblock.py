"""NeoMind Self-Unblock Engine

When the agent encounters obstacles (network timeout, disk full, missing deps,
DB corruption), it automatically:
1. Diagnoses the problem (known fixes or diagnostic script)
2. Attempts repair (safe, sandboxed fixes only)
3. Reports to user if repair fails

Safety constraints:
- Adhoc scripts run in /tmp sandbox with 30s timeout
- Max 50 lines per script
- Only whitelisted modules can be pip-installed
- No modification of /app source code

No external dependencies — stdlib only.
"""

import os
import re
import subprocess
import tempfile
import json
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Tuple, Optional, List, Dict

logger = logging.getLogger(__name__)

SANDBOX_DIR = Path("/tmp/neomind_sandbox")
UNBLOCK_LOG = Path("/data/neomind/evolution/unblock_history.jsonl")


class SelfUnblocker:
    """Self-rescue engine for common runtime obstacles."""

    MAX_SCRIPT_LINES = 50       # Script line limit
    TIMEOUT = 30                # Script execution timeout (seconds)

    # ── Known fixes (no LLM needed) ────────────────────────

    KNOWN_FIXES: Dict[str, str] = {
        "disk_full": (
            "import shutil, os\n"
            "usage = shutil.disk_usage('/data')\n"
            "print(f'Data: {usage.used/1e9:.1f}GB / {usage.total/1e9:.1f}GB')\n"
            "usage2 = shutil.disk_usage('/tmp')\n"
            "print(f'Tmp:  {usage2.used/1e9:.1f}GB / {usage2.total/1e9:.1f}GB')\n"
            "# Clean old temp files\n"
            "cleaned = 0\n"
            "for d in ['/tmp', '/data/neomind/evolution']:\n"
            "    if not os.path.isdir(d): continue\n"
            "    for f in os.listdir(d):\n"
            "        p = os.path.join(d, f)\n"
            "        if f.startswith('tmp') or f.endswith('.tmp'):\n"
            "            try:\n"
            "                os.remove(p) if os.path.isfile(p) else shutil.rmtree(p)\n"
            "                cleaned += 1\n"
            "            except: pass\n"
            "print(f'Cleaned {cleaned} temp files')\n"
        ),

        "network_check": (
            "import urllib.request, socket\n"
            "socket.setdefaulttimeout(5)\n"
            "targets = [\n"
            "    ('httpbin.org', 'https://httpbin.org/ip'),\n"
            "    ('api.deepseek.com', 'https://api.deepseek.com'),\n"
            "]\n"
            "for name, url in targets:\n"
            "    try:\n"
            "        r = urllib.request.urlopen(url, timeout=5)\n"
            "        print(f'{name}: OK ({r.status})')\n"
            "    except Exception as e:\n"
            "        print(f'{name}: FAILED ({e})')\n"
        ),

        "db_integrity": (
            "import sqlite3, os, glob\n"
            "dbs = glob.glob('/data/neomind/db/*.db')\n"
            "for db_path in dbs:\n"
            "    name = os.path.basename(db_path)\n"
            "    try:\n"
            "        c = sqlite3.connect(db_path)\n"
            "        result = c.execute('PRAGMA integrity_check').fetchone()\n"
            "        size = os.path.getsize(db_path)\n"
            "        print(f'{name}: {result[0]} ({size/1024:.0f}KB)')\n"
            "        c.close()\n"
            "    except Exception as e:\n"
            "        print(f'{name}: ERROR - {e}')\n"
        ),

        "memory_check": (
            "import os\n"
            "# Read from /proc/meminfo (Linux)\n"
            "try:\n"
            "    with open('/proc/meminfo') as f:\n"
            "        info = {}\n"
            "        for line in f:\n"
            "            parts = line.split(':')\n"
            "            if len(parts) == 2:\n"
            "                key = parts[0].strip()\n"
            "                val = parts[1].strip().split()[0]\n"
            "                info[key] = int(val)\n"
            "    total = info.get('MemTotal', 0) / 1024\n"
            "    free = info.get('MemAvailable', 0) / 1024\n"
            "    print(f'Memory: {total:.0f}MB total, {free:.0f}MB available')\n"
            "    print(f'Usage: {(1 - free/total) * 100:.1f}%')\n"
            "except Exception as e:\n"
            "    print(f'Cannot read meminfo: {e}')\n"
        ),

        "import_check": (
            "import importlib.util\n"
            "modules = ['openai', 'yaml', 'rich', 'aiohttp', 'requests',\n"
            "           'beautifulsoup4', 'tiktoken', 'sqlite3', 'json']\n"
            "missing = []\n"
            "for m in modules:\n"
            "    spec = importlib.util.find_spec(m.replace('-', '_'))\n"
            "    status = 'OK' if spec else 'MISSING'\n"
            "    if not spec: missing.append(m)\n"
            "    print(f'  {m}: {status}')\n"
            "print(f'\\nResult: {len(missing)} missing' if missing else '\\nAll imports OK')\n"
        ),

        "process_check": (
            "import os, subprocess\n"
            "# Check running processes\n"
            "result = subprocess.run(['ps', 'aux'], capture_output=True, text=True, timeout=5)\n"
            "lines = result.stdout.splitlines()\n"
            "python_procs = [l for l in lines if 'python' in l.lower()]\n"
            "print(f'Python processes: {len(python_procs)}')\n"
            "for p in python_procs:\n"
            "    print(f'  {p[:120]}')\n"
        ),
    }

    # Modules allowed for auto pip-install
    SAFE_MODULES = frozenset({
        "requests", "beautifulsoup4", "lxml", "html2text",
        "tiktoken", "psutil", "pyyaml", "chardet",
        "trafilatura", "feedparser", "readability-lxml",
    })

    def __init__(self):
        SANDBOX_DIR.mkdir(parents=True, exist_ok=True)
        UNBLOCK_LOG.parent.mkdir(parents=True, exist_ok=True)

    # ── Public API ─────────────────────────────────────────

    def diagnose(self, error_type: str, error_msg: str) -> Tuple[str, str]:
        """Diagnose a problem, return (diagnosis_output, suggestion).

        First tries known fixes, then generates ad-hoc diagnostic.
        """
        # Try known fixes first
        for key, script in self.KNOWN_FIXES.items():
            if key in error_type.lower() or key in error_msg.lower():
                ok, output = self._safe_exec(script)
                self._log("diagnose", error_type, ok, output)
                return output, f"Known diagnostic: {key}"

        # Auto-diagnostic for unknown errors
        diag_script = self._generate_diagnostic(error_type, error_msg)
        ok, output = self._safe_exec(diag_script)
        self._log("diagnose", error_type, ok, output)
        return output, "Auto-diagnostic complete" if ok else f"Diagnostic failed: {output}"

    def attempt_fix(self, error_type: str, error_msg: str) -> Tuple[bool, str]:
        """Attempt automatic repair.

        Safe repairs only:
        - Clean temp files (disk full)
        - pip install missing module (whitelisted)
        - Rebuild DB index (corruption)
        - Reset connections (network)
        """
        error_lower = error_msg.lower()

        # Disk full → clean temp files
        if "disk" in error_lower or "no space" in error_lower:
            ok, output = self._safe_exec(self.KNOWN_FIXES["disk_full"])
            self._log("fix", "disk_full", ok, output)
            return ok, output

        # Missing module → pip install (whitelisted only)
        if "ModuleNotFoundError" in error_msg or "ImportError" in error_msg:
            module = self._extract_module_name(error_msg)
            if module and module in self.SAFE_MODULES:
                ok, output = self._safe_exec(
                    f"import subprocess\n"
                    f"r = subprocess.run(\n"
                    f"    ['pip', 'install', '--break-system-packages', '{module}'],\n"
                    f"    capture_output=True, text=True, timeout=120\n"
                    f")\n"
                    f"print(r.stdout[-200:] if r.returncode == 0 else r.stderr[-200:])\n"
                )
                self._log("fix", f"pip_install_{module}", ok, output)
                return ok, output
            elif module:
                return False, f"Module '{module}' not in whitelist — manual install required"

        # DB corruption → reindex
        if "database" in error_lower and ("corrupt" in error_lower or "malformed" in error_lower):
            ok, output = self._safe_exec(
                "import sqlite3, glob\n"
                "for db_path in glob.glob('/data/neomind/db/*.db'):\n"
                "    try:\n"
                "        c = sqlite3.connect(db_path)\n"
                "        c.execute('REINDEX')\n"
                "        c.execute('PRAGMA integrity_check')\n"
                "        result = c.fetchone()\n"
                "        c.close()\n"
                "        print(f'{db_path}: {result[0]}')\n"
                "    except Exception as e:\n"
                "        print(f'{db_path}: FAILED - {e}')\n"
            )
            self._log("fix", "db_reindex", ok, output)
            return ok, output

        # SQLite locked → close connections
        if "database is locked" in error_lower:
            ok, output = self._safe_exec(
                "import sqlite3\n"
                "# Set WAL mode for better concurrency\n"
                "import glob\n"
                "for db_path in glob.glob('/data/neomind/db/*.db'):\n"
                "    try:\n"
                "        c = sqlite3.connect(db_path)\n"
                "        c.execute('PRAGMA journal_mode=WAL')\n"
                "        c.execute('PRAGMA busy_timeout=5000')\n"
                "        c.close()\n"
                "        print(f'{db_path}: WAL mode set')\n"
                "    except Exception as e:\n"
                "        print(f'{db_path}: {e}')\n"
            )
            self._log("fix", "db_locked", ok, output)
            return ok, output

        self._log("fix", error_type, False, "No automatic fix available")
        return False, "No automatic fix available for this error type"

    def run_diagnostic_suite(self) -> Dict[str, str]:
        """Run all known diagnostics and return results."""
        results = {}
        for name, script in self.KNOWN_FIXES.items():
            ok, output = self._safe_exec(script)
            results[name] = output if ok else f"FAILED: {output}"
        return results

    def write_adhoc_script(self, task_description: str,
                           llm_func) -> Tuple[bool, str]:
        """Use LLM to generate and execute an adhoc diagnostic script.

        Args:
            task_description: What the script should do
            llm_func: Callable that takes a prompt string, returns code string

        Safety:
        - Max 50 lines
        - No file writes, no network requests, no /app modifications
        - 30s timeout
        """
        prompt = (
            f"Write a Python diagnostic script to: {task_description}\n\n"
            f"Requirements:\n"
            f"- Maximum 50 lines\n"
            f"- Only use standard library modules\n"
            f"- Do NOT modify any files\n"
            f"- Do NOT send network requests\n"
            f"- Print diagnostic results to stdout\n"
            f"- Handle exceptions gracefully\n"
            f"\n"
            f"Output ONLY the Python code, no markdown or explanation."
        )

        try:
            script = llm_func(prompt)
        except Exception as e:
            return False, f"LLM generation failed: {e}"

        # Strip markdown code fences if present
        script = re.sub(r'^```python\s*\n', '', script)
        script = re.sub(r'\n```\s*$', '', script)

        # Safety checks
        lines = script.strip().split('\n')
        if len(lines) > self.MAX_SCRIPT_LINES:
            return False, f"Script too long ({len(lines)} lines, max {self.MAX_SCRIPT_LINES})"

        dangerous = ["os.remove", "shutil.rmtree", "open(", ".write(",
                      "requests.", "urllib.request.urlopen",
                      "subprocess.run", "subprocess.call",
                      "exec(", "eval("]
        for d in dangerous:
            if d in script:
                return False, f"Script contains forbidden operation: {d}"

        ok, output = self._safe_exec(script)
        self._log("adhoc", task_description[:100], ok, output)
        return ok, output

    # ── Internal ───────────────────────────────────────────

    def _safe_exec(self, script: str) -> Tuple[bool, str]:
        """Execute script in sandbox with timeout."""
        script_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode='w', suffix='.py', dir=str(SANDBOX_DIR),
                delete=False, prefix='diag_'
            ) as f:
                f.write(script)
                f.flush()
                script_path = f.name

            result = subprocess.run(
                ["python", script_path],
                capture_output=True, text=True,
                timeout=self.TIMEOUT,
                cwd=str(SANDBOX_DIR),
                env={**os.environ, "PYTHONPATH": "/app"},
            )

            if result.returncode == 0:
                return True, result.stdout[-1000:].strip()
            else:
                output = (result.stderr or result.stdout)[-1000:].strip()
                return False, output

        except subprocess.TimeoutExpired:
            return False, f"Script timed out ({self.TIMEOUT}s)"
        except Exception as e:
            return False, f"Execution error: {e}"
        finally:
            if script_path:
                try:
                    os.unlink(script_path)
                except Exception:
                    pass

    def _generate_diagnostic(self, error_type: str, error_msg: str) -> str:
        """Generate a basic diagnostic script for unknown errors."""
        return (
            "import sys, os, platform\n"
            "print('=== NeoMind Diagnostic ===')\n"
            f"print('Error type: {error_type}')\n"
            f"print('Error msg: {error_msg[:200]}')\n"
            "print()\n"
            "print(f'Python: {sys.version}')\n"
            "print(f'Platform: {platform.platform()}')\n"
            "print(f'PID: {os.getpid()}')\n"
            "print(f'CWD: {os.getcwd()}')\n"
            "print()\n"
            "# Check disk\n"
            "import shutil\n"
            "for path in ['/', '/data', '/tmp']:\n"
            "    try:\n"
            "        u = shutil.disk_usage(path)\n"
            "        print(f'Disk {path}: {u.free/1e9:.1f}GB free / {u.total/1e9:.1f}GB')\n"
            "    except: pass\n"
            "print()\n"
            "# Check data dir\n"
            "data = '/data/neomind'\n"
            "if os.path.isdir(data):\n"
            "    items = os.listdir(data)\n"
            "    print(f'Data dir: {len(items)} items')\n"
            "    for item in sorted(items)[:10]:\n"
            "        p = os.path.join(data, item)\n"
            "        size = os.path.getsize(p) if os.path.isfile(p) else 0\n"
            "        print(f'  {item} ({size/1024:.0f}KB)' if size else f'  {item}/')\n"
        )

    def _extract_module_name(self, error_msg: str) -> Optional[str]:
        """Extract module name from import error message."""
        m = re.search(r"No module named '(\w+)'", error_msg)
        if m:
            return m.group(1)
        m = re.search(r"cannot import name '(\w+)' from '(\w+)'", error_msg)
        if m:
            return m.group(2)
        return None

    def _log(self, action: str, target: str, success: bool, detail: str):
        """Append to unblock history log."""
        try:
            entry = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "action": action,
                "target": target[:100],
                "success": success,
                "detail": detail[:300],
            }
            with open(UNBLOCK_LOG, "a") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass
