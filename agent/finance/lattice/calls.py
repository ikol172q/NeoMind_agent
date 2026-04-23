"""L3 · Toulmin-structured actionable calls.

One LLM pass returns up to 5 candidate calls from the L2 theme set.
MMR (λ=0.7) then picks at most 3 diverse calls. Post-validation
drops any call whose `grounds` list references a theme_id that
doesn't exist in the current refresh — the LLM cannot invent
grounds that L2 didn't surface.

Zero calls is a valid output: "no high-conviction action today"
beats forced emission. We explicitly tell the LLM this in the
system prompt and accept empty responses.

Why Toulmin and not free-form advice? The structure (claim /
grounds / warrant / qualifier / rebuttal) forces the LLM to name
*why* the grounds justify the claim (warrant) and *what would
falsify it* (rebuttal). That makes each call independently
auditable — the user can accept the grounds but reject the
warrant, or accept both but trigger on the rebuttal condition.

Plan: plans/2026-04-20_insight-lattice.md §L3.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence

import httpx

from agent.finance.lattice import spec
from agent.finance.lattice.themes import Theme, build_themes

logger = logging.getLogger(__name__)

_DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
_CALLS_MODEL = "deepseek-chat"
_CALLS_TTL_S = 900.0           # 15 min, per plan
_CALLS_TIMEOUT_S = 45.0

# Identity imports from spec — same objects, not copies. L1
# contract tests assert this with `is`.
_MAX_CANDIDATES = spec.MAX_CANDIDATES
_MAX_CALLS = spec.MAX_CALLS
_MMR_LAMBDA = spec.MMR_LAMBDA

_CONFIDENCE = spec.CONFIDENCE_VALUES
_HORIZON = spec.TIME_HORIZON_VALUES

_calls_cache: Dict[str, tuple[float, Dict[str, Any]]] = {}
_calls_cache_lock = threading.Lock()


# ── Data class ─────────────────────────────────────────

@dataclass
class Call:
    id: str
    claim: str
    grounds: List[str]              # theme_ids
    warrant: str                    # why grounds justify claim
    qualifier: str                  # condition/confidence modifier
    rebuttal: str                   # what would invalidate the call
    confidence: str                 # high | medium | low
    time_horizon: str               # intraday | days | weeks | quarter

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ── LLM generation ─────────────────────────────────────

_SYSTEM_PROMPT_BASE = (
    "You are a disciplined investment analyst. Given a set of "
    "observational themes (pre-clustered facts from the market + the "
    "user's positions), propose up to 5 CANDIDATE actionable calls "
    "using the Toulmin argument structure: claim, grounds, warrant, "
    "qualifier, rebuttal. "
    "HARD RULES: "
    "(1) Every call's `grounds` list must reference theme_ids from "
    "the provided set — no invented grounds. "
    "(2) The `warrant` must explain WHY the grounds imply the claim "
    "(not restate the claim). "
    "(3) The `rebuttal` must name a concrete observable that would "
    "falsify the call. "
    "(4) If the themes do not support ANY high-conviction call, "
    "return an EMPTY candidates list — zero calls is a valid answer. "
    "Never force-emit. "
    "Reply JSON only."
)


def _system_prompt() -> str:
    """System prompt = base + language directive from taxonomy (V5)."""
    from agent.finance.lattice.taxonomy import load_taxonomy
    lang = load_taxonomy().output_language
    return _SYSTEM_PROMPT_BASE + spec.language_directive(lang)


def _generation_prompt(themes: List[Theme]) -> str:
    lines: List[str] = []
    for t in themes:
        lines.append(
            f'  - theme_id="{t.id}" · title="{t.title}" · '
            f'severity={t.severity} · members={len(t.members)} · '
            f'narrative="{t.narrative}"'
        )
    themes_block = "\n".join(lines) if lines else "  (no themes available)"
    return (
        "AVAILABLE THEMES (the ONLY valid `grounds` values):\n"
        f"{themes_block}\n\n"
        "Task: Propose up to 5 candidate actionable calls. Each call "
        "must have every field filled. Candidate diversity matters — "
        "the downstream MMR selector will drop duplicates. If no "
        "high-conviction call exists, return empty list.\n\n"
        "QUALIFIER RULE: the qualifier MUST include at least one "
        "concrete threshold or trigger — a number, a ratio, a named "
        "sizing rule, or a named index/ratio crossing. Examples of "
        "GOOD qualifiers: 'size at ≤ 2% of book', 'skip if VIX > 22', "
        "'intraday only; unwind before close', '30d ATM puts, not "
        "weeklies'. Examples of BAD qualifiers (DO NOT PRODUCE): "
        "'market conditions may change', 'moderate conviction', "
        "'this is a tactical call'. If you cannot state a concrete "
        "trigger, you do not have a high-conviction call — drop it.\n\n"
        "REBUTTAL RULE: the rebuttal MUST name a specific observable "
        "that would falsify the call (e.g. 'if VIX closes above 25', "
        "'if AAPL reports revenue > 10% below guidance'). Vague "
        "rebuttals ('unexpected events') are unacceptable.\n\n"
        'Reply with JSON: {"candidates": [ '
        '{"claim": "...", "grounds": ["theme_id_1", ...], '
        '"warrant": "...", "qualifier": "...", "rebuttal": "...", '
        '"confidence": "high|medium|low", '
        '"time_horizon": "intraday|days|weeks|quarter"}, ... ]}'
    )


def _call_llm(prompt: str) -> Dict[str, Any]:
    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY missing")
    with httpx.Client(timeout=httpx.Timeout(_CALLS_TIMEOUT_S)) as client:
        resp = client.post(
            _DEEPSEEK_URL,
            json={
                "model": _CALLS_MODEL,
                "messages": [
                    {"role": "system", "content": _system_prompt()},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.4,
                "max_tokens": 1200,
                "response_format": {"type": "json_object"},
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
    if resp.status_code != 200:
        raise RuntimeError(f"DeepSeek {resp.status_code}: {resp.text[:200]}")
    return json.loads(resp.json()["choices"][0]["message"]["content"])


# ── Validation ─────────────────────────────────────────

_REQUIRED = spec.CALL_REQUIRED_FIELDS


def _validate_candidate(
    raw: Dict[str, Any],
    valid_theme_ids: set[str],
) -> Optional[Dict[str, Any]]:
    """Return a sanitised dict or None if the candidate is invalid.

    Rules:
      - All required fields present and non-empty strings (except grounds).
      - grounds is a non-empty list of theme_ids all existing in the
        current refresh — drops calls that reference phantom themes.
      - confidence / time_horizon must be in the allowed enum.
      - warrant must be distinct from the claim (not a tautology).
    """
    try:
        for f in _REQUIRED:
            if f not in raw:
                return None
        claim = str(raw["claim"]).strip()
        warrant = str(raw["warrant"]).strip()
        qualifier = str(raw["qualifier"]).strip()
        rebuttal = str(raw["rebuttal"]).strip()
        if not (claim and warrant and qualifier and rebuttal):
            return None
        # Tautology guard — spec-defined, TAUTOLOGY_MIN_EXTENSION
        # chars of extension required. See spec.is_tautological_warrant.
        if spec.is_tautological_warrant(claim, warrant):
            return None
        grounds_raw = raw.get("grounds") or []
        if not isinstance(grounds_raw, list) or not grounds_raw:
            return None
        grounds = [str(g).strip() for g in grounds_raw if str(g).strip()]
        if not grounds:
            return None
        # Every ground must be a real theme
        unknown = [g for g in grounds if g not in valid_theme_ids]
        if unknown:
            logger.info("calls: dropping candidate — unknown grounds %s", unknown)
            return None
        confidence = str(raw["confidence"]).strip().lower()
        if confidence not in _CONFIDENCE:
            return None
        horizon = str(raw["time_horizon"]).strip().lower()
        if horizon not in _HORIZON:
            return None
        return {
            "claim": claim,
            "grounds": grounds,
            "warrant": warrant,
            "qualifier": qualifier,
            "rebuttal": rebuttal,
            "confidence": confidence,
            "time_horizon": horizon,
        }
    except Exception as exc:
        logger.warning("calls: candidate validation failed: %s", exc)
        return None


# ── MMR selector ───────────────────────────────────────

def _ground_similarity(a: Sequence[str], b: Sequence[str]) -> float:
    """Thin adapter over spec.ground_similarity (Sequence vs Set)."""
    return spec.ground_similarity(set(a), set(b))


def _relevance_score(call: Dict[str, Any], theme_by_id: Dict[str, Theme]) -> float:
    """A call's MMR relevance — delegates to spec.relevance_score so
    there is one source of truth for the severity × confidence math."""
    grounds = []
    for gid in call["grounds"]:
        t = theme_by_id.get(gid)
        if t is None:
            continue
        grounds.append((t.severity, len(t.members)))
    return spec.relevance_score(grounds, call["confidence"])


def select_calls_mmr(
    candidates: List[Dict[str, Any]],
    themes: List[Theme],
    *,
    k: int = _MAX_CALLS,
    lambda_: float = _MMR_LAMBDA,
) -> List[Dict[str, Any]]:
    """MMR over the candidate pool. Similarity between two calls =
    Jaccard of their `grounds` sets; two calls that quote the same
    evidence are redundant.

    MMR(c) = λ·rel(c) − (1−λ)·max(sim(c, s) for s in selected)
    """
    if not candidates:
        return []
    theme_by_id = {t.id: t for t in themes}
    remaining = list(candidates)
    # Stable ID assignment for output
    for i, c in enumerate(remaining):
        c.setdefault("_rel", _relevance_score(c, theme_by_id))

    selected: List[Dict[str, Any]] = []
    seen_ground_sets: set[frozenset[str]] = set()
    while remaining and len(selected) < k:
        best = None
        best_score = -1e9
        for c in remaining:
            # Hard dedup: two calls with identical grounds are
            # redundant by the plan's diversity rule, regardless of
            # what MMR would pick.
            if frozenset(c["grounds"]) in seen_ground_sets:
                continue
            rel = c["_rel"]
            if selected:
                max_sim = max(
                    _ground_similarity(c["grounds"], s["grounds"]) for s in selected
                )
            else:
                max_sim = 0.0
            mmr_score = spec.mmr(rel, max_sim, lambda_)
            if mmr_score > best_score:
                best_score = mmr_score
                best = c
        if best is None:
            break
        selected.append(best)
        seen_ground_sets.add(frozenset(best["grounds"]))
        remaining.remove(best)

    for c in selected:
        c.pop("_rel", None)
    return selected


# ── Cache ──────────────────────────────────────────────

def _cache_key(project_id: str, themes: List[Theme]) -> str:
    tid = "|".join(sorted(t.id for t in themes))
    tn = "|".join(sorted(t.narrative for t in themes))
    return hashlib.sha1(f"{project_id}::{tid}::{tn}".encode()).hexdigest()[:12]


def _cached(key: str) -> Optional[Dict[str, Any]]:
    with _calls_cache_lock:
        entry = _calls_cache.get(key)
    if entry is None:
        return None
    if time.time() - entry[0] > _CALLS_TTL_S:
        return None
    return entry[1]


def _put(key: str, value: Dict[str, Any]) -> None:
    with _calls_cache_lock:
        _calls_cache[key] = (time.time(), value)


# ── Pipeline entry points ──────────────────────────────

def generate_calls(
    themes: List[Theme],
    *,
    project_id: str = "",
    fresh: bool = False,
) -> List[Call]:
    """Generate up to 3 Toulmin calls from the given themes.

    Contract: returns [] in every failure mode (LLM unreachable,
    malformed JSON, no valid candidates). L3 should never take down
    the endpoint.
    """
    if not themes:
        return []

    cache_key = _cache_key(project_id, themes)
    if not fresh:
        cached = _cached(cache_key)
        if cached is not None:
            return [Call(**c) for c in cached.get("calls", [])]

    valid_theme_ids = {t.id for t in themes}
    prompt = _generation_prompt(themes)
    try:
        reply = _call_llm(prompt)
    except Exception as exc:
        logger.warning("calls: LLM generation failed: %s", exc)
        _put(cache_key, {"calls": []})
        return []

    raw_candidates = reply.get("candidates") or []
    if not isinstance(raw_candidates, list):
        logger.warning("calls: malformed candidates: %r", type(raw_candidates))
        _put(cache_key, {"calls": []})
        return []

    validated: List[Dict[str, Any]] = []
    for raw in raw_candidates[:_MAX_CANDIDATES]:
        v = _validate_candidate(raw, valid_theme_ids)
        if v is not None:
            validated.append(v)

    if not validated:
        logger.info("calls: no candidates passed validation — zero-call output")
        _put(cache_key, {"calls": []})
        return []

    picked = select_calls_mmr(validated, themes)

    calls: List[Call] = []
    for i, c in enumerate(picked):
        calls.append(Call(
            id=f"call_{i+1:03d}",
            claim=c["claim"],
            grounds=c["grounds"],
            warrant=c["warrant"],
            qualifier=c["qualifier"],
            rebuttal=c["rebuttal"],
            confidence=c["confidence"],
            time_horizon=c["time_horizon"],
        ))

    _put(cache_key, {"calls": [call.to_dict() for call in calls]})
    return calls


def build_calls(project_id: str, *, fresh: bool = False) -> Dict[str, Any]:
    """Full L1 + L2 + L3 pipeline for the endpoint."""
    themes_payload = build_themes(project_id, fresh=fresh)
    # Re-hydrate Theme objects for generate_calls (build_themes returns dicts)
    from agent.finance.lattice.themes import ThemeMember
    themes = [
        Theme(
            id=t["id"],
            title=t["title"],
            narrative=t["narrative"],
            narrative_source=t["narrative_source"],
            members=[ThemeMember(**m) for m in t["members"]],
            tags=t["tags"],
            severity=t["severity"],
            cited_numbers=t.get("cited_numbers", []),
        )
        for t in themes_payload["themes"]
    ]
    calls = generate_calls(themes, project_id=project_id, fresh=fresh)
    return {
        **themes_payload,
        "calls": [c.to_dict() for c in calls],
    }
