"""Scheduler job — periodic strategies audit.

Layer 0a of the anti-hallucination guardrail.  Runs ``audit_all(limit=5)``
once a day, automatically promoting `unverified` strategies to
`verified` / `partially_verified` (or leaving them `unverified` if no
corpus support found) without any human action.

Cron default: ``0 4 * * *`` — once daily at 04:00 UTC, off the busy
market-hours window.  At 5/day, the 36 entries get fully audited
in 8 days.  Each subsequent run picks up entries that age past the
freshness window (B11 follow-up) or that are still unverified.

Failure modes (graceful):
* Missing DEEPSEEK_API_KEY → audit returns ``unsupported`` for every
  numeric field; entries stay ``unverified`` with no harm done.
* Network unreachable → no corpus blobs fetched; audit returns
  ``error="no corpus blobs could be fetched"``; entries stay
  ``unverified``.
* DeepSeek 429 / 5xx → individual claim verdicts come back
  ``unsupported``; partial run still records progress.

Manual rerun:
    python -m agent.finance.scheduler.runner --run-once audit_strategies
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from agent.finance.persistence import connect, dao, ensure_schema

logger = logging.getLogger(__name__)


JOB_NAME = "audit_strategies"
DEFAULT_CRON = "0 4 * * *"
DESCRIPTION = (
    "Run the strategies auditor (Layer 0) on N unverified entries / day. "
    "Grounds free-text claims in RawStore bytes via LLM-as-extractor + "
    "mechanical post-validation; promotes unverified → verified when "
    "every claim's number appears literally in a fetched source page."
)


_DEFAULT_BATCH_LIMIT = 5


async def run(limit: int = _DEFAULT_BATCH_LIMIT) -> Dict[str, Any]:
    """Execute one audit batch.  Returns a summary dict."""
    ensure_schema()

    with connect() as conn:
        run_id = dao.start_analysis_run(
            conn,
            job_name=JOB_NAME,
            run_type="scheduled",
            metadata={"limit": int(limit)},
        )

    # Lazy import keeps the scheduler module load cheap.
    try:
        from agent.finance.strategies.auditor import audit_all
    except Exception as exc:
        logger.warning("audit_strategies: auditor import failed: %s", exc)
        with connect() as conn:
            dao.complete_analysis_run(
                conn, run_id,
                status="failed",
                error_message=f"auditor import failed: {exc}",
                rows_written=0,
            )
        return {"run_id": run_id, "status": "failed",
                "reason": f"auditor import failed: {exc}",
                "wrote_n": 0}

    reports = audit_all(limit=int(limit))

    n_promoted     = sum(1 for r in reports if r.overall_state in ("verified", "partially_verified"))
    n_still_unverified = sum(1 for r in reports if r.overall_state == "unverified")
    n_errors       = sum(1 for r in reports if r.error)

    sample = [
        {"strategy_id": r.strategy_id, "state": r.overall_state,
         "n_corpus_blobs": len(r.corpus),
         "n_supported": sum(1 for v in r.verdicts if v.state == "supported"),
         "n_unsupported": sum(1 for v in r.verdicts if v.state == "unsupported")}
        for r in reports[:5]
    ]

    with connect() as conn:
        dao.complete_analysis_run(
            conn, run_id,
            status="completed",
            error_message=None,
            rows_written=len(reports),
        )

    summary = {
        "run_id":           run_id,
        "status":           "completed",
        "audited_n":        len(reports),
        "promoted_n":       n_promoted,
        "still_unverified": n_still_unverified,
        "errors_n":         n_errors,
        "sample":           sample,
        "explanation":      (
            f"Audited {len(reports)} entries. Promoted {n_promoted} to "
            f"verified / partially_verified. {n_still_unverified} stayed "
            f"unverified (no corpus support found). {n_errors} hit fetch "
            f"errors. Each promoted entry's strategies.yaml provenance is "
            f"updated; raw://<sha256> citations added to sources[]; full "
            f"audit log written to docs/strategies/audit_logs/."
        ),
    }
    logger.info("audit_strategies complete: %s",
                {k: v for k, v in summary.items() if k != "sample"})
    return summary
