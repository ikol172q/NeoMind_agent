"""NeoMind Self-Restart — Supervisor-Based Process Restart

Allows NeoMind to restart its own agent process after code modifications,
without needing Docker socket access or full container rebuild.

Architecture:
    tini (PID 1) → supervisord → neomind-agent (this process)
                                  ↑
                         supervisorctl restart neomind-agent

Flow:
    1. self_edit.py applies code change + git commit
    2. hot_reload() tries importlib.reload (works for simple module changes)
    3. If deeper restart needed → self_restart.request_restart()
    4. Writes restart intent to /data/neomind/restart_intent.json
    5. Calls `supervisorctl restart neomind-agent`
    6. On next boot, agent reads restart_intent.json → notifies user

Requirements:
    - supervisord running (Telegram daemon mode only)
    - Source code volume-mounted (./agent:/app/agent) for persistence
    - /data/neomind is a persistent Docker volume

No external dependencies — stdlib only.
"""

import json
import logging
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

RESTART_INTENT_FILE = Path("/data/neomind/restart_intent.json")
RESTART_LOG_FILE = Path("/data/neomind/restart_log.jsonl")


def is_supervisor_managed() -> bool:
    """Check if we're running under supervisord."""
    # supervisord sets this, or we can check for the socket
    supervisor_sock = Path("/tmp/supervisor.sock")
    return supervisor_sock.exists()


def request_restart(
    reason: str,
    changed_files: Optional[list] = None,
    notify_chat_id: Optional[int] = None,
    delay_seconds: float = 1.0,
) -> Tuple[bool, str]:
    """Request a graceful agent process restart via supervisord.

    This does NOT restart the container — only the agent process.
    supervisord keeps health-monitor, watchdog, and data-collector running.

    Args:
        reason: Why the restart is needed (for audit trail)
        changed_files: List of files that were modified
        notify_chat_id: Telegram chat_id to notify after restart
        delay_seconds: Seconds to wait before restart (allows response to be sent)

    Returns:
        (success, message) — Note: if success=True, this process will die shortly
    """
    if not is_supervisor_managed():
        return False, (
            "Not running under supervisord. "
            "Self-restart only works in Telegram daemon mode. "
            "For CLI mode, just restart manually."
        )

    # Write restart intent so the NEW process knows what happened
    intent = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "reason": reason[:500],
        "changed_files": changed_files or [],
        "notify_chat_id": notify_chat_id,
        "pid": os.getpid(),
    }

    try:
        RESTART_INTENT_FILE.parent.mkdir(parents=True, exist_ok=True)
        RESTART_INTENT_FILE.write_text(json.dumps(intent, ensure_ascii=False, indent=2))
    except Exception as e:
        logger.error(f"Failed to write restart intent: {e}")
        return False, f"Failed to write restart intent: {e}"

    # Append to restart log (audit trail)
    try:
        with open(RESTART_LOG_FILE, "a") as f:
            f.write(json.dumps(intent, ensure_ascii=False) + "\n")
    except Exception:
        pass  # non-critical

    logger.warning(f"[self-restart] Requesting restart in {delay_seconds}s: {reason}")

    # Schedule the actual restart
    # We use a subprocess so the current request can finish responding
    # before the process dies
    try:
        subprocess.Popen(
            ["sh", "-c", f"sleep {delay_seconds} && supervisorctl restart neomind-agent"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True, f"Restart scheduled in {delay_seconds}s: {reason}"
    except Exception as e:
        logger.error(f"Failed to schedule restart: {e}")
        # Clean up intent file since restart won't happen
        RESTART_INTENT_FILE.unlink(missing_ok=True)
        return False, f"Failed to schedule restart: {e}"


def check_restart_intent() -> Optional[dict]:
    """Check if this process was started after a self-restart.

    Called on startup. Returns the restart intent if one exists,
    then cleans up the intent file.

    Returns:
        dict with restart info, or None if normal startup
    """
    if not RESTART_INTENT_FILE.exists():
        return None

    try:
        intent = json.loads(RESTART_INTENT_FILE.read_text())
        # Clean up — one-time read
        RESTART_INTENT_FILE.unlink(missing_ok=True)
        logger.info(f"[self-restart] Post-restart: {intent.get('reason', '?')}")
        return intent
    except Exception as e:
        logger.warning(f"Failed to read restart intent: {e}")
        RESTART_INTENT_FILE.unlink(missing_ok=True)
        return None


def get_restart_history(limit: int = 10) -> list:
    """Get recent restart history from the log."""
    if not RESTART_LOG_FILE.exists():
        return []
    try:
        lines = RESTART_LOG_FILE.read_text().splitlines()
        entries = []
        for line in lines[-limit:]:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return entries
    except Exception:
        return []


def needs_full_restart(changed_file: str) -> bool:
    """Determine if a code change requires a full process restart
    or if hot-reload is sufficient.

    Files that need full restart:
    - telegram_bot.py (event loop, handlers registered at startup)
    - __init__.py files (import chain)
    - core.py, main.py (entrypoint)
    - config files (loaded once at startup)

    Files that can hot-reload:
    - evolution/* modules (lazy-loaded singletons)
    - config/*.yaml (re-read on access in some modes)
    - Most utility modules
    """
    # Patterns that need full restart
    restart_patterns = [
        "telegram_bot.py",
        "__init__.py",
        "core.py",
        "main.py",
        "agent_config.py",
        "docker-entrypoint.sh",
        "supervisord.conf",
        # Handler registration files
        "code_commands.py",
        "shared_commands.py",
        "finance_commands.py",
    ]

    basename = os.path.basename(changed_file)
    if basename in restart_patterns:
        return True

    # Config files loaded at startup
    if changed_file.endswith((".yaml", ".yml")):
        return True

    return False
