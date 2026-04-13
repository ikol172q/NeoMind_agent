# agent/finance/response_validator.py
"""
Finance Response Validator — enforces the Five Iron Rules.

Intercepts every LLM response in `fin` mode and validates:
  Rule 1: No financial numbers from LLM memory (must come from tool calls)
  Rule 2: No approximate calculations (must go through QuantEngine)
  Rule 3: Every data point has source + timestamp
  Rule 4: Recommendations need confidence + time horizon + scenarios
  Rule 5: Source conflicts are shown, never silently resolved

See: plans/FINANCE_CORRECTNESS_RULES.md
"""

import re
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any, Set, Tuple


# ── Result Types ─────────────────────────────────────────────────────

@dataclass
class ValidationResult:
    """Outcome of a single validation pass."""
    passed: bool
    warnings: List[str] = field(default_factory=list)
    blocked: bool = False
    reason: str = ""
    action: str = ""  # "re_route_to_tool", "add_disclaimer", "add_source", ""
    unverified_prices: List[str] = field(default_factory=list)
    approximate_calcs: List[str] = field(default_factory=list)
    unsourced_data: List[str] = field(default_factory=list)
    missing_time_horizons: bool = False
    missing_confidence: bool = False
    missing_disclaimer: bool = False

    def summary(self) -> str:
        if self.passed and not self.warnings:
            return ""
        parts = []
        if self.unverified_prices:
            parts.append(f"⚠️ 未验证价格: {', '.join(self.unverified_prices)}")
        if self.approximate_calcs:
            parts.append(f"⚠️ 近似计算: {', '.join(self.approximate_calcs)}")
        if self.unsourced_data:
            parts.append(f"⚠️ 缺少数据源: {', '.join(self.unsourced_data)}")
        if self.missing_time_horizons:
            parts.append(f"⚠️ 建议包含时间框架 (Rule 4)")
        if self.missing_confidence:
            parts.append(f"⚠️ 建议包含置信度 (Rule 4)")
        if self.missing_disclaimer:
            parts.append(f"⚠️ 建议包含免责声明 (Rule 4)")
        if self.warnings:
            parts.extend(f"⚠️ {w}" for w in self.warnings)
        return "\n".join(parts)


# ── Price Extraction ─────────────────────────────────────────────────

# Patterns for financial prices/amounts
PRICE_PATTERNS = [
    re.compile(r'\$[\d,]+\.?\d*'),              # $195.42
    re.compile(r'¥[\d,]+\.?\d*'),               # ¥1,234.56
    re.compile(r'HK\$[\d,]+\.?\d*'),            # HK$85.20
    re.compile(r'€[\d,]+\.?\d*'),               # €123.45
    re.compile(r'£[\d,]+\.?\d*'),               # £99.00
    re.compile(r'[\d,]+\.?\d*\s*(?:USD|CNY|HKD|BTC|ETH|EUR|GBP|JPY)(?:\b)'),
]

# Patterns that indicate approximate (non-computed) math
MATH_TRIGGER_PATTERNS = [
    re.compile(r'(?:approximately|about|roughly|around|circa)\s+[\$¥€£][\d,]+', re.IGNORECASE),
    re.compile(r'~[\$¥€£][\d,]+'),              # ~$76,000
    re.compile(r'(?:大约|大概|约|差不多)\s*[\$¥€£]?[\d,]+', re.IGNORECASE),  # Chinese approx
]

# Patterns that indicate sourced data (Rule 3 compliance)
SOURCE_PATTERNS = [
    re.compile(r'\(source:\s*\w+', re.IGNORECASE),
    re.compile(r'\((?:Finnhub|CoinGecko|yfinance|AKShare|Binance|Reuters|Bloomberg)', re.IGNORECASE),
    re.compile(r'(?:数据来源|来源)[：:]\s*\w+', re.IGNORECASE),
    re.compile(r'\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}\s*(?:UTC|CST|EST|PST)', re.IGNORECASE),
]

# Patterns to exclude from price validation (these are not market data)
PRICE_EXCLUDE_PATTERNS = [
    re.compile(r'(?:fee|cost|commission|手续费|佣金)\s*(?:is|of|为|：)\s*[\$¥]', re.IGNORECASE),
    re.compile(r'(?:minimum|maximum|min|max)\s*[\$¥]', re.IGNORECASE),
    # Example/hypothetical prices in explanations
    re.compile(r'(?:example|e\.g\.|for instance|假设|例如|比如)', re.IGNORECASE),
]

# Known safe patterns (tool output markers)
TOOL_OUTPUT_MARKERS = [
    "(source:",
    "(Finnhub,",
    "(CoinGecko,",
    "(yfinance,",
    "(AKShare,",
    "(Binance,",
    "(computed)",
    "(QuantEngine)",
    "data_type:",
    "freshness:",
]

# Rule 4: Recommendation detection patterns
RECOMMENDATION_KEYWORDS = [
    "recommend", "建议", "suggest", "suggestion",
    "看好", "看空", "bullish", "bearish",
    "buy", "sell", "strong buy", "strong sell",
    "outperform", "underperform", "overweight", "underweight",
    "should", "ought to", "would be wise",
]

# Time horizon keywords
TIME_HORIZON_KEYWORDS = [
    "short", "medium", "long", "term",  # English
    "短期", "中期", "长期", "期限",     # Chinese
    "3 months", "6 months", "12 months", "1 year", "5 years",
    "3个月", "6个月", "12个月", "1年", "5年",
]

# Confidence level patterns
CONFIDENCE_PATTERNS = [
    re.compile(r'(\d+)%\s*(?:confident|confidence)', re.IGNORECASE),
    re.compile(r'(very|fairly|somewhat|quite|highly)\s*(confident|likely|probable)', re.IGNORECASE),
    re.compile(r'置信度|把握|信心', re.IGNORECASE),
    re.compile(r'(\d+)%', re.IGNORECASE),  # Any percentage as confidence indicator
]

# Disclaimer patterns
DISCLAIMER_PATTERNS = [
    re.compile(r'not\s+(?:financial|investment)\s+advice', re.IGNORECASE),
    re.compile(r'(?:financial|investment)\s+advice\s+disclaimer', re.IGNORECASE),
    re.compile(r'非投资建议|仅供参考|免责声明', re.IGNORECASE),
    re.compile(r'informational\s+purposes?\s+(?:only|alone)', re.IGNORECASE),
    re.compile(r'do\s+your\s+own\s+research|DYOR', re.IGNORECASE),
]

# Rule 5: Known data sources that might conflict
KNOWN_DATA_SOURCES = [
    "Finnhub", "Reuters", "Bloomberg", "CoinGecko", "Binance",
    "yfinance", "AKShare", "Investing.com", "财新", "证券时报",
    "新华网", "FX678", "TokenTerminal", "Glassnode",
]


def _extract_prices(text: str) -> List[str]:
    """Extract all financial price/amount strings from text."""
    prices = []
    for pat in PRICE_PATTERNS:
        prices.extend(pat.findall(text))
    return prices


def _extract_prices_from_tool_results(tool_results: List[Dict]) -> Set[str]:
    """Extract price strings that appeared in tool call results."""
    tool_prices = set()
    for result in tool_results:
        content = str(result.get("content", "") or result.get("output", ""))
        for pat in PRICE_PATTERNS:
            for match in pat.findall(content):
                # Normalize: strip whitespace, keep raw form
                tool_prices.add(match.strip())
    return tool_prices


def _normalize_price(price_str: str) -> str:
    """Normalize a price string for comparison (remove commas, whitespace)."""
    return re.sub(r'[,\s]', '', price_str)


def _line_has_source(text: str, price: str) -> bool:
    """Check if the line containing this price also has source attribution."""
    # Find the line containing the price
    for line in text.split('\n'):
        if price in line:
            for marker in TOOL_OUTPUT_MARKERS:
                if marker in line:
                    return True
            for pat in SOURCE_PATTERNS:
                if pat.search(line):
                    return True
    return False


def _is_in_excluded_context(text: str, price: str) -> bool:
    """Check if price appears in an excluded context (examples, fees, etc)."""
    for line in text.split('\n'):
        if price in line:
            for pat in PRICE_EXCLUDE_PATTERNS:
                if pat.search(line):
                    return True
    return False


# ── Main Validator ───────────────────────────────────────────────────

class FinanceResponseValidator:
    """
    Validates every LLM response in fin mode against the Five Iron Rules.

    Usage:
        validator = FinanceResponseValidator()
        result = validator.validate(response_text, tool_results_this_turn)
        if not result.passed:
            # Handle: append disclaimer, re-route, or warn
    """

    def __init__(self, strict: bool = False):
        """
        Args:
            strict: If True, block responses with unverified data.
                    If False (default), add warnings but allow through.
        """
        self.strict = strict

    def validate_agent_analysis(
        self,
        analysis,  # AgentAnalysis — imported lazily to avoid a hard dep
        tool_results: Optional[List[Dict]] = None,
    ) -> "ValidationResult":
        """Structural validation for a parsed ``AgentAnalysis``.

        Runs on top of Pydantic (which already enforces types + enums +
        confidence bounds) to catch semantic issues Pydantic can't:

          - ``buy`` or ``sell`` signals must cite at least one source.
          - High-confidence signals (>=8) with zero sources are suspicious.
          - The ``reason`` field is re-run through the free-text validator
            (Rules 1 / 2 / 3) against ``tool_results`` to catch hallucinated
            prices or approximate math inside the rationale.
          - ``target_price`` with ``signal == 'hold'`` is flagged as
            mixed-message but not blocked.

        Args:
            analysis: Parsed ``AgentAnalysis`` instance.
            tool_results: Tool outputs from this turn (same shape as
                ``validate()``).

        Returns:
            ``ValidationResult`` — ``passed=False`` if any structural
            constraint fails, plus any free-text rule violations found in
            ``analysis.reason``.
        """
        # Lazy import to avoid a required dep from validator -> schema
        from .signal_schema import AgentAnalysis

        if not isinstance(analysis, AgentAnalysis):
            return ValidationResult(
                passed=False,
                blocked=True,
                reason=(
                    f"validate_agent_analysis requires an AgentAnalysis "
                    f"instance, got {type(analysis).__name__}"
                ),
            )

        # First: free-text rule sweep on the reason field
        result = self.validate(analysis.reason, tool_results=tool_results)

        # Structural checks layered on top
        if analysis.signal in ("buy", "sell") and not analysis.sources:
            result.passed = False
            result.warnings.append(
                f"signal={analysis.signal!r} but sources list is empty — "
                f"actionable signals must cite data sources (Rule 3)."
            )
            if self.strict:
                result.blocked = True
                result.action = "add_sources"
                result.reason = "non-hold signal with empty sources"

        if analysis.confidence >= 8 and not analysis.sources:
            result.warnings.append(
                f"confidence={analysis.confidence} with zero sources — "
                f"high conviction requires evidence."
            )

        if analysis.signal == "hold" and analysis.target_price is not None:
            result.warnings.append(
                f"signal='hold' paired with target_price={analysis.target_price} "
                f"sends a mixed message; omit target on hold or switch signal."
            )

        # Non-hold parse_fallback reasons are an operational smell
        if analysis.reason.startswith("[parse_fallback]"):
            result.warnings.append(
                "reason carries [parse_fallback] marker — upstream LLM output "
                "failed strict+lenient parse layers. Investigate prompt drift."
            )

        return result

    def validate(
        self,
        response: str,
        tool_results: Optional[List[Dict]] = None,
    ) -> ValidationResult:
        """Run all five rule checks on a response.

        Args:
            response: The LLM's response text.
            tool_results: List of tool call results from this turn.
                          Each dict should have 'content' or 'output' key.

        Returns:
            ValidationResult with pass/fail and details.
        """
        tool_results = tool_results or []
        result = ValidationResult(passed=True)

        # Rule 1: No unverified financial numbers
        self._check_unverified_prices(response, tool_results, result)

        # Rule 2: No approximate calculations
        self._check_approximate_math(response, result)

        # Rule 3: Source attribution (only if prices exist)
        self._check_source_attribution(response, result)

        # Rule 4: Recommendation quality checks
        self._check_time_horizons(response, result)
        self._check_confidence(response, result)
        self._check_disclaimer(response, result)

        # Rule 5: Source conflict visibility
        self._check_conflicts_shown(response, result)

        # Determine overall pass/fail
        if result.unverified_prices or result.approximate_calcs:
            result.passed = False
            if self.strict:
                result.blocked = True
                result.action = "re_route_to_tool"
                result.reason = (
                    f"Response blocked: contains unverified data. "
                    f"{result.summary()}"
                )
            else:
                result.action = "add_disclaimer"

        return result

    def _check_unverified_prices(
        self,
        response: str,
        tool_results: List[Dict],
        result: ValidationResult,
    ):
        """Rule 1: Every price must originate from a tool call."""
        prices_in_response = _extract_prices(response)
        if not prices_in_response:
            return

        tool_prices = _extract_prices_from_tool_results(tool_results)
        # Also consider prices from the response that have source markers
        # (these were rendered by VerifiedDataPoint.render())

        for price in prices_in_response:
            # Skip if in excluded context (examples, fees)
            if _is_in_excluded_context(response, price):
                continue

            # Check if this price came from tool output
            normalized = _normalize_price(price)
            tool_match = any(
                _normalize_price(tp) == normalized or normalized in _normalize_price(tp)
                for tp in tool_prices
            )

            if not tool_match:
                # Maybe the line has source attribution (from VerifiedDataPoint)
                if _line_has_source(response, price):
                    continue
                result.unverified_prices.append(price)

    def _check_approximate_math(self, response: str, result: ValidationResult):
        """Rule 2: No approximate calculations — must use QuantEngine."""
        for pattern in MATH_TRIGGER_PATTERNS:
            matches = pattern.findall(response)
            for match in matches:
                # Skip if it's clearly a computed result
                if "(computed)" in response or "(QuantEngine)" in response:
                    continue
                result.approximate_calcs.append(match)

    def _check_source_attribution(self, response: str, result: ValidationResult):
        """Rule 3: Prices should have source + timestamp."""
        prices = _extract_prices(response)
        if not prices:
            return

        for price in prices:
            if _is_in_excluded_context(response, price):
                continue
            if not _line_has_source(response, price):
                result.unsourced_data.append(price)
                if price not in result.unverified_prices:
                    result.warnings.append(
                        f"价格 {price} 缺少来源标注 (Rule 3)"
                    )

    def _is_recommendation(self, response: str) -> bool:
        """Check if response contains recommendation keywords."""
        response_lower = response.lower()
        for keyword in RECOMMENDATION_KEYWORDS:
            if keyword in response_lower:
                return True
        return False

    def _check_time_horizons(self, response: str, result: ValidationResult):
        """Rule 4a: Recommendations should mention at least 2 of 3 time horizons."""
        if not self._is_recommendation(response):
            return

        # Look for time horizon mentions
        horizons_found = 0
        response_lower = response.lower()

        # Check for short-term indicators
        if any(x in response_lower for x in ["short term", "short-term", "短期", "3 month", "3个月"]):
            horizons_found += 1

        # Check for medium-term indicators
        if any(x in response_lower for x in ["medium term", "medium-term", "中期", "6 month", "6个月"]):
            horizons_found += 1

        # Check for long-term indicators
        if any(x in response_lower for x in ["long term", "long-term", "长期", "1 year", "5 year", "1年", "5年"]):
            horizons_found += 1

        if horizons_found < 2:
            result.missing_time_horizons = True
            result.warnings.append(
                "建议包含至少2个时间框架 (短/中/长期) 以支持推荐意见 (Rule 4a)"
            )

    def _check_confidence(self, response: str, result: ValidationResult):
        """Rule 4b: Recommendations should include confidence level."""
        if not self._is_recommendation(response):
            return

        for pattern in CONFIDENCE_PATTERNS:
            if pattern.search(response):
                return  # Found confidence indicator

        result.missing_confidence = True
        result.warnings.append(
            "建议包含置信度或把握程度 (如百分比或强度描述) (Rule 4b)"
        )

    def _check_disclaimer(self, response: str, result: ValidationResult):
        """Rule 4c: Recommendations should include a disclaimer."""
        if not self._is_recommendation(response):
            return

        for pattern in DISCLAIMER_PATTERNS:
            if pattern.search(response):
                return  # Found disclaimer

        result.missing_disclaimer = True
        result.warnings.append(
            "建议包含免责声明 (如'非投资建议'或'仅供参考') (Rule 4c)"
        )

    def _check_conflicts_shown(self, response: str, result: ValidationResult):
        """Rule 5: When sources mention different numbers, both must be shown."""
        # Find all data source mentions
        sources_found = {}
        for source in KNOWN_DATA_SOURCES:
            if source.lower() in response.lower():
                if source not in sources_found:
                    sources_found[source] = []

        if len(sources_found) < 2:
            return  # Only one or no sources, no conflict to worry about

        # Look for patterns where different sources give different values
        # This is a heuristic check for explicit conflict statements
        conflict_indicators = [
            "however", "but", "on the other hand", "in contrast",
            "different", "differ", "conflict", "disagree",
            "however", "而", "但", "对比", "不同",
        ]

        response_lower = response.lower()
        for indicator in conflict_indicators:
            if indicator in response_lower:
                # Check if multiple sources mentioned in proximity
                lines = response.split('\n')
                for line in lines:
                    line_lower = line.lower()
                    sources_in_line = sum(1 for src in sources_found if src.lower() in line_lower)
                    if sources_in_line >= 2 and any(ind in line_lower for ind in conflict_indicators):
                        return  # Conflict is clearly shown

        # If we have multiple sources but no clear conflict exposition,
        # add a warning if we detect potential data points
        if len(sources_found) >= 2:
            numbers = _extract_prices(response)
            if len(numbers) >= 2:
                result.warnings.append(
                    f"检测到多个数据源 ({', '.join(sources_found.keys())}) 和多个数值。"
                    f"请确保明确显示任何数据冲突而非隐瞒 (Rule 5)"
                )

    def build_disclaimer(self, result: ValidationResult) -> str:
        """Build a disclaimer string to append to the response.

        Called when strict=False and validation found issues.
        """
        parts = ["\n\n---", "⚠️ **数据验证提醒 / Data Validation Notice:**"]

        if result.unverified_prices:
            parts.append(
                f"- 以下价格未经数据源验证，可能来自模型记忆: "
                f"{', '.join(result.unverified_prices)}。"
                f"建议使用 `/price <ticker>` 获取实时数据。"
            )

        if result.approximate_calcs:
            parts.append(
                f"- 以下计算为近似值: {', '.join(result.approximate_calcs)}。"
                f"建议使用 `/calc` 获取精确结果。"
            )

        if result.unsourced_data:
            parts.append(
                f"- 部分数据缺少来源标注。所有金融数据应包含 "
                f"(source, timestamp, freshness)。"
            )

        if result.missing_time_horizons:
            parts.append(
                "- [Rule 4a] 投资建议应包含多个时间框架（短期/中期/长期）"
                "以便投资者根据自己的目标选择。"
            )

        if result.missing_confidence:
            parts.append(
                "- [Rule 4b] 投资建议应包含置信度或把握程度，"
                "帮助用户评估建议的可靠性。"
            )

        if result.missing_disclaimer:
            parts.append(
                "- [Rule 4c] 投资建议应包含免责声明（如'非投资建议'或'仅供参考'），"
                "以确保用户了解风险和局限性。"
            )

        return "\n".join(parts)


# ── Convenience singleton ────────────────────────────────────────────

_validator: Optional[FinanceResponseValidator] = None


def get_finance_validator(strict: bool = False) -> FinanceResponseValidator:
    """Get or create the singleton validator."""
    global _validator
    if _validator is None:
        _validator = FinanceResponseValidator(strict=strict)
    return _validator
