/**
 * FinIntegrityBadge — fin-data-platform sibling of the lattice's
 * IntegrityBadge in DigestView.tsx. Same look, same drill-down
 * behaviour, hits /api/integrity/check (the SQLite-store invariants:
 * schema, dedup, attribution, temporal, compliance).
 *
 * Lazy fetch — only on click — so a closed badge costs nothing.
 */
import { useState } from 'react'
import { Database, ShieldAlert, ShieldCheck } from 'lucide-react'
import {
  useFinDbHealth,
  useFinIntegrity,
  useFinLatticeObs,
  type FinIntegrityCheck,
  type FinLatticeObs,
} from '@/lib/api'

export function FinIntegrityBadge() {
  const [open, setOpen] = useState(false)
  const q = useFinIntegrity(open)
  const dbHealth = useFinDbHealth()
  const lineage = useFinLatticeObs(open)
  const checks = q.data?.checks ?? []
  const allPass = q.data?.all_pass

  const status: 'unknown' | 'pass' | 'fail' =
    q.data == null ? 'unknown' : allPass ? 'pass' : 'fail'
  const color =
    status === 'pass'
      ? 'var(--color-green)'
      : status === 'fail'
        ? 'var(--color-amber,#e5a200)'
        : 'var(--color-dim)'
  const Icon = status === 'fail' ? ShieldAlert : ShieldCheck

  return (
    <div className="relative">
      <button
        data-testid="fin-integrity-toggle"
        data-integrity-status={status}
        onClick={() => setOpen(!open)}
        className="inline-flex items-center gap-1 px-2 py-0.5 rounded border text-[10px] transition"
        style={{ borderColor: color, color }}
        title={
          status === 'unknown'
            ? 'Run live integrity checks on the fin SQLite store'
            : allPass
              ? `Fin DB ✓ — ${q.data?.summary}. Click for details.`
              : `Fin DB ⚠ — ${q.data?.summary}. Click to see failures.`
        }
      >
        <Database size={10} />
        <Icon size={10} />
        <span className="font-mono">
          {status === 'unknown' ? 'fin' : `fin ${q.data?.summary}`}
        </span>
      </button>
      {open && (
        <>
          {/* Click-away catcher — matches the AsOfPicker pattern.
              Without this the popover stayed open across tab clicks
              and would only close by re-clicking the fin badge.
              The fixed-inset overlay absorbs clicks outside, the
              tabIndex=-1 + aria-hidden keeps it out of the tab
              order and the screen-reader tree. */}
          <button
            onClick={() => setOpen(false)}
            className="fixed inset-0 z-10 cursor-default"
            tabIndex={-1}
            aria-hidden="true"
          />
        <div
          data-testid="fin-integrity-panel"
          className="absolute top-full right-0 mt-1 w-[420px] max-h-[440px] overflow-y-auto rounded border border-[var(--color-border)] bg-[var(--color-panel)] shadow-lg p-3 text-[10px] z-20 flex flex-col gap-2"
        >
          <div className="flex items-center justify-between">
            <span className="uppercase tracking-wider text-[var(--color-dim)]">
              Fin Data Platform — Live Integrity
            </span>
            <button
              onClick={() => {
                q.refetch()
                dbHealth.refetch()
              }}
              disabled={q.isFetching}
              className="text-[var(--color-dim)] hover:text-[var(--color-text)] text-[9px]"
              title="re-run checks"
            >
              {q.isFetching ? 'running…' : 'refresh'}
            </button>
          </div>
          {/* Top stats row — table counts so the user can see how
              much data is in the store at a glance. Each number's
              data-source attribute documents which SQL row count
              it represents (audit trail in DOM). */}
          {dbHealth.data && (
            <div
              data-testid="fin-integrity-counts"
              data-source="GET /api/db/health → counts.*"
              className="flex flex-wrap gap-x-3 gap-y-1 text-[9px] text-[var(--color-dim)] border-b border-[var(--color-border)] pb-1.5"
            >
              <span data-source="counts.market_data_daily"><b className="text-[var(--color-text)]">{dbHealth.data.counts.market_data_daily}</b> bars</span>
              <span data-source="counts.tickers_universe"><b className="text-[var(--color-text)]">{dbHealth.data.counts.tickers_universe}</b> tickers</span>
              <span data-source="counts.tax_lots"><b className="text-[var(--color-text)]">{dbHealth.data.counts.tax_lots}</b> lots</span>
              <span data-source="counts.wash_sale_events"><b className="text-[var(--color-text)]">{dbHealth.data.counts.wash_sale_events}</b> wash sales</span>
              <span data-source="counts.pdt_round_trips"><b className="text-[var(--color-text)]">{dbHealth.data.counts.pdt_round_trips}</b> PDT round-trips</span>
              <span data-source="counts.analysis_runs"><b className="text-[var(--color-text)]">{dbHealth.data.counts.analysis_runs}</b> runs</span>
            </div>
          )}
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
                  ? ' — every invariant holds on the SQLite store.'
                  : ' — see failing checks below.'}
              </div>
              <div className="flex flex-col gap-1.5">
                {checks.map((c) => (
                  <FinCheckRow key={c.name} check={c} />
                ))}
              </div>
              {/* Lineage: what L1 obs this store would emit into the
                  lattice right now. Direct answer to "where does my
                  recommendation actually come from?". */}
              {lineage.data && lineage.data.available && (
                <div
                  data-testid="fin-lineage-section"
                  className="border-t border-[var(--color-border)] pt-1.5 flex flex-col gap-1"
                >
                  <div className="flex items-baseline justify-between">
                    <span className="text-[9px] uppercase tracking-wider text-[var(--color-dim)]">
                      → emits {lineage.data.count} L1 obs into lattice (
                      <span className="text-[var(--color-accent)] font-mono">{lineage.data.feeds_into}</span>
                      )
                    </span>
                  </div>
                  {lineage.data.obs.length === 0 && (
                    <div className="text-[9px] italic text-[var(--color-dim)]">
                      No L1 obs being emitted right now (no recent wash
                      sales / PDT / near-LT lots in the store).
                    </div>
                  )}
                  {lineage.data.obs.map((o) => (
                    <FinLineageRow key={o.id} obs={o} />
                  ))}
                  <div className="text-[8px] text-[var(--color-dim)] italic leading-[1.4] pt-0.5">
                    {lineage.data.explanation}
                  </div>
                </div>
              )}
              <div className="text-[9px] text-[var(--color-dim)] border-t border-[var(--color-border)] pt-1.5 leading-[1.4]">
                Storage-layer guarantees (schema dedup / attribution /
                temporal consistency / IRS &amp; PDT rule logic).
                Sibling of the lattice 5/5 widget. Both run in CI on
                every commit.
              </div>
            </>
          )}
        </div>
        </>
      )}
    </div>
  )
}

function FinLineageRow({ obs }: { obs: FinLatticeObs }) {
  const [expand, setExpand] = useState(false)
  const sevColor =
    obs.severity === 'alert'
      ? 'var(--color-red)'
      : obs.severity === 'warn'
        ? 'var(--color-amber,#e5a200)'
        : 'var(--color-dim)'
  const symbol = obs.source.symbol ?? obs.tags.find((t) => t.startsWith('symbol:'))?.slice(7) ?? ''
  return (
    <div
      data-testid={`fin-lineage-${obs.kind}`}
      className="rounded border border-[var(--color-border)] bg-[var(--color-bg)]/40 px-2 py-1 cursor-pointer"
      onClick={() => setExpand(!expand)}
    >
      <div className="flex items-baseline gap-2 text-[10px]">
        <span style={{ color: sevColor }} className="font-mono w-3">
          {obs.severity === 'warn' ? '⚠' : obs.severity === 'alert' ? '✗' : '·'}
        </span>
        <span className="font-mono text-[var(--color-text)]">{obs.kind}</span>
        {symbol && (
          <span className="text-[var(--color-accent)] font-mono">{symbol}</span>
        )}
        <span className="text-[var(--color-dim)] truncate flex-1">
          {obs.source.widget}
        </span>
        <span className="text-[8px] text-[var(--color-dim)]">{expand ? '▾' : '▸'}</span>
      </div>
      {expand && (
        <div className="mt-1 text-[9px] text-[var(--color-dim)] flex flex-col gap-0.5">
          <div className="leading-[1.4]">{obs.text}</div>
          <div className="flex flex-wrap gap-1 pt-0.5">
            {obs.tags.map((t) => (
              <span
                key={t}
                className="font-mono text-[8px] px-1 rounded bg-[var(--color-bg)] border border-[var(--color-border)]"
              >
                {t}
              </span>
            ))}
          </div>
          <div className="font-mono text-[8px] pt-0.5">
            generator: <span className="text-[var(--color-accent)]">{obs.source.generator ?? '?'}</span>
          </div>
        </div>
      )}
    </div>
  )
}

// What each invariant *means* in plain language. Shown when the user
// expands a check row — even passing rows expand, with explanation
// instead of offenders. The keys match check.name from the backend.
const CHECK_DESCRIPTIONS: Record<string, string> = {
  schema_version_matches:
    "Refuses to operate on a future-version DB. Prevents silent data corruption when running an old code build against a newer schema.",
  signal_dedup_keys_unique:
    "strategy_signals.dedup_key is a content hash of (symbol, strategy_id, horizon, signal_type, target_price, stop_loss). Repeated runs of the same job MUST collapse to one row + bumped seen_count, not duplicate.",
  lot_idempotency_keys_unique:
    "tax_lots.idempotency_key is set when ingesting from CSV / broker statements; lets re-imports be no-ops. UNIQUE only when not NULL (paper trades / manual entry skip the key).",
  market_data_pk_unique:
    "Composite PK (symbol, market, trade_date) on market_data_daily — same bar from yfinance must REPLACE, not append. INSERT OR REPLACE in DAO.",
  market_data_has_source:
    "Storage-layer enforcement of response_validator's Rule 3 (every data point has source + timestamp). Same convention as VerifiedDataPoint in data_hub.py.",
  signals_have_run_ref:
    "Every strategy_signal.run_id either points at a real analysis_runs row, or is NULL. FK enforces this on insert; this check verifies the invariant against bulk-imported data too.",
  scheduler_jobs_match_registry:
    "Every job in DEFAULT_JOBS has a row in scheduler_jobs (and vice versa). Catches the brief inconsistency between adding a new job and the next scheduler tick mirroring it.",
  runs_temporally_consistent:
    "completed_at >= started_at AND duration_seconds >= 0. A negative duration almost always means clock skew or a buggy stamping path.",
  lots_temporally_consistent:
    "close_date >= open_date for every closed lot. Trivially impossible to violate via DAO, but bulk imports could.",
  run_durations_match_timestamps:
    "duration_seconds equals (completed_at - started_at) within 1.5s tolerance. Catches the case where the runner stamps a duration from a different clock than the timestamps.",
  wash_sale_within_window:
    "IRS § 1091: |sell_date - replacement_date| ≤ 30 days. Verified against the lots' actual dates, not just the stored days_between value.",
  pdt_within_5_trading_days:
    "FINRA PDT: detected round-trips reference trades within 9 calendar days (≈ 5 trading days + weekends + ~2 holidays upper bound).",
  holding_period_classification:
    "IRS Pub 544/550: closed lots' holding_period_qualified ('long_term' iff days_held > 365). Boundary tested at 365 → short_term, 366 → long_term.",
  ui_data_sources_resolvable:
    "Every UI element with a data-source attribute (PDT counter, fin badge counts row) must resolve to a real backend value — not a fabricated, stale, or detached display. Manifest in agent/finance/integrity/checks/viz.py. Inspect the data-source attrs in DevTools to see the audit trail in the DOM.",
}

function FinCheckRow({ check }: { check: FinIntegrityCheck }) {
  const [expand, setExpand] = useState(false)
  const hasOffenders = !!check.offenders && check.offenders.length > 0
  const description = CHECK_DESCRIPTIONS[check.name]
  const layerColor: Record<string, string> = {
    data: 'var(--color-blue,#5fa8ff)',
    compute: 'var(--color-purple,#b07eff)',
    compliance: 'var(--color-amber,#e5a200)',
    viz: 'var(--color-pink,#ff6fbb)',
  }
  void layerColor // referenced from rows below — silences unused-var when imported standalone
  return (
    <div
      data-testid={`fin-integrity-check-${check.name}`}
      data-integrity-pass={check.pass ? 'true' : 'false'}
      className={
        'rounded border px-2 py-1.5 transition ' +
        (check.pass
          ? 'border-[var(--color-border)] bg-[var(--color-bg)]/40 hover:border-[var(--color-accent)]/50'
          : 'border-[var(--color-amber,#e5a200)] bg-[var(--color-bg)]/40')
      }
    >
      <div
        className="flex items-start gap-1.5 cursor-pointer"
        onClick={() => setExpand(!expand)}
      >
        <span style={{ color: check.pass ? 'var(--color-green)' : 'var(--color-amber,#e5a200)' }}>
          {check.pass ? '✓' : '⚠'}
        </span>
        <div className="flex-1">
          <div className="text-[var(--color-text)] flex items-center gap-1.5">
            <span
              className="text-[8px] uppercase tracking-wider px-1 rounded"
              style={{ color: layerColor[check.layer] ?? 'var(--color-dim)', borderColor: 'currentColor' }}
            >
              {check.layer}
            </span>
            {check.label}
          </div>
          <div className="text-[var(--color-dim)] mt-0.5">{check.detail}</div>
          {check.error && (
            <div className="text-[var(--color-red)] mt-0.5">{check.error}</div>
          )}
        </div>
        <span className="text-[var(--color-dim)] text-[9px]">{expand ? '▾' : '▸'}</span>
      </div>
      {expand && (
        <div className="mt-1.5 flex flex-col gap-1 text-[9px]">
          {description && (
            <div className="text-[var(--color-dim)] leading-[1.4] italic">
              {description}
            </div>
          )}
          <div className="font-mono text-[8px] text-[var(--color-dim)]">
            check_name: <span className="text-[var(--color-accent)]">{check.name}</span>
            {' · '}layer: <span className="text-[var(--color-accent)]">{check.layer}</span>
          </div>
          {hasOffenders && (
            <>
              <div className="text-[var(--color-amber,#e5a200)]">
                {check.offenders!.length} offending row{check.offenders!.length === 1 ? '' : 's'}:
              </div>
              <pre className="leading-[1.3] text-[var(--color-dim)] bg-[var(--color-bg)] rounded p-1 overflow-x-auto">
                {JSON.stringify(check.offenders, null, 2)}
              </pre>
            </>
          )}
        </div>
      )}
    </div>
  )
}
