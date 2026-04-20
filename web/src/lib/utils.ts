/** tiny class-name concat util (shadcn style, no external dep) */
export function cn(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(' ')
}

/** ts.slice(0, 19) + replace T with space */
export function fmtTs(ts: string | undefined | null): string {
  if (!ts) return ''
  return String(ts).slice(0, 19).replace('T', ' ')
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
