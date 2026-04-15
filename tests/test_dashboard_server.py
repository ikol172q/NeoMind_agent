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
                 fail_for: Optional[set] = None,
                 symbol_to_history: Optional[dict] = None):
        self.symbol_to_quote = symbol_to_quote or {}
        self.fail_for = fail_for or set()
        self.symbol_to_history = symbol_to_history or {}

    async def get_quote(self, symbol: str, market: str = "us"):
        if symbol in self.fail_for:
            raise RuntimeError(f"mock upstream failure for {symbol}")
        return self.symbol_to_quote.get(symbol)

    async def get_history(self, symbol: str, period: str = "3mo",
                          interval: str = "1d"):
        if symbol in self.fail_for:
            raise RuntimeError(f"mock upstream failure for {symbol}")
        return self.symbol_to_history.get(symbol)


def _synthetic_bars(n: int = 60, start_price: float = 100.0) -> list:
    """Generate n daily OHLCV bars with a simple sine-wave pattern so
    indicators (SMA/EMA/RSI/MACD/BB/ATR) produce meaningful values."""
    import math
    bars = []
    base = start_price
    for i in range(n):
        # Sine wave with amplitude 5 and some drift
        close = base + 5 * math.sin(i / 6.0) + i * 0.1
        high = close + 1.5
        low = close - 1.2
        open_ = close - 0.5
        bars.append({
            "date": f"2026-02-{(i % 28) + 1:02d}T00:00:00",
            "open": open_, "high": high, "low": low, "close": close,
            "volume": 1_000_000 + i * 10_000,
        })
    return bars


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
    return _MockDataHub(symbol_to_history={
        "AAPL": _synthetic_bars(60),
        "MSFT": _synthetic_bars(60, start_price=400.0),
    }, symbol_to_quote={
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


# ── Phase 5.6 — paper trading endpoints ──────────────────────────


@pytest.fixture
def tmp_paper_engine(registered_project, tmp_investment_root):
    """Fresh PaperTradingEngine whose data_dir is under the tmp
    investment root, so each test gets an isolated account."""
    from agent.finance.paper_trading import PaperTradingEngine
    data_dir = tmp_investment_root / registered_project / "paper_trading"
    data_dir.mkdir(parents=True)
    return PaperTradingEngine(initial_capital=100_000.0, data_dir=data_dir)


@pytest.fixture
def paper_client(mock_hub, registered_project, tmp_paper_engine):
    """Dashboard client wired to the shared tmp_paper_engine so test
    assertions can cross-check state between HTTP calls and the
    engine instance directly."""
    def factory(project_id: str):
        assert project_id == registered_project
        return tmp_paper_engine
    app = create_app(data_hub=mock_hub, paper_engine_factory=factory)
    return TestClient(app), tmp_paper_engine, registered_project


def test_paper_account_starts_empty(paper_client):
    client, _engine, pid = paper_client
    res = client.get(f"/api/paper/account?project_id={pid}")
    assert res.status_code == 200
    body = res.json()
    assert body["initial_capital"] == 100_000.0
    assert body["cash"] == 100_000.0
    assert body["equity"] == 100_000.0
    assert body["total_trades"] == 0
    assert body["positions"] == 0


def test_paper_positions_empty_initially(paper_client):
    client, _engine, pid = paper_client
    res = client.get(f"/api/paper/positions?project_id={pid}")
    assert res.status_code == 200
    assert res.json()["positions"] == []


def test_paper_place_market_buy_then_account_reflects_position(paper_client):
    client, engine, pid = paper_client
    res = client.post(
        f"/api/paper/order?project_id={pid}"
        f"&symbol=AAPL&side=buy&quantity=10&order_type=market"
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["order"]["status"] == "filled"
    assert body["order"]["symbol"] == "AAPL"
    assert body["order"]["filled_quantity"] == 10

    # Positions endpoint now reflects the fill
    pos_res = client.get(f"/api/paper/positions?project_id={pid}")
    positions = pos_res.json()["positions"]
    assert len(positions) == 1
    assert positions[0]["symbol"] == "AAPL"
    assert positions[0]["quantity"] == 10

    # Account endpoint shows reduced cash. Note: paper_trading's
    # `total_trades` counter only increments on SELL that closes a
    # position (it counts round-trips, not individual fills), so a
    # standalone BUY leaves it at 0.
    acct = client.get(f"/api/paper/account?project_id={pid}").json()
    assert acct["cash"] < 100_000.0  # 10 * ~$192 mock price + commission
    assert acct["positions"] == 1


def test_paper_place_order_rejects_invalid_symbol(paper_client):
    client, _engine, pid = paper_client
    res = client.post(
        f"/api/paper/order?project_id={pid}"
        f"&symbol=bad%20sym&side=buy&quantity=1&order_type=market"
    )
    assert res.status_code == 400


def test_paper_place_order_rejects_invalid_side(paper_client):
    client, _engine, pid = paper_client
    res = client.post(
        f"/api/paper/order?project_id={pid}"
        f"&symbol=AAPL&side=nope&quantity=1&order_type=market"
    )
    assert res.status_code == 400


def test_paper_place_order_502_when_no_quote_available(paper_client):
    client, _engine, pid = paper_client
    # BROKEN is in the mock_hub's fail_for set
    res = client.post(
        f"/api/paper/order?project_id={pid}"
        f"&symbol=BROKEN&side=buy&quantity=1&order_type=market"
    )
    assert res.status_code == 502


def test_paper_refresh_updates_positions_prices(paper_client):
    client, engine, pid = paper_client
    # Establish a position first
    client.post(
        f"/api/paper/order?project_id={pid}"
        f"&symbol=AAPL&side=buy&quantity=5&order_type=market"
    )
    # Now call refresh — should re-fetch AAPL quote via mock hub
    res = client.post(f"/api/paper/refresh?project_id={pid}")
    assert res.status_code == 200
    body = res.json()
    updated_symbols = [u["symbol"] for u in body["updated"]]
    assert "AAPL" in updated_symbols


def test_paper_trades_returns_recent_fills(paper_client):
    client, _engine, pid = paper_client
    client.post(
        f"/api/paper/order?project_id={pid}"
        f"&symbol=AAPL&side=buy&quantity=3&order_type=market"
    )
    client.post(
        f"/api/paper/order?project_id={pid}"
        f"&symbol=MSFT&side=buy&quantity=2&order_type=market"
    )
    res = client.get(f"/api/paper/trades?project_id={pid}&limit=10")
    trades = res.json()["trades"]
    assert len(trades) == 2
    symbols = {t["symbol"] for t in trades}
    assert symbols == {"AAPL", "MSFT"}


def test_paper_reset_requires_confirm(paper_client):
    client, _engine, pid = paper_client
    res = client.post(f"/api/paper/reset?project_id={pid}")
    assert res.status_code == 400
    assert "confirm" in res.json()["detail"].lower()


def test_paper_reset_clears_account(paper_client):
    client, _engine, pid = paper_client
    client.post(
        f"/api/paper/order?project_id={pid}"
        f"&symbol=AAPL&side=buy&quantity=4&order_type=market"
    )
    # Confirm the position opened (cash dropped, positions count = 1)
    pre = client.get(f"/api/paper/account?project_id={pid}").json()
    assert pre["cash"] < 100_000.0
    assert pre["positions"] == 1

    # Now reset with confirm
    res = client.post(f"/api/paper/reset?project_id={pid}&confirm=yes")
    assert res.status_code == 200
    # Account back to clean
    a = client.get(f"/api/paper/account?project_id={pid}").json()
    assert a["cash"] == 100_000.0
    assert a["positions"] == 0
    assert client.get(f"/api/paper/positions?project_id={pid}").json()["positions"] == []


def test_paper_account_400_on_invalid_project_id(paper_client):
    client, _engine, _pid = paper_client
    res = client.get("/api/paper/account?project_id=../etc")
    assert res.status_code == 400


def test_paper_account_404_on_unregistered_project(paper_client):
    client, _engine, _pid = paper_client
    res = client.get("/api/paper/account?project_id=never-registered")
    assert res.status_code == 404


# ── Phase 5.7 — chart + technical indicators ─────────────────────


def test_chart_returns_bars_and_default_indicators(client):
    res = client.get("/api/chart/AAPL?period=3mo&interval=1d")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["symbol"] == "AAPL"
    assert body["period"] == "3mo"
    assert body["interval"] == "1d"
    assert len(body["bars"]) == 60
    # Default indicator set: sma20, ema20, rsi, macd, bb
    assert "sma20" in body["indicators"]
    assert "ema20" in body["indicators"]
    assert "rsi" in body["indicators"]
    assert "macd" in body["indicators"]
    assert "bb" in body["indicators"]
    # MACD structure is nested
    assert set(body["indicators"]["macd"]) == {"line", "signal", "histogram"}
    # BB structure is nested
    assert set(body["indicators"]["bb"]) == {"upper", "middle", "lower"}


def test_chart_honours_explicit_indicator_set(client):
    res = client.get(
        "/api/chart/AAPL?period=3mo&interval=1d&indicators=sma50,ema50,atr"
    )
    body = res.json()
    assert set(body["indicators"]) == {"sma50", "ema50", "atr"}
    # atr is a flat list aligned with bars
    assert len(body["indicators"]["atr"]) == len(body["bars"])


def test_chart_computes_rsi_within_0_100_range(client):
    res = client.get("/api/chart/AAPL?period=3mo&interval=1d&indicators=rsi")
    rsi = res.json()["indicators"]["rsi"]
    # Skip None values (warmup period) and verify the rest are in [0, 100]
    for v in rsi:
        if v is not None:
            assert 0.0 <= v <= 100.0


def test_chart_400_on_invalid_period(client):
    res = client.get("/api/chart/AAPL?period=bogus")
    assert res.status_code == 400


def test_chart_400_on_invalid_interval(client):
    res = client.get("/api/chart/AAPL?period=3mo&interval=5s")
    assert res.status_code == 400


def test_chart_400_on_unknown_indicator(client):
    res = client.get(
        "/api/chart/AAPL?period=3mo&indicators=rsi,bogus_ind"
    )
    assert res.status_code == 400
    assert "bogus_ind" in res.json()["detail"]


def test_chart_400_on_invalid_symbol(client):
    res = client.get("/api/chart/bad%20sym?period=3mo")
    assert res.status_code == 400


def test_chart_404_when_no_history_data(client):
    res = client.get("/api/chart/NOPE?period=3mo")
    assert res.status_code == 404


def test_chart_502_when_upstream_raises(client):
    res = client.get("/api/chart/BROKEN?period=3mo")
    assert res.status_code == 502


def test_index_html_includes_lightweight_charts_cdn(client):
    body = client.get("/").text
    assert "lightweight-charts" in body
    assert "price-chart" in body
    assert "rsi-chart" in body
    assert "macd-chart" in body


# ── Phase 5.8 — fleet-dispatched async analyze ───────────────────


class _MockFleetBackend:
    """Drop-in for FleetBackend that returns deterministic task_ids
    and lets tests flip a task between pending/completed/failed."""

    def __init__(self):
        self._tasks: dict = {}
        self._next_id = 0
        self.session = object()  # non-None sentinel

    def session_or_none(self):
        return self.session

    async def ensure_started(self):
        return self.session

    async def dispatch_analysis(self, symbol: str, project_id: str) -> str:
        self._next_id += 1
        tid = f"mock-task-{self._next_id:04d}"
        self._tasks[tid] = {
            "task_id": tid,
            "symbol": symbol,
            "project_id": project_id,
            "member": "fin-rt",
            "created_at": "2026-04-14T00:00:00+00:00",
            "status": "pending",
        }
        return tid

    def get_task_status(self, task_id: str) -> dict:
        from fastapi import HTTPException
        if task_id not in self._tasks:
            raise HTTPException(404, f"unknown task_id {task_id!r}")
        return dict(self._tasks[task_id])

    def complete(self, task_id: str, signal_dict: dict) -> None:
        self._tasks[task_id].update({
            "status": "completed",
            "signal": signal_dict,
            "reply": "mock reply",
        })

    def fail(self, task_id: str, error: str) -> None:
        self._tasks[task_id].update({
            "status": "failed",
            "error": error,
        })

    async def shutdown(self):
        pass


@pytest.fixture
def fleet_client(mock_hub, registered_project):
    backend = _MockFleetBackend()
    app = create_app(data_hub=mock_hub, fleet_backend=backend)
    return TestClient(app), backend, registered_project


def test_analyze_use_fleet_returns_task_id(fleet_client):
    client, backend, pid = fleet_client
    res = client.post(f"/api/analyze/AAPL?project_id={pid}&use_fleet=true")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["use_fleet"] is True
    assert body["status"] == "pending"
    assert body["task_id"].startswith("mock-task-")
    assert body["symbol"] == "AAPL"


def test_task_status_endpoint_returns_pending_then_completed(fleet_client):
    client, backend, pid = fleet_client
    # Dispatch
    dispatch = client.post(
        f"/api/analyze/MSFT?project_id={pid}&use_fleet=true"
    ).json()
    tid = dispatch["task_id"]

    # Poll 1 — still pending
    r1 = client.get(f"/api/tasks/{tid}")
    assert r1.status_code == 200
    assert r1.json()["status"] == "pending"

    # Mark completed via the mock backend
    backend.complete(tid, {
        "signal": "buy", "confidence": 7, "reason": "mock",
        "risk_level": "medium", "sources": ["mock"],
    })

    # Poll 2 — completed with signal
    r2 = client.get(f"/api/tasks/{tid}").json()
    assert r2["status"] == "completed"
    assert r2["signal"]["signal"] == "buy"
    assert r2["signal"]["confidence"] == 7


def test_task_status_returns_failed_with_error(fleet_client):
    client, backend, pid = fleet_client
    tid = client.post(
        f"/api/analyze/AAPL?project_id={pid}&use_fleet=true"
    ).json()["task_id"]

    backend.fail(tid, "LLM upstream timeout")
    r = client.get(f"/api/tasks/{tid}").json()
    assert r["status"] == "failed"
    assert "timeout" in r["error"]


def test_task_status_404_on_unknown_task_id(fleet_client):
    client, _backend, _pid = fleet_client
    res = client.get("/api/tasks/never-dispatched-xyz")
    assert res.status_code == 404


def test_analyze_sync_path_unchanged_when_use_fleet_false(
    fleet_client,
):
    """Backward compat: use_fleet=false (the default) still hits the
    synchronous DataHub + write_analysis path and returns the
    artifact + signal fields, NOT a task_id."""
    client, _backend, pid = fleet_client
    res = client.post(f"/api/analyze/AAPL?project_id={pid}")
    assert res.status_code == 200
    body = res.json()
    assert "task_id" not in body
    assert "artifact" in body
    assert body["signal"]["signal"] == "hold"  # MVP stub


def test_analyze_use_fleet_still_validates_project_id(fleet_client):
    client, _backend, _pid = fleet_client
    res = client.post("/api/analyze/AAPL?project_id=../etc&use_fleet=true")
    assert res.status_code == 400


def test_analyze_use_fleet_still_validates_symbol(fleet_client):
    client, _backend, pid = fleet_client
    res = client.post(
        f"/api/analyze/bad%20sym?project_id={pid}&use_fleet=true"
    )
    assert res.status_code == 400


def test_index_html_has_use_fleet_checkbox(client):
    body = client.get("/").text
    assert "use-fleet" in body
    assert "fleet (real LLM)" in body
    assert "pollTask" in body
