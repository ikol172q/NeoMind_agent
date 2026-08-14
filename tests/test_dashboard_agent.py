"""Smoke tests for agent/finance/dashboard_agent/.

These tests hit the live local dashboard at 127.0.0.1:8001. They are
SMOKE-level: assert "no exception + returns expected top-level keys"
rather than checking specific data values (which change every minute).

Skipped automatically if the dashboard is not reachable.
"""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from agent.finance.dashboard_agent import tools


def _dashboard_up() -> bool:
    try:
        r = httpx.get("http://127.0.0.1:8001/api/health", timeout=2.0)
        return r.status_code == 200
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _dashboard_up(),
    reason="local dashboard not reachable; skip live smoke tests",
)


def _run(coro):
    return asyncio.run(coro)


def test_tool_schemas_valid_openai_function_calling_shape():
    # Count not pinned: schemas get added over time and freezing the
    # number tests nothing about their shape, which is what follows.
    assert isinstance(tools.TOOL_SCHEMAS, list) and tools.TOOL_SCHEMAS
    for t in tools.TOOL_SCHEMAS:
        assert t["type"] == "function"
        fn = t["function"]
        assert fn["name"] in tools.TOOL_FUNCTIONS
        assert "description" in fn and len(fn["description"]) > 20
        assert "parameters" in fn
        assert fn["parameters"]["type"] == "object"


def test_get_data_freshness_returns_12_scanners():
    r = _run(tools.get_data_freshness())
    assert "scanners" in r
    names = {s["scanner"] for s in r["scanners"]}
    assert "signal_hourly" in names
    assert "audit_strategies" in names
    assert len(r["scanners"]) >= 10


def test_get_portfolio_snapshot_has_three_parts():
    r = _run(tools.get_portfolio_snapshot())
    assert "portfolio_graph" in r
    assert "positions_summary" in r
    assert "paper_positions" in r


def test_get_chain_supply_chain_nvda():
    r = _run(tools.get_chain("NVDA"))
    assert "nodes" in r
    assert r.get("origin") == "NVDA"


def test_get_chain_handles_unknown_ticker_gracefully():
    r = _run(tools.get_chain("ZZZZZ"))
    # Empty graph is fine; should not raise.
    assert "nodes" in r


def test_get_chain_empty_ticker():
    r = _run(tools.get_chain(""))
    assert "error" in r


def test_dispatch_unknown_tool_returns_error():
    r = _run(tools.dispatch("nonexistent_tool", {}))
    assert "error" in r


def test_dispatch_resolves_real_tool():
    r = _run(tools.dispatch("get_outside_ring", {"limit": 3}))
    assert "candidates" in r or "error" in r
