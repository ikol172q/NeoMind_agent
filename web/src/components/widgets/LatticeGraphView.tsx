import { useEffect, useMemo, useRef, useState } from 'react'
import { ZoomIn, ZoomOut, HelpCircle } from 'lucide-react'
import {
  useLatticeGraph,
  type LatticeGraphEdge, type LatticeGraphNode,
  type LatticeGraphPayload, type LatticeLayer,
} from '@/lib/api'
import { LatticeTracePanel, type TraceSelection } from './LatticeTracePanel'

interface Props {
  projectId: string
  /** When set, scroll to and highlight a node/edge. */
  initialFocusNodeId?: string | null
  /** Phase 6 followup: callback to jump to Strategies tab from
   *  reverse-strategy chips on L0 widget nodes. */
  onJumpToStrategies?: (strategyId: string) => void
}

// Exported for test harness inspection — keeps the visual-encoding
// constants discoverable from the test files.
export const VIZ_CONSTANTS = {
  COL_WIDTH: 220, COL_GAP: 30, NODE_W: 180, NODE_H: 34,
}

// ── Visual encoding constants ──────────────────────────
// Kept here (not spec.py) because these are UI-only decisions.
// Provenance kinds themselves come from the backend (LatticeGraphNode
// type), which we trust.

const LAYER_COLS: Record<LatticeLayer, number> = {
  'L0': 0, 'L1': 1, 'L1.5': 2, 'L2': 3, 'L3': 4,
}
const LAYER_LABELS: Record<LatticeLayer, string> = {
  'L0':  'L0 · source',
  'L1':  'L1 · observations',
  'L1.5':'L1.5 · sub-themes',
  'L2':  'L2 · themes',
  'L3':  'L3 · calls',
}
// V10·A1: per-layer explainer shown in column-header popover.
// Deliberately beginner-framed: what this layer IS, HOW it's computed
// (deterministic vs LLM), which spec.py constants control it, and the
// key invariant a reader can use to audit it.
const LAYER_EXPLAINERS: Record<LatticeLayer, {
  what: string; how: string; spec: string; invariant: string;
}> = {
  'L0': {
    what: 'External widget sources (anomaly detector, earnings calendar, sector heatmap, etc.). These are the raw inputs to the lattice.',
    how:  'Fetched live from /api/openbb/*. Zero transformation. Zero LLM.',
    spec: '—  widget set is fixed in code.',
    invariant: 'Click an L0 node to see the raw payload it returned this cycle.',
  },
  'L1': {
    what: 'Atomic observations — one fact per row, tagged with dimensions (symbol, market, sector, severity, timescale).',
    how:  'Deterministic Python generators (one per widget). No LLM. 100% reproducible from the L0 payload.',
    spec: 'Tags conform to `spec.DIMENSIONS`. Severity ∈ {alert, warn, info}.',
    invariant: 'Every L1 node has a `source.widget` and `source.generator` — click to see which function produced it.',
  },
  'L1.5': {
    what: 'Sub-themes — intermediate clusters between observations and themes. Pure tag-intersection, no narrative.',
    how:  'Deterministic. Each L1 obs is scored against every sub-theme signature in the taxonomy. No LLM.',
    spec: 'Weight = `base_membership_weight` × `cluster_severity_bonus` (see `spec.py`). Clamped ≤ 1.0.',
    invariant: 'Click a membership edge to see the Jaccard numerator/denominator + severity bonus. The weight on the edge must equal the formula re-computed.',
  },
  'L2': {
    what: 'Themes — clustered observations with a 1-sentence LLM narrative summarizing what they have in common.',
    how:  'Clustering is deterministic (same formula as L1.5). Narrative is LLM (deepseek-chat). Validator rejects any narrative that cites a number not verbatim present in the member obs text.',
    spec: 'Cluster: `spec.final_membership_weight`. Narrative validator: numbers must overlap obs text.',
    invariant: '`narrative_source` = "llm" when the LLM narrative passed; "template_fallback" when rejected. Click L2 → Deep Trace for the exact prompt + response + validator outcome.',
  },
  'L3': {
    what: 'High-conviction Toulmin calls — claim / grounds / warrant / qualifier / rebuttal. Up to `max_items` shown.',
    how:  'LLM generates up to `max_candidates` candidates. Deterministic validator rejects invalid ones (phantom grounds, tautology, missing fields). MMR selects top-k by λ-weighted relevance vs diversity.',
    spec: 'Selection: `spec.mmr(λ=mmr_lambda)`. Validator: `spec.is_tautological_warrant` + grounds must reference real L2 theme_ids.',
    invariant: 'Click L3 → Deep Trace to see every candidate + why the unselected ones were dropped (`drop_reason`).',
  },
}
const COL_WIDTH = 220
const COL_GAP = 30
const NODE_W = 180
const NODE_H = 34
const ROW_GAP = 10
const TOP_MARGIN = 42
const SIDE_MARGIN = 20

const SEVERITY_COLOR = {
  alert: 'var(--color-red)',
  warn: 'var(--color-amber, #e5a200)',
  info: 'var(--color-accent)',
}

// ── Main component ─────────────────────────────────────

const ZOOM_MIN = 0.5
const ZOOM_MAX = 2.0
const ZOOM_STEP = 1.18   // 18% per wheel tick

interface ViewTransform { scale: number; tx: number; ty: number }
const IDENTITY: ViewTransform = { scale: 1, tx: 0, ty: 0 }

export function LatticeGraphView({ projectId, initialFocusNodeId, onJumpToStrategies }: Props) {
  const q = useLatticeGraph(projectId)
  const [selection, setSelection] = useState<TraceSelection>(null)

  // Phase 6 followup: when arriving with a deep-link from Strategies
  // tab (`initialFocusNodeId="widget:chart"`), auto-select that node
  // so the right inspector pre-fills with its reverse map without
  // requiring a click.
  useEffect(() => {
    if (!initialFocusNodeId || !q.data) return
    const node = q.data.nodes.find((n) => n.id === initialFocusNodeId)
    if (node) setSelection({ type: 'node', node })
  }, [initialFocusNodeId, q.data])

  const [view, setView] = useState<ViewTransform>(IDENTITY)
  const [isPanning, setIsPanning] = useState(false)
  // Refs: wrapper = the element that receives CSS transform; viewport
  // = the scrollable container the wrapper sits inside (its clientRect
  // drives the clamp bounds).
  const wrapperRef = useRef<HTMLDivElement | null>(null)
  const viewportRef = useRef<HTMLDivElement | null>(null)
  // The wheel-listener useEffect must re-run when the viewport div
  // actually mounts — first render can early-return (loading/error/
  // empty) so the div with `ref=` never mounts, ref stays null, and a
  // `[]`-deps effect never re-runs. Mirror the DOM node into state so
  // the effect fires on attach.
  const [viewportEl, setViewportEl] = useState<HTMLDivElement | null>(null)
  const bindViewport = (el: HTMLDivElement | null) => {
    viewportRef.current = el
    setViewportEl(el)
  }
  const svgRef = useRef<SVGSVGElement | null>(null)
  const dragRef = useRef<null | { lastX: number; lastY: number; movedPx: number }>(null)
  const suppressClickRef = useRef(false)
  const teardownPanRef = useRef<null | (() => void)>(null)
  // V8: hovered node id drives the overlap-glow — when an L1 obs node
  // is hovered, every theme node that contains it as a member glows.
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null)
  // V10·A1: which layer's `?` popover is open (click-to-open,
  // click-outside or click-again to close).
  const [explainLayer, setExplainLayer] = useState<LatticeLayer | null>(null)

  const layout = useMemo(() => q.data ? computeLayout(q.data) : null, [q.data])
  const layoutRef = useRef(layout)
  layoutRef.current = layout

  // Overlap set: for the currently-hovered node, every node connected
  // to it by a membership edge. When the user hovers an L1 obs, this
  // highlights every L2 theme it's a member of (and vice versa) — makes
  // the "same observation lives in multiple themes" overlap visible at
  // a glance. Recomputed only when hover changes.
  const overlapSet = useMemo<Set<string>>(() => {
    if (!hoveredNodeId || !q.data) return new Set()
    const s = new Set<string>()
    s.add(hoveredNodeId)
    for (const e of q.data.edges) {
      if (e.kind !== 'membership') continue
      if (e.source === hoveredNodeId) s.add(e.target)
      else if (e.target === hoveredNodeId) s.add(e.source)
    }
    return s
  }, [hoveredNodeId, q.data])

  // Clean up pan listeners if the component unmounts mid-drag.
  useEffect(() => {
    return () => {
      const tm = teardownPanRef.current
      if (tm) tm()
    }
  }, [])

  // ── Wheel / trackpad: pan by default, zoom with ctrl/meta ──
  // Modern infinite-canvas convention (Figma / tldraw / Miro / Excalidraw):
  //   plain wheel / two-finger trackpad scroll → PAN
  //   ctrl+wheel / two-finger trackpad pinch  → ZOOM
  // Browsers synthesize trackpad pinch as wheel + ctrlKey=true, so a
  // single handler covers both gestures.
  //
  // CRITICAL: React 18+ wraps `onWheel` in a PASSIVE listener — calling
  // `e.preventDefault()` from there is a no-op + emits a console error,
  // and the page underneath the lattice keeps scrolling. We attach a
  // native non-passive listener via useEffect so preventDefault wins
  // over native scroll. Must live BEFORE the early-return branches
  // below (loading/error/empty) so React's hook order is stable.
  useEffect(() => {
    const vp = viewportEl
    if (!vp) return
    const handler = (e: WheelEvent) => {
      e.preventDefault()
      if (e.ctrlKey || e.metaKey) {
        const rect = vp.getBoundingClientRect()
        const cursorX = e.clientX - rect.left
        const cursorY = e.clientY - rect.top
        setView(v => {
          const factor = e.deltaY < 0 ? ZOOM_STEP : 1 / ZOOM_STEP
          const newScale = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, v.scale * factor))
          if (newScale === v.scale) return v
          const k = newScale / v.scale
          const next: ViewTransform = {
            scale: newScale,
            tx: cursorX - (cursorX - v.tx) * k,
            ty: cursorY - (cursorY - v.ty) * k,
          }
          return clampView(next)
        })
        return
      }
      if (e.deltaX === 0 && e.deltaY === 0) return
      setView(v => clampView({
        scale: v.scale,
        tx: v.tx - e.deltaX,
        ty: v.ty - e.deltaY,
      }))
    }
    vp.addEventListener('wheel', handler, { passive: false })
    return () => { vp.removeEventListener('wheel', handler) }
  }, [viewportEl])

  // Clamp view so the *node bounding box* (not the empty canvas)
  // always covers the viewport when zoomed in, or fits within the
  // viewport when zoomed out. Earlier versions clamped on the full
  // SVG canvas, which let users pan into the gaps between columns /
  // rows — looking like a "black screen" even though math was fine.
  //
  //   Content nodes in screen space: (tx + s*bbox.x, ty + s*bbox.y)
  //                                to (tx + s*(bbox.x + bbox.w), ...)
  //   Viewport: (0, 0) to (vpW, vpH)
  //
  // For the bbox to fully cover viewport (bbox scaled ≥ viewport):
  //   tx + s*bbox.x ≤ 0  AND  tx + s*(bbox.x + bbox.w) ≥ vpW
  //   → tx ∈ [vpW - s*(bbox.x + bbox.w), -s*bbox.x]
  // For bbox to fully fit (bbox scaled ≤ viewport):
  //   tx + s*bbox.x ≥ 0  AND  tx + s*(bbox.x + bbox.w) ≤ vpW
  //   → tx ∈ [-s*bbox.x, vpW - s*(bbox.x + bbox.w)]
  // Unified: the two range endpoints are `-s*bbox.x` and
  // `vpW - s*(bbox.x + bbox.w)`; min/max picks the right order.
  function clampView(v: ViewTransform): ViewTransform {
    const vp = viewportRef.current
    const lay = layoutRef.current
    if (!vp || !lay) return v
    const vpW = vp.clientWidth
    const vpH = vp.clientHeight
    if (vpW === 0 || vpH === 0) return v
    const bbox = lay.contentBox
    const a_x = -v.scale * bbox.x
    const b_x = vpW - v.scale * (bbox.x + bbox.width)
    const a_y = -v.scale * bbox.y
    const b_y = vpH - v.scale * (bbox.y + bbox.height)
    const minTx = Math.min(a_x, b_x)
    const maxTx = Math.max(a_x, b_x)
    const minTy = Math.min(a_y, b_y)
    const maxTy = Math.max(a_y, b_y)
    const tx = Math.min(maxTx, Math.max(minTx, v.tx))
    const ty = Math.min(maxTy, Math.max(minTy, v.ty))
    return {
      scale: v.scale,
      tx: Number.isFinite(tx) ? tx : 0,
      ty: Number.isFinite(ty) ? ty : 0,
    }
  }

  if (q.isLoading) {
    return <div className="p-3 text-[11px] italic text-[var(--color-dim)]">building graph…</div>
  }
  if (q.isError) {
    return <div className="p-3 text-[11px] text-[var(--color-red)]">{(q.error as Error).message.slice(0, 200)}</div>
  }
  if (!q.data || !layout || q.data.nodes.length === 0) {
    return <div className="p-3 text-[11px] italic text-[var(--color-dim)]">no lattice data yet</div>
  }

  function resetView() { setView(IDENTITY) }
  function zoomBy(factor: number) {
    const vp = viewportRef.current
    if (!vp) return
    const vpW = vp.clientWidth
    const vpH = vp.clientHeight
    setView(v => {
      const newScale = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, v.scale * factor))
      if (newScale === v.scale) return v
      // Zoom around viewport center.
      const cx = vpW / 2
      const cy = vpH / 2
      const k = newScale / v.scale
      const next: ViewTransform = {
        scale: newScale,
        tx: cx - (cx - v.tx) * k,
        ty: cy - (cy - v.ty) * k,
      }
      return clampView(next)
    })
  }

  // Pan: mousedown on empty space arms the drag + attaches document-
  // level mousemove/mouseup listeners SYNCHRONOUSLY. dxPx is directly
  // added to tx because the transform is now CSS pixels, not viewBox.
  function onMouseDown(e: React.MouseEvent<HTMLDivElement>) {
    if (e.button !== 0) return
    const target = e.target as Element
    if (target.closest('[data-node-id], [data-edge-source]')) return
    if (teardownPanRef.current) teardownPanRef.current()
    dragRef.current = { lastX: e.clientX, lastY: e.clientY, movedPx: 0 }

    const onMove = (me: MouseEvent) => {
      const d = dragRef.current
      if (!d) return
      const dxPx = me.clientX - d.lastX
      const dyPx = me.clientY - d.lastY
      d.movedPx += Math.abs(dxPx) + Math.abs(dyPx)
      if (!Number.isFinite(dxPx) || !Number.isFinite(dyPx)) return
      d.lastX = me.clientX
      d.lastY = me.clientY
      setView(v => {
        const next: ViewTransform = {
          scale: v.scale,
          tx: v.tx + dxPx,
          ty: v.ty + dyPx,
        }
        return clampView(next)
      })
    }
    const onUp = () => {
      if (dragRef.current && dragRef.current.movedPx > 4) {
        suppressClickRef.current = true
        setTimeout(() => { suppressClickRef.current = false }, 0)
      }
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
    window.addEventListener('blur', onUp)
    teardownPanRef.current = teardown
    setIsPanning(true)
  }

  function onClickCapture(e: React.MouseEvent) {
    if (suppressClickRef.current) {
      e.stopPropagation()
      e.preventDefault()
      suppressClickRef.current = false
    }
  }

  return (
    <div className="flex h-full min-h-0 relative" data-testid="lattice-graph-wrap">
      {/* Zoom controls — floating top-left */}
      <div
        className="absolute top-2 left-2 z-10 flex flex-col gap-1"
        data-testid="lattice-zoom-controls"
      >
        <button
          data-testid="lattice-zoom-in"
          onClick={() => zoomBy(ZOOM_STEP)}
          className="w-6 h-6 flex items-center justify-center rounded border border-[var(--color-border)] bg-[var(--color-panel)] text-[var(--color-dim)] hover:text-[var(--color-text)]"
          title="zoom in (⌘/ctrl + scroll up · or pinch)"
        ><ZoomIn size={11} /></button>
        <button
          data-testid="lattice-zoom-out"
          onClick={() => zoomBy(1 / ZOOM_STEP)}
          className="w-6 h-6 flex items-center justify-center rounded border border-[var(--color-border)] bg-[var(--color-panel)] text-[var(--color-dim)] hover:text-[var(--color-text)]"
          title="zoom out (⌘/ctrl + scroll down · or pinch)"
        ><ZoomOut size={11} /></button>
        <button
          data-testid="lattice-zoom-reset"
          onClick={resetView}
          className="w-6 h-6 flex items-center justify-center rounded border border-[var(--color-border)] bg-[var(--color-panel)] text-[var(--color-dim)] hover:text-[var(--color-text)] font-mono text-[8.5px] tracking-tight"
          title="reset to 1:1 (100% zoom, no pan)"
        >1:1</button>
        <div
          data-testid="lattice-zoom-level"
          title="scroll / two-finger drag → pan · ⌘ or ctrl + scroll (or pinch) → zoom · click + drag → pan"
          className="text-[9px] font-mono text-center text-[var(--color-dim)] pt-0.5 cursor-help"
        >{Math.round(view.scale * 100)}%</div>
      </div>

      <div
        ref={bindViewport}
        className="flex-1 min-w-0 overflow-hidden relative"
        data-testid="lattice-graph-scroll"
        onMouseDown={onMouseDown}
        onClickCapture={onClickCapture}
        style={{
          cursor: isPanning ? 'grabbing' : 'grab',
          userSelect: 'none',
        }}
      >
        {/* Sticky column-header overlay. Each label is positioned at
            its column's screen-x (after pan + zoom) but CLAMPED to
            the viewport bounds so the label is always visible even
            when its column is panned off-screen — Excel-style frozen
            panes. When clamped, a ◀ / ▶ marker hints the column is
            offscreen in that direction. Reserved 32px on the right
            so labels never overlap the layer-help (?) strip. */}
        <div
          data-testid="lattice-column-headers"
          className="absolute top-0 left-0 pointer-events-none"
          style={{
            right: 180,  // leave room for the layer-help-strip on the right
            height: 32,
            zIndex: 25,  // above SVG (z=auto/0), below layer-help-strip (z=30)
            // Solid background so labels and the gaps BETWEEN labels
            // both fully occlude any SVG content rising into the band.
            // Earlier gradient bottom ~40% was transparent → user saw
            // L1/L1.5/L3 nodes "bleeding through" between labels.
            background:    'var(--color-bg)',
            borderBottom:  '1px solid var(--color-border)',
            boxShadow:     '0 2px 8px rgba(0,0,0,0.55)',
          }}
        >
          {(Object.keys(LAYER_LABELS) as LatticeLayer[]).map((layer) => {
            const naturalX = SIDE_MARGIN + LAYER_COLS[layer] * (COL_WIDTH + COL_GAP) + NODE_W / 2
            const screenX  = naturalX * view.scale + view.tx
            const vpW      = viewportEl?.clientWidth ?? 1200
            // Reserve right margin so the legend (?L0...?L3) doesn't get covered
            const RIGHT_RESERVED = 180
            // Clamp half-label margin so the centered label stays
            // wholly visible. 60px ≈ widest label "L1.5 · SUB-THEMES".
            const halfW    = 60
            const minX     = halfW + 6
            const maxX     = Math.max(minX, vpW - RIGHT_RESERVED - halfW - 4)
            const clamped  = Math.max(minX, Math.min(maxX, screenX))
            const offLeft  = screenX < minX
            const offRight = screenX > maxX
            const dim      = offLeft || offRight
            return (
              <span
                key={layer}
                data-testid={`lattice-column-header-${layer}`}
                data-clamped={dim ? 'true' : undefined}
                style={{
                  position:       'absolute',
                  left:           clamped,
                  top:            6,
                  transform:      'translateX(-50%)',
                  fontSize:       10,
                  fontFamily:     'ui-monospace, monospace',
                  letterSpacing:  '0.05em',
                  color:          dim ? 'var(--color-dim)' : 'var(--color-text)',
                  opacity:        dim ? 0.6 : 1,
                  textTransform:  'uppercase',
                  whiteSpace:     'nowrap',
                  background:     'var(--color-bg)',
                  padding:        '2px 6px',
                  borderRadius:   3,
                  border:         '1px solid var(--color-border)',
                  boxShadow:      '0 1px 4px rgba(0,0,0,0.5)',
                }}
              >
                {offLeft ? '◀ ' : ''}{LAYER_LABELS[layer].toUpperCase()}{offRight ? ' ▶' : ''}
              </span>
            )
          })}
        </div>

        {/* V10·A1: layer explainer strip — 5 `?` buttons fixed at
            graph viewport top-right, always above the SVG / pan
            region. Lives INSIDE the viewport (not the wrap) so the
            trace-panel sibling never covers it. z-30 keeps it above
            the column-header strip (z=25). */}
        <div
          className="absolute top-2 right-2 z-30 flex items-center gap-1 pointer-events-none"
          data-testid="lattice-layer-help-strip"
        >
          {(Object.keys(LAYER_LABELS) as LatticeLayer[]).map((layer) => (
            <LayerHelpButton
              key={layer}
              layer={layer}
              open={explainLayer === layer}
              onToggle={() => setExplainLayer(l => l === layer ? null : layer)}
              onClose={() => setExplainLayer(null)}
            />
          ))}
        </div>
        <div
          ref={wrapperRef}
          data-testid="lattice-svg-viewport"
          style={{
            position: 'absolute',
            top: 0,
            left: 0,
            transformOrigin: '0 0',
            transform: `translate(${view.tx}px, ${view.ty}px) scale(${view.scale})`,
            willChange: 'transform',
          }}
        >
        <svg
          ref={svgRef}
          data-testid="lattice-svg"
          data-zoom-scale={view.scale.toFixed(3)}
          width={layout.width}
          height={layout.height}
          viewBox={`0 0 ${layout.width} ${layout.height}`}
          style={{ display: 'block' }}
        >
          <g>
            {/* Column headers — kept in SVG for export/print fidelity
                but visually covered by the HTML overlay (which is
                always-visible and pan/zoom-aware via clamping). */}
            {(Object.keys(LAYER_LABELS) as LatticeLayer[]).map((layer) => {
              const x = SIDE_MARGIN + LAYER_COLS[layer] * (COL_WIDTH + COL_GAP) + NODE_W / 2
              return (
                <text
                  key={layer}
                  x={x} y={18}
                  textAnchor="middle"
                  className="fill-[var(--color-dim)]"
                  style={{ fontSize: 10, fontFamily: 'ui-monospace, monospace', letterSpacing: '0.05em', opacity: 0 }}
                >
                  {LAYER_LABELS[layer].toUpperCase()}
                </text>
              )
            })}

            {/* Edges first (so nodes render on top) */}
            {layout.edges.map((e, i) => (
              <EdgeSvg
                key={i}
                edge={e.edge}
                x1={e.x1} y1={e.y1} x2={e.x2} y2={e.y2}
                selected={isEdgeSelected(selection, e.edge)}
                dimmed={isSelectionActive(selection) && !isEdgeSelected(selection, e.edge) && !isEdgeAdjacentToSelection(selection, e.edge)}
                onClick={() => setSelection({ type: 'edge', edge: e.edge })}
              />
            ))}

            {/* Nodes */}
            {layout.nodes.map((n) => (
              <NodeSvg
                key={n.node.id}
                node={n.node}
                x={n.x} y={n.y} w={NODE_W} h={NODE_H}
                selected={isNodeSelected(selection, n.node)}
                dimmed={isSelectionActive(selection) && !isNodeSelected(selection, n.node) && !isNodeAdjacentToSelection(selection, n.node, layout.edges)}
                onClick={() => setSelection({ type: 'node', node: n.node })}
                focused={initialFocusNodeId === n.node.id}
                overlapping={overlapSet.has(n.node.id) && overlapSet.size > 1 && hoveredNodeId !== n.node.id}
                hoverRoot={hoveredNodeId === n.node.id && overlapSet.size > 1}
                onPointerEnter={() => setHoveredNodeId(n.node.id)}
                onPointerLeave={() => setHoveredNodeId(prev => prev === n.node.id ? null : prev)}
              />
            ))}
          </g>
        </svg>
        </div>
      </div>

      <LatticeTracePanel
        selection={selection}
        graph={q.data}
        projectId={projectId}
        onClose={() => setSelection(null)}
        onSelectNodeById={(id) => {
          const node = q.data!.nodes.find((n) => n.id === id)
          if (node) setSelection({ type: 'node', node })
        }}
        onJumpToStrategies={onJumpToStrategies}
      />
    </div>
  )
}


// ── V10·A1 layer-help button + popover ─────────────────
// Small `?` pill per layer. Click opens a 4-part popover explaining
// what the layer is, how it's computed, which spec.py constants
// govern it, and the key invariant a reader can audit.

function LayerHelpButton({
  layer, open, onToggle, onClose,
}: {
  layer: LatticeLayer
  open: boolean
  onToggle: () => void
  onClose: () => void
}) {
  const info = LAYER_EXPLAINERS[layer]
  const shortLabel = layer   // "L0" / "L1" / "L1.5" / "L2" / "L3"
  return (
    <div className="relative pointer-events-auto">
      <button
        data-testid={`layer-help-${layer}`}
        data-layer-help-open={open ? 'true' : undefined}
        onClick={onToggle}
        className={
          'inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded border text-[9px] font-mono transition ' +
          (open
            ? 'border-[var(--color-accent)] text-[var(--color-accent)] bg-[var(--color-panel)]'
            : 'border-[var(--color-border)] bg-[var(--color-panel)] text-[var(--color-dim)] hover:text-[var(--color-text)] hover:border-[var(--color-accent)]')
        }
        title={`What is ${layer}?`}
      >
        <HelpCircle size={9} />
        <span>{shortLabel}</span>
      </button>
      {open && (
        <div
          data-testid={`layer-help-popover-${layer}`}
          className="absolute top-full right-0 mt-1 w-[320px] rounded border border-[var(--color-border)] bg-[var(--color-panel)] shadow-lg p-3 text-[10px] leading-[1.5] flex flex-col gap-2 z-20"
        >
          <div className="flex items-center justify-between">
            <span className="font-mono text-[var(--color-accent)] uppercase tracking-wider">
              {LAYER_LABELS[layer]}
            </span>
            <button
              onClick={onClose}
              className="text-[var(--color-dim)] hover:text-[var(--color-text)] text-[11px] leading-none"
              title="close"
            >×</button>
          </div>
          <ExplainField label="What" text={info.what} />
          <ExplainField label="How" text={info.how} />
          <ExplainField label="Spec" text={info.spec} mono />
          <ExplainField label="Audit" text={info.invariant} />
        </div>
      )}
    </div>
  )
}

function ExplainField({ label, text, mono }: { label: string; text: string; mono?: boolean }) {
  return (
    <div>
      <div className="text-[9px] uppercase tracking-wider text-[var(--color-dim)]">{label}</div>
      <div className={mono
        ? 'text-[var(--color-text)] font-mono text-[9.5px]'
        : 'text-[var(--color-text)]'}>
        {text}
      </div>
    </div>
  )
}


// ── Layout math ────────────────────────────────────────

interface LaidOutNode {
  node: LatticeGraphNode
  x: number          // top-left x
  y: number          // top-left y
  cx: number         // center x
  cy: number         // center y
}

interface LaidOutEdge {
  edge: LatticeGraphEdge
  x1: number; y1: number
  x2: number; y2: number
}

function computeLayout(g: LatticeGraphPayload): {
  nodes: LaidOutNode[]
  edges: LaidOutEdge[]
  width: number
  height: number
  /** Bounding box of the visible *nodes* (not the full SVG canvas).
   *  Used for pan clamping so users can't park the viewport on the
   *  empty margins / inter-column gaps. */
  contentBox: { x: number; y: number; width: number; height: number }
} {
  // Bucket nodes by layer, stable-sort by id
  const byLayer: Record<LatticeLayer, LatticeGraphNode[]> = {
    L0: [], L1: [], 'L1.5': [], L2: [], L3: [],
  }
  for (const n of g.nodes) byLayer[n.layer].push(n)
  for (const layer of Object.keys(byLayer) as LatticeLayer[]) {
    byLayer[layer].sort((a, b) => a.id.localeCompare(b.id))
  }

  // Place nodes: each layer stacks vertically
  const posById: Record<string, LaidOutNode> = {}
  let maxRows = 0
  for (const layer of Object.keys(byLayer) as LatticeLayer[]) {
    const col = LAYER_COLS[layer]
    const nodes = byLayer[layer]
    maxRows = Math.max(maxRows, nodes.length)
    nodes.forEach((n, i) => {
      const x = SIDE_MARGIN + col * (COL_WIDTH + COL_GAP)
      const y = TOP_MARGIN + i * (NODE_H + ROW_GAP)
      posById[n.id] = { node: n, x, y, cx: x + NODE_W / 2, cy: y + NODE_H / 2 }
    })
  }

  const laidEdges: LaidOutEdge[] = []
  for (const e of g.edges) {
    const s = posById[e.source]
    const t = posById[e.target]
    if (!s || !t) continue
    laidEdges.push({
      edge: e,
      x1: s.x + NODE_W, y1: s.cy,
      x2: t.x,           y2: t.cy,
    })
  }

  const width = SIDE_MARGIN * 2 + 5 * COL_WIDTH + 4 * COL_GAP
  const height = TOP_MARGIN + maxRows * (NODE_H + ROW_GAP) + 20

  const nodes = Object.values(posById)
  // Tight bounding box of the visible nodes. When nodes is empty
  // we fall back to the full canvas so the clamp math still works.
  let contentBox = { x: 0, y: 0, width, height }
  if (nodes.length > 0) {
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
    for (const n of nodes) {
      if (n.x < minX) minX = n.x
      if (n.y < minY) minY = n.y
      if (n.x + NODE_W > maxX) maxX = n.x + NODE_W
      if (n.y + NODE_H > maxY) maxY = n.y + NODE_H
    }
    // Small padding so nodes aren't flush against the viewport edge
    // at the clamp limits.
    const PAD = 12
    contentBox = {
      x: minX - PAD,
      y: minY - PAD,
      width: (maxX - minX) + 2 * PAD,
      height: (maxY - minY) + 2 * PAD,
    }
  }

  return { nodes, edges: laidEdges, width, height, contentBox }
}


// ── Node rendering ─────────────────────────────────────

function NodeSvg({
  node, x, y, w, h, selected, dimmed, focused, onClick,
  overlapping, hoverRoot, onPointerEnter, onPointerLeave,
}: {
  node: LatticeGraphNode
  x: number; y: number; w: number; h: number
  selected: boolean
  dimmed: boolean
  focused: boolean
  onClick: () => void
  overlapping: boolean
  hoverRoot: boolean
  onPointerEnter: () => void
  onPointerLeave: () => void
}) {
  const prov = node.provenance.computed_by
  const isDiamond = prov === 'llm' || prov === 'llm+validator' || prov === 'llm+mmr'
  const severity = (node.attrs as Record<string, unknown>).severity as string | undefined
  const sevColor = severity ? SEVERITY_COLOR[severity as keyof typeof SEVERITY_COLOR] : undefined
  const strokeColor = selected
    ? 'var(--color-accent)'
    : (overlapping || hoverRoot)
      ? 'var(--color-accent)'
      : sevColor ?? 'var(--color-border)'
  const strokeWidth = selected ? 3.5 : focused ? 3 : (overlapping || hoverRoot) ? 2 : 1
  const fill = dimmed ? 'var(--color-panel)' : 'var(--color-bg)'
  const opacity = dimmed ? 0.35 : 1
  // Soft glow on overlap partners — subtle enough not to overwhelm
  // severity coloring but unmistakable as a visual link. Selected /
  // deep-link-focused nodes get a stronger glow so the user can spot
  // the destination after a cross-tab jump (Phase 6 followup).
  const glowFilter =
    selected || focused
      ? 'drop-shadow(0 0 10px var(--color-accent)) drop-shadow(0 0 18px var(--color-accent))'
      : (overlapping || hoverRoot)
        ? 'drop-shadow(0 0 4px var(--color-accent))'
        : undefined

  const shapeClass = isDiamond
    ? `node-shape-diamond node-provenance-${prov.replace('+', '-')}`
    : `node-shape-rect node-provenance-${prov.replace('+', '-')}`

  return (
    <g
      data-testid={`node-${node.id}`}
      data-node-id={node.id}
      data-layer={node.layer}
      data-provenance={prov}
      data-selected={selected ? 'true' : undefined}
      data-focused={focused ? 'true' : undefined}
      data-overlapping={overlapping ? 'true' : undefined}
      data-hover-root={hoverRoot ? 'true' : undefined}
      className={shapeClass}
      onClick={onClick}
      onPointerEnter={onPointerEnter}
      onPointerLeave={onPointerLeave}
      style={{ cursor: 'pointer', opacity, filter: glowFilter }}
    >
      {isDiamond ? (
        <polygon
          points={`${x + w / 2},${y} ${x + w},${y + h / 2} ${x + w / 2},${y + h} ${x},${y + h / 2}`}
          fill={fill}
          stroke={strokeColor}
          strokeWidth={strokeWidth}
        />
      ) : (
        <rect
          x={x} y={y} width={w} height={h}
          rx={3}
          fill={fill}
          stroke={strokeColor}
          strokeWidth={strokeWidth}
        />
      )}
      {/* Provenance corner badge */}
      {prov === 'llm+validator' && (
        <g data-testid={`node-${node.id}-badge-validator`}>
          <circle cx={x + w - 8} cy={y + 8} r={5} fill="var(--color-green)" />
          <text x={x + w - 8} y={y + 11} textAnchor="middle"
            style={{ fontSize: 8, fill: 'var(--color-bg)' }}>✓</text>
        </g>
      )}
      {prov === 'llm+mmr' && (
        <g data-testid={`node-${node.id}-badge-mmr`}>
          <circle cx={x + w - 8} cy={y + 8} r={5} fill="var(--color-accent)" />
          <text x={x + w - 8} y={y + 11} textAnchor="middle"
            style={{ fontSize: 7, fill: 'var(--color-bg)', fontWeight: 700 }}>M</text>
        </g>
      )}
      {/* Label */}
      <text
        x={x + w / 2}
        y={y + h / 2 + 3}
        textAnchor="middle"
        style={{
          fontSize: 9.5,
          fill: 'var(--color-text)',
          fontFamily: 'ui-monospace, monospace',
          pointerEvents: 'none',
        }}
      >
        {truncate(node.label, 28)}
      </text>
    </g>
  )
}


// ── Edge rendering ─────────────────────────────────────

function EdgeSvg({
  edge, x1, y1, x2, y2, selected, dimmed, onClick,
}: {
  edge: LatticeGraphEdge
  x1: number; y1: number; x2: number; y2: number
  selected: boolean
  dimmed: boolean
  onClick: () => void
}) {
  const dx = Math.max(40, (x2 - x1) * 0.5)
  const path = `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`

  let stroke = 'var(--color-border)'
  let dasharray = ''
  let strokeWidth = 1

  if (edge.kind === 'membership') {
    const w = edge.weight ?? 0
    stroke = 'var(--color-accent)'
    strokeWidth = 0.6 + w * 2.2   // 0.6–2.8 based on weight
  } else if (edge.kind === 'grounds') {
    stroke = 'var(--color-amber, #e5a200)'
    dasharray = '4 3'
    strokeWidth = 1.5
  } else if (edge.kind === 'source_emission') {
    stroke = 'var(--color-dim)'
    strokeWidth = 0.8
  }

  if (selected) {
    stroke = 'var(--color-accent)'
    strokeWidth = Math.max(strokeWidth, 2.5)
  }

  const opacity = dimmed ? 0.15 : selected ? 1 : 0.7

  return (
    <g
      data-testid={`edge-${edge.source}-${edge.target}`}
      data-edge-source={edge.source}
      data-edge-target={edge.target}
      data-edge-kind={edge.kind}
      data-edge-weight={edge.weight ?? undefined}
      data-selected={selected ? 'true' : undefined}
      className={`edge-kind-${edge.kind}`}
      onClick={onClick}
      style={{ cursor: 'pointer' }}
    >
      {/* Invisible wider hit target for easier clicking */}
      <path d={path} stroke="transparent" strokeWidth={10} fill="none" />
      <path
        d={path}
        stroke={stroke}
        strokeWidth={strokeWidth}
        strokeDasharray={dasharray || undefined}
        fill="none"
        opacity={opacity}
      />
    </g>
  )
}


// ── Selection helpers ──────────────────────────────────

function isSelectionActive(s: TraceSelection): boolean {
  return s !== null
}

function isNodeSelected(s: TraceSelection, n: LatticeGraphNode): boolean {
  return s?.type === 'node' && s.node.id === n.id
}

function isEdgeSelected(s: TraceSelection, e: LatticeGraphEdge): boolean {
  return s?.type === 'edge'
    && s.edge.source === e.source
    && s.edge.target === e.target
}

function isNodeAdjacentToSelection(
  s: TraceSelection, n: LatticeGraphNode, edges: LaidOutEdge[],
): boolean {
  if (s?.type === 'node') {
    return edges.some(e =>
      (e.edge.source === s.node.id && e.edge.target === n.id) ||
      (e.edge.target === s.node.id && e.edge.source === n.id))
  }
  if (s?.type === 'edge') {
    return s.edge.source === n.id || s.edge.target === n.id
  }
  return false
}

function isEdgeAdjacentToSelection(
  s: TraceSelection, e: LatticeGraphEdge,
): boolean {
  if (s?.type === 'node') {
    return e.source === s.node.id || e.target === s.node.id
  }
  return false
}


// ── Utils ──────────────────────────────────────────────

function truncate(s: string, n: number): string {
  return s.length <= n ? s : s.slice(0, n - 1) + '…'
}
