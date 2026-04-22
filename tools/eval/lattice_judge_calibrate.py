#!/usr/bin/env python3
"""Adversarial calibration for the L2 judge.

Feeds the judge a set of deliberately broken themes and checks that
each axis correctly scores ≤2 on the intended failure mode. If the
judge passes a bad theme, the rubric needs tightening.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.eval.lattice_judge import judge_themes  # noqa: E402


# Synthetic observations used as members for adversarial themes
_OBS: List[Dict[str, Any]] = [
    {
        "id": "obs_fake_a",
        "kind": "technical_near_52w_high",
        "text": "AAPL at 95.2% of 52w range.",
        "tags": ["symbol:AAPL", "technical:near_52w_high"],
        "severity": "info",
    },
    {
        "id": "obs_fake_b",
        "kind": "earnings_soon",
        "text": "MSFT reports earnings in 3 days.",
        "tags": ["symbol:MSFT", "risk:earnings", "timescale:days"],
        "severity": "warn",
    },
    {
        "id": "obs_fake_c",
        "kind": "sector_mover",
        "text": "Energy sector up 1.45% today (top-ranked).",
        "tags": ["sector:Energy", "direction:up", "timescale:intraday"],
        "severity": "info",
    },
]


_CASES: List[Dict[str, Any]] = [
    {
        "id": "case_hallucinated_number",
        "expected_fail": "citation_validity",
        "theme": {
            "id": "theme_bad_cite",
            "title": "Earnings risk",
            "narrative": "MSFT reports earnings in 7 days, with AAPL up 42.7% YTD.",
            "narrative_source": "llm",
            "severity": "warn",
            "cited_numbers": ["7", "42.7"],
            "tags": ["risk:earnings"],
            "members": [
                {"obs_id": "obs_fake_b", "weight": 1.0},
            ],
        },
    },
    {
        "id": "case_grab_bag_members",
        "expected_fail": "theme_coherence",
        "theme": {
            "id": "theme_bad_coh",
            "title": "Earnings risk",
            "narrative": "Earnings risk building across the book.",
            "narrative_source": "llm",
            "severity": "warn",
            "cited_numbers": [],
            "tags": ["risk:earnings"],
            # Grab-bag: AAPL 52w-high and an energy sector move do not
            # belong in theme_earnings_risk
            "members": [
                {"obs_id": "obs_fake_a", "weight": 1.0},
                {"obs_id": "obs_fake_c", "weight": 1.0},
            ],
        },
    },
    {
        "id": "case_contradictory_narrative",
        "expected_fail": "narrative_accuracy",
        "theme": {
            "id": "theme_bad_acc",
            "title": "Sector rotation",
            "narrative": "Technology sector lags deeply with a sharp selloff led by NVDA.",
            "narrative_source": "llm",
            "severity": "warn",
            "cited_numbers": [],
            "tags": ["regime:rotation"],
            # Narrative talks about Tech/NVDA but members are Energy
            "members": [
                {"obs_id": "obs_fake_c", "weight": 1.0},
            ],
        },
    },
    {
        "id": "case_inverted_weights",
        "expected_fail": "member_fit",
        "theme": {
            "id": "theme_bad_fit",
            "title": "Near-highs",
            "narrative": "AAPL leading the near-highs cluster.",
            "narrative_source": "llm",
            "severity": "info",
            "cited_numbers": ["95.2"],
            "tags": ["technical:near_52w_high"],
            # AAPL is the only near-highs member — but we give it low
            # weight and an unrelated obs high weight
            "members": [
                {"obs_id": "obs_fake_a", "weight": 0.1},
                {"obs_id": "obs_fake_c", "weight": 0.95},
            ],
        },
    },
]


def main():
    themes = [c["theme"] for c in _CASES]
    scores = judge_themes(themes, _OBS, n_samples=3)
    failures: List[str] = []

    print("\n=== L2 judge adversarial calibration ===\n")
    print(f"{'case':34} {'expected':22} {'coh':>4} {'fit':>4} {'acc':>4} {'cite':>4} {'result':>8}")
    print("-" * 96)
    for case in _CASES:
        tid = case["theme"]["id"]
        expected = case["expected_fail"]
        s = scores.get(tid, {})
        coh = s.get("theme_coherence")
        fit = s.get("member_fit")
        acc = s.get("narrative_accuracy")
        cite = s.get("citation_validity")
        caught_val = s.get(expected)
        caught = (caught_val is not None) and caught_val <= 2
        status = "PASS" if caught else "FAIL"
        print(f"{case['id']:34} {expected:22} {coh!s:>4} {fit!s:>4} {acc!s:>4} {cite!s:>4} {status:>8}")
        if not caught:
            failures.append(f"{case['id']}: expected {expected}<=2, got {caught_val}")

    print()
    if failures:
        print(f"{len(failures)}/{len(_CASES)} cases failed:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print(f"{len(_CASES)}/{len(_CASES)} adversarial cases caught. Judge rubric calibrated.")


if __name__ == "__main__":
    main()
