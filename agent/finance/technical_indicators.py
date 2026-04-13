"""
Technical indicators for the fin persona — pure Python, no TA-Lib / numpy.

This module intentionally has zero external dependencies so it can be used
inside backtests, live scanning, and fleet workers without worrying about
an optional wheel being absent. All functions operate on ``list[float]``
(or ``list[float | None]``) and return lists of the same length with
``None`` in positions that don't yet have enough history — preserving
index alignment with the input prices.

Convention: the **most recent** value is at the END of each input list.
So for a 20-day SMA on a 25-day series, positions 0..18 are ``None`` and
positions 19..24 carry values.

Implemented:

  - sma(prices, period)              Simple Moving Average
  - ema(prices, period)               Exponential Moving Average (α = 2/(n+1))
  - rsi(prices, period=14)            Relative Strength Index (Wilder smoothing)
  - macd(prices, fast=12, slow=26, signal=9) → (macd, signal, histogram)
  - bollinger_bands(prices, period=20, num_std=2.0) → (upper, middle, lower)
  - atr(highs, lows, closes, period=14)   Average True Range (Wilder)

All indicators are re-exported from ``agent.finance.technical_indicators``
and are safe for concurrent use (no global state).

Contract: plans/2026-04-12_fin_deepening_fusion_plan.md §4 Phase 3.1.
"""

from __future__ import annotations

import math
from typing import List, Optional, Sequence, Tuple

__all__ = [
    "sma",
    "ema",
    "rsi",
    "macd",
    "bollinger_bands",
    "atr",
    "IndicatorError",
]


class IndicatorError(ValueError):
    """Raised for invalid indicator inputs (bad period, wrong length, etc.)."""


# ── Simple + Exponential Moving Averages ────────────────────────────────


def sma(prices: Sequence[float], period: int) -> List[Optional[float]]:
    """Simple moving average. Output aligned to input; first period-1 are None."""
    if period <= 0:
        raise IndicatorError(f"period must be positive, got {period}")
    n = len(prices)
    if n == 0:
        return []

    out: List[Optional[float]] = [None] * n
    if n < period:
        return out

    window_sum = sum(prices[:period])
    out[period - 1] = window_sum / period
    for i in range(period, n):
        window_sum += prices[i] - prices[i - period]
        out[i] = window_sum / period
    return out


def ema(prices: Sequence[float], period: int) -> List[Optional[float]]:
    """Exponential moving average. Seed uses SMA of first ``period`` values,
    then α = 2/(period+1) smoothing afterwards."""
    if period <= 0:
        raise IndicatorError(f"period must be positive, got {period}")
    n = len(prices)
    if n == 0:
        return []

    out: List[Optional[float]] = [None] * n
    if n < period:
        return out

    alpha = 2.0 / (period + 1)
    seed = sum(prices[:period]) / period
    out[period - 1] = seed
    prev = seed
    for i in range(period, n):
        prev = alpha * prices[i] + (1 - alpha) * prev
        out[i] = prev
    return out


# ── RSI (Wilder smoothing) ──────────────────────────────────────────────


def rsi(prices: Sequence[float], period: int = 14) -> List[Optional[float]]:
    """Relative Strength Index via Wilder's smoothing.

    Returns values in [0, 100]. First ``period`` indices are None (need
    period-1 differences to seed + one observation to emit).
    """
    if period <= 0:
        raise IndicatorError(f"period must be positive, got {period}")
    n = len(prices)
    out: List[Optional[float]] = [None] * n
    if n < period + 1:
        return out

    # Initial gains/losses over the first `period` diffs
    gains = 0.0
    losses = 0.0
    for i in range(1, period + 1):
        change = prices[i] - prices[i - 1]
        if change >= 0:
            gains += change
        else:
            losses -= change

    avg_gain = gains / period
    avg_loss = losses / period
    out[period] = _rsi_from_avg(avg_gain, avg_loss)

    # Wilder smoothing for subsequent bars
    for i in range(period + 1, n):
        change = prices[i] - prices[i - 1]
        gain = change if change > 0 else 0.0
        loss = -change if change < 0 else 0.0
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        out[i] = _rsi_from_avg(avg_gain, avg_loss)

    return out


def _rsi_from_avg(avg_gain: float, avg_loss: float) -> float:
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


# ── MACD ────────────────────────────────────────────────────────────────


def macd(
    prices: Sequence[float],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> Tuple[List[Optional[float]], List[Optional[float]], List[Optional[float]]]:
    """MACD triple: (macd_line, signal_line, histogram).

    macd_line = EMA(prices, fast) − EMA(prices, slow)
    signal_line = EMA(macd_line, signal)
    histogram = macd_line − signal_line
    """
    if fast <= 0 or slow <= 0 or signal <= 0:
        raise IndicatorError("fast/slow/signal must all be positive")
    if fast >= slow:
        raise IndicatorError(f"fast ({fast}) must be < slow ({slow})")

    n = len(prices)
    fast_ema = ema(prices, fast)
    slow_ema = ema(prices, slow)

    macd_line: List[Optional[float]] = [None] * n
    for i in range(n):
        if fast_ema[i] is not None and slow_ema[i] is not None:
            macd_line[i] = fast_ema[i] - slow_ema[i]

    # Build dense sub-series of macd values to run signal EMA on, then
    # stitch back into the aligned output. First valid MACD index is
    # slow-1 (when both EMAs are non-None).
    first_valid = None
    for i in range(n):
        if macd_line[i] is not None:
            first_valid = i
            break

    signal_line: List[Optional[float]] = [None] * n
    if first_valid is not None:
        dense = [macd_line[i] for i in range(first_valid, n)]  # type: ignore[misc]
        signal_dense = ema(dense, signal)
        for k, v in enumerate(signal_dense):
            signal_line[first_valid + k] = v

    histogram: List[Optional[float]] = [None] * n
    for i in range(n):
        if macd_line[i] is not None and signal_line[i] is not None:
            histogram[i] = macd_line[i] - signal_line[i]

    return macd_line, signal_line, histogram


# ── Bollinger Bands ─────────────────────────────────────────────────────


def bollinger_bands(
    prices: Sequence[float], period: int = 20, num_std: float = 2.0
) -> Tuple[List[Optional[float]], List[Optional[float]], List[Optional[float]]]:
    """Bollinger Bands: (upper, middle, lower).

    middle = SMA(prices, period)
    upper  = middle + num_std * stdev(prices window)
    lower  = middle - num_std * stdev(prices window)

    Uses sample standard deviation (ddof=0 — population variance), which
    matches the original Bollinger convention.
    """
    if period <= 0:
        raise IndicatorError(f"period must be positive, got {period}")
    if num_std < 0:
        raise IndicatorError(f"num_std must be non-negative, got {num_std}")

    n = len(prices)
    middle = sma(prices, period)
    upper: List[Optional[float]] = [None] * n
    lower: List[Optional[float]] = [None] * n

    for i in range(period - 1, n):
        window = prices[i - period + 1 : i + 1]
        mean = middle[i]
        if mean is None:
            continue
        variance = sum((x - mean) ** 2 for x in window) / period
        sd = math.sqrt(variance)
        upper[i] = mean + num_std * sd
        lower[i] = mean - num_std * sd

    return upper, middle, lower


# ── Average True Range (Wilder) ─────────────────────────────────────────


def atr(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    period: int = 14,
) -> List[Optional[float]]:
    """Average True Range via Wilder smoothing.

    True range for bar i (i ≥ 1):
        max(
            high_i - low_i,
            abs(high_i - close_{i-1}),
            abs(low_i  - close_{i-1}),
        )
    First bar uses ``high - low`` only.

    ATR at index ``period`` is the simple average of the first ``period``
    TR values; subsequent bars use Wilder smoothing:
        atr_i = (atr_{i-1} * (period - 1) + tr_i) / period
    """
    if period <= 0:
        raise IndicatorError(f"period must be positive, got {period}")
    if not (len(highs) == len(lows) == len(closes)):
        raise IndicatorError(
            f"highs / lows / closes must be same length "
            f"(got {len(highs)}, {len(lows)}, {len(closes)})"
        )

    n = len(closes)
    out: List[Optional[float]] = [None] * n
    if n < period + 1:
        return out

    # Compute true range series
    tr: List[float] = [highs[0] - lows[0]]
    for i in range(1, n):
        tr.append(
            max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
        )

    # Seed: SMA of first `period` TR values (indices 0..period-1)
    seed = sum(tr[:period]) / period
    out[period - 1] = seed

    prev = seed
    for i in range(period, n):
        prev = (prev * (period - 1) + tr[i]) / period
        out[i] = prev
    return out
