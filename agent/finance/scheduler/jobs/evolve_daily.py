"""evolve_daily — the fin harness self-evolution trigger (Phase 3.4).

Closes Gap 1: the loop had no trigger — fin_rollout / fin_outcome / fin_evolve
were only ever callable from a REPL or tests, so "self-evolution" couldn't run
by itself. This job drives one full pass:

    backfill matured decision outcomes    (fin_outcome.backfill)
    -> small-N synthetic rollouts          (fin_rollout — reward-labeled episodes)
    -> mine low-reward patterns             (fin_evolve.mine — outcome-aware)
    -> draft human-review proposals          (fin_evolve.propose + save_proposals)

It deliberately STOPS at draft. It never calls gated_apply — mutating the
harness still requires explicit human approval. So "self-evolution" here means
self-data-generation + self-mining + self-proposal-drafting; *promotion* stays
human. (gated_apply itself carries the Phase 3.2 statistical gate + Phase 3.3
safety gates, but a human must run it.)

OPT-IN — this module is intentionally NOT in scheduler.core.DEFAULT_JOBS, so it
does NOT run autonomously and spends nothing on its own. Run it by hand and
review what it drafts:

    python -m agent.finance.scheduler.jobs.evolve_daily

To graduate it to a daily autonomous run (still draft-only — it never
auto-applies), add this one line to DEFAULT_JOBS in scheduler/core.py and
redeploy:

    "agent.finance.scheduler.jobs.evolve_daily",

…after which ``--run-once evolve_daily`` and the APScheduler daemon both pick
it up on the DEFAULT_CRON below.

Cost: the rollout step hits the live agent (~$0.07 at runs_per_intent=1 × 3
intents). backfill hits yfinance (free). mining is offline. Both data steps are
best-effort — a failure in either still lets the job mine the existing episode
corpus and draft from it.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from agent.finance.persistence import connect, ensure_schema
from agent.finance.persistence import dao

logger = logging.getLogger(__name__)


JOB_NAME = "evolve_daily"
DEFAULT_CRON = "30 5 * * *"   # 05:30 UTC daily — before learning_daily (06:00)
DESCRIPTION = (
    "Fin harness self-evolution (draft-only): backfill decision outcomes -> "
    "small-N synthetic rollouts -> mine low-reward patterns -> draft "
    "human-review proposals. NEVER auto-applies (gated_apply stays manual). "
    "OPT-IN: not in DEFAULT_JOBS until explicitly enabled. ~$0.07/run."
)


async def run(runs_per_intent: int = 1, days: int = 14,
              do_backfill: bool = True) -> Dict[str, Any]:
    ensure_schema()
    with connect() as conn:
        run_id = dao.start_analysis_run(conn, job_name=JOB_NAME, run_type="scheduled")

    summary: Dict[str, Any] = {"job": JOB_NAME, "run_id": run_id}
    rows_written = 0
    try:
        from agent.finance import fin_rollout, fin_evolve

        # 1) Close the outcome loop on matured decisions (best-effort; network).
        if do_backfill:
            try:
                from agent.finance import fin_outcome
                summary["backfill"] = fin_outcome.backfill()
            except Exception as exc:  # noqa: BLE001
                summary["backfill_error"] = f"{type(exc).__name__}: {exc}"
                logger.warning("evolve_daily backfill failed: %s", exc)

        # 2) Generate a small batch of reward-labeled synthetic rollouts (live
        #    agent — the cost step). Best-effort: failure still lets us mine the
        #    existing episode corpus.
        try:
            seeds = fin_rollout.build_seeds(runs_per_intent, run_id=f"evolve-{run_id}")
            roll = await fin_rollout.run_rollouts(seeds)
            summary["rollouts"] = roll.get("summary")
        except Exception as exc:  # noqa: BLE001
            summary["rollout_error"] = f"{type(exc).__name__}: {exc}"
            logger.warning("evolve_daily rollouts failed: %s", exc)

        # 3) Mine (outcome-aware) + draft proposals for NEW rules only — dedup
        #    against any rule that already has a proposal so daily runs don't
        #    spam duplicates.
        diag = fin_evolve.mine(days=days)
        proposals = fin_evolve.propose(diag)
        existing_rules = {p.get("rule") for p in fin_evolve.list_proposals()}
        new_props = [p for p in proposals if p.get("rule") not in existing_rules]
        paths = fin_evolve.save_proposals(new_props) if new_props else []

        summary["mine"] = {**(diag.get("corpus") or {}),
                           "patterns": len(diag.get("patterns", []))}
        summary["proposals_drafted"] = len(new_props)
        summary["proposal_ids"] = [p["id"] for p in new_props]
        summary["proposal_paths"] = paths
        rows_written = len(new_props)

        with connect() as conn:
            dao.complete_analysis_run(conn, run_id, status="completed",
                                      rows_written=rows_written)
        summary["status"] = "completed"
        return summary

    except Exception as exc:  # noqa: BLE001
        logger.exception("evolve_daily failed")
        with connect() as conn:
            dao.complete_analysis_run(conn, run_id, status="failed",
                                      error_message=str(exc))
        summary["status"] = "failed"
        summary["error"] = str(exc)
        return summary


if __name__ == "__main__":
    import asyncio
    import json

    print(json.dumps(asyncio.run(run()), ensure_ascii=False, indent=2, default=str))
