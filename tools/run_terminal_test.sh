#!/usr/bin/env bash
# Run a real-terminal test and reap what *this run* leaves behind.
#
# The harness starts an iTerm2 window and a Python process inside it. When a
# run is interrupted, times out, or window creation fails, the process
# survives — and a full-screen application that has lost its window never
# exits, because it waits for input that cannot arrive. Enough of those and
# the machine is short of memory, which has happened here.
#
# The cleanup is a trap rather than a final line: a script that only tidies up
# on the happy path tidies up exactly when it was not needed.
#
# **It kills only its own descendants.** An earlier version called the shared
# reaper, which pattern-matches every `pytest tests/` on the machine — and it
# killed a full-suite run someone had deliberately started in the background,
# thirty minutes in. That is the same mistake `reap_test_processes.sh` records
# in its own header about matching the bare word "playwright". Ownership is
# the process tree, not a name that looks familiar.
#
# **iTerm2 windows are not touched.** They accumulate visibly and the user
# closes them; a script that closed them would eventually close one that was
# not its own.
#
# Usage: tools/run_terminal_test.sh <script.py> [timeout_seconds] [args...]
#
# Anything after the timeout is passed through to the script.
set -u
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT="${1:?usage: run_terminal_test.sh <script.py> [timeout_seconds] [args...]}"
LIMIT="${2:-180}"
shift $(( $# > 2 ? 2 : $# ))

cleanup() {
  local code=$?
  # The whole process group, not a walk of the tree. Killing the child first
  # and enumerating afterwards orphans its grandchildren — `pgrep -P` cannot
  # see them any more, they keep holding the inherited stdout, and whatever is
  # reading that pipe waits forever for an EOF that never comes. That is what
  # hung this wrapper twice.
  local remaining=0
  if [ -n "${PGID:-}" ]; then
    kill -9 -- "-${PGID}" 2>/dev/null
    sleep 1
    remaining=$(pgrep -g "${PGID}" 2>/dev/null | wc -l | tr -d " ")
  fi
  echo "── reaping ──"
  # Reported as what is left, not as what was killed. "Killed 3" says nothing
  # about whether a fourth survived, and survivors are the whole problem.
  echo "  own processes still running: ${remaining}"
  local windows
  windows=$(osascript -e 'tell application "iTerm2" to count of windows' 2>/dev/null || echo "?")
  echo "  iTerm2 windows open: ${windows} (yours to close — ⌘W)"
  echo "  load: $(uptime | sed 's/.*averages: //')"
  exit $code
}
trap cleanup EXIT INT TERM

# `set -m` gives the background job its own process group, which is what
# makes a single group kill possible. Without it the job shares this shell's
# group and killing the group would take the wrapper with it.
set -m
"${REPO}/.venv/bin/python" "$SCRIPT" "$@" &
PID=$!
PGID=$(ps -o pgid= -p "$PID" 2>/dev/null | tr -d " ")
set +m

# Polled rather than `wait`ed. A `wait` on a pid the watchdog has already
# SIGKILLed does not always return in this shell, and the wrapper then hangs
# for as long as whatever is calling it allows — which is worse than the
# runaway it was added to prevent.
DEADLINE=$(( SECONDS + LIMIT ))
TIMED_OUT=0
while kill -0 "$PID" 2>/dev/null; do
  if [ "$SECONDS" -ge "$DEADLINE" ]; then
    echo "  timed out after ${LIMIT}s"
    TIMED_OUT=1
    # The group, so a grandchild cannot outlive it holding the pipe open.
    kill -9 -- "-${PGID:-$PID}" 2>/dev/null
    break
  fi
  sleep 1
done

if [ "$TIMED_OUT" -eq 1 ]; then
  STATUS=124
else
  wait "$PID" 2>/dev/null
  STATUS=$?
fi
exit $STATUS
