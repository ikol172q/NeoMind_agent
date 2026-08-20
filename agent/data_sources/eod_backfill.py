"""EOD backfill — keep market_data_daily fresh + cover ALL holdings.

Why this exists: daily_market_pull pulls only the "active universe" through the
server's long-lived (rate-limited) yfinance session, so market_data_daily went
stale (stuck 2026-05-08) AND 5 holdings had zero rows. yfinance's HISTORY
endpoint still works where fast_info/info throttle — this pulls it and upserts
via the existing dao.upsert_market_data_daily (idempotent, re-runnable).

Run standalone (fresh process = no throttle):
    python -m agent.data_sources.eod_backfill
"""
from __future__ import annotations

import logging
from contextlib import closing
from typing import Any, Dict, List

from agent.fin_provider import fin_module

_persistence = fin_module('persistence')
connect, ensure_schema = _persistence.connect, _persistence.ensure_schema
dao = getattr(_persistence, 'dao', None) or fin_module('persistence.dao')

logger = logging.getLogger(__name__)


def _f(v) -> Any:
    try:
        import math
        f = float(v)
        return None if math.isnan(f) else f
    except Exception:
        return None


def fetch_eod_bars(ticker: str, period: str = "6mo") -> List[Dict[str, Any]]:
    """yfinance daily history → bars in dao.upsert shape. [] on failure."""
    try:
        import yfinance as yf
        h = yf.Ticker(ticker).history(period=period, auto_adjust=False)
    except Exception as exc:  # noqa: BLE001
        logger.warning("eod history(%s) failed: %s", ticker, exc)
        return []
    if h is None or len(h) == 0:
        return []
    cols = set(h.columns)
    bars: List[Dict[str, Any]] = []
    for idx, row in h.iterrows():
        close = _f(row.get("Close"))
        adj = _f(row.get("Adj Close")) if "Adj Close" in cols else close
        vol = row.get("Volume")
        bars.append({
            "date": idx.date().isoformat(),
            "open": _f(row.get("Open")), "high": _f(row.get("High")),
            "low": _f(row.get("Low")), "close": close,
            "adjusted_close": adj if adj is not None else close,
            "volume": int(vol) if (vol is not None and _f(vol) is not None) else None,
        })
    return bars


def backfill_eod(tickers: List[str], period: str = "6mo", market: str = "us") -> Dict[str, Any]:
    ensure_schema()
    total = 0
    ok: List[Dict[str, Any]] = []
    fail: List[str] = []
    for tk in sorted({t.upper().strip() for t in tickers if t}):
        bars = fetch_eod_bars(tk, period)
        if not bars:
            fail.append(tk)
            continue
        # 🔴 2026-07-30 真事故: 这里原来是 `with connect() as conn:` ——
        #    `with <sqlite3.Connection>` 只**提交事务, 不关闭连接**。690 个 ticker 的循环
        #    因此泄漏 690 条连接, 每条在 WAL 下占 3 个 fd (db / -wal / -shm)。
        #    交互 shell 的 fd 上限是 1,048,576 所以手跑永远正常; 但 **launchd 只给 256**,
        #    于是定时任务每天跑到第 ~127 个 ticker 就死于
        #    `sqlite3.OperationalError: unable to open database file` (SQLITE_CANTOPEN)。
        #    实测后果: 690 个 symbol 里 550 个陈旧 —— 按字母序靠后的全军覆没
        #    (QQQ 第 521 / SPY 579 / SSP 584 / VITL 655), 而 market_data_daily 是
        #    相关性 / 回撤告警 / regime / 回测共用的底座。
        #    (下游 `spreads()` 的陈旧回落只是止血, 治不了这个生产端。)
        #    修法: closing() 负责关连接, 内层 `with conn` 仍负责提交 —— 峰值 fd 占用回到 3。
        with closing(connect()) as conn, conn:
            n = dao.upsert_market_data_daily(
                conn, symbol=tk, market=market, bars=bars, source="yfinance-history",
            )
        total += n
        ok.append({"ticker": tk, "rows": len(bars), "latest": bars[-1]["date"]})
    return {"total_rows": total, "ok": ok, "fail": fail}


def _watchlist_and_held() -> List[str]:
    with connect() as conn:
        wl = [r["ticker"] for r in conn.execute("SELECT DISTINCT ticker FROM user_watchlist").fetchall()]
        held = [r["symbol"] for r in conn.execute(
            "SELECT DISTINCT symbol FROM tax_lots WHERE close_date IS NULL").fetchall()]
    return sorted({*(t for t in wl if t), *(s for s in held if s)})


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    tickers = _watchlist_and_held()
    print(f"backfilling EOD for {len(tickers)} tickers...")
    res = backfill_eod(tickers)
    print(f"total rows: {res['total_rows']} | ok: {len(res['ok'])} | fail: {res['fail']}")
    for o in res["ok"]:
        print(f"  {o['ticker']:6} {o['rows']} rows, latest {o['latest']}")
