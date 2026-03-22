#!/bin/bash
# ────────────────────────────────────────────────────────────────
# neomind-provider.1m.sh — xbar plugin for NeoMind provider control
#
# Shows current LLM provider status in macOS menu bar.
# Allows switching between litellm (local Ollama) and direct (DeepSeek/z.ai).
#
# Refresh interval: 1 minute (configurable via filename)
#
# Dependencies:
#   - python3 (macOS built-in or Homebrew)
#   - provider-ctl.py (in same directory)
#   - ~/.neomind/provider-state.json (shared with Docker bot)
#
# Install:
#   1. Symlink to xbar plugins dir:
#      ln -s ~/Desktop/NeoMind_agent/xbar/neomind-provider.1m.sh \
#            "$HOME/Library/Application Support/xbar/plugins/"
#   2. Make executable: chmod +x xbar/neomind-provider.1m.sh
#   3. Refresh xbar
# ────────────────────────────────────────────────────────────────

# ── PATH setup (macOS xbar has minimal PATH) ──────────────────
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

# ── Config ─────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CTL="$SCRIPT_DIR/provider-ctl.py"
STATE_DIR="${NEOMIND_STATE_DIR:-$HOME/.neomind}"
STATE_FILE="$STATE_DIR/provider-state.json"
PYTHON=$(command -v python3 || echo "/usr/bin/python3")
BOT_NAME="neomind"

# ── Read state ─────────────────────────────────────────────────
# Use python3 to parse JSON (jq may not be installed)
read_state() {
    if [ ! -f "$STATE_FILE" ]; then
        echo "no_state"
        return
    fi
    "$PYTHON" -c "
import json, sys
try:
    s = json.load(open('$STATE_FILE'))
    bot = s.get('bots', {}).get('$BOT_NAME', {})
    mode = bot.get('provider_mode', 'unknown')
    by = bot.get('updated_by', '?')
    at = bot.get('updated_at', '?')
    health = s.get('litellm', {}).get('health_ok', False)
    bots = list(s.get('bots', {}).keys())
    print(f'{mode}|{by}|{at}|{health}|{\",\".join(bots)}')
except Exception as e:
    print(f'error|{e}|||')
" 2>/dev/null
}

STATE_RAW=$(read_state)
IFS='|' read -r MODE UPDATED_BY UPDATED_AT HEALTH_OK ALL_BOTS <<< "$STATE_RAW"

# ── Menu bar title ─────────────────────────────────────────────
if [ "$MODE" = "litellm" ]; then
    echo "🧠 LLM:🏠"
elif [ "$MODE" = "direct" ]; then
    echo "🧠 LLM:☁️"
elif [ "$MODE" = "no_state" ]; then
    echo "🧠 LLM:?"
elif [ "$MODE" = "error" ]; then
    echo "🧠 LLM:⚠️"
else
    echo "🧠 LLM:?"
fi

echo "---"

# ── Status section ─────────────────────────────────────────────
if [ "$MODE" = "no_state" ]; then
    echo "No provider state found | color=gray"
    echo "Run NeoMind bot once to initialize | color=gray size=12"
    echo "---"
    echo "State file: $STATE_FILE | color=gray size=11"
    exit 0
fi

if [ "$MODE" = "error" ]; then
    echo "⚠️ Error reading state | color=red"
    echo "$UPDATED_BY | color=gray size=11"
    echo "---"
    exit 0
fi

# Current mode
if [ "$MODE" = "litellm" ]; then
    echo "✅ Mode: LiteLLM (Local Ollama) | color=#00aa00"
    echo "   Free, private, lower latency | size=11 color=gray"
else
    echo "✅ Mode: Direct API (DeepSeek/z.ai) | color=#0088ff"
    echo "   Higher quality, costs per token | size=11 color=gray"
fi

echo "Updated: $UPDATED_AT by $UPDATED_BY | size=11 color=gray"

echo "---"

# ── LiteLLM Health ─────────────────────────────────────────────
if [ "$HEALTH_OK" = "True" ]; then
    echo "🟢 LiteLLM: Healthy"
else
    echo "🔴 LiteLLM: Unhealthy"
fi

echo "Check Health Now | bash='$PYTHON' param1='$CTL' param2='health' terminal=false refresh=true"

echo "---"

# ── Switch Mode ────────────────────────────────────────────────
echo "Switch Provider"

if [ "$MODE" != "litellm" ]; then
    echo "-- 🏠 Switch to LiteLLM (Local) | bash='$PYTHON' param1='$CTL' param2='set' param3='$BOT_NAME' param4='litellm' terminal=false refresh=true"
else
    echo "-- 🏠 LiteLLM (Current) | color=gray"
fi

if [ "$MODE" != "direct" ]; then
    echo "-- ☁️  Switch to Direct API | bash='$PYTHON' param1='$CTL' param2='set' param3='$BOT_NAME' param4='direct' terminal=false refresh=true"
else
    echo "-- ☁️  Direct API (Current) | color=gray"
fi

echo "---"

# ── Per-bot status (if multiple bots) ─────────────────────────
IFS=',' read -ra BOT_LIST <<< "$ALL_BOTS"
if [ ${#BOT_LIST[@]} -gt 1 ]; then
    echo "All Bots"
    for bot in "${BOT_LIST[@]}"; do
        BOT_MODE=$("$PYTHON" -c "
import json
s = json.load(open('$STATE_FILE'))
print(s.get('bots', {}).get('$bot', {}).get('provider_mode', '?'))
" 2>/dev/null)
        if [ "$BOT_MODE" = "litellm" ]; then
            ICON="🏠"
        elif [ "$BOT_MODE" = "direct" ]; then
            ICON="☁️"
        else
            ICON="?"
        fi
        echo "-- $bot: $ICON $BOT_MODE | color=#333333"
        echo "---- → LiteLLM | bash='$PYTHON' param1='$CTL' param2='set' param3='$bot' param4='litellm' terminal=false refresh=true"
        echo "---- → Direct   | bash='$PYTHON' param1='$CTL' param2='set' param3='$bot' param4='direct' terminal=false refresh=true"
    done
    echo "---"
fi

# ── Tools ──────────────────────────────────────────────────────
echo "Tools"
echo "-- Show Full Status | bash='$PYTHON' param1='$CTL' param2='get' terminal=true"
echo "-- Open State File | bash='open' param1='$STATE_FILE' terminal=false"
echo "-- Open State Dir  | bash='open' param1='$STATE_DIR' terminal=false"
echo "---"
echo "State: $STATE_FILE | size=11 color=gray"
