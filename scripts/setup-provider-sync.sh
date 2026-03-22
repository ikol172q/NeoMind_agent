#!/bin/bash
# ────────────────────────────────────────────────────────────────
# setup-provider-sync.sh — Setup bidirectional provider sync
#
# Run once to configure:
# 1. ~/.neomind directory (shared state between xbar and Docker)
# 2. xbar plugin symlink
# 3. provider-ctl.py permissions
# ────────────────────────────────────────────────────────────────

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${CYAN}[setup]${NC} $1"; }
ok()    { echo -e "${GREEN}[setup]${NC} $1"; }
warn()  { echo -e "${YELLOW}[setup]${NC} $1"; }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
XBAR_DIR="$PROJECT_DIR/xbar"
STATE_DIR="$HOME/.neomind"
XBAR_PLUGINS="$HOME/Library/Application Support/xbar/plugins"

echo ""
info "╔══════════════════════════════════════════════╗"
info "║  NeoMind Provider Sync Setup                 ║"
info "╚══════════════════════════════════════════════╝"
echo ""

# ── 1. Create state directory ──────────────────────────────────
info "Step 1: State directory"
if [ -d "$STATE_DIR" ]; then
    ok "  ~/.neomind already exists"
else
    mkdir -p "$STATE_DIR"
    ok "  Created ~/.neomind"
fi

# ── 2. Make scripts executable ─────────────────────────────────
info "Step 2: File permissions"
chmod +x "$XBAR_DIR/neomind-provider.1m.sh" 2>/dev/null && ok "  xbar plugin: executable" || warn "  xbar plugin not found"
chmod +x "$XBAR_DIR/provider-ctl.py" 2>/dev/null && ok "  provider-ctl.py: executable" || warn "  provider-ctl.py not found"

# ── 3. Verify python3 ─────────────────────────────────────────
info "Step 3: Python3 check"
if command -v python3 >/dev/null 2>&1; then
    PYVER=$(python3 --version 2>&1)
    ok "  $PYVER found at $(command -v python3)"
else
    warn "  python3 not found! Install via: brew install python3"
    warn "  xbar plugin will not work without python3"
fi

# ── 4. xbar plugin symlink ────────────────────────────────────
info "Step 4: xbar plugin"
if [ -d "$XBAR_PLUGINS" ]; then
    LINK="$XBAR_PLUGINS/neomind-provider.1m.sh"
    if [ -L "$LINK" ]; then
        ok "  Symlink already exists"
    elif [ -f "$LINK" ]; then
        warn "  File exists but is not a symlink — skipping"
        warn "  Remove it manually if you want to replace: rm '$LINK'"
    else
        ln -s "$XBAR_DIR/neomind-provider.1m.sh" "$LINK"
        ok "  Symlinked to xbar plugins"
    fi
else
    warn "  xbar plugins directory not found"
    warn "  Install xbar from https://xbarapp.com and re-run this script"
    warn "  Or manually symlink:"
    warn "    ln -s '$XBAR_DIR/neomind-provider.1m.sh' '<xbar-plugins-dir>/'"
fi

# ── 5. Deprecation notice ─────────────────────────────────────
info "Step 5: Cleanup"
OLD_SCRIPT="$XBAR_DIR/switch-provider.sh"
if [ -f "$OLD_SCRIPT" ]; then
    warn "  Found deprecated switch-provider.sh"
    warn "  This script is replaced by provider-ctl.py + neomind-provider.1m.sh"
    warn "  You can safely remove it: rm '$OLD_SCRIPT'"
fi

# Check for old xbar symlinks
if [ -d "$XBAR_PLUGINS" ]; then
    for f in "$XBAR_PLUGINS"/neomind-switch*.sh "$XBAR_PLUGINS"/switch-provider*.sh; do
        if [ -f "$f" ] || [ -L "$f" ]; then
            warn "  Found old xbar plugin: $(basename "$f")"
            warn "  Consider removing: rm '$f'"
        fi
    done
fi

# ── Summary ────────────────────────────────────────────────────
echo ""
ok "Setup complete!"
echo ""
info "How it works:"
echo "  1. xbar menu shows current LLM provider mode (🏠 local / ☁️  cloud)"
echo "  2. Click to switch — writes to ~/.neomind/provider-state.json"
echo "  3. Docker bot detects the change on next request (no restart needed)"
echo "  4. Bot can also switch via /provider command in Telegram"
echo ""
info "Quick commands:"
echo "  python3 $XBAR_DIR/provider-ctl.py get              # show status"
echo "  python3 $XBAR_DIR/provider-ctl.py set neomind litellm  # → local"
echo "  python3 $XBAR_DIR/provider-ctl.py set neomind direct   # → cloud"
echo "  python3 $XBAR_DIR/provider-ctl.py health            # check LiteLLM"
echo ""
