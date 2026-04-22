import { useMemo, useState } from 'react'
import {
  useLatticeCalls, useWatchlist, usePaperPositions,
  type LatticeCall, type LatticeTheme, type LatticeObservation,
} from '@/lib/api'
import { Button } from '@/components/ui/Button'
import {
  Sparkles, RefreshCw, ChevronRight, ChevronDown,
  Target, Shield, AlertCircle, Info,
} from 'lucide-react'

interface Props {
  projectId: string
  onJumpToChat?: (prompt: string, ctx?: { symbol?: string; project?: boolean }) => void
}

type Mode = 'summary' | 'drilldown' | 'flat'

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

export function DigestView({ projectId, onJumpToChat }: Props) {
  const q = useLatticeCalls(projectId)
  const wl = useWatchlist(projectId)
  const pos = usePaperPositions(projectId)
  const [mode, setMode] = useState<Mode>('summary')

  const isFreshInstall =
    (wl.data?.entries?.length ?? 0) === 0 &&
    (pos.data?.positions?.length ?? 0) === 0

  const payload = q.data
  const themes = payload?.themes ?? []
  const calls = payload?.calls ?? []
  const observations = payload?.observations ?? []

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

      <div className="flex-1 overflow-y-auto" data-testid="digest-body">
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
            onJumpToChat={onJumpToChat}
            onJumpToDrilldown={() => setMode('drilldown')}
          />
        )}
        {!q.isLoading && !q.isError && !isFreshInstall && mode === 'drilldown' && (
          <DrilldownMode
            calls={calls}
            themes={themes}
            observations={observations}
            startCollapsed
            onJumpToChat={onJumpToChat}
          />
        )}
        {!q.isLoading && !q.isError && !isFreshInstall && mode === 'flat' && (
          <DrilldownMode
            calls={calls}
            themes={themes}
            observations={observations}
            startCollapsed={false}
            onJumpToChat={onJumpToChat}
          />
        )}
      </div>
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
        {(['summary', 'drilldown', 'flat'] as Mode[]).map(m => (
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
                  : 'all layers expanded (debug)'
            }
          >
            {m[0].toUpperCase()}
          </button>
        ))}
      </div>
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
  calls, themes, observations, onJumpToChat, onJumpToDrilldown,
}: {
  calls: LatticeCall[]
  themes: LatticeTheme[]
  observations: LatticeObservation[]
  onJumpToChat?: (prompt: string, ctx?: { symbol?: string; project?: boolean }) => void
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
          onJumpToChat={onJumpToChat}
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
  calls, themes, observations, startCollapsed, onJumpToChat,
}: {
  calls: LatticeCall[]
  themes: LatticeTheme[]
  observations: LatticeObservation[]
  startCollapsed: boolean
  onJumpToChat?: (prompt: string, ctx?: { symbol?: string; project?: boolean }) => void
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
            onJumpToChat={onJumpToChat}
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
          />
        ))}
      </Section>

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
  call, themeById, obsById, obsToThemes, startCollapsed, onJumpToChat,
}: {
  call: LatticeCall
  themeById: Record<string, LatticeTheme>
  obsById: Record<string, LatticeObservation>
  obsToThemes: Record<string, string[]>
  startCollapsed: boolean
  onJumpToChat?: (prompt: string, ctx?: { symbol?: string; project?: boolean }) => void
}) {
  const [open, setOpen] = useState(!startCollapsed)
  const themes = call.grounds.map(g => themeById[g]).filter(Boolean)

  return (
    <div className="border-t border-[var(--color-border)] first:border-t-0" data-testid={`drill-call-${call.id}`}>
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
                />
              ))}
            </div>
          </div>
          {onJumpToChat && (
            <button
              onClick={() => onJumpToChat(
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
  theme, obsById, obsToThemes, startCollapsed,
}: {
  theme: LatticeTheme
  obsById: Record<string, LatticeObservation>
  obsToThemes: Record<string, string[]>
  startCollapsed: boolean
}) {
  const [open, setOpen] = useState(!startCollapsed)

  return (
    <div data-testid={`drill-theme-${theme.id}`}>
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
              />
            )
          })}
        </div>
      )}
    </div>
  )
}

function ObservationRow({
  obs, weight, belongsTo,
}: {
  obs: LatticeObservation
  weight?: number
  belongsTo?: string[]
}) {
  const reverseHint = belongsTo && belongsTo.length > 0
    ? `also in: ${belongsTo.join(', ')}`
    : undefined
  return (
    <div
      data-testid={`obs-${obs.id}`}
      title={reverseHint}
      className="group flex items-start gap-2 text-[11px] py-0.5 hover:bg-[var(--color-bg)]/40 rounded px-1 -mx-1"
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
