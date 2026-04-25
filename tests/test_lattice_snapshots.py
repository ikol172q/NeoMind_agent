"""V8 · lattice snapshot storage — write/read/list.

Fast, pure-filesystem tests. Uses NEOMIND_INVESTMENT_ROOT to redirect
storage to a temp dir so we don't touch real user data.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.lattice_fast


@pytest.fixture
def tmp_root(tmp_path, monkeypatch):
    """Redirect investment_root → a temp dir with a registered project."""
    # Register a project: create the directory so list_projects() sees it.
    pid = "fin-test"
    (tmp_path / pid).mkdir(parents=True)
    # Minimum marker the investment_projects module requires
    (tmp_path / pid / "watchlist.json").write_text('{"entries": []}')
    monkeypatch.setenv("NEOMIND_INVESTMENT_ROOT", str(tmp_path))
    # Reset the module-level cache if any
    from agent.finance import investment_projects
    if hasattr(investment_projects, "_cached_root"):
        investment_projects._cached_root = None  # type: ignore[attr-defined]
    return tmp_path, pid


def test_today_str_is_utc_date_format():
    from agent.finance.lattice.snapshots import today_str
    t = today_str()
    assert len(t) == 10
    assert t[4] == "-" and t[7] == "-"


def test_snapshot_path_rejects_bad_date(tmp_root):
    _, pid = tmp_root
    from agent.finance.lattice.snapshots import snapshot_path
    with pytest.raises(ValueError):
        snapshot_path(pid, "2026/04/23")
    with pytest.raises(ValueError):
        snapshot_path(pid, "04-23-2026")
    with pytest.raises(ValueError):
        snapshot_path(pid, "")


def test_write_and_read_round_trip(tmp_root):
    from agent.finance.lattice.snapshots import write_snapshot, read_snapshot
    root, pid = tmp_root
    payload = {
        "project_id": pid,
        "observations": [{"id": "obs_1", "text": "AAPL near 52w"}],
        "themes": [{"id": "theme_1", "narrative": "near highs"}],
        "calls": [{"id": "call_1", "claim": "watch close"}],
    }
    path = write_snapshot(pid, payload, date_str="2026-04-23")
    assert path.is_file()
    assert path.parent.name == "lattice_snapshots"
    assert path.name == "2026-04-23.json"

    envelope = read_snapshot(pid, "2026-04-23")
    assert envelope is not None
    assert envelope["snapshot_meta"]["version"] == 1
    assert envelope["snapshot_meta"]["date"] == "2026-04-23"
    assert envelope["payload"] == payload


def test_read_missing_returns_none(tmp_root):
    from agent.finance.lattice.snapshots import read_snapshot
    _, pid = tmp_root
    assert read_snapshot(pid, "1970-01-01") is None


def test_list_snapshots_newest_first(tmp_root):
    from agent.finance.lattice.snapshots import write_snapshot, list_snapshots
    _, pid = tmp_root
    for d in ["2026-04-20", "2026-04-23", "2026-04-21"]:
        write_snapshot(pid, {"date_marker": d}, date_str=d)
    snaps = list_snapshots(pid)
    assert [s["date"] for s in snaps] == ["2026-04-23", "2026-04-21", "2026-04-20"]
    assert all(s["size_bytes"] > 0 for s in snaps)
    assert all(s["recorded_at"] for s in snaps)


def test_list_snapshots_empty_when_missing_dir(tmp_root):
    from agent.finance.lattice.snapshots import list_snapshots
    _, pid = tmp_root
    # No snapshot dir created yet
    assert list_snapshots(pid) == []


def test_list_snapshots_skips_non_date_files(tmp_root):
    from agent.finance.lattice.snapshots import (
        write_snapshot, list_snapshots, _snapshot_dir,
    )
    _, pid = tmp_root
    write_snapshot(pid, {"x": 1}, date_str="2026-04-23")
    d = _snapshot_dir(pid)
    (d / "junk.json").write_text("{}")
    (d / "README.md").write_text("hi")
    dates = [s["date"] for s in list_snapshots(pid)]
    assert dates == ["2026-04-23"]


def test_read_corrupt_snapshot_returns_none(tmp_root):
    from agent.finance.lattice.snapshots import read_snapshot, snapshot_path
    _, pid = tmp_root
    path = snapshot_path(pid, "2026-04-23")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not json {{{ at all")
    # Must not raise — caller shouldn't crash on a broken archived day.
    assert read_snapshot(pid, "2026-04-23") is None


def test_write_overwrites_same_day(tmp_root):
    from agent.finance.lattice.snapshots import write_snapshot, read_snapshot
    _, pid = tmp_root
    write_snapshot(pid, {"version": "old"}, date_str="2026-04-23")
    write_snapshot(pid, {"version": "new"}, date_str="2026-04-23")
    envelope = read_snapshot(pid, "2026-04-23")
    assert envelope is not None
    assert envelope["payload"] == {"version": "new"}


def test_write_honours_output_language_field(tmp_root):
    from agent.finance.lattice.snapshots import write_snapshot, read_snapshot
    _, pid = tmp_root
    write_snapshot(pid, {"output_language": "zh-CN-mixed"},
                   date_str="2026-04-23")
    env = read_snapshot(pid, "2026-04-23")
    assert env is not None
    assert env["snapshot_meta"]["output_language"] == "zh-CN-mixed"
