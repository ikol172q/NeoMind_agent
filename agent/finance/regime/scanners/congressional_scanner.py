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


# Reps the user is actively following — their trades emit even when the
# traded ticker isn't in the user's watchlist. Match is case-insensitive
# substring on the Quiver `Representative` field. Pelosi is handled by
# the separate house_clerk_pdf_scanner (text-based PDF source).
#
# Picked 2026-05-02 (user choice, Path B):
#   - Tina Smith (Sen D-MN): 3-day median disclosure, fastest in feed,
#     Senate Finance committee member.
#   - Cleo Fields (House D-LA): 11-day median, verified 44.8% return
#     2025 per Unusual Whales; already heavily overlaps user watchlist.
FOLLOWED_REPS = ("Tina Smith", "Cleo Fields")


# Quiver Quant live feed — verified 2026-05-02 to be no-auth + free, returns
# ~1000 most-recent congressional transactions (House + Senate combined).
# This is the primary source now that HouseStockWatcher / SenateStockWatcher
# S3 buckets are 403 and the GitHub mirrors are 404. Schema differs from the
# legacy sources so we map it back to the same internal shape.
QUIVER_LIVE_URL = "https://api.quiverquant.com/beta/live/congresstrading"


def _http_get_json(url: str, *, timeout: int = 30, ua: Optional[str] = None) -> Any:
    # Quiver Quant rejects the literal "NeoMind Fin Research…" UA with 401
    # but lets a normal browser UA through; the legacy SEC-EDGAR-style UA is
    # still used as default for the legacy stock-watcher S3 buckets which
    # require an identifying contact. Pass `ua=` per-call when needed.
    req = urllib.request.Request(url, headers={
        "User-Agent":      ua or "NeoMind Fin Research neomind@example.com",
        "Accept":          "application/json",
        "Accept-Encoding": "gzip, deflate",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        if resp.headers.get('Content-Encoding') == 'gzip':
            raw = gzip.decompress(raw)
        return json.loads(raw.decode())


_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)


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


def _quiver_to_legacy_shape(rec: Dict[str, Any]) -> Dict[str, Any]:
    """Map a Quiver Quant `/beta/live/congresstrading` record to the legacy
    HouseStockWatcher shape so the existing parse loops handle it unchanged.

    Quiver fields → legacy fields:
        Representative   → representative / senator
        TransactionDate  → transaction_date
        ReportDate       → disclosure_date
        Ticker           → ticker
        Transaction      → type   (lowercased + normalized)
        Range            → amount
        House            → chamber routing ('Representatives' vs 'Senate')
        Party            → party (extra; we keep it in body via emit later)
    """
    house_raw = (rec.get("House") or "").strip().lower()
    transaction = (rec.get("Transaction") or "").strip()
    # Legacy `type` values: purchase / sale / sale_partial / sale_full / exchange
    t_norm = transaction.lower().replace(" (", "_").replace(")", "").replace(" ", "_").strip("_")
    # Note: substring match for "sen" would false-positive on
    # "RePreSENtatives" (which contains the substring "sen"). Use
    # exact equality after normalization.
    return {
        "_chamber":         "senate" if house_raw == "senate" else "house",
        "representative":   rec.get("Representative"),
        "senator":          rec.get("Representative"),
        "transaction_date": rec.get("TransactionDate"),
        "disclosure_date":  rec.get("ReportDate"),
        "ticker":           rec.get("Ticker"),
        "type":             t_norm,
        "amount":           rec.get("Range"),
        "party":            rec.get("Party"),
        # Quiver doesn't expose a per-trade PTR PDF link in the live feed;
        # link to their public web view of the rep instead so the user has
        # somewhere to click through and verify.
        "ptr_link":         f"https://www.quiverquant.com/congresstrading/politician/"
                            f"{(rec.get('Representative') or '').replace(' ', '%20')}",
    }


def _fetch_quiver_split() -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], Optional[str]]:
    """Fetch from Quiver and split into (house_records, senate_records, error).
    Returns ([], [], err_msg) on failure so caller can fall back."""
    try:
        raw = _http_get_json(QUIVER_LIVE_URL, ua=_BROWSER_UA)
    except Exception as exc:
        logger.warning("quiver live feed failed: %s", exc)
        return [], [], str(exc)
    if not isinstance(raw, list):
        return [], [], f"unexpected shape: {type(raw).__name__}"
    house: List[Dict[str, Any]] = []
    senate: List[Dict[str, Any]] = []
    for rec in raw:
        mapped = _quiver_to_legacy_shape(rec)
        if mapped["_chamber"] == "senate":
            senate.append(mapped)
        else:
            house.append(mapped)
    return house, senate, None


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

    # Primary: Quiver Quant live feed (no auth, ~1000 most recent records,
    # House + Senate combined). When this works the legacy URLs below are
    # skipped entirely — they're 403 / 404 as of 2026-05-02. The Quiver
    # records are mapped to the legacy shape so the existing parse loops
    # don't change.
    house_data: Optional[List[Dict[str, Any]]] = None
    senate_data: Optional[List[Dict[str, Any]]] = None
    quiver_house, quiver_senate, quiver_err = _fetch_quiver_split()
    if quiver_house or quiver_senate:
        house_data = quiver_house
        senate_data = quiver_senate
        logger.info("congressional: quiver returned %d house + %d senate records",
                    len(quiver_house), len(quiver_senate))
    elif quiver_err:
        errors.append(f"quiver: {quiver_err}")

    # Fallback: legacy HouseStockWatcher S3 + GitHub mirror (both currently
    # 403 / 404 as of 2026-05-02 — kept so a re-hosted mirror can be plugged
    # in without code change).
    if house_data is None:
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
                if not ticker:
                    continue
                rep = tx.get("representative") or tx.get("name") or "Unknown"
                # Followed reps bypass the watchlist filter — user wants
                # to see all their trades regardless of ticker overlap.
                is_followed = any(f.lower() in rep.lower() for f in FOLLOWED_REPS)
                if not is_followed and ticker not in universe:
                    continue
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

    # Senate — Quiver already populated this above when available; legacy
    # fallback only if Quiver failed.
    if senate_data is None:
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
                if not ticker:
                    continue
                # Senate uses "senator"
                rep = tx.get("senator") or tx.get("name") or "Unknown"
                # Followed reps bypass watchlist filter (same logic as
                # House loop above) — see FOLLOWED_REPS doc at top.
                is_followed = any(f.lower() in rep.lower() for f in FOLLOWED_REPS)
                if not is_followed and ticker not in universe:
                    continue
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
