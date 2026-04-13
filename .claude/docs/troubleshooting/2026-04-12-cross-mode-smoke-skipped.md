# Changes to shared paths require cross-mode smoke

**Date**: 2026-04-12
**Category**: regression safety / shared code paths

## Symptom
Fix a bug in coding mode. Commit + push. Discover later that chat or fin
mode broke because the fix touched a shared dispatcher.

## WRONG
```
Edit agent/services/code_commands.py::stream_response to add a gate for
coding mode. Run CLI coding smoke. Pass. git commit. git push.
```
Didn't check that chat + fin still boot and respond.

## RIGHT
The pre-commit hook at `tools/hooks/pre-commit` automates this:
```bash
# Triggered on any git commit where staged files match shared-paths regex
# Shared paths:
#   agent/services/code_commands.py
#   agent/services/nl_interpreter.py
#   agent/core.py
#   agent/agentic/agentic_loop.py
#   agent/integration/telegram_bot.py
#   agent/coding/tools.py
#   agent/config/*.yaml
#   agent/config.yaml

# Runs tests/integration/cross_mode_boot_smoke.py:
#   chat:   launch CLI --mode chat, send "你好,简单介绍", verify response
#   fin:    launch CLI --mode fin, send "AAPL 现价", verify response
#   coding: launch CLI --mode coding, send "列出 agent 子目录", verify response

# If any mode crashes / times out / returns empty → blocks commit
```

Install once per clone:
```bash
./tools/hooks/install.sh
```

Bypass only with `NEOMIND_SKIP_SMOKE=1 git commit ...` when you have
manually verified all 3 modes.

## WHY
NeoMind's mode-specific logic (`coding.yaml`, `chat.yaml`, `fin.yaml`
system prompts, NL interpreter patterns) is gated by a small number of
shared dispatchers in `code_commands.py` / `nl_interpreter.py` / `core.py`.
A fix that "only affects coding mode" often goes through these shared
functions. The gate might be correct for coding but break chat's or
fin's path through the same code.

Example: when adding `_mode_allows_auto_search = False for mode == "coding"`,
if I had accidentally inverted the condition, chat and fin would have
lost auto_search capability. Only runtime boot smoke catches this.

## What to do if the hook blocks a commit
1. Read the smoke output — which mode failed, what was the error
2. Is the failure related to your change? If yes → fix before commit
3. Is the failure pre-existing (e.g. LLM API down)? Investigate, don't
   just skip
4. Is the failure a flake (timeout, network)? Retry once; if repeats,
   investigate
5. Only as last resort: `NEOMIND_SKIP_SMOKE=1 git commit ...` with a
   commit message noting why you bypassed

## Related
`.claude/docs/troubleshooting/2026-04-12-feature-gate-single-fix-site.md`
— the auto_search hijack that started the whole "gate at shared paths"
conversation.
