"""NeoMind Watchdog — Lightweight Heartbeat Monitor

A minimal watchdog process that:
1. Monitors the main agent's heartbeat file
2. Detects hangs (heartbeat stale > 90s)
3. Attempts to restart via supervisorctl
4. Sends Telegram alerts on failures

This is intentionally simpler than health_monitor.py — it's the last
line of defense. If health_monitor dies, watchdog still detects hangs.

Runs as a separate supervisord program with autorestart.
No external dependencies — stdlib only.
"""

import os
import sys
import time
import json
import signal
import subprocess
import logging
from pathlib import Path
from datetime import datetime, timezone

logger = logging.getLogger("watchdog")

HEARTBEAT_FILE = Path("/data/neomind/heartbeat")
WATCHDOG_STATE = Path("/data/neomind/watchdog_state.json")
HEARTBEAT_TIMEOUT = 120     # More lenient than health_monitor (120s vs 90s)
CHECK_INTERVAL = 45         # Check every 45s
MAX_RESTARTS = 5            # Max forced restarts before giving up
RESTART_COOLDOWN = 600      # 10 minutes between forced restarts


class WatchdogState:
    """Simple persistent state for watchdog."""

    def __init__(self):
        self.forced_restarts: int = 0
        self.last_forced_restart: float = 0
        self.last_alert: float = 0
        self.load()

    def load(self):
        if WATCHDOG_STATE.exists():
            try:
                data = json.loads(WATCHDOG_STATE.read_text())
                self.forced_restarts = data.get("forced_restarts", 0)
                self.last_forced_restart = data.get("last_forced_restart", 0)
                self.last_alert = data.get("last_alert", 0)
            except Exception:
                pass

    def save(self):
        try:
            WATCHDOG_STATE.parent.mkdir(parents=True, exist_ok=True)
            tmp = WATCHDOG_STATE.with_suffix(".tmp")
            tmp.write_text(json.dumps({
                "forced_restarts": self.forced_restarts,
                "last_forced_restart": self.last_forced_restart,
                "last_alert": self.last_alert,
            }))
            tmp.replace(WATCHDOG_STATE)
        except Exception:
            pass

    def can_restart(self) -> bool:
        """Check if we're allowed to force-restart."""
        if self.forced_restarts >= MAX_RESTARTS:
            return False
        if time.time() - self.last_forced_restart < RESTART_COOLDOWN:
            return False
        return True

    def record_restart(self):
        self.forced_restarts += 1
        self.last_forced_restart = time.time()
        self.save()


def send_alert(message: str, state: WatchdogState):
    """Send Telegram alert (rate-limited to 1 per 5 minutes)."""
    if time.time() - state.last_alert < 300:
        return  # Rate limit

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_ADMIN_CHAT_ID")
    if not token or not chat_id:
        return

    try:
        import urllib.request
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = json.dumps({
            "chat_id": chat_id,
            "text": f"🐕 NeoMind Watchdog\n\n{message}",
        })
        req = urllib.request.Request(
            url, payload.encode(), {"Content-Type": "application/json"}
        )
        urllib.request.urlopen(req, timeout=10)
        state.last_alert = time.time()
        state.save()
    except Exception as e:
        logger.error(f"Alert failed: {e}")


def restart_agent():
    """Attempt to restart the agent via supervisorctl."""
    try:
        result = subprocess.run(
            ["supervisorctl", "restart", "neomind-agent"],
            capture_output=True, text=True, timeout=30
        )
        logger.info(f"Restart result: {result.stdout.strip()}")
        return result.returncode == 0
    except Exception as e:
        logger.error(f"Restart failed: {e}")
        return False


def check_heartbeat() -> float:
    """Return heartbeat age in seconds, or -1 if no heartbeat."""
    if not HEARTBEAT_FILE.exists():
        return -1
    try:
        return time.time() - HEARTBEAT_FILE.stat().st_mtime
    except Exception:
        return -1


def main():
    """Watchdog main loop."""
    state = WatchdogState()
    logger.info(f"Watchdog started (forced_restarts so far: {state.forced_restarts})")

    # Wait for agent to start up
    time.sleep(30)

    consecutive_failures = 0

    def shutdown(signum, frame):
        logger.info("Watchdog shutting down")
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    while True:
        time.sleep(CHECK_INTERVAL)

        age = check_heartbeat()

        if age == -1:
            # No heartbeat file — agent may not have started yet
            consecutive_failures += 1
            if consecutive_failures > 5:
                logger.warning("No heartbeat file after extended wait")
            continue

        if age < HEARTBEAT_TIMEOUT:
            # Healthy
            if consecutive_failures > 3:
                logger.info("Agent heartbeat recovered")
            consecutive_failures = 0
            continue

        # Heartbeat stale
        consecutive_failures += 1
        logger.warning(f"Heartbeat stale: {age:.0f}s (limit: {HEARTBEAT_TIMEOUT}s)")

        if consecutive_failures >= 3:
            msg = (
                f"Agent unresponsive for {int(age)}s\n"
                f"Consecutive failures: {consecutive_failures}"
            )

            if state.can_restart():
                logger.info("Attempting forced restart...")
                ok = restart_agent()
                if ok:
                    state.record_restart()
                    send_alert(
                        f"{msg}\nForced restart #{state.forced_restarts} initiated.",
                        state
                    )
                    consecutive_failures = 0
                    time.sleep(30)  # Wait for restart
                else:
                    send_alert(f"{msg}\nForced restart FAILED!", state)
            else:
                if state.forced_restarts >= MAX_RESTARTS:
                    send_alert(
                        f"{msg}\nMax restarts ({MAX_RESTARTS}) reached.\n"
                        f"Manual intervention required!",
                        state
                    )
                else:
                    send_alert(
                        f"{msg}\nWaiting for restart cooldown.",
                        state
                    )


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [watchdog] %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    main()
