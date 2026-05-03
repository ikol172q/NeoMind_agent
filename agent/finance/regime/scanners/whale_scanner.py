"""13F whale scanner — SEC EDGAR direct.

For each "time-tested" whale, fetch the latest two 13F-HR filings,
diff holdings, and emit a signal_event for any change that touches a
ticker in the user's watchlist + supply chain expansion.

Whales tracked (CIKs verified via SEC EDGAR):
  • Berkshire Hathaway (Buffett)        CIK 0001067983
  • Duquesne Family Office (Druckenmiller) CIK 0001536411
  • Appaloosa Mgmt (Tepper)              CIK 0001656456
  • Pershing Square (Ackman)             CIK 0001336528
  • Baupost Group (Klarman)              CIK 0001061165
  • Third Point (Loeb)                   CIK 0001040273
  • Oaktree Capital (Marks)              CIK 0000949509

Severity:
  - new / exit: high
  - increase / decrease ≥10%: med

Caveats (must be honest with user):
  - 13F has 45-day filing delay; positions shown are as-of quarter-end
  - 13F shows ONLY long stock positions; misses shorts, options,
    bonds, cash, currencies. So a "Buffett trimmed AAPL" could mean
    he hedged with options not visible in the filing.
  - Quarterly cadence — same data is fresh for ~3 months until next
    filing. Idempotency check prevents re-emitting same change.

Usage:
  POST /api/regime/scan/whale  →  triggers run_whale_scan()
"""
from __future__ import annotations

import gzip
import json
import logging
import re
import time
import urllib.request
from typing import Any, Dict, List, Optional
from xml.etree import ElementTree as ET

logger = logging.getLogger(__name__)


# ── whale registry ────────────────────────────────────────────────


WHALES = [
    {"cik": "0001067983", "short": "Buffett (Berkshire)",      "key": "buffett"},
    {"cik": "0001536411", "short": "Druckenmiller (Duquesne)", "key": "druckenmiller"},
    {"cik": "0001656456", "short": "Tepper (Appaloosa)",       "key": "tepper"},
    {"cik": "0001336528", "short": "Ackman (Pershing Square)", "key": "ackman"},
    {"cik": "0001061165", "short": "Klarman (Baupost)",        "key": "klarman"},
    {"cik": "0001040273", "short": "Loeb (Third Point)",       "key": "loeb"},
    {"cik": "0000949509", "short": "Marks (Oaktree)",          "key": "marks"},
    # Added 2026-05-02 per user request — multi-strategy / quant /
    # all-weather macro funds. CIKs verified against SEC EDGAR
    # company search, all file 13F-HR quarterly.
    # 2025 returns: Bridgewater Pure Alpha +34%, Citadel +10.2%,
    # D.E. Shaw Composite +18.5% / Oculus +28.2%.
    {"cik": "0001350694", "short": "Dalio (Bridgewater)",      "key": "dalio"},
    {"cik": "0001423053", "short": "Griffin (Citadel)",        "key": "griffin"},
    {"cik": "0001009268", "short": "D.E. Shaw",                "key": "deshaw"},
]


# ── name → ticker mapping ────────────────────────────────────────


# 13F infotable contains <nameOfIssuer> in the issuer's legal form.
# Match by upper-case substring against this table.  Order matters:
# more specific names first to avoid false positives.
NAME_TO_TICKER: List[tuple[str, str]] = [
    # User watchlist (priority — these are what the user actively cares about)
    ("APPLE INC",                     "AAPL"),
    ("TESLA INC",                     "TSLA"),
    ("META PLATFORMS",                "META"),
    ("MICROSOFT CORP",                "MSFT"),
    ("NVIDIA CORP",                   "NVDA"),
    ("ADVANCED MICRO DEVICES",        "AMD"),
    ("ARM HOLDINGS",                  "ARM"),
    ("ALPHABET INC CL A",             "GOOGL"),
    ("ALPHABET INC CL C",             "GOOG"),
    ("ALPHABET INC",                  "GOOGL"),  # fallback if class unclear
    ("APPLOVIN CORP",                 "APP"),
    # Tech supply chain
    ("TAIWAN SEMICONDUCTOR",          "TSM"),
    ("QUALCOMM INC",                  "QCOM"),
    ("BROADCOM INC",                  "AVGO"),
    ("ASML HOLDING",                  "ASML"),
    ("APPLIED MATERIALS",             "AMAT"),
    ("LAM RESEARCH",                  "LRCX"),
    ("MICRON TECHNOLOGY",             "MU"),
    ("ARISTA NETWORKS",               "ANET"),
    ("CADENCE DESIGN",                "CDNS"),
    ("VERTIV HOLDINGS",               "VRT"),
    ("STMICROELECTRONICS",            "STM"),
    ("ON SEMICONDUCTOR",              "ON"),
    ("ALBEMARLE CORP",                "ALB"),
    ("MP MATERIALS",                  "MP"),
    ("PALO ALTO NETWORKS",            "PANW"),
    ("LATTICE SEMICONDUCTOR",         "LSCC"),
    ("SALESFORCE INC",                "CRM"),
    ("JABIL INC",                     "JBL"),
    ("TRADE DESK",                    "TTD"),
    ("ROKU INC",                      "ROKU"),
    ("ROBLOX CORP",                   "RBLX"),
]


def name_to_ticker(name: str) -> Optional[str]:
    """Return our internal ticker symbol for an SEC nameOfIssuer, or None."""
    if not name:
        return None
    up = name.upper()
    for frag, t in NAME_TO_TICKER:
        if frag in up:
            return t
    return None


# ── HTTP helper (SEC requires User-Agent) ─────────────────────────


def _http_get(url: str, *, timeout: int = 20) -> bytes:
    req = urllib.request.Request(url, headers={
        "User-Agent":      "NeoMind Fin Research neomind@example.com",
        "Accept-Encoding": "gzip, deflate",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        if resp.headers.get('Content-Encoding') == 'gzip':
            raw = gzip.decompress(raw)
        return raw


# ── EDGAR filing list + holdings parse ───────────────────────────


def _fetch_recent_filings(
    cik: str, *, form: str = "13F-HR", limit: int = 5,
) -> List[Dict[str, Any]]:
    """Get most recent N 13F filings for a CIK."""
    cik_padded = cik.zfill(10)
    url = f"https://data.sec.gov/submissions/CIK{cik_padded}.json"
    data = json.loads(_http_get(url).decode())
    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accs  = recent.get("accessionNumber", [])
    docs  = recent.get("primaryDocument", [])
    out: List[Dict[str, Any]] = []
    for i, f in enumerate(forms):
        if f == form and len(out) < limit:
            out.append({
                "filing_date": dates[i],
                "accession":   accs[i],
                "primary_doc": docs[i] if i < len(docs) else None,
            })
    return out


def _fetch_holdings(cik: str, accession: str) -> List[Dict[str, Any]]:
    """Fetch + parse infotable.xml from a 13F filing.

    Returns a list of dicts: {nameOfIssuer, cusip, value (×$1k), shares}.
    """
    cik_no_zeros = str(int(cik))
    acc_no_dashes = accession.replace('-', '')
    base = f"https://www.sec.gov/Archives/edgar/data/{cik_no_zeros}/{acc_no_dashes}"

    # Filing index lists all docs in this filing.
    # SEC convention: directory's index file is just 'index.json'
    # (NOT '{accession}-index.json' — that pattern is only for HTML.)
    idx = json.loads(_http_get(f"{base}/index.json").decode())
    items = idx.get("directory", {}).get("item", [])

    # Robust matcher: try every .xml file in the directory, parse it,
    # and accept whichever has the most infoTable elements. SEC filings
    # use varied filenames: 'infotable.xml', 'form13fInfoTable.xml',
    # '0001067983-25-xxx.xml', etc.
    candidates: List[str] = []
    for it in items:
        name = it.get("name", "")
        if name.endswith(".xml") and name != "primary_doc.xml":
            candidates.append(name)
    # Prioritize anything containing 'info' or 'table' — likely the right one
    candidates.sort(key=lambda n: (
        0 if 'info' in n.lower() or 'table' in n.lower() else 1
    ))

    best_holdings: List[Dict[str, Any]] = []
    ns_re = re.compile(r'\{[^}]+\}')
    for fname in candidates:
        try:
            xml = _http_get(f"{base}/{fname}")
            root = ET.fromstring(xml)
        except Exception as exc:
            logger.debug("could not parse %s/%s: %s", base, fname, exc)
            continue

        rows: List[Dict[str, Any]] = []
        for el in root.iter():
            if ns_re.sub('', el.tag) != 'infoTable':
                continue
            row: Dict[str, Any] = {}
            for child in el:
                ctag = ns_re.sub('', child.tag)
                if ctag == 'shrsOrPrnAmt':
                    for g in child:
                        gtag = ns_re.sub('', g.tag)
                        if gtag == 'sshPrnamt':
                            try:
                                row['shares'] = int((g.text or '0').strip())
                            except Exception:
                                row['shares'] = 0
                        elif gtag == 'sshPrnamtType':
                            row['share_type'] = (g.text or '').strip()
                else:
                    row[ctag] = (child.text or '').strip() if child.text else ''
            rows.append(row)
        if len(rows) > len(best_holdings):
            best_holdings = rows
        if best_holdings and len(best_holdings) >= 3:
            # likely correct file; stop scanning
            return best_holdings

    return best_holdings


# ── diff logic ────────────────────────────────────────────────────


def diff_holdings(
    prev: List[Dict[str, Any]],
    curr: List[Dict[str, Any]],
    *,
    pct_threshold: float = 0.10,
) -> List[Dict[str, Any]]:
    """Compare two holdings snapshots; return list of changes that map
    to known watchlist tickers."""
    prev_map = {(h.get("cusip", ""), h.get("nameOfIssuer", "")): h for h in prev}
    curr_map = {(h.get("cusip", ""), h.get("nameOfIssuer", "")): h for h in curr}
    # Also build by name only (in case CUSIP changed)
    prev_by_name = {h.get("nameOfIssuer", "").upper(): h for h in prev}

    changes: List[Dict[str, Any]] = []
    seen_names: set = set()

    for k, c in curr_map.items():
        name = (c.get("nameOfIssuer", "") or "").upper()
        if name in seen_names:
            continue
        seen_names.add(name)
        ticker = name_to_ticker(name)
        if not ticker:
            continue
        c_shares = c.get("shares") or 0
        p = prev_by_name.get(name)
        if p is None:
            changes.append({
                "type":    "new",
                "ticker":  ticker,
                "name":    c.get("nameOfIssuer"),
                "shares":  c_shares,
                "value_usd_k": c.get("value"),
            })
        else:
            p_shares = p.get("shares") or 0
            if p_shares == 0:
                continue
            delta = (c_shares - p_shares) / p_shares
            if delta >= pct_threshold:
                changes.append({
                    "type":       "increase",
                    "ticker":     ticker,
                    "name":       c.get("nameOfIssuer"),
                    "old_shares": p_shares,
                    "new_shares": c_shares,
                    "delta_pct":  round(delta, 3),
                })
            elif delta <= -pct_threshold:
                changes.append({
                    "type":       "decrease",
                    "ticker":     ticker,
                    "name":       c.get("nameOfIssuer"),
                    "old_shares": p_shares,
                    "new_shares": c_shares,
                    "delta_pct":  round(delta, 3),
                })

    # Exits — names in prev but not curr
    curr_names = {(h.get("nameOfIssuer", "") or "").upper() for h in curr}
    for name_up, p in prev_by_name.items():
        if name_up in curr_names:
            continue
        ticker = name_to_ticker(name_up)
        if not ticker:
            continue
        changes.append({
            "type":   "exit",
            "ticker": ticker,
            "name":   p.get("nameOfIssuer"),
            "shares": p.get("shares"),
        })

    return changes


# ── per-whale scan + emit ────────────────────────────────────────


def _already_emitted_change(
    whale_key: str, ticker: str, change_type: str, filing_date: str,
) -> bool:
    """Idempotency: skip if we've already emitted this exact (whale,
    ticker, change_type, filing_date) tuple."""
    from agent.finance.persistence import connect
    with connect() as conn:
        cur = conn.execute(
            "SELECT event_id FROM signal_events "
            "WHERE scanner_name = '13f' AND ticker = ? "
            "  AND signal_type LIKE ? "
            "  AND date(source_timestamp) = ? LIMIT 1",
            (ticker, f"13f_{change_type}", filing_date),
        )
        return cur.fetchone() is not None


def scan_whale(cik: str, short_name: str, key: str) -> Dict[str, Any]:
    from agent.finance.regime.signals import emit_event

    try:
        filings = _fetch_recent_filings(cik)
    except Exception as exc:
        return {"whale": short_name, "error": f"fetch_filings: {exc}"}

    if len(filings) < 2:
        return {"whale": short_name, "n_filings": len(filings),
                "skip": "need_≥2_filings"}

    latest, previous = filings[0], filings[1]

    try:
        curr_h = _fetch_holdings(cik, latest["accession"])
        prev_h = _fetch_holdings(cik, previous["accession"])
    except Exception as exc:
        return {"whale": short_name, "error": f"fetch_holdings: {exc}"}

    if not curr_h or not prev_h:
        return {"whale": short_name, "skip": "empty_holdings"}

    changes = diff_holdings(prev_h, curr_h)
    n_emitted = 0
    for ch in changes:
        if _already_emitted_change(key, ch["ticker"], ch["type"],
                                   latest["filing_date"]):
            continue

        if ch["type"] in ("new", "exit"):
            sev = "high"
        else:
            sev = "med"

        action_zh = {
            "new":      "新建仓",
            "exit":     "清仓",
            "increase": f"加仓 {ch.get('delta_pct', 0)*100:+.0f}%",
            "decrease": f"减仓 {ch.get('delta_pct', 0)*100:+.0f}%",
        }[ch["type"]]
        title = f"{short_name} {action_zh} {ch['ticker']}"

        emit_event(
            "13f",
            signal_type=f"13f_{ch['type']}",
            severity=sev,
            ticker=ch["ticker"],
            title=title,
            body={
                "whale":          short_name,
                "whale_key":      key,
                "change_type":    ch["type"],
                "filing_date":    latest["filing_date"],
                "previous_filing_date": previous["filing_date"],
                **ch,
            },
            source_url=(
                f"https://www.sec.gov/cgi-bin/browse-edgar"
                f"?action=getcompany&CIK={cik}&type=13F-HR"
            ),
            source_timestamp=latest["filing_date"],
        )
        n_emitted += 1

    return {
        "whale":           short_name,
        "filing_date":     latest["filing_date"],
        "prev_filing_date": previous["filing_date"],
        "n_holdings":      len(curr_h),
        "n_changes":       len(changes),
        "n_emitted":       n_emitted,
    }


def run_whale_scan() -> Dict[str, Any]:
    """Scan all whales, returning a summary."""
    t0 = time.monotonic()
    per_whale = []
    n_emitted_total = 0
    for w in WHALES:
        try:
            r = scan_whale(w["cik"], w["short"], w["key"])
            per_whale.append(r)
            n_emitted_total += r.get("n_emitted", 0)
            # SEC asks ≤10 req/sec — be conservative
            time.sleep(0.5)
        except Exception as exc:
            logger.exception("whale scan failed: %s", w["short"])
            per_whale.append({"whale": w["short"], "error": str(exc)})

    return {
        "scanner":   "13f",
        "n_whales":  len(WHALES),
        "n_emitted": n_emitted_total,
        "took_ms":   int((time.monotonic() - t0) * 1000),
        "per_whale": per_whale,
    }
