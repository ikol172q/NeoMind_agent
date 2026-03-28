"""Comprehensive tests for agent/evolution/scheduler.py — EvolutionScheduler."""

import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from agent.evolution.scheduler import EvolutionScheduler


@pytest.fixture
def mock_evolve():
    """Create a mock AutoEvolve instance."""
    evolve = MagicMock()
    evolve.should_run_daily.return_value = False
    evolve.should_run_weekly.return_value = False
    evolve.run_startup_check.return_value = MagicMock(checks_passed=5, issues=[])
    evolve.run_daily_audit.return_value = MagicMock(total_calls=100, errors=2)
    evolve.run_weekly_retro.return_value = MagicMock(total_sessions=7, total_tasks=35)
    return evolve


@pytest.fixture
def scheduler(mock_evolve):
    return EvolutionScheduler(mock_evolve)


class TestSchedulerInit:
    """Initialization tests."""

    def test_init_stores_evolve(self, scheduler, mock_evolve):
        assert scheduler.auto_evolve is mock_evolve

    def test_init_default_values(self, scheduler):
        assert scheduler.daily_ran_this_session is False
        assert scheduler.weekly_ran_this_session is False
        assert scheduler.turn_check_interval == 50
        assert scheduler.last_turn_checked == 0
        assert scheduler.actions_taken == []


class TestCheckAndRunPending:
    """Tests for check_and_run_pending()."""

    def test_runs_health_check(self, scheduler, mock_evolve):
        actions = scheduler.check_and_run_pending()
        mock_evolve.run_startup_check.assert_called_once()
        assert any("Health check" in a for a in actions)

    def test_returns_actions(self, scheduler):
        actions = scheduler.check_and_run_pending()
        assert isinstance(actions, list)
        assert len(actions) >= 1

    def test_health_check_failure(self, scheduler, mock_evolve):
        mock_evolve.run_startup_check.side_effect = Exception("DB error")
        actions = scheduler.check_and_run_pending()
        assert any("error" in a.lower() for a in actions)

    def test_no_evolve_instance(self):
        s = EvolutionScheduler(None)
        actions = s.check_and_run_pending()
        assert actions == []


class TestOnSessionStart:
    """Tests for on_session_start()."""

    def test_runs_health_check(self, scheduler, mock_evolve):
        actions = scheduler.on_session_start()
        mock_evolve.run_startup_check.assert_called_once()
        assert any("Health" in a for a in actions)

    def test_runs_daily_when_due(self, scheduler, mock_evolve):
        mock_evolve.should_run_daily.return_value = True
        actions = scheduler.on_session_start()
        mock_evolve.run_daily_audit.assert_called_once()
        assert scheduler.daily_ran_this_session is True
        assert any("Daily audit" in a for a in actions)

    def test_skips_daily_when_not_due(self, scheduler, mock_evolve):
        mock_evolve.should_run_daily.return_value = False
        scheduler.on_session_start()
        mock_evolve.run_daily_audit.assert_not_called()
        assert scheduler.daily_ran_this_session is False

    def test_runs_weekly_when_due(self, scheduler, mock_evolve):
        mock_evolve.should_run_weekly.return_value = True
        actions = scheduler.on_session_start()
        mock_evolve.run_weekly_retro.assert_called_once()
        assert scheduler.weekly_ran_this_session is True

    def test_skips_weekly_when_not_due(self, scheduler, mock_evolve):
        mock_evolve.should_run_weekly.return_value = False
        scheduler.on_session_start()
        mock_evolve.run_weekly_retro.assert_not_called()

    def test_daily_guard_prevents_duplicate(self, scheduler, mock_evolve):
        mock_evolve.should_run_daily.return_value = True
        scheduler.daily_ran_this_session = True
        scheduler.on_session_start()
        mock_evolve.run_daily_audit.assert_not_called()

    def test_weekly_guard_prevents_duplicate(self, scheduler, mock_evolve):
        mock_evolve.should_run_weekly.return_value = True
        scheduler.weekly_ran_this_session = True
        scheduler.on_session_start()
        mock_evolve.run_weekly_retro.assert_not_called()

    def test_health_check_error(self, scheduler, mock_evolve):
        mock_evolve.run_startup_check.side_effect = Exception("fail")
        actions = scheduler.on_session_start()
        assert any("error" in a.lower() for a in actions)

    def test_daily_audit_error(self, scheduler, mock_evolve):
        mock_evolve.should_run_daily.return_value = True
        mock_evolve.run_daily_audit.side_effect = Exception("db fail")
        actions = scheduler.on_session_start()
        assert any("error" in a.lower() for a in actions)

    def test_weekly_retro_error(self, scheduler, mock_evolve):
        mock_evolve.should_run_weekly.return_value = True
        mock_evolve.run_weekly_retro.side_effect = Exception("retro fail")
        actions = scheduler.on_session_start()
        assert any("error" in a.lower() for a in actions)

    def test_no_evolve_returns_empty(self):
        s = EvolutionScheduler(None)
        assert s.on_session_start() == []


class TestOnTurnComplete:
    """Tests for on_turn_complete()."""

    def test_skips_before_interval(self, scheduler):
        actions = scheduler.on_turn_complete(10)
        assert actions == []

    def test_checks_at_interval(self, scheduler, mock_evolve):
        mock_evolve.should_run_daily.return_value = True
        actions = scheduler.on_turn_complete(50)
        mock_evolve.should_run_daily.assert_called()
        assert scheduler.last_turn_checked == 50

    def test_runs_daily_at_interval(self, scheduler, mock_evolve):
        mock_evolve.should_run_daily.return_value = True
        actions = scheduler.on_turn_complete(50)
        mock_evolve.run_daily_audit.assert_called_once()
        assert scheduler.daily_ran_this_session is True

    def test_skips_daily_if_already_ran(self, scheduler, mock_evolve):
        mock_evolve.should_run_daily.return_value = True
        scheduler.daily_ran_this_session = True
        actions = scheduler.on_turn_complete(50)
        mock_evolve.run_daily_audit.assert_not_called()

    def test_multiple_intervals(self, scheduler, mock_evolve):
        mock_evolve.should_run_daily.return_value = False
        scheduler.on_turn_complete(50)
        scheduler.on_turn_complete(60)  # within interval, skip
        assert scheduler.last_turn_checked == 50
        scheduler.on_turn_complete(100)  # next interval
        assert scheduler.last_turn_checked == 100

    def test_no_evolve_returns_empty(self):
        s = EvolutionScheduler(None)
        assert s.on_turn_complete(50) == []

    def test_daily_audit_error(self, scheduler, mock_evolve):
        mock_evolve.should_run_daily.return_value = True
        mock_evolve.run_daily_audit.side_effect = Exception("err")
        actions = scheduler.on_turn_complete(50)
        assert any("error" in a.lower() for a in actions)


class TestOnSessionEnd:
    """Tests for on_session_end()."""

    def test_runs_daily_if_not_yet_run(self, scheduler, mock_evolve):
        mock_evolve.should_run_daily.return_value = True
        actions = scheduler.on_session_end()
        mock_evolve.run_daily_audit.assert_called_once()
        assert scheduler.daily_ran_this_session is True

    def test_skips_daily_if_already_ran(self, scheduler, mock_evolve):
        scheduler.daily_ran_this_session = True
        mock_evolve.should_run_daily.return_value = True
        actions = scheduler.on_session_end()
        mock_evolve.run_daily_audit.assert_not_called()

    def test_skips_daily_if_not_due(self, scheduler, mock_evolve):
        mock_evolve.should_run_daily.return_value = False
        actions = scheduler.on_session_end()
        mock_evolve.run_daily_audit.assert_not_called()

    def test_no_evolve_returns_empty(self):
        s = EvolutionScheduler(None)
        assert s.on_session_end() == []

    def test_daily_error_handled(self, scheduler, mock_evolve):
        mock_evolve.should_run_daily.return_value = True
        mock_evolve.run_daily_audit.side_effect = Exception("err")
        actions = scheduler.on_session_end()
        assert any("error" in a.lower() for a in actions)


class TestSchedulerLifecycle:
    """Integration tests simulating a full session lifecycle."""

    def test_full_session_flow(self, mock_evolve):
        mock_evolve.should_run_daily.return_value = True
        mock_evolve.should_run_weekly.return_value = True
        s = EvolutionScheduler(mock_evolve)

        # Start
        start_actions = s.on_session_start()
        assert s.daily_ran_this_session is True
        assert s.weekly_ran_this_session is True

        # Turns — daily already ran, should not re-run
        turn_actions = s.on_turn_complete(50)
        assert len(turn_actions) == 0

        # End — daily already ran
        end_actions = s.on_session_end()
        assert mock_evolve.run_daily_audit.call_count == 1  # Only once

    def test_long_session_daily_at_turn(self, mock_evolve):
        """Daily audit runs at turn 50 if not run at session start."""
        mock_evolve.should_run_daily.return_value = False
        s = EvolutionScheduler(mock_evolve)
        s.on_session_start()
        assert s.daily_ran_this_session is False

        # Now daily becomes due during the session
        mock_evolve.should_run_daily.return_value = True
        actions = s.on_turn_complete(50)
        assert s.daily_ran_this_session is True
        mock_evolve.run_daily_audit.assert_called_once()
