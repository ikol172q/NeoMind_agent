"""Tests for agent/finance/risk_manager.py — CircuitBreaker + Kelly fractional."""

from __future__ import annotations

import threading
import time

import pytest

from agent.finance.risk_manager import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerState,
    RiskLevel,
    RiskLimits,
    RiskManager,
)
from agent.finance.paper_trading import OrderSide


# ── CircuitBreaker state machine ────────────────────────────────────────

def _fast_cb(failure_threshold=3, cooldown=0.05, success_threshold=2):
    """Build a CB with fast timings suitable for unit tests."""
    return CircuitBreaker(
        name="test",
        config=CircuitBreakerConfig(
            failure_threshold=failure_threshold,
            cooldown_seconds=cooldown,
            success_threshold=success_threshold,
        ),
    )


def test_initial_state_closed():
    cb = _fast_cb()
    assert cb.state == CircuitBreakerState.CLOSED
    assert cb.allow() is True


def test_failures_below_threshold_stay_closed():
    cb = _fast_cb(failure_threshold=3)
    cb.record_failure()
    cb.record_failure()
    assert cb.state == CircuitBreakerState.CLOSED
    assert cb.allow() is True


def test_failures_at_threshold_trip_to_open():
    cb = _fast_cb(failure_threshold=3)
    for _ in range(3):
        cb.record_failure()
    assert cb.state == CircuitBreakerState.OPEN
    assert cb.allow() is False


def test_success_while_closed_resets_consecutive_failures():
    cb = _fast_cb(failure_threshold=3)
    cb.record_failure()
    cb.record_failure()
    cb.record_success()
    cb.record_failure()
    cb.record_failure()
    # Should still be CLOSED — the 3rd failure was reset by the success
    assert cb.state == CircuitBreakerState.CLOSED


def test_cooldown_transitions_open_to_half_open():
    cb = _fast_cb(failure_threshold=2, cooldown=0.05)
    cb.record_failure()
    cb.record_failure()
    assert cb.state == CircuitBreakerState.OPEN
    # Before cooldown: still OPEN
    assert cb.allow() is False
    # After cooldown: auto-transition
    time.sleep(0.08)
    assert cb.state == CircuitBreakerState.HALF_OPEN
    assert cb.allow() is True


def test_half_open_successes_return_to_closed():
    cb = _fast_cb(failure_threshold=2, cooldown=0.02, success_threshold=2)
    cb.record_failure()
    cb.record_failure()
    time.sleep(0.04)
    assert cb.state == CircuitBreakerState.HALF_OPEN
    cb.record_success()
    cb.record_success()
    assert cb.state == CircuitBreakerState.CLOSED


def test_half_open_failure_immediately_reopens():
    cb = _fast_cb(failure_threshold=2, cooldown=0.02, success_threshold=2)
    cb.record_failure()
    cb.record_failure()
    time.sleep(0.04)
    assert cb.state == CircuitBreakerState.HALF_OPEN
    cb.record_failure()  # a single failure on probe → straight back to OPEN
    assert cb.state == CircuitBreakerState.OPEN


def test_reset_forces_closed():
    cb = _fast_cb(failure_threshold=2)
    cb.record_failure()
    cb.record_failure()
    assert cb.state == CircuitBreakerState.OPEN
    cb.reset()
    assert cb.state == CircuitBreakerState.CLOSED
    assert cb.allow() is True


def test_snapshot_shape():
    cb = _fast_cb(failure_threshold=5, cooldown=30.0, success_threshold=3)
    cb.record_failure()
    snap = cb.snapshot()
    assert snap["name"] == "test"
    assert snap["state"] == "closed"
    assert snap["consecutive_failures"] == 1
    assert snap["config"]["failure_threshold"] == 5
    assert snap["config"]["cooldown_seconds"] == 30.0
    assert snap["config"]["success_threshold"] == 3


def test_thread_safe_concurrent_failures():
    """N threads each call record_failure(); final count must equal N.

    If the Lock were missing, the ++ pattern would lose updates under
    contention and the CB might not trip even with enough failures.
    """
    cb = _fast_cb(failure_threshold=100, cooldown=60.0)
    N = 50
    errors: list = []

    def worker():
        try:
            cb.record_failure()
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(N)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    snap = cb.snapshot()
    assert snap["consecutive_failures"] == N


def test_invalid_kelly_fraction_rejected():
    with pytest.raises(ValueError):
        RiskManager(kelly_fraction=0.0)
    with pytest.raises(ValueError):
        RiskManager(kelly_fraction=-0.1)
    with pytest.raises(ValueError):
        RiskManager(kelly_fraction=1.5)


# ── Kelly fractional default (0.25x, Round 6) ───────────────────────────


def _seed_kelly_history(rm: RiskManager, wins: int, losses: int,
                        avg_win: float, avg_loss: float):
    """Seed the manager with a trade history that gives a known Kelly result."""
    for _ in range(wins):
        rm.record_trade("AAPL", OrderSide.BUY, avg_win)
    for _ in range(losses):
        rm.record_trade("AAPL", OrderSide.BUY, -avg_loss)


def test_kelly_default_is_quarter():
    rm = RiskManager(account_value=100_000.0)
    assert rm.kelly_fraction == 0.25


def test_kelly_sizing_scales_with_fraction():
    """Quarter-Kelly must produce half the dollar size of half-Kelly for the
    same history (until it hits the max_position_size_pct cap)."""
    # Lower the cap so Kelly — not the limit — drives the answer.
    limits = RiskLimits(max_position_size_pct=0.50)

    # Win rate 60%, win/loss 2:1 → full Kelly ≈ 40% of portfolio
    # quarter Kelly ≈ 10%, half Kelly ≈ 20%, both below the 50% cap.
    rm_q = RiskManager(limits=limits, account_value=100_000.0, kelly_fraction=0.25)
    _seed_kelly_history(rm_q, wins=12, losses=8, avg_win=200.0, avg_loss=100.0)
    sizing_q = rm_q.calculate_position_size("AAPL", 100.0, method="kelly")

    rm_h = RiskManager(limits=limits, account_value=100_000.0, kelly_fraction=0.50)
    _seed_kelly_history(rm_h, wins=12, losses=8, avg_win=200.0, avg_loss=100.0)
    sizing_h = rm_h.calculate_position_size("AAPL", 100.0, method="kelly")

    # Half-Kelly should be ~2x quarter-Kelly in dollar terms (exact ratio
    # may differ by a share or two due to int() truncation)
    assert sizing_q.dollar_amount > 0
    assert sizing_h.dollar_amount > 0
    ratio = sizing_h.dollar_amount / sizing_q.dollar_amount
    assert 1.8 < ratio < 2.2, f"expected ~2x, got {ratio}"


def test_kelly_respects_max_position_size_cap():
    """Even if full Kelly > the account limit, sizing must not exceed cap."""
    limits = RiskLimits(max_position_size_pct=0.05)  # 5% cap
    rm = RiskManager(limits=limits, account_value=100_000.0, kelly_fraction=1.0)
    # Extreme edge: 90% win rate, 5:1 ratio → full Kelly ~88%
    _seed_kelly_history(rm, wins=18, losses=2, avg_win=500.0, avg_loss=100.0)
    sizing = rm.calculate_position_size("AAPL", 100.0, method="kelly")
    assert sizing.pct_of_portfolio <= 0.05 + 1e-9


def test_kelly_falls_back_to_fixed_on_insufficient_history():
    rm = RiskManager(account_value=100_000.0, kelly_fraction=0.25)
    # Only 5 trades — below the 10-trade threshold
    _seed_kelly_history(rm, wins=3, losses=2, avg_win=100.0, avg_loss=50.0)
    sizing = rm.calculate_position_size("AAPL", 100.0, method="kelly")
    # Fixed sizing gives max_position_size_pct (10% default) of portfolio
    assert sizing.pct_of_portfolio == pytest.approx(0.10)


# ── CircuitBreaker integration with RiskManager ─────────────────────────


def test_assess_trade_short_circuits_when_breaker_open():
    cb = _fast_cb(failure_threshold=1)
    cb.record_failure()
    assert cb.state == CircuitBreakerState.OPEN

    rm = RiskManager(account_value=100_000.0, circuit_breaker=cb)
    # Small, normally-safe trade — should be rejected anyway because CB is open
    assessment = rm.assess_trade("AAPL", OrderSide.BUY, 5, 150.0)
    assert assessment.allowed is False
    assert assessment.risk_level == RiskLevel.CRITICAL
    assert any("Circuit breaker" in w for w in assessment.warnings)
    assert assessment.metadata.get("circuit_breaker_state") == "open"


def test_assess_trade_runs_normally_when_breaker_closed():
    cb = _fast_cb(failure_threshold=5)
    rm = RiskManager(account_value=100_000.0, circuit_breaker=cb)
    assessment = rm.assess_trade("AAPL", OrderSide.BUY, 5, 150.0)
    assert assessment.allowed is True
    assert not any("Circuit breaker" in w for w in assessment.warnings)


def test_assess_trade_no_breaker_attached_runs_normally():
    """Backward compat: RiskManager() with no CB arg behaves as before."""
    rm = RiskManager(account_value=100_000.0)
    assessment = rm.assess_trade("AAPL", OrderSide.BUY, 5, 150.0)
    assert assessment.allowed is True
    assert rm.circuit_breaker is None
