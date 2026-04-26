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
              much data is in the store at a glance. */}
          {dbHealth.data && (
            <div
              data-testid="fin-integrity-counts"
              className="flex flex-wrap gap-x-3 gap-y-1 text-[9px] text-[var(--color-dim)] border-b border-[var(--color-border)] pb-1.5"
            >
              <span><b className="text-[var(--color-text)]">{dbHealth.data.counts.market_data_daily}</b> bars</span>
              <span><b className="text-[var(--color-text)]">{dbHealth.data.counts.tickers_universe}</b> tickers</span>
              <span><b className="text-[var(--color-text)]">{dbHealth.data.counts.tax_lots}</b> lots</span>
              <span><b className="text-[var(--color-text)]">{dbHealth.data.counts.wash_sale_events}</b> wash sales</span>
              <span><b className="text-[var(--color-text)]">{dbHealth.data.counts.pdt_round_trips}</b> PDT round-trips</span>
              <span><b className="text-[var(--color-text)]">{dbHealth.data.counts.analysis_runs}</b> runs</span>
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

function FinCheckRow({ check }: { check: FinIntegrityCheck }) {
  const [expand, setExpand] = useState(false)
  const hasOffenders = !!check.offenders && check.offenders.length > 0
  const layerColor: Record<string, string> = {
    data: 'var(--color-blue,#5fa8ff)',
    compute: 'var(--color-purple,#b07eff)',
    compliance: 'var(--color-amber,#e5a200)',
    viz: 'var(--color-pink,#ff6fbb)',
  }
  return (
    <div
      data-testid={`fin-integrity-check-${check.name}`}
      data-integrity-pass={check.pass ? 'true' : 'false'}
      className={
        'rounded border px-2 py-1.5 ' +
        (check.pass
          ? 'border-[var(--color-border)] bg-[var(--color-bg)]/40'
          : 'border-[var(--color-amber,#e5a200)] bg-[var(--color-bg)]/40')
      }
    >
      <div
        className="flex items-start gap-1.5 cursor-pointer"
        onClick={() => hasOffenders && setExpand(!expand)}
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
        {hasOffenders && (
          <span className="text-[var(--color-dim)] text-[9px]">{expand ? '▾' : '▸'}</span>
        )}
      </div>
      {expand && hasOffenders && (
        <pre className="mt-1.5 text-[9px] leading-[1.3] text-[var(--color-dim)] bg-[var(--color-bg)] rounded p-1 overflow-x-auto">
          {JSON.stringify(check.offenders, null, 2)}
        </pre>
      )}
    </div>
  )
}
