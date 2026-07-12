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


def test_mine_skips_infra_error_episodes():
    """Episodes with score=None (infra/llm_error — no harness signal) must be
    excluded from the mined corpus."""
    eps = [_ep("decision", 0.2, ["缺免责声明 (Rule 4c)"]),
           _ep("decision", None, [])]      # infra error → score None → skip
    orig = E._iter_episodes
    E._iter_episodes = lambda **k: iter(eps)
    try:
        diag = E.mine(reward_max=0.5, days=99)
    finally:
        E._iter_episodes = orig
    assert diag["corpus"]["scored_episodes"] == 1   # the None-score one excluded


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


def test_insert_block_before_closing_anchor():
    original = "## 角色\nrule A\n\n---\n\n现在开始。用户问的下一条消息会跟在 user role 里。\n"
    out = E._insert_block(original, ["", "## NEW", "<!-- m -->", "- new rule", ""])
    # NEW section must land BEFORE the '---'/begin group, not after "现在开始"
    assert out.index("## NEW") < out.index("---")
    assert out.index("## NEW") < out.index("现在开始")
    assert "rule A" in out and "现在开始" in out


def test_insert_block_fallback_append_when_no_anchor():
    original = "just a prompt body, no begin line\n"
    out = E._insert_block(original, ["", "## NEW", "- x", ""])
    assert out.rstrip().endswith("- x")  # appended at end


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


def _run_gate(pid, base_rollouts, ver_rollouts):
    """Run gated_apply with run_rollouts mocked to return the given base/verify
    rollout rows. Isolates the drift DB to a temp path so the longitudinal
    monitor never writes real state during tests."""
    import asyncio
    import tempfile as _tf
    from agent.finance import fin_rollout
    E._DRIFT_DB = Path(_tf.mkdtemp()) / "drift.db"
    seq = iter([{"rollouts": base_rollouts}, {"rollouts": ver_rollouts}])

    async def fake_run(seeds, temperature=None):
        return next(seq)

    orig_run, orig_seeds = fin_rollout.run_rollouts, fin_rollout.build_seeds
    fin_rollout.run_rollouts = fake_run
    fin_rollout.build_seeds = lambda *a, **k: []
    try:
        return asyncio.run(E.gated_apply([pid], runs_per_intent=1))
    finally:
        fin_rollout.run_rollouts, fin_rollout.build_seeds = orig_run, orig_seeds


def _uniform(reward, n, ok=True):
    return [{"query": f"q{i}", "reward_score": reward, "ok": ok, "reply_chars": 100}
            for i in range(n)]


def _run_gate_with_rewards(pid, before_after, n_pairs=3):
    """Uniform base/verify rollouts at the given (before, after) reward."""
    before, after = before_after
    return _run_gate(pid, _uniform(before, n_pairs), _uniform(after, n_pairs))


def test_gate_keeps_on_improvement():
    with tempfile.TemporaryDirectory() as d:
        sysmd, pid = _gate_setup(d)
        r = _run_gate_with_rewards(pid, (0.2, 0.8))   # 3 pairs, each +0.6
        assert r["kept"] is True and r["reverted"] is False and r["delta"] == 0.6
        assert r["status"] == "kept" and r["win_rate"] == 1.0 and r["n_paired"] == 3
        assert "免责声明" in sysmd.read_text(encoding="utf-8")   # change kept


def test_gate_reverts_on_regression():
    with tempfile.TemporaryDirectory() as d:
        sysmd, pid = _gate_setup(d)
        r = _run_gate_with_rewards(pid, (0.8, 0.2))   # 3 pairs, each -0.6
        assert r["kept"] is False and r["reverted"] is True and r["delta"] == -0.6
        assert r["status"] == "reverted" and r["win_rate"] == 0.0
        assert sysmd.read_text(encoding="utf-8") == "原始 system prompt\n"  # restored
        # proposal marked reverted
        p = E.list_proposals()[0]
        assert p["status"] == "reverted"


def test_gate_inconclusive_on_insufficient_n():
    """A big improvement with only n=1 paired sample must NOT promote — the n=2
    noise trap. The edit is rolled back and marked inconclusive."""
    with tempfile.TemporaryDirectory() as d:
        sysmd, pid = _gate_setup(d)
        r = _run_gate_with_rewards(pid, (0.2, 0.9), n_pairs=1)
        assert r["kept"] is False and r["status"] == "inconclusive"
        assert sysmd.read_text(encoding="utf-8") == "原始 system prompt\n"  # rolled back
        assert E.list_proposals()[0]["status"] == "inconclusive"


def test_gate_reverts_on_subthreshold_noise():
    """A positive but tiny mean delta (below min_improve) no longer 'passes' —
    the old min_delta=-0.1 gate would have kept it."""
    with tempfile.TemporaryDirectory() as d:
        sysmd, pid = _gate_setup(d)
        r = _run_gate_with_rewards(pid, (0.50, 0.52), n_pairs=3)  # +0.02 < 0.05
        assert r["kept"] is False and r["status"] == "reverted"
        assert sysmd.read_text(encoding="utf-8") == "原始 system prompt\n"


def test_gate_safety_blocks_newly_broken_query():
    """Phase 3.3: an edit that improves mean reward on most queries but BREAKS a
    case (newly ok=False) must NOT promote — safety dominates reward."""
    with tempfile.TemporaryDirectory() as d:
        sysmd, pid = _gate_setup(d)
        base = _uniform(0.5, 4)                       # q0..q3 all fine
        ver = _uniform(0.9, 3)                        # q0..q2 improved
        ver.append({"query": "q3", "ok": False})     # q3 newly broken
        r = _run_gate(pid, base, ver)
        assert r["status"] == "safety_blocked" and r["kept"] is False
        assert r["new_failures"] == ["q3"]
        assert sysmd.read_text(encoding="utf-8") == "原始 system prompt\n"  # reverted


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
