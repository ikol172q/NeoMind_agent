import {
  type LatticeGraphNode, type LatticeGraphEdge, type LatticeGraphPayload,
  type MembershipComputationDetail,
} from '@/lib/api'
import { X } from 'lucide-react'

export type TraceSelection =
  | { type: 'node'; node: LatticeGraphNode }
  | { type: 'edge'; edge: LatticeGraphEdge }
  | null

interface Props {
  selection: TraceSelection
  graph: LatticeGraphPayload
  onClose: () => void
  onSelectNodeById: (id: string) => void
}

const PROVENANCE_LABEL: Record<string, string> = {
  'source':          '🔌 external widget',
  'deterministic':   '🔧 deterministic algorithm (no LLM)',
  'llm':             '✨ LLM output',
  'llm+validator':   '✨🛡 LLM output + validator',
  'llm+mmr':         '✨📐 LLM candidate + MMR selection',
}

export function LatticeTracePanel({
  selection, graph, onClose, onSelectNodeById,
}: Props) {
  if (!selection) {
    return (
      <div
        data-testid="trace-panel-empty"
        className="w-80 shrink-0 border-l border-[var(--color-border)] p-3 text-[11px] text-[var(--color-dim)] italic"
      >
        Click any node or edge to see how it was computed.
      </div>
    )
  }

  return (
    <div
      data-testid="trace-panel"
      className="w-80 shrink-0 border-l border-[var(--color-border)] bg-[var(--color-panel)] flex flex-col min-h-0"
    >
      <div className="flex items-center gap-2 px-3 py-1.5 border-b border-[var(--color-border)] shrink-0">
        <span className="text-[10px] uppercase tracking-wider text-[var(--color-dim)] flex-1">
          {selection.type === 'node' ? 'Node · trace' : 'Edge · trace'}
        </span>
        <button
          data-testid="trace-panel-close"
          onClick={onClose}
          className="text-[var(--color-dim)] hover:text-[var(--color-text)]"
        >
          <X size={12} />
        </button>
      </div>
      <div className="flex-1 overflow-y-auto p-3 text-[11px] text-[var(--color-text)] leading-[1.55]">
        {selection.type === 'node'
          ? <NodeDetail node={selection.node} onSelectNodeById={onSelectNodeById} />
          : <EdgeDetail edge={selection.edge} graph={graph} onSelectNodeById={onSelectNodeById} />
        }
      </div>
    </div>
  )
}


// ── Node detail ────────────────────────────────────────

function NodeDetail({
  node, onSelectNodeById,
}: {
  node: LatticeGraphNode
  onSelectNodeById: (id: string) => void
}) {
  const prov = node.provenance
  const attrs = node.attrs as Record<string, unknown>

  return (
    <div className="flex flex-col gap-3" data-testid="trace-node-detail">
      <Section title="Identity">
        <KV k="id" v={node.id} />
        <KV k="layer" v={node.layer} />
        <KV k="label" v={node.label} />
      </Section>

      <Section title="Provenance">
        <div className="mb-1 text-[var(--color-accent)]"
             data-testid="trace-panel-provenance">
          {PROVENANCE_LABEL[prov.computed_by] ?? prov.computed_by}
        </div>
        <KV k="method" v={prov.method} />
        {prov.model && <KV k="model" v={prov.model} />}
        {prov.inputs.length > 0 && (
          <div>
            <div className="text-[var(--color-dim)] text-[10px] uppercase tracking-wider pt-1">
              Inputs ({prov.inputs.length})
            </div>
            <div className="flex flex-wrap gap-1 pt-0.5">
              {prov.inputs.map((id) => (
                <button
                  key={id}
                  data-testid={`trace-input-${id}`}
                  onClick={() => onSelectNodeById(id)}
                  className="px-1.5 py-0.5 rounded border border-[var(--color-border)] text-[10px] font-mono text-[var(--color-accent)] hover:bg-[var(--color-bg)]/60"
                  title={`jump to ${id}`}
                >
                  {id}
                </button>
              ))}
            </div>
          </div>
        )}
      </Section>

      <Section title="Attributes">
        {Object.entries(attrs).map(([k, v]) => (
          <KV key={k} k={k} v={formatAttr(v)} />
        ))}
      </Section>
    </div>
  )
}


// ── Edge detail ────────────────────────────────────────

function EdgeDetail({
  edge, graph, onSelectNodeById,
}: {
  edge: LatticeGraphEdge
  graph: LatticeGraphPayload
  onSelectNodeById: (id: string) => void
}) {
  const nodeById = Object.fromEntries(graph.nodes.map(n => [n.id, n]))
  const src = nodeById[edge.source]
  const tgt = nodeById[edge.target]

  return (
    <div className="flex flex-col gap-3" data-testid="trace-edge-detail">
      <Section title="Endpoints">
        <NodeLink node={src} label="source" onClick={() => onSelectNodeById(edge.source)} />
        <NodeLink node={tgt} label="target" onClick={() => onSelectNodeById(edge.target)} />
      </Section>

      <Section title="Kind">
        <div>
          <span data-testid="trace-edge-kind"
                className="px-1.5 py-0.5 rounded border border-[var(--color-border)] font-mono text-[10px]">
            {edge.kind}
          </span>
        </div>
        {edge.weight !== null && (
          <KV k="weight (rounded)" v={edge.weight.toFixed(3)}
              testId="trace-edge-weight" />
        )}
      </Section>

      <Section title="Computation">
        <KV k="method" v={edge.computation.method} />
        {edge.kind === 'membership' && <MembershipBreakdown
          detail={edge.computation.detail as unknown as MembershipComputationDetail}
        />}
        {edge.kind === 'grounds' && <GroundsDetail detail={edge.computation.detail} />}
        {edge.kind === 'source_emission' && <SourceEmissionDetail detail={edge.computation.detail} />}
      </Section>
    </div>
  )
}

function MembershipBreakdown({ detail }: { detail: MembershipComputationDetail }) {
  const base = detail.base
  const bonus = detail.severity_bonus
  const final = detail.final
  return (
    <div className="flex flex-col gap-1 pt-1"
         data-testid="trace-edge-computation-membership">
      <div className="font-mono text-[10px] text-[var(--color-dim)]">
        base = |tags ∩ any_of| / |any_of|
      </div>
      <div className="font-mono text-[10.5px]">
        <span data-testid="trace-edge-jaccard">
          {detail.jaccard_num}/{detail.jaccard_den}
        </span>
        {' '}
        {detail.all_of_required.length > 0 && detail.all_of_satisfied && (
          <span className="text-[var(--color-green)]">· all_of ✓</span>
        )}
        {detail.all_of_required.length > 0 && !detail.all_of_satisfied && (
          <span className="text-[var(--color-red)]">· all_of ✗</span>
        )}
      </div>
      <div className="font-mono text-[10.5px]">
        base = <span data-testid="trace-edge-base">{base.toFixed(4)}</span>
      </div>
      <div className="font-mono text-[10px] text-[var(--color-dim)] pt-1">
        final = clip(base × severity_bonus, 0, 1)
      </div>
      <div className="font-mono text-[10.5px]">
        severity = {detail.severity} · bonus =
        <span data-testid="trace-edge-severity-bonus"> {bonus.toFixed(2)}</span>
      </div>
      <div className="font-mono text-[11px] pt-1">
        final = <span
          data-testid="trace-edge-final"
          className="text-[var(--color-accent)]"
        >{final.toFixed(6)}</span>
      </div>
      {detail.any_of_matched.length > 0 && (
        <div className="pt-1">
          <div className="text-[10px] uppercase tracking-wider text-[var(--color-dim)]">
            any_of matched
          </div>
          <div className="flex flex-wrap gap-1 pt-0.5">
            {detail.any_of_matched.map((t) => (
              <span key={t} className="px-1 rounded border border-[var(--color-border)] font-mono text-[10px]">
                {t}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function GroundsDetail({ detail }: { detail: Record<string, unknown> }) {
  const lam = detail.mmr_lambda as number | undefined
  const maxCalls = detail.max_calls as number | undefined
  const maxCand = detail.max_candidates as number | undefined
  return (
    <div className="flex flex-col gap-0.5 pt-1 font-mono text-[10.5px]"
         data-testid="trace-edge-computation-grounds">
      <div>This theme was selected by the LLM as a ground,</div>
      <div>and survived MMR diversity selection:</div>
      <div className="pt-1">MMR λ = {lam}</div>
      <div>pool cap = {maxCand} candidates</div>
      <div>output cap = {maxCalls} calls</div>
      <div className="text-[var(--color-dim)] pt-1 text-[9.5px]">
        (per-candidate MMR scores land in V4 instrumentation.)
      </div>
    </div>
  )
}

function SourceEmissionDetail({ detail }: { detail: Record<string, unknown> }) {
  return (
    <div className="flex flex-col gap-0.5 pt-1 font-mono text-[10.5px]"
         data-testid="trace-edge-computation-source">
      <div>widget: {String(detail.widget)}</div>
      <div>generator: {String(detail.generator)}</div>
      {detail.field ? <div>field: {String(detail.field)}</div> : null}
      {detail.symbol ? <div>symbol: {String(detail.symbol)}</div> : null}
    </div>
  )
}


// ── Tiny helpers ───────────────────────────────────────

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider text-[var(--color-dim)] border-b border-[var(--color-border)] pb-0.5 mb-1">
        {title}
      </div>
      <div className="flex flex-col gap-0.5">{children}</div>
    </div>
  )
}

function KV({
  k, v, testId,
}: {
  k: string
  v: React.ReactNode
  testId?: string
}) {
  return (
    <div className="flex gap-2 text-[10.5px]">
      <span className="text-[var(--color-dim)] w-24 shrink-0 font-mono">{k}</span>
      <span className="flex-1 font-mono break-words" data-testid={testId}>{v}</span>
    </div>
  )
}

function NodeLink({
  node, label, onClick,
}: {
  node: LatticeGraphNode | undefined
  label: string
  onClick: () => void
}) {
  if (!node) return <KV k={label} v={<span className="text-[var(--color-red)]">(missing)</span>} />
  return (
    <div className="flex gap-2 text-[10.5px]">
      <span className="text-[var(--color-dim)] w-16 shrink-0 font-mono">{label}</span>
      <button
        onClick={onClick}
        data-testid={`trace-edge-${label}-link`}
        className="flex-1 text-left font-mono text-[var(--color-accent)] hover:underline"
        title={`open ${node.id}`}
      >
        [{node.layer}] {node.label.length > 40 ? node.label.slice(0, 39) + '…' : node.label}
      </button>
    </div>
  )
}

function formatAttr(v: unknown): string {
  if (v === null || v === undefined) return '—'
  if (typeof v === 'string') return v.length > 80 ? v.slice(0, 79) + '…' : v
  if (typeof v === 'number' || typeof v === 'boolean') return String(v)
  if (Array.isArray(v)) {
    return v.length === 0 ? '[]' : v.map(x => String(x)).join(', ').slice(0, 200)
  }
  if (typeof v === 'object') {
    const s = JSON.stringify(v)
    return s.length > 140 ? s.slice(0, 139) + '…' : s
  }
  return String(v)
}
