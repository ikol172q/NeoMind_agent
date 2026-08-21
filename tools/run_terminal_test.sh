#!/usr/bin/env bash
# Run a real-terminal test and reap what it leaves, whatever happens to it.
#
# The harness starts an iTerm2 window and a Python process inside it. When a
# run is interrupted, times out, or the window creation itself fails, the
# process survives — and a full-screen application that has lost its window
# never exits, because it is waiting for input that cannot arrive. Enough of
# those and the machine is short of memory, which has already happened here.
#
# So the cleanup is a trap rather than a final line: a script that only tidies
# up on the happy path tidies up exactly when it was not needed.
#
# **iTerm2 windows are not touched.** They accumulate visibly and the user
# closes them; a script that closed them would eventually close one that was
# not its own. Processes are a different matter — those are ours to end.
#
# Usage: tools/run_terminal_test.sh <script.py> [timeout_seconds]
set -u
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT="${1:?usage: run_terminal_test.sh <script.py> [timeout_seconds]}"
LIMIT="${2:-180}"

cleanup() {
  local code=$?
  echo "── reaping ──"
  "${REPO}/tools/reap_test_processes.sh" 2>/dev/null | sed 's/^/  /'
  # The window is left alone; say so, so its absence is not read as a failure
  # to clean up.
  local windows
  windows=$(osascript -e 'tell application "iTerm2" to count of windows' 2>/dev/null || echo "?")
  echo "  iTerm2 windows open: ${windows} (yours to close — ⌘W)"
  exit $code
}
trap cleanup EXIT INT TERM

"${REPO}/.venv/bin/python" "$SCRIPT" &
PID=$!
( sleep "$LIMIT"; kill -9 "$PID" 2>/dev/null ) &
WATCHDOG=$!
wait "$PID"
STATUS=$?
kill "$WATCHDOG" 2>/dev/null
exit $STATUS
