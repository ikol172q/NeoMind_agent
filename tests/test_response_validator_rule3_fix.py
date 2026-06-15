"""Regression tests for the Rule-3 false-positive fix (2026-06-02).

The validator was reading "$40" out of "$40T", "$150" out of "$150B", and
"$100"/"$250" out of "$100k-$250k" (TAM / spend / disclosure ranges, not
stock prices), and didn't recognize the agents' [ev:]/[fact:] citations as a
source. Both produced spurious Rule-3 warnings that floored episode reward.

Run:  ~/.neomind_fin_venv/bin/python tests/test_response_validator_rule3_fix.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.finance import response_validator as V


def test_magnitude_suffixes_not_extracted_as_prices():
    for s in ["$40T", "$150B", "$100k", "$5M", "$2.5b", "$100k-$250k"]:
        assert V._extract_prices(s) == [], f"should not extract a price from {s!r}: {V._extract_prices(s)}"


def test_real_prices_still_extracted():
    assert V._extract_prices("收盘 $195.42") == ["$195.42"]
    assert V._extract_prices("买在 $250,000 的仓位")  # bare amount preserved
    # space after price must not suppress it
    assert "$195.42" in V._extract_prices("$195.42 close")


def test_ev_fact_tags_count_as_source():
    assert V._line_has_source("NVDA 收盘 $195.42 [ev:73eee74f]", "$195.42") is True
    assert V._line_has_source("成本 $195.42 [fact:abc123]", "$195.42") is True
    assert V._line_has_source("收盘 $195.42 无来源", "$195.42") is False


def test_validate_no_rule3_on_tam_and_cited_lines():
    text = ("- Jensen 称机器人市场 $40T 潜力 [ev:73eee74f]\n"
            "- NVDA 计划在台湾年支出 $150B [ev:327412f8]\n"
            "- 收盘价 $195.42 [ev:abc]")
    res = V.get_finance_validator().validate(text, tool_results=[])
    rule3 = [w for w in res.warnings if "(Rule 3)" in w]
    assert rule3 == [], f"no Rule-3 expected, got: {rule3}"


def test_validate_still_flags_genuinely_unsourced_price():
    # a bare, uncited, tool-unverified stock price must still be caught
    # (as unverified/unsourced — exact rule tag varies; the point is the
    # fix didn't blind the validator to real omissions).
    res = V.get_finance_validator().validate("我觉得它会到 $195.42", tool_results=[])
    assert not res.passed
    assert "$195.42" in res.unverified_prices or "$195.42" in res.unsourced_data


def test_chinese_fee_and_min_in_excluded_context():
    # Hardened PRICE_EXCLUDE_PATTERNS (2026-06-15): 中文 fee WITHOUT a connector
    # and 中文 min/max are non-market-data → in excluded context → not flagged.
    assert V._is_in_excluded_context("每笔手续费 $5", "$5") is True
    assert V._is_in_excluded_context("佣金 $1.00", "$1.00") is True
    assert V._is_in_excluded_context("最低 $1 起投", "$1") is True
    assert V._is_in_excluded_context("至少 $25,000", "$25,000") is True


def test_fee_word_does_not_excuse_a_real_price_on_same_line():
    # Anchoring guard: a fee word earlier in the line must NOT put an unsourced
    # REAL price later in the line into excluded context ($ must follow the fee word).
    assert V._is_in_excluded_context("手续费高，股价收在 $195.42", "$195.42") is False


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for fn in fns:
        try:
            fn(); print(f"  PASS  {fn.__name__}"); passed += 1
        except AssertionError as e:
            print(f"  FAIL  {fn.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            import traceback; traceback.print_exc()
            print(f"  ERROR {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(fns)} passed")
    sys.exit(0 if passed == len(fns) else 1)
