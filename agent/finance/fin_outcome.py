"""fin_outcome — the missing sparse/delayed reward: did a proposed decision
turn out right?

Phase 3.1 of the Fin Harness Evolution Loop
(``plans/2026-06-01_fin-harness-evolution-loop.md``).

Phase 0 wrote ``pending_pnl`` into every episode's reward bag but **nothing
ever read it** — the outcome loop was open. The production reward was therefore
validator-regex only ("did the reply carry a disclaimer / time horizon / cited
price"), which optimises *compliance*, not whether the call was *right*. A
self-evolving trading agent that never learns whether its decisions made money
is the deepest gap in the loop. There is also no upstream data: a proposed
decision never becomes a paper trade, so there is nothing to "backfill" — we
have to *produce* the outcome signal.

This module closes the loop with a decision-outcome ledger:

  record_decisions()   — at turn time, append each directional decision
                         (ticker, action, ts, req_id) to a pending ledger.
                         ZERO network — the reply path stays network-free.
  backfill()           — offline job: for decisions old enough that a forward
                         window has elapsed, fetch the forward price return and
                         score it directionally (add↑=good, trim/sell↓=good,
                         hold/watch flat=good). Writes a realized reward keyed
                         by the episode's req_id.
  load_realized_index()— join key for ``fin_reward.score_episode``:
                         {req_id: mean realized reward across that turn's
                         decisions}.

Honest caveats (documented, not hidden):
- A short-horizon (≈5 trading day) return is mostly market noise for a single
  decision. The signal only emerges aggregated over many episodes in mining —
  it is **not** a per-turn gate signal (the gate can't wait days for an
  outcome).
- Direction-of-return is a coarse proxy for "good call" (no position sizing, no
  risk adjustment). It is strictly better than regex compliance, not a P&L
  attribution system.

Design rules (mirrors fin_reward):
- ``record_decisions`` is best-effort and never raises into the reply path, and
  does no network I/O.
- ``backfill`` is resilient: a single ticker/parse failure never aborts the
  batch; immature or unfetchable entries stay pending for a later run.
- The pending rewrite preserves concurrent appends by matching on a per-entry
  ``id`` (not line content), so a turn writing a new decision mid-backfill is
  not clobbered.
"""
from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

from agent.evolution.episode_capture import EPISODES_ROOT  # noqa: E402

OUTCOMES_ROOT = EPISODES_ROOT.parent / "outcomes"
_PENDING = OUTCOMES_ROOT / "pending.jsonl"
_REALIZED = OUTCOMES_ROOT / "realized.jsonl"
_WRITE_LOCK = threading.Lock()

SCHEMA = "fin_outcome.v1"

# Decision vocabulary — shared with fin_reward._BULLISH/_BEARISH/_NEUTRAL.
_BULLISH = {"add"}
_BEARISH = {"trim", "sell", "pass"}
_NEUTRAL = {"hold", "watch_only"}
_DIRECTIONAL = _BULLISH | _BEARISH | _NEUTRAL

_DEFAULT_SCALE = 0.05         # a 5% forward move = full-magnitude reward
_DEFAULT_HORIZON_DAYS = 5     # trading bars forward from the decision bar
_DEFAULT_MIN_AGE_DAYS = 7     # calendar days before a decision is "mature"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clip(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _directional_reward(action: str, ret: float, *, scale: float = _DEFAULT_SCALE) -> float:
    """Map a forward return to [-1, 1] given the decision's implied direction.

    bullish  (add):            reward = ret / scale          (price up = good)
    bearish  (trim/sell/pass): reward = -ret / scale         (price down = good)
    neutral  (hold/watch_only):reward = 1 - 2*|ret|/scale    (staying flat = good)
    unknown action → 0.0 (no signal).
    """
    action = (action or "").strip().lower()
    if scale <= 0:
        scale = _DEFAULT_SCALE
    if action in _BULLISH:
        return round(_clip(ret / scale), 3)
    if action in _BEARISH:
        return round(_clip(-ret / scale), 3)
    if action in _NEUTRAL:
        return round(_clip(1.0 - 2.0 * abs(ret) / scale), 3)
    return 0.0


def record_decisions(*, decisions: List[Dict[str, Any]], req_id: Optional[str],
                     chat_id: Optional[Any] = None, ts: Optional[str] = None) -> int:
    """Append directional decisions to the pending ledger.

    Best-effort, ZERO network, never raises. Skips decisions with no ticker or
    a non-directional action. Returns the number of entries written.
    """
    try:
        ts = ts or _now().isoformat()
        rows: List[Dict[str, Any]] = []
        for d in decisions or []:
            ticker = (d.get("ticker") or "").strip().upper()
            action = (d.get("action") or "").strip().lower()
            if not ticker or action not in _DIRECTIONAL:
                continue
            rows.append({
                "schema": SCHEMA,
                "id": uuid.uuid4().hex[:12],
                "status": "pending",
                "ticker": ticker,
                "action": action,
                "ts": ts,
                "req_id": req_id,
                "chat_id": (str(chat_id) if chat_id is not None else None),
            })
        if not rows:
            return 0
        OUTCOMES_ROOT.mkdir(parents=True, exist_ok=True)
        with _WRITE_LOCK:
            with _PENDING.open("a", encoding="utf-8") as fh:
                for r in rows:
                    fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        return len(rows)
    except Exception:  # never break the reply path
        logger.debug("fin_outcome.record_decisions failed", exc_info=True)
        return 0


def _default_price_lookup(ticker: str) -> Optional[List[Dict[str, Any]]]:
    """Daily OHLC bars (oldest→newest) via the existing FinanceDataHub.

    Network — used only by the offline backfill job. Returns None on failure.
    """
    try:
        import asyncio
        from agent.finance.data_hub import FinanceDataHub
        hub = FinanceDataHub()
        return asyncio.run(hub.get_history(ticker, period="3mo", interval="1d"))
    except Exception:
        logger.debug("fin_outcome price lookup failed for %s", ticker, exc_info=True)
        return None


def _bar_date(bar: Dict[str, Any]) -> str:
    return str(bar.get("date", ""))[:10]


def _returns_for(bars: List[Dict[str, Any]], decision_ts: str, horizon_days: int):
    """Given daily bars (oldest→newest) and a decision timestamp, return
    ``(entry_close, end_close, matured)``.

    entry = close of the last bar on/before the decision date; end = close
    ``horizon_days`` bars later. ``matured`` is False when there aren't enough
    forward bars yet (so the entry stays pending and retries on a later run).
    """
    if not bars:
        return None, None, False
    dday = (decision_ts or "")[:10]
    entry_i: Optional[int] = None
    for i, b in enumerate(bars):
        if _bar_date(b) <= dday:
            entry_i = i
        else:
            break
    if entry_i is None:
        return None, None, False
    end_i = entry_i + horizon_days
    if end_i >= len(bars):
        return None, None, False  # not enough forward data yet
    try:
        entry = float(bars[entry_i]["close"])
        end = float(bars[end_i]["close"])
    except (KeyError, TypeError, ValueError):
        return None, None, False
    if entry <= 0:
        return None, None, False
    return entry, end, True


def backfill(*, min_age_days: int = _DEFAULT_MIN_AGE_DAYS,
             horizon_days: int = _DEFAULT_HORIZON_DAYS,
             scale: float = _DEFAULT_SCALE,
             price_fn: Optional[Callable[[str], Optional[List[Dict[str, Any]]]]] = None,
             now: Optional[datetime] = None) -> Dict[str, Any]:
    """Score matured pending decisions by forward return; write realized rewards.

    Resilient: a single ticker/parse failure never aborts the batch. Immature
    entries (or ones whose price fetch fails) stay pending for a later run.
    Concurrency-safe: the network fetch happens outside the lock, and the
    pending rewrite removes only the specific entry ``id``s that were scored,
    so a turn appending a new decision mid-run is not lost.

    ``price_fn(ticker) -> bars`` is injectable (tests pass a fake; default hits
    the live FinanceDataHub). Returns a summary dict.
    """
    price_fn = price_fn or _default_price_lookup
    now = now or _now()

    # 1) Snapshot pending under lock (cheap), then release before any network.
    if not _PENDING.exists():
        return {"ok": True, "n_pending": 0, "n_scored": 0, "n_immature": 0,
                "n_failed": 0, "mean_realized": None}
    with _WRITE_LOCK:
        raw_lines = [ln for ln in _PENDING.read_text(encoding="utf-8").splitlines() if ln.strip()]

    # 2) Compute outside the lock (network is slow — never hold the lock for it).
    scored_ids: set = set()
    realized_rows: List[Dict[str, Any]] = []
    n_scored = n_immature = n_failed = 0
    bars_cache: Dict[str, Optional[List[Dict[str, Any]]]] = {}

    for raw in raw_lines:
        try:
            row = json.loads(raw)
        except json.JSONDecodeError:
            continue
        ticker = row.get("ticker")
        action = row.get("action")
        ts = row.get("ts") or ""
        eid = row.get("id")
        try:
            age = (now - datetime.fromisoformat(ts)).days if ts else 10 ** 6
        except ValueError:
            age = 10 ** 6
        if age < min_age_days:
            n_immature += 1
            continue  # stays pending (id not in scored_ids)
        if ticker not in bars_cache:
            bars_cache[ticker] = price_fn(ticker)
        entry, end, matured = _returns_for(bars_cache.get(ticker) or [], ts, horizon_days)
        if not matured or entry is None or end is None:
            n_failed += 1
            continue  # stays pending — retry later
        ret = (end - entry) / entry
        reward = _directional_reward(action, ret, scale=scale)
        realized_rows.append({
            "schema": SCHEMA, "ticker": ticker, "action": action,
            "decision_ts": ts, "req_id": row.get("req_id"), "chat_id": row.get("chat_id"),
            "entry": round(entry, 4), "end": round(end, 4), "ret": round(ret, 4),
            "horizon_days": horizon_days, "reward": reward, "scored_ts": now.isoformat(),
        })
        if eid:
            scored_ids.add(eid)
        n_scored += 1

    # 3) Persist under lock: append realized, then rewrite pending keeping any
    #    entry whose id we did NOT just score (preserves concurrent appends).
    OUTCOMES_ROOT.mkdir(parents=True, exist_ok=True)
    with _WRITE_LOCK:
        if realized_rows:
            with _REALIZED.open("a", encoding="utf-8") as fh:
                for r in realized_rows:
                    fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        current = [ln for ln in _PENDING.read_text(encoding="utf-8").splitlines() if ln.strip()] \
            if _PENDING.exists() else []
        survivors: List[str] = []
        for ln in current:
            try:
                eid = json.loads(ln).get("id")
            except json.JSONDecodeError:
                survivors.append(ln)  # keep unparseable rather than drop silently
                continue
            if eid not in scored_ids:
                survivors.append(ln)
        _PENDING.write_text("\n".join(survivors) + ("\n" if survivors else ""), encoding="utf-8")

    rewards = [r["reward"] for r in realized_rows]
    mean_realized = round(sum(rewards) / len(rewards), 3) if rewards else None
    return {"ok": True, "n_pending": len(raw_lines), "n_scored": n_scored,
            "n_immature": n_immature, "n_failed": n_failed,
            "mean_realized": mean_realized}


def load_realized_index() -> Dict[str, float]:
    """Map ``req_id`` → mean realized reward across that turn's decisions.

    Consumed by ``fin_reward.score_episode`` to fold the sparse outcome into an
    episode's score. Returns {} when nothing has been backfilled yet.
    """
    if not _REALIZED.exists():
        return {}
    agg: Dict[str, List[float]] = {}
    try:
        for raw in _REALIZED.read_text(encoding="utf-8").splitlines():
            if not raw.strip():
                continue
            try:
                r = json.loads(raw)
            except json.JSONDecodeError:
                continue
            rid = r.get("req_id")
            rw = r.get("reward")
            if rid and isinstance(rw, (int, float)):
                agg.setdefault(rid, []).append(float(rw))
    except OSError:
        return {}
    return {k: round(sum(v) / len(v), 3) for k, v in agg.items() if v}
