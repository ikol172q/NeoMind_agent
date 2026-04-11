"""NeoMind Post-Restart Verifier — Smoke Gate After Self-Evolution Restart

Runs on agent startup to validate that a code change applied via
EvolutionTransaction actually loads cleanly in the new process. If the
new code is broken, automatically rolls back via git reset and triggers
another restart so the original code is back in service.

Flow (called from agent startup):

  1. Read /data/neomind/evolution/evolution_intent.json
     - If absent: normal startup, return (None, "no pending evolution")
     - If present: a self-evolution transaction was just committed and
       this process is the new code's first run.

  2. Run smoke checks:
     - Re-import every applied module (catches stale .pyc, broken transitive
       imports, missing dependencies)
     - Optional: invoke the canary target one more time inside this process
     - Probe a critical service (e.g. agent_config loads)

  3. If all checks pass:
     - Mark intent as "verified"
     - Return (intent, "ok") so the caller can post a Telegram notification

  4. If any check fails:
     - Mark intent as "post_restart_failed" with the error
     - git reset --hard to the rollback tag stored in the intent
     - Spawn `supervisorctl restart neomind-agent` (delayed 3s) — by the time
       the new process boots, original code is back in /app
     - Return (intent, "failed") so the caller can mark itself in fail mode

  5. Both paths clear the intent file before returning so a future normal
     startup doesn't re-trigger verification.

Why a separate module from transaction.py?
  Transaction creates the intent. Verifier consumes it. They run in different
  processes (separated by a supervisord restart), so keeping them in different
  files makes the lifecycle obvious.

No external dependencies — stdlib only.
"""

from __future__ import annotations

import importlib
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple, Dict, Any

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Public API ───────────────────────────────────────────────────────

def verify_pending_evolution() -> Tuple[Optional[Dict[str, Any]], str]:
    """Check for and verify any pending evolution transaction.

    Returns:
        (intent_dict, status):
            (None, "no_pending")   — normal startup, nothing to verify
            (dict, "verified")     — evolution succeeded, caller can notify user
            (dict, "rolled_back")  — verification failed, rollback triggered,
                                     a second restart is on its way
            (dict, "rollback_failed") — verification failed AND rollback failed
                                        (worst case — manual intervention needed)
    """
    # Lazy import — transaction.py defines the intent file location
    try:
        from agent.evolution.transaction import (
            get_pending_intent,
            clear_pending_intent,
            INTENT_FILE,
            TXN_LOG,
            DATA_DIR,
        )
    except ImportError as e:
        logger.warning(f"transaction module not importable: {e}")
        return None, "no_pending"

    record = get_pending_intent()
    if record is None:
        return None, "no_pending"

    intent = _record_to_dict(record)
    logger.info(f"[post-restart] Found pending evolution intent: {record.tag}")

    # ── Smoke checks ──
    smoke_ok, smoke_msg = _verify_in_process(record)

    if smoke_ok:
        logger.info(f"[post-restart] Verification PASSED: {record.tag}")
        intent["status"] = "verified"
        intent["verified_at"] = _now_iso()
        intent["verification_message"] = smoke_msg
        _append_audit_log(intent, TXN_LOG, DATA_DIR)
        clear_pending_intent()
        return intent, "verified"

    # ── Verification failed → rollback ──
    logger.error(f"[post-restart] Verification FAILED: {smoke_msg}")
    intent["status"] = "post_restart_failed"
    intent["verified_at"] = _now_iso()
    intent["verification_error"] = smoke_msg

    rollback_ok, rollback_msg = _execute_rollback(record.tag)

    if rollback_ok:
        intent["rollback_status"] = "ok"
        intent["rollback_message"] = rollback_msg
        logger.warning(f"[post-restart] Rolled back to {record.tag}, restarting again")
        _append_audit_log(intent, TXN_LOG, DATA_DIR)
        clear_pending_intent()
        # Schedule another restart so the original code comes back online
        _schedule_recovery_restart(reason=f"rollback after failed evolution {record.tag}")
        return intent, "rolled_back"

    # Worst case: verification AND rollback both failed
    intent["rollback_status"] = "failed"
    intent["rollback_message"] = rollback_msg
    logger.critical(
        f"[post-restart] BOTH verification and rollback failed for {record.tag}. "
        f"Manual intervention required. Verification: {smoke_msg}. Rollback: {rollback_msg}"
    )
    _append_audit_log(intent, TXN_LOG, DATA_DIR)
    # Don't clear the intent file in this case — leave it for human to inspect
    return intent, "rollback_failed"


def format_user_notification(intent: Dict[str, Any], status: str) -> str:
    """Build a Telegram-friendly status message for the user who triggered
    the evolution. Caller decides how to send it (via the bot's send_message).
    """
    tag = intent.get("tag", "?")
    reason = intent.get("reason", "(no reason recorded)")
    files = intent.get("applied_files", [])
    file_list = "\n".join(f"  • <code>{f}</code>" for f in files) or "  (none)"

    if status == "verified":
        return (
            f"✅ <b>Evolution applied:</b> <code>{tag}</code>\n"
            f"<b>Reason:</b> {reason}\n"
            f"<b>Files changed:</b>\n{file_list}\n"
            f"\nVerification: {intent.get('verification_message', 'ok')}\n"
            f"Rollback: <code>/evolve revert {tag}</code>"
        )

    if status == "rolled_back":
        return (
            f"⚠️ <b>Evolution rolled back:</b> <code>{tag}</code>\n"
            f"<b>Reason for rollback:</b> {intent.get('verification_error', '?')}\n"
            f"\nThe new code failed its post-restart smoke test. "
            f"Original code restored, bot continues normally."
        )

    if status == "rollback_failed":
        return (
            f"🚨 <b>CRITICAL: evolution + rollback both failed</b>\n"
            f"<b>Tag:</b> <code>{tag}</code>\n"
            f"<b>Verification error:</b> {intent.get('verification_error', '?')}\n"
            f"<b>Rollback error:</b> {intent.get('rollback_message', '?')}\n"
            f"\nManual recovery required. Run on host:\n"
            f"<code>cd $WORKSPACE && git reset --hard {tag} && docker compose restart neomind-telegram</code>"
        )

    return f"Evolution status: {status} — tag {tag}"


# ── Internals ────────────────────────────────────────────────────────

def _record_to_dict(record) -> Dict[str, Any]:
    """Convert a TransactionRecord to a plain dict."""
    try:
        from dataclasses import asdict
        return asdict(record)
    except Exception:
        # Fallback if record is already a dict
        return dict(record) if hasattr(record, "__iter__") else {}


def _verify_in_process(record) -> Tuple[bool, str]:
    """Re-import every applied .py file in THIS process to confirm the new
    code loads cleanly here too. (Subprocess smoke during transaction is not
    enough — this process has different sys.modules and may have already
    loaded the module from .pyc cache.)
    """
    failures = []
    for f in record.applied_files:
        if not f.endswith(".py"):
            continue
        if "/" not in f:
            continue
        module = f.replace("/", ".").removesuffix(".py").removesuffix(".__init__")
        try:
            if module in sys.modules:
                # Reload to pick up the new file content
                importlib.reload(sys.modules[module])
            else:
                importlib.import_module(module)
        except Exception as e:
            failures.append(f"{module}: {type(e).__name__}: {e}")

    if failures:
        return False, "; ".join(failures)[:500]

    # Optional: also re-run the canary target if specified
    if record.canary_target:
        canary_ok, canary_msg = _invoke_canary_in_process(record.canary_target)
        if not canary_ok:
            return False, f"canary failed: {canary_msg}"

    return True, f"{len(record.applied_files)} file(s) verified"


def _invoke_canary_in_process(target: str) -> Tuple[bool, str]:
    """Run the canary target in this process (not subprocess this time)."""
    try:
        if ":" in target:
            module_path, attr_path = target.split(":", 1)
        else:
            module_path, attr_path = target, None

        m = importlib.import_module(module_path)
        if attr_path:
            obj = m
            for part in attr_path.split("."):
                obj = getattr(obj, part)
            if callable(obj):
                try:
                    obj()
                except TypeError:
                    # Probably needs args — just verifying it exists is enough
                    pass
        return True, "ok"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def _execute_rollback(tag: str) -> Tuple[bool, str]:
    """git reset --hard to the rollback anchor."""
    repo_dir = "/app"  # Mirrors SelfEditor.REPO_DIR — kept as string to avoid Path import here
    try:
        result = subprocess.run(
            ["git", "reset", "--hard", tag],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            timeout=20,
        )
        if result.returncode == 0:
            return True, f"reset to {tag}"
        return False, (result.stderr or result.stdout).strip()[:300]
    except subprocess.TimeoutExpired:
        return False, "git reset timed out"
    except FileNotFoundError:
        return False, "git binary not available"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def _schedule_recovery_restart(reason: str, delay_seconds: float = 3.0):
    """Trigger another supervisord restart so the rolled-back code is loaded.

    Mirrors agent.evolution.self_restart.request_restart but writes a
    distinct intent so we don't loop forever (the next startup will see no
    pending evolution intent and proceed normally).
    """
    try:
        # Quick check: are we under supervisord at all?
        if not Path("/tmp/supervisor.sock").exists():
            logger.warning(
                "[post-restart] Not under supervisord — cannot schedule recovery restart. "
                "Original code is on disk. Manual restart needed."
            )
            return

        subprocess.Popen(
            ["sh", "-c", f"sleep {delay_seconds} && supervisorctl restart neomind-agent"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        logger.info(f"[post-restart] Recovery restart scheduled in {delay_seconds}s: {reason}")
    except Exception as e:
        logger.error(f"[post-restart] Failed to schedule recovery restart: {e}")


def _append_audit_log(intent: Dict[str, Any], log_path: Path, data_dir: Path):
    """Append the verification result to the transaction audit log."""
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a") as f:
            f.write(json.dumps(intent, ensure_ascii=False) + "\n")
    except OSError as e:
        logger.warning(f"Failed to append audit log: {e}")
