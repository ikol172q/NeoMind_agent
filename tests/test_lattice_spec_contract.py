"""L1 · spec ↔ implementation contract tests.

Goal: prove that every algorithmic constant used by production code
is THE SAME OBJECT (identity, not just equal value) as the one in
agent/finance/lattice/spec.py. If anyone ever declares a local copy
with equivalent values, these tests fail — even though behaviour
would still pass, because drift risk is real.
"""
from __future__ import annotations

import pytest


pytestmark = pytest.mark.lattice_fast


# ── identity of constants ──────────────────────────────

def test_themes_cluster_severity_bonus_is_spec_object():
    from agent.finance.lattice import themes, spec
    assert themes._SEVERITY_BONUS is spec.CLUSTER_SEVERITY_BONUS


def test_themes_severity_bonus_function_is_spec():
    from agent.finance.lattice import themes, spec
    assert themes._severity_bonus is spec.cluster_severity_bonus


def test_themes_severity_rank_function_is_spec():
    from agent.finance.lattice import themes, spec
    assert themes._severity_rank is spec.severity_rank


def test_calls_mmr_lambda_is_spec_value():
    from agent.finance.lattice import calls, spec
    assert calls._MMR_LAMBDA == spec.MMR_LAMBDA
    # floats can't use `is`; pin the number explicitly so a future
    # `_MMR_LAMBDA = 0.6` in calls.py (without spec update) still fails
    assert calls._MMR_LAMBDA == 0.7


def test_calls_max_cap_is_spec_value():
    from agent.finance.lattice import calls, spec
    assert calls._MAX_CALLS == spec.MAX_CALLS == 3
    assert calls._MAX_CANDIDATES == spec.MAX_CANDIDATES == 5


def test_calls_enums_are_spec_objects():
    from agent.finance.lattice import calls, spec
    assert calls._CONFIDENCE is spec.CONFIDENCE_VALUES
    assert calls._HORIZON is spec.TIME_HORIZON_VALUES
    assert calls._REQUIRED is spec.CALL_REQUIRED_FIELDS


# ── spec values are what we claim they are ─────────────
#
# These lock the *numeric values* of the spec itself, so a casual
# edit to spec.py without judgement still trips a test. Any bump
# requires editing two places: spec.py AND this file. That's
# intentional friction.

def test_spec_cluster_severity_bonus_values():
    from agent.finance.lattice import spec
    assert spec.CLUSTER_SEVERITY_BONUS == {"alert": 1.0, "warn": 0.85, "info": 0.7}
    assert spec.CLUSTER_SEVERITY_BONUS_DEFAULT == 0.7


def test_spec_ground_severity_score_values():
    from agent.finance.lattice import spec
    assert spec.GROUND_SEVERITY_SCORE == {"alert": 1.0, "warn": 0.7, "info": 0.5}
    assert spec.GROUND_SEVERITY_SCORE_DEFAULT == 0.5


def test_spec_confidence_score_values():
    from agent.finance.lattice import spec
    assert spec.CONFIDENCE_SCORE == {"high": 1.0, "medium": 0.7, "low": 0.4}
    assert spec.CONFIDENCE_SCORE_DEFAULT == 0.5


def test_spec_severity_rank_values():
    from agent.finance.lattice import spec
    assert spec.SEVERITY_RANK == {"alert": 0, "warn": 1, "info": 2}
    assert spec.SEVERITY_RANK_DEFAULT == 3


def test_spec_mmr_and_caps():
    from agent.finance.lattice import spec
    assert spec.MMR_LAMBDA == 0.7
    assert spec.MAX_CALLS == 3
    assert spec.MAX_CANDIDATES == 5
    assert spec.TAUTOLOGY_MIN_EXTENSION == 10


def test_spec_enum_values_exhaustive():
    from agent.finance.lattice import spec
    assert set(spec.CONFIDENCE_VALUES) == {"high", "medium", "low"}
    assert set(spec.TIME_HORIZON_VALUES) == {"intraday", "days", "weeks", "quarter"}
    # Provenance / layers / edge kinds are used by V2 graph endpoint;
    # pin them here so the graph can't silently invent a new kind.
    assert set(spec.PROVENANCE_KINDS) == {
        "source", "deterministic", "llm", "llm+validator", "llm+mmr",
    }
    assert set(spec.LAYERS) == {"L0", "L1", "L1.5", "L2", "L3"}
    assert set(spec.EDGE_KINDS) == {"source_emission", "membership", "grounds"}


def test_spec_call_required_fields_match_validator():
    """The candidate validator iterates this tuple; order matters
    for error messages but set equality is the contract."""
    from agent.finance.lattice import spec
    assert set(spec.CALL_REQUIRED_FIELDS) == {
        "claim", "grounds", "warrant", "qualifier", "rebuttal",
        "confidence", "time_horizon",
    }
