# agent/web/ — Unified web access layer for NeoMind
#
# Architecture:
#   cache.py      → URL response cache with TTL
#   extractor.py  → Content extraction (trafilatura, readability, BS4, Playwright)
#   crawler.py    → Multi-page BFS crawl
#
# Usage:
#   from agent.web.extractor import WebExtractor
#   from agent.web.cache import URLCache
#   from agent.web.crawler import BFSCrawler
