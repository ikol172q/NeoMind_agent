/**
 * AgentSummary — renders the NeoMind fin agent's grounded 3-sentence read
 * (优势 / 劣势 / 综合) for a ticker. The text is SYNTHESIZED from already-
 * verified+dated inputs (diagnostic chain + 10-K facts + holders + 13F +
 * thesis) and number-gated server-side, so nothing here is unsourced. The
 * footer lists each data source with its as-of date (freshness).
 *
 * AgentPlaceholder — a marker dropped at dashboard spots that WANT an LLM
 * summary but whose context engine isn't wired yet (portfolio / news / …).
 */
import { Bot, RefreshCw, Loader2 } from 'lucide-react'
import { useAgentSynthesis, useRefreshAgentSynthesis } from '@/lib/api'
import { fmtTs } from '@/lib/utils'

export function AgentSummary({ ticker }: { ticker: string }) {
  const q = useAgentSynthesis(ticker)
  const refresh = useRefreshAgentSynthesis()
  const d = q.data
  const loading = q.isLoading || refresh.isPending
  const has = !!(d && (d.advantage || d.disadvantage || d.synthesis))
  const refreshFailed = refresh.isError && !refresh.isPending

  return (
    <div className="rounded border border-cyan-500/30 bg-cyan-500/[0.04] p-2.5 mb-3" data-testid="agent-summary">
      <div className="flex items-center gap-1.5 mb-1">
        <Bot size={13} className="text-cyan-300" />
        <span className="text-[12px] font-semibold text-cyan-200">🤖 NeoMind 速读</span>
        <span className="text-[9px] italic text-[var(--color-dim)]">优势 · 劣势 · 综合 · 仅由已验证数据合成</span>
        <button
          onClick={() => refresh.mutate(ticker)}
          disabled={loading}
          className="ml-auto text-[10px] px-1.5 py-0.5 rounded border border-cyan-500/40 text-cyan-300 hover:bg-cyan-500/10 disabled:opacity-50 inline-flex items-center gap-1"
          title="后台用 LLM 重新合成(只允许引用已验证数据)"
        >
          {loading ? <Loader2 size={10} className="animate-spin" /> : <RefreshCw size={10} />} 刷新
        </button>
      </div>

      {loading && !has && (
        <div className="text-[10px] italic text-[var(--color-dim)] py-1">生成中… (后台合成,首次稍慢)</div>
      )}
      {refreshFailed && (
        <div className="text-[10px] text-amber-400/90 py-1">
          ⚠️ 刷新失败 (LLM router 繁忙) — 已保留上次结果,稍后再点刷新
        </div>
      )}
      {!loading && !has && (
        <div className="text-[10px] italic text-[var(--color-dim)] py-1">
          数据不足,暂不合成 —— 需先有基本面 / 10-K 抽取 / 认知。宁可留空也不编。
        </div>
      )}
      {has && d && (
        <div className="space-y-1 text-[11px] leading-snug">
          {d.advantage && <div><span className="text-emerald-400 font-semibold mr-1">优势</span>{d.advantage}</div>}
          {d.disadvantage && <div><span className="text-amber-400 font-semibold mr-1">劣势</span>{d.disadvantage}</div>}
          {d.synthesis && <div><span className="text-cyan-300 font-semibold mr-1">综合</span>{d.synthesis}</div>}
          <div className="text-[9px] text-[var(--color-dim)] pt-1 border-t border-[var(--color-border)]/30 mt-1">
            来源:{' '}
            {d.sources.length === 0 ? '—' : d.sources.map((s, i) => (
              <span key={i}>
                {i > 0 && ' / '}
                {s.url
                  ? <a href={s.url} target="_blank" rel="noopener noreferrer"
                      className="text-cyan-400 hover:text-cyan-300 underline decoration-dotted">{s.source}·{s.asof}</a>
                  : <span>{s.source}·{s.asof}</span>}
              </span>
            ))}
            {d.generated_at && <> · 生成 {fmtTs(d.generated_at)}</>}
          </div>
        </div>
      )}
    </div>
  )
}

export function AgentPlaceholder({ label }: { label: string }) {
  return (
    <div className="rounded border border-dashed border-cyan-500/25 bg-cyan-500/[0.025] px-2 py-1.5 mb-2 text-[10px] text-[var(--color-dim)] flex items-center gap-1.5">
      <Bot size={12} className="text-cyan-400/60 flex-shrink-0" />
      <span>🤖 NeoMind 分析 · {label}</span>
      <span className="italic ml-auto">待接入 (占位)</span>
    </div>
  )
}
