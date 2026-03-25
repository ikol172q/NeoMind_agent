#!/bin/bash
# ─────────────────────────────────────────────────────────
# NeoMind Docker Entrypoint
#
# Handles:
# 1. Environment validation (API keys)
# 2. OpenClaw gateway auto-detection
# 3. Data directory setup
# 4. Graceful shutdown
# ─────────────────────────────────────────────────────────

set -e

# ── Color helpers ────────────────────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${CYAN}[neomind]${NC} $1"; }
warn()  { echo -e "${YELLOW}[neomind]${NC} $1"; }
ok()    { echo -e "${GREEN}[neomind]${NC} $1"; }
err()   { echo -e "${RED}[neomind]${NC} $1"; }

# ── Validate required API key ────────────────────────────
if [ -z "$DEEPSEEK_API_KEY" ] && [ -z "$ZAI_API_KEY" ]; then
    err "No API key found!"
    echo "  Set DEEPSEEK_API_KEY or ZAI_API_KEY in your .env file"
    echo "  or pass via: docker run -e DEEPSEEK_API_KEY=your_key ..."
    exit 1
fi

# ── Setup data directories ───────────────────────────────
# Config dir (bind mount from macOS ~/.neomind — for JSON state files)
mkdir -p /data/neomind/.neomind/finance
mkdir -p /data/neomind/.neomind/conversations

# DB dir (named volume — fast, reliable SQLite)
mkdir -p /data/neomind/db/finance

# Symlink so NeoMind finds its config at ~/.neomind
if [ ! -L "$HOME/.neomind" ] && [ ! -d "$HOME/.neomind" ]; then
    ln -sf /data/neomind/.neomind "$HOME/.neomind"
fi

# ── SQLite DB migration (one-time) ────────────────────────
# Move DBs from bind mount (~/.neomind/) to named volume (/data/neomind/db/)
# for better SQLite performance. Copy, don't move — old file stays as backup.
migrate_db() {
    local OLD_DB="$1"
    local NEW_DB="$2"
    if [ -f "$OLD_DB" ] && [ ! -f "$NEW_DB" ]; then
        info "Migrating DB: $OLD_DB → $NEW_DB"
        cp "$OLD_DB" "$NEW_DB"
        # Verify new DB is readable
        if sqlite3 "$NEW_DB" "SELECT 1;" >/dev/null 2>&1; then
            ok "Migration verified: $NEW_DB"
        else
            warn "Migration verification failed — keeping old DB"
            rm -f "$NEW_DB"
        fi
    fi
}

migrate_db "/data/neomind/.neomind/chat_history.db" "/data/neomind/db/chat_history.db"
migrate_db "/data/neomind/.neomind/usage.db" "/data/neomind/db/usage.db"
migrate_db "/data/neomind/.neomind/finance/memory.db" "/data/neomind/db/finance/memory.db"

# Export explicit DB paths so modules don't guess
export NEOMIND_CHAT_DB="/data/neomind/db/chat_history.db"
export NEOMIND_USAGE_DB="/data/neomind/db/usage.db"
export NEOMIND_MEMORY_DIR="/data/neomind/db/finance"

# ── OpenClaw auto-detection ──────────────────────────────
if [ -n "$OPENCLAW_DEVICE_TOKEN" ]; then
    ok "OpenClaw token found — gateway mode enabled"

    # Auto-detect gateway URL if not explicitly set
    if [ -z "$OPENCLAW_GATEWAY_URL" ]; then
        # Try the Docker Compose service name first
        if getent hosts openclaw-gateway >/dev/null 2>&1; then
            export OPENCLAW_GATEWAY_URL="ws://openclaw-gateway:18789"
            ok "Auto-detected OpenClaw gateway: $OPENCLAW_GATEWAY_URL"
        # Try the default Docker network bridge
        elif getent hosts openclaw >/dev/null 2>&1; then
            export OPENCLAW_GATEWAY_URL="ws://openclaw:18789"
            ok "Auto-detected OpenClaw gateway: $OPENCLAW_GATEWAY_URL"
        else
            export OPENCLAW_GATEWAY_URL="ws://host.docker.internal:18789"
            warn "Using host gateway: $OPENCLAW_GATEWAY_URL"
            warn "  If OpenClaw is in Docker, use docker-compose for networking"
        fi
    else
        ok "OpenClaw gateway: $OPENCLAW_GATEWAY_URL"
    fi

    # Setup OpenClaw memory bridge directory
    if [ -n "$OPENCLAW_MEMORY_DIR" ]; then
        info "OpenClaw memory dir: $OPENCLAW_MEMORY_DIR"
    elif [ -d "/data/openclaw/memory" ]; then
        export OPENCLAW_MEMORY_DIR="/data/openclaw/memory"
        info "Detected OpenClaw memory at $OPENCLAW_MEMORY_DIR"
    fi
else
    info "No OPENCLAW_DEVICE_TOKEN — standalone mode"
    info "  To connect to OpenClaw, set OPENCLAW_DEVICE_TOKEN in .env"
fi

# ── Print startup info ───────────────────────────────────
echo ""
info "╔══════════════════════════════════════╗"
info "║       NeoMind Agent v0.2.0          ║"
info "╚══════════════════════════════════════╝"
echo ""

# Show which API keys are configured
[ -n "$DEEPSEEK_API_KEY" ] && ok "DeepSeek API: ✓"
[ -n "$ZAI_API_KEY" ]      && ok "z.ai API: ✓"
[ -n "$FINNHUB_API_KEY" ]  && ok "Finnhub: ✓"
[ -n "$TAVILY_API_KEY" ]   && ok "Tavily: ✓"
[ -n "$SERPER_API_KEY" ]   && ok "Serper: ✓"
[ -n "$NEWSAPI_API_KEY" ]  && ok "NewsAPI: ✓"
[ -n "$MOONSHOT_API_KEY" ]   && ok "Moonshot/Kimi: ✓"
[ -n "$TELEGRAM_BOT_TOKEN" ] && ok "Telegram Bot: ✓"

echo ""

# ── Handle signals for graceful shutdown ─────────────────
trap 'info "Shutting down..."; kill -TERM $PID; wait $PID' SIGTERM SIGINT

# ── Launch Mode ──────────────────────────────────────────
# Check if first arg is "telegram" — run as Telegram bot daemon
if [ "$1" = "telegram" ]; then
    info "Starting as Telegram bot daemon..."
    if [ -z "$TELEGRAM_BOT_TOKEN" ]; then
        err "TELEGRAM_BOT_TOKEN not set!"
        echo "  Create a bot via @BotFather and add to .env"
        exit 1
    fi
    exec python -u -c "
import traceback
try:
    import asyncio
    print('[debug] Importing finance components...', flush=True)
    from agent.finance import get_finance_components
    from agent_config import AgentConfigManager

    print('[debug] Initializing config...', flush=True)
    cfg = AgentConfigManager(mode='fin')
    components = get_finance_components(cfg)
    print(f'[debug] Components loaded: {list(components.keys())}', flush=True)

    print('[debug] Importing telegram bot...', flush=True)
    from agent.finance.telegram_bot import run_telegram_bot, HAS_TELEGRAM
    print(f'[debug] python-telegram-bot available: {HAS_TELEGRAM}', flush=True)

    if not HAS_TELEGRAM:
        print('ERROR: python-telegram-bot not installed!', flush=True)
        import sys; sys.exit(1)

    print('[debug] Starting bot...', flush=True)
    asyncio.run(run_telegram_bot(components))
except Exception as e:
    print(f'FATAL ERROR: {e}', flush=True)
    traceback.print_exc()
    import sys; sys.exit(1)
"
fi

# Default: interactive CLI mode
exec python main.py "$@"
