"""
Comprehensive unit tests for agent/finance/quant_engine.py
Tests all quantitative computation methods and result classes.
"""

import pytest
import math
from agent.finance.quant_engine import (
    QuantEngine,
    ComputationResult,
    OptionResult,
    ScenarioResult,
    DCFResult,
)


class TestComputationResult:
    """Test ComputationResult dataclass."""

    def test_creation(self):
        """Test creating a computation result."""
        result = ComputationResult(
            value=12589.25,
            formula="FV = P(1+r)^n",
            steps=["Step 1", "Step 2"],
            unit="USD",
        )
        assert result.value == 12589.25
        assert result.formula == "FV = P(1+r)^n"
        assert len(result.steps) == 2

    def test_str_representation(self):
        """Test string representation."""
        result = ComputationResult(value=100.5, unit="USD")
        assert str(result) == "100.5 USD"


class TestOptionResult:
    """Test OptionResult dataclass."""

    def test_creation(self):
        """Test creating option result."""
        result = OptionResult(
            price=5.25,
            delta=0.65,
            gamma=0.03,
            theta=-0.05,
            vega=0.15,
            rho=0.10,
        )
        assert result.price == 5.25
        assert result.delta == 0.65


class TestScenarioResult:
    """Test ScenarioResult dataclass."""

    def test_creation(self):
        """Test creating scenario result."""
        result = ScenarioResult(
            expected_value=5.0,
            variance=4.5,
            std_deviation=2.1,
            best_case=15.0,
            worst_case=-5.0,
        )
        assert result.expected_value == 5.0
        assert result.worst_case == -5.0

    def test_risk_reward_ratio(self):
        """Test risk/reward ratio calculation."""
        result = ScenarioResult(
            expected_value=0,
            variance=0,
            std_deviation=0,
            best_case=100,
            worst_case=-50,
        )
        assert result.risk_reward_ratio == 2.0

    def test_risk_reward_ratio_zero_worst_case(self):
        """Test risk/reward with zero worst case."""
        result = ScenarioResult(
            expected_value=0,
            variance=0,
            std_deviation=0,
            best_case=100,
            worst_case=0,
        )
        assert result.risk_reward_ratio == float('inf')


class TestDCFResult:
    """Test DCFResult dataclass."""

    def test_creation(self):
        """Test creating DCF result."""
        result = DCFResult(
            intrinsic_value=150.50,
            terminal_value=1200.00,
            terminal_value_pv=500.00,
            pv_cash_flows=[100, 90, 80],
        )
        assert result.intrinsic_value == 150.50
        assert len(result.pv_cash_flows) == 3


class TestQuantEngine:
    """Test QuantEngine quantitative methods."""

    @pytest.fixture
    def engine(self):
        """Create a QuantEngine instance."""
        return QuantEngine()

    # ── Compound Return Tests ──

    def test_compound_return_basic_annual(self, engine):
        """Test basic compound return with annual compounding."""
        result = engine.compound_return(
            principal=10000,
            annual_rate=0.08,
            years=10,
            compounding="annual",
        )

        # FV = 10000 * (1.08)^10 ≈ 21589.25
        assert abs(result.value - 21589.25) < 10
        assert result.unit == "USD"
        assert len(result.steps) > 0

    def test_compound_return_monthly_compounding(self, engine):
        """Test compound return with monthly compounding."""
        result = engine.compound_return(
            principal=10000,
            annual_rate=0.08,
            years=10,
            compounding="monthly",
        )

        # Monthly should give slightly higher value than annual
        assert result.value > 21589
        assert "monthly" in str(result.steps).lower() or "Monthly" in str(result.steps)

    def test_compound_return_continuous(self, engine):
        """Test compound return with continuous compounding."""
        result = engine.compound_return(
            principal=10000,
            annual_rate=0.08,
            years=10,
            compounding="continuous",
        )

        # e^(0.08*10) * 10000 ≈ 22255.4
        assert result.value > 22000

    def test_compound_return_daily(self, engine):
        """Test compound return with daily compounding."""
        result = engine.compound_return(
            principal=10000,
            annual_rate=0.08,
            years=10,
            compounding="daily",
        )

        assert result.value > 21589

    def test_compound_return_with_contributions(self, engine):
        """Test compound return with monthly contributions."""
        result = engine.compound_return(
            principal=10000,
            annual_rate=0.08,
            years=10,
            monthly_contribution=100,
            compounding="annual",
        )

        # Should be much higher due to contributions
        assert result.value > 30000

    def test_compound_return_zero_rate(self, engine):
        """Test compound return with zero interest rate."""
        result = engine.compound_return(
            principal=10000,
            annual_rate=0.0,
            years=10,
            compounding="annual",
        )

        assert result.value == 10000

    # ── Option Pricing Tests ──

    def test_option_pricing_call(self, engine):
        """Test Black-Scholes call option pricing."""
        result = engine.option_pricing(
            S=100,           # Current price
            K=100,           # Strike price
            T=1,             # 1 year to expiry
            r=0.05,          # 5% risk-free rate
            sigma=0.2,       # 20% volatility
            option_type="call",
        )

        assert result.price > 0
        assert 0 <= result.delta <= 1
        assert result.gamma > 0
        assert result.vega > 0

    def test_option_pricing_put(self, engine):
        """Test Black-Scholes put option pricing."""
        result = engine.option_pricing(
            S=100,
            K=100,
            T=1,
            r=0.05,
            sigma=0.2,
            option_type="put",
        )

        assert result.price > 0
        assert -1 <= result.delta <= 0

    def test_option_pricing_itm_call(self, engine):
        """Test in-the-money call option."""
        result = engine.option_pricing(
            S=110,
            K=100,
            T=1,
            r=0.05,
            sigma=0.2,
            option_type="call",
        )

        # ITM call should have higher price
        assert result.price > 10
        assert result.delta > 0.5

    def test_option_pricing_otm_call(self, engine):
        """Test out-of-the-money call option."""
        result = engine.option_pricing(
            S=90,
            K=100,
            T=1,
            r=0.05,
            sigma=0.2,
            option_type="call",
        )

        # OTM call should have lower price
        assert result.price < 10
        assert result.delta < 0.5

    def test_option_pricing_short_maturity(self, engine):
        """Test option with short time to expiry."""
        result = engine.option_pricing(
            S=100,
            K=100,
            T=0.01,  # 1 day
            r=0.05,
            sigma=0.2,
            option_type="call",
        )

        # Short-dated option should have lower value
        assert result.price > 0
        assert result.theta < 0  # Time decay for call

    # ── Scenario Analysis Tests ──

    def test_scenario_analysis_basic(self, engine):
        """Test basic scenario analysis."""
        scenarios = [
            {"probability": 0.25, "outcome": 20, "label": "bull"},
            {"probability": 0.50, "outcome": 10, "label": "base"},
            {"probability": 0.25, "outcome": -10, "label": "bear"},
        ]

        result = engine.scenario_analysis(scenarios)

        # Expected value should be 0.25*20 + 0.5*10 + 0.25*(-10) = 7.5
        assert abs(result.expected_value - 7.5) < 0.01
        assert result.best_case == 20
        assert result.worst_case == -10

    def test_scenario_analysis_invalid_probabilities(self, engine):
        """Test scenario analysis with invalid probabilities."""
        scenarios = [
            {"probability": 0.5, "outcome": 10, "label": "a"},
            {"probability": 0.3, "outcome": 20, "label": "b"},
        ]

        with pytest.raises(ValueError):
            engine.scenario_analysis(scenarios)

    def test_scenario_analysis_variance_std_dev(self, engine):
        """Test variance and standard deviation calculation."""
        scenarios = [
            {"probability": 0.5, "outcome": 10},
            {"probability": 0.5, "outcome": -10},
        ]

        result = engine.scenario_analysis(scenarios)

        assert result.expected_value == 0
        assert result.variance > 0
        assert result.std_deviation == math.sqrt(result.variance)

    # ── DCF Valuation Tests ──

    def test_dcf_valuation_basic(self, engine):
        """Test basic DCF valuation."""
        cash_flows = [100, 110, 120, 130, 140]
        discount_rate = 0.10
        terminal_growth = 0.03

        result = engine.dcf_valuation(cash_flows, discount_rate, terminal_growth)

        assert result.intrinsic_value > 0
        assert result.terminal_value > 0
        assert result.terminal_value_pv > 0
        assert len(result.pv_cash_flows) == 5

    def test_dcf_valuation_pv_decreases_over_time(self, engine):
        """Test that present values decrease over time."""
        cash_flows = [100, 100, 100, 100, 100]
        discount_rate = 0.10
        terminal_growth = 0.02

        result = engine.dcf_valuation(cash_flows, discount_rate, terminal_growth)

        # PVs should be decreasing
        for i in range(len(result.pv_cash_flows) - 1):
            assert result.pv_cash_flows[i] >= result.pv_cash_flows[i + 1]

    def test_dcf_valuation_invalid_terminal_growth(self, engine):
        """Test DCF with terminal growth >= discount rate."""
        cash_flows = [100, 110, 120]
        discount_rate = 0.05
        terminal_growth = 0.05

        with pytest.raises(ValueError):
            engine.dcf_valuation(cash_flows, discount_rate, terminal_growth)

    def test_dcf_valuation_sensitivity(self, engine):
        """Test DCF sensitivity analysis."""
        cash_flows = [100, 110, 120]
        discount_rate = 0.10
        terminal_growth = 0.03

        result = engine.dcf_valuation(cash_flows, discount_rate, terminal_growth)

        # Should have sensitivity analysis for ±1%
        assert len(result.sensitivity) > 0
        assert any("dr=" in key and "tg=" in key for key in result.sensitivity.keys())

    # ── Portfolio Risk Tests ──

    def test_sharpe_ratio(self, engine):
        """Test Sharpe ratio calculation."""
        sharpe = engine.sharpe_ratio(
            portfolio_return=0.12,
            risk_free_rate=0.04,
            std_deviation=0.15,
        )

        # (0.12 - 0.04) / 0.15 ≈ 0.533
        assert abs(sharpe - 0.5333) < 0.01

    def test_sharpe_ratio_zero_volatility(self, engine):
        """Test Sharpe ratio with zero volatility."""
        sharpe = engine.sharpe_ratio(
            portfolio_return=0.12,
            risk_free_rate=0.04,
            std_deviation=0.0,
        )

        assert sharpe == float('inf')

    def test_value_at_risk_95(self, engine):
        """Test VaR at 95% confidence."""
        var = engine.value_at_risk(
            portfolio_value=100000,
            mean_return=0.10,
            std_deviation=0.15,
            confidence=0.95,
        )

        # VaR should be negative (maximum loss)
        assert var < 100000

    def test_value_at_risk_99(self, engine):
        """Test VaR at 99% confidence."""
        var_99 = engine.value_at_risk(
            portfolio_value=100000,
            mean_return=0.10,
            std_deviation=0.15,
            confidence=0.99,
        )

        var_95 = engine.value_at_risk(
            portfolio_value=100000,
            mean_return=0.10,
            std_deviation=0.15,
            confidence=0.95,
        )

        # 99% confidence should show larger loss than 95%
        assert var_99 < var_95

    def test_position_size_calculation(self, engine):
        """Test position sizing."""
        result = engine.position_size(
            portfolio_value=100000,
            risk_per_trade=0.02,
            entry_price=100,
            stop_loss_price=95,
        )

        # Max risk = 100000 * 0.02 = 2000
        # Risk per share = 5
        # Shares = floor(2000 / 5) = 400
        assert result.value == 400
        assert "shares" in result.unit

    def test_position_size_equal_entry_stop(self, engine):
        """Test position size when entry equals stop."""
        result = engine.position_size(
            portfolio_value=100000,
            risk_per_trade=0.02,
            entry_price=100,
            stop_loss_price=100,  # Equal to entry
        )

        assert result.value == 0

    def test_position_size_larger_account(self, engine):
        """Test that larger account allows more shares."""
        result1 = engine.position_size(
            portfolio_value=50000,
            risk_per_trade=0.02,
            entry_price=100,
            stop_loss_price=95,
        )

        result2 = engine.position_size(
            portfolio_value=100000,
            risk_per_trade=0.02,
            entry_price=100,
            stop_loss_price=95,
        )

        assert result2.value > result1.value

    # ── Format Result Tests ──

    def test_format_result_computation(self, engine):
        """Test formatting computation result."""
        result = ComputationResult(
            value=12589.25,
            formula="FV = P(1+r)^n",
            steps=["Step 1: Calculate"],
            unit="USD",
        )

        formatted = engine.format_result(result)

        assert "12589.25" in formatted
        assert "FV = P(1+r)^n" in formatted
        assert "Step 1" in formatted

    def test_format_result_option(self, engine):
        """Test formatting option result."""
        result = OptionResult(
            price=5.25,
            delta=0.65,
            gamma=0.03,
            theta=-0.05,
            vega=0.15,
            rho=0.10,
            steps=["Step 1"],
        )

        formatted = engine.format_result(result)

        assert "5.25" in formatted
        assert "Delta" in formatted
        assert "Gamma" in formatted

    def test_format_result_scenario(self, engine):
        """Test formatting scenario result."""
        result = ScenarioResult(
            expected_value=5.0,
            variance=4.5,
            std_deviation=2.1,
            best_case=15.0,
            worst_case=-5.0,
            scenarios=[
                {"label": "bull", "outcome": 15, "probability": 0.25},
            ],
        )

        formatted = engine.format_result(result)

        assert "5.0" in formatted
        assert "bull" in formatted

    def test_format_result_dcf(self, engine):
        """Test formatting DCF result."""
        result = DCFResult(
            intrinsic_value=150.50,
            terminal_value=1200.00,
            terminal_value_pv=500.00,
            pv_cash_flows=[100, 90, 80],
            sensitivity={"dr=9%_tg=2%": 145.0},
        )

        formatted = engine.format_result(result)

        assert "150.50" in formatted
        assert "1,200.00" in formatted


class TestQuantEngineIntegration:
    """Integration tests for QuantEngine."""

    @pytest.fixture
    def engine(self):
        """Create engine for integration tests."""
        return QuantEngine()

    def test_complete_investment_analysis(self, engine):
        """Test complete investment analysis workflow."""
        # 1. Estimate future cash flows and value company
        cash_flows = [1000, 1100, 1210, 1331, 1464]
        dcf = engine.dcf_valuation(
            cash_flows=cash_flows,
            discount_rate=0.10,
            terminal_growth=0.03,
        )

        assert dcf.intrinsic_value > 0

        # 2. Price option on the stock (using at-the-money strike, not DCF value)
        option = engine.option_pricing(
            S=150,
            K=150,  # at-the-money
            T=1,
            r=0.05,
            sigma=0.20,
            option_type="call",
        )

        assert option.price > 0

    def test_risk_adjusted_sizing(self, engine):
        """Test position sizing with risk metrics."""
        # Calculate Sharpe ratio
        sharpe = engine.sharpe_ratio(0.12, 0.04, 0.15)

        # Size position based on entry/exit
        position = engine.position_size(
            portfolio_value=100000,
            risk_per_trade=0.02,
            entry_price=100,
            stop_loss_price=95,
        )

        assert position.value > 0
        assert sharpe > 0

    def test_scenario_planning(self, engine):
        """Test scenario-based planning."""
        scenarios = [
            {"probability": 0.2, "outcome": 30, "label": "strong growth"},
            {"probability": 0.5, "outcome": 10, "label": "base case"},
            {"probability": 0.3, "outcome": -15, "label": "recession"},
        ]

        result = engine.scenario_analysis(scenarios)

        # Expected value should be weighted
        expected = 0.2*30 + 0.5*10 + 0.3*(-15)
        assert abs(result.expected_value - expected) < 0.01

        # Risk/reward should be positive
        assert result.risk_reward_ratio > 0
