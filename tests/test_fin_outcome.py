"""Unit tests for agent.finance.fin_outcome (Phase 3.1 outcome loop).

Fully offline: price lookups are injected (price_fn), ledger paths are pointed
at a fresh temp dir per test. No network, no live agent.

Run:  ~/.neomind_fin_venv/bin/python tests/test_fin_outcome.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.finance import fin_outcome as O
from agent.finance import fin_reward as R

_NOW = datetime(2026, 6, 7, tzinfo=timezone.utc)


def _fresh() -> Path:
    """Point the module's ledger paths at a brand-new temp dir."""
    d = Path(tempfile.mkdtemp(prefix="fin_outcome_test_"))
    O.OUTCOMES_ROOT = d
    O._PENDING = d / "pending.jsonl"
    O._REALIZED = d / "realized.jsonl"
    return d


def _bars(closes, start="2026-05-01"):
    """Daily bars oldest→newest; index i ↔ calendar day start+i."""
    base = date.fromisoformat(start)
    return [{"date": (base + timedelta(days=i)).isoformat() + "T00:00:00",
             "open": c, "high": c, "low": c, "close": c, "volume": 1000}
            for i, c in enumerate(closes)]


# decision on 2026-05-20 → entry bar index 19; horizon 5 → end bar index 24.
_DEC_TS = "2026-05-20T10:00:00+00:00"


# ── directional reward math ───────────────────────────────────────────────

def test_directional_bullish():
    assert O._directional_reward("add", 0.05) == 1.0       # +5% = full reward
    assert O._directional_reward("add", -0.05) == -1.0
    assert O._directional_reward("add", 0.025) == 0.5
    assert O._directional_reward("add", 0.5) == 1.0        # clipped to 1


def test_directional_bearish():
    assert O._directional_reward("sell", -0.05) == 1.0     # down = good for sell
    assert O._directional_reward("trim", 0.05) == -1.0
    assert O._directional_reward("pass", -0.50) == 1.0     # clipped


def test_directional_neutral():
    assert O._directional_reward("hold", 0.0) == 1.0       # flat = good
    assert O._directional_reward("watch_only", 0.05) == -1.0   # 1-2*1
    assert O._directional_reward("hold", 0.0125) == 0.5    # 1-2*0.25
    assert O._directional_reward("frobnicate", 0.05) == 0.0    # unknown → 0


# ── record_decisions ──────────────────────────────────────────────────────

def test_record_filters_and_writes():
    _fresh()
    n = O.record_decisions(decisions=[
        {"ticker": "nvda", "action": "ADD"},
        {"ticker": "", "action": "sell"},         # no ticker → skip
        {"ticker": "AAPL", "action": "chatter"},  # non-directional → skip
        {"ticker": "MSFT", "action": "hold"},
    ], req_id="r1", chat_id=42)
    assert n == 2
    rows = [json.loads(ln) for ln in O._PENDING.read_text().splitlines()]
    assert {r["ticker"] for r in rows} == {"NVDA", "MSFT"}
    assert all(r["req_id"] == "r1" and r["chat_id"] == "42" and r["id"] for r in rows)


def test_record_garbage_safe():
    _fresh()
    assert O.record_decisions(decisions=None, req_id="r") == 0
    assert O.record_decisions(decisions=[{"foo": "bar"}], req_id="r") == 0
    assert O.record_decisions(decisions=[{"ticker": "X"}], req_id="r") == 0  # no action
    assert not O._PENDING.exists() or not O._PENDING.read_text().strip()


# ── backfill ──────────────────────────────────────────────────────────────

def test_backfill_scores_matured():
    _fresh()
    O.record_decisions(decisions=[{"ticker": "NVDA", "action": "add"}],
                       req_id="r1", ts=_DEC_TS)
    closes = [100.0] * 40
    closes[24] = 105.0   # entry(19)=100, end(24)=105 → +5%
    res = O.backfill(price_fn=lambda t: _bars(closes), min_age_days=0,
                     horizon_days=5, now=_NOW)
    assert res["n_scored"] == 1 and res["mean_realized"] == 1.0
    assert not O._PENDING.read_text().strip()              # cleared
    real = [json.loads(ln) for ln in O._REALIZED.read_text().splitlines()]
    assert real[0]["ticker"] == "NVDA" and real[0]["reward"] == 1.0 \
        and real[0]["req_id"] == "r1" and real[0]["ret"] == 0.05


def test_backfill_immature_stays_pending():
    _fresh()
    O.record_decisions(decisions=[{"ticker": "NVDA", "action": "add"}],
                       req_id="r1", ts="2026-06-06T10:00:00+00:00")  # 1 day old
    res = O.backfill(price_fn=lambda t: _bars([100.0] * 40), min_age_days=7,
                     horizon_days=5, now=_NOW)
    assert res["n_scored"] == 0 and res["n_immature"] == 1
    assert len(O._PENDING.read_text().splitlines()) == 1   # survives


def test_backfill_resilient_and_survivors():
    _fresh()
    O.record_decisions(decisions=[{"ticker": "GOOD", "action": "add"}],
                       req_id="r1", ts=_DEC_TS)
    O.record_decisions(decisions=[{"ticker": "BAD", "action": "add"}],
                       req_id="r2", ts=_DEC_TS)
    closes = [100.0] * 40
    closes[24] = 102.0   # +2% → add reward 0.4

    def pf(t):
        return _bars(closes) if t == "GOOD" else None   # BAD fetch fails

    res = O.backfill(price_fn=pf, min_age_days=0, horizon_days=5, now=_NOW)
    assert res["n_scored"] == 1 and res["n_failed"] == 1
    surv = [json.loads(ln) for ln in O._PENDING.read_text().splitlines()]
    assert len(surv) == 1 and surv[0]["ticker"] == "BAD"   # GOOD removed, BAD kept
    real = [json.loads(ln) for ln in O._REALIZED.read_text().splitlines()]
    assert real[0]["ticker"] == "GOOD" and real[0]["reward"] == 0.4


def test_backfill_not_enough_forward_bars_stays_pending():
    _fresh()
    O.record_decisions(decisions=[{"ticker": "NVDA", "action": "add"}],
                       req_id="r1", ts=_DEC_TS)
    # only 22 bars: entry idx 19, end idx 24 doesn't exist → immature/failed
    res = O.backfill(price_fn=lambda t: _bars([100.0] * 22), min_age_days=0,
                     horizon_days=5, now=_NOW)
    assert res["n_scored"] == 0 and res["n_failed"] == 1
    assert len(O._PENDING.read_text().splitlines()) == 1


# ── load_realized_index ───────────────────────────────────────────────────

def test_load_realized_index_aggregates_by_reqid():
    _fresh()
    O.OUTCOMES_ROOT.mkdir(parents=True, exist_ok=True)
    rows = [{"req_id": "r1", "reward": 1.0}, {"req_id": "r1", "reward": 0.0},
            {"req_id": "r2", "reward": -0.5}, {"req_id": None, "reward": 0.3}]
    O._REALIZED.write_text("\n".join(json.dumps(x) for x in rows) + "\n")
    idx = O.load_realized_index()
    assert idx == {"r1": 0.5, "r2": -0.5}   # None skipped, r1 averaged


# ── score_episode (in fin_reward) ─────────────────────────────────────────

def test_score_episode_base_only_when_no_outcome():
    ep = {"req_id": "r1", "signals": {"reward": {"score": 1.0}}}
    s = R.score_episode(ep, realized_index={})
    assert s["score"] == 1.0 and s["matured"] is False and s["realized"] is None


def test_score_episode_blends_outcome():
    ep = {"req_id": "r1", "signals": {"reward": {"score": 1.0}}}
    s = R.score_episode(ep, realized_index={"r1": -1.0})   # 0.6*1 + 0.4*(-1)
    assert s["matured"] is True and s["realized"] == -1.0 and s["score"] == 0.2


def test_score_episode_validator_fallback_and_garbage():
    ep2 = {"req_id": "x", "signals": {"reward": {"validator": {"score": 0.5}}}}
    assert R.score_episode(ep2)["score"] == 0.5            # falls back to validator
    assert R.score_episode({"signals": "notadict"})["score"] == 0.0  # safe


def test_end_to_end_loop_pulls_right_call_up():
    """A compliance-failing (dense -0.5) but CORRECT (sell before -5%) decision
    should be pulled UP by the outcome — the whole point of Phase 3.1."""
    _fresh()
    O.record_decisions(decisions=[{"ticker": "NVDA", "action": "sell"}],
                       req_id="rE", ts=_DEC_TS)
    closes = [100.0] * 40
    closes[24] = 95.0    # -5% → sell reward +1.0
    O.backfill(price_fn=lambda t: _bars(closes), min_age_days=0,
               horizon_days=5, now=_NOW)
    idx = O.load_realized_index()
    assert idx["rE"] == 1.0
    ep = {"req_id": "rE", "signals": {"reward": {"score": -0.5}}}
    s = R.score_episode(ep, realized_index=idx)
    assert s["matured"] is True and s["score"] == 0.1       # 0.6*-0.5 + 0.4*1.0


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
