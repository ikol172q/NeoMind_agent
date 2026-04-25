# useEffect with `ref.current` + `[]` deps dies when first render early-returns

## The failure

Trackpad two-finger scroll on the lattice canvas did nothing. No console
errors, no pan, bundle verified to contain `addEventListener('wheel', h,
{ passive: false })`. Playwright headless e2e passed (wheel Δty=-200
observed). User's real browser: no movement, no diagnostics.

Diagnostic `console.log('[lattice] wheel listener attached on', vp)` was
added inside the useEffect. On hard-refresh, **the log never printed.**
That proved the effect body ran but `viewportRef.current` was `null` — 
listener was never attached.

## WRONG

```tsx
function LatticeGraphView() {
  const viewportRef = useRef<HTMLDivElement | null>(null)
  const q = useQuery(...)

  // Runs once on mount. `viewportRef.current` is `null` at this point
  // if the early returns below hit, because the ref-bearing div has not
  // yet been committed to the DOM.
  useEffect(() => {
    const vp = viewportRef.current
    if (!vp) return
    const handler = (e: WheelEvent) => { e.preventDefault(); /* ... */ }
    vp.addEventListener('wheel', handler, { passive: false })
    return () => vp.removeEventListener('wheel', handler)
  }, [])

  if (q.isLoading) return <div>building graph…</div>   // ← first render
  if (q.isError)   return <div>{q.error.message}</div>
  if (!q.data)     return <div>no lattice data yet</div>

  return (
    <div ref={viewportRef} data-testid="lattice-graph-scroll">
      …
    </div>
  )
}
```

Sequence that breaks it:
1. Render #1: `q.isLoading === true`. Returns the "building graph…" div.
   The ref-bearing div is **not** in the tree, so React never calls the
   ref callback. `viewportRef.current === null`.
2. useEffect runs after commit. Sees null, returns early.
3. Render #2: data arrives, the real div mounts, ref assigned to the
   node. **But useEffect has `[]` deps → never re-runs.**

`useRef` mutations do not trigger re-render and do not retrigger effect
deps. The effect only runs again if a dep changes or the component
remounts — neither happens here.

## RIGHT

Mirror the DOM node into component state via a callback ref. State
writes retrigger the effect.

```tsx
const viewportRef = useRef<HTMLDivElement | null>(null)
const [viewportEl, setViewportEl] = useState<HTMLDivElement | null>(null)
const bindViewport = (el: HTMLDivElement | null) => {
  viewportRef.current = el        // keep for imperative reads (clamp, zoom)
  setViewportEl(el)               // drives the effect
}

useEffect(() => {
  const vp = viewportEl
  if (!vp) return
  const handler = (e: WheelEvent) => { e.preventDefault(); /* ... */ }
  vp.addEventListener('wheel', handler, { passive: false })
  return () => vp.removeEventListener('wheel', handler)
}, [viewportEl])                  // ← re-runs whenever the node mounts/unmounts

// …
<div ref={bindViewport} data-testid="lattice-graph-scroll">…</div>
```

## Why it hides so well

- Headless e2e was "fast path": data fetch resolved before the effect
  measured, so render #1 already had the div. Real browser with network
  latency took the loading branch first.
- No React warning, no console error. The bug is **silent** — the
  listener just never exists.
- `useRef` feels like it updates the closure — it does for subsequent
  imperative reads, but it doesn't re-run hooks.
- Every symptom (wheel doesn't pan) made me look at the wheel handler's
  body and the React passive-listener bug, not the attachment timing.

## How to spot this class of bug

Any time a `useEffect` reads `someRef.current` and does setup on it:

- [ ] Is the ref-bearing element *always* rendered from the very first
      commit? If there's a conditional return before it, you have this
      bug.
- [ ] Are the effect's deps `[]`? Then state changes don't re-run it.
- [ ] Could the first render ever be a loading/error/empty skeleton?

Rule of thumb: **`useRef.current` is not a dep. If an effect needs a DOM
node that may appear later, expose that node via state or use a
callback ref that sets state.**

## Related

- React docs, "Manipulating the DOM with Refs" → "When is the ref
  attached?" — refs are set during commit, so effects that run during
  the same commit as an early-returned skeleton see null.
- [2026-04-23-drag-listener-useeffect-race.md](2026-04-23-drag-listener-useeffect-race.md)
  — adjacent gotcha: attaching document-level mouse listeners via
  useEffect creates its own race; prefer synchronous attach in the
  event handler.
