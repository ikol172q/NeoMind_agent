"""SEC Schedule 13D activist scanner — EDGAR full-text search (EFTS).

A Schedule 13D is filed within 10 days by anyone acquiring **>5%** of a
company's voting stock **with intent to influence** control (board seats,
strategy, M&A). Unlike a 13F (passive, quarterly, 45-day lag) or a 13G
(passive >5% holder — index funds, low signal), a 13D is an *active*
campaign: an activist publicly planting a flag. That makes it a strong,
relatively timely conviction signal for the positioning lens.

Data source: EDGAR full-text search JSON API (efts.sec.gov/LATEST/
search-index). We query per **subject company CIK** (forms=SC 13D) so each
hit is a 13D/13D-A filed *against a ticker we care about*. The activist =
the filer entity (every display_name whose CIK != the subject's).

Scope: union(user_watchlist, held symbols) only — bounded (~dozens), and
those are the tickers the scorecard/drawer actually surface. Most mega-caps
have **no** recent 13D (activists don't target $1T+ names) — that absence
is itself honest signal, not a bug.

Caveats (surfaced):
    - EFTS returns the 100 most-recent hits per query; for our low-volume
      subject filter that's complete.
    - "Activist" here is literal 13D-filer; some 13D filers are founders /
      large insiders rather than campaign funds. Body keeps the raw filer
      name so the user can judge.
    - SEC fair-access: descriptive UA with contact required, ~10 req/s cap.
"""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_UA = "NeoMind Research admin@neomind.local"
_EFTS_URL = "https://efts.sec.gov/LATEST/search-index"
_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"

_T2C_CACHE: Dict[str, str] = {}


def _ticker_to_cik() -> Dict[str, str]:
    """ticker (UPPER) -> zero-padded 10-digit CIK. Cached per process."""
    if _T2C_CACHE:
        return _T2C_CACHE
    import httpx
    with httpx.Client(timeout=20, headers={"User-Agent": _UA}) as c:
        data = c.get(_TICKERS_URL).json()
    for v in data.values():
        try:
            _T2C_CACHE[v["ticker"].upper()] = str(v["cik_str"]).zfill(10)
        except Exception:
            continue
    return _T2C_CACHE


def _scan_tickers() -> List[str]:
    """Union of user_watchlist + currently-held symbols (tax_lots)."""
    from agent.finance.persistence import connect
    tks: set[str] = set()
    with connect() as conn:
        try:
            for r in conn.execute("SELECT ticker FROM user_watchlist").fetchall():
                if r["ticker"]:
                    tks.add(r["ticker"].upper())
        except Exception:
            pass
        try:
            for r in conn.execute("SELECT DISTINCT symbol FROM tax_lots").fetchall():
                if r["symbol"]:
                    tks.add(r["symbol"].upper())
        except Exception:
            pass
    return sorted(tks)


def _clean_filer(display_name: str) -> str:
    """'Ante Joachim Christoph  (CIK 0001826146)' -> 'Ante Joachim Christoph'."""
    return re.sub(r"\s*\(CIK\s*\d+\)\s*$", "", display_name or "").strip()


def _filing_index_url(filer_cik: str, adsh: str) -> str:
    """Filing index page (validated like the 13F browse URLs)."""
    nodash = adsh.replace("-", "")
    cik_int = str(int(filer_cik))  # EDGAR Archives path uses unpadded CIK
    return f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{nodash}/{adsh}-index.htm"


def _already_emitted(ticker: str, adsh: str) -> bool:
    from agent.finance.persistence import connect
    with connect() as conn:
        cur = conn.execute(
            "SELECT 1 FROM signal_events WHERE scanner_name = '13d' "
            "AND ticker = ? AND json_extract(body_json, '$.adsh') = ? LIMIT 1",
            (ticker, adsh),
        )
        return cur.fetchone() is not None


def run_activist_13d_scan(
    *,
    tickers: Optional[List[str]] = None,
    lookback_days: int = 1095,
    max_per_ticker: int = 25,
) -> Dict[str, Any]:
    """Scan recent SC 13D / SC 13D/A filings against the watchlist+held
    tickers; emit one signal_event per new (ticker, accession).

    lookback_days defaults to ~3y: a 13D campaign can stay active for years,
    so we keep older ones as context — the positioning lens date-weights
    (only ≤~400d counts as live conviction).
    """
    from agent.finance.regime.signals import emit_event
    import httpx

    t0 = time.monotonic()
    if tickers is None:
        tickers = _scan_tickers()
    try:
        t2c = _ticker_to_cik()
    except Exception as exc:
        return {"scanner": "13d", "n_seen": 0, "n_emitted": 0,
                "errors": [f"ticker map: {exc}"], "took_ms": 0}

    cutoff = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).date().isoformat()
    n_seen = n_emitted = 0
    errors: List[str] = []

    with httpx.Client(timeout=15, headers={"User-Agent": _UA}) as client:
        for tk in tickers:
            subject_cik = t2c.get(tk)
            if not subject_cik:
                continue
            try:
                resp = client.get(_EFTS_URL, params={"forms": "SC 13D", "ciks": subject_cik})
                hits = resp.json().get("hits", {}).get("hits", [])
            except Exception as exc:
                errors.append(f"{tk}: {exc}")
                time.sleep(0.2)
                continue

            for h in hits[:max_per_ticker]:
                s = h.get("_source", {})
                n_seen += 1
                file_date = s.get("file_date") or ""
                if file_date < cutoff:
                    continue
                adsh = s.get("adsh") or ""
                if not adsh or _already_emitted(tk, adsh):
                    continue

                ciks = s.get("ciks", [])
                names = s.get("display_names", [])
                # EFTS ciks[0]/display_names[0] is the SUBJECT (issuer); the
                # rest are the filers (reporting persons). The `ciks` filter
                # matches ANY party, so we MUST drop hits where our ticker is
                # itself the filer (e.g. WMT's 13D *against* Symbotic) — those
                # belong to the other ticker, not ours. Keep only hits where
                # OUR cik is the subject (someone is targeting our ticker).
                if not ciks or ciks[0].lstrip("0") != subject_cik.lstrip("0"):
                    continue
                filers = [_clean_filer(nm) for nm in names[1:]]
                if not filers:  # degenerate: only subject listed
                    continue
                filer = filers[0]
                filer_cik = ciks[1] if len(ciks) > 1 else subject_cik
                form = s.get("form") or "SC 13D"
                is_amend = form.endswith("/A")

                title = (
                    f"🏴 {tk}: 活动家 {filer} 提交 {form} "
                    f"({'增持/修正' if is_amend else '新举牌'}, {file_date})"
                )
                emit_event(
                    "13d",
                    signal_type="activist_13d_amend" if is_amend else "activist_13d_new",
                    severity="high" if not is_amend else "med",
                    ticker=tk,
                    title=title,
                    body={
                        "filer": filer,
                        "filer_cik": filer_cik,
                        "subject_cik": subject_cik,
                        "form": form,
                        "is_amendment": is_amend,
                        "file_date": file_date,
                        "adsh": adsh,
                    },
                    source_url=_filing_index_url(filer_cik, adsh),
                    source_timestamp=file_date,
                )
                n_emitted += 1
            time.sleep(0.15)  # respect SEC rate limit

    return {
        "scanner": "13d",
        "n_seen": n_seen,
        "n_emitted": n_emitted,
        "n_tickers": len(tickers),
        "errors": errors,
        "took_ms": int((time.monotonic() - t0) * 1000),
    }
