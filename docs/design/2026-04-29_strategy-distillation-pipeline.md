# Strategy distillation pipeline — what's wrong, what's correct

**Date**: 2026-04-29  
**Author**: NeoMind agent (driven by user pushback that current pipeline produces near-identical results across days)  
**Scope**: full redesign of the L0 → L3 → strategy ranking flow

---

## 0. The user's complaint, distilled

> "我不认为每天的 Strategies tab 的内容几乎一样，显然是算法或者某个地方有点问题或者设置过于死板。目前的样子完全没法帮助投资。"

Every Difficulty filter at every date returns essentially identical cards in
identical order with similar fit numbers. This is **not a UI bug**. It is a
**fundamental algorithm bug**: the pipeline cannot extract differential signal
from one day to the next, even when the underlying market is genuinely
different.

This document explains why, and what the scientifically correct replacement is.

---

## 1. Five structural defects in the current pipeline

### 1.1 Tag-set obs lose all the information

L0 widgets emit observations as **categorical tags**:

```
AAPL at top of 20d range  → tags: ["technical:near_52w_high", "symbol:AAPL"]
```

But a strategy's relevance depends on **numbers**:
- AAPL at the **86th** percentile vs **94th** percentile of its 20-day range:
  one is "stretched", the other is "rocket". Both render as
  `near_52w_high`. Same tag set → same theme → same score. We've thrown
  away the only signal that matters.
- META earnings in **0d** vs **5d**: implied vol is qualitatively different.
  Both render as `catalyst:earnings`.
- VIX at **18** vs **34**: completely different regime for short-vol
  strategies. Either both fire `regime:vix` or neither does.

The pipeline is operating on a **discretized 4-bit shadow** of a continuous
state space. **No clever downstream matcher can recover the bits we threw away
at L0.**

### 1.2 The matcher is a heuristic, not a financial model

`_score_strategy()` in `strategy_matcher.py` is a hand-coded rule book:

```python
if expected == strategy.get("horizon"):           breakdown["horizon_match"] = 3
if strategy.get("asset_class") == "options":      breakdown["options_asset_class"] = 2
if "risk:earnings" in tag_set:                    breakdown["earnings_event"] = 2
```

This is a **categorical proxy** for what the user actually wants to know:

> Given today's market state and my account, what is the **expected utility**
> of putting this strategy on?

That requires:

- A **payoff function** for the strategy: `payoff(spot_at_expiry, strikes, IV, ...)`
- A **forecast distribution** of the underlying: `p(spot_at_expiry | today's IV regime)`
- Integration: `E[PnL] = ∫ payoff(x) · p(x|regime) dx`

None of which the current matcher does. It just adds +3 if horizons match.

### 1.3 No regime conditioning

A "covered call on SPY" is:
- **Excellent** when IV is at 70th+ percentile (fat premium, mean-revert
  vol back down)
- **Mediocre** when IV is at 30th percentile (thin premium, vol can spike up)
- **Bad** when realized vol is materially below implied (theta isn't
  compensating you)

Current matcher ignores all three. It scores covered_call_etf at 7 every day
because every day has the same tag set (`technical:near_52w_high`,
`regime:vix`, etc.).

### 1.4 No empirical Bayesian prior

We have a **snapshot history**: 6 days of full lattice state stored on disk.
A scientifically correct fit score uses this:

> The fit of strategy X today should be close to the average historical
> P&L of X **conditional on a regime vector similar to today's**.

We never compute this. We never even compute a regime vector.

### 1.5 Single-strategy ranking, not portfolio selection

The user thinks in **portfolios**. They want a basket like:

```
1 income-generating short-vol position (covered call)
1 hedge against tail risk (long put or VXX call)
1 directional exposure (long ETF)
1 carry / cash position
```

The current top-5 is just the top-5 cards by score, all from the same family
(short-vol options): covered_call_etf, cash_secured_put_etf,
vertical_bull_put_spread, vertical_bear_call_spread, iron_condor_index.
**This is not investing advice. It's a SQL ORDER BY.**

---

## 2. The scientifically correct pipeline

```
┌─────────────────────────────────────────────────────────────────┐
│ L0: SOURCE WIDGETS                                              │
│   Each widget emits NUMERIC metrics + (optional) tag annotations│
│                                                                 │
│   chart        → {pct_20d, pct_252d, distance_to_52w_high, ...} │
│   iv_widget    → {iv, iv_rank_252d, iv_term_slope, ...}         │
│   earnings_cal → {next_earnings_days, last_earnings_move, ...}  │
│   sector_map   → {sector_z_score_5d, breadth, dispersion, ...}  │
│   vix          → {vix, vix_rank_252d, vix_term_slope, ...}      │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ L1: DAILY REGIME FINGERPRINT                                    │
│   regime_vector(d) = [                                          │
│     VIX_pctile_252,            // implied-vol regime            │
│     RV_60d_pctile,             // realized-vol regime           │
│     market_breadth,            // % stocks above 50d MA         │
│     sector_dispersion,         // std-dev of sector returns     │
│     earnings_density_5d,       // # earnings in next 5 days     │
│     term_structure_slope,      // VIX9D − VIX                   │
│     put_call_ratio,                                             │
│     credit_spread,             // HYG OAS                       │
│     ...                                                         │
│   ]                                                             │
│                                                                 │
│   This is a ~20-dim vector. Two days are "similar" iff their    │
│   vectors are close (cosine / Mahalanobis). Cross-day           │
│   discrimination LIVES HERE.                                    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ L2: THEMES — kept for HUMAN explanation, not scoring            │
│   "Earnings risk", "Sector rotation", etc. remain as a          │
│   semantic cluster of L1 obs for the narrative card.            │
│   Scoring DOES NOT route through them.                          │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ L3: STRATEGY EXPECTED UTILITY (analytic where possible)         │
│                                                                 │
│   Each strategy YAML gains a quantitative profile:              │
│     delta, theta, vega, gamma                                   │
│     expected_hold_days                                          │
│     breakeven_RV (the realized vol at which strategy P&L = 0)  │
│     payoff_function: (spot_at_T, strikes, IV) → P&L            │
│     greeks_under_regime: f(IV_pctile) → adjusted greeks        │
│                                                                 │
│   For each strategy, given today's regime:                      │
│     payoff_dist = analytic_payoff(strategy, today_regime)       │
│     E[PnL]      = ∫ payoff(x) p(x | regime) dx                  │
│     P(profit)   = ∫ I{payoff(x) > 0} p(x | regime) dx           │
│     VaR_95      = inv_payoff_dist(0.05)                         │
│     E[max_DD]   = regime-conditional drawdown estimate          │
│                                                                 │
│   The forecast distribution p(x|regime) comes from:             │
│     - Black-Scholes if regime is in the IV-coherent zone        │
│     - Empirical bootstrap from past 60 days otherwise           │
│     - Heston / SABR if we want term-structure calibration       │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ L4: BAYESIAN CALIBRATION (empirical prior)                      │
│                                                                 │
│   model_score = composite_utility(E[PnL], P(profit), VaR, ...)  │
│                                                                 │
│   For each strategy s:                                          │
│     similar_days = k-NN(today_regime, past_regimes, k=20,       │
│                         metric=Mahalanobis, max_distance=ε)     │
│     historical_PnL_dist = empirical_PnL(s, similar_days)        │
│                                                                 │
│     // Bayesian shrinkage — confidence rises with sample size  │
│     β = 1 / (1 + n/n0)        where n = |similar_days|, n0 = 5  │
│     posterior_score = β · model_score + (1−β) · empirical_score │
│                                                                 │
│   When similar_days is empty, β → 1 (model only).               │
│   When similar_days is rich, β → 0 (data dominates).            │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ L5: CONSTRAINT SATISFACTION (hard filter)                       │
│                                                                 │
│   Drop strategy s when ANY of:                                  │
│     • min_capital(s) > account.equity                           │
│     • s.PDT_relevant AND account.equity < 25k AND               │
│         PDT_remaining < safety_buffer                           │
│     • s.wash_sale_risk == 'high' AND                            │
│         account has realized loss in same underlying ≤ 30 days  │
│     • s.options_level > account.options_level                   │
│     • s.holding_period_min > today + horizon                    │
│                                                                 │
│   These are the user's REAL constraints — they belong as a hard │
│   filter, not a -2 penalty in the score.                        │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ L6: PORTFOLIO SELECTION (k-best diversified)                    │
│                                                                 │
│   Goal: pick K strategies (default 5) to MAXIMIZE              │
│     Σ posterior_score_i                                         │
│   subject to:                                                   │
│     |portfolio_delta|  ≤ δ_max                                  │
│     |portfolio_vega|   ≤ ν_max                                  │
│     |portfolio_theta|  ≤ θ_max                                  │
│     max_pairwise_correlation ≤ ρ_max                            │
│     sector_concentration ≤ s_max                                │
│                                                                 │
│   Solve as a small MMR (Maximal Marginal Relevance) — already   │
│   used at L3 for call selection — or a 0-1 quadratic program if │
│   the catalog is small.                                         │
│                                                                 │
│   Output is the diversified BASKET, not the top-5 of one family.│
└─────────────────────────────────────────────────────────────────┘
```

### 2.1 Why this gives day-to-day differentiation that the current pipeline can't

- **L1 regime vector**: 20 continuous dims means today's vector is
  effectively unique. Cosine distance to yesterday's is small but nonzero;
  to last month's it's larger. **This signal alone changes scores every day.**

- **L3 expected utility**: covered call's E[PnL] is a function of (IV, RV,
  spot_distance_to_strike, days_to_expiry). All four change daily. The
  score reflects them.

- **L4 empirical prior**: the same regime appearing twice in history (e.g.
  two prior earnings-density-spike + low-VIX days) gives a sharper prior;
  a unique regime today gives a wider one. The fit number reflects
  uncertainty, not just point estimate.

- **L6 portfolio selection**: when one short-vol strategy already maxes out
  the basket's vega budget, the next-best ADD is a long-vol or
  delta-neutral hedge — not the next short-vol strategy. The basket
  composition genuinely changes day-to-day as the market changes.

---

## 3. What's salvageable from the current code

| Current piece | Keep / Replace | Notes |
|---|---|---|
| L0 widgets (chart / earnings / sector / market_regime) | Keep, augment | Add `metrics: {}` block alongside the existing `tags: []`. |
| L1 observations as tags | Keep for narrative, ignore for scoring | Tag set still useful for the "why this card" prose. |
| L2 themes (LLM-narrated clusters) | Keep, demote | Themes are semantic shortcuts for the reader. Scoring routes around them. |
| L3 calls (Toulmin-structured) | Keep | The Warrant/Qualifier/Rebuttal frame is good. Just feed it from the new scorer. |
| `match_strategy()` (categorical) | **Replace** | This is the heart of the bug. |
| `match_all_against_themes()` (categorical) | **Replace** | Same. |
| Snapshot history on disk | **Use** | Becomes the empirical prior dataset for L4. |
| Strategy YAML catalog | Keep, augment | Add the quantitative profile block (greeks, payoff, breakeven). |

---

## 4. The uncomfortable truths (these are real, not deflections)

1. **Real options scoring needs an options chain feed.** IBKR / Tradier / TDA /
   ORATS are options. Without one, "expected covered-call P&L" is
   guesswork. We can fake it with implied-vol estimates from historical
   30-day RV, but the result is bounded in quality.

2. **Empirical prior needs a backtest harness.** "Strategy X's P&L on
   historical days similar to today" requires (a) a strategy executor that
   takes a parameter set + a date, runs the strategy, and returns a P&L
   curve; (b) a stored timeline of past days' regime vectors. Neither
   exists in the current codebase.

3. **Multi-criteria utility is calibration-heavy.** The composite score has
   weights `w1·E[PnL]/risk + w2·P(profit) + w3·tax + ...` that are not
   universal — they depend on the user's risk preferences. We need a
   small UI for the user to set these (or sensible defaults).

4. **Some strategies don't have closed-form payoffs.** Iron condor on an
   index ETF is closed-form. "Pairs trade XLE / XLK" is not — it requires
   cointegration estimation, which itself is regime-conditional. For
   these, fall back to a lookup table or skip the analytic step.

5. **Without a real account state, the constraint layer is theoretical.**
   We have `account.equity` from paper trading. We don't have realized-loss
   timeline, PDT history per ticker, or options approval level. Wash sale
   filtering needs this.

---

## 5. Concrete next steps

The scientifically correct order is:

**Step A: Numeric L0 obs**
- Each widget gains a `metrics: {}` block alongside `tags: []`.
- Backward-compatible: existing tag-based code still works.
- This UNLOCKS everything downstream.

**Step B: Daily regime vector**
- Pure function `regime_vector(date) → np.array(20)`.
- Stored alongside each lattice snapshot (one extra row in the snapshot
  envelope).
- Adds a `/api/lattice/regime` endpoint.

**Step C: Strategy quantitative profile**
- Each YAML entry gains:
  ```yaml
  quantitative_profile:
    payoff_class: covered_call | iron_condor | vertical_spread | ...
    greeks_template:
      delta: -0.4   # for short call leg
      theta: 0.05   # daily decay $/contract
      vega: -0.18
      gamma: -0.02
    expected_hold_days: 30
    breakeven_RV_pctile: 0.50  # below this RV, strategy profits
  ```
- For 36 strategies, this is ~1 day of careful YAML authoring.

**Step D: Closed-form scorer**
- Black-Scholes-derived `expected_utility(strategy_profile, regime_vector)`.
- Replaces `_score_strategy()`.
- Returns a `(score, breakdown_dict)` shape so the UI doesn't have to
  change.

**Step E: Bayesian prior from snapshot history**
- k-NN over past `regime_vector` storage.
- Empirical P&L lookup needs the backtest harness — that's the long pole.
- Until backtest exists, β = 1 (model only) is fine.

**Step F: Portfolio selection at the API edge**
- New endpoint `/api/strategies/portfolio?asOf=X&k=5` returns the
  diversified basket given today's regime.
- The Strategies tab's "today's relevant strategies" sort uses this output
  for the top-N chips.

The user's complaint about visual sameness vanishes after Step A + Step B
alone, because the regime vector is a continuous function of the day's
input data. The full scientific correctness needs all six steps.

---

## 6. What I'm NOT doing

- I'm not going to ship Step A piecemeal and call it done. The user
  rightly pushed back on incrementalism that doesn't change the fundamental
  problem.

- I'm not going to add more tag categories. The bug is that we're working
  in tag space at all, not that we're missing a tag.

- I'm not going to tune the matcher's bonuses (`+3` for horizon match,
  `+2` for options) — that's deck-chair-on-Titanic territory.

The next commit on this branch should be Step A + B together (numeric obs +
regime vector), with the new scorer (Step D) right behind. Steps C and E
can land in subsequent commits as the strategy YAML gets the quantitative
profile filled out.

---

## Appendix: References

- Hull, *Options, Futures and Other Derivatives* (10ed): closed-form
  payoffs and Black-Scholes pricing.
- Avellaneda & Lipkin, *A market-induced mechanism for stock pinning*: how
  realized-vs-implied vol differential drives short-vol P&L.
- Marcos López de Prado, *Advances in Financial Machine Learning*: regime
  fingerprinting, k-NN over feature vectors, the bias-variance trade-off
  in Bayesian shrinkage of model vs empirical scores.
- The CBOE VIX whitepaper for the term-structure / variance-swap framing.
- Asness/Frazzini/Pedersen, *Quality minus junk* and related: regime-
  conditional return decomposition; basis for the quantitative profile
  shape.
