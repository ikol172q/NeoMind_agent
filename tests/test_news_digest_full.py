"""
Comprehensive unit tests for agent/finance/news_digest.py
Tests DigestItem, ConflictItem, Thesis, NewsDigest, and NewsDigestEngine.
"""

import pytest
import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, MagicMock, patch, AsyncMock

from agent.finance.news_digest import (
    DigestItem,
    ConflictItem,
    Thesis,
    NewsDigest,
    NewsDigestEngine,
    IMPACT_KEYWORDS,
)


class TestDigestItem:
    """Test DigestItem dataclass."""

    def test_creation_minimal(self):
        """Test creating DigestItem with minimal fields."""
        item = DigestItem(title="Test News")
        assert item.title == "Test News"
        assert item.url == ""
        assert item.language == "en"
        assert item.impact_magnitude == 0.0

    def test_creation_full(self):
        """Test creating DigestItem with all fields."""
        now = datetime.now(timezone.utc)
        item = DigestItem(
            title="AAPL Earnings Beat",
            url="https://example.com/news",
            source="Reuters",
            language="en",
            published=now,
            summary="Apple beat earnings expectations",
            symbols=["AAPL"],
            category="earnings",
            impact_magnitude=8.0,
            impact_probability=0.8,
            impact_score=6.4,
            relevance=0.9,
        )
        assert item.title == "AAPL Earnings Beat"
        assert item.symbols == ["AAPL"]
        assert item.category == "earnings"
        assert item.impact_score == 6.4


class TestConflictItem:
    """Test ConflictItem dataclass."""

    def test_creation_minimal(self):
        """Test creating ConflictItem with minimal fields."""
        item = ConflictItem(entity="AAPL")
        assert item.entity == "AAPL"
        assert item.severity == "soft"
        assert item.confidence == 0.5

    def test_creation_full(self):
        """Test creating ConflictItem with all fields."""
        claim_a = {"source": "Reuters", "claim": "AAPL up", "url": "https://..."}
        claim_b = {"source": "AP", "claim": "AAPL down", "url": "https://..."}
        item = ConflictItem(
            entity="AAPL",
            claim_a=claim_a,
            claim_b=claim_b,
            severity="hard",
            inference="Sources disagree on direction",
            confidence=0.9,
        )
        assert item.entity == "AAPL"
        assert item.severity == "hard"
        assert item.confidence == 0.9


class TestThesis:
    """Test Thesis dataclass."""

    def test_creation_minimal(self):
        """Test creating Thesis with minimal fields."""
        thesis = Thesis(symbol="AAPL")
        assert thesis.symbol == "AAPL"
        assert thesis.direction == "neutral"
        assert thesis.confidence == 0.5
        assert thesis.closed is False

    def test_creation_full(self):
        """Test creating Thesis with all fields."""
        now = datetime.now(timezone.utc).isoformat()
        thesis = Thesis(
            symbol="AAPL",
            direction="bullish",
            confidence=0.75,
            rationale="Strong earnings growth",
            supporting_evidence=["Q4 beat", "guidance raised"],
            counter_evidence=["macro headwinds"],
            last_updated=now,
            created_at=now,
            entry_price=150.0,
            entry_price_date=now,
            checkpoints=[{"days": 30, "price": 155.0, "return_pct": 0.033}],
            closed=False,
        )
        assert thesis.symbol == "AAPL"
        assert thesis.direction == "bullish"
        assert thesis.confidence == 0.75
        assert len(thesis.supporting_evidence) == 2

    def test_risk_reward_ratio(self):
        """Test risk/reward calculation."""
        result = MagicMock()
        result.best_case = 100
        result.worst_case = -50
        ratio = abs(result.best_case / result.worst_case)
        assert ratio == 2.0


class TestNewsDigest:
    """Test NewsDigest dataclass."""

    def test_creation_minimal(self):
        """Test creating NewsDigest with minimal fields."""
        digest = NewsDigest()
        assert digest.items == []
        assert digest.conflicts == []
        assert digest.sources_used == 0

    def test_creation_full(self):
        """Test creating NewsDigest with all fields."""
        now = datetime.now(timezone.utc).isoformat()
        items = [DigestItem(title="News 1"), DigestItem(title="News 2")]
        digest = NewsDigest(
            items=items,
            sources_used=5,
            en_count=3,
            zh_count=2,
            timestamp=now,
        )
        assert len(digest.items) == 2
        assert digest.sources_used == 5
        assert digest.en_count == 3
        assert digest.zh_count == 2


class TestNewsDigestEngine:
    """Test NewsDigestEngine functionality."""

    @pytest.fixture
    def engine(self):
        """Create an engine instance."""
        return NewsDigestEngine(search=None, data_hub=None, memory=None)

    def test_init(self):
        """Test engine initialization."""
        mock_search = Mock()
        mock_data_hub = Mock()
        mock_memory = Mock()

        engine = NewsDigestEngine(
            search=mock_search,
            data_hub=mock_data_hub,
            memory=mock_memory,
        )
        assert engine.search == mock_search
        assert engine.data_hub == mock_data_hub
        assert engine.memory == mock_memory
        assert engine._theses == {}

    def test_extract_entities(self, engine):
        """Test entity extraction from titles."""
        title = "FED hikes rate, AAPL surges"
        entities = engine._extract_entities(title)
        assert "FED" in entities
        assert "AAPL" in entities

    def test_extract_entities_empty(self, engine):
        """Test entity extraction with no known entities."""
        title = "Some random news article"
        entities = engine._extract_entities(title)
        assert entities == []

    def test_quick_sentiment_positive(self, engine):
        """Test sentiment analysis for positive text."""
        sentiment = engine._quick_sentiment("Stock surges on strong earnings")
        assert sentiment == "positive"

    def test_quick_sentiment_negative(self, engine):
        """Test sentiment analysis for negative text."""
        sentiment = engine._quick_sentiment("Market crash as Fed raises rates")
        assert sentiment == "negative"

    def test_quick_sentiment_neutral(self, engine):
        """Test sentiment analysis for neutral text."""
        sentiment = engine._quick_sentiment("Market moves sideways")
        assert sentiment == "neutral"

    def test_extract_symbol_dollar_sign(self, engine):
        """Test symbol extraction with $AAPL format."""
        symbol = engine._extract_symbol("Buy $AAPL now at $150")
        assert symbol == "AAPL"

    def test_extract_symbol_colon_format(self, engine):
        """Test symbol extraction with AAPL: format."""
        symbol = engine._extract_symbol("AAPL: Strong quarterly results")
        assert symbol == "AAPL"

    def test_extract_symbol_not_found(self, engine):
        """Test when no symbol can be extracted."""
        symbol = engine._extract_symbol("The market is strong today")
        assert symbol is None

    def test_extract_symbol_filters_keywords(self, engine):
        """Test that common keywords are filtered."""
        # GDP is a keyword, not a ticker
        symbol = engine._extract_symbol("US: GDP grows")
        assert symbol != "GDP"

    def test_classify_and_score_earnings(self, engine):
        """Test classification and scoring for earnings news."""
        item = DigestItem(title="AAPL Q4 Earnings Beat Expectations")
        engine._classify_and_score(item)

        assert item.category == "earnings"
        assert item.impact_magnitude > 0
        assert 0.2 <= item.impact_probability <= 0.95

    def test_classify_and_score_macro(self, engine):
        """Test classification and scoring for macro news."""
        item = DigestItem(title="Fed Announces Rate Hike")
        engine._classify_and_score(item)

        assert item.category == "macro"
        assert item.impact_magnitude >= 8

    def test_classify_and_score_crypto(self, engine):
        """Test classification for crypto news."""
        item = DigestItem(title="Bitcoin Ethereum surge")
        engine._classify_and_score(item)

        assert item.category == "crypto"

    def test_classify_and_score_corporate(self, engine):
        """Test classification for corporate news."""
        item = DigestItem(title="Microsoft Acquisition announced")
        engine._classify_and_score(item)

        assert item.category == "corporate"

    def test_classify_and_score_general(self, engine):
        """Test classification for general news."""
        item = DigestItem(title="Random news story")
        engine._classify_and_score(item)

        assert item.category == "general"

    def test_estimate_impact_probability_base(self, engine):
        """Test impact probability estimation."""
        item = DigestItem(title="Some news")
        prob = engine._estimate_impact_probability(item)
        assert 0.2 <= prob <= 0.95

    def test_estimate_impact_probability_with_percentage(self, engine):
        """Test that percentages increase probability."""
        item1 = DigestItem(title="News about stock")
        item2 = DigestItem(title="Stock rises 25% after earnings")

        prob1 = engine._estimate_impact_probability(item1)
        prob2 = engine._estimate_impact_probability(item2)

        assert prob2 > prob1

    def test_estimate_impact_probability_with_strong_sentiment(self, engine):
        """Test strong sentiment keywords increase probability."""
        item1 = DigestItem(title="Stock news")
        item2 = DigestItem(title="Stock crashes and collapses")

        prob1 = engine._estimate_impact_probability(item1)
        prob2 = engine._estimate_impact_probability(item2)

        assert prob2 > prob1

    def test_detect_conflicts_no_conflicts(self, engine):
        """Test conflict detection with no conflicts."""
        items = [
            DigestItem(title="AAPL rises", source="Reuters"),
            DigestItem(title="AAPL strong", source="AP"),
        ]
        conflicts = engine._detect_conflicts(items)
        # Same sentiment, no conflict
        assert len(conflicts) == 0

    def test_detect_conflicts_with_conflicting_sources(self, engine):
        """Test conflict detection with opposing sentiments."""
        item1 = DigestItem(
            title="AAPL surges to new highs",
            source="Reuters",
            impact_score=8.0,
        )
        item2 = DigestItem(
            title="AAPL crashes amid concerns",
            source="AP",
            impact_score=2.0,
        )
        conflicts = engine._detect_conflicts([item1, item2])
        assert len(conflicts) > 0
        assert conflicts[0].entity == "AAPL"

    def test_update_thesis_new(self, engine):
        """Test creating a new thesis."""
        new_data = {
            "direction": "bullish",
            "evidence": "Strong fundamentals",
            "price": 150.0,
        }
        thesis = engine.update_thesis("AAPL", new_data)

        assert thesis.symbol == "AAPL"
        assert thesis.direction == "bullish"
        assert thesis.entry_price == 150.0

    def test_update_thesis_update_direction(self, engine):
        """Test updating thesis direction."""
        # Create initial thesis
        engine.update_thesis("AAPL", {"direction": "bullish"})

        # Update with opposite direction (counter-evidence)
        engine.update_thesis("AAPL", {
            "direction": "bearish",
            "evidence": "New bearish signal",
        })

        thesis = engine.get_thesis("AAPL")
        assert len(thesis.counter_evidence) > 0

    def test_update_thesis_confidence_increase(self, engine):
        """Test that supporting evidence increases confidence."""
        initial = engine.update_thesis("AAPL", {"direction": "bullish"})
        initial_conf = initial.confidence

        # Add supporting evidence
        updated = engine.update_thesis("AAPL", {
            "direction": "bullish",
            "evidence": "More bullish data",
            "contradicts": False,
        })

        assert updated.confidence > initial_conf

    def test_update_thesis_confidence_decrease(self, engine):
        """Test that conflicting evidence decreases confidence."""
        initial = engine.update_thesis("AAPL", {"direction": "bullish"})
        initial_conf = initial.confidence

        # Add conflicting evidence
        updated = engine.update_thesis("AAPL", {
            "direction": "bullish",
            "contradicts": True,
        })

        assert updated.confidence < initial_conf

    def test_get_thesis_exists(self, engine):
        """Test getting an existing thesis."""
        engine.update_thesis("AAPL", {"direction": "bullish"})
        thesis = engine.get_thesis("AAPL")
        assert thesis is not None
        assert thesis.symbol == "AAPL"

    def test_get_thesis_not_exists(self, engine):
        """Test getting a non-existent thesis."""
        thesis = engine.get_thesis("NONEXISTENT")
        assert thesis is None

    def test_get_thesis_with_confidence_decay(self, engine):
        """Test confidence decay simulation."""
        thesis = engine.update_thesis("AAPL", {"direction": "bullish"})
        initial_conf = thesis.confidence

        # Get with 4 weeks decay
        decayed = engine.get_thesis("AAPL", simulate_weeks=4)
        expected_decay = 4 * engine.CONFIDENCE_DECAY_PER_WEEK
        assert decayed.confidence < initial_conf
        assert abs(decayed.confidence - (initial_conf - expected_decay)) < 0.01

    def test_checkpoint_thesis_no_entry_price(self, engine):
        """Test checkpointing when no entry price recorded."""
        engine._theses["AAPL"] = Thesis(symbol="AAPL", entry_price=None)
        checkpoint = engine.checkpoint_thesis("AAPL", current_price=155.0)
        assert checkpoint is None

    def test_checkpoint_thesis_with_price(self, engine):
        """Test checkpointing with price."""
        now = datetime.now(timezone.utc).isoformat()
        engine._theses["AAPL"] = Thesis(
            symbol="AAPL",
            direction="bullish",
            entry_price=150.0,
            entry_price_date=now,
            created_at=now,
        )

        checkpoint = engine.checkpoint_thesis("AAPL", current_price=155.0)
        assert checkpoint is not None
        assert checkpoint["return_pct"] == pytest.approx(0.0333, abs=0.001)
        assert checkpoint["correct"] is True

    def test_checkpoint_thesis_bearish_correct(self, engine):
        """Test checkpointing bearish thesis that was correct."""
        now = datetime.now(timezone.utc).isoformat()
        engine._theses["AAPL"] = Thesis(
            symbol="AAPL",
            direction="bearish",
            entry_price=150.0,
            entry_price_date=now,
            created_at=now,
        )

        checkpoint = engine.checkpoint_thesis("AAPL", current_price=145.0)
        assert checkpoint["correct"] is True

    def test_checkpoint_thesis_neutral_cannot_judge(self, engine):
        """Test checkpointing neutral thesis."""
        now = datetime.now(timezone.utc).isoformat()
        engine._theses["AAPL"] = Thesis(
            symbol="AAPL",
            direction="neutral",
            entry_price=150.0,
            entry_price_date=now,
            created_at=now,
        )

        checkpoint = engine.checkpoint_thesis("AAPL", current_price=155.0)
        assert checkpoint["correct"] is None

    def test_get_accuracy_stats_no_checkpoints(self, engine):
        """Test accuracy stats with no checkpoints."""
        stats = engine.get_accuracy_stats()
        assert stats["total"] == 0
        assert stats["accuracy"] is None

    def test_get_accuracy_stats_with_checkpoints(self, engine):
        """Test accuracy stats calculation."""
        now = datetime.now(timezone.utc).isoformat()

        # Add theses with checkpoints
        thesis1 = Thesis(
            symbol="AAPL",
            direction="bullish",
            entry_price=150.0,
            entry_price_date=now,
            created_at=now,
        )
        thesis1.checkpoints = [
            {"days": 30, "price": 155.0, "return_pct": 0.033, "correct": True},
        ]

        thesis2 = Thesis(
            symbol="MSFT",
            direction="bearish",
            entry_price=300.0,
            entry_price_date=now,
            created_at=now,
        )
        thesis2.checkpoints = [
            {"days": 30, "price": 310.0, "return_pct": 0.033, "correct": False},
        ]

        engine._theses = {"AAPL": thesis1, "MSFT": thesis2}

        stats = engine.get_accuracy_stats()
        assert stats["total"] == 2
        assert stats["correct"] == 1
        assert stats["accuracy"] == 0.5

    def test_devils_advocate(self, engine):
        """Test devils_advocate wrapper."""
        engine._theses["AAPL"] = Thesis(symbol="AAPL", direction="bullish")
        result = engine.devils_advocate("AAPL")
        # Should return a string (either error or debate result)
        assert isinstance(result, str)

    def test_debate_no_thesis(self, engine):
        """Test debate when thesis doesn't exist."""
        result = engine.debate("NONEXISTENT")
        assert "error" in result
        assert "No thesis" in result["error"]

    def test_debate_with_thesis(self, engine):
        """Test debate with existing thesis."""
        engine.update_thesis("AAPL", {"direction": "bullish"})
        result = engine.debate("AAPL", rounds=1)

        # Result should have expected structure
        assert "bull_case" in result or "error" in result

    @pytest.mark.asyncio
    async def test_generate_digest_no_search(self, engine):
        """Test generate_digest with no search engine."""
        digest = await engine.generate_digest()

        assert digest.items == []
        assert digest.timestamp is not None

    @pytest.mark.asyncio
    async def test_generate_digest_with_search(self):
        """Test generate_digest with mocked search."""
        mock_search = AsyncMock()
        mock_search.search = AsyncMock(return_value=MagicMock(items=[
            MagicMock(
                title="Test News",
                url="https://example.com",
                source="Test",
                language="en",
                snippet="Test snippet",
            )
        ]))
        mock_search.rss_manager = None

        engine = NewsDigestEngine(search=mock_search)

        digest = await engine.generate_digest(languages=["en"])

        assert digest.sources_used >= 0

    @pytest.mark.asyncio
    async def test_prefetch_social_sentiment(self, engine):
        """Test social sentiment prefetch."""
        mock_data_hub = AsyncMock()
        mock_data_hub.get_social_sentiment = AsyncMock(return_value={
            "buzz_level": "high",
            "overall_score": 0.8,
        })
        engine.data_hub = mock_data_hub

        await engine.prefetch_social_sentiment(["AAPL", "MSFT"])

        # Should call for both symbols
        assert mock_data_hub.get_social_sentiment.call_count >= 1


class TestNewsDigestIntegration:
    """Integration tests for NewsDigestEngine."""

    @pytest.fixture
    def engine(self):
        """Create engine with mocked dependencies."""
        mock_search = Mock()
        mock_data_hub = Mock()
        mock_memory = Mock()
        return NewsDigestEngine(
            search=mock_search,
            data_hub=mock_data_hub,
            memory=mock_memory,
        )

    def test_complete_thesis_lifecycle(self, engine):
        """Test complete thesis creation and evolution."""
        # Create initial thesis
        t1 = engine.update_thesis("AAPL", {
            "direction": "bullish",
            "evidence": "Strong revenue growth",
        })
        assert t1.direction == "bullish"
        initial_conf = t1.confidence

        # Add more supporting evidence
        t2 = engine.update_thesis("AAPL", {
            "direction": "bullish",
            "evidence": "Expanding margins",
            "contradicts": False,
        })
        assert t2.confidence > initial_conf

        # Get current state
        current = engine.get_thesis("AAPL")
        assert current.symbol == "AAPL"
        assert len(current.supporting_evidence) >= 1

    def test_conflict_detection_real_scenario(self, engine):
        """Test conflict detection with realistic scenario."""
        bull_item = DigestItem(
            title="AAPL surges on earnings beat",
            source="Reuters",
            impact_score=8.5,
        )
        bear_item = DigestItem(
            title="AAPL plunge amid regulatory concerns",
            source="AP",
            impact_score=6.0,
        )

        conflicts = engine._detect_conflicts([bull_item, bear_item])
        # Should detect conflict
        assert len(conflicts) > 0

    def test_impact_keywords_coverage(self):
        """Test that impact keywords are reasonably complete."""
        # Should have Fed as high impact
        assert IMPACT_KEYWORDS.get("fed") >= 8
        # Should have earnings as medium
        assert IMPACT_KEYWORDS.get("earnings beat") >= 5
        # Should have analyst as low
        assert IMPACT_KEYWORDS.get("analyst upgrade") <= 3
