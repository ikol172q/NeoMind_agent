#!/usr/bin/env bash
# sync_launchd_env.sh — copy LLM API keys from the current shell into
# the launchd GUI session so the auto-started fin dashboard
# (com.neomind.fin-dashboard) can reach DeepSeek / GLM / Moonshot /
# z.ai. Run once per macOS login (keys in launchd session don't
# persist across reboot/logout).
#
# Usage:
#   source ~/.zshrc        # ensure keys are in your shell
#   ./scripts/sync_launchd_env.sh
#
# Safety: this writes key values into launchd's in-memory env table,
# never to disk. The plist itself stays clean.

set -euo pipefail

# Keys we care about. Add any new providers here.
KEYS=(
  DEEPSEEK_API_KEY
  ZAI_API_KEY
  GLM_API_KEY
  MOONSHOT_API_KEY
  ANTHROPIC_API_KEY
  OPENAI_API_KEY
)

missing=()
synced=()

for var in "${KEYS[@]}"; do
  val="${!var:-}"
  if [[ -z "$val" ]]; then
    missing+=("$var")
    continue
  fi
  launchctl setenv "$var" "$val"
  synced+=("$var")
done

if ((${#synced[@]})); then
  echo "✓ synced into launchd session env:"
  for k in "${synced[@]}"; do
    echo "    $k"
  done
fi
if ((${#missing[@]})); then
  echo "— not set in current shell (skipped):"
  for k in "${missing[@]}"; do
    echo "    $k"
  done
fi

# Kick the dashboard to pick them up
if launchctl list 2>/dev/null | grep -q "com.neomind.fin-dashboard"; then
  echo ""
  echo "Restarting com.neomind.fin-dashboard with fresh env..."
  launchctl kickstart -k "gui/$UID/com.neomind.fin-dashboard"
  echo "✓ dashboard restart requested"
  # Wait up to 10s for it to come back
  for i in {1..10}; do
    if curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8001/api/health | grep -q 200; then
      echo "✓ http://127.0.0.1:8001 healthy after ${i}s"
      exit 0
    fi
    sleep 1
  done
  echo "⚠ dashboard did not respond to /api/health within 10s — check ~/Library/Logs/neomind-fin-dashboard.log"
fi
