# agent/search/router.py
"""
Search Router — classifies queries and selects optimal source combinations.

Query types:
  - news:      Time-sensitive events, breaking news → prioritize Brave News, Google News, NewsAPI
  - tech:      Programming, libraries, APIs       → prioritize Serper (Google), DDG, Jina
  - academic:  Research papers, definitions        → prioritize Exa (semantic), Tavily
  - finance:   Markets, stocks, crypto             → all sources + financial RSS
  - general:   Everything else                     → balanced mix via RRF

The router doesn't prevent any source from firing — it adjusts trust weights
and result limits per source to optimize the blend for each query type.
"""

import re
from typing import Dict, List, Tuple, Optional


class QueryRouter:
    """Classifies search queries and returns optimized source configurations.

    Usage:
        router = QueryRouter()
        query_type, weights = router.route("latest news on AI regulation")
        # → ("news", {"brave": 0.9, "gnews_en": 0.9, "serper_news": 0.8, ...})
    """

    # ── Query type detection patterns ────────────────────────────────

    NEWS_PATTERNS = [
        r"\b(news|breaking|headline|today|yesterday|this week|this month)\b",
        r"\b(announcement|announced|releases?d?|launches?d?|update)\b",
        r"\b(happened|happening|event|incident|report)\b",
        r"(政策|新闻|公告|发布|事件|最新)",  # Chinese news triggers
    ]

    TECH_PATTERNS = [
        r"\b(python|javascript|typescript|rust|go|java|ruby|swift|kotlin)\b",
        r"\b(api|sdk|library|framework|package|module|npm|pip|cargo)\b",
        r"\b(github|stackoverflow|documentation|tutorial|how to|setup|install)\b",
        r"\b(bug|error|fix|debug|exception|traceback|deprecat)\b",
        r"\b(docker|kubernetes|aws|gcp|azure|terraform|CI/CD)\b",
        r"\b(react|vue|angular|nextjs|fastapi|django|flask|express)\b",
        r"(代码|编程|开发|部署|框架|接口)",  # Chinese tech triggers
    ]

    FINANCE_PATTERNS = [
        r"\b(stock|share|equity|bond|treasury|yield)\b",
        r"\b(market|nasdaq|s&p|dow|nyse|ipo|etf)\b",
        r"\b(crypto|bitcoin|ethereum|btc|eth|defi|nft)\b",
        r"\b(fed|fomc|interest rate|inflation|cpi|gdp|unemployment)\b",
        r"\b(earnings|revenue|profit|dividend|valuation|p/e|eps)\b",
        r"(股票|基金|A股|港股|美股|加密|币|行情|涨跌|央行|降息|加息)",
        r"\$[A-Z]{1,5}\b",  # $AAPL, $TSLA
    ]

    ACADEMIC_PATTERNS = [
        r"\b(research|paper|study|journal|arxiv|pubmed|scholar)\b",
        r"\b(theory|theorem|algorithm|proof|hypothesis|experiment)\b",
        r"\b(definition|explain|what is)\b|概念|定义|论文|研究",
    ]

    # ── Source trust weight profiles per query type ───────────────────
    # Higher weight = more trusted for this query type
    # These override the default 0.5 trust in RRF merger

    WEIGHT_PROFILES: Dict[str, Dict[str, float]] = {
        "news": {
            "brave": 0.85, "brave_news": 0.95,
            "serper": 0.80, "serper_news": 0.90,
            "gnews_en": 0.90, "gnews_zh": 0.85,
            "newsapi": 0.90,
            "tavily": 0.75,
            "ddg_en": 0.65, "ddg_zh": 0.60,
            "jina": 0.60,
            "searxng": 0.70,
        },
        "tech": {
            "serper": 0.90, "serper_kg": 0.95,  # Google excels at tech
            "ddg_en": 0.80,
            "brave": 0.80,
            "jina": 0.85,      # Jina's semantic search good for tech
            "tavily": 0.80,
            "gnews_en": 0.40,  # News less relevant for tech queries
            "gnews_zh": 0.35,
            "newsapi": 0.30,
            "searxng": 0.75,
        },
        "finance": {
            "brave": 0.80, "brave_news": 0.85,
            "serper": 0.85, "serper_news": 0.90,
            "gnews_en": 0.85, "gnews_zh": 0.80,
            "newsapi": 0.85,
            "tavily": 0.80,
            "ddg_en": 0.70, "ddg_zh": 0.65,
            "jina": 0.65,
            "rss": 0.85,  # Financial RSS feeds highly relevant
            "searxng": 0.70,
        },
        "academic": {
            "tavily": 0.90,    # Tavily good at deep content extraction
            "jina": 0.90,      # Semantic search excels for academic
            "serper": 0.80,
            "brave": 0.75,
            "ddg_en": 0.70,
            "gnews_en": 0.40,
            "gnews_zh": 0.35,
            "newsapi": 0.30,
            "searxng": 0.70,
        },
        "general": {
            # Balanced weights — no strong preference
            "brave": 0.75,
            "serper": 0.75,
            "ddg_en": 0.70, "ddg_zh": 0.65,
            "gnews_en": 0.60, "gnews_zh": 0.55,
            "tavily": 0.75,
            "jina": 0.70,
            "newsapi": 0.55,
            "searxng": 0.65,
        },
    }

    def route(self, query: str) -> Tuple[str, Dict[str, float]]:
        """Classify a query and return optimal source trust weights.

        Args:
            query: The search query string

        Returns:
            (query_type, trust_weights) where query_type is one of
            "news", "tech", "finance", "academic", "general"
            and trust_weights is {source_name: trust_score}
        """
        query_type = self.classify(query)
        weights = self.WEIGHT_PROFILES.get(query_type, self.WEIGHT_PROFILES["general"])
        return query_type, weights

    def classify(self, query: str) -> str:
        """Classify a query into a type based on pattern matching.

        Returns the type with the highest match score.
        Finance and tech take priority over news when tied, because
        "Fed rate cut today" is finance (not generic news).
        """
        scores = {
            "finance": self._score(query, self.FINANCE_PATTERNS),
            "tech": self._score(query, self.TECH_PATTERNS),
            "academic": self._score(query, self.ACADEMIC_PATTERNS),
            "news": self._score(query, self.NEWS_PATTERNS),
        }

        # Need at least 1 pattern match to classify as non-general
        # Priority order: finance > tech > academic > news (when tied)
        best_type = max(scores, key=scores.get)
        best_score = scores[best_type]

        if best_score < 1:
            return "general"

        # If finance/tech tie with news, prefer the more specific category
        if best_type == "news" and best_score > 0:
            for specific in ("finance", "tech", "academic"):
                if scores[specific] >= best_score:
                    return specific

        return best_type

    def _score(self, query: str, patterns: List[str]) -> int:
        """Count how many patterns match in the query."""
        query_lower = query.lower()
        count = 0
        for pattern in patterns:
            if re.search(pattern, query_lower):
                count += 1
        return count

    def get_profile(self, query_type: str) -> Dict[str, float]:
        """Get the trust weight profile for a query type."""
        return self.WEIGHT_PROFILES.get(query_type, self.WEIGHT_PROFILES["general"])
