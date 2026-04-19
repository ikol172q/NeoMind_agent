"""Tests for agent.finance.openbb_adapter — verifies every widget
endpoint returns a shape OpenBB Workspace can render, widgets.json is
well-formed, CORS is attached, and the agent /query SSE stream
produces the expected events.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.finance import investment_projects, openbb_adapter


# ── Shared mocks (mirrors test_dashboard_server.py style) ────────


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


class _MockHub:
    def __init__(self, symbol_to_quote=None, symbol_to_history=None):
        self.symbol_to_quote = symbol_to_quote or {}
        self.symbol_to_history = symbol_to_history or {}

    async def get_quote(self, symbol, market="us"):
        return self.symbol_to_quote.get(symbol)

    async def get_history(self, symbol, period="3mo", interval="1d"):
        return self.symbol_to_history.get(symbol)


def _bars(n=60, start=100.0):
    import math
    out = []
    for i in range(n):
        close = start + 5 * math.sin(i / 6.0) + i * 0.1
        out.append({
            "date": f"2026-02-{(i % 28) + 1:02d}T00:00:00",
            "open": close - 0.5, "high": close + 1.5,
            "low": close - 1.2, "close": close,
            "volume": 1_000_000 + i * 10_000,
        })
    return out


@pytest.fixture
def tmp_investment_root(tmp_path, monkeypatch):
    root = tmp_path / "Investment"
    root.mkdir()
    monkeypatch.setenv("NEOMIND_INVESTMENT_ROOT", str(root))
    return root


@pytest.fixture
def registered_project(tmp_investment_root):
    pid = "fin-core"
    investment_projects.register_project(pid, "test project")
    return pid


@pytest.fixture
def mock_engine_factory():
    def factory(project_id: str):
        eng = MagicMock()
        eng.get_account_summary.return_value = {
            "cash": 95_000.0, "equity": 103_500.0,
            "total_pnl": 3_500.0, "total_pnl_pct": 3.5,
            "realized_pnl": 1_000.0, "unrealized_pnl": 2_500.0,
            "total_trades": 7, "win_rate": 57.0,
        }
        # Fake position
        pos = MagicMock()
        pos.symbol = "AAPL"
        pos.side = MagicMock(value="long")
        pos.quantity = 10
        pos.entry_price = 180.0
        pos.current_price = 192.5
        pos.unrealized_pnl = 125.0
        pos.unrealized_pnl_pct = 6.94
        pos.opened_at = datetime(2026, 4, 1, tzinfo=timezone.utc)
        eng.get_all_positions.return_value = [pos]
        # Fake trade
        tr = MagicMock()
        tr.timestamp = datetime(2026, 4, 10, 14, 0, tzinfo=timezone.utc)
        tr.symbol = "AAPL"
        tr.side = MagicMock(value="buy")
        tr.quantity = 10
        tr.price = 180.0
        tr.commission = 1.0
        tr.pnl = 0.0
        eng.get_trade_history.return_value = [tr]
        return eng
    return factory


@pytest.fixture
def mock_fleet():
    fleet = MagicMock()
    fleet.member = "fin-rt"
    fleet.dispatch_chat = AsyncMock(return_value="task_test_001")

    # Cycle: first poll pending, next completed
    _calls = {"n": 0}

    def get_task_status(task_id):
        _calls["n"] += 1
        if _calls["n"] < 2:
            return {"status": "pending", "task_id": task_id}
        return {
            "status": "completed", "task_id": task_id,
            "reply": "这是测试回复。",
        }
    fleet.get_task_status = get_task_status
    return fleet


@pytest.fixture
def client(mock_engine_factory, mock_fleet, tmp_investment_root):
    hub = _MockHub(
        symbol_to_quote={
            "AAPL": _MockQuote(
                symbol="AAPL",
                price=_MockPrice(value=192.55, source="mock-finnhub"),
                change=1.85, change_pct=0.97,
                volume=51_234_000, high=193.40, low=190.11,
                name="Apple Inc.",
            ),
        },
        symbol_to_history={"AAPL": _bars(60)},
    )

    def list_recent(project_id, limit):
        return [
            {
                "written_at": "2026-04-19T14:00:00Z",
                "symbol": "AAPL",
                "signal": {
                    "signal": "hold", "confidence": 3,
                    "reason": "[dashboard] live snapshot",
                    "target_price": None,
                    "risk_level": "medium",
                },
            },
        ]

    app = FastAPI()
    openbb_adapter.add_cors(app)
    app.include_router(
        openbb_adapter.build_data_router(
            get_hub=lambda: hub,
            get_engine=lambda pid: mock_engine_factory(pid),
            list_recent_analyses=list_recent,
        ),
        prefix="/openbb",
    )
    app.include_router(
        openbb_adapter.build_agent_router(mock_fleet),
        prefix="/openbb",
    )
    return TestClient(app)


# ── widgets.json / apps.json ─────────────────────────────────────


def test_widgets_json_all_fields_present(client):
    r = client.get("/openbb/widgets.json")
    assert r.status_code == 200
    catalog = r.json()
    assert len(catalog) >= 7, "expect at least 7 widgets"
    for wid, w in catalog.items():
        assert "name" in w
        assert "description" in w
        assert "category" in w
        assert "type" in w
        assert "endpoint" in w
        assert "gridData" in w
        assert "w" in w["gridData"]
        assert "h" in w["gridData"]


def test_apps_json_valid(client):
    r = client.get("/openbb/apps.json")
    assert r.status_code == 200
    apps = r.json()
    assert "neomind_research" in apps
    assert "tabs" in apps["neomind_research"]


# ── CORS ─────────────────────────────────────────────────────────


def test_cors_allow_origin_pro_openbb(client):
    r = client.get(
        "/openbb/widgets.json",
        headers={"Origin": "https://pro.openbb.co"},
    )
    assert r.status_code == 200
    # Starlette CORSMiddleware sets this header on simple GET
    assert r.headers.get("access-control-allow-origin") == "https://pro.openbb.co"


def test_cors_preflight(client):
    r = client.options(
        "/openbb/widgets.json",
        headers={
            "Origin": "https://pro.openbb.co",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == "https://pro.openbb.co"


# ── Data endpoints ───────────────────────────────────────────────


def test_quote_returns_metric_array(client):
    r = client.get("/openbb/quote", params={"symbol": "AAPL"})
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    assert len(body) >= 4
    for item in body:
        assert "label" in item
        assert "value" in item


def test_quote_invalid_symbol_400(client):
    r = client.get("/openbb/quote", params={"symbol": "../etc"})
    assert r.status_code == 400


def test_quote_unknown_symbol_graceful(client):
    r = client.get("/openbb/quote", params={"symbol": "ZZZZ"})
    assert r.status_code == 200
    body = r.json()
    # Should return a "no quote available" metric row
    assert any("no quote" in str(x.get("value", "")).lower() for x in body)


def test_chart_returns_plotly_shape(client):
    r = client.get("/openbb/chart",
                   params={"symbol": "AAPL", "period": "3mo", "interval": "1d"})
    assert r.status_code == 200
    body = r.json()
    assert "data" in body
    assert "layout" in body
    assert isinstance(body["data"], list)
    assert len(body["data"]) >= 1  # at least candlestick
    # First trace should be the candlestick for price
    first = body["data"][0]
    assert first["type"] in ("candlestick", "scatter")


def test_chart_empty_data_graceful(client):
    r = client.get("/openbb/chart", params={"symbol": "MSFT"})
    assert r.status_code == 200
    body = r.json()
    assert "data" in body
    assert body["data"] == []


def test_history_table(client, registered_project):
    r = client.get("/openbb/history",
                   params={"project_id": registered_project, "limit": 10})
    assert r.status_code == 200
    rows = r.json()
    assert isinstance(rows, list)
    assert len(rows) == 1
    assert rows[0]["symbol"] == "AAPL"
    assert rows[0]["signal"] == "hold"


def test_history_unknown_project_returns_empty(client):
    r = client.get("/openbb/history",
                   params={"project_id": "nonexistent-proj", "limit": 5})
    assert r.status_code == 200
    assert r.json() == []


def test_history_invalid_project_id_400(client):
    r = client.get("/openbb/history",
                   params={"project_id": "../etc/passwd"})
    assert r.status_code == 400


def test_paper_account_metric(client, registered_project):
    r = client.get("/openbb/paper_account",
                   params={"project_id": registered_project})
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    labels = [m["label"] for m in body]
    assert "Cash" in labels
    assert "Equity" in labels
    assert "Total PnL" in labels


def test_paper_positions_table(client, registered_project):
    r = client.get("/openbb/paper_positions",
                   params={"project_id": registered_project})
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["symbol"] == "AAPL"
    assert rows[0]["side"] == "long"


def test_paper_trades_table(client, registered_project):
    r = client.get("/openbb/paper_trades",
                   params={"project_id": registered_project, "limit": 5})
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["symbol"] == "AAPL"


# ── News ─────────────────────────────────────────────────────────


def test_news_missing_miniflux_returns_hint_row(client, monkeypatch):
    """Without credentials, we surface a hint as a single feed row
    rather than a 503 (so the widget still renders)."""
    monkeypatch.delenv("MINIFLUX_USERNAME", raising=False)
    monkeypatch.delenv("MINIFLUX_PASSWORD", raising=False)
    r = client.get("/openbb/news", params={"limit": 5})
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert "MINIFLUX" in body[0]["summary"]


# ── Agent (Copilot) ──────────────────────────────────────────────


def test_agents_json(client):
    r = client.get("/openbb/agents.json")
    assert r.status_code == 200
    meta = r.json()
    assert "neomind_fin" in meta
    agent = meta["neomind_fin"]
    assert "name" in agent
    assert "endpoints" in agent
    assert agent["endpoints"]["query"] == "/openbb/query"
    assert agent["features"]["streaming"] is True


def test_query_requires_human_message(client, registered_project):
    r = client.post("/openbb/query", json={"messages": []})
    assert r.status_code == 400


def test_query_rejects_unregistered_project(client, registered_project):
    r = client.post(
        "/openbb/query",
        json={
            "messages": [{"role": "human", "content": "hi"}],
            "project_id": "nonexistent",
        },
    )
    assert r.status_code == 404


def test_query_sse_streams_to_completion(client, registered_project):
    r = client.post(
        "/openbb/query",
        json={
            "messages": [{"role": "human", "content": "一句话介绍 AAPL"}],
            "project_id": registered_project,
        },
    )
    assert r.status_code == 200
    body = r.text
    # SSE-formatted: "event: message\ndata: {...}\n\n"
    # Parse every data: line as JSON and collect content fields
    contents = []
    for line in body.split("\n"):
        line = line.strip()
        if line.startswith("data: "):
            try:
                contents.append(json.loads(line[len("data: "):]).get("content", ""))
            except Exception:
                pass
    assert any("fin-rt working" in c for c in contents), contents
    # Final completed reply — mock returns "这是测试回复。"
    assert any("这是测试回复" in c for c in contents), contents


def test_query_message_too_long(client, registered_project):
    r = client.post(
        "/openbb/query",
        json={
            "messages": [{"role": "human", "content": "x" * 5000}],
            "project_id": registered_project,
        },
    )
    assert r.status_code == 400
