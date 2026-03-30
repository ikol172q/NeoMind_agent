#!/usr/bin/env bash
# Install NeoMind git hooks
# Run once after cloning: bash scripts/install-hooks.sh

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || echo ".")"
HOOKS_DIR="$REPO_ROOT/.git/hooks"
SCRIPT_DIR="$REPO_ROOT/scripts/hooks"

echo "Installing NeoMind git hooks..."

if [ -f "$SCRIPT_DIR/pre-commit" ]; then
    cp "$SCRIPT_DIR/pre-commit" "$HOOKS_DIR/pre-commit"
    chmod +x "$HOOKS_DIR/pre-commit"
    echo "✅ pre-commit hook installed"
else
    echo "❌ scripts/hooks/pre-commit not found"
    exit 1
fi

echo "Done. Hooks will run automatically on 'git commit'."
