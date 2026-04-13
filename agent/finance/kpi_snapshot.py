"""
KPI snapshot + fail-fast hook for fin persona investment projects.

Reads the analysis JSON files persisted under
``~/Desktop/Investment/<project_id>/analyses/`` (via Phase 0's
``investment_projects`` data firewall), computes operational KPIs over
a rolling window, optionally writes the snapshot back to
``<project>/kpi/weekly.jsonl``, and triggers a fail-fast signal via
``SharedMemory.record_feedback`` when the fin persona needs to drop to
rules-only mode on next boot.

Why this module exists:

The Investment v1 plan (Round 2-3) required a quantitative fail-fast
mechanism — "if accuracy < 50% over 2 weeks, switch to rules-only".
That design assumes we already label every signal with a ground-truth
outcome (3-day forward price movement). Outcome labeling is a separate
phase; this module ships the operational half that works with data we
already have:

  - **parse_fallback_rate** — fraction of signals whose reason starts
    with ``[parse_fallback]``. High rate means the LLM is producing
    garbage structured output; prompt needs attention before anything
    else matters.
  - **signal_noise_ratio** — (buy + sell) / total. Near-zero means
    the agent is stuck in observer mode and never recommending action.
  - **accuracy** — ``Optional[float]``, set to None until outcome
    tracking lands. Fail-fast still fires on the first two even when
    accuracy is None.

Contract: plans/2026-04-12_fin_deepening_fusion_plan.md §4 Phase 3.
"""

from __future__ import annotations

import json
import logging
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import investment_projects

logger = logging.getLogger(__name__)

__all__ = [
    "KpiThresholds",
    "KpiSnapshot",
    "compute_kpi_snapshot",
    "write_kpi_snapshot",
    "check_fail_fast",
    "run_kpi_and_fail_fast",
]


# ── Thresholds ──────────────────────────────────────────────────────────


@dataclass
class KpiThresholds:
    """Fail-fast thresholds. Override per project as needed."""

    # Trigger fail-fast if > this fraction of signals couldn't be parsed
    max_parse_fallback_rate: float = 0.20

    # Trigger fail-fast if < this fraction of signals are actionable
    # (buy or sell). Requires min_signals_for_noise_check samples to fire.
    min_signal_noise_ratio: float = 0.10
    min_signals_for_noise_check: int = 10

    # Trigger fail-fast if known accuracy < this (None-aware: only
    # applies when an accuracy value is actually present)
    min_accuracy: float = 0.50


# ── Snapshot dataclass ──────────────────────────────────────────────────


@dataclass
class KpiSnapshot:
    """Result of ``compute_kpi_snapshot``. Serialisable via ``to_dict``."""

    project_id: str
    window_days: int
    window_start: str  # ISO8601
    window_end: str
    total_signals: int
    buy_count: int
    hold_count: int
    sell_count: int
    signal_noise_ratio: float
    avg_confidence: Optional[float]
    parse_fallback_count: int
    parse_fallback_rate: float
    accuracy: Optional[float] = None
    fail_fast_triggered: bool = False
    fail_fast_reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "window_days": self.window_days,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "total_signals": self.total_signals,
            "buy_count": self.buy_count,
            "hold_count": self.hold_count,
            "sell_count": self.sell_count,
            "signal_noise_ratio": self.signal_noise_ratio,
            "avg_confidence": self.avg_confidence,
            "parse_fallback_count": self.parse_fallback_count,
            "parse_fallback_rate": self.parse_fallback_rate,
            "accuracy": self.accuracy,
            "fail_fast_triggered": self.fail_fast_triggered,
            "fail_fast_reasons": list(self.fail_fast_reasons),
        }


# ── Read analyses ───────────────────────────────────────────────────────


def _parse_analysis_file(path: Path) -> Optional[Dict[str, Any]]:
    """Best-effort load of one analysis JSON. Returns None on any error."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.debug("kpi_snapshot: skipping %s (%s)", path, exc)
        return None


def _iter_analyses_in_window(
    project_id: str, window_start: datetime, window_end: datetime
) -> List[Dict[str, Any]]:
    """Yield analysis dicts whose ``written_at`` falls inside the window."""
    proj_dir = investment_projects.get_project_dir(project_id)
    analyses_dir = proj_dir / "analyses"
    if not analyses_dir.exists():
        return []

    out: List[Dict[str, Any]] = []
    for path in sorted(analyses_dir.glob("*.json")):
        data = _parse_analysis_file(path)
        if not data:
            continue
        written_at_str = data.get("written_at")
        if not isinstance(written_at_str, str):
            continue
        try:
            written_at = datetime.fromisoformat(written_at_str)
        except ValueError:
            continue
        if window_start <= written_at <= window_end:
            out.append(data)
    return out


# ── Compute ─────────────────────────────────────────────────────────────


def compute_kpi_snapshot(
    project_id: str,
    window_days: int = 14,
    now: Optional[datetime] = None,
    thresholds: Optional[KpiThresholds] = None,
) -> KpiSnapshot:
    """Compute KPIs for a project over the trailing ``window_days`` window.

    Args:
        project_id: Investment project id (must be registered).
        window_days: How many trailing days to look back.
        now: Reference "end of window" timestamp. Defaults to
            ``datetime.now()`` — tests can inject a fixed clock.
        thresholds: Optional override for fail-fast thresholds.

    Returns:
        A populated ``KpiSnapshot`` (also with ``fail_fast_triggered``
        and ``fail_fast_reasons`` filled). Does NOT write anywhere — use
        ``write_kpi_snapshot`` or ``run_kpi_and_fail_fast`` for that.
    """
    if window_days <= 0:
        raise ValueError(f"window_days must be positive, got {window_days}")

    thresholds = thresholds or KpiThresholds()
    end = now or datetime.now()
    start = end - timedelta(days=window_days)

    rows = _iter_analyses_in_window(project_id, start, end)

    buy = hold = sell = 0
    confidences: List[int] = []
    parse_fallback = 0

    for row in rows:
        signal_obj = row.get("signal") or {}
        sig = signal_obj.get("signal")
        if sig == "buy":
            buy += 1
        elif sig == "sell":
            sell += 1
        else:
            hold += 1  # default any unknown to hold-bucket
        conf = signal_obj.get("confidence")
        if isinstance(conf, (int, float)):
            confidences.append(int(conf))
        reason = signal_obj.get("reason", "")
        if isinstance(reason, str) and reason.startswith("[parse_fallback]"):
            parse_fallback += 1

    total = buy + hold + sell
    if total > 0:
        signal_noise = (buy + sell) / total
        parse_fallback_rate = parse_fallback / total
        avg_conf: Optional[float] = (
            statistics.mean(confidences) if confidences else None
        )
    else:
        signal_noise = 0.0
        parse_fallback_rate = 0.0
        avg_conf = None

    snap = KpiSnapshot(
        project_id=project_id,
        window_days=window_days,
        window_start=start.isoformat(),
        window_end=end.isoformat(),
        total_signals=total,
        buy_count=buy,
        hold_count=hold,
        sell_count=sell,
        signal_noise_ratio=signal_noise,
        avg_confidence=avg_conf,
        parse_fallback_count=parse_fallback,
        parse_fallback_rate=parse_fallback_rate,
        accuracy=None,  # populated by future outcome tracker phase
    )

    # Evaluate fail-fast triggers
    reasons: List[str] = []
    if total > 0 and parse_fallback_rate > thresholds.max_parse_fallback_rate:
        reasons.append(
            f"parse_fallback_rate {parse_fallback_rate:.2%} exceeds "
            f"{thresholds.max_parse_fallback_rate:.0%} threshold — prompt drift"
        )
    if (
        total >= thresholds.min_signals_for_noise_check
        and signal_noise < thresholds.min_signal_noise_ratio
    ):
        reasons.append(
            f"signal_noise_ratio {signal_noise:.2%} below "
            f"{thresholds.min_signal_noise_ratio:.0%} threshold "
            f"(only {buy + sell} actionable out of {total}) — observer mode"
        )
    if snap.accuracy is not None and snap.accuracy < thresholds.min_accuracy:
        reasons.append(
            f"accuracy {snap.accuracy:.2%} below "
            f"{thresholds.min_accuracy:.0%} threshold"
        )

    snap.fail_fast_triggered = bool(reasons)
    snap.fail_fast_reasons = reasons
    return snap


# ── Write ───────────────────────────────────────────────────────────────


def write_kpi_snapshot(
    project_id: str,
    window_days: int = 14,
    now: Optional[datetime] = None,
    thresholds: Optional[KpiThresholds] = None,
) -> KpiSnapshot:
    """Compute and append a KPI snapshot to ``<project>/kpi/weekly.jsonl``."""
    snap = compute_kpi_snapshot(
        project_id=project_id,
        window_days=window_days,
        now=now,
        thresholds=thresholds,
    )
    investment_projects.kpi_snapshot(project_id, snap.to_dict())
    return snap


# ── Fail-fast hook ──────────────────────────────────────────────────────


def check_fail_fast(
    snap: KpiSnapshot,
    shared_memory,
    source_mode: str = "fin",
    source_instance: Optional[str] = None,
) -> bool:
    """If ``snap.fail_fast_triggered``, record a feedback entry so the fin
    persona sees it on next boot and can downgrade to rules-only.

    Args:
        snap: A ``KpiSnapshot`` already evaluated by ``compute_kpi_snapshot``.
        shared_memory: A ``SharedMemory`` instance (injected for testability;
            callers typically pass the project's live instance).
        source_mode: The persona that generated this trigger. Defaults to
            "fin" since that's where the rule lives.
        source_instance: Optional fleet instance name (e.g. "fin-rt").

    Returns:
        True if a fail_fast entry was written, False otherwise.
    """
    if not snap.fail_fast_triggered:
        return False

    payload = {
        "kpi": snap.to_dict(),
        "triggered_at": datetime.now().isoformat(),
    }
    content = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    try:
        shared_memory.record_feedback(
            feedback_type="fail_fast",
            content=content,
            source_mode=source_mode,
            source_instance=source_instance,
            project_id=snap.project_id,
        )
        logger.warning(
            "kpi_snapshot: fail_fast triggered for project %s — %s",
            snap.project_id,
            "; ".join(snap.fail_fast_reasons),
        )
        return True
    except Exception as exc:
        logger.error(
            "kpi_snapshot: failed to record fail_fast feedback: %s", exc
        )
        return False


# ── Convenience ─────────────────────────────────────────────────────────


def run_kpi_and_fail_fast(
    project_id: str,
    shared_memory,
    window_days: int = 14,
    now: Optional[datetime] = None,
    thresholds: Optional[KpiThresholds] = None,
    source_mode: str = "fin",
    source_instance: Optional[str] = None,
    write: bool = True,
) -> KpiSnapshot:
    """One-shot: compute KPI, optionally write to ``kpi/weekly.jsonl``,
    and record fail_fast feedback if triggered."""
    if write:
        snap = write_kpi_snapshot(
            project_id=project_id,
            window_days=window_days,
            now=now,
            thresholds=thresholds,
        )
    else:
        snap = compute_kpi_snapshot(
            project_id=project_id,
            window_days=window_days,
            now=now,
            thresholds=thresholds,
        )

    check_fail_fast(
        snap,
        shared_memory=shared_memory,
        source_mode=source_mode,
        source_instance=source_instance,
    )
    return snap
