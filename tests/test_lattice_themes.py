"""D2 · Insight Lattice — L2 theme clustering + narrative tests.

Three classes of tests:
  1. Unit — clustering math (Jaccard weight, overlap preserved,
     min_members respected).
  2. Narrative validation — LLM citation post-check drops
     hallucinated numbers and falls back to the template.
  3. End-to-end — seed REST state, /api/lattice/themes returns the
     expected shape, overlap empirically proven at the theme level.
"""
from __future__ import annotations

import json
import urllib.request
import urllib.error
from urllib.parse import urlencode

import pytest

BASE_URL = "http://127.0.0.1:8001/"
PROJECT = "fin-core"


# ── Unit tests (no backend) ────────────────────────────

def test_membership_weight_math():
    from agent.finance.lattice.themes import _membership_weight
    from agent.finance.lattice.taxonomy import ThemeSignature

    # Pure any_of
    sig = ThemeSignature(id="t", title="T", any_of=frozenset(["a", "b"]))
    assert _membership_weight({"a", "b", "c"}, sig) == 1.0
    assert _membership_weight({"a", "c"}, sig) == 0.5
    assert _membership_weight({"c"}, sig) == 0.0

    # all_of hard gate
    sig2 = ThemeSignature(id="t", title="T",
                          any_of=frozenset(["x", "y"]),
                          all_of=frozenset(["req"]))
    assert _membership_weight({"x", "req"}, sig2) == (0.5 + 1.0) / 2
    assert _membership_weight({"x", "y"}, sig2) == 0.0, "all_of must match"


def test_cluster_preserves_overlap():
    """The non-negotiable: a single observation that matches multiple
    theme signatures ends up in all of them."""
    from agent.finance.lattice.themes import cluster_observations
    from agent.finance.lattice.observations import Observation
    from agent.finance.lattice.taxonomy import ThemeSignature

    sigs = [
        ThemeSignature(id="t_a", title="A", any_of=frozenset(["tag_a"])),
        ThemeSignature(id="t_b", title="B", any_of=frozenset(["tag_b"])),
    ]
    obs = [Observation(id="o1", kind="x", text="ambidextrous", tags=["tag_a", "tag_b"])]
    clusters = cluster_observations(obs, sigs)
    theme_ids = {c["sig"].id for c in clusters}
    assert theme_ids == {"t_a", "t_b"}, "overlap lost"
    # Every cluster should have o1 as member
    for c in clusters:
        member_ids = [o.id for o, _ in c["members"]]
        assert "o1" in member_ids


def test_cluster_drops_themes_below_min_members():
    from agent.finance.lattice.themes import cluster_observations
    from agent.finance.lattice.observations import Observation
    from agent.finance.lattice.taxonomy import ThemeSignature

    sigs = [
        ThemeSignature(id="t_picky", title="Picky",
                       any_of=frozenset(["rare_tag"]), min_members=3),
    ]
    obs = [
        Observation(id="o1", kind="x", text="a", tags=["rare_tag"]),
        Observation(id="o2", kind="x", text="b", tags=["rare_tag"]),
    ]
    clusters = cluster_observations(obs, sigs)
    # Only 2 members, min=3 → theme dropped
    assert clusters == []


def test_narrative_citation_validator_accepts_good_claim():
    from agent.finance.lattice.themes import _validate_llm_narrative
    from agent.finance.lattice.observations import Observation

    members = [
        (Observation(id="o1", kind="x",
                     text="AAPL up 2.59% today.", tags=[], numbers={"pct": 2.59}),
         1.0),
    ]
    good = {"narrative": "AAPL rose 2.59% on the session.", "cited_numbers": ["2.59%"]}
    assert _validate_llm_narrative(good, members)


def test_narrative_citation_validator_rejects_hallucinated():
    from agent.finance.lattice.themes import _validate_llm_narrative
    from agent.finance.lattice.observations import Observation

    members = [
        (Observation(id="o1", kind="x",
                     text="AAPL up 2.59% today.", tags=[], numbers={"pct": 2.59}),
         1.0),
    ]
    # LLM invented "7.3%" — not in any member
    bad = {"narrative": "AAPL rose 7.3% on the session.", "cited_numbers": ["7.3%"]}
    assert not _validate_llm_narrative(bad, members)


def test_narrative_falls_back_to_template_on_llm_failure(monkeypatch):
    """If the LLM call raises, the generator must still return a
    valid payload with source=template_fallback — never propagate
    the failure upstream."""
    from agent.finance.lattice import themes
    from agent.finance.lattice.observations import Observation

    def _explode(*a, **kw):
        raise RuntimeError("synthetic LLM outage")
    monkeypatch.setattr(themes, "_call_llm", _explode)

    members = [
        (Observation(id="o1", kind="earnings", text="AAPL reports in 8d.",
                     tags=["symbol:AAPL"], numbers={"days_until": 8}), 1.0),
    ]
    result = themes.generate_narrative("theme_test", "Earnings risk", members, fresh=True)
    assert result["source"] == "template_fallback"
    assert "AAPL" in result["narrative"]


# ── End-to-end (requires dashboard) ────────────────────

def _backend_up() -> bool:
    try:
        with urllib.request.urlopen(BASE_URL + "api/health", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def _reset():
    try:
        with urllib.request.urlopen(BASE_URL + f"api/watchlist?project_id={PROJECT}", timeout=3) as r:
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


def _fetch_themes():
    url = BASE_URL + f"api/lattice/themes?project_id={PROJECT}&fresh=1"
    with urllib.request.urlopen(url, timeout=180) as r:
        return json.loads(r.read())


@pytest.fixture(scope="module", autouse=True)
def _skip_if_no_backend():
    if not _backend_up():
        pytest.skip(f"backend not reachable at {BASE_URL}")


def test_themes_endpoint_returns_envelope():
    _reset()
    d = _fetch_themes()
    assert d["project_id"] == PROJECT
    assert isinstance(d["observations"], list)
    assert isinstance(d["themes"], list)
    for t in d["themes"]:
        assert "id" in t and "title" in t and "narrative" in t
        assert isinstance(t["members"], list)
        assert t["narrative_source"] in ("llm", "template_fallback")


def test_themes_narratives_cite_member_numbers():
    """Every LLM-sourced narrative must contain a number that appears
    somewhere in its members (post-validation enforced on server)."""
    import re
    _reset()
    for s in ("AAPL", "MSFT", "NVDA", "TSLA"):
        _seed_watch(s)
    _place_order("AAPL", 5)
    d = _fetch_themes()
    number_re = re.compile(r"[+-]?\d+(?:\.\d+)?%?")
    for t in d["themes"]:
        if t["narrative_source"] != "llm":
            continue
        narrative_nums = set(number_re.findall(t["narrative"]))
        member_ids = {m["obs_id"] for m in t["members"]}
        member_text = " ".join(
            o["text"] for o in d["observations"] if o["id"] in member_ids
        )
        member_nums = set(number_re.findall(member_text))
        # At least one narrative number should appear in member text
        assert narrative_nums & member_nums, (
            f"theme {t['id']} narrative cites {narrative_nums} "
            f"but member text has {member_nums}. Narrative: {t['narrative']!r}"
        )


def test_themes_overlap_preserved_end_to_end():
    """Seed multiple large caps so at least one lands in BOTH
    earnings_risk and near_highs clusters — same obs_id must appear
    in both themes' members lists."""
    _reset()
    for s in ("AAPL", "MSFT", "NVDA", "GOOGL", "META"):
        _seed_watch(s)
    _place_order("AAPL", 5)
    d = _fetch_themes()

    from collections import defaultdict
    memberships = defaultdict(set)
    for t in d["themes"]:
        for m in t["members"]:
            memberships[m["obs_id"]].add(t["id"])
    shared = {oid: tids for oid, tids in memberships.items() if len(tids) >= 2}
    assert shared, (
        f"no observation belongs to ≥2 themes — overlap broken at L2. "
        f"memberships: {dict(memberships)}"
    )


def test_themes_respects_min_members():
    """theme_sector_rotation has min_members=2. With an empty project
    (just baseline sector observations) we should still see it ONLY
    if we have at least 2 sector-movement obs."""
    _reset()
    d = _fetch_themes()
    for t in d["themes"]:
        # Find the signature's min_members by matching id — loaded via taxonomy
        from agent.finance.lattice.taxonomy import load_taxonomy
        sigs = {s.id: s for s in load_taxonomy().themes}
        sig = sigs.get(t["id"])
        if sig:
            assert len(t["members"]) >= sig.min_members, (
                f"theme {t['id']} shipped with {len(t['members'])} members "
                f"but min is {sig.min_members}"
            )


def test_themes_member_weights_in_range():
    _reset()
    _seed_watch("AAPL")
    _place_order("AAPL", 5)
    d = _fetch_themes()
    for t in d["themes"]:
        for m in t["members"]:
            assert 0 < m["weight"] <= 1.0, f"weight out of range: {m}"


def test_themes_severity_inherited_from_worst_member():
    """Theme severity rolls up to the most severe member."""
    _reset()
    _seed_watch("AAPL")
    _seed_watch("MSFT")
    _place_order("AAPL", 5)
    d = _fetch_themes()
    obs_by_id = {o["id"]: o for o in d["observations"]}
    severity_rank = {"alert": 0, "warn": 1, "info": 2}
    for t in d["themes"]:
        if not t["members"]:
            continue
        member_sevs = [
            severity_rank.get(obs_by_id[m["obs_id"]]["severity"], 3)
            for m in t["members"]
            if m["obs_id"] in obs_by_id
        ]
        if not member_sevs:
            continue
        expected_rank = min(member_sevs)
        actual_rank = severity_rank.get(t["severity"], 3)
        assert actual_rank == expected_rank, (
            f"theme {t['id']} severity {t['severity']} != "
            f"expected from members"
        )
