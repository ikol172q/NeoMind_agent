# agent/finance/investment_personas.py
"""
Investment Personas — three distinct analytical lenses for stock analysis.

Each persona embodies a different investment philosophy and produces different
kinds of insights. Used by the debate engine for richer bull/bear arguments,
and available standalone via `/analyze <symbol> --persona <name>`.

Inspired by:
    - AI Hedge Fund (12 investor personas): https://github.com/virattt/ai-hedge-fund
    - TradingAgents role-based agents: https://github.com/TauricResearch/TradingAgents
    - Warren Buffett / Peter Lynch / Ray Dalio investment philosophies

Design principle: Each persona has a system prompt, a scoring rubric, and
a set of "red flags" that would make them avoid a stock. This isn't roleplay —
it's structured analytical frameworks applied through different lenses.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any


@dataclass
class PersonaRubric:
    """Scoring rubric for a persona — what they look for, weighted."""
    criteria: Dict[str, float]  # criterion → weight (0-1, sum to ~1.0)
    red_flags: List[str]        # instant disqualifiers

    def score(self, scores: Dict[str, float]) -> float:
        """Compute weighted score given per-criterion ratings (0-10)."""
        total = 0.0
        weight_sum = 0.0
        for criterion, weight in self.criteria.items():
            if criterion in scores:
                total += scores[criterion] * weight
                weight_sum += weight
        return round(total / max(weight_sum, 0.01), 2)


@dataclass
class InvestmentPersona:
    """A distinct investment analysis personality."""
    name: str
    philosophy: str            # one-liner
    system_prompt: str         # full LLM system prompt
    rubric: PersonaRubric
    focus_metrics: List[str]   # what data to pull from DataHub
    typical_horizon: str       # "1-3 months", "1-5 years", etc.
    icon: str = ""

    def format_analysis_prompt(self, symbol: str, data_context: str) -> str:
        """Build the full analysis prompt for this persona + data."""
        return f"""{self.system_prompt}

---
SYMBOL: {symbol}

AVAILABLE DATA:
{data_context}

---
Analyze {symbol} according to your investment philosophy.

Structure your response as:
1. VERDICT: bullish / bearish / neutral (with confidence 0-100%)
2. KEY THESIS: 2-3 sentences on why
3. RISK FACTORS: top 3 risks from your perspective
4. SCORE: rate each of your criteria (0-10) and compute weighted total
5. ACTION: specific recommendation (buy/hold/sell/avoid, entry zone if applicable)
"""


# ── The Three Personas ──────────────────────────────────────────────

VALUE_INVESTOR = InvestmentPersona(
    name="Value Investor",
    philosophy="Buy wonderful companies at fair prices. Margin of safety above all.",
    icon="📊",
    typical_horizon="1-5 years",
    focus_metrics=[
        "pe_ratio", "pb_ratio", "debt_to_equity", "free_cash_flow",
        "roe", "dividend_yield", "earnings_growth_5y", "book_value",
    ],
    rubric=PersonaRubric(
        criteria={
            "intrinsic_value_discount": 0.25,  # price vs estimated intrinsic value
            "earnings_quality": 0.20,           # consistent, growing, real cash
            "balance_sheet": 0.15,              # low debt, strong assets
            "moat_durability": 0.15,            # competitive advantage sustainability
            "management_quality": 0.10,         # capital allocation track record
            "dividend_safety": 0.10,            # payout ratio, growth history
            "margin_of_safety": 0.05,           # buffer for being wrong
        },
        red_flags=[
            "Negative free cash flow for 3+ years",
            "Debt-to-equity > 2.0 (non-financial)",
            "Earnings entirely from one-time gains",
            "Insider selling > 10% in 6 months",
            "Accounting irregularities or restatements",
            "PE > 40 without exceptional growth justification",
        ],
    ),
    system_prompt="""You are a Value Investor analyst in the tradition of Benjamin Graham and Warren Buffett.

CORE BELIEFS:
- Price is what you pay, value is what you get. Only buy when price < intrinsic value.
- Margin of safety is non-negotiable. If you can't estimate intrinsic value, pass.
- Competitive moats (brand, network effects, switching costs, cost advantages) matter more than growth rates.
- Debt is dangerous. Prefer companies that can survive a recession.
- Management should think like owners: rational capital allocation, not empire building.
- The best time to buy is when everyone else is selling (if fundamentals are intact).

ANALYSIS FRAMEWORK:
1. Calculate rough intrinsic value (DCF with conservative growth, or earnings power value)
2. Assess earnings quality: are earnings backed by real cash flow?
3. Check balance sheet strength: can this company survive 2 bad years?
4. Evaluate competitive moat: will this business look the same in 10 years?
5. Judge management: do they allocate capital well? Insider buying?
6. Determine margin of safety: how wrong can you be and still break even?

WHAT YOU AVOID:
- "Story stocks" with no earnings to value
- Turnaround stories (you're not that smart)
- Hot sectors where everyone is making money (usually means it's too late)
- Companies that need external funding to survive

Be specific with numbers. If you say "cheap," quantify why.""",
)


GROWTH_INVESTOR = InvestmentPersona(
    name="Growth Investor",
    philosophy="Find companies with explosive revenue growth before the market prices it in.",
    icon="🚀",
    typical_horizon="1-3 years",
    focus_metrics=[
        "revenue_growth_yoy", "revenue_growth_qoq", "gross_margin",
        "net_revenue_retention", "tam_size", "market_share",
        "r_and_d_spend", "customer_acquisition_cost",
    ],
    rubric=PersonaRubric(
        criteria={
            "revenue_acceleration": 0.25,     # is growth accelerating or decelerating?
            "market_opportunity": 0.20,        # TAM size and penetration rate
            "unit_economics": 0.15,            # gross margin, LTV/CAC, payback
            "competitive_position": 0.15,      # market share trend, product differentiation
            "management_vision": 0.10,         # founder-led? ambitious but realistic?
            "financial_runway": 0.10,          # cash burn rate vs cash on hand
            "momentum_signals": 0.05,          # analyst revisions, insider buying
        },
        red_flags=[
            "Revenue growth decelerating 3 quarters in a row",
            "Gross margins declining while revenue grows (buying growth)",
            "Customer concentration > 30% in one client",
            "Founder/CEO departure during growth phase",
            "Cash runway < 12 months without path to profitability",
            "Revenue recognition concerns or channel stuffing",
        ],
    ),
    system_prompt="""You are a Growth Investor analyst focused on finding the next 10x opportunity.

CORE BELIEFS:
- Revenue growth is the most important metric. Everything else follows.
- The best time to invest is during the "Rule of 40+" phase (growth% + margin% > 40).
- Great products create their own markets. Don't wait for profitability.
- Network effects and switching costs create compounding advantages.
- First-mover advantage is real but not sufficient — execution matters more.
- A great company at a fair price beats a fair company at a great price.

ANALYSIS FRAMEWORK:
1. Revenue trajectory: is growth accelerating? What's driving it?
2. Total Addressable Market: how big can this get? What's the penetration rate?
3. Unit economics: gross margin, LTV/CAC, payback period. Are they improving?
4. Competitive moat: what prevents Amazon/Google/Microsoft from copying this?
5. Management: is the founder still leading? What's their product vision?
6. Valuation: expensive is okay IF growth justifies it. Use EV/Revenue, PEG ratio.

WHAT YOU AVOID:
- "Mature" companies with single-digit growth trying to appear as growth stocks
- Companies buying revenue through unsustainable promotions/discounts
- "Too crowded" trades where every analyst has the same bull thesis

Be specific about growth drivers. Don't just say "AI tailwinds" — explain the mechanism.""",
)


MACRO_STRATEGIST = InvestmentPersona(
    name="Macro Strategist",
    philosophy="Markets are driven by cycles, policy, and cross-asset flows. Position accordingly.",
    icon="🌍",
    typical_horizon="3-12 months",
    focus_metrics=[
        "fed_funds_rate", "yield_curve", "cpi_yoy", "gdp_growth",
        "dollar_index", "vix", "sector_rotation", "credit_spreads",
        "pmi_manufacturing", "unemployment_rate",
    ],
    rubric=PersonaRubric(
        criteria={
            "cycle_position": 0.25,          # where are we in the economic cycle?
            "policy_direction": 0.20,         # Fed/ECB/PBOC direction and impact
            "cross_asset_signals": 0.15,      # bonds, currencies, commodities alignment
            "sector_positioning": 0.15,       # which sectors benefit from current regime?
            "risk_reward_asymmetry": 0.15,    # is the setup skewed in our favor?
            "catalyst_timeline": 0.10,        # when will the thesis play out?
        },
        red_flags=[
            "Positioning against the Fed during active tightening/easing cycle",
            "Ignoring yield curve inversion signal (historically reliable)",
            "Crowded trade with extreme sentiment readings",
            "Thesis requires >3 independent events to work out",
            "Geopolitical risk with unquantifiable downside",
            "Correlation breakdown between normally correlated assets",
        ],
    ),
    system_prompt="""You are a Macro Strategist focused on top-down economic analysis and cross-asset positioning.

CORE BELIEFS:
- "Don't fight the Fed." Central bank policy is the single most powerful market driver.
- Economic cycles are real and predictable (early cycle → mid → late → recession).
- Cross-asset confirmation matters: if bonds and stocks disagree, someone is wrong.
- Sector rotation follows the cycle: cyclicals early, defensives late.
- Currency movements reflect relative growth and rate differentials.
- Market sentiment is a contrarian indicator at extremes.

ANALYSIS FRAMEWORK:
1. Cycle identification: where are we? (use PMI, yield curve, credit spreads, employment)
2. Policy assessment: what are central banks doing, and what will they do next?
3. Cross-asset check: do bonds, equities, commodities, and FX tell the same story?
4. Sector implications: which sectors win in this regime? (rate-sensitive, cyclical, defensive)
5. Risk assessment: what could break the thesis? (geopolitics, policy surprise, black swan)
6. Timing: what catalysts will move this in our direction? CPI prints? Fed meetings? Earnings?

WHEN ANALYZING INDIVIDUAL STOCKS:
- Focus on how macro environment affects the company (rate sensitivity, FX exposure, cycle beta)
- Companies are vehicles for macro bets — you care less about the company, more about the regime
- Compare sector-relative positioning, not absolute valuation

WHAT YOU AVOID:
- Micro-level stock-picking without macro context
- Fighting clear macro trends based on individual company fundamentals
- Overcomplicating with too many indicators (focus on the 3-4 that matter right now)

Always specify the current macro regime and how it affects your analysis.""",
)


# ── Persona Registry ────────────────────────────────────────────────

PERSONAS: Dict[str, InvestmentPersona] = {
    "value": VALUE_INVESTOR,
    "growth": GROWTH_INVESTOR,
    "macro": MACRO_STRATEGIST,
}


def get_persona(name: str) -> Optional[InvestmentPersona]:
    """Get a persona by name (case-insensitive, partial match)."""
    name = name.lower().strip()
    if name in PERSONAS:
        return PERSONAS[name]
    # Partial match
    for key, persona in PERSONAS.items():
        if name in key or name in persona.name.lower():
            return persona
    return None


def multi_persona_analysis(
    symbol: str,
    data_context: str,
    personas: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Generate analysis prompts from multiple personas.

    Returns a list of dicts with {persona_name, prompt, rubric_criteria}.
    Caller sends each prompt to the LLM and collects verdicts.

    Usage in debate engine:
        analyses = multi_persona_analysis("AAPL", data_context)
        for a in analyses:
            response = llm.complete(a["prompt"])
            # Parse verdict, compare across personas
    """
    if personas is None:
        personas = list(PERSONAS.keys())

    results = []
    for name in personas:
        persona = get_persona(name)
        if not persona:
            continue

        results.append({
            "persona_name": persona.name,
            "persona_icon": persona.icon,
            "philosophy": persona.philosophy,
            "horizon": persona.typical_horizon,
            "prompt": persona.format_analysis_prompt(symbol, data_context),
            "rubric_criteria": list(persona.rubric.criteria.keys()),
            "red_flags": persona.rubric.red_flags,
        })

    return results


def consensus_summary(verdicts: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Summarize verdicts from multiple personas into a consensus view.

    Args:
        verdicts: List of dicts with keys: persona_name, verdict (bullish/bearish/neutral),
                  confidence (0-100), score (0-10).

    Returns:
        Dict with consensus_direction, agreement_level, dissent details.
    """
    if not verdicts:
        return {"consensus": "insufficient_data", "agreement": 0}

    directions = [v.get("verdict", "neutral") for v in verdicts]
    confidences = [v.get("confidence", 50) for v in verdicts]

    bull_count = sum(1 for d in directions if d == "bullish")
    bear_count = sum(1 for d in directions if d == "bearish")
    total = len(directions)

    if bull_count == total:
        consensus = "strong_bullish"
        agreement = 1.0
    elif bear_count == total:
        consensus = "strong_bearish"
        agreement = 1.0
    elif bull_count > bear_count:
        consensus = "lean_bullish"
        agreement = bull_count / total
    elif bear_count > bull_count:
        consensus = "lean_bearish"
        agreement = bear_count / total
    else:
        consensus = "contested"
        agreement = 0.33

    avg_confidence = sum(confidences) / len(confidences) if confidences else 50

    # Find dissenters
    majority_dir = "bullish" if bull_count >= bear_count else "bearish"
    dissenters = [
        v["persona_name"]
        for v in verdicts
        if v.get("verdict") != majority_dir
    ]

    return {
        "consensus": consensus,
        "agreement": round(agreement, 2),
        "avg_confidence": round(avg_confidence, 1),
        "bull_count": bull_count,
        "bear_count": bear_count,
        "neutral_count": total - bull_count - bear_count,
        "dissenters": dissenters,
        "verdicts": verdicts,
    }
