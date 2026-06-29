/**
 * ThesisReviewBanner — Goal 2: evidence-driven review trigger.
 *
 * Compares NEW SEC events (since you last reviewed) against THIS holding's
 * thesis and says whether they confirm / weaken / break it — and which
 * 投资理念 element (L0 下行 / L1 a-e) they touch. It is a REPORTER, not a
 * decider: the only "action" it implies is "该复盘 — 跑一遍 a→b→c→d→e".
 * It never recommends buy/sell and never comments on position size.
 *
 * Loud only when 破/动摇 (something needs your attention). Quiet otherwise.
 */
import { AlertTriangle, RefreshCw, Loader2, CheckCircle2 } from 'lucide-react'
import { useThesisReview, useRefreshThesisReview } from '@/lib/api'

const CLS_STYLE: Record<string, string> = {
  '破':   'text-red-400',
  '动摇': 'text-amber-400',
  '印证': 'text-emerald-400',
  '无关': 'text-[var(--color-dim)]',
}

export function ThesisReviewBanner({ ticker }: { ticker: string }) {
  const q = useThesisReview(ticker)
  const refresh = useRefreshThesisReview()
  const d = q.data
  const loading = q.isLoading || refresh.isPending
  const verdict = d?.verdict
  const loud = verdict === '破' || verdict === '动摇'
  // material items only (skip 无关 in the list)
  const items = (d?.items ?? []).filter(it => it.classification !== '无关')

  // nothing to show pre-load / no thesis
  if (!d && !loading) return null
  if (d && d.status === 'no_thesis') return null

  const tone = loud
    ? 'border-amber-500/40 bg-amber-500/[0.06]'
    : 'border-[var(--color-border)] bg-[var(--color-panel)]/40'

  return (
    <div className={`rounded border ${tone} p-2.5 mb-3`} data-testid="thesis-review">
      <div className="flex items-center gap-1.5 mb-1">
        {loud
          ? <AlertTriangle size={13} className="text-amber-400" />
          : <CheckCircle2 size={13} className="text-emerald-500/70" />}
        <span className="text-[12px] font-semibold text-[var(--color-text)]">
          {loud ? `⚠️ 该复盘 · 新证据${verdict}了你的论点` : '✓ 论点暂稳 · 自上次复盘无 material 新证据'}
        </span>
        <button
          onClick={() => refresh.mutate(ticker)}
          disabled={loading}
          className="ml-auto text-[10px] px-1.5 py-0.5 rounded border border-[var(--color-border)] text-[var(--color-dim)] hover:text-[var(--color-text)] disabled:opacity-50 inline-flex items-center gap-1"
          title="重新比对最新 SEC 事件 vs 论点"
        >
          {loading ? <Loader2 size={10} className="animate-spin" /> : <RefreshCw size={10} />} 刷新
        </button>
      </div>

      {loud && items.length > 0 && (
        <div className="space-y-1 text-[11px] leading-snug mt-1">
          {items.map((it, i) => (
            <div key={i} className="flex gap-1.5">
              <span className={`font-semibold ${CLS_STYLE[it.classification] ?? ''}`}>{it.classification}</span>
              {it.touches && it.touches !== '—' && (
                <span className="text-[9px] px-1 rounded bg-[var(--color-border)]/40 text-[var(--color-dim)] self-center">{it.touches}</span>
              )}
              <span className="text-[var(--color-text)]">{it.ref}</span>
              <span className="text-[var(--color-dim)]">— {it.why}</span>
            </div>
          ))}
        </div>
      )}

      <div className="text-[9px] text-[var(--color-dim)] italic pt-1 mt-1 border-t border-[var(--color-border)]/30">
        只提示「该复盘」,不替你做决定 —— 看到后请自己跑 a→b→c→d→e。不构成买卖建议。
        {d?.anchor_at && <> · 对比基准 {d.anchor_at.slice(0, 10)}(上次复盘)</>}
      </div>
    </div>
  )
}
