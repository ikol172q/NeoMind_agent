import { useMemo, useRef, useState } from 'react'
import { ZoomIn, ZoomOut, Maximize2 } from 'lucide-react'
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

const ZOOM_MIN = 0.3
const ZOOM_MAX = 3.0
const ZOOM_STEP = 1.18   // 18% per wheel tick

interface ViewTransform { scale: number; tx: number; ty: number }
const IDENTITY: ViewTransform = { scale: 1, tx: 0, ty: 0 }

export function LatticeGraphView({ projectId, initialFocusNodeId }: Props) {
  const q = useLatticeGraph(projectId)
  const [selection, setSelection] = useState<TraceSelection>(null)
  const [view, setView] = useState<ViewTransform>(IDENTITY)
  const svgRef = useRef<SVGSVGElement | null>(null)
  const dragRef = useRef<null | {
    startX: number; startY: number; startTx: number; startTy: number;
  }>(null)

  const layout = useMemo(() => q.data ? computeLayout(q.data) : null, [q.data])

  if (q.isLoading) {
    return <div className="p-3 text-[11px] italic text-[var(--color-dim)]">building graph…</div>
  }
  if (q.isError) {
    return <div className="p-3 text-[11px] text-[var(--color-red)]">{(q.error as Error).message.slice(0, 200)}</div>
  }
  if (!q.data || !layout || q.data.nodes.length === 0) {
    return <div className="p-3 text-[11px] italic text-[var(--color-dim)]">no lattice data yet</div>
  }

  // ── Zoom / pan handlers ────────────────────────────
  function svgPoint(clientX: number, clientY: number): { x: number; y: number } {
    const svg = svgRef.current
    if (!svg) return { x: 0, y: 0 }
    const rect = svg.getBoundingClientRect()
    // Convert client coords → viewBox coords (account for current scale/pan)
    const scale = svg.viewBox.baseVal.width / rect.width
    return {
      x: (clientX - rect.left) * scale,
      y: (clientY - rect.top) * scale,
    }
  }

  function onWheel(e: React.WheelEvent<SVGSVGElement>) {
    e.preventDefault()
    const factor = e.deltaY < 0 ? ZOOM_STEP : 1 / ZOOM_STEP
    const newScale = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, view.scale * factor))
    if (newScale === view.scale) return
    // Zoom around cursor: keep the viewBox point under cursor fixed
    const p = svgPoint(e.clientX, e.clientY)
    const k = newScale / view.scale
    setView({
      scale: newScale,
      tx: p.x - (p.x - view.tx) * k,
      ty: p.y - (p.y - view.ty) * k,
    })
  }

  function onMouseDown(e: React.MouseEvent<SVGSVGElement>) {
    // Start a pan only on empty background — not on interactive node/edge groups
    const target = e.target as Element
    if (target.closest('[data-node-id], [data-edge-source]')) return
    dragRef.current = {
      startX: e.clientX, startY: e.clientY,
      startTx: view.tx, startTy: view.ty,
    }
  }
  function onMouseMove(e: React.MouseEvent<SVGSVGElement>) {
    if (!dragRef.current) return
    const svg = svgRef.current
    if (!svg) return
    const rect = svg.getBoundingClientRect()
    const scale = svg.viewBox.baseVal.width / rect.width
    setView(v => ({
      ...v,
      tx: dragRef.current!.startTx + (e.clientX - dragRef.current!.startX) * scale,
      ty: dragRef.current!.startTy + (e.clientY - dragRef.current!.startY) * scale,
    }))
  }
  function onMouseUp() { dragRef.current = null }

  function resetView() { setView(IDENTITY) }
  function zoomBy(factor: number) {
    const newScale = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, view.scale * factor))
    // Zoom around viewBox center
    const svg = svgRef.current
    if (!svg) return
    const cx = svg.viewBox.baseVal.width / 2
    const cy = svg.viewBox.baseVal.height / 2
    const k = newScale / view.scale
    setView({
      scale: newScale,
      tx: cx - (cx - view.tx) * k,
      ty: cy - (cy - view.ty) * k,
    })
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
          title="zoom in (wheel up)"
        ><ZoomIn size={11} /></button>
        <button
          data-testid="lattice-zoom-out"
          onClick={() => zoomBy(1 / ZOOM_STEP)}
          className="w-6 h-6 flex items-center justify-center rounded border border-[var(--color-border)] bg-[var(--color-panel)] text-[var(--color-dim)] hover:text-[var(--color-text)]"
          title="zoom out (wheel down)"
        ><ZoomOut size={11} /></button>
        <button
          data-testid="lattice-zoom-reset"
          onClick={resetView}
          className="w-6 h-6 flex items-center justify-center rounded border border-[var(--color-border)] bg-[var(--color-panel)] text-[var(--color-dim)] hover:text-[var(--color-text)]"
          title="reset view"
        ><Maximize2 size={10} /></button>
        <div
          data-testid="lattice-zoom-level"
          className="text-[9px] font-mono text-center text-[var(--color-dim)] pt-0.5"
        >{Math.round(view.scale * 100)}%</div>
      </div>

      <div className="flex-1 min-w-0 overflow-hidden" data-testid="lattice-graph-scroll">
        <svg
          ref={svgRef}
          data-testid="lattice-svg"
          data-zoom-scale={view.scale.toFixed(3)}
          viewBox={`0 0 ${layout.width} ${layout.height}`}
          width="100%"
          height="100%"
          preserveAspectRatio="xMidYMid meet"
          onWheel={onWheel}
          onMouseDown={onMouseDown}
          onMouseMove={onMouseMove}
          onMouseUp={onMouseUp}
          onMouseLeave={onMouseUp}
          style={{
            display: 'block',
            cursor: dragRef.current ? 'grabbing' : 'grab',
            userSelect: 'none',
          }}
        >
          <g
            data-testid="lattice-svg-viewport"
            transform={`translate(${view.tx},${view.ty}) scale(${view.scale})`}
          >
            {/* Column headers */}
            {(Object.keys(LAYER_LABELS) as LatticeLayer[]).map((layer) => {
              const x = SIDE_MARGIN + LAYER_COLS[layer] * (COL_WIDTH + COL_GAP) + NODE_W / 2
              return (
                <text
                  key={layer}
                  x={x} y={18}
                  textAnchor="middle"
                  className="fill-[var(--color-dim)]"
                  style={{ fontSize: 10, fontFamily: 'ui-monospace, monospace', letterSpacing: '0.05em' }}
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
              />
            ))}
          </g>
        </svg>
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
      />
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

  return { nodes: Object.values(posById), edges: laidEdges, width, height }
}


// ── Node rendering ─────────────────────────────────────

function NodeSvg({
  node, x, y, w, h, selected, dimmed, focused, onClick,
}: {
  node: LatticeGraphNode
  x: number; y: number; w: number; h: number
  selected: boolean
  dimmed: boolean
  focused: boolean
  onClick: () => void
}) {
  const prov = node.provenance.computed_by
  const isDiamond = prov === 'llm' || prov === 'llm+validator' || prov === 'llm+mmr'
  const severity = (node.attrs as Record<string, unknown>).severity as string | undefined
  const sevColor = severity ? SEVERITY_COLOR[severity as keyof typeof SEVERITY_COLOR] : undefined
  const strokeColor = selected
    ? 'var(--color-accent)'
    : sevColor ?? 'var(--color-border)'
  const strokeWidth = selected ? 2.5 : focused ? 2 : 1
  const fill = dimmed ? 'var(--color-panel)' : 'var(--color-bg)'
  const opacity = dimmed ? 0.35 : 1

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
      className={shapeClass}
      onClick={onClick}
      style={{ cursor: 'pointer', opacity }}
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
