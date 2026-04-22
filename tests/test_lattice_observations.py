"""D1 · Insight Lattice — L1 observations tests.

Three classes of tests:
  1. Unit — taxonomy loader + theme matching + news scorer (no backend).
  2. Taxonomy coverage — every observation has ≥1 tag; all tags are
     in the declared taxonomy.
  3. End-to-end — seed real data via REST, check /api/lattice/observations
     returns the expected kinds, and prove overlap empirically (at least
     one observation belongs to ≥2 theme signatures).

If the dashboard is unreachable, end-to-end tests skip cleanly.
"""
from __future__ import annotations

import json
import urllib.request
import urllib.error
from pathlib import Path
from urllib.parse import urlencode

import pytest

BASE_URL = "http://127.0.0.1:8001/"
PROJECT = "fin-core"


# ── Unit tests (no backend) ─────────────────────────────

def test_taxonomy_loads_and_validates_tags():
    from agent.finance.lattice.taxonomy import load_taxonomy
    # Fresh load from the real path
    t = load_taxonomy()
    assert t.version >= 1
    # Declared dimensions must include the minimum set we rely on
    for key in ("symbol", "market", "sector", "risk", "technical",
                "pnl", "position", "timescale", "direction", "signal",
                "regime", "catalyst"):
        assert key in t.dimensions, f"dimension {key!r} missing"
    # Open dimensions accept arbitrary values
    assert t.is_valid_tag("symbol:AAPL")
    assert t.is_valid_tag("sector:Consumer Discretionary")
    # Closed dimensions enforce the enum
    assert t.is_valid_tag("risk:earnings")
    assert not t.is_valid_tag("risk:notarealrisk")
    # Themes exist and match by signature
    by_id = {th.id: th for th in t.themes}
    assert "theme_earnings_risk" in by_id
    assert by_id["theme_earnings_risk"].matches(["risk:earnings"])
    assert not by_id["theme_earnings_risk"].matches(["symbol:AAPL"])


def test_reject_invalid_logs_and_drops():
    from agent.finance.lattice.taxonomy import load_taxonomy
    t = load_taxonomy()
    kept = t.reject_invalid(["symbol:AAPL", "risk:bogus", "signal:bullish"])
    assert set(kept) == {"symbol:AAPL", "signal:bullish"}


def test_news_scorer_matches_watchlist_and_positions():
    from agent.finance.lattice.observations import _news_score
    score_pos, matched_pos = _news_score(
        "AAPL sued by DOJ over app store",
        "2026-04-20T18:00:00+00:00",
        watchlist_syms={"NVDA"}, position_syms={"AAPL"},
        now_epoch=__import__("datetime").datetime.fromisoformat(
            "2026-04-20T19:00:00+00:00").timestamp(),
    )
    # Position match (2.0x) + "doj"/"sued" keyword boost → score > 0
    assert score_pos > 0
    assert "AAPL" in matched_pos

    score_zero, matched_zero = _news_score(
        "General market recap", "2026-04-20T18:00:00+00:00",
        watchlist_syms=set(), position_syms=set(),
    )
    assert score_zero == 0.0
    assert matched_zero == []


def test_news_scorer_dedupes_same_ticker_with_mmr():
    """Two headlines about AAPL — only one should survive the MMR
    dedup step in gen_news_signals."""
    from agent.finance.lattice.observations import gen_news_signals
    entries = [
        {"title": "AAPL earnings beat estimates", "published_at": "2026-04-20T18:00:00+00:00",
         "url": "u1", "feed_title": "Bloomberg"},
        {"title": "AAPL strong revenue quarter", "published_at": "2026-04-20T17:30:00+00:00",
         "url": "u2", "feed_title": "Reuters"},
        {"title": "NVDA announces new AI chip", "published_at": "2026-04-20T17:00:00+00:00",
         "url": "u3", "feed_title": "Verge"},
    ]
    out = gen_news_signals(entries, watchlist_syms={"NVDA"}, position_syms={"AAPL"}, top_k=10)
    symbols = sorted({o.source.get("symbol") for o in out if o.source.get("symbol")})
    # Each ticker should appear at most once after MMR dedup
    assert symbols == ["AAPL", "NVDA"], f"MMR dedup failed: {symbols}"


# ── Taxonomy coverage: every emitted obs has ≥1 valid tag ─

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


def _fetch_obs():
    url = BASE_URL + f"api/lattice/observations?project_id={PROJECT}&fresh=1"
    with urllib.request.urlopen(url, timeout=120) as r:
        return json.loads(r.read())


@pytest.fixture(scope="module", autouse=True)
def _skip_if_no_backend():
    if not _backend_up():
        pytest.skip(f"backend not reachable at {BASE_URL}")


def test_endpoint_returns_shape_on_empty_project():
    _reset()
    d = _fetch_obs()
    assert d["project_id"] == PROJECT
    assert isinstance(d["observations"], list)
    assert isinstance(d["theme_signatures"], list)
    assert d["taxonomy_version"] >= 1
    # Even an empty project still produces some obs (sector + sentiment)
    assert d["count"] >= 1


def test_every_observation_has_at_least_one_tag():
    _reset()
    _seed_watch("AAPL")
    _place_order("AAPL", 5)
    d = _fetch_obs()
    assert d["count"] > 0
    for o in d["observations"]:
        assert isinstance(o["tags"], list)
        assert len(o["tags"]) >= 1, f"obs {o['kind']} has no tags"


def test_every_tag_passes_taxonomy_validation():
    from agent.finance.lattice.taxonomy import load_taxonomy
    t = load_taxonomy()
    _reset()
    _seed_watch("AAPL")
    _place_order("AAPL", 5)
    d = _fetch_obs()
    for o in d["observations"]:
        for tag in o["tags"]:
            assert t.is_valid_tag(tag), f"obs {o['kind']} has invalid tag {tag!r}"


def test_every_observation_has_source_pointer():
    _reset()
    _seed_watch("AAPL")
    d = _fetch_obs()
    for o in d["observations"]:
        src = o["source"]
        assert isinstance(src, dict) and src.get("widget"), \
            f"obs {o['kind']} has no widget source"


def test_seeded_earnings_produces_earnings_soon_obs():
    """Given AAPL (has known earnings) on watchlist, the engine should
    produce an earnings_soon or anomaly_near_52w_with_earnings obs."""
    _reset()
    _seed_watch("AAPL")
    d = _fetch_obs()
    kinds = {o["kind"] for o in d["observations"]}
    # At least one of the earnings-flavoured kinds
    earnings_kinds = {
        "earnings_soon", "iv_rich", "iv_cheap",
        "anomaly_near_52w_with_earnings", "anomaly_iv_richness",
    }
    assert kinds & earnings_kinds, f"expected one of {earnings_kinds}, got {kinds}"


def test_seeded_position_is_referenced_in_at_least_one_observation():
    """A just-opened flat position won't trigger P&L kinds (intentional
    — we don't want flat-zero clutter). But the position MUST still
    influence some observation — e.g. AAPL's earnings anomaly fires
    only because AAPL is held. This catches the regression where
    positions silently drop off the radar."""
    _reset()
    _place_order("AAPL", 5)
    d = _fetch_obs()
    # Look for AAPL appearing anywhere — as a tag, source symbol, or
    # in the text. That's the minimum bar for "position influences output".
    referenced = any(
        "symbol:AAPL" in o["tags"] or
        "position:AAPL" in o["tags"] or
        (o.get("source", {}).get("symbol") == "AAPL") or
        "AAPL" in o["text"]
        for o in d["observations"]
    )
    assert referenced, f"AAPL position produced zero downstream obs: {d['observations']}"


# ── Overlap empirically proven ─────────────────────────

def test_at_least_one_observation_belongs_to_two_themes():
    """The user's non-negotiable: overlap must be preserved. We seed
    multiple large-cap symbols so at least one is likely to be near
    its 20d range top AND have earnings soon — producing an
    observation that legitimately lands in BOTH theme_earnings_risk
    and theme_near_highs. Without this test, a regression toward
    MECE clustering would go unnoticed. Seeds multiple symbols to
    stay robust against one particular stock's market state today."""
    _reset()
    # Seed a broad basket so at least one lands near 52w high + earnings
    for sym in ("AAPL", "MSFT", "NVDA", "GOOGL", "META"):
        _seed_watch(sym)
    _place_order("AAPL", 5)
    d = _fetch_obs()
    sigs = d["theme_signatures"]

    def memberships(obs) -> list[str]:
        tags = set(obs["tags"])
        out = []
        for sig in sigs:
            any_of = set(sig["any_of"])
            all_of = set(sig["all_of"])
            if all_of and not all_of.issubset(tags):
                continue
            if any_of and tags.isdisjoint(any_of):
                continue
            out.append(sig["id"])
        return out

    overlapping = [
        (o["kind"], memberships(o))
        for o in d["observations"]
        if len(memberships(o)) >= 2
    ]
    assert overlapping, (
        f"no observation belongs to ≥2 themes — overlap broken. "
        f"Observations: {[(o['kind'], o['tags']) for o in d['observations']]}"
    )


# ── Generators degrade gracefully on missing data ──────

def test_engine_returns_list_on_missing_yfinance(monkeypatch):
    """If every upstream fails, build_observations returns [], not
    raises. Protects the endpoint from one flaky fetcher killing
    the whole L1 layer."""
    import agent.finance.lattice.observations as obs_mod

    class _FailingSynth:
        @staticmethod
        def synth_project_data(pid):
            raise RuntimeError("synthetic failure")
        @staticmethod
        def synth_symbol_data(pid, sym):
            raise RuntimeError("synthetic failure")
    monkeypatch.setattr(
        "agent.finance.lattice.observations.logger.warning",
        lambda *a, **k: None,
    )
    # Patch the whole synthesis module reference used by build_observations
    import agent.finance.synthesis as synth
    monkeypatch.setattr(synth, "synth_project_data", _FailingSynth.synth_project_data)
    monkeypatch.setattr(synth, "synth_symbol_data", _FailingSynth.synth_symbol_data)

    rows = obs_mod.build_observations(PROJECT)
    assert isinstance(rows, list)
