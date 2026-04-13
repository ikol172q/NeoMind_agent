# Never close iTerm2 windows programmatically

**Date**: 2026-04-12 (and earlier session 2026-04-12 ~03:02)
**Category**: iTerm2 / session safety
**Severity**: session-killing

## Symptom
User complains "你开了好多个 terminal, 为啥不把不用的关了".
I write a "smart" cleanup script that iterates `app.windows` and closes
those that don't match a filter. The filter is a heuristic based on
recent screen content. The heuristic fails. All windows close,
including the one running Claude Code itself. Session terminated
mid-task.

## WRONG
```python
# The actual pattern that killed Claude Code's session on 2026-04-12
import iterm2
async with iterm2.Connection.async_create() as conn:
    app = await iterm2.async_get_app(conn)
    for w in app.windows:
        # "filter" — keep Claude Code's window
        screen = await get_recent_screen_tail(w, lines=10)
        if "bypass permissions on" not in screen:
            await w.async_close()
            # Summary: kept=0 closed=9
            # (The banner had scrolled out of the last 10 lines!
            # Claude Code's own window was closed too.)
```

Any variant: `[w.close() for w in ...]`, `app.windows[0].async_close()`,
`osascript tell application "iTerm2" to close windows ...`.

## RIGHT
**Do nothing.** The user can `⌘W` to close each window manually. The
cost of clutter (~1 MB RAM per window) is massively less than the cost
of killing their session mid-task.

If a test runner created a window, let its own context manager close
only ITS OWN window on exit:
```python
async with ITerm2CliTester(cfg) as tester:
    # tester.__aexit__ closes only self._window (the window IT created)
    ...
# self._window is gone, other windows untouched
```

If the user explicitly asks for cleanup, refuse politely or list
windows to the user so they can pick manually. **Do not run any
heuristic filter.**

## WHY
There is NO reliable way from iTerm2's API to identify which window is
Claude Code's session:
- No special env var visible from outside the process
- No special window title (Claude Code doesn't set one)
- No unique process marker
- Screen content changes constantly (banner scrolls out, filter fails)

Any filter is a heuristic that WILL fail eventually. The failure mode
is catastrophic (session killed, conversation lost, progress lost).

## Enforcement
PreToolUse hook at `tools/hooks/iterm2_safety_hook.py` auto-blocks
Bash commands matching dangerous patterns:
- `.async_close()` calls
- `for w in app.windows` loops
- `osascript` controlling iTerm
- `pkill iterm` / `killall iterm`

Bypass only with `NEOMIND_ALLOW_ITERM2_CLOSE=1` and explicit user consent
on that specific operation.

## Related
`~/.claude/projects/-Users-paomian-kong-Desktop/memory/feedback_never_close_iterm2_windows.md`
— user-level memory file with the original incident detail.
