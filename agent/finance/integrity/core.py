"""Integrity-check runner — matches the ``lattice/selfcheck.py`` idiom.

Plain functions, manually appended in ``run_integrity_check``. No
decorator-based auto-discovery: the cost of "register a new check by
appending to a list" is one line, and the value of having ONE pattern
across the project (selfcheck for lattice, integrity for fin DB) is
worth more than auto-discovery.

Adding a new check:
  1. Write ``check_X(conn) -> dict`` returning ``{pass, detail, offenders?}``
     under one of ``checks/{schema,attribution,temporal,compliance}.py``
  2. Import it here in ``_collect_checks``
  3. Append a tuple ``(name, label, layer, fn)``

Cross-references:
  - This is the **storage-layer** counterpart to the **LLM-output-layer**
    rules in ``agent/finance/response_validator.py`` (the Five Iron
    Rules). Specifically, ``market_data_has_source`` is the persistence
    enforcement of Rule 3 ("every data point has source + timestamp").
  - The lattice has its own ``run_selfcheck()`` over the lattice graph;
    this module covers the SQLite store. Both return the same payload
    shape so the UI badge widget renders either with no plumbing
    differences.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from agent.finance.persistence import connect, ensure_schema

logger = logging.getLogger(__name__)


# Each registered check is a tuple: (name, label, layer, fn)
CheckTuple = Tuple[str, str, str, Callable[[sqlite3.Connection], Dict[str, Any]]]


def _collect_checks() -> List[CheckTuple]:
    """The single source of truth for "what gets checked".

    Imports happen lazily here so module-import order is safe and we
    can run the bare framework without pulling in every check's deps.
    """
    from agent.finance.integrity.checks.attribution import (
        check_market_data_attributed,
        check_scheduler_registry_alignment,
        check_signal_run_fk,
    )
    from agent.finance.integrity.checks.compliance import (
        check_holding_period,
        check_pdt_window,
        check_wash_sale_window,
    )
    from agent.finance.integrity.checks.schema import (
        check_lot_idempotency_unique,
        check_market_data_pk_unique,
        check_schema_version,
        check_signal_dedup_unique,
    )
    from agent.finance.integrity.checks.temporal import (
        check_duration_arithmetic,
        check_lot_dates,
        check_run_durations,
    )
    from agent.finance.integrity.checks.viz import (
        check_ui_data_sources_resolvable,
    )

    return [
        # ── Schema layer ──
        ("schema_version_matches",     "DB schema_version equals code SCHEMA_VERSION",
         "data", check_schema_version),
        ("signal_dedup_keys_unique",   "strategy_signals.dedup_key has no duplicates",
         "data", check_signal_dedup_unique),
        ("lot_idempotency_keys_unique","tax_lots.idempotency_key has no duplicates (when set)",
         "data", check_lot_idempotency_unique),
        ("market_data_pk_unique",      "market_data_daily PK has no duplicates",
         "data", check_market_data_pk_unique),

        # ── Attribution layer (storage-side enforcement of
        #    response_validator's Five Iron Rules — Rule 3 mainly) ──
        ("market_data_has_source",     "Every market_data_daily row has source + fetched_at",
         "data", check_market_data_attributed),
        ("signals_have_run_ref",       "Every strategy_signal.run_id references an existing analysis_run",
         "data", check_signal_run_fk),
        ("scheduler_jobs_match_registry","Every registered job has a scheduler_jobs row, no orphans",
         "data", check_scheduler_registry_alignment),

        # ── Temporal layer ──
        ("runs_temporally_consistent", "Every completed run has started_at <= completed_at, dur >= 0",
         "compute", check_run_durations),
        ("lots_temporally_consistent", "Every closed tax_lot has close_date >= open_date",
         "compute", check_lot_dates),
        ("run_durations_match_timestamps","duration_seconds equals completed_at - started_at",
         "compute", check_duration_arithmetic),

        # ── Compliance layer ──
        ("wash_sale_within_window",    "Every wash_sale_event has |sell_date - replacement_date| <= 30",
         "compliance", check_wash_sale_window),
        ("pdt_within_5_trading_days",  "Every pdt_round_trip references trades <= 5 trading days apart",
         "compliance", check_pdt_window),
        ("holding_period_classification","Closed lots' holding_period_qualified matches close_date - open_date",
         "compliance", check_holding_period),

        # ── Visualization layer (Task 15) ──
        # Closes the audit loop on the UI side: every documented
        # data-source in a UI component must resolve to a real value.
        # See agent/finance/integrity/checks/viz.py for the manifest.
        ("ui_data_sources_resolvable",
         "Every UI data-source attribute resolves to a real backend value",
         "viz", check_ui_data_sources_resolvable),
    ]


# Public surface kept for backward compat with the UI/CLI imports —
# computed lazily on first access so simply importing this module is
# free.
def _checks_cached() -> List[CheckTuple]:
    if not hasattr(_checks_cached, "_v"):
        _checks_cached._v = _collect_checks()  # type: ignore[attr-defined]
    return _checks_cached._v  # type: ignore[attr-defined]


# Backward-compat re-exports (CLI imports CHECKS for layer counting).
class _CheckSpecLike:
    __slots__ = ("name", "label", "layer", "func")
    def __init__(self, t: CheckTuple) -> None:
        self.name, self.label, self.layer, self.func = t


def _checks_as_specs() -> List[_CheckSpecLike]:
    return [_CheckSpecLike(t) for t in _checks_cached()]


CHECKS = _checks_as_specs  # callable; older code did `from . import CHECKS` as list


# ── Report types ─────────────────────────────────────────────────────


@dataclass
class CheckResult:
    name: str
    label: str
    layer: str
    passed: bool
    detail: str
    offenders: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "name": self.name,
            "label": self.label,
            "layer": self.layer,
            "pass": self.passed,
            "detail": self.detail,
        }
        if self.offenders:
            d["offenders"] = self.offenders
        if self.error is not None:
            d["error"] = self.error
        return d


@dataclass
class IntegrityReport:
    summary: str
    all_pass: bool
    timestamp: str
    checks: List[CheckResult]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "summary": self.summary,
            "all_pass": self.all_pass,
            "timestamp": self.timestamp,
            "checks": [c.to_dict() for c in self.checks],
        }


# ── Runner ───────────────────────────────────────────────────────────


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def run_integrity_check(
    layer_filter: Optional[str] = None,
    db_conn: Optional[sqlite3.Connection] = None,
) -> Dict[str, Any]:
    """Run every check (or just one layer) and return a report dict.

    A crashing check yields ``{"pass": False, "error": "..."}`` rather
    than propagating — the report must always come back well-formed,
    or the UI badge would be unable to surface "the framework itself
    is broken" (the worst of all signals).
    """
    ensure_schema()
    selected = [
        t for t in _checks_cached()
        if layer_filter is None or t[2] == layer_filter
    ]

    if db_conn is not None:
        results = [_run_one(t, db_conn) for t in selected]
    else:
        with connect() as conn:
            results = [_run_one(t, conn) for t in selected]

    passed = sum(1 for r in results if r.passed)
    return IntegrityReport(
        summary=f"{passed}/{len(results)} pass",
        all_pass=passed == len(results),
        timestamp=_now_iso(),
        checks=results,
    ).to_dict()


def _run_one(t: CheckTuple, conn: sqlite3.Connection) -> CheckResult:
    name, label, layer, fn = t
    try:
        out = fn(conn)
    except Exception as exc:  # noqa: BLE001
        logger.exception("integrity check %r crashed", name)
        return CheckResult(
            name=name, label=label, layer=layer, passed=False,
            detail="check raised an exception",
            error=f"{type(exc).__name__}: {exc}",
        )
    return CheckResult(
        name=name, label=label, layer=layer,
        passed=bool(out.get("pass", False)),
        detail=str(out.get("detail", "")),
        offenders=list(out.get("offenders", [])),
    )
