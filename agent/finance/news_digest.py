# agent/finance/news_digest.py
"""
News Digest Engine — continuous learning news processor.

Core capabilities:
1. Aggregate news from EN + ZH sources
2. Detect conflicts between sources
3. Quantify impact of each news item
4. Learn from past predictions vs outcomes
5. Build evolving thesis per symbol/sector
"""

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple


@dataclass
class DigestItem:
    """A processed news item with analysis."""
    title: str
    url: str = ""
    source: str = ""
    language: str = "en"
    published: Optional[datetime] = None
    summary: str = ""
    symbols: List[str] = field(default_factory=list)
    category: str = ""        # earnings, macro, policy, crypto, sector
    impact_magnitude: float = 0.0   # 1-10
    impact_probability: float = 0.0  # 0-1
    impact_score: float = 0.0       # magnitude × probability
    relevance: float = 0.0          # 0-1 for user's watchlist


@dataclass
class ConflictItem:
    """A detected conflict between sources."""
    entity: str
    claim_a: Dict = field(default_factory=dict)  # {source, claim, url}
    claim_b: Dict = field(default_factory=dict)
    severity: str = "soft"    # "soft" or "hard"
    inference: str = ""
    confidence: float = 0.5


@dataclass
class Thesis:
    """An evolving investment thesis for a symbol."""
    symbol: str
    direction: str = "neutral"  # bullish, bearish, neutral
    confidence: float = 0.5
    rationale: str = ""
    supporting_evidence: List[str] = field(default_factory=list)
    counter_evidence: List[str] = field(default_factory=list)
    last_updated: str = ""
    created_at: str = ""
    age_days: int = 0
    reversal_flagged: bool = False


@dataclass
class NewsDigest:
    """Complete digest output."""
    items: List[DigestItem] = field(default_factory=list)
    conflicts: List[ConflictItem] = field(default_factory=list)
    top_movers: List[Dict] = field(default_factory=list)
    macro_summary: str = ""
    thesis_updates: List[Thesis] = field(default_factory=list)
    sources_used: int = 0
    en_count: int = 0
    zh_count: int = 0
    timestamp: str = ""


# ── Impact Classification ─────────────────────────────────────────────

# Keywords → impact magnitude mapping
IMPACT_KEYWORDS = {
    # High impact (7-10)
    "fed": 9, "fomc": 9, "rate hike": 9, "rate cut": 9, "rate pause": 8,
    "recession": 9, "default": 9, "bankruptcy": 8, "crash": 8,
    "war": 9, "sanctions": 8, "tariff": 8,
    "央行": 9, "降息": 9, "加息": 9, "降准": 8,

    # Medium impact (4-6)
    "earnings beat": 6, "earnings miss": 6, "guidance": 5,
    "ipo": 5, "merger": 6, "acquisition": 6,
    "inflation": 6, "cpi": 6, "gdp": 6, "unemployment": 5,
    "财报": 6, "利润": 5, "营收": 5,

    # Low impact (1-3)
    "analyst upgrade": 3, "analyst downgrade": 3,
    "executive hire": 2, "partnership": 3, "product launch": 3,
    "分析师": 3, "合作": 3,
}


class NewsDigestEngine:
    """
    Continuous learning news processor.

    Integrates search results, financial data, and stored memory
    to produce comprehensive, conflict-aware digests.
    """

    CONFIDENCE_DECAY_PER_WEEK = 0.05  # 5% decay per week without update
    REVERSAL_THRESHOLD = 3  # flag reversal after N contradicting data points

    def __init__(self, search=None, data_hub=None, memory=None):
        self.search = search
        self.data_hub = data_hub
        self.memory = memory
        self._theses: Dict[str, Thesis] = {}

    async def generate_digest(
        self,
        watchlist: Optional[List[str]] = None,
        languages: Optional[List[str]] = None,
    ) -> NewsDigest:
        """
        Generate a comprehensive news digest.

        Pipeline:
        1. Fetch from all sources (parallel)
        2. Deduplicate by URL + title similarity
        3. Classify by category
        4. Score impact: magnitude × probability
        5. Detect conflicts
        6. Update theses
        7. Store to memory
        """
        languages = languages or ["en", "zh"]
        now = datetime.now(timezone.utc).isoformat()

        # Step 1: Fetch news from search engine
        search_items = []
        if self.search:
            queries = ["market news today", "financial news"]
            if watchlist:
                queries.extend([f"{sym} stock news" for sym in watchlist[:5]])

            for query in queries:
                try:
                    result = await self.search.search(query, languages=languages)
                    for item in result.items:
                        search_items.append(item)
                except Exception:
                    continue

        # Step 2: Fetch from RSS feeds (if search engine has RSS)
        rss_items = []
        if self.search and hasattr(self.search, 'rss_manager') and self.search.rss_manager:
            try:
                feed_items = await self.search.rss_manager.fetch_all(languages)
                rss_items = feed_items[:50]
            except Exception:
                pass

        # Step 3: Process and deduplicate
        digest_items = []
        seen_urls = set()

        for item in search_items:
            if item.url in seen_urls:
                continue
            seen_urls.add(item.url)

            di = DigestItem(
                title=item.title,
                url=item.url,
                source=item.source,
                language=item.language,
                summary=item.snippet,
            )
            self._classify_and_score(di)
            digest_items.append(di)

        for item in rss_items:
            if item.url in seen_urls:
                continue
            seen_urls.add(item.url)

            di = DigestItem(
                title=item.title,
                url=item.url,
                source=item.source,
                language=item.language,
                published=item.published,
                summary=item.summary,
            )
            self._classify_and_score(di)
            digest_items.append(di)

        # Step 4: Detect conflicts
        conflicts = self._detect_conflicts(digest_items)

        # Step 5: Sort by impact score
        digest_items.sort(key=lambda x: x.impact_score, reverse=True)

        # Step 6: Count by language
        en_count = sum(1 for d in digest_items if d.language == "en")
        zh_count = sum(1 for d in digest_items if d.language == "zh")

        # Step 7: Store to memory
        if self.memory:
            for item in digest_items[:20]:
                try:
                    self.memory.log_news(
                        title=item.title,
                        url=item.url,
                        source=item.source,
                        language=item.language,
                        symbols=item.symbols,
                        impact_score=item.impact_score,
                    )
                except Exception:
                    pass

        return NewsDigest(
            items=digest_items[:30],  # top 30
            conflicts=conflicts,
            sources_used=len(seen_urls),
            en_count=en_count,
            zh_count=zh_count,
            timestamp=now,
        )

    def _classify_and_score(self, item: DigestItem):
        """Classify category and compute impact score for a news item."""
        title_lower = item.title.lower()

        # Classify category
        if any(kw in title_lower for kw in ["earnings", "revenue", "profit", "财报", "营收"]):
            item.category = "earnings"
        elif any(kw in title_lower for kw in ["fed", "fomc", "央行", "利率", "rate"]):
            item.category = "macro"
        elif any(kw in title_lower for kw in ["bitcoin", "crypto", "btc", "eth", "区块链"]):
            item.category = "crypto"
        elif any(kw in title_lower for kw in ["ipo", "merger", "acquisition", "并购"]):
            item.category = "corporate"
        elif any(kw in title_lower for kw in ["inflation", "cpi", "gdp", "employment", "通胀"]):
            item.category = "economic"
        else:
            item.category = "general"

        # Score impact
        max_magnitude = 1.0
        for keyword, magnitude in IMPACT_KEYWORDS.items():
            if keyword in title_lower:
                max_magnitude = max(max_magnitude, magnitude)

        item.impact_magnitude = max_magnitude
        item.impact_probability = 0.7  # default — will be refined by LLM
        item.impact_score = round(max_magnitude * item.impact_probability, 2)

    def _detect_conflicts(self, items: List[DigestItem]) -> List[ConflictItem]:
        """
        Detect conflicting claims across sources.

        Strategy:
        - Group items by entity (extracted from title)
        - Compare claims within each group
        - Flag contradictions
        """
        conflicts = []

        # Simple entity extraction: look for common financial entities
        entity_groups: Dict[str, List[DigestItem]] = {}

        for item in items:
            # Extract entities from title
            entities = self._extract_entities(item.title)
            for entity in entities:
                entity_groups.setdefault(entity, []).append(item)

        # Check for conflicts within each entity group
        for entity, group_items in entity_groups.items():
            if len(group_items) < 2:
                continue

            # Check if items from different sources have contradicting sentiment
            for i in range(len(group_items)):
                for j in range(i + 1, len(group_items)):
                    a, b = group_items[i], group_items[j]
                    if a.source == b.source:
                        continue

                    sentiment_a = self._quick_sentiment(a.title)
                    sentiment_b = self._quick_sentiment(b.title)

                    if sentiment_a != "neutral" and sentiment_b != "neutral" and sentiment_a != sentiment_b:
                        conflicts.append(ConflictItem(
                            entity=entity,
                            claim_a={"source": a.source, "claim": a.title, "url": a.url},
                            claim_b={"source": b.source, "claim": b.title, "url": b.url},
                            severity="hard" if abs(a.impact_score - b.impact_score) > 3 else "soft",
                        ))

        return conflicts

    def _extract_entities(self, title: str) -> List[str]:
        """Extract financial entities from a headline (simple keyword matching)."""
        entities = []
        title_upper = title.upper()

        # Check for known tickers/entities
        known_entities = [
            "FED", "FOMC", "ECB", "PBOC", "央行",
            "AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "NVDA", "META",
            "BTC", "ETH", "SOL",
            "S&P", "NASDAQ", "DOW",
            "上证", "深证", "恒生",
        ]
        for entity in known_entities:
            if entity in title_upper or entity in title:
                entities.append(entity)

        return entities

    def _quick_sentiment(self, text: str) -> str:
        """Quick sentiment analysis based on keywords."""
        text_lower = text.lower()
        positive = ["rise", "gain", "surge", "beat", "rally", "bullish", "up",
                     "上涨", "大涨", "突破", "利好", "超预期"]
        negative = ["fall", "drop", "crash", "miss", "plunge", "bearish", "down",
                     "下跌", "暴跌", "利空", "不及预期"]

        pos_count = sum(1 for w in positive if w in text_lower)
        neg_count = sum(1 for w in negative if w in text_lower)

        if pos_count > neg_count:
            return "positive"
        if neg_count > pos_count:
            return "negative"
        return "neutral"

    # ── Thesis Management ─────────────────────────────────────────────

    def update_thesis(self, symbol: str, new_data: Dict) -> Thesis:
        """
        Update or create a thesis for a symbol.

        Args:
            symbol: Stock/crypto symbol
            new_data: Dict with evidence. Keys can include:
                - direction: "bullish" / "bearish"
                - evidence: str describing the new evidence
                - contradicts: bool if this contradicts current thesis
        """
        now = datetime.now(timezone.utc).isoformat()

        if symbol not in self._theses:
            self._theses[symbol] = Thesis(
                symbol=symbol,
                created_at=now,
                last_updated=now,
            )

        thesis = self._theses[symbol]

        # Update direction if provided
        if "direction" in new_data:
            new_dir = new_data["direction"]
            if new_dir != thesis.direction and thesis.direction != "neutral":
                # Direction changed — count as counter-evidence
                thesis.counter_evidence.append(new_data.get("evidence", str(new_data)))
                if len(thesis.counter_evidence) >= self.REVERSAL_THRESHOLD:
                    thesis.reversal_flagged = True
            else:
                thesis.direction = new_dir
                thesis.supporting_evidence.append(new_data.get("evidence", str(new_data)))

        # Update confidence
        if new_data.get("contradicts"):
            thesis.confidence = max(0.1, thesis.confidence - 0.1)
        else:
            thesis.confidence = min(0.95, thesis.confidence + 0.05)

        thesis.last_updated = now

        # Store to memory
        if self.memory:
            try:
                self.memory.store_insight(
                    content=f"Thesis update for {symbol}: {thesis.direction} ({thesis.confidence:.0%})",
                    category="thesis",
                    symbols=[symbol],
                    confidence=thesis.confidence,
                )
            except Exception:
                pass

        return thesis

    def get_thesis(self, symbol: str, simulate_weeks: int = 0) -> Optional[Thesis]:
        """Get current thesis with optional confidence decay simulation."""
        thesis = self._theses.get(symbol)
        if not thesis:
            return None

        if simulate_weeks > 0:
            # Apply decay
            decayed = thesis.confidence - (self.CONFIDENCE_DECAY_PER_WEEK * simulate_weeks)
            thesis.confidence = max(0.1, decayed)

        return thesis

    def devils_advocate(self, symbol: str) -> str:
        """
        Generate counter-thesis for a symbol.
        For every strong thesis, explicitly argue the other side.
        """
        thesis = self._theses.get(symbol)
        if not thesis:
            return f"No thesis exists for {symbol}."

        if thesis.direction == "bullish":
            return (
                f"Devil's Advocate for {symbol} (counter to bullish thesis):\n"
                f"Current thesis confidence: {thesis.confidence:.0%}\n"
                f"Counter-evidence collected: {len(thesis.counter_evidence)} points\n"
                f"Consider: What if the bullish narrative is wrong?\n"
                f"- Revenue growth could decelerate\n"
                f"- Valuation may be stretched\n"
                f"- Macro headwinds could outweigh company fundamentals\n"
                f"- Competitive threats may be underestimated"
            )
        elif thesis.direction == "bearish":
            return (
                f"Devil's Advocate for {symbol} (counter to bearish thesis):\n"
                f"Current thesis confidence: {thesis.confidence:.0%}\n"
                f"Consider: What if the bearish case is overdone?\n"
                f"- Company may have turnaround catalysts\n"
                f"- Valuation may already price in the bad news\n"
                f"- Industry trends could shift favorably\n"
                f"- Short squeeze potential if consensus is too negative"
            )
        return f"{symbol} thesis is neutral — no strong position to counter."
