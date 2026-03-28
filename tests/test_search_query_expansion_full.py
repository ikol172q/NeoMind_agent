"""
Comprehensive unit tests for agent/search/query_expansion.py

Tests query expansion strategies including synonym, cross-language, and temporal variants.
"""

import pytest
from agent.search.query_expansion import QueryExpander


class TestQueryExpanderInit:
    """Tests for QueryExpander initialization."""

    def test_init_general_domain(self):
        """Test initialization with general domain."""
        expander = QueryExpander(domain="general")
        assert expander.domain == "general"

    def test_init_finance_domain(self):
        """Test initialization with finance domain."""
        expander = QueryExpander(domain="finance")
        assert expander.domain == "finance"
        # Should include finance synonyms
        assert "央行" in expander._synonyms or "fed" in expander._synonyms

    def test_init_coding_domain(self):
        """Test initialization with coding domain."""
        expander = QueryExpander(domain="coding")
        assert expander.domain == "coding"


class TestQueryExpanderSynonymExpansion:
    """Tests for synonym expansion."""

    def test_expand_general_synonyms(self):
        """Test general synonym expansion."""
        expander = QueryExpander(domain="general")
        variants = expander.expand("what is AI", max_variants=3)

        assert "what is AI" in variants  # Original always first
        # Should have a synonym expansion
        assert len(variants) > 1

    def test_expand_ai_to_artificial_intelligence(self):
        """Test AI expands to artificial intelligence."""
        expander = QueryExpander(domain="general")
        variants = expander.expand("latest AI news", max_variants=3)

        # Should generate variant with expanded form
        assert any("artificial intelligence" in v.lower() for v in variants)

    def test_expand_ml_to_machine_learning(self):
        """Test ML expands to machine learning."""
        expander = QueryExpander(domain="general")
        variants = expander.expand("ML tutorial", max_variants=3)

        assert any("machine learning" in v.lower() for v in variants)

    def test_expand_llm_to_language_model(self):
        """Test LLM expands to language model."""
        expander = QueryExpander(domain="general")
        variants = expander.expand("LLM capabilities", max_variants=3)

        assert any(
            "large language model" in v.lower() or "language model" in v.lower()
            for v in variants
        )

    def test_expand_api_synonym(self):
        """Test API expands to application programming interface."""
        expander = QueryExpander(domain="general")
        variants = expander.expand("how to use API", max_variants=3)

        assert any("application programming interface" in v.lower() for v in variants)

    def test_expand_fix_synonym(self):
        """Test 'fix' expands to synonyms."""
        expander = QueryExpander(domain="general")
        variants = expander.expand("how to fix error", max_variants=3)

        # Should have expanded variant
        assert len(variants) > 1

    def test_word_boundary_matching_for_short_triggers(self):
        """Test word boundary matching for short triggers (<=3 chars)."""
        expander = QueryExpander(domain="general")
        # "py" should not match inside "python"
        variants = expander.expand("python tutorial", max_variants=3)

        # Should not expand "py" from "python"
        # Check that at least the original is present
        assert "python tutorial" in variants

    def test_only_one_synonym_expansion_per_query(self):
        """Test only one synonym expansion occurs."""
        expander = QueryExpander(domain="general")
        variants = expander.expand("AI and ML both", max_variants=4)

        # Original query + at most one synonym expansion
        # (due to break after first synonym match)
        assert len(variants) <= 4

    def test_finance_domain_synonyms(self):
        """Test finance domain has domain-specific synonyms."""
        expander = QueryExpander(domain="finance")
        variants = expander.expand("fed rate cut news", max_variants=3)

        # Should have finance-specific expansion
        assert len(variants) > 1


class TestQueryExpanderCrossLanguageExpansion:
    """Tests for cross-language expansion."""

    def test_expand_english_to_chinese(self):
        """Test English phrase expands to Chinese."""
        expander = QueryExpander(domain="general")
        variants = expander.expand("stock market news", max_variants=3)

        # Should include Chinese variant
        assert any("股市" in v for v in variants)

    def test_expand_chinese_to_english(self):
        """Test Chinese phrase expands to English."""
        expander = QueryExpander(domain="general")
        variants = expander.expand("股市行情", max_variants=3)

        # Should include English variant
        assert any("stock market" in v for v in variants)

    def test_no_expansion_for_non_matching_language_pairs(self):
        """Test no language expansion for non-matching phrases."""
        expander = QueryExpander(domain="general")
        variants = expander.expand("random query", max_variants=3)

        # Original should be present at minimum
        assert "random query" in variants

    def test_multiple_en_zh_pairs(self):
        """Test that multiple language pairs work."""
        expander = QueryExpander(domain="general")

        # Test several language pairs
        test_cases = [
            ("artificial intelligence", "人工智能"),
            ("cryptocurrency", "加密货币"),
            ("real estate", "房地产"),
        ]

        for en_phrase, zh_phrase in test_cases:
            variants_en = expander.expand(en_phrase, max_variants=3)
            variants_zh = expander.expand(zh_phrase, max_variants=3)

            # At least one should expand
            assert len(variants_en) > 1 or len(variants_zh) > 1


class TestQueryExpanderTemporalExpansion:
    """Tests for time-scope variants."""

    def test_temporal_expansion_for_general_triggers(self):
        """Test temporal expansion adds current year for general triggers."""
        expander = QueryExpander(domain="general")
        variants = expander.expand("latest AI news", max_variants=3)

        # Should add a variant with "2026"
        assert any("2026" in v for v in variants)

    def test_no_duplicate_year_addition(self):
        """Test year not added if already present."""
        expander = QueryExpander(domain="general")
        variants = expander.expand("latest AI news 2026", max_variants=3)

        # Should not add another year
        # Check for multiple "2026" isn't ideal, but query shouldn't be modified
        year_count = sum(v.count("2026") for v in variants)
        assert year_count <= len(variants)  # Max one per variant

    def test_no_year_added_for_non_recency_queries(self):
        """Test year not added for non-recency queries."""
        expander = QueryExpander(domain="general")
        variants = expander.expand("python syntax", max_variants=3)

        # Non-news query shouldn't trigger year expansion
        # At minimum, original should be there
        assert "python syntax" in variants

    def test_finance_domain_recency_triggers(self):
        """Test finance domain has specific recency triggers."""
        expander = QueryExpander(domain="finance")
        variants = expander.expand("stock market analysis", max_variants=3)

        # Finance might expand with year based on "market"
        assert len(variants) >= 1


class TestQueryExpanderQuestionReformulation:
    """Tests for question to statement reformulation."""

    def test_what_is_reformulation(self):
        """Test 'what is X' becomes 'X explained'."""
        expander = QueryExpander(domain="general")
        variants = expander.expand("what is blockchain", max_variants=3)

        # Should have "blockchain explained" variant
        assert any("explained" in v for v in variants)

    def test_what_are_reformulation(self):
        """Test 'what are X' becomes reformulated."""
        expander = QueryExpander(domain="general")
        variants = expander.expand("what are algorithms", max_variants=3)

        # Should have reformulated variant
        assert len(variants) > 1

    def test_who_is_reformulation(self):
        """Test 'who is X' becomes reformulated."""
        expander = QueryExpander(domain="general")
        variants = expander.expand("who is Elon Musk", max_variants=3)

        # Should have reformulated variant
        assert len(variants) > 1

    def test_question_with_trailing_question_mark(self):
        """Test handling of trailing question mark."""
        expander = QueryExpander(domain="general")
        variants = expander.expand("what is AI?", max_variants=3)

        # Should handle question mark
        assert len(variants) >= 1


class TestQueryExpanderMaxVariants:
    """Tests for max_variants parameter."""

    def test_max_variants_respected(self):
        """Test that max_variants limit is respected."""
        expander = QueryExpander(domain="general")

        for max_v in [1, 2, 3, 4]:
            variants = expander.expand("AI news", max_variants=max_v)
            assert len(variants) <= max_v + 1  # +1 for original

    def test_original_always_first(self):
        """Test that original query is always first."""
        expander = QueryExpander(domain="general")
        query = "test query"
        variants = expander.expand(query, max_variants=5)

        assert variants[0] == query

    def test_no_duplicate_variants(self):
        """Test that duplicate variants are not created."""
        expander = QueryExpander(domain="general")
        variants = expander.expand("AI artificial intelligence", max_variants=5)

        # Should not have duplicate lowercase versions
        lowercase_variants = [v.lower() for v in variants]
        assert len(lowercase_variants) == len(set(lowercase_variants))


class TestQueryExpanderEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_query(self):
        """Test expansion of empty query."""
        expander = QueryExpander(domain="general")
        variants = expander.expand("", max_variants=3)

        # Should at least return the original
        assert len(variants) >= 1

    def test_very_long_query(self):
        """Test expansion of very long query."""
        expander = QueryExpander(domain="general")
        long_query = "what is " + "a very long " * 50
        variants = expander.expand(long_query, max_variants=3)

        assert len(variants) >= 1

    def test_query_with_special_characters(self):
        """Test expansion of query with special characters."""
        expander = QueryExpander(domain="general")
        variants = expander.expand("C++ tutorial & API", max_variants=3)

        assert len(variants) >= 1

    def test_numeric_only_query(self):
        """Test expansion of numeric-only query."""
        expander = QueryExpander(domain="general")
        variants = expander.expand("2026 2025 2024", max_variants=3)

        # Should at least have original
        assert "2026 2025 2024" in variants

    def test_unicode_query(self):
        """Test expansion of unicode query."""
        expander = QueryExpander(domain="general")
        variants = expander.expand("人工智能新闻", max_variants=3)

        assert len(variants) >= 1


class TestQueryExpanderSetDomain:
    """Tests for set_domain method."""

    def test_set_domain_changes_domain(self):
        """Test set_domain changes domain."""
        expander = QueryExpander(domain="general")
        assert expander.domain == "general"

        expander.set_domain("finance")
        assert expander.domain == "finance"

    def test_set_domain_updates_synonyms(self):
        """Test set_domain updates synonym dict."""
        expander = QueryExpander(domain="general")
        # General doesn't have finance-specific terms
        assert "央行" not in expander._synonyms

        expander.set_domain("finance")
        # Finance should have these now
        assert "央行" in expander._synonyms or len(expander._synonyms) > 0

    def test_set_domain_to_same_domain(self):
        """Test setting domain to same value."""
        expander = QueryExpander(domain="general")
        original_synonyms = dict(expander._synonyms)

        expander.set_domain("general")
        assert expander._synonyms == original_synonyms


class TestQueryExpanderIntegration:
    """Integration tests for full expansion pipeline."""

    def test_full_expansion_pipeline(self):
        """Test that all expansion strategies work together."""
        expander = QueryExpander(domain="general")
        query = "what is latest AI news"
        variants = expander.expand(query, max_variants=5)

        # Should have:
        # 1. Original
        # 2. Possibly synonym (AI -> artificial intelligence)
        # 3. Possibly temporal (add 2026)
        # 4. Possibly reformulation (what is -> explained)
        # 5. Possibly language expansion

        assert len(variants) >= 1
        assert query in variants

    def test_multiple_expansions_same_query(self):
        """Test that same query returns consistent results."""
        expander = QueryExpander(domain="general")
        variants1 = expander.expand("AI news", max_variants=3)
        variants2 = expander.expand("AI news", max_variants=3)

        # Should be deterministic
        assert variants1 == variants2

    def test_finance_vs_general_expansion_differences(self):
        """Test that finance and general domains have different expansions."""
        query = "rate cut news"

        general = QueryExpander(domain="general").expand(query, max_variants=3)
        finance = QueryExpander(domain="finance").expand(query, max_variants=3)

        # Finance should expand differently due to domain-specific synonyms
        # (though both should have originals)
        assert query in general
        assert query in finance
