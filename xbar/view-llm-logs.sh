#!/bin/bash
# View NeoMind LLM call logs (called from xbar)
export PATH="/usr/local/bin:/opt/homebrew/bin:$PATH"
docker logs neomind-telegram 2>&1 | grep -E '\[llm\]|\[llm-think\]|\[LLM\]|provider|model|timeout|error|mode_models' | tail -50
