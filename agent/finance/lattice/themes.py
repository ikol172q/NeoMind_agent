"""L2 · theme clustering + narrative generation.

Two-step pipeline:

    1. Cluster (deterministic, pure compute).
       Each theme from the taxonomy YAML defines a tag signature.
       An observation's membership weight = |obs.tags ∩ theme.tags| /
       |theme.tags|. Same observation can belong to multiple themes
       — overlap is preserved by construction (this is the whole
       point of the lattice).

    2. Narrative (LLM, one short sentence per non-empty theme).
       Cheap. Cached by content-hash of member obs_ids so identical
       theme contents across refreshes don't re-hit the LLM.
       Post-validation: the LLM must cite at least one number that
       actually appears in a member observation's text or numbers.
       If it doesn't, we fall back to a deterministic templated
       sentence rather than ship a hallucinated narrative.

No LLM is in the clustering critical path — that's a deliberate
choice from the research (plans/2026-04-20_insight-lattice.md §A).
LLM-driven clustering was shown to drift between refreshes, which
would undermine the whole 'this structure is auditable' promise.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence

import httpx

from agent.constants.models import DEFAULT_MODEL
from agent.finance.lattice import spec
from agent.finance.lattice.observations import (
    Observation,
    build_observations,
    build_observations_run,
)
from agent.finance.lattice.taxonomy import ThemeSignature, load_taxonomy

logger = logging.getLogger(__name__)

_DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
_NARRATIVE_MODEL = DEFAULT_MODEL
# Inner per-narrative cache TTL.  This sub-cache is content-addressed
# by ``_content_hash(theme_id + members)``, so a TTL is unnecessary —
# but kept as a long ceiling so a runaway leaked-process doesn't
# accumulate stale entries forever.  The OUTER ``dep_hash`` cache
# (B5-L2) catches almost all repeat calls; this inner cache only fires
# on partial overlaps where some themes' members changed and others
# didn't.
_NARRATIVE_TTL_S = 86400.0   # 24h — effectively infinite for sessions
_NARRATIVE_TIMEOUT_S = 30.0

# Per-theme narrative cache: key is a content hash of (theme_id +
# sorted member obs texts). Cache is process-local; restart clears.
_narrative_cache: Dict[str, tuple[float, Dict[str, Any]]] = {}
_narrative_cache_lock = threading.Lock()

# V6 deep-trace store: keyed by theme_id (last-write-wins within
# TTL). Holds the exact prompt sent, the raw LLM response, and
# the validator outcome so /api/lattice/trace/theme_* can answer
# "how was this narrative computed?" with the actual bytes. TTL
# matches the narrative cache.
_narrative_trace: Dict[str, tuple[float, Dict[str, Any]]] = {}
_narrative_trace_lock = threading.Lock()


def _put_narrative_trace(theme_id: str, entry: Dict[str, Any]) -> None:
    with _narrative_trace_lock:
        _narrative_trace[theme_id] = (time.time(), entry)


def get_narrative_trace(theme_id: str) -> Optional[Dict[str, Any]]:
    """Return the most recent trace for a theme, or None if TTL has
    expired or no trace was captured (e.g., served from cache on
    the request that's asking). Exported for the trace endpoint."""
    with _narrative_trace_lock:
        entry = _narrative_trace.get(theme_id)
    if entry is None:
        return None
    if time.time() - entry[0] > _NARRATIVE_TTL_S:
        return None
    return entry[1]


# ── Data class ─────────────────────────────────────────

@dataclass
class ThemeMember:
    obs_id: str
    weight: float                         # 0-1 Jaccard-ish membership score


@dataclass
class Theme:
    id: str
    title: str
    narrative: str                        # 1-2 sentences, LLM-generated
    narrative_source: str                 # "llm" | "template_fallback"
    members: List[ThemeMember]
    tags: List[str]                       # union of distinctive tags on members
    severity: str                         # inherited from most severe member
    cited_numbers: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["members"] = [asdict(m) for m in self.members]
        return d


# ── Cluster step (pure compute) ────────────────────────

def _membership_weight(obs_tags: set[str], sig: ThemeSignature) -> float:
    """Thin adapter over spec.base_membership_weight so the
    function signature that production code expects (taking a
    ThemeSignature) stays intact while the math lives in one place.
    Any divergence between this wrapper and spec is caught by L1
    contract tests."""
    return spec.base_membership_weight(obs_tags, sig.any_of, sig.all_of)


# Identity imports from spec — NOT local re-declarations. Tests
# assert (is, not ==) so any future regression to a local copy
# breaks Layer 1 contract tests immediately.
_SEVERITY_BONUS = spec.CLUSTER_SEVERITY_BONUS
_severity_bonus = spec.cluster_severity_bonus


def cluster_observations(
    observations: Sequence[Observation],
    signatures: Optional[Sequence[ThemeSignature]] = None,
) -> List[Dict[str, Any]]:
    """Run every observation past every theme signature; collect
    non-empty themes that meet ``min_members``. Returns the raw
    per-theme grouping (no narrative yet — that's step 2).

    Final weight = tag_overlap_weight * severity_bonus. Tag overlap
    is the "does this obs belong to the theme?" signal; severity
    is the "how illustrative is this obs?" signal. Multiplying the
    two lets the highest-severity member rank first within a theme
    even when every member matches the tag signature fully.

    Returns: list of dicts with keys
      {sig, members: [(Observation, weight), ...]}
    """
    sigs = signatures if signatures is not None else load_taxonomy().themes
    out: List[Dict[str, Any]] = []
    for sig in sigs:
        members: List[tuple[Observation, float]] = []
        for obs in observations:
            # Go through spec.final_membership_weight directly so the
            # complete formula (base × severity_bonus, clipped) has
            # a single implementation. The L4 tests recompute every
            # emitted edge's weight from this same function, so any
            # local divergence here would fail loudly.
            final_w = spec.final_membership_weight(
                set(obs.tags), sig.any_of, sig.all_of, obs.severity,
            )
            if final_w > 0:
                members.append((obs, final_w))
        if len(members) < sig.min_members:
            continue
        # Sort members by weight desc so the narrative prompt sees
        # the most-definitive obs first (ordering can nudge LLMs).
        members.sort(key=lambda t: -t[1])
        out.append({"sig": sig, "members": members})
    return out


# ── LLM narrative step ─────────────────────────────────

_SYSTEM_PROMPT_BASE = (
    "You write one short sentence describing a cluster of financial "
    "observations. You NEVER invent data. You cite at least one specific "
    "number (a percentage, price, count, or time frame) that appears "
    "verbatim in the member observations you are given. Reply JSON only."
)


def _system_prompt() -> str:
    """Assemble the system prompt from the base + the effective
    language directive. V6: runtime.get_effective_language() lets
    the UI toggle override the YAML without a restart."""
    from agent.finance.lattice import runtime
    return _SYSTEM_PROMPT_BASE + spec.language_directive(runtime.get_effective_language())


def _narrative_prompt(theme_title: str, members: List[tuple[Observation, float]]) -> str:
    lines: List[str] = []
    for obs, w in members:
        lines.append(f'  - "{obs.text}"  (tags={obs.tags})')
    n = len(members)
    if n >= 3:
        coverage_clause = (
            f"There are {n} members — your sentence MUST reference at "
            f"least 2 of them (not just the most extreme) by naming "
            f"their distinguishing attribute (symbol, sector, or metric). "
            f"Cite AT LEAST 2 numbers, each appearing verbatim in a "
            f"different member's text."
        )
    elif n == 2:
        coverage_clause = (
            "There are 2 members — your sentence must reference both. "
            "Cite at least one number that appears verbatim in member text."
        )
    else:
        coverage_clause = (
            "Cite at least one number that appears verbatim in the "
            "single member's text."
        )
    return (
        f"THEME TITLE: {theme_title}\n\n"
        f"MEMBER OBSERVATIONS:\n"
        f"{chr(10).join(lines)}\n\n"
        f"Task: Write ONE sentence (<=40 words) that captures what "
        f"ties these observations together. Start with a symbol, a "
        f"sector, or a verb; no preambles like 'This cluster...' or "
        f"'The observations...'. {coverage_clause} "
        f"Do not say the theme title verbatim.\n\n"
        'Reply with JSON: {"narrative": "...", '
        '"cited_numbers": ["...", "..."]}'
    )


_NUMBER_RE = re.compile(r"[+-]?\d+(?:\.\d+)?%?")


def _extract_numbers_from_obs(members: List[tuple[Observation, float]]) -> set[str]:
    """Return every numeric-looking token present in any member's text
    or numbers dict. Used to post-validate LLM citation claims."""
    toks: set[str] = set()
    for obs, _ in members:
        for m in _NUMBER_RE.findall(obs.text):
            toks.add(m)
        for v in obs.numbers.values():
            try:
                toks.add(str(int(v)) if float(v).is_integer() else f"{v:.1f}")
                toks.add(f"{v:.2f}")
            except Exception:
                pass
    return toks


def _content_hash(theme_id: str, members: List[tuple[Observation, float]]) -> str:
    payload = theme_id + "|" + "|".join(
        f"{o.id}:{o.text}" for o, _ in sorted(members, key=lambda t: t[0].id)
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


def _cached_narrative(key: str) -> Optional[Dict[str, Any]]:
    with _narrative_cache_lock:
        entry = _narrative_cache.get(key)
    if entry is None:
        return None
    if time.time() - entry[0] > _NARRATIVE_TTL_S:
        return None
    return entry[1]


def _put_narrative(key: str, value: Dict[str, Any]) -> None:
    with _narrative_cache_lock:
        _narrative_cache[key] = (time.time(), value)


def _template_narrative(theme_title: str, members: List[tuple[Observation, float]]) -> Dict[str, Any]:
    """Deterministic fallback when the LLM fails or hallucinates
    numbers. Quality is worse than LLM but auditable — every word
    comes from either the theme title or a member obs."""
    if not members:
        return {"narrative": theme_title + " (no members).", "cited_numbers": []}
    top = members[0][0]
    extras = len(members) - 1
    base = top.text.rstrip(".")
    if extras > 0:
        return {
            "narrative": f"{base}; {extras} related fact{'s' if extras > 1 else ''} in this cluster.",
            "cited_numbers": list(_extract_numbers_from_obs(members)),
        }
    return {"narrative": f"{base}.", "cited_numbers": list(_extract_numbers_from_obs(members))}


def _call_llm(prompt: str) -> Dict[str, Any]:
    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY missing")
    with httpx.Client(timeout=httpx.Timeout(_NARRATIVE_TIMEOUT_S)) as client:
        resp = client.post(
            _DEEPSEEK_URL,
            json={
                "model": _NARRATIVE_MODEL,
                "messages": [
                    {"role": "system", "content": _system_prompt()},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.3,
                "max_tokens": 200,
                "response_format": {"type": "json_object"},
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
    if resp.status_code != 200:
        raise RuntimeError(f"DeepSeek {resp.status_code}: {resp.text[:200]}")
    content = resp.json()["choices"][0]["message"]["content"]
    return json.loads(content)


def _validate_llm_narrative(
    reply: Dict[str, Any],
    members: List[tuple[Observation, float]],
) -> bool:
    """Ensure the LLM's claimed citations actually appear in member
    text. Drops hallucinated numbers silently — fallback handles the
    rejection path.

    Rule: at least ONE number in the narrative text must be a literal
    substring of some member obs's text or a stringified member number.
    """
    narrative = str(reply.get("narrative", ""))
    if not narrative:
        return False
    obs_tokens = _extract_numbers_from_obs(members)
    narrative_tokens = set(_NUMBER_RE.findall(narrative))
    if not narrative_tokens:
        return False
    # At least one token overlap
    return bool(narrative_tokens & obs_tokens) or any(
        tok in " ".join(o.text for o, _ in members) for tok in narrative_tokens
    )


def generate_narrative(
    theme_id: str,
    theme_title: str,
    members: List[tuple[Observation, float]],
    *,
    fresh: bool = False,
) -> Dict[str, Any]:
    """Return {narrative, source, cited_numbers}. ``source`` is
    'llm' if the LLM call succeeded + validated, 'template_fallback'
    otherwise.

    V6: captures full trace (prompt, raw response, validation result,
    model, duration) into _narrative_trace keyed by theme_id so the
    /api/lattice/trace endpoint can answer 'how was this narrative
    computed?' with the exact bytes sent and received.

    V8: cache key prefixed by the effective output language so both
    language variants coexist in cache. Toggling the UI language no
    longer needs to clear the cache — the first toggle misses (LLM
    called), subsequent toggles between the same pair hit (instant).
    """
    from agent.finance.lattice import runtime
    lang = runtime.get_effective_language()
    cache_key = f"{lang}::{_content_hash(theme_id, members)}"
    if not fresh:
        cached = _cached_narrative(cache_key)
        if cached is not None:
            # Record a minimal trace note so the endpoint can at least
            # say "this refresh served from cache; re-run with fresh=1
            # to see the live LLM conversation"
            _put_narrative_trace(theme_id, {
                "kind": "cache_hit",
                "note": "narrative served from the 5-min content-hash cache; "
                        "no LLM call was made on this request",
                "cache_key": cache_key,
            })
            return cached

    prompt = _narrative_prompt(theme_title, members)
    system_prompt = _system_prompt()
    trace: Dict[str, Any] = {
        "kind": "llm_call",
        "model": _NARRATIVE_MODEL,
        "temperature": 0.3,
        "system_prompt": system_prompt,
        "user_prompt": prompt,
        "member_obs_ids": [o.id for o, _ in members],
        "cache_key": cache_key,
    }
    t0 = time.monotonic()
    try:
        reply = _call_llm(prompt)
    except Exception as exc:
        duration_ms = int((time.monotonic() - t0) * 1000)
        logger.warning("themes: LLM failed for %s: %s — using template fallback", theme_id, exc)
        tmpl = _template_narrative(theme_title, members)
        result = {"narrative": tmpl["narrative"], "source": "template_fallback",
                  "cited_numbers": tmpl["cited_numbers"]}
        _put_narrative(cache_key, result)
        trace.update({
            "duration_ms": duration_ms,
            "raw_response": None,
            "error": str(exc),
            "fallback_reason": "llm_exception",
            "final_source": "template_fallback",
        })
        _put_narrative_trace(theme_id, trace)
        return result

    duration_ms = int((time.monotonic() - t0) * 1000)
    trace["duration_ms"] = duration_ms
    trace["raw_response"] = reply

    if not _validate_llm_narrative(reply, members):
        logger.info("themes: LLM narrative failed citation check for %s — using template", theme_id)
        tmpl = _template_narrative(theme_title, members)
        result = {"narrative": tmpl["narrative"], "source": "template_fallback",
                  "cited_numbers": tmpl["cited_numbers"]}
        _put_narrative(cache_key, result)
        trace.update({
            "validator": {
                "passed": False,
                "reason": "narrative cites no number present verbatim in member text",
            },
            "fallback_reason": "validation_failed",
            "final_source": "template_fallback",
        })
        _put_narrative_trace(theme_id, trace)
        return result

    result = {
        "narrative": str(reply.get("narrative", "")).strip(),
        "source": "llm",
        "cited_numbers": [str(x) for x in (reply.get("cited_numbers") or [])],
    }
    _put_narrative(cache_key, result)
    trace.update({
        "validator": {"passed": True, "reason": "numbers cited appear in member text"},
        "final_source": "llm",
    })
    _put_narrative_trace(theme_id, trace)
    return result


# ── Full pipeline entry point ──────────────────────────

_severity_rank = spec.severity_rank


def _theme_severity(members: List[tuple[Observation, float]]) -> str:
    """Theme inherits the most severe member's severity."""
    if not members:
        return "info"
    return min(members, key=lambda t: _severity_rank(t[0].severity))[0].severity


def _theme_tags(members: List[tuple[Observation, float]], sig: ThemeSignature, max_tags: int = 8) -> List[str]:
    """Tags that distinguish this theme from others. Start with the
    signature's own defining tags, then add the most common member
    tags not already in the signature."""
    distinctive = list(sig.any_of) + list(sig.all_of)
    freq: Dict[str, int] = {}
    for obs, _ in members:
        for t in obs.tags:
            if t in distinctive:
                continue
            freq[t] = freq.get(t, 0) + 1
    ranked = sorted(freq.items(), key=lambda kv: -kv[1])
    extra = [t for t, _ in ranked[: max_tags - len(distinctive)]]
    return distinctive + extra


def _cluster_to_layer(
    observations: Sequence[Observation],
    signatures: Sequence[ThemeSignature],
    *,
    fresh: bool,
    generate_narratives: bool,
    budget: Optional[spec.LayerBudget] = None,
) -> List[Theme]:
    """Shared builder for any middle layer (sub_themes, themes, ...).
    Runs the deterministic tag clusterer; optionally asks the LLM to
    write a narrative per non-empty cluster.

    sub_themes skip the narrative call — the UX presents them as
    compact groupings, not standalone prose. Saves ~5 LLM calls
    per refresh when n=4 is engaged.

    V7: when `budget.min_members` is set, it OVERRIDES each
    signature's own min_members (layer-wide floor). When
    `budget.max_items` is set, the output is sorted by
    (severity_rank, -member_count) and trimmed to that cap.
    """
    if not signatures:
        return []
    # V7: apply layer-wide min_members floor (if set) on top of the
    # per-signature min_members. Takes the MAX (tighter wins).
    effective_sigs = signatures
    if budget is not None and budget.min_members is not None:
        floor = budget.min_members
        effective_sigs = [
            ThemeSignature(
                id=s.id, title=s.title, any_of=s.any_of, all_of=s.all_of,
                min_members=max(s.min_members, floor),
            )
            for s in signatures
        ]
    clusters = cluster_observations(observations, effective_sigs)
    out: List[Theme] = []
    for c in clusters:
        sig: ThemeSignature = c["sig"]
        members: List[tuple[Observation, float]] = c["members"]
        if generate_narratives:
            narrative = generate_narrative(sig.id, sig.title, members, fresh=fresh)
            narrative_text = narrative["narrative"]
            narrative_source = narrative["source"]
            cited_numbers = narrative["cited_numbers"]
        else:
            # Template-only for intermediate layers — short join of
            # member kinds, no LLM needed.
            narrative_text = f"{sig.title} ({len(members)} obs)"
            narrative_source = "template_fallback"
            cited_numbers = []
        out.append(Theme(
            id=sig.id,
            title=sig.title,
            narrative=narrative_text,
            narrative_source=narrative_source,
            members=[ThemeMember(obs_id=o.id, weight=round(w, 3)) for o, w in members],
            tags=_theme_tags(members, sig),
            severity=_theme_severity(members),
            cited_numbers=cited_numbers,
        ))
    out.sort(key=lambda t: (_severity_rank(t.severity), -len(t.members)))
    # V7: apply max_items cap after severity/count sort
    if budget is not None and budget.max_items is not None:
        out = out[:budget.max_items]
    return out


# Bumped whenever the L2 prompt template (system / user) changes.
# Embedded in DepHashInputs.prompt_template_version so cached themes
# never get reused across a prompt edit.
THEMES_PROMPT_TEMPLATE_VERSION = "v1"

# Bumped whenever the L2 pipeline shape (cluster → narrate → validate)
# changes how it serialises. Stored in DepHashInputs.extra to
# invalidate snapshot reads on shape change.
THEMES_PIPELINE_VERSION = "v1"


def build_themes(project_id: str, *, fresh: bool = False) -> Dict[str, Any]:
    """Full L1 (+ optional L1.5) + L2 pipeline: observations → clusters
    → narratives.

    Thin wrapper that drops the run metadata.  Use
    :func:`build_themes_run` if you want the (result, meta) tuple —
    the router does, so it can surface the dep_hash and cache-hit
    status in the response payload.
    """
    result, _meta = build_themes_run(project_id, fresh=fresh)
    return result


def build_themes_run(
    project_id: str, *, fresh: bool = False,
) -> "tuple[Dict[str, Any], Dict[str, Any]]":
    """Outer ``dep_hash`` cache around the L2 pipeline.

    Inputs to the dep_hash:
      * the L1 observations dep_hash (already content-addressed via
        B5-L1) — captures every byte of input that drove the L1
        layer
      * effective budget hash (max_items caps for obs / sub_themes /
        themes)
      * effective language directive (zh / en / bilingual switch)
      * taxonomy version
      * prompt_template_version (bumps invalidate cached LLM
        narratives)
      * llm_model_id + llm_temperature
      * code_git_sha
      * pipeline_version

    Strict cache by user approval — at temperature > 0 the FIRST
    call writes the LLM response, subsequent identical-input calls
    return the cached response (cache the first roll).  Edit the
    prompt template → bump THEMES_PROMPT_TEMPLATE_VERSION → all
    cached themes invalidate.
    """
    from agent.finance.compute import (
        DepHashInputs,
        compute_dep_hash,
        get_code_git_sha,
        open_dep_cache,
    )
    from agent.finance.compute.cache import _utcnow_iso
    from agent.finance.lattice import runtime

    # ── L1 observations (already cached via B5-L1) ──
    observations, obs_meta = build_observations_run(project_id, fresh=fresh)

    tax = load_taxonomy()
    budgets = runtime.get_effective_budgets()
    bh = runtime.budget_hash(budgets)
    lang = runtime.get_effective_language()

    # ── Compose dep_hash inputs ──
    inputs = DepHashInputs(
        blob_hashes=tuple([
            f"obs:{obs_meta.get('dep_hash') or ''}",
            f"budget:{bh}",
            f"lang:{lang}",
        ]),
        prompt_template_version= THEMES_PROMPT_TEMPLATE_VERSION,
        llm_model_id=            _NARRATIVE_MODEL,
        llm_temperature=         0.3,
        sample_strategy=         "",
        taxonomy_version=        str(tax.version or ""),
        code_git_sha=            get_code_git_sha(),
        extra=(
            ("pipeline_version", THEMES_PIPELINE_VERSION),
        ),
    )
    dep_hash = compute_dep_hash(inputs)

    cache = open_dep_cache(project_id)

    def _build_meta(*, hit: bool, compute_run_id: Optional[str], started_at: str, completed_at: Optional[str]) -> Dict[str, Any]:
        return {
            "dep_hash":                dep_hash,
            "compute_run_id":          compute_run_id,
            "cache_hit":               hit,
            "started_at":              started_at,
            "completed_at":            completed_at,
            "taxonomy_version":        inputs.taxonomy_version,
            "code_git_sha":            inputs.code_git_sha,
            "pipeline_version":        THEMES_PIPELINE_VERSION,
            "prompt_template_version": THEMES_PROMPT_TEMPLATE_VERSION,
            "llm_model_id":            _NARRATIVE_MODEL,
            "llm_temperature":         0.3,
            "language":                lang,
            "budget_hash":             bh,
            "step":                    "themes",
            # Cross-link to the L1 run that fed us — UI breadcrumb
            # uses these to render "L2 from L1 run X" lineage.
            "obs_dep_hash":            obs_meta.get("dep_hash"),
            "obs_compute_run_id":      obs_meta.get("compute_run_id"),
            "obs_cache_hit":           obs_meta.get("cache_hit"),
        }

    # ── CACHE HIT path ──
    if not fresh:
        hit = cache.get(dep_hash, "themes")
        if hit:
            try:
                cached_blob = hit.read_payload()
                cached = json.loads(cached_blob.decode("utf-8")) if cached_blob else None
            except Exception as exc:
                logger.warning("themes cache read failed (%s) — falling through", exc)
                cached = None
            if cached is not None:
                meta = _build_meta(
                    hit=True,
                    compute_run_id=hit.compute_run_id,
                    started_at=hit.started_at,
                    completed_at=hit.completed_at,
                )
                return cached, meta

    # ── CACHE MISS path — run the full L2 pipeline ──
    started_at_iso = _utcnow_iso()

    # Apply L1 budget cap before clustering.  Sort by severity then
    # confidence so the least-important obs drop first.
    if budgets.observations.max_items is not None:
        observations = sorted(
            observations,
            key=lambda o: (_severity_rank(o.severity), -(o.confidence or 0.0)),
        )[:budgets.observations.max_items]

    sub_themes = _cluster_to_layer(
        observations, tax.sub_themes, fresh=fresh, generate_narratives=False,
        budget=budgets.sub_themes,
    )
    themes = _cluster_to_layer(
        observations, tax.themes, fresh=fresh, generate_narratives=True,
        budget=budgets.themes,
    )

    result = {
        "project_id":   project_id,
        "observations": [o.to_dict() for o in observations],
        "sub_themes":   [t.to_dict() for t in sub_themes],
        "themes":       [t.to_dict() for t in themes],
    }

    # Persist
    snapshot_payload = json.dumps(
        result, sort_keys=True, ensure_ascii=False, default=str,
    ).encode("utf-8")
    try:
        written = cache.put(
            inputs=     inputs,
            step=       "themes",
            payload=    snapshot_payload,
            crawl_run_id=None,
            started_at= started_at_iso,
        )
        compute_run_id = written.compute_run_id
        completed_at   = written.completed_at
    except Exception as exc:
        logger.warning("themes cache.put failed (%s) — returning uncached result", exc)
        compute_run_id = None
        completed_at   = _utcnow_iso()

    meta = _build_meta(
        hit=False,
        compute_run_id=compute_run_id,
        started_at=started_at_iso,
        completed_at=completed_at,
    )
    return result, meta
