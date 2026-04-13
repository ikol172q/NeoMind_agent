"""Tests for agent/finance/kpi_snapshot.py — KPI computation + fail-fast hook."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest

from agent.finance import investment_projects
from agent.finance.kpi_snapshot import (
    KpiSnapshot,
    KpiThresholds,
    check_fail_fast,
    compute_kpi_snapshot,
    run_kpi_and_fail_fast,
    write_kpi_snapshot,
)


@pytest.fixture
def tmp_root(tmp_path, monkeypatch):
    """Isolate the Investment root to a tmp dir per test."""
    root = tmp_path / "Investment"
    root.mkdir()
    monkeypatch.setenv("NEOMIND_INVESTMENT_ROOT", str(root))
    return root


@pytest.fixture
def registered_project(tmp_root):
    investment_projects.register_project("proj", "test project")
    return "proj"


def _write(project_id: str, symbol: str, signal: str, confidence: int,
           reason: str = "ok", sources: list = None):
    investment_projects.write_analysis(
        project_id, symbol,
        {
            "signal": signal,
            "confidence": confidence,
            "reason": reason,
            "target_price": None,
            "risk_level": "medium",
            "sources": sources or [],
        },
    )


# ── Empty project ───────────────────────────────────────────────────────


def test_empty_project_zero_signals(registered_project):
    snap = compute_kpi_snapshot(registered_project)
    assert snap.total_signals == 0
    assert snap.buy_count == snap.hold_count == snap.sell_count == 0
    assert snap.signal_noise_ratio == 0.0
    assert snap.parse_fallback_rate == 0.0
    assert snap.avg_confidence is None
    assert snap.fail_fast_triggered is False


# ── Healthy mix ─────────────────────────────────────────────────────────


def test_healthy_mix_no_fail_fast(registered_project):
    for _ in range(5):
        _write(registered_project, "AAPL", "buy", 7, "good")
    for _ in range(4):
        _write(registered_project, "MSFT", "sell", 6, "weak")
    for _ in range(2):
        _write(registered_project, "NVDA", "hold", 5, "wait")

    snap = compute_kpi_snapshot(registered_project)
    assert snap.total_signals == 11
    assert snap.buy_count == 5
    assert snap.sell_count == 4
    assert snap.hold_count == 2
    assert snap.signal_noise_ratio == pytest.approx(9 / 11)
    assert snap.parse_fallback_rate == 0.0
    assert snap.avg_confidence is not None
    assert 5.5 < snap.avg_confidence < 6.5
    assert snap.fail_fast_triggered is False


# ── Parse-fallback rate fail-fast ───────────────────────────────────────


def test_high_parse_fallback_rate_triggers_fail_fast(registered_project):
    _write(registered_project, "AAPL", "buy", 7, "ok")
    _write(registered_project, "AAPL", "hold", 1, "[parse_fallback] bad json")
    _write(registered_project, "AAPL", "hold", 1, "[parse_fallback] another")
    _write(registered_project, "AAPL", "hold", 1, "[parse_fallback] yet another")

    # 3/4 = 75% parse_fallback > 20% threshold
    snap = compute_kpi_snapshot(registered_project)
    assert snap.parse_fallback_count == 3
    assert snap.parse_fallback_rate == pytest.approx(0.75)
    assert snap.fail_fast_triggered is True
    assert any("parse_fallback" in r for r in snap.fail_fast_reasons)


def test_low_parse_fallback_does_not_trigger(registered_project):
    _write(registered_project, "AAPL", "buy", 7, "ok")
    for _ in range(20):
        _write(registered_project, "AAPL", "buy", 7, "ok")
    _write(registered_project, "AAPL", "hold", 1, "[parse_fallback] rare")

    snap = compute_kpi_snapshot(registered_project)
    # 1/22 < 20%
    assert snap.parse_fallback_rate < 0.20
    # Also high signal_noise so no other trigger
    assert snap.fail_fast_triggered is False


# ── Signal-noise fail-fast (observer mode) ──────────────────────────────


def test_observer_mode_triggers_fail_fast(registered_project):
    """All holds, ≥10 samples → signal_noise=0 < 10% → fail_fast."""
    for _ in range(15):
        _write(registered_project, "AAPL", "hold", 5, "waiting")

    snap = compute_kpi_snapshot(registered_project)
    assert snap.signal_noise_ratio == 0.0
    assert snap.fail_fast_triggered is True
    assert any("observer mode" in r for r in snap.fail_fast_reasons)


def test_observer_mode_below_min_samples_does_not_trigger(registered_project):
    """All holds but only 5 samples — below the 10-sample floor → no trigger."""
    for _ in range(5):
        _write(registered_project, "AAPL", "hold", 5, "waiting")

    snap = compute_kpi_snapshot(registered_project)
    assert snap.signal_noise_ratio == 0.0
    # Not triggered: total < min_signals_for_noise_check
    assert snap.fail_fast_triggered is False


# ── Window filter ───────────────────────────────────────────────────────


def test_window_filter_excludes_old_analyses(registered_project, monkeypatch):
    """Analyses outside the window must not count."""
    # Old analysis: stamp a file manually so written_at is 30 days ago
    import json
    from pathlib import Path

    proj_dir = investment_projects.get_project_dir(registered_project)
    old_dt = datetime.now() - timedelta(days=30)
    old_file = proj_dir / "analyses" / "old.json"
    old_file.write_text(
        json.dumps(
            {
                "project_id": registered_project,
                "symbol": "AAPL",
                "written_at": old_dt.isoformat(),
                "signal": {
                    "signal": "buy",
                    "confidence": 7,
                    "reason": "old",
                    "target_price": None,
                    "risk_level": "medium",
                    "sources": [],
                },
            }
        )
    )
    # Recent analysis inside window
    _write(registered_project, "MSFT", "sell", 6)

    snap = compute_kpi_snapshot(registered_project, window_days=14)
    # Only the recent one counts
    assert snap.total_signals == 1
    assert snap.sell_count == 1
    assert snap.buy_count == 0


def test_custom_now_freezes_window(registered_project, monkeypatch):
    """Inject a clock so tests can reason about window timing deterministically."""
    _write(registered_project, "AAPL", "buy", 7, "ok")
    far_future = datetime.now() + timedelta(days=100)
    snap = compute_kpi_snapshot(registered_project, window_days=14, now=far_future)
    # Our 'now' is 100 days in the future so recent analysis is outside window
    assert snap.total_signals == 0


# ── Threshold overrides ─────────────────────────────────────────────────


def test_threshold_override_can_disable_fail_fast(registered_project):
    for _ in range(20):
        _write(registered_project, "AAPL", "hold", 5, "[parse_fallback] bad")

    # Default thresholds → would trigger (100% parse_fallback + 0% noise)
    default_snap = compute_kpi_snapshot(registered_project)
    assert default_snap.fail_fast_triggered is True

    # Relaxed thresholds → no trigger
    relaxed = KpiThresholds(
        max_parse_fallback_rate=1.0,
        min_signal_noise_ratio=0.0,
        min_signals_for_noise_check=100,
    )
    relaxed_snap = compute_kpi_snapshot(registered_project, thresholds=relaxed)
    assert relaxed_snap.fail_fast_triggered is False


# ── write_kpi_snapshot ──────────────────────────────────────────────────


def test_write_kpi_snapshot_appends_to_weekly_jsonl(registered_project):
    import json
    _write(registered_project, "AAPL", "buy", 7)
    _write(registered_project, "MSFT", "sell", 6)

    snap = write_kpi_snapshot(registered_project)
    assert isinstance(snap, KpiSnapshot)
    kpi_file = (
        investment_projects.get_project_dir(registered_project)
        / "kpi"
        / "weekly.jsonl"
    )
    lines = kpi_file.read_text().strip().split("\n")
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["total_signals"] == 2
    assert record["project_id"] == "proj"
    assert "recorded_at" in record  # added by investment_projects.kpi_snapshot


# ── check_fail_fast (SharedMemory integration via mock) ─────────────────


def test_check_fail_fast_records_when_triggered():
    snap = KpiSnapshot(
        project_id="proj",
        window_days=14,
        window_start=datetime.now().isoformat(),
        window_end=datetime.now().isoformat(),
        total_signals=15,
        buy_count=0,
        hold_count=15,
        sell_count=0,
        signal_noise_ratio=0.0,
        avg_confidence=5.0,
        parse_fallback_count=0,
        parse_fallback_rate=0.0,
        fail_fast_triggered=True,
        fail_fast_reasons=["observer mode"],
    )
    mem = MagicMock()
    result = check_fail_fast(snap, shared_memory=mem, source_instance="fin-rt")
    assert result is True
    mem.record_feedback.assert_called_once()
    kwargs = mem.record_feedback.call_args.kwargs
    assert kwargs["feedback_type"] == "fail_fast"
    assert kwargs["source_mode"] == "fin"
    assert kwargs["source_instance"] == "fin-rt"
    assert kwargs["project_id"] == "proj"
    # Content is a JSON blob — verify it parses and contains the kpi
    import json
    payload = json.loads(kwargs["content"])
    assert payload["kpi"]["total_signals"] == 15


def test_check_fail_fast_no_op_when_not_triggered():
    snap = KpiSnapshot(
        project_id="proj",
        window_days=14,
        window_start="",
        window_end="",
        total_signals=5,
        buy_count=3,
        hold_count=1,
        sell_count=1,
        signal_noise_ratio=0.8,
        avg_confidence=7.0,
        parse_fallback_count=0,
        parse_fallback_rate=0.0,
        fail_fast_triggered=False,
    )
    mem = MagicMock()
    result = check_fail_fast(snap, shared_memory=mem)
    assert result is False
    mem.record_feedback.assert_not_called()


def test_check_fail_fast_survives_memory_exception():
    snap = KpiSnapshot(
        project_id="proj",
        window_days=14,
        window_start="",
        window_end="",
        total_signals=15,
        buy_count=0,
        hold_count=15,
        sell_count=0,
        signal_noise_ratio=0.0,
        avg_confidence=5.0,
        parse_fallback_count=0,
        parse_fallback_rate=0.0,
        fail_fast_triggered=True,
        fail_fast_reasons=["observer mode"],
    )
    mem = MagicMock()
    mem.record_feedback.side_effect = RuntimeError("db down")
    # Should not crash the caller
    result = check_fail_fast(snap, shared_memory=mem)
    assert result is False


# ── run_kpi_and_fail_fast end-to-end ────────────────────────────────────


def test_run_kpi_and_fail_fast_writes_and_triggers(registered_project):
    for _ in range(15):
        _write(registered_project, "AAPL", "hold", 5, "waiting")

    mem = MagicMock()
    snap = run_kpi_and_fail_fast(
        registered_project, shared_memory=mem, write=True,
    )

    assert snap.fail_fast_triggered is True
    # Wrote to kpi/weekly.jsonl
    kpi_file = (
        investment_projects.get_project_dir(registered_project)
        / "kpi"
        / "weekly.jsonl"
    )
    assert kpi_file.exists()
    # Recorded fail_fast feedback
    mem.record_feedback.assert_called_once()


def test_run_kpi_and_fail_fast_write_false_skips_file(registered_project):
    _write(registered_project, "AAPL", "buy", 7)
    mem = MagicMock()
    run_kpi_and_fail_fast(registered_project, shared_memory=mem, write=False)
    kpi_file = (
        investment_projects.get_project_dir(registered_project)
        / "kpi"
        / "weekly.jsonl"
    )
    assert not kpi_file.exists()
