#!/usr/bin/env bash
# Quick restart — kills uvicorn on 8003 and starts a fresh foreground
# uvicorn from this NeoMind_agent checkout. No SPA rebuild (use
# rebuild_spa.command for that).
#
# NEOMIND_RAW_DEV=1 enables /api/raw/_dev/seed for browser smoke
# testing of the phaseB1 raw-store path.
set -euo pipefail

cd "$(dirname "$0")"

echo "→ killing existing uvicorn on port 8003 (if any)…"
EXISTING=$(lsof -nP -iTCP:8003 -sTCP:LISTEN -t 2>/dev/null || true)
if [ -n "${EXISTING:-}" ]; then
    echo "  PID(s): $EXISTING"
    kill $EXISTING 2>/dev/null || true
    sleep 1
    EXISTING=$(lsof -nP -iTCP:8003 -sTCP:LISTEN -t 2>/dev/null || true)
    if [ -n "${EXISTING:-}" ]; then
        echo "  force-killing: $EXISTING"
        kill -9 $EXISTING 2>/dev/null || true
    fi
fi

echo "→ ensuring warcio is installed in .venv…"
.venv/bin/python -c "import warcio" 2>/dev/null || \
    .venv/bin/pip install --quiet "warcio>=1.7"

echo "→ starting uvicorn (foreground; Ctrl+C to stop)…"
echo "  cwd: $(pwd)"
echo "  NEOMIND_RAW_DEV=1 enables /api/raw/_dev/seed for browser smoke testing."
echo ""
NEOMIND_RAW_DEV=1 .venv/bin/python -c "
import uvicorn
from agent.finance.dashboard_server import create_app
uvicorn.run(create_app(), host='127.0.0.1', port=8003, log_level='info')
"
