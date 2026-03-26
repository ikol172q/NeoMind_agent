# agent/search/query_expansion.py
"""
Universal Query Expansion — generates variant queries for broader search coverage.

Strategies:
  1. Synonym expansion (general + domain-specific)
  2. Cross-language expansion (EN ↔ ZH)
  3. Time-scope variants for recency-sensitive queries
  4. Reformulation variants (question → statement, etc.)

Works across all NeoMind modes. Domain-specific synonyms loaded per mode.
"""

import re
from typing import List, Dict, Optional


class QueryExpander:
    """Generates variant queries for multi-source search.

    Usage:
        expander = QueryExpander(domain="general")
        variants = expander.expand("latest AI news")
        # → ["latest AI news", "recent artificial intelligence news", "AI新闻"]
    """

    # ── General synonyms (all modes) ─────────────────────────────────
    GENERAL_SYNONYMS: Dict[str, List[str]] = {
        "ai": ["artificial intelligence", "machine learning"],
        "ml": ["machine learning", "deep learning"],
        "llm": ["large language model", "GPT", "language model"],
        "api": ["application programming interface", "REST API", "web API"],
        "db": ["database"],
        "js": ["javascript"],
        "ts": ["typescript"],
        "py": ["python"],
        "latest": ["recent", "new", "current"],
        "best": ["top", "recommended", "most popular"],
        "how to": ["tutorial", "guide"],
        "fix": ["solve", "resolve", "troubleshoot"],
        "error": ["bug", "issue", "problem"],
        "performance": ["optimization", "speed", "efficiency"],
    }

    # ── Financial synonyms (fin mode) ────────────────────────────────
    FINANCE_SYNONYMS: Dict[str, List[str]] = {
        "fed": ["federal reserve", "FOMC", "Jerome Powell"],
        "rate hike": ["interest rate increase", "tightening"],
        "rate cut": ["interest rate decrease", "easing", "dovish"],
        "earnings": ["quarterly results", "revenue report"],
        "ipo": ["initial public offering", "going public"],
        "merger": ["acquisition", "M&A", "buyout"],
        "recession": ["economic downturn", "contraction"],
        "inflation": ["CPI", "consumer prices"],
        "央行": ["中国人民银行", "PBOC", "货币政策"],
        "降息": ["利率下调", "宽松"],
        "加息": ["利率上调", "紧缩"],
        "股市": ["A股", "stock market", "证券市场"],
    }

    # ── Cross-language pairs ─────────────────────────────────────────
    EN_ZH_PAIRS: Dict[str, str] = {
        "stock market": "股市行情",
        "interest rate": "利率",
        "inflation": "通货膨胀",
        "unemployment": "失业率",
        "trade war": "贸易战",
        "real estate": "房地产",
        "cryptocurrency": "加密货币",
        "oil price": "油价",
        "gold price": "金价",
        "artificial intelligence": "人工智能",
        "deep learning": "深度学习",
        "quantum computing": "量子计算",
        "electric vehicle": "电动汽车",
        "semiconductor": "半导体",
    }

    # ── Time-scope trigger words ─────────────────────────────────────
    RECENCY_TRIGGERS = {
        "general": ["news", "latest", "update", "release", "launch", "announcement"],
        "finance": ["stock", "price", "market", "crypto", "bitcoin", "股", "行情", "走势"],
    }

    def __init__(self, domain: str = "general"):
        """
        Args:
            domain: "general", "finance", or "coding"
        """
        self.domain = domain
        self._synonyms = dict(self.GENERAL_SYNONYMS)
        if domain == "finance":
            self._synonyms.update(self.FINANCE_SYNONYMS)

    def expand(self, query: str, max_variants: int = 3) -> List[str]:
        """Generate variant queries for broader coverage.

        Returns [original_query, variant1, variant2, ...].
        Total results ≤ max_variants + 1 (original always first).
        """
        variants = [query]
        query_lower = query.lower()

        # 1. Synonym expansion (pick first matching synonym)
        # Use word-boundary-aware matching to avoid "py" matching inside "python"
        for trigger, synonyms in self._synonyms.items():
            # For short triggers (≤3 chars), require word boundary
            if len(trigger) <= 3:
                pattern = r'\b' + re.escape(trigger) + r'\b'
                if not re.search(pattern, query_lower):
                    continue
            elif trigger not in query_lower:
                continue

            for syn in synonyms[:1]:
                if len(trigger) <= 3:
                    variant = re.sub(r'\b' + re.escape(trigger) + r'\b', syn, query_lower, count=1)
                else:
                    variant = query_lower.replace(trigger, syn, 1)
                if variant not in [v.lower() for v in variants]:
                    variants.append(variant)
            break  # one synonym expansion per query

        # 2. Cross-language expansion
        for en, zh in self.EN_ZH_PAIRS.items():
            if en in query_lower:
                variants.append(zh)
                break
            if zh in query:
                variants.append(en)
                break

        # 3. Time-scope variant
        triggers = self.RECENCY_TRIGGERS.get(self.domain, self.RECENCY_TRIGGERS["general"])
        if any(w in query_lower for w in triggers):
            if "today" not in query_lower and "2026" not in query_lower and "今日" not in query:
                variants.append(f"{query} 2026")

        # 4. Question → statement reformulation
        q_lower = query_lower.strip()
        if q_lower.startswith(("what is ", "what are ", "who is ")):
            # "what is X" → "X explained" or "X definition"
            subject = re.sub(r'^(what is|what are|who is)\s+', '', q_lower).rstrip('?')
            variants.append(f"{subject} explained")

        return variants[:max_variants + 1]

    def set_domain(self, domain: str):
        """Switch domain (e.g., when mode changes)."""
        self.domain = domain
        self._synonyms = dict(self.GENERAL_SYNONYMS)
        if domain == "finance":
            self._synonyms.update(self.FINANCE_SYNONYMS)
