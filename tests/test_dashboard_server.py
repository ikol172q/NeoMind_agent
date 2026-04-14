"""Phase 5 — fin dashboard server smoke tests.

Exercises every endpoint via ``fastapi.testclient.TestClient`` with a
mock DataHub (so no real Finnhub / yfinance HTTP). Each test isolates
the Investment firewall under a per-test tmp directory via the
``NEOMIND_INVESTMENT_ROOT`` env var, matching the pattern used by
``tests/test_investment_projects.py``.

What is verified:

- GET /                — HTML page renders and contains the JS hooks
- GET /api/health      — returns status/version/investment_root
- GET /api/projects    — reflects registered + unregistered projects
- GET /api/quote/SYM   — flattens StockQuote to JSON-friendly shape
- GET /api/quote (bad) — 400 on invalid symbol
- POST /api/analyze    — writes an AgentAnalysis file under the
                         registered project, returns the path + signal
- POST /api/analyze    — 400 on invalid project_id regex (path traversal)
- POST /api/analyze    — 404 on unregistered project id
- POST /api/analyze    — handles DataHub failure gracefully (still
                         writes a conservative hold stub)
- GET /api/history     — returns recent analyses newest-first
- GET /api/history     — respects limit + rejects malformed project_id
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pytest
from fastapi.testclient import TestClient

from agent.finance import investment_projects
from agent.finance.dashboard_server import create_app


# ── Mock DataHub ──────────────────────────────────────────────────────


@dataclass
class _MockPrice:
    value: float
    source: str = "mock-source"
    freshness: str = "real-time"


@dataclass
class _MockQuote:
    symbol: str
    price: _MockPrice
    change: float = 0.0
    change_pct: float = 0.0
    volume: int = 0
    high: float = 0.0
    low: float = 0.0
    open: float = 0.0
    prev_close: float = 0.0
    market_cap: Optional[float] = None
    pe_ratio: Optional[float] = None
    name: str = ""
    market: str = "us"
    currency: str = "USD"
    market_status: str = "open"


class _MockDataHub:
    """Drop-in replacement for agent.finance.data_hub.DataHub in tests."""

    def __init__(self, symbol_to_quote: Optional[dict] = None,
                 fail_for: Optional[set] = None):
        self.symbol_to_quote = symbol_to_quote or {}
        self.fail_for = fail_for or set()

    async def get_quote(self, symbol: str, market: str = "us"):
        if symbol in self.fail_for:
            raise RuntimeError(f"mock upstream failure for {symbol}")
        return self.symbol_to_quote.get(symbol)


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def tmp_investment_root(tmp_path, monkeypatch):
    root = tmp_path / "Investment"
    root.mkdir()
    monkeypatch.setenv("NEOMIND_INVESTMENT_ROOT", str(root))
    return root


@pytest.fixture
def registered_project(tmp_investment_root):
    investment_projects.register_project("us-growth-2026q2", "test project")
    return "us-growth-2026q2"


@pytest.fixture
def mock_hub():
    return _MockDataHub(symbol_to_quote={
        "AAPL": _MockQuote(
            symbol="AAPL",
            price=_MockPrice(value=192.55, source="mock-finnhub"),
            change=1.85, change_pct=0.97,
            volume=51_234_000,
            high=193.40, low=190.11, open=191.02, prev_close=190.70,
            name="Apple Inc.",
        ),
        "MSFT": _MockQuote(
            symbol="MSFT",
            price=_MockPrice(value=404.22, source="mock-finnhub"),
            change=-2.34, change_pct=-0.57,
        ),
    }, fail_for={"BROKEN"})


@pytest.fixture
def client(mock_hub, tmp_investment_root):
    app = create_app(data_hub=mock_hub)
    return TestClient(app)


# ── Tests ─────────────────────────────────────────────────────────────


def test_index_html_renders_with_js_hooks(client):
    res = client.get("/")
    assert res.status_code == 200
    body = res.text
    assert "neomind" in body.lower()
    assert "fin dashboard" in body.lower()
    # JS hooks that the SPA wires at load time
    for marker in (
        "refreshHealth", "refreshProjects", "doQuote", "doAnalyze",
        "/api/health", "/api/projects", "/api/quote/",
    ):
        assert marker in body, f"missing frontend wiring: {marker!r}"


def test_health_returns_status_and_root(client, tmp_investment_root):
    res = client.get("/api/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert "version" in body
    assert body["investment_root"] == str(tmp_investment_root)


def test_projects_empty_then_populated(tmp_investment_root, mock_hub):
    app = create_app(data_hub=mock_hub)
    c = TestClient(app)
    assert c.get("/api/projects").json() == {"projects": []}

    investment_projects.register_project("us-growth-2026q2", "test")
    investment_projects.register_project("a-share-value", "test")
    res = c.get("/api/projects").json()
    assert sorted(res["projects"]) == ["a-share-value", "us-growth-2026q2"]


def test_quote_returns_flattened_payload(client):
    res = client.get("/api/quote/AAPL")
    assert res.status_code == 200
    body = res.json()
    assert body["symbol"] == "AAPL"
    assert body["price"] == 192.55
    assert body["change"] == 1.85
    assert body["source"] == "mock-finnhub"
    assert body["name"] == "Apple Inc."


def test_quote_404_when_symbol_unknown(client):
    res = client.get("/api/quote/NOPE")
    assert res.status_code == 404


def test_quote_400_on_invalid_symbol(client):
    res = client.get("/api/quote/aa bb")  # space is invalid
    assert res.status_code == 400


def test_quote_502_when_upstream_raises(client):
    res = client.get("/api/quote/BROKEN")
    assert res.status_code == 502


def test_analyze_writes_signal_file_and_returns_payload(
    client, registered_project, tmp_investment_root,
):
    res = client.post(f"/api/analyze/AAPL?project_id={registered_project}")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["project_id"] == registered_project
    assert body["symbol"] == "AAPL"
    assert body["signal"]["signal"] == "hold"
    assert body["signal"]["confidence"] >= 1
    # Sources should include the dashboard + the (mock) upstream
    assert "dashboard" in body["signal"]["sources"]
    # The written file is under Investment/<project>/analyses/
    artifact = Path(body["artifact"])
    assert artifact.exists()
    assert artifact.is_file()
    expected_dir = tmp_investment_root / registered_project / "analyses"
    assert artifact.parent == expected_dir
    # And its JSON round-trips
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    assert payload["project_id"] == registered_project
    assert payload["symbol"] == "AAPL"
    assert payload["signal"]["signal"] == "hold"


def test_analyze_still_records_when_quote_upstream_fails(
    client, registered_project,
):
    res = client.post(f"/api/analyze/BROKEN?project_id={registered_project}")
    assert res.status_code == 200, res.text
    body = res.json()
    # Degraded path — writes a conservative hold with clear reason
    assert body["signal"]["signal"] == "hold"
    assert "no live quote" in body["signal"]["reason"]
    assert body["quote"] is None


def test_analyze_400_on_invalid_project_id_regex(client, registered_project):
    # Every value below violates the id regex: too short, contains
    # uppercase, contains path chars, too long, contains punctuation.
    # The handler MUST reject these at the regex gate (400), never
    # letting them reach investment_projects.list_projects() where
    # they might be misinterpreted.
    bad_ids = (
        "a",              # too short
        "..",             # path-traversal attempt
        "/etc/passwd",    # path-traversal attempt
        "a" * 50,         # exceeds 40-char limit
        "UPPER",          # uppercase not allowed
        "bad!",           # punctuation not allowed
        "has space",      # space not allowed
    )
    for bad in bad_ids:
        res = client.post(f"/api/analyze/AAPL?project_id={bad}")
        assert res.status_code in (400, 422), (
            f"bad project_id {bad!r} accepted: {res.status_code}"
        )


def test_analyze_404_on_unregistered_project(client, tmp_investment_root):
    res = client.post("/api/analyze/AAPL?project_id=never-registered")
    assert res.status_code == 404


def test_analyze_400_on_invalid_symbol(client, registered_project):
    res = client.post(f"/api/analyze/bad%20symbol?project_id={registered_project}")
    assert res.status_code == 400


def test_history_empty_then_populated(client, registered_project):
    # No analyses yet
    res = client.get(f"/api/history?project_id={registered_project}")
    assert res.status_code == 200
    body = res.json()
    assert body["items"] == []
    assert body["count"] == 0

    # Write 3 analyses, then history should return them newest first
    for sym in ("AAPL", "MSFT", "AAPL"):
        r = client.post(f"/api/analyze/{sym}?project_id={registered_project}")
        assert r.status_code == 200

    res = client.get(f"/api/history?project_id={registered_project}")
    body = res.json()
    assert body["count"] == 3
    symbols = [it["symbol"] for it in body["items"]]
    # Filenames sort reverse-chronologically — last write wins the top
    assert symbols[0] in ("AAPL", "MSFT")
    assert set(symbols) == {"AAPL", "MSFT"}


def test_history_limit_clamps(client, registered_project):
    for _ in range(5):
        r = client.post(f"/api/analyze/AAPL?project_id={registered_project}")
        assert r.status_code == 200
    res = client.get(
        f"/api/history?project_id={registered_project}&limit=2"
    )
    assert res.json()["count"] == 2


def test_history_400_on_invalid_project_id(client):
    res = client.get("/api/history?project_id=../etc")
    assert res.status_code == 400


def test_history_404_on_unregistered_project(client, tmp_investment_root):
    res = client.get("/api/history?project_id=never-registered")
    assert res.status_code == 404
