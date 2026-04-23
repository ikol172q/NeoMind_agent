"""L2 · formula-level unit tests.

For every formula in spec.py:
  - parametrised exact-numeric tests cover hand-picked edge cases
  - hypothesis property tests cover 500+ random inputs, checking
    invariants (range, determinism, overlap preservation).

If anyone changes the math, these tests fail with a precise diff
("expected 0.567, got 0.500 at tags={...}").
"""
from __future__ import annotations

import pytest
from hypothesis import given, strategies as st, settings, HealthCheck

from agent.finance.lattice import spec


pytestmark = pytest.mark.lattice_fast


# Known-tag universe for hypothesis tests
_TAGS = [
    "symbol:A", "symbol:B", "symbol:C",
    "risk:earnings", "risk:macro",
    "technical:near_52w_high", "technical:near_52w_low", "technical:breakout",
    "direction:up", "direction:down",
    "timescale:short", "timescale:intraday",
    "catalyst:earnings", "catalyst:fed",
    "signal:bullish", "signal:bearish",
]
_SEVERITIES = ["alert", "warn", "info", "unknown_sev"]


# ── base_membership_weight ─────────────────────────────

@pytest.mark.parametrize("obs_tags, any_of, all_of, expected", [
    # (obs tags, sig.any_of, sig.all_of, expected base weight)
    (frozenset({"a", "b"}),       frozenset({"a", "b"}), frozenset(),        1.0),
    (frozenset({"a"}),            frozenset({"a", "b"}), frozenset(),        0.5),
    (frozenset({"a", "b", "c"}),  frozenset({"a", "b"}), frozenset(),        1.0),   # extras ignored
    (frozenset({"c"}),            frozenset({"a", "b"}), frozenset(),        0.0),   # no intersection
    (frozenset({"a", "req"}),     frozenset({"a", "b"}), frozenset({"req"}), (0.5 + 1.0) / 2),  # both halves
    (frozenset({"a"}),            frozenset({"a", "b"}), frozenset({"req"}), 0.0),   # all_of unsatisfied
    (frozenset({"req"}),          frozenset(),           frozenset({"req"}), 1.0),   # only all_of
    (frozenset(),                 frozenset(),           frozenset(),        0.0),   # fully empty
    (frozenset({"x"}),            frozenset(),           frozenset(),        0.0),   # empty signature
])
def test_base_membership_weight_exact(obs_tags, any_of, all_of, expected):
    got = spec.base_membership_weight(obs_tags, any_of, all_of)
    assert abs(got - expected) < 1e-12, f"expected {expected!r}, got {got!r}"


# ── final_membership_weight (with severity bonus) ─────

@pytest.mark.parametrize("obs_tags, any_of, all_of, severity, expected", [
    # severity 'alert' → bonus=1.0 → unchanged from base
    (frozenset({"a"}), frozenset({"a", "b"}), frozenset(), "alert", 0.5),
    # severity 'warn' → bonus=0.85
    (frozenset({"a"}), frozenset({"a", "b"}), frozenset(), "warn",  0.5 * 0.85),
    # severity 'info' → bonus=0.7
    (frozenset({"a"}), frozenset({"a", "b"}), frozenset(), "info",  0.5 * 0.7),
    # unknown severity falls back to default 0.7
    (frozenset({"a"}), frozenset({"a", "b"}), frozenset(), "crit",  0.5 * 0.7),
    # full match + alert → exactly 1.0 (would be 1.0 × 1.0)
    (frozenset({"a", "b"}), frozenset({"a", "b"}), frozenset(), "alert", 1.0),
    # full any_of match + all_of satisfied + warn → (1.0+1.0)/2 × 0.85
    (frozenset({"a", "b", "r"}), frozenset({"a", "b"}), frozenset({"r"}), "warn",
     ((1.0 + 1.0) / 2) * 0.85),
    # base 0 stays 0 regardless of severity (no spread)
    (frozenset({"x"}), frozenset({"a", "b"}), frozenset(), "alert", 0.0),
])
def test_final_membership_weight_exact(obs_tags, any_of, all_of, severity, expected):
    got = spec.final_membership_weight(obs_tags, any_of, all_of, severity)
    assert abs(got - expected) < 1e-12, f"expected {expected!r}, got {got!r}"


# ── Production wrapper parity ──────────────────────────

def test_themes_membership_wrapper_matches_spec():
    """themes._membership_weight must produce the SAME number as
    spec.base_membership_weight for the same inputs. Wrapper must
    not drift."""
    from agent.finance.lattice import themes
    from agent.finance.lattice.taxonomy import ThemeSignature

    test_cases = [
        (frozenset({"a", "b"}), frozenset({"a", "b"}), frozenset()),
        (frozenset({"a"}),      frozenset({"a", "b"}), frozenset()),
        (frozenset({"a", "r"}), frozenset({"a", "b"}), frozenset({"r"})),
        (frozenset({"a"}),      frozenset({"a", "b"}), frozenset({"r"})),
        (frozenset({"x"}),      frozenset({"a", "b"}), frozenset()),
    ]
    for tags, any_of, all_of in test_cases:
        sig = ThemeSignature(id="t", title="T", any_of=any_of, all_of=all_of)
        got = themes._membership_weight(tags, sig)
        expected = spec.base_membership_weight(tags, any_of, all_of)
        assert got == expected, f"wrapper drift: {tags} {any_of}/{all_of} → {got} vs {expected}"


def test_cluster_observations_weight_equals_spec_final_formula():
    """cluster_observations stores final weight on every member —
    that number must equal spec.final_membership_weight output."""
    from agent.finance.lattice import themes
    from agent.finance.lattice.observations import Observation
    from agent.finance.lattice.taxonomy import ThemeSignature

    obs = [
        Observation(id="o1", kind="x", text="t1",
                    tags=["a", "b"], severity="alert"),
        Observation(id="o2", kind="x", text="t2",
                    tags=["a"], severity="warn"),
        Observation(id="o3", kind="x", text="t3",
                    tags=["a", "r"], severity="info"),
    ]
    sig = ThemeSignature(id="s", title="S",
                         any_of=frozenset({"a", "b"}),
                         all_of=frozenset({"r"}))
    clusters = themes.cluster_observations(obs, [sig])
    assert len(clusters) == 1
    for o, w in clusters[0]["members"]:
        expected = spec.final_membership_weight(
            set(o.tags), sig.any_of, sig.all_of, o.severity,
        )
        assert w == expected, f"{o.id}: clustered {w} vs spec {expected}"


# ── Property: weight always in [0, 1] ──────────────────

@given(
    obs_tags=st.sets(st.sampled_from(_TAGS), max_size=8),
    any_of=st.sets(st.sampled_from(_TAGS), max_size=4),
    all_of=st.sets(st.sampled_from(_TAGS), max_size=3),
    severity=st.sampled_from(_SEVERITIES),
)
@settings(max_examples=500, deadline=None,
          suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_final_weight_always_in_unit_interval(obs_tags, any_of, all_of, severity):
    w = spec.final_membership_weight(
        frozenset(obs_tags), frozenset(any_of), frozenset(all_of), severity,
    )
    assert 0.0 <= w <= 1.0, f"weight {w} out of [0, 1] for {obs_tags=} {severity=}"


# ── Property: determinism (same input → same output) ──

@given(
    obs_tags=st.sets(st.sampled_from(_TAGS), min_size=1),
    any_of=st.sets(st.sampled_from(_TAGS), min_size=1, max_size=4),
    severity=st.sampled_from(["alert", "warn", "info"]),
)
@settings(max_examples=200, deadline=None)
def test_property_final_weight_deterministic(obs_tags, any_of, severity):
    w1 = spec.final_membership_weight(
        frozenset(obs_tags), frozenset(any_of), frozenset(), severity)
    w2 = spec.final_membership_weight(
        frozenset(obs_tags), frozenset(any_of), frozenset(), severity)
    assert w1 == w2


# ── Property: overlap preservation (no MECE bias) ─────

@given(
    obs_tags=st.sets(st.sampled_from(_TAGS), min_size=2),
    sig_any=st.sets(st.sampled_from(_TAGS), min_size=1, max_size=3),
)
@settings(max_examples=200, deadline=None)
def test_property_same_signature_same_weight(obs_tags, sig_any):
    """Two signatures with identical any_of must give identical
    weights for the same obs. Overlap is preserved by construction."""
    w1 = spec.final_membership_weight(
        frozenset(obs_tags), frozenset(sig_any), frozenset(), "warn")
    w2 = spec.final_membership_weight(
        frozenset(obs_tags), frozenset(sig_any), frozenset(), "warn")
    assert w1 == w2
    # If any_of hits, both are >0 (no MECE)
    if obs_tags & sig_any:
        assert w1 > 0


# ── is_tautological_warrant ────────────────────────────

@pytest.mark.parametrize("claim, warrant, expected", [
    ("Hold AAPL", "Hold AAPL", True),                          # exact equality
    ("HOLD AAPL", "hold aapl", True),                          # case-insensitive
    ("Hold AAPL", "Hold AAPL because", True),                  # only +9 chars
    ("Hold AAPL", "Hold AAPL because it", False),              # +12 chars (≥10)
    ("Hold AAPL", "Because IV is elevated, the prudent move is to hold.", False),
    ("Buy NVDA", "Buy NVDA", True),
    ("Short TSLA 5%", "Shorting TSLA at 5% makes sense", False),  # different text
])
def test_tautology_guard_exact(claim, warrant, expected):
    assert spec.is_tautological_warrant(claim, warrant) == expected


# ── ground_similarity ──────────────────────────────────

@pytest.mark.parametrize("a, b, expected", [
    ({"t1", "t2"},      {"t1", "t2"},      1.0),       # identical
    ({"t1"},            {"t2"},            0.0),       # disjoint
    ({"t1", "t2"},      {"t1"},            0.5),       # 1 shared / 2 union
    ({"t1", "t2", "t3"}, {"t2", "t3", "t4"}, 2/4),     # 2 shared / 4 union
    (set(),             {"t1"},            0.0),       # empty left
    ({"t1"},            set(),             0.0),       # empty right
    (set(),             set(),             0.0),       # both empty
])
def test_ground_similarity_exact(a, b, expected):
    got = spec.ground_similarity(a, b)
    assert abs(got - expected) < 1e-12


# ── relevance_score ────────────────────────────────────

def test_relevance_score_breakdown_hand_computed():
    """Lock the full formula with a hand-computed case:
    grounds = [(alert, 3 members), (warn, 5 members)],
    confidence = high.

    alert_contrib = 1.0 × (1 + min(3,5)/5)   = 1.0 × 1.6 = 1.6
    warn_contrib  = 0.7 × (1 + min(5,5)/5)   = 0.7 × 2.0 = 1.4
    subtotal      = 3.0
    final         = 3.0 × confidence_score(high) = 3.0 × 1.0 = 3.0
    """
    got = spec.relevance_score([("alert", 3), ("warn", 5)], "high")
    assert abs(got - 3.0) < 1e-12


def test_relevance_score_saturates_at_5_members():
    """min(n_members, 5) caps the size contribution."""
    a = spec.relevance_score([("warn", 5)], "medium")
    b = spec.relevance_score([("warn", 50)], "medium")
    assert a == b


def test_relevance_score_zero_when_no_grounds():
    assert spec.relevance_score([], "high") == 0.0


@given(
    n_grounds=st.integers(min_value=0, max_value=5),
    confidence=st.sampled_from(["high", "medium", "low"]),
)
@settings(max_examples=100, deadline=None)
def test_property_relevance_nonneg(n_grounds, confidence):
    grounds = [("warn", 3) for _ in range(n_grounds)]
    assert spec.relevance_score(grounds, confidence) >= 0.0


# ── mmr ────────────────────────────────────────────────

def test_mmr_formula_exact():
    # λ=0.7, rel=1.0, max_sim=0.0  → 0.7·1.0 - 0.3·0.0 = 0.7
    assert abs(spec.mmr(1.0, 0.0) - 0.7) < 1e-12
    # λ=0.7, rel=1.0, max_sim=1.0  → 0.7·1.0 - 0.3·1.0 = 0.4
    assert abs(spec.mmr(1.0, 1.0) - 0.4) < 1e-12
    # explicit lambda
    assert abs(spec.mmr(2.0, 0.5, lambda_=0.5) - (0.5*2.0 - 0.5*0.5)) < 1e-12


@given(
    rel=st.floats(min_value=0, max_value=10, allow_nan=False, allow_infinity=False),
    max_sim=st.floats(min_value=0, max_value=1, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=200, deadline=None)
def test_property_mmr_monotonic_in_relevance(rel, max_sim):
    """Higher relevance (all else equal) → higher MMR."""
    a = spec.mmr(rel, max_sim)
    b = spec.mmr(rel + 0.1, max_sim)
    assert b >= a
