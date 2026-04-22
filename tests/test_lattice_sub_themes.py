"""D6 · n=4 sub-theme layer — tests for the configurable middle
layer between L1 observations and L2 themes.

Gate: flipping a `sub_themes:` block in lattice_taxonomy.yaml must
produce an extra layer in the pipeline + endpoint with zero code
changes. These tests drive a temporary YAML through the loader to
validate that.
"""
from __future__ import annotations

import json
import textwrap
import urllib.request
from pathlib import Path

import pytest

BASE_URL = "http://127.0.0.1:8001/"
PROJECT = "fin-core"


# ── Unit ───────────────────────────────────────────────

def test_taxonomy_loads_sub_themes_from_real_yaml():
    """The shipped taxonomy declares sub_themes; the loader must
    expose them on the Taxonomy dataclass."""
    from agent.finance.lattice.taxonomy import load_taxonomy
    t = load_taxonomy()
    assert len(t.sub_themes) >= 1, "shipped taxonomy should declare ≥1 sub_theme"
    for st in t.sub_themes:
        # Every sub-theme must have a non-empty signature
        assert st.any_of or st.all_of, f"sub_theme {st.id!r} has empty signature"


def test_taxonomy_without_sub_themes_defaults_to_empty(tmp_path):
    """Dropping the sub_themes block from YAML must degrade gracefully
    back to n=3 behaviour — empty list, pipeline unchanged."""
    from agent.finance.lattice.taxonomy import load_taxonomy
    yaml_body = textwrap.dedent("""
        version: 1
        dimensions:
          symbol:
            description: "x"
          market:
            valid_values: [US]
          risk:
            valid_values: [earnings]
        themes:
          - id: t_x
            title: "T"
            signature:
              any_of: ["risk:earnings"]
            min_members: 1
    """).strip()
    p = tmp_path / "tax.yaml"
    p.write_text(yaml_body, encoding="utf-8")
    t = load_taxonomy(path=p)
    assert t.sub_themes == [], "missing sub_themes block should produce empty list"
    assert len(t.themes) == 1


def test_taxonomy_loads_sub_themes_from_custom_yaml(tmp_path):
    """Adding a sub_themes block with ONE signature should produce
    one ThemeSignature in Taxonomy.sub_themes. This is the D6 gate —
    YAML switch with zero code changes."""
    from agent.finance.lattice.taxonomy import load_taxonomy
    yaml_body = textwrap.dedent("""
        version: 1
        dimensions:
          symbol:
            description: "x"
          market:
            valid_values: [US]
          risk:
            valid_values: [earnings]
          timescale:
            valid_values: [short]
        themes:
          - id: t_x
            title: "T"
            signature:
              any_of: ["risk:earnings"]
        sub_themes:
          - id: st_event
            title: "Event risk"
            signature:
              any_of: ["risk:earnings"]
              all_of: ["timescale:short"]
            min_members: 1
    """).strip()
    p = tmp_path / "tax.yaml"
    p.write_text(yaml_body, encoding="utf-8")
    t = load_taxonomy(path=p)
    assert len(t.sub_themes) == 1
    st = t.sub_themes[0]
    assert st.id == "st_event"
    assert st.any_of == frozenset({"risk:earnings"})
    assert st.all_of == frozenset({"timescale:short"})


def test_cluster_observations_applied_to_sub_themes_preserves_overlap():
    """Same observation can land in a sub_theme AND a theme — same
    soft-membership rule as L2. This is the non-negotiable."""
    from agent.finance.lattice.themes import cluster_observations
    from agent.finance.lattice.observations import Observation
    from agent.finance.lattice.taxonomy import ThemeSignature

    theme_sig = ThemeSignature(
        id="t_earnings", title="Earnings",
        any_of=frozenset({"risk:earnings"}),
    )
    subtheme_sig = ThemeSignature(
        id="st_event", title="Event",
        any_of=frozenset({"risk:earnings"}),
        all_of=frozenset({"timescale:short"}),
    )
    obs = [
        Observation(
            id="o1", kind="earnings_soon",
            text="AAPL reports in 3d.",
            tags=["symbol:AAPL", "risk:earnings", "timescale:short"],
        ),
    ]
    theme_clusters = cluster_observations(obs, [theme_sig])
    sub_clusters = cluster_observations(obs, [subtheme_sig])
    assert len(theme_clusters) == 1
    assert len(sub_clusters) == 1
    assert theme_clusters[0]["members"][0][0].id == "o1"
    assert sub_clusters[0]["members"][0][0].id == "o1"


# ── End-to-end ─────────────────────────────────────────

def _backend_up() -> bool:
    try:
        with urllib.request.urlopen(BASE_URL + "api/health", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


@pytest.fixture(scope="module", autouse=True)
def _skip_if_no_backend():
    if not _backend_up():
        pytest.skip(f"backend not reachable at {BASE_URL}")


def test_calls_endpoint_includes_sub_themes_field():
    """The /api/lattice/calls payload must surface `sub_themes` so
    the frontend DigestView can render the L1.5 section."""
    url = BASE_URL + f"api/lattice/calls?project_id={PROJECT}"
    with urllib.request.urlopen(url, timeout=300) as r:
        d = json.loads(r.read())
    assert "sub_themes" in d, "payload missing sub_themes key"
    assert isinstance(d["sub_themes"], list)


def test_sub_themes_obey_standard_theme_invariants():
    """Each sub_theme must have: id, title, members[], severity."""
    url = BASE_URL + f"api/lattice/calls?project_id={PROJECT}"
    with urllib.request.urlopen(url, timeout=300) as r:
        d = json.loads(r.read())
    required = {"id", "title", "members", "severity"}
    for st in d.get("sub_themes", []):
        assert required.issubset(st.keys()), f"sub_theme missing fields: {st}"
        assert isinstance(st["members"], list)
        for m in st["members"]:
            assert "obs_id" in m and "weight" in m


def test_sub_themes_members_reference_real_observations():
    """A sub_theme's obs_ids must all exist in the observations list
    — no orphan references."""
    url = BASE_URL + f"api/lattice/calls?project_id={PROJECT}"
    with urllib.request.urlopen(url, timeout=300) as r:
        d = json.loads(r.read())
    obs_ids = {o["id"] for o in d["observations"]}
    for st in d.get("sub_themes", []):
        for m in st["members"]:
            assert m["obs_id"] in obs_ids, (
                f"sub_theme {st['id']} references phantom obs {m['obs_id']}"
            )
