"""NeoMind Health Monitor — Independent Process

Runs alongside the main NeoMind agent as a separate supervisord program.

Features:
1. Heartbeat detection: Main process writes heartbeat every 30s, monitor detects timeout
2. Crash analysis: Reads agent.log tail to find errors after crash
3. Boot loop detection: 3 restarts in 5 minutes → safe mode
4. Telegram alerting: Notifies user on critical issues
5. HTTP health endpoint: Docker HEALTHCHECK on port 18791

No external dependencies — stdlib only.
"""

import os
import sys
import time
import json
import signal
import logging
import sqlite3
from pathlib import Path
from datetime import datetime, timezone, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
from typing import Optional, Dict, Any

logger = logging.getLogger("health-monitor")

# ── Configuration ──────────────────────────────────────────
HEARTBEAT_FILE = Path("/data/neomind/heartbeat")
CRASH_LOG_DIR = Path("/data/neomind/crash_log")
STATE_FILE = Path("/data/neomind/health_state.json")
AGENT_LOG = Path("/data/neomind/agent.log")

HEARTBEAT_TIMEOUT = 90       # seconds: no heartbeat for 90s → hung
HEARTBEAT_CHECK_INTERVAL = 30  # check every 30s
BOOT_LOOP_WINDOW = 300       # 5-minute window
BOOT_LOOP_THRESHOLD = 3      # 3 restarts in window → boot loop
HEALTH_PORT = 18791          # HTTP health endpoint port

# SQLite databases to monitor
SQLITE_DATABASES = {
    "learnings": Path("/data/neomind/db/learnings.db"),
    "cost_tracking": Path("/data/neomind/db/cost_tracking.db"),
    "market_data": Path("/data/neomind/db/market_data.db"),
    "news_data": Path("/data/neomind/db/news_data.db"),
    "briefings": Path("/data/neomind/db/briefings.db"),
}

SQLITE_HEALTH_CHECK_INTERVAL = 480  # 480 * 30s = 4 hours
WAL_CHECKPOINT_THRESHOLD = 10 * 1024 * 1024  # 10MB WAL size threshold

# ── Health State Persistence ──────────────────────────────


class HealthState:
    """Persistent health state — survives restarts via JSON file."""

    def __init__(self):
        self.restart_times: list = []
        self.safe_mode: bool = False
        self.last_crash_reason: Optional[str] = None
        self.total_restarts: int = 0
        self.last_healthy_ts: Optional[str] = None
        self.alerts_sent: int = 0
        self.load()

    def load(self):
        if STATE_FILE.exists():
            try:
                data = json.loads(STATE_FILE.read_text())
                self.restart_times = data.get("restart_times", [])
                self.safe_mode = data.get("safe_mode", False)
                self.last_crash_reason = data.get("last_crash_reason")
                self.total_restarts = data.get("total_restarts", 0)
                self.last_healthy_ts = data.get("last_healthy_ts")
                self.alerts_sent = data.get("alerts_sent", 0)
            except Exception as e:
                logger.warning(f"Failed to load health state: {e}")

    def save(self):
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_FILE.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps({
                "restart_times": self.restart_times[-20:],
                "safe_mode": self.safe_mode,
                "last_crash_reason": self.last_crash_reason,
                "total_restarts": self.total_restarts,
                "last_healthy_ts": self.last_healthy_ts,
                "alerts_sent": self.alerts_sent,
            }, ensure_ascii=False, indent=2))
            tmp.replace(STATE_FILE)  # atomic
        except Exception as e:
            logger.error(f"Failed to save health state: {e}")

    def record_restart(self):
        now = datetime.now(timezone.utc).isoformat()
        self.restart_times.append(now)
        self.total_restarts += 1
        self.save()

    def record_healthy(self):
        self.last_healthy_ts = datetime.now(timezone.utc).isoformat()
        self.save()

    def is_boot_loop(self) -> bool:
        """3 restarts within 5 minutes = boot loop."""
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=BOOT_LOOP_WINDOW)).isoformat()
        recent = [t for t in self.restart_times if t > cutoff]
        return len(recent) >= BOOT_LOOP_THRESHOLD

    def clear_safe_mode(self):
        """Manually exit safe mode (via /evolve safe-mode off)."""
        self.safe_mode = False
        self.restart_times = []
        self.save()

    def get_status_dict(self) -> Dict[str, Any]:
        """Return status for HTTP endpoint and dashboard."""
        return {
            "safe_mode": self.safe_mode,
            "total_restarts": self.total_restarts,
            "last_crash_reason": self.last_crash_reason,
            "last_healthy_ts": self.last_healthy_ts,
            "alerts_sent": self.alerts_sent,
            "recent_restarts": len([
                t for t in self.restart_times
                if t > (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
            ]),
        }


# ── HTTP Health Endpoint ──────────────────────────────────


class HealthHandler(BaseHTTPRequestHandler):
    """HTTP handler for Docker HEALTHCHECK and external monitoring."""

    state: Optional[HealthState] = None

    def do_GET(self):
        if self.path == "/health":
            self._handle_health()
        elif self.path == "/status":
            self._handle_status()
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'{"error":"not_found"}')

    def _handle_health(self):
        """Simple health check — 200 if heartbeat is fresh, 503 otherwise."""
        if HEARTBEAT_FILE.exists():
            try:
                mtime = HEARTBEAT_FILE.stat().st_mtime
                age = time.time() - mtime
                if age < HEARTBEAT_TIMEOUT:
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        "status": "healthy",
                        "heartbeat_age_s": int(age),
                        "safe_mode": self.state.safe_mode if self.state else False,
                    }).encode())
                    return
            except Exception:
                pass

        # Heartbeat missing or stale
        self.send_response(503)
        self.end_headers()
        self.wfile.write(json.dumps({
            "status": "unhealthy",
            "reason": "heartbeat_timeout",
            "safe_mode": self.state.safe_mode if self.state else False,
        }).encode())

    def _handle_status(self):
        """Detailed status endpoint for dashboard."""
        self.send_response(200)
        self.end_headers()
        status = self.state.get_status_dict() if self.state else {}
        self.wfile.write(json.dumps(status, ensure_ascii=False).encode())

    def log_message(self, format, *args):
        pass  # Suppress HTTP access logs


# ── SQLite Health Checks ──────────────────────────────────

def check_sqlite_health(state: Optional[HealthState] = None) -> Dict[str, Any]:
    """Check SQLite database integrity and optimize.

    1. Run PRAGMA integrity_check on all databases
    2. Run PRAGMA optimize on each database
    3. Check WAL file sizes and checkpoint if > 10MB
    4. Report corruption via alert

    Returns: {"healthy": bool, "databases": {db_name: status_dict}, "alerts": []}
    """
    alerts = []
    database_statuses = {}
    all_healthy = True

    for db_name, db_path in SQLITE_DATABASES.items():
        status = {"name": db_name, "healthy": True, "path": str(db_path)}

        # Skip if database doesn't exist yet
        if not db_path.exists():
            status["healthy"] = True
            status["note"] = "database_not_created_yet"
            database_statuses[db_name] = status
            continue

        try:
            conn = sqlite3.connect(str(db_path), timeout=5.0)
            conn.execute("PRAGMA busy_timeout=5000")

            # 1. Run integrity check
            try:
                integrity_result = conn.execute("PRAGMA integrity_check").fetchone()[0]
                if integrity_result != "ok":
                    status["healthy"] = False
                    status["corruption"] = integrity_result
                    all_healthy = False
                    alert_msg = f"SQLite corruption in {db_name}: {integrity_result[:200]}"
                    alerts.append(alert_msg)
                    logger.error(alert_msg)
                else:
                    status["integrity"] = "ok"
            except Exception as e:
                status["integrity_check_error"] = str(e)
                logger.warning(f"Integrity check failed for {db_name}: {e}")

            # 2. Run optimize (should be done every ~4 hours)
            try:
                conn.execute("PRAGMA optimize")
                conn.commit()
                status["optimized"] = True
            except Exception as e:
                status["optimize_error"] = str(e)
                logger.debug(f"PRAGMA optimize failed for {db_name}: {e}")

            # 3. Check WAL file size and checkpoint if needed
            wal_path = db_path.with_suffix(".db-wal")
            if wal_path.exists():
                try:
                    wal_size = wal_path.stat().st_size
                    status["wal_size_mb"] = round(wal_size / 1024 / 1024, 2)

                    if wal_size > WAL_CHECKPOINT_THRESHOLD:
                        # Auto-checkpoint: passive mode (non-blocking)
                        try:
                            conn.execute("PRAGMA wal_autocheckpoint=1000")
                            # Attempt checkpoint
                            conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
                            conn.commit()
                            status["wal_checkpointed"] = True
                            logger.info(f"WAL checkpointed for {db_name} ({wal_size / 1024 / 1024:.1f}MB)")
                        except Exception as cp_err:
                            status["wal_checkpoint_error"] = str(cp_err)
                            logger.warning(f"WAL checkpoint failed for {db_name}: {cp_err}")
                except Exception as e:
                    status["wal_check_error"] = str(e)
                    logger.debug(f"WAL check failed for {db_name}: {e}")
            else:
                status["wal_size_mb"] = 0

            conn.close()
            database_statuses[db_name] = status

        except Exception as e:
            status["healthy"] = False
            status["error"] = str(e)
            all_healthy = False
            alert_msg = f"SQLite health check failed for {db_name}: {str(e)[:200]}"
            alerts.append(alert_msg)
            logger.error(alert_msg)
            database_statuses[db_name] = status

    # Send alert if any databases are unhealthy
    if alerts and state:
        alert_text = "SQLite Health Issues:\n" + "\n".join(alerts[:5])
        send_telegram_alert(alert_text, state)

    return {
        "healthy": all_healthy,
        "databases": database_statuses,
        "alerts": alerts,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


# ── Telegram Alerting ─────────────────────────────────────


def send_telegram_alert(message: str, state: Optional[HealthState] = None):
    """Send alert via Telegram. Uses stdlib only — no external deps."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_ADMIN_CHAT_ID")

    if not token or not chat_id:
        logger.warning("Telegram alerting not configured "
                       "(set TELEGRAM_BOT_TOKEN + TELEGRAM_ADMIN_CHAT_ID)")
        return False

    try:
        import urllib.request
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = json.dumps({
            "chat_id": chat_id,
            "text": f"🤖 NeoMind Alert\n\n{message}",
            "parse_mode": "HTML",
        })
        req = urllib.request.Request(
            url, payload.encode(),
            {"Content-Type": "application/json"}
        )
        urllib.request.urlopen(req, timeout=10)
        if state:
            state.alerts_sent += 1
            state.save()
        logger.info(f"Telegram alert sent: {message[:80]}...")
        return True
    except Exception as e:
        logger.error(f"Telegram alert failed: {e}")
        return False


# ── Crash Analysis ────────────────────────────────────────


def analyze_crash(log_path: Optional[str] = None) -> str:
    """Analyze agent log tail to find crash reason."""
    path = Path(log_path) if log_path else AGENT_LOG
    try:
        if not path.exists():
            return "No agent log found"

        with open(path) as f:
            lines = f.readlines()[-100:]

        # Look for Python tracebacks
        errors = []
        in_traceback = False
        for line in lines:
            if "Traceback" in line:
                in_traceback = True
                errors.append(line.rstrip())
            elif in_traceback:
                errors.append(line.rstrip())
                if not line.startswith(" ") and not line.startswith("\t"):
                    in_traceback = False
            elif any(kw in line for kw in ["ERROR", "FATAL", "Exception", "killed"]):
                errors.append(line.rstrip())

        if errors:
            return "\n".join(errors[-10:])

        # Check for OOM signals
        oom_lines = [l for l in lines if "oom" in l.lower() or "killed" in l.lower()]
        if oom_lines:
            return "\n".join(oom_lines[-3:])

        return "No obvious error found (possible OOM or SIGKILL)"
    except Exception as e:
        return f"Log analysis failed: {e}"


def save_crash_report(reason: str, state: HealthState):
    """Save crash report to crash_log directory."""
    CRASH_LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    report_path = CRASH_LOG_DIR / f"crash_{ts}.txt"
    try:
        report_path.write_text(
            f"Crash Report — {ts}\n"
            f"{'=' * 50}\n"
            f"Safe mode: {state.safe_mode}\n"
            f"Total restarts: {state.total_restarts}\n"
            f"Reason:\n{reason}\n"
        )
        # Keep only last 20 crash reports
        reports = sorted(CRASH_LOG_DIR.glob("crash_*.txt"))
        for old in reports[:-20]:
            old.unlink(missing_ok=True)
    except Exception as e:
        logger.error(f"Failed to save crash report: {e}")


# ── Watchdog Loop ─────────────────────────────────────────


def watchdog_loop(state: HealthState):
    """Main monitoring loop — runs forever, checks heartbeat periodically."""
    state.record_restart()
    logger.info(f"Health monitor started (restart #{state.total_restarts})")

    # Boot loop detection on startup
    if state.is_boot_loop():
        msg = (
            "⚠️ Boot Loop Detected!\n"
            f"Restarted {BOOT_LOOP_THRESHOLD}+ times in {BOOT_LOOP_WINDOW // 60} minutes.\n"
            "Entering SAFE MODE — all evolution features disabled."
        )
        logger.critical(msg)
        state.safe_mode = True
        state.save()

        # Set env var for main process to detect
        os.environ["NEOMIND_SAFE_MODE"] = "1"

        # Analyze and alert
        crash_info = analyze_crash()
        state.last_crash_reason = crash_info[:500]
        state.save()
        save_crash_report(crash_info, state)
        send_telegram_alert(f"{msg}\n\nRecent errors:\n{crash_info[:300]}", state)
    else:
        logger.info("No boot loop detected — normal operation")
        if state.safe_mode:
            # Check if we should auto-exit safe mode (no recent restarts)
            cutoff = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
            recent = [t for t in state.restart_times if t > cutoff]
            if len(recent) <= 1:
                logger.info("Stable for 30+ minutes — auto-exiting safe mode")
                state.clear_safe_mode()
                send_telegram_alert("✅ NeoMind stable — exiting safe mode", state)

    # Continuous monitoring
    consecutive_misses = 0
    check_iteration = 0
    while True:
        time.sleep(HEARTBEAT_CHECK_INTERVAL)
        check_iteration += 1

        # Check SQLite health every 4 hours (every 480 iterations of 30-second checks)
        if check_iteration >= SQLITE_HEALTH_CHECK_INTERVAL:
            check_iteration = 0
            logger.info("Running SQLite health check...")
            sqlite_status = check_sqlite_health(state)
            if not sqlite_status["healthy"]:
                logger.warning(f"SQLite health issues detected: {sqlite_status['alerts']}")
            else:
                logger.info("SQLite databases healthy")

        if not HEARTBEAT_FILE.exists():
            consecutive_misses += 1
            if consecutive_misses == 1:
                logger.info("No heartbeat file yet (agent may be starting up)")
            elif consecutive_misses >= 3:
                logger.warning(f"No heartbeat file after {consecutive_misses} checks")
            continue

        try:
            age = time.time() - HEARTBEAT_FILE.stat().st_mtime
        except Exception:
            continue

        if age < HEARTBEAT_TIMEOUT:
            # Healthy
            if consecutive_misses > 3:
                logger.info("Heartbeat recovered")
                send_telegram_alert("✅ NeoMind heartbeat recovered", state)
            consecutive_misses = 0
            state.record_healthy()
        else:
            consecutive_misses += 1
            if consecutive_misses == 3:
                # First real alarm — 3 consecutive misses
                msg = (
                    f"⚠️ Agent unresponsive!\n"
                    f"Heartbeat stale for {int(age)}s (limit: {HEARTBEAT_TIMEOUT}s)\n"
                    f"Consecutive misses: {consecutive_misses}"
                )
                logger.warning(msg)

                crash_info = analyze_crash()
                state.last_crash_reason = crash_info[:500]
                state.save()
                save_crash_report(crash_info, state)
                send_telegram_alert(f"{msg}\n\nRecent log:\n{crash_info[:300]}", state)

                # Try self-diagnosis
                try:
                    from agent.evolution.self_unblock import SelfUnblocker
                    unblocker = SelfUnblocker()
                    diag_result, suggestion = unblocker.diagnose("hang", "Agent main process unresponsive")
                    if diag_result:
                        send_telegram_alert(f"Auto-diagnosis:\n{diag_result[:300]}", state)
                except Exception as diag_err:
                    logger.error(f"Self-diagnosis failed: {diag_err}")

            elif consecutive_misses % 10 == 0:
                # Periodic reminders every 5 minutes
                msg = f"⚠️ Agent still unresponsive ({int(age)}s without heartbeat)"
                logger.warning(msg)
                send_telegram_alert(msg, state)


# ── Heartbeat Writer (for main process to import) ─────────


class HeartbeatWriter:
    """Daemon thread that writes heartbeat file every 30s.

    Usage in main process:
        from agent.evolution.health_monitor import HeartbeatWriter
        heartbeat = HeartbeatWriter()
        heartbeat.start()
    """

    def __init__(self, interval: int = 30):
        self.interval = interval
        self.heartbeat_path = HEARTBEAT_FILE
        self._thread: Optional[threading.Thread] = None
        self._running = False

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="heartbeat")
        self._thread.start()
        logger.info(f"Heartbeat writer started (interval={self.interval}s)")

    def stop(self):
        self._running = False

    def _loop(self):
        while self._running:
            try:
                self.heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
                self.heartbeat_path.write_text(
                    json.dumps({
                        "ts": time.time(),
                        "iso": datetime.now(timezone.utc).isoformat(),
                        "pid": os.getpid(),
                    })
                )
            except Exception as e:
                logger.debug(f"Heartbeat write failed: {e}")
            time.sleep(self.interval)

    def beat(self):
        """Manual heartbeat — call during long operations to prevent timeout."""
        try:
            self.heartbeat_path.write_text(
                json.dumps({
                    "ts": time.time(),
                    "iso": datetime.now(timezone.utc).isoformat(),
                    "pid": os.getpid(),
                })
            )
        except Exception:
            pass


# ── Main ──────────────────────────────────────────────────


def main():
    """Entry point when run as independent process by supervisord."""
    CRASH_LOG_DIR.mkdir(parents=True, exist_ok=True)
    state = HealthState()

    # Start HTTP health endpoint in background thread
    HealthHandler.state = state
    try:
        server = HTTPServer(("0.0.0.0", HEALTH_PORT), HealthHandler)
        http_thread = threading.Thread(target=server.serve_forever, daemon=True)
        http_thread.start()
        logger.info(f"Health endpoint listening on http://0.0.0.0:{HEALTH_PORT}/health")
    except OSError as e:
        logger.error(f"Failed to start health endpoint on port {HEALTH_PORT}: {e}")
        # Continue without HTTP endpoint — watchdog still works

    # Handle graceful shutdown
    def shutdown(signum, frame):
        logger.info("Health monitor shutting down")
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    # Run watchdog loop (blocks forever)
    watchdog_loop(state)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [health-monitor] %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    main()
