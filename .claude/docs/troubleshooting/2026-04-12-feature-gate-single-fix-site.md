# Feature gate fixes must check ALL call sites

**Date**: 2026-04-12
**Category**: feature gating / cross-cutting fixes

## Symptom
"Disable this feature in mode X" or "block this behavior when Y".
Fix one call site, declare done, same bug persists elsewhere.

## WRONG (auto_search hijack in coding mode — 4 iterations)
1. Fixed `agent/integration/telegram_bot.py::_should_search` — still hijacked
2. Added gate in `agent/services/code_commands.py::stream_response` — still hijacked
3. Added hard gate in `agent/core.py::search_sync` — still hijacked
4. FINALLY discovered `agent/services/nl_interpreter.py` rewrites "search
   for X" → "/search X" BEFORE any gate runs, fixed by skipping 'search'
   pattern category for coding mode

## RIGHT
Before writing any fix:
```bash
grep -r "searcher\.search\|should_search\|auto_search\|/search" agent/
```
Enumerate every match. Understand which paths need the gate. Pick a
strategy:
- **Chokepoint** — find a single function every path goes through and
  gate there
- **Defense in depth** — apply the gate at every path AND add a
  belt-and-braces env var fail-closed default

Belt-and-braces example: `NEOMIND_MODE=coding` env var propagated from
the runner to the bot subprocess, checked by every gate. Even if one
path is missed, the env var catches it.

## WHY
NeoMind has multi-layer dispatch:
- Telegram surface → `telegram_bot.py` handler → LLM call
- CLI surface → `stream_response` → `prepare_prompt` → NL interpreter → LLM call
- Direct `/search` command → `stream_response_async` → LLM call
- Auto-search trigger regex → hybrid search engine → LLM call

Each layer can independently invoke the search engine. A single-point
fix misses alternate paths. This is not unique to NeoMind — any agent
with dispatch + interpreter + tools has the same structure.

## How to know you got them all
After the fix, run a negative test: send the exact user phrase that
triggered the bug and verify the feature is off. Do this on EVERY
surface (CLI + Telegram + wherever else).
