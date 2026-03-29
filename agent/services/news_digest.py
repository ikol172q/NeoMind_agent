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
    """An evolving investment thesis for a symbol.

    Decision tracking fields (entry_price, checkpoints) enable
    post-hoc accuracy measurement. Inspired by FinMem's self-evolution:
        https://github.com/pipiku915/FinMem-LLM-StockTrading
    """
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

    # ── Decision tracking (new) ──────────────────────────────────
    entry_price: Optional[float] = None       # price when thesis was created
    entry_price_date: str = ""                # date of entry_price snapshot
    checkpoints: List[Dict] = field(default_factory=list)
    # Each checkpoint: {"days": 30, "date": "...", "price": 1.23, "return_pct": 0.05, "correct": True}
    accuracy: Optional[bool] = None           # final verdict: was the thesis correct?
    closed: bool = False                      # thesis still active or resolved?
    closed_reason: str = ""                   # "hit_target" | "stop_loss" | "reversal" | "manual"


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
        self._last_digest_items: List[DigestItem] = []
        self._last_conflicts: List[ConflictItem] = []

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

        # Step 4a: Pre-fetch social sentiment for mentioned symbols
        # So _estimate_impact_probability Signal 6 can read from cache
        mentioned_symbols = set()
        for di in digest_items:
            sym = self._extract_symbol(di.title)
            if sym:
                mentioned_symbols.add(sym)
        if mentioned_symbols:
            try:
                await self.prefetch_social_sentiment(list(mentioned_symbols))
            except Exception:
                pass  # non-critical; scoring works without social data

        # Step 4b: Detect conflicts
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

        # Cache for debate engine access
        self._last_digest_items = digest_items
        self._last_conflicts = conflicts

        return NewsDigest(
            items=digest_items[:30],  # top 30
            conflicts=conflicts,
            sources_used=len(seen_urls),
            en_count=en_count,
            zh_count=zh_count,
            timestamp=now,
        )

    def _classify_and_score(self, item: DigestItem):
        """Classify category and compute impact score for a news item.

        Impact probability is now DYNAMIC instead of the old hardcoded 0.7.
        Uses a multi-signal heuristic:
          - Sentiment strength (strong positive/negative → higher probability)
          - Source trust score (from SourceTrustTracker if available)
          - Specificity signals (named entities, numbers, dates → higher)
          - Category priors (macro/earnings → higher base than general)

        For even better accuracy, integrate FinBERT for sentiment classification:
            https://huggingface.co/ProsusAI/finbert
            https://github.com/ProsusAI/finBERT
        """
        title_lower = item.title.lower()

        # ── Classify category ────────────────────────────────────────
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

        # ── Score magnitude (unchanged) ──────────────────────────────
        max_magnitude = 1.0
        for keyword, magnitude in IMPACT_KEYWORDS.items():
            if keyword in title_lower:
                max_magnitude = max(max_magnitude, magnitude)
        item.impact_magnitude = max_magnitude

        # ── Dynamic impact probability ───────────────────────────────
        item.impact_probability = self._estimate_impact_probability(item)
        item.impact_score = round(max_magnitude * item.impact_probability, 2)

    def _estimate_impact_probability(self, item: DigestItem) -> float:
        """Estimate the probability that a news item actually impacts the market.

        Multi-signal heuristic replacing the old hardcoded 0.7.
        Range: 0.2 (noise) to 0.95 (near-certain impact).
        """
        title_lower = item.title.lower()
        prob = 0.5  # base prior

        # ── Signal 1: Category prior ─────────────────────────────────
        # Macro/earnings news has higher base probability of moving markets
        category_boost = {
            "macro": 0.15,      # Fed decisions almost always move markets
            "earnings": 0.12,   # Earnings reports are concrete events
            "economic": 0.10,   # CPI/GDP are scheduled, market watches closely
            "corporate": 0.08,  # M&A has direct price impact
            "crypto": 0.05,    # Crypto news is noisy, lower base
            "general": 0.0,
        }
        prob += category_boost.get(item.category, 0.0)

        # ── Signal 2: Sentiment strength ─────────────────────────────
        # Strong sentiment (positive or negative) → higher probability of impact
        sentiment = self._quick_sentiment(item.title)
        if sentiment in ("positive", "negative"):
            # Count how many sentiment keywords matched (stronger signal)
            text_lower = item.title.lower()
            positive_kw = ["surge", "soar", "beat", "record", "rally", "breakthrough",
                           "大涨", "暴涨", "突破", "超预期", "创新高"]
            negative_kw = ["crash", "plunge", "collapse", "miss", "default", "crisis",
                           "暴跌", "崩盘", "违约", "危机", "爆雷"]
            strong_count = sum(1 for w in (positive_kw + negative_kw) if w in text_lower)
            if strong_count >= 2:
                prob += 0.15  # very strong language
            elif strong_count == 1:
                prob += 0.08  # moderately strong
            else:
                prob += 0.03  # mild sentiment
        # Neutral sentiment → slight penalty (opinion/noise)

        # ── Signal 3: Specificity ────────────────────────────────────
        # Numbers, percentages, dates → concrete, more likely impactful
        import re
        if re.search(r'\d+\.?\d*%', item.title):
            prob += 0.08  # has a percentage → specific claim
        if re.search(r'\$[\d,.]+[BMKbmk]?', item.title):
            prob += 0.06  # has a dollar amount
        if re.search(r'Q[1-4]\s*20\d{2}|FY\s*20\d{2}', item.title, re.IGNORECASE):
            prob += 0.05  # references a specific quarter/year

        # ── Signal 4: Source trust ───────────────────────────────────
        # If SourceTrustTracker is available, use trust score
        if hasattr(self, 'search') and self.search and hasattr(self.search, 'source_trust'):
            try:
                domain = item.source or ""
                trust = self.search.source_trust.get_trust(domain)
                # trust is typically 0.3-0.9; center around 0.6
                prob += (trust - 0.6) * 0.2  # ±0.06 adjustment
            except Exception:
                pass

        # ── Signal 5: Recency penalty ────────────────────────────────
        # Very old news gets a probability discount (less likely to move markets NOW)
        if item.published:
            try:
                age_hours = (datetime.now(timezone.utc) - item.published).total_seconds() / 3600
                if age_hours > 72:
                    prob -= 0.10  # 3+ days old
                elif age_hours > 24:
                    prob -= 0.05  # 1-3 days old
                # < 24h: no penalty (fresh)
            except Exception:
                pass

        # ── Signal 6: Social sentiment buzz ────────────────────────────
        # If DataHub is available and item mentions a symbol, check social buzz.
        # High buzz + aligned sentiment → higher probability of real impact.
        # Inspired by: Finnhub Social Sentiment API, FinBERT social signals
        if self.data_hub and hasattr(self.data_hub, 'get_social_sentiment'):
            symbol = self._extract_symbol(item.title)
            if symbol:
                try:
                    import asyncio
                    # Try to get from cache (sync-safe); full async call happens in digest flow
                    cache_key = f"social_sentiment_{symbol}"
                    cached = getattr(self.data_hub, 'cache', None)
                    social = cached.get(cache_key, ttl=1800) if cached else None

                    if social:
                        buzz = social.get("buzz_level", "low")
                        score = social.get("overall_score", 0.5)
                        # High buzz amplifies probability
                        if buzz == "high":
                            prob += 0.10
                        elif buzz == "medium":
                            prob += 0.04
                        # Extreme sentiment (very bullish or very bearish) boosts further
                        if score > 0.75 or score < 0.25:
                            prob += 0.06
                except Exception:
                    pass

        # Clamp to valid range
        return max(0.2, min(0.95, round(prob, 2)))

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

    def _extract_symbol(self, text: str) -> Optional[str]:
        """Extract a stock ticker symbol from text.

        Looks for common patterns like $AAPL, AAPL:, or standalone
        1-5 uppercase letter sequences that look like tickers.
        """
        import re
        # $AAPL style
        m = re.search(r'\$([A-Z]{1,5})\b', text)
        if m:
            return m.group(1)
        # AAPL: or (AAPL) style
        m = re.search(r'\b([A-Z]{1,5})[\s]*[:\)]', text)
        if m and m.group(1) not in ("CEO", "CFO", "GDP", "CPI", "IPO", "ETF", "SEC", "FDA", "NYSE", "API"):
            return m.group(1)
        return None

    async def prefetch_social_sentiment(self, symbols: List[str]):
        """Pre-fetch social sentiment for a batch of symbols into DataHub cache.

        Called during generate_digest() so that _estimate_impact_probability()
        can read from cache synchronously.

        Reference: https://finnhub.io/docs/api/social-sentiment
        """
        if not self.data_hub or not hasattr(self.data_hub, 'get_social_sentiment'):
            return
        import asyncio
        tasks = [self.data_hub.get_social_sentiment(s) for s in symbols[:10]]  # limit to 10
        await asyncio.gather(*tasks, return_exceptions=True)

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
                - price: float, current price (auto-fetched from DataHub if omitted)
        """
        now = datetime.now(timezone.utc).isoformat()

        if symbol not in self._theses:
            # New thesis — record entry price for decision tracking
            entry_price = new_data.get("price")
            if entry_price is None and self.data_hub:
                try:
                    quote = self.data_hub.get_quote(symbol)
                    if quote and quote.price:
                        entry_price = quote.price.value
                except Exception:
                    pass

            self._theses[symbol] = Thesis(
                symbol=symbol,
                created_at=now,
                last_updated=now,
                entry_price=entry_price,
                entry_price_date=now,
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

    def checkpoint_thesis(self, symbol: str, current_price: Optional[float] = None) -> Optional[Dict]:
        """
        Record a price checkpoint for an active thesis.
        Call at 30/60/90 day intervals to track accuracy over time.

        Args:
            symbol: Ticker symbol.
            current_price: Current price. Auto-fetched from DataHub if omitted.

        Returns:
            Checkpoint dict or None if no thesis/price available.
        """
        thesis = self._theses.get(symbol)
        if not thesis or thesis.entry_price is None:
            return None

        if current_price is None and self.data_hub:
            try:
                quote = self.data_hub.get_quote(symbol)
                if quote and quote.price:
                    current_price = quote.price.value
            except Exception:
                return None

        if current_price is None:
            return None

        now = datetime.now(timezone.utc)
        created = datetime.fromisoformat(thesis.created_at.replace('Z', '+00:00'))
        days_elapsed = (now - created).days

        return_pct = (current_price - thesis.entry_price) / thesis.entry_price

        # Was direction correct?
        if thesis.direction == "bullish":
            correct = return_pct > 0
        elif thesis.direction == "bearish":
            correct = return_pct < 0
        else:
            correct = None  # neutral → can't judge

        checkpoint = {
            "days": days_elapsed,
            "date": now.isoformat(),
            "price": current_price,
            "return_pct": round(return_pct, 4),
            "correct": correct,
        }

        thesis.checkpoints.append(checkpoint)
        thesis.age_days = days_elapsed

        # Store to memory
        if self.memory:
            try:
                self.memory.store_insight(
                    content=(
                        f"Thesis checkpoint {symbol}: {days_elapsed}d, "
                        f"entry ${thesis.entry_price:.2f} → ${current_price:.2f} "
                        f"({return_pct:+.1%}), direction {thesis.direction}, "
                        f"correct: {correct}"
                    ),
                    category="thesis_checkpoint",
                    symbols=[symbol],
                    confidence=thesis.confidence,
                )
            except Exception:
                pass

        return checkpoint

    def get_accuracy_stats(self) -> Dict:
        """
        Compute aggregate accuracy statistics across all theses.
        Enables "am I getting better over time?" self-reflection.

        Returns:
            Dict with overall accuracy, per-category stats, common errors.
        """
        all_checkpoints = []
        for symbol, thesis in self._theses.items():
            for cp in thesis.checkpoints:
                if cp.get("correct") is not None:
                    all_checkpoints.append({
                        "symbol": symbol,
                        "direction": thesis.direction,
                        "category": thesis.rationale[:20] if thesis.rationale else "unknown",
                        **cp,
                    })

        if not all_checkpoints:
            return {"total": 0, "accuracy": None, "message": "No checkpoints recorded yet."}

        correct_count = sum(1 for cp in all_checkpoints if cp["correct"])
        total = len(all_checkpoints)
        accuracy = correct_count / total

        # Break down by direction
        bull_cps = [cp for cp in all_checkpoints if cp["direction"] == "bullish"]
        bear_cps = [cp for cp in all_checkpoints if cp["direction"] == "bearish"]

        bull_acc = sum(1 for cp in bull_cps if cp["correct"]) / max(len(bull_cps), 1)
        bear_acc = sum(1 for cp in bear_cps if cp["correct"]) / max(len(bear_cps), 1)

        # Average return by correctness
        correct_returns = [cp["return_pct"] for cp in all_checkpoints if cp["correct"]]
        wrong_returns = [cp["return_pct"] for cp in all_checkpoints if not cp["correct"]]

        return {
            "total": total,
            "correct": correct_count,
            "accuracy": round(accuracy, 3),
            "bull_accuracy": round(bull_acc, 3) if bull_cps else None,
            "bear_accuracy": round(bear_acc, 3) if bear_cps else None,
            "avg_return_when_correct": round(sum(correct_returns) / max(len(correct_returns), 1), 4) if correct_returns else None,
            "avg_return_when_wrong": round(sum(wrong_returns) / max(len(wrong_returns), 1), 4) if wrong_returns else None,
            "symbols_tracked": list(set(cp["symbol"] for cp in all_checkpoints)),
        }

    def devils_advocate(self, symbol: str) -> str:
        """
        Generate counter-thesis for a symbol (legacy wrapper).
        Calls debate() and returns the bear/bull side as a string.
        """
        result = self.debate(symbol)
        if isinstance(result, str):
            return result
        # Return the counter-side summary
        return result.get("counter_summary", result.get("error", "No debate output."))

    def debate(self, symbol: str, rounds: int = 1) -> dict:
        """
        Data-driven adversarial debate for a symbol.

        For every Thesis, a Bull Agent and Bear Agent argue from REAL evidence
        (news items, counter-evidence, supporting-evidence, known conflicts).
        Inspired by TradingAgents (Bullish/Bearish Researcher adversarial debate)
        and FREE-MAD (no forced consensus — presenting divergence IS the value).

        References:
            - TradingAgents: https://github.com/TauricResearch/TradingAgents
            - FREE-MAD: https://arxiv.org/pdf/2509.11035
            - Decision Protocols: https://github.com/lkaesberg/decision-protocols
            - DebateLLM: https://github.com/instadeepai/DebateLLM

        Args:
            symbol: Ticker to debate.
            rounds: Number of debate rounds (each round = bull + bear).
                    More rounds → deeper exploration. Default 1 for speed.

        Returns:
            dict with keys:
                symbol, direction, confidence,
                bull_case: {core_argument, key_assumptions, evidence, risk_if_wrong},
                bear_case: {core_argument, key_assumptions, evidence, risk_if_wrong},
                divergence_points: [str],  — where bull and bear fundamentally disagree
                counter_summary: str,      — one-paragraph counter to current thesis
                verdict: str,              — "high_conviction" | "contested" | "insufficient_data"
        """
        thesis = self._theses.get(symbol)
        if not thesis:
            return {"error": f"No thesis exists for {symbol}. Run analysis first."}

        # ── Gather all available evidence ────────────────────────────

        supporting = list(thesis.supporting_evidence)
        counter = list(thesis.counter_evidence)

        # Pull relevant news items from recent digest
        relevant_news = []
        for item in getattr(self, '_last_digest_items', []):
            if symbol.upper() in [s.upper() for s in item.symbols]:
                relevant_news.append({
                    "title": item.title,
                    "source": item.source,
                    "impact": item.impact_score,
                    "category": item.category,
                    "sentiment": self._quick_sentiment(item.title),
                })

        # Pull relevant conflicts
        relevant_conflicts = []
        for conflict in getattr(self, '_last_conflicts', []):
            if symbol.upper() in conflict.entity.upper():
                relevant_conflicts.append({
                    "entity": conflict.entity,
                    "claim_a": conflict.claim_a,
                    "claim_b": conflict.claim_b,
                    "severity": conflict.severity,
                })

        # ── Build Bull Case ──────────────────────────────────────────

        bull_evidence = list(supporting)
        bear_evidence = list(counter)

        # Enrich from news: positive news → bull, negative → bear
        for news in relevant_news:
            entry = f"[{news['source']}] {news['title']} (impact: {news['impact']:.1f})"
            if news["sentiment"] == "positive":
                bull_evidence.append(entry)
            elif news["sentiment"] == "negative":
                bear_evidence.append(entry)
            else:
                # Neutral news with high impact → both sides should consider
                if news["impact"] >= 5:
                    bull_evidence.append(f"(Neutral/High-Impact) {entry}")
                    bear_evidence.append(f"(Neutral/High-Impact) {entry}")

        # Conflicts are evidence for BOTH sides (uncertainty itself is bearish)
        for conflict in relevant_conflicts:
            conflict_str = (
                f"CONFLICT [{conflict['severity']}]: "
                f"{conflict['claim_a'].get('source', '?')}: \"{conflict['claim_a'].get('claim', '?')}\" "
                f"vs {conflict['claim_b'].get('source', '?')}: \"{conflict['claim_b'].get('claim', '?')}\""
            )
            bear_evidence.append(conflict_str)
            bull_evidence.append(f"(Disputed) {conflict_str}")

        # ── Construct structured arguments ───────────────────────────

        bull_case = {
            "core_argument": self._build_bull_argument(symbol, thesis, bull_evidence),
            "key_assumptions": self._build_assumptions("bullish", thesis, bull_evidence),
            "evidence": bull_evidence[:10],  # cap for readability
            "evidence_count": len(bull_evidence),
            "risk_if_wrong": self._risk_if_wrong("bullish", thesis, bear_evidence),
        }

        bear_case = {
            "core_argument": self._build_bear_argument(symbol, thesis, bear_evidence),
            "key_assumptions": self._build_assumptions("bearish", thesis, bear_evidence),
            "evidence": bear_evidence[:10],
            "evidence_count": len(bear_evidence),
            "risk_if_wrong": self._risk_if_wrong("bearish", thesis, bull_evidence),
        }

        # ── Identify divergence points ───────────────────────────────

        divergence = []
        if relevant_conflicts:
            divergence.append(f"Sources disagree on {len(relevant_conflicts)} claim(s)")
        if len(bull_evidence) > 0 and len(bear_evidence) > 0:
            bull_strength = len(bull_evidence)
            bear_strength = len(bear_evidence)
            ratio = bull_strength / max(bear_strength, 1)
            if 0.5 < ratio < 2.0:
                divergence.append(f"Evidence is roughly balanced (bull: {bull_strength}, bear: {bear_strength})")
            elif ratio >= 2.0:
                divergence.append(f"Bull evidence dominates ({bull_strength} vs {bear_strength})")
            else:
                divergence.append(f"Bear evidence dominates ({bear_strength} vs {bull_strength})")
        if thesis.reversal_flagged:
            divergence.append("REVERSAL FLAGGED: counter-evidence accumulation exceeded threshold")
        if thesis.confidence < 0.4:
            divergence.append(f"Low confidence ({thesis.confidence:.0%}) — thesis is weakening")

        # ── Verdict ──────────────────────────────────────────────────

        total_evidence = len(bull_evidence) + len(bear_evidence)
        if total_evidence < 3:
            verdict = "insufficient_data"
        elif thesis.confidence >= 0.7 and not thesis.reversal_flagged and len(relevant_conflicts) == 0:
            verdict = "high_conviction"
        else:
            verdict = "contested"

        # ── Counter-summary (one paragraph, opposing current thesis) ─

        if thesis.direction == "bullish":
            counter_summary = (
                f"BEAR CASE for {symbol}: {bear_case['core_argument']} "
                f"Key risk: {bear_case['risk_if_wrong']} "
                f"Based on {len(bear_evidence)} piece(s) of counter-evidence. "
                f"Verdict: {verdict}."
            )
        elif thesis.direction == "bearish":
            counter_summary = (
                f"BULL CASE for {symbol}: {bull_case['core_argument']} "
                f"Key risk: {bull_case['risk_if_wrong']} "
                f"Based on {len(bull_evidence)} piece(s) of supporting evidence. "
                f"Verdict: {verdict}."
            )
        else:
            counter_summary = (
                f"{symbol} thesis is neutral. "
                f"Bull has {len(bull_evidence)} points, Bear has {len(bear_evidence)} points. "
                f"Verdict: {verdict}."
            )

        return {
            "symbol": symbol,
            "direction": thesis.direction,
            "confidence": thesis.confidence,
            "bull_case": bull_case,
            "bear_case": bear_case,
            "divergence_points": divergence,
            "counter_summary": counter_summary,
            "verdict": verdict,
            "news_count": len(relevant_news),
            "conflict_count": len(relevant_conflicts),
        }

    def debate_with_personas(self, symbol: str) -> dict:
        """Multi-persona debate: Value + Growth + Macro all weigh in.

        Generates structured analysis prompts from three distinct investment
        philosophies, providing the caller with everything needed to send
        to an LLM and collect verdicts.

        References:
            - AI Hedge Fund (12 personas): https://github.com/virattt/ai-hedge-fund
            - TradingAgents multi-role: https://github.com/TauricResearch/TradingAgents

        Returns:
            dict with:
                base_debate: output of self.debate() (bull/bear)
                persona_prompts: [{persona_name, prompt, ...}] ready for LLM
                thesis_context: summary data for prompt injection
        """
        # Get the base adversarial debate first
        base = self.debate(symbol)
        if "error" in base:
            return base

        thesis = self._theses.get(symbol)

        # Build data context summary for persona prompts
        context_lines = [
            f"Direction: {thesis.direction} (confidence: {thesis.confidence:.0%})",
            f"Rationale: {thesis.rationale}",
            f"Supporting evidence: {len(thesis.supporting_evidence)} items",
            f"Counter evidence: {len(thesis.counter_evidence)} items",
        ]
        if thesis.entry_price:
            context_lines.append(f"Entry price: ${thesis.entry_price:.2f}")
        if thesis.checkpoints:
            latest = thesis.checkpoints[-1]
            context_lines.append(
                f"Latest checkpoint: ${latest.get('price', '?')} "
                f"(return: {latest.get('return_pct', 0):.1%})"
            )

        # Add debate findings
        context_lines.append(f"\nBull case: {base['bull_case']['core_argument']}")
        context_lines.append(f"Bear case: {base['bear_case']['core_argument']}")
        context_lines.append(f"Verdict: {base['verdict']}")

        # Add RAG context if available
        rag_context = ""
        if hasattr(self, '_rag') and self._rag:
            try:
                rag_context = self._rag.query_for_context(
                    f"{symbol} earnings revenue outlook",
                    top_k=3, symbol=symbol,
                )
                if rag_context:
                    context_lines.append(f"\n--- Document Context ---\n{rag_context}")
            except Exception:
                pass

        data_context = "\n".join(context_lines)

        # Generate persona prompts
        try:
            from agent.finance.investment_personas import multi_persona_analysis
            persona_prompts = multi_persona_analysis(symbol, data_context)
        except ImportError:
            persona_prompts = []

        return {
            "symbol": symbol,
            "base_debate": base,
            "persona_prompts": persona_prompts,
            "thesis_context": data_context,
            "personas_available": [p["persona_name"] for p in persona_prompts],
        }

    # ── Debate helper methods ────────────────────────────────────────

    def _build_bull_argument(self, symbol: str, thesis: Thesis, evidence: list) -> str:
        """Build the core bullish argument from evidence."""
        if not evidence:
            return f"Limited bullish evidence available for {symbol}."
        positive_count = sum(1 for e in evidence if "Neutral" not in str(e) and "Disputed" not in str(e) and "CONFLICT" not in str(e))
        return (
            f"{symbol} has {positive_count} supporting data point(s). "
            f"Current thesis: {thesis.rationale or thesis.direction} "
            f"at {thesis.confidence:.0%} confidence."
        )

    def _build_bear_argument(self, symbol: str, thesis: Thesis, evidence: list) -> str:
        """Build the core bearish argument from evidence."""
        if not evidence:
            return f"Limited bearish evidence available for {symbol}."
        negative_count = sum(1 for e in evidence if "Neutral" not in str(e) and "Disputed" not in str(e))
        conflict_count = sum(1 for e in evidence if "CONFLICT" in str(e))
        parts = [f"{symbol} faces {negative_count} challenge(s)"]
        if conflict_count:
            parts.append(f"with {conflict_count} source conflict(s) adding uncertainty")
        if thesis.reversal_flagged:
            parts.append("— REVERSAL already flagged")
        return ". ".join(parts) + "."

    def _build_assumptions(self, side: str, thesis: Thesis, evidence: list) -> list:
        """Identify the key assumptions the given side is making."""
        assumptions = []
        if side == "bullish":
            assumptions.append("Current growth trajectory will continue")
            assumptions.append("No major macro shock disrupts the sector")
            if thesis.confidence > 0.7:
                assumptions.append(f"High confidence ({thesis.confidence:.0%}) is justified by fundamentals")
        else:
            assumptions.append("Negative trends are structural, not temporary")
            assumptions.append("Market has not yet fully priced in the downside")
            if thesis.reversal_flagged:
                assumptions.append("Counter-evidence accumulation signals genuine deterioration")
        return assumptions

    def _risk_if_wrong(self, side: str, thesis: Thesis, opposing_evidence: list) -> str:
        """Articulate what happens if this side's thesis is wrong."""
        opp_count = len(opposing_evidence)
        if side == "bullish":
            return (
                f"If bullish thesis is wrong, {opp_count} piece(s) of counter-evidence "
                f"suggest downside risk. Watch for: thesis reversal, confidence decay below 40%, "
                f"or 3+ conflicting source claims."
            )
        else:
            return (
                f"If bearish thesis is wrong, {opp_count} piece(s) of bull evidence "
                f"suggest missed upside. Watch for: earnings beat, insider buying, "
                f"or sentiment shift from negative to neutral."
            )
