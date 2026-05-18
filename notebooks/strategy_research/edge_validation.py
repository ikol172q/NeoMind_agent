"""Edge-validation backtest framework.

Run:
    .neomind_fin_venv/bin/python notebooks/strategy_research/edge_validation.py

What this does:
    1. Pulls 2 years of OHLC for the user's watchlist + SPY benchmark
       via yfinance (free, public data)
    2. Runs THREE strategies:
        A. SPY buy & hold (baseline)
        B. Pure technical: RSI mean-reversion on user's tickers
        C. (Placeholder) NeoMind signal-driven — empty until
           signal_snapshots table accumulates >=60 days of history
    3. Reports per-strategy: total return, CAGR, Sharpe, max drawdown,
       win rate, vs SPY
    4. Computes Information Coefficient (IC) of NeoMind combined signal
       vs forward 5-day returns — answers "does my signal predict?"
       IF signal_snapshots has data; else skips with a clear message

What this does NOT do:
    - Use NeoMind signal_events directly (only 17 days of history)
    - Trade real money
    - Account for transaction costs / slippage / borrow rates
      (vectorbt has these features; turn on when you're closer to live)

Why this is honest:
    Your true edge probably comes from combining 10-K extracted
    relations + 13F whale moves + congress + insider — none of which
    are in yfinance OHLC. THIS SCRIPT cannot prove your edge yet
    because we don't have historical NeoMind score data.

    What it DOES prove: the framework works end-to-end. When
    signal_snapshots accumulates 60+ days (around 2026-07-15), come
    back and re-run — it'll automatically pick up real signal history.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import warnings
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

warnings.filterwarnings("ignore")  # keep output readable

import numpy as np
import pandas as pd
import vectorbt as vbt
import yfinance as yf

DB_PATH = Path.home() / ".neomind" / "fin" / "fin.db"
BENCHMARK = "SPY"
LOOKBACK_YEARS = 2


def _watchlist_tickers() -> List[str]:
    if not DB_PATH.exists():
        return ["AAPL", "NVDA", "GOOGL", "AMD", "META", "MSFT", "TSLA"]
    conn = sqlite3.connect(str(DB_PATH))
    rows = conn.execute(
        "SELECT ticker FROM user_watchlist WHERE tier IN ('core','adjacent')"
    ).fetchall()
    conn.close()
    return [r[0] for r in rows] or ["AAPL", "NVDA", "GOOGL", "AMD"]


def _fetch_prices(tickers: List[str], years: int = LOOKBACK_YEARS) -> pd.DataFrame:
    end = datetime.now()
    start = end - timedelta(days=int(years * 365.25))
    print(f"📥 fetching {len(tickers)} tickers from yfinance "
          f"({start.date()} → {end.date()})...")
    raw = yf.download(
        tickers, start=start, end=end,
        progress=False, auto_adjust=True,
        threads=True,
    )["Close"]
    if isinstance(raw, pd.Series):
        raw = raw.to_frame()
    # Drop columns (tickers) with no data at all — e.g. delisted/OTC
    raw = raw.dropna(axis=1, how="all")
    dropped = set(tickers) - set(raw.columns)
    if dropped:
        print(f"   ⚠ dropped (no data): {sorted(dropped)}")
    # Then drop rows where any remaining ticker has NaN (only keep
    # dates where ALL kept tickers have a price).
    df = raw.dropna(how="all").ffill().dropna()
    print(f"   ✓ {len(df)} trading days, {df.shape[1]} symbols")
    return df


def _report(name: str, pf) -> Dict[str, float]:
    """vectorbt Portfolio → metric dict."""
    s = pf.stats()
    out = {
        "total_return_pct": float(s["Total Return [%]"]),
        "cagr_pct":         float(s.get("Annualized Return [%]", float("nan"))),
        "sharpe":           float(s.get("Sharpe Ratio", float("nan"))),
        "sortino":          float(s.get("Sortino Ratio", float("nan"))),
        "max_dd_pct":       float(s["Max Drawdown [%]"]),
        "win_rate_pct":     float(s.get("Win Rate [%]", float("nan"))),
        "n_trades":         int(s.get("Total Trades", 0) or 0),
    }
    print(f"\n📊 {name}")
    print(f"  total return  : {out['total_return_pct']:+8.2f}%")
    print(f"  CAGR          : {out['cagr_pct']:+8.2f}%")
    print(f"  Sharpe        : {out['sharpe']:8.3f}")
    print(f"  Sortino       : {out['sortino']:8.3f}")
    print(f"  Max drawdown  : {out['max_dd_pct']:+8.2f}%")
    print(f"  Win rate      : {out['win_rate_pct']:8.2f}%")
    print(f"  # trades      : {out['n_trades']:8d}")
    return out


# ─── Strategy A: SPY buy & hold ──────────────────────────────────────


def strat_spy_hold() -> Tuple[str, Dict[str, float]]:
    prices = _fetch_prices([BENCHMARK])
    spy = prices[BENCHMARK]
    entries = pd.Series(False, index=spy.index); entries.iloc[0] = True
    exits = pd.Series(False, index=spy.index); exits.iloc[-1] = True
    pf = vbt.Portfolio.from_signals(spy, entries, exits, init_cash=10_000, freq="1D")
    return "A. SPY buy & hold (baseline)", _report("A. SPY buy & hold", pf)


# ─── Strategy B: RSI mean-reversion on watchlist ────────────────────


def strat_rsi_mean_reversion() -> Tuple[str, Dict[str, float]]:
    tickers = _watchlist_tickers()
    prices = _fetch_prices(tickers)
    rsi = vbt.RSI.run(prices, window=14).rsi
    entries = rsi < 30
    exits   = rsi > 70
    pf = vbt.Portfolio.from_signals(
        prices, entries, exits,
        init_cash=10_000, freq="1D",
        fees=0.0005,    # 5 bps round-trip approx
        slippage=0.0005,
    )
    # Aggregate to portfolio level (equal weight across tickers)
    return "B. RSI<30/>70 mean-reversion on watchlist", \
        _report("B. RSI mean-reversion (watchlist)", pf)


# ─── Edge analysis: NeoMind combined signal IC ──────────────────────


def neomind_ic_analysis() -> Optional[Dict[str, float]]:
    """Information Coefficient: correlation between NeoMind combined
    signal at day t and forward 5-day return.

    IC > 0.05 = real edge. IC > 0.10 = strong edge. IC ≈ 0 = no edge.

    Requires signal_snapshots to have data. At v1 launch this table is
    fresh — won't have entries until tomorrow's first cron tick.
    """
    if not DB_PATH.exists():
        print("\n⏭  signal_snapshots: no DB found, skipping")
        return None
    conn = sqlite3.connect(str(DB_PATH))
    try:
        df = pd.read_sql_query(
            "SELECT ticker, snapshot_date, combined "
            "FROM signal_snapshots WHERE data_complete = 1",
            conn,
        )
    finally:
        conn.close()

    if df.empty:
        print("\n⏭  signal_snapshots: empty (cron hasn't run yet).")
        print("   Tomorrow ~22:00 UTC the daily snapshot cron writes the")
        print("   first row. Need ~30 days minimum, 60+ days for any")
        print("   statistical signal. Re-run this script around 2026-07-15.")
        return None

    n_days = df["snapshot_date"].nunique()
    n_tickers = df["ticker"].nunique()
    print(f"\n🔬 NeoMind IC analysis: {n_days} days × {n_tickers} tickers")

    if n_days < 30:
        print(f"   Only {n_days} days of history; need >=30 for any IC signal.")
        print(f"   Result would be noise. Skipping.")
        return None

    tickers = df["ticker"].unique().tolist()
    prices = _fetch_prices(tickers, years=1)
    fwd_5d = prices.pct_change(5).shift(-5)

    df["snapshot_date"] = pd.to_datetime(df["snapshot_date"])
    df = df.pivot_table(index="snapshot_date", columns="ticker", values="combined")
    df = df.reindex(prices.index).ffill()

    pairs = []
    for t in tickers:
        if t not in df.columns or t not in fwd_5d.columns: continue
        joined = pd.DataFrame({"signal": df[t], "fwd": fwd_5d[t]}).dropna()
        if len(joined) < 20: continue
        ic = joined["signal"].corr(joined["fwd"])
        pairs.append((t, ic, len(joined)))

    pairs.sort(key=lambda x: -abs(x[1]))
    print(f"   per-ticker IC (correlation of signal_t vs forward_5d_return):")
    for t, ic, n in pairs[:10]:
        marker = "✅" if abs(ic) > 0.05 else "·"
        print(f"     {marker} {t:6s} IC={ic:+.3f}  (n={n})")
    avg_ic = float(np.mean([ic for _, ic, _ in pairs])) if pairs else 0.0
    print(f"   📊 cross-ticker mean IC: {avg_ic:+.4f}  "
          f"({'real edge' if abs(avg_ic) > 0.05 else 'no edge yet'})")
    return {"mean_ic": avg_ic, "n_pairs": len(pairs)}


# ─── Main ────────────────────────────────────────────────────────────


def main() -> int:
    print("=" * 65)
    print(" NeoMind edge-validation backtest")
    print("=" * 65)
    print(f" watchlist : {_watchlist_tickers()}")
    print(f" benchmark : {BENCHMARK}")
    print(f" lookback  : {LOOKBACK_YEARS} years")
    print()

    results: Dict[str, Dict[str, float]] = {}

    name_a, m_a = strat_spy_hold()
    results[name_a] = m_a

    name_b, m_b = strat_rsi_mean_reversion()
    results[name_b] = m_b

    # NeoMind signal IC (the real question — "does my edge work?")
    ic = neomind_ic_analysis()
    if ic:
        results["NeoMind IC"] = ic

    print()
    print("=" * 65)
    print(" SUMMARY")
    print("=" * 65)
    for name, m in results.items():
        if "total_return_pct" in m:
            print(f"  {name:50s} ret={m['total_return_pct']:+7.1f}%  "
                  f"Sharpe={m['sharpe']:.2f}")
        elif "mean_ic" in m:
            print(f"  {name:50s} mean IC={m['mean_ic']:+.4f}")

    print()
    print("📝 Next:")
    print("  · Tomorrow ~22:00 UTC signal_snapshot_daily writes first row")
    print("  · After 30-60 days re-run this — neomind_ic_analysis() will")
    print("    tell you if your signals predict forward returns")
    print("  · If IC > 0.05 → real edge → encode into QuantConnect algo")
    print("  · If IC ≈ 0    → no edge → iterate on signal weighting in")
    print("    agent/finance/strategy_signals.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
