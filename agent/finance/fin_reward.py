"""fin_reward — synthesize a per-turn reward for the fin agent harness.

Phase 0 of the Fin Harness Evolution Loop
(``plans/2026-06-01_fin-harness-evolution-loop.md``).

The fin agent runs on a **frozen, remote** model (DeepSeek V4) — we can't
fine-tune it. To make the *harness* self-evolving we need a reward signal
attached to every turn's trajectory, the way an RL rollout attaches reward
to an episode. The dormant evolution loop (``reflection`` / ``prompt_tuner``
/ ``distillation`` / ``skill_forge``) can then mine *low-reward* turns and
propose harness fixes. This module is the scoreboard those modules read.

It computes reward only from signals NeoMind already produces:

  Dense / immediate (synchronous, cheap — always computed):
    - validator: ``FinanceResponseValidator`` five-rules verdict
      (passed / warnings / blocked). "Did the answer obey the correctness
      rules?" Pure regex, no network.

  Dense / immediate (OPT-IN, network-heavy → default OFF):
    - scorecard agreement: for each decision the agent *proposed*, does its
      lean match the deterministic ``decision_scorecard`` lean? Enable with
      ``with_scorecard=True`` or env ``NEOMIND_FIN_REWARD_SCORECARD=1``.

  Sparse / delayed (NOT computed here — hook only):
    - paper PnL: only known after a proposal is accepted and time passes.
      We record the proposed decisions under ``pending_pnl`` so a later
      backfill job (Phase 2) can attach realized PnL to this episode.

Design rules
------------
- NEVER raise into the response path. Every public function is best-effort;
  on any internal error it returns a reward bag with ``error`` set and a
  neutral-ish score, so a broken reward computation can't break a reply.
- The default path does NO network I/O. Scorecard is opt-in.
- Output is a plain JSON-serializable dict so it can live inside an
  episode's ``signals`` bag (schema-stable).
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

SCHEMA = "fin_reward.v1"

# Decision vocabulary shared by dashboard_agent proposals and
# decision_scorecard.build_scorecard()["suggested_lean"].
_BULLISH = {"add"}
_NEUTRAL = {"hold", "watch_only"}
_BEARISH = {"trim", "sell", "pass"}


def _group(lean: str) -> str:
    if lean in _BULLISH:
        return "bull"
    if lean in _BEARISH:
        return "bear"
    if lean in _NEUTRAL:
        return "neutral"
    return "unknown"


def _agreement(proposed: str, lean: str) -> float:
    """Score how well a proposed action agrees with the scorecard lean.

    +1.0 exact match · +0.3 same direction group · -1.0 opposite
    (bull vs bear) · 0.0 when one side is neutral and the other directional,
    or either is unknown.
    """
    proposed = (proposed or "").strip().lower()
    lean = (lean or "").strip().lower()
    if not proposed or not lean:
        return 0.0
    if proposed == lean:
        return 1.0
    gp, gl = _group(proposed), _group(lean)
    if gp == "unknown" or gl == "unknown":
        return 0.0
    if gp == gl:
        return 0.3
    if {gp, gl} == {"bull", "bear"}:
        return -1.0
    return 0.0


def _validator_score(passed: bool, blocked: bool, n_warnings: int) -> float:
    """Map a validator verdict to [-1, 1].

    blocked → -1.0 (hard correctness failure)
    failed (not blocked) → -0.5
    passed, no warnings → 1.0
    passed, k warnings → decays from 0.8, floored at 0.2
    """
    if blocked:
        return -1.0
    if not passed:
        return -0.5
    if n_warnings <= 0:
        return 1.0
    return max(0.2, 0.8 - 0.2 * n_warnings)


def _run_validator(reply: str, tool_results: Optional[List[Dict[str, Any]]],
                   strict: bool) -> Dict[str, Any]:
    """Best-effort validator pass. Returns a JSON-able sub-bag."""
    try:
        from agent.finance.response_validator import get_finance_validator
        vr = get_finance_validator(strict=strict).validate(
            reply or "", tool_results=tool_results or [])
        passed = bool(getattr(vr, "passed", True))
        blocked = bool(getattr(vr, "blocked", False))
        warnings = list(getattr(vr, "warnings", []) or [])
        # Capture the structured fields too — a failed turn often sets these
        # WITHOUT appending a warning string (e.g. an unverified price), so
        # without them passed=False is opaque and the miner can't act on it.
        unverified = list(getattr(vr, "unverified_prices", []) or [])
        unsourced = list(getattr(vr, "unsourced_data", []) or [])
        approx = list(getattr(vr, "approximate_calcs", []) or [])
        flags = [k for k in ("missing_time_horizons", "missing_confidence",
                             "missing_disclaimer") if getattr(vr, k, False)]
        return {
            "passed": passed,
            "blocked": blocked,
            "n_warnings": len(warnings),
            "warnings": warnings[:8],
            "unverified_prices": unverified[:8],
            "unsourced_data": unsourced[:8],
            "approximate_calcs": approx[:8],
            "missing_flags": flags,
            "action": getattr(vr, "action", "") or "",
            "reason": getattr(vr, "reason", "") or "",
            "score": round(_validator_score(passed, blocked, len(warnings)), 3),
        }
    except Exception:  # never break the reply path
        logger.debug("fin_reward: validator failed", exc_info=True)
        return {"passed": True, "blocked": False, "n_warnings": 0,
                "warnings": [], "unverified_prices": [], "unsourced_data": [],
                "approximate_calcs": [], "missing_flags": [],
                "action": "", "reason": "", "score": 0.0,
                "error": "validator_failed"}


def _run_scorecard(decisions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Best-effort scorecard-agreement pass (network-heavy — opt-in only)."""
    items: List[Dict[str, Any]] = []
    try:
        from agent.finance.decision_scorecard import build_scorecard
        for d in decisions:
            ticker = (d.get("ticker") or "").strip().upper()
            action = (d.get("action") or "").strip().lower()
            if not ticker or not action:
                continue
            try:
                sc = build_scorecard(ticker)
                lean = (sc.get("suggested_lean") or "").lower()
                agree = _agreement(action, lean)
                items.append({"ticker": ticker, "proposed": action,
                              "scorecard_lean": lean, "agreement": agree})
            except Exception:
                items.append({"ticker": ticker, "proposed": action,
                              "scorecard_lean": None, "agreement": None,
                              "error": "build_scorecard_failed"})
    except Exception:
        logger.debug("fin_reward: scorecard import failed", exc_info=True)
        return {"computed": False, "n_decisions": len(decisions),
                "agreement": None, "items": [], "error": "scorecard_failed"}

    scored = [i["agreement"] for i in items if isinstance(i.get("agreement"), (int, float))]
    avg = round(sum(scored) / len(scored), 3) if scored else None
    return {"computed": True, "n_decisions": len(decisions),
            "agreement": avg, "items": items}


def compute_reward(
    *,
    query: str,
    reply: str,
    tool_results: Optional[List[Dict[str, Any]]] = None,
    decisions: Optional[List[Dict[str, Any]]] = None,
    finish_reason: Optional[str] = None,
    with_scorecard: Optional[bool] = None,
    strict: bool = False,
) -> Dict[str, Any]:
    """Compute a per-turn reward bag for the fin agent.

    Args:
        query: the user's message (kept for traceability, not scored).
        reply: the final assistant text the user saw.
        tool_results: tool turns from this answer() call — each a dict with
            a ``content`` (or ``output``) key. Passed to the validator so it
            can tell tool-grounded numbers from hallucinated ones.
        decisions: proposed write-actions extracted from the reply, each
            ``{"ticker", "action", "note"}`` (action in the scorecard lean
            vocabulary). Used for scorecard agreement + the delayed-PnL hook.
        finish_reason: "stop" | "length" | "max_turns" | "llm_error" — a
            non-"stop" finish caps the score (degenerate trajectory).
        with_scorecard: run the network-heavy scorecard agreement pass.
            Defaults to env ``NEOMIND_FIN_REWARD_SCORECARD`` (off).
        strict: run the validator in strict (blocking) mode.

    Returns:
        JSON-serializable reward bag (see SCHEMA). Always returns — never
        raises.
    """
    decisions = decisions or []
    if with_scorecard is None:
        with_scorecard = os.getenv("NEOMIND_FIN_REWARD_SCORECARD", "") not in ("", "0", "false", "False")

    reply = reply or ""
    empty_reply = not reply.strip()
    # Split infra failures from agent-attributable ones. An LLM/router error
    # (llm_error) says NOTHING about harness quality, so it must NOT become a
    # negative the miner clusters against — exclude it from the signal entirely
    # (score=None → every numeric consumer skips it). A non-converging loop
    # (max_turns) or an empty reply IS agent-attributable → hard negative.
    infra_error = finish_reason == "llm_error"
    agent_error = finish_reason == "max_turns"

    validator = _run_validator(reply, tool_results, strict)

    scorecard: Dict[str, Any]
    if with_scorecard and decisions:
        scorecard = _run_scorecard(decisions)
    else:
        scorecard = {"computed": False, "n_decisions": len(decisions),
                     "agreement": None, "items": []}

    # ── combine ──
    score: Optional[float] = validator["score"]
    if scorecard.get("computed") and scorecard.get("agreement") is not None:
        score = 0.7 * validator["score"] + 0.3 * float(scorecard["agreement"])
    if infra_error:
        score = None                       # no signal — excluded everywhere
    elif empty_reply or agent_error:
        score = min(score, -1.0)           # agent-attributable hard negative

    return {
        "schema": SCHEMA,
        "score": (round(float(score), 3) if isinstance(score, (int, float)) else None),
        "validator": validator,
        "scorecard": scorecard,
        # Delayed-reward hook: the decisions the agent proposed this turn.
        # A Phase-2 backfill job attaches realized paper PnL here later.
        "pending_pnl": [
            {"ticker": (d.get("ticker") or "").upper(),
             "action": (d.get("action") or "").lower(),
             "note": d.get("note") or ""}
            for d in decisions
            if d.get("ticker") and d.get("action")
        ],
        "structural": {
            "empty_reply": empty_reply,
            "error_reply": bool(infra_error or agent_error),   # back-compat
            "infra_error": infra_error,
            "agent_error": agent_error,
            "finish_reason": finish_reason,
            "n_decisions": len(decisions),
            "n_tool_results": len(tool_results or []),
        },
    }


# How much a *matured* forward-return outcome (fin_outcome.backfill) shifts an
# episode's offline score relative to the dense validator score. Kept below 0.5
# on purpose: a single short-horizon return is noisy, so the dense compliance
# signal still anchors the score until many outcomes accumulate.
_OUTCOME_WEIGHT = 0.4


def score_episode(episode: Dict[str, Any], *,
                  realized_index: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """Unified OFFLINE score for a recorded episode — for mining / dashboards.

    Blends the dense reward already stored at turn time (validator, plus
    scorecard if it was enabled) with the sparse *realized* outcome (forward
    return) once ``fin_outcome.backfill`` has matured it.

    Pure function: NO network, NO validator re-run. It reads the stored
    ``signals.reward`` and a precomputed ``realized_index`` (req_id → reward
    from ``fin_outcome.load_realized_index``). When no outcome is available yet
    the score is just the dense base — identical to the legacy behaviour, so
    callers can switch over without changing results for un-matured episodes.

    Returns ``{score, base, realized, matured}``.
    """
    try:
        sig = episode.get("signals") or {}
        rw = sig.get("reward") or {}
        base = rw.get("score")
        if not isinstance(base, (int, float)):
            base = (rw.get("validator") or {}).get("score")
        if not isinstance(base, (int, float)):
            base = 0.0
        base = float(base)

        realized: Optional[float] = None
        if realized_index:
            rid = episode.get("req_id")
            if rid is not None:
                cand = realized_index.get(rid)
                if isinstance(cand, (int, float)):
                    realized = float(cand)

        if realized is not None:
            score = round((1.0 - _OUTCOME_WEIGHT) * base + _OUTCOME_WEIGHT * realized, 3)
            return {"score": score, "base": round(base, 3),
                    "realized": round(realized, 3), "matured": True}
        return {"score": round(base, 3), "base": round(base, 3),
                "realized": None, "matured": False}
    except Exception:  # never raise from offline scoring
        logger.debug("fin_reward.score_episode failed", exc_info=True)
        return {"score": 0.0, "base": 0.0, "realized": None, "matured": False,
                "error": "score_episode_failed"}
