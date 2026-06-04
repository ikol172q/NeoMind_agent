"""fin_rollout — synthetic rollout generator for the Fin Harness Evolution Loop.

Phase 2a (``plans/2026-06-01_fin-harness-evolution-loop.md``).

The loop needs reward-labeled trajectories to mine. Real ones accumulate too
slowly when the agent is used sparsely. So we generate them: representative
fin questions across the intent buckets (decision / synthesis / lookup) ×
real-world tickers, run through the *live* agent, producing fully
reward-labeled episodes (Phase 0 wired the reward into every episode).

This is the RL-rollout / DSec-sandbox analog for a frozen, remote model: the
environment generates trajectories on demand rather than waiting on users —
except here the thing being improved is the harness (routing / prompt /
exemplars), not the model's weights.

Cost note: each rollout is a full ``answer()`` turn. decision/synthesis route
to pro (~12x flash); keep batches small or run off-peak. Nothing here runs
automatically — a caller (CLI or the Phase 2 scheduler job) decides when.

Rollout episodes are namespaced with a ``rollout-<run_id>-...`` session_id so
downstream mining can tell synthetic trajectories from real user ones and
weight them accordingly.
"""
from __future__ import annotations

import asyncio
import glob
import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Public tickers used as fill-ins (not user PII — common AI/semis names).
TICKERS = ["NVDA", "META", "AMD", "ARM", "AVGO", "GOOGL", "TSM", "MSFT"]

# Templates per intent. {t}/{t1}/{t2} are filled from TICKERS. Chosen to
# exercise the tools (so the validator has tool results to ground against)
# and to span the routing buckets fin_router classifies.
SEED_TEMPLATES: Dict[str, List[str]] = {
    "decision": [
        "我该不该现在减仓 {t}",
        "{t} 财报前要不要先对冲一下",
        "{t} 该加仓还是观望",
        "现在要不要给组合整体对冲",
    ],
    "synthesis": [
        "为什么 {t} 最近 smart money 在动",
        "自上次复盘以来 {t} 有什么变化",
        "对比一下 {t1} 和 {t2} 的持仓信号",
        "{t} 的供应链如果出问题会传导到哪",
    ],
    "lookup": [
        "{t} 最近有哪些 signal",
        "看一下数据新鲜度，哪些 scanner 旧了",
        "{t} 现在 smart money 是什么动向",
        "我 watchlist 外围最近有什么票冒头",
    ],
}


def build_seeds(n_per_intent: int = 2, run_id: str = "r0",
                intents: Optional[List[str]] = None) -> List[Dict[str, str]]:
    """Build a deterministic batch of rollout seeds.

    Returns a list of ``{"intent", "query", "chat_id"}``. Tickers rotate by
    index so a batch spans several names. chat_ids are unique per seed so each
    rollout starts from empty history (no cross-contamination). ``intents``
    optionally restricts which buckets to generate (e.g. only the
    recommendation intents a proposal actually affects).
    """
    seeds: List[Dict[str, str]] = []
    for intent, templates in SEED_TEMPLATES.items():
        if intents is not None and intent not in intents:
            continue
        for i in range(n_per_intent):
            tpl = templates[i % len(templates)]
            t = TICKERS[(i) % len(TICKERS)]
            t1 = TICKERS[i % len(TICKERS)]
            t2 = TICKERS[(i + 1) % len(TICKERS)]
            query = tpl.format(t=t, t1=t1, t2=t2)
            seeds.append({
                "intent": intent,
                "query": query,
                "chat_id": f"rollout-{run_id}-{intent}-{i}",
            })
    return seeds


def _episodes_by_chat_id(chat_ids: set, days_back: int = 2) -> Dict[str, Dict[str, Any]]:
    """Read recent episode files; return the latest episode per chat_id."""
    from agent.evolution.episode_capture import EPISODES_ROOT
    out: Dict[str, Dict[str, Any]] = {}
    files = sorted(glob.glob(str(EPISODES_ROOT / "*.jsonl")), reverse=True)[:days_back]
    for f in files:
        try:
            lines = open(f, encoding="utf-8").read().splitlines()
        except OSError:
            continue
        for raw in lines:
            if not raw.strip():
                continue
            try:
                rec = json.loads(raw)
            except json.JSONDecodeError:
                continue
            sid = rec.get("session_id")
            if sid in chat_ids:
                out[sid] = rec  # later lines overwrite → keep latest
    return out


async def run_rollouts(seeds: List[Dict[str, str]],
                       temperature: Optional[float] = None) -> Dict[str, Any]:
    """Run each seed through the live agent, then join back the reward-labeled
    episodes. Resilient: one failing rollout doesn't abort the batch.

    ``temperature`` is forwarded to the agent — pass 0.0 for *evaluation*
    rollouts (deterministic, low-variance) vs the default 0.3 for data
    generation.

    Returns ``{"rollouts": [...per seed...], "summary": {...}}``.
    """
    from agent.finance.dashboard_agent.agent import answer

    results: List[Dict[str, Any]] = []
    for s in seeds:
        row: Dict[str, Any] = {"intent": s["intent"], "query": s["query"],
                               "chat_id": s["chat_id"], "ok": False}
        try:
            reply = await answer(s["chat_id"], s["query"], temperature=temperature)
            row["ok"] = True
            row["reply_chars"] = len(reply.text or "")
            row["n_proposals"] = len(reply.proposals)
        except Exception as exc:  # noqa: BLE001
            row["error"] = f"{type(exc).__name__}: {exc}"
            logger.warning("rollout failed: %s — %s", s["chat_id"], exc)
        results.append(row)

    # Join reward-labeled episodes back in.
    episodes = _episodes_by_chat_id({s["chat_id"] for s in seeds})
    for row in results:
        ep = episodes.get(row["chat_id"])
        if not ep:
            continue
        sig = ep.get("signals", {}) or {}
        rw = sig.get("reward") or {}
        row["model"] = sig.get("model")
        row["intent_logged"] = sig.get("intent")
        row["reasoning_effort"] = sig.get("reasoning_effort")
        row["tokens_in"] = sig.get("tokens_in")
        row["tokens_out"] = sig.get("tokens_out")
        row["reward_score"] = rw.get("score")

    # Aggregate.
    by_intent: Dict[str, Dict[str, Any]] = {}
    for row in results:
        it = row["intent"]
        b = by_intent.setdefault(it, {"count": 0, "scored": 0, "reward_sum": 0.0})
        b["count"] += 1
        if isinstance(row.get("reward_score"), (int, float)):
            b["scored"] += 1
            b["reward_sum"] += row["reward_score"]
    for b in by_intent.values():
        b["mean_reward"] = round(b["reward_sum"] / b["scored"], 3) if b["scored"] else None
        b.pop("reward_sum", None)

    summary = {
        "n": len(results),
        "n_ok": sum(1 for r in results if r["ok"]),
        "n_scored": sum(1 for r in results if isinstance(r.get("reward_score"), (int, float))),
        "by_intent": by_intent,
        "total_tokens_in": sum(r.get("tokens_in") or 0 for r in results),
        "total_tokens_out": sum(r.get("tokens_out") or 0 for r in results),
    }
    return {"rollouts": results, "summary": summary}


def generate(n_per_intent: int = 2, run_id: str = "r0") -> Dict[str, Any]:
    """Sync entry: build seeds, run them, return rollouts + summary."""
    seeds = build_seeds(n_per_intent=n_per_intent, run_id=run_id)
    return asyncio.run(run_rollouts(seeds))
