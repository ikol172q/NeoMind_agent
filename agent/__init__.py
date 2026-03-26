# agent/__init__.py
from .core import NeoMindAgent
from .search_legacy import OptimizedDuckDuckGoSearch, DuckDuckGoSearch
from .search.engine import UniversalSearchEngine

__all__ = [
    'NeoMindAgent',
    'UniversalSearchEngine',
    'OptimizedDuckDuckGoSearch',
    'DuckDuckGoSearch',
]
