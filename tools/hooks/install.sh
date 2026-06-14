#!/bin/bash
# Install NeoMind git hooks into the local clone's .git/hooks/.
# Run once per clone:  ./tools/hooks/install.sh

set -e
REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

install_hook() {
    local src="tools/hooks/$1" dest=".git/hooks/$1"
    if [ ! -f "$src" ]; then
        echo "❌ source hook not found at $src"; exit 1
    fi
    # Backup any existing real (non-symlink) hook
    if [ -f "$dest" ] && [ ! -L "$dest" ]; then
        local backup="$dest.bak.$(date +%s)"
        echo "ℹ existing $1 found, backing up to $backup"
        mv "$dest" "$backup"
    fi
    # Symlink so future updates to the source auto-apply
    ln -sf "../../$src" "$dest"
    chmod +x "$src" "$dest"
    echo "✅ Installed $1 hook: $dest → $src"
}

install_hook pre-commit
install_hook pre-push
chmod +x tools/hooks/scan_staged_pii.py 2>/dev/null || true
echo ""
echo "The hook will run cross-mode boot smoke (~90s) when staged changes"
echo "touch shared code paths (code_commands / nl_interpreter / core /"
echo "agentic_loop / telegram_bot / coding/tools / config/*.yaml)."
echo ""
echo "Bypass for emergencies:  NEOMIND_SKIP_SMOKE=1 git commit ..."
