# Never use arbitrary line limits to read terminal

**Date**: 2026-04-12
**Category**: terminal capture / testing

## Symptom / when this happens
User asks to "read the whole terminal" / "看 terminal context" / "100% 内容".
I pick a number (120, 500, 10000) and call it "all". User correctly
identifies it as a shortcut.

## WRONG
```python
screen = await tester.capture(lines=120)   # too small
screen = await tester.capture(lines=500)   # still arbitrary
screen = await tester.capture(lines=10000) # just a bigger number
```

## RIGHT
```python
tester.start_recording()        # begin absolute-scrollback accumulation
await tester.send(user_input)
await wait_for_response(tester, max_wait)
# wait_for_response polls capture() every 0.3s; each capture populates
# the recording dict by absolute scrollback index
screen = tester.stop_recording()  # returns EVERY visible line across
                                  # the entire recording window
```

## WHY
iTerm2's `async_get_screen_contents()` returns only the visible window
(no scrollback API). Any `lines=N` approach picks a number based on
window size, which is always wrong for long bot outputs that scroll.
The recording mechanism polls continuously and accumulates by absolute
position, so regardless of how much content scrolls, everything is
captured.

"Read the whole terminal" means ALL content, not "a large number of
lines". Line limits are fundamentally broken for this use case.

## Reference
`tests/integration/cli_tester_iterm2.py` — `start_recording`,
`stop_recording`, `capture` (extended to populate recording dict)
