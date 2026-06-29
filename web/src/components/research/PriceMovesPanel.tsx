/**
 * PriceMovesPanel — Slice 1 visible surface: 今日异动 (today's price moves).
 *
 * Cross-source validated price (Finnhub real-time × yfinance cross-check), so
 * each move carries a confidence. This is an OBSERVATION layer feeding your
 * a→b→c→d→e — never a buy/sell signal ("今天跌了不构成卖出"). Click a ticker
 * to open its drawer and run your own read.
 */
import { TrendingUp, TrendingDown } from 'lucide-react'
import { usePriceMoves } from '@/lib/api'
import { todayLocal } from '@/lib/utils'

export function PriceMovesPanel({ onOpen }: { onOpen: (t: string) => void }) {
  const q = usePriceMoves(5)
  const d = q.data
  if (!d) return null

  return (
    <div className="rounded border border-[var(--color-border)] bg-[var(--color-panel)]/40 p-2.5 mb-3" data-testid="price-moves">
      <div className="flex items-center gap-1.5 mb-1.5">
        <span className="text-[12px] font-semibold text-[var(--color-text)]">📈 价格异动 · {todayLocal()}</span>
        <span className="text-[9px] italic text-[var(--color-dim)]">
          当日 |涨跌| ≥ {d.threshold_pct}% · Finnhub 实时(点开抽屉看交叉校验)· 观察,非买卖信号
        </span>
      </div>
      {d.moves.length === 0 && (
        <div className="text-[10px] italic text-[var(--color-dim)] py-0.5">{todayLocal()} 无 ≥{d.threshold_pct}% 异动</div>
      )}
      <div className="flex flex-wrap gap-1.5">
        {d.moves.map(m => {
          const up = m.day_change_pct >= 0
          const Icon = up ? TrendingUp : TrendingDown
          return (
            <button
              key={m.ticker}
              onClick={() => onOpen(m.ticker)}
              className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded border border-[var(--color-border)] hover:border-[var(--color-accent)]/60 text-[11px]"
              title={`现价 $${m.price}${m.move_since_review != null && !m.ref_stale ? ` · 自复盘 ${m.move_since_review}%` : ''}${m.confidence !== 'high' ? ` · 可信度 ${m.confidence}` : ''}`}
            >
              <span className="font-semibold text-[var(--color-text)]">{m.ticker}</span>
              <Icon size={11} className={up ? 'text-emerald-400' : 'text-red-400'} />
              <span className={up ? 'text-emerald-400' : 'text-red-400'}>
                {up ? '+' : ''}{m.day_change_pct}%
              </span>
              {m.confidence === 'low' && (
                <span className="text-[8px] text-amber-400/80" title="两源价格背离,存疑">⚠</span>
              )}
            </button>
          )
        })}
      </div>
      <div className="text-[9px] text-[var(--color-dim)] italic mt-1.5">
        EOD 历史截至 <b className="text-[var(--color-text)]">{d.eod_asof ?? '—'}</b>(每日 cron 自动刷新)· 今日涨跌为实时
        {d.eod_data_stale && <> · ⚠️ 部分"自复盘"基准滞后</>}
      </div>
    </div>
  )
}
