# NeoMind Web Access Enhancement Plan

## Current State Analysis

### What NeoMind Already Has
- `read_webpage()` in `agent/core.py` — 5-layer fallback strategy (trafilatura → BS4 → html2text → requests-html → raw fallback)
- `BrowserDaemon` in `agent/browser/daemon.py` — Playwright-based headless Chromium with goto/text/links/click/snapshot/screenshot
- `/read <url>` command — fetch webpage and inject into AI memory
- `/browse` command — directory browsing only (NOT web browsing)
- Dependencies: `beautifulsoup4`, `trafilatura`, `html2text`, `requests-html`, `playwright` (in optional deps)

### Three Critical Gaps

1. **No Playwright fallback in `read_webpage()`** — When trafilatura/BS4 fail on JS-rendered pages, there's no automatic fallback to BrowserDaemon. The two systems are completely disconnected.

2. **Link extraction disabled** — `_try_trafilatura()` uses `include_links=False`. BS4 strategy also strips links. Users cannot discover or follow sub-links.

3. **No crawl capability** — Can only read single pages. No way to discover and traverse links from a starting URL.

---

## Phase 1: Short-term (1-2 hours) — Improve Single-Page Quality + Link Extraction

### Task 1.1: Wire BrowserDaemon as fallback in `read_webpage()`
**File:** `agent/core.py` → `read_webpage()` method
**Change:** Add `_try_playwright()` as a strategy between `_try_requests_html` and `_try_fallback`
**Details:**
```python
async def _try_playwright(self, url, max_length):
    """Fallback to headless Chromium for JS-rendered pages."""
    try:
        from agent.browser.daemon import get_browser
        browser = await get_browser()
        await browser.execute("goto", [url])
        text = await browser.execute("text", [])
        return text[:max_length] if text and len(text.strip()) > 100 else None
    except Exception:
        return None
```
**Note:** `read_webpage()` is currently sync. Need to either:
- (a) Use `asyncio.run()` / `asyncio.get_event_loop().run_until_complete()` to call async BrowserDaemon from sync context, OR
- (b) Make `read_webpage()` async (bigger refactor, save for Phase 2)

**Recommended:** Option (a) for now — minimal disruption.

### Task 1.2: Enable link extraction in trafilatura
**File:** `agent/core.py` → `_try_trafilatura()` method (line ~2169)
**Change:** `include_links=False` → `include_links=True`
**Impact:** Extracted text will include `[link text](url)` markdown-style links.

### Task 1.3: Add link extraction to BS4 strategy
**File:** `agent/core.py` → `_try_beautifulsoup()` method
**Change:** After extracting text, also extract all `<a href>` tags and append a "Links" section at the bottom of the output.

### Task 1.4: New `/links <url>` command
**File:** `agent/core.py` → add `handle_links_command()` method + register in command dict
**Behavior:**
1. Fetch the URL (reuse `requests.get` with same headers as BS4 strategy)
2. Parse with BS4, extract all `<a href>` tags
3. Classify as internal (same domain) vs external
4. Return numbered list:
   ```
   Internal Links:
   [1] About Us → /about
   [2] Products → /products

   External Links:
   [3] GitHub → https://github.com/...
   ```
5. User can then say `/read 3` to follow link #3

**Dependencies:** None new — uses existing `beautifulsoup4` + `requests`.

---

## Phase 2: Medium-term (1-2 days) — Deep Reading + Crawl

### Task 2.1: Integrate `readability-lxml` for article extraction
**Install:** `pip install readability-lxml`
**License:** BSD (free, open-source, no lock-in)
**File:** `agent/core.py` → add `_try_readability()` strategy
**Details:**
```python
def _try_readability(self, url, max_length):
    from readability import Document
    import html2text

    response = requests.get(url, headers=self._default_headers(), timeout=15)
    doc = Document(response.text)
    clean_html = doc.summary()
    title = doc.title()

    h = html2text.HTML2Text()
    h.ignore_links = False  # Keep links!
    h.ignore_images = True
    markdown = h.handle(clean_html)

    return f"# {title}\n\n{markdown}"[:max_length]
```
**Insert position:** After trafilatura, before BS4 (readability has F1=0.937, very high quality).

### Task 2.2: New `/crawl <url> [depth]` command
**File:** New file `agent/web/crawler.py` + register command in `core.py`
**Behavior:**
```
/crawl https://docs.example.com 2
```
1. Fetch start URL, extract content + links
2. Filter to same-domain links only
3. BFS up to `depth` levels (default: 1)
4. Cap at `max_pages` (default: 10) to prevent runaway
5. Return structured output:
   ```
   Crawled 8 pages from docs.example.com (depth=2)

   [1] / — Getting Started (2,340 words)
   [2] /install — Installation Guide (1,200 words)
   ...
   ```
6. All content added to AI memory for Q&A.

**Key design decisions:**
- Same-domain only by default (safety)
- Respect robots.txt
- Rate limit: 1 req/sec (polite crawling)
- User can override max_pages with flag: `/crawl --max 20 <url>`

### Task 2.3: URL request cache
**File:** `agent/web/cache.py`
**Mechanism:** In-memory dict with TTL (30 min default)
```python
_cache: Dict[str, Tuple[str, float]] = {}  # url → (content, timestamp)
```
**Benefit:** `/crawl` won't re-fetch pages already read via `/read`. Saves bandwidth, speeds up workflow.

### Task 2.4: readability + html2text → high-quality Markdown output
**Details:** Wire readability extraction through html2text converter with optimal settings:
- `ignore_links = False` (preserve links for crawling)
- `body_width = 0` (no line wrapping)
- `unicode_snob = True` (preserve unicode)
- `protect_links = True`

### Task 2.5: Update pyproject.toml dependencies
Add to `[project.optional-dependencies]` → `full`:
```toml
"readability-lxml>=0.8.1",
```

---

## Phase 3: Long-term (3-5 days) — Production-Grade Crawling

### Task 3.1: Integrate Crawl4AI
**Install:** `pip install crawl4ai && crawl4ai-setup`
**License:** Apache 2.0 (free, open-source, no lock-in)
**GitHub:** github.com/unclecode/crawl4ai (62k+ stars)
**Why:**
- 4x faster than Firecrawl self-hosted
- Built-in anti-detection (stealth mode)
- Built-in caching
- Outputs structured Markdown with metadata
- Pure Python, no Docker/Redis needed
- Designed for AI agents

**Integration point:** Replace the BFS crawler from Phase 2 with Crawl4AI's native deep crawl:
```python
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig

async with AsyncWebCrawler() as crawler:
    result = await crawler.arun(url=url, config=CrawlerRunConfig(...))
    # result.markdown, result.links, result.metadata
```

### Task 3.2: Add playwright-stealth to BrowserDaemon
**Install:** `pip install playwright-stealth`
**File:** `agent/browser/daemon.py` → `start()` method
**Change:** After creating page, apply stealth:
```python
from playwright_stealth import stealth_async
await stealth_async(self._page)
```
**Impact:** Major sites (Cloudflare-protected, etc.) that currently block NeoMind's browser will become accessible.

### Task 3.3: New `/webmap <url>` command
**Behavior:** Quick sitemap discovery:
1. Try fetching `/sitemap.xml` first
2. If not available, do a shallow BFS (depth=1) to discover top-level links
3. Output categorized site structure:
   ```
   docs.example.com Site Map:
   ├── Getting Started (5 pages)
   │   ├── /install
   │   ├── /quickstart
   │   └── ...
   ├── API Reference (12 pages)
   └── Blog (8 posts)
   ```

### Task 3.4: Unified `agent/web/` module architecture
**New directory structure:**
```
agent/web/
├── __init__.py
├── fetcher.py      # Layer 1: HTTP fetch (requests, aiohttp)
├── renderer.py     # Layer 2: JS rendering (BrowserDaemon wrapper)
├── extractor.py    # Layer 3: Content extraction (readability, trafilatura, BS4)
├── crawler.py      # Layer 4: Multi-page crawl (BFS + Crawl4AI)
├── cache.py        # URL response cache
└── links.py        # Link extraction and classification
```
**Benefit:** Clean separation of concerns. Each layer can be tested independently. `read_webpage()` in core.py becomes a thin wrapper that calls these layers.

---

## Dependency Summary

| Phase | New Dependency | License | Size | Purpose |
|-------|---------------|---------|------|---------|
| 1 | None | — | — | Uses existing deps |
| 2 | `readability-lxml` | BSD | ~50KB | Article extraction (F1=0.937) |
| 3 | `crawl4ai` | Apache 2.0 | ~2MB | Production crawling engine |
| 3 | `playwright-stealth` | MIT | ~30KB | Anti-bot-detection for Playwright |

**Total cost: $0. All free, open-source, no vendor lock-in.**

---

## Content Extraction Quality Benchmarks

| Tool | F1 Score | Best For | Currently in NeoMind? |
|------|----------|----------|----------------------|
| trafilatura | 0.945 | News/articles | Yes (optional dep) |
| readability-lxml | 0.937 | Article body | No → Add in Phase 2 |
| BS4 (manual rules) | ~0.70-0.85 | General HTML | Yes (core dep) |
| html2text | ~0.80 | HTML→Markdown | Yes (optional dep) |
| requests-html | ~0.75 | JS-rendered SPA | Yes (optional dep) |
| Crawl4AI | 0.90-0.95 | AI-optimized | No → Add in Phase 3 |

---

## Files to Modify

| File | Phase | Changes |
|------|-------|---------|
| `agent/core.py` | 1, 2 | Add Playwright fallback, enable links, new commands |
| `agent/browser/daemon.py` | 1, 3 | Stealth plugin, expose as fallback |
| `pyproject.toml` | 2, 3 | New optional dependencies |
| `agent/web/__init__.py` | 3 | New module |
| `agent/web/fetcher.py` | 3 | HTTP fetch layer |
| `agent/web/renderer.py` | 3 | JS rendering layer |
| `agent/web/extractor.py` | 3 | Content extraction layer |
| `agent/web/crawler.py` | 2, 3 | Crawl logic |
| `agent/web/cache.py` | 2 | URL cache |
| `agent/web/links.py` | 1, 2 | Link extraction/classification |
