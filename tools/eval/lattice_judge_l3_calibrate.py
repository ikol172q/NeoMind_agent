#!/usr/bin/env python3
"""Adversarial calibration for the L3 judge.

Feeds deliberately broken Toulmin calls and checks that each
axis correctly scores the intended failure mode ≤2. If the judge
passes a bad call, the rubric needs tightening.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.eval.lattice_judge import judge_calls  # noqa: E402


_THEMES: List[Dict[str, Any]] = [
    {"id": "theme_earnings_risk", "title": "Earnings risk", "severity": "warn",
     "narrative": "AAPL reports earnings in 3 days with elevated IV."},
    {"id": "theme_near_highs", "title": "Near-highs", "severity": "info",
     "narrative": "NVDA at 94th percentile of 52w range."},
    {"id": "theme_macro_regime", "title": "Macro regime", "severity": "warn",
     "narrative": "Weak breadth; only 25 of 98 S&P100 stocks advancing."},
]


_CASES: List[Dict[str, Any]] = [
    {
        "id": "case_vague_commentary",
        "expected_fail": "claim_actionability",
        "call": {
            "id": "call_001",
            "claim": "Markets are uncertain and investors should stay informed.",
            "grounds": ["theme_macro_regime"],
            "warrant": "Weak breadth combined with volatility creates an environment "
                       "where active monitoring matters more than usual.",
            "qualifier": "This applies through the end of the week.",
            "rebuttal": "If breadth improves to 60+ S&P100 stocks advancing.",
            "confidence": "medium",
            "time_horizon": "days",
        },
    },
    {
        "id": "case_cargo_cult_grounds",
        "expected_fail": "grounds_traceability",
        "call": {
            "id": "call_002",
            "claim": "Buy TSLA ahead of the Fed meeting next month.",
            "grounds": ["theme_earnings_risk", "theme_near_highs"],
            "warrant": "Macro Fed-cycle timing typically favors high-beta names "
                       "regardless of single-stock setups.",
            "qualifier": "Size at 2% of book, size down if VIX > 25.",
            "rebuttal": "If Fed signals a pause instead of a cut.",
            "confidence": "medium",
            "time_horizon": "weeks",
        },
    },
    {
        "id": "case_tautological_warrant",
        "expected_fail": "warrant_validity",
        "call": {
            "id": "call_003",
            "claim": "Hold AAPL through earnings.",
            "grounds": ["theme_earnings_risk"],
            "warrant": "Holding AAPL through earnings is the right call because "
                       "the appropriate action is to hold AAPL through earnings.",
            "qualifier": "If options are used, size puts at 0.5% of book.",
            "rebuttal": "If AAPL pre-announces a revenue miss.",
            "confidence": "medium",
            "time_horizon": "days",
        },
    },
    {
        "id": "case_generic_qualifier",
        "expected_fail": "qualifier_specificity",
        "call": {
            "id": "call_004",
            "claim": "Trim NVDA exposure by 25%.",
            "grounds": ["theme_near_highs"],
            "warrant": "Price near 52w highs with no fundamental re-rating is a "
                       "common setup for mean reversion in the following 2 weeks.",
            "qualifier": "Market conditions may change.",
            "rebuttal": "If NVDA breaks out above its prior 52w high on volume.",
            "confidence": "medium",
            "time_horizon": "days",
        },
    },
    {
        "id": "case_unfalsifiable_rebuttal",
        "expected_fail": "rebuttal_realism",
        "call": {
            "id": "call_005",
            "claim": "Hedge the book with SPY puts at 1% of NAV.",
            "grounds": ["theme_macro_regime"],
            "warrant": "Breadth narrowness historically precedes index-level "
                       "drawdowns, and cheap hedges compound carry into the drawdown.",
            "qualifier": "Use 30-day ATM puts, skip if VIX > 22 (premium too rich).",
            "rebuttal": "If unexpected events occur.",
            "confidence": "medium",
            "time_horizon": "weeks",
        },
    },
]


def main():
    calls = [c["call"] for c in _CASES]
    scores = judge_calls(calls, _THEMES, n_samples=3)
    failures: List[str] = []

    print("\n=== L3 judge adversarial calibration ===\n")
    header = (f"{'case':30} {'expected':26} {'act':>4} {'grnd':>4} "
              f"{'war':>4} {'qual':>4} {'reb':>4} {'result':>8}")
    print(header)
    print("-" * len(header))
    for case in _CASES:
        cid = case["call"]["id"]
        expected = case["expected_fail"]
        s = scores.get(cid, {})
        act = s.get("claim_actionability")
        grnd = s.get("grounds_traceability")
        war = s.get("warrant_validity")
        qual = s.get("qualifier_specificity")
        reb = s.get("rebuttal_realism")
        caught_val = s.get(expected)
        caught = (caught_val is not None) and caught_val <= 2
        status = "PASS" if caught else "FAIL"
        print(f"{case['id']:30} {expected:26} {act!s:>4} {grnd!s:>4} "
              f"{war!s:>4} {qual!s:>4} {reb!s:>4} {status:>8}")
        if not caught:
            failures.append(f"{case['id']}: expected {expected}<=2, got {caught_val}")

    print()
    if failures:
        print(f"{len(failures)}/{len(_CASES)} cases failed:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print(f"{len(_CASES)}/{len(_CASES)} adversarial cases caught. L3 rubric calibrated.")


if __name__ == "__main__":
    main()
