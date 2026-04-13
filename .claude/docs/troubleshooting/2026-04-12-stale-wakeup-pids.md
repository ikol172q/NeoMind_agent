# Wakeup prompt pids are stale — always re-fetch

**Date**: 2026-04-12
**Category**: ScheduleWakeup / async loops

## Symptom
A ScheduleWakeup prompt says "check ps 22227" but 22227 is dead or
reassigned. I blindly check it, panic, re-investigate.

## WRONG
```bash
# Wakeup fires: "Check ps 22227, read dumps"
ps -p 22227  # → not found
# → "runner died, something's wrong, investigate"
```

## RIGHT
```bash
# On ANY wakeup, before trusting the pid in the prompt:
pgrep -f <runner_name>     # get CURRENT pid
# or
pgrep -f "coding_cli_judged_runner"
# THEN check that pid + tail log + read dumps
```

## WHY
Wakeups are scheduled before the runner may have been replaced. Between
scheduling and firing, I may have:
- killed the runner to apply a fix
- launched a new instance with a different pid
- the runner may have crashed and been relaunched

The pid in the wakeup prompt is a **hint**, not ground truth. Always
re-fetch. `pgrep` is free; being wrong is expensive.
