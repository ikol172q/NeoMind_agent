/**
 * PortfolioWidget — Step F (#89) MMR diversified portfolio selection.
 *
 * Shows ONE most-recommended strategy + 3-8 alternatives that are
 * INTENTIONALLY DIFFERENT (different payoff_class / asset_class /
 * regime_sensitivity direction) so the user has real options
 * instead of a list of near-clones.
 *
 * Sits on the Strategies tab between RegimeFingerprintWidget and
 * the strategy cards.  When the user picks a date in AsOfPicker the
 * portfolio re-runs against that date's regime.
 */
import { useState } from 'react'
import { usePortfolioSelection, type PortfolioEntry } from '@/lib/api'


export interface PortfolioWidgetProps {
  asOf?: string                                                 // 'live' or YYYY-MM-DD
}


export function PortfolioWidget({ asOf }: PortfolioWidgetProps) {
  const [nAlts, setNAlts] = useState<number>(5)
  const [lambda, setLambda] = useState<number>(0.65)
  const q = usePortfolioSelection(asOf, nAlts, lambda)

  if (q.isLoading) {
    return (
      <div className="mb-3 rounded border border-[var(--color-border)] bg-[var(--color-bg)]/40 p-2.5 text-[10px] text-[var(--color-dim)]">
        loading portfolio…
      </div>
    )
  }
  if (q.isError || !q.data) {
    return (
      <div
        data-testid="portfolio-widget-error"
        className="mb-3 rounded border border-[var(--color-amber,#e5a200)]/40 bg-[var(--color-amber,#e5a200)]/[0.05] p-2 text-[10px] text-[var(--color-dim)]"
      >
        ⚠ portfolio 不可用（regime fingerprint 缺失或 backfill 未跑）
      </div>
    )
  }

  const portfolio = q.data
  const top = portfolio.top
  if (!top) {
    return null
  }

  return (
    <div
      data-testid="portfolio-widget"
      className="mb-3 rounded border border-[var(--color-accent)]/40 bg-[var(--color-accent)]/[0.04] p-3"
    >
      <div className="flex items-center gap-2 mb-2 text-[10px] text-[var(--color-dim)]">
        <span className="font-semibold text-[var(--color-text)]">
          🏆 今日最推荐 + 替代方案 / Top + Alternatives (MMR)
        </span>
        <span className="font-mono">{portfolio.fingerprint_date}</span>
        <span>·</span>
        <span>method: {portfolio.selection_method}</span>
        <span>·</span>
        <span>λ={portfolio.lambda.toFixed(2)}</span>
        <div className="ml-auto flex items-center gap-2">
          <label className="flex items-center gap-1">
            <span>n=</span>
            <select
              data-testid="portfolio-n-alts"
              value={nAlts}
              onChange={(e) => setNAlts(parseInt(e.target.value))}
              className="bg-[var(--color-panel)] border border-[var(--color-border)] rounded px-1 py-0.5 text-[10px]"
            >
              {[3, 4, 5, 6, 7, 8].map((n) => (
                <option key={n} value={n}>{n}</option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-1">
            <span>λ=</span>
            <select
              data-testid="portfolio-lambda"
              value={lambda}
              onChange={(e) => setLambda(parseFloat(e.target.value))}
              className="bg-[var(--color-panel)] border border-[var(--color-border)] rounded px-1 py-0.5 text-[10px]"
            >
              <option value={0.85}>0.85 偏相关</option>
              <option value={0.65}>0.65 平衡</option>
              <option value={0.45}>0.45 偏多样</option>
            </select>
          </label>
        </div>
      </div>

      {/* TOP — most recommended */}
      <div
        data-testid="portfolio-top"
        className="mb-2.5 px-2.5 py-2 rounded bg-[var(--color-panel)] border border-[var(--color-accent)]/60"
      >
        <div className="flex items-center gap-2 mb-1">
          <span className="text-[9px] uppercase tracking-wider text-[var(--color-dim)]">最推荐 / TOP</span>
          <span className="text-[var(--color-text)] font-semibold">
            {top.name_zh ?? top.name_en ?? top.strategy_id}
          </span>
          <span className="text-[8.5px] text-[var(--color-dim)] font-mono">
            ({top.strategy_id})
          </span>
          <span className="ml-auto text-[10px] font-mono text-[var(--color-green)]">
            fit {top.score.toFixed(2)}/10
          </span>
        </div>
        <div className="flex flex-wrap gap-1.5 text-[9px] text-[var(--color-dim)]">
          {top.horizon && <span className="px-1.5 py-0.5 rounded border border-[var(--color-border)]">{top.horizon}</span>}
          {top.asset_class && <span className="px-1.5 py-0.5 rounded border border-[var(--color-border)]">{top.asset_class}</span>}
          {top.difficulty && <span>{'★'.repeat(top.difficulty)}{'☆'.repeat(5 - top.difficulty)}</span>}
          <span className="px-1.5 py-0.5 rounded border border-[var(--color-border)]">formula: {top.formula ?? 'unknown'}</span>
        </div>
      </div>

      {/* ALTERNATIVES — by MMR */}
      <div className="text-[9px] uppercase tracking-wider text-[var(--color-dim)] mb-1">
        替代方案 / Alternatives ({portfolio.alternatives.length})
        <span className="ml-2 normal-case tracking-normal text-[8.5px] italic">
          (按 MMR 排序 — 与 TOP 不同 payoff_class / asset_class / regime 方向)
        </span>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-1.5">
        {portfolio.alternatives.map((alt: PortfolioEntry, idx: number) => (
          <div
            key={alt.strategy_id}
            data-testid={`portfolio-alt-${alt.strategy_id}`}
            className="px-2 py-1.5 rounded bg-[var(--color-panel)]/70 border border-[var(--color-border)] hover:border-[var(--color-accent)]/40 transition"
          >
            <div className="flex items-center gap-1.5">
              <span className="text-[8.5px] text-[var(--color-dim)] font-mono w-3.5">
                #{idx + 2}
              </span>
              <span className="text-[10px] text-[var(--color-text)] font-medium truncate">
                {alt.name_zh ?? alt.name_en ?? alt.strategy_id}
              </span>
              <span className="ml-auto text-[9.5px] font-mono text-[var(--color-text)]">
                {alt.score.toFixed(2)}
              </span>
            </div>
            <div className="flex items-center gap-2 text-[8.5px] text-[var(--color-dim)] mt-0.5">
              {alt._diversity_from_top != null && (
                <span title="Diversity from TOP — higher means more different">
                  div: {(alt._diversity_from_top * 100).toFixed(0)}%
                </span>
              )}
              {alt._mmr_score != null && (
                <span title="MMR score = λ × relevance − (1−λ) × similarity">
                  mmr: {alt._mmr_score.toFixed(3)}
                </span>
              )}
              {alt.horizon && <span>· {alt.horizon}</span>}
              {alt.asset_class && <span>· {alt.asset_class}</span>}
            </div>
          </div>
        ))}
      </div>

      <div className="mt-2 text-[8.5px] text-[var(--color-dim)] italic leading-[1.4]">
        MMR (Maximal Marginal Relevance) 把 fit score 和"和 TOP 的差异度"加权混合。
        λ 越高越偏向"高分但相似"的候选；λ 越低越偏向"中等高分但更多样"的候选。
        diversity = 1 − similarity(候选, TOP)。
        <span className="font-mono">
          {' '}考察了 {portfolio.n_candidates_considered ?? '?'} 个候选。
        </span>
      </div>
    </div>
  )
}
