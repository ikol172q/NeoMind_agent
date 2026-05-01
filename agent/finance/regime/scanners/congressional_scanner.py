"""Congressional STOCK Act scanner.

Pulls from public S3 JSON datasets maintained by housestockwatcher.com
and senatestockwatcher.com — these aggregate House + Senate periodic
transaction reports (PTRs) into clean JSON, updated daily.

Data sources:
  House:  https://house-stock-watcher-data.s3-us-west-2.amazonaws.com/data/all_transactions.json
  Senate: https://senate-stock-watcher-data.s3-us-west-2.amazonaws.com/aggregate/all_transactions.json

Each transaction:
  representative   : "Pelosi, Nancy"
  ticker          : "NVDA"
  transaction_date: "2026-04-15"
  type            : "purchase" / "sale" / "exchange"
  amount          : "$1,001 - $15,000"  (range, per STOCK Act format)
  ...

Signal severity:
  - high:  ≥3 congressmembers same-direction within 14d on watchlist ticker
  - high:  any single trade in user's watchlist with amount range ≥$100k
  - med:   single trade in watchlist (any amount)
  - skip:  trade not in watchlist + supply chain

Caveats (must surface):
  - 45-day disclosure window — data is stale
  - amounts are RANGES, not exact ($1k–$15k bracket etc.)
  - no shorts, no options, no private investments visible
  - some members file late or dispute filings
"""
from __future__ import annotations

import gzip
import json
import logging
import re
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# NOTE 2026-05-01: original housestockwatcher / senatestockwatcher
# S3 buckets returned 403 — likely made private. Tried alternatives
# (capitoltrades.com RSS, GitHub mirrors, Quiver Quant) — all paywalled
# or rate-limited. Real data sources currently in use:
#   1. raw House XML zip — http://disclosures-clerk.house.gov/public_disc/financial-pdfs/2026FD.zip
#      → contains 2026FD.xml + thousands of PDF PTRs.  XML has only
#        member-name + filing-date; we'd need to parse the PDFs to
#        extract ticker / amount / direction.  Skip for now.
#   2. Senate eFD search — efdsearch.senate.gov needs cookies + CSRF.
#
# Easiest stable source: Quiver Quantitative's free CSV (paid for
# real-time but historical is free): keep as TODO until confirmed.
HOUSE_URL = (
    "https://house-stock-watcher-data.s3-us-west-2.amazonaws.com/"
    "data/all_transactions.json"
)
SENATE_URL = (
    "https://senate-stock-watcher-data.s3-us-west-2.amazonaws.com/"
    "aggregate/all_transactions.json"
)
# Backup mirror — sometimes works when primary is throttled
HOUSE_URL_MIRROR = (
    "https://raw.githubusercontent.com/jeremiak/Disclosed-House-Stock-Watcher/master/"
    "data/all_transactions.json"
)
SENATE_URL_MIRROR = (
    "https://raw.githubusercontent.com/jeremiak/Disclosed-Senate-Stock-Watcher/master/"
    "data/all_transactions.json"
)


def _http_get_json(url: str, *, timeout: int = 30) -> Any:
    req = urllib.request.Request(url, headers={
        "User-Agent":      "NeoMind Fin Research neomind@example.com",
        "Accept-Encoding": "gzip, deflate",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        if resp.headers.get('Content-Encoding') == 'gzip':
            raw = gzip.decompress(raw)
        return json.loads(raw.decode())


def _ticker_universe() -> set:
    """Watchlist + supply-chain expansion = our scanner universe."""
    from agent.finance.regime.signals import (
        list_watchlist, expand_supply_chain,
    )
    user = [w["ticker"] for w in list_watchlist()]
    return set(user) | set(expand_supply_chain(user))


def _normalize_ticker(t: Optional[str]) -> Optional[str]:
    if not t:
        return None
    t = t.strip().upper()
    # Strip share class suffix (.A, .B, /A, /B)
    t = re.sub(r"[./]([A-Z])$", "", t)
    if not t or t == "N/A" or t == "--":
        return None
    return t


def _already_emitted_tx(rep: str, ticker: str, tx_type: str, tx_date: str) -> bool:
    from agent.finance.persistence import connect
    with connect() as conn:
        cur = conn.execute(
            "SELECT event_id FROM signal_events "
            "WHERE scanner_name = 'stock_act' AND ticker = ? "
            "  AND signal_type = ? AND date(source_timestamp) = ? "
            "  AND title LIKE ? "
            "LIMIT 1",
            (ticker, f"stock_act_{tx_type}", tx_date, f"%{rep[:30]}%"),
        )
        return cur.fetchone() is not None


def _amount_severity(amount_str: Optional[str]) -> str:
    """Map STOCK Act amount range string to severity."""
    if not amount_str:
        return "med"
    s = amount_str.lower().replace(",", "").replace("$", "")
    # Look for upper bound
    nums = re.findall(r"\d+(?:\.\d+)?(?:m|k)?", s)
    if not nums:
        return "med"
    upper = nums[-1]
    if upper.endswith("m"):
        v = float(upper[:-1]) * 1_000_000
    elif upper.endswith("k"):
        v = float(upper[:-1]) * 1_000
    else:
        v = float(upper)
    if v >= 100_000:
        return "high"
    return "med"


def _fmt_amount(amount_str: Optional[str]) -> str:
    if not amount_str:
        return ""
    return amount_str.strip()


def run_congressional_scan(
    *,
    lookback_days: int = 30,
    max_per_chamber: int = 5000,
) -> Dict[str, Any]:
    """Fetch House + Senate transactions, emit signals for any in
    watchlist universe within the lookback window."""
    from agent.finance.regime.signals import emit_event

    t0 = time.monotonic()
    universe = _ticker_universe()
    if not universe:
        return {"scanner": "stock_act", "skip": "empty_watchlist"}

    cutoff_iso = (date.today() - timedelta(days=lookback_days)).isoformat()
    n_emitted = 0
    n_seen_house = 0
    n_seen_senate = 0
    errors: List[str] = []

    # House — try primary then mirror
    house_data = None
    for url in (HOUSE_URL, HOUSE_URL_MIRROR):
        try:
            house_data = _http_get_json(url)
            if isinstance(house_data, list):
                break
        except Exception as exc:
            logger.warning("house URL %s failed: %s", url, exc)
            continue
    try:
        if isinstance(house_data, list):
            for tx in house_data[-max_per_chamber:]:
                n_seen_house += 1
                tdate = tx.get("transaction_date") or tx.get("disclosure_date") or ""
                if not tdate or tdate < cutoff_iso:
                    continue
                ticker = _normalize_ticker(tx.get("ticker"))
                if not ticker or ticker not in universe:
                    continue
                rep = tx.get("representative") or tx.get("name") or "Unknown"
                tx_type = (tx.get("type") or "").lower().strip()
                if tx_type not in ("purchase", "sale", "exchange",
                                    "sale_partial", "sale_full"):
                    continue
                if _already_emitted_tx(rep, ticker, tx_type, tdate):
                    continue
                amount = _fmt_amount(tx.get("amount"))
                sev = _amount_severity(tx.get("amount"))
                action = "买入" if tx_type == "purchase" else (
                    "卖出" if "sale" in tx_type else "exchange"
                )
                emit_event(
                    "stock_act",
                    signal_type=f"stock_act_{tx_type}",
                    severity=sev,
                    ticker=ticker,
                    title=f"🏛 House: {rep} {action} {ticker} ({amount})",
                    body={
                        "chamber":       "house",
                        "representative": rep,
                        "transaction_type": tx_type,
                        "amount_range":   amount,
                        "transaction_date": tdate,
                        "disclosure_date":  tx.get("disclosure_date"),
                    },
                    source_url=tx.get("ptr_link") or
                        "https://disclosures-clerk.house.gov/PublicDisclosure/FinancialDisclosure",
                    source_timestamp=tdate,
                )
                n_emitted += 1
    except Exception as exc:
        logger.exception("house fetch failed")
        errors.append(f"house: {exc}")

    # Senate — try primary then mirror
    senate_data = None
    for url in (SENATE_URL, SENATE_URL_MIRROR):
        try:
            senate_data = _http_get_json(url)
            if isinstance(senate_data, list):
                break
        except Exception as exc:
            logger.warning("senate URL %s failed: %s", url, exc)
            continue
    try:
        if isinstance(senate_data, list):
            for tx in senate_data[-max_per_chamber:]:
                n_seen_senate += 1
                tdate = tx.get("transaction_date") or tx.get("disclosure_date") or ""
                if not tdate or tdate < cutoff_iso:
                    continue
                ticker = _normalize_ticker(tx.get("ticker"))
                if not ticker or ticker not in universe:
                    continue
                # Senate uses "senator"
                rep = tx.get("senator") or tx.get("name") or "Unknown"
                tx_type = (tx.get("type") or "").lower().strip()
                # Senate type values: "Purchase", "Sale (Full)", "Sale (Partial)", "Exchange"
                tx_type_clean = re.sub(r"[^a-z]+", "_", tx_type).strip("_")
                if not tx_type_clean:
                    continue
                if _already_emitted_tx(rep, ticker, tx_type_clean, tdate):
                    continue
                amount = _fmt_amount(tx.get("amount"))
                sev = _amount_severity(tx.get("amount"))
                action = "买入" if "purchase" in tx_type else (
                    "卖出" if "sale" in tx_type else "exchange"
                )
                emit_event(
                    "stock_act",
                    signal_type=f"stock_act_{tx_type_clean}",
                    severity=sev,
                    ticker=ticker,
                    title=f"🏛 Senate: {rep} {action} {ticker} ({amount})",
                    body={
                        "chamber":       "senate",
                        "senator":       rep,
                        "transaction_type": tx_type,
                        "amount_range":   amount,
                        "transaction_date": tdate,
                        "disclosure_date":  tx.get("disclosure_date"),
                    },
                    source_url=tx.get("ptr_link") or
                        "https://efdsearch.senate.gov/search/",
                    source_timestamp=tdate,
                )
                n_emitted += 1
    except Exception as exc:
        logger.exception("senate fetch failed")
        errors.append(f"senate: {exc}")

    return {
        "scanner":        "stock_act",
        "lookback_days":  lookback_days,
        "n_house_seen":   n_seen_house,
        "n_senate_seen":  n_seen_senate,
        "n_emitted":      n_emitted,
        "errors":         errors,
        "took_ms":        int((time.monotonic() - t0) * 1000),
    }
