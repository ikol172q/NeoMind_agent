"""Tests for agent.finance.agent_audit — zero-data-loss LLM-call audit.

Verifies:
- Request / response / error events are written as JSONL lines
- Nothing is truncated (full messages[], full content, long reasoning
  all preserved byte-for-byte)
- Append-only: past lines are never mutated
- Query API: recent(), by_task(), by_req(), stats() work correctly
- HTTP router: /api/audit/recent / /task/{id} / /req/{id} / /stats
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.finance import agent_audit


@pytest.fixture
def audit_log(tmp_path, monkeypatch):
    """Isolated audit dir per test."""
    # Redirect the module-level default to a tmp root by monkey-
    # patching the resolved path function.
    root = tmp_path / "_audit"
    root.mkdir()
    log = agent_audit.AuditLogger(root=root)
    # Also swap the module singleton so the HTTP router uses this
    monkeypatch.setattr(agent_audit, "_default", log)
    return log


def test_record_request_roundtrip(audit_log):
    rid = agent_audit.new_req_id()
    audit_log.record_request(
        req_id=rid,
        endpoint="fleet.worker",
        agent_id="fleet-worker",
        messages=[
            {"role": "system", "content": "你是 fin persona"},
            {"role": "user", "content": "介绍 AAPL"},
        ],
        model="deepseek-reasoner",
        max_tokens=8192,
        temperature=0.3,
        task_id="task_123_1",
        project_id="fin-core",
    )
    entries = audit_log.recent()
    assert len(entries) == 1
    e = entries[0]
    assert e["req_id"] == rid
    assert e["task_id"] == "task_123_1"
    assert e["kind"] == "request"
    assert e["payload"]["model"] == "deepseek-reasoner"
    assert e["payload"]["max_tokens"] == 8192
    # Full messages preserved
    assert len(e["payload"]["messages"]) == 2
    assert e["payload"]["messages"][0]["content"] == "你是 fin persona"


def test_record_response_full_bodies(audit_log):
    """Responses must carry the FULL reply, no 200-char cap, plus
    reasoning_content for R1."""
    rid = agent_audit.new_req_id()
    long_reply = "这是一段长回复。" * 200  # ~2000 chars
    long_reasoning = "思考过程..." * 500
    audit_log.record_response(
        req_id=rid,
        agent_id="fleet-worker",
        endpoint="fleet.worker",
        content=long_reply,
        reasoning_content=long_reasoning,
        finish_reason="stop",
        usage={"prompt_tokens": 50, "completion_tokens": 1600, "total_tokens": 1650},
        duration_ms=12345,
        task_id="task_abc",
    )
    entries = audit_log.recent()
    e = entries[0]
    # Zero truncation
    assert e["payload"]["content"] == long_reply
    assert e["payload"]["reasoning_content"] == long_reasoning
    assert e["payload"]["usage"]["total_tokens"] == 1650
    assert e["payload"]["duration_ms"] == 12345


def test_append_only_never_overwrites(audit_log):
    """Write 5 entries, check all 5 survive, file grows monotonically."""
    path = audit_log._today()
    sizes = []
    for i in range(5):
        audit_log.record_request(
            req_id=f"r{i}", endpoint="x", agent_id="x",
            messages=[{"role": "user", "content": f"msg {i}"}],
            model="test", max_tokens=100,
        )
        sizes.append(path.stat().st_size)
    # Strictly increasing file size = pure append
    for a, b in zip(sizes, sizes[1:]):
        assert b > a, f"file shrank from {a} to {b}"
    # All 5 entries readable
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 5
    parsed = [json.loads(l) for l in lines]
    assert [p["req_id"] for p in parsed] == ["r0", "r1", "r2", "r3", "r4"]


def test_filter_by_task_id(audit_log):
    for i in range(3):
        audit_log.record_request(
            req_id=f"r{i}", endpoint="x", agent_id="x",
            messages=[{"role": "user", "content": "m"}],
            model="test", task_id="task_A",
        )
    audit_log.record_request(
        req_id="r_other", endpoint="x", agent_id="x",
        messages=[{"role": "user", "content": "m"}],
        model="test", task_id="task_B",
    )
    entries_A = audit_log.by_task("task_A")
    entries_B = audit_log.by_task("task_B")
    assert len(entries_A) == 3
    assert len(entries_B) == 1
    assert entries_B[0]["req_id"] == "r_other"


def test_filter_by_req_id(audit_log):
    rid = "uniq_req_abc"
    audit_log.record_request(
        req_id=rid, endpoint="x", agent_id="x",
        messages=[{"role": "user", "content": "q"}],
        model="test",
    )
    audit_log.record_response(
        req_id=rid, agent_id="x", endpoint="x",
        content="answer", duration_ms=100,
    )
    audit_log.record_request(
        req_id="other", endpoint="x", agent_id="x",
        messages=[], model="test",
    )
    paired = audit_log.by_req(rid)
    assert len(paired) == 2
    kinds = [e["kind"] for e in paired]
    assert "request" in kinds and "response" in kinds


def test_error_event(audit_log):
    audit_log.record_error(
        req_id="r1",
        agent_id="fleet-worker",
        endpoint="fleet.worker",
        error_type="HTTPError",
        error_msg="401 Unauthorized",
        traceback_text="Traceback (most recent call last):\n  File ...",
        duration_ms=500,
        task_id="task_xyz",
    )
    entries = audit_log.recent(kind="error")
    assert len(entries) == 1
    e = entries[0]
    assert e["kind"] == "error"
    assert e["payload"]["error_type"] == "HTTPError"
    assert "Traceback" in e["payload"]["traceback"]


def test_stats_aggregation(audit_log):
    for i in range(3):
        audit_log.record_request(
            req_id=f"r{i}", endpoint="fleet.worker", agent_id="fleet-worker",
            messages=[{"role": "user", "content": "m"}],
            model="test",
        )
        audit_log.record_response(
            req_id=f"r{i}", agent_id="fleet-worker", endpoint="fleet.worker",
            content=f"reply {i}",
            usage={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
            duration_ms=100,
        )
    s = audit_log.stats()
    assert s["total_entries"] == 6
    assert s["by_kind"]["request"] == 3
    assert s["by_kind"]["response"] == 3
    assert s["by_agent"]["fleet-worker"] == 6
    assert s["tokens_in"] == 30   # 10 × 3
    assert s["tokens_out"] == 60  # 20 × 3


def test_unicode_preserved(audit_log):
    """ensure_ascii=False: Chinese / emoji chars are not escaped."""
    audit_log.record_response(
        req_id="u1", agent_id="x", endpoint="x",
        content="你好！🚀 QQQ vs VOO 对比",
    )
    path = audit_log._today()
    raw = path.read_text(encoding="utf-8")
    # Chinese chars appear verbatim, not \uXXXX
    assert "你好" in raw
    assert "🚀" in raw
    assert "\\u" not in raw  # no unicode escape sequences


# ── HTTP router ───────────────────────────────────────────────────


@pytest.fixture
def client(audit_log):
    app = FastAPI()
    app.include_router(agent_audit.build_audit_router())
    # prime with a few entries
    audit_log.record_request(
        req_id="req1", endpoint="fleet.worker", agent_id="fleet-worker",
        messages=[{"role": "user", "content": "msg"}],
        model="test", task_id="task_999",
    )
    audit_log.record_response(
        req_id="req1", agent_id="fleet-worker", endpoint="fleet.worker",
        content="hello",
        usage={"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
        duration_ms=120, task_id="task_999",
    )
    return TestClient(app)


def test_http_recent(client):
    r = client.get("/api/audit/recent?limit=10")
    assert r.status_code == 200
    body = r.json()
    assert len(body["entries"]) == 2


def test_http_by_task(client):
    r = client.get("/api/audit/task/task_999")
    assert r.status_code == 200
    body = r.json()
    assert len(body["entries"]) == 2


def test_http_by_req(client):
    r = client.get("/api/audit/req/req1")
    assert r.status_code == 200
    body = r.json()
    assert len(body["entries"]) == 2


def test_http_stats(client):
    r = client.get("/api/audit/stats")
    assert r.status_code == 200
    s = r.json()
    assert s["total_entries"] == 2
    assert s["tokens_in"] == 5
    assert s["tokens_out"] == 2
