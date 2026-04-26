"""Scheduler job implementations.

Each job module exposes:

    JOB_NAME: str           — unique name registered with the scheduler
    DEFAULT_CRON: str       — default cron expression (5-field, UTC)
    DESCRIPTION: str        — human-readable description
    async def run(...) -> dict
                            — does the work; returns a small summary
                              dict for logging. Must be safe to call
                              repeatedly (idempotent at the DB level).
"""
