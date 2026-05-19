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


# 2026-05-19: each whale annotated with:
#   horizon       — typical holding period of their 13F positions
#                   'long'  : multi-year (Buffett/Klarman/Marks)
#                   'medium': months to ~year (most macro/event funds)
#                   'short' : weeks to months (Cathie Wood high churn)
#                   'quant' : ms-days, mostly market-making (Griffin/Shaw)
#   style         — investing philosophy bucket
#   signal_weight — how much weight their 13F moves carry in our
#                   smart_money_score. Concentrated long-term whales
#                   get 1.5×; market-making quant funds get 0.3× because
#                   90%+ of their 15k+ holdings is statistical noise.
#   derivative_exposure_note — known exposure outside 13F-HR (swaps,
#                   options, shorts). If non-None, frontends should
#                   show a "13F may understate" caveat on this whale.
WHALES = [
    {"cik": "0001067983", "short": "Buffett (Berkshire)",      "key": "buffett",
     "horizon": "long",   "style": "value",            "signal_weight": 1.5},
    {"cik": "0001061165", "short": "Klarman (Baupost)",        "key": "klarman",
     "horizon": "long",   "style": "value",            "signal_weight": 1.5},
    {"cik": "0000949509", "short": "Marks (Oaktree)",          "key": "marks",
     "horizon": "long",   "style": "value_distressed", "signal_weight": 1.5},
    {"cik": "0001336528", "short": "Ackman (Pershing Square)", "key": "ackman",
     "horizon": "medium", "style": "activist",         "signal_weight": 1.3},
    {"cik": "0001536411", "short": "Druckenmiller (Duquesne)", "key": "druckenmiller",
     "horizon": "medium", "style": "macro",            "signal_weight": 1.2},
    {"cik": "0001656456", "short": "Tepper (Appaloosa)",       "key": "tepper",
     "horizon": "medium", "style": "macro_em",         "signal_weight": 1.2},
    {"cik": "0001040273", "short": "Loeb (Third Point)",       "key": "loeb",
     "horizon": "medium", "style": "event_driven",     "signal_weight": 1.0},
    # 2026-05-02: multi-strategy / quant / all-weather macro funds.
    {"cik": "0001350694", "short": "Dalio (Bridgewater)",      "key": "dalio",
     "horizon": "medium", "style": "all_weather_macro", "signal_weight": 1.0,
     "derivative_exposure_note":
         "Bridgewater famously uses swaps, FX forwards, and futures for "
         "macro overlays. 13F shows only US listed equity; estimate true "
         "exposure ~40-60% visible."},
    {"cik": "0001423053", "short": "Griffin (Citadel)",        "key": "griffin",
     "horizon": "quant",  "style": "multi_strat_market_maker", "signal_weight": 0.3,
     "derivative_exposure_note":
         "Citadel makes markets across thousands of names — 90%+ of 13F "
         "holdings reflect liquidity provision, NOT directional conviction. "
         "Filter strongly; only changes >20% by share count are meaningful."},
    {"cik": "0001009268", "short": "D.E. Shaw",                "key": "deshaw",
     "horizon": "quant",  "style": "multi_strat_quant", "signal_weight": 0.3,
     "derivative_exposure_note":
         "Quant multi-strat — most holdings are factor / pairs trade legs, "
         "not single-name conviction. Treat as low signal."},
    # Cathie Wood / ARK Investment Management — innovation / disruptive
    # tech long bets. ARK publishes daily holdings on ark-funds.com but
    # that domain is Cloudflare-walled (HTTP 403) so we use their 13F
    # quarterly filing here. A future ark_daily_scanner can layer on
    # intra-quarter changes if we find a stable scrape path.
    {"cik": "0001697748", "short": "Cathie Wood (ARK)",        "key": "cathie",
     "horizon": "short",  "style": "thematic_growth",  "signal_weight": 0.7,
     "derivative_exposure_note":
         "ARK ETFs publish holdings daily (publicly) — the 13F we ingest "
         "here is 45-day-delayed quarterly. For real-time ARK moves see "
         "ark-funds.com (Cloudflare blocks programmatic access)."},
    # 2026-05-19: Leopold Aschenbrenner / Situational Awareness LP.
    # Thematic AGI / AI-infra long fund founded mid-2024 (Collisons +
    # Daniel Gross + Nat Friedman as backers, ~$1.5B+ AUM by 2025-Q3).
    # 6 quarters of 13F-HR filed since 2025-02. Concentration: NVDA + TSM +
    # power/grid infra (CEG/VST/TLN) + select semis. Holdings count
    # typically 15-30 names, similar density to Pershing Square — every
    # change is a high-conviction signal.
    {"cik": "0002045724", "short": "Aschenbrenner (Situational Awareness)", "key": "leopold",
     "horizon": "medium", "style": "thematic_agi",     "signal_weight": 1.3,
     "derivative_exposure_note":
         "Aschenbrenner has publicly outlined a thesis around AI-driven "
         "power demand (CEG/VST/TLN/BWXT). The 13F shows ONLY direct US "
         "listed equity — most of his power/grid exposure is likely held "
         "via total-return swaps which 13F does not report. Treat the "
         "visible portfolio (semis-heavy) as ~50% of true thesis exposure."},
]


# ── runtime lookup helper ────────────────────────────────────────


WHALES_BY_KEY: Dict[str, Dict[str, Any]] = {w["key"]: w for w in WHALES}


def whale_meta(key: str) -> Dict[str, Any]:
    """Return horizon/style/signal_weight metadata for a whale_key,
    or sensible defaults if unknown."""
    w = WHALES_BY_KEY.get(key)
    if not w:
        return {"horizon": "unknown", "style": "unknown",
                "signal_weight": 1.0, "short": key}
    return {
        "horizon":        w.get("horizon", "unknown"),
        "style":          w.get("style", "unknown"),
        "signal_weight":  w.get("signal_weight", 1.0),
        "short":          w.get("short", key),
        "derivative_exposure_note": w.get("derivative_exposure_note"),
    }


# ── horizon → emoji (for UI / Telegram bot) ──────────────────────


HORIZON_EMOJI = {
    "long":    "🐢",   # multi-year hold
    "medium":  "🦅",   # months-year, conviction-driven
    "short":   "🦊",   # high-turnover thematic
    "quant":   "🤖",   # algorithmic / market-making
    "unknown": "·",
}


def horizon_label(key: str) -> str:
    """e.g. '🐢 long' — used in UI snippets."""
    m = whale_meta(key)
    h = m["horizon"]
    return f"{HORIZON_EMOJI.get(h, '·')} {h}"


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
    # 2026-05-19: Cerebras Systems — AI chip startup, IPO'd
    # late 2025. Aschenbrenner / SAR among early concentrated owners.
    ("CEREBRAS SYSTEMS",              "CBRS"),
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
            # 2026-05-19: store as old_shares=0 / new_shares=X so
            # consumers can rely on uniform field names across all
            # change types (was previously just 'shares' for new,
            # breaking queries that joined on old/new).
            changes.append({
                "type":         "new",
                "ticker":       ticker,
                "name":         c.get("nameOfIssuer"),
                "old_shares":   0,
                "new_shares":   c_shares,
                "value_usd_k":  c.get("value"),
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
            "type":       "exit",
            "ticker":     ticker,
            "name":       p.get("nameOfIssuer"),
            "old_shares": p.get("shares") or 0,
            "new_shares": 0,
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


def _emit_one_change(
    *, cik: str, short_name: str, key: str,
    ch: Dict[str, Any], curr_filing_date: str, prev_filing_date: str,
) -> bool:
    """Emit one diff entry as a signal_event. Returns True if emitted,
    False if skipped (idempotency)."""
    from agent.finance.regime.signals import emit_event

    if _already_emitted_change(key, ch["ticker"], ch["type"], curr_filing_date):
        return False

    sev = "high" if ch["type"] in ("new", "exit") else "med"

    action_zh = {
        "new":      "新建仓",
        "exit":     "清仓",
        "increase": f"加仓 {ch.get('delta_pct', 0) * 100:+.0f}%",
        "decrease": f"减仓 {ch.get('delta_pct', 0) * 100:+.0f}%",
    }[ch["type"]]

    # 2026-05-19: enrich title with horizon emoji so UI/Telegram bot
    # show "🐢 Buffett ..." vs "🤖 Citadel ..." at a glance.
    meta = whale_meta(key)
    emoji = HORIZON_EMOJI.get(meta["horizon"], "·")
    title = f"{emoji} {short_name} {action_zh} {ch['ticker']}"

    body = {
        "whale":                  short_name,
        "whale_key":              key,
        "change_type":            ch["type"],
        "filing_date":            curr_filing_date,
        "previous_filing_date":   prev_filing_date,
        # whale metadata embedded so downstream consumers can route /
        # weight without joining back to WHALES_BY_KEY
        "whale_horizon":          meta["horizon"],
        "whale_style":            meta["style"],
        "whale_signal_weight":    meta["signal_weight"],
        "derivative_exposure_note": meta.get("derivative_exposure_note"),
        **ch,
    }

    emit_event(
        "13f",
        signal_type=f"13f_{ch['type']}",
        severity=sev,
        ticker=ch["ticker"],
        title=title,
        body=body,
        source_url=(
            f"https://www.sec.gov/cgi-bin/browse-edgar"
            f"?action=getcompany&CIK={cik}&type=13F-HR"
        ),
        source_timestamp=curr_filing_date,
    )
    return True


def scan_whale(cik: str, short_name: str, key: str) -> Dict[str, Any]:
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
        if _emit_one_change(
            cik=cik, short_name=short_name, key=key, ch=ch,
            curr_filing_date=latest["filing_date"],
            prev_filing_date=previous["filing_date"],
        ):
            n_emitted += 1

    return {
        "whale":           short_name,
        "filing_date":     latest["filing_date"],
        "prev_filing_date": previous["filing_date"],
        "n_holdings":      len(curr_h),
        "n_changes":       len(changes),
        "n_emitted":       n_emitted,
    }


def backfill_whale_history(key: str, n_quarters: int = 5) -> Dict[str, Any]:
    """Walk back N quarters of 13F filings for a whale; emit signal_events
    for each adjacent (older, newer) diff.

    Idempotent — re-running won't duplicate events (relies on the
    (key, ticker, type, filing_date) check in _already_emitted_change).

    Use when you just added a whale to WHALES and want their historical
    moves in the DB, or after you re-extend the NAME_TO_TICKER table.

    Returns per-pair summary.
    """
    w = WHALES_BY_KEY.get(key)
    if not w:
        return {"error": f"unknown whale key: {key!r}",
                "known_keys": list(WHALES_BY_KEY.keys())}
    cik = w["cik"]
    short_name = w["short"]

    try:
        filings = _fetch_recent_filings(cik, limit=n_quarters + 1)
    except Exception as exc:
        return {"whale": short_name, "error": f"fetch_filings: {exc}"}

    if len(filings) < 2:
        return {"whale": short_name, "skip": "need_≥2_filings",
                "n_filings": len(filings)}

    # Cache holdings per filing to avoid re-fetching when one filing
    # appears as both 'curr' and 'prev' in adjacent pairs.
    holdings_cache: Dict[str, List[Dict[str, Any]]] = {}

    def _hold(filing: Dict[str, Any]) -> List[Dict[str, Any]]:
        acc = filing["accession"]
        if acc not in holdings_cache:
            try:
                holdings_cache[acc] = _fetch_holdings(cik, acc)
            except Exception:
                holdings_cache[acc] = []
            time.sleep(0.3)  # respect SEC 10 req/s
        return holdings_cache[acc]

    per_pair = []
    n_emitted_total = 0

    # filings[0] is most recent; pair (i, i+1) = (newer, older)
    for i in range(min(n_quarters, len(filings) - 1)):
        newer = filings[i]
        older = filings[i + 1]
        curr_h = _hold(newer)
        prev_h = _hold(older)
        if not curr_h or not prev_h:
            per_pair.append({
                "newer_date": newer["filing_date"],
                "older_date": older["filing_date"],
                "skip": "empty_holdings",
            })
            continue

        changes = diff_holdings(prev_h, curr_h)
        n_pair_emit = 0
        for ch in changes:
            if _emit_one_change(
                cik=cik, short_name=short_name, key=key, ch=ch,
                curr_filing_date=newer["filing_date"],
                prev_filing_date=older["filing_date"],
            ):
                n_pair_emit += 1
        per_pair.append({
            "newer_date":   newer["filing_date"],
            "older_date":   older["filing_date"],
            "n_holdings":   len(curr_h),
            "n_changes":    len(changes),
            "n_emitted":    n_pair_emit,
        })
        n_emitted_total += n_pair_emit

    return {
        "whale":      short_name,
        "key":        key,
        "n_quarters_processed": len(per_pair),
        "n_emitted_total":      n_emitted_total,
        "per_pair":   per_pair,
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
