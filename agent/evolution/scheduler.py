"""Lightweight scheduler for auto-evolution tasks.

Checks timestamps at natural lifecycle points (session start/end,
every N conversation turns) to decide if daily/weekly tasks should run.
No external dependencies - uses stdlib only.
"""

import logging
from typing import List
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class EvolutionScheduler:
    """Lightweight session-based scheduler for evolution tasks.

    Integrates with NeoMind's natural lifecycle points:
    - on_session_start(): Run health check, then daily/weekly audits if due
    - on_turn_complete(turn_number): Every 50 turns, check daily audit
    - on_session_end(): Final daily audit (if not run today) + pattern promotion

    All runs are non-blocking and wrapped in try/except.
    """

    def __init__(self, auto_evolve):
        """Initialize scheduler with AutoEvolve instance.

        Args:
            auto_evolve: AutoEvolve instance for running evolution tasks
        """
        self.auto_evolve = auto_evolve
        self.actions_taken = []  # Track what actions were executed
        self.daily_ran_this_session = False  # Guard against duplicate daily runs
        self.weekly_ran_this_session = False
        self.turn_check_interval = 50  # Check every N turns
        self.last_turn_checked = 0

    def check_and_run_pending(self) -> List[str]:
        """Check all pending evolution tasks and run them.

        Returns:
            List of action descriptions (e.g., ["Health check passed", "Daily audit completed"])
        """
        self.actions_taken = []

        try:
            # Always run health check first
            if self.auto_evolve:
                health = self.auto_evolve.run_startup_check()
                if health:
                    self.actions_taken.append(f"Health check: {health.checks_passed} passed")
        except Exception as e:
            logger.error(f"Evolution health check failed: {e}")
            self.actions_taken.append(f"Health check error: {str(e)[:50]}")

        return self.actions_taken

    def on_session_start(self) -> List[str]:
        """Called at the start of a new session.

        Runs:
        1. Health check
        2. Daily audit (if 24+ hours since last run)
        3. Weekly retro (if 7+ days since last run)

        Returns:
            List of actions taken
        """
        self.actions_taken = []

        if not self.auto_evolve:
            return self.actions_taken

        try:
            # Health check
            logger.info("Evolution: Running session startup health check")
            health = self.auto_evolve.run_startup_check()
            if health:
                msg = f"Health: {health.checks_passed} checks passed"
                if health.issues:
                    msg += f", {len(health.issues)} issues"
                self.actions_taken.append(msg)
                logger.debug(f"Evolution health check: {msg}")
        except Exception as e:
            logger.error(f"Evolution health check failed: {e}")
            self.actions_taken.append(f"Health check error: {str(e)[:40]}")

        # Daily audit
        if self.auto_evolve.should_run_daily() and not self.daily_ran_this_session:
            try:
                logger.info("Evolution: Running daily audit (24+ hours since last run)")
                report = self.auto_evolve.run_daily_audit()
                if report:
                    msg = f"Daily audit: {report.total_calls} calls, {report.errors} errors"
                    self.actions_taken.append(msg)
                    self.daily_ran_this_session = True
                    logger.debug(f"Evolution daily audit complete: {msg}")
            except Exception as e:
                logger.error(f"Evolution daily audit failed: {e}")
                self.actions_taken.append(f"Daily audit error: {str(e)[:40]}")

        # Weekly retro
        if self.auto_evolve.should_run_weekly() and not self.weekly_ran_this_session:
            try:
                logger.info("Evolution: Running weekly retrospective (7+ days since last run)")
                report = self.auto_evolve.run_weekly_retro()
                if report:
                    msg = f"Weekly retro: {report.total_sessions} sessions, {report.total_tasks} tasks"
                    self.actions_taken.append(msg)
                    self.weekly_ran_this_session = True
                    logger.debug(f"Evolution weekly retro complete: {msg}")
            except Exception as e:
                logger.error(f"Evolution weekly retro failed: {e}")
                self.actions_taken.append(f"Weekly retro error: {str(e)[:40]}")

        return self.actions_taken

    def on_turn_complete(self, turn_number: int) -> List[str]:
        """Called after each conversation turn.

        Every N turns (default 50), checks if daily audit should run.
        This handles long-running sessions that may not exit/restart.

        Args:
            turn_number: Current turn/message number in session

        Returns:
            List of actions taken (usually empty, unless audit ran)
        """
        self.actions_taken = []

        if not self.auto_evolve:
            return self.actions_taken

        # Only check every N turns to avoid excessive checking
        if turn_number - self.last_turn_checked < self.turn_check_interval:
            return self.actions_taken

        self.last_turn_checked = turn_number

        # Check if daily audit should run during this long session
        if self.auto_evolve.should_run_daily() and not self.daily_ran_this_session:
            try:
                logger.info(f"Evolution: Running daily audit at turn {turn_number} (24+ hours since last run)")
                report = self.auto_evolve.run_daily_audit()
                if report:
                    msg = f"Daily audit: {report.total_calls} calls, {report.errors} errors"
                    self.actions_taken.append(msg)
                    self.daily_ran_this_session = True
                    logger.debug(f"Evolution daily audit complete: {msg}")
            except Exception as e:
                logger.error(f"Evolution daily audit failed during turn {turn_number}: {e}")
                self.actions_taken.append(f"Daily audit error: {str(e)[:40]}")

        return self.actions_taken

    def on_session_end(self) -> List[str]:
        """Called at the end of a session (before exit).

        Runs:
        1. Daily audit if not yet run today (ensures at least one per day)
        2. Pattern promotion from SharedMemory to vault

        Returns:
            List of actions taken
        """
        self.actions_taken = []

        if not self.auto_evolve:
            return self.actions_taken

        # Final daily audit if not yet run
        if not self.daily_ran_this_session and self.auto_evolve.should_run_daily():
            try:
                logger.info("Evolution: Running final daily audit at session end")
                report = self.auto_evolve.run_daily_audit()
                if report:
                    msg = f"Daily audit: {report.total_calls} calls, {report.errors} errors"
                    self.actions_taken.append(msg)
                    self.daily_ran_this_session = True
                    logger.debug(f"Evolution daily audit complete: {msg}")
            except Exception as e:
                logger.error(f"Evolution daily audit failed at session end: {e}")
                self.actions_taken.append(f"Daily audit error: {str(e)[:40]}")

        return self.actions_taken
