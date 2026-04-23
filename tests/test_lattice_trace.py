"""V6 · Deep trace instrumentation + language toggle — tests.

Three layers:
  - spec contract: DROP_REASONS enum + validator returns tuples
  - unit: validator returns the expected drop reason for each
    synthetic failure; MMR trace captures per-candidate scores
  - integration: /api/lattice/trace/{node_id} returns the live
    prompt + candidate pool; /api/lattice/language toggles
"""
from __future__ import annotations

import json
import urllib.request
import urllib.parse

import pytest

from agent.finance.lattice import spec


pytestmark = pytest.mark.lattice_fast


BASE_URL = "http://127.0.0.1:8001/"


# ── Spec contract ──────────────────────────────────────

def test_drop_reasons_enum_complete():
    """Every drop-reason string produced by _validate_candidate or
    select_calls_mmr must be in spec.DROP_REASONS. If someone adds
    a new reason in the code, spec.py must be updated first."""
    assert set(spec.DROP_REASONS) == {
        "missing_field", "invalid_confidence", "invalid_horizon",
        "tautology", "grounds_empty", "grounds_phantom",
        "mmr_hard_dedup", "mmr_low_score", "candidate_pool_full",
    }


# ── Validator returns tuple + uses spec reasons ───────

def test_validator_returns_tuple_shape():
    """The new contract: _validate_candidate returns exactly a
    3-tuple (sanitised|None, drop_reason|None, drop_detail|None)."""
    from agent.finance.lattice.calls import _validate_candidate
    good = {
        "claim": "Buy AAPL on earnings strength (short-dated calls).",
        "grounds": ["theme_x"], "warrant": "elevated IV often mean-reverts after print",
        "qualifier": "size ≤1% book", "rebuttal": "if IV doesn't compress",
        "confidence": "medium", "time_horizon": "days",
    }
    result = _validate_candidate(good, {"theme_x"})
    assert isinstance(result, tuple) and len(result) == 3
    assert result[0] is not None
    assert result[1] is None
    assert result[2] is None


@pytest.mark.parametrize("mutation,expected_reason", [
    # Missing required field
    ({"claim": ""},              "missing_field"),
    ({"warrant": "  "},          "missing_field"),
    # Enum violations
    ({"confidence": "extreme"},  "invalid_confidence"),
    ({"time_horizon": "year"},   "invalid_horizon"),
    # Tautology guard
    ({"warrant": "Buy AAPL"},    "tautology"),   # equal to claim
    # Grounds
    ({"grounds": []},            "grounds_empty"),
    ({"grounds": ["ghost"]},     "grounds_phantom"),
])
def test_validator_reports_expected_drop_reason(mutation, expected_reason):
    from agent.finance.lattice.calls import _validate_candidate
    base = {
        "claim": "Buy AAPL",
        "grounds": ["theme_real"],
        "warrant": "because the setup favours asymmetric upside this week",
        "qualifier": "size ≤ 1% of book",
        "rebuttal": "if revenue guide down",
        "confidence": "medium",
        "time_horizon": "days",
    }
    raw = {**base, **mutation}
    _, reason, _ = _validate_candidate(raw, {"theme_real"})
    assert reason == expected_reason, (
        f"mutation {mutation} expected {expected_reason}, got {reason}"
    )
    assert reason in spec.DROP_REASONS


# ── MMR trace return shape ─────────────────────────────

def test_mmr_return_trace_yields_per_candidate_entries():
    from agent.finance.lattice.calls import select_calls_mmr
    from agent.finance.lattice.themes import Theme, ThemeMember

    themes = [
        Theme(id=f"t{i}", title=f"T{i}", narrative="", narrative_source="llm",
              members=[ThemeMember(f"o{i}", 1.0)], tags=[], severity="warn")
        for i in range(3)
    ]
    cands = [
        {"claim": f"C{i}", "grounds": [f"t{i}"], "warrant": "w", "qualifier": "q",
         "rebuttal": "r", "confidence": "high", "time_horizon": "days"}
        for i in range(3)
    ]
    picked, trace = select_calls_mmr(cands, themes, k=2, return_trace=True)
    assert len(picked) == 2
    assert len(trace) == 3
    # Two accepted, one dropped as candidate_pool_full
    statuses = [t["status"] for t in trace]
    assert statuses.count("accepted") == 2
    assert statuses.count("dropped") == 1
    dropped = [t for t in trace if t["status"] == "dropped"][0]
    assert dropped["drop_reason"] == "candidate_pool_full"
    assert dropped["drop_reason"] in spec.DROP_REASONS
    # Every accepted candidate has a numeric selected_mmr_score
    for t in trace:
        if t["status"] == "accepted":
            assert isinstance(t["selected_mmr_score"], float)
            assert t.get("selected_max_sim") is not None


def test_mmr_hard_dedup_reported():
    from agent.finance.lattice.calls import select_calls_mmr
    from agent.finance.lattice.themes import Theme, ThemeMember

    themes = [
        Theme(id="t_a", title="A", narrative="", narrative_source="llm",
              members=[ThemeMember("o", 1.0)], tags=[], severity="warn"),
    ]
    cands = [
        {"claim": "first", "grounds": ["t_a"], "warrant": "w", "qualifier": "q",
         "rebuttal": "r", "confidence": "high", "time_horizon": "days"},
        {"claim": "dup",   "grounds": ["t_a"], "warrant": "w", "qualifier": "q",
         "rebuttal": "r", "confidence": "high", "time_horizon": "days"},
    ]
    _, trace = select_calls_mmr(cands, themes, k=3, return_trace=True)
    statuses = [t["status"] for t in trace]
    assert "accepted" in statuses
    dropped = [t for t in trace if t["status"] == "dropped"]
    assert len(dropped) == 1
    assert dropped[0]["drop_reason"] == "mmr_hard_dedup"


# ── Runtime language override ──────────────────────────

def test_runtime_set_override_clear():
    from agent.finance.lattice import runtime
    # Clean slate
    runtime.set_language_override("clear")
    assert runtime.get_language_override() is None

    runtime.set_language_override("zh-CN-mixed")
    assert runtime.get_language_override() == "zh-CN-mixed"
    assert runtime.get_effective_language() == "zh-CN-mixed"

    runtime.set_language_override("en")
    assert runtime.get_language_override() == "en"
    assert runtime.get_effective_language() == "en"

    runtime.set_language_override("clear")
    assert runtime.get_language_override() is None


def test_runtime_rejects_unknown_language():
    from agent.finance.lattice import runtime
    with pytest.raises(ValueError):
        runtime.set_language_override("klingon")


# ── Live integration (lattice_slow) ────────────────────

def _backend_up() -> bool:
    try:
        with urllib.request.urlopen(BASE_URL + "api/health", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


@pytest.mark.lattice_slow
def test_language_endpoint_roundtrip():
    if not _backend_up():
        pytest.skip("backend unreachable")
    original = json.loads(urllib.request.urlopen(
        BASE_URL + "api/lattice/language", timeout=5).read())
    try:
        # Set to en
        r = urllib.request.urlopen(urllib.request.Request(
            BASE_URL + "api/lattice/language?lang=en", method="POST"), timeout=5)
        body = json.loads(r.read())
        assert body["active"] == "en"

        # Set to zh-CN-mixed
        r = urllib.request.urlopen(urllib.request.Request(
            BASE_URL + "api/lattice/language?lang=zh-CN-mixed", method="POST"), timeout=5)
        body = json.loads(r.read())
        assert body["active"] == "zh-CN-mixed"

        # Clear
        r = urllib.request.urlopen(urllib.request.Request(
            BASE_URL + "api/lattice/language?lang=clear", method="POST"), timeout=5)
        body = json.loads(r.read())
        assert body["override"] is None
    finally:
        # Restore whatever the test started with
        if original.get("override"):
            urllib.request.urlopen(urllib.request.Request(
                BASE_URL + "api/lattice/language?lang=" + urllib.parse.quote(original["override"]),
                method="POST"), timeout=5)


@pytest.mark.lattice_slow
def test_language_endpoint_rejects_bad_value():
    if not _backend_up():
        pytest.skip("backend unreachable")
    try:
        urllib.request.urlopen(urllib.request.Request(
            BASE_URL + "api/lattice/language?lang=klingon", method="POST"), timeout=5)
        raise AssertionError("expected 400")
    except urllib.error.HTTPError as exc:
        assert exc.code == 400


@pytest.mark.lattice_slow
def test_trace_endpoint_returns_obs_layer_note():
    if not _backend_up():
        pytest.skip("backend unreachable")
    r = urllib.request.urlopen(
        BASE_URL + "api/lattice/trace/obs_something_123?project_id=fin-core",
        timeout=10,
    )
    body = json.loads(r.read())
    assert body["layer"] == "L1"
    assert body["trace"]["kind"] == "deterministic"


@pytest.mark.lattice_slow
def test_trace_endpoint_returns_subtheme_layer_note():
    if not _backend_up():
        pytest.skip("backend unreachable")
    r = urllib.request.urlopen(
        BASE_URL + "api/lattice/trace/subtheme_anything?project_id=fin-core",
        timeout=10,
    )
    body = json.loads(r.read())
    assert body["layer"] == "L1.5"
    assert body["trace"]["kind"] == "deterministic"


@pytest.mark.lattice_slow
def test_trace_endpoint_theme_includes_llm_prompt_if_live():
    """After fresh=1 calls refresh, the theme trace must include the
    actual prompt that was sent. Skipped when DeepSeek unavailable."""
    import os
    if not _backend_up():
        pytest.skip("backend unreachable")
    if not os.environ.get("DEEPSEEK_API_KEY"):
        pytest.skip("no DEEPSEEK_API_KEY")
    # Force fresh regeneration so the trace populates
    urllib.request.urlopen(
        BASE_URL + "api/lattice/calls?project_id=fin-core&fresh=1",
        timeout=300,
    ).read()
    # Pick one theme from the payload
    calls_payload = json.loads(urllib.request.urlopen(
        BASE_URL + "api/lattice/calls?project_id=fin-core", timeout=30,
    ).read())
    themes = calls_payload["themes"]
    if not themes:
        pytest.skip("no themes in current fin-core state")
    theme_id = themes[0]["id"]
    r = urllib.request.urlopen(
        BASE_URL + f"api/lattice/trace/{theme_id}?project_id=fin-core",
        timeout=10,
    )
    body = json.loads(r.read())
    trace = body["trace"]
    # Either llm_call (we just regenerated) OR cache_hit if
    # something raced — both are valid shapes. If llm_call, the
    # prompt text must be non-empty.
    assert trace["kind"] in ("llm_call", "cache_hit")
    if trace["kind"] == "llm_call":
        assert trace["model"] == "deepseek-chat"
        assert len(trace["user_prompt"]) > 100
        assert trace["validator"]["passed"] in (True, False)
        assert trace["final_source"] in ("llm", "template_fallback")
