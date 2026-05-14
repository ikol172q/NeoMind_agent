"""Aggressive historical-data backfill orchestrator.

User push 2026-05-10: stop saying "wait for daily jobs to accumulate"
when most data has been freely available for years.

Runs 4 backfills:
  1. Adjacent ring auto-promote — for each Core ticker, scan its
     stock_anchored_facts.competitor/customer/supplier rows and
     promote any rows with payload.ticker set to user_watchlist
     (tier='adjacent', parent_ticker=originating Core).

  2. SPY + watchlist 5y EOD → market_data_daily — single yfinance
     batch per ticker. Makes vs-benchmark calc not depend on daily
     pull or yfinance live fallback.

  3. Re-extract 10-K for tickers with missing fact types — many
     extractions returned 0 for customer/supplier/segment due to
     LLM gaps. Re-run picks up improvements.

  4. Earnings history extension — Phase 3 daily job already pulls
     into earnings_history with no LIMIT, so this is a no-op
     verification.

Usage:
    .venv/bin/python tools/backfill_data.py                 # dry-run
    .venv/bin/python tools/backfill_data.py --apply         # actually write
    .venv/bin/python tools/backfill_data.py --apply --skip 2,3   # subset

Idempotent: re-running is safe (auto-promote skips already-existing,
EOD upsert replaces, re-extract overwrites).

Cost: ~$0.30 if any 10-K re-extract runs (3 missing fact types ×
$0.01 × 9 tickers max). Otherwise free (yfinance + local SQL).
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import urllib.request
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

# Set up logging before importing anything else
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("backfill")

from agent.finance.persistence import connect, ensure_schema


# ── 1. Adjacent ring auto-promote ──────────────────────────────────


# Curated name → US-tradable ticker mapping. LLM extractions usually
# pick the legal entity name ("Taiwan Semiconductor Manufacturing
# Company Limited"); this dict maps to the ADR/equivalent that the
# user can actually research and trade. Conservative — only entries
# with a public US listing or major ADR. Update by hand.
NAME_TO_TICKER = {
    # Semis / NVDA supply chain
    "taiwan semiconductor manufacturing company limited": "TSM",
    "taiwan semiconductor manufacturing company": "TSM",
    "taiwan semiconductor": "TSM",
    "tsmc": "TSM",
    "samsung electronics co., ltd.": "SSNLF",       # OTC ADR
    "samsung electronics": "SSNLF",
    "sk hynix inc.": "HXSCF",                        # OTC ADR
    "sk hynix": "HXSCF",
    "micron technology, inc.": "MU",
    "micron technology": "MU",
    "micron": "MU",
    "hon hai precision industry co., ltd.": "HNHPF",  # OTC ADR (Foxconn parent)
    "hon hai precision industry": "HNHPF",
    "hon hai": "HNHPF",
    "fabrinet": "FN",
    # Gaming / AAPL
    "nintendo": "NTDOY",     # OTC ADR
    "nintendo co., ltd.": "NTDOY",
    # Other commonly mentioned
    "advanced micro devices, inc.": "AMD",
    "advanced micro devices": "AMD",
    "alibaba group holding limited": "BABA",
    "alibaba": "BABA",
    "tencent": "TCEHY",       # OTC ADR
    "baidu, inc.": "BIDU",
    "baidu": "BIDU",
    "asml holding n.v.": "ASML",
    "asml": "ASML",
    "qualcomm incorporated": "QCOM",
    "qualcomm": "QCOM",
    "broadcom inc.": "AVGO",
    "broadcom": "AVGO",
    "international business machines corporation": "IBM",
    "oracle corporation": "ORCL",
    "oracle": "ORCL",
    "salesforce, inc.": "CRM",
    "salesforce": "CRM",
    "snowflake inc.": "SNOW",
    "snowflake": "SNOW",
    "palantir technologies inc.": "PLTR",
    "palantir": "PLTR",
    # Cloud / streaming / META & GOOGL competitors
    "snap inc.": "SNAP",
    "snap": "SNAP",
    "pinterest, inc.": "PINS",
    "pinterest": "PINS",
    "netflix, inc.": "NFLX",
    "netflix": "NFLX",
    "disney": "DIS",
    "the walt disney company": "DIS",
    "spotify technology s.a.": "SPOT",
    "spotify": "SPOT",
}


def _name_to_ticker(name: str) -> str | None:
    """Lookup a curated US-tradable ticker for a legal entity name.
    Returns None if unmapped. Lowercased exact match plus a fallback
    that strips common suffixes."""
    key = (name or "").strip().lower().rstrip(".")
    if key in NAME_TO_TICKER:
        return NAME_TO_TICKER[key]
    # Try stripping common corporate suffixes
    for suf in (" inc", " inc.", " corporation", " corp.", " corp",
                " co., ltd.", " company limited", ", inc.", ", inc",
                " n.v.", " s.a.", " ltd.", " ltd"):
        if key.endswith(suf):
            key2 = key[: -len(suf)].strip().rstrip(",.")
            if key2 in NAME_TO_TICKER:
                return NAME_TO_TICKER[key2]
    return None


def auto_promote_adjacent(apply: bool = False, max_per_parent: int = 5) -> Dict[str, Any]:
    """For each Core ticker, scan competitor/customer/supplier facts.
    Promote any related entity with payload.ticker set to Adjacent
    tier with parent_ticker pointing back. Falls back to NAME_TO_TICKER
    lookup when the extraction lacks an explicit ticker symbol —
    handles common international entities (TSMC, Samsung, Nintendo, …)
    that the LLM pulled from 10-K text by name only."""
    ensure_schema()
    promoted: List[Dict[str, str]] = []
    skipped: List[str] = []
    with connect() as conn:
        cores = [r["ticker"] for r in conn.execute(
            "SELECT ticker FROM user_watchlist WHERE tier='core' ORDER BY ticker"
        )]
        existing = {r["ticker"] for r in conn.execute(
            "SELECT ticker FROM user_watchlist"
        )}
        for core in cores:
            n_for_this_core = 0
            facts = conn.execute(
                "SELECT id, fact_type, payload_json FROM stock_anchored_facts "
                "WHERE ticker = ? AND fact_type IN ('competitor','customer','supplier') "
                "ORDER BY id",
                (core,),
            ).fetchall()
            for f in facts:
                if n_for_this_core >= max_per_parent:
                    break
                try:
                    payload = json.loads(f["payload_json"] or "{}")
                except json.JSONDecodeError:
                    continue
                related_ticker = (payload.get("ticker") or "").strip().upper()
                related_name = payload.get("name", "?")
                # Fallback: curated name → ticker lookup so NVDA's
                # TSMC/Samsung-style entries also get promoted.
                if not related_ticker:
                    mapped = _name_to_ticker(related_name)
                    if mapped:
                        related_ticker = mapped
                if not related_ticker:
                    skipped.append(f"{core} {f['fact_type']}/{related_name}: no payload.ticker")
                    continue
                if related_ticker in existing:
                    skipped.append(f"{core} → {related_ticker}: already in watchlist")
                    continue
                promoted.append({
                    "ticker":        related_ticker,
                    "parent_ticker": core,
                    "via":           f["fact_type"],
                    "from_fact_id":  f["id"],
                    "name":          related_name,
                })
                existing.add(related_ticker)
                n_for_this_core += 1
        if apply and promoted:
            now = datetime.now(timezone.utc).isoformat()
            for p in promoted:
                conn.execute(
                    "INSERT INTO user_watchlist "
                    "(ticker, tier, parent_ticker, note, importance, added_at) "
                    "VALUES (?, 'adjacent', ?, ?, 1, ?)",
                    (p["ticker"], p["parent_ticker"],
                     f"auto-promoted from {p['parent_ticker']} 10-K {p['via']}: {p['name']}",
                     now),
                )
                # Audit row
                conn.execute(
                    "INSERT INTO watchlist_audit "
                    "(audit_id, ticker, action, from_tier, to_tier, "
                    " trigger_kind, trigger_ref_id, ts, note) "
                    "VALUES (?, ?, 'promote', NULL, 'adjacent', "
                    " 'fact', ?, ?, ?)",
                    (str(uuid.uuid4()), p["ticker"], str(p["from_fact_id"]),
                     now, f"backfill auto-promote from {p['parent_ticker']} {p['via']}"),
                )
    logger.info("auto_promote_adjacent: %d promoted, %d skipped",
                len(promoted), len(skipped))
    return {
        "step":     "auto_promote_adjacent",
        "applied":  apply,
        "promoted": promoted,
        "n_promoted": len(promoted),
        "n_skipped":  len(skipped),
        "sample_skipped": skipped[:10],
    }


# ── 2. SPY + watchlist 5y EOD → market_data_daily ──────────────────


def backfill_eod_prices(
    tickers: List[str],
    period: str = "5y",
    apply: bool = False,
) -> Dict[str, Any]:
    """yfinance batch fetch + upsert. Reads existing rows so UI sees
    history immediately for benchmark calc + future technical chart."""
    if not tickers:
        return {"step": "backfill_eod", "n_tickers": 0, "n_rows": 0}
    n_inserted = 0
    n_already = 0
    per_ticker: Dict[str, int] = {}
    if not apply:
        logger.info("DRY-RUN backfill_eod_prices for %d tickers (period=%s)",
                    len(tickers), period)
        return {
            "step": "backfill_eod", "applied": False,
            "n_tickers": len(tickers), "tickers": tickers,
            "estimated_rows": len(tickers) * 1300,   # ~250 trading days * 5y
        }
    try:
        import yfinance as yf
    except ImportError:
        return {"step": "backfill_eod", "error": "yfinance not installed"}
    ensure_schema()
    with connect() as conn:
        for t in tickers:
            try:
                df = yf.Ticker(t).history(period=period, interval="1d", auto_adjust=False)
                if df is None or df.empty:
                    per_ticker[t] = 0
                    continue
                t_inserted = 0
                t_already = 0
                for idx, row in df.iterrows():
                    try:
                        date_str = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)[:10]
                    except Exception:
                        continue
                    cur = conn.execute(
                        "SELECT 1 FROM market_data_daily "
                        "WHERE symbol=? AND market='US' AND trade_date=?",
                        (t, date_str),
                    )
                    if cur.fetchone():
                        t_already += 1
                        continue
                    conn.execute(
                        "INSERT INTO market_data_daily "
                        "(symbol, market, trade_date, open, high, low, close, "
                        " adjusted_close, volume, source, fetched_at) "
                        "VALUES (?, 'US', ?, ?, ?, ?, ?, ?, ?, "
                        " 'yfinance-backfill', ?)",
                        (t, date_str,
                         _f(row.get("Open")), _f(row.get("High")),
                         _f(row.get("Low")),  _f(row.get("Close")),
                         _f(row.get("Adj Close")) or _f(row.get("Close")),
                         _i(row.get("Volume")),
                         datetime.now(timezone.utc).isoformat()),
                    )
                    t_inserted += 1
                per_ticker[t] = t_inserted
                n_inserted += t_inserted
                n_already += t_already
                logger.info("EOD %s: %d new, %d already had", t, t_inserted, t_already)
            except Exception as exc:
                logger.warning("EOD %s failed: %s", t, exc)
                per_ticker[t] = -1
    return {
        "step": "backfill_eod", "applied": apply,
        "n_tickers":  len(tickers),
        "n_inserted": n_inserted,
        "n_already":  n_already,
        "per_ticker": per_ticker,
    }


def _f(v) -> Optional[float]:
    try:
        if v is None: return None
        f = float(v)
        return f if f == f else None  # NaN check
    except (TypeError, ValueError):
        return None


def _i(v) -> Optional[int]:
    try:
        if v is None: return None
        i = int(float(v))
        return i if i >= 0 else None
    except (TypeError, ValueError):
        return None


# ── 3. Re-extract 10-K for missing fact types ──────────────────────


_EXPECTED_FACT_TYPES = ("business_summary", "segment", "risk", "competitor", "customer", "supplier")


def reextract_gaps(
    tickers: List[str], apply: bool = False,
    base_url: str = "http://127.0.0.1:8001",
) -> Dict[str, Any]:
    """For each ticker, count which fact_types have ≥1 row. If <4 of
    the 6 expected types are present, queue a regenerate for ALL types
    (cheaper to re-run all than per-type since 10-K is sliced once)."""
    ensure_schema()
    queued: List[Dict[str, Any]] = []
    skipped: List[str] = []
    results: Dict[str, Any] = {}
    with connect() as conn:
        for t in tickers:
            present = set()
            rows = conn.execute(
                "SELECT DISTINCT fact_type FROM stock_anchored_facts WHERE ticker=?",
                (t,),
            ).fetchall()
            for r in rows:
                present.add(r["fact_type"])
            missing = [ft for ft in _EXPECTED_FACT_TYPES if ft not in present]
            if len(present) >= 4 or len(missing) <= 2:
                skipped.append(f"{t}: {len(present)} types present, skipping")
                continue
            queued.append({"ticker": t, "present": sorted(present), "missing": missing})
    if not apply:
        return {
            "step": "reextract_gaps", "applied": False,
            "n_queued": len(queued), "queued": queued,
            "n_skipped": len(skipped),
        }
    # Hit the regenerate endpoint
    for q in queued:
        t = q["ticker"]
        url = f"{base_url}/api/stock/{t}/anchored/regenerate"
        try:
            req = urllib.request.Request(url, method="POST")
            with urllib.request.urlopen(req, timeout=180) as resp:
                results[t] = json.loads(resp.read().decode())
            logger.info("reextract %s: ok", t)
        except Exception as exc:
            results[t] = {"error": str(exc)}
            logger.warning("reextract %s failed: %s", t, exc)
    return {
        "step": "reextract_gaps", "applied": apply,
        "n_queued": len(queued),
        "results": results,
    }


# ── Top-level orchestrator ─────────────────────────────────────────


def run_all(apply: bool = False, skip_steps: Set[int] = None) -> Dict[str, Any]:
    skip_steps = skip_steps or set()
    summary: Dict[str, Any] = {"started_at": datetime.now(timezone.utc).isoformat()}

    # Always read state for reporting
    with connect() as conn:
        cores = [r["ticker"] for r in conn.execute(
            "SELECT ticker FROM user_watchlist WHERE tier='core' ORDER BY ticker"
        )]
        all_watchlist = [r["ticker"] for r in conn.execute(
            "SELECT ticker FROM user_watchlist ORDER BY ticker"
        )]
    summary["cores"] = cores

    if 1 not in skip_steps:
        summary["step1_adjacent"] = auto_promote_adjacent(apply=apply)
    if 2 not in skip_steps:
        # SPY + all watchlist tickers (incl any newly-promoted Adjacent)
        with connect() as conn:
            current_watchlist = [r["ticker"] for r in conn.execute(
                "SELECT ticker FROM user_watchlist ORDER BY ticker"
            )]
        eod_tickers = sorted(set(["SPY", "QQQ", "VTI"] + current_watchlist))
        summary["step2_eod"] = backfill_eod_prices(eod_tickers, "5y", apply=apply)
    if 3 not in skip_steps:
        summary["step3_reextract"] = reextract_gaps(cores, apply=apply)

    summary["finished_at"] = datetime.now(timezone.utc).isoformat()
    return summary


def _print_summary(s: Dict[str, Any]) -> None:
    print()
    print("=" * 60)
    print("BACKFILL SUMMARY")
    print("=" * 60)
    print(f"started:  {s['started_at']}")
    print(f"finished: {s['finished_at']}")
    print(f"cores:    {s['cores']}")
    if "step1_adjacent" in s:
        s1 = s["step1_adjacent"]
        print(f"\n[1] Adjacent auto-promote ({'APPLIED' if s1['applied'] else 'DRY'})"
              f": +{s1['n_promoted']} new (skipped {s1['n_skipped']})")
        for p in s1["promoted"][:10]:
            print(f"    {p['ticker']:6s} ← {p['parent_ticker']:6s} via {p['via']}/{p['name'][:40]}")
    if "step2_eod" in s:
        s2 = s["step2_eod"]
        if s2.get("applied"):
            print(f"\n[2] EOD prices ({'APPLIED'}): {s2['n_inserted']} new rows, "
                  f"{s2['n_already']} already")
            for t, n in s2.get("per_ticker", {}).items():
                print(f"    {t:6s}: {n} rows")
        else:
            print(f"\n[2] EOD prices (DRY): {s2['n_tickers']} tickers, "
                  f"~{s2['estimated_rows']} estimated rows")
    if "step3_reextract" in s:
        s3 = s["step3_reextract"]
        print(f"\n[3] 10-K re-extract ({'APPLIED' if s3['applied'] else 'DRY'})"
              f": {s3['n_queued']} tickers queued")
        for q in s3.get("queued", [])[:10]:
            print(f"    {q['ticker']:6s} missing: {q['missing']}")
    print()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--apply", action="store_true",
                   help="Actually write changes (default: dry-run)")
    p.add_argument("--skip", default="",
                   help="Comma-separated step numbers to skip (1,2,3)")
    args = p.parse_args()
    skip = {int(x) for x in args.skip.split(",") if x.strip()}
    summary = run_all(apply=args.apply, skip_steps=skip)
    _print_summary(summary)
    return 0 if "error" not in str(summary) else 1


if __name__ == "__main__":
    sys.exit(main())
