"""D3 · Insight Lattice — L3 Toulmin-structured calls tests.

Three classes of tests:
  1. Unit — MMR diversity selector, candidate validator, ground
     validation, tautology guard.
  2. LLM-failure resilience — L3 must never break the endpoint.
  3. End-to-end — /api/lattice/calls returns the right envelope;
     every call's grounds reference real theme_ids; no two calls
     share their entire ground set.
"""
from __future__ import annotations

import json
import urllib.request
from urllib.parse import urlencode

import pytest

BASE_URL = "http://127.0.0.1:8001/"
PROJECT = "fin-core"


# ── Unit ────────────────────────────────────────────────

def test_mmr_picks_diverse_calls_over_redundant_ones():
    from agent.finance.lattice.calls import select_calls_mmr
    from agent.finance.lattice.themes import Theme, ThemeMember

    themes = [
        Theme(id="t_a", title="A", narrative="", narrative_source="llm",
              members=[ThemeMember("o1", 1.0)], tags=[], severity="alert"),
        Theme(id="t_b", title="B", narrative="", narrative_source="llm",
              members=[ThemeMember("o2", 1.0)], tags=[], severity="warn"),
        Theme(id="t_c", title="C", narrative="", narrative_source="llm",
              members=[ThemeMember("o3", 1.0)], tags=[], severity="info"),
    ]
    cands = [
        {"claim": "X", "grounds": ["t_a"], "warrant": "w", "qualifier": "q",
         "rebuttal": "r", "confidence": "high", "time_horizon": "days"},
        # Redundant with the first — same grounds
        {"claim": "X'", "grounds": ["t_a"], "warrant": "w", "qualifier": "q",
         "rebuttal": "r", "confidence": "high", "time_horizon": "days"},
        {"claim": "Y", "grounds": ["t_b"], "warrant": "w", "qualifier": "q",
         "rebuttal": "r", "confidence": "high", "time_horizon": "days"},
        {"claim": "Z", "grounds": ["t_c"], "warrant": "w", "qualifier": "q",
         "rebuttal": "r", "confidence": "medium", "time_horizon": "weeks"},
    ]
    picked = select_calls_mmr(cands, themes, k=3)
    grounds_sets = [frozenset(c["grounds"]) for c in picked]
    # No two picked calls can have the same grounds set
    assert len(grounds_sets) == len(set(grounds_sets)), (
        f"MMR returned redundant calls: {grounds_sets}"
    )
    # Must have picked 3 out of 4 (one of the redundant pair dropped)
    assert len(picked) == 3


def test_mmr_respects_k_cap_and_empty_input():
    from agent.finance.lattice.calls import select_calls_mmr
    assert select_calls_mmr([], [], k=3) == []


def test_validator_drops_call_with_unknown_grounds():
    """V6: validator now returns (sanitised, drop_reason, drop_detail).
    Phantom grounds → (None, 'grounds_phantom', {unknown, valid_theme_ids})."""
    from agent.finance.lattice.calls import _validate_candidate
    raw = {
        "claim": "Hold AAPL", "grounds": ["theme_fake_001"],
        "warrant": "weak breadth implies caution",
        "qualifier": "medium confidence", "rebuttal": "VIX < 15",
        "confidence": "medium", "time_horizon": "days",
    }
    sanitised, reason, detail = _validate_candidate(raw, valid_theme_ids={"theme_earnings_risk"})
    assert sanitised is None
    assert reason == "grounds_phantom"
    assert "theme_fake_001" in detail["unknown"]


def test_validator_accepts_well_formed_call():
    from agent.finance.lattice.calls import _validate_candidate
    raw = {
        "claim": "Hold AAPL through earnings",
        "grounds": ["theme_earnings_risk"],
        "warrant": "IV is elevated which typically compresses after print",
        "qualifier": "medium confidence, skip if VIX > 25",
        "rebuttal": "if AAPL pre-announces a warning",
        "confidence": "medium", "time_horizon": "days",
    }
    sanitised, reason, detail = _validate_candidate(
        raw, valid_theme_ids={"theme_earnings_risk"},
    )
    assert reason is None
    assert detail is None
    assert sanitised is not None
    assert sanitised["grounds"] == ["theme_earnings_risk"]
    assert sanitised["confidence"] == "medium"


def test_validator_drops_tautological_warrant():
    from agent.finance.lattice.calls import _validate_candidate
    raw = {
        "claim": "Hold AAPL through earnings",
        "grounds": ["theme_earnings_risk"],
        "warrant": "Hold AAPL through earnings",
        "qualifier": "medium confidence", "rebuttal": "if bad",
        "confidence": "medium", "time_horizon": "days",
    }
    sanitised, reason, detail = _validate_candidate(
        raw, valid_theme_ids={"theme_earnings_risk"},
    )
    assert sanitised is None
    assert reason == "tautology"
    assert detail["delta_chars"] == 0   # claim == warrant → 0-char extension


def test_validator_drops_unknown_confidence_or_horizon():
    from agent.finance.lattice.calls import _validate_candidate
    base = {
        "claim": "Hold AAPL", "grounds": ["theme_a"],
        "warrant": "weak breadth implies caution",
        "qualifier": "q", "rebuttal": "r",
        "confidence": "medium", "time_horizon": "days",
    }
    sanitised, reason, detail = _validate_candidate(
        {**base, "confidence": "extreme"}, valid_theme_ids={"theme_a"},
    )
    assert sanitised is None
    assert reason == "invalid_confidence"
    assert detail["got"] == "extreme"

    sanitised, reason, detail = _validate_candidate(
        {**base, "time_horizon": "forever"}, valid_theme_ids={"theme_a"},
    )
    assert sanitised is None
    assert reason == "invalid_horizon"
    assert detail["got"] == "forever"


def test_generate_calls_returns_empty_on_llm_failure(monkeypatch):
    """If the LLM call throws, generate_calls must return []
    — L3 must never propagate failures to the endpoint layer."""
    from agent.finance.lattice import calls as calls_mod
    from agent.finance.lattice.themes import Theme, ThemeMember

    def _boom(*a, **kw):
        raise RuntimeError("synthetic LLM outage")
    monkeypatch.setattr(calls_mod, "_call_llm", _boom)

    themes = [Theme(id="t1", title="T", narrative="n", narrative_source="llm",
                    members=[ThemeMember("o1", 1.0)], tags=[], severity="warn")]
    assert calls_mod.generate_calls(themes, project_id="p", fresh=True) == []


def test_generate_calls_returns_empty_for_empty_themes():
    from agent.finance.lattice.calls import generate_calls
    assert generate_calls([], project_id="p", fresh=True) == []


def test_generate_calls_drops_all_when_every_candidate_references_phantom(monkeypatch):
    """LLM returns calls grounded in theme_ids we don't have — every
    one is dropped, output is []."""
    from agent.finance.lattice import calls as calls_mod
    from agent.finance.lattice.themes import Theme, ThemeMember

    def _fake_llm(prompt):
        return {"candidates": [
            {"claim": "X", "grounds": ["theme_fake"],
             "warrant": "weak breadth implies caution",
             "qualifier": "q", "rebuttal": "r",
             "confidence": "medium", "time_horizon": "days"},
        ]}
    monkeypatch.setattr(calls_mod, "_call_llm", _fake_llm)

    themes = [Theme(id="theme_real", title="Real", narrative="n",
                    narrative_source="llm",
                    members=[ThemeMember("o1", 1.0)], tags=[], severity="warn")]
    assert calls_mod.generate_calls(themes, project_id="p", fresh=True) == []


# ── End-to-end (requires dashboard) ────────────────────

def _backend_up() -> bool:
    try:
        with urllib.request.urlopen(BASE_URL + "api/health", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def _reset():
    try:
        with urllib.request.urlopen(
            BASE_URL + f"api/watchlist?project_id={PROJECT}", timeout=3
        ) as r:
            data = json.loads(r.read())
        for e in data.get("entries", []):
            req = urllib.request.Request(
                BASE_URL + f"api/watchlist/{e['symbol']}?project_id={PROJECT}&market={e['market']}",
                method="DELETE",
            )
            urllib.request.urlopen(req, timeout=3).read()
    except Exception:
        pass
    try:
        urllib.request.urlopen(
            urllib.request.Request(
                BASE_URL + f"api/paper/reset?project_id={PROJECT}&confirm=yes",
                method="POST",
            ),
            timeout=5,
        ).read()
    except Exception:
        pass


def _seed_watch(symbol: str, market: str = "US"):
    req = urllib.request.Request(
        BASE_URL + f"api/watchlist?project_id={PROJECT}",
        data=json.dumps({"symbol": symbol, "market": market, "note": ""}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    urllib.request.urlopen(req, timeout=5).read()


def _place_order(symbol: str, qty: int):
    qs = urlencode({
        "project_id": PROJECT, "symbol": symbol, "side": "buy",
        "quantity": qty, "order_type": "market",
    })
    urllib.request.urlopen(
        urllib.request.Request(BASE_URL + f"api/paper/order?{qs}", method="POST"),
        timeout=10,
    ).read()
    urllib.request.urlopen(
        urllib.request.Request(BASE_URL + f"api/paper/refresh?project_id={PROJECT}", method="POST"),
        timeout=10,
    ).read()


def _fetch_calls():
    url = BASE_URL + f"api/lattice/calls?project_id={PROJECT}&fresh=1"
    with urllib.request.urlopen(url, timeout=300) as r:
        return json.loads(r.read())


@pytest.fixture(scope="module", autouse=True)
def _skip_if_no_backend():
    if not _backend_up():
        pytest.skip(f"backend not reachable at {BASE_URL}")


def test_calls_endpoint_returns_envelope():
    _reset()
    d = _fetch_calls()
    assert d["project_id"] == PROJECT
    assert isinstance(d["observations"], list)
    assert isinstance(d["themes"], list)
    assert isinstance(d["calls"], list)
    # 0 calls is a valid answer — don't assert a lower bound
    assert len(d["calls"]) <= 3


def test_every_call_has_toulmin_schema():
    _reset()
    _seed_watch("AAPL")
    _place_order("AAPL", 5)
    d = _fetch_calls()
    required = {"id", "claim", "grounds", "warrant", "qualifier",
                "rebuttal", "confidence", "time_horizon"}
    for c in d["calls"]:
        assert required.issubset(c.keys()), f"call missing fields: {c}"
        assert isinstance(c["grounds"], list) and c["grounds"]
        assert c["confidence"] in ("high", "medium", "low")
        assert c["time_horizon"] in ("intraday", "days", "weeks", "quarter")


def test_every_ground_references_real_theme():
    """A call's grounds must only contain theme_ids that exist in
    the same response. Ungrounded calls are bugs."""
    _reset()
    for s in ("AAPL", "MSFT", "NVDA"):
        _seed_watch(s)
    _place_order("AAPL", 5)
    d = _fetch_calls()
    theme_ids = {t["id"] for t in d["themes"]}
    for c in d["calls"]:
        unknown = [g for g in c["grounds"] if g not in theme_ids]
        assert not unknown, (
            f"call {c['id']} references phantom themes {unknown}; "
            f"known themes: {theme_ids}"
        )


def test_calls_are_diverse_no_identical_ground_sets():
    _reset()
    for s in ("AAPL", "MSFT", "NVDA", "GOOGL", "META"):
        _seed_watch(s)
    _place_order("AAPL", 5)
    d = _fetch_calls()
    seen: set[frozenset[str]] = set()
    for c in d["calls"]:
        gs = frozenset(c["grounds"])
        assert gs not in seen, (
            f"two calls share identical grounds {gs} — MMR failed"
        )
        seen.add(gs)


def test_warrant_is_not_tautological():
    _reset()
    _seed_watch("AAPL")
    _place_order("AAPL", 5)
    d = _fetch_calls()
    for c in d["calls"]:
        claim = c["claim"].lower().strip()
        warrant = c["warrant"].lower().strip()
        assert warrant != claim, f"call {c['id']} warrant equals claim"
        # warrant should add at least 10 chars of reasoning
        if claim in warrant:
            assert len(warrant) - len(claim) >= 10, (
                f"call {c['id']} warrant barely extends claim"
            )
