"""Insight Lattice — executable specification.

SINGLE SOURCE OF TRUTH for every algorithmic constant, enum, and
formula. Implementation (themes.py, calls.py, graph.py, viz) MUST
import from here. Anything that cannot import from here is either
a bug or evidence that the spec is incomplete.

Invariant (enforced by tests/test_lattice_spec_contract.py):
  production code uses the same objects exported here — not a copy,
  not a separately-declared dict with equivalent values. Identity,
  not just equality.

Rules for editing this file:
  1. Any change to a numeric value must be accompanied by a
     fixture update under tests/lattice_fixtures/ (V4 on).
  2. Any new enum value must be added here first; tests for that
     value's acceptance/rejection come next; implementation last.
  3. Formulas in this file are the reference. Production functions
     must produce bit-identical outputs for the same inputs — this
     is verified by parametrised + property-based tests in
     tests/test_lattice_formulas.py.
"""
from __future__ import annotations

from typing import AbstractSet


# ── Severity axes ───────────────────────────────────────

# Applied in cluster_observations: final_weight = clip(base * bonus, 0, 1)
CLUSTER_SEVERITY_BONUS: dict[str, float] = {
    "alert": 1.0,
    "warn":  0.85,
    "info":  0.7,
}
CLUSTER_SEVERITY_BONUS_DEFAULT: float = 0.7

# Applied in _relevance_score for L3 MMR. Different table, different
# purpose: here the score is a ground's "weight" contribution to the
# call's relevance, not a multiplier on membership.
GROUND_SEVERITY_SCORE: dict[str, float] = {
    "alert": 1.0,
    "warn":  0.7,
    "info":  0.5,
}
GROUND_SEVERITY_SCORE_DEFAULT: float = 0.5

# Severity ordering for rollups (alert > warn > info).
SEVERITY_RANK: dict[str, int] = {"alert": 0, "warn": 1, "info": 2}
SEVERITY_RANK_DEFAULT: int = 3


# ── L3 call selection ──────────────────────────────────

MMR_LAMBDA: float = 0.7
MAX_CALLS: int = 3
MAX_CANDIDATES: int = 5

# Confidence weights used inside _relevance_score.
CONFIDENCE_SCORE: dict[str, float] = {"high": 1.0, "medium": 0.7, "low": 0.4}
CONFIDENCE_SCORE_DEFAULT: float = 0.5


# ── L3 validation enums ────────────────────────────────

CONFIDENCE_VALUES: tuple[str, ...] = ("high", "medium", "low")
TIME_HORIZON_VALUES: tuple[str, ...] = ("intraday", "days", "weeks", "quarter")

# Required Toulmin fields on a raw LLM candidate.
CALL_REQUIRED_FIELDS: tuple[str, ...] = (
    "claim", "grounds", "warrant", "qualifier", "rebuttal",
    "confidence", "time_horizon",
)

# Tautology guard: a warrant that is a substring of the claim and
# extends it by fewer than this many characters is rejected as
# adding no reasoning.
TAUTOLOGY_MIN_EXTENSION: int = 10


# ── V6 · Deep trace (candidate drop reasons) ───────────

# Why a single L3 candidate was dropped before reaching the final
# calls list. Every drop in production must use one of these.
# Matches the rejection paths in _validate_candidate +
# select_calls_mmr. If a new drop reason is introduced, add it
# here first (L1 contract test will fail otherwise).
DROP_REASONS: tuple[str, ...] = (
    "missing_field",        # required Toulmin field absent / empty
    "invalid_confidence",   # confidence ∉ CONFIDENCE_VALUES
    "invalid_horizon",      # time_horizon ∉ TIME_HORIZON_VALUES
    "tautology",            # warrant fails is_tautological_warrant
    "grounds_empty",        # grounds list empty after strip
    "grounds_phantom",      # a ground references a theme_id not in the payload
    "mmr_hard_dedup",       # identical grounds set already selected
    "mmr_low_score",        # MMR score too low vs the k selected
    "candidate_pool_full",  # pool already at MAX_CALLS
)


# ── Graph provenance enumeration (V2 uses this) ────────

# Exact set of `computed_by` values the /api/lattice/graph endpoint
# may emit. Adding a new kind requires a spec edit FIRST.
PROVENANCE_KINDS: tuple[str, ...] = (
    "source",           # L0 external widget
    "deterministic",    # Python algorithm; no LLM involved
    "llm",              # LLM output, no post-validation
    "llm+validator",    # LLM output + deterministic validator pass
    "llm+mmr",          # LLM candidate pool + MMR selection
)

LAYERS: tuple[str, ...] = ("L0", "L1", "L1.5", "L2", "L3")

EDGE_KINDS: tuple[str, ...] = (
    "source_emission",   # L0 widget → L1 observation
    "membership",        # L1 obs → L1.5 sub-theme or L2 theme (Jaccard)
    "grounds",           # L2 theme → L3 call (LLM-selected, MMR-survived)
)


# ── Output language (V5) ───────────────────────────────

# Valid values for Taxonomy.output_language, which drives how L2
# narratives and L3 Toulmin fields get written. Default stays "en"
# for backward compatibility; "zh-CN-mixed" writes prose in Chinese
# while preserving tickers / sectors / financial terms in English
# (the judge rubric extracts numbers via regex, which is unicode-
# safe, so scoring keeps working).
OUTPUT_LANGUAGES: tuple[str, ...] = ("en", "zh-CN-mixed")
OUTPUT_LANGUAGE_DEFAULT: str = "en"

_LANGUAGE_DIRECTIVES: dict[str, str] = {
    "en": "",                                     # no extra directive — prompts are English natively
    "zh-CN-mixed": (
        " Write the narrative (or claim / warrant / qualifier / rebuttal) "
        "in Simplified Chinese. KEEP in English, verbatim: ticker symbols "
        "(e.g. AAPL, NVDA, TSLA), sector names (e.g. Energy, Technology, "
        "Consumer Discretionary), and standard financial/derivatives "
        "terms (IV, DTE, MMR, VIX, earnings, Fed, ATM, OTM). Numbers, "
        "percentages, and units stay as-is. Example good: "
        "'AAPL 即将在 7 天后发布 earnings，考虑买入 protective puts 对冲 "
        "IV 扩张。'"
    ),
}


def language_directive(language: str) -> str:
    """Return the system-prompt snippet that tells the LLM what
    language to produce. The caller appends this to the base system
    prompt at call time.

    Unknown languages fall back to OUTPUT_LANGUAGE_DEFAULT (i.e., no
    additional directive) rather than raising, so a bad config in
    the YAML doesn't break the live endpoint.
    """
    return _LANGUAGE_DIRECTIVES.get(language, _LANGUAGE_DIRECTIVES[OUTPUT_LANGUAGE_DEFAULT])


# ── Reference formulas ─────────────────────────────────

def cluster_severity_bonus(severity: str) -> float:
    """Multiplier applied to the base Jaccard membership weight.
    Isolates the severity→weight mapping so every caller goes
    through one function."""
    return CLUSTER_SEVERITY_BONUS.get(severity, CLUSTER_SEVERITY_BONUS_DEFAULT)


def severity_rank(severity: str) -> int:
    """Smaller = more severe. Used to order themes and pick the
    worst member for theme.severity rollup."""
    return SEVERITY_RANK.get(severity, SEVERITY_RANK_DEFAULT)


def confidence_score(conf: str) -> float:
    """Maps a call's self-reported confidence to a relevance
    multiplier."""
    return CONFIDENCE_SCORE.get(conf, CONFIDENCE_SCORE_DEFAULT)


def ground_severity_score(severity: str) -> float:
    """The per-ground severity contribution to a call's MMR
    relevance."""
    return GROUND_SEVERITY_SCORE.get(severity, GROUND_SEVERITY_SCORE_DEFAULT)


def base_membership_weight(
    obs_tags: AbstractSet[str],
    sig_any_of: AbstractSet[str],
    sig_all_of: AbstractSet[str],
) -> float:
    """Pure tag-intersection weight — no severity bonus.

    Mirrors production `_membership_weight` in themes.py. Used both
    for L1→L1.5 and L1→L2 clustering (same math, different signatures).

    Rules:
      - If all_of is non-empty and not fully covered: 0.0 (hard gate).
      - If any_of is non-empty and has zero intersection: 0.0.
      - any_weight = |obs ∩ any_of| / |any_of|.
      - If both any_of and all_of are set and the hard gate passes,
        the two "halves" average: (any_weight + 1.0) / 2.
      - If only all_of and it passes: 1.0.
      - If only any_of: any_weight.
    """
    if sig_all_of and not sig_all_of.issubset(obs_tags):
        return 0.0
    any_weight = 0.0
    if sig_any_of:
        hits = len(obs_tags & sig_any_of)
        if hits == 0:
            return 0.0
        any_weight = hits / len(sig_any_of)
    if sig_all_of:
        return (any_weight + 1.0) / 2 if sig_any_of else 1.0
    return any_weight


def final_membership_weight(
    obs_tags: AbstractSet[str],
    sig_any_of: AbstractSet[str],
    sig_all_of: AbstractSet[str],
    obs_severity: str,
) -> float:
    """The weight actually stored on a cluster edge.

        w_final = clip(base_membership_weight × cluster_severity_bonus,
                       0, 1)

    Returns 0.0 verbatim when base is 0 (no artificial spread) so
    downstream `w > 0` gating behaves correctly.
    """
    base = base_membership_weight(obs_tags, sig_any_of, sig_all_of)
    if base == 0.0:
        return 0.0
    return min(1.0, base * cluster_severity_bonus(obs_severity))


def ground_similarity(a: AbstractSet[str], b: AbstractSet[str]) -> float:
    """Jaccard over two calls' ground sets; used for MMR diversity.

        sim = |a ∩ b| / |a ∪ b|   (0 when either is empty)
    """
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def relevance_score(
    grounds_sevs_and_sizes: list[tuple[str, int]],
    confidence: str,
) -> float:
    """L3 MMR relevance, matching `_relevance_score` in calls.py.

        rel = confidence_score × Σ_{g ∈ grounds}
                 ground_severity_score(g.severity) × (1 + min(g.n_members, 5) / 5)

    A ground theme contributes more when it's more severe AND has
    more members (capped at 5-member saturation).
    """
    s = 0.0
    for sev, n_members in grounds_sevs_and_sizes:
        s += ground_severity_score(sev) * (1 + min(n_members, 5) / 5)
    return s * confidence_score(confidence)


def mmr(
    relevance_c: float,
    max_similarity: float,
    lambda_: float = MMR_LAMBDA,
) -> float:
    """MMR combined score for a candidate given its relevance and
    the max similarity to any already-selected candidate.

        mmr = λ · rel(c) − (1−λ) · max_sim(c, selected)
    """
    return lambda_ * relevance_c - (1.0 - lambda_) * max_similarity


def is_tautological_warrant(claim: str, warrant: str) -> bool:
    """Mirrors the tautology guard in `_validate_candidate`. True =
    reject the candidate.

    A warrant is tautological if:
      (a) it equals the claim (case-insensitive), OR
      (b) the claim is a substring of the warrant AND the warrant
          extends the claim by fewer than TAUTOLOGY_MIN_EXTENSION
          characters (i.e., adds no real reasoning).
    """
    c_lower = claim.lower()
    w_lower = warrant.lower()
    if c_lower == w_lower:
        return True
    if c_lower in w_lower and (len(w_lower) - len(c_lower)) < TAUTOLOGY_MIN_EXTENSION:
        return True
    return False
