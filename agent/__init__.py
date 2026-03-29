# agent/__init__.py
"""NeoMind Agent — Three-tier architecture.

Core → Services → Personalities (Chat 类人 / Coding 工程师 / Finance 赚钱)

Primary export: NeoMindAgent (aliased as NeoMindCore for forward-compat).
"""
from .core import NeoMindAgent
from .search_legacy import OptimizedDuckDuckGoSearch, DuckDuckGoSearch
from .search.engine import UniversalSearchEngine

# Forward-compatible alias for the eventual rename
NeoMindCore = NeoMindAgent

__all__ = [
    'NeoMindAgent',
    'NeoMindCore',
    'UniversalSearchEngine',
    'OptimizedDuckDuckGoSearch',
    'DuckDuckGoSearch',
]
