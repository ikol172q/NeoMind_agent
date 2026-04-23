import { useEffect, useMemo, useRef, useState } from 'react'
import {
  useLatticeCalls, useWatchlist, usePaperPositions, useAnomalies,
  type LatticeCall, type LatticeTheme, type LatticeObservation,
  type AnomalyFlag,
} from '@/lib/api'
import { useQueryClient } from '@tanstack/react-query'
import { Button } from '@/components/ui/Button'
import { LatticeGraphView } from './LatticeGraphView'
import { useLatticeLanguage, setLatticeLanguage } from '@/lib/api'
import {
  Sparkles, RefreshCw, ChevronRight, ChevronDown, Languages,
  Target, Shield, AlertCircle, Info, AlertTriangle,
} from 'lucide-react'

export interface DigestFocus {
  symbol?: string
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

export function DigestView({ projectId, onJumpToChat, focus }: Props) {
  const q = useLatticeCalls(projectId)
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

  const ctx: DigestCtx = {
    highlightId,
    registerRef: (id, el) => { targetRefs.current[id] = el },
    onJumpToChat,
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
          <LatticeGraphView projectId={projectId} />
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
}: {
  mode: Mode
  setMode: (m: Mode) => void
  fetchedAt?: string
  loading: boolean
  onRefresh: () => void
}) {
  return (
    <div className="flex items-center gap-2 px-3 py-1.5 border-b border-[var(--color-border)] shrink-0">
      <Sparkles size={12} className="text-[var(--color-accent)]" />
      <span className="text-[10px] uppercase tracking-wider text-[var(--color-dim)] flex-1">
        Today's lattice · L1 → L2 → L3
        {fetchedAt && (
          <span className="ml-2 text-[var(--color-dim)]/80">
            updated {new Date(fetchedAt).toLocaleTimeString()}
          </span>
        )}
      </span>
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
      <LanguageToggle />
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
    </div>
  )
}


function LanguageToggle() {
  const qc = useQueryClient()
  const q = useLatticeLanguage()
  const active = q.data?.active
  const label = active === 'zh-CN-mixed' ? '中' : active === 'en' ? 'EN' : '—'
  const title = active === 'zh-CN-mixed'
    ? 'Output language: 中英混合 — click to switch to English'
    : active === 'en'
      ? 'Output language: English — click to switch to 中英混合'
      : 'Output language (loading)'
  return (
    <button
      data-testid="digest-language-toggle"
      data-language-active={active}
      onClick={async () => {
        if (!active) return
        const next = active === 'en' ? 'zh-CN-mixed' : 'en'
        try {
          await setLatticeLanguage(next)
        } catch (e) {
          console.error('failed to set language', e)
          return
        }
        // Busts server caches; now bust client caches so UI repaints
        qc.invalidateQueries({ queryKey: ['lattice_language'] })
        qc.invalidateQueries({ queryKey: ['lattice_calls'] })
        qc.invalidateQueries({ queryKey: ['lattice_graph'] })
        qc.invalidateQueries({ queryKey: ['lattice_trace'] })
      }}
      disabled={!active}
      className="inline-flex items-center gap-1 px-2 py-0.5 rounded border border-[var(--color-border)] text-[10px] text-[var(--color-dim)] hover:text-[var(--color-text)] hover:border-[var(--color-accent)] transition"
      title={title}
    >
      <Languages size={10} />
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
          {call.claim}
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
            <b>Warrant:</b> {call.warrant}
          </div>
        </div>
      )}
      {expanded === 'unless' && (
        <div className="pl-5 pt-1 flex flex-col gap-1" data-testid={`expand-unless-${call.id}`}>
          <div className="text-[10px] uppercase tracking-wider text-[var(--color-dim)]">Rebuttal (falsifier)</div>
          <div className="text-[11px] text-[var(--color-text)]">{call.rebuttal}</div>
          <div className="text-[10px] text-[var(--color-dim)] pt-1">
            <b>Qualifier:</b> {call.qualifier}
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
        <div className="flex-1 text-[12px] text-[var(--color-text)]">{call.claim}</div>
        <span
          className="text-[9px] uppercase tracking-wider px-1.5 py-0.5 rounded border shrink-0"
          style={{ borderColor: CONF_COLOR[call.confidence], color: CONF_COLOR[call.confidence] }}
        >
          {call.confidence}
        </span>
      </button>
      {open && (
        <div className="px-6 pb-2 flex flex-col gap-1 text-[11px]">
          <div><b className="text-[var(--color-dim)]">Warrant:</b> {call.warrant}</div>
          <div><b className="text-[var(--color-dim)]">Qualifier:</b> {call.qualifier}</div>
          <div><b className="text-[var(--color-dim)]">Rebuttal:</b> {call.rebuttal}</div>
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
