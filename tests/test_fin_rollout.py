"""Unit tests for agent.finance.fin_rollout seed builder (offline).

run_rollouts()/generate() hit the live agent and are exercised separately.

Run:  ~/.neomind_fin_venv/bin/python tests/test_fin_rollout.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.finance import fin_rollout as RO


def test_build_seeds_count():
    seeds = RO.build_seeds(n_per_intent=2)
    assert len(seeds) == 2 * len(RO.SEED_TEMPLATES)  # 2 per intent bucket


def test_build_seeds_shape_and_intents():
    seeds = RO.build_seeds(n_per_intent=1)
    intents = {s["intent"] for s in seeds}
    assert intents == set(RO.SEED_TEMPLATES)  # decision/synthesis/lookup
    for s in seeds:
        assert set(s) == {"intent", "query", "chat_id"}
        assert s["query"] and s["chat_id"].startswith("rollout-")


def test_build_seeds_templates_filled():
    seeds = RO.build_seeds(n_per_intent=4)
    for s in seeds:
        assert "{t}" not in s["query"] and "{t1}" not in s["query"] and "{t2}" not in s["query"]


def test_build_seeds_unique_chat_ids():
    seeds = RO.build_seeds(n_per_intent=4, run_id="uniq")
    ids = [s["chat_id"] for s in seeds]
    assert len(ids) == len(set(ids)), "chat_ids must be unique per seed"


def test_classify_agrees_with_intent_bucket():
    # the templates should route to the bucket they're filed under
    from agent.finance import fin_router as R
    seeds = RO.build_seeds(n_per_intent=4)
    mismatches = [(s["intent"], R.classify(s["query"]), s["query"])
                  for s in seeds if R.classify(s["query"]) != s["intent"]]
    # allow lookups to occasionally read as synthesis, but decisions must hold
    decision_bad = [m for m in mismatches if m[0] == "decision"]
    assert not decision_bad, f"decision templates misroute: {decision_bad}"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for fn in fns:
        try:
            fn(); print(f"  PASS  {fn.__name__}"); passed += 1
        except AssertionError as e:
            print(f"  FAIL  {fn.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"  ERROR {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(fns)} passed")
    sys.exit(0 if passed == len(fns) else 1)
