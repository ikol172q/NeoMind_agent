# Scorer v3 — Probabilistic Decision Score

**Date**: 2026-04-30
**Status**: design + implementation
**Author**: pair (Claude + irene)

## Why we're doing this

The v2 closed-form scorer has been validated on 5y of fingerprint history
(39 120 rows × 1304 days × 30 strategies) and **fails three out of six**
quantitative checks:

| metric | v2 result | what it means |
|---|---|---|
| Δ h-l at cutoff 3.0 | +1.18% / 30d, hit 74% | ✅ binary threshold has signal |
| Information Coefficient (per-day Spearman) | 0.0313 ± 0.31, 53% pos | ⚠️ borderline, threshold for "real alpha" is 0.05 |
| Decile monotonicity | non-monotonic (U-shaped) | ❌ **deciles 1-6 decline**, deciles 7-10 recover, **decile 1 (0.29-1.46) wins at +1.62%** |
| Long-short Sharpe | 1.77 annualised | ✅ but driven by U-shape extremes, not by ranking |
| Permutation null p-value (IC) | **1.0** (null mean 0.044 > obs 0.031) | ❌ **random shuffles give a HIGHER IC** than the actual model |
| Regime stratification | low-RA: -0.14 IC; mid: +0.07; high: +0.11 | ❌ system **anti-predictive in fear regimes** |

The verdict is sharp:

> The v2 scorer's RANKING is statistically indistinguishable from random
> (p≈1 vs permutation null), but it does have a usable BINARY signal at
> high cutoffs. The Sharpe headline number is artifact.

There are two failure modes here:

1. **Linear weighted sum can't represent the interactions.** v2 is
   `w_pnl × E_pnl + w_profit × P_profit + w_drawdown × VaR + w_regime × match`.
   That can't capture `high_vol × low_breadth → bad for momentum but good
   for mean-reversion`. Real finance has interactions everywhere.

2. **A single 0-10 score is lossy.** Compresses prob-of-profit, expected
   return, tail risk, and uncertainty into one number. The user can't
   tell whether a "fit 4.5" means "70% prob, +1% return, ±0.5% std" or
   "55% prob, +5% return, ±15% std" — but those are wildly different
   decisions.

Both must be addressed. **Just refitting the four scalar weights** would
be a band-aid: it might lift IC from 0.031 to ~0.05, but the model still
can't represent non-linear interactions, AND we still wouldn't
distinguish "high-confidence small win" from "low-confidence big win".

## Method survey

What we consider, with one-line pro / con each:

| # | method | strength | weakness | pick? |
|---|---|---|---|---|
| A | Hierarchical Bayesian (PyMC / NumPyro) | natural credible intervals, partial-pooling across strategies | heavy dep, slow inference (MCMC), overkill at 39k rows | later |
| B | **Gradient-boosted trees** (LightGBM / sklearn GBR) | handles non-linear interactions, fast, feature importance, well-understood | needs care w/ time series (no shuffled CV) | **YES** |
| C | Random Forest | similar to B but less precise, easier defaults | usually underperforms B in this regime | no |
| D | Neural net (MLP / TabNet / FT-Transformer) | flexible, handles big features | overkill at 39k rows, hard to validate | no |
| E | **Quantile regression** (sklearn `loss='quantile'`) | predicts tail directly (10/50/90) — exactly what user needs for risk | one model per quantile = 3× train cost | **YES** |
| F | Conformal prediction (cv-based) | **distribution-free** prediction intervals w/ coverage guarantee | wrap on top of B+E, not standalone | **YES** (wrapper) |
| G | Reinforcement learning (Q-learning over portfolios) | learns policy directly, optimizes for cumulative reward | needs ~10× more data; hard to interpret; risk of exploiting backtest artifacts | later |
| H | Information-theoretic feature selection (mutual information) | catches U-shape & non-monotone | only feature selection, not predictor | bonus |
| I | Causal inference (do-calculus / IV) | "would changing X cause Y?" not just correlation | can't do this without intervention data; we observe history only | no |

## v3 architecture: Probabilistic Decision Score (PDS)

Replace `score: float (0-10)` with a 4-field dict:

```jsonc
{
  "prob_profit_30d":  0.62,    // calibrated P(realized > 0)
  "expected_return":  0.014,   // median predicted realized return
  "tail_5pct":       -0.038,   // 5th percentile (CVaR proxy)
  "confidence":       0.78,    // 0..1 — width of CI / k-NN agreement
  // legacy 0-10 score retained for back-compat:
  "score":            5.6,     // = prob_profit × 10 (for sort)
}
```

Components:

1. **`prob_profit_30d`** — binary classifier (gradient boosting).
   - Features: 5 regime scores + strategy's quantitative_profile +
     payoff_class one-hot + days-since-event indicators.
   - Target: `realized_pnl_pct > 0`.
   - Calibrated via isotonic regression on a held-out fold so that
     `prob = 0.7` ⇒ ~70% actually positive.
2. **`expected_return`** — quantile regression, 50th percentile.
   - GBR with `loss="quantile"`, `alpha=0.5`.
   - More robust than mean to outliers.
3. **`tail_5pct`** — quantile regression, 5th percentile.
   - Same model class, `alpha=0.05`.
   - This IS the user's risk number. "We expect 5% of the time to be
     worse than -3.8%."
4. **`confidence`** — k-NN agreement.
   - Find K nearest historical days by regime-distance.
   - Confidence = 1 − std(realized P&L of the K neighbors) ÷ scale.
   - Low confidence = highly variable history → don't trust the point
     estimate.

Training scheme:

- **Walk-forward purged CV**: 12 folds, each fold trains on data
  ending T days before the test fold to avoid look-ahead through the
  30-day forward return. Standard Lopez de Prado purging.
- **One model per payoff_class family** (long-only, covered_call,
  iron_condor, momentum, mean_reversion, hedge). Within a family the
  decision logic is similar; across families it isn't.
- **Hyperparameter search**: small grid (n_estimators ∈ {100, 200},
  max_depth ∈ {3, 5}, learning_rate ∈ {0.05, 0.1}). Picked by held-out IC.

Acceptance criteria for v3:

- per-day IC mean ≥ **0.06** (vs v2 0.031)
- decile monotonicity: spearman(decile, mean_realized) ≥ **0.7**
- permutation null p-value ≤ **0.05**
- regime stratification: IC ≥ **0** in all three risk-appetite buckets
- if any of these fail, ROLLBACK to v2 binary-cutoff signal (with
  "use as filter, not ranker" UI banner)

## What the user sees in the UI

Strategy cards become richer:

```
ETF 备兑开仓                                 [unverified]
  prob ≥0     74% ✓   median +1.4%   tail -2.1%   confidence 82%
  fit 5.4 / 10  (= prob × 10, used only for sort)
```

The PortfolioWidget MMR alternatives get a similar four-pack.

A new toggle in Settings: "Show me uncertainty bands?" — when on, every
score is shown with its 90% CI from the quantile model.

## Implementation plan (this commit)

1. ✅ Design doc (this file)
2. `agent/finance/regime/scorer_v3.py`
   - `train_pds(rows, save_to=...)` — fit & save
   - `score_pds(fingerprint, strategy)` — predict probabilistic 4-tuple
3. Walk-forward harness in `backtest.py`:
   - `compare_v2_v3(hold_days=30)` runs both on the same 39k rows
4. `regime_train_v3.command` — `.venv-host` script that retrains and
   stores model artifacts in `~/.neomind/fin/models/scorer_v3.pkl`
5. `/api/regime/v3/score` endpoint
6. UI: extend `PortfolioWidget` to display the 4-tuple + uncertainty
7. Re-run `regime_validate.command` after deployment to confirm
   acceptance criteria

## What we're NOT doing (yet)

- Bayesian hierarchical model — defer until we have ≥3y of *real*
  realized P&L, not proxy. Proxy P&L's biases would mislead a Bayesian
  model with strong priors.
- RL — needs more data + a real broker simulator with slippage.
- Per-strategy autoencoder for similarity — interesting but premature
  optimization vs the current MMR similarity.
- LightGBM — sklearn's GBR is sufficient for this scale; saves a
  dependency. We can swap in LightGBM later via a 2-line edit.

## Trade-off note

A tree model fit on PROXY P&L will inherit the proxy's biases. We're
explicitly aware: any signal v3 finds might be "the proxy's quirks"
not "real edge." Mitigation:

- The IC and decile metrics use the same proxy on both sides, so they
  measure model quality, not absolute P&L.
- When real broker P&L flows in (Phase G), retrain on that.
- Until then: v3 is "less wrong than v2", not "right."
