"""Recent SEC material filings (8-K / 6-K) — the FRESHNESS layer.

Goal-1 dimension #3 ("最新动态/事件"): the single authoritative, dated, free,
universal source for "what just happened" at a company is its SEC 8-K (US) /
6-K (foreign private issuer) material-event filings — earnings, guidance, exec
changes, M&A, material agreements. Every holding files them; each is dated.

US 8-K filings carry structured `items` codes (2.02 = results, 5.02 = officer
change, 1.01 = material agreement …) which we decode into a label so the user
sees the event TYPE at a glance. Foreign 6-K has no item taxonomy → we show
date + a link to the filing itself.

DB-sourced via data.sec.gov (no yfinance). Cached; every row carries its
filing date (freshness). CIK resolved from SEC's authoritative ticker map.
"""
from __future__ import annotations

import json
import logging
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter

from agent.finance.persistence import connect

logger = logging.getLogger(__name__)

# SEC requires a non-empty UA. Generic so we don't leak user PII to SEC logs
# (matches agent/data_sources/sec_edgar._USER_AGENT).
_UA = {"User-Agent": "NeoMind Research Agent contact@neomind.local"}
_TTL_S = 6 * 3600.0

# 8-K item code → concise Chinese label (only the ones that matter to a holder)
_ITEM_LABELS = {
    "1.01": "重大协议", "1.02": "协议终止", "2.01": "资产收购/处置",
    "2.02": "业绩(财报)", "2.03": "新增债务", "2.05": "重组成本",
    "3.01": "退市警示", "3.02": "增发股份", "4.01": "更换审计",
    "5.01": "控制权变更", "5.02": "高管/董事变动", "5.03": "章程修订",
    "5.07": "股东投票", "7.01": "FD 披露", "8.01": "其他事件",
    "9.01": "财务附件",
}
_NOISE_ITEMS = {"9.01"}  # attachment marker — drop from the label unless it's alone

_cik_map: Dict[str, str] = {}


def _resolve_cik(ticker: str) -> Optional[str]:
    """ticker → 10-digit CIK via SEC's authoritative company_tickers.json (cached)."""
    global _cik_map
    if not _cik_map:
        try:
            data = json.load(urllib.request.urlopen(
                urllib.request.Request("https://www.sec.gov/files/company_tickers.json", headers=_UA), timeout=20))
            _cik_map = {v["ticker"].upper(): f"{int(v['cik_str']):010d}" for v in data.values()}
        except Exception as e:
            logger.warning("recent_filings: company_tickers.json fetch failed: %s", e)
            return None
    return _cik_map.get(ticker.upper())


def _decode_items(items: str) -> str:
    if not items:
        return ""
    codes = [c.strip() for c in items.split(",") if c.strip()]
    labels = [_ITEM_LABELS.get(c, c) for c in codes if c not in _NOISE_ITEMS]
    if not labels and codes:  # only 9.01 etc.
        labels = [_ITEM_LABELS.get(codes[0], codes[0])]
    return " · ".join(dict.fromkeys(labels))  # dedupe, keep order


def _ensure_table(conn) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS recent_filings ("
        " ticker TEXT PRIMARY KEY, items_json TEXT, fetched_at TEXT)"
    )


def fetch_recent_filings(ticker: str, lookback_days: int = 150, limit: int = 8) -> List[Dict[str, Any]]:
    """Live fetch of recent 8-K/6-K from SEC submissions. Each row: form, date,
    event-type label, item codes, URL. Returns [] on failure (honest empty)."""
    ticker = ticker.upper().strip()
    cik = _resolve_cik(ticker)
    if not cik:
        return []
    cik_int = int(cik)
    try:
        d = json.load(urllib.request.urlopen(
            urllib.request.Request(f"https://data.sec.gov/submissions/CIK{cik}.json", headers=_UA), timeout=20))
    except Exception as e:
        logger.warning("recent_filings(%s): submissions fetch failed: %s", ticker, e)
        return []
    r = d["filings"]["recent"]
    n = len(r["form"])
    items_arr = r.get("items", [""] * n)
    doc_arr = r.get("primaryDocument", [""] * n)
    desc_arr = r.get("primaryDocDescription", [""] * n)
    cutoff = (datetime.now(timezone.utc).date() - timedelta(days=lookback_days)).isoformat()
    out: List[Dict[str, Any]] = []
    for i in range(n):
        form = r["form"][i]
        if form not in ("8-K", "6-K", "8-K/A"):
            continue
        fdate = r["filingDate"][i]
        if fdate < cutoff:
            continue
        acc = r["accessionNumber"][i].replace("-", "")
        doc = doc_arr[i]
        url = (f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc}/{doc}" if doc
               else f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type={form}")
        label = _decode_items(items_arr[i]) or (desc_arr[i] if form.startswith("6-K") else "")
        out.append({
            "form": form, "date": fdate, "event": label or form,
            "items": items_arr[i], "url": url,
        })
        if len(out) >= limit:
            break
    return out


def get_recent_filings(ticker: str, refresh: bool = False) -> Dict[str, Any]:
    ticker = ticker.upper().strip()
    now = datetime.now(timezone.utc)
    with connect() as conn:
        _ensure_table(conn)
        row = conn.execute("SELECT items_json, fetched_at FROM recent_filings WHERE ticker=?", (ticker,)).fetchone()
    if row and not refresh:
        try:
            age = (now - datetime.fromisoformat(row["fetched_at"])).total_seconds()
        except Exception:
            age = 1e9
        if age < _TTL_S:
            return {"ticker": ticker, "filings": json.loads(row["items_json"] or "[]"),
                    "fetched_at": row["fetched_at"], "source": "cache"}
    filings = fetch_recent_filings(ticker)
    iso = now.isoformat()
    with connect() as conn:
        _ensure_table(conn)
        conn.execute(
            "INSERT INTO recent_filings (ticker, items_json, fetched_at) VALUES (?,?,?) "
            "ON CONFLICT(ticker) DO UPDATE SET items_json=excluded.items_json, fetched_at=excluded.fetched_at",
            (ticker, json.dumps(filings, ensure_ascii=False), iso))
    return {"ticker": ticker, "filings": filings, "fetched_at": iso, "source": "live"}


def build_recent_filings_router() -> APIRouter:
    router = APIRouter(prefix="/api/stock", tags=["recent-filings"])

    @router.get("/{ticker}/recent_filings")
    def recent(ticker: str, refresh: bool = False) -> Dict[str, Any]:
        return get_recent_filings(ticker, refresh=refresh)

    return router
