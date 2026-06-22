# SEC 10-K iXBRL metadata soup buries Item 1; page-header glue breaks anchors

**Date**: 2026-06-21
**Where**: `agent/data_sources/sec_edgar.py` (`_html_to_text`, `slice_10k_sections`)
**Symptom**: anchored extraction (`stock_anchored_facts`) returns ~nothing for modern
filings — only `business_summary`, zero competitors/customers/suppliers/risks. Live
`fin.db` had 1 business_summary per ticker and **no edges**, for every name.

## WRONG (two stacked, silent bugs)

1. **`_html_to_text` did not strip inline-XBRL metadata.** Modern 10-Ks (Workiva)
   carry an `<ix:header>` + `<ix:resources>` block (~60K chars of CIK / period /
   `*:Member` dimension soup) at the document TOP. `BeautifulSoup(...).get_text()`
   dumps that ahead of the narrative, so `item1_full[:40000]` is pure XBRL soup —
   "Intel" / "Competition" sit ~77K chars deeper and never reach the extractor.
   (AMD: item1_full=34467 chars, zero occurrences of "compet".)

2. **Item-1A / Item-7 body anchors used `\bitem...`.** After flattening, the running
   page-header "Table of Contents" loses its space and GLUES to the header:
   `...ContentsITEM 1A. RISK FACTORS` (AMD literally renders as `sITEM 1A`). `\bitem`
   needs a word boundary, so it matched only the TOC entry, not the body →
   `item1_full = text[3000 : TOC_pos]` (≤5000) → `None`.

Both fail **silently**: the extractor gets garbage/empty text → emits 0 items → no
exception. Reads as "the LLM found no competitors" when it never saw the prose.

## RIGHT

1. Decompose iXBRL metadata before `get_text`:
   `for m in soup.find_all(["ix:header","ix:hidden","ix:resources"]): m.decompose()`
2. Drop the leading `\b` on the item-1A / item-7 anchors (the required
   "risk factors" / "management's discussion" suffix keeps false positives out).
3. Filter TOC anchors via `_body_anchors()` — a real header is followed by prose,
   not by another "Item N" within ~300 chars.

Verified across AMD / META / NVDA / GOOGL / AAPL (no regression). AMD: item1_full
0→62887, item1a_risks 25→131838, competitors 0→**10 verified** (2 dropped
`not_verbatim` — the gate working); coverage 0.14→0.43. META 0.14→0.57.

## WHY it matters

One HTML→text function feeds the ENTIRE anchored pipeline. A silent
extraction-starvation bug there makes every downstream layer (edges / identity /
coverage / theses) look empty while the code "runs fine." **Assert the extractor's
INPUT text is non-trivial and contains an expected token — not just that the call
returned without error.** First hypothesis ("slicer broken → feed item1_full") was a
no-op (competitor already fell back to item1_full, which was itself the soup); the
real fault was one layer deeper. Diagnose to the true root, with evidence.
