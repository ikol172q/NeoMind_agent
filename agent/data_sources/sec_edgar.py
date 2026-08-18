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
    """Strip HTML to readable text. Preserves paragraph structure.

    2026-05-19 fixes for SEC EDGAR oddities that broke section
    detection on MSFT/NVDA/TSLA/etc:

    - SEC filings often wrap words in inline tags for styling
      (``<b>RIS</b><b>K FACTORS</b>``), which after get_text(separator="\n")
      becomes ``RIS\nK FACTORS``. Mid-word newlines like this broke the
      `\\brisk\\s*factors\\b` regex used to anchor section bounds —
      the parser only saw the TOC entry (``Item 1A.\\nRisk Factors``)
      and used it as the body start, silently truncating Item 1 before
      the Competition subsection.
    - Non-breaking spaces (``\\xa0``) similarly fragment regex matches
      that expect plain spaces.

    Normalization order matters: NBSP → space first, then re-glue
    mid-word newlines (single newline between two short letter runs is
    almost always a styling artifact), then collapse whitespace.
    """
    soup = BeautifulSoup(html, "html.parser")
    # 2026-06-21: inline-XBRL filings (Workiva etc.) carry an
    # ix:header / ix:resources block (~60K chars of CIK / period /
    # dimension-member soup) at the document top. get_text() would dump
    # that ahead of the real narrative, pushing Item 1 past the slicer's
    # window and starving every downstream extractor. Drop the
    # non-rendered iXBRL metadata before flattening to text.
    for _meta in soup.find_all(["ix:header", "ix:hidden", "ix:resources"]):
        _meta.decompose()
    text = soup.get_text(separator="\n")
    # NBSP and other whitespace unicode → regular space
    text = text.replace("\xa0", " ").replace(" ", " ").replace("​", "")
    # Re-glue mid-word breaks: a letter run, newline(s), another letter
    # run where the join would be a plausible word continuation.
    # We use a heuristic: if both sides are letters, no spaces, and the
    # next chunk continues lowercase or is short uppercase (≤5 chars),
    # treat as a single word that was split for styling.
    def _glue(m: re.Match) -> str:
        return m.group(1) + m.group(2)
    text = re.sub(r"([A-Za-z]{1,5})\n+([A-Za-z]{1,5})\b", _glue, text)
    # Normalize whitespace — collapse 3+ newlines to 2, multi-space to single
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text


# A same-line prefix this short is a page-header crumb ("Table of Contents" is
# 17 chars), not a sentence. Anything longer that also ends in a space is prose.
_MAX_HEADER_CRUMB = 25


def _heading_anchors(text: str, starts: list[int]) -> list[int]:
    """Keep anchors that look like section *headings*, drop in-text cross-references.

    Both real 10-K filings in our holdings exercise a different edge, and the
    naive "must start a line" test gets exactly one of them right:

    * GOOGL — the MD&A body contains ``"...included in Item 8 as well as
      Item 7A Quantitative and Qualitative Disclosures About Market Risk..."``.
      Same-line prefix is 43 chars of prose ending in a **space**.
    * AMD — the real heading renders glued to the running page header after
      ``_html_to_text`` flattening: ``"...Table of ContentsITEM 7A. QUANTITATIVE"``.
      Same-line prefix is ``'s'`` — mid-line, but **no separating space**.

    So the discriminator is not "starts a line", it is *"is there running prose
    in front of it"*: an anchor is a heading when the text before it on the same
    line is empty, is glued directly to it (no space — page-header artifact), or
    is a short header crumb. Prose that flows into the anchor with a space is a
    cross-reference.

    If filtering would remove every candidate, the originals are returned
    unchanged — same sparse > wrong contract as :func:`_body_anchors`.
    """
    out = []
    for s in starts:
        prefix = text[text.rfind("\n", 0, s) + 1: s]
        stripped = prefix.strip()
        if (not stripped                          # heading owns the line
                or not prefix.endswith((" ", "\t"))   # glued to a page-header crumb
                or len(stripped) <= _MAX_HEADER_CRUMB):
            out.append(s)
    return out or starts


def _body_anchors(text: str, starts: list[int]) -> list[int]:
    """Drop table-of-contents anchors from a list of section-header match
    positions. A real (body) section header is followed by prose; a TOC
    row is followed by another "Item N" within a few hundred chars. If
    filtering would remove every candidate, return the originals unchanged
    (sparse > wrong).
    """
    body = [s for s in starts
            if not re.search(r"(?i)\bitem\s*\d", text[s + 15: s + 300])]
    return body or starts


def _find_mda_body(text: str) -> Optional[str]:
    """Locate the real Item-7 MD&A body when the primary "Item 7." header
    is only a stub.

    Many filers (e.g. E.W. Scripps / SSP) put nothing under the "Item 7."
    heading but a reference — "...required by this item is filed as part of
    this Form 10-K. See Index to Consolidated Financial Statement
    Information at page F-1" — and place the actual MD&A prose later, in the
    financial ("F-page") section, under the SAME full title. The default
    slicer keys off the "Item 7." prefix and lands on the stub (bounded by
    the equally-stubby "Item 7A."/"Item 8." a few hundred chars later),
    yielding a near-empty slice that starves the segment / debt extractors.

    Strategy: find every occurrence of the full MD&A title, bound each below
    by the auditor's report ("Report of Independent Registered Public
    Accounting Firm" — a PCAOB-required phrase present in every US 10-K, and
    the reliable start of the financial statements that follow MD&A). Take
    the SHORTEST span that still contains the MD&A hallmark headings
    (Liquidity and Capital Resources + Results of Operations). Shortest-valid
    skips the TOC entries and the stub occurrence and isolates the real body.
    Returns None if no such body is found (sparse > wrong).
    """
    if not text:
        return None
    starts = [m.start() for m in re.finditer(
        r"(?i)management.{0,3}s\s*discussion\s*and\s*analysis\s*of\s*"
        r"financial\s*condition\s*and\s*results\s*of\s*operations", text)]
    ends = [m.start() for m in re.finditer(
        r"(?i)report\s*of\s*independent\s*registered\s*public\s*accounting\s*firm",
        text)]
    if not starts or not ends:
        return None
    best: Optional[str] = None
    best_len: Optional[int] = None
    for s in starts:
        e_cands = [a for a in ends if a > s + 2000]
        if not e_cands:
            continue
        e = min(e_cands)
        seg = text[s:e]
        if not re.search(r"(?i)liquidity\s+and\s+capital\s+resources", seg):
            continue
        if not re.search(r"(?i)results\s+of\s+operations", seg):
            continue
        if best_len is None or (e - s) < best_len:
            best_len, best = (e - s), seg
    return best


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
    # 2026-05-19: trailing \b on risk_factors / etc dropped — SEC HTML
    # often has no whitespace between section header and following body
    # text after BeautifulSoup's separator='\n' + our mid-word join
    # (e.g. "RISK FACTORSOur operations" — no space, no boundary). The
    # leading \bitem\s*1a\b still constrains false positives.
    # No leading \b: running page-headers ("Table of Contents") can glue to
    # the section header after BeautifulSoup flattening — AMD/META render the
    # body as "...ContentsITEM 1A. RISK FACTORS", which \bitem would miss
    # (matching only the TOC entry). The required "risk factors" suffix keeps
    # false positives out.
    item1a_starts = _body_anchors(text, [m.start() for m in re.finditer(
        r"(?i)item\s*1a\b\.?\s*\n*\s*risk\s*factors", text)])
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
    item7_starts = _body_anchors(text, [m.start() for m in re.finditer(
        r"(?i)item\s*7\b\.?\s*\n*\s*management.{0,3}s\s*discussion", text)])
    # No leading \b (body "Item 8. Financial Statements" can render glued to
    # a page-header). NOT _body_anchors-filtered: a short Item 7A legitimately
    # sits within ~300 chars of Item 8, and filtering it would push the MD&A
    # end deep into the financial statements. min(ends>start) below already
    # picks the earliest correct bound; pre-start TOC ends are just ignored.
    #
    # 🔴 2026-08-17 — but they must be *headings*, not in-text cross-references.
    # GOOGL's MD&A contains the sentence "...see Note 1 and Note 3 ... included
    # in Item 8 as well as Item 7A Quantitative and Qualitative Disclosures
    # About Market Risk of this Annual Report on Form 10-K." That mid-sentence
    # phrase matched, min(ends) picked it, and Alphabet's MD&A got cut at
    # 17.5K chars — **right before "Executive Overview"**, which is where every
    # number lives. Result: the slice had 0 dollar figures, so the segments and
    # debt extractors correctly emitted nothing (their prompts require the
    # figure to appear in the source), and the dossier reported those dimensions
    # empty for the last two months. A parsing bug that looked like "the LLM
    # can't find Alphabet's segments".
    # _heading_anchors keeps only anchors with no running prose in front of
    # them on the same line — headings qualify, cross-references don't.
    item7_ends = _heading_anchors(text, [m.start() for m in re.finditer(
        r"(?i)item\s*(7a|8)\b\.?\s*\n*\s*"
        r"(quantitative|financial\s*statements)", text)])
    if item7_starts and item7_ends:
        # "biggest gap" picker, same as item1a
        for s in item7_starts:
            ends = [a for a in item7_ends if a > s]
            if not ends:
                continue
            e = min(ends)
            if item7_text is None or (e - s) > len(item7_text):
                item7_text = text[s:e]

    # F-page fallback: when the "Item 7." header is only a stub pointing to
    # the financial pages (SSP-class filers), the primary slice is a few
    # hundred chars. Recover the real MD&A body from the F-pages so the
    # segment + debt extractors have their source. Only triggers when the
    # primary slice is too short to be a real MD&A — normal filers untouched.
    if not item7_text or len(item7_text) < 2000:
        fallback_mda = _find_mda_body(text)
        if fallback_mda:
            item7_text = fallback_mda

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
# 2026-05-19: STRICT version — keyword must be alone on its line
# (followed only by whitespace / punctuation, then end-of-line).
# Used as cutoff bound inside `_slice_subsection` so a bulleted
# competitor description ("• suppliers and licensors...") doesn't
# falsely terminate the Competition subsection.
_ITEM1_NEXT_SUBSECTION_PATTERN_STRICT = (
    r"(?im)^\s*(government\s*regulation|regulatory(?:\s*matters)?|"
    r"intellectual\s*property|human\s*capital|employees|"
    r"available\s*information|environmental|seasonality|"
    r"sustainability|properties|sales\s*and\s*marketing|"
    r"research\s*and\s*development|corporate\s*information|"
    r"competition|customers?|suppliers?|sources\s*and\s*availability"
    r"(?:\s*of\s*materials?)?|"
    r"manufacturing|supply\s*chain|backlog|product\s*development|"
    r"cybersecurity|insurance|patents\s*and\s*proprietary)\s*[.:]?\s*$"
)


def _slice_subsection(parent_text: Optional[str],
                      header_pattern: str) -> Optional[str]:
    """Inside a parent section text, find a subsection by its STANDALONE
    header and return its content up to the next subsection header.

    2026-05-19 fix: previously the next-subsection terminator pattern
    `_ITEM1_NEXT_SUBSECTION_PATTERN` used `^\\s*({keyword})\\b` —
    matched ANY line starting with `suppliers and licensors...` mid-
    section. NVDA's Competition subsection legitimately starts a
    bulleted competitor list with `• suppliers and licensors of
    hardware...such as AMD, Intel, ...`, and the matcher cut the
    section AT that bullet, dropping every named competitor below.

    Real subsection headers are STANDALONE — keyword + optional
    punctuation + end-of-line, nothing else. Tighten the terminator
    regex to require this: keyword followed by `[\\s.:]*$` (i.e., the
    rest of the line is whitespace / punctuation only).

    Returns None if no opening header found. Sparse > fabricated.
    """
    if not parent_text:
        return None
    standalone = re.compile(rf"(?im)^\s*{header_pattern}\s*$")
    cm = standalone.search(parent_text)
    if cm is None:
        # 2026-05-19: CamelCase fallback — some filers (AAPL etc) emit
        # `<font>Competition</font><font>The markets...</font>` which
        # BeautifulSoup flattens to "CompetitionThe markets" with no
        # separator. Recognize this by matching the keyword as a prefix
        # immediately followed by an uppercase letter (start of body).
        camel = re.compile(rf"(?im)^\s*({header_pattern})(?=[A-Z])")
        cm = camel.search(parent_text)
        if cm is None:
            return None
    after = parent_text[cm.start():]
    # Tighter: keyword must be alone on its line for it to count as
    # the NEXT subsection header (cutting bound).
    strict_next = re.compile(_ITEM1_NEXT_SUBSECTION_PATTERN_STRICT)
    next_sub = strict_next.search(after[100:])
    # Cap aggressively raised: NVDA-class filings have ~3-5K chars of
    # competitor description (bulleted list with company names). 12K
    # was already enough, keep it.
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


# ─── Foreign / pre-IPO filers (20-F / S-1) — Goal-1 P2 blind-spot fill ──
# Foreign private issuers (ARM, NBIS) file 20-F; fresh IPOs (CBRS) only have an
# S-1. The 10-K slicer returns None for them → zero anchored facts. This fills
# the two HIGH-VALUE, FINDABLE sections — Business (item1_full) + Risk Factors
# (item1a_risks) — so business_summary + risks extractors work. The brittle
# competitor/supplier/customer slicing is deliberately left None (the verbatim
# gate then just yields little, never anything false).
_FOREIGN_FORMS = ("20-F", "20-F/A", "S-1", "S-1/A", "F-1", "F-1/A")


def _latest_foreign_filing(submissions: dict) -> Optional[FilingRef]:
    recent = (submissions.get("filings") or {}).get("recent") or {}
    forms = recent.get("form") or []
    accs = recent.get("accessionNumber") or []
    docs = recent.get("primaryDocument") or []
    dates = recent.get("filingDate") or []
    sizes = recent.get("size") or []
    cands = [i for i, f in enumerate(forms) if f in _FOREIGN_FORMS]
    if not cands:
        return None
    # Pick the MOST RECENT full foreign filing. Two failure modes to avoid:
    #   1. thin amendments (a 20-F/A cover page or exhibits-only re-file lacks
    #      the risk+business body) — exclude anything below a size floor; a real
    #      annual report / registration is 5-30 MB, amendments are «1 MB.
    #   2. an old LARGE filing — picking purely by size grabs a years-old 20-F
    #      that may describe a company that no longer exists (e.g. NBIS's CIK
    #      still carries pre-spinoff Yandex 20-Fs; ARM's largest is its 2024,
    #      not the latest 2026). Recency must dominate.
    def _sz(i: int) -> int:
        return sizes[i] if i < len(sizes) else 0
    SIZE_FLOOR = 2_000_000  # ~2 MB — cleanly separates real filings from amendments
    substantial = [i for i in cands if _sz(i) >= SIZE_FLOOR]
    pool = substantial or cands  # fall back to all if none clears the floor
    # most recent by filing date; size breaks ties so a base form beats its /A
    best = max(pool, key=lambda i: (dates[i] if i < len(dates) else "", _sz(i)))
    return FilingRef(accession=accs[best], primary_doc=docs[best], filing_date=dates[best], form=forms[best])


def _slice_foreign_mda(text: str) -> Optional[str]:
    """20-F Item 5 "Operating and Financial Review and Prospects" — the 20-F
    equivalent of a 10-K's Item 7 MD&A, and the home of the segment / revenue
    and debt-maturity discussion.

    Why this exists (2026-08-17): ``get_foreign_sections`` used to hardcode
    ``item7_mda=None``, so **every 20-F filer could never populate the segment
    or debt dimensions** — not "the extractor failed", the source was never
    fetched. ARM (a 20-F filer) sat at 33% dossier coverage for that reason.

    Picking the body is the whole problem: ARM's filing mentions the Item 5
    title **9 times** (TOC rows, "refer to Item 5...", the body). Two cheaper
    discriminators were tried and both failed on real filings:

    * *"must be a heading"* (:func:`_heading_anchors`) — the cross-reference
      ``... including, but not limited to, "Item 5. Operating and Financial
      Review and Prospects."`` survives it, because ``_html_to_text`` breaks
      the line right after the opening quote, so the title *does* start a line.
    * *biggest span to the next Item 6* — the TOC row and that cross-reference
      both sit near the top of the document, so they reach for an Item 6
      hundreds of thousands of chars away and win. ARM came out as a
      404,229-char slice (half the filing).

    What works is the same shape :func:`_find_mda_body` uses for 10-Ks:
    bound each candidate by the **nearest** following Item 6 heading, keep only
    spans that actually contain MD&A hallmarks (Results of Operations +
    Liquidity), and take the **shortest** survivor. TOC rows are too short to
    hold the hallmarks; stray cross-references produce spans that are valid but
    far longer than the real body, so shortest-valid isolates it.
    """
    if not text:
        return None
    low = text.lower()
    starts = [m.start() for m in re.finditer(
        r"item\s*5[.\s]{0,4}\s*operating\s+and\s+financial\s+review", low)]
    ends = [m.start() for m in re.finditer(
        r"item\s*6[.\s]{0,4}\s*directors", low)]
    if not starts:
        return None
    best, best_len = None, None
    for st in starts:
        after = [e for e in ends if e > st]
        end = min(after) if after else min(st + 200_000, len(text))
        seg = text[st:end]
        if len(seg) < 5000:
            continue                      # TOC row
        seg_low = seg.lower()
        if "results of operations" not in seg_low:
            continue
        if "liquidity" not in seg_low:
            continue
        if best_len is None or len(seg) < best_len:
            best_len, best = len(seg), seg
    return best


def _slice_foreign(text: str) -> tuple[Optional[str], Optional[str]]:
    """Return (business_region, risk_region). Heuristic but safe — the
    downstream verbatim gate drops anything not literally in these bytes."""
    low = text.lower()
    # Risk Factors: among all "risk factors" hits, the REAL section is the one
    # with the most content before the next "Item N" heading (TOC entries and
    # cross-references are short). Picking by content beats "2nd occurrence".
    risk = None
    best_start, best_len = None, 0
    for m in re.finditer(r"risk\s+factors", low):
        s = m.start()
        nxt = re.search(r"\n\s*item\s+\d", low[s + 80: s + 80_000])
        seg_len = nxt.start() if nxt else 60_000
        if seg_len > best_len:
            best_len, best_start = seg_len, s
    if best_start is not None and best_len > 2000:
        risk = text[best_start: best_start + 60_000]
    # Business: try the strongest anchors first (20-F Item 4 / S-1 Business).
    biz = None
    for pat in (
        r"item\s*4[.\s].{0,60}?information on the company",
        r"business overview", r"overview of our business",
        r"our business", r"company overview", r"prospectus summary",
        r"\bbusiness\b",
    ):
        m = re.search(pat, low)
        if m and m.start() > 1500:  # skip the TOC near the very top
            biz = text[m.start():m.start() + 45_000]
            break
    if not biz:
        biz = text[5_000:50_000]  # fallback: skip cover/TOC, take the body
    return biz, risk


def get_foreign_sections(ticker: str) -> Optional[SlicedSections]:
    """20-F / S-1 → SlicedSections (Business + Risk Factors + Item 5 MD&A).
    None if no such filing. Used as a fallback when get_10k_sections returns None."""
    cik = lookup_cik(ticker)
    if cik is None:
        return None
    sub = get_submissions(cik)
    f = _latest_foreign_filing(sub)
    if f is None:
        logger.info("sec_edgar: no 20-F/S-1 for CIK %s", cik)
        return None
    html = fetch_filing_html(cik, f.accession, f.primary_doc)
    text = _html_to_text(html)
    biz, risk = _slice_foreign(text)
    # 20-F Item 5 is the MD&A equivalent — without it the segment and debt
    # extractors have no source at all and report empty forever.
    mda = _slice_foreign_mda(text)
    return SlicedSections(
        item1_full=biz, item1_competition=None, item1_customers=None,
        item1_suppliers=None, item1a_risks=risk, item7_mda=mda,
        source_url=filing_url(cik, f.accession, f.primary_doc),
        filing_date=f.filing_date, accession=f.accession,
    )
