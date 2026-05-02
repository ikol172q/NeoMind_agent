"""House Clerk PTR PDF scanner — official source for House reps that
Quiver Quant's free /beta/live tier doesn't cover (notably Pelosi and
Khanna). Senate trades stay in congressional_scanner.py via Quiver.

Pipeline (idempotent, safe to re-run):
    1. Download annual ZIP from disclosures-clerk.house.gov (~20-30 KB)
    2. Parse XML → find PTR (FilingType=P) records by followed reps
    3. For each (rep, year, DocID) not already in signal_events,
       download the PDF (~60-80 KB, 1-2 pages)
    4. Extract transactions with pdfplumber → emit signal_event with
       source_url pointing to the official PDF (so the user can click
       through and verify every number)

Followed reps are hardcoded for now — the user picked them deliberately
based on substantive press coverage (Pelosi: gold-standard reference;
Khanna: best alpha track record per Newsweek 2025-12). Add more by
appending to FOLLOWED_REPS with the canonical (last, first, state)
triple from the House Clerk XML.

Why follow the official source instead of paying Quiver $50/mo:
    - Free, no rate limits we care about
    - PDFs are the legal record (Quiver derives from these too)
    - One-PDF-per-PTR makes diffing trivial — DocID is a primary key
    - 45-day STOCK Act disclosure window is the structural ceiling on
      freshness regardless of source

Caveats (must surface to user via widget header):
    - 45-day disclosure window — same staleness as STOCK Act mandates
    - PDF format is hand-edited; field positions can shift between
      filings. Parser uses heuristic line splits with multiple fallbacks
    - Spouse-attributed trades (Owner=SP) are tagged in body so the
      user knows it's the spouse account, not the member directly
"""
from __future__ import annotations

import io
import logging
import re
import time
import urllib.request
import zipfile
from datetime import date, datetime
from typing import Any, Dict, Iterator, List, Optional
from xml.etree import ElementTree as ET

logger = logging.getLogger(__name__)


# Canonical (last, first, state) tuples from House Clerk XML. Match is
# strict on all three so namesakes (e.g. "Khanna, Lisa Vedernikova" who
# is also a candidate filer) don't get pulled in.
#
# Currently Pelosi only — Khanna's office files PTRs as scanned image
# PDFs (~1MB each, no text layer), which would require OCR to parse.
# Skipped here, can re-add when we add a tesseract pipeline. See
# 2026-05-02 dogfood: tested 4 of his PDFs → all 0 chars extractable.
FOLLOWED_REPS = [
    {"last": "Pelosi", "first": "Nancy", "state": "CA11",
     "display": "Nancy Pelosi", "cn": "佩洛西"},
]

ZIP_URL_TEMPLATE = (
    "https://disclosures-clerk.house.gov/public_disc/financial-pdfs/{year}FD.zip"
)
PDF_URL_TEMPLATE = (
    "https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/{year}/{doc_id}.pdf"
)

_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)


def _http_get(url: str, *, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers={
        "User-Agent": _BROWSER_UA,
        "Accept": "*/*",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _fetch_annual_xml(year: int) -> Optional[ET.Element]:
    """Download the year's FD ZIP and return the parsed XML root, or
    None if the year hasn't been published yet."""
    try:
        raw_zip = _http_get(ZIP_URL_TEMPLATE.format(year=year))
    except Exception as exc:
        logger.warning("house clerk zip %d fetch failed: %s", year, exc)
        return None
    with zipfile.ZipFile(io.BytesIO(raw_zip)) as zf:
        xml_name = f"{year}FD.xml"
        if xml_name not in zf.namelist():
            logger.warning("house clerk %d zip missing %s", year, xml_name)
            return None
        with zf.open(xml_name) as fh:
            return ET.parse(fh).getroot()


def _iter_followed_ptrs(root: ET.Element, year: int) -> Iterator[Dict[str, Any]]:
    """Yield {rep, doc_id, filing_date} for every PTR (FilingType=P) by
    a followed rep in the given XML."""
    for member in root.findall("Member"):
        last = (member.findtext("Last") or "").strip()
        first = (member.findtext("First") or "").strip()
        state = (member.findtext("StateDst") or "").strip()
        ftype = (member.findtext("FilingType") or "").strip()
        if ftype != "P":
            continue
        for rep in FOLLOWED_REPS:
            if (last == rep["last"] and first == rep["first"]
                    and state == rep["state"]):
                doc_id = (member.findtext("DocID") or "").strip()
                if not doc_id:
                    continue
                yield {
                    "rep":         rep,
                    "doc_id":      doc_id,
                    "filing_date": (member.findtext("FilingDate") or "").strip(),
                    "year":        year,
                }


def _doc_id_already_seen(doc_id: str) -> bool:
    """Per-PTR idempotency: have we already emitted any signal_event
    derived from this DocID? The DocID is unique per PTR filing, so
    one positive hit means the whole PDF was processed."""
    from agent.finance.persistence import connect
    with connect() as conn:
        cur = conn.execute(
            "SELECT 1 FROM signal_events "
            "WHERE scanner_name = 'house_clerk_pdf' "
            "AND json_extract(body_json, '$.doc_id') = ? LIMIT 1",
            (doc_id,),
        )
        return cur.fetchone() is not None


# ── PDF text → structured transactions ────────────────────────────

# Asset-type abbreviations seen in the brackets, e.g. [ST] = stock,
# [OP] = option, [OT] = other. We keep the full bracket as-is for the
# user; widget can decode if it wants.
_TICKER_RE = re.compile(r"\(([A-Z]{1,5})\)\s*(?:\[(\w+)\])?")
# Date-pair "MM/DD/YYYY MM/DD/YYYY" (transaction date, notification date)
_DATE_PAIR_RE = re.compile(r"(\d{2}/\d{2}/\d{4})\s+(\d{2}/\d{2}/\d{4})")
# Amount range "$1,000,001 - $5,000,000". Tolerate text between the
# two halves because PDF wrap can interleave the ticker — e.g.
# "$250,001 - Stock (GOOGL) [OP] $500,000".
_AMOUNT_RE = re.compile(r"\$\s*([\d,]+)\s*-.*?\$\s*([\d,]+)")
# Owner is at start of each transaction line: SP / JT / DC / etc.
_OWNER_RE = re.compile(r"^\s*(SP|JT|DC|JT/SP|--?)\s+")


_FILING_STATUS_RE = re.compile(r"^\s*F\s+S")  # 'F      S     : New'
_DESC_RE = re.compile(r"^\s*D\s*[:.][\s]*(.+)")
# Type letter (P / E / S / S (partial)) sits immediately before the
# transaction date pair. Anchor on the date so we pick the right
# letter even when the asset name wraps (e.g.
# "Alphabet Inc. - Class A Common P 01/14/2025...").
_TYPE_BEFORE_DATE_RE = re.compile(r"\b(P|E|S\s*\(partial\)|S)\s+\d{2}/\d{2}/\d{4}")


def _parse_pdf_transactions(pdf_bytes: bytes, doc_id: str) -> List[Dict[str, Any]]:
    """Best-effort text extraction from a House Clerk PTR PDF.

    Real-world layout: each transaction starts with an owner-code line
    (SP/JT/DC + asset name + type + dates + amount-lower) and wraps to
    1-2 continuation lines (asset-name continuation, ticker, amount-upper)
    before the 'F  S  : New' / 'D : <description>' lines that close the
    block.

    Strategy:
        1. Walk lines; on each owner-code line, consume continuation
           lines up to (but not including) the next 'F  S' line.
        2. Concatenate into one logical row, then run the field regexes
           on the joined string. This makes the parser tolerant to
           page-break wrap, inline ticker placement, etc.
        3. Capture the description from the next 'D :' line as context.
    """
    import pdfplumber  # lazy import — only loaded when scanner runs

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        full_text = "\n".join((page.extract_text() or "") for page in pdf.pages)

    # House Clerk PDFs use NULL bytes (\x00) as visual padding inside
    # field labels like 'F\x00\x00\x00\x00\x00 S\x00\x00\x00\x00\x00: New'.
    # Strip them so our \s-based regexes can match cleanly. Doing it once
    # at the top is cheaper than handling NULLs in every regex.
    full_text = full_text.replace("\x00", "")
    lines = full_text.split("\n")
    txns: List[Dict[str, Any]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        owner_m = _OWNER_RE.match(line)
        if not owner_m:
            i += 1
            continue
        owner = owner_m.group(1)

        # Consume this line + continuations up to (but not including)
        # the next 'F  S' line, capping at 4 to avoid runaway.
        block_lines = [line[owner_m.end():]]
        j = i + 1
        while j < len(lines) and j < i + 5:
            if _FILING_STATUS_RE.match(lines[j]) or _OWNER_RE.match(lines[j]):
                break
            # Skip the repeated header line that appears mid-doc when
            # filings span pages.
            if "ID Owner Asset Transaction" in lines[j]:
                break
            block_lines.append(lines[j])
            j += 1
        joined = " ".join(s.strip() for s in block_lines if s.strip())

        # Run regexes on the joined string.
        ticker_m = _TICKER_RE.search(joined)
        ticker = ticker_m.group(1) if ticker_m else None
        asset_class = ticker_m.group(2) if ticker_m else None
        asset_name = (joined[:ticker_m.start()] if ticker_m else joined).strip()
        # Strip trailing "common" / "stock" wrap fragments from name.
        asset_name = re.sub(r"\s+", " ", asset_name)[:200]

        date_m = _DATE_PAIR_RE.search(joined)
        amount_m = _AMOUNT_RE.search(joined)

        # Type letter sits immediately before the transaction date pair,
        # regardless of whether the ticker wraps to the next line.
        type_m = _TYPE_BEFORE_DATE_RE.search(joined)
        tx_type = re.sub(r"\s+", " ", type_m.group(1)).strip() if type_m else "?"

        # Description: scan the next 1-3 lines after the block for 'D :'.
        description = ""
        for k in range(j, min(j + 3, len(lines))):
            d_m = _DESC_RE.match(lines[k])
            if d_m:
                description = d_m.group(1).strip()
                break

        # Skip rows that didn't yield enough fields (mutual fund without
        # a ticker symbol is the typical case; we filter those upstream
        # since the user can't act on them).
        if not amount_m:
            i = j
            continue

        txns.append({
            "owner":         owner,
            "ticker":        ticker,
            "asset_name":    asset_name,
            "asset_class":   asset_class,
            "type":          tx_type,
            "tx_date":       date_m.group(1) if date_m else None,
            "notif_date":    date_m.group(2) if date_m else None,
            "amount_range":  f"${amount_m.group(1)} - ${amount_m.group(2)}",
            "description":   description[:300],
            "doc_id":        doc_id,
        })
        i = j
    return txns


# ── emit_event glue ───────────────────────────────────────────────

def _amount_severity(amount_range: str) -> str:
    """Severity from the upper bound of the disclosed range."""
    m = _AMOUNT_RE.search(amount_range or "")
    if not m:
        return "med"
    try:
        upper = int(m.group(2).replace(",", ""))
    except ValueError:
        return "med"
    if upper >= 1_000_000:
        return "high"
    if upper >= 100_000:
        return "high"
    return "med"


def _normalize_tx_type(t: str) -> str:
    """Map PDF abbreviations to the existing stock_act_<type> convention
    so widget badges (买入 / 卖出 / 换股) line up with Quiver-sourced events."""
    t = (t or "").lower().strip()
    if t == "p":
        return "purchase"
    if t == "s":
        return "sale"
    if "partial" in t:
        return "sale_partial"
    if t == "e":
        return "exchange"
    return "other"


def _to_iso_date(mm_dd_yyyy: Optional[str]) -> Optional[str]:
    if not mm_dd_yyyy:
        return None
    try:
        return datetime.strptime(mm_dd_yyyy, "%m/%d/%Y").date().isoformat()
    except ValueError:
        return None


def run_house_clerk_pdf_scan(
    *,
    years: Optional[List[int]] = None,
    max_new_pdfs: int = 50,
) -> Dict[str, Any]:
    """Scan the House Clerk annual ZIPs for new PTRs by followed reps,
    parse PDFs, emit signal_events.

    Idempotent — already-processed DocIDs are skipped via signal_events
    lookup, so daily cron runs cost nothing once caught up.
    """
    from agent.finance.regime.signals import emit_event

    t0 = time.monotonic()
    if years is None:
        # Current year + previous year — cheap enough to always check both
        # because each ZIP is 20-30 KB.
        cur = date.today().year
        years = [cur - 1, cur]

    n_seen_filings = 0
    n_new_pdfs = 0
    n_emitted = 0
    errors: List[str] = []

    for year in years:
        root = _fetch_annual_xml(year)
        if root is None:
            errors.append(f"year {year} zip unavailable")
            continue
        for ptr in _iter_followed_ptrs(root, year):
            n_seen_filings += 1
            doc_id = ptr["doc_id"]
            if _doc_id_already_seen(doc_id):
                continue
            if n_new_pdfs >= max_new_pdfs:
                logger.info("house_clerk_pdf: hit max_new_pdfs cap %d", max_new_pdfs)
                break
            n_new_pdfs += 1
            # PDF year folder = transaction year (when trades happened),
            # not the filing year that the XML is grouped under. A PTR
            # filed Jan 2026 covering Dec 2025 trades lives at /2025/.
            # Try the XML year first, then the previous year as fallback.
            pdf_bytes = None
            pdf_url = None
            for try_year in (year, year - 1):
                candidate = PDF_URL_TEMPLATE.format(year=try_year, doc_id=doc_id)
                try:
                    pdf_bytes = _http_get(candidate)
                    pdf_url = candidate
                    break
                except Exception:
                    continue
            if pdf_bytes is None:
                logger.warning("house clerk PDF %s not found in /%d/ or /%d/",
                               doc_id, year, year - 1)
                errors.append(f"pdf {doc_id}: 404 in both year folders")
                continue
            try:
                txns = _parse_pdf_transactions(pdf_bytes, doc_id)
            except Exception as exc:
                logger.exception("house clerk PDF %s parse failed", doc_id)
                errors.append(f"parse {doc_id}: {exc}")
                continue

            rep = ptr["rep"]
            for tx in txns:
                # signals.emit_event requires either ticker OR theme. We
                # care about stock/option trades — mutual funds / private
                # holdings without a ticker symbol are low-signal noise
                # (the user can't act on them anyway), so we skip them
                # rather than fabricate a theme.
                if not tx.get("ticker"):
                    continue
                tx_date_iso = _to_iso_date(tx["tx_date"]) or ptr["filing_date"]
                tx_type_norm = _normalize_tx_type(tx["type"])
                action = "买入" if tx_type_norm == "purchase" else (
                    "卖出" if "sale" in tx_type_norm else "换股")
                title = (
                    f"🏛 House: {rep['display']} {action} "
                    f"{tx['ticker'] or tx['asset_name'][:30]} ({tx['amount_range']})"
                )
                emit_event(
                    "house_clerk_pdf",
                    signal_type=f"stock_act_{tx_type_norm}",
                    severity=_amount_severity(tx["amount_range"]),
                    ticker=tx["ticker"],
                    title=title,
                    body={
                        "chamber":          "house",
                        "representative":   rep["display"],
                        "rep_cn":           rep["cn"],
                        "rep_state":        rep["state"],
                        # Normalized form ('purchase'/'sale'/'sale_partial')
                        # so widget action mapping (买入/卖出/换股) matches the
                        # Quiver-sourced events. Raw form kept as transaction_type_raw.
                        "transaction_type": tx_type_norm,
                        "transaction_type_raw": tx["type"],
                        "amount_range":     tx["amount_range"],
                        "transaction_date": tx_date_iso,
                        "notification_date": _to_iso_date(tx["notif_date"]),
                        "owner":            tx["owner"],
                        "asset_name":       tx["asset_name"],
                        "asset_class":      tx["asset_class"],
                        "description":      tx["description"],
                        "doc_id":           doc_id,
                        "filing_date":      ptr["filing_date"],
                        "source":           "house_clerk_pdf",
                    },
                    source_url=pdf_url,
                    source_timestamp=tx_date_iso,
                )
                n_emitted += 1

    return {
        "scanner":         "house_clerk_pdf",
        "years":           years,
        "n_seen_filings":  n_seen_filings,
        "n_new_pdfs":      n_new_pdfs,
        "n_emitted":       n_emitted,
        "errors":          errors,
        "took_ms":         int((time.monotonic() - t0) * 1000),
    }
