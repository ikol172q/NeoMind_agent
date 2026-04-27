import { useEffect, useMemo, useRef, useState } from 'react'
import {
  useLatticeCalls, useWatchlist, usePaperPositions, useAnomalies,
  useLatticeSnapshots, useLatticeBudgets, setLatticeBudgets,
  useLatticeSelfcheck,
  type LatticeCall, type LatticeTheme, type LatticeObservation,
  type AnomalyFlag,
} from '@/lib/api'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Button } from '@/components/ui/Button'
import { FreshnessBar } from '@/components/FreshnessBar'
import { LatticeGraphView } from './LatticeGraphView'
import { ReasoningText } from './ReasoningText'
import { useLatticeLanguage, setLatticeLanguage } from '@/lib/api'
import {
  Sparkles, RefreshCw, ChevronRight, ChevronDown, Languages,
  Target, Shield, AlertCircle, Info, AlertTriangle,
  Calendar, History, SlidersHorizontal, ShieldCheck, ShieldAlert,
  Settings as SettingsIcon,
} from 'lucide-react'

export interface DigestFocus {
  symbol?: string
  /** Phase 6 followup: deep-link from Strategies tab into the lattice
   *  graph focused on a specific L0 widget node. Triggers trace mode
   *  + auto-selects `widget:{widgetId}` in the trace panel. */
  widgetId?: string
  /** Phase 6 followup: generic node-id deep-link. Used for L2 theme
   *  jumps (e.g. `theme_near_highs`) and any other layer. Takes
   *  precedence over `widgetId` if both are set. */
  nodeId?: string
  /** Monotonic counter — bump to re-trigger the highlight even when
   *  the symbol is unchanged (e.g. clicking the same cite twice). */
  nonce?: number
}

interface Props {
  projectId: string
  onJumpToChat?: (prompt: string, ctx?: { symbol?: string; project?: boolean }) => void
  /** When this changes, DigestView flips to flat mode, scrolls to
   *  nodes matching `symbol`, and applies a transient highlight. */
  focus?: DigestFocus | null
  /** Phase A (temporal replay): 'live' or YYYY-MM-DD. Forwarded to
   *  LatticeGraphView and downstream so the L2 inspector's
   *  "Top N strategies" reads from the same time slice. */
  asOf?: string
  /** When provided, the header gets a `config` button that calls this.
   *  Used by Research tab to open the watchlist + portfolio drawer. */
  onOpenConfig?: () => void
  /** Phase 5 V4: each L3 call's strategy_match chip is clickable —
   *  route to Strategies tab focused on the matched strategy id. */
  onJumpToStrategies?: (strategyId: string) => void
}

type Mode = 'summary' | 'drilldown' | 'flat' | 'trace'

const HIGHLIGHT_MS = 2500

const SEVERITY_COLOR: Record<string, string> = {
  alert: 'var(--color-red)',
  warn: 'var(--color-amber, #e5a200)',
  info: 'var(--color-accent)',
}

const CONF_COLOR: Record<string, string> = {
  high: 'var(--color-green)',
  medium: 'var(--color-accent)',
  low: 'var(--color-dim)',
}

export function DigestView({ projectId, onJumpToChat, focus, onOpenConfig, onJumpToStrategies, asOf }: Props) {
  // V8: when historicalDate is non-null, render that archived day
  // instead of live. Null = live mode.
  // Phase A: the global asOf picker takes priority over the local
  // 'past' button. When asOf is set to a date, every useLatticeCalls
  // call site flips to historical-snapshot mode for that date so
  // Research stays time-coherent with Strategies.
  const [historicalDate, setHistoricalDate] = useState<string | null>(null)
  const effectiveDate = (asOf && asOf !== 'live') ? asOf : historicalDate
  const q = useLatticeCalls(projectId, effectiveDate)
  const anomalies = useAnomalies(projectId)
  const wl = useWatchlist(projectId)
  const pos = usePaperPositions(projectId)
  const [mode, setMode] = useState<Mode>('summary')
  const [highlightId, setHighlightId] = useState<string | null>(null)
  const scrollBodyRef = useRef<HTMLDivElement | null>(null)
  const targetRefs = useRef<Record<string, HTMLElement | null>>({})

  const isFreshInstall =
    (wl.data?.entries?.length ?? 0) === 0 &&
    (pos.data?.positions?.length ?? 0) === 0

  const payload = q.data
  const themes = payload?.themes ?? []
  const subThemes = payload?.sub_themes ?? []
  const calls = payload?.calls ?? []
  const observations = payload?.observations ?? []

  // External focus: when a chat citation routes back to us, flip to
  // flat mode (so every layer is rendered + findable) and scroll to
  // the first matching node. One-shot highlight that auto-clears.
  useEffect(() => {
    if (!focus || !focus.symbol) return
    const symbol = focus.symbol.toUpperCase()
    setMode('flat')
    // Wait one tick for flat mode to render all sections/rows
    const t = window.setTimeout(() => {
      const target = findFocusTarget(symbol, calls, themes, observations)
      if (!target) return
      setHighlightId(target)
      const el = targetRefs.current[target]
      if (el && scrollBodyRef.current) {
        el.scrollIntoView({ behavior: 'smooth', block: 'center' })
      }
      window.setTimeout(() => setHighlightId(null), HIGHLIGHT_MS)
    }, 60)
    return () => window.clearTimeout(t)
  }, [focus?.symbol, focus?.nonce, calls, themes, observations])

  // Phase 6 followup: deep-link from Strategies → Research focused on
  // an L0 widget OR L2 theme. Switch to trace mode and let
  // LatticeGraphView pick up initialFocusNodeId.
  useEffect(() => {
    if (focus?.widgetId || focus?.nodeId) setMode('trace')
  }, [focus?.widgetId, focus?.nodeId, focus?.nonce])

  const ctx: DigestCtx = {
    highlightId,
    registerRef: (id, el) => { targetRefs.current[id] = el },
    onJumpToChat,
    onJumpToStrategies,
  }

  return (
    <div
      data-testid="digest-view"
      className="h-full flex flex-col bg-[var(--color-panel)] border border-[var(--color-border)] rounded-md overflow-hidden"
    >
      <Header
        mode={mode}
        setMode={setMode}
        fetchedAt={payload?.fetched_at}
        loading={q.isFetching}
        onRefresh={() => q.refetch()}
        projectId={projectId}
        historicalDate={historicalDate}
        setHistoricalDate={setHistoricalDate}
        onOpenConfig={onOpenConfig}
        globalAsOf={asOf}
      />
      {/* V9: thin animated progress bar during any refetch. Old data
          stays visible below (via placeholderData: keepPreviousData)
          so the user can keep reading, but mutating controls are
          locked until the new data lands. */}
      {q.isFetching && !q.isLoading && (
        <div
          data-testid="digest-refresh-bar"
          className="h-[2px] bg-[var(--color-accent)] animate-pulse shrink-0"
          aria-label="regenerating lattice — data may change shortly"
        />
      )}
      {/* B6-Step1: provenance breadcrumb. Reads run_meta from the
          /api/lattice/calls payload (B5-L3) — surfaces dep_hash,
          compute_run_id, model, cache_hit and the L3 ← L2 ← L1
          lineage chain so the user can trace any rendered call back
          to the exact bytes that produced it. */}
      <FreshnessBar
        meta={payload?.run_meta}
        pipelineLabel="Research"
        showSnapshotHint
        refreshing={q.isFetching}
        onOpenRun={(id) =>
          window.open(
            `/api/compute/runs/${encodeURIComponent(id)}?project_id=${encodeURIComponent(projectId)}`,
            '_blank',
            'noopener',
          )
        }
      />


      {(anomalies.data?.flags?.length ?? 0) > 0 && !isFreshInstall && (
        <AnomalyStrip
          flags={anomalies.data!.flags}
          onJumpToChat={onJumpToChat}
          onFocusSymbol={(sym) => {
            setMode('flat')
            // Mirror the focus-prop pathway so anomaly click ==
            // external-cite click for the same symbol.
            window.setTimeout(() => {
              const t = findFocusTarget(sym, calls, themes, observations)
              if (t) {
                setHighlightId(t)
                targetRefs.current[t]?.scrollIntoView({ behavior: 'smooth', block: 'center' })
                window.setTimeout(() => setHighlightId(null), HIGHLIGHT_MS)
              }
            }, 60)
          }}
        />
      )}

      <div className="flex-1 overflow-y-auto" data-testid="digest-body" ref={scrollBodyRef}>
        {q.isLoading && (
          <div className="p-3 text-[11px] italic text-[var(--color-dim)]">
            reading the lattice…
          </div>
        )}
        {q.isError && (
          <div className="p-3 text-[11px] text-[var(--color-red)]">
            {(q.error as Error).message.slice(0, 200)}
          </div>
        )}
        {!q.isLoading && !q.isError && isFreshInstall && (
          <Quickstart />
        )}
        {!q.isLoading && !q.isError && !isFreshInstall && mode === 'summary' && (
          <SummaryMode
            calls={calls}
            themes={themes}
            observations={observations}
            ctx={ctx}
            onJumpToDrilldown={() => setMode('drilldown')}
          />
        )}
        {!q.isLoading && !q.isError && !isFreshInstall && mode === 'drilldown' && (
          <DrilldownMode
            calls={calls}
            themes={themes}
            subThemes={subThemes}
            observations={observations}
            startCollapsed
            ctx={ctx}
          />
        )}
        {!q.isLoading && !q.isError && !isFreshInstall && mode === 'flat' && (
          <DrilldownMode
            calls={calls}
            themes={themes}
            subThemes={subThemes}
            observations={observations}
            startCollapsed={false}
            ctx={ctx}
          />
        )}
        {/* Trace mode uses useLatticeGraph (its own query) so it is
            not gated on /calls loading; let LatticeGraphView render
            its own loading/empty/error state. */}
        {mode === 'trace' && !isFreshInstall && (
          <LatticeGraphView
            projectId={projectId}
            initialFocusNodeId={
              focus?.nodeId ?? (focus?.widgetId ? `widget:${focus.widgetId}` : undefined)
            }
            onJumpToStrategies={onJumpToStrategies}
            asOf={asOf}
          />
        )}
      </div>
    </div>
  )
}


// Context threaded to each row so they can participate in the
// ref-map + highlight state without prop-drilling 5 deep.
interface DigestCtx {
  highlightId: string | null
  registerRef: (id: string, el: HTMLElement | null) => void
  onJumpToChat?: (prompt: string, ctx?: { symbol?: string; project?: boolean }) => void
  /** Phase 5 V4: route from a call's strategy_match chip to Strategies tab. */
  onJumpToStrategies?: (strategyId: string) => void
}


function findFocusTarget(
  symbol: string,
  calls: LatticeCall[],
  themes: LatticeTheme[],
  observations: LatticeObservation[],
): string | null {
  const symU = symbol.toUpperCase()
  // Prefer L1 (most specific) → L2 → L3. The user clicked a citation,
  // they want the evidence, not the high-level claim.
  for (const o of observations) {
    if (
      o.tags.includes(`symbol:${symU}`) ||
      o.tags.includes(`position:${symU}`) ||
      o.text.toUpperCase().includes(symU)
    ) {
      return `obs-${o.id}`
    }
  }
  for (const t of themes) {
    if (t.narrative.toUpperCase().includes(symU)) {
      return `drill-theme-${t.id}`
    }
  }
  for (const c of calls) {
    if (c.claim.toUpperCase().includes(symU)) {
      return `drill-call-${c.id}`
    }
  }
  return null
}


// ── Anomaly strip ──────────────────────────────────────

function AnomalyStrip({
  flags, onJumpToChat, onFocusSymbol,
}: {
  flags: AnomalyFlag[]
  onJumpToChat?: (prompt: string, ctx?: { symbol?: string; project?: boolean }) => void
  onFocusSymbol: (sym: string) => void
}) {
  return (
    <div
      data-testid="digest-anomaly-strip"
      className="flex flex-wrap gap-1 px-3 py-1.5 border-b border-[var(--color-border)] bg-[var(--color-bg)]/40 shrink-0"
    >
      {flags.slice(0, 6).map((f, i) => {
        const color = SEVERITY_COLOR[f.severity] ?? SEVERITY_COLOR.info
        return (
          <div
            key={i}
            className="inline-flex items-stretch rounded border whitespace-nowrap overflow-hidden"
            style={{ borderColor: color }}
          >
            <button
              data-testid={`digest-anomaly-${f.kind}-${f.symbol}`}
              onClick={() => onFocusSymbol(f.symbol)}
              className="flex items-center gap-1 px-2 py-0.5 text-[10px] transition hover:brightness-125"
              style={{ color }}
              title={`[${f.severity.toUpperCase()}] ${f.kind} · click to scroll to evidence`}
            >
              <AlertTriangle size={9} />
              {f.message}
            </button>
            {onJumpToChat && (
              <button
                data-testid={`digest-anomaly-ask-${f.kind}-${f.symbol}`}
                onClick={() => onJumpToChat(
                  `Dig into this flag: "${f.message}". What should I actually do about it?`,
                  { symbol: f.symbol },
                )}
                className="px-1.5 text-[10px] border-l"
                style={{ color, borderColor: color }}
                title="ask fin about this flag"
              >
                ask
              </button>
            )}
          </div>
        )
      })}
    </div>
  )
}


// ── Header / mode toggle ──────────────────────────────

function Header({
  mode, setMode, fetchedAt, loading, onRefresh,
  projectId, historicalDate, setHistoricalDate, onOpenConfig, globalAsOf,
}: {
  mode: Mode
  setMode: (m: Mode) => void
  fetchedAt?: string
  loading: boolean
  onRefresh: () => void
  projectId: string
  historicalDate: string | null
  setHistoricalDate: (d: string | null) => void
  onOpenConfig?: () => void
  /** B6 followup: top-nav AsOfPicker is the single source of truth.
   *  When ``globalAsOf`` is set to a YYYY-MM-DD, the local
   *  HistoryPicker stays hidden (was a duplicate that confused
   *  users — see #65). */
  globalAsOf?: string
}) {
  const isLocalHistorical = historicalDate !== null
  const isGlobalHistorical = !!(globalAsOf && globalAsOf !== 'live')
  const isHistorical = isLocalHistorical || isGlobalHistorical
  const historicalLabel = globalAsOf && globalAsOf !== 'live' ? globalAsOf : historicalDate
  return (
    <div className="flex items-center gap-2 px-3 py-1.5 border-b border-[var(--color-border)] shrink-0">
      <Sparkles size={12} className="text-[var(--color-accent)]" />
      <span className="text-[10px] uppercase tracking-wider text-[var(--color-dim)] flex-1">
        {isHistorical ? (
          <>
            <span className="text-[var(--color-amber,#e5a200)]">
              Historical · {historicalLabel}
            </span>
            {isLocalHistorical && !isGlobalHistorical && (
              <button
                onClick={() => setHistoricalDate(null)}
                className="ml-2 text-[var(--color-accent)] hover:underline normal-case tracking-normal"
                data-testid="digest-historical-clear"
              >
                ← back to live
              </button>
            )}
            {isGlobalHistorical && (
              <span className="ml-2 normal-case tracking-normal text-[var(--color-dim)]">
                (use the global picker top-right to change date)
              </span>
            )}
          </>
        ) : (
          <>
            Today's lattice · L1 (observations) → L2 (themes) → L3 (calls)
            {fetchedAt && (
              <span className="ml-2 text-[var(--color-dim)]/80">
                updated {new Date(fetchedAt).toLocaleTimeString()}
              </span>
            )}
          </>
        )}
      </span>
      {/* B6 followup: hide the local HistoryPicker when the global
          top-nav AsOfPicker is in non-Live mode — having both was the
          'two date pickers' confusion (#65). When global is Live we
          still expose the local picker for backwards-compat with
          users who want a quick per-tab time-travel. */}
      {!isGlobalHistorical && (
        <HistoryPicker
          projectId={projectId}
          value={historicalDate}
          onChange={setHistoricalDate}
          disabled={loading}
        />
      )}
      <IntegrityBadge projectId={projectId} disabled={loading || isHistorical} />
      <BudgetsPicker disabled={isHistorical || loading} />
      <div
        className="flex rounded border border-[var(--color-border)] overflow-hidden text-[10px]"
        data-testid="digest-mode-toggle"
      >
        {(['summary', 'drilldown', 'flat', 'trace'] as Mode[]).map(m => (
          <button
            key={m}
            data-testid={`digest-mode-${m}`}
            onClick={() => setMode(m)}
            className={
              'px-2 py-0.5 transition ' +
              (mode === m
                ? 'bg-[var(--color-accent)] text-[var(--color-bg)]'
                : 'text-[var(--color-dim)] hover:text-[var(--color-text)]')
            }
            title={
              m === 'summary' ? 'Toulmin chips only'
                : m === 'drilldown' ? 'L3 → L2 → L1 accordion'
                  : m === 'flat' ? 'all layers expanded (debug)'
                    : 'full graph with provenance (V3)'
            }
          >
            {m[0].toUpperCase()}
          </button>
        ))}
      </div>
      <LanguageToggle fetchingLattice={loading} />
      <Button
        size="sm"
        variant="ghost"
        onClick={onRefresh}
        disabled={loading}
        data-testid="digest-refresh"
        title="rebuild the lattice (bypasses cache)"
      >
        <RefreshCw size={11} className={loading ? 'animate-spin' : ''} />
      </Button>
      {onOpenConfig && (
        <button
          data-testid="research-config-open"
          onClick={onOpenConfig}
          title="Edit watchlist + portfolio (lattice L0 inputs)"
          className="flex items-center gap-1 text-[10px] text-[var(--color-dim)] hover:text-[var(--color-text)] border border-[var(--color-border)] rounded px-2 py-0.5 transition"
        >
          <SettingsIcon size={11} />
          <span>config</span>
        </button>
      )}
    </div>
  )
}


function HistoryPicker({
  projectId, value, onChange, disabled,
}: {
  projectId: string
  value: string | null
  onChange: (d: string | null) => void
  disabled?: boolean
}) {
  const [open, setOpen] = useState(false)
  const q = useLatticeSnapshots(projectId)
  const snapshots = q.data?.snapshots ?? []

  return (
    <div className="relative">
      <button
        data-testid="digest-history-toggle"
        disabled={disabled}
        onClick={() => setOpen(!open)}
        className={
          'inline-flex items-center gap-1 px-2 py-0.5 rounded border text-[10px] transition ' +
          (value
            ? 'border-[var(--color-amber,#e5a200)] text-[var(--color-amber,#e5a200)]'
            : 'border-[var(--color-border)] text-[var(--color-dim)] hover:text-[var(--color-text)] hover:border-[var(--color-accent)]')
        }
        title={value
          ? `Viewing archived lattice for ${value}`
          : 'View an archived past lattice (auto-saved daily)'}
      >
        {value ? <History size={10} /> : <Calendar size={10} />}
        <span className="font-mono">{value ?? 'past'}</span>
      </button>
      {open && (
        <div
          data-testid="digest-history-menu"
          className="absolute top-full right-0 mt-1 min-w-[180px] max-h-[260px] overflow-y-auto rounded border border-[var(--color-border)] bg-[var(--color-panel)] shadow-lg z-20 text-[10px]"
        >
          <button
            onClick={() => { onChange(null); setOpen(false) }}
            className="w-full text-left px-2 py-1 hover:bg-[var(--color-accent)]/15 text-[var(--color-text)]"
            data-testid="digest-history-live"
          >
            <b>Live</b> — today, auto-refreshing
          </button>
          <div className="border-t border-[var(--color-border)]">
            {snapshots.length === 0 && (
              <div className="px-2 py-1.5 text-[var(--color-dim)] italic">
                No snapshots yet. They accumulate when you refresh the
                live lattice — one file per calendar day (UTC).
              </div>
            )}
            {snapshots.map(s => {
              const active = s.date === value
              return (
                <button
                  key={s.date}
                  data-testid={`digest-history-date-${s.date}`}
                  onClick={() => { onChange(s.date); setOpen(false) }}
                  className={
                    'w-full text-left px-2 py-1 hover:bg-[var(--color-accent)]/15 font-mono ' +
                    (active ? 'text-[var(--color-accent)]' : 'text-[var(--color-text)]')
                  }
                >
                  {s.date}
                  {s.output_language && (
                    <span className="ml-2 text-[9px] text-[var(--color-dim)]">
                      {s.output_language === 'zh-CN-mixed' ? '中' : 'EN'}
                    </span>
                  )}
                </button>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}


// ── V10·A2 live integrity badge ────────────────────────
//
// A small badge that, on click, runs /api/lattice/selfcheck and
// shows a structured pass/fail report for each documented invariant.
// Lazy — doesn't run on page load; fires only when user clicks.

function IntegrityBadge({
  projectId, disabled,
}: {
  projectId: string
  disabled?: boolean
}) {
  const [open, setOpen] = useState(false)
  // Only fetch when the panel opens (or stays open). Saves a recompute
  // on every page load.
  const q = useLatticeSelfcheck(projectId, open)
  const checks = q.data?.checks ?? []
  const allPass = q.data?.all_pass
  // Show unknown (grey) if never fetched, pass (green) if clean,
  // warn (amber) if any check failed.
  const status: 'unknown' | 'pass' | 'fail' =
    q.data == null ? 'unknown' : allPass ? 'pass' : 'fail'
  const color = status === 'pass'
    ? 'var(--color-green)'
    : status === 'fail'
      ? 'var(--color-amber,#e5a200)'
      : 'var(--color-dim)'
  const Icon = status === 'fail' ? ShieldAlert : ShieldCheck

  return (
    <div className="relative">
      <button
        data-testid="digest-integrity-toggle"
        data-integrity-status={status}
        disabled={disabled}
        onClick={() => setOpen(!open)}
        className="inline-flex items-center gap-1 px-2 py-0.5 rounded border text-[10px] transition disabled:opacity-50"
        style={{ borderColor: color, color }}
        title={status === 'unknown'
          ? 'Run live integrity checks on the current lattice'
          : allPass
            ? `Integrity ✓ — ${q.data?.summary}. Click for details.`
            : `Integrity ⚠ — ${q.data?.summary}. Click to see failures.`}
      >
        <Icon size={10} />
        <span className="font-mono">
          {status === 'unknown' ? 'check' : q.data?.summary}
        </span>
      </button>
      {open && (
        <div
          data-testid="digest-integrity-panel"
          className="absolute top-full right-0 mt-1 w-[380px] max-h-[400px] overflow-y-auto rounded border border-[var(--color-border)] bg-[var(--color-panel)] shadow-lg p-3 text-[10px] z-20 flex flex-col gap-2"
        >
          <div className="flex items-center justify-between">
            <span className="uppercase tracking-wider text-[var(--color-dim)]">
              Live integrity report
            </span>
            <button
              onClick={() => { q.refetch(); }}
              disabled={q.isFetching}
              className="text-[var(--color-dim)] hover:text-[var(--color-text)] text-[9px]"
              title="re-run checks"
            >
              {q.isFetching ? 'running…' : 'refresh'}
            </button>
          </div>
          {q.isLoading && (
            <div className="italic text-[var(--color-dim)]">running checks…</div>
          )}
          {q.isError && (
            <div className="text-[var(--color-red)]">
              {(q.error as Error).message.slice(0, 200)}
            </div>
          )}
          {q.data && (
            <>
              <div className="text-[var(--color-text)]">
                <b>{q.data.summary}</b>
                {allPass
                  ? ' — every invariant holds on the current lattice.'
                  : ' — see failing checks below.'}
              </div>
              <div className="flex flex-col gap-1.5">
                {checks.map(c => (
                  <IntegrityCheckRow key={c.name} check={c} />
                ))}
              </div>
              <div className="text-[9px] text-[var(--color-dim)] border-t border-[var(--color-border)] pt-1.5 leading-[1.4]">
                These are <b>live</b> — recomputed every time you click
                refresh. They're also run in CI on every commit.
                Click a failing row to see the offenders.
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}

function IntegrityCheckRow({ check }: { check: {
  name: string; label: string; pass: boolean; detail: string; offenders?: unknown[]
} }) {
  const [expand, setExpand] = useState(false)
  const hasOffenders = !!check.offenders && check.offenders.length > 0
  return (
    <div
      data-testid={`integrity-check-${check.name}`}
      data-integrity-pass={check.pass ? 'true' : 'false'}
      className={
        'rounded border px-2 py-1.5 ' +
        (check.pass
          ? 'border-[var(--color-border)] bg-[var(--color-bg)]/40'
          : 'border-[var(--color-amber,#e5a200)]/60 bg-[var(--color-amber,#e5a200)]/10')
      }
    >
      <button
        onClick={() => hasOffenders && setExpand(!expand)}
        className="w-full flex items-start gap-2 text-left"
      >
        <span
          className="text-[10px] shrink-0 mt-0.5"
          style={{ color: check.pass ? 'var(--color-green)' : 'var(--color-amber,#e5a200)' }}
        >
          {check.pass ? '✓' : '⚠'}
        </span>
        <div className="flex-1">
          <div className="text-[var(--color-text)]">{check.label}</div>
          <div className="text-[9px] text-[var(--color-dim)] font-mono">
            {check.detail}
          </div>
        </div>
        {hasOffenders && (
          <span className="text-[9px] text-[var(--color-dim)]">
            {expand ? '▾' : '▸'}
          </span>
        )}
      </button>
      {expand && check.offenders && (
        <pre
          data-testid={`integrity-offenders-${check.name}`}
          className="mt-1 text-[9px] text-[var(--color-amber,#e5a200)] font-mono overflow-x-auto"
        >
          {JSON.stringify(check.offenders, null, 2)}
        </pre>
      )}
    </div>
  )
}


// ── V9 layer-budget override knob ─────────────────────
//
// A small cog button in the header that opens a drawer with 5
// controls (L1.5 max, L2 max, L3 max, L3 candidate pool, MMR λ).
// Applying fires POST /api/lattice/budgets → runtime override →
// every RQ key that includes budget_hash re-keys → pipeline re-runs.

interface BudgetDraft {
  sub_themes_max: number | null
  themes_max: number | null
  calls_max: number | null
  calls_candidates: number | null
  calls_lambda: number | null
}

// Helper: a field value is an "override" iff it differs from the
// YAML default. Used to color inputs + show the `budgets*` badge.
function isOverridden(value: number | null, yamlDefault: number | null): boolean {
  if (value === null && yamlDefault === null) return false
  if (value === null || yamlDefault === null) return true
  return Math.abs(value - yamlDefault) > 1e-9
}

function BudgetsPicker({ disabled }: { disabled: boolean }) {
  const [open, setOpen] = useState(false)
  const qc = useQueryClient()
  const q = useLatticeBudgets()
  const state = q.data
  const active = !!state?.override

  // Build initial draft from the effective values. `null` means "use
  // default" — important for min_members and max_items which may be
  // null by design.
  const draft0: BudgetDraft = {
    sub_themes_max: state?.effective.sub_themes.max_items ?? null,
    themes_max:     state?.effective.themes.max_items ?? null,
    calls_max:      state?.effective.calls.max_items ?? null,
    calls_candidates: state?.effective.calls.max_candidates ?? null,
    calls_lambda:   state?.effective.calls.mmr_lambda ?? null,
  }
  const [draft, setDraft] = useState<BudgetDraft>(draft0)
  // Reset the draft each time the panel opens so it always reflects
  // the current effective state.
  useEffect(() => {
    if (open) setDraft(draft0)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, state?.effective_hash])

  const mutation = useMutation({
    mutationFn: async (clear: boolean) => {
      const body = clear ? {} : {
        sub_themes: { max_items: draft.sub_themes_max },
        themes:     { max_items: draft.themes_max },
        calls: {
          max_items: draft.calls_max,
          max_candidates: draft.calls_candidates,
          mmr_lambda: draft.calls_lambda,
        },
      }
      return setLatticeBudgets(body)
    },
    onSuccess: (resp) => {
      // Publish the new effective state so components that depend on
      // budget_hash re-key synchronously.
      qc.setQueryData(['lattice_budgets'], {
        ...state,
        effective: resp.effective,
        override: resp.override,
        effective_hash: resp.effective_hash,
      })
      setOpen(false)
    },
  })

  const label = active ? 'budgets*' : 'budgets'

  return (
    <div className="relative">
      <button
        data-testid="digest-budgets-toggle"
        data-budgets-override={active ? 'true' : undefined}
        disabled={disabled || !state}
        onClick={() => setOpen(!open)}
        className={
          'inline-flex items-center gap-1 px-2 py-0.5 rounded border text-[10px] transition disabled:opacity-50 ' +
          (active
            ? 'border-[var(--color-accent)] text-[var(--color-accent)]'
            : 'border-[var(--color-border)] text-[var(--color-dim)] hover:text-[var(--color-text)] hover:border-[var(--color-accent)]')
        }
        title={disabled
          ? 'Budget controls disabled while viewing a historical snapshot'
          : active
            ? 'Runtime override active — click to adjust or reset to YAML'
            : 'Tune per-layer node counts live (runtime override)'}
      >
        <SlidersHorizontal size={10} />
        <span className="font-mono">{label}</span>
      </button>
      {open && state && (
        <div
          data-testid="digest-budgets-panel"
          className="absolute top-full right-0 mt-1 w-[260px] rounded border border-[var(--color-border)] bg-[var(--color-panel)] shadow-lg z-20 p-3 flex flex-col gap-2 text-[10px]"
        >
          <div className="flex items-center justify-between text-[var(--color-dim)] uppercase tracking-wider">
            <span>Layer budgets · runtime</span>
            {active && (
              <span className="text-[var(--color-accent)] normal-case tracking-normal">
                override active
              </span>
            )}
          </div>
          <BudgetRow
            label="L1.5 sub-themes · max"
            value={draft.sub_themes_max}
            effective={state.effective.sub_themes.max_items}
            yamlDefault={state.yaml_default.sub_themes.max_items}
            min={0} max={20}
            onChange={v => setDraft(d => ({ ...d, sub_themes_max: v }))}
            testId="budget-input-sub-themes-max"
          />
          <BudgetRow
            label="L2 themes · max"
            value={draft.themes_max}
            effective={state.effective.themes.max_items}
            yamlDefault={state.yaml_default.themes.max_items}
            min={0} max={20}
            onChange={v => setDraft(d => ({ ...d, themes_max: v }))}
            testId="budget-input-themes-max"
          />
          <BudgetRow
            label="L3 calls · max"
            value={draft.calls_max}
            effective={state.effective.calls.max_items}
            yamlDefault={state.yaml_default.calls.max_items}
            min={0} max={10}
            onChange={v => setDraft(d => ({ ...d, calls_max: v }))}
            testId="budget-input-calls-max"
          />
          <BudgetRow
            label="L3 · candidate pool"
            value={draft.calls_candidates}
            effective={state.effective.calls.max_candidates}
            yamlDefault={state.yaml_default.calls.max_candidates}
            min={1} max={5}
            onChange={v => setDraft(d => ({ ...d, calls_candidates: v }))}
            testId="budget-input-calls-candidates"
          />
          <BudgetRow
            label="L3 · MMR λ (0=diverse, 1=relevant)"
            value={draft.calls_lambda}
            effective={state.effective.calls.mmr_lambda}
            yamlDefault={state.yaml_default.calls.mmr_lambda}
            min={0} max={1} step={0.05}
            onChange={v => setDraft(d => ({ ...d, calls_lambda: v }))}
            testId="budget-input-calls-lambda"
          />
          <div className="text-[9px] text-[var(--color-dim)] pt-1 leading-[1.4]">
            Changes to <b>L3 pool</b> re-run the LLM; others are instant.
            Each (language × budget) combo is cached separately —
            flipping back to a seen combo is a memory hit.
          </div>
          <div className="flex items-center justify-between gap-2 pt-1">
            <button
              data-testid="digest-budgets-reset"
              onClick={() => mutation.mutate(true)}
              disabled={mutation.isPending || !active}
              className="px-2 py-0.5 rounded border border-[var(--color-border)] text-[var(--color-dim)] hover:text-[var(--color-text)] disabled:opacity-40"
              title="Clear runtime override (fall back to YAML)"
            >
              reset
            </button>
            <div className="flex items-center gap-1">
              <button
                onClick={() => setOpen(false)}
                disabled={mutation.isPending}
                className="px-2 py-0.5 rounded border border-[var(--color-border)] text-[var(--color-dim)] hover:text-[var(--color-text)]"
              >
                cancel
              </button>
              <button
                data-testid="digest-budgets-apply"
                onClick={() => mutation.mutate(false)}
                disabled={mutation.isPending}
                className="px-2 py-0.5 rounded bg-[var(--color-accent)] text-[var(--color-bg)] hover:brightness-110 disabled:opacity-60"
              >
                {mutation.isPending ? 'applying…' : 'apply'}
              </button>
            </div>
          </div>
          {mutation.isError && (
            <div className="text-[9px] text-[var(--color-red)]">
              {(mutation.error as Error).message.slice(0, 140)}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function BudgetRow({
  label, value, effective, yamlDefault, min, max, step, onChange, testId,
}: {
  label: string
  /** Draft value — may be `null` to mean "use default". */
  value: number | null
  /** Currently-effective value (from server) — shown in the input as
   *  ghost text when `value` is null, so the user can see what "auto"
   *  actually resolves to without having to guess. */
  effective: number | null
  /** YAML baseline — used to decide whether the effective value is
   *  a runtime override (yellow/accent) or the default (dim). */
  yamlDefault: number | null
  min: number
  max: number
  step?: number
  onChange: (v: number | null) => void
  testId: string
}) {
  const overridden = isOverridden(value ?? effective, yamlDefault)
  // Display value: what's in the draft, else what's currently effective,
  // else blank. "Blank + placeholder" is avoided — user asked to see the
  // actual number when they focus.
  const displayValue = value !== null
    ? value
    : effective !== null
      ? effective
      : ''
  return (
    <label className="flex items-center gap-2 text-[var(--color-text)]">
      <span className="flex-1">{label}</span>
      <input
        data-testid={testId}
        data-overridden={overridden ? 'true' : undefined}
        type="number"
        value={displayValue}
        placeholder="auto"
        min={min}
        max={max}
        step={step ?? 1}
        onChange={e => {
          const raw = e.target.value
          if (raw === '') { onChange(null); return }
          const n = Number(raw)
          if (Number.isFinite(n)) onChange(n)
        }}
        className={
          'w-16 px-1 py-0.5 bg-[var(--color-bg)] border rounded font-mono text-[10px] text-right ' +
          (overridden
            ? 'border-[var(--color-accent)] text-[var(--color-accent)]'
            : 'border-[var(--color-border)] text-[var(--color-dim)]')
        }
      />
    </label>
  )
}


function LanguageToggle({ fetchingLattice }: { fetchingLattice: boolean }) {
  const qc = useQueryClient()
  const q = useLatticeLanguage()
  const active = q.data?.active

  // V8: language is now part of every dependent query's key
  // (useLatticeCalls / useLatticeGraph / useLatticeTrace). Flipping
  // active language switches the key — RQ serves from memory if the
  // other language has already been fetched, or fetches fresh
  // otherwise. No explicit refetch needed here.
  const mutation = useMutation({
    mutationFn: async (next: 'en' | 'zh-CN-mixed') => {
      const resp = await setLatticeLanguage(next)
      qc.setQueryData(['lattice_language'], {
        active: resp.active,
        override: resp.override,
        yaml_default: resp.yaml_default,
        available: ['en', 'zh-CN-mixed'],
      })
      return resp
    },
  })

  const pending = mutation.isPending
  const label = pending
    ? '…'
    : active === 'zh-CN-mixed' ? '中' : active === 'en' ? 'EN' : '—'
  const title = pending
    ? 'Regenerating narratives in the selected language (this calls the LLM — takes a few seconds)'
    : active === 'zh-CN-mixed'
      ? 'Output language: 中英混合 — click to switch to English'
      : active === 'en'
        ? 'Output language: English — click to switch to 中英混合'
        : 'Output language (loading)'
  return (
    <button
      data-testid="digest-language-toggle"
      data-language-active={active}
      data-language-pending={pending ? 'true' : undefined}
      onClick={() => {
        if (!active || pending || fetchingLattice) return
        const next = active === 'en' ? 'zh-CN-mixed' : 'en'
        mutation.mutate(next)
      }}
      disabled={!active || pending || fetchingLattice}
      className="inline-flex items-center gap-1 px-2 py-0.5 rounded border border-[var(--color-border)] text-[10px] text-[var(--color-dim)] hover:text-[var(--color-text)] hover:border-[var(--color-accent)] transition disabled:opacity-60"
      title={title}
    >
      <Languages size={10} className={pending ? 'animate-pulse' : ''} />
      <span className="font-mono">{label}</span>
    </button>
  )
}


// ── Quickstart (empty state) ───────────────────────────

function Quickstart() {
  return (
    <div data-testid="digest-quickstart" className="flex flex-col gap-2 p-3 text-[12px]">
      <div className="text-[var(--color-accent)] font-semibold">
        Welcome — the lattice needs real data to distil.
      </div>
      <ol className="list-decimal ml-5 space-y-1 text-[var(--color-text)]">
        <li>Add symbols to the <b>Watchlist</b> below (try <code>AAPL</code>, <code>NVDA</code>).</li>
        <li>Open the <b>Paper</b> tab, place a small order.</li>
        <li>Come back — this panel will show 3-layer reasoning:<br/>
          <span className="text-[var(--color-dim)]">observations → themes → Toulmin calls.</span>
        </li>
      </ol>
    </div>
  )
}


// ── Summary mode ───────────────────────────────────────

function SummaryMode({
  calls, themes, observations, ctx, onJumpToDrilldown,
}: {
  calls: LatticeCall[]
  themes: LatticeTheme[]
  observations: LatticeObservation[]
  ctx: DigestCtx
  onJumpToDrilldown: () => void
}) {
  const themeById = useMemo(
    () => Object.fromEntries(themes.map(t => [t.id, t])),
    [themes],
  )

  if (calls.length === 0) {
    return (
      <div className="p-3 text-[12px] text-[var(--color-text)] flex flex-col gap-2" data-testid="digest-zero-calls">
        <div className="flex items-center gap-2">
          <Info size={14} className="text-[var(--color-dim)]" />
          <span>No high-conviction call today.</span>
        </div>
        <div className="text-[11px] text-[var(--color-dim)]">
          {themes.length} theme{themes.length === 1 ? '' : 's'} and{' '}
          {observations.length} observation{observations.length === 1 ? '' : 's'} are still in scope.
          Switch to <button
            className="underline hover:text-[var(--color-accent)]"
            onClick={onJumpToDrilldown}
            data-testid="digest-goto-drilldown-from-empty"
          >drilldown</button> to see the evidence.
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col divide-y divide-[var(--color-border)]" data-testid="summary-calls">
      {calls.slice(0, 4).map(c => (
        <CallChipRow
          key={c.id}
          call={c}
          themes={c.grounds.map(g => themeById[g]).filter(Boolean)}
          onJumpToChat={ctx.onJumpToChat}
        />
      ))}
    </div>
  )
}

function CallChipRow({
  call, themes, onJumpToChat,
}: {
  call: LatticeCall
  themes: LatticeTheme[]
  onJumpToChat?: (prompt: string, ctx?: { symbol?: string; project?: boolean }) => void
}) {
  const [expanded, setExpanded] = useState<'because' | 'unless' | null>(null)

  return (
    <div className="p-3 flex flex-col gap-1.5" data-testid={`summary-call-${call.id}`}>
      <div className="flex items-start gap-2">
        <Target size={12} className="mt-0.5 shrink-0" style={{ color: CONF_COLOR[call.confidence] }} />
        <div className="flex-1 text-[12px] text-[var(--color-text)] leading-[1.5]">
          {/* Phase 6 followup #4: reasoning hyperlinks — recognised
              tokens (tickers / percentages / layer-ids) become hover
              chips that explain themselves. */}
          <ReasoningText text={call.claim} />
        </div>
        <div className="flex items-center gap-1 shrink-0 text-[9px] uppercase tracking-wider">
          <span className="px-1.5 py-0.5 rounded border border-[var(--color-border)] text-[var(--color-dim)]">
            {call.time_horizon}
          </span>
          <span
            className="px-1.5 py-0.5 rounded border"
            style={{ borderColor: CONF_COLOR[call.confidence], color: CONF_COLOR[call.confidence] }}
            data-testid={`call-conf-${call.id}`}
          >
            {call.confidence}
          </span>
        </div>
      </div>
      <div className="flex flex-wrap gap-1.5 text-[10px]">
        <Chip
          label="Because"
          icon={<Shield size={9} />}
          active={expanded === 'because'}
          onClick={() => setExpanded(expanded === 'because' ? null : 'because')}
          testId={`chip-because-${call.id}`}
        />
        <Chip
          label="Unless"
          icon={<AlertCircle size={9} />}
          active={expanded === 'unless'}
          onClick={() => setExpanded(expanded === 'unless' ? null : 'unless')}
          testId={`chip-unless-${call.id}`}
        />
        {onJumpToChat && (
          <button
            data-testid={`chip-ask-${call.id}`}
            onClick={() => onJumpToChat(
              `Expand on this call: "${call.claim}" — what could change it?`,
              { project: true },
            )}
            className="text-[10px] text-[var(--color-dim)] hover:text-[var(--color-accent)] underline underline-offset-2"
          >
            ask
          </button>
        )}
      </div>
      {expanded === 'because' && (
        <div className="pl-5 pt-1 flex flex-col gap-1" data-testid={`expand-because-${call.id}`}>
          <div className="text-[10px] uppercase tracking-wider text-[var(--color-dim)]">Grounds (themes)</div>
          {themes.length === 0 ? (
            <div className="text-[11px] italic text-[var(--color-red)]">
              grounds reference no known theme
            </div>
          ) : (
            themes.map(t => (
              <div key={t.id} className="text-[11px] flex gap-2">
                <span
                  className="shrink-0 w-16 text-[9px] uppercase tracking-wider"
                  style={{ color: SEVERITY_COLOR[t.severity] }}
                >
                  {t.severity}
                </span>
                <span className="text-[var(--color-text)]">
                  <b>{t.title}</b> · {t.narrative}
                </span>
              </div>
            ))
          )}
          <div className="text-[10px] text-[var(--color-dim)] pt-1">
            <b>Warrant:</b> <ReasoningText text={call.warrant} />
          </div>
        </div>
      )}
      {expanded === 'unless' && (
        <div className="pl-5 pt-1 flex flex-col gap-1" data-testid={`expand-unless-${call.id}`}>
          <div className="text-[10px] uppercase tracking-wider text-[var(--color-dim)]">Rebuttal (falsifier)</div>
          <div className="text-[11px] text-[var(--color-text)]"><ReasoningText text={call.rebuttal} /></div>
          <div className="text-[10px] text-[var(--color-dim)] pt-1">
            <b>Qualifier:</b> <ReasoningText text={call.qualifier} />
          </div>
        </div>
      )}
    </div>
  )
}

function Chip({
  label, icon, active, onClick, testId,
}: {
  label: string
  icon: React.ReactNode
  active: boolean
  onClick: () => void
  testId: string
}) {
  return (
    <button
      data-testid={testId}
      onClick={onClick}
      className={
        'inline-flex items-center gap-1 px-1.5 py-0.5 rounded border transition ' +
        (active
          ? 'bg-[var(--color-accent)] text-[var(--color-bg)] border-[var(--color-accent)]'
          : 'border-[var(--color-border)] text-[var(--color-dim)] hover:text-[var(--color-text)]')
      }
    >
      {icon}
      <span>{label}</span>
    </button>
  )
}


// ── Drilldown / Flat mode ──────────────────────────────

function DrilldownMode({
  calls, themes, subThemes, observations, startCollapsed, ctx,
}: {
  calls: LatticeCall[]
  themes: LatticeTheme[]
  subThemes: LatticeTheme[]
  observations: LatticeObservation[]
  startCollapsed: boolean
  ctx: DigestCtx
}) {
  const themeById = useMemo(
    () => Object.fromEntries(themes.map(t => [t.id, t])),
    [themes],
  )
  const obsById = useMemo(
    () => Object.fromEntries(observations.map(o => [o.id, o])),
    [observations],
  )
  // Reverse index: which themes does each observation belong to?
  const obsToThemes = useMemo(() => {
    const m: Record<string, string[]> = {}
    for (const t of themes) {
      for (const mem of t.members) {
        if (!m[mem.obs_id]) m[mem.obs_id] = []
        m[mem.obs_id].push(t.id)
      }
    }
    return m
  }, [themes])

  return (
    <div className="flex flex-col" data-testid="drilldown-body">
      <Section
        title={`L3 · ${calls.length} call${calls.length === 1 ? '' : 's'}`}
        startOpen={!startCollapsed || calls.length > 0}
        testId="section-l3"
      >
        {calls.length === 0 && (
          <div className="p-3 text-[11px] italic text-[var(--color-dim)]">
            No high-conviction call today.
          </div>
        )}
        {calls.map(c => (
          <CallDrilldown
            key={c.id}
            call={c}
            themeById={themeById}
            obsById={obsById}
            obsToThemes={obsToThemes}
            startCollapsed={startCollapsed}
            ctx={ctx}
          />
        ))}
      </Section>

      <Section
        title={`L2 · ${themes.length} theme${themes.length === 1 ? '' : 's'}`}
        startOpen={!startCollapsed}
        testId="section-l2"
      >
        {themes.map(t => (
          <ThemeDrilldown
            key={t.id}
            theme={t}
            obsById={obsById}
            obsToThemes={obsToThemes}
            startCollapsed={startCollapsed}
            ctx={ctx}
          />
        ))}
      </Section>

      {subThemes.length > 0 && (
        <Section
          title={`L1.5 · ${subThemes.length} sub-theme${subThemes.length === 1 ? '' : 's'}`}
          startOpen={!startCollapsed}
          testId="section-l15"
        >
          {subThemes.map(t => (
            <ThemeDrilldown
              key={t.id}
              theme={t}
              obsById={obsById}
              obsToThemes={obsToThemes}
              startCollapsed={startCollapsed}
              ctx={ctx}
            />
          ))}
        </Section>
      )}

      <Section
        title={`L1 · ${observations.length} observation${observations.length === 1 ? '' : 's'}`}
        startOpen={!startCollapsed}
        testId="section-l1"
      >
        <div className="p-2 flex flex-col gap-1">
          {observations.map(o => (
            <ObservationRow
              key={o.id}
              obs={o}
              belongsTo={(obsToThemes[o.id] ?? []).map(id => themeById[id]?.title ?? id)}
              ctx={ctx}
            />
          ))}
        </div>
      </Section>
    </div>
  )
}

function Section({
  title, children, startOpen, testId,
}: {
  title: string
  children: React.ReactNode
  startOpen: boolean
  testId: string
}) {
  const [open, setOpen] = useState(startOpen)
  return (
    <div className="border-b border-[var(--color-border)] last:border-b-0" data-testid={testId}>
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-2 px-3 py-1.5 text-[10px] uppercase tracking-wider text-[var(--color-dim)] hover:text-[var(--color-text)] transition"
        data-testid={`${testId}-toggle`}
      >
        {open ? <ChevronDown size={10} /> : <ChevronRight size={10} />}
        <span>{title}</span>
      </button>
      {open && <div>{children}</div>}
    </div>
  )
}

function CallDrilldown({
  call, themeById, obsById, obsToThemes, startCollapsed, ctx,
}: {
  call: LatticeCall
  themeById: Record<string, LatticeTheme>
  obsById: Record<string, LatticeObservation>
  obsToThemes: Record<string, string[]>
  startCollapsed: boolean
  ctx: DigestCtx
}) {
  const [open, setOpen] = useState(!startCollapsed)
  const themes = call.grounds.map(g => themeById[g]).filter(Boolean)
  const targetId = `drill-call-${call.id}`
  const highlighted = ctx.highlightId === targetId

  return (
    <div
      ref={el => ctx.registerRef(targetId, el)}
      className={
        'border-t border-[var(--color-border)] first:border-t-0 transition-shadow ' +
        (highlighted ? 'ring-2 ring-[var(--color-accent)] rounded' : '')
      }
      data-testid={targetId}
      data-highlighted={highlighted ? 'true' : undefined}
    >
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-start gap-2 px-3 py-2 text-left hover:bg-[var(--color-bg)]/40"
      >
        {open ? <ChevronDown size={10} className="mt-1 shrink-0" /> : <ChevronRight size={10} className="mt-1 shrink-0" />}
        <div className="flex-1 text-[12px] text-[var(--color-text)]"><ReasoningText text={call.claim} /></div>
        {/* Phase 5 V4: catalog reference chip — present iff strategy_matcher
            found a fit. Clicking jumps to the Strategies tab focused on
            this strategy. Stop propagation so the click doesn't also
            toggle the call open/closed. */}
        {call.strategy_match && (
          <span
            data-testid={`call-strategy-${call.strategy_match.strategy_id}`}
            data-source="lattice.calls[*].strategy_match (deterministic — agent.finance.lattice.strategy_matcher)"
            onClick={(e) => {
              e.stopPropagation()
              ctx.onJumpToStrategies?.(call.strategy_match!.strategy_id)
            }}
            className="text-[9px] px-1.5 py-0.5 rounded border shrink-0 cursor-pointer hover:bg-[var(--color-accent)]/10 transition flex items-center gap-1"
            style={{ borderColor: 'var(--color-accent)', color: 'var(--color-accent)' }}
            title={
              `Strategy: ${call.strategy_match.name_en} (${call.strategy_match.name_zh}) — score ${call.strategy_match.score}\n` +
              `breakdown: ${JSON.stringify(call.strategy_match.score_breakdown)}\n` +
              `click to open in Strategies tab`
            }
          >
            <span>{call.strategy_match.strategy_id}</span>
            {call.strategy_match.difficulty != null && (
              <span className="text-[var(--color-amber,#e5a200)]">
                {'★'.repeat(call.strategy_match.difficulty)}
              </span>
            )}
          </span>
        )}
        <span
          className="text-[9px] uppercase tracking-wider px-1.5 py-0.5 rounded border shrink-0"
          style={{ borderColor: CONF_COLOR[call.confidence], color: CONF_COLOR[call.confidence] }}
        >
          {call.confidence}
        </span>
      </button>
      {open && (
        <div className="px-6 pb-2 flex flex-col gap-1 text-[11px]">
          <div><b className="text-[var(--color-dim)]">Warrant:</b> <ReasoningText text={call.warrant} /></div>
          <div><b className="text-[var(--color-dim)]">Qualifier:</b> <ReasoningText text={call.qualifier} /></div>
          <div><b className="text-[var(--color-dim)]">Rebuttal:</b> <ReasoningText text={call.rebuttal} /></div>
          <div className="pt-1">
            <b className="text-[var(--color-dim)]">Grounds ({themes.length}):</b>
            <div className="pl-3 pt-1 flex flex-col gap-1.5">
              {themes.map(t => (
                <ThemeDrilldown
                  key={t.id}
                  theme={t}
                  obsById={obsById}
                  obsToThemes={obsToThemes}
                  startCollapsed
                  ctx={ctx}
                />
              ))}
            </div>
          </div>
          {ctx.onJumpToChat && (
            <button
              onClick={() => ctx.onJumpToChat!(
                `Expand on this call: "${call.claim}" — what could change it?`,
                { project: true },
              )}
              className="self-start mt-1 text-[10px] text-[var(--color-accent)] hover:underline"
            >
              ask more in chat →
            </button>
          )}
        </div>
      )}
    </div>
  )
}

function ThemeDrilldown({
  theme, obsById, obsToThemes, startCollapsed, ctx,
}: {
  theme: LatticeTheme
  obsById: Record<string, LatticeObservation>
  obsToThemes: Record<string, string[]>
  startCollapsed: boolean
  ctx: DigestCtx
}) {
  const [open, setOpen] = useState(!startCollapsed)
  const targetId = `drill-theme-${theme.id}`
  const highlighted = ctx.highlightId === targetId

  return (
    <div
      ref={el => ctx.registerRef(targetId, el)}
      data-testid={targetId}
      data-highlighted={highlighted ? 'true' : undefined}
      className={highlighted ? 'ring-2 ring-[var(--color-accent)] rounded' : ''}
    >
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-start gap-2 text-left hover:text-[var(--color-text)] text-[var(--color-text)]"
      >
        {open ? <ChevronDown size={9} className="mt-1 shrink-0" /> : <ChevronRight size={9} className="mt-1 shrink-0" />}
        <span
          className="shrink-0 text-[9px] uppercase tracking-wider mt-0.5"
          style={{ color: SEVERITY_COLOR[theme.severity] }}
        >
          {theme.severity}
        </span>
        <div className="flex-1 text-[11px]">
          <b>{theme.title}</b> · <span className="text-[var(--color-dim)]">{theme.narrative}</span>
        </div>
        <span className="text-[9px] text-[var(--color-dim)] shrink-0 mt-0.5">
          {theme.members.length} obs
        </span>
      </button>
      {open && (
        <div className="pl-5 pt-1 flex flex-col gap-0.5">
          {theme.members.map(m => {
            const obs = obsById[m.obs_id]
            if (!obs) return null
            return (
              <ObservationRow
                key={m.obs_id}
                obs={obs}
                weight={m.weight}
                belongsTo={(obsToThemes[m.obs_id] ?? [])
                  .filter(tid => tid !== theme.id)}
                ctx={ctx}
              />
            )
          })}
        </div>
      )}
    </div>
  )
}

function ObservationRow({
  obs, weight, belongsTo, ctx,
}: {
  obs: LatticeObservation
  weight?: number
  belongsTo?: string[]
  ctx: DigestCtx
}) {
  const reverseHint = belongsTo && belongsTo.length > 0
    ? `also in: ${belongsTo.join(', ')}`
    : undefined
  const targetId = `obs-${obs.id}`
  const highlighted = ctx.highlightId === targetId
  return (
    <div
      ref={el => ctx.registerRef(targetId, el)}
      data-testid={targetId}
      data-highlighted={highlighted ? 'true' : undefined}
      title={reverseHint}
      className={
        'group flex items-start gap-2 text-[11px] py-0.5 hover:bg-[var(--color-bg)]/40 rounded px-1 -mx-1 transition-shadow ' +
        (highlighted ? 'ring-2 ring-[var(--color-accent)]' : '')
      }
    >
      <span
        className="shrink-0 w-14 text-[9px] uppercase tracking-wider mt-0.5"
        style={{ color: SEVERITY_COLOR[obs.severity] }}
      >
        {obs.severity}
      </span>
      <span className="flex-1 text-[var(--color-text)]">{obs.text}</span>
      {typeof weight === 'number' && (
        <span className="shrink-0 text-[9px] text-[var(--color-dim)] mt-0.5">
          w {weight.toFixed(2)}
        </span>
      )}
      {reverseHint && (
        <span
          className="opacity-0 group-hover:opacity-100 transition shrink-0 text-[9px] text-[var(--color-accent)] mt-0.5"
          data-testid={`obs-${obs.id}-reverse`}
        >
          {belongsTo!.length} other{belongsTo!.length === 1 ? '' : 's'}
        </span>
      )}
    </div>
  )
}
