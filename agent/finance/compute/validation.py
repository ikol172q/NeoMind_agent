"""Phase B7 — per-step validation framework.

Every compute_run can carry a ``ValidationReport``: an ordered list
of ``ValidationCheck`` rows that document which post-condition checks
ran and what state they ended in.  Per operator instruction, ``FAIL``
shows a red badge but does NOT block the result from being served —
the user sees the failure in the UI and decides whether to re-run.

The 7 pipeline steps come from the design doc
(docs/design/2026-04-26_provenance-architecture.md §
"Validation framework"):

    1. collect    — Crawler:     response 2xx; content_length > N;
                                 charset detected; rate-limit honored;
                                 supersedes report
    2. save       — RawStore:    sha256 of bytes equals filename;
                                 meta.json valid; FTS5 row inserted
    3. load       — RawStore:    sha256 of read bytes equals expected
                                 (silent disk corruption check)
    4. algorithm  — Observation: bit-identical when re-run on same
                                 input; obs_id stability
    5. llm        — Theme/Call:  response valid JSON; matches schema;
                                 cited_numbers exist verbatim;
                                 fallback narrative ≠ silent success
    6. distill    — Aggregator:  every theme.grounds resolves; every
                                 call.grounds resolves; counts within
                                 historical p10–p90
    7. visualize  — UI:          every chip data-source resolves to
                                 real backend value (already in place
                                 via integrity check)

State naming borrows Dagster's vocabulary so we can emit OpenLineage
events later if desired.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)


# ── Public types ──────────────────────────────────────────────────


# State enum.  Borrow Dagster's freshness vocabulary so we can later
# emit OpenLineage events without renaming.
ValidationState = str  # one of "pass" / "warn" / "fail" / "unknown"

VALID_STATES: tuple[str, ...] = ("pass", "warn", "fail", "unknown")

# Step enum.  Aligns with the 7 design-doc rows.  Stored as a string
# rather than an enum so legacy SQL rows survive a future enum bump.
ValidationStep = str
VALID_STEPS: tuple[str, ...] = (
    "collect",
    "save",
    "load",
    "algorithm",
    "llm",
    "distill",
    "visualize",
)


@dataclass(frozen=True)
class ValidationCheck:
    """One run of one named check.  All fields are JSON-serialisable.

    Construct via the helper functions ``passing()`` / ``warn()`` /
    ``fail()`` rather than this constructor directly — the helpers
    enforce state vocabulary at the boundary.
    """

    name:           str            # e.g. "obs.row_count_within_p10_p90"
    step:           str            # one of VALID_STEPS
    state:          str            # one of VALID_STATES
    message:        str            # human-readable
    actual_value:   Optional[float] = None
    expected_value: Optional[float] = None
    extra:          Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # Drop nulls to keep the JSON snapshot lean.
        return {k: v for k, v in d.items() if v is not None}


def passing(name: str, step: str, message: str = "ok", *, actual: Optional[float] = None,
            expected: Optional[float] = None, extra: Optional[Dict[str, Any]] = None) -> ValidationCheck:
    return ValidationCheck(name=name, step=step, state="pass", message=message,
                           actual_value=actual, expected_value=expected, extra=extra)


def warn(name: str, step: str, message: str, *, actual: Optional[float] = None,
         expected: Optional[float] = None, extra: Optional[Dict[str, Any]] = None) -> ValidationCheck:
    return ValidationCheck(name=name, step=step, state="warn", message=message,
                           actual_value=actual, expected_value=expected, extra=extra)


def failing(name: str, step: str, message: str, *, actual: Optional[float] = None,
            expected: Optional[float] = None, extra: Optional[Dict[str, Any]] = None) -> ValidationCheck:
    return ValidationCheck(name=name, step=step, state="fail", message=message,
                           actual_value=actual, expected_value=expected, extra=extra)


def unknown(name: str, step: str, message: str = "not evaluated", *,
            extra: Optional[Dict[str, Any]] = None) -> ValidationCheck:
    return ValidationCheck(name=name, step=step, state="unknown", message=message, extra=extra)


# ── ValidationReport ──────────────────────────────────────────────


@dataclass(frozen=True)
class ValidationReport:
    """Aggregate report across one compute_run.  Built by the
    runner that called the compute function — each builder returns a
    list of checks; the aggregator wraps them in a report and persists
    via ``ValidationStore.put_report``.
    """

    compute_run_id: str
    checks:         List[ValidationCheck] = field(default_factory=list)

    # ── derived properties ──

    @property
    def n_total(self) -> int:
        return len(self.checks)

    @property
    def n_pass(self) -> int:
        return sum(1 for c in self.checks if c.state == "pass")

    @property
    def n_warn(self) -> int:
        return sum(1 for c in self.checks if c.state == "warn")

    @property
    def n_fail(self) -> int:
        return sum(1 for c in self.checks if c.state == "fail")

    @property
    def n_unknown(self) -> int:
        return sum(1 for c in self.checks if c.state == "unknown")

    @property
    def overall_state(self) -> ValidationState:
        """Roll-up: if any fail → fail, else any warn → warn, else if
        all unknown → unknown, else pass."""
        if self.n_fail > 0:
            return "fail"
        if self.n_warn > 0:
            return "warn"
        if self.n_pass == 0 and self.n_unknown > 0:
            return "unknown"
        return "pass"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "compute_run_id": self.compute_run_id,
            "n_total":        self.n_total,
            "n_pass":         self.n_pass,
            "n_warn":         self.n_warn,
            "n_fail":         self.n_fail,
            "n_unknown":      self.n_unknown,
            "overall_state":  self.overall_state,
            "checks":         [c.to_dict() for c in self.checks],
        }


# ── Store: SQLite-backed persistence ──────────────────────────────


_SCHEMA_VALIDATIONS = """
CREATE TABLE IF NOT EXISTS compute_validations (
    compute_run_id TEXT NOT NULL,
    check_name     TEXT NOT NULL,
    step           TEXT NOT NULL,
    state          TEXT NOT NULL,
    message        TEXT NOT NULL,
    actual_value   REAL,
    expected_value REAL,
    extra_json     TEXT,
    ts             TEXT NOT NULL,
    PRIMARY KEY (compute_run_id, check_name)
);

CREATE INDEX IF NOT EXISTS idx_validations_state
    ON compute_validations(state, step);

CREATE INDEX IF NOT EXISTS idx_validations_run
    ON compute_validations(compute_run_id);
"""


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class ValidationStore:
    """SQLite-backed validation persistence layer.  Lives inside the
    same ``_dep_index.sqlite`` as ``compute_runs`` (in B4) so a single
    transaction can persist both — a compute_run row + its
    validations are guaranteed to land together or roll back together.

    Construct via :meth:`for_dep_cache` so the path matches what
    DepCache uses.
    """

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        with self._open() as conn:
            conn.executescript(_SCHEMA_VALIDATIONS)

    @classmethod
    def for_dep_cache(cls, dep_cache: Any) -> "ValidationStore":
        """Build a ValidationStore that shares the DepCache's SQLite."""
        return cls(str(dep_cache.db_path))

    def _open(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    # ── write ──

    def put_report(self, report: ValidationReport) -> None:
        """Persist every check in a single transaction.  Re-runs of
        the same (compute_run_id, check_name) replace the prior row
        (PRIMARY KEY ON CONFLICT REPLACE) so a runner that recomputes
        a check doesn't accumulate duplicates."""
        if not report.checks:
            return
        rows: List[tuple[Any, ...]] = []
        ts = _utcnow_iso()
        for c in report.checks:
            rows.append((
                report.compute_run_id,
                c.name,
                c.step,
                c.state,
                c.message,
                c.actual_value,
                c.expected_value,
                json.dumps(c.extra, sort_keys=True, ensure_ascii=False) if c.extra else None,
                ts,
            ))
        conn = self._open()
        try:
            conn.executemany(
                """
                INSERT OR REPLACE INTO compute_validations
                  (compute_run_id, check_name, step, state, message,
                   actual_value, expected_value, extra_json, ts)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            conn.commit()
        finally:
            conn.close()

    # ── read ──

    def get_report(self, compute_run_id: str) -> Optional[ValidationReport]:
        conn = self._open()
        try:
            rows = conn.execute(
                """SELECT * FROM compute_validations
                       WHERE compute_run_id=? ORDER BY step, check_name""",
                (compute_run_id,),
            ).fetchall()
        finally:
            conn.close()
        if not rows:
            return None
        checks = [_row_to_check(r) for r in rows]
        return ValidationReport(compute_run_id=compute_run_id, checks=checks)

    def list_failing(
        self,
        *,
        step:  Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Cross-run aggregation: most recent fail/warn checks.
        Useful for an operator dashboard answering 'what's broken?'."""
        sql = (
            "SELECT * FROM compute_validations "
            "WHERE state IN ('fail','warn') "
        )
        params: list[Any] = []
        if step is not None:
            sql += "AND step=? "
            params.append(step)
        sql += "ORDER BY ts DESC LIMIT ?"
        params.append(int(limit))
        conn = self._open()
        try:
            rows = conn.execute(sql, params).fetchall()
        finally:
            conn.close()
        return [_row_to_check_dict(r) for r in rows]

    def aggregate_by_step(self) -> List[Dict[str, Any]]:
        """One row per (step, state) with counts.  Backs the cache-
        stats overview ("16 algorithm checks · 14 pass · 2 warn")."""
        conn = self._open()
        try:
            rows = conn.execute(
                """SELECT step, state, COUNT(*) AS n
                       FROM compute_validations
                       GROUP BY step, state
                       ORDER BY step, state"""
            ).fetchall()
        finally:
            conn.close()
        return [{"step": r["step"], "state": r["state"], "n": int(r["n"])} for r in rows]

    # ── rolling p10/p90 (anomaly detector) ──

    def percentile_bounds(
        self,
        check_name: str,
        *,
        n_samples: int = 30,
    ) -> Optional[tuple[float, float]]:
        """Compute (p10, p90) over the last ``n_samples`` PASS rows
        for ``check_name``.  Returns ``None`` when fewer than 5 samples
        exist (too few for a reliable bound).  Used by callers that
        want to flag today's value as an outlier — e.g. obs.row_count
        in the algorithm step.
        """
        conn = self._open()
        try:
            rows = conn.execute(
                """SELECT actual_value FROM compute_validations
                       WHERE check_name=? AND state='pass'
                         AND actual_value IS NOT NULL
                       ORDER BY ts DESC LIMIT ?""",
                (check_name, int(n_samples)),
            ).fetchall()
        finally:
            conn.close()
        vals = sorted(float(r["actual_value"]) for r in rows)
        if len(vals) < 5:
            return None
        # Linear interpolation percentile, simple closed-form.
        def pct(p: float) -> float:
            idx = (len(vals) - 1) * p
            lo = int(idx)
            hi = min(lo + 1, len(vals) - 1)
            return vals[lo] + (vals[hi] - vals[lo]) * (idx - lo)
        return pct(0.10), pct(0.90)


# ── helpers ───────────────────────────────────────────────────────


def _row_to_check(r: sqlite3.Row) -> ValidationCheck:
    extra = None
    if r["extra_json"]:
        try:
            extra = json.loads(r["extra_json"])
        except Exception:
            extra = None
    return ValidationCheck(
        name=           r["check_name"],
        step=           r["step"],
        state=          r["state"],
        message=        r["message"],
        actual_value=   r["actual_value"],
        expected_value= r["expected_value"],
        extra=          extra,
    )


def _row_to_check_dict(r: sqlite3.Row) -> Dict[str, Any]:
    d = dict(r)
    if d.get("extra_json"):
        try:
            d["extra"] = json.loads(d.pop("extra_json"))
        except Exception:
            d["extra"] = None
            d.pop("extra_json", None)
    else:
        d.pop("extra_json", None)
        d["extra"] = None
    return d


# ── Algorithm-step checks for L1 observations ────────────────────


def algorithm_checks_for_observations(
    *,
    rows_count:           int,
    inputs_summary:       Dict[str, Any],
    historical_bounds:    Optional[tuple[float, float]] = None,
) -> List[ValidationCheck]:
    """Return the algorithm-step ValidationCheck list for one
    observations build.  Caller passes ``historical_bounds`` from
    ``ValidationStore.percentile_bounds("obs.row_count_within_p10_p90")``
    if available; on the first ~5 runs we lack data so the bounds
    check is recorded as ``unknown`` (not ``warn``).
    """
    out: List[ValidationCheck] = []

    # 1. Did we produce any observations at all?  An empty list is a
    # warn (not fail) because some upstream-empty days are legitimate.
    if rows_count == 0:
        out.append(warn(
            name="obs.nonempty",
            step="algorithm",
            message="0 observations emitted — did the upstream synthesis "
                    "return any data?",
            actual=0.0,
        ))
    else:
        out.append(passing(
            name="obs.nonempty",
            step="algorithm",
            message=f"{rows_count} observations emitted",
            actual=float(rows_count),
        ))

    # 2. Row-count within historical p10–p90.  Reports the metric on
    # every run so future runs accumulate samples.
    if historical_bounds is not None and rows_count > 0:
        p10, p90 = historical_bounds
        if rows_count < p10 or rows_count > p90:
            out.append(warn(
                name="obs.row_count_within_p10_p90",
                step="algorithm",
                message=f"row_count={rows_count} outside historical "
                        f"[p10={p10:.0f}, p90={p90:.0f}]",
                actual=float(rows_count),
                expected=p90,
                extra={"p10": p10, "p90": p90},
            ))
        else:
            out.append(passing(
                name="obs.row_count_within_p10_p90",
                step="algorithm",
                message=f"row_count={rows_count} ∈ [p10={p10:.0f}, p90={p90:.0f}]",
                actual=float(rows_count),
                expected=p90,
                extra={"p10": p10, "p90": p90},
            ))
    else:
        # Bootstrap: not enough history to evaluate.  Still record the
        # actual_value so future runs get the sample.
        out.append(unknown(
            name="obs.row_count_within_p10_p90",
            step="algorithm",
            message="insufficient history (need ≥5 prior PASS samples)",
            extra={"actual": float(rows_count)},
        ))

    # 3. Inputs sanity: did we have at least one symbol AND at least
    # one news entry OR positions?  Empty inputs → useless output.
    n_sym = int(inputs_summary.get("n_symbols") or 0)
    n_news = int(inputs_summary.get("n_news_entries") or 0)
    has_pos = bool(inputs_summary.get("has_positions"))
    if n_sym == 0:
        out.append(warn(
            name="obs.inputs_have_symbols",
            step="algorithm",
            message="no symbols in input — watchlist + positions both empty?",
            actual=0.0,
        ))
    else:
        out.append(passing(
            name="obs.inputs_have_symbols",
            step="algorithm",
            message=f"{n_sym} symbols",
            actual=float(n_sym),
        ))

    if n_news == 0 and not has_pos:
        out.append(warn(
            name="obs.inputs_have_signal",
            step="algorithm",
            message="no news AND no positions — observations will be sparse",
        ))
    else:
        out.append(passing(
            name="obs.inputs_have_signal",
            step="algorithm",
            message=f"{n_news} news entries · positions={'yes' if has_pos else 'no'}",
        ))

    return out


# ── LLM-step checks for themes / calls ───────────────────────────


def llm_checks_for_themes(
    *,
    n_themes:        int,
    n_with_llm:      int,
    n_template_fallback: int,
) -> List[ValidationCheck]:
    """LLM-step checks for build_themes.  ``n_with_llm`` counts themes
    whose narrative came from the LLM; ``n_template_fallback`` counts
    themes that fell back to a deterministic template (LLM was
    unreachable, returned bad JSON, or failed cited_numbers
    validation).
    """
    out: List[ValidationCheck] = []

    if n_themes == 0:
        out.append(unknown(
            name="themes.llm_responded",
            step="llm",
            message="no themes to evaluate",
        ))
        return out

    fallback_ratio = (n_template_fallback / n_themes) if n_themes > 0 else 0.0
    if n_template_fallback == 0:
        out.append(passing(
            name="themes.llm_responded",
            step="llm",
            message=f"{n_with_llm}/{n_themes} themes have LLM narrative",
            actual=float(n_with_llm),
            expected=float(n_themes),
        ))
    elif fallback_ratio < 0.5:
        out.append(warn(
            name="themes.llm_responded",
            step="llm",
            message=f"{n_template_fallback}/{n_themes} themes fell back to "
                    f"template — partial LLM outage?",
            actual=float(n_template_fallback),
            expected=0.0,
        ))
    else:
        out.append(failing(
            name="themes.llm_responded",
            step="llm",
            message=f"{n_template_fallback}/{n_themes} themes fell back to "
                    f"template — LLM provider down?",
            actual=float(n_template_fallback),
            expected=0.0,
        ))

    return out


def llm_checks_for_calls(
    *,
    n_calls:               int,
    n_grounds_resolved:    int,
    n_grounds_unresolved:  int,
) -> List[ValidationCheck]:
    """LLM-step checks for build_calls.  ``n_grounds_resolved`` /
    ``n_grounds_unresolved`` are summed across every call's
    ``grounds`` list — each ground is supposed to resolve to a real
    L2 theme or L1 observation; unresolved grounds mean the LLM
    invented a citation.
    """
    out: List[ValidationCheck] = []

    if n_calls == 0:
        out.append(unknown(
            name="calls.grounds_resolve",
            step="llm",
            message="no calls to evaluate",
        ))
        return out

    total = n_grounds_resolved + n_grounds_unresolved
    if n_grounds_unresolved == 0:
        out.append(passing(
            name="calls.grounds_resolve",
            step="llm",
            message=f"{total} grounds resolved across {n_calls} calls",
            actual=float(n_grounds_resolved),
            expected=float(total),
        ))
    elif n_grounds_unresolved <= 2:
        out.append(warn(
            name="calls.grounds_resolve",
            step="llm",
            message=f"{n_grounds_unresolved}/{total} grounds unresolved",
            actual=float(n_grounds_resolved),
            expected=float(total),
        ))
    else:
        out.append(failing(
            name="calls.grounds_resolve",
            step="llm",
            message=f"{n_grounds_unresolved}/{total} grounds unresolved — "
                    f"LLM hallucinated citations",
            actual=float(n_grounds_resolved),
            expected=float(total),
        ))

    return out


def aggregate_checks(checks_iter: Iterable[ValidationCheck]) -> List[ValidationCheck]:
    """Flatten + de-dup by ``name`` (last write wins).  The runner
    composes algorithm checks + llm checks + future visualize checks
    into one list before persisting; this helper is the safe
    composition point."""
    by_name: Dict[str, ValidationCheck] = {}
    for c in checks_iter:
        by_name[c.name] = c
    return list(by_name.values())
