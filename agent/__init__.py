# agent/__init__.py
from .core import NeoMindAgent
from .search import OptimizedDuckDuckGoSearch, DuckDuckGoSearch

__all__ = [
    'NeoMindAgent',
    'OptimizedDuckDuckGoSearch',
    'DuckDuckGoSearch'
]