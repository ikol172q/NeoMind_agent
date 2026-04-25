# UI bug: never ship a fix without a real browser repro

**Session:** 2026-04-23, Insight Lattice pan/zoom black-screen saga

## What happened

User reported "pan causes black screen in the full-graph view". I shipped
five successive fixes across the pan/zoom code — each time reasoning
through the math, the React state handling, the CTM conversion, the
event race windows — and each time told the user "this one's it, try
again". User kept responding "还是黑屏" / "不行" / "还是"  five rounds in a
row, getting visibly frustrated.

Only when I actually ran Playwright — driving the real bundle through
Chromium, dumping `wrapper_rect` / `vp_rect` / all `[data-node-id]`
bounding rects, writing screenshots — did I see what "black screen"
actually was: at high zoom + aggressive pan, the clamp let the viewport
land fully inside the empty gap between column 3 and column 4 of nodes.
Mathematically correct, visually black. The earlier five fixes were
each solving a phantom problem (or adding complexity that wasn't the
bug).

## WRONG

```
user: "pan causes black screen"
assistant: [reads code, spots plausible bug, edits, ships, tells user to test]
user: "still black screen"
assistant: [reads code again, spots another plausible bug, edits, ships]
user: "still"
assistant: [goto loop, 5x]
```

Symptoms that this was happening:
- Every fix felt "obviously correct" before shipping.
- The bug persisted across architecturally-different rewrites
  (viewBox transform → CSS transform → pointer events → document
  listeners). That's a signal the fault model is wrong, not the
  implementation.
- User repeated the same complaint verbatim.

## RIGHT

```python
# playwright repro — driving the actual bundle, not reasoning about it
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_context(viewport={"width": 1600, "height": 1000}).new_page()
    page.goto("http://127.0.0.1:8001/")
    page.click('[data-testid="tab-research"]')
    page.click('[data-testid="digest-mode-trace"]')
    # interleaved zoom + pan, big range
    for _ in range(3): page.mouse.wheel(0, -100)
    page.mouse.down(); page.mouse.move(cx+400, cy+200); page.mouse.up()
    # dump state AND screenshot after each step
    state = page.evaluate("() => ({ wrapper: ..., nodes: ..., viewport: ... })")
    page.screenshot(path="after_drag.png")
```

The state dump answered the question in one glance: 22 nodes, 2 inside
viewport, wrapper correctly covering viewport per the math — but the
VISIBLE area landed on canvas margins between node columns. Fix was
obvious once visible: clamp on node bbox, not canvas extent.

## WHY

- UI state (CSS transforms, event ordering, browser quirks, layout
  race conditions) is high-dimensional. Reading the code inside the
  editor captures only the JS logic — not what the pixels look like,
  not what the DOM bounding rects report, not what `preserveAspectRatio`
  letterboxing actually does at the viewport size the user is using.
- "Shipping and asking the user to test" burns user trust very fast.
  Each rejected fix makes the *next* fix less credible even if correct.
- A 40-line Playwright repro costs ~5 minutes; four wrong fixes cost
  the user an hour and significant goodwill.

## Rules

1. **For any UI bug the user can reproduce, your first move is to
   reproduce it yourself in a real browser.** Playwright headless is
   the default; only fall back to reasoning when the repro is
   unavailable.
2. **Dump structured state alongside screenshots.** Bounding rects,
   computed styles, transform matrices, counts of visible elements.
   The screenshot shows the symptom; the state dump shows the cause.
3. **If three plausible fixes in a row don't land, the fault model
   is wrong.** Stop editing. Repro harder until you can see the bug
   happen with your own eyes.
4. **Don't declare "this is it" to the user if you haven't reproduced
   the bug yourself.** At best say "here's what I changed — I haven't
   reproduced the original, please verify."
