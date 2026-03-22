#!/bin/bash
# ============================================================
# NeoMind Provider Switch — called by xbar menu
#
# Usage: ./switch-provider.sh litellm   → enable LiteLLM
#        ./switch-provider.sh direct    → disable LiteLLM
#
# Actions:
# 1. Update .env (LITELLM_ENABLED=true/false)
# 2. Restart neomind-telegram container
# 3. Verify the switch worked
# ============================================================

set -e

NEOMIND_DIR="$HOME/Desktop/NeoMind_agent"
ENV_FILE="$NEOMIND_DIR/.env"
TARGET="${1:-direct}"

cd "$NEOMIND_DIR"

if [ "$TARGET" = "litellm" ]; then
    # Check LiteLLM is actually running before enabling
    LITELLM_OK=$(curl -s -o /dev/null -w "%{http_code}" --max-time 3 http://localhost:4000/health/liveliness 2>/dev/null)
    if [ "$LITELLM_OK" != "200" ]; then
        osascript -e 'display notification "LiteLLM 未运行！先启动 LiteLLM 再切换" with title "NeoMind" sound name "Basso"'
        exit 1
    fi

    # Enable LiteLLM in .env
    if /usr/bin/grep -q "^LITELLM_ENABLED=" "$ENV_FILE"; then
        sed -i.bak 's/^LITELLM_ENABLED=.*/LITELLM_ENABLED=true/' "$ENV_FILE"
    else
        echo "LITELLM_ENABLED=true" >> "$ENV_FILE"
    fi

    # Restart container
    docker compose restart neomind-telegram 2>/dev/null

    osascript -e 'display notification "已切换到 LiteLLM (本地 Ollama, 免费)" with title "NeoMind" sound name "Glass"'

elif [ "$TARGET" = "direct" ]; then
    # Disable LiteLLM in .env
    if /usr/bin/grep -q "^LITELLM_ENABLED=" "$ENV_FILE"; then
        sed -i.bak 's/^LITELLM_ENABLED=.*/LITELLM_ENABLED=false/' "$ENV_FILE"
    fi

    # Restart container
    docker compose restart neomind-telegram 2>/dev/null

    osascript -e 'display notification "已切换到 Direct DeepSeek/z.ai" with title "NeoMind" sound name "Glass"'
fi

# Cleanup sed backup
rm -f "$ENV_FILE.bak"
