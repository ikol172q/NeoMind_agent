"""fin_evolve — mine reward-labeled episodes, draft human-reviewed harness proposals.

Phase 2b (``plans/2026-06-01_fin-harness-evolution-loop.md``).

The loop's payoff: read the reward-labeled trajectories (Phase 0) — real +
synthetic rollouts (Phase 2a) — find what systematically drags reward down,
and draft a **concrete, human-reviewed** proposal to fix the harness. Nothing
is auto-applied (user choice 2026-06-02: "提议+人审"). ``apply_proposal``
refuses unless ``approved=True`` and backs up the target first.

Why a focused module instead of reusing evolution.reflection / prompt_tuner:
those exist but target different substrates — ``ReflectionEngine`` generates
free-text *hypotheses* from conversation summaries (LLM-driven, no
reward/episode mining); ``PromptTuner`` does OPRO over *YAML params*
(temperature etc.), not freeform system.md text. The "mine reward-labeled fin
episodes by validator-rule cluster → draft a system.md text edit" layer is the
missing connective tissue, so it lives here. The dormant modules remain for
their own niches.

Design: mining is **deterministic** (cluster by the ``(Rule N)`` tag the
validator stamps on each warning) — no LLM, no hallucination. Proposals for
*known, unambiguous* rules are templated; ambiguous patterns (e.g. Rule 3,
which can be a validator false-positive on example numbers) are emitted as
``investigate`` proposals, not edits.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_RULE_RE = re.compile(r"\(Rule (\d+[a-z]?)\)")

# Where drafted proposals live (pending human review).
from agent.evolution.episode_capture import EPISODES_ROOT  # noqa: E402
PROPOSALS_ROOT = EPISODES_ROOT.parent / "proposals"

# system.md for the dashboard (Telegram) agent — the main evolvable surface.
SYSTEM_MD = Path(__file__).parent / "dashboard_agent" / "system.md"

# Known validator rules → how to act. Templated edits for the unambiguous
# ones; "investigate" for patterns that may be validator-side, not agent-side.
_RULE_PLAYBOOK: Dict[str, Dict[str, Any]] = {
    "4a": {
        "kind": "system_md_append",
        "title": "每条买卖/加减仓建议给至少 2 个时间框架",
        "section": "## ⚖️ 推荐合规(自动进化提议)",
        "text": "- **时间框架**:每条买卖/加减仓建议给至少 2 个(短/中/长期),"
                "各自写预期与触发条件。",
        "rationale": "validator Rule 4a 反复触发:推荐缺时间框架。system.md 当前没强制。",
    },
    "4c": {
        "kind": "system_md_append",
        "title": "每条推荐结尾附免责声明",
        "section": "## ⚖️ 推荐合规(自动进化提议)",
        "text": "- **免责声明**:涉及买卖建议的回复结尾加一句"
                "「以上为信号摘要,非投资建议,请自行复核」。",
        "rationale": "validator Rule 4c 反复触发:推荐缺免责声明。system.md 当前没强制。",
    },
    "3": {
        "kind": "investigate",
        "title": "价格缺来源标注 — 先查是 agent 漏标还是 validator 误报",
        "rationale": "Rule 3 触发最频繁,但部分被标价格(如 $100,001 / $250,000)像是"
                     "示例/阈值数字而非真实报价 → 可能是 validator 误报。system.md 已要求"
                     "每个数字带 [ev:]/[fact:]。先人工判断:① agent 真漏标 → 强化提示;"
                     "② validator 把示例数字当报价 → 改 validator 的价格抽取。不盲目改 prompt。",
    },
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# A prompt's closing "now begin" instruction. Rules appended AFTER it carry
# little authority (the model is already told to start), which measurably hurt
# compliance — so we insert evolution blocks into the body, just ABOVE it.
_CLOSING_ANCHOR_RE = re.compile(r"现在开始|现在,?\s*开始|now begin", re.IGNORECASE)


def _insert_block(original: str, block_lines: List[str]) -> str:
    """Insert ``block_lines`` into the prompt body, before the closing
    instruction (and any '---'/blank separator above it). Falls back to append
    when no closing anchor is found.
    """
    lines = original.split("\n")
    anchor = next((i for i, ln in enumerate(lines) if _CLOSING_ANCHOR_RE.search(ln)), None)
    if anchor is None:
        return original.rstrip("\n") + "\n" + "\n".join(block_lines) + "\n"
    j = anchor
    while j - 1 >= 0 and lines[j - 1].strip() in ("", "---"):
        j -= 1
    return "\n".join(lines[:j] + block_lines + lines[j:])


def _iter_episodes(days: int = 14, limit: int = 2000):
    from agent.evolution.episode_capture import iter_recent_episodes
    yield from iter_recent_episodes(limit=limit, days_back=days)


def mine(*, reward_max: float = 0.5, days: int = 14) -> Dict[str, Any]:
    """Cluster low-reward episodes by validator rule tag.

    Returns a diagnosis: per-rule {count, episodes, intents, examples} ranked
    by how many distinct episodes the rule drags, plus corpus stats.
    """
    # Score episodes with the OUTCOME-AWARE scorer: a decision that passed the
    # validator (compliant) but lost money now scores low and surfaces here —
    # the whole point of Phase 3.1. Episodes without a matured outcome score
    # exactly as before (just the dense validator base).
    from agent.finance import fin_reward, fin_outcome
    realized_index = fin_outcome.load_realized_index()

    n_total = 0
    n_low = 0
    n_synthetic = 0
    n_outcome = 0
    rule_stats: Dict[str, Dict[str, Any]] = {}
    for ep in _iter_episodes(days=days):
        sig = ep.get("signals") or {}
        rw = sig.get("reward") or {}
        if not isinstance(rw.get("score"), (int, float)):
            continue  # episode never got a reward — skip (unchanged gate)
        scored = fin_reward.score_episode(ep, realized_index=realized_index)
        score = scored["score"]
        if scored.get("matured"):
            n_outcome += 1
        n_total += 1
        if str(ep.get("session_id", "")).startswith("rollout-"):
            n_synthetic += 1
        if score > reward_max:
            continue
        n_low += 1
        intent = sig.get("intent")
        warnings = (rw.get("validator") or {}).get("warnings") or []
        seen_rules_this_ep = set()
        for w in warnings:
            m = _RULE_RE.search(w or "")
            rule = m.group(1) if m else "untagged"
            st = rule_stats.setdefault(
                rule, {"rule": rule, "count": 0, "episodes": 0,
                       "intents": set(), "examples": []})
            st["count"] += 1
            if rule not in seen_rules_this_ep:
                st["episodes"] += 1
                seen_rules_this_ep.add(rule)
            if intent:
                st["intents"].add(intent)
            if len(st["examples"]) < 3 and w not in st["examples"]:
                st["examples"].append(w)

    patterns = []
    for st in rule_stats.values():
        st["intents"] = sorted(st["intents"])
        patterns.append(st)
    # Rank by distinct episodes affected, then raw count.
    patterns.sort(key=lambda s: (s["episodes"], s["count"]), reverse=True)

    return {
        "generated_ts": _now_iso(),
        "params": {"reward_max": reward_max, "days": days},
        "corpus": {"scored_episodes": n_total, "low_reward_episodes": n_low,
                   "synthetic_episodes": n_synthetic,
                   "outcome_scored_episodes": n_outcome},
        "patterns": patterns,
    }


def propose(diagnosis: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Turn ranked patterns into concrete, human-reviewable proposals.

    Known unambiguous rules → templated proposal. Ambiguous → investigate.
    Unknown rules → a generic 'review' proposal (no auto-draft).
    """
    proposals: List[Dict[str, Any]] = []
    for pat in diagnosis.get("patterns", []):
        rule = pat["rule"]
        play = _RULE_PLAYBOOK.get(rule)
        base = {
            "id": uuid.uuid4().hex[:12],
            "created_ts": _now_iso(),
            "rule": rule,
            "evidence": {"count": pat["count"], "episodes": pat["episodes"],
                         "intents": pat["intents"], "examples": pat["examples"]},
            "status": "pending",
        }
        if play is None:
            proposals.append({**base, "kind": "review",
                              "title": f"未识别的 Rule {rule} 反复触发",
                              "rationale": "无模板,需人工判断改 system.md / 工具 / validator。",
                              "target": None, "proposed_change": None,
                              "expected_impact": "消除 Rule %s 警告" % rule})
            continue
        if play["kind"] == "investigate":
            proposals.append({**base, "kind": "investigate",
                              "title": play["title"], "rationale": play["rationale"],
                              "target": None, "proposed_change": None,
                              "expected_impact": "确认根因后再定改动"})
            continue
        # system_md_append
        proposals.append({**base, "kind": "system_md_append",
                          "title": play["title"], "rationale": play["rationale"],
                          "target": str(SYSTEM_MD),
                          "section": play["section"],
                          "proposed_change": play["text"],
                          "expected_impact": f"消除 Rule {rule} 警告 → 该类轨迹 reward 上移"})
    return proposals


def save_proposals(proposals: List[Dict[str, Any]]) -> List[str]:
    PROPOSALS_ROOT.mkdir(parents=True, exist_ok=True)
    paths = []
    for p in proposals:
        path = PROPOSALS_ROOT / f"{p['id']}.json"
        path.write_text(json.dumps(p, ensure_ascii=False, indent=2), encoding="utf-8")
        paths.append(str(path))
    return paths


def list_proposals(status: Optional[str] = None) -> List[Dict[str, Any]]:
    if not PROPOSALS_ROOT.exists():
        return []
    out = []
    for f in sorted(PROPOSALS_ROOT.glob("*.json")):
        try:
            p = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if status is None or p.get("status") == status:
            out.append(p)
    return out


def apply_proposal(proposal_id: str, *, approved: bool = False) -> Dict[str, Any]:
    """Apply an approved system_md_append proposal. REFUSES unless approved.

    Backs up the target (``.bak.<ts>``) before editing — reversible. The
    appended block is wrapped in a marker so it's easy to find/revert. This is
    the only place that mutates the harness, and only by explicit human go.
    Phase 2c will add golden-replay + drift gates in front of this.
    """
    if not approved:
        return {"ok": False, "error": "refused: proposal requires explicit approval (approved=True)"}
    path = PROPOSALS_ROOT / f"{proposal_id}.json"
    if not path.exists():
        return {"ok": False, "error": f"no such proposal: {proposal_id}"}
    p = json.loads(path.read_text(encoding="utf-8"))
    if p.get("status") != "pending":
        return {"ok": False, "error": f"proposal status is {p.get('status')}, not pending"}
    if p.get("kind") != "system_md_append":
        return {"ok": False, "error": f"apply only supports system_md_append, got {p.get('kind')}"}

    target = Path(p["target"])
    if not target.exists():
        return {"ok": False, "error": f"target missing: {target}"}
    original = target.read_text(encoding="utf-8")
    marker = f"<!-- fin_evolve:{proposal_id} -->"
    if marker in original:
        return {"ok": False, "error": "already applied (marker present)"}

    ts = _now_iso().replace(":", "").replace("-", "")[:15]
    backup = target.with_suffix(target.suffix + f".bak.{ts}")
    backup.write_text(original, encoding="utf-8")

    block_lines = ["", p["section"], marker, p["proposed_change"], ""]
    new_text = _insert_block(original, block_lines)
    target.write_text(new_text, encoding="utf-8")

    p["status"] = "applied"
    p["applied_ts"] = _now_iso()
    p["backup"] = str(backup)
    path.write_text(json.dumps(p, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "backup": str(backup),
            "inserted_chars": len(new_text) - len(original)}


def _mark_status(proposal_id: str, status: str) -> None:
    path = PROPOSALS_ROOT / f"{proposal_id}.json"
    if path.exists():
        p = json.loads(path.read_text(encoding="utf-8"))
        p["status"] = status
        p["status_ts"] = _now_iso()
        path.write_text(json.dumps(p, ensure_ascii=False, indent=2), encoding="utf-8")


def _mean_reward(rollouts_result: Dict[str, Any]) -> Optional[float]:
    scores = [r.get("reward_score") for r in rollouts_result.get("rollouts", [])
              if isinstance(r.get("reward_score"), (int, float))]
    return round(sum(scores) / len(scores), 3) if scores else None


async def gated_apply(proposal_ids, *, intents=("decision", "synthesis"),
                      runs_per_intent: int = 3, min_improve: float = 0.05,
                      min_pairs: int = 3, min_win_rate: float = 0.6,
                      run_id: str = "gate") -> Dict[str, Any]:
    """Phase 2c/3.2 — statistically-gated reward-delta apply.

    baseline rollout → apply proposal(s) → verification rollout → decide:
      - ``inconclusive`` : fewer than ``min_pairs`` paired queries — not enough
        evidence to trust ANY delta (the n=2 noise trap from 2026-06-03). The
        edit is rolled back; nothing is promoted on insufficient power.
      - ``kept``         : mean paired improvement >= ``min_improve`` AND a
        majority (``min_win_rate``) of paired queries individually improved.
      - ``reverted``     : regression or sub-threshold noise.

    Evaluation rollouts run at temperature=0 and are compared PER-QUERY
    (paired) to cancel query-to-query variance. The old lax ``min_delta=-0.1``
    (which admitted zero/negative deltas) is gone — a change must *earn* its
    keep. (drift_detector PSI / golden corpus still deferred — Phase 3.3.)

    Returns the measurement: before / after / delta / win_rate / n_paired /
    status / kept / reverted.
    """
    from agent.finance import fin_rollout
    proposal_ids = list(proposal_ids)
    intents = list(intents)

    if not SYSTEM_MD.exists():
        return {"ok": False, "error": f"system.md missing: {SYSTEM_MD}"}
    snapshot = SYSTEM_MD.read_text(encoding="utf-8")  # one snapshot → clean multi-revert

    # Evaluation rollouts run at temperature=0 (deterministic) so the SAME
    # query is reproducible — the only thing that changes between base and
    # verify is the prompt edit. We then compare PER-QUERY (paired) deltas,
    # which cancels query-to-query variance. Both are needed because the raw
    # reward is bimodal and noisy at small n (see troubleshooting 2026-06-03).
    base = await fin_rollout.run_rollouts(
        fin_rollout.build_seeds(runs_per_intent, run_id=f"{run_id}-base", intents=intents),
        temperature=0.0)
    before = _mean_reward(base)

    applied = []
    for pid in proposal_ids:
        res = apply_proposal(pid, approved=True)
        if not res.get("ok"):
            SYSTEM_MD.write_text(snapshot, encoding="utf-8")  # abort → restore
            return {"ok": False, "error": f"apply failed for {pid}: {res.get('error')}",
                    "before": before, "applied": applied}
        applied.append(pid)

    ver = await fin_rollout.run_rollouts(
        fin_rollout.build_seeds(runs_per_intent, run_id=f"{run_id}-verify", intents=intents),
        temperature=0.0)
    after = _mean_reward(ver)

    paired_delta, pairs = _paired_delta(base, ver)
    # Decide on the PAIRED delta (variance-reduced); fall back to mean diff.
    delta = paired_delta if paired_delta is not None else (
        None if (before is None or after is None) else round(after - before, 3))
    n_pairs = len(pairs)
    wins = sum(1 for p in pairs
               if isinstance(p.get("delta"), (int, float)) and p["delta"] > 0)
    win_rate = round(wins / n_pairs, 3) if n_pairs else None

    # Gate decision (Phase 3.2 — power, not a lax -0.1 threshold). Asymmetry is
    # gone: a zero/negative delta no longer "passes".
    if delta is None or n_pairs < min_pairs:
        status = "inconclusive"          # not enough evidence to trust a delta
    elif delta >= min_improve and win_rate is not None and win_rate >= min_win_rate:
        status = "kept"
    else:
        status = "reverted"              # regression or sub-threshold noise
    kept = status == "kept"

    common = {"before": before, "after": after, "delta": delta,
              "paired_delta": paired_delta, "n_paired": n_pairs,
              "win_rate": win_rate, "pairs": pairs, "status": status,
              "min_improve": min_improve, "min_pairs": min_pairs,
              "min_win_rate": min_win_rate, "proposals": applied}
    if not kept:
        SYSTEM_MD.write_text(snapshot, encoding="utf-8")
        for pid in applied:
            _mark_status(pid, status)    # "reverted" or "inconclusive"
        return {"ok": True, "kept": False, "reverted": True, **common}

    for pid in applied:
        _mark_status(pid, "applied_verified")
    return {"ok": True, "kept": True, "reverted": False, **common}


def _paired_delta(base: Dict[str, Any], ver: Dict[str, Any]):
    """Match base vs verify rollouts by query and return (mean_delta, pairs).

    Pairing cancels query-to-query variance: only the prompt edit differs
    between the two runs of the same (temperature=0) query.
    """
    bmap = {r["query"]: r.get("reward_score") for r in base.get("rollouts", [])}
    pairs = []
    for r in ver.get("rollouts", []):
        q, a, b = r["query"], r.get("reward_score"), bmap.get(r["query"])
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            pairs.append({"query": q, "before": b, "after": a, "delta": round(a - b, 3)})
    mean_delta = round(sum(p["delta"] for p in pairs) / len(pairs), 3) if pairs else None
    return mean_delta, pairs


def run(*, reward_max: float = 0.5, days: int = 14) -> Dict[str, Any]:
    """Mine → propose → persist. Does NOT apply. Returns diagnosis + proposals."""
    diag = mine(reward_max=reward_max, days=days)
    proposals = propose(diag)
    save_proposals(proposals)
    return {"diagnosis": diag, "proposals": proposals}
