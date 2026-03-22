---
name: digest
description: Daily/weekly activity summary — aggregate evidence trail and logs into human-readable digest
modes: [shared]
allowed-tools: [Bash, Read]
version: 1.0.0
---

# Digest — Activity Summary

Generate a concise, human-readable summary of what happened over a time period.
Turns raw evidence trail + logs into insight.

## When to Use

- User asks "今天做了什么?", "what happened today?", "weekly summary"
- Automatically at end of day (if scheduled)
- After a sprint completes

## Data Sources

1. **Evidence trail** (`~/.neomind/evidence/audit.jsonl`)
   - LLM calls (count, modes used, tokens)
   - Commands executed
   - Files modified
   - Sprints completed

2. **Unified logs** (`~/.neomind/logs/YYYY-MM-DD.jsonl`)
   - All LLM requests/responses
   - Provider usage (LiteLLM vs Direct)
   - Errors and fallbacks

3. **SharedMemory** changes
   - New facts learned
   - Preferences updated
   - Feedback received

## Output: Daily Digest

```
📊 NeoMind Daily Digest — YYYY-MM-DD
─────────────────────────────────────

ACTIVITY:
  LLM calls: 42 (chat: 20, coding: 15, fin: 7)
  Commands: 18
  Files modified: 6
  Sprints: 1 completed (goal: "fix auth bug")

PROVIDER:
  LiteLLM (local): 35 calls, $0
  DeepSeek (fallback): 7 calls, ~$0.02

HIGHLIGHTS:
  - Completed sprint "fix auth bug" in 45 min
  - Learned: user prefers Chinese responses
  - 2 guard warnings triggered (rm -rf blocked)

ISSUES:
  - 3 LLM errors (all recovered via fallback)
  - Ollama was down 10:30-10:45

MEMORY:
  - New fact: "weekly team meeting on Thursdays"
  - Preference updated: max_tokens → 2000
```

## Output: Weekly Digest

Same structure but aggregated across 7 days, with:
- Trends (more/fewer calls? New patterns?)
- Comparison to previous week
- Top topics discussed
- Recommendations (from AutoEvolve retro)

## Rules

- Digest must be generated from ACTUAL data, not estimates
- If data source is missing, say so (don't fabricate)
- Keep it concise — this is a summary, not a raw dump
- Highlight anomalies (errors, unusual patterns)
- Privacy: never include message content, only metadata
