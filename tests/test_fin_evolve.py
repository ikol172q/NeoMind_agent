"""Unit tests for agent.finance.fin_evolve (Phase 2b miner/proposer).

Offline: synthetic episodes via monkeypatched _iter_episodes; apply tested
against a temp system.md + temp proposals dir. No live agent.

Run:  ~/.neomind_fin_venv/bin/python tests/test_fin_evolve.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.finance import fin_evolve as E


def _ep(intent, score, warnings, sid="real-1"):
    return {"session_id": sid, "signals": {"intent": intent,
            "reward": {"score": score, "validator": {"warnings": warnings}}}}


SYNTH = [
    _ep("decision", 0.2, ["价格 $100 缺少来源标注 (Rule 3)",
                          "建议包含至少2个时间框架 (Rule 4a)",
                          "建议包含免责声明 (Rule 4c)"]),
    _ep("synthesis", 0.2, ["价格 $250 缺少来源标注 (Rule 3)",
                           "建议包含免责声明 (Rule 4c)"], sid="rollout-r0-synthesis-0"),
    _ep("lookup", 0.2, ["价格 $40 缺少来源标注 (Rule 3)"]),
    _ep("decision", 1.0, []),   # high reward → ignored by miner
]


def test_rule_regex():
    assert E._RULE_RE.search("foo (Rule 4a)").group(1) == "4a"
    assert E._RULE_RE.search("bar (Rule 3)").group(1) == "3"
    assert E._RULE_RE.search("no tag") is None


def test_mine_ranks_rule3_top(monkeypatch=None):
    orig = E._iter_episodes
    E._iter_episodes = lambda **k: iter(SYNTH)
    try:
        diag = E.mine(reward_max=0.5, days=99)
    finally:
        E._iter_episodes = orig
    assert diag["corpus"]["low_reward_episodes"] == 3   # the 1.0 one excluded
    assert diag["corpus"]["synthetic_episodes"] == 1
    top = diag["patterns"][0]
    assert top["rule"] == "3" and top["episodes"] == 3   # Rule 3 in all 3 low eps
    rules = {p["rule"]: p for p in diag["patterns"]}
    assert rules["4c"]["episodes"] == 2 and rules["4a"]["episodes"] == 1


def test_propose_kinds():
    diag = {"patterns": [
        {"rule": "4c", "count": 2, "episodes": 2, "intents": ["decision"], "examples": ["x"]},
        {"rule": "3", "count": 5, "episodes": 3, "intents": ["lookup"], "examples": ["y"]},
        {"rule": "9z", "count": 1, "episodes": 1, "intents": [], "examples": ["z"]},
    ]}
    props = {p["rule"]: p for p in E.propose(diag)}
    assert props["4c"]["kind"] == "system_md_append" and props["4c"]["proposed_change"]
    assert props["3"]["kind"] == "investigate" and props["3"]["proposed_change"] is None
    assert props["9z"]["kind"] == "review"


def test_apply_refuses_without_approval(tmp=None):
    with tempfile.TemporaryDirectory() as d:
        _patch_paths(d)
        diag = {"patterns": [{"rule": "4c", "count": 1, "episodes": 1, "intents": [], "examples": []}]}
        props = E.propose(diag); E.save_proposals(props)
        pid = props[0]["id"]
        r = E.apply_proposal(pid, approved=False)
        assert r["ok"] is False and "refused" in r["error"]


def test_apply_with_approval_edits_and_backs_up():
    with tempfile.TemporaryDirectory() as d:
        _patch_paths(d)
        sysmd = Path(d) / "system.md"
        sysmd.write_text("原始 system prompt\n", encoding="utf-8")
        E.SYSTEM_MD = sysmd
        diag = {"patterns": [{"rule": "4c", "count": 1, "episodes": 1, "intents": [], "examples": []}]}
        props = E.propose(diag)  # target uses E.SYSTEM_MD at propose time
        E.save_proposals(props)
        pid = props[0]["id"]
        r = E.apply_proposal(pid, approved=True)
        assert r["ok"] is True, r
        body = sysmd.read_text(encoding="utf-8")
        assert "原始 system prompt" in body and "免责声明" in body
        assert f"fin_evolve:{pid}" in body          # marker present
        assert Path(r["backup"]).exists()           # backup written
        # idempotent: second apply refuses (already applied)
        assert E.apply_proposal(pid, approved=True)["ok"] is False


def _gate_setup(d):
    """Common setup for gate tests: temp paths + a pending 4c proposal."""
    _patch_paths(d)
    sysmd = Path(d) / "system.md"
    sysmd.write_text("原始 system prompt\n", encoding="utf-8")
    E.SYSTEM_MD = sysmd  # set before propose() so proposal.target points here
    diag = {"patterns": [{"rule": "4c", "count": 1, "episodes": 1, "intents": [], "examples": []}]}
    props = E.propose(diag)
    E.save_proposals(props)
    return sysmd, props[0]["id"]


def _run_gate_with_rewards(pid, before_after):
    """Run gated_apply with fin_rollout.run_rollouts mocked to return the given
    (before, after) mean rewards in sequence."""
    import asyncio
    from agent.finance import fin_rollout
    seq = iter([{"rollouts": [{"reward_score": before_after[0]}]},
                {"rollouts": [{"reward_score": before_after[1]}]}])

    async def fake_run(seeds):
        return next(seq)

    orig_run, orig_seeds = fin_rollout.run_rollouts, fin_rollout.build_seeds
    fin_rollout.run_rollouts = fake_run
    fin_rollout.build_seeds = lambda *a, **k: []
    try:
        return asyncio.run(E.gated_apply([pid], runs_per_intent=1))
    finally:
        fin_rollout.run_rollouts, fin_rollout.build_seeds = orig_run, orig_seeds


def test_gate_keeps_on_improvement():
    with tempfile.TemporaryDirectory() as d:
        sysmd, pid = _gate_setup(d)
        r = _run_gate_with_rewards(pid, (0.2, 0.8))
        assert r["kept"] is True and r["reverted"] is False and r["delta"] == 0.6
        assert "免责声明" in sysmd.read_text(encoding="utf-8")   # change kept


def test_gate_reverts_on_regression():
    with tempfile.TemporaryDirectory() as d:
        sysmd, pid = _gate_setup(d)
        r = _run_gate_with_rewards(pid, (0.8, 0.2))
        assert r["kept"] is False and r["reverted"] is True and r["delta"] == -0.6
        assert sysmd.read_text(encoding="utf-8") == "原始 system prompt\n"  # restored
        # proposal marked reverted
        p = E.list_proposals()[0]
        assert p["status"] == "reverted"


def _patch_paths(d):
    E.PROPOSALS_ROOT = Path(d) / "proposals"
    E.SYSTEM_MD = Path(d) / "system.md"


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
