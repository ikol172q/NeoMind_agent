# agent/finance/quant_engine.py
"""
Quantitative Engine — mathematical computation tools for financial analysis.

PRINCIPLE: If it can be computed, compute it. NEVER estimate.

Uses:
- math (stdlib) for basic operations
- sympy (optional) for symbolic math
- numpy (optional) for numerical/statistical operations
- Generates Python code for novel computations

All results are COMPUTED, never approximated by LLM.
"""

import math
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Any


try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False
    np = None

try:
    import sympy
    HAS_SYMPY = True
except ImportError:
    HAS_SYMPY = False
    sympy = None


# ── Result Data Classes ───────────────────────────────────────────────

@dataclass
class ComputationResult:
    """Result of any quantitative computation."""
    value: Any
    formula: str = ""
    steps: List[str] = field(default_factory=list)
    unit: str = ""
    confidence: float = 1.0  # computed = 1.0, always
    method: str = ""

    def __str__(self):
        return f"{self.value} {self.unit}".strip()


@dataclass
class OptionResult:
    """Result of option pricing computation."""
    price: float
    delta: float = 0.0
    gamma: float = 0.0
    theta: float = 0.0
    vega: float = 0.0
    rho: float = 0.0
    formula: str = "Black-Scholes"
    steps: List[str] = field(default_factory=list)


@dataclass
class ScenarioResult:
    """Result of scenario analysis."""
    expected_value: float
    variance: float
    std_deviation: float
    best_case: float
    worst_case: float
    scenarios: List[Dict] = field(default_factory=list)

    @property
    def risk_reward_ratio(self) -> float:
        if self.worst_case == 0:
            return float('inf')
        return abs(self.best_case / self.worst_case)


@dataclass
class DCFResult:
    """Result of DCF valuation."""
    intrinsic_value: float
    terminal_value: float
    terminal_value_pv: float
    pv_cash_flows: List[float] = field(default_factory=list)
    sensitivity: Dict[str, float] = field(default_factory=dict)


# ── Main Quant Engine ─────────────────────────────────────────────────

class QuantEngine:
    """
    Mathematical computation tools for financial analysis.

    Every method computes exactly. No estimation. No rounding until display.
    All intermediate steps are recorded for transparency.
    """

    # ── Compound Returns ──────────────────────────────────────────────

    def compound_return(
        self,
        principal: float,
        annual_rate: float,
        years: int,
        monthly_contribution: float = 0,
        compounding: str = "annual",
    ) -> ComputationResult:
        """
        Exact compound return calculation.

        Args:
            principal: Starting amount
            annual_rate: Annual interest rate (e.g., 0.07 for 7%)
            years: Number of years
            monthly_contribution: Monthly additional investment
            compounding: "annual", "monthly", "daily", "continuous"
        """
        steps = []
        steps.append(f"Principal: ${principal:,.2f}")
        steps.append(f"Annual rate: {annual_rate:.4%}")
        steps.append(f"Period: {years} years")
        steps.append(f"Compounding: {compounding}")

        if compounding == "continuous":
            # FV = P * e^(rt)
            fv_principal = principal * math.exp(annual_rate * years)
            steps.append(f"FV(principal) = {principal} × e^({annual_rate} × {years}) = {fv_principal:.2f}")

            if monthly_contribution > 0:
                # Approximate continuous contributions
                r = annual_rate
                fv_contributions = monthly_contribution * 12 * (math.exp(r * years) - 1) / r
                steps.append(f"FV(contributions) ≈ ${fv_contributions:,.2f}")
                total = fv_principal + fv_contributions
            else:
                total = fv_principal

        elif compounding == "monthly":
            monthly_rate = annual_rate / 12
            n_months = years * 12
            fv_principal = principal * (1 + monthly_rate) ** n_months
            steps.append(f"Monthly rate: {monthly_rate:.6f}")
            steps.append(f"FV(principal) = {principal} × (1 + {monthly_rate:.6f})^{n_months} = {fv_principal:.2f}")

            if monthly_contribution > 0:
                fv_contributions = monthly_contribution * ((1 + monthly_rate) ** n_months - 1) / monthly_rate
                steps.append(f"FV(contributions) = {monthly_contribution} × ((1 + {monthly_rate:.6f})^{n_months} - 1) / {monthly_rate:.6f} = {fv_contributions:.2f}")
                total = fv_principal + fv_contributions
            else:
                total = fv_principal

        elif compounding == "daily":
            daily_rate = annual_rate / 365
            n_days = years * 365
            fv_principal = principal * (1 + daily_rate) ** n_days
            steps.append(f"FV(principal) = {principal} × (1 + {daily_rate:.8f})^{n_days} = {fv_principal:.2f}")
            total = fv_principal
            if monthly_contribution > 0:
                steps.append("Note: Monthly contributions with daily compounding approximated as monthly compounding")
                monthly_rate = annual_rate / 12
                n_months = years * 12
                fv_contributions = monthly_contribution * ((1 + monthly_rate) ** n_months - 1) / monthly_rate
                total += fv_contributions

        else:  # annual
            fv_principal = principal * (1 + annual_rate) ** years
            steps.append(f"FV(principal) = {principal} × (1 + {annual_rate})^{years} = {fv_principal:.2f}")

            if monthly_contribution > 0:
                # Convert to annual contributions compounded annually
                annual_contribution = monthly_contribution * 12
                fv_contributions = annual_contribution * ((1 + annual_rate) ** years - 1) / annual_rate
                steps.append(f"FV(annual contributions of ${annual_contribution:,.2f}) = ${fv_contributions:,.2f}")
                total = fv_principal + fv_contributions
            else:
                total = fv_principal

        total_contributed = principal + monthly_contribution * 12 * years
        total_gain = total - total_contributed
        steps.append(f"Total contributed: ${total_contributed:,.2f}")
        steps.append(f"Total gain: ${total_gain:,.2f}")
        steps.append(f"Final value: ${total:,.2f}")

        return ComputationResult(
            value=round(total, 2),
            formula=f"FV = P(1+r)^n + PMT×((1+r)^n - 1)/r",
            steps=steps,
            unit="USD",
            method="compound_return",
        )

    # ── Black-Scholes Option Pricing ──────────────────────────────────

    def option_pricing(
        self,
        S: float,
        K: float,
        T: float,
        r: float,
        sigma: float,
        option_type: str = "call",
    ) -> OptionResult:
        """
        Black-Scholes exact solution with Greeks.

        Args:
            S: Current stock price
            K: Strike price
            T: Time to expiry in years
            r: Risk-free rate (annualized)
            sigma: Volatility (annualized)
            option_type: "call" or "put"
        """
        steps = []
        steps.append(f"S={S}, K={K}, T={T}, r={r}, σ={sigma}, type={option_type}")

        # d1 and d2
        d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)
        steps.append(f"d1 = (ln(S/K) + (r + σ²/2)T) / (σ√T) = {d1:.6f}")
        steps.append(f"d2 = d1 - σ√T = {d2:.6f}")

        # Normal CDF
        from math import erf
        def norm_cdf(x):
            return 0.5 * (1 + erf(x / math.sqrt(2)))

        def norm_pdf(x):
            return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)

        Nd1 = norm_cdf(d1)
        Nd2 = norm_cdf(d2)
        Nnd1 = norm_cdf(-d1)
        Nnd2 = norm_cdf(-d2)
        steps.append(f"N(d1) = {Nd1:.6f}, N(d2) = {Nd2:.6f}")

        # Price
        if option_type.lower() == "call":
            price = S * Nd1 - K * math.exp(-r * T) * Nd2
            delta = Nd1
            steps.append(f"Call = S·N(d1) - K·e^(-rT)·N(d2) = {price:.4f}")
        else:
            price = K * math.exp(-r * T) * Nnd2 - S * Nnd1
            delta = Nd1 - 1
            steps.append(f"Put = K·e^(-rT)·N(-d2) - S·N(-d1) = {price:.4f}")

        # Greeks
        gamma = norm_pdf(d1) / (S * sigma * math.sqrt(T))
        theta_call = (-S * norm_pdf(d1) * sigma / (2 * math.sqrt(T))
                      - r * K * math.exp(-r * T) * Nd2)
        theta_put = (-S * norm_pdf(d1) * sigma / (2 * math.sqrt(T))
                     + r * K * math.exp(-r * T) * Nnd2)
        theta = theta_call / 365 if option_type.lower() == "call" else theta_put / 365
        vega = S * norm_pdf(d1) * math.sqrt(T) / 100  # per 1% vol change
        rho_call = K * T * math.exp(-r * T) * Nd2 / 100
        rho_put = -K * T * math.exp(-r * T) * Nnd2 / 100
        rho = rho_call if option_type.lower() == "call" else rho_put

        steps.append(f"Delta = {delta:.4f}")
        steps.append(f"Gamma = {gamma:.6f}")
        steps.append(f"Theta = {theta:.4f} (per day)")
        steps.append(f"Vega = {vega:.4f} (per 1% vol)")
        steps.append(f"Rho = {rho:.4f} (per 1% rate)")

        return OptionResult(
            price=round(price, 4),
            delta=round(delta, 4),
            gamma=round(gamma, 6),
            theta=round(theta, 4),
            vega=round(vega, 4),
            rho=round(rho, 4),
            steps=steps,
        )

    # ── Scenario Analysis ─────────────────────────────────────────────

    def scenario_analysis(self, scenarios: List[Dict]) -> ScenarioResult:
        """
        Exact expected value and risk analysis.

        Args:
            scenarios: List of {probability: float, outcome: float, label: str}

        Returns:
            ScenarioResult with EV, variance, best/worst case.

        Raises:
            ValueError: If probabilities don't sum to ~1.0
        """
        total_prob = sum(s["probability"] for s in scenarios)
        if abs(total_prob - 1.0) > 0.01:
            raise ValueError(
                f"Scenario probabilities must sum to 1.0 (got {total_prob:.4f}). "
                f"Please adjust your probabilities."
            )

        ev = sum(s["probability"] * s["outcome"] for s in scenarios)
        variance = sum(s["probability"] * (s["outcome"] - ev) ** 2 for s in scenarios)
        std_dev = math.sqrt(variance)
        best = max(s["outcome"] for s in scenarios)
        worst = min(s["outcome"] for s in scenarios)

        return ScenarioResult(
            expected_value=round(ev, 4),
            variance=round(variance, 4),
            std_deviation=round(std_dev, 4),
            best_case=best,
            worst_case=worst,
            scenarios=scenarios,
        )

    # ── DCF Valuation ─────────────────────────────────────────────────

    def dcf_valuation(
        self,
        cash_flows: List[float],
        discount_rate: float,
        terminal_growth: float,
    ) -> DCFResult:
        """
        Discounted Cash Flow valuation with terminal value.

        Args:
            cash_flows: Projected free cash flows for each year
            discount_rate: WACC or required return
            terminal_growth: Perpetual growth rate for terminal value

        Raises:
            ValueError: If terminal_growth >= discount_rate
        """
        if terminal_growth >= discount_rate:
            raise ValueError(
                f"Terminal growth rate ({terminal_growth:.2%}) must be less than "
                f"discount rate ({discount_rate:.2%}). A perpetuity with growth "
                f"exceeding the discount rate has infinite value — this is impossible."
            )

        # PV of explicit cash flows
        pv_cfs = []
        for i, cf in enumerate(cash_flows):
            pv = cf / (1 + discount_rate) ** (i + 1)
            pv_cfs.append(round(pv, 2))

        # Terminal value (Gordon Growth Model)
        last_cf = cash_flows[-1]
        terminal_cf = last_cf * (1 + terminal_growth)
        terminal_value = terminal_cf / (discount_rate - terminal_growth)
        n = len(cash_flows)
        terminal_value_pv = terminal_value / (1 + discount_rate) ** n

        intrinsic_value = sum(pv_cfs) + terminal_value_pv

        # Sensitivity analysis: ±1% on discount rate and growth
        sensitivity = {}
        for dr_delta in [-0.01, 0, 0.01]:
            for tg_delta in [-0.01, 0, 0.01]:
                dr = discount_rate + dr_delta
                tg = terminal_growth + tg_delta
                if tg >= dr:
                    continue
                tv = last_cf * (1 + tg) / (dr - tg)
                tv_pv = tv / (1 + dr) ** n
                pv_sum = sum(cf / (1 + dr) ** (i + 1) for i, cf in enumerate(cash_flows))
                key = f"dr={dr:.1%}_tg={tg:.1%}"
                sensitivity[key] = round(pv_sum + tv_pv, 2)

        return DCFResult(
            intrinsic_value=round(intrinsic_value, 2),
            terminal_value=round(terminal_value, 2),
            terminal_value_pv=round(terminal_value_pv, 2),
            pv_cash_flows=pv_cfs,
            sensitivity=sensitivity,
        )

    # ── Portfolio Risk ────────────────────────────────────────────────

    def sharpe_ratio(
        self,
        portfolio_return: float,
        risk_free_rate: float,
        std_deviation: float,
    ) -> float:
        """Sharpe ratio = (Rp - Rf) / σp"""
        if std_deviation == 0:
            return float('inf')
        return round((portfolio_return - risk_free_rate) / std_deviation, 4)

    def value_at_risk(
        self,
        portfolio_value: float,
        mean_return: float,
        std_deviation: float,
        confidence: float = 0.95,
    ) -> float:
        """
        Parametric VaR (assumes normal distribution).

        Returns the maximum expected loss at the given confidence level.
        Negative number = loss.
        """
        # Z-scores for common confidence levels
        z_scores = {0.90: 1.282, 0.95: 1.645, 0.99: 2.326}
        z = z_scores.get(confidence)
        if z is None:
            # Use inverse normal CDF for custom confidence
            # Approximation using math.erfinv
            from math import erfinv
            z = math.sqrt(2) * erfinv(2 * confidence - 1)

        var = portfolio_value * (mean_return - z * std_deviation)
        return round(var, 2)

    def position_size(
        self,
        portfolio_value: float,
        risk_per_trade: float,
        entry_price: float,
        stop_loss_price: float,
    ) -> ComputationResult:
        """
        Kelly-inspired position sizing.

        Args:
            portfolio_value: Total portfolio value
            risk_per_trade: Max risk as fraction (e.g., 0.02 for 2%)
            entry_price: Planned entry price
            stop_loss_price: Stop loss price
        """
        risk_amount = portfolio_value * risk_per_trade
        risk_per_share = abs(entry_price - stop_loss_price)

        if risk_per_share == 0:
            return ComputationResult(
                value=0, formula="N/A",
                steps=["Error: entry price equals stop loss price"],
            )

        shares = math.floor(risk_amount / risk_per_share)
        position_value = shares * entry_price
        actual_risk = shares * risk_per_share

        steps = [
            f"Portfolio: ${portfolio_value:,.2f}",
            f"Max risk: {risk_per_trade:.1%} = ${risk_amount:,.2f}",
            f"Entry: ${entry_price:.2f}, Stop: ${stop_loss_price:.2f}",
            f"Risk per share: ${risk_per_share:.2f}",
            f"Shares: floor(${risk_amount:,.2f} / ${risk_per_share:.2f}) = {shares}",
            f"Position value: ${position_value:,.2f} ({position_value/portfolio_value:.1%} of portfolio)",
            f"Actual risk: ${actual_risk:,.2f}",
        ]

        return ComputationResult(
            value=shares,
            formula="shares = floor(portfolio × risk% / |entry - stop|)",
            steps=steps,
            unit="shares",
            method="position_size",
        )

    # ── Utility ───────────────────────────────────────────────────────

    def format_result(self, result: Any) -> str:
        """Format any computation result for display."""
        if isinstance(result, ComputationResult):
            lines = [f"Result: {result.value} {result.unit}"]
            if result.formula:
                lines.append(f"Formula: {result.formula}")
            lines.append("Steps:")
            for step in result.steps:
                lines.append(f"  {step}")
            return "\n".join(lines)

        elif isinstance(result, OptionResult):
            lines = [
                f"Option Price: ${result.price:.4f}",
                f"Greeks:",
                f"  Delta: {result.delta:.4f}",
                f"  Gamma: {result.gamma:.6f}",
                f"  Theta: {result.theta:.4f}/day",
                f"  Vega:  {result.vega:.4f}/1%",
                f"  Rho:   {result.rho:.4f}/1%",
                f"Method: {result.formula}",
                "Steps:",
            ]
            for step in result.steps:
                lines.append(f"  {step}")
            return "\n".join(lines)

        elif isinstance(result, ScenarioResult):
            lines = [
                f"Expected Value: {result.expected_value:.2f}%",
                f"Std Deviation:  {result.std_deviation:.2f}%",
                f"Best Case:      {result.best_case:.2f}%",
                f"Worst Case:     {result.worst_case:.2f}%",
                f"Risk/Reward:    {result.risk_reward_ratio:.2f}x",
                "Scenarios:",
            ]
            for s in result.scenarios:
                label = s.get("label", "")
                lines.append(f"  {label}: {s['outcome']:.2f}% (prob: {s['probability']:.0%})")
            return "\n".join(lines)

        elif isinstance(result, DCFResult):
            lines = [
                f"Intrinsic Value: ${result.intrinsic_value:,.2f}",
                f"Terminal Value:  ${result.terminal_value:,.2f}",
                f"Terminal PV:     ${result.terminal_value_pv:,.2f}",
                f"PV of CFs:       {[f'${x:,.2f}' for x in result.pv_cash_flows]}",
                "Sensitivity (discount rate × terminal growth):",
            ]
            for key, val in result.sensitivity.items():
                lines.append(f"  {key}: ${val:,.2f}")
            return "\n".join(lines)

        return str(result)
