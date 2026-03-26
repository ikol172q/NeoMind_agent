# agent/search_engine.py
"""
Compatibility bridge — imports from the new agent.search package.

This module exists because agent/search.py (the old DDG-only search)
must coexist during the transition. Once fully migrated, agent/search.py
can be removed and this bridge can import directly from agent.search.

Usage in core.py:
    from .search_engine import UniversalSearchEngine
"""

from .search.engine import UniversalSearchEngine
from .search.sources import SearchItem, SearchResult
from .search.reranker import FlashReranker, RRFMerger
from .search.query_expansion import QueryExpander
from .search.cache import SearchCache

__all__ = [
    "UniversalSearchEngine",
    "SearchItem", "SearchResult",
    "FlashReranker", "RRFMerger",
    "QueryExpander", "SearchCache",
]
