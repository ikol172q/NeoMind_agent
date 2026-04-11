# Canary Nightly Smoke — Design Stub

**Status:** Design only. Not wired. Reference for a future session to activate.
**Source plan:** `plans/2026-04-11_todo_activation_closed_loop.md` Phase E item E1.

---

## Purpose

Catch regressions in the canary pipeline BEFORE a real self-evolution needs them. Currently, every `CanaryDeployer.deploy_and_verify()` call is the first smoke test since the last one — if something broke in the meantime (canary container died, bot token rotated, router rate-limit config changed), the first evolution of the day surfaces it as a failure instead of a clean run.

A nightly cron that runs a 5-scenario subset of the Telethon validator against the canary bot closes this gap: any regression is visible in a log file before you touch self-evolution tomorrow.

---

## Proposed shape

### Invocation

```bash
#!/bin/bash
# /usr/local/bin/neomind-canary-nightly.sh
set -euo pipefail

cd $REPO_ROOT
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

# Make sure canary is still up
if ! docker ps --format '{{.Names}}' | grep -q '^neomind-canary$'; then
    echo "canary container missing — starting"
    docker compose --profile canary up -d neomind-canary
    sleep 15
fi

# Run a 5-scenario smoke against the canary bot via Telethon
NEOMIND_TESTER_TARGET=canary \
    .venv/bin/python tests/integration/canary_nightly_smoke.py \
    > /tmp/canary-nightly-$(date +%Y-%m-%d).log 2>&1 || true

# If PASS, prune old logs to keep 14 days
find /tmp -name 'canary-nightly-*.log' -mtime +14 -delete
```

### Schedule

Two options depending on how invasive the user wants cron to be:

**Option A — macOS LaunchAgent** (recommended):
```xml
<!-- ~/Library/LaunchAgents/com.neomind.canary-nightly.plist -->
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.neomind.canary-nightly</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>/usr/local/bin/neomind-canary-nightly.sh</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>3</integer>
        <key>Minute</key>
        <integer>30</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>/tmp/canary-nightly.stdout.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/canary-nightly.stderr.log</string>
</dict>
</plist>
```

Install with:
```bash
launchctl load ~/Library/LaunchAgents/com.neomind.canary-nightly.plist
```

**Option B — crontab**:
```
30 3 * * * /usr/local/bin/neomind-canary-nightly.sh
```

LaunchAgent is preferred on macOS because it respects sleep/wake (runs on next wake if missed) and doesn't need the terminal app to be running.

### Scenario set

5 scenarios, ~4-6 min total runtime, chosen to exercise every critical code path without burning rate-limit budget:

1. `/status` — slash command handling + provider state
2. `/mode fin` — mode switching
3. `AAPL 现价` — fin-mode NL dispatch → finance_get_stock → real yfinance
4. `/tune status` — tune subcommand
5. `10000元 年化8% 10年复利终值` — finance_compute with LLM arg extraction

All 5 were validated in the Phase A pre-activation smoke (2026-04-11). PASS threshold: ≥4/5 (allow 1 transient 429).

### Alerting

Simple — if the nightly run fails (exit non-zero or `RESULT: <4/5`), the log file contains the diagnostics. A future enhancement could:
- Post a message to `@your_neomind_bot` itself ("canary nightly FAIL at $(date)")
- Write a JSON file `~/.neomind/canary-nightly-status.json` that xbar reads and shows a red indicator

For now, the log file + manual check is sufficient given a daily cadence.

---

## Blockers for activation

1. The 6 pre-existing monkey-patch bugs (see `feedback_canary_orchestrator_gotchas.md`) need to be fixed in source so the cron script doesn't have to duplicate the prelude from `/tmp/phase_d_evolve.py`. Otherwise the nightly script becomes a 400-line monster.
2. A new `tests/integration/canary_nightly_smoke.py` script needs to be written — a simplified version of the Phase A smoke runner targeting the canary bot.
3. User needs to decide: LaunchAgent (needs plist install) vs crontab (simpler but less reliable).

Estimated scope once the 6 gotchas are fixed: ~1 hour (write the smoke script, write the LaunchAgent plist, install, validate one nightly run manually).

---

## When to activate

After a future session hardens the 6 canary-orchestrator gotchas. At that point the nightly smoke becomes trivially cheap to wire up and catches regressions before they affect real self-evolution runs.

Current priority: ship the 6 fixes first, THEN this.
