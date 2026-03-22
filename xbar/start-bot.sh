#!/bin/bash
# Start NeoMind Telegram bot (called from xbar)
export PATH="/usr/local/bin:/opt/homebrew/bin:$PATH"
cd "$HOME/Desktop/NeoMind_agent" && docker compose up neomind-telegram -d
