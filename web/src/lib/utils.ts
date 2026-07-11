/** tiny class-name concat util (shadcn style, no external dep) */
export function cn(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(' ')
}

/**
 * Render a UTC ISO timestamp in the user's LOCAL timezone (so every displayed
 * time matches the global header clock — DB stores UTC, we display local).
 * A pure date ("YYYY-MM-DD", no time) is returned as-is (TZ-shifting a bare
 * date would wrongly roll it a day). Unparseable input falls back to a slice.
 */
export function fmtTs(ts: string | undefined | null): string {
  if (!ts) return ''
  const s = String(ts)
  if (!s.includes('T') && !s.includes(':')) return s.slice(0, 10)  // date-only → leave alone
  const d = new Date(s)
  if (Number.isNaN(d.getTime())) return s.slice(0, 19).replace('T', ' ')
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

/** Current LOCAL date as YYYY-MM-DD (same TZ as the global clock). Use this
 * instead of the word "今天/Today" so a date is always explicit. */
export function todayLocal(): string {
  return new Date().toLocaleDateString('sv-SE')
}

export function fmtNum(v: unknown, digits = 2): string {
  if (v === null || v === undefined || v === '') return '—'
  const n = Number(v)
  if (!Number.isFinite(n)) return String(v)
  return n.toLocaleString(undefined, {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  })
}

export function fmtCap(v: number | null | undefined): string {
  if (v === null || v === undefined) return '—'
  if (v >= 1e12) return `¥${(v / 1e12).toFixed(2)} 万亿`
  if (v >= 1e8) return `¥${(v / 1e8).toFixed(1)} 亿`
  return `¥${v.toLocaleString()}`
}

/** Mask a brokerage account id for display: keep the leading letter + last 4,
 * mask the middle (so dogfood screenshots of the local dashboard don't leak the
 * full account number). "U12345678" → "U••••5678". Short ids (≤4) pass through. */
export function maskAccount(acct: string | number | null | undefined): string {
  if (acct === null || acct === undefined || acct === '') return '—'
  const s = String(acct)
  if (s.length <= 4) return s
  const head = /^[A-Za-z]/.test(s) ? s[0] : ''
  return `${head}••••${s.slice(-4)}`
}

export function fmtRelativeTime(iso: string | undefined): string {
  if (!iso) return ''
  const t = new Date(iso).getTime()
  if (!Number.isFinite(t)) return ''
  const secs = Math.round((Date.now() - t) / 1000)
  if (secs < 60) return `${secs}s ago`
  if (secs < 3600) return `${Math.round(secs / 60)}m ago`
  if (secs < 86400) return `${Math.round(secs / 3600)}h ago`
  return `${Math.round(secs / 86400)}d ago`
}
