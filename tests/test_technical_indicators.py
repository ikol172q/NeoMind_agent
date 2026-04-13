"""Tests for agent/finance/technical_indicators.py — numerics on known values."""

from __future__ import annotations

import math

import pytest

from agent.finance.technical_indicators import (
    IndicatorError,
    atr,
    bollinger_bands,
    ema,
    macd,
    rsi,
    sma,
)


# ── SMA ─────────────────────────────────────────────────────────────────


def test_sma_none_until_period():
    prices = [1.0, 2.0, 3.0, 4.0]
    out = sma(prices, 3)
    assert out[0] is None
    assert out[1] is None
    assert out[2] == pytest.approx(2.0)  # (1+2+3)/3
    assert out[3] == pytest.approx(3.0)  # (2+3+4)/3


def test_sma_constant_series():
    out = sma([5.0] * 10, 4)
    assert out[:3] == [None, None, None]
    for v in out[3:]:
        assert v == pytest.approx(5.0)


def test_sma_preserves_length():
    out = sma([1, 2, 3, 4, 5, 6, 7], 3)
    assert len(out) == 7


def test_sma_empty():
    assert sma([], 3) == []


def test_sma_too_short():
    out = sma([1.0, 2.0], 5)
    assert out == [None, None]


def test_sma_invalid_period():
    with pytest.raises(IndicatorError):
        sma([1, 2, 3], 0)
    with pytest.raises(IndicatorError):
        sma([1, 2, 3], -1)


# ── EMA ─────────────────────────────────────────────────────────────────


def test_ema_matches_sma_on_constant():
    """For a constant series, EMA must equal the constant."""
    out = ema([10.0] * 10, 3)
    assert out[0] is None
    assert out[1] is None
    for v in out[2:]:
        assert v == pytest.approx(10.0)


def test_ema_responds_to_jump():
    """After a price jump, EMA trends toward the new level."""
    prices = [10.0] * 5 + [20.0] * 5
    out = ema(prices, 3)
    # Seed at index 2 (period-1) = average of 10,10,10 = 10
    assert out[2] == pytest.approx(10.0)
    # After the jump, values should increase monotonically toward 20
    post_jump = [v for v in out[5:] if v is not None]
    for a, b in zip(post_jump, post_jump[1:]):
        assert b > a
        assert b <= 20.0


def test_ema_invalid_period():
    with pytest.raises(IndicatorError):
        ema([1.0, 2.0, 3.0], 0)


# ── RSI ─────────────────────────────────────────────────────────────────


def test_rsi_strict_uptrend_is_100():
    prices = list(range(1, 20))  # 1, 2, ..., 19
    out = rsi(prices, period=14)
    # First 14 are None (need period+1 diffs → emit at index 14)
    assert all(v is None for v in out[:14])
    # All subsequent should be 100 (pure gains, zero losses)
    for v in out[14:]:
        assert v == pytest.approx(100.0)


def test_rsi_strict_downtrend_is_zero():
    prices = list(range(20, 1, -1))  # 20, 19, ..., 2
    out = rsi(prices, period=14)
    for v in out[14:]:
        assert v == pytest.approx(0.0)


def test_rsi_alternating_is_near_50():
    """Strict alternating ±1 should yield RSI very close to 50."""
    prices = [10 + (i % 2) for i in range(40)]  # 10, 11, 10, 11, ...
    out = rsi(prices, period=14)
    # Stationary around 50 (some Wilder transient as new bars come in)
    stable = [v for v in out[-5:] if v is not None]
    for v in stable:
        assert 45.0 <= v <= 55.0


def test_rsi_too_short_returns_all_none():
    out = rsi([1.0, 2.0, 3.0], period=14)
    assert out == [None, None, None]


def test_rsi_invalid_period():
    with pytest.raises(IndicatorError):
        rsi([1.0, 2.0, 3.0], period=0)


# ── MACD ────────────────────────────────────────────────────────────────


def test_macd_linear_series_converges_to_constant_lag():
    """On a perfectly linear series with slope 1, the MACD line converges
    to a constant difference between fast-EMA lag and slow-EMA lag.

    For fast=12 slow=26 with a unit-slope line:
      EMA_lag(n) ≈ (n-1)/2
      fast_lag = 5.5,  slow_lag = 12.5
      MACD = slow_lag − fast_lag = 7.0 (line lags by slow, fast leads by (slow-fast)/2 = 7)
    """
    prices = [float(i) for i in range(80)]
    m_line, s_line, hist = macd(prices, fast=12, slow=26, signal=9)

    # Last value should be very close to 7.0 after long convergence
    assert m_line[-1] == pytest.approx(7.0, abs=0.1)
    assert s_line[-1] == pytest.approx(7.0, abs=0.1)
    assert hist[-1] == pytest.approx(0.0, abs=0.1)


def test_macd_aligned_lengths():
    prices = list(range(60))
    m_line, s_line, hist = macd(prices)
    assert len(m_line) == len(prices)
    assert len(s_line) == len(prices)
    assert len(hist) == len(prices)


def test_macd_invalid_fast_slow():
    with pytest.raises(IndicatorError):
        macd([1.0] * 50, fast=26, slow=12)  # fast >= slow
    with pytest.raises(IndicatorError):
        macd([1.0] * 50, fast=0, slow=26)


# ── Bollinger Bands ─────────────────────────────────────────────────────


def test_bollinger_constant_series_has_zero_width():
    """Flat price → zero variance → upper == middle == lower."""
    prices = [100.0] * 30
    upper, middle, lower = bollinger_bands(prices, period=20, num_std=2.0)
    assert middle[19] == pytest.approx(100.0)
    assert upper[19] == pytest.approx(100.0)
    assert lower[19] == pytest.approx(100.0)


def test_bollinger_symmetric_bands():
    prices = [float(x) for x in range(1, 41)]
    upper, middle, lower = bollinger_bands(prices, period=20, num_std=2.0)
    # Upper and lower must be symmetric about middle
    for i, m in enumerate(middle):
        if m is None:
            continue
        assert (upper[i] - m) == pytest.approx(m - lower[i])


def test_bollinger_invalid_params():
    with pytest.raises(IndicatorError):
        bollinger_bands([1.0, 2.0, 3.0], period=0)
    with pytest.raises(IndicatorError):
        bollinger_bands([1.0, 2.0, 3.0], period=2, num_std=-1)


# ── ATR ─────────────────────────────────────────────────────────────────


def test_atr_constant_range_bars():
    """Bars with constant high-low range of 2.0 → ATR = 2.0 once seeded."""
    n = 20
    closes = [100.0 + i for i in range(n)]
    highs = [c + 1.0 for c in closes]
    lows = [c - 1.0 for c in closes]
    out = atr(highs, lows, closes, period=5)
    for v in out[4:]:
        assert v == pytest.approx(2.0, abs=0.01)


def test_atr_length_mismatch():
    with pytest.raises(IndicatorError):
        atr([1.0, 2.0], [1.0], [1.0, 2.0])


def test_atr_too_short_returns_all_none():
    out = atr([1.0, 2.0], [0.5, 1.5], [0.8, 1.8], period=14)
    assert out == [None, None]


def test_atr_invalid_period():
    with pytest.raises(IndicatorError):
        atr([1.0, 2.0, 3.0], [1.0, 2.0, 3.0], [1.0, 2.0, 3.0], period=0)
