"""Scorer v3 — Probabilistic Decision Score (PDS).

Replaces v2's single 0-10 closed-form score with a 4-tuple:

    {
      "prob_profit_30d":  0.62,     # calibrated P(realized > 0)
      "expected_return":  0.014,    # 50th-percentile predicted return
      "tail_5pct":       -0.038,    # 5th-percentile (CVaR proxy)
      "confidence":       0.78,     # 0..1, from k-NN regime agreement
      "score":            6.2,      # = prob_profit × 10  (back-compat)
    }

Trained on the ``backtest_results`` SQLite table populated by
``regime_backtest.command``.

Key design choices (rationale in
``docs/design/2026-04-30_scorer-v3-probabilistic.md``):

  • One model PER payoff-class family (covered_call, credit_spread,
    long_vol, dca, momentum, mean_reversion, hedge).  Within a family
    the decision logic is similar; across families it isn't.
  • GradientBoostingClassifier for prob_profit (handles non-linear
    interactions, fast at 39k rows).
  • GradientBoostingRegressor with quantile loss for the 50/5 percentile
    heads.
  • Walk-forward purged time-series CV: train on 80% by date, test on
    most-recent 20%, with a `purge_days` gap to avoid leakage through
    the 30-day forward return.
  • Isotonic regression to calibrate prob_profit on the test fold.
  • Per-bucket k-NN over fingerprint for confidence (cheap).
"""
from __future__ import annotations

import json
import logging
import math
import os
import pickle
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ── feature engineering ──────────────────────────────────────────


_PAYOFF_FAMILIES: Dict[str, str] = {
    # covered-call family (short-vol, capped upside)
    "covered_call":               "covered_call",
    "covered_call_etf":           "covered_call",
    "covered_strangle":           "covered_call",
    "cash_secured_put":           "covered_call",
    "wheel":                      "covered_call",
    # credit spreads (defined-risk short-vol)
    "vertical_bull_put_spread":   "credit_spread",
    "vertical_bear_call_spread":  "credit_spread",
    "iron_condor":                "credit_spread",
    "iron_condor_index":          "credit_spread",
    "iron_butterfly":             "credit_spread",
    "credit_spread":              "credit_spread",
    # long-vol
    "long_call":                  "long_vol",
    "long_put":                   "long_vol",
    "long_straddle":              "long_vol",
    "long_strangle":              "long_vol",
    # debit spreads (theta-friendly directional)
    "calendar_spread":            "debit_spread",
    "diagonal_spread":            "debit_spread",
    "vertical_bull_call_spread":  "debit_spread",
    "vertical_bear_put_spread":   "debit_spread",
    "debit_spread":               "debit_spread",
    # long-only / DCA / passive
    "dca":                        "long_only",
    "buy_and_hold":               "long_only",
    "lazy_portfolio_three_fund":  "long_only",
    "target_date_fund":           "long_only",
    "permanent_portfolio":        "long_only",
    "dollar_cost_averaging_index":"long_only",
    "dividend_growth_etf":        "long_only",
    # momentum / trend
    "momentum_breakout":          "momentum",
    "trend_following":            "momentum",
    "swing_breakout":             "momentum",
    "fifty_two_week_high_breakout_swing": "momentum",
    "cross_sectional_momentum":   "momentum",
    "sector_rotation":            "momentum",
    "sector_rotation_business_cycle": "momentum",
    # mean reversion / value
    "mean_reversion":             "mean_reversion",
    "mean_reversion_oversold_bounce_rsi2": "mean_reversion",
    "low_volatility_factor":      "mean_reversion",
    "value_factor":               "mean_reversion",
    # hedge
    "bear_market_hedge":          "hedge",
    "tail_risk_hedge":            "hedge",
    # bond / event
    "bond_ladder":                "bond",
    "treasury_ladder":            "bond",
    "event_fade":                 "event",
    "event_drift":                "event",
}


def _payoff_family(payoff_class: Optional[str]) -> str:
    if not payoff_class:
        return "other"
    return _PAYOFF_FAMILIES.get(payoff_class, "other")


def _feature_vector(
    fp: Dict[str, Any],
    strategy: Dict[str, Any],
    *,
    feature_set: str = "full",
) -> List[float]:
    """Build a numeric feature row for one (fingerprint, strategy) pair.

    feature_set:
      "full"        — all 15 features (default)
      "regime_only" — only 5 regime bucket scores (positions 0-4)
      "family_only" — only payoff family one-hot (positions 12-14)
      "no_family"   — drop family one-hot (positions 0-11)
      "interaction" — regime × strategy_sensitivity products (5 features)

    Features (15 numbers):
      0-4:   regime bucket scores (5)
      5-9:   regime sensitivities from quantitative_profile (5)
      10:    expected_hold_days
      11:    breakeven_RV_pctile
      12-14: payoff-class-specific intercepts (one-hot for top 3 freq)
    """
    profile = strategy.get("quantitative_profile") or {}
    sens = profile.get("regime_sensitivity", {}) or {}
    keys = ("risk_appetite_score", "volatility_regime_score",
            "breadth_score", "event_density_score", "flow_score")
    sens_keys = ("risk_appetite", "volatility_regime",
                 "breadth", "event_density", "flow")

    regime_vals = [float(fp.get(k)) if fp.get(k) is not None else 50.0
                   for k in keys]
    sens_vals = [float(sens.get(k, 0.0)) for k in sens_keys]
    hold_days = float(profile.get("expected_hold_days") or 30)
    rv_pct = float(profile.get("breakeven_RV_pctile") or 0.5)
    fam = _payoff_family(profile.get("payoff_class"))
    fam_vals = [
        1.0 if fam == "covered_call"   else 0.0,
        1.0 if fam == "long_only"      else 0.0,
        1.0 if fam == "credit_spread"  else 0.0,
    ]

    if feature_set == "regime_only":
        return regime_vals
    if feature_set == "family_only":
        return fam_vals
    if feature_set == "no_family":
        return regime_vals + sens_vals + [hold_days, rv_pct]
    if feature_set == "interaction":
        # 5 features: regime[i] * sensitivity[i] (centered at 50)
        return [(r - 50.0) / 50.0 * s for r, s in zip(regime_vals, sens_vals)]
    # full
    return regime_vals + sens_vals + [hold_days, rv_pct] + fam_vals


FEATURE_NAMES = [
    "ra_score", "vol_score", "breadth_score", "event_score", "flow_score",
    "sens_ra", "sens_vol", "sens_breadth", "sens_event", "sens_flow",
    "expected_hold_days", "breakeven_RV_pctile",
    "is_covered_call", "is_long_only", "is_credit_spread",
]


# ── training ─────────────────────────────────────────────────────


def _model_dir() -> str:
    """Where pickled models live on disk."""
    base = os.path.expanduser("~/.neomind/fin/models")
    os.makedirs(base, exist_ok=True)
    return base


def _isotonic_calibrate(
    raw_scores: List[float],
    y_true: List[int],
) -> List[Tuple[float, float]]:
    """Pool-Adjacent-Violators isotonic regression.  Returns a list of
    (threshold, calibrated_prob) pairs that we look up at inference."""
    n = len(raw_scores)
    if n == 0:
        return []
    pairs = sorted(zip(raw_scores, y_true), key=lambda p: p[0])
    xs = [p[0] for p in pairs]
    ys = [float(p[1]) for p in pairs]
    weights = [1.0] * n
    # Pool-Adjacent-Violators
    i = 0
    while i < len(ys) - 1:
        if ys[i] > ys[i + 1]:
            total_w = weights[i] + weights[i + 1]
            avg = (ys[i] * weights[i] + ys[i + 1] * weights[i + 1]) / total_w
            ys[i] = avg
            weights[i] = total_w
            del ys[i + 1]
            del xs[i + 1]
            del weights[i + 1]
            if i > 0:
                i -= 1
        else:
            i += 1
    return list(zip(xs, ys))


def _isotonic_apply(
    table: List[Tuple[float, float]],
    raw: float,
) -> float:
    if not table:
        return 0.5
    # Linear interpolation between calibration anchors.
    if raw <= table[0][0]:
        return table[0][1]
    if raw >= table[-1][0]:
        return table[-1][1]
    for i in range(len(table) - 1):
        x0, y0 = table[i]
        x1, y1 = table[i + 1]
        if x0 <= raw <= x1:
            if x1 == x0:
                return y0
            t = (raw - x0) / (x1 - x0)
            return y0 + t * (y1 - y0)
    return 0.5


def train_pds(
    *,
    purge_days: int = 35,
    test_frac:  float = 0.2,
    save_dir:   Optional[str] = None,
) -> Dict[str, Any]:
    """Train the v3 PDS model from ``backtest_results`` rows.

    Strategy: walk-forward time split.  Order all rows by
    ``fingerprint_date``, hold out the most-recent ``test_frac``
    fraction as test, and ``purge_days`` between train and test to
    block 30d-forward-return leakage.

    Trains ONE model per payoff-class family (or skips the family if
    fewer than 200 training rows).

    Returns a summary with per-family test metrics.  Side effect:
    writes pickled models to ``save_dir`` (default
    ``~/.neomind/fin/models/scorer_v3``).
    """
    from agent.finance.persistence import connect
    from agent.finance.lattice.strategy_matcher import _load_strategies

    # Late import — sklearn is heavy.
    try:
        from sklearn.ensemble import (
            GradientBoostingClassifier,
            GradientBoostingRegressor,
        )
    except ImportError as exc:
        raise RuntimeError(
            f"sklearn not available in this venv ({exc}). "
            f"Run: .venv-host/bin/pip install scikit-learn"
        )

    save_dir = save_dir or os.path.join(_model_dir(), "scorer_v3")
    os.makedirs(save_dir, exist_ok=True)

    catalog = {s["id"]: s for s in _load_strategies(include_unverified=True)}

    # ── Pull full dataset ──
    with connect() as conn:
        cur = conn.execute(
            """SELECT fingerprint_date, strategy_id,
                      predicted_score, realized_pnl_pct, underlying_return
                 FROM backtest_results
                 WHERE hold_days = 30 AND realized_pnl_pct IS NOT NULL"""
        )
        all_rows = [dict(r) for r in cur.fetchall()]

        fps_cur = conn.execute(
            "SELECT * FROM regime_fingerprints"
        )
        fp_by_date = {r["fingerprint_date"]: dict(r) for r in fps_cur.fetchall()}

    if len(all_rows) < 1000:
        return {"error": f"only {len(all_rows)} rows — run regime_backtest first"}

    # Attach fingerprints + features + family
    enriched: List[Dict[str, Any]] = []
    for r in all_rows:
        fp = fp_by_date.get(r["fingerprint_date"])
        if not fp:
            continue
        strat = catalog.get(r["strategy_id"])
        if not strat:
            continue
        fam = _payoff_family((strat.get("quantitative_profile") or {}).get("payoff_class"))
        feat = _feature_vector(fp, strat)
        enriched.append({
            "date":     r["fingerprint_date"],
            "sid":      r["strategy_id"],
            "family":   fam,
            "x":        feat,
            "y_real":   float(r["realized_pnl_pct"]),
            "y_bin":    int(r["realized_pnl_pct"] > 0),
        })

    if not enriched:
        return {"error": "no rows after enrichment"}

    enriched.sort(key=lambda e: e["date"])
    n = len(enriched)
    cut_idx = int(n * (1.0 - test_frac))
    cut_date = enriched[cut_idx]["date"]
    purge_until = _add_days(cut_date, -purge_days)
    train_rows = [e for e in enriched if e["date"] <= purge_until]
    test_rows  = [e for e in enriched[cut_idx:]]

    logger.info(
        "[V3-TRAIN] n_total=%d n_train=%d n_test=%d cut_date=%s purge_until=%s",
        n, len(train_rows), len(test_rows), cut_date, purge_until,
    )

    # Group by family
    by_fam_train: Dict[str, List[Dict[str, Any]]] = {}
    by_fam_test:  Dict[str, List[Dict[str, Any]]] = {}
    for r in train_rows:
        by_fam_train.setdefault(r["family"], []).append(r)
    for r in test_rows:
        by_fam_test.setdefault(r["family"], []).append(r)

    family_metrics: Dict[str, Dict[str, Any]] = {}
    models: Dict[str, Dict[str, Any]] = {}

    for fam, train_fam in by_fam_train.items():
        if len(train_fam) < 200:
            logger.info("[V3-TRAIN] skip %s (only %d train rows)", fam, len(train_fam))
            continue
        test_fam = by_fam_test.get(fam, [])

        Xtr = [r["x"] for r in train_fam]
        ytr_bin = [r["y_bin"]  for r in train_fam]
        ytr_ret = [r["y_real"] for r in train_fam]

        # ── Probability of profit ──
        clf = GradientBoostingClassifier(
            n_estimators=120, max_depth=3, learning_rate=0.08,
            random_state=42,
        )
        clf.fit(Xtr, ytr_bin)

        # ── Quantile heads — median + 5th percentile ──
        med = GradientBoostingRegressor(
            loss="quantile", alpha=0.5,
            n_estimators=120, max_depth=3, learning_rate=0.08,
            random_state=42,
        )
        tail = GradientBoostingRegressor(
            loss="quantile", alpha=0.05,
            n_estimators=120, max_depth=3, learning_rate=0.08,
            random_state=42,
        )
        med.fit(Xtr, ytr_ret)
        tail.fit(Xtr, ytr_ret)

        # ── Calibrate prob_profit on TEST fold ──
        if test_fam:
            Xte = [r["x"] for r in test_fam]
            yte_bin = [r["y_bin"]  for r in test_fam]
            yte_ret = [r["y_real"] for r in test_fam]
            raw_proba = clf.predict_proba(Xte)[:, 1].tolist()
            iso_table = _isotonic_calibrate(raw_proba, yte_bin)

            # Test metrics
            cal_proba = [_isotonic_apply(iso_table, p) for p in raw_proba]
            med_pred  = med.predict(Xte).tolist()
            tail_pred = tail.predict(Xte).tolist()

            test_metrics = {
                "n":              len(test_fam),
                "auc_proxy":      _auc(raw_proba, yte_bin),
                "mean_pred_prob": round(sum(cal_proba) / len(cal_proba), 3),
                "mean_realized":  round(sum(yte_ret)   / len(yte_ret),   5),
                "calibration_brier": _brier(cal_proba, yte_bin),
                "median_pred_avg":   round(sum(med_pred)  / len(med_pred),  5),
                "tail_pred_avg":     round(sum(tail_pred) / len(tail_pred), 5),
                "ic_test":           _spearman(cal_proba, yte_ret),
            }
        else:
            iso_table = []
            test_metrics = {"n": 0, "skip": "no_test_rows"}

        # Persist
        bundle = {
            "family":     fam,
            "feature_names": FEATURE_NAMES,
            "clf":        pickle.dumps(clf),
            "med":        pickle.dumps(med),
            "tail":       pickle.dumps(tail),
            "iso_table":  iso_table,
        }
        with open(os.path.join(save_dir, f"{fam}.pkl"), "wb") as f:
            pickle.dump(bundle, f)
        models[fam] = bundle
        family_metrics[fam] = {
            "n_train": len(train_fam),
            "n_test":  len(test_fam),
            "test":    test_metrics,
        }
        logger.info("[V3-TRAIN] family=%s done — %s", fam, test_metrics)

    # Save metadata
    meta = {
        "schema":  "scorer_v3.v1",
        "trained_at": _now_iso(),
        "purge_days": purge_days,
        "test_frac":  test_frac,
        "n_total":    n,
        "cut_date":   cut_date,
        "families":   family_metrics,
    }
    with open(os.path.join(save_dir, "meta.json"), "w") as f:
        json.dump(meta, f, indent=2, default=str)

    return meta


# ── inference ────────────────────────────────────────────────────


_LOADED_MODELS: Optional[Dict[str, Dict[str, Any]]] = None


def _load_models(save_dir: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    global _LOADED_MODELS
    if _LOADED_MODELS is not None:
        return _LOADED_MODELS
    save_dir = save_dir or os.path.join(_model_dir(), "scorer_v3")
    if not os.path.isdir(save_dir):
        _LOADED_MODELS = {}
        return _LOADED_MODELS
    bundles: Dict[str, Dict[str, Any]] = {}
    for fname in os.listdir(save_dir):
        if not fname.endswith(".pkl"):
            continue
        path = os.path.join(save_dir, fname)
        try:
            with open(path, "rb") as f:
                b = pickle.load(f)
            b["clf"]  = pickle.loads(b["clf"])
            b["med"]  = pickle.loads(b["med"])
            b["tail"] = pickle.loads(b["tail"])
            bundles[b["family"]] = b
        except Exception as exc:
            logger.warning("failed to load %s: %s", fname, exc)
    _LOADED_MODELS = bundles
    return bundles


def reload_models() -> int:
    """Force reload (called by API after retrain)."""
    global _LOADED_MODELS
    _LOADED_MODELS = None
    return len(_load_models())


def score_pds(
    fingerprint: Dict[str, Any],
    strategy:    Dict[str, Any],
    *,
    knn_k: int = 8,
    skip_confidence: bool = False,
) -> Dict[str, Any]:
    """Predict the 4-tuple Probabilistic Decision Score.

    Set ``skip_confidence=True`` for batch / backtest scoring to skip
    the per-call SQL kNN scan (which is O(N) over backtest_results).
    """
    profile = strategy.get("quantitative_profile") or {}
    fam = _payoff_family(profile.get("payoff_class"))
    bundles = _load_models()
    bundle = bundles.get(fam)

    feat = _feature_vector(fingerprint, strategy)

    if bundle is None:
        # No model for this family — fall back to v2 score wrapped.
        from agent.finance.regime.scorer import score_strategy as v2_score
        v2 = v2_score(strategy, fingerprint)
        return {
            "prob_profit_30d":  None,
            "expected_return":  None,
            "tail_5pct":        None,
            "confidence":       None,
            "score":            v2["score"],
            "scorer":           "v2_fallback",
            "reason":           f"no v3 model for family={fam}",
        }

    raw_p = bundle["clf"].predict_proba([feat])[0][1]
    cal_p = _isotonic_apply(bundle["iso_table"], raw_p)
    med   = float(bundle["med"].predict([feat])[0])
    tail  = float(bundle["tail"].predict([feat])[0])

    # Confidence from k-NN agreement on regime distance.
    confidence = None if skip_confidence else _knn_confidence(fingerprint, knn_k)

    return {
        "prob_profit_30d":  round(cal_p, 4),
        "expected_return":  round(med, 5),
        "tail_5pct":        round(tail, 5),
        "confidence":       round(confidence, 3) if confidence is not None else None,
        "score":            round(cal_p * 10.0, 2),
        "scorer":           "v3_pds",
        "family":           fam,
        "raw_prob":         round(raw_p, 4),
    }


# ── auxiliary ────────────────────────────────────────────────────


def diagnose_v3(
    *,
    purge_days: int = 35,
    test_frac:  float = 0.2,
    n_permutations: int = 100,
) -> Dict[str, Any]:
    """Decompose v3's high IC: is it real regime signal, or strategy
    memorization?  Runs four ablations + permutation null + per-strategy
    breakdown.

    Returns:
      • full_ic      / full_decile_rho            (baseline = current v3)
      • regime_ic    / regime_decile_rho          (only 5 regime features)
      • family_ic    / family_decile_rho          (only payoff one-hot)
      • no_family_ic / no_family_decile_rho       (drop family, keep regime + per-strategy)
      • interaction_ic / interaction_decile_rho   (only regime × sensitivity products)
      • within_strategy_ic_mean: avg per-strategy IC over time (regime-driven)
      • per_strategy_ic_top3 / bottom3: who's best / worst at within-day prediction
      • permutation_null_ic_mean / p_value_full_ic
      • family_breakdown: per family, hold-out IC

    Interpretation guide:
      - If full_ic ≫ regime_ic ≈ family_ic: model is memorizing strategy means
      - If regime_ic ≈ full_ic: regime features carry the signal — real alpha proxy
      - If full_ic ≫ within_strategy_ic_mean: cross-strategy ranking is memorization
      - If p_value_full_ic ≥ 0.05: indistinguishable from random
    """
    from agent.finance.persistence import connect
    from agent.finance.lattice.strategy_matcher import _load_strategies

    try:
        from sklearn.ensemble import GradientBoostingRegressor
    except ImportError:
        return {"error": "sklearn missing"}

    catalog = {s["id"]: s for s in _load_strategies(include_unverified=True)}

    with connect() as conn:
        cur = conn.execute(
            """SELECT b.fingerprint_date, b.strategy_id,
                      b.realized_pnl_pct,
                      f.risk_appetite_score, f.volatility_regime_score,
                      f.breadth_score, f.event_density_score, f.flow_score
                 FROM backtest_results b
                 JOIN regime_fingerprints f
                   ON b.fingerprint_date = f.fingerprint_date
                 WHERE b.hold_days = 30 AND b.realized_pnl_pct IS NOT NULL""",
        )
        rows = [dict(r) for r in cur.fetchall()]

    if not rows:
        return {"error": "no rows"}

    rows.sort(key=lambda r: r["fingerprint_date"])
    n = len(rows)
    cut_idx = int(n * (1.0 - test_frac))
    cut_date = rows[cut_idx]["fingerprint_date"]
    purge_until = _add_days(cut_date, -purge_days)
    train_rows = [r for r in rows if r["fingerprint_date"] <= purge_until]
    test_rows = rows[cut_idx:]

    def _fp_dict(r):
        return {
            "risk_appetite_score":         r["risk_appetite_score"],
            "volatility_regime_score":     r["volatility_regime_score"],
            "breadth_score":               r["breadth_score"],
            "event_density_score":         r["event_density_score"],
            "flow_score":                  r["flow_score"],
        }

    def _train_predict(feature_set: str):
        Xtr = []
        ytr = []
        for r in train_rows:
            strat = catalog.get(r["strategy_id"])
            if not strat:
                continue
            Xtr.append(_feature_vector(_fp_dict(r), strat, feature_set=feature_set))
            ytr.append(float(r["realized_pnl_pct"]))
        if not Xtr:
            return None, None
        model = GradientBoostingRegressor(
            n_estimators=80, max_depth=3, learning_rate=0.08,
            random_state=42,
        )
        model.fit(Xtr, ytr)

        Xte = []
        yte = []
        for r in test_rows:
            strat = catalog.get(r["strategy_id"])
            if not strat:
                continue
            Xte.append(_feature_vector(_fp_dict(r), strat, feature_set=feature_set))
            yte.append(float(r["realized_pnl_pct"]))
        preds = model.predict(Xte).tolist()
        return preds, yte

    # 1) Run 5 ablations
    ablations = {}
    for fs in ["full", "regime_only", "family_only", "no_family", "interaction"]:
        preds, yte = _train_predict(fs)
        if preds is None:
            ablations[fs] = {"error": "no train rows"}
            continue
        ic = _spearman(preds, yte)
        # decile rho
        n_te = len(preds)
        srt = sorted(zip(preds, yte), key=lambda p: p[0])
        deciles = []
        for d in range(10):
            lo = int(n_te *  d      / 10)
            hi = int(n_te * (d + 1) / 10)
            chunk = srt[lo:hi]
            if chunk:
                deciles.append(sum(c[1] for c in chunk) / len(chunk))
        decile_rho = _spearman(list(range(len(deciles))), deciles) if len(deciles) >= 5 else None
        ablations[fs] = {
            "n_test":            n_te,
            "ic":                ic,
            "decile_rho":        decile_rho,
            "decile_means":      [round(d, 5) for d in deciles],
        }

    # 2) Within-strategy IC: for each strategy, IC of its OWN time series
    by_strategy: Dict[str, List[Dict[str, Any]]] = {}
    full_preds, _ = _train_predict("full")
    full_yte_strat = [r["strategy_id"] for r in test_rows
                      if catalog.get(r["strategy_id"])]
    full_yte = [float(r["realized_pnl_pct"]) for r in test_rows
                if catalog.get(r["strategy_id"])]
    for sid, p, y in zip(full_yte_strat, full_preds, full_yte):
        by_strategy.setdefault(sid, []).append((p, y))
    within: Dict[str, float] = {}
    for sid, pairs in by_strategy.items():
        if len(pairs) < 30:
            continue
        rho = _spearman([p[0] for p in pairs], [p[1] for p in pairs])
        if rho is not None:
            within[sid] = rho
    if within:
        within_mean = sum(within.values()) / len(within)
        sorted_within = sorted(within.items(), key=lambda kv: -kv[1])
        top3 = sorted_within[:3]
        bot3 = sorted_within[-3:]
    else:
        within_mean = None
        top3 = []
        bot3 = []

    # 3) Permutation null on FULL feature set
    import random
    rng = random.Random(42)
    null_ics: List[float] = []
    if full_preds:
        for _ in range(n_permutations):
            shuffled = list(full_preds)
            rng.shuffle(shuffled)
            ic = _spearman(shuffled, full_yte)
            if ic is not None:
                null_ics.append(ic)
    obs_ic = ablations.get("full", {}).get("ic") or 0
    if null_ics:
        p_val = sum(1 for x in null_ics if abs(x) >= abs(obs_ic)) / len(null_ics)
        null_mean = sum(null_ics) / len(null_ics)
    else:
        p_val = None
        null_mean = None

    # 4) Per-day cross-strategy IC (this is "alpha" in quant terms)
    test_by_date: Dict[str, List[tuple]] = {}
    for sid, p, y in zip(full_yte_strat, full_preds, full_yte):
        # find date — match index
        pass
    # Re-walk to get date pairing
    full_predictions_by_date: Dict[str, List[tuple]] = {}
    idx = 0
    for r in test_rows:
        if not catalog.get(r["strategy_id"]):
            continue
        if idx >= len(full_preds):
            break
        full_predictions_by_date.setdefault(r["fingerprint_date"], []).append(
            (full_preds[idx], float(r["realized_pnl_pct"]))
        )
        idx += 1

    per_day_ics: List[float] = []
    for date, pairs in full_predictions_by_date.items():
        if len(pairs) < 5:
            continue
        ic = _spearman([p[0] for p in pairs], [p[1] for p in pairs])
        if ic is not None:
            per_day_ics.append(ic)
    if per_day_ics:
        per_day_ic_mean = sum(per_day_ics) / len(per_day_ics)
        per_day_ic_pos  = sum(1 for x in per_day_ics if x > 0) / len(per_day_ics)
    else:
        per_day_ic_mean = None
        per_day_ic_pos  = None

    return {
        "n_train":  len(train_rows),
        "n_test":   len(test_rows),
        "cut_date": cut_date,
        "ablations": ablations,
        "within_strategy_ic": {
            "mean":       round(within_mean, 4) if within_mean is not None else None,
            "n":          len(within),
            "top3":       [{"sid": k, "ic": round(v, 4)} for k, v in top3],
            "bottom3":    [{"sid": k, "ic": round(v, 4)} for k, v in bot3],
        },
        "per_day_cross_strategy_ic": {
            "mean":       round(per_day_ic_mean, 4) if per_day_ic_mean is not None else None,
            "pct_positive": round(per_day_ic_pos, 3) if per_day_ic_pos is not None else None,
            "n_days":     len(per_day_ics),
            "interpretation": (
                "This is the 'true alpha' metric: across strategies on the same day, "
                "does the model's ranking match realized?"
            ),
        },
        "permutation_null_full": {
            "obs_ic":       round(obs_ic, 4),
            "null_mean":    round(null_mean, 4) if null_mean is not None else None,
            "p_value":      round(p_val, 4) if p_val is not None else None,
            "n_perms":      n_permutations,
        },
    }


def _knn_confidence(fp: Dict[str, Any], k: int = 8) -> float:
    """Confidence proxy: 1 − std(realized P&L of K most-similar past
    days) / scale.  Capped to [0, 1]."""
    from agent.finance.persistence import connect

    target = [
        fp.get("risk_appetite_score") or 50.0,
        fp.get("volatility_regime_score") or 50.0,
        fp.get("breadth_score") or 50.0,
        fp.get("event_density_score") or 50.0,
        fp.get("flow_score") or 50.0,
    ]
    target_date = fp.get("fingerprint_date")
    sql = (
        "SELECT b.realized_pnl_pct, "
        "       f.risk_appetite_score, f.volatility_regime_score, "
        "       f.breadth_score, f.event_density_score, f.flow_score "
        "FROM backtest_results b "
        "JOIN regime_fingerprints f ON b.fingerprint_date = f.fingerprint_date "
        "WHERE b.hold_days=30 AND b.realized_pnl_pct IS NOT NULL"
    )
    with connect() as conn:
        rows = conn.execute(sql).fetchall()
    if not rows:
        return 0.5
    scored: List[Tuple[float, float]] = []  # (distance, realized)
    for r in rows:
        if target_date and r.keys() and r["realized_pnl_pct"] is None:
            continue
        v = [
            r["risk_appetite_score"] or 50.0,
            r["volatility_regime_score"] or 50.0,
            r["breadth_score"] or 50.0,
            r["event_density_score"] or 50.0,
            r["flow_score"] or 50.0,
        ]
        d = math.sqrt(sum((a - b) ** 2 for a, b in zip(target, v)))
        scored.append((d, float(r["realized_pnl_pct"])))
    scored.sort(key=lambda x: x[0])
    nb = scored[:max(3, k)]
    if not nb:
        return 0.5
    rels = [r for _, r in nb]
    mean = sum(rels) / len(rels)
    var  = sum((r - mean) ** 2 for r in rels) / max(1, len(rels) - 1)
    std  = math.sqrt(var)
    # Confidence: collapse std into [0,1] — std=0.05 → conf~0.5;
    # std=0 → 1.0; std=0.10+ → 0.0.
    return max(0.0, min(1.0, 1.0 - std / 0.10))


def _spearman(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    def rank(v):
        order = sorted(range(n), key=lambda i: v[i])
        ranks = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1
            for kk in range(i, j + 1):
                ranks[order[kk]] = avg
            i = j + 1
        return ranks
    rx, ry = rank(xs), rank(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    sx2 = sum((x - mx) ** 2 for x in rx)
    sy2 = sum((y - my) ** 2 for y in ry)
    if sx2 == 0 or sy2 == 0:
        return None
    sxy = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    return round(sxy / math.sqrt(sx2 * sy2), 4)


def _auc(scores, labels):
    pos = [s for s, l in zip(scores, labels) if l == 1]
    neg = [s for s, l in zip(scores, labels) if l == 0]
    if not pos or not neg:
        return None
    n = 0
    win = 0
    for p in pos:
        for q in neg:
            n += 1
            if p > q:
                win += 1
            elif p == q:
                win += 0.5
    return round(win / n, 4)


def _brier(probs, labels):
    if not probs:
        return None
    s = sum((p - l) ** 2 for p, l in zip(probs, labels)) / len(probs)
    return round(s, 5)


def _add_days(iso_date: str, delta: int) -> str:
    from datetime import date, timedelta
    return (date.fromisoformat(iso_date) + timedelta(days=delta)).isoformat()


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
