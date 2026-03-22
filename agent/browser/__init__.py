# agent/browser/__init__.py
"""
NeoMind Browser — persistent headless Chromium daemon.

Inspired by gstack's browse server architecture:
- Persistent Chromium process (survives between commands)
- HTTP server for command dispatch
- ~100ms latency after cold start
- ARIA snapshot → @ref system for reliable element targeting
- Cookie/session persistence across calls

Shared by all 3 personalities:
- chat: web search, information extraction
- coding: UI testing, visual regression
- fin: financial data scraping, evidence screenshots
"""

from .daemon import BrowserDaemon, get_browser

__all__ = ['BrowserDaemon', 'get_browser']
