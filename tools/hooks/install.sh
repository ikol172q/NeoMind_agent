#!/bin/bash
# Install NeoMind git hooks into the local clone's .git/hooks/.
# Run once per clone:  ./tools/hooks/install.sh

set -e
REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

HOOK_SRC="tools/hooks/pre-commit"
HOOK_DEST=".git/hooks/pre-commit"

if [ ! -f "$HOOK_SRC" ]; then
    echo "❌ source hook not found at $HOOK_SRC"
    exit 1
fi

# Backup any existing hook
if [ -f "$HOOK_DEST" ] && [ ! -L "$HOOK_DEST" ]; then
    BACKUP="$HOOK_DEST.bak.$(date +%s)"
    echo "ℹ existing hook found, backing up to $BACKUP"
    mv "$HOOK_DEST" "$BACKUP"
fi

# Create symlink so future updates to tools/hooks/pre-commit auto-apply
ln -sf "../../$HOOK_SRC" "$HOOK_DEST"
chmod +x "$HOOK_SRC"
chmod +x "$HOOK_DEST"

echo "✅ Installed pre-commit hook: $HOOK_DEST → $HOOK_SRC"
echo ""
echo "The hook will run cross-mode boot smoke (~90s) when staged changes"
echo "touch shared code paths (code_commands / nl_interpreter / core /"
echo "agentic_loop / telegram_bot / coding/tools / config/*.yaml)."
echo ""
echo "Bypass for emergencies:  NEOMIND_SKIP_SMOKE=1 git commit ..."
