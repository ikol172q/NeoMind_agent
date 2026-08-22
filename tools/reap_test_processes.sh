#!/usr/bin/env bash
# Reap what a *pytest* run leaves behind — and nothing else.
#
# Killing pytest does not reap its children. The web suite starts a Playwright
# chromium per test file, so an interrupted full run leaves dozens of browsers
# holding memory; that is how a background test run slows the machine down and,
# on one occasion, got the dashboard OOM-killed.
#
# Deliberately narrow. An earlier version matched the bare word "playwright"
# and killed the editor's MCP playwright server, which was nobody's leftover.
# Only processes whose command line ties them to this repo's test run are
# touched, and the reaper never matches an MCP server or a browser the user
# started.
set -u
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

PATTERNS=(
  "python.* -m pytest .*tests/"          # the run itself
  "${REPO}/.venv/bin/python .*pytest"    # the run, launched by path
  # A real-terminal test launches the CLI in an iTerm2 window. Closing the
  # window is the user's to do — never this script's — but the interpreter
  # behind it is a leftover like any other, and a full-screen app that lost
  # its window keeps running forever waiting for input that cannot arrive.
  "${REPO}/.venv/bin/python .*main\.py"
  # An ACP client spawns NeoMind per run. A client that dies without closing
  # stdin leaves this holding the pipe.
  "${REPO}/.venv/bin/python -m agent\.integration\.acp_stdio"
  # Front-end prototypes driven against that server.
  "node .*neomind-tui/tui\.mjs"
)

found=0
for pat in "${PATTERNS[@]}"; do
  pids=$(pgrep -f "$pat" 2>/dev/null || true)
  if [ -n "$pids" ]; then
    echo "  pytest → $(echo "$pids" | wc -l | tr -d ' ') 个"
    echo "$pids" | xargs -r kill 2>/dev/null || true
    found=1
  fi
done

# Chromium started *by playwright's driver under this repo* only. The MCP
# server's browsers do not carry this path.
orphans=$(pgrep -f "${REPO}/.venv/.*chrome" 2>/dev/null || true)
if [ -n "$orphans" ]; then
  echo "  本仓 chromium 孤儿 → $(echo "$orphans" | wc -l | tr -d ' ') 个"
  echo "$orphans" | xargs -r kill 2>/dev/null || true
  found=1
fi

sleep 2
for pat in "${PATTERNS[@]}"; do
  pids=$(pgrep -f "$pat" 2>/dev/null || true)
  [ -n "$pids" ] && echo "$pids" | xargs -r kill -9 2>/dev/null || true
done

[ "$found" -eq 0 ] && echo "  没有本仓测试遗留进程"
echo "  负载: $(uptime | sed 's/.*load averages: //')"
