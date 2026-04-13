"""Phase 2.2 — RiskManager enforcement wired into PaperTradingEngine.

Tests the opt-in risk check injection:

  PaperTradingEngine(risk_manager=X)  → risk-gated (new)
  PaperTradingEngine()                → legacy advisory-only (unchanged)

Environment variable ``NEOMIND_PAPER_TRADING_BYPASS_RISK=1`` bypasses
the check even when a risk_manager is attached.
"""

from __future__ import annotations

import os

import pytest

from agent.finance.paper_trading import (
    OrderSide,
    OrderStatus,
    PaperTradingEngine,
)
from agent.finance.risk_manager import (
    CircuitBreaker,
    CircuitBreakerConfig,
    RiskLimits,
    RiskManager,
)


@pytest.fixture(autouse=True)
def _clear_bypass_env(monkeypatch):
    """Make sure no stray env var leaks between tests."""
    monkeypatch.delenv("NEOMIND_PAPER_TRADING_BYPASS_RISK", raising=False)


@pytest.fixture
def engine_no_risk():
    """Legacy mode — exactly what existing callers get."""
    e = PaperTradingEngine(initial_capital=100_000.0, slippage_rate=0.0)
    e.update_price("AAPL", 150.0)
    return e


@pytest.fixture
def engine_with_risk():
    """New mode — risk_manager attached, 10% position cap."""
    rm = RiskManager(
        limits=RiskLimits(max_position_size_pct=0.10),
        account_value=100_000.0,
    )
    e = PaperTradingEngine(
        initial_capital=100_000.0,
        slippage_rate=0.0,
        risk_manager=rm,
    )
    e.update_price("AAPL", 150.0)
    return e


# ── Backward-compat: default engine is unchanged ────────────────────────


def test_default_engine_has_no_risk_manager(engine_no_risk):
    assert engine_no_risk.risk_manager is None


def test_default_engine_allows_oversize_buy(engine_no_risk):
    """Legacy mode: engine does NOT enforce risk checks.

    This is exactly the behavior the 10 existing TestPaperTrading tests
    rely on. If this regresses, a pile of existing tests also regress.
    """
    # $100k buy (66% of portfolio) — way over any sane position limit
    order = engine_no_risk.place_order("AAPL", OrderSide.BUY, 400)
    # Still rejected (insufficient funds), but with the legacy error,
    # NOT a risk_rejected error
    assert "risk_rejected" not in order.metadata.get("error", "")


# ── New mode: risk check enforced ───────────────────────────────────────


def test_risk_engine_allows_small_buy(engine_with_risk):
    """5 * $150 = $750 = 0.75% of $100k → well under 10% cap."""
    order = engine_with_risk.place_order("AAPL", OrderSide.BUY, 5)
    assert order.status == OrderStatus.FILLED
    assert order.metadata.get("error", "") == ""


def test_risk_engine_rejects_oversize_buy(engine_with_risk):
    """100 * $150 = $15,000 = 15% of portfolio → over the 10% position cap."""
    order = engine_with_risk.place_order("AAPL", OrderSide.BUY, 100)
    assert order.status == OrderStatus.REJECTED
    err = order.metadata.get("error", "")
    assert err.startswith("risk_rejected"), f"unexpected error: {err}"
    assert "Position size" in err
    assert "risk_level" in order.metadata
    assert len(order.metadata.get("risk_warnings", [])) > 0


def test_risk_engine_does_not_fill_rejected_order(engine_with_risk):
    """A risk-rejected order must NOT touch cash or positions."""
    initial_cash = engine_with_risk.account.cash
    engine_with_risk.place_order("AAPL", OrderSide.BUY, 100)
    assert engine_with_risk.account.cash == initial_cash
    assert "AAPL" not in engine_with_risk.account.positions
    # Also: no trade record created
    assert len(engine_with_risk.trades) == 0


def test_risk_engine_rejects_sell_when_daily_loss_cap_hit(engine_with_risk):
    """Record a big loss, then any new trade should be blocked."""
    engine_with_risk.risk_manager.record_trade(
        "AAPL", OrderSide.SELL, -5000.0,
    )
    order = engine_with_risk.place_order("AAPL", OrderSide.BUY, 5)
    assert order.status == OrderStatus.REJECTED
    assert order.metadata.get("error", "").startswith("risk_rejected")


# ── Kill switch bypass ──────────────────────────────────────────────────


def test_bypass_env_var_skips_risk_check(engine_with_risk, monkeypatch):
    monkeypatch.setenv("NEOMIND_PAPER_TRADING_BYPASS_RISK", "1")
    # Same oversize buy that normally gets risk_rejected
    order = engine_with_risk.place_order("AAPL", OrderSide.BUY, 100)
    # Not risk-rejected; goes through to fill / insufficient-funds / etc.
    assert "risk_rejected" not in order.metadata.get("error", "")


def test_bypass_env_var_wrong_value_still_enforces(engine_with_risk, monkeypatch):
    """Only '1' bypasses — 'true', 'yes', '0' etc. do NOT."""
    for val in ("0", "true", "yes", "on", ""):
        monkeypatch.setenv("NEOMIND_PAPER_TRADING_BYPASS_RISK", val)
        order = engine_with_risk.place_order("AAPL", OrderSide.BUY, 100)
        assert order.metadata.get("error", "").startswith("risk_rejected"), (
            f"bypass should NOT activate for env value {val!r}"
        )


# ── Circuit breaker integration path ───────────────────────────────────


def test_open_circuit_breaker_blocks_all_trades():
    """When the risk_manager's circuit_breaker is open, every trade is rejected
    at the risk layer — even small ones that would normally pass."""
    cb = CircuitBreaker(
        name="test",
        config=CircuitBreakerConfig(failure_threshold=1, cooldown_seconds=60.0),
    )
    cb.record_failure()  # trip it
    rm = RiskManager(account_value=100_000.0, circuit_breaker=cb)
    engine = PaperTradingEngine(
        initial_capital=100_000.0, slippage_rate=0.0, risk_manager=rm,
    )
    engine.update_price("AAPL", 150.0)
    order = engine.place_order("AAPL", OrderSide.BUY, 1)  # 1 share → trivially safe
    assert order.status == OrderStatus.REJECTED
    err = order.metadata.get("error", "")
    assert "risk_rejected" in err
    assert "Circuit breaker" in err


def test_closed_circuit_breaker_allows_normal_trades():
    cb = CircuitBreaker(
        name="test",
        config=CircuitBreakerConfig(failure_threshold=5, cooldown_seconds=60.0),
    )
    rm = RiskManager(account_value=100_000.0, circuit_breaker=cb)
    engine = PaperTradingEngine(
        initial_capital=100_000.0, slippage_rate=0.0, risk_manager=rm,
    )
    engine.update_price("AAPL", 150.0)
    order = engine.place_order("AAPL", OrderSide.BUY, 5)
    assert order.status == OrderStatus.FILLED
