#!/bin/bash
# ─────────────────────────────────────────────────────────
# NeoMind — Pull & Rebuild Script
#
# Run this after git pull to rebuild and restart containers.
# Your data (memory, predictions, conversations) is safe —
# it lives in Docker volumes, not in the image.
#
# Usage:
#   ./update.sh              # rebuild + restart all running services
#   ./update.sh telegram     # rebuild + restart only telegram bot
#   ./update.sh --no-cache   # full rebuild (slow, but fixes dep issues)
# ─────────────────────────────────────────────────────────

set -e

GREEN='\033[0;32m'
CYAN='\033[0;36m'
NC='\033[0m'

info() { echo -e "${CYAN}[update]${NC} $1"; }
ok()   { echo -e "${GREEN}[update]${NC} $1"; }

# Parse args
SERVICE=""
BUILD_ARGS=""
for arg in "$@"; do
    case $arg in
        --no-cache) BUILD_ARGS="--no-cache" ;;
        telegram)   SERVICE="neomind-telegram" ;;
        cli)        SERVICE="neomind" ;;
        all)        SERVICE="" ;;
        *)          SERVICE="$arg" ;;
    esac
done

# Step 1: Pull latest code
info "Pulling latest code..."
git pull --ff-only 2>/dev/null || {
    info "git pull skipped (not a git repo or has local changes)"
}

# Step 2: Rebuild image
info "Rebuilding Docker image... ${BUILD_ARGS}"
if [ -n "$SERVICE" ]; then
    docker compose build $BUILD_ARGS "$SERVICE"
else
    docker compose build $BUILD_ARGS
fi

# Step 3: Restart containers (data volumes preserved)
info "Restarting containers..."
if [ -n "$SERVICE" ]; then
    docker compose up -d "$SERVICE"
else
    # Restart only currently running services
    RUNNING=$(docker compose ps --services --filter "status=running" 2>/dev/null)
    if [ -n "$RUNNING" ]; then
        docker compose up -d $RUNNING
    else
        info "No running services found. Start with: docker compose up neomind-telegram -d"
    fi
fi

# Step 4: Show status
echo ""
ok "Update complete!"
docker compose ps
echo ""

# Show what changed
info "Recent changes:"
git log --oneline -5 2>/dev/null || true
