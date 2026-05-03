/**
 * ArchitectureView — codebase module force-graph (replaces the
 * standalone plans/architecture_interactive.html).
 *
 * Data: GET /api/architecture (cached AST-parsed JSON from
 *   scripts/gen_architecture.py)
 * Action: POST /api/architecture/regenerate (re-runs the generator)
 *
 * Design choices:
 * - react-force-graph-2d (canvas) handles ~100 nodes / ~200 edges
 *   smoothly at 60fps and is ~10KB gzipped.
 * - Side panel: search + group filter + module list + selected detail.
 * - Click highlights node + neighbors, dims rest. Click empty space
 *   clears selection.
 * - Hover tooltip shows path + lines + classes/funcs counts.
 */
import { useMemo, useRef, useState, useEffect, useCallback } from 'react'
import ForceGraph2D, { type ForceGraphMethods } from 'react-force-graph-2d'
import { Loader2, Sparkles, Search } from 'lucide-react'
import { useArchitecture, useRegenArchitecture, type ArchModule } from '@/lib/api'

interface GraphNode extends ArchModule {
  x?: number
  y?: number
  __r: number  // node radius derived from line count
}

interface GraphLink {
  source: string | GraphNode
  target: string | GraphNode
  synthetic?: boolean
}

export function ArchitectureView() {
  const dataQ = useArchitecture()
  const regenMu = useRegenArchitecture()
  const [search, setSearch] = useState('')
  const [activeGroups, setActiveGroups] = useState<Set<string>>(new Set())
  const [selected, setSelected] = useState<ArchModule | null>(null)
  const [hovered, setHovered] = useState<ArchModule | null>(null)
  const [containerSize, setContainerSize] = useState({ w: 800, h: 700 })
  const containerRef = useRef<HTMLDivElement>(null)
  const graphRef = useRef<ForceGraphMethods<GraphNode, GraphLink> | undefined>(undefined)

  // Resize observer so the canvas tracks the parent
  useEffect(() => {
    if (!containerRef.current) return
    const ro = new ResizeObserver(entries => {
      for (const e of entries) {
        const { width, height } = e.contentRect
        setContainerSize({ w: Math.max(400, width), h: Math.max(400, height) })
      }
    })
    ro.observe(containerRef.current)
    return () => ro.disconnect()
  }, [])

  // Once data loads, default all groups on
  useEffect(() => {
    if (!dataQ.data) return
    setActiveGroups(new Set(dataQ.data.modules.map(m => m.group)))
  }, [dataQ.data])

  // Group palette derived from data (group → label, color, count)
  const groups = useMemo(() => {
    const map = new Map<string, { label: string; color: string; count: number }>()
    for (const m of dataQ.data?.modules ?? []) {
      const e = map.get(m.group) ?? { label: m.groupLabel, color: m.color, count: 0 }
      e.count += 1
      map.set(m.group, e)
    }
    return [...map.entries()].sort((a, b) => b[1].count - a[1].count)
  }, [dataQ.data])

  // Filtered nodes + edges fed to the force graph
  const graphData = useMemo<{ nodes: GraphNode[]; links: GraphLink[] }>(() => {
    if (!dataQ.data) return { nodes: [], links: [] }
    const filtered = dataQ.data.modules.filter(m => activeGroups.has(m.group))
    const ids = new Set(filtered.map(m => m.id))
    const nodes: GraphNode[] = filtered.map(m => ({
      ...m,
      __r: Math.max(4, Math.min(22, Math.sqrt(m.lines / 10))),
    }))
    const links: GraphLink[] = dataQ.data.edges
      .filter(e => ids.has(e.source) && ids.has(e.target))
      .map(e => ({ source: e.source, target: e.target, synthetic: e.synthetic }))
    return { nodes, links }
  }, [dataQ.data, activeGroups])

  // Side-panel module list (search + active-group + sort by lines desc)
  const listed = useMemo(() => {
    if (!dataQ.data) return []
    const q = search.trim().toLowerCase()
    return dataQ.data.modules
      .filter(m => activeGroups.has(m.group))
      .filter(m => !q || m.name.toLowerCase().includes(q) || m.path.toLowerCase().includes(q))
      .sort((a, b) => b.lines - a.lines)
  }, [dataQ.data, activeGroups, search])

  // Neighborhood lookup for highlight on click
  const neighborhood = useMemo(() => {
    const out = new Map<string, Set<string>>()
    for (const e of dataQ.data?.edges ?? []) {
      if (!out.has(e.source)) out.set(e.source, new Set())
      if (!out.has(e.target)) out.set(e.target, new Set())
      out.get(e.source)!.add(e.target)
      out.get(e.target)!.add(e.source)
    }
    return out
  }, [dataQ.data])

  const linkedSet = useMemo(() => {
    if (!selected) return null
    const s = new Set<string>([selected.id])
    neighborhood.get(selected.id)?.forEach(n => s.add(n))
    return s
  }, [selected, neighborhood])

  const toggleGroup = (g: string) => {
    setActiveGroups(prev => {
      const next = new Set(prev)
      if (next.has(g)) next.delete(g)
      else next.add(g)
      return next
    })
  }

  const focusNode = useCallback((m: ArchModule) => {
    setSelected(m)
    const node = graphData.nodes.find(n => n.id === m.id)
    if (node && node.x != null && node.y != null) {
      graphRef.current?.centerAt(node.x, node.y, 600)
      // Light zoom so the neighborhood stays in frame; aggressive
      // zoom (>2x) makes labels collide with each other.
      graphRef.current?.zoom(1.4, 600)
    }
  }, [graphData.nodes])

  const tooltipModule = hovered ?? selected
  const generatedAtRel = dataQ.data?.generated_at
    ? `${Math.round((Date.now() / 1000 - dataQ.data.generated_at) / 60)} 分钟前`
    : '—'

  return (
    <div className="flex gap-3 h-[700px]" data-testid="architecture-view">
      {/* Side panel */}
      <div className="w-[280px] flex-shrink-0 flex flex-col bg-[var(--color-panel)]/40 border border-[var(--color-border)] rounded">
        <div className="p-2.5 border-b border-[var(--color-border)] space-y-2">
          <div className="flex items-center justify-between">
            <div className="text-[10px] uppercase tracking-wider text-[var(--color-dim)]">
              {dataQ.data?.modules.length ?? 0} modules · {dataQ.data?.edges.length ?? 0} edges
            </div>
            <button
              onClick={() => regenMu.mutate()}
              disabled={regenMu.isPending}
              className="text-[10px] px-1.5 py-0.5 rounded border border-[var(--color-border)] hover:border-[var(--color-accent)] flex items-center gap-1 disabled:opacity-50"
              title="重新解析 agent/ 下的 AST imports (~5-15s)"
            >
              {regenMu.isPending
                ? <><Loader2 size={10} className="animate-spin" /> 重新生成…</>
                : <><Sparkles size={10} /> regen</>}
            </button>
          </div>
          <div className="text-[9.5px] text-[var(--color-dim)]">cached {generatedAtRel}</div>
          <div className="relative">
            <Search size={11} className="absolute left-2 top-1/2 -translate-y-1/2 text-[var(--color-dim)]" />
            <input
              type="text"
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="search module / path…"
              className="w-full pl-7 pr-2 py-1 bg-[var(--color-bg)] border border-[var(--color-border)] rounded text-[11px] outline-none focus:border-[var(--color-accent)]"
            />
          </div>
        </div>

        {/* Group filter chips */}
        <div className="p-1.5 border-b border-[var(--color-border)] flex flex-wrap gap-1">
          {groups.map(([g, info]) => {
            const on = activeGroups.has(g)
            return (
              <button
                key={g}
                onClick={() => toggleGroup(g)}
                className="text-[9px] px-1.5 py-0.5 rounded border transition-opacity"
                style={{
                  borderColor: info.color,
                  background: on ? info.color : 'transparent',
                  color: on ? '#fff' : info.color,
                  opacity: on ? 1 : 0.55,
                }}
                title={`${info.count} modules`}
              >
                {info.label}
              </button>
            )
          })}
        </div>

        {/* Module list */}
        <div className="flex-1 overflow-y-auto">
          {dataQ.isLoading && (
            <div className="p-3 text-[10px] text-[var(--color-dim)]">loading…</div>
          )}
          {dataQ.error && (
            <div className="p-3 text-[10px] text-red-400">
              {(dataQ.error as Error).message}
            </div>
          )}
          {listed.map(m => {
            const isSel = selected?.id === m.id
            return (
              <button
                key={m.id}
                onClick={() => focusNode(m)}
                className={`w-full text-left px-2.5 py-1 flex items-center justify-between text-[11px] border-l-[3px] transition-colors ${
                  isSel
                    ? 'bg-[var(--color-accent)]/15 border-l-[var(--color-accent)]'
                    : 'border-l-transparent hover:bg-[var(--color-panel)]/60'
                }`}
              >
                <span className="flex items-center gap-1.5 min-w-0">
                  <span
                    className="w-1.5 h-1.5 rounded-full flex-shrink-0"
                    style={{ background: m.color }}
                  />
                  <span className="truncate">{m.name}</span>
                </span>
                <span className="text-[9px] text-[var(--color-dim)] flex-shrink-0 ml-2">
                  {m.lines}L
                </span>
              </button>
            )
          })}
          {!dataQ.isLoading && listed.length === 0 && (
            <div className="p-3 text-[10px] text-[var(--color-dim)] italic">
              no modules match
            </div>
          )}
        </div>

        {/* Selected module detail */}
        {selected && (
          <div className="p-2.5 border-t border-[var(--color-border)] bg-[var(--color-panel)]/60">
            <div className="text-[12px] font-semibold text-[var(--color-text)] mb-0.5">
              {selected.name}
            </div>
            <div className="text-[9.5px] font-mono text-[var(--color-dim)] mb-1.5">
              {selected.path}
            </div>
            <div className="grid grid-cols-3 gap-1 text-[10px] text-center mb-1.5">
              <Stat v={selected.lines} k="lines" />
              <Stat v={selected.totalClasses} k="classes" />
              <Stat v={selected.totalFunctions} k="funcs" />
            </div>
            {selected.moduleDoc && (
              <div className="text-[10px] leading-snug text-[var(--color-text)]/80 max-h-[100px] overflow-y-auto">
                {selected.moduleDoc.slice(0, 280)}
                {selected.moduleDoc.length > 280 && '…'}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Force graph */}
      <div
        ref={containerRef}
        className="flex-1 relative bg-[var(--color-panel)]/20 border border-[var(--color-border)] rounded overflow-hidden"
      >
        {dataQ.data && (
          <ForceGraph2D
            ref={graphRef}
            graphData={graphData}
            width={containerSize.w}
            height={containerSize.h}
            nodeRelSize={1}
            cooldownTicks={120}
            nodeCanvasObject={(node, ctx, scale) => {
              const n = node as GraphNode
              const r = n.__r
              const isLinked = linkedSet ? linkedSet.has(n.id) : true
              const isSel = selected?.id === n.id
              ctx.globalAlpha = isLinked ? 1 : 0.12
              ctx.beginPath()
              ctx.arc(n.x ?? 0, n.y ?? 0, r, 0, 2 * Math.PI)
              ctx.fillStyle = n.color
              ctx.fill()
              if (isSel) {
                ctx.strokeStyle = '#fff'
                ctx.lineWidth = 2 / scale
                ctx.stroke()
              }
              // Label policy — keep screen-space density manageable:
              //   - selected node + 1-hop neighbors when something is selected
              //   - otherwise only the largest modules (> 800 lines)
              //   - or when the user has zoomed way in (scale > 3.5)
              const showLabel =
                isSel
                || (selected ? (linkedSet?.has(n.id) && n.lines > 200) : n.lines > 800)
                || scale > 3.5
              if (showLabel) {
                // 11px in screen space (independent of zoom)
                const fontPx = 11 / scale
                ctx.globalAlpha = isLinked ? 0.95 : 0.06
                ctx.fillStyle = isSel ? '#ffffff' : '#cbd5e1'
                ctx.font = `${fontPx}px system-ui`
                ctx.textAlign = 'center'
                ctx.textBaseline = 'top'
                ctx.fillText(n.name, n.x ?? 0, (n.y ?? 0) + r + 1)
              }
              ctx.globalAlpha = 1
            }}
            nodePointerAreaPaint={(node, color, ctx) => {
              const n = node as GraphNode
              ctx.beginPath()
              ctx.arc(n.x ?? 0, n.y ?? 0, n.__r + 2, 0, 2 * Math.PI)
              ctx.fillStyle = color
              ctx.fill()
            }}
            linkColor={(link) => {
              const l = link as GraphLink
              if (!selected) return l.synthetic ? 'rgba(99,102,241,0.25)' : 'rgba(71,85,105,0.35)'
              const sId = typeof l.source === 'string' ? l.source : l.source.id
              const tId = typeof l.target === 'string' ? l.target : l.target.id
              const isHl = sId === selected.id || tId === selected.id
              return isHl ? 'rgba(59,130,246,0.85)' : 'rgba(71,85,105,0.04)'
            }}
            linkWidth={(link) => {
              const l = link as GraphLink
              if (!selected) return 1
              const sId = typeof l.source === 'string' ? l.source : l.source.id
              const tId = typeof l.target === 'string' ? l.target : l.target.id
              return sId === selected.id || tId === selected.id ? 2 : 1
            }}
            onNodeClick={(node) => focusNode(node as ArchModule)}
            onNodeHover={(node) => setHovered((node as ArchModule) ?? null)}
            onBackgroundClick={() => setSelected(null)}
          />
        )}

        {/* Hover tooltip */}
        {tooltipModule && (
          <div className="absolute top-2 right-2 max-w-[260px] p-2 bg-[var(--color-bg)]/95 border border-[var(--color-border)] rounded text-[10px] pointer-events-none shadow-lg">
            <div className="font-semibold text-[var(--color-text)]">{tooltipModule.name}</div>
            <div className="font-mono text-[9px] text-[var(--color-dim)] truncate">{tooltipModule.path}</div>
            <div className="text-[var(--color-dim)] mt-0.5">
              {tooltipModule.lines}L · {tooltipModule.totalClasses}c · {tooltipModule.totalFunctions}f
            </div>
            <div className="text-[9px] mt-0.5" style={{ color: tooltipModule.color }}>
              {tooltipModule.groupLabel}
            </div>
          </div>
        )}

        {regenMu.error && (
          <div className="absolute bottom-2 left-2 right-2 p-2 bg-red-500/15 border border-red-500/40 rounded text-[10px] text-red-300">
            重新生成失败: {(regenMu.error as Error).message}
          </div>
        )}
      </div>
    </div>
  )
}

function Stat({ v, k }: { v: number; k: string }) {
  return (
    <div className="bg-[var(--color-bg)]/60 rounded py-0.5">
      <div className="text-[var(--color-text)] font-semibold">{v}</div>
      <div className="text-[var(--color-dim)] text-[9px]">{k}</div>
    </div>
  )
}
