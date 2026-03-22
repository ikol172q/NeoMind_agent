#!/bin/bash
# View NeoMind Telegram bot logs (called from xbar)
export PATH="/usr/local/bin:/opt/homebrew/bin:$PATH"
docker logs neomind-telegram --tail 50 -f
