"""Unit tests for agent.finance.fin_reward (Phase 0 reward synthesizer).

Pure-logic + best-effort tests. The validator path is real (regex, no
network); the scorecard path stays OFF by default so these run offline.

Run directly:  ~/.neomind_fin_venv/bin/python tests/test_fin_reward.py
Or via pytest: ~/.neomind_fin_venv/bin/python -m pytest tests/test_fin_reward.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.finance import fin_reward as fr


# ── _agreement ───────────────────────────────────────────────────────

def test_agreement_exact():
    assert fr._agreement("add", "add") == 1.0
    assert fr._agreement("hold", "hold") == 1.0


def test_agreement_same_group():
    # hold + watch_only are both neutral
    assert fr._agreement("hold", "watch_only") == 0.3
    # trim + sell + pass are all bearish
    assert fr._agreement("trim", "sell") == 0.3
    assert fr._agreement("sell", "pass") == 0.3


def test_agreement_opposite():
    assert fr._agreement("add", "trim") == -1.0
    assert fr._agreement("add", "sell") == -1.0
    assert fr._agreement("pass", "add") == -1.0


def test_agreement_neutral_vs_directional():
    assert fr._agreement("hold", "add") == 0.0    # neutral vs bull
    assert fr._agreement("watch_only", "sell") == 0.0  # neutral vs bear


def test_agreement_unknown_or_empty():
    assert fr._agreement("", "add") == 0.0
    assert fr._agreement("add", "") == 0.0
    assert fr._agreement("garbage", "add") == 0.0


# ── _validator_score ─────────────────────────────────────────────────

def test_validator_score_mapping():
    assert fr._validator_score(passed=True, blocked=False, n_warnings=0) == 1.0
    assert fr._validator_score(passed=True, blocked=True, n_warnings=0) == -1.0
    assert fr._validator_score(passed=False, blocked=False, n_warnings=0) == -0.5
    # warnings decay from 0.8, floored at 0.2 (round: avoid float noise)
    assert round(fr._validator_score(passed=True, blocked=False, n_warnings=1), 3) == 0.6
    assert round(fr._validator_score(passed=True, blocked=False, n_warnings=5), 3) == 0.2


# ── compute_reward: shape + structural overrides ─────────────────────

def test_compute_reward_shape():
    r = fr.compute_reward(query="how's my book?",
                          reply="先看整体持仓结构，再决定要不要动。",
                          tool_results=[])
    assert r["schema"] == fr.SCHEMA
    assert isinstance(r["score"], float)
    assert -1.0 <= r["score"] <= 1.0
    assert r["validator"]["passed"] is True          # no numbers → no rule-1 fail
    assert r["scorecard"]["computed"] is False       # opt-in, default off
    assert r["pending_pnl"] == []
    assert r["structural"]["finish_reason"] is None


def test_compute_reward_pending_pnl_from_decisions():
    r = fr.compute_reward(
        query="should I add NVDA?",
        reply="NVDA 信号偏正，可考虑分批建仓。",
        decisions=[{"ticker": "nvda", "action": "Add", "note": "earnings soon"},
                   {"ticker": "", "action": "hold"}],   # dropped: no ticker
    )
    assert r["pending_pnl"] == [
        {"ticker": "NVDA", "action": "add", "note": "earnings soon"}
    ]
    assert r["structural"]["n_decisions"] == 2


def test_compute_reward_max_turns_is_negative():
    r = fr.compute_reward(query="x", reply="(stuck)", finish_reason="max_turns")
    assert r["score"] <= -1.0
    assert r["structural"]["error_reply"] is True
    assert r["structural"]["agent_error"] is True      # max_turns = agent-attributable
    assert r["structural"]["infra_error"] is False


def test_compute_reward_infra_error_excluded_from_signal():
    # An LLM/router failure carries no harness-quality signal: score must be
    # None (so every numeric consumer skips it) and flagged infra_error.
    r = fr.compute_reward(query="x", reply="⚠️ LLM 调用失败", finish_reason="llm_error")
    assert r["score"] is None
    assert r["structural"]["infra_error"] is True
    assert r["structural"]["agent_error"] is False
    assert r["structural"]["error_reply"] is True      # back-compat flag still set


def test_compute_reward_empty_reply_is_negative():
    r = fr.compute_reward(query="x", reply="   ", finish_reason="stop")
    assert r["score"] <= -1.0
    assert r["structural"]["empty_reply"] is True


def test_compute_reward_never_raises_on_garbage():
    # weird/None-ish inputs must not blow up the reply path
    r = fr.compute_reward(query="", reply=None, tool_results=None,
                          decisions=None, finish_reason=None)  # type: ignore[arg-type]
    assert r["schema"] == fr.SCHEMA
    assert isinstance(r["score"], float)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for fn in fns:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL  {fn.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"  ERROR {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(fns)} passed")
    sys.exit(0 if passed == len(fns) else 1)
