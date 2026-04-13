"""Tests for fleet/transcripts.py — the per-agent persistent log."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from fleet.transcripts import (
    AgentTranscript,
    AgentTurn,
    TranscriptError,
    transcript_path_for,
)


# ── AgentTurn validation ────────────────────────────────────────────────


def test_agent_turn_basic_fields():
    t = AgentTurn(role="user", content="hello")
    assert t.role == "user"
    assert t.content == "hello"
    assert t.ts  # auto-set
    assert t.metadata == {}


def test_agent_turn_with_metadata():
    t = AgentTurn(role="assistant", content="hi", metadata={"model": "ds"})
    assert t.metadata["model"] == "ds"


def test_agent_turn_rejects_invalid_role():
    with pytest.raises(TranscriptError):
        AgentTurn(role="wizard", content="abra")


def test_agent_turn_rejects_non_string_content():
    with pytest.raises(TranscriptError):
        AgentTurn(role="user", content=42)  # type: ignore[arg-type]


def test_agent_turn_rejects_non_dict_metadata():
    with pytest.raises(TranscriptError):
        AgentTurn(role="user", content="x", metadata="not-a-dict")  # type: ignore[arg-type]


def test_agent_turn_to_from_json_roundtrip():
    original = AgentTurn(
        role="assistant",
        content="the signal is hold",
        metadata={"duration_s": 1.23, "model": "deepseek"},
    )
    line = original.to_json()
    assert "\n" not in line  # JSONL: one line, no embedded newlines
    decoded = AgentTurn.from_json(line)
    assert decoded.role == original.role
    assert decoded.content == original.content
    assert decoded.metadata == original.metadata


def test_agent_turn_from_json_rejects_corrupt():
    with pytest.raises(TranscriptError):
        AgentTurn.from_json("{not valid json")


def test_agent_turn_from_json_rejects_non_object():
    with pytest.raises(TranscriptError):
        AgentTurn.from_json("42")


# ── transcript_path_for ────────────────────────────────────────────────


def test_transcript_path_default_base(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    path = transcript_path_for("proj", "fin-rt")
    assert str(path).endswith("teams/proj/transcripts/fin-rt.jsonl")


def test_transcript_path_explicit_base(tmp_path):
    path = transcript_path_for("proj", "fin-rt", base_dir=str(tmp_path))
    assert path == tmp_path / "teams" / "proj" / "transcripts" / "fin-rt.jsonl"


def test_transcript_path_rejects_traversal():
    with pytest.raises(TranscriptError):
        transcript_path_for("proj", "../etc/passwd")


def test_transcript_path_rejects_non_alpha_start():
    with pytest.raises(TranscriptError):
        transcript_path_for("proj", "1fin")


def test_transcript_path_rejects_empty():
    with pytest.raises(TranscriptError):
        transcript_path_for("proj", "")


# ── AgentTranscript basic lifecycle ────────────────────────────────────


def test_transcript_starts_empty_and_not_loaded(tmp_path):
    t = AgentTranscript("proj", "fin-rt", base_dir=str(tmp_path))
    assert t.turn_count() == 0
    assert not t.loaded


def test_ensure_loaded_on_missing_file(tmp_path):
    t = AgentTranscript("proj", "fin-rt", base_dir=str(tmp_path))
    t.ensure_loaded()
    assert t.loaded
    assert t.turn_count() == 0


def test_append_turn_persists_to_disk(tmp_path):
    t = AgentTranscript("proj", "fin-rt", base_dir=str(tmp_path))
    t.append_turn(AgentTurn(role="user", content="analyze AAPL"))
    path = t.path
    assert path.exists()
    lines = path.read_text().strip().split("\n")
    assert len(lines) == 1
    decoded = json.loads(lines[0])
    assert decoded["role"] == "user"
    assert decoded["content"] == "analyze AAPL"


def test_append_many_turns_same_order(tmp_path):
    t = AgentTranscript("proj", "fin-rt", base_dir=str(tmp_path))
    for i in range(5):
        t.append_turn(AgentTurn(role="system", content=f"tick {i}"))
    assert t.turn_count() == 5
    lines = t.path.read_text().strip().split("\n")
    assert len(lines) == 5
    for i, line in enumerate(lines):
        assert json.loads(line)["content"] == f"tick {i}"


def test_append_turns_batch(tmp_path):
    t = AgentTranscript("proj", "fin-rt", base_dir=str(tmp_path))
    batch = [
        AgentTurn(role="user", content="one"),
        AgentTurn(role="assistant", content="two"),
        AgentTurn(role="user", content="three"),
    ]
    t.append_turns(batch)
    assert t.turn_count() == 3
    assert [x.content for x in t.turns] == ["one", "two", "three"]


def test_append_rejects_non_agent_turn(tmp_path):
    t = AgentTranscript("proj", "fin-rt", base_dir=str(tmp_path))
    with pytest.raises(TranscriptError):
        t.append_turn("not a turn")  # type: ignore[arg-type]


# ── Fresh instance re-load from disk ───────────────────────────────────


def test_fresh_instance_loads_prior_turns(tmp_path):
    t1 = AgentTranscript("proj", "fin-rt", base_dir=str(tmp_path))
    t1.append_turn(AgentTurn(role="user", content="hi"))
    t1.append_turn(AgentTurn(role="assistant", content="hello"))

    t2 = AgentTranscript("proj", "fin-rt", base_dir=str(tmp_path))
    assert not t2.loaded
    t2.ensure_loaded()
    assert t2.loaded
    assert t2.turn_count() == 2
    assert [x.content for x in t2.turns] == ["hi", "hello"]


def test_append_after_lazy_load_doesnt_duplicate(tmp_path):
    t1 = AgentTranscript("proj", "fin-rt", base_dir=str(tmp_path))
    t1.append_turn(AgentTurn(role="user", content="first"))

    # Fresh instance: append WITHOUT manually calling ensure_loaded
    # should still produce a file with [first, second], not duplicate
    t2 = AgentTranscript("proj", "fin-rt", base_dir=str(tmp_path))
    t2.append_turn(AgentTurn(role="user", content="second"))
    assert t2.turn_count() == 2

    # And the final disk state has both
    t3 = AgentTranscript("proj", "fin-rt", base_dir=str(tmp_path))
    t3.ensure_loaded()
    assert [x.content for x in t3.turns] == ["first", "second"]


# ── Corrupt lines are skipped gracefully ───────────────────────────────


def test_corrupt_line_skipped_with_warning(tmp_path):
    path = tmp_path / "teams" / "proj" / "transcripts" / "agent.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text(
        '{"role":"user","content":"ok","ts":"2026-01-01T00:00:00+00:00","metadata":{}}\n'
        'NOT JSON GARBAGE\n'
        '{"role":"assistant","content":"hi","ts":"2026-01-01T00:00:01+00:00","metadata":{}}\n'
    )
    t = AgentTranscript("proj", "agent", base_dir=str(tmp_path))
    t.ensure_loaded()
    # Only 2 valid turns survived
    assert t.turn_count() == 2
    assert [x.role for x in t.turns] == ["user", "assistant"]


# ── Concurrent appends ────────────────────────────────────────────────


def test_concurrent_appends_no_loss_no_corruption(tmp_path):
    """50 threads each append 1 turn — all 50 must end up in the file,
    each as a valid parseable JSON line."""
    t = AgentTranscript("proj", "fin-rt", base_dir=str(tmp_path))
    N = 50

    def worker(i):
        t.append_turn(AgentTurn(
            role="system", content=f"event-{i}", metadata={"i": i},
        ))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(N)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()

    assert t.turn_count() == N
    # Reload and verify disk has all 50 as parseable lines
    t2 = AgentTranscript("proj", "fin-rt", base_dir=str(tmp_path))
    t2.ensure_loaded()
    assert t2.turn_count() == N
    tags = {x.content for x in t2.turns}
    assert tags == {f"event-{i}" for i in range(N)}


# ── Eviction ──────────────────────────────────────────────────────────


def test_evict_memory_drops_turns_keeps_file(tmp_path):
    t = AgentTranscript("proj", "fin-rt", base_dir=str(tmp_path))
    t.append_turn(AgentTurn(role="user", content="persistent"))
    assert t.turn_count() == 1
    t.evict_memory()
    assert not t.loaded
    assert len(t.turns) == 0
    # Disk still has it
    assert t.path.exists()
    lines = t.path.read_text().strip().split("\n")
    assert len(lines) == 1
    # Reload works
    t.ensure_loaded()
    assert t.turn_count() == 1
    assert t.turns[0].content == "persistent"


def test_is_stale_default_false(tmp_path):
    t = AgentTranscript("proj", "fin-rt", base_dir=str(tmp_path), evict_after_seconds=60.0)
    # Just constructed — not stale
    assert not t.is_stale()


def test_is_stale_after_very_short_window(tmp_path):
    t = AgentTranscript("proj", "fin-rt", base_dir=str(tmp_path), evict_after_seconds=0.001)
    # After any time at all, it's stale
    import time
    time.sleep(0.01)
    assert t.is_stale()


def test_mark_accessed_refreshes_stale(tmp_path):
    t = AgentTranscript("proj", "fin-rt", base_dir=str(tmp_path), evict_after_seconds=0.05)
    import time
    time.sleep(0.06)
    assert t.is_stale()
    t.mark_accessed()
    assert not t.is_stale()
