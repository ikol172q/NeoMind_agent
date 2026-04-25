"""NeoMind fin scheduler.

Periodically runs data-pull and analysis jobs and persists results
into the SQLite layer at ``agent.finance.persistence``. Replaces the
"every quote is a live fetch" model — the UI now reads from DB and
sees results from the latest scheduled run.

Architecture:

    runner.py               # entry point — starts APScheduler daemon
        |
        v
    core.JobRegistry        # in-memory map of job_name → callable
        |
        v
    jobs/<job_name>.py      # one file per job, async def run(...)

Each job:
    1. Calls dao.start_analysis_run() → run_id
    2. Does work (fetch data, write rows)
    3. Calls dao.complete_analysis_run(run_id, status=..., rows_written=...)
    4. Catches exceptions, marks run failed, doesn't propagate (the
       scheduler should keep running even if one job fails)

Manual rerun: ``python -m agent.finance.scheduler.runner --run-once <name>``.
"""

from agent.finance.scheduler.core import JobRegistry, run_job_once

__all__ = ["JobRegistry", "run_job_once"]
