# Don't shortcut-hunt when user asks for "100% fidelity"

**Date**: 2026-04-12
**Category**: testing / user fidelity

## Symptom
User says "100% 用户使用情形模拟" / "真实终端" / "实际 client 调用".
I try to substitute something faster/simpler that's "close enough".

## WRONG
- Using tmux send-keys instead of real iTerm2 (no bracketed paste, no
  real key events, no cocoa input layer)
- Window rows=40 "for speed" → content scrolls off
- Window rows=200 "to be generous" → prompt detection breaks
- Polling 1s "to reduce CPU" → fast bots scroll content off between polls
- Skipping Telegram cross-surface "because CLI covers the same path"
  (it doesn't — auto_search had 4 separate paths across CLI + Telegram)

## RIGHT
Follow `.claude/skills/real-terminal-fidelity-testing/SKILL.md` verbatim:
- Real iTerm2 via `iterm2` Python API
- Recording-based capture (see 2026-04-12-arbitrary-terminal-line-limits.md)
- Window cols=120 rows=60-80 (documented sweet spot)
- Polling 0.3s
- Cross-surface: CLI via iTerm2 AND Telegram via Telethon, same scenarios

## WHY
Fidelity shortcuts usually work 90% of the time. The 10% where they fail
is where the hardest bugs live (the ones that only surface under realistic
conditions — ANSI rendering, terminal escape, bracketed paste, real IME,
concurrent streams). An 85%-fidelity tester is worse than none because
it creates false confidence.

When the user explicitly asked for fidelity, they're asking for the 10%.
