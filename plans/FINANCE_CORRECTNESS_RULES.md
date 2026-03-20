# Finance Personality — Correctness Rules & Validation Framework

**Date:** 2026-03-17
**Priority:** HIGHEST — This document defines the non-negotiable rules for financial correctness.

**Core Principle:** When it comes to money, being wrong is worse than being slow. Every piece of data must be verified, every calculation must be computed (never guessed), and every recommendation must be grounded in evidence.

---

## 1. The Five Iron Rules

These rules are absolute. No exception. No shortcut.

### Rule 1: NEVER Output a Number From LLM Memory

```
WRONG:  User asks "What's AAPL at?" → LLM responds "$178.50" from training data
RIGHT:  User asks "What's AAPL at?" → Tool call to Finnhub → "$195.42 (Finnhub, 2026-03-17 14:32 UTC)"
```

**Implementation:** A pre-response validator intercepts every response in `fin` mode. If the response contains a dollar/yuan/price figure that did NOT originate from a tool call in that turn, the response is BLOCKED and re-routed through the appropriate data tool.

```python
class FinanceResponseValidator:
    """
    Intercepts every response before it reaches the user.
    Blocks any financial data not sourced from a tool call.
    """

    PRICE_PATTERNS = [
        r'\$[\d,]+\.?\d*',           # $195.42
        r'¥[\d,]+\.?\d*',            # ¥1,234.56
        r'HK\$[\d,]+\.?\d*',         # HK$85.20
        r'[\d,]+\.?\d*\s*(USD|CNY|HKD|BTC|ETH)',  # 195.42 USD
    ]

    def validate(self, response: str, tool_calls_this_turn: list) -> ValidationResult:
        """
        Check if response contains financial data.
        If yes, verify it came from a tool call.
        If no tool call → BLOCK.
        """
        prices_in_response = self._extract_prices(response)
        prices_from_tools = self._extract_prices_from_tool_results(tool_calls_this_turn)

        unverified = []
        for price in prices_in_response:
            if not self._price_matches_tool_output(price, prices_from_tools):
                unverified.append(price)

        if unverified:
            return ValidationResult(
                passed=False,
                reason=f"Response contains unverified prices: {unverified}. "
                       f"Re-routing through data tools.",
                action="re_route_to_tool"
            )

        return ValidationResult(passed=True)
```

### Rule 2: EVERY Calculation Goes Through QuantEngine

```
WRONG:  LLM says "Your $10,000 at 7% for 30 years becomes about $76,000"
RIGHT:  QuantEngine.compound_return(10000, 0.07, 30) = $76,122.55
        Response: "Your $10,000 at 7% annual for 30 years = $76,122.55 (computed)"
```

**Implementation:** System prompt FORBIDS inline math. All math expressions are detected and routed to QuantEngine.

```python
class MathInterceptor:
    """
    Detects when LLM is about to do mental math.
    Forces computation through QuantEngine.
    """

    MATH_TRIGGERS = [
        r'approximately \$[\d,]+',   # "approximately $76,000"
        r'about \$[\d,]+',           # "about $76,000"
        r'roughly \$[\d,]+',         # "roughly $76,000"
        r'around \$[\d,]+',          # "around $76,000"
        r'~\$[\d,]+',               # "~$76,000"
        r'results? in \$[\d,]+',     # "results in $76,000"
    ]

    def check(self, response: str) -> bool:
        """Returns True if response contains approximate calculations."""
        for pattern in self.MATH_TRIGGERS:
            if re.search(pattern, response):
                return True
        return False
```

### Rule 3: EVERY Data Point Has Source + Timestamp

```
WRONG:  "AAPL is trading at $195.42"
RIGHT:  "AAPL: $195.42 (source: Finnhub, as of 2026-03-17 14:32 UTC, 15-min delayed)"
```

**Implementation:** Data objects carry provenance metadata that is ALWAYS rendered.

```python
@dataclass
class VerifiedDataPoint:
    """Every piece of financial data must carry this metadata."""
    value: Any                    # the actual data
    source: str                   # "finnhub", "coingecko", "reuters", etc.
    timestamp: datetime           # when the data was fetched
    freshness: str               # "real-time", "15-min delayed", "daily close", "cached 5m"
    confidence: float            # 0.0 to 1.0
    data_type: str               # "fact", "estimate", "opinion"

    def render(self) -> str:
        """Human-readable with full provenance."""
        delay_note = f", {self.freshness}" if self.freshness != "real-time" else ""
        return (f"{self.value} "
                f"(source: {self.source}, "
                f"as of {self.timestamp.strftime('%Y-%m-%d %H:%M UTC')}"
                f"{delay_note})")
```

### Rule 4: EVERY Recommendation Has Confidence + Time Horizon + Scenarios

```
WRONG:  "I think you should buy AAPL"
RIGHT:  "Analysis suggests bullish case for AAPL:

         SHORT TERM (1-4 weeks): Neutral to slightly bullish
           Bull case: $200 (+2.4%) — strong earnings momentum. Prob: 55%
           Bear case: $185 (-5.3%) — broader market pullback. Prob: 30%
           Base case: $192-198 range-bound. Prob: 45%
           Expected value: +0.8%

         MEDIUM TERM (1-6 months): Bullish
           Bull case: $230 (+17.7%) — AI revenue acceleration. Prob: 40%
           Bear case: $165 (-15.6%) — recession fears. Prob: 20%
           Base case: $205-215 gradual climb. Prob: 40%
           Expected value: +6.2%

         LONG TERM (6-12 months): Moderately bullish
           Depends heavily on: Fed rate path, AI capex cycle, iPhone cycle
           Confidence: 55% (uncertain — too many macro variables)

         Sources: [Finnhub earnings data, Reuters analysis, 财新 macro outlook]
         ⚠️ This is analysis, not financial advice."
```

### Rule 5: CONFLICTS Are ALWAYS Shown, NEVER Resolved Silently

```
WRONG:  Agent picks Reuters over 财新 and shows only Reuters view.
RIGHT:  "⚠️ CONFLICTING REPORTS on Fed rate decision:

         📰 Reuters (trust: 0.90): 'Fed signals rate pause through Q3'
            Source: reuters.com/fed-decision-march2026, 2026-03-17
         📰 财新 (trust: 0.85): 'Market expects Fed to cut 25bp in June'
            Source: caixin.com/finance/2026-03-17/macro

         MY INFERENCE: Reuters is reporting the official statement (pause),
         while 财新 is reporting market expectations (futures pricing in cut).
         Both can be simultaneously true. The Fed said pause, but markets
         don't believe them. Watch CME FedWatch tool for probability.

         Confidence in inference: 72%"
```

---

## 2. Data Validation Pipeline

Every piece of data flows through this pipeline before reaching the user:

```
                    ┌──────────────┐
                    │  Raw Data    │ ← from API/search/RSS
                    └──────┬───────┘
                           │
                    ┌──────▼───────┐
                    │  Source Check │ Is the source known and trusted?
                    │              │ If unknown: trust = 0.5, flag it
                    └──────┬───────┘
                           │
                    ┌──────▼───────┐
                    │  Freshness   │ How old is this data?
                    │  Check       │ If stale: label it clearly
                    └──────┬───────┘
                           │
                    ┌──────▼───────┐
                    │  Sanity      │ Does this make sense?
                    │  Check       │ AAPL at $5? → probably wrong
                    └──────┬───────┘
                           │
                    ┌──────▼───────┐
                    │  Cross-Ref   │ Do multiple sources agree?
                    │  Check       │ If conflict → flag it
                    └──────┬───────┘
                           │
                    ┌──────▼───────┐
                    │  Provenance  │ Attach source + timestamp
                    │  Tag         │ MANDATORY for every data point
                    └──────┬───────┘
                           │
                    ┌──────▼───────┐
                    │  User Output │ Rendered with full attribution
                    └──────────────┘
```

**Sanity check examples:**

```python
class DataSanityChecker:
    """
    Catches obviously wrong data before it reaches the user.
    """

    def check_stock_price(self, symbol, price, market="us"):
        """
        Reject clearly wrong prices.
        Uses last known price as anchor (from memory).
        """
        last_known = self.memory.get_last_price(symbol)
        if last_known:
            change_pct = abs(price - last_known) / last_known * 100

            # >50% change in one fetch → almost certainly wrong data
            if change_pct > 50:
                return SanityResult(
                    passed=False,
                    reason=f"{symbol} price changed {change_pct:.1f}% "
                           f"({last_known} → {price}). Likely data error. "
                           f"Fetching from secondary source.",
                    action="re_fetch_from_fallback"
                )

            # >20% change → unusual, flag but allow
            if change_pct > 20:
                return SanityResult(
                    passed=True,
                    warning=f"⚠️ {symbol} moved {change_pct:.1f}% since last check. "
                            f"Verify this is correct."
                )

        return SanityResult(passed=True)

    def check_crypto_price(self, coin_id, price):
        """Crypto is more volatile, wider sanity bounds."""
        last_known = self.memory.get_last_price(coin_id)
        if last_known:
            change_pct = abs(price - last_known) / last_known * 100
            if change_pct > 80:  # Wider for crypto
                return SanityResult(passed=False, reason="Extreme change", action="re_fetch")
        return SanityResult(passed=True)
```

---

## 3. Comprehensive Unit Test Plan

### 3.1 QuantEngine Tests — Mathematical Correctness

Every formula must match known, independently verified answers.

```python
# tests/test_quant_engine.py

class TestCompoundReturn:
    """All expected values computed independently with WolframAlpha."""

    def test_basic_compound(self):
        """$10,000 at 7% for 30 years = $76,122.55"""
        result = quant.compound_return(10000, 0.07, 30)
        assert abs(result - 76122.55) < 0.01

    def test_with_monthly_contributions(self):
        """$10,000 initial + $500/month at 7% for 30 years = $606,438.34"""
        result = quant.compound_return(10000, 0.07, 30, monthly_contribution=500)
        assert abs(result - 606438.34) < 1.00  # ±$1 tolerance

    def test_zero_rate(self):
        """0% return = principal unchanged"""
        result = quant.compound_return(10000, 0.0, 30)
        assert result == 10000.0

    def test_negative_rate(self):
        """Negative returns reduce principal"""
        result = quant.compound_return(10000, -0.05, 10)
        assert result < 10000.0
        assert abs(result - 5987.37) < 0.01

    def test_one_period(self):
        """Single period = simple return"""
        result = quant.compound_return(10000, 0.10, 1)
        assert abs(result - 11000.0) < 0.01


class TestBlackScholes:
    """Test cases from Hull's 'Options, Futures & Other Derivatives'"""

    def test_call_option_basic(self):
        """Known case: S=42, K=40, T=0.5, r=0.1, σ=0.2 → C≈4.76"""
        result = quant.option_pricing(S=42, K=40, T=0.5, r=0.1, sigma=0.2, option_type="call")
        assert abs(result.price - 4.76) < 0.02

    def test_put_option_basic(self):
        """Put-call parity: P = C - S + K*exp(-rT)"""
        call = quant.option_pricing(S=42, K=40, T=0.5, r=0.1, sigma=0.2, option_type="call")
        put = quant.option_pricing(S=42, K=40, T=0.5, r=0.1, sigma=0.2, option_type="put")
        # Put-call parity
        parity_put = call.price - 42 + 40 * math.exp(-0.1 * 0.5)
        assert abs(put.price - parity_put) < 0.01

    def test_deep_in_the_money_call(self):
        """Deep ITM call ≈ S - K*exp(-rT)"""
        result = quant.option_pricing(S=100, K=50, T=1.0, r=0.05, sigma=0.2, option_type="call")
        intrinsic = 100 - 50 * math.exp(-0.05)
        assert result.price >= intrinsic  # Must be ≥ intrinsic value

    def test_deep_out_of_money_put(self):
        """Deep OTM put ≈ 0"""
        result = quant.option_pricing(S=100, K=20, T=0.25, r=0.05, sigma=0.2, option_type="put")
        assert result.price < 0.01

    def test_at_the_money(self):
        """ATM: call and put prices should be roughly equal (at low rates)"""
        call = quant.option_pricing(S=100, K=100, T=1.0, r=0.01, sigma=0.2, option_type="call")
        put = quant.option_pricing(S=100, K=100, T=1.0, r=0.01, sigma=0.2, option_type="put")
        assert abs(call.price - put.price) < 1.0  # Close but not identical due to r

    def test_greeks_sum(self):
        """Delta of call + delta of put = 1 (approximately)"""
        call = quant.option_pricing(S=100, K=100, T=1.0, r=0.05, sigma=0.2, option_type="call")
        put = quant.option_pricing(S=100, K=100, T=1.0, r=0.05, sigma=0.2, option_type="put")
        # call_delta - put_delta = exp(-r*T) ≈ 1
        assert abs(call.delta - put.delta - math.exp(-0.05)) < 0.01


class TestScenarioAnalysis:
    """Expected value calculations must be exact."""

    def test_simple_scenarios(self):
        """
        Bull: +20% prob 0.4
        Base: +5%  prob 0.4
        Bear: -15% prob 0.2
        EV = 0.4*20 + 0.4*5 + 0.2*(-15) = 8 + 2 + (-3) = 7.0%
        """
        result = quant.scenario_analysis([
            {"probability": 0.4, "outcome": 20},
            {"probability": 0.4, "outcome": 5},
            {"probability": 0.2, "outcome": -15},
        ])
        assert abs(result.expected_value - 7.0) < 0.001

    def test_probabilities_must_sum_to_one(self):
        """Reject scenarios where probabilities don't sum to ~1.0"""
        with pytest.raises(ValueError, match="probabilities must sum to 1.0"):
            quant.scenario_analysis([
                {"probability": 0.5, "outcome": 10},
                {"probability": 0.3, "outcome": -5},
            ])

    def test_variance_calculation(self):
        """Variance = Σ p_i * (x_i - EV)²"""
        result = quant.scenario_analysis([
            {"probability": 0.5, "outcome": 10},
            {"probability": 0.5, "outcome": -10},
        ])
        assert abs(result.expected_value - 0.0) < 0.001
        assert abs(result.variance - 100.0) < 0.001  # 0.5*(10-0)² + 0.5*(-10-0)²


class TestDCFValuation:
    """Discounted Cash Flow must match textbook examples."""

    def test_simple_dcf(self):
        """
        Cash flows: [100, 110, 121] discount rate 10%, terminal growth 3%
        PV = 100/1.1 + 110/1.21 + 121/1.331 + terminal_value/1.331
        Terminal = 121*1.03/(0.10-0.03) = 1781.86
        TV_PV = 1781.86/1.331 = 1338.73
        Total ≈ 90.91 + 90.91 + 90.88 + 1338.73 = 1611.43
        """
        result = quant.dcf_valuation(
            cash_flows=[100, 110, 121],
            discount_rate=0.10,
            terminal_growth=0.03
        )
        assert abs(result.intrinsic_value - 1611.43) < 1.0

    def test_terminal_growth_exceeds_discount_rate(self):
        """Should raise error — growth > discount rate is impossible long-term"""
        with pytest.raises(ValueError, match="terminal growth.*exceed.*discount"):
            quant.dcf_valuation(
                cash_flows=[100],
                discount_rate=0.05,
                terminal_growth=0.08
            )


class TestPortfolioRisk:
    """Risk calculations with known textbook answers."""

    def test_sharpe_ratio(self):
        """
        Portfolio return: 12%, risk-free: 3%, std dev: 15%
        Sharpe = (12-3)/15 = 0.6
        """
        result = quant.sharpe_ratio(
            portfolio_return=0.12,
            risk_free_rate=0.03,
            std_deviation=0.15
        )
        assert abs(result - 0.6) < 0.001

    def test_var_95(self):
        """
        Portfolio: $100K, mean return: 10%, std: 20%
        VaR(95%) = 100000 * (0.10 - 1.645 * 0.20) = -$22,900
        """
        result = quant.value_at_risk(
            portfolio_value=100000,
            mean_return=0.10,
            std_deviation=0.20,
            confidence=0.95
        )
        assert abs(result - (-22900)) < 100
```

### 3.2 Data Validation Tests

```python
# tests/test_data_validation.py

class TestFinanceResponseValidator:
    """Ensure no unverified financial data reaches the user."""

    def test_blocks_hallucinated_price(self):
        """Response with price but no tool call → BLOCKED."""
        validator = FinanceResponseValidator()
        result = validator.validate(
            response="AAPL is currently trading at $195.42",
            tool_calls_this_turn=[]
        )
        assert result.passed is False
        assert result.action == "re_route_to_tool"

    def test_allows_tool_sourced_price(self):
        """Response with price FROM a tool call → ALLOWED."""
        validator = FinanceResponseValidator()
        result = validator.validate(
            response="AAPL: $195.42 (source: Finnhub, 2026-03-17 14:32 UTC)",
            tool_calls_this_turn=[
                ToolResult(tool="finnhub_quote", output={"price": 195.42})
            ]
        )
        assert result.passed is True

    def test_blocks_approximate_calculation(self):
        """Response with 'approximately' + number → BLOCKED for QuantEngine."""
        interceptor = MathInterceptor()
        assert interceptor.check("That gives you approximately $76,000") is True
        assert interceptor.check("The result is $76,122.55 (computed)") is False

    def test_cny_price_detected(self):
        """Chinese yuan prices also caught."""
        validator = FinanceResponseValidator()
        result = validator.validate(
            response="贵州茅台当前价格 ¥1,850.00",
            tool_calls_this_turn=[]
        )
        assert result.passed is False


class TestDataSanityChecker:
    """Catch obviously wrong data."""

    def test_rejects_50pct_stock_move(self):
        """Stock price 50%+ different from last known → reject."""
        checker = DataSanityChecker(mock_memory_with_aapl_at_195)
        result = checker.check_stock_price("AAPL", 95.0)  # 51% drop
        assert result.passed is False

    def test_warns_on_20pct_move(self):
        """Stock price 20%+ change → allow with warning."""
        checker = DataSanityChecker(mock_memory_with_aapl_at_195)
        result = checker.check_stock_price("AAPL", 155.0)  # 20.5% drop
        assert result.passed is True
        assert result.warning is not None

    def test_accepts_normal_move(self):
        """Stock price <5% change → clean pass."""
        checker = DataSanityChecker(mock_memory_with_aapl_at_195)
        result = checker.check_stock_price("AAPL", 192.0)  # 1.5% drop
        assert result.passed is True
        assert result.warning is None

    def test_crypto_wider_bounds(self):
        """Crypto allows larger moves (80% threshold)."""
        checker = DataSanityChecker(mock_memory_with_btc_at_65000)
        result = checker.check_crypto_price("bitcoin", 50000.0)  # 23% drop
        assert result.passed is True  # Crypto is volatile, this is plausible


class TestSourceTimestamp:
    """Every output must carry source + timestamp."""

    def test_verified_data_point_renders_correctly(self):
        dp = VerifiedDataPoint(
            value="$195.42",
            source="Finnhub",
            timestamp=datetime(2026, 3, 17, 14, 32),
            freshness="15-min delayed",
            confidence=0.95,
            data_type="fact"
        )
        rendered = dp.render()
        assert "Finnhub" in rendered
        assert "2026-03-17 14:32 UTC" in rendered
        assert "15-min delayed" in rendered

    def test_missing_timestamp_raises(self):
        """Cannot create data point without timestamp."""
        with pytest.raises(TypeError):
            VerifiedDataPoint(value="$195.42", source="Finnhub")
```

### 3.3 Search Engine Tests

```python
# tests/test_hybrid_search.py

class TestHybridSearch:
    """Search must be reliable, multi-source, and handle failures."""

    @pytest.mark.asyncio
    async def test_basic_en_search(self):
        """English search returns results."""
        engine = HybridSearchEngine(test_config)
        results = await engine.search("AAPL stock price", languages=["en"])
        assert len(results.items) > 0
        assert results.timestamp is not None

    @pytest.mark.asyncio
    async def test_basic_zh_search(self):
        """Chinese search returns results."""
        engine = HybridSearchEngine(test_config)
        results = await engine.search("A股行情", languages=["zh"])
        assert len(results.items) > 0

    @pytest.mark.asyncio
    async def test_ddg_failure_fallback(self):
        """When DDG fails, RSS + Tier 2 still return results."""
        engine = HybridSearchEngine(test_config)
        engine.sources["ddg_en"] = FailingSource()
        engine.sources["ddg_zh"] = FailingSource()
        results = await engine.search("market news")
        assert len(results.items) > 0  # RSS should still work

    @pytest.mark.asyncio
    async def test_all_sources_down(self):
        """When everything fails, return empty with clear error."""
        engine = HybridSearchEngine(test_config)
        for key in engine.sources:
            engine.sources[key] = FailingSource()
        results = await engine.search("anything")
        assert len(results.items) == 0
        assert results.error is not None
        assert "all sources unavailable" in results.error.lower()

    @pytest.mark.asyncio
    async def test_deduplication(self):
        """Same URL from multiple sources → one result."""
        engine = HybridSearchEngine(test_config)
        engine.sources = {
            "src1": MockSource([SearchItem(url="https://example.com/article")]),
            "src2": MockSource([SearchItem(url="https://example.com/article")]),
        }
        results = await engine.search("test")
        urls = [item.url for item in results.items]
        assert len(urls) == len(set(urls))  # No duplicates

    @pytest.mark.asyncio
    async def test_rrf_ranking(self):
        """Higher-ranked items in more sources get higher RRF score."""
        engine = HybridSearchEngine(test_config)
        engine.sources = {
            "src1": MockSource([ItemA_rank1, ItemB_rank2]),
            "src2": MockSource([ItemA_rank1, ItemC_rank2]),
        }
        results = await engine.search("test")
        # ItemA appears #1 in both sources → should be top result
        assert results.items[0].url == ItemA_rank1.url

    @pytest.mark.asyncio
    async def test_conflict_detection(self):
        """Conflicting claims across sources are flagged."""
        engine = HybridSearchEngine(test_config)
        results = await engine.search("Fed rate decision")
        # This is integration-level; mock sources with conflicting headlines
        # to verify conflict detection works


class TestRateLimiter:
    """Rate limiter prevents API abuse."""

    @pytest.mark.asyncio
    async def test_ddg_rate_limit_respected(self):
        """No more than 1 DDG request per 1.5 seconds."""
        limiter = TokenBucketLimiter(rate=1, per=1.5)
        start = time.time()
        for _ in range(3):
            await limiter.acquire()
        elapsed = time.time() - start
        assert elapsed >= 3.0  # 3 requests × 1.5s minimum

    def test_cache_prevents_duplicate_search(self):
        """Same query within TTL → cache hit, no API call."""
        cache = SearchCache(ttl_seconds=1800)
        cache.set("AAPL news", [mock_result])
        result = cache.get("AAPL news")
        assert result is not None
        assert result == [mock_result]
```

### 3.4 Secure Memory Tests

```python
# tests/test_secure_memory.py

class TestSecureMemory:
    """Memory must be encrypted, timestamped, and recoverable."""

    def test_database_is_encrypted(self, tmp_path):
        """Raw database file should not contain readable text."""
        store = SecureMemoryStore(base_path=tmp_path, passphrase="test123")
        store.store_insight("AAPL earnings beat by 15%", symbols=["AAPL"])

        # Read raw bytes
        db_bytes = (tmp_path / "memory.db").read_bytes()
        assert b"AAPL" not in db_bytes  # Should be encrypted
        assert b"earnings" not in db_bytes

    def test_wrong_passphrase_rejected(self, tmp_path):
        """Wrong passphrase → access denied."""
        store = SecureMemoryStore(base_path=tmp_path, passphrase="correct")
        store.store_insight("secret data")
        store.close()

        with pytest.raises(AuthenticationError):
            SecureMemoryStore(base_path=tmp_path, passphrase="wrong")

    def test_timestamps_are_iso8601(self, tmp_path):
        """All timestamps must be ISO 8601 format."""
        store = SecureMemoryStore(base_path=tmp_path, passphrase="test123")
        store.store_insight("test insight")
        insights = store.get_insights(limit=1)
        ts = insights[0].created_at
        # Should parse as ISO 8601
        datetime.fromisoformat(ts)  # Raises if not valid

    def test_data_persists_across_sessions(self, tmp_path):
        """Data survives close and reopen."""
        store1 = SecureMemoryStore(base_path=tmp_path, passphrase="test123")
        store1.store_insight("persistent data", symbols=["MSFT"])
        store1.close()

        store2 = SecureMemoryStore(base_path=tmp_path, passphrase="test123")
        insights = store2.get_insights(symbols=["MSFT"])
        assert len(insights) == 1
        assert "persistent data" in insights[0].content

    def test_directory_permissions(self, tmp_path):
        """Storage directory must be owner-only (700)."""
        store = SecureMemoryStore(base_path=tmp_path / "finance", passphrase="test")
        perms = oct(os.stat(tmp_path / "finance").st_mode)[-3:]
        assert perms == "700"

    def test_backup_creation(self, tmp_path):
        """Daily backup is created."""
        store = SecureMemoryStore(base_path=tmp_path, passphrase="test123")
        store.store_insight("backup test")
        store.create_backup()
        backups = list((tmp_path / "backups").glob("memory_*.db"))
        assert len(backups) >= 1

    def test_corrupt_db_recovery(self, tmp_path):
        """Corrupted database auto-recovers from backup."""
        store = SecureMemoryStore(base_path=tmp_path, passphrase="test123")
        store.store_insight("important data")
        store.create_backup()
        store.close()

        # Corrupt the database
        db_path = tmp_path / "memory.db"
        db_path.write_bytes(b"corrupted garbage data")

        # Should auto-recover from backup
        store2 = SecureMemoryStore(base_path=tmp_path, passphrase="test123")
        insights = store2.get_insights()
        assert len(insights) == 1  # Recovered from backup

    def test_audit_log(self, tmp_path):
        """All operations are logged."""
        store = SecureMemoryStore(base_path=tmp_path, passphrase="test123")
        store.store_insight("logged operation")
        store.get_insights()

        audit = store.get_audit_log()
        assert len(audit) >= 2  # store + get
        assert audit[0].operation in ("INSERT", "SELECT")
        assert audit[0].timestamp is not None


class TestPredictionTracking:
    """Predictions must be tracked and scored."""

    def test_store_prediction(self, tmp_path):
        store = SecureMemoryStore(base_path=tmp_path, passphrase="test")
        pred_id = store.store_prediction(
            symbol="AAPL",
            prediction={"direction": "up", "target": 200, "confidence": 0.7},
            time_horizon="short",
            deadline="2026-04-15"
        )
        assert pred_id is not None

    def test_resolve_prediction(self, tmp_path):
        store = SecureMemoryStore(base_path=tmp_path, passphrase="test")
        pred_id = store.store_prediction(
            symbol="AAPL",
            prediction={"direction": "up", "target": 200, "confidence": 0.7},
            time_horizon="short",
            deadline="2026-04-15"
        )
        store.resolve_prediction(pred_id, actual_outcome="AAPL reached $205", accuracy=0.85)
        pred = store.get_prediction(pred_id)
        assert pred.resolved_at is not None
        assert pred.accuracy_score == 0.85

    def test_past_deadline_detection(self, tmp_path):
        store = SecureMemoryStore(base_path=tmp_path, passphrase="test")
        store.store_prediction(
            symbol="AAPL",
            prediction={"direction": "up", "target": 200},
            time_horizon="short",
            deadline="2026-01-01"  # Already past
        )
        overdue = store.get_overdue_predictions()
        assert len(overdue) >= 1
```

### 3.5 News Digest Tests

```python
# tests/test_news_digest.py

class TestConflictDetection:
    """Conflicts between sources must be caught."""

    def test_detects_contradicting_headlines(self):
        digest = NewsDigestEngine(mock_search, mock_hub, mock_memory)
        items = [
            NewsItem(source="reuters", title="Fed signals rate pause through Q3"),
            NewsItem(source="caixin", title="Fed likely to cut rates in June"),
        ]
        conflicts = digest.detect_conflicts(items)
        assert len(conflicts) >= 1
        assert "Fed" in conflicts[0].entity

    def test_no_false_conflict_on_different_topics(self):
        digest = NewsDigestEngine(mock_search, mock_hub, mock_memory)
        items = [
            NewsItem(source="reuters", title="AAPL reports record earnings"),
            NewsItem(source="cnbc", title="Oil prices drop on supply concerns"),
        ]
        conflicts = digest.detect_conflicts(items)
        assert len(conflicts) == 0

    def test_soft_conflict_different_magnitude(self):
        digest = NewsDigestEngine(mock_search, mock_hub, mock_memory)
        items = [
            NewsItem(source="reuters", title="Inflation rises 3.2% in February"),
            NewsItem(source="wsj", title="Inflation jumps 3.5% in February"),
        ]
        conflicts = digest.detect_conflicts(items)
        assert len(conflicts) >= 1
        assert conflicts[0].severity == "soft"  # Same direction, different number


class TestImpactScoring:
    """Impact scores must be computed, not guessed."""

    def test_impact_score_range(self):
        digest = NewsDigestEngine(mock_search, mock_hub, mock_memory)
        score = digest.quantify_impact(
            NewsItem(title="Fed raises rates 50bp"),
            symbol="SPY"
        )
        assert 0 <= score.magnitude <= 10
        assert 0 <= score.probability <= 1
        assert score.impact == score.magnitude * score.probability

    def test_high_impact_event(self):
        """Rate decision = high magnitude."""
        digest = NewsDigestEngine(mock_search, mock_hub, mock_memory)
        score = digest.quantify_impact(
            NewsItem(title="Fed raises rates 100bp unexpectedly")
        )
        assert score.magnitude >= 8

    def test_low_impact_event(self):
        """Minor executive hire = low magnitude."""
        digest = NewsDigestEngine(mock_search, mock_hub, mock_memory)
        score = digest.quantify_impact(
            NewsItem(title="Company X hires new VP of Marketing")
        )
        assert score.magnitude <= 3


class TestContinuousLearning:
    """Thesis must evolve with new data."""

    def test_thesis_update(self):
        digest = NewsDigestEngine(mock_search, mock_hub, mock_memory)
        # Initial thesis
        digest.update_thesis("AAPL", {"direction": "bullish", "confidence": 0.7})
        # Reinforcing data
        digest.update_thesis("AAPL", {"earnings_beat": True, "guidance_raised": True})
        thesis = digest.get_thesis("AAPL")
        assert thesis.confidence > 0.7  # Should increase

    def test_thesis_reversal_flagged(self):
        digest = NewsDigestEngine(mock_search, mock_hub, mock_memory)
        digest.update_thesis("AAPL", {"direction": "bullish", "confidence": 0.8})
        # Contradicting data
        digest.update_thesis("AAPL", {"earnings_miss": True, "guidance_cut": True, "ceo_departure": True})
        thesis = digest.get_thesis("AAPL")
        assert thesis.reversal_flagged is True

    def test_confidence_decay(self):
        digest = NewsDigestEngine(mock_search, mock_hub, mock_memory)
        digest.update_thesis("AAPL", {"direction": "bullish", "confidence": 0.8})
        # Simulate 5 weeks passing with no updates
        thesis = digest.get_thesis("AAPL", simulate_weeks=5)
        assert thesis.confidence < 0.8  # Decayed
        assert thesis.confidence >= 0.55  # 5 weeks × 5% decay from 0.8
```

### 3.6 Mode Integration Tests

```python
# tests/test_fin_mode.py

class TestModeSwitch:
    """Mode switching must be clean with no state leakage."""

    def test_switch_to_fin(self):
        config = AgentConfigManager(mode="chat")
        assert config.switch_mode("fin") is True
        assert config.mode == "fin"

    def test_switch_back_to_chat(self):
        config = AgentConfigManager(mode="fin")
        assert config.switch_mode("chat") is True
        assert config.mode == "chat"

    def test_fin_system_prompt_loaded(self):
        config = AgentConfigManager(mode="fin")
        assert "Personal Finance" in config.system_prompt
        assert "第一性原理" in config.system_prompt

    def test_fin_commands_available(self):
        config = AgentConfigManager(mode="fin")
        commands = config.available_commands
        assert "stock" in commands
        assert "crypto" in commands
        assert "digest" in commands
        assert "compute" in commands

    def test_coding_commands_not_in_fin(self):
        config = AgentConfigManager(mode="fin")
        commands = config.available_commands
        assert "refactor" not in commands
        assert "test" not in commands

    def test_no_state_leakage_between_modes(self):
        """Finance memory doesn't pollute chat mode."""
        config = AgentConfigManager(mode="fin")
        config.switch_mode("chat")
        assert "stock" not in config.available_commands
        assert "Personal Finance" not in config.system_prompt

    def test_invalid_mode_rejected(self):
        config = AgentConfigManager(mode="chat")
        assert config.switch_mode("invalid") is False
        assert config.mode == "chat"  # Unchanged

    def test_fin_config_values(self):
        config = AgentConfigManager(mode="fin")
        assert config.get("finance.memory_encryption") is True
        assert config.get("finance.source_languages") == ["en", "zh"]
        assert config.get("finance.conflict_resolution") is True
```

---

## 4. Continuous Validation (Runtime)

These checks run EVERY time in production, not just in tests:

```python
class RuntimeValidator:
    """
    Always-on checks that run in production.
    If any check fails, the response is modified or blocked.
    """

    def validate_before_output(self, response, context):
        checks = [
            self.check_no_hallucinated_prices(response, context),
            self.check_no_approximate_math(response),
            self.check_all_data_has_source(response),
            self.check_disclaimer_present(response, context),
            self.check_time_horizons_present(response, context),
            self.check_confidence_levels_present(response, context),
        ]
        failures = [c for c in checks if not c.passed]
        if failures:
            return self.remediate(response, failures, context)
        return response

    def check_no_hallucinated_prices(self, response, context):
        """Rule 1: No prices from LLM memory."""
        # Implementation: see FinanceResponseValidator above

    def check_no_approximate_math(self, response):
        """Rule 2: No 'approximately' or 'about' with dollar amounts."""
        # Implementation: see MathInterceptor above

    def check_all_data_has_source(self, response):
        """Rule 3: Every number has (source: X, timestamp: Y)."""
        # Check for financial figures without attribution

    def check_disclaimer_present(self, response, context):
        """Rule 4: Recommendations include confidence + disclaimer."""
        if context.contains_recommendation:
            if "confidence" not in response.lower():
                return CheckResult(passed=False, reason="Missing confidence level")
            if "not financial advice" not in response.lower() and \
               "informational purposes" not in response.lower():
                return CheckResult(passed=False, reason="Missing disclaimer")
        return CheckResult(passed=True)

    def check_time_horizons_present(self, response, context):
        """Rule 4: Recommendations have short/medium/long analysis."""
        if context.contains_recommendation:
            horizons = ["short", "medium", "long"]
            found = [h for h in horizons if h in response.lower()]
            if len(found) < 2:  # At least 2 of 3 horizons
                return CheckResult(passed=False, reason="Missing time horizons")
        return CheckResult(passed=True)
```

---

## 5. Test Execution Guide

```bash
# Run all finance tests
pytest tests/test_quant_engine.py tests/test_data_validation.py \
       tests/test_hybrid_search.py tests/test_secure_memory.py \
       tests/test_news_digest.py tests/test_fin_mode.py -v

# Run only critical correctness tests (fast, no network)
pytest tests/test_quant_engine.py tests/test_data_validation.py -v -m "not network"

# Run with coverage
pytest tests/ -v --cov=agent/finance --cov-report=html

# Run integration tests (requires network + API keys)
pytest tests/test_integration_live.py -v -m "network"

# Target: 95%+ coverage for quant_engine.py and data_validation.py
# Target: 85%+ coverage for all other finance modules
```
