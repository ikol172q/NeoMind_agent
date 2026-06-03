"""Unit tests for agent.finance.fin_router (Phase 1 difficulty routing).

Run:  ~/.neomind_fin_venv/bin/python tests/test_fin_router.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.finance import fin_router as R


def test_classify_decision():
    for q in [
        "我该不该清仓 TSLA?",
        "要不要对冲一下组合",
        "NVDA 现在加仓行不行",   # 加...行不行 → 加不加-ish; ensure 加仓 matches
        "should I sell my MSFT?",
        "现在该减仓吗",
        "止盈 GOOGL 还是继续拿",
    ]:
        assert R.classify(q) == "decision", q


def test_classify_synthesis():
    for q in [
        "为什么 MSFT 最近涨这么多",
        "对比一下 NVDA 和 MSFT",
        "自上次复盘 TSLA 变了啥",
        "why is TSLA down today",
        "帮我分析下半导体板块",
        "解释下这个供应链传导",
    ]:
        assert R.classify(q) == "synthesis", q


def test_classify_lookup():
    for q in [
        "TSLA 现在多少钱",
        "看一下最近的 signal",
        "scanner 上次什么时候跑的",   # freshness lookup, no decision/synth keyword
        "AAPL 最近有什么新闻",
        "我持仓里有哪些票",
    ]:
        assert R.classify(q) == "lookup", q


def test_decision_beats_synthesis():
    # an actionable question that also asks "why" is still a decision
    assert R.classify("为什么我现在该买 NVDA") == "decision"
    assert R.classify("分析一下我到底要不要清仓 TSLA") == "decision"


def test_route_policy_mapping():
    d = R.route("该不该清仓 TSLA")
    assert d["model"] == R.MODEL_PRO and d["reasoning_effort"] == "high" and d["max_tokens"] == 6000
    s = R.route("为什么 MSFT 涨")
    assert s["model"] == R.MODEL_PRO and s["reasoning_effort"] == "high"
    lk = R.route("TSLA 多少钱")
    assert lk["model"] == R.MODEL_FLASH and lk["reasoning_effort"] == "low" and lk["max_tokens"] == 2000


def test_route_explicit_override():
    # user forced pro on a lookup → honour model, sensible effort
    r = R.route("TSLA 多少钱", explicit_model="deepseek-v4-pro")
    assert r["model"] == "deepseek-v4-pro" and r["reasoning_effort"] == "high"
    assert r["intent"] == "lookup"  # intent still classified honestly
    r2 = R.route("该不该清仓", explicit_model="deepseek-v4-flash")
    assert r2["model"] == "deepseek-v4-flash" and r2["reasoning_effort"] == "low"


def test_route_keys_serializable():
    r = R.route("anything")
    assert set(r) == {"intent", "model", "reasoning_effort", "max_tokens", "reason"}
    assert r["reasoning_effort"] in ("low", "medium", "high", "max", "xhigh")


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
