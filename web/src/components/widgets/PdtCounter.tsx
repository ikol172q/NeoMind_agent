/**
 * PdtCounter — header pill showing the FINRA Pattern Day Trader
 * round-trip count over the rolling 5-business-day window.
 *
 * Reads from /api/db/health.counts.pdt_round_trips (which is total
 * across history) — V1. A more accurate reading would need a
 * window-aware endpoint (TODO: add /api/compliance/pdt to surface
 * the same data compute_pdt_status produces). Once that lands, swap
 * the data source and the badge becomes properly time-windowed.
 *
 * The pill colour is informational only (we never block trades; the
 * brokerage's own PDT enforcement is the actual bound). The user is
 * responsible for not using >3 round-trips in 5 business days while
 * <$25k account equity.
 */
import { AlertTriangle, Clock } from 'lucide-react'
import { useFinDbHealth } from '@/lib/api'

const PDT_LIMIT = 3

export function PdtCounter() {
  const q = useFinDbHealth()
  if (!q.data) return null
  const total = q.data.counts.pdt_round_trips ?? 0

  // Placeholder: total recorded round-trips, not windowed. See
  // module docstring — we'll switch to window-aware once the
  // /api/compliance/pdt endpoint lands.
  const used = total
  const remaining = Math.max(0, PDT_LIMIT - used)
  const danger = used >= PDT_LIMIT
  const warn = used >= PDT_LIMIT - 1

  const color = danger
    ? 'var(--color-red)'
    : warn
      ? 'var(--color-amber,#e5a200)'
      : 'var(--color-green)'
  const Icon = danger ? AlertTriangle : Clock

  return (
    <div
      data-testid="pdt-counter"
      data-pdt-status={danger ? 'breach' : warn ? 'warn' : 'ok'}
      data-source="GET /api/db/health → counts.pdt_round_trips"
      className="inline-flex items-center gap-1 px-2 py-0.5 rounded border text-[10px] font-mono"
      style={{ borderColor: color, color }}
      title={
        danger
          ? `PDT: ${used}/${PDT_LIMIT} round-trips logged. <$25k accounts cannot exceed 3 day trades in 5 business days.`
          : `PDT: ${used}/${PDT_LIMIT} round-trips logged (${remaining} headroom). The 5-business-day rolling window applies on accounts <$25k.`
      }
    >
      <Icon size={10} />
      <span>
        PDT {used}/{PDT_LIMIT}
      </span>
    </div>
  )
}
