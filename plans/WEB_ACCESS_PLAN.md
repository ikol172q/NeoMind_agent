# NeoMind Web Access Enhancement Plan

> **Version:** v3 (2026-03-26) — Updated with implementation status
> **Status:** Phase 1 + Phase 2 + Auto-trigger + Telegram: **DONE** | Phase 3: PENDING

---

## Implementation Status

### Phase 1: Single-Page Quality + Link Extraction — ✅ DONE

| Task | Status | Files Changed |
|------|--------|---------------|
| 1.1 Sync→async bridge (`_browser_sync`, `_browser_loop`) | ✅ Done | `agent/core.py` |
| 1.2 `_try_playwright()` inserted in strategy chain | ✅ Done | `agent/core.py` |
| 1.3 trafilatura: `include_links=True`, `include_tables=True`, `include_formatting=True` | ✅ Done | `agent/core.py` |
| 1.4 BS4 strategy: link extraction + `--- Links Found ---` block | ✅ Done | `agent/core.py` |
| 1.5 `/links` command + `/read N` follow-up + `_last_links` storage | ✅ Done | `agent/core.py` |
| 1.6 `_add_webpage_to_memory()`: 6000→10000 chars + links section protection | ✅ Done | `agent/core.py` |

### Phase 2: Multi-Page Crawl + Unified Architecture — ✅ DONE

| Task | Status | Files Changed |
|------|--------|---------------|
| 2.1 `agent/web/extractor.py` — WebExtractor with 5 strategies | ✅ Done | New file |
| 2.2 `readability-lxml` integrated as strategy #2 | ✅ Done | `agent/web/extractor.py` |
| 2.3 `/crawl` command + `BFSCrawler` + `CrawlReport` | ✅ Done | `agent/web/crawler.py`, `agent/core.py` |
| 2.4 `URLCache` with 30min TTL | ✅ Done | `agent/web/cache.py` |
| 2.5 `pyproject.toml`: `readability-lxml`, `[web]` dep group, `agent.web` package | ✅ Done | `pyproject.toml` |

### Auto-Trigger Integration — ✅ DONE

| Task | Status | Files Changed |
|------|--------|---------------|
| `classify_and_enhance_input()` — URL + context → auto `/read`/`/links`/`/crawl` | ✅ Done (9/9 tests) | `agent/core.py` |
| `NaturalLanguageInterpreter` — web_read, web_links, web_crawl patterns (中英文) | ✅ Done (10/10 tests) | `agent/natural_language.py` |
| System prompt — WEB ACCESS TOOLS section added | ✅ Done | `agent/config/chat.yaml`, `agent/config/coding.yaml` |

### Telegram Bot Integration — ✅ DONE

| Task | Status | Files Changed |
|------|--------|---------------|
| `/read`, `/links`, `/crawl` registered as Telegram commands | ✅ Done | `agent/finance/telegram_bot.py` |
| Web command handlers with Telegram formatting + reaction lifecycle | ✅ Done | `agent/finance/telegram_bot.py` |
| URL auto-detection in `_process_and_reply` → auto-fetch + inject LLM context | ✅ Done | `agent/finance/telegram_bot.py` |
| `/read N` follow-up from `/links` result (per-chat link storage) | ✅ Done | `agent/finance/telegram_bot.py` |
| `/help` updated with 🌐 网页 section | ✅ Done | `agent/finance/telegram_bot.py` |
| WebExtractor + URLCache lazy init in bot `__init__` | ✅ Done | `agent/finance/telegram_bot.py` |

### Phase 3: Production-Grade (PENDING — do when needed)

| Task | Status | Details |
|------|--------|---------|
| 3.1 Upgrade Crawl4AI as `/crawl` primary engine | Pending | Replace BFS with Crawl4AI native deep crawl |
| 3.2 `playwright-stealth` for BrowserDaemon | Pending | Anti-bot detection for Cloudflare etc. |
| 3.3 `/webmap <url>` command | Pending | Sitemap discovery + tree view |
| 3.4 Full `agent/web/` refactor (fetcher/renderer layers) | Pending | Move extraction logic out of core.py |
| 3.5 `pyproject.toml` Phase 3 deps | Pending | `crawl4ai`, `playwright-stealth` |

---

## New Commands (all implemented)

```
/read <url>                    — Read single page (6 strategies + Playwright fallback)
/read N                        — Follow link #N from last /links result
/links <url>                   — Extract all links, numbered (internal/external split)
/links                         — Re-show last link list
/crawl <url>                   — BFS crawl same-domain pages (default: depth=1, max=10)
/crawl <url> --depth 2 --max 20
```

## Auto-Trigger (no manual commands needed)

Users can use natural language — NeoMind auto-detects intent:

| User says | Auto-triggers |
|-----------|--------------|
| Paste bare URL `https://...` | → `/read <url>` |
| "帮我看看 https://..." / "read https://..." | → `/read <url>` |
| "爬取 https://..." / "crawl https://..." | → `/crawl <url>` |
| "提取链接 https://..." / "show links from https://..." | → `/links <url>` |

Works via 3 layers:
1. `classify_and_enhance_input()` — input pre-processing (regex, keyword matching)
2. `NaturalLanguageInterpreter` — pattern-based NL→command mapping
3. System prompt — LLM knows about tools, can decide to invoke them

---

## Files Modified (complete list)

| File | What Changed |
|------|-------------|
| `agent/core.py` | +340 lines: bridge, strategies, /links, /crawl, /read N, memory upgrade, URL auto-detect |
| `agent/natural_language.py` | +20 lines: web_read, web_links, web_crawl patterns |
| `agent/config/chat.yaml` | +10 lines: WEB ACCESS TOOLS in system prompt |
| `agent/config/coding.yaml` | +7 lines: WEB ACCESS TOOLS in system prompt |
| `agent/web/__init__.py` | New: module init |
| `agent/web/extractor.py` | New: WebExtractor (5 strategies, link extraction, scoring) |
| `agent/web/crawler.py` | New: BFSCrawler, CrawlResult, CrawlReport |
| `agent/web/cache.py` | New: URLCache with TTL |
| `agent/finance/telegram_bot.py` | +200 lines: /read, /links, /crawl commands, URL auto-fetch, WebExtractor init |
| `pyproject.toml` | +readability-lxml, +[web] dep group, +agent.web package |

## Dependencies Added

| Dependency | License | Phase | Required? |
|-----------|---------|-------|-----------|
| `readability-lxml` | BSD | 2 | Optional (graceful fallback) |
| `crawl4ai` | Apache 2.0 | 3 (future) | Optional |
| `playwright-stealth` | MIT | 3 (future) | Optional |

**Cost: $0. All free, open-source, no vendor lock-in.**
