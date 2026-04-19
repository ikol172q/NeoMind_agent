"""Tests for agent.finance.chat_stream — POST /api/chat + audit log.

Mocks FleetBackend.dispatch_chat so no fleet is actually spawned.
Verifies:
- Happy path: valid project + message → task_id returned + JSONL audit line appended
- Input validation: empty / overlong / control-char messages → 400
- Project validation: bad regex / unregistered project → 400 / 404
- Audit log path lives under the Investment firewall
- GET /api/chat/log replays the JSONL lines newest-last
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.finance import chat_stream, investment_projects


# ── Fixtures ───────────────────────────────────────────────────────

@pytest.fixture
def tmp_investment_root(tmp_path, monkeypatch):
    root = tmp_path / "Investment"
    root.mkdir()
    monkeypatch.setenv("NEOMIND_INVESTMENT_ROOT", str(root))
    return root


@pytest.fixture
def registered_project(tmp_investment_root):
    pid = "chat-test-proj"
    investment_projects.register_project(pid, "test project for chat_stream")
    return pid


@pytest.fixture
def mock_fleet():
    fleet = MagicMock()
    fleet.member = "fin-rt"
    fleet.dispatch_chat = AsyncMock(return_value="task-abcdef12")
    return fleet


@pytest.fixture
def client(mock_fleet):
    app = FastAPI()
    app.include_router(chat_stream.build_chat_router(mock_fleet))
    return TestClient(app)


# ── Happy path ─────────────────────────────────────────────────────

def test_chat_dispatches_and_returns_task_id(
    client, mock_fleet, registered_project,
):
    r = client.post(
        "/api/chat",
        params={"project_id": registered_project, "message": "茅台怎么样?"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["task_id"] == "task-abcdef12"
    assert body["kind"] == "chat"
    assert body["project_id"] == registered_project
    mock_fleet.dispatch_chat.assert_awaited_once()
    # The prompt passed to dispatch_chat should contain the original message
    call_args = mock_fleet.dispatch_chat.await_args
    prompt = call_args.args[0] if call_args.args else call_args.kwargs["prompt"]
    assert "茅台怎么样?" in prompt


def test_audit_log_written(
    client, mock_fleet, registered_project, tmp_investment_root,
):
    client.post(
        "/api/chat",
        params={"project_id": registered_project, "message": "hello fin"},
    )
    log_dir = tmp_investment_root / registered_project / "chat_log"
    assert log_dir.exists()
    files = list(log_dir.glob("*.jsonl"))
    assert len(files) == 1
    lines = files[0].read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["message"] == "hello fin"
    assert entry["task_id"] == "task-abcdef12"
    assert entry["project_id"] == registered_project
    assert entry["member"] == "fin-rt"


# ── Input validation ───────────────────────────────────────────────

def test_chat_rejects_empty_message(client, registered_project):
    r = client.post(
        "/api/chat",
        params={"project_id": registered_project, "message": "   "},
    )
    assert r.status_code == 400
    assert "empty" in r.json()["detail"].lower()


def test_chat_rejects_overlong_message(client, registered_project):
    r = client.post(
        "/api/chat",
        params={
            "project_id": registered_project,
            "message": "x" * (chat_stream._MAX_MSG_LEN + 1),
        },
    )
    assert r.status_code == 400
    assert "too long" in r.json()["detail"].lower()


def test_chat_rejects_control_chars(client, registered_project):
    r = client.post(
        "/api/chat",
        params={"project_id": registered_project, "message": "hello\x00world"},
    )
    assert r.status_code == 400


def test_chat_rejects_bad_project_id_regex(client):
    r = client.post(
        "/api/chat",
        params={"project_id": "../etc/passwd", "message": "hi"},
    )
    assert r.status_code == 400


def test_chat_rejects_unregistered_project(client, tmp_investment_root):
    r = client.post(
        "/api/chat",
        params={"project_id": "nonexistent-proj", "message": "hi"},
    )
    assert r.status_code == 404


# ── Log replay ─────────────────────────────────────────────────────

def test_chat_log_replay(client, registered_project):
    for msg in ["first", "second", "third"]:
        r = client.post(
            "/api/chat",
            params={"project_id": registered_project, "message": msg},
        )
        assert r.status_code == 200

    r = client.get(
        "/api/chat/log",
        params={"project_id": registered_project, "limit": 5},
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body["entries"]) == 3
    messages = [e["message"] for e in body["entries"]]
    assert messages == ["first", "second", "third"]


def test_chat_log_empty_when_no_log(client, registered_project):
    r = client.get(
        "/api/chat/log",
        params={"project_id": registered_project},
    )
    assert r.status_code == 200
    assert r.json()["entries"] == []


# ── Prompt shape ───────────────────────────────────────────────────

def test_build_chat_prompt_includes_project_and_message():
    p = chat_stream.build_chat_prompt("what about AAPL?", "proj-1")
    assert "proj-1" in p
    assert "what about AAPL?" in p
