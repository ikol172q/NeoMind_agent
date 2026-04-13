"""Tests for agent/finance/signal_schema.py — Pydantic models + parse ladder."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from agent.finance.signal_schema import (
    AgentAnalysis,
    AnalysisResult,
    SignalParseError,
    StockQuoteSchema,
    hold_fallback,
    parse_signal,
    parse_signal_strict,
)
from agent.finance.response_validator import get_finance_validator


# ── StockQuoteSchema ────────────────────────────────────────────────────

def test_stock_quote_uppercases_symbol():
    q = StockQuoteSchema(symbol="aapl", price=150.0)
    assert q.symbol == "AAPL"


def test_stock_quote_rejects_negative_price():
    with pytest.raises(ValidationError):
        StockQuoteSchema(symbol="AAPL", price=-1.0)


def test_stock_quote_frozen():
    q = StockQuoteSchema(symbol="AAPL", price=150.0)
    with pytest.raises(ValidationError):
        q.price = 200.0  # type: ignore[misc]


# ── AgentAnalysis ───────────────────────────────────────────────────────

def test_agent_analysis_happy_path():
    a = AgentAnalysis(signal="buy", confidence=8, reason="strong earnings")
    assert a.signal == "buy"
    assert a.confidence == 8
    assert a.risk_level == "medium"
    assert a.sources == []


def test_agent_analysis_rejects_out_of_range_confidence():
    with pytest.raises(ValidationError):
        AgentAnalysis(signal="buy", confidence=11, reason="x")
    with pytest.raises(ValidationError):
        AgentAnalysis(signal="buy", confidence=0, reason="x")


def test_agent_analysis_rejects_unknown_signal():
    with pytest.raises(ValidationError):
        AgentAnalysis(signal="moon", confidence=5, reason="x")  # type: ignore[arg-type]


def test_agent_analysis_rejects_extra_fields():
    with pytest.raises(ValidationError):
        AgentAnalysis(
            signal="buy", confidence=5, reason="x", extra_field="boom"  # type: ignore[call-arg]
        )


def test_agent_analysis_strips_empty_sources():
    a = AgentAnalysis(
        signal="buy", confidence=5, reason="x",
        sources=["Finnhub", "", "   ", "Reuters"],
    )
    assert a.sources == ["Finnhub", "Reuters"]


# ── parse_signal_strict ─────────────────────────────────────────────────

def test_parse_strict_clean_json():
    out = parse_signal_strict(
        '{"signal":"buy","confidence":8,"reason":"ok","risk_level":"low"}'
    )
    assert out.signal == "buy"
    assert out.risk_level == "low"


def test_parse_strict_rejects_prose():
    with pytest.raises(SignalParseError):
        parse_signal_strict("Here is the analysis: the signal is buy.")


def test_parse_strict_rejects_fenced_block():
    # Strict layer must reject — it's the lenient layer's job to handle fences.
    with pytest.raises(SignalParseError):
        parse_signal_strict('```json\n{"signal":"buy","confidence":5,"reason":"x"}\n```')


def test_parse_strict_rejects_non_string_input():
    with pytest.raises(SignalParseError):
        parse_signal_strict(None)  # type: ignore[arg-type]


# ── parse_signal (3-layer ladder) ───────────────────────────────────────

def test_ladder_strict_layer():
    a, layer = parse_signal('{"signal":"sell","confidence":6,"reason":"slowdown"}')
    assert layer == "strict"
    assert a.signal == "sell"


def test_ladder_lenient_markdown_fence():
    raw = 'Here is my analysis:\n```json\n{"signal":"BULLISH","confidence":"7/10","reason":"ok"}\n```'
    a, layer = parse_signal(raw)
    assert layer == "lenient"
    assert a.signal == "buy"     # normalized from BULLISH
    assert a.confidence == 7     # coerced from "7/10"


def test_ladder_lenient_percent_confidence():
    raw = '{"signal":"neutral","confidence":"70%","reason":"mixed"}'
    a, layer = parse_signal(raw)
    assert layer == "lenient"
    assert a.signal == "hold"    # neutral -> hold
    assert a.confidence == 7     # 70% -> 7.0 -> 7


def test_ladder_lenient_trailing_comma_repair():
    raw = '{"signal":"buy","confidence":5,"reason":"ok",}'
    a, layer = parse_signal(raw)
    assert layer == "lenient"
    assert a.signal == "buy"


def test_ladder_lenient_aliased_keys():
    raw = '{"action":"SHORT","conviction":8,"rationale":"overvalued"}'
    a, layer = parse_signal(raw)
    assert layer == "lenient"
    assert a.signal == "sell"
    assert a.confidence == 8


def test_ladder_lenient_float_confidence():
    raw = '{"signal":"buy","confidence":0.7,"reason":"ok"}'
    a, layer = parse_signal(raw)
    assert layer == "lenient"
    assert a.confidence == 7


def test_ladder_fallback_on_garbage():
    a, layer = parse_signal("totally unparseable garbage output")
    assert layer == "fallback"
    assert a.signal == "hold"
    assert a.confidence == 1
    assert a.risk_level == "high"
    assert a.reason.startswith("[parse_fallback]")


def test_ladder_fallback_on_none_input():
    a, layer = parse_signal(None)  # type: ignore[arg-type]
    assert layer == "fallback"
    assert a.signal == "hold"


def test_ladder_fallback_on_missing_required_fields():
    # Valid JSON but missing the required 'reason' field
    a, layer = parse_signal('{"signal":"buy","confidence":7}')
    assert layer == "fallback"
    assert a.signal == "hold"


def test_hold_fallback_truncates_long_error():
    err = "x" * 500
    a = hold_fallback(err, max_len=100)
    assert len(a.reason) <= 120  # 100 + prefix
    assert a.reason.endswith("...")


# ── AnalysisResult wrapper ──────────────────────────────────────────────

def test_analysis_result_round_trip():
    quote = StockQuoteSchema(symbol="AAPL", price=150.0, change_percent=1.2)
    analysis = AgentAnalysis(
        signal="buy", confidence=8, reason="strong earnings",
        sources=["Finnhub"],
    )
    result = AnalysisResult(
        symbol="AAPL", quote=quote, analysis=analysis, project_id="us-growth-2026q2",
    )
    dumped = result.model_dump_json()
    # Deserialize back
    data = json.loads(dumped)
    assert data["symbol"] == "AAPL"
    assert data["analysis"]["confidence"] == 8
    assert data["project_id"] == "us-growth-2026q2"
    assert data["model_used"] == "deepseek-reasoner"  # default per memory preference


def test_analysis_result_default_model_is_deepseek():
    quote = StockQuoteSchema(symbol="AAPL", price=150.0)
    analysis = AgentAnalysis(signal="hold", confidence=5, reason="x")
    result = AnalysisResult(symbol="AAPL", quote=quote, analysis=analysis)
    assert result.model_used == "deepseek-reasoner"


# ── validate_agent_analysis (structural checks on top of Pydantic) ──────

def test_validator_flags_buy_without_sources():
    v = get_finance_validator(strict=False)
    a = AgentAnalysis(signal="buy", confidence=7, reason="looks good", sources=[])
    r = v.validate_agent_analysis(a)
    assert r.passed is False
    assert any("empty" in w for w in r.warnings)


def test_validator_accepts_buy_with_sources():
    v = get_finance_validator(strict=False)
    a = AgentAnalysis(
        signal="buy", confidence=7, reason="earnings beat per Finnhub",
        sources=["Finnhub"],
    )
    r = v.validate_agent_analysis(a)
    # Non-reason checks pass; .reason may still emit free-text warnings
    assert not any("empty" in w for w in r.warnings)


def test_validator_warns_high_confidence_zero_sources():
    v = get_finance_validator(strict=False)
    # hold is allowed to have no sources structurally, but high confidence
    # without evidence is still a warning.
    a = AgentAnalysis(signal="hold", confidence=9, reason="gut feel", sources=[])
    r = v.validate_agent_analysis(a)
    assert any("confidence=9" in w for w in r.warnings)


def test_validator_flags_hold_with_target_price():
    v = get_finance_validator(strict=False)
    a = AgentAnalysis(
        signal="hold", confidence=5, reason="wait and see",
        target_price=200.0, sources=["x"],
    )
    r = v.validate_agent_analysis(a)
    assert any("mixed message" in w for w in r.warnings)


def test_validator_flags_parse_fallback_marker():
    v = get_finance_validator(strict=False)
    a = hold_fallback("bad LLM output")
    r = v.validate_agent_analysis(a)
    assert any("parse_fallback" in w for w in r.warnings)


def test_validator_rejects_non_agent_analysis_input():
    v = get_finance_validator(strict=False)
    r = v.validate_agent_analysis({"signal": "buy"})  # type: ignore[arg-type]
    assert r.passed is False
    assert r.blocked is True


def test_validator_strict_mode_blocks_buy_no_sources():
    # Instantiate directly — get_finance_validator() is a cached singleton
    # so the strict flag from a later call doesn't override an earlier one.
    from agent.finance.response_validator import FinanceResponseValidator
    v = FinanceResponseValidator(strict=True)
    a = AgentAnalysis(signal="buy", confidence=8, reason="ok", sources=[])
    r = v.validate_agent_analysis(a)
    assert r.passed is False
    assert r.blocked is True
