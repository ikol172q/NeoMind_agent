"""SEC Form 4 insider trading scanner — pulls from openinsider.com.

Form 4 is the executive-officer / director / 10%-owner disclosure
required within **two business days** of any open-market trade. That
2-day window makes it the freshest signal in our Smart Money stack
(cf. STOCK Act 45 days, 13F 45 days quarterly, House Clerk PDFs
~25-30 days). When a CEO puts personal cash into their own stock,
that's a strong bullish prior — they have access to forward-looking
material non-public information that won't be reflected in the price
for weeks.

Data source: openinsider.com — a public scraping aggregator that
re-renders SEC EDGAR Form 4 filings into a clean HTML table. Two
specific screens we read:
    - /latest-cluster-buys      (≥2 insiders same ticker, last 30d)
    - /latest-insider-purchases-25k (single CEO/CFO buy ≥ $25k)

Why scrape openinsider rather than EDGAR directly:
    - EDGAR's Form 4 ATOM feed is ungrouped — every individual
      filing is a separate entry, no concept of "cluster". To detect
      clusters we'd have to ingest hundreds of filings/day and
      group ourselves. openinsider does this for us.
    - openinsider also filters out 10b5-1 plan sales (mechanical,
      low signal), which is exactly what we'd want anyway.

Caveats (must surface):
    - HTML scrape is fragile — table column order is hardcoded; if
      openinsider redesigns we lose this until the parser is updated.
    - Sells filtered out by design (often planned 10b5-1 exits, not
      a meaningful signal).
"""
from __future__ import annotations

import logging
import re
import time
import urllib.request
from datetime import date, datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


CLUSTER_BUYS_URL = "http://openinsider.com/latest-cluster-buys"
LARGE_CEO_BUYS_URL = "http://openinsider.com/latest-insider-purchases-25k"

_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)


def _http_get(url: str, *, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers={
        "User-Agent": _BROWSER_UA,
        "Accept": "text/html,application/xhtml+xml",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    # openinsider serves latin-1 in some headers; let bs4 normalize.
    return raw.decode("utf-8", errors="replace")


def _parse_value_to_usd(s: str) -> float:
    """Parse '$1,234,567' → 1234567.0. Returns 0.0 on failure."""
    if not s:
        return 0.0
    cleaned = re.sub(r"[^\d.\-]", "", s.strip())
    try:
        return float(cleaned) if cleaned else 0.0
    except ValueError:
        return 0.0


def _parse_qty(s: str) -> int:
    """Parse '+4,822' → 4822, '-1,000' → -1000."""
    if not s:
        return 0
    cleaned = re.sub(r"[^\d.\-]", "", s.strip())
    try:
        return int(float(cleaned)) if cleaned else 0
    except ValueError:
        return 0


def _parse_openinsider_table(html: str) -> List[Dict[str, Any]]:
    """Returns a list of {ticker, company, n_insiders, trade_type, price,
    qty, owned, delta_own_pct, value_usd, trade_date, filing_date}.

    Column order (verified 2026-05-02):
        0  X (action flag)
        1  Filing Date (with timestamp)
        2  Trade Date
        3  Ticker
        4  Company Name
        5  Industry
        6  Ins (# insiders, on cluster pages)
        7  Trade Type ('P - Purchase' / 'S - Sale' / 'OE' / etc)
        8  Price (per share)
        9  Qty (signed)
        10 Owned (post-trade total)
        11 ΔOwn (% change in holding)
        12 Value (total USD)
        13 1d return (post-trade)
        14 1w return
    """
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", class_="tinytable")
    if not table:
        return []
    rows: List[Dict[str, Any]] = []
    for tr in table.find_all("tr")[1:]:  # skip header
        cells = [td.get_text(strip=True).replace("\xa0", " ") for td in tr.find_all("td")]
        if len(cells) < 13:
            continue
        # n_insiders cell present on cluster page; on single-buy page it
        # may be absent. Treat missing as 1.
        try:
            n_insiders = int(cells[6]) if cells[6].isdigit() else 1
        except (ValueError, IndexError):
            n_insiders = 1
        rows.append({
            "filing_date":   cells[1].split()[0] if cells[1] else "",
            "trade_date":    cells[2],
            "ticker":        cells[3],
            "company":       cells[4][:80],
            "industry":      cells[5][:60] if len(cells) > 5 else "",
            "n_insiders":    n_insiders,
            "trade_type":    cells[7] if len(cells) > 7 else "",
            "price":         _parse_value_to_usd(cells[8] if len(cells) > 8 else ""),
            "qty":           _parse_qty(cells[9] if len(cells) > 9 else ""),
            "owned":         _parse_qty(cells[10] if len(cells) > 10 else ""),
            "delta_own_pct": cells[11].strip() if len(cells) > 11 else "",
            "value_usd":     _parse_value_to_usd(cells[12] if len(cells) > 12 else ""),
            # Post-trade return columns (openinsider tracks how the
            # stock moved after the insider bought) — useful sanity
            # check for "did this signal actually pay off?".
            "return_1d":     cells[13].strip() if len(cells) > 13 else "",
            "return_1w":     cells[14].strip() if len(cells) > 14 else "",
        })
    return rows


def _already_emitted(ticker: str, trade_date: str, value_usd: float) -> bool:
    """Per-(ticker, trade_date, value) idempotency. value provides a
    crude tiebreaker for multiple insiders trading the same ticker on
    the same day."""
    from agent.finance.persistence import connect
    rounded_value = int(round(value_usd))
    with connect() as conn:
        cur = conn.execute(
            "SELECT 1 FROM signal_events "
            "WHERE scanner_name = 'insider_form4' "
            "AND ticker = ? "
            "AND date(source_timestamp) = ? "
            "AND CAST(json_extract(body_json, '$.value_usd') AS INTEGER) = ? "
            "LIMIT 1",
            (ticker, trade_date, rounded_value),
        )
        return cur.fetchone() is not None


def _severity(value_usd: float, n_insiders: int) -> str:
    if value_usd >= 1_000_000 or n_insiders >= 5:
        return "high"
    if value_usd >= 100_000 or n_insiders >= 3:
        return "high"
    return "med"


def _format_value(value_usd: float) -> str:
    if value_usd >= 1_000_000:
        return f"${value_usd / 1_000_000:.1f}M"
    if value_usd >= 1_000:
        return f"${value_usd / 1_000:.0f}K"
    return f"${int(value_usd)}"


def run_insider_form4_scan(
    *,
    max_per_screen: int = 50,
) -> Dict[str, Any]:
    """Scan openinsider cluster buys + large single buys, emit
    signal_events for each new (ticker, trade_date, value) tuple.

    Idempotent — already-seen events are skipped via signal_events
    lookup. Daily cron runs cost nothing once caught up.
    """
    from agent.finance.regime.signals import emit_event

    t0 = time.monotonic()
    n_seen = 0
    n_emitted = 0
    errors: List[str] = []

    # Two screens: cluster buys (group signal) + large single CEO buys.
    # Use a (source, url) tag so we can distinguish them in the body
    # and the user can see which screen surfaced each event.
    for screen_name, url in (
        ("cluster_buys", CLUSTER_BUYS_URL),
        ("large_buys",   LARGE_CEO_BUYS_URL),
    ):
        try:
            html = _http_get(url)
        except Exception as exc:
            logger.warning("openinsider %s fetch failed: %s", screen_name, exc)
            errors.append(f"{screen_name}: {exc}")
            continue

        try:
            rows = _parse_openinsider_table(html)
        except Exception as exc:
            logger.exception("openinsider %s parse failed", screen_name)
            errors.append(f"{screen_name} parse: {exc}")
            continue

        for row in rows[:max_per_screen]:
            n_seen += 1
            ticker = row["ticker"]
            trade_date = row["trade_date"]
            value_usd = row["value_usd"]
            # Filter: only buys (P = Purchase). Skip sales / option grants
            # — they're often mechanical and low-signal.
            trade_type = row.get("trade_type", "").upper()
            if not trade_type.startswith("P"):
                continue
            if not ticker or not trade_date or value_usd < 1_000:
                continue
            if _already_emitted(ticker, trade_date, value_usd):
                continue

            n = row["n_insiders"]
            # Cluster signal: many insiders all buying = strong prior.
            # Single-large-buy signal: a CEO putting >$25k of personal
            # cash in is also strong. Distinguish in title.
            if n >= 2:
                title = f"⚪ {ticker}: {n} 内部人共买入 {_format_value(value_usd)} ({trade_date})"
            else:
                title = f"⚪ {ticker}: 内部人买入 {_format_value(value_usd)} @ ${row['price']:.2f} ({trade_date})"

            emit_event(
                "insider_form4",
                signal_type="insider_buy_cluster" if n >= 2 else "insider_buy_single",
                severity=_severity(value_usd, n),
                ticker=ticker,
                title=title,
                body={
                    "company":       row["company"],
                    "industry":      row["industry"],
                    "n_insiders":    n,
                    "trade_type":    row["trade_type"],
                    "price":         row["price"],
                    "qty":           row["qty"],
                    "owned":         row.get("owned", 0),
                    "delta_own_pct": row.get("delta_own_pct", ""),
                    "value_usd":     value_usd,
                    "return_1d":     row.get("return_1d", ""),
                    "return_1w":     row.get("return_1w", ""),
                    "trade_date":    trade_date,
                    "filing_date":   row["filing_date"],
                    "screen":        screen_name,
                },
                # Per-ticker page on openinsider lets the user click
                # through to see all insider activity for that ticker.
                source_url=f"http://openinsider.com/{ticker}",
                source_timestamp=trade_date,
            )
            n_emitted += 1

    return {
        "scanner":    "insider_form4",
        "n_seen":     n_seen,
        "n_emitted":  n_emitted,
        "errors":     errors,
        "took_ms":    int((time.monotonic() - t0) * 1000),
    }
