import { useState } from 'react'
import {
  useLatticeTrace,
  useWidgetStrategies,
  type LatticeGraphNode, type LatticeGraphEdge, type LatticeGraphPayload,
  type MembershipComputationDetail,
} from '@/lib/api'
import { X, ChevronRight, ChevronDown, ExternalLink, BookOpen } from 'lucide-react'

export type TraceSelection =
  | { type: 'node'; node: LatticeGraphNode }
  | { type: 'edge'; edge: LatticeGraphEdge }
  | null

interface Props {
  selection: TraceSelection
  graph: LatticeGraphPayload
  projectId: string
  onClose: () => void
  onSelectNodeById: (id: string) => void
  /** Phase 6 followup: callback to jump to Strategies tab from
   *  reverse-map chips on L0 widget nodes. */
  onJumpToStrategies?: (strategyId: string) => void
}

const PROVENANCE_LABEL: Record<string, string> = {
  'source':          '🔌 external widget',
  'deterministic':   '🔧 deterministic algorithm (no LLM)',
  'llm':             '✨ LLM output',
  'llm+validator':   '✨🛡 LLM output + validator',
  'llm+mmr':         '✨📐 LLM candidate + MMR selection',
}

export function LatticeTracePanel({
  selection, graph, projectId, onClose, onSelectNodeById, onJumpToStrategies,
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
          ? <>
              <NodeDetail node={selection.node} onSelectNodeById={onSelectNodeById} onJumpToStrategies={onJumpToStrategies} />
              <DeepTraceSection node={selection.node} projectId={projectId} />
            </>
          : <EdgeDetail edge={selection.edge} graph={graph} onSelectNodeById={onSelectNodeById} />
        }
      </div>
    </div>
  )
}


// ── Node detail ────────────────────────────────────────

function NodeDetail({
  node, onSelectNodeById, onJumpToStrategies,
}: {
  node: LatticeGraphNode
  onSelectNodeById: (id: string) => void
  onJumpToStrategies?: (strategyId: string) => void
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

      {/* V11: L1 obs nodes link upstream to the L0 widget node that
          generated them. The L0 node holds the raw widget payload
          (V10·A3) and external dashboard links (V11). Old behaviour
          (scroll to a tile in the Research grid) is dead since the
          grid moved to LegacyTab. */}
      {node.layer === 'L1' && Boolean((attrs.source as Record<string, unknown> | undefined)?.widget) && (
        <button
          data-testid="trace-jump-to-widget"
          onClick={() => {
            const w = String((attrs.source as Record<string, unknown>).widget)
            onSelectNodeById(`widget:${w}`)
          }}
          className="self-start px-2 py-0.5 rounded border border-[var(--color-accent)] text-[10px] text-[var(--color-accent)] hover:bg-[var(--color-accent)]/10"
        >
          ↳ open L0 source: {String((attrs.source as Record<string, unknown>).widget)}
        </button>
      )}

      {/* V10·A3: raw widget payload on L0 nodes — the exact JSON
          that fed the L1 generators this cycle. Collapsed by default
          so it doesn't overwhelm the panel; expand to audit. */}
      {node.layer === 'L0' && attrs.raw_payload != null && (
        <RawPayloadSection payload={attrs.raw_payload} />
      )}

      {/* V11: outbound links to authoritative public dashboards for
          this widget type. NeoMind doesn't try to compete with
          TradingView/Finviz/Yahoo on UI — it links out. */}
      {node.layer === 'L0' && typeof attrs.widget === 'string' && (
        <ExternalLinksSection widget={attrs.widget} />
      )}

      {/* Phase 6 Step 6: reverse map — which catalog strategies declare
          this L0 widget as a data dependency. Closes the audit loop:
          from a widget node in the graph, see *all strategies that
          depend on it*. */}
      {node.layer === 'L0' && typeof attrs.widget === 'string' && (
        <WidgetStrategiesSection widgetId={attrs.widget} onJumpToStrategies={onJumpToStrategies} />
      )}

      <Section title="Attributes">
        {Object.entries(attrs).map(([k, v]) => (
          <KV key={k} k={k} v={formatAttr(v)} />
        ))}
      </Section>
    </div>
  )
}


// V10·A3: show the exact widget payload on L0 nodes. Collapsed by
// default; click to expand. Preformatted JSON so the user can spot
// "nothing came from this widget this cycle" (empty arrays, nulls)
// or trace specific values back to the observations generated from them.
function RawPayloadSection({ payload }: { payload: unknown }) {
  const [open, setOpen] = useState(false)
  const text = JSON.stringify(payload, null, 2)
  const lines = text.split('\n').length
  return (
    <div data-testid="trace-l0-raw-payload" className="flex flex-col gap-1">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1 text-[10px] uppercase tracking-wider text-[var(--color-dim)] hover:text-[var(--color-text)] self-start"
      >
        {open ? <ChevronDown size={10} /> : <ChevronRight size={10} />}
        <span>Raw widget payload · {lines} lines</span>
      </button>
      {open && (
        <pre
          data-testid="trace-l0-raw-payload-body"
          className="max-h-[260px] overflow-auto p-2 rounded bg-[var(--color-bg)] border border-[var(--color-border)] text-[9.5px] font-mono text-[var(--color-text)] leading-[1.45]"
        >{text}</pre>
      )}
      <div className="text-[9px] text-[var(--color-dim)] italic leading-[1.4]">
        This is exactly what fed the L1 generators this cycle. Every
        L1 observation originates from a field in this blob.
      </div>
    </div>
  )
}


/**
 * WidgetStrategiesSection — Phase 6 Step 6 (reverse map).
 *
 * For an L0 widget node in the lattice graph, list every catalog
 * strategy that declares this widget as a data dependency. Closes
 * the audit loop: from "this widget" → "every strategy that needs
 * it" → click any to drill into the strategy.
 *
 * Renders only when the API call succeeds AND there's ≥1 strategy.
 * Quietly hides on 404 (some L0 widgets — like fin_db.* — aren't
 * declared as data_requirements anywhere because they're "checks"
 * not "data feeds").
 */
function WidgetStrategiesSection({ widgetId, onJumpToStrategies }: { widgetId: string; onJumpToStrategies?: (strategyId: string) => void }) {
  const q = useWidgetStrategies(widgetId)

  if (!q.data) {
    if (q.isLoading) {
      return (
        <div data-testid="widget-strategies-loading"
             className="text-[10px] italic text-[var(--color-dim)]">
          checking strategy dependencies…
        </div>
      )
    }
    return null
  }

  const { strategy_count, strategies, widget } = q.data

  return (
    <div
      data-testid={`widget-strategies-${widgetId}`}
      data-source={`/api/lattice/widgets/${widgetId}/strategies`}
      className="flex flex-col gap-1"
    >
      <div className="flex items-center gap-1 text-[10px] uppercase tracking-wider text-[var(--color-dim)]">
        <BookOpen size={9} />
        <span>Powered by {strategy_count} strateg{strategy_count === 1 ? 'y' : 'ies'}</span>
      </div>

      {strategy_count === 0 ? (
        <div className="text-[10px] italic text-[var(--color-dim)] leading-[1.4]">
          No catalog strategy currently declares this widget as a data
          requirement. {widget.status === 'planned'
            ? 'This widget is planned but not yet exposed in any strategy — likely a curation gap (an upcoming strategy will use it).'
            : 'This widget is referenced by lattice but no strategy has declared a hard dependency on it. Often true for compliance widgets (wash sale / PDT) which are checks, not data feeds.'}
        </div>
      ) : (
        <div className="flex flex-wrap gap-1">
          {strategies.map((s) => {
            const tooltipText =
              `${s.name_en ?? ''} — ${s.name_zh ?? ''}\n` +
              `horizon: ${s.horizon} · difficulty: ${'★'.repeat(s.difficulty ?? 0)}\n` +
              `${s.feasible_at_10k ? '✓ feasible at $10k' : '⚠ requires more capital'}` +
              (onJumpToStrategies ? '\n→ click to open in Strategies tab' : '')
            const baseClass = 'px-1.5 py-0.5 rounded border border-[var(--color-border)] text-[9.5px] font-mono transition'
            if (onJumpToStrategies) {
              return (
                <button
                  key={s.id}
                  data-testid={`reverse-strategy-${s.id}`}
                  data-strategy-id={s.id}
                  onClick={() => onJumpToStrategies(s.id)}
                  className={`${baseClass} cursor-pointer text-[var(--color-accent)] hover:bg-[var(--color-accent)]/10 hover:border-[var(--color-accent)]`}
                  title={tooltipText}
                >
                  {s.id}
                </button>
              )
            }
            return (
              <span
                key={s.id}
                data-testid={`reverse-strategy-${s.id}`}
                data-strategy-id={s.id}
                className={`${baseClass} cursor-help hover:border-[var(--color-accent)]/60`}
                title={tooltipText}
              >
                {s.id}
              </span>
            )
          })}
        </div>
      )}

      <div className="text-[9px] italic text-[var(--color-dim)] leading-[1.4]">
        {widget.status === 'available'
          ? 'This widget is ✓ available — actively emitting L1 obs.'
          : widget.status === 'planned'
            ? '⚠ This widget is "planned" — referenced by strategies but no L1 generator yet (real data gap).'
            : 'Status: deprecated.'}
      </div>
    </div>
  )
}


// V11: per-widget outbound links. Mapping is curated, not derived —
// each widget type points at the public products users would use to
// dig deeper. Choices favour: free / no-login / no-paywall, and
// cover both US (Yahoo/Finviz/TradingView) and CN (雪球) markets.
const WIDGET_EXTERNAL_LINKS: Record<string, Array<{ label: string; url: string; note?: string }>> = {
  chart: [
    { label: 'TradingView', url: 'https://www.tradingview.com/chart/', note: 'realtime charting' },
    { label: 'Yahoo Finance', url: 'https://finance.yahoo.com/quote/' },
    { label: '雪球', url: 'https://xueqiu.com/', note: 'A股 + 美股' },
  ],
  earnings: [
    { label: 'Yahoo Earnings', url: 'https://finance.yahoo.com/calendar/earnings', note: 'consensus + dates' },
    { label: 'Earnings Whispers', url: 'https://www.earningswhispers.com/', note: 'whisper numbers' },
  ],
  sectors: [
    { label: 'Finviz Map', url: 'https://finviz.com/map.ashx', note: 'visual sector heatmap' },
    { label: '雪球 行业', url: 'https://xueqiu.com/hq#exchange=cn&plate=1_1_1' },
    { label: 'OpenBB sectors', url: 'https://my.openbb.co/' },
  ],
  sentiment: [
    { label: 'CNN Fear & Greed', url: 'https://www.cnn.com/markets/fear-and-greed', note: 'composite index' },
    { label: 'AAII Sentiment', url: 'https://www.aaii.com/sentimentsurvey' },
  ],
  anomalies: [
    { label: 'Finviz Top Movers', url: 'https://finviz.com/screener.ashx?v=111&s=ta_topgainers' },
    { label: 'TradingView Screener', url: 'https://www.tradingview.com/screener/' },
  ],
  news: [
    { label: 'Yahoo Finance News', url: 'https://finance.yahoo.com/news/' },
    { label: 'Reuters Markets', url: 'https://www.reuters.com/markets/' },
    { label: '雪球 头条', url: 'https://xueqiu.com/today' },
  ],
  market_regime: [
    { label: 'TradingView Markets', url: 'https://www.tradingview.com/markets/' },
    { label: 'OpenBB Platform', url: 'https://my.openbb.co/' },
  ],
  portfolio: [
    { label: 'Yahoo Portfolio', url: 'https://finance.yahoo.com/portfolios/', note: 'manage there too' },
  ],
}

function ExternalLinksSection({ widget }: { widget: string }) {
  const links = WIDGET_EXTERNAL_LINKS[widget]
  if (!links || links.length === 0) return null
  return (
    <div data-testid="trace-l0-external-links" className="flex flex-col gap-1">
      <div className="text-[10px] uppercase tracking-wider text-[var(--color-dim)]">
        Look at it externally
      </div>
      <div className="flex flex-wrap gap-1.5">
        {links.map(({ label, url, note }) => (
          <a
            key={url}
            data-testid={`trace-l0-link-${widget}`}
            href={url}
            target="_blank"
            rel="noopener noreferrer"
            title={note ?? label}
            className="inline-flex items-center gap-1 px-2 py-0.5 rounded border border-[var(--color-border)] text-[10px] text-[var(--color-text)] hover:border-[var(--color-accent)] hover:text-[var(--color-accent)] transition"
          >
            <ExternalLink size={9} />
            <span>{label}</span>
          </a>
        ))}
      </div>
      <div className="text-[9px] text-[var(--color-dim)] italic leading-[1.4]">
        NeoMind tags + snapshots this widget for the lattice. For deep
        exploration (charts, screeners, fundamentals) the products above
        are authoritative.
      </div>
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

// ── V6 Deep Trace section ──────────────────────────────

function DeepTraceSection({
  node, projectId,
}: {
  node: LatticeGraphNode
  projectId: string
}) {
  const q = useLatticeTrace(projectId, node.id)

  return (
    <div className="mt-4" data-testid="trace-panel-deep-section">
      <div className="text-[10px] uppercase tracking-wider text-[var(--color-dim)] border-b border-[var(--color-border)] pb-0.5 mb-1">
        Deep trace · how was this derived?
      </div>
      {q.isLoading && (
        <div className="text-[10px] italic text-[var(--color-dim)]">fetching trace…</div>
      )}
      {q.isError && (
        <div className="text-[10px] text-[var(--color-dim)]" data-testid="trace-panel-deep-missing">
          No captured trace for this node. It was either served from
          cache on this refresh, or the TTL expired. Hit the Research
          refresh button (⟳) to rebuild and try again.
        </div>
      )}
      {q.data && <DeepTraceRender payload={q.data.trace} layer={node.layer} />}
    </div>
  )
}

function DeepTraceRender({
  payload, layer,
}: {
  payload: Record<string, unknown>
  layer: string
}) {
  const kind = payload.kind as string | undefined

  if (kind === "deterministic") {
    return (
      <div className="text-[10px] italic text-[var(--color-dim)]"
           data-testid="trace-panel-deep-deterministic">
        {String(payload.note ?? "Deterministic — see upstream edges for the math.")}
      </div>
    )
  }

  if (kind === "source") {
    return (
      <div className="text-[10px] italic text-[var(--color-dim)]">
        {String(payload.note ?? "External widget.")}
      </div>
    )
  }

  if (kind === "cache_hit") {
    return (
      <div className="text-[10px] italic text-[var(--color-dim)]">
        {String(payload.note ?? "Served from cache; no LLM call on this refresh.")}
      </div>
    )
  }

  if (kind === "llm_call" && layer === "L2") {
    // Narrative trace
    return (
      <div className="flex flex-col gap-1" data-testid="trace-panel-deep-llm">
        <KV k="model" v={String(payload.model)} />
        <KV k="temperature" v={String(payload.temperature)} />
        <KV k="duration_ms" v={String(payload.duration_ms)} testId="trace-panel-deep-duration" />
        <KV k="members" v={Array.isArray(payload.member_obs_ids)
          ? (payload.member_obs_ids as string[]).join(', ')
          : '—'} />
        <Collapsible
          title="System prompt"
          testId="trace-panel-deep-system-prompt"
          content={String(payload.system_prompt ?? '')}
        />
        <Collapsible
          title="User prompt"
          testId="trace-panel-deep-user-prompt"
          content={String(payload.user_prompt ?? '')}
        />
        <Collapsible
          title="Raw LLM response"
          testId="trace-panel-deep-raw-response"
          content={JSON.stringify(payload.raw_response ?? null, null, 2)}
        />
        {payload.validator != null && (
          <div className="text-[10px] pt-1">
            <b className="text-[var(--color-dim)]">validator:</b>{' '}
            <span style={{
              color: (payload.validator as Record<string, unknown>)?.passed
                ? 'var(--color-green)' : 'var(--color-red)',
            }}>
              {(payload.validator as Record<string, unknown>)?.passed ? 'PASS' : 'FAIL'}
            </span>
            {' — '}
            {String((payload.validator as Record<string, unknown>)?.reason ?? '')}
          </div>
        )}
        <KV k="final_source" v={String(payload.final_source ?? '')} />
        {payload.error ? <KV k="error" v={String(payload.error)} /> : null}
      </div>
    )
  }

  if (kind === "llm+mmr" && layer === "L3") {
    // L3 call trace: per_call + pool
    const perCall = payload.per_call as Record<string, unknown> | undefined
    const pool = payload.pool as Record<string, unknown> | undefined
    if (!pool) return <div className="text-[10px] italic">No pool trace captured.</div>
    const candidates = (pool.candidate_trace as Record<string, unknown>[]) ?? []
    return (
      <div className="flex flex-col gap-1" data-testid="trace-panel-deep-mmr">
        <KV k="model" v={String(pool.model)} />
        <KV k="temperature" v={String(pool.temperature)} />
        <KV k="duration_ms" v={String(pool.duration_ms)} />
        <KV k="validated_count" v={String(pool.validated_count ?? '—')} />
        <KV k="selected" v={Array.isArray(pool.selected_call_ids)
          ? (pool.selected_call_ids as string[]).join(', ') : '—'} />
        <Collapsible
          title="LLM system prompt"
          testId="trace-panel-deep-system-prompt"
          content={String(pool.system_prompt ?? '')}
        />
        <Collapsible
          title="LLM user prompt"
          testId="trace-panel-deep-user-prompt"
          content={String(pool.user_prompt ?? '')}
        />
        <Collapsible
          title={`LLM raw response (${candidates.length} candidates)`}
          testId="trace-panel-deep-raw-response"
          content={JSON.stringify(pool.raw_response ?? null, null, 2)}
        />
        <div className="pt-2">
          <div className="text-[10px] uppercase tracking-wider text-[var(--color-dim)]">
            Candidate pool ({candidates.length})
          </div>
          <div className="flex flex-col gap-1 pt-1"
               data-testid="trace-panel-deep-candidates">
            {candidates.map((c, i) => (
              <CandidateRow
                key={i}
                c={c}
                isThisCall={c.final_call_id === perCall?.call_id}
              />
            ))}
          </div>
        </div>
      </div>
    )
  }

  // Fallback: dump JSON
  return (
    <pre className="text-[10px] font-mono whitespace-pre-wrap break-all text-[var(--color-dim)]">
      {JSON.stringify(payload, null, 2).slice(0, 2000)}
    </pre>
  )
}

function CandidateRow({
  c, isThisCall,
}: {
  c: Record<string, unknown>
  isThisCall: boolean
}) {
  const status = String(c.status ?? 'unknown')
  const reason = String(c.drop_reason ?? '')
  const finalId = String(c.final_call_id ?? '')
  const raw = (c.raw ?? c.sanitised) as Record<string, unknown> | undefined
  const claim = raw?.claim ? String(raw.claim) : '(no claim)'
  const mmr = (c.mmr as Record<string, unknown>) ?? {}
  const mmrScore = mmr.selected_mmr_score as number | undefined

  const borderColor =
    status === 'accepted' ? 'var(--color-green)' :
    status === 'passed_validator' ? 'var(--color-accent)' :
    'var(--color-dim)'
  const accent = isThisCall ? 'var(--color-accent)' : 'transparent'
  return (
    <div
      data-testid={`trace-candidate-${c.candidate_idx}`}
      data-status={status}
      data-drop-reason={reason || undefined}
      className="border rounded p-1.5"
      style={{
        borderColor,
        background: isThisCall ? 'var(--color-accent)/10' : 'transparent',
        boxShadow: isThisCall ? `0 0 0 1px ${accent} inset` : undefined,
      }}
    >
      <div className="flex items-center gap-2 text-[10px]">
        <span className="font-mono">#{String(c.candidate_idx ?? '?')}</span>
        <span
          className="px-1 rounded border text-[9px] uppercase"
          style={{ borderColor, color: borderColor }}
        >
          {status}
        </span>
        {reason && (
          <span className="text-[var(--color-red)] text-[9px]">drop: {reason}</span>
        )}
        {finalId && (
          <span className="ml-auto text-[var(--color-accent)] text-[9px]">→ {finalId}</span>
        )}
        {mmrScore !== undefined && (
          <span className="text-[9px] text-[var(--color-dim)]">mmr {mmrScore.toFixed(3)}</span>
        )}
      </div>
      <div className="text-[10px] pt-1 font-mono break-words">
        {claim.length > 150 ? claim.slice(0, 149) + '…' : claim}
      </div>
      {c.drop_detail != null && Object.keys(c.drop_detail as Record<string, unknown>).length > 0 && (
        <details className="text-[9px] text-[var(--color-dim)] pt-0.5">
          <summary className="cursor-pointer">drop detail</summary>
          <pre className="whitespace-pre-wrap break-all">
            {JSON.stringify(c.drop_detail, null, 2)}
          </pre>
        </details>
      )}
    </div>
  )
}

function Collapsible({
  title, content, testId,
}: {
  title: string
  content: string
  testId?: string
}) {
  const [open, setOpen] = useState(false)
  return (
    <div className="pt-1">
      <button
        data-testid={testId ? `${testId}-toggle` : undefined}
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1 text-[10px] text-[var(--color-dim)] hover:text-[var(--color-text)]"
      >
        {open ? <ChevronDown size={9} /> : <ChevronRight size={9} />}
        {title} <span className="text-[var(--color-dim)]">({content.length} chars)</span>
      </button>
      {open && (
        <pre
          data-testid={testId}
          className="mt-1 p-2 bg-[var(--color-bg)]/50 border border-[var(--color-border)] rounded text-[9.5px] font-mono whitespace-pre-wrap break-all max-h-64 overflow-auto"
        >
          {content}
        </pre>
      )}
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
