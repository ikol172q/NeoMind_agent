"""Unit tests for the evolve_daily self-evolution trigger (Phase 3.4).

Fully offline: dao/connect/ensure_schema and the live-agent rollout are mocked;
mining runs against synthetic episodes; proposals + system.md live in a temp
dir. Asserts the job drafts proposals, dedups across runs, survives a rollout
failure, and NEVER auto-applies (system.md untouched).

Run:  ~/.neomind_fin_venv/bin/python tests/test_evolve_daily.py
"""
from __future__ import annotations

import asyncio
import importlib
import os
import sys
import tempfile
import types
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

J = importlib.import_module("agent.finance.scheduler.jobs.evolve_daily")
from agent.finance import fin_rollout, fin_evolve, fin_outcome


class _FakeConn:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


# Synthetic low-reward episodes carrying a templated validator rule (4c).
LOW = [
    {"session_id": "s1", "req_id": "r1", "signals": {"intent": "decision",
        "reward": {"score": 0.2, "validator": {"warnings": ["建议包含免责声明 (Rule 4c)"]}}}},
    {"session_id": "s2", "req_id": "r2", "signals": {"intent": "synthesis",
        "reward": {"score": 0.2, "validator": {"warnings": ["建议包含免责声明 (Rule 4c)"]}}}},
]


def _patch_common(tmp):
    # Mock the persistence layer so no real DB is touched.
    J.ensure_schema = lambda: None
    J.connect = lambda: _FakeConn()
    J.dao = types.SimpleNamespace(
        start_analysis_run=lambda conn, **k: 123,
        complete_analysis_run=lambda conn, run_id, **k: None,
    )
    # Proposals + the evolvable system.md live in temp.
    fin_evolve.PROPOSALS_ROOT = Path(tmp) / "proposals"
    fin_evolve.SYSTEM_MD = Path(tmp) / "system.md"
    fin_evolve.SYSTEM_MD.write_text("原始 system prompt\n", encoding="utf-8")
    # Mock the live-agent rollout + outcome backfill (no network).

    async def _fake_roll(seeds, temperature=None):
        return {"summary": {"n": len(seeds), "n_scored": 0}, "rollouts": []}

    fin_rollout.run_rollouts = _fake_roll
    fin_rollout.build_seeds = lambda *a, **k: [{"intent": "decision", "query": "q", "chat_id": "c"}]
    fin_outcome.backfill = lambda **k: {"ok": True, "n_scored": 0}


def test_evolve_daily_drafts_and_completes():
    with tempfile.TemporaryDirectory() as d:
        _patch_common(d)
        fin_evolve._iter_episodes = lambda **k: iter(LOW)
        r = asyncio.run(J.run())
        assert r["status"] == "completed"
        assert r["proposals_drafted"] >= 1
        props = fin_evolve.list_proposals()
        assert any(p["rule"] == "4c" and p["status"] == "pending" for p in props)
        # NEVER auto-applied: the evolvable surface is untouched.
        assert fin_evolve.SYSTEM_MD.read_text(encoding="utf-8") == "原始 system prompt\n"


def test_evolve_daily_dedups_existing_rule():
    with tempfile.TemporaryDirectory() as d:
        _patch_common(d)
        fin_evolve._iter_episodes = lambda **k: iter(LOW)
        first = asyncio.run(J.run())
        assert first["proposals_drafted"] >= 1
        second = asyncio.run(J.run())          # same rule already has a proposal
        assert second["proposals_drafted"] == 0    # deduped — no daily spam


def test_evolve_daily_survives_rollout_failure():
    with tempfile.TemporaryDirectory() as d:
        _patch_common(d)
        fin_evolve._iter_episodes = lambda **k: iter(LOW)

        async def _boom(seeds, temperature=None):
            raise RuntimeError("no api key")

        fin_rollout.run_rollouts = _boom
        r = asyncio.run(J.run())
        assert r["status"] == "completed"          # rollout failure is contained
        assert "rollout_error" in r
        assert r["proposals_drafted"] >= 1          # still mined existing episodes


def test_evolve_daily_is_opt_in_not_registered():
    """The job must NOT be in DEFAULT_JOBS — autonomy is opt-in."""
    from agent.finance.scheduler import core
    assert "agent.finance.scheduler.jobs.evolve_daily" not in core.DEFAULT_JOBS
    # but it exposes the full job contract so it CAN be registered later.
    for attr in ("JOB_NAME", "DEFAULT_CRON", "DESCRIPTION", "run"):
        assert hasattr(J, attr)


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
