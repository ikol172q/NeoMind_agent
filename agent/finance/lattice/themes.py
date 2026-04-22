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

from agent.finance.lattice.observations import Observation, build_observations
from agent.finance.lattice.taxonomy import ThemeSignature, load_taxonomy

logger = logging.getLogger(__name__)

_DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
_NARRATIVE_MODEL = "deepseek-chat"
_NARRATIVE_TTL_S = 300.0
_NARRATIVE_TIMEOUT_S = 30.0

# Per-theme narrative cache: key is a content hash of (theme_id +
# sorted member obs texts). Cache is process-local; restart clears.
_narrative_cache: Dict[str, tuple[float, Dict[str, Any]]] = {}
_narrative_cache_lock = threading.Lock()


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
    """Weight = fraction of the theme's defining tags present in obs.

    For a signature with any_of=[A, B] and all_of=[C]:
      - all_of must fully match (otherwise weight 0)
      - any_of weight is |obs ∩ any_of| / |any_of|
      - if both present, avg the two components
    """
    if sig.all_of and not sig.all_of.issubset(obs_tags):
        return 0.0
    any_weight = 0.0
    if sig.any_of:
        hits = len(obs_tags & sig.any_of)
        if hits == 0:
            return 0.0
        any_weight = hits / len(sig.any_of)
    if sig.all_of:
        all_weight = 1.0  # fully matched by construction above
        return (any_weight + all_weight) / 2 if sig.any_of else all_weight
    return any_weight


_SEVERITY_BONUS = {"alert": 1.0, "warn": 0.85, "info": 0.7}


def _severity_bonus(severity: str) -> float:
    return _SEVERITY_BONUS.get(severity, 0.7)


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
            w = _membership_weight(set(obs.tags), sig)
            if w > 0:
                final_w = min(1.0, w * _severity_bonus(obs.severity))
                members.append((obs, final_w))
        if len(members) < sig.min_members:
            continue
        # Sort members by weight desc so the narrative prompt sees
        # the most-definitive obs first (ordering can nudge LLMs).
        members.sort(key=lambda t: -t[1])
        out.append({"sig": sig, "members": members})
    return out


# ── LLM narrative step ─────────────────────────────────

_SYSTEM_PROMPT = (
    "You write one short sentence describing a cluster of financial "
    "observations. You NEVER invent data. You cite at least one specific "
    "number (a percentage, price, count, or time frame) that appears "
    "verbatim in the member observations you are given. Reply JSON only."
)


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
                    {"role": "system", "content": _SYSTEM_PROMPT},
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
    otherwise."""
    cache_key = _content_hash(theme_id, members)
    if not fresh:
        cached = _cached_narrative(cache_key)
        if cached is not None:
            return cached

    prompt = _narrative_prompt(theme_title, members)
    try:
        reply = _call_llm(prompt)
    except Exception as exc:
        logger.warning("themes: LLM failed for %s: %s — using template fallback", theme_id, exc)
        tmpl = _template_narrative(theme_title, members)
        result = {"narrative": tmpl["narrative"], "source": "template_fallback",
                  "cited_numbers": tmpl["cited_numbers"]}
        _put_narrative(cache_key, result)
        return result

    if not _validate_llm_narrative(reply, members):
        logger.info("themes: LLM narrative failed citation check for %s — using template", theme_id)
        tmpl = _template_narrative(theme_title, members)
        result = {"narrative": tmpl["narrative"], "source": "template_fallback",
                  "cited_numbers": tmpl["cited_numbers"]}
        _put_narrative(cache_key, result)
        return result

    result = {
        "narrative": str(reply.get("narrative", "")).strip(),
        "source": "llm",
        "cited_numbers": [str(x) for x in (reply.get("cited_numbers") or [])],
    }
    _put_narrative(cache_key, result)
    return result


# ── Full pipeline entry point ──────────────────────────

def _severity_rank(severity: str) -> int:
    return {"alert": 0, "warn": 1, "info": 2}.get(severity, 3)


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
) -> List[Theme]:
    """Shared builder for any middle layer (sub_themes, themes, ...).
    Runs the deterministic tag clusterer; optionally asks the LLM to
    write a narrative per non-empty cluster.

    sub_themes skip the narrative call — the UX presents them as
    compact groupings, not standalone prose. Saves ~5 LLM calls
    per refresh when n=4 is engaged.
    """
    if not signatures:
        return []
    clusters = cluster_observations(observations, signatures)
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
    return out


def build_themes(project_id: str, *, fresh: bool = False) -> Dict[str, Any]:
    """Full L1 (+ optional L1.5) + L2 pipeline: observations → clusters
    → narratives.

    Returns a dict with:
      observations  — L1 rows
      sub_themes    — L1.5 rows (empty list when YAML has no sub_themes)
      themes        — L2 rows with LLM narrative + members

    `sub_themes` is the D6 hook: adding a `sub_themes:` block to
    lattice_taxonomy.yaml engages n=4. No code change required.
    """
    observations = build_observations(project_id, fresh=fresh)
    tax = load_taxonomy()

    sub_themes = _cluster_to_layer(
        observations, tax.sub_themes, fresh=fresh, generate_narratives=False,
    )
    themes = _cluster_to_layer(
        observations, tax.themes, fresh=fresh, generate_narratives=True,
    )

    return {
        "project_id": project_id,
        "observations": [o.to_dict() for o in observations],
        "sub_themes": [t.to_dict() for t in sub_themes],
        "themes": [t.to_dict() for t in themes],
    }
