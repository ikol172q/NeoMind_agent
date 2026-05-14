"""Daily macro calendar scanner — Phase 3.

Pulls upcoming high+medium-impact US macro events (FOMC / CPI / PPI /
NFP / GDP / Retail Sales / unemployment claims) for the current week.
Emits theme-level signal_event (no ticker, theme='macro') so the
chain panel + NeoMindLiveStream surface them.

Source: Forex Factory weekly XML (faireconomy.media mirror) — free,
no auth, structured fields including explicit impact rating.
Originally tried Trading Economics RSS but it returns 403 for
non-browser User-Agent + lacks impact field.

Per plan §5 Pillar 3 + §7 Phase 3. Macro releases move whole
sectors (FOMC affects all rate-sensitive names; CPI affects
everything), so retail needs a same-day latency budget.

Run cadence: 06:45 daily. Idempotency: 24h dedup window per
event title.
"""
from __future__ import annotations

import json
import logging
import re
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from agent.finance.persistence import connect, dao, ensure_schema

logger = logging.getLogger(__name__)

JOB_NAME = "macro_calendar"
DEFAULT_CRON = "45 6 * * *"   # 06:45 daily

DESCRIPTION = (
    "Daily fetch of this-week high-impact macro events (FOMC, CPI, "
    "NFP, etc) from Forex Factory XML. US events promoted to high "
    "severity, China events to med (relevant for AI/semis exports). "
    "Other countries skipped to keep noise down."
)

_FF_XML_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.xml"
# Countries we care about (USD = US releases, CNY = China releases —
# matter for our 9-name AI/semis-heavy watchlist).
_RELEVANT_COUNTRIES = {"USD", "CNY"}
_REQUEST_TIMEOUT_S = 10
_DEDUP_WINDOW_HOURS = 24


async def run() -> Dict[str, Any]:
    with connect() as conn:
        run_id = dao.start_analysis_run(
            conn, job_name=JOB_NAME, run_type="scheduled",
        )
    summary: Dict[str, Any] = {"run_id": run_id, "status": "running"}
    try:
        result = _do_scan()
        summary.update({"status": "completed", **result})
        logger.info(
            "[macro_calendar] checked=%d emitted=%d skipped_dup=%d errors=%d",
            result.get("n_checked", 0), result["n_emitted"],
            result["n_skipped"], result["n_errors"],
        )
    except Exception as exc:
        logger.exception("macro_calendar failed")
        summary.update({"status": "failed", "error": str(exc)})

    with connect() as conn:
        dao.finish_analysis_run(
            conn, run_id=run_id,
            status=summary["status"],
            summary_json=summary,
        )
    return summary


def _do_scan() -> Dict[str, Any]:
    ensure_schema()
    now = datetime.now(timezone.utc)
    dedup_cutoff = (now - timedelta(hours=_DEDUP_WINDOW_HOURS)).isoformat()

    try:
        req = urllib.request.Request(
            _FF_XML_URL,
            headers={"User-Agent": "Mozilla/5.0 neomind-fin-dashboard"},
        )
        with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT_S) as resp:
            xml = resp.read().decode("windows-1252", errors="replace")
    except Exception as exc:
        logger.warning("Forex Factory XML fetch failed: %s", exc)
        return {
            "n_checked": 0, "n_emitted": 0, "n_skipped": 0, "n_errors": 1,
            "error": f"XML fetch failed: {exc}",
        }

    events = _parse_ff_events(xml)
    n_emitted = 0
    n_skipped = 0
    n_errors = 0
    n_filtered = 0

    for ev in events:
        # Filter: only relevant countries + impact High/Medium
        if ev.get("country") not in _RELEVANT_COUNTRIES:
            n_filtered += 1
            continue
        impact = ev.get("impact", "").lower()
        if impact not in ("high", "medium"):
            n_filtered += 1
            continue
        title = ev.get("title", "")
        # Make title unique per occurrence (e.g. "CPI y/y · USD · 05-15-2026")
        unique_title = f"{title} · {ev.get('country','')} · {ev.get('date','')}"
        try:
            if _already_emitted(unique_title, dedup_cutoff):
                n_skipped += 1
                continue
            _emit_macro_event(ev, unique_title, now)
            n_emitted += 1
        except Exception as exc:
            n_errors += 1
            logger.warning("emit macro %r: %s", title[:50], exc)

    return {
        "n_checked":  len(events),
        "n_filtered": n_filtered,
        "n_emitted":  n_emitted,
        "n_skipped":  n_skipped,
        "n_errors":   n_errors,
        "scanned_at": now.isoformat(),
    }


def _parse_ff_events(xml: str) -> List[Dict[str, str]]:
    """Parse Forex Factory weekly XML — extract <event> blocks with
    fields: title, country, date, time, impact, forecast, previous, url."""
    events = []
    for m in re.finditer(r"<event>(.*?)</event>", xml, re.DOTALL | re.IGNORECASE):
        block = m.group(1)
        ev = {}
        for field in ("title", "country", "date", "time", "impact",
                      "forecast", "previous", "url"):
            # Both <title>X</title> and <title><![CDATA[X]]></title> forms
            mm = re.search(
                rf"<{field}>\s*(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?\s*</{field}>",
                block, re.DOTALL | re.IGNORECASE,
            )
            if mm:
                ev[field] = mm.group(1).strip()
        if ev.get("title"):
            events.append(ev)
    return events


def _already_emitted(unique_title: str, dedup_cutoff: str) -> bool:
    """Same unique_title within last 24h = duplicate."""
    with connect() as conn:
        cur = conn.execute(
            "SELECT event_id FROM signal_events "
            "WHERE scanner_name = 'macro_calendar' AND title = ? "
            "  AND detected_at >= ? LIMIT 1",
            (unique_title, dedup_cutoff),
        )
        return cur.fetchone() is not None


def _emit_macro_event(ev: Dict[str, str], unique_title: str, now: datetime) -> None:
    impact = ev.get("impact", "").lower()
    severity = "high" if impact == "high" else "med"
    body = {
        "country":  ev.get("country", ""),
        "date":     ev.get("date", ""),       # MM-DD-YYYY format from FF
        "time":     ev.get("time", ""),
        "forecast": ev.get("forecast", ""),
        "previous": ev.get("previous", ""),
        "impact":   ev.get("impact", ""),
    }
    with connect() as conn:
        conn.execute(
            "INSERT INTO signal_events "
            "(event_id, scanner_name, theme, signal_type, severity, "
            " title, body_json, source_url, detected_at) "
            "VALUES (?, 'macro_calendar', 'macro', 'macro_release', ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), severity, unique_title, json.dumps(body),
             ev.get("url", ""), now.isoformat()),
        )
