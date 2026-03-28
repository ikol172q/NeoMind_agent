"""
Comprehensive unit tests for agent/finance/investment_personas.py
Tests personas, scoring rubrics, and consensus analysis.
"""

import pytest
from typing import List, Dict, Any

from agent.finance.investment_personas import (
    PersonaRubric,
    InvestmentPersona,
    VALUE_INVESTOR,
    GROWTH_INVESTOR,
    MACRO_STRATEGIST,
    PERSONAS,
    get_persona,
    multi_persona_analysis,
    consensus_summary,
)


# ── PersonaRubric Tests ──────────────────────────────────────────────

class TestPersonaRubric:
    def test_creation(self):
        rubric = PersonaRubric(
            criteria={
                "metric_a": 0.5,
                "metric_b": 0.3,
                "metric_c": 0.2,
            },
            red_flags=["Bad condition", "Worse condition"],
        )
        assert len(rubric.criteria) == 3
        assert len(rubric.red_flags) == 2

    def test_score_calculation(self):
        """Test weighted scoring."""
        rubric = PersonaRubric(
            criteria={
                "quality": 0.6,
                "value": 0.4,
            },
            red_flags=[],
        )
        scores = {
            "quality": 8.0,
            "value": 6.0,
        }
        result = rubric.score(scores)
        expected = (8.0 * 0.6 + 6.0 * 0.4) / 1.0
        assert result == expected

    def test_score_partial_criteria(self):
        """Test scoring when not all criteria are present."""
        rubric = PersonaRubric(
            criteria={"a": 0.5, "b": 0.5},
            red_flags=[],
        )
        scores = {"a": 7.0}  # b is missing
        result = rubric.score(scores)
        # Should only use criterion a
        assert result == 7.0

    def test_score_empty_criteria(self):
        """Test scoring with no criteria."""
        rubric = PersonaRubric(criteria={}, red_flags=[])
        scores = {"unused": 5.0}
        result = rubric.score(scores)
        assert result == 0.0  # division by zero protection

    def test_score_zero_weight_sum(self):
        """Test when weight sum is zero."""
        rubric = PersonaRubric(
            criteria={"a": 0.0, "b": 0.0},
            red_flags=[],
        )
        scores = {"a": 10.0, "b": 10.0}
        result = rubric.score(scores)
        assert result >= 0  # Should not crash

    def test_rubric_with_single_criterion(self):
        """Test rubric with one criterion."""
        rubric = PersonaRubric(
            criteria={"single_metric": 1.0},
            red_flags=[],
        )
        scores = {"single_metric": 7.5}
        result = rubric.score(scores)
        assert result == 7.5

    def test_rubric_weights_sum_to_one(self):
        """Test rubric where weights sum to exactly 1.0."""
        rubric = PersonaRubric(
            criteria={
                "a": 0.25,
                "b": 0.25,
                "c": 0.25,
                "d": 0.25,
            },
            red_flags=[],
        )
        assert sum(rubric.criteria.values()) == 1.0


# ── InvestmentPersona Tests ──────────────────────────────────────────

class TestInvestmentPersona:
    def test_persona_attributes(self):
        """Test that all personas have required attributes."""
        for name, persona in PERSONAS.items():
            assert persona.name is not None
            assert persona.philosophy is not None
            assert persona.system_prompt is not None
            assert persona.rubric is not None
            assert persona.focus_metrics is not None
            assert persona.typical_horizon is not None

    def test_format_analysis_prompt(self):
        """Test analysis prompt generation."""
        prompt = VALUE_INVESTOR.format_analysis_prompt(
            "AAPL",
            "Market cap: $2.5T\nP/E: 25x",
        )
        assert "AAPL" in prompt
        assert "Market cap" in prompt
        assert "VERDICT" in prompt
        assert "KEY THESIS" in prompt
        assert "RISK FACTORS" in prompt
        assert "SCORE" in prompt
        assert "ACTION" in prompt

    def test_value_investor_persona(self):
        """Test value investor characteristics."""
        assert "Value" in VALUE_INVESTOR.name
        assert VALUE_INVESTOR.icon == "📊"
        assert "1-5 years" in VALUE_INVESTOR.typical_horizon
        assert "pe_ratio" in VALUE_INVESTOR.focus_metrics
        assert "intrinsic_value_discount" in VALUE_INVESTOR.rubric.criteria

    def test_growth_investor_persona(self):
        """Test growth investor characteristics."""
        assert "Growth" in GROWTH_INVESTOR.name
        assert GROWTH_INVESTOR.icon == "🚀"
        assert "1-3 years" in GROWTH_INVESTOR.typical_horizon
        assert "revenue_growth" in str(GROWTH_INVESTOR.focus_metrics).lower()
        assert "revenue_acceleration" in GROWTH_INVESTOR.rubric.criteria

    def test_macro_strategist_persona(self):
        """Test macro strategist characteristics."""
        assert "Macro" in MACRO_STRATEGIST.name
        assert MACRO_STRATEGIST.icon == "🌍"
        assert "3-12 months" in MACRO_STRATEGIST.typical_horizon
        assert "fed_funds_rate" in MACRO_STRATEGIST.focus_metrics
        assert "cycle_position" in MACRO_STRATEGIST.rubric.criteria

    def test_persona_has_red_flags(self):
        """Test that personas have defined red flags."""
        for persona in PERSONAS.values():
            assert len(persona.rubric.red_flags) > 0

    def test_value_investor_red_flags(self):
        """Test value investor red flags."""
        red_flags = VALUE_INVESTOR.rubric.red_flags
        assert any("free cash flow" in flag.lower() for flag in red_flags)
        assert any("debt" in flag.lower() for flag in red_flags)

    def test_growth_investor_red_flags(self):
        """Test growth investor red flags."""
        red_flags = GROWTH_INVESTOR.rubric.red_flags
        assert any("growth" in flag.lower() for flag in red_flags)

    def test_macro_strategist_red_flags(self):
        """Test macro strategist red flags."""
        red_flags = MACRO_STRATEGIST.rubric.red_flags
        assert any("fed" in flag.lower() or "cycle" in flag.lower() for flag in red_flags)


# ── get_persona Tests ────────────────────────────────────────────────

class TestGetPersona:
    def test_get_persona_by_exact_name(self):
        """Test retrieving persona by exact key."""
        persona = get_persona("value")
        assert persona is not None
        assert persona.name == "Value Investor"

    def test_get_persona_case_insensitive(self):
        """Test case-insensitive persona lookup."""
        persona = get_persona("VALUE")
        assert persona is not None

    def test_get_persona_by_name_substring(self):
        """Test retrieving persona by name substring."""
        persona = get_persona("growth")
        assert persona is not None
        assert "Growth" in persona.name

    def test_get_persona_partial_match(self):
        """Test partial name matching."""
        persona = get_persona("Macro")
        assert persona is not None

    def test_get_persona_nonexistent(self):
        """Test getting nonexistent persona."""
        persona = get_persona("nonexistent_persona_xyz")
        assert persona is None

    def test_get_persona_empty_string(self):
        """Test with empty string."""
        persona = get_persona("")
        assert persona is None

    def test_all_personas_retrievable(self):
        """Test that all defined personas are retrievable."""
        for key in PERSONAS.keys():
            persona = get_persona(key)
            assert persona is not None


# ── multi_persona_analysis Tests ────────────────────────────────────

class TestMultiPersonaAnalysis:
    def test_multi_persona_default(self):
        """Test multi-persona analysis with default personas."""
        analyses = multi_persona_analysis("AAPL", "Market cap: $2.5T")
        assert len(analyses) == 3  # All three personas

    def test_multi_persona_select_subset(self):
        """Test multi-persona with selected personas."""
        analyses = multi_persona_analysis(
            "MSFT",
            "Revenue growth: 15% YoY",
            personas=["value", "growth"],
        )
        assert len(analyses) == 2

    def test_multi_persona_single(self):
        """Test multi-persona with just one persona."""
        analyses = multi_persona_analysis(
            "GOOGL",
            "Data: test",
            personas=["macro"],
        )
        assert len(analyses) == 1

    def test_multi_persona_output_structure(self):
        """Test output structure of multi-persona analysis."""
        analyses = multi_persona_analysis("TEST", "Context", personas=["value"])
        analysis = analyses[0]

        assert "persona_name" in analysis
        assert "persona_icon" in analysis
        assert "philosophy" in analysis
        assert "horizon" in analysis
        assert "prompt" in analysis
        assert "rubric_criteria" in analysis
        assert "red_flags" in analysis

    def test_multi_persona_includes_prompt(self):
        """Test that analysis includes complete prompt."""
        analyses = multi_persona_analysis("AAPL", "Context data")
        for analysis in analyses:
            prompt = analysis["prompt"]
            assert "AAPL" in prompt
            assert "Context data" in prompt

    def test_multi_persona_invalid_persona_name(self):
        """Test with invalid persona name (should be skipped)."""
        analyses = multi_persona_analysis(
            "TEST",
            "Data",
            personas=["value", "nonexistent", "growth"],
        )
        # Should only include valid personas
        assert len(analyses) == 2

    def test_multi_persona_empty_list(self):
        """Test with empty persona list."""
        analyses = multi_persona_analysis("TEST", "Data", personas=[])
        assert len(analyses) == 0

    def test_multi_persona_none_personas(self):
        """Test with None personas (should use all)."""
        analyses = multi_persona_analysis("TEST", "Data", personas=None)
        assert len(analyses) == 3


# ── consensus_summary Tests ──────────────────────────────────────────

class TestConsensusSummary:
    def test_consensus_empty_verdicts(self):
        """Test consensus with empty verdict list."""
        result = consensus_summary([])
        assert result["consensus"] == "insufficient_data"
        assert result["agreement"] == 0

    def test_consensus_all_bullish(self):
        """Test when all verdicts are bullish."""
        verdicts = [
            {"persona_name": "Value", "verdict": "bullish", "confidence": 80},
            {"persona_name": "Growth", "verdict": "bullish", "confidence": 90},
            {"persona_name": "Macro", "verdict": "bullish", "confidence": 75},
        ]
        result = consensus_summary(verdicts)
        assert result["consensus"] == "strong_bullish"
        assert result["agreement"] == 1.0
        assert result["bull_count"] == 3
        assert result["bear_count"] == 0

    def test_consensus_all_bearish(self):
        """Test when all verdicts are bearish."""
        verdicts = [
            {"persona_name": "Value", "verdict": "bearish", "confidence": 80},
            {"persona_name": "Growth", "verdict": "bearish", "confidence": 85},
        ]
        result = consensus_summary(verdicts)
        assert result["consensus"] == "strong_bearish"
        assert result["agreement"] == 1.0
        assert result["bear_count"] == 2

    def test_consensus_mixed_bullish_majority(self):
        """Test consensus with bullish majority."""
        verdicts = [
            {"persona_name": "A", "verdict": "bullish", "confidence": 80},
            {"persona_name": "B", "verdict": "bullish", "confidence": 75},
            {"persona_name": "C", "verdict": "bearish", "confidence": 60},
        ]
        result = consensus_summary(verdicts)
        assert result["consensus"] == "lean_bullish"
        assert result["bull_count"] == 2
        assert result["bear_count"] == 1
        assert "C" in result["dissenters"]

    def test_consensus_mixed_bearish_majority(self):
        """Test consensus with bearish majority."""
        verdicts = [
            {"persona_name": "A", "verdict": "bullish", "confidence": 70},
            {"persona_name": "B", "verdict": "bearish", "confidence": 80},
            {"persona_name": "C", "verdict": "bearish", "confidence": 85},
        ]
        result = consensus_summary(verdicts)
        assert result["consensus"] == "lean_bearish"
        assert result["bear_count"] == 2
        assert result["bull_count"] == 1

    def test_consensus_split_decision(self):
        """Test consensus when split 50-50."""
        verdicts = [
            {"persona_name": "A", "verdict": "bullish", "confidence": 80},
            {"persona_name": "B", "verdict": "bearish", "confidence": 80},
        ]
        result = consensus_summary(verdicts)
        assert result["consensus"] == "contested"

    def test_consensus_includes_neutrals(self):
        """Test consensus counting neutral verdicts."""
        verdicts = [
            {"persona_name": "A", "verdict": "bullish", "confidence": 70},
            {"persona_name": "B", "verdict": "neutral", "confidence": 50},
            {"persona_name": "C", "verdict": "bearish", "confidence": 70},
        ]
        result = consensus_summary(verdicts)
        assert result["neutral_count"] == 1

    def test_consensus_average_confidence(self):
        """Test average confidence calculation."""
        verdicts = [
            {"persona_name": "A", "verdict": "bullish", "confidence": 80},
            {"persona_name": "B", "verdict": "bullish", "confidence": 100},
        ]
        result = consensus_summary(verdicts)
        assert result["avg_confidence"] == 90.0

    def test_consensus_with_missing_confidence(self):
        """Test consensus when confidence is missing."""
        verdicts = [
            {"persona_name": "A", "verdict": "bullish"},  # No confidence
            {"persona_name": "B", "verdict": "bullish", "confidence": 80},
        ]
        result = consensus_summary(verdicts)
        # Should handle missing confidence (defaults to 50)
        assert result["avg_confidence"] is not None

    def test_consensus_identifies_dissenters(self):
        """Test that dissenters are correctly identified."""
        verdicts = [
            {"persona_name": "Persona1", "verdict": "bullish", "confidence": 80},
            {"persona_name": "Persona2", "verdict": "bullish", "confidence": 75},
            {"persona_name": "Persona3", "verdict": "bearish", "confidence": 60},
        ]
        result = consensus_summary(verdicts)
        assert "Persona3" in result["dissenters"]
        assert len(result["dissenters"]) == 1

    def test_consensus_multiple_dissenters(self):
        """Test with multiple dissenters."""
        verdicts = [
            {"persona_name": "P1", "verdict": "bullish", "confidence": 80},
            {"persona_name": "P2", "verdict": "bearish", "confidence": 70},
            {"persona_name": "P3", "verdict": "bearish", "confidence": 75},
        ]
        result = consensus_summary(verdicts)
        # Majority is bearish, so bullish persona is dissenter
        assert len(result["dissenters"]) >= 1


# ── Edge Cases and Integration Tests ────────────────────────────────

class TestPersonasEdgeCases:
    def test_persona_rubric_extreme_weights(self):
        """Test rubric with extreme weight distributions."""
        rubric = PersonaRubric(
            criteria={"a": 0.99, "b": 0.01},
            red_flags=[],
        )
        scores = {"a": 10.0, "b": 0.0}
        result = rubric.score(scores)
        assert result > 9.0  # Should be heavily weighted to a

    def test_persona_rubric_scores_out_of_range(self):
        """Test scoring with out-of-range values."""
        rubric = PersonaRubric(
            criteria={"metric": 1.0},
            red_flags=[],
        )
        # Scores can be >10 or <0
        scores = {"metric": 15.0}
        result = rubric.score(scores)
        assert result == 15.0

    def test_get_persona_whitespace(self):
        """Test persona lookup with whitespace."""
        persona = get_persona("  value  ")
        assert persona is not None

    def test_multi_persona_duplicate_personas(self):
        """Test when same persona requested multiple times."""
        analyses = multi_persona_analysis(
            "TEST",
            "Data",
            personas=["value", "value", "growth"],
        )
        # Should handle duplicates gracefully
        assert len(analyses) >= 2

    def test_consensus_single_verdict(self):
        """Test consensus with just one verdict."""
        verdicts = [
            {"persona_name": "Lone", "verdict": "bullish", "confidence": 100},
        ]
        result = consensus_summary(verdicts)
        assert result["consensus"] == "strong_bullish"
        assert result["agreement"] == 1.0

    def test_consensus_verdict_missing_verdict_field(self):
        """Test consensus when verdict field is missing."""
        verdicts = [
            {"persona_name": "A", "confidence": 80},  # No verdict
            {"persona_name": "B", "verdict": "bullish", "confidence": 80},
        ]
        result = consensus_summary(verdicts)
        # Should handle gracefully
        assert result["consensus"] in ["lean_bullish", "contested", "insufficient_data"]

    def test_persona_analysis_very_long_context(self):
        """Test analysis prompt with very long data context."""
        long_context = "Data point " * 1000  # Very long
        analyses = multi_persona_analysis("TEST", long_context)
        for analysis in analyses:
            prompt = analysis["prompt"]
            assert long_context in prompt

    def test_persona_symbols_extraction(self):
        """Test multi-persona with multiple symbols mentioned."""
        context = "Compare AAPL vs MSFT vs GOOGL earnings"
        analyses = multi_persona_analysis("COMPARISON", context)
        # All analyses should mention the comparison context
        for analysis in analyses:
            assert "AAPL" in analysis["prompt"] or "COMPARISON" in analysis["prompt"]
