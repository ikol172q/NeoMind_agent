"""SEC EDGAR fetcher — pure deterministic, no LLM.

Why this module exists: the existing stock_research.py asks DeepSeek
to generate competitors/customers/suppliers from the ticker symbol
alone. That fabricates ~50% of the output (see ROKU↔NFLX bug). The
truthful path is to fetch the company's actual 10-K from SEC EDGAR
and let an LLM extract structured facts from real filing text — with
a verbatim-quote validation gate after.

This module only fetches. It does not call any LLM.

Usage:
    cik = lookup_cik("ROKU")
    sub = get_submissions(cik)
    f10k = latest_10k(sub)
    html = fetch_filing_html(cik, f10k.accession, f10k.primary_doc)
    sections = slice_competition_sections(html)
    # → {"item1_competition": "...", "item1a_risks": "...", "source_url": "https://..."}

SEC requirements (https://www.sec.gov/os/accessing-edgar-data):
- ≤ 10 requests/second
- Must send descriptive User-Agent

Caching:
- ticker→CIK map: filesystem JSON, refreshed weekly
- submissions JSON: per-CIK file, refreshed daily
- filing HTML: per-accession file, cached forever (10-Ks don't change
  after filing)
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# SEC requires a non-empty UA. Generic so we don't leak user PII to SEC logs.
_USER_AGENT = "NeoMind Research Agent contact@neomind.local"
_HEADERS = {"User-Agent": _USER_AGENT, "Accept-Encoding": "gzip, deflate"}
_HTTP_TIMEOUT = 30.0

# Filesystem cache root — separate from SQLite fin.db because 10-K HTMLs
# are 1-3 MB each and don't belong in a transactional DB.
_CACHE_ROOT = Path.home() / ".neomind" / "fin" / "cache" / "sec_edgar"

_TICKER_MAP_TTL_S = 7 * 24 * 3600       # weekly
_SUBMISSIONS_TTL_S = 24 * 3600          # daily
_FILING_TTL_S = 10 * 365 * 24 * 3600    # ~forever (10-K immutable post-filing)


@dataclass
class FilingRef:
    accession: str           # "0001628280-26-008114"
    primary_doc: str         # "roku-20251231.htm"
    filing_date: str         # "2026-02-13"
    form: str                # "10-K"


@dataclass
class SlicedSections:
    item1_full: Optional[str]          # full Item 1 (Business) region
    item1_competition: Optional[str]   # Competition subsection
    item1_customers: Optional[str]     # Customers / Customer Concentration
    item1_suppliers: Optional[str]     # Sources of Supply / Manufacturing
    item1a_risks: Optional[str]        # full Item 1A Risk Factors
    item7_mda: Optional[str]           # MD&A — segment revenue tables live here
    source_url: str
    filing_date: str
    accession: str


# ─── Cache helpers ───────────────────────────────────────────────

def _cache_path(*parts: str) -> Path:
    p = _CACHE_ROOT.joinpath(*parts)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _read_cached_text(path: Path, ttl_s: int) -> Optional[str]:
    if not path.exists():
        return None
    age = time.time() - path.stat().st_mtime
    if age > ttl_s:
        return None
    return path.read_text(encoding="utf-8")


def _write_cache_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


# ─── HTTP ────────────────────────────────────────────────────────

def _get(url: str) -> str:
    """Single GET with SEC-compliant headers and timeout."""
    with httpx.Client(timeout=httpx.Timeout(_HTTP_TIMEOUT), headers=_HEADERS) as c:
        r = c.get(url, follow_redirects=True)
        r.raise_for_status()
        return r.text


# ─── Public API ──────────────────────────────────────────────────

def lookup_cik(ticker: str) -> Optional[int]:
    """Return the SEC CIK for ``ticker`` (uppercase). None if not found."""
    ticker = ticker.upper().strip()
    cache = _cache_path("ticker_map.json")
    raw = _read_cached_text(cache, _TICKER_MAP_TTL_S)
    if raw is None:
        raw = _get("https://www.sec.gov/files/company_tickers.json")
        _write_cache_text(cache, raw)
    data = json.loads(raw)
    for entry in data.values():
        if entry.get("ticker") == ticker:
            return int(entry["cik_str"])
    return None


def get_submissions(cik: int) -> dict:
    """Fetch /submissions/CIK{cik}.json. Returns the full JSON dict."""
    cache = _cache_path("submissions", f"CIK{cik:010d}.json")
    raw = _read_cached_text(cache, _SUBMISSIONS_TTL_S)
    if raw is None:
        url = f"https://data.sec.gov/submissions/CIK{cik:010d}.json"
        raw = _get(url)
        _write_cache_text(cache, raw)
    return json.loads(raw)


def latest_10k(submissions: dict) -> Optional[FilingRef]:
    """Return the most-recent 10-K from a submissions JSON, or None."""
    recent = (submissions.get("filings") or {}).get("recent") or {}
    forms = recent.get("form") or []
    accs = recent.get("accessionNumber") or []
    docs = recent.get("primaryDocument") or []
    dates = recent.get("filingDate") or []
    for i, f in enumerate(forms):
        if f == "10-K":
            return FilingRef(
                accession=accs[i],
                primary_doc=docs[i],
                filing_date=dates[i],
                form=f,
            )
    return None


def fetch_filing_html(cik: int, accession: str, primary_doc: str) -> str:
    """Fetch the primary HTML document of a filing. Cached forever."""
    acc_clean = accession.replace("-", "")
    cache = _cache_path("filings", str(cik), f"{acc_clean}_{primary_doc}")
    raw = _read_cached_text(cache, _FILING_TTL_S)
    if raw is None:
        url = filing_url(cik, accession, primary_doc)
        raw = _get(url)
        _write_cache_text(cache, raw)
    return raw


def filing_url(cik: int, accession: str, primary_doc: str) -> str:
    acc_clean = accession.replace("-", "")
    return (
        f"https://www.sec.gov/Archives/edgar/data/{cik}/"
        f"{acc_clean}/{primary_doc}"
    )


# ─── HTML → text + section slicing ──────────────────────────────

def _html_to_text(html: str) -> str:
    """Strip HTML to readable text. Preserves paragraph structure."""
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(separator="\n")
    # Normalize whitespace — collapse 3+ newlines to 2, multi-space to single
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text


def slice_10k_sections(html: str, source_url: str,
                       accession: str, filing_date: str
                       ) -> SlicedSections:
    """Extract Item 1 (full Business region + Competition subsection)
    AND Item 1A (Risk Factors) from a 10-K HTML.

    Returns the slices that downstream extractors consume:
    - item1_full: full Item 1 region (used by business_summary,
      and as fallback source if a specific subsection isn't found)
    - item1_competition: Competition subsection only (used by
      competitors extractor for tighter context)
    - item1a_risks: full Risk Factors region (used by risks extractor;
      also competitors since competitors are often named in 1A)

    SEC HTML conventions vary widely; we use permissive regex on the
    flattened text. Returns None for any section we couldn't locate.
    """
    text = _html_to_text(html)

    # SEC 10-Ks are formatted inconsistently. Section headers appear
    # multiple times (TOC entries, running page headers, body). We
    # use Item 1A as the only reliable cross-document anchor (it's
    # always present, distinctly named, and bounds Item 1 above and
    # Item 1B/2/3 below). For each candidate header position, the
    # "real body" is the one with the largest gap to the next anchor.
    item1a_starts = [m.start() for m in re.finditer(
        r"(?i)\bitem\s*1a\b\.?\s*\n*\s*risk\s*factors\b", text)]
    next_section_starts = [m.start() for m in re.finditer(
        r"(?i)\bitem\s*(1b|2|3)\b\.?\s*\n*\s*"
        r"(unresolved\s*staff\s*comments|properties|legal\s*proceedings)",
        text)]

    item1a_body_start = None
    item1a_body_end = None
    for s in item1a_starts:
        ends = [a for a in next_section_starts if a > s]
        e = min(ends) if ends else min(s + 250_000, len(text))
        size = e - s
        if (item1a_body_end is None) or (size > item1a_body_end - item1a_body_start):
            item1a_body_start, item1a_body_end = s, e

    item1a_text = (text[item1a_body_start:item1a_body_end]
                   if item1a_body_start is not None else None)

    # Item 1 spans from somewhere near the document start to Item 1A
    # body. We don't try to find a separate "Item 1" anchor (formatting
    # too inconsistent — sometimes "Business" alone, sometimes spread
    # across <p> tags). Instead: take everything between the first
    # *substantial* run of body text and the Item 1A body start.
    item1_text = None
    if item1a_body_start is not None and item1a_body_start > 5000:
        item1_text = text[3000:item1a_body_start]

    # Item 7 (MD&A) — usually has the revenue-by-segment tables that
    # are the truth source for our segments extractor. Bounded above
    # by Item 6 (now reserved, often missing) or Item 5, and bounded
    # below by Item 7A or Item 8.
    item7_text = None
    item7_starts = [m.start() for m in re.finditer(
        r"(?i)\bitem\s*7\b\.?\s*\n*\s*management.{0,3}s\s*discussion", text)]
    item7_ends = [m.start() for m in re.finditer(
        r"(?i)\bitem\s*(7a|8)\b\.?\s*\n*\s*"
        r"(quantitative|financial\s*statements)", text)]
    if item7_starts and item7_ends:
        # "biggest gap" picker, same as item1a
        for s in item7_starts:
            ends = [a for a in item7_ends if a > s]
            if not ends:
                continue
            e = min(ends)
            if item7_text is None or (e - s) > len(item7_text):
                item7_text = text[s:e]

    competition_text = _slice_subsection(item1_text, "competition")
    customers_text = _slice_subsection(item1_text, r"customers?")
    # Suppliers section has many possible header names — try each
    suppliers_text = (
        _slice_subsection(item1_text, r"sources\s*(and\s*availability\s*of\s*)?materials?")
        or _slice_subsection(item1_text, r"manufacturing")
        or _slice_subsection(item1_text, r"suppliers?")
        or _slice_subsection(item1_text, r"supply\s*chain")
    )

    return SlicedSections(
        item1_full=item1_text,
        item1_competition=competition_text,
        item1_customers=customers_text,
        item1_suppliers=suppliers_text,
        item1a_risks=item1a_text,
        item7_mda=item7_text,
        source_url=source_url,
        filing_date=filing_date,
        accession=accession,
    )


# ─── Subsection slicer (shared across customers / suppliers / etc) ──

# Subsection headers that signal "the previous subsection ended".
# Used as terminating anchors when we slice a named subsection out
# of Item 1.
_ITEM1_NEXT_SUBSECTION_PATTERN = (
    r"(?im)^\s*(government\s*regulation|regulatory|"
    r"intellectual\s*property|human\s*capital|employees|"
    r"available\s*information|environmental|seasonality|"
    r"sustainability|properties|sales\s*and\s*marketing|"
    r"research\s*and\s*development|corporate\s*information|"
    r"competition|customers?|suppliers?|sources\s*and\s*availability|"
    r"manufacturing|supply\s*chain|backlog|product\s*development|"
    r"cybersecurity|insurance)\b"
)


def _slice_subsection(parent_text: Optional[str],
                      header_pattern: str) -> Optional[str]:
    """Inside a parent section text, find a subsection by its STANDALONE
    header and return its content up to the next subsection header.

    Strict standalone-only match (not inline) to avoid catching the
    word "customers" inside body prose like "we serve our customers
    by…". If a 10-K doesn't structure a section with a header,
    returning None is the right honest answer — the extractor will
    receive None and emit []. Sparse > fabricated.

    Returns None if no header found. Capped at ~12K chars to keep
    extractor prompts bounded.
    """
    if not parent_text:
        return None
    standalone = re.compile(rf"(?im)^\s*{header_pattern}\s*$")
    cm = standalone.search(parent_text)
    if cm is None:
        return None
    after = parent_text[cm.start():]
    next_sub = re.search(_ITEM1_NEXT_SUBSECTION_PATTERN, after[100:])
    cutoff = (next_sub.start() + 100) if next_sub else min(12_000, len(after))
    return after[:cutoff].strip()


def get_10k_sections(ticker: str) -> Optional[SlicedSections]:
    """One-shot orchestration: ticker → SlicedSections (or None)."""
    cik = lookup_cik(ticker)
    if cik is None:
        logger.info("sec_edgar: no CIK for ticker %s", ticker)
        return None
    sub = get_submissions(cik)
    f10k = latest_10k(sub)
    if f10k is None:
        logger.info("sec_edgar: no 10-K filings for CIK %s", cik)
        return None
    html = fetch_filing_html(cik, f10k.accession, f10k.primary_doc)
    return slice_10k_sections(
        html=html,
        source_url=filing_url(cik, f10k.accession, f10k.primary_doc),
        accession=f10k.accession,
        filing_date=f10k.filing_date,
    )
