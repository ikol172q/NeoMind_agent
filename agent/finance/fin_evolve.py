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


def _iter_episodes(days: int = 14, limit: int = 2000):
    from agent.evolution.episode_capture import iter_recent_episodes
    yield from iter_recent_episodes(limit=limit, days_back=days)


def mine(*, reward_max: float = 0.5, days: int = 14) -> Dict[str, Any]:
    """Cluster low-reward episodes by validator rule tag.

    Returns a diagnosis: per-rule {count, episodes, intents, examples} ranked
    by how many distinct episodes the rule drags, plus corpus stats.
    """
    n_total = 0
    n_low = 0
    n_synthetic = 0
    rule_stats: Dict[str, Dict[str, Any]] = {}
    for ep in _iter_episodes(days=days):
        sig = ep.get("signals") or {}
        rw = sig.get("reward") or {}
        score = rw.get("score")
        if not isinstance(score, (int, float)):
            continue
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
                   "synthetic_episodes": n_synthetic},
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

    block = f"\n\n{p['section']}\n{marker}\n{p['proposed_change']}\n"
    target.write_text(original + block, encoding="utf-8")

    p["status"] = "applied"
    p["applied_ts"] = _now_iso()
    p["backup"] = str(backup)
    path.write_text(json.dumps(p, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "backup": str(backup), "appended_chars": len(block)}


def run(*, reward_max: float = 0.5, days: int = 14) -> Dict[str, Any]:
    """Mine → propose → persist. Does NOT apply. Returns diagnosis + proposals."""
    diag = mine(reward_max=reward_max, days=days)
    proposals = propose(diag)
    save_proposals(proposals)
    return {"diagnosis": diag, "proposals": proposals}
