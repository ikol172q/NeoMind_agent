# Drag handlers: attach document listeners synchronously, not via useEffect

**Session:** 2026-04-23, Insight Lattice pan/zoom

## What happened

Pan was implemented as:

```tsx
function onMouseDown(e) {
  dragRef.current = { lastX: e.clientX, lastY: e.clientY }
  setIsPanning(true)    // ← queues re-render
}

// useEffect attaches listeners when isPanning flips true
useEffect(() => {
  if (!isPanning) return
  document.addEventListener('mousemove', onMove)
  document.addEventListener('mouseup', onUp)
  return () => { /* cleanup */ }
}, [isPanning])
```

React commits state 1–16ms after `setIsPanning(true)`. In that window,
any `mouseup` (or quick click: mousedown+up within one frame) fires
before the effect attaches its listener. Consequence:

- `isPanning` stays `true` (onUp never ran)
- `dragRef.current` stays set with stale `lastX`
- Effect finally commits — listeners attach — but the drag already
  ended
- Next incidental `mousemove` (even with no button held) is treated
  as a drag: `dxPx = e.clientX - staleLastX` is a huge delta; pan jumps
  catastrophically. Combined with a soft clamp, content flies to an
  edge and reads as black.

This was the real "2nd/3rd drag goes black" bug the user hit repeatedly.

## WRONG

```tsx
// onMouseDown arms state; useEffect attaches listeners.
// Between state flip and effect commit, mouseup can slip through
// unhandled.
function onMouseDown(e) {
  dragRef.current = { ... }
  setIsPanning(true)
}
useEffect(() => {
  if (!isPanning) return
  document.addEventListener('mousemove', onMove)
  document.addEventListener('mouseup', onUp)
  return cleanup
}, [isPanning])
```

Symptoms: drag sometimes "sticks" — content jumps on next mouse move;
`isPanning` cursor stays `grabbing` even after release; hovering over
the SVG with no button down starts panning.

## RIGHT

Attach listeners synchronously inside the mousedown handler. Store the
teardown function in a ref. Call teardown on mouseup (or component
unmount via a minimal useEffect cleanup).

```tsx
const teardownPanRef = useRef<(() => void) | null>(null)

function onMouseDown(e) {
  if (e.button !== 0) return
  if (teardownPanRef.current) teardownPanRef.current()  // idempotent
  dragRef.current = { lastX: e.clientX, lastY: e.clientY, movedPx: 0 }

  const onMove = (me) => { /* pan logic */ }
  const onUp = () => {
    dragRef.current = null
    setIsPanning(false)
    teardown()
  }
  const teardown = () => {
    document.removeEventListener('mousemove', onMove)
    document.removeEventListener('mouseup', onUp)
    window.removeEventListener('blur', onUp)
    teardownPanRef.current = null
  }

  document.addEventListener('mousemove', onMove)
  document.addEventListener('mouseup', onUp)
  window.addEventListener('blur', onUp)   // escape hatch on alt-tab
  teardownPanRef.current = teardown
  setIsPanning(true)                      // UI-only (cursor style)
}

// Minimal useEffect just for unmount cleanup
useEffect(() => () => teardownPanRef.current?.(), [])
```

Key properties:
- Listener attached BEFORE any render cycle can complete.
- `isPanning` state is for UI (cursor style) only; not for listener
  lifecycle.
- Teardown is idempotent and called from multiple paths (mouseup,
  blur, unmount, re-arming on next mousedown).

## Related: drag-then-click-selects-node

After fixing the race, a second subtle bug remained: dragging onto a
node then releasing fired `click` on the node, opening its trace panel
as if the user had selected it. Solution: accumulate `movedPx` in the
mousemove handler; on mouseup, if `movedPx > 4` set a
`suppressClickRef` flag; `onClickCapture` on the viewport swallows the
next click. Auto-clear via `setTimeout(0)` in case no spurious click
arrives (else the *next real* click gets eaten).

## WHY

- React batches `setState` calls. The "attach listeners on state flip"
  idiom assumes the effect runs before any related user event — false
  for fast clicks or sub-frame pointer events.
- Event handlers run synchronously; effects run after render commit.
  For anything that needs to start an event subscription *atomically*
  with an event, subscribe in the handler, not the effect.
- Pointer capture (`setPointerCapture`) is a different answer to this
  problem but has cross-browser quirks on SVG elements (Safari/Firefox).
  Document listeners are the most portable.

## Detection

If you write a drag/resize/pan handler and find yourself debugging
"the drag sometimes gets stuck" or "the first drag works but the
second does weird things", 90% of the time it's this race. Grep your
PR for the pattern:

```
onMouseDown   → setState(...)
useEffect([state]) → add/remove document listener
```

If you see it, rewrite.
