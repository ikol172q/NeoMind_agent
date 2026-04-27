/**
 * FreshnessBar — Phase B6-Step1 visible breadcrumb.
 *
 * Renders one row above each lattice tab body showing the dep_hash,
 * compute_run_id, model + temperature, cache hit/miss state, and a
 * compact lineage chip ("L3 ← L2 ← L1") that tells the user "this
 * view's content was computed from these specific upstream runs".
 *
 * Click dep_hash → copy to clipboard
 * Click "lineage" chip → expand into a small panel listing each run id
 * Click compute_run_id → opens /api/compute/runs/{id} in a new tab
 *
 * The bar is intentionally simple — single row, monospace ids, low
 * vertical real estate.  The Status panel (B6-Step2) will be the
 * larger draggable surface; this bar is just the always-visible
 * provenance breadcrumb the design doc calls "Freshness Bar".
 */
import { useState } from 'react'
import type { LatticeRunMeta } from '@/lib/api'

interface Props {
  /** When undefined the bar renders a thin "historical snapshot"
   *  hint instead of disappearing — historical-snapshot reads
   *  (as_of=YYYY-MM-DD) deliberately don't carry run_meta because
   *  the snapshot envelope is a frozen artifact, not a live cache.
   *  The hint tells the user that's why the dep_hash chips are
   *  absent. */
  meta: LatticeRunMeta | undefined
  /** A short label that prefixes the row, e.g. "Research" or
   *  "Strategies".  Helps the user disambiguate when several tabs
   *  show the bar simultaneously (rare but possible). */
  pipelineLabel?: string
  /** Optional click-through to open a "compute run detail" surface.
   *  When not supplied the run_id chip is non-interactive. */
  onOpenRun?: (computeRunId: string) => void
  /** When true and meta is undefined, render the historical-snapshot
   *  hint row.  When false (default) and meta is undefined, render
   *  nothing.  Set to true on tabs that always want the strip's
   *  vertical real estate reserved. */
  showSnapshotHint?: boolean
}

const SHORT_HASH_LEN = 8

function shortHash(h: string | null | undefined): string {
  if (!h) return '—'
  return h.slice(0, SHORT_HASH_LEN)
}

function fmtTime(iso: string | null | undefined): string {
  if (!iso) return ''
  // Rendered as HH:MM:SS UTC for compactness
  try {
    const d = new Date(iso)
    return d.toLocaleTimeString('en-GB', { hour12: false })
  } catch {
    return iso.slice(11, 19)
  }
}

export function FreshnessBar({ meta, pipelineLabel, onOpenRun, showSnapshotHint }: Props) {
  const [expanded, setExpanded] = useState(false)
  const [copied, setCopied] = useState<string | null>(null)

  if (!meta) {
    if (!showSnapshotHint) return null
    return (
      <div
        data-testid="freshness-bar"
        data-mode="snapshot"
        className="
          flex flex-wrap items-center gap-x-3 px-2 py-1 text-[10.5px]
          border-b border-[var(--color-border)]
          bg-[var(--color-panel-2,var(--color-panel))]
          text-[var(--color-dim)] italic font-mono select-none
        "
        title={
          'No live run_meta because this view is reading a historical snapshot ' +
          '(as_of=YYYY-MM-DD). Snapshot envelopes are frozen artifacts and do ' +
          'not carry the dep_hash cache breadcrumb. Switch the date picker ' +
          'back to "Live" to see the dep_hash + cache-hit row.'
        }
      >
        {pipelineLabel && (
          <span className="not-italic uppercase tracking-wide">{pipelineLabel}</span>
        )}
        <span>📜 historical snapshot — provenance breadcrumb hidden (switch to Live to see dep_hash)</span>
      </div>
    )
  }

  const cacheHit = meta.cache_hit === true
  const hitColor = cacheHit
    ? 'var(--color-green, #4caf50)'
    : 'var(--color-amber, #ff9800)'

  function copy(value: string, key: string) {
    try {
      void navigator.clipboard.writeText(value)
      setCopied(key)
      window.setTimeout(() => setCopied((c) => (c === key ? null : c)), 1500)
    } catch {
      // Clipboard API unavailable — degrade silently.
    }
  }

  return (
    <div
      data-testid="freshness-bar"
      className="
        flex flex-wrap items-center gap-x-3 gap-y-1
        px-2 py-1 text-[10.5px]
        border-b border-[var(--color-border)]
        bg-[var(--color-panel-2,var(--color-panel))]
        font-mono select-none
      "
      title={
        cacheHit
          ? 'Served from dep_hash cache — strict content-addressed match'
          : 'Freshly computed — no matching dep_hash in cache'
      }
    >
      {/* Pipeline label + cache pill */}
      {pipelineLabel && (
        <span className="text-[var(--color-dim)] uppercase tracking-wide">
          {pipelineLabel}
        </span>
      )}
      <span
        className="px-1.5 py-[1px] rounded text-[9.5px] uppercase tracking-wide"
        style={{
          background: hitColor,
          color: 'var(--color-bg, #000)',
          opacity: 0.85,
        }}
      >
        {cacheHit ? 'cached' : 'fresh'}
      </span>

      {/* Time */}
      <span className="text-[var(--color-dim)]" title={meta.completed_at || meta.started_at}>
        {fmtTime(meta.completed_at || meta.started_at)}
      </span>

      {/* dep_hash — clickable to copy */}
      <button
        type="button"
        className="text-[var(--color-fg)] hover:underline"
        title={`dep_hash: click to copy full hash\n${meta.dep_hash}`}
        onClick={() => copy(meta.dep_hash, 'dep')}
      >
        ⚙ {shortHash(meta.dep_hash)}
        {copied === 'dep' && (
          <span className="ml-1 text-[var(--color-green,#4caf50)]">✓</span>
        )}
      </button>

      {/* compute_run_id — opens run detail */}
      {meta.compute_run_id && (
        <button
          type="button"
          className="text-[var(--color-accent)] hover:underline"
          title={`compute_run_id: ${meta.compute_run_id}\nclick to view detail`}
          onClick={() =>
            onOpenRun
              ? onOpenRun(meta.compute_run_id!)
              : copy(meta.compute_run_id!, 'run')
          }
        >
          🏷 {shortHash(meta.compute_run_id)}
          {copied === 'run' && (
            <span className="ml-1 text-[var(--color-green,#4caf50)]">✓</span>
          )}
        </button>
      )}

      {/* Model + temperature */}
      {meta.llm_model_id && (
        <span className="text-[var(--color-dim)]">
          🧠 {meta.llm_model_id}
          {typeof meta.llm_temperature === 'number' && (
            <> @ T={meta.llm_temperature}</>
          )}
        </span>
      )}

      {/* B7: validation badge */}
      {meta.validation_state && (
        <span
          className="px-1.5 py-[1px] rounded text-[9.5px] uppercase tracking-wide"
          style={{
            background:
              meta.validation_state === 'fail'
                ? 'var(--color-red, #f44336)'
                : meta.validation_state === 'warn'
                  ? 'var(--color-amber, #ff9800)'
                  : meta.validation_state === 'pass'
                    ? 'var(--color-green, #4caf50)'
                    : 'var(--color-dim, #888)',
            color: 'var(--color-bg, #000)',
            opacity: 0.85,
          }}
          title={
            (meta.validation_summary
              ? `pass=${meta.validation_summary.n_pass ?? 0} ` +
                `warn=${meta.validation_summary.n_warn ?? 0} ` +
                `fail=${meta.validation_summary.n_fail ?? 0} ` +
                `unknown=${meta.validation_summary.n_unknown ?? 0}`
              : '') +
            ` — fail does NOT block the result; this badge only surfaces it`
          }
        >
          ✓ {meta.validation_summary?.n_pass ?? 0}/{meta.validation_summary?.n_total ?? 0}
        </span>
      )}

      {/* Inputs summary (when present) */}
      {meta.inputs_summary && (
        <span className="text-[var(--color-dim)]">
          📰{' '}
          {meta.inputs_summary.n_news_entries ?? 0} news ·{' '}
          {meta.inputs_summary.n_symbols ?? 0} sym ·{' '}
          {meta.inputs_summary.n_anomalies ?? 0} anom
        </span>
      )}

      {/* Lineage chip — only present on themes / calls */}
      {(meta.themes_compute_run_id || meta.obs_compute_run_id) && (
        <button
          type="button"
          className="ml-auto text-[var(--color-dim)] hover:text-[var(--color-fg)] hover:underline"
          onClick={() => setExpanded((e) => !e)}
          title="Click to expand the L3 ← L2 ← L1 lineage chain"
        >
          {meta.step === 'calls'
            ? `L3 ← L2 ← L1 ${expanded ? '▾' : '▸'}`
            : `L2 ← L1 ${expanded ? '▾' : '▸'}`}
        </button>
      )}

      {/* Expanded lineage panel — minimal: one row per upstream layer */}
      {expanded && (
        <div className="basis-full mt-1 ml-2 grid grid-cols-[auto_1fr] gap-x-2 gap-y-0.5 text-[10px]">
          {meta.themes_compute_run_id && (
            <>
              <span className="text-[var(--color-dim)]">L2 themes:</span>
              <span>
                run{' '}
                <button
                  type="button"
                  className="text-[var(--color-accent)] hover:underline"
                  onClick={() =>
                    onOpenRun
                      ? onOpenRun(meta.themes_compute_run_id!)
                      : copy(meta.themes_compute_run_id!, 'thrun')
                  }
                >
                  {shortHash(meta.themes_compute_run_id)}
                </button>{' '}
                · dep {shortHash(meta.themes_dep_hash)}{' '}
                <span
                  className="ml-1"
                  style={{
                    color: meta.themes_cache_hit
                      ? 'var(--color-green, #4caf50)'
                      : 'var(--color-amber, #ff9800)',
                  }}
                >
                  {meta.themes_cache_hit ? '· cached' : '· fresh'}
                </span>
              </span>
            </>
          )}
          {meta.obs_compute_run_id && (
            <>
              <span className="text-[var(--color-dim)]">L1 obs:</span>
              <span>
                run{' '}
                <button
                  type="button"
                  className="text-[var(--color-accent)] hover:underline"
                  onClick={() =>
                    onOpenRun
                      ? onOpenRun(meta.obs_compute_run_id!)
                      : copy(meta.obs_compute_run_id!, 'obrun')
                  }
                >
                  {shortHash(meta.obs_compute_run_id)}
                </button>{' '}
                · dep {shortHash(meta.obs_dep_hash)}{' '}
                <span
                  className="ml-1"
                  style={{
                    color: meta.obs_cache_hit
                      ? 'var(--color-green, #4caf50)'
                      : 'var(--color-amber, #ff9800)',
                  }}
                >
                  {meta.obs_cache_hit ? '· cached' : '· fresh'}
                </span>
              </span>
            </>
          )}
          {meta.code_git_sha && (
            <>
              <span className="text-[var(--color-dim)]">code:</span>
              <span title="git short SHA at uvicorn start">
                {meta.code_git_sha}
              </span>
            </>
          )}
        </div>
      )}
    </div>
  )
}
