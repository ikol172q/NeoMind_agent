# SVG viewBox + inner <g> transform: avoid for pan/zoom

**Session:** 2026-04-23, Insight Lattice pan/zoom rewrite

## What happened

For the Insight Lattice full-graph view, first I implemented pan/zoom
by nesting a `<g transform="translate(tx,ty) scale(s)">` inside an SVG
with `viewBox="0 0 W H"` and `preserveAspectRatio="xMidYMid meet"`.
Deltas were computed in viewBox units via `getScreenCTM().inverse()`.

Four different bugs came out of this single architectural choice:
1. `viewBox.width / rect.width` for screen→viewBox conversion is only
   correct for width-fit; fails on height-fit (letterboxing).
2. `getScreenCTM()` on root SVG doesn't include the inner `<g>`'s
   transform — easy to forget which layer you're at.
3. Zoom-around-cursor math accumulates float error differently
   depending on whether you invert through CTM or do raw arithmetic.
4. `preserveAspectRatio="meet"` letterboxes the viewBox in the
   container, and `rect.width` returns the full container width, not
   the rendered viewBox width — so `dxPx / (vb.w / rect.w)` is wrong
   by a factor of the aspect-ratio mismatch.

Each of these manifested as "off by some amount", which combined with
the separate clamp-on-canvas bug (see other entry) produced
indistinguishable black-screen behavior. Chasing them individually
took four rewrites.

## WRONG

```tsx
<svg
  viewBox="0 0 1260 1382"
  width="100%" height="100%"
  preserveAspectRatio="xMidYMid meet"
>
  <g transform={`translate(${tx},${ty}) scale(${s})`}>
    {/* content */}
  </g>
</svg>
```

Plus any of:
```ts
// WRONG 1 — assumes width-fit
const scale = svg.viewBox.baseVal.width / rect.width
dxVb = dxPx * scale

// WRONG 2 — min() is closer but still has ctm.e / ctm.f letterbox offset issues
const pxPerVb = Math.min(rect.w/vb.w, rect.h/vb.h)
dxVb = dxPx / pxPerVb

// WRONG 3 — CTM inverse also works but you have to remember it's the
// root SVG's CTM, NOT the inner <g>'s (which has the view transform)
const ctm = svg.getScreenCTM()
const pt = svg.createSVGPoint(); pt.x = clientX; pt.y = clientY
const vb = pt.matrixTransform(ctm.inverse())
```

## RIGHT

Use plain CSS transform on a wrapper `<div>` around a natural-size SVG.
One coordinate system, no viewBox scaling, no `preserveAspectRatio`,
no CTM conversion:

```tsx
<div ref={viewportRef} className="overflow-hidden relative"
     onWheel={onWheel} onMouseDown={onMouseDown}>
  <div
    style={{
      position: 'absolute', top: 0, left: 0,
      transformOrigin: '0 0',
      transform: `translate(${tx}px, ${ty}px) scale(${scale})`,
    }}
  >
    <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`}>
      {/* content — no inner transform */}
    </svg>
  </div>
</div>
```

Pan math becomes `tx += dxClientX` (no conversion). Zoom-at-cursor uses
`clientX - viewport.getBoundingClientRect().left` directly.

## WHY

- CSS transforms operate in CSS pixels. Screen pixels, pointer event
  coords, `getBoundingClientRect` results are all CSS pixels. Staying
  in one unit eliminates every "off by X scale factor" bug.
- `preserveAspectRatio` solves a real problem (aspect-preserving fit)
  but it does so by introducing letterboxing, and the viewBox math for
  pointer coords in a letterboxed SVG is subtly different between
  width-fit and height-fit cases.
- `getScreenCTM().inverse()` works, but it's a matrix you can't easily
  eyeball. When zoom/pan feels "slightly off", you can't tell whether
  it's your math or CTM's letterbox handling.
- Modern browsers composite CSS transforms on the GPU; the performance
  is identical to SVG inner-group transforms for this use case.

## When SVG viewBox transform IS appropriate

- Static diagrams with no interactive pan/zoom.
- Viz where aspect-preservation is the only requirement and there's no
  user interaction.
- Cases where you need the SVG element itself to resize responsively
  (e.g., filling a container whose size changes).

For pan/zoom, always CSS-transform a wrapper.
