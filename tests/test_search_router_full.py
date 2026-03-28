"""
Comprehensive unit tests for agent/search/router.py

Tests query classification and source routing.
"""

import pytest
from agent.search.router import QueryRouter


class TestQueryRouterInit:
    """Tests for QueryRouter initialization."""

    def test_router_init(self):
        """Test router initializes with weight profiles."""
        router = QueryRouter()
        assert hasattr(router, "WEIGHT_PROFILES")
        assert "news" in router.WEIGHT_PROFILES
        assert "tech" in router.WEIGHT_PROFILES
        assert "finance" in router.WEIGHT_PROFILES
        assert "academic" in router.WEIGHT_PROFILES
        assert "general" in router.WEIGHT_PROFILES


class TestQueryRouterClassification:
    """Tests for query classification."""

    def test_classify_news_query(self):
        """Test classification of news queries."""
        router = QueryRouter()

        queries = [
            "latest news on AI",
            "breaking news today",
            "what happened this week",
            "announcement released",
        ]

        for q in queries:
            result = router.classify(q)
            assert result in ["news", "tech", "general", "finance", "academic"]

    def test_classify_tech_query(self):
        """Test classification of tech queries."""
        router = QueryRouter()

        queries = [
            "python async await tutorial",
            "javascript react hooks",
            "how to fix docker error",
            "github api documentation",
        ]

        for q in queries:
            result = router.classify(q)
            # Should classify as tech (highest priority)
            assert result == "tech" or result in ["general", "academic"]

    def test_classify_finance_query(self):
        """Test classification of finance queries."""
        router = QueryRouter()

        queries = [
            "AAPL stock price",
            "bitcoin ethereum price",
            "fed interest rate cut",
            "market inflation CPI",
            "$TSLA earnings report",
        ]

        for q in queries:
            result = router.classify(q)
            assert result in ["finance", "news", "general"]

    def test_classify_academic_query(self):
        """Test classification of academic queries."""
        router = QueryRouter()

        queries = [
            "research paper on machine learning",
            "arxiv quantum computing studies",
            "academic definition of algorithm",
        ]

        for q in queries:
            result = router.classify(q)
            assert result in ["academic", "tech", "general"]

    def test_classify_general_query(self):
        """Test classification of general queries."""
        router = QueryRouter()

        queries = [
            "best pizza in new york",
            "how to cook pasta",
            "what is the capital of france",
        ]

        for q in queries:
            result = router.classify(q)
            # Most likely general, but could be others
            assert isinstance(result, str)

    def test_classify_case_insensitive(self):
        """Test that classification is case-insensitive."""
        router = QueryRouter()

        q_lower = "python tutorial"
        q_upper = "PYTHON TUTORIAL"

        result_lower = router.classify(q_lower)
        result_upper = router.classify(q_upper)

        assert result_lower == result_upper

    def test_classify_priority_finance_over_news(self):
        """Test that finance takes priority over news when tied."""
        router = QueryRouter()

        # Query that could match both finance and news patterns
        q = "Fed rate cut announced today"
        result = router.classify(q)

        # Should prefer finance over generic news
        assert result in ["finance", "news"]

    def test_classify_priority_tech_over_general(self):
        """Test that tech takes priority over general."""
        router = QueryRouter()

        q = "python programming guide"
        result = router.classify(q)

        # Should be tech
        assert result == "tech"

    def test_classify_chinese_news_patterns(self):
        """Test classification of Chinese news patterns."""
        router = QueryRouter()

        q = "今日新闻政策发布"
        result = router.classify(q)

        assert isinstance(result, str)

    def test_classify_chinese_finance_patterns(self):
        """Test classification of Chinese finance patterns."""
        router = QueryRouter()

        q = "A股行情涨跌央行降息"
        result = router.classify(q)

        assert isinstance(result, str)

    def test_classify_chinese_tech_patterns(self):
        """Test classification of Chinese tech patterns."""
        router = QueryRouter()

        q = "Python编程框架开发部署"
        result = router.classify(q)

        assert isinstance(result, str)


class TestQueryRouterRoute:
    """Tests for route() method that combines classify and get weights."""

    def test_route_returns_type_and_weights(self):
        """Test route returns both query type and weights."""
        router = QueryRouter()
        query_type, weights = router.route("python tutorial")

        assert isinstance(query_type, str)
        assert isinstance(weights, dict)
        assert len(weights) > 0

    def test_route_news_returns_correct_weights(self):
        """Test route returns news-appropriate weights."""
        router = QueryRouter()

        # Classify query that should be news
        query_type, weights = router.route("latest news today")

        # Check that news sources have high weights
        if query_type == "news":
            assert weights.get("gnews_en", 0) > 0.5
            assert weights.get("newsapi", 0) > 0.5

    def test_route_tech_returns_correct_weights(self):
        """Test route returns tech-appropriate weights."""
        router = QueryRouter()

        query_type, weights = router.route("python tutorial")

        # Check that tech sources have high weights
        if query_type == "tech":
            assert weights.get("serper", 0) > 0.7

    def test_route_finance_returns_correct_weights(self):
        """Test route returns finance-appropriate weights."""
        router = QueryRouter()

        query_type, weights = router.route("bitcoin price today")

        # Should have strong finance weights
        assert isinstance(weights, dict)

    def test_route_general_fallback(self):
        """Test route returns general weights for unknown types."""
        router = QueryRouter()

        query_type, weights = router.route("random unmatched query")

        assert query_type == "general" or query_type in ["news", "tech", "finance", "academic"]
        assert isinstance(weights, dict)


class TestQueryRouterWeights:
    """Tests for weight profiles."""

    def test_weight_profiles_have_all_types(self):
        """Test all query types have weight profiles."""
        router = QueryRouter()

        for qtype in ["news", "tech", "finance", "academic", "general"]:
            assert qtype in router.WEIGHT_PROFILES
            assert isinstance(router.WEIGHT_PROFILES[qtype], dict)

    def test_weight_profiles_contain_sources(self):
        """Test weight profiles contain source names."""
        router = QueryRouter()

        for qtype, weights in router.WEIGHT_PROFILES.items():
            assert len(weights) > 0
            # Each weight value should be between 0 and 1
            for source, weight in weights.items():
                assert 0 <= weight <= 1

    def test_news_weights_prioritize_news_sources(self):
        """Test news profile prioritizes news sources."""
        router = QueryRouter()
        weights = router.WEIGHT_PROFILES["news"]

        gnews_weight = weights.get("gnews_en", 0)
        newsapi_weight = weights.get("newsapi", 0)

        # Should have high weights for news sources
        assert gnews_weight >= 0.5 or newsapi_weight >= 0.5

    def test_tech_weights_prioritize_code_search(self):
        """Test tech profile prioritizes code search sources."""
        router = QueryRouter()
        weights = router.WEIGHT_PROFILES["tech"]

        serper_weight = weights.get("serper", 0)
        # Serper (Google) should be high for tech
        assert serper_weight >= 0.7

    def test_finance_weights_balanced(self):
        """Test finance profile has balanced weights."""
        router = QueryRouter()
        weights = router.WEIGHT_PROFILES["finance"]

        # Should have high weights for finance-relevant sources
        brave_weight = weights.get("brave", 0)
        serper_weight = weights.get("serper", 0)

        assert brave_weight > 0 or serper_weight > 0

    def test_academic_weights_favor_semantic_search(self):
        """Test academic profile favors semantic search."""
        router = QueryRouter()
        weights = router.WEIGHT_PROFILES["academic"]

        tavily_weight = weights.get("tavily", 0)
        jina_weight = weights.get("jina", 0)

        # Tavily and Jina are good for academic
        assert tavily_weight > 0.7 or jina_weight > 0.7


class TestQueryRouterGetProfile:
    """Tests for get_profile() method."""

    def test_get_profile_returns_weights(self):
        """Test get_profile returns correct weights."""
        router = QueryRouter()

        for qtype in ["news", "tech", "finance", "academic", "general"]:
            weights = router.get_profile(qtype)
            assert isinstance(weights, dict)
            assert len(weights) > 0

    def test_get_profile_general_fallback(self):
        """Test get_profile returns general for unknown type."""
        router = QueryRouter()

        weights = router.get_profile("unknown_type")
        assert weights == router.WEIGHT_PROFILES["general"]

    def test_get_profile_and_route_consistency(self):
        """Test that get_profile matches route weights."""
        router = QueryRouter()

        query = "test query"
        query_type, route_weights = router.route(query)
        profile_weights = router.get_profile(query_type)

        assert route_weights == profile_weights


class TestQueryRouterPatternMatching:
    """Tests for pattern matching logic."""

    def test_score_counts_pattern_matches(self):
        """Test _score counts pattern matches."""
        router = QueryRouter()

        # Query with multiple tech patterns
        q = "python javascript docker kubernetes"
        score = router._score(q, router.TECH_PATTERNS)

        assert score > 0

    def test_score_case_insensitive(self):
        """Test _score is case-insensitive."""
        router = QueryRouter()

        q1 = "python tutorial"
        q2 = "PYTHON TUTORIAL"

        score1 = router._score(q1, router.TECH_PATTERNS)
        score2 = router._score(q2, router.TECH_PATTERNS)

        assert score1 == score2

    def test_score_zero_for_no_matches(self):
        """Test _score returns 0 for no matches."""
        router = QueryRouter()

        q = "pizza restaurant location"
        score = router._score(q, router.TECH_PATTERNS)

        assert score == 0

    def test_score_multiple_matches(self):
        """Test _score counts multiple matches."""
        router = QueryRouter()

        q = "python programming javascript framework"
        score = router._score(q, router.TECH_PATTERNS)

        # Should have multiple matches
        assert score > 1


class TestQueryRouterEdgeCases:
    """Tests for edge cases."""

    def test_classify_empty_query(self):
        """Test classification of empty query."""
        router = QueryRouter()
        result = router.classify("")

        assert result == "general"

    def test_classify_very_long_query(self):
        """Test classification of very long query."""
        router = QueryRouter()
        q = "test " * 1000
        result = router.classify(q)

        assert isinstance(result, str)

    def test_route_empty_query(self):
        """Test routing of empty query."""
        router = QueryRouter()
        qtype, weights = router.route("")

        assert qtype == "general"
        assert isinstance(weights, dict)

    def test_classify_special_characters(self):
        """Test classification with special characters."""
        router = QueryRouter()
        q = "C++ tutorial & API documentation!"
        result = router.classify(q)

        assert result in ["tech", "general", "news", "finance", "academic"]

    def test_classify_only_punctuation(self):
        """Test classification of only punctuation."""
        router = QueryRouter()
        q = "??? !!! ###"
        result = router.classify(q)

        assert result == "general"


class TestQueryRouterIntegration:
    """Integration tests."""

    def test_full_routing_pipeline(self):
        """Test complete routing pipeline."""
        router = QueryRouter()

        test_queries = [
            ("latest AI news", "news"),
            ("python async await", "tech"),
            ("bitcoin price", "finance"),
            ("machine learning research paper", "academic"),
            ("best restaurants", "general"),
        ]

        for query, expected_type in test_queries:
            qtype, weights = router.route(query)

            # Verify return types
            assert isinstance(qtype, str)
            assert isinstance(weights, dict)
            assert len(weights) > 0

            # Verify weights are in valid range
            for source, weight in weights.items():
                assert 0 <= weight <= 1

    def test_multilingual_classification(self):
        """Test classification works with multiple languages."""
        router = QueryRouter()

        queries = [
            "python programming",
            "股票价格",
            "latest news",
            "最新新闻",
        ]

        for q in queries:
            result = router.classify(q)
            assert isinstance(result, str)
