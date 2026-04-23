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

# V6 deep-trace: keyed by call_id in its final slot (after MMR
# selection). Also keep the full pool under a sentinel key so a
# trace request against a dropped candidate ("why wasn't THIS
# candidate shipped?") can be answered. TTL matches calls cache.
_calls_trace: Dict[str, tuple[float, Dict[str, Any]]] = {}
_calls_trace_lock = threading.Lock()
_POOL_TRACE_KEY = "__pool__"


def _put_call_trace(call_id: str, entry: Dict[str, Any]) -> None:
    with _calls_trace_lock:
        _calls_trace[call_id] = (time.time(), entry)


def get_call_trace(call_id: str) -> Optional[Dict[str, Any]]:
    """Return trace for a specific call_id (call_001, call_002, ...).
    The pool — list of ALL candidates with accept/drop reasons — is
    under the sentinel key returned by get_call_pool_trace below."""
    with _calls_trace_lock:
        entry = _calls_trace.get(call_id)
    if entry is None:
        return None
    if time.time() - entry[0] > _CALLS_TTL_S:
        return None
    return entry[1]


def get_call_pool_trace() -> Optional[Dict[str, Any]]:
    """The shared candidate-pool trace for the most recent
    generate_calls() invocation. Every call_* node shares this."""
    return get_call_trace(_POOL_TRACE_KEY)


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
    """V6: use runtime.get_effective_language() so the UI toggle
    (POST /api/lattice/language) can override the YAML default
    without a restart."""
    from agent.finance.lattice import runtime
    return _SYSTEM_PROMPT_BASE + spec.language_directive(runtime.get_effective_language())


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
) -> tuple[Optional[Dict[str, Any]], Optional[str], Optional[Dict[str, Any]]]:
    """V6: returns a 3-tuple (sanitised, drop_reason, drop_detail).

    - On success: (sanitised_dict, None, None)
    - On reject:  (None, <spec.DROP_REASONS value>, {diagnostic fields})

    drop_reason is one of spec.DROP_REASONS; drop_detail carries
    whatever context is useful for the trace UI (phantom ground
    ids, invalid enum value, etc.).
    """
    try:
        for f in _REQUIRED:
            if f not in raw:
                return None, "missing_field", {"field": f}
        claim = str(raw["claim"]).strip()
        warrant = str(raw["warrant"]).strip()
        qualifier = str(raw["qualifier"]).strip()
        rebuttal = str(raw["rebuttal"]).strip()
        if not claim:
            return None, "missing_field", {"field": "claim", "value": "empty_after_strip"}
        if not warrant:
            return None, "missing_field", {"field": "warrant", "value": "empty_after_strip"}
        if not qualifier:
            return None, "missing_field", {"field": "qualifier", "value": "empty_after_strip"}
        if not rebuttal:
            return None, "missing_field", {"field": "rebuttal", "value": "empty_after_strip"}
        # Tautology guard — spec-defined, TAUTOLOGY_MIN_EXTENSION
        # chars of extension required. See spec.is_tautological_warrant.
        if spec.is_tautological_warrant(claim, warrant):
            return None, "tautology", {
                "claim": claim,
                "warrant": warrant,
                "delta_chars": len(warrant) - len(claim),
                "min_extension": spec.TAUTOLOGY_MIN_EXTENSION,
            }
        grounds_raw = raw.get("grounds") or []
        if not isinstance(grounds_raw, list) or not grounds_raw:
            return None, "grounds_empty", {"grounds_raw": grounds_raw}
        grounds = [str(g).strip() for g in grounds_raw if str(g).strip()]
        if not grounds:
            return None, "grounds_empty", {"grounds_raw": grounds_raw}
        # Every ground must be a real theme
        unknown = [g for g in grounds if g not in valid_theme_ids]
        if unknown:
            logger.info("calls: dropping candidate — unknown grounds %s", unknown)
            return None, "grounds_phantom", {
                "unknown": unknown,
                "valid_theme_ids": sorted(valid_theme_ids),
            }
        confidence = str(raw["confidence"]).strip().lower()
        if confidence not in _CONFIDENCE:
            return None, "invalid_confidence", {
                "got": confidence,
                "allowed": list(_CONFIDENCE),
            }
        horizon = str(raw["time_horizon"]).strip().lower()
        if horizon not in _HORIZON:
            return None, "invalid_horizon", {
                "got": horizon,
                "allowed": list(_HORIZON),
            }
        return {
            "claim": claim,
            "grounds": grounds,
            "warrant": warrant,
            "qualifier": qualifier,
            "rebuttal": rebuttal,
            "confidence": confidence,
            "time_horizon": horizon,
        }, None, None
    except Exception as exc:
        logger.warning("calls: candidate validation failed: %s", exc)
        return None, "missing_field", {"exception": str(exc)}


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
    return_trace: bool = False,
) -> List[Dict[str, Any]]:
    """MMR over the candidate pool. Similarity between two calls =
    Jaccard of their `grounds` sets; two calls that quote the same
    evidence are redundant.

    MMR(c) = λ·rel(c) − (1−λ)·max(sim(c, s) for s in selected)

    V6: when return_trace=True, returns (selected, trace) where
    trace is a list[dict] with per-candidate {status, mmr_score,
    relevance, max_sim, reason_if_dropped}. Default-off to keep
    the existing external call shape stable."""
    if not candidates:
        return ([], []) if return_trace else []
    theme_by_id = {t.id: t for t in themes}
    remaining = list(candidates)
    for i, c in enumerate(remaining):
        c.setdefault("_rel", _relevance_score(c, theme_by_id))

    selected: List[Dict[str, Any]] = []
    seen_ground_sets: set[frozenset[str]] = set()
    trace_per_candidate: Dict[int, Dict[str, Any]] = {
        id(c): {"candidate_idx": i, "relevance": c["_rel"],
                "status": "pending", "mmr_rounds": []}
        for i, c in enumerate(candidates)
    }

    while remaining and len(selected) < k:
        best = None
        best_score = -1e9
        best_max_sim = 0.0
        for c in remaining:
            if frozenset(c["grounds"]) in seen_ground_sets:
                trace_per_candidate[id(c)]["status"] = "dropped"
                trace_per_candidate[id(c)]["drop_reason"] = "mmr_hard_dedup"
                trace_per_candidate[id(c)]["drop_detail"] = {
                    "grounds_set": sorted(c["grounds"]),
                }
                continue
            rel = c["_rel"]
            max_sim = max(
                (_ground_similarity(c["grounds"], s["grounds"]) for s in selected),
                default=0.0,
            )
            mmr_score = spec.mmr(rel, max_sim, lambda_)
            trace_per_candidate[id(c)]["mmr_rounds"].append({
                "round": len(selected),
                "relevance": rel,
                "max_sim": max_sim,
                "mmr_score": mmr_score,
            })
            if mmr_score > best_score:
                best_score = mmr_score
                best_max_sim = max_sim
                best = c
        if best is None:
            break
        selected.append(best)
        seen_ground_sets.add(frozenset(best["grounds"]))
        remaining.remove(best)
        trace_per_candidate[id(best)]["status"] = "accepted"
        trace_per_candidate[id(best)]["selected_mmr_score"] = best_score
        trace_per_candidate[id(best)]["selected_max_sim"] = best_max_sim
        # Candidates not hard-deduped but NOT chosen stay "pending"
        # across more MMR rounds; after the loop, mark any still-
        # pending as "dropped mmr_low_score".

    for c in candidates:
        t = trace_per_candidate[id(c)]
        if t["status"] == "pending":
            if len(selected) >= k:
                t["status"] = "dropped"
                t["drop_reason"] = "candidate_pool_full"
                t["drop_detail"] = {"max_calls": k, "chosen": len(selected)}
            else:
                t["status"] = "dropped"
                t["drop_reason"] = "mmr_low_score"
                t["drop_detail"] = {"best_round_score": max(
                    (r["mmr_score"] for r in t["mmr_rounds"]), default=None)}

    for c in selected:
        c.pop("_rel", None)

    if return_trace:
        trace_list = [trace_per_candidate[id(c)] for c in candidates]
        return selected, trace_list
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

    V6: captures the FULL candidate pool including dropped reasons
    + MMR scores into _calls_trace[_POOL_TRACE_KEY] and per-call
    traces under _calls_trace[call_id]. The trace endpoint serves
    "how was this call derived?" + "why wasn't THAT candidate
    shipped?" queries directly from this store.
    """
    if not themes:
        return []

    cache_key = _cache_key(project_id, themes)
    if not fresh:
        cached = _cached(cache_key)
        if cached is not None:
            _put_call_trace(_POOL_TRACE_KEY, {
                "kind": "cache_hit",
                "note": "calls served from the 15-min cache; re-run "
                        "with fresh=1 to capture live candidate pool",
                "cache_key": cache_key,
            })
            return [Call(**c) for c in cached.get("calls", [])]

    valid_theme_ids = {t.id for t in themes}
    prompt = _generation_prompt(themes)
    system_prompt = _system_prompt()
    llm_trace: Dict[str, Any] = {
        "kind": "llm_call",
        "model": _CALLS_MODEL,
        "temperature": 0.4,
        "system_prompt": system_prompt,
        "user_prompt": prompt,
        "theme_ids_available": sorted(valid_theme_ids),
        "cache_key": cache_key,
    }
    t0 = time.monotonic()
    try:
        reply = _call_llm(prompt)
    except Exception as exc:
        duration_ms = int((time.monotonic() - t0) * 1000)
        logger.warning("calls: LLM generation failed: %s", exc)
        _put(cache_key, {"calls": []})
        llm_trace.update({
            "duration_ms": duration_ms,
            "error": str(exc),
            "raw_candidates": [],
            "validated": [],
            "selected_call_ids": [],
            "candidate_trace": [],
        })
        _put_call_trace(_POOL_TRACE_KEY, llm_trace)
        return []

    duration_ms = int((time.monotonic() - t0) * 1000)
    llm_trace["duration_ms"] = duration_ms
    llm_trace["raw_response"] = reply

    raw_candidates = reply.get("candidates") or []
    if not isinstance(raw_candidates, list):
        logger.warning("calls: malformed candidates: %r", type(raw_candidates))
        _put(cache_key, {"calls": []})
        llm_trace.update({
            "error": f"candidates field is {type(raw_candidates).__name__}, expected list",
            "validated": [],
            "selected_call_ids": [],
            "candidate_trace": [],
        })
        _put_call_trace(_POOL_TRACE_KEY, llm_trace)
        return []

    # Validate every candidate, recording drop reasons per failure
    candidate_trace: List[Dict[str, Any]] = []
    validated: List[Dict[str, Any]] = []
    validated_to_source_idx: Dict[int, int] = {}   # id(v) → position in raw
    for idx, raw in enumerate(raw_candidates[:_MAX_CANDIDATES]):
        v, drop_reason, drop_detail = _validate_candidate(raw, valid_theme_ids)
        entry = {
            "candidate_idx": idx,
            "raw": raw,
        }
        if v is None:
            entry["status"] = "dropped"
            entry["drop_reason"] = drop_reason
            entry["drop_detail"] = drop_detail or {}
        else:
            entry["status"] = "passed_validator"
            entry["sanitised"] = v
            validated_to_source_idx[id(v)] = idx
            validated.append(v)
        candidate_trace.append(entry)

    if not validated:
        logger.info("calls: no candidates passed validation — zero-call output")
        _put(cache_key, {"calls": []})
        llm_trace.update({
            "candidate_trace": candidate_trace,
            "validated_count": 0,
            "selected_call_ids": [],
        })
        _put_call_trace(_POOL_TRACE_KEY, llm_trace)
        return []

    picked, mmr_trace_list = select_calls_mmr(validated, themes, return_trace=True)
    # Merge MMR trace back into candidate_trace by original candidate_idx.
    for v_idx, m_entry in enumerate(mmr_trace_list):
        src_idx = validated_to_source_idx.get(id(validated[v_idx]))
        if src_idx is None:
            continue
        target = candidate_trace[src_idx]
        target["mmr"] = {
            "status": m_entry["status"],
            "relevance": m_entry["relevance"],
            "mmr_rounds": m_entry["mmr_rounds"],
        }
        if m_entry.get("status") == "accepted":
            target["mmr"]["selected_mmr_score"] = m_entry.get("selected_mmr_score")
            target["mmr"]["selected_max_sim"] = m_entry.get("selected_max_sim")
        elif m_entry.get("status") == "dropped":
            target["status"] = "dropped"
            target["drop_reason"] = m_entry["drop_reason"]
            target["drop_detail"] = m_entry.get("drop_detail") or {}

    calls: List[Call] = []
    selected_call_ids: List[str] = []
    for i, c in enumerate(picked):
        call_id = f"call_{i+1:03d}"
        selected_call_ids.append(call_id)
        calls.append(Call(
            id=call_id,
            claim=c["claim"],
            grounds=c["grounds"],
            warrant=c["warrant"],
            qualifier=c["qualifier"],
            rebuttal=c["rebuttal"],
            confidence=c["confidence"],
            time_horizon=c["time_horizon"],
        ))
        # Tag the picked candidate in the trace with its final id
        src_idx = validated_to_source_idx.get(id(c))
        if src_idx is not None:
            candidate_trace[src_idx]["final_call_id"] = call_id

    _put(cache_key, {"calls": [call.to_dict() for call in calls]})
    llm_trace.update({
        "candidate_trace": candidate_trace,
        "validated_count": len(validated),
        "selected_call_ids": selected_call_ids,
    })
    _put_call_trace(_POOL_TRACE_KEY, llm_trace)
    # Also index per-call for direct lookup by call_id
    for i, c in enumerate(picked):
        src_idx = validated_to_source_idx.get(id(c))
        if src_idx is None:
            continue
        call_id = selected_call_ids[i]
        _put_call_trace(call_id, {
            "kind": "call_origin",
            "call_id": call_id,
            "candidate_idx": src_idx,
            "candidate_trace": candidate_trace[src_idx],
            "pool_size": len(raw_candidates[:_MAX_CANDIDATES]),
            "validated_count": len(validated),
            "model": _CALLS_MODEL,
        })
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
