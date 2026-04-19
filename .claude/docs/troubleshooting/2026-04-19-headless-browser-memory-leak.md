# Headless browser + parallel polls without teardown → host OOM

**Date**: 2026-04-19
**Category**: resource discipline / debug tooling
**Severity**: user-blocking (triggered "system out of application memory" + Force Quit dialog)

## Symptom

User shows macOS "Your system has run out of application memory" dialog.
Activity monitor: 92% RAM, 36 GB swap, Python 23 GB, Chrome 19.9 GB.
Investigation finds the *primary* hogs are the user's own processes
(`mlx_lm.server Qwen3-30B`, everyday Chrome with hundreds of tabs,
Docker Desktop) — BUT I contributed ~500 MB–1 GB on top by spawning
headless Chrome for CDP-based visual verification and running multiple
200-second `run_in_background` polling loops concurrently. On an
already-stressed machine, even a few hundred MB of debug scaffolding is
enough to tip it into swap-thrashing territory.

## WRONG

```bash
# Fire-and-forget headless Chrome for screenshotting — no cleanup on exit
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --headless=new \
  --user-data-dir=/tmp/neomind_chrome_profile \
  --remote-debugging-port=9222 \
  http://127.0.0.1:8001
# Script exits without pkill. Chrome lingers. user-data-dir leaks to /tmp.

# Simultaneously kick off multiple 200s background polls
Bash(run_in_background=true, "for i in $(seq 1 40); do curl ...; sleep 5; done")
Bash(run_in_background=true, "for i in $(seq 1 60); do curl ...; sleep 3; done")
# Two bash shells pinned for ~3 min each, both hitting an LLM backend
# that's already slow — pure overlap, no benefit.
```

No `vm_stat` check before. No `trap` for cleanup. No memory budget.

## RIGHT

**Rule 1 — every spawned browser has a teardown**. Wrap headless
Chrome in a try/finally (Python) or `trap` (shell):

```python
proc = subprocess.Popen([CHROME, "--headless=new", "--user-data-dir", tmpdir, ...])
try:
    # do CDP work
    ...
finally:
    proc.terminate()
    try: proc.wait(timeout=3)
    except Exception: proc.kill()
    shutil.rmtree(tmpdir, ignore_errors=True)
```

```bash
CHROME_PID=""
cleanup() { [ -n "$CHROME_PID" ] && kill "$CHROME_PID" 2>/dev/null; rm -rf /tmp/shot_profile; }
trap cleanup EXIT
"$CHROME_BIN" --headless --user-data-dir=/tmp/shot_profile ... &
CHROME_PID=$!
...
```

**Rule 2 — check memory pressure before memory-sensitive ops**:

```bash
vm_stat | awk '/Pages free|Pages active|Pages inactive|Pages wired|Pages compressed/'
# or just:
memory_pressure | head -3
```

On macOS, `memory_pressure` returns Normal/Warn/Critical. If Warn or
Critical, don't spawn new browsers; ask the user or skip the visual
verification step.

**Rule 3 — one background poll at a time**. If you fire a second
long-running `run_in_background`, cancel the first via TaskStop or
shorten the interval. Never have two curl-poll loops sleeping
simultaneously for the same kind of signal.

**Rule 4 — prefer short segmented polls for interactive sessions**.
Instead of one 200s background poll, do 30s foreground polls and
return to the conversation. The user can redirect; you don't occupy
tool slots.

## WHY

- The user's machine is a shared finite resource. Their *own* mental
  model of "memory budget" is based on the apps they consciously
  opened; debug-tool Chromium instances you spawn silently don't fit
  their model and feel like a betrayal when the machine freezes.
- `--user-data-dir=/tmp/...` that doesn't get deleted accumulates
  across runs: each CDP driver run leaves 4-10 MB, and more
  importantly, can keep the Chrome instance alive longer than your
  script if the parent exits abnormally.
- Concurrent background bash polls each pin a shell + subprocess tree.
  Not huge individually, but on an already-OOM machine every 50 MB
  matters.
- Visual verification via headless Chrome is legitimate (the user
  explicitly asked for it on 2026-04-19), but the tool's *cost*
  (memory, disk, process count) must match the benefit. One careful
  screenshot run with cleanup = fine. Three uncleaned runs + parallel
  polls = OOM contribution.

## Lesson condensed

- `trap`/`finally` is mandatory, not polite.
- Check `memory_pressure` before spawning Chrome/Docker/any
  multi-hundred-MB process on a user's personal machine.
- Don't stack `run_in_background` tasks; one at a time.
- When user reports "卡" / "太慢" / "OOM" — stop new work immediately,
  diagnose & cleanup first, don't compound with more commands.
