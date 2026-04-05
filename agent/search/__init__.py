# agent/search/__init__.py
"""
Universal Search Engine — multi-source, multi-strategy search for all NeoMind modes.

Architecture:
  - 13 search sources (DDG, Google News, Brave, Serper, Tavily, Jina, NewsAPI,
    Exa, SearXNG, Crawl4AI, You.com, Perplexity Sonar, ScrapeGraphAI)
  - Smart query router (news/tech/finance/academic/general)
  - Query expansion (synonyms + cross-language + time-scope + reformulation)
  - RRF fusion with trust-weighted scoring
  - FlashRank + Cohere semantic reranking (optional)
  - Dual content extraction (trafilatura + Crawl4AI fallback)
  - Layered cache (memory 5min + SQLite 24h)
  - Local vector search (FAISS + sentence-transformers)
  - Search quality metrics tracking
  - MCP server for external agent integration
"""

from .engine import UniversalSearchEngine
from .sources import (
    SearchItem, SearchResult,
    DuckDuckGoSource, GoogleNewsRSSSource, NewsAPISource,
    BraveSearchSource, SerperSource, TavilySource,
    SearXNGSource, JinaSearchSource, ExaSearchSource,
    YouComSource, PerplexitySonarSource, ScrapeGraphAIExtractor,
    Crawl4AIExtractor, ContentExtractor,
)
from .reranker import FlashReranker, RRFMerger, CohereReranker
from .query_expansion import QueryExpander
from .router import QueryRouter
from .cache import SearchCache, DiskSearchCache
from .metrics import SearchMetrics
from .vector_store import LocalVectorStore

# Phase 1: Chat 搜索增强
from .multi_source import MultiSourceSynthesizer, SynthesisStrategy
from .deep_summarizer import DeepSummarizer, SummaryResult, summarize
from .citation_manager import CitationManager, Citation, create_citation

__all__ = [
    "UniversalSearchEngine",
    "SearchItem", "SearchResult",
    "DuckDuckGoSource", "GoogleNewsRSSSource", "NewsAPISource",
    "BraveSearchSource", "SerperSource", "TavilySource",
    "SearXNGSource", "JinaSearchSource", "ExaSearchSource",
    "YouComSource", "PerplexitySonarSource", "ScrapeGraphAIExtractor",
    "Crawl4AIExtractor", "ContentExtractor",
    "FlashReranker", "RRFMerger", "CohereReranker",
    "QueryExpander", "QueryRouter",
    "SearchCache", "DiskSearchCache",
    "SearchMetrics",
    "LocalVectorStore",
    # Phase 1: Chat 搜索增强
    "MultiSourceSynthesizer", "SynthesisStrategy",
    "DeepSummarizer", "SummaryResult", "summarize",
    "CitationManager", "Citation", "create_citation",
]
