"""Tests for agent.finance.news_hub — Miniflux proxy with basic auth.

Mocks urllib.request.urlopen so no real network. Asserts:
- Normalisation: ``entries`` payload → ``NewsEntry`` dicts with snippet stripped of HTML
- Basic Auth header construction
- Symbol filter: case-insensitive substring match against title
- 401 → HTTPException 503 with hint
- Unreachable → HTTPException 503 with hint
- Config missing → HTTPException 503 before any network call
"""

from __future__ import annotations

import base64
import io
import json
from unittest.mock import patch, MagicMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from fastapi import FastAPI

from agent.finance import news_hub


# ── Fixtures ───────────────────────────────────────────────────────

SAMPLE_PAYLOAD = {
    "total": 3,
    "entries": [
        {
            "id": 1,
            "title": "AAPL hits new high on Vision Pro sales",
            "url": "https://example.com/aapl",
            "published_at": "2026-04-19T10:00:00Z",
            "feed": {"id": 5, "title": "Bloomberg Markets"},
            "content": "<p>Apple Inc (<b>AAPL</b>) closed at a record…</p>",
        },
        {
            "id": 2,
            "title": "Fed holds rates steady",
            "url": "https://example.com/fed",
            "published_at": "2026-04-19T09:30:00Z",
            "feed": {"id": 6, "title": "WSJ Markets"},
            "content": "<div>The Federal Reserve announced…</div>",
        },
        {
            "id": 3,
            "title": "TSLA delivers record quarter",
            "url": "https://example.com/tsla",
            "published_at": "2026-04-19T09:00:00Z",
            "feed": {"id": 7, "title": "Reuters"},
            "content": "Tesla reported Q1 deliveries…",
        },
    ],
}


def _mock_urlopen_ok(payload=SAMPLE_PAYLOAD):
    def _fn(req, timeout=None):
        resp = MagicMock()
        resp.read.return_value = json.dumps(payload).encode("utf-8")
        resp.__enter__ = lambda self: resp
        resp.__exit__ = lambda *a: False
        return resp
    return _fn


@pytest.fixture
def env_set(monkeypatch):
    monkeypatch.setenv("MINIFLUX_URL", "http://127.0.0.1:8080")
    monkeypatch.setenv("MINIFLUX_USERNAME", "neomind")
    monkeypatch.setenv("MINIFLUX_PASSWORD", "supersecret")


@pytest.fixture
def router_client(env_set):
    app = FastAPI()
    app.include_router(news_hub.build_news_router())
    return TestClient(app)


# ── Unit tests — normalisation & helpers ───────────────────────────

def test_strip_html_removes_tags_and_collapses_whitespace():
    src = "<p>hello <b>world</b></p>  \n\t foo"
    out = news_hub._strip_html(src)
    assert out == "hello world foo"


def test_strip_html_truncates_long():
    out = news_hub._strip_html("x" * 500, max_len=100)
    assert len(out) <= 100
    assert out.endswith("…")


def test_normalise_entry_handles_missing_fields():
    e = news_hub._normalise_entry({"id": 1, "title": "t", "url": "u"})
    assert e is not None
    assert e.id == 1
    assert e.feed_title == ""
    assert e.snippet == ""


def test_basic_auth_header_roundtrip():
    h = news_hub._basic_auth_header("alice", "s3cret")
    assert h.startswith("Basic ")
    decoded = base64.b64decode(h.removeprefix("Basic ")).decode()
    assert decoded == "alice:s3cret"


# ── fetch_entries integration with mocked urlopen ──────────────────

def test_fetch_entries_returns_normalised_list(env_set):
    with patch.object(news_hub.urllib.request, "urlopen",
                      side_effect=_mock_urlopen_ok()):
        entries = news_hub.fetch_entries(limit=10)
    assert len(entries) == 3
    assert entries[0].title.startswith("AAPL")
    assert entries[0].feed_title == "Bloomberg Markets"
    assert "<" not in entries[0].snippet  # html stripped


def test_fetch_entries_applies_symbol_filter(env_set):
    with patch.object(news_hub.urllib.request, "urlopen",
                      side_effect=_mock_urlopen_ok()):
        entries = news_hub.fetch_entries(limit=10, symbols=["aapl"])
    titles = [e.title for e in entries]
    assert len(titles) == 1
    assert "AAPL" in titles[0]


def test_fetch_entries_symbol_filter_multi(env_set):
    with patch.object(news_hub.urllib.request, "urlopen",
                      side_effect=_mock_urlopen_ok()):
        entries = news_hub.fetch_entries(limit=10, symbols=["AAPL", "TSLA"])
    assert {e.title for e in entries} == {
        "AAPL hits new high on Vision Pro sales",
        "TSLA delivers record quarter",
    }


def test_fetch_entries_missing_creds_raises_503(monkeypatch):
    monkeypatch.delenv("MINIFLUX_USERNAME", raising=False)
    monkeypatch.delenv("MINIFLUX_PASSWORD", raising=False)
    with pytest.raises(HTTPException) as exc_info:
        news_hub.fetch_entries(limit=5)
    assert exc_info.value.status_code == 503
    assert "MINIFLUX_USERNAME" in exc_info.value.detail


def test_fetch_entries_401_translates_to_503(env_set):
    import urllib.error
    err = urllib.error.HTTPError(
        "http://x", 401, "Unauthorized", {}, io.BytesIO(b""),
    )
    with patch.object(news_hub.urllib.request, "urlopen", side_effect=err):
        with pytest.raises(HTTPException) as exc_info:
            news_hub.fetch_entries(limit=5)
    assert exc_info.value.status_code == 503
    assert "401" in exc_info.value.detail


def test_fetch_entries_unreachable_translates_to_503(env_set):
    import urllib.error
    err = urllib.error.URLError("Connection refused")
    with patch.object(news_hub.urllib.request, "urlopen", side_effect=err):
        with pytest.raises(HTTPException) as exc_info:
            news_hub.fetch_entries(limit=5)
    assert exc_info.value.status_code == 503
    assert "unreachable" in exc_info.value.detail


# ── Router tests ───────────────────────────────────────────────────

def test_router_api_news_happy_path(router_client):
    with patch.object(news_hub.urllib.request, "urlopen",
                      side_effect=_mock_urlopen_ok()):
        r = router_client.get("/api/news?limit=5")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 3
    assert len(body["entries"]) == 3
    assert "fetched_at" in body


def test_router_api_news_limit_clamped(router_client):
    # limit > max should be a 422 from FastAPI Query bounds
    r = router_client.get("/api/news?limit=9999")
    assert r.status_code == 422


def test_router_api_news_health_ok(router_client):
    with patch.object(news_hub.urllib.request, "urlopen",
                      side_effect=_mock_urlopen_ok({"entries": []})):
        r = router_client.get("/api/news/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_router_api_news_health_missing_creds(monkeypatch):
    monkeypatch.delenv("MINIFLUX_USERNAME", raising=False)
    monkeypatch.delenv("MINIFLUX_PASSWORD", raising=False)
    app = FastAPI()
    app.include_router(news_hub.build_news_router())
    client = TestClient(app)
    r = client.get("/api/news/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert "MINIFLUX_USERNAME" in body["reason"]
