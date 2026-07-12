/**
 * CognitionMap — personal world-model knowledge graph.
 *
 * Force-graph of typed nodes; colour encodes provenance state (req7 at a
 * glance: red=unverified candidate … blue=source-anchored). Lens switcher
 * projects the graph onto one edge family (causal/time/space/…) for the
 * multi-dimensional view (req4). LOD labels keep dense graphs readable (req9).
 *
 * Modelled on ArchitectureView.tsx (same ResizeObserver + focus + label-LOD
 * pattern); structured with no early-return before the canvas container so the
 * ResizeObserver ref always attaches (see troubleshooting 2026-04-24).
 */
import { useMemo, useRef, useState, useEffect, useCallback } from 'react'
import ForceGraph2D, { type ForceGraphMethods } from 'react-force-graph-2d'
import { Loader2, Search, Plus, Network, ShieldCheck, Sparkles, Link2, Anchor, Trash2, Download } from 'lucide-react'
import {
  useMapGraph, useMapMeta, useMapNode, useSaveNode, useLinkNodes, useDeleteNode,
  useSelfcheck, useGround, useConnect, useExpand, useMapSearch,
  PROV_COLOR, PROV_LABEL, TRUSTED_STATES,
  type ProvState, type MapNodeRow, type NodeDetail, type SelfcheckIssue,
} from '@/lib/cognition'

interface Props { projectId: string }

interface GraphNode extends MapNodeRow { x?: number; y?: number; __r: number }
interface GraphLink { source: string | GraphNode; target: string | GraphNode; rel: string; state: ProvState }

export function CognitionMapTab({ projectId }: Props) {
  const metaQ = useMapMeta()
  const [lens, setLens] = useState<string | null>(null)
  const graphQ = useMapGraph(projectId, lens)
  const [search, setSearch] = useState('')
  const [semantic, setSemantic] = useState(false)
  const searchQ = useMapSearch(projectId, search, semantic)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const detailQ = useMapNode(projectId, selectedId)
  const [showCreate, setShowCreate] = useState(false)
  const [showAudit, setShowAudit] = useState(false)
  // Privacy toggle for AI actions: off = local model only; on = personal
  // content may go to a cloud model. Off by default (混合路由).
  const [allowCloud, setAllowCloud] = useState(false)
  const auditQ = useSelfcheck(projectId, showAudit)
  const [containerSize, setContainerSize] = useState({ w: 800, h: 700 })
  const containerRef = useRef<HTMLDivElement>(null)
  const graphRef = useRef<ForceGraphMethods<GraphNode, GraphLink> | undefined>(undefined)

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

  const nodes = graphQ.data?.nodes ?? []
  const edges = graphQ.data?.edges ?? []

  // degree → node radius (more-connected nodes read as bigger)
  const degree = useMemo(() => {
    const d = new Map<string, number>()
    for (const e of edges) {
      d.set(e.source_id, (d.get(e.source_id) ?? 0) + 1)
      d.set(e.target_id, (d.get(e.target_id) ?? 0) + 1)
    }
    return d
  }, [edges])

  const graphData = useMemo<{ nodes: GraphNode[]; links: GraphLink[] }>(() => {
    const gnodes: GraphNode[] = nodes.map(n => ({
      ...n,
      __r: Math.max(4, Math.min(18, 4 + (degree.get(n.id) ?? 0) * 2)),
    }))
    const ids = new Set(gnodes.map(n => n.id))
    const links: GraphLink[] = edges
      .filter(e => ids.has(e.source_id) && ids.has(e.target_id))
      .map(e => ({ source: e.source_id, target: e.target_id, rel: e.rel, state: e.state }))
    return { nodes: gnodes, links }
  }, [nodes, edges, degree])

  const neighborhood = useMemo(() => {
    const out = new Map<string, Set<string>>()
    for (const e of edges) {
      if (!out.has(e.source_id)) out.set(e.source_id, new Set())
      if (!out.has(e.target_id)) out.set(e.target_id, new Set())
      out.get(e.source_id)!.add(e.target_id)
      out.get(e.target_id)!.add(e.source_id)
    }
    return out
  }, [edges])

  const linkedSet = useMemo(() => {
    if (!selectedId) return null
    const s = new Set<string>([selectedId])
    neighborhood.get(selectedId)?.forEach(n => s.add(n))
    return s
  }, [selectedId, neighborhood])

  const listed = useMemo(() => {
    // Semantic mode: server-ranked results (already sorted by similarity).
    if (semantic && search.trim() && searchQ.data?.ok) return searchQ.data.results
    const q = search.trim().toLowerCase()
    return nodes
      .filter(n => !q || n.title.toLowerCase().includes(q) || n.id.toLowerCase().includes(q))
      .sort((a, b) => (degree.get(b.id) ?? 0) - (degree.get(a.id) ?? 0))
  }, [nodes, search, degree, semantic, searchQ.data])

  const focusNode = useCallback((id: string) => {
    setSelectedId(id)
    const node = graphData.nodes.find(n => n.id === id)
    if (node && node.x != null && node.y != null) {
      graphRef.current?.centerAt(node.x, node.y, 600)
      graphRef.current?.zoom(1.6, 600)
    }
  }, [graphData.nodes])

  const lensKeys = Object.keys(metaQ.data?.lenses ?? {})
  const counts = useMemo(() => {
    const c: Record<string, number> = {}
    for (const n of nodes) c[n.prov_state] = (c[n.prov_state] ?? 0) + 1
    return c
  }, [nodes])

  return (
    <div className="flex flex-col lg:flex-row gap-3 h-[78vh]" data-testid="cognition-map">
      {/* Side panel */}
      <div className="w-full lg:w-[300px] flex-shrink-0 flex flex-col bg-[var(--color-panel)]/40 border border-[var(--color-border)] rounded">
        <div className="p-2.5 border-b border-[var(--color-border)] space-y-2">
          <div className="flex items-center justify-between">
            <div className="text-[10px] uppercase tracking-wider text-[var(--color-dim)] flex items-center gap-1">
              <Network size={11} /> {nodes.length} 节点 · {edges.length} 边
            </div>
            <div className="flex items-center gap-1">
              <button
                onClick={() => setShowAudit(v => !v)}
                className={`text-[10px] px-1.5 py-0.5 rounded border flex items-center gap-1 ${
                  showAudit ? 'border-[var(--color-accent)] text-[var(--color-accent)]'
                            : 'border-[var(--color-border)] hover:border-[var(--color-accent)]'}`}
                title="自查: 未验证/过期/无源/矛盾"
              >
                <ShieldCheck size={10} /> 审查{auditQ.data ? ` (${auditQ.data.issue_count})` : ''}
              </button>
              <button
                onClick={() => setShowCreate(v => !v)}
                className="text-[10px] px-1.5 py-0.5 rounded border border-[var(--color-border)] hover:border-[var(--color-accent)] flex items-center gap-1"
              >
                <Plus size={10} /> 新建
              </button>
              <a
                href={`/api/map/backup?project_id=${encodeURIComponent(projectId)}`}
                title="备份: 下载整个图谱 (.bundle，含完整 git 历史，可 git clone 还原)"
                className="text-[10px] px-1.5 py-0.5 rounded border border-[var(--color-border)] hover:border-[var(--color-accent)] flex items-center gap-1 text-[var(--color-dim)]"
              >
                <Download size={10} /> 备份
              </a>
            </div>
          </div>
          <div className="flex items-center gap-1">
            <div className="relative flex-1">
              <Search size={11} className="absolute left-2 top-1/2 -translate-y-1/2 text-[var(--color-dim)]" />
              <input
                type="text" value={search} onChange={e => setSearch(e.target.value)}
                placeholder={semantic ? '语义搜索（按意思找）…' : '搜索节点 / id…'}
                className="w-full pl-7 pr-2 py-1 bg-[var(--color-bg)] border border-[var(--color-border)] rounded text-[11px] outline-none focus:border-[var(--color-accent)]"
              />
            </div>
            <button
              onClick={() => setSemantic(v => !v)}
              title="语义搜索（按意思找相关节点，而非关键词）"
              className={`text-[9px] px-1.5 py-1 rounded border flex-shrink-0 flex items-center gap-1 ${
                semantic ? 'border-[var(--color-accent)] text-[var(--color-accent)]'
                         : 'border-[var(--color-border)] text-[var(--color-dim)] hover:border-[var(--color-accent)]'}`}
            >
              {semantic && searchQ.isFetching ? <Loader2 size={9} className="animate-spin" /> : null}语义
            </button>
          </div>
          {semantic && searchQ.data && !searchQ.data.ok && searchQ.data.reason === 'deps_unavailable' && (
            <div className="text-[9px] text-amber-400">语义引擎未就绪（faiss/模型未装），已回退关键词</div>
          )}
          {/* Provenance legend (req7) */}
          <div className="flex flex-wrap gap-1.5 text-[9px]">
            {(metaQ.data?.provenance_states ?? []).map(s => (
              <span key={s} className="flex items-center gap-1 text-[var(--color-dim)]">
                <span className="w-2 h-2 rounded-full" style={{ background: PROV_COLOR[s] }} />
                {PROV_LABEL[s]} {counts[s] ? `(${counts[s]})` : ''}
              </span>
            ))}
          </div>
        </div>

        {/* Lens chips (req4) */}
        <div className="p-1.5 border-b border-[var(--color-border)] flex flex-wrap gap-1">
          <LensChip label="全部" active={lens === null} onClick={() => setLens(null)} />
          {lensKeys.map(k => (
            <LensChip key={k} label={k} active={lens === k} onClick={() => setLens(k)} />
          ))}
        </div>

        {showCreate && (
          <CreateNodePanel
            projectId={projectId}
            nodeTypes={metaQ.data?.node_types ?? ['concept']}
            onDone={() => setShowCreate(false)}
          />
        )}

        {showAudit && (
          <div className="border-b border-[var(--color-border)] bg-[var(--color-bg)]/40 max-h-[30%] overflow-y-auto">
            {auditQ.isLoading && <div className="p-2 text-[10px] text-[var(--color-dim)]">审查中…</div>}
            {auditQ.data && auditQ.data.issue_count === 0 && (
              <div className="p-2 text-[10px] text-green-400">✓ 无问题：{auditQ.data.node_count} 个节点都干净</div>
            )}
            {auditQ.data && auditQ.data.issues.map((it: SelfcheckIssue, i) => (
              <button key={i} onClick={() => focusNode(it.node_id)}
                className="w-full text-left px-2 py-1 text-[10px] hover:bg-[var(--color-panel)]/60 border-l-[3px] border-l-transparent">
                <span className={it.severity === 'warn' ? 'text-amber-400' : 'text-[var(--color-dim)]'}>
                  [{it.kind}]
                </span> <span className="text-[var(--color-text)]/80">{it.title}</span>
                <div className="text-[9px] text-[var(--color-dim)] pl-1">{it.detail}</div>
              </button>
            ))}
          </div>
        )}

        {/* Node list */}
        <div className="flex-1 overflow-y-auto">
          {graphQ.isLoading && <div className="p-3 text-[10px] text-[var(--color-dim)]">loading…</div>}
          {graphQ.error && <div className="p-3 text-[10px] text-red-400">{(graphQ.error as Error).message}</div>}
          {listed.map(n => {
            const isSel = selectedId === n.id
            return (
              <button
                key={n.id} onClick={() => focusNode(n.id)}
                className={`w-full text-left px-2.5 py-1 flex items-center justify-between text-[11px] border-l-[3px] transition-colors ${
                  isSel ? 'bg-[var(--color-accent)]/15 border-l-[var(--color-accent)]'
                        : 'border-l-transparent hover:bg-[var(--color-panel)]/60'}`}
              >
                <span className="flex items-center gap-1.5 min-w-0">
                  <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: PROV_COLOR[n.prov_state] }} />
                  <span className="truncate">{n.title}</span>
                </span>
                <span className="text-[9px] text-[var(--color-dim)] flex-shrink-0 ml-2">{n.type}</span>
              </button>
            )
          })}
          {!graphQ.isLoading && listed.length === 0 && (
            <div className="p-3 text-[10px] text-[var(--color-dim)] italic">
              还没有节点 — 点「新建」开始，或让 NeoMind chat 存一条结论进来。
            </div>
          )}
        </div>

        {/* Selected node detail */}
        {selectedId && (
          <div className="p-2.5 border-t border-[var(--color-border)] bg-[var(--color-panel)]/60 max-h-[42%] overflow-y-auto">
            {detailQ.isLoading && <div className="text-[10px] text-[var(--color-dim)]">loading…</div>}
            {detailQ.data && <NodeDetailView d={detailQ.data} />}
            {detailQ.data && (
              <NodeActions
                projectId={projectId} node={detailQ.data} allNodes={nodes}
                allowCloud={allowCloud} setAllowCloud={setAllowCloud}
                onDeleted={() => setSelectedId(null)}
              />
            )}
          </div>
        )}
      </div>

      {/* Force graph */}
      <div ref={containerRef} className="flex-1 relative bg-[var(--color-panel)]/20 border border-[var(--color-border)] rounded overflow-hidden min-h-[400px]">
        {graphQ.data && (
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
              const isSel = selectedId === n.id
              const trusted = TRUSTED_STATES.includes(n.prov_state)
              ctx.globalAlpha = isLinked ? 1 : 0.12
              ctx.beginPath()
              ctx.arc(n.x ?? 0, n.y ?? 0, r, 0, 2 * Math.PI)
              ctx.fillStyle = PROV_COLOR[n.prov_state]
              ctx.fill()
              // Untrusted (candidate-zone) nodes get a dashed ring so they
              // read as "not yet promoted" even at a glance (req7/req8).
              if (!trusted) {
                ctx.setLineDash([2 / scale, 2 / scale])
                ctx.strokeStyle = 'rgba(255,255,255,0.6)'
                ctx.lineWidth = 1 / scale
                ctx.stroke()
                ctx.setLineDash([])
              }
              if (isSel) {
                ctx.strokeStyle = '#fff'; ctx.lineWidth = 2 / scale; ctx.stroke()
              }
              const showLabel = isSel || (selectedId ? linkedSet?.has(n.id) : scale > 1.5) || scale > 3.5
              if (showLabel) {
                const fontPx = 11 / scale
                ctx.globalAlpha = isLinked ? 0.95 : 0.06
                ctx.fillStyle = isSel ? '#ffffff' : '#cbd5e1'
                ctx.font = `${fontPx}px system-ui`
                ctx.textAlign = 'center'; ctx.textBaseline = 'top'
                ctx.fillText(n.title.slice(0, 18), n.x ?? 0, (n.y ?? 0) + r + 1)
              }
              ctx.globalAlpha = 1
            }}
            nodePointerAreaPaint={(node, color, ctx) => {
              const n = node as GraphNode
              ctx.beginPath(); ctx.arc(n.x ?? 0, n.y ?? 0, n.__r + 2, 0, 2 * Math.PI)
              ctx.fillStyle = color; ctx.fill()
            }}
            linkColor={(link) => {
              const l = link as GraphLink
              if (!selectedId) return 'rgba(100,116,139,0.35)'
              const sId = typeof l.source === 'string' ? l.source : l.source.id
              const tId = typeof l.target === 'string' ? l.target : l.target.id
              return sId === selectedId || tId === selectedId ? 'rgba(59,130,246,0.85)' : 'rgba(71,85,105,0.05)'
            }}
            linkDirectionalArrowLength={3}
            linkDirectionalArrowRelPos={1}
            onNodeClick={(node) => focusNode((node as GraphNode).id)}
            onBackgroundClick={() => setSelectedId(null)}
          />
        )}
      </div>
    </div>
  )
}

function LensChip({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={`text-[9px] px-1.5 py-0.5 rounded border transition-colors ${
        active ? 'bg-[var(--color-accent)] border-[var(--color-accent)] text-white'
               : 'border-[var(--color-border)] text-[var(--color-dim)] hover:border-[var(--color-accent)]'}`}
    >
      {label}
    </button>
  )
}

function NodeDetailView({ d }: { d: import('@/lib/cognition').NodeDetail }) {
  // The full-node endpoint carries provenance.state (authoritative); the flat
  // prov_state only exists on index rows, so read the nested field here.
  const state = d.provenance.state
  return (
    <div>
      <div className="flex items-center gap-1.5 mb-0.5">
        <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: PROV_COLOR[state] }} />
        <span className="text-[12px] font-semibold text-[var(--color-text)]">{d.title}</span>
      </div>
      <div className="text-[9px] text-[var(--color-dim)] mb-1.5">
        {d.type} · {PROV_LABEL[state]} · {d.confidence} · {d.origin}
      </div>
      {d.body && <div className="text-[10px] leading-snug text-[var(--color-text)]/80 mb-1.5 whitespace-pre-wrap">{d.body}</div>}
      {d.sources.length > 0 && (
        <div className="text-[9px] text-[var(--color-dim)] mb-1">
          来源: {d.sources.map(s => <span key={s} className="font-mono">{s.slice(0, 16)}… </span>)}
        </div>
      )}
      {d.edges.length > 0 && (
        <div className="text-[9px] text-[var(--color-dim)]">
          {d.edges.length} 条边: {d.edges.map((e, i) => <span key={i}>{e.rel}→{e.target.slice(0, 10)} </span>)}
        </div>
      )}
    </div>
  )
}

function CreateNodePanel({ projectId, nodeTypes, onDone }:
  { projectId: string; nodeTypes: string[]; onDone: () => void }) {
  const [title, setTitle] = useState('')
  const [type, setType] = useState(nodeTypes[0] ?? 'concept')
  const [body, setBody] = useState('')
  const save = useSaveNode(projectId)
  const submit = () => {
    if (!title.trim()) return
    save.mutate({ title: title.trim(), type, body }, {
      onSuccess: () => { setTitle(''); setBody(''); onDone() },
    })
  }
  return (
    <div className="p-2 border-b border-[var(--color-border)] space-y-1.5 bg-[var(--color-bg)]/40">
      <input
        autoFocus value={title} onChange={e => setTitle(e.target.value)}
        placeholder="节点标题…"
        className="w-full px-2 py-1 bg-[var(--color-bg)] border border-[var(--color-border)] rounded text-[11px] outline-none focus:border-[var(--color-accent)]"
      />
      <div className="flex gap-1.5">
        <select value={type} onChange={e => setType(e.target.value)}
          className="px-1.5 py-1 bg-[var(--color-bg)] border border-[var(--color-border)] rounded text-[10px] outline-none">
          {nodeTypes.map(t => <option key={t} value={t}>{t}</option>)}
        </select>
        <button onClick={submit} disabled={save.isPending || !title.trim()}
          className="flex-1 text-[10px] px-2 py-1 rounded bg-[var(--color-accent)] text-white disabled:opacity-50 flex items-center justify-center gap-1">
          {save.isPending ? <Loader2 size={10} className="animate-spin" /> : <Plus size={10} />} 保存 (未验证)
        </button>
      </div>
      <textarea value={body} onChange={e => setBody(e.target.value)}
        placeholder="正文（可选）…" rows={2}
        className="w-full px-2 py-1 bg-[var(--color-bg)] border border-[var(--color-border)] rounded text-[10px] outline-none focus:border-[var(--color-accent)] resize-none" />
      {save.error && <div className="text-[9px] text-red-400">{(save.error as Error).message}</div>}
    </div>
  )
}

function NodeActions({ projectId, node, allNodes, allowCloud, setAllowCloud, onDeleted }: {
  projectId: string; node: NodeDetail; allNodes: MapNodeRow[]
  allowCloud: boolean; setAllowCloud: (v: boolean) => void; onDeleted: () => void
}) {
  const expand = useExpand(projectId)
  const connect = useConnect(projectId)
  const ground = useGround(projectId)
  const save = useSaveNode(projectId)
  const link = useLinkNodes(projectId)
  const del = useDeleteNode(projectId)
  const [target, setTarget] = useState('')
  const [url, setUrl] = useState('')
  const [phrase, setPhrase] = useState('')
  const others = allNodes.filter(n => n.id !== node.id)
  const localErr = (reason?: string) =>
    reason === 'local_model_unavailable' ? '本地模型不可达 — 勾选「用云端」或启动 MLX' : reason

  return (
    <div className="mt-2 pt-2 border-t border-[var(--color-border)] space-y-2">
      <label className="flex items-center gap-1 text-[9px] text-[var(--color-dim)]">
        <input type="checkbox" checked={allowCloud} onChange={e => setAllowCloud(e.target.checked)} />
        用云端模型（个人内容会发送到云）
      </label>

      {/* expand (req8) */}
      <div>
        <button onClick={() => expand.mutate({ node_id: node.id, allow_cloud: allowCloud })}
          disabled={expand.isPending}
          className="text-[10px] px-1.5 py-0.5 rounded border border-[var(--color-border)] hover:border-[var(--color-accent)] flex items-center gap-1 disabled:opacity-50">
          {expand.isPending ? <Loader2 size={10} className="animate-spin" /> : <Sparkles size={10} />} 拓展（LLM 建议相关概念）
        </button>
        {expand.data && !expand.data.ok && <div className="text-[9px] text-amber-400 mt-1">{localErr(expand.data.reason)}</div>}
        {expand.error && <div className="text-[9px] text-red-400 mt-1">调用失败: {(expand.error as Error).message}</div>}
        {expand.data?.ok && expand.data.suggestions?.map((s, i) => (
          <div key={i} className="flex items-center justify-between gap-1 mt-1 text-[10px]">
            <span className="truncate" title={s.why}>🔴 {s.title} <span className="text-[var(--color-dim)]">({s.type})</span></span>
            <button onClick={() => save.mutate({ title: s.title, type: s.type, origin: 'llm-expand', body: s.why })}
              className="text-[9px] px-1 py-0.5 rounded border border-[var(--color-border)] hover:border-[var(--color-accent)] flex-shrink-0">添加</button>
          </div>
        ))}
      </div>

      {/* connect (req3) */}
      <div>
        <div className="flex items-center gap-1">
          <select value={target} onChange={e => setTarget(e.target.value)}
            className="flex-1 min-w-0 px-1 py-0.5 bg-[var(--color-bg)] border border-[var(--color-border)] rounded text-[9px] outline-none">
            <option value="">连接到…</option>
            {others.map(n => <option key={n.id} value={n.id}>{n.title}</option>)}
          </select>
          <button onClick={() => target && connect.mutate({ a: node.id, b: target, allow_cloud: allowCloud })}
            disabled={!target || connect.isPending}
            className="text-[9px] px-1.5 py-0.5 rounded border border-[var(--color-border)] hover:border-[var(--color-accent)] disabled:opacity-50 flex items-center gap-1 flex-shrink-0">
            {connect.isPending ? <Loader2 size={10} className="animate-spin" /> : <Link2 size={10} />} 分析
          </button>
        </div>
        {connect.data && !connect.data.ok && <div className="text-[9px] text-amber-400 mt-1">{localErr(connect.data.reason)}</div>}
        {connect.error && <div className="text-[9px] text-red-400 mt-1">调用失败: {(connect.error as Error).message}</div>}
        {connect.data?.ok && connect.data.suggestion && (
          <div className="mt-1 text-[10px]">
            <div className="text-[var(--color-text)]/80">建议: <b>{connect.data.suggestion.rel}</b> · {connect.data.suggestion.reason}</div>
            <button onClick={() => { const s = connect.data!.suggestion!; link.mutate({ source_id: s.source_id, target: s.target, rel: s.rel, note: s.reason }) }}
              className="text-[9px] px-1 py-0.5 mt-0.5 rounded border border-[var(--color-border)] hover:border-[var(--color-accent)]">应用（未验证边）</button>
          </div>
        )}
      </div>

      {/* ground (req7 promotion gate) */}
      <div className="space-y-1">
        <input value={url} onChange={e => setUrl(e.target.value)} placeholder="来源 URL…"
          className="w-full px-1.5 py-0.5 bg-[var(--color-bg)] border border-[var(--color-border)] rounded text-[9px] outline-none" />
        <input value={phrase} onChange={e => setPhrase(e.target.value)} placeholder="必须在该页面逐字出现的短语…"
          className="w-full px-1.5 py-0.5 bg-[var(--color-bg)] border border-[var(--color-border)] rounded text-[9px] outline-none" />
        <button onClick={() => url && phrase && ground.mutate({ node_id: node.id, url, phrase })}
          disabled={!url || !phrase || ground.isPending}
          className="text-[9px] px-1.5 py-0.5 rounded border border-[var(--color-border)] hover:border-[var(--color-accent)] disabled:opacity-50 flex items-center gap-1">
          {ground.isPending ? <Loader2 size={10} className="animate-spin" /> : <Anchor size={10} />} 验证并锚定来源
        </button>
        {ground.data && (
          <div className={`text-[9px] ${ground.data.ok ? 'text-green-400' : 'text-amber-400'}`}>
            {ground.data.ok ? `✓ 已锚定 → ${ground.data.state}`
              : (ground.data.reason === 'phrase_not_found_verbatim' ? '✗ 短语未在页面中逐字出现 — 未晋升' : ground.data.reason)}
          </div>
        )}
        {ground.error && <div className="text-[9px] text-red-400">调用失败: {(ground.error as Error).message}</div>}
      </div>

      {/* delete */}
      <button
        onClick={() => { if (confirm(`删除节点「${node.title}」？(本地 git 仍保留历史)`)) del.mutate(node.id, { onSuccess: onDeleted }) }}
        disabled={del.isPending}
        className="text-[9px] px-1.5 py-0.5 rounded border border-red-500/40 text-red-400 hover:bg-red-500/10 disabled:opacity-50 flex items-center gap-1">
        {del.isPending ? <Loader2 size={10} className="animate-spin" /> : <Trash2 size={10} />} 删除节点
      </button>
    </div>
  )
}
