#!/usr/bin/env bash
# Rebuild ONLY the React SPA + restart uvicorn. Faster than a full
# infrastructure check when only UI source changed.
#
# Double-click in Finder. Window stays open after exit.
#
# This is the NeoMind_agent-rooted equivalent of
# Investment/cowork/neomind-fin-platform/rebuild_spa.command — points
# at NeoMind_agent (the source-of-truth checkout) and uses .venv.
set -e

cd "$(dirname "$0")"

echo "════════════════════════════════════════════════════════════"
echo "  NeoMind — fast SPA rebuild + uvicorn restart"
echo "  cwd: $(pwd)"
echo "════════════════════════════════════════════════════════════"

# Kill existing uvicorn on 8003 (if any)
EXISTING=$(lsof -nP -iTCP:8003 -sTCP:LISTEN -t 2>/dev/null || true)
if [ -n "$EXISTING" ]; then
    echo "→ killing uvicorn on 8003 (PID: $EXISTING)…"
    kill $EXISTING 2>/dev/null || true
    sleep 1
    EXISTING=$(lsof -nP -iTCP:8003 -sTCP:LISTEN -t 2>/dev/null || true)
    [ -n "$EXISTING" ] && kill -9 $EXISTING 2>/dev/null || true
fi

# Rebuild React SPA — fail loudly so we see compile errors.
if ! command -v npm >/dev/null 2>&1; then
    echo "❌ npm not found — install Node.js first (e.g. brew install node)"
    read -p "Press Return to close…" _
    exit 1
fi

cd web
echo ""
echo "→ npm run build (verbose)…"
BUILD_LOG="/tmp/neomind-rebuild-$$.log"
if npm run build > "$BUILD_LOG" 2>&1; then
    echo "  ✓ web/dist/ updated"
    tail -5 "$BUILD_LOG"
else
    echo "  ❌ build FAILED — full output below:"
    echo "  ─────────────────────────────────────────"
    cat "$BUILD_LOG" | tail -50
    echo "  ─────────────────────────────────────────"
    rm -f "$BUILD_LOG"
    read -p "Press Return to close…" _
    exit 1
fi
rm -f "$BUILD_LOG"
cd ..

# Open browser tab + start uvicorn (foreground)
echo ""
echo "════════════════════════════════════════════════════════════"
echo "→ Starting uvicorn on http://127.0.0.1:8003 (Ctrl+C to stop)"
echo "════════════════════════════════════════════════════════════"

( sleep 3
  for i in 1 2 3 4 5 6 7 8 9 10; do
    if curl -sS -o /dev/null --max-time 1 http://127.0.0.1:8003/api/health 2>/dev/null; then
      open http://127.0.0.1:8003/ 2>/dev/null
      break
    fi
    sleep 1
  done
) &

NEOMIND_RAW_DEV=1 .venv/bin/python -c "
import uvicorn
from agent.finance.dashboard_server import create_app
uvicorn.run(create_app(), host='127.0.0.1', port=8003, log_level='info')
"

read -p "Press Return to close…" _
