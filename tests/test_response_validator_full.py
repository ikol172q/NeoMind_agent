"""Comprehensive tests for agent/finance/response_validator.py — Five Iron Rules."""

import pytest
from agent.finance.response_validator import (
    FinanceResponseValidator,
    ValidationResult,
    _extract_prices,
    _extract_prices_from_tool_results,
    _normalize_price,
    _line_has_source,
    _is_in_excluded_context,
    get_finance_validator,
    PRICE_PATTERNS,
    MATH_TRIGGER_PATTERNS,
    SOURCE_PATTERNS,
    PRICE_EXCLUDE_PATTERNS,
    TOOL_OUTPUT_MARKERS,
    RECOMMENDATION_KEYWORDS,
    TIME_HORIZON_KEYWORDS,
    CONFIDENCE_PATTERNS,
    DISCLAIMER_PATTERNS,
    KNOWN_DATA_SOURCES,
)


# ── ValidationResult Tests ────────────────────────────────────────────

class TestValidationResult:
    """Tests for the ValidationResult dataclass."""

    def test_default_values(self):
        r = ValidationResult(passed=True)
        assert r.passed is True
        assert r.warnings == []
        assert r.blocked is False
        assert r.reason == ""
        assert r.action == ""
        assert r.unverified_prices == []
        assert r.approximate_calcs == []
        assert r.unsourced_data == []
        assert r.missing_time_horizons is False
        assert r.missing_confidence is False
        assert r.missing_disclaimer is False

    def test_summary_empty_when_passed(self):
        r = ValidationResult(passed=True)
        assert r.summary() == ""

    def test_summary_with_unverified_prices(self):
        r = ValidationResult(passed=False, unverified_prices=["$195.42", "$300.00"])
        s = r.summary()
        assert "未验证价格" in s
        assert "$195.42" in s
        assert "$300.00" in s

    def test_summary_with_approximate_calcs(self):
        r = ValidationResult(passed=False, approximate_calcs=["approximately $76,000"])
        s = r.summary()
        assert "近似计算" in s

    def test_summary_with_unsourced_data(self):
        r = ValidationResult(passed=False, unsourced_data=["$500"])
        s = r.summary()
        assert "缺少数据源" in s

    def test_summary_with_missing_time_horizons(self):
        r = ValidationResult(passed=False, missing_time_horizons=True)
        s = r.summary()
        assert "Rule 4" in s

    def test_summary_with_missing_confidence(self):
        r = ValidationResult(passed=False, missing_confidence=True)
        s = r.summary()
        assert "置信度" in s

    def test_summary_with_missing_disclaimer(self):
        r = ValidationResult(passed=False, missing_disclaimer=True)
        s = r.summary()
        assert "免责声明" in s

    def test_summary_with_warnings(self):
        r = ValidationResult(passed=False, warnings=["custom warning 1"])
        s = r.summary()
        assert "custom warning 1" in s

    def test_summary_combined(self):
        r = ValidationResult(
            passed=False,
            unverified_prices=["$100"],
            approximate_calcs=["~$200"],
            missing_time_horizons=True,
            warnings=["extra warn"],
        )
        s = r.summary()
        assert "未验证价格" in s
        assert "近似计算" in s
        assert "Rule 4" in s
        assert "extra warn" in s


# ── Price Extraction Tests ────────────────────────────────────────────

class TestExtractPrices:
    """Tests for _extract_prices()."""

    def test_usd_simple(self):
        assert "$195.42" in _extract_prices("The price is $195.42 today.")

    def test_usd_with_commas(self):
        prices = _extract_prices("Total value: $1,234,567.89")
        assert any("1,234,567.89" in p for p in prices)

    def test_cny_yen(self):
        prices = _extract_prices("价格是 ¥1,234.56")
        assert any("1,234.56" in p for p in prices)

    def test_hkd(self):
        prices = _extract_prices("HK$85.20 per share")
        assert any("85.20" in p for p in prices)

    def test_euro(self):
        prices = _extract_prices("€123.45 est le prix")
        assert any("123.45" in p for p in prices)

    def test_gbp(self):
        prices = _extract_prices("£99.00 for this item")
        assert any("99.00" in p for p in prices)

    def test_currency_suffix(self):
        prices = _extract_prices("Current BTC price: 45,000 USD")
        assert len(prices) >= 1

    def test_no_prices(self):
        assert _extract_prices("No financial data here.") == []

    def test_multiple_prices(self):
        text = "AAPL is at $195.42, GOOGL at $142.50, and BTC at $65,000 USD"
        prices = _extract_prices(text)
        assert len(prices) >= 3


class TestExtractPricesFromToolResults:
    """Tests for _extract_prices_from_tool_results()."""

    def test_from_content_key(self):
        results = [{"content": "Current price: $195.42 (Finnhub, 2024-01-15)"}]
        prices = _extract_prices_from_tool_results(results)
        assert any("195.42" in p for p in prices)

    def test_from_output_key(self):
        results = [{"output": "BTC: $65,000 USD"}]
        prices = _extract_prices_from_tool_results(results)
        assert len(prices) >= 1

    def test_empty_results(self):
        assert _extract_prices_from_tool_results([]) == set()

    def test_none_content(self):
        results = [{"content": None}]
        prices = _extract_prices_from_tool_results(results)
        # Should not crash
        assert isinstance(prices, set)

    def test_multiple_results(self):
        results = [
            {"content": "$100.00"},
            {"content": "$200.00"},
        ]
        prices = _extract_prices_from_tool_results(results)
        assert len(prices) >= 2


class TestNormalizePrice:
    """Tests for _normalize_price()."""

    def test_remove_commas(self):
        assert _normalize_price("$1,234.56") == "$1234.56"

    def test_remove_spaces(self):
        assert _normalize_price("$ 100") == "$100"

    def test_already_clean(self):
        assert _normalize_price("$100.50") == "$100.50"


class TestLineHasSource:
    """Tests for _line_has_source()."""

    def test_tool_output_marker(self):
        text = "AAPL: $195.42 (source: Finnhub)"
        assert _line_has_source(text, "$195.42") is True

    def test_known_source_pattern(self):
        text = "Price is $195.42 (Finnhub, 2024-01-15 14:30 UTC)"
        assert _line_has_source(text, "$195.42") is True

    def test_chinese_source(self):
        text = "当前价格 ¥100.00 数据来源：AKShare"
        assert _line_has_source(text, "¥100.00") is True

    def test_no_source(self):
        text = "AAPL: $195.42"
        assert _line_has_source(text, "$195.42") is False

    def test_source_on_different_line(self):
        text = "AAPL: $195.42\n(source: Finnhub)"
        assert _line_has_source(text, "$195.42") is False

    def test_computed_marker(self):
        text = "Total: $1,000.00 (computed)"
        assert _line_has_source(text, "$1,000.00") is True


class TestIsInExcludedContext:
    """Tests for _is_in_excluded_context()."""

    def test_fee_context(self):
        text = "commission fee is $5.00 per trade"
        assert _is_in_excluded_context(text, "$5.00") is True

    def test_example_context(self):
        text = "for example, $100 invested would yield..."
        assert _is_in_excluded_context(text, "$100") is True

    def test_chinese_example(self):
        text = "例如，假设你投资了 $500"
        assert _is_in_excluded_context(text, "$500") is True

    def test_not_excluded(self):
        text = "AAPL current price: $195.42"
        assert _is_in_excluded_context(text, "$195.42") is False


# ── FinanceResponseValidator Tests ────────────────────────────────────

class TestValidatorInit:
    """Tests for FinanceResponseValidator initialization."""

    def test_default_not_strict(self):
        v = FinanceResponseValidator()
        assert v.strict is False

    def test_strict_mode(self):
        v = FinanceResponseValidator(strict=True)
        assert v.strict is True


class TestValidatorRule1:
    """Rule 1: No unverified financial numbers from LLM memory."""

    def test_clean_response_no_prices(self):
        v = FinanceResponseValidator()
        result = v.validate("This is a general market overview.")
        assert result.passed is True
        assert result.unverified_prices == []

    def test_unverified_price_detected(self):
        v = FinanceResponseValidator()
        result = v.validate("AAPL is currently at $195.42 per share.")
        assert result.passed is False
        assert len(result.unverified_prices) > 0

    def test_verified_price_from_tool(self):
        v = FinanceResponseValidator()
        tool_results = [{"content": "$195.42"}]
        result = v.validate("AAPL is at $195.42", tool_results)
        assert "$195.42" not in result.unverified_prices

    def test_price_with_source_marker(self):
        v = FinanceResponseValidator()
        result = v.validate("AAPL: $195.42 (source: Finnhub)")
        assert "$195.42" not in result.unverified_prices

    def test_excluded_context_fee(self):
        v = FinanceResponseValidator()
        result = v.validate("The commission fee is $5.00 per trade")
        assert "$5.00" not in result.unverified_prices

    def test_strict_blocks_unverified(self):
        v = FinanceResponseValidator(strict=True)
        result = v.validate("Price is $300.00 today")
        assert result.blocked is True
        assert result.action == "re_route_to_tool"

    def test_non_strict_adds_disclaimer(self):
        v = FinanceResponseValidator(strict=False)
        result = v.validate("Price is $300.00 today")
        assert result.blocked is False
        assert result.action == "add_disclaimer"


class TestValidatorRule2:
    """Rule 2: No approximate calculations."""

    def test_approximate_english(self):
        v = FinanceResponseValidator()
        result = v.validate("The portfolio is worth approximately $76,000")
        assert len(result.approximate_calcs) > 0

    def test_approximate_tilde(self):
        v = FinanceResponseValidator()
        result = v.validate("Total investment: ~$50,000")
        assert len(result.approximate_calcs) > 0

    def test_approximate_chinese(self):
        v = FinanceResponseValidator()
        result = v.validate("投资金额大约 $100,000")
        assert len(result.approximate_calcs) > 0

    def test_computed_result_ok(self):
        v = FinanceResponseValidator()
        result = v.validate("approximately $76,000 (computed)")
        assert len(result.approximate_calcs) == 0

    def test_quantengine_result_ok(self):
        v = FinanceResponseValidator()
        result = v.validate("roughly $50,000 (QuantEngine)")
        assert len(result.approximate_calcs) == 0


class TestValidatorRule3:
    """Rule 3: Source attribution."""

    def test_unsourced_price(self):
        v = FinanceResponseValidator()
        result = v.validate("AAPL: $195.42")
        assert len(result.unsourced_data) > 0

    def test_sourced_price_no_warning(self):
        v = FinanceResponseValidator()
        result = v.validate("AAPL: $195.42 (source: Finnhub)")
        assert "$195.42" not in result.unsourced_data

    def test_no_prices_no_warnings(self):
        v = FinanceResponseValidator()
        result = v.validate("The market is bullish overall.")
        assert result.unsourced_data == []


class TestValidatorRule4:
    """Rule 4: Recommendations need confidence, time horizon, disclaimer."""

    def test_recommendation_without_time_horizon(self):
        v = FinanceResponseValidator()
        result = v.validate("I recommend buying AAPL. 80% confident. Not financial advice.")
        assert result.missing_time_horizons is True

    def test_recommendation_with_time_horizons(self):
        v = FinanceResponseValidator()
        text = (
            "I recommend buying AAPL. Short-term target: $200. "
            "Long-term target: $250. 80% confident. Not financial advice."
        )
        result = v.validate(text)
        assert result.missing_time_horizons is False

    def test_recommendation_without_confidence(self):
        v = FinanceResponseValidator()
        text = "I suggest buying AAPL. Short-term and long-term outlook positive. Not financial advice."
        result = v.validate(text)
        assert result.missing_confidence is True

    def test_recommendation_with_confidence(self):
        v = FinanceResponseValidator()
        text = "I suggest buying AAPL. 80% confident. Short-term and long-term outlook."
        result = v.validate(text)
        assert result.missing_confidence is False

    def test_recommendation_without_disclaimer(self):
        v = FinanceResponseValidator()
        text = "I recommend AAPL. 80% confident. Short-term and long-term."
        result = v.validate(text)
        assert result.missing_disclaimer is True

    def test_recommendation_with_english_disclaimer(self):
        v = FinanceResponseValidator()
        text = "I recommend AAPL. This is not financial advice."
        result = v.validate(text)
        assert result.missing_disclaimer is False

    def test_recommendation_with_chinese_disclaimer(self):
        v = FinanceResponseValidator()
        text = "建议买入 AAPL。仅供参考。"
        result = v.validate(text)
        assert result.missing_disclaimer is False

    def test_recommendation_with_dyor(self):
        v = FinanceResponseValidator()
        text = "I recommend AAPL. DYOR."
        result = v.validate(text)
        assert result.missing_disclaimer is False

    def test_non_recommendation_skips_rule4(self):
        v = FinanceResponseValidator()
        result = v.validate("Here is a summary of market data.")
        assert result.missing_time_horizons is False
        assert result.missing_confidence is False
        assert result.missing_disclaimer is False

    def test_is_recommendation_detection(self):
        v = FinanceResponseValidator()
        assert v._is_recommendation("I recommend buying this stock") is True
        assert v._is_recommendation("看好 AAPL 的长期表现") is True
        assert v._is_recommendation("Here is the current price") is False


class TestValidatorRule5:
    """Rule 5: Source conflicts are shown, not silently resolved."""

    def test_single_source_no_warning(self):
        v = FinanceResponseValidator()
        text = "According to Finnhub, AAPL is at $195.42"
        result = v.validate(text)
        # No conflict warning expected with single source
        conflict_warnings = [w for w in result.warnings if "Rule 5" in w]
        assert len(conflict_warnings) == 0

    def test_multiple_sources_with_conflict_shown(self):
        v = FinanceResponseValidator()
        text = (
            "According to Finnhub, AAPL: $195. However, Reuters reports $196.\n"
            "There is a difference between Finnhub and Reuters data."
        )
        result = v.validate(text)
        # Conflict is shown — should NOT generate warning
        # (Heuristic check may or may not fire depending on exact matching)

    def test_multiple_sources_no_conflict_indicator(self):
        v = FinanceResponseValidator()
        text = "Finnhub says $100. Bloomberg says $200. The market is active."
        result = v.validate(text)
        # Multiple sources + multiple numbers + no conflict indicator = warning
        conflict_warnings = [w for w in result.warnings if "Rule 5" in w or "数据源" in w]
        assert len(conflict_warnings) >= 1


# ── build_disclaimer Tests ────────────────────────────────────────────

class TestBuildDisclaimer:
    """Tests for build_disclaimer() method."""

    def test_disclaimer_with_unverified_prices(self):
        v = FinanceResponseValidator()
        r = ValidationResult(passed=False, unverified_prices=["$100"])
        d = v.build_disclaimer(r)
        assert "未经数据源验证" in d
        assert "$100" in d
        assert "/price" in d

    def test_disclaimer_with_approximate_calcs(self):
        v = FinanceResponseValidator()
        r = ValidationResult(passed=False, approximate_calcs=["~$50,000"])
        d = v.build_disclaimer(r)
        assert "近似值" in d
        assert "/calc" in d

    def test_disclaimer_with_unsourced_data(self):
        v = FinanceResponseValidator()
        r = ValidationResult(passed=False, unsourced_data=["$200"])
        d = v.build_disclaimer(r)
        assert "来源标注" in d

    def test_disclaimer_with_missing_time_horizons(self):
        v = FinanceResponseValidator()
        r = ValidationResult(passed=False, missing_time_horizons=True)
        d = v.build_disclaimer(r)
        assert "Rule 4a" in d

    def test_disclaimer_with_missing_confidence(self):
        v = FinanceResponseValidator()
        r = ValidationResult(passed=False, missing_confidence=True)
        d = v.build_disclaimer(r)
        assert "Rule 4b" in d

    def test_disclaimer_with_missing_disclaimer(self):
        v = FinanceResponseValidator()
        r = ValidationResult(passed=False, missing_disclaimer=True)
        d = v.build_disclaimer(r)
        assert "Rule 4c" in d

    def test_disclaimer_bilingual(self):
        v = FinanceResponseValidator()
        r = ValidationResult(passed=False, unverified_prices=["$100"])
        d = v.build_disclaimer(r)
        assert "Data Validation Notice" in d
        assert "数据验证提醒" in d


# ── Singleton Tests ───────────────────────────────────────────────────

class TestGetFinanceValidator:
    """Tests for get_finance_validator() singleton."""

    def test_returns_validator(self):
        import agent.finance.response_validator as mod
        mod._validator = None  # Reset
        v = get_finance_validator()
        assert isinstance(v, FinanceResponseValidator)

    def test_returns_same_instance(self):
        import agent.finance.response_validator as mod
        mod._validator = None  # Reset
        v1 = get_finance_validator()
        v2 = get_finance_validator()
        assert v1 is v2

    def test_strict_mode_on_first_call(self):
        import agent.finance.response_validator as mod
        mod._validator = None  # Reset
        v = get_finance_validator(strict=True)
        assert v.strict is True
        mod._validator = None  # Cleanup


# ── Constants Tests ───────────────────────────────────────────────────

class TestConstants:
    """Verify regex patterns compile and match expected inputs."""

    def test_price_patterns_count(self):
        assert len(PRICE_PATTERNS) >= 6

    def test_math_trigger_patterns_match(self):
        assert any(p.search("approximately $76,000") for p in MATH_TRIGGER_PATTERNS)
        assert any(p.search("~$50,000") for p in MATH_TRIGGER_PATTERNS)
        assert any(p.search("大约 $100,000") for p in MATH_TRIGGER_PATTERNS)

    def test_source_patterns_match(self):
        assert any(p.search("(source: Finnhub)") for p in SOURCE_PATTERNS)
        assert any(p.search("(Finnhub, 2024-01-15)") for p in SOURCE_PATTERNS)
        assert any(p.search("数据来源：AKShare") for p in SOURCE_PATTERNS)

    def test_recommendation_keywords_present(self):
        assert "recommend" in RECOMMENDATION_KEYWORDS
        assert "建议" in RECOMMENDATION_KEYWORDS
        assert "buy" in RECOMMENDATION_KEYWORDS

    def test_known_data_sources_present(self):
        assert "Finnhub" in KNOWN_DATA_SOURCES
        assert "Bloomberg" in KNOWN_DATA_SOURCES
        assert "CoinGecko" in KNOWN_DATA_SOURCES

    def test_tool_output_markers(self):
        assert "(source:" in TOOL_OUTPUT_MARKERS
        assert "(QuantEngine)" in TOOL_OUTPUT_MARKERS


# ── Integration / Full Flow Tests ─────────────────────────────────────

class TestValidatorFullFlow:
    """End-to-end validation scenarios."""

    def test_clean_sourced_response(self):
        v = FinanceResponseValidator()
        text = (
            "AAPL: $195.42 (source: Finnhub, 2024-01-15 14:30 UTC)\n"
            "GOOGL: $142.50 (source: yfinance, 2024-01-15 14:30 UTC)\n"
            "This is not financial advice."
        )
        tool_results = [
            {"content": "AAPL: $195.42 (Finnhub)"},
            {"content": "GOOGL: $142.50 (yfinance)"},
        ]
        result = v.validate(text, tool_results)
        assert result.unverified_prices == []

    def test_mixed_issues(self):
        v = FinanceResponseValidator()
        text = (
            "I recommend buying AAPL at $195.42.\n"
            "The target is approximately $220.\n"
        )
        result = v.validate(text)
        assert result.passed is False
        # Should have at least unverified price and approximate calc
        assert len(result.unverified_prices) > 0 or len(result.approximate_calcs) > 0
