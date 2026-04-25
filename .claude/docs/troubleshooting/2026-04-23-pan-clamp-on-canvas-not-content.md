# Pan/zoom clamp: clamp on node bbox, not canvas extent

**Session:** 2026-04-23, Insight Lattice full-graph "black screen"

## What happened

Pan/zoom clamp used the SVG canvas's full width/height (1260×458 —
including side margins, column gaps, row gaps) as the bounding box.
At 3× zoom with aggressive pan, the clamp formula

```
excessX = vpW - layoutW * scale   // -2462 px at s=3, vpW=1318
tx ∈ [min(0, excessX), max(0, excessX)]
```

let `tx` reach -2462px. Mathematically "content covers viewport" the
whole range — but the content extent *includes* the empty margins and
the empty ~30px-wide columns of air between node groups. At extreme
tx, the viewport landed fully inside one of those empty regions.

Result: viewport filled with SVG `<g>` background (black), no visible
nodes, only a few passing edge curves. User sees a black screen and
reports "pan causes black screen". Clamp is provably correct for
covering the canvas, but canvas ≠ content.

## WRONG

```ts
function clampView(v, layoutW, layoutH) {
  const excessX = vpW - layoutW * v.scale  // uses CANVAS extent
  const excessY = vpH - layoutH * v.scale
  return {
    scale: v.scale,
    tx: clip(v.tx, Math.min(0, excessX), Math.max(0, excessX)),
    ty: clip(v.ty, Math.min(0, excessY), Math.max(0, excessY)),
  }
}
```

Signature: `(view, canvasW, canvasH) → view`. The canvas is what you
can see `<svg width>` / `<svg height>` of, so intuitive, but it's the
wrong thing to clamp on for user-perceptible content.

## RIGHT

Compute a tight bounding box over the actual nodes (or visual focus
elements) during layout, and clamp on *that*:

```ts
function computeLayout(g): Layout {
  const nodes = ...
  let minX = Inf, minY = Inf, maxX = -Inf, maxY = -Inf
  for (const n of nodes) {
    if (n.x < minX) minX = n.x
    if (n.y < minY) minY = n.y
    if (n.x + NODE_W > maxX) maxX = n.x + NODE_W
    if (n.y + NODE_H > maxY) maxY = n.y + NODE_H
  }
  const PAD = 12
  const contentBox = {
    x: minX - PAD, y: minY - PAD,
    width: maxX - minX + 2*PAD, height: maxY - minY + 2*PAD,
  }
  return { nodes, edges, width, height, contentBox }
}

function clampView(v) {
  const bbox = layoutRef.current.contentBox
  // At either endpoint, the content bbox is flush against one edge
  // of the viewport.
  const a_x = -v.scale * bbox.x
  const b_x = vpW - v.scale * (bbox.x + bbox.width)
  const minTx = Math.min(a_x, b_x), maxTx = Math.max(a_x, b_x)
  // same for y
  return { ..., tx: clip(v.tx, minTx, maxTx), ... }
}
```

Verified with Playwright: at ZOOM_MAX + max drag in any direction,
the number of `[data-node-id]` elements intersecting the viewport
rect went from 2/22 (mostly black) → 12/20 (clearly populated).

## WHY

- "Content covers viewport" is a math invariant; "user sees meaningful
  content" is a UX invariant. They're not the same when your canvas
  contains structured whitespace (grid layouts, column/row lattices,
  padded diagrams).
- A canvas-clamp is easier to write (you already know W and H) but
  invites exactly this trap at higher zoom levels where the content-
  to-canvas ratio matters.
- If computing a tight node bbox is expensive (many nodes), memoize it
  — it only changes when the layout data changes.

## Complementary safety measures

- **Cap zoom at a level where the content stays dense in the viewport.**
  For NeoMind's 5-column lattice at typical container sizes, this was
  2.0× (originally 3.0×). At 3× the content is 7% of viewport coverage
  in the worst case — even with bbox clamp, dragging shows mostly edges
  and whitespace between a handful of nodes.
- **Never clamp against zero content.** If `contentBox` is empty
  (no nodes yet), fall back to canvas extent or identity transform;
  don't let pan range become `[undefined, undefined]`.
