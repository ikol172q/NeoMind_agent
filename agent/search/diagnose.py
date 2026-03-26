#!/usr/bin/env python3
# agent/search/diagnose.py
"""
Search Engine Diagnostic Tool — run this to check the health of all search components.

Usage:
    python -m agent.search.diagnose          # Quick status check
    python -m agent.search.diagnose --live   # Live search test (requires network)
"""

import sys
import os
import asyncio
import time

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def check_dependencies():
    """Check which optional dependencies are installed."""
    print("\n[Dependencies]")
    deps = {
        "duckduckgo_search": "DuckDuckGo search (Tier 1)",
        "feedparser": "Google News RSS parsing (Tier 1)",
        "trafilatura": "Content extraction (primary)",
        "flashrank": "FlashRank semantic reranker",
        "lxml": "Fast HTML parsing",
        "aiohttp": "Async HTTP client",
        "crawl4ai": "Crawl4AI content extraction (fallback)",
    }
    for module, desc in deps.items():
        try:
            __import__(module)
            print(f"  + {desc} ({module})")
        except ImportError:
            print(f"  - {desc} ({module}) — pip install {module}")


def check_api_keys():
    """Check which API keys are configured."""
    print("\n[API Keys]")
    keys = {
        "BRAVE_API_KEY": "Brave Search (Tier 2)",
        "SERPER_API_KEY": "Serper.dev Google SERP (Tier 2)",
        "TAVILY_API_KEY": "Tavily AI Search (Tier 2)",
        "JINA_API_KEY": "Jina AI Search (Tier 2)",
        "NEWSAPI_API_KEY": "NewsAPI.org (Tier 2)",
        "SEARXNG_URL": "SearXNG self-hosted (Tier 3)",
    }
    configured = 0
    for key, desc in keys.items():
        val = os.getenv(key)
        if val:
            # Mask the key
            masked = val[:4] + "..." + val[-4:] if len(val) > 8 else "***"
            print(f"  + {desc}: {masked}")
            configured += 1
        else:
            print(f"  - {desc}: not set")
    print(f"\n  {configured}/{len(keys)} API keys configured")


def check_engine():
    """Initialize and display engine status."""
    print("\n[Engine Status]")
    from agent.search.engine import UniversalSearchEngine
    engine = UniversalSearchEngine(domain="general")
    print(engine.get_status())
    return engine


def check_router():
    """Test the query router."""
    print("\n[Query Router]")
    from agent.search.router import QueryRouter
    router = QueryRouter()
    test_queries = [
        "latest news on AI", "python tutorial async await",
        "AAPL stock price", "quantum computing papers",
        "best pizza in New York", "央行降息", "react component tutorial",
    ]
    for q in test_queries:
        qtype = router.classify(q)
        print(f"  {qtype:10s} ← \"{q}\"")


def check_expansion():
    """Test query expansion."""
    print("\n[Query Expansion]")
    from agent.search.query_expansion import QueryExpander
    exp = QueryExpander(domain="general")
    tests = ["AI regulation news", "how to fix python import error", "what is blockchain"]
    for q in tests:
        variants = exp.expand(q)
        print(f"  \"{q}\" → {len(variants)} variants: {variants}")


async def live_search_test(engine):
    """Run a live search test (requires network)."""
    print("\n[Live Search Test]")
    query = "artificial intelligence latest developments 2026"
    print(f"  Query: \"{query}\"")
    start = time.time()
    success, text = await engine.search(query)
    elapsed = time.time() - start
    print(f"  Success: {success}")
    print(f"  Time: {elapsed:.2f}s")
    if success:
        lines = text.split("\n")
        for line in lines[:15]:
            print(f"  {line}")
        if len(lines) > 15:
            print(f"  ... ({len(lines) - 15} more lines)")
    else:
        print(f"  Error: {text}")


def main():
    live = "--live" in sys.argv

    print("=" * 60)
    print("  NeoMind Universal Search Engine — Diagnostic Report")
    print("=" * 60)

    check_dependencies()
    check_api_keys()
    engine = check_engine()
    check_router()
    check_expansion()

    if live:
        asyncio.run(live_search_test(engine))
    else:
        print("\n[Live Search]")
        print("  Skipped (use --live flag to run)")

    print("\n" + "=" * 60)
    print("  Diagnostic complete.")
    print("=" * 60)


if __name__ == "__main__":
    main()
