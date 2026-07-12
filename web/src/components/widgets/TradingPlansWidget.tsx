/**
 * TradingPlansWidget — 📋 交易计划.
 *
 * Read-only surfacing of ~/trading_plans/*.md (discipline cards +
 * event checklists) on the home tab. The plans already existed as
 * files + an API, but had no UI — this lists them and opens the full
 * markdown in a modal.
 *
 * List  → useTradingPlans()  (metadata only)
 * Detail→ useTradingPlan(name) (full content, fetched on open)
 */
import { useEffect, useState } from 'react'
import { FileText, X, ChevronDown, ChevronRight } from 'lucide-react'
import { useTradingPlans, useTradingPlan } from '@/lib/api'
import { FreshnessChip } from './FreshnessChip'
import { MiniMarkdown } from '@/components/widgets/MiniMarkdown'
import { useCollapsed } from '@/lib/useCollapsed'

function TradingPlanModal({ name, onClose }: { name: string; onClose: () => void }) {
  const q = useTradingPlan(name)

  // ESC closes — consistent with the app's other modals.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <>
      <div className="fixed inset-0 bg-black/50 z-40" onClick={onClose} />
      <div
        data-testid="trading-plan-modal"
        className="fixed top-[5vh] left-1/2 -translate-x-1/2 w-[760px] max-w-[92vw] bg-[var(--color-bg)] border border-[var(--color-border)] rounded shadow-2xl z-50 flex flex-col"
        style={{ maxHeight: '90dvh' }}
      >
        <div className="flex items-start gap-3 px-4 py-3 border-b border-[var(--color-border)] bg-[var(--color-panel)]/60">
          <FileText size={16} className="text-[var(--color-accent)] mt-0.5 flex-shrink-0" />
          <div className="flex-1 min-w-0">
            <h2 className="text-[14px] font-semibold truncate">{q.data?.title ?? name}</h2>
            <div className="text-[10px] text-[var(--color-dim)] mt-0.5 font-mono truncate">
              {name}
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-[var(--color-dim)] hover:text-[var(--color-text)] p-1 flex-shrink-0"
          >
            <X size={16} />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto px-4 py-3 text-[11px]">
          {q.isLoading && <div className="italic text-[var(--color-dim)]">loading…</div>}
          {q.isError && (
            <div className="text-[var(--color-red)]">
              加载失败: {(q.error as Error).message.slice(0, 160)}
            </div>
          )}
          {q.data && <MiniMarkdown text={q.data.content} />}
        </div>
      </div>
    </>
  )
}

export function TradingPlansWidget() {
  const q = useTradingPlans()
  const [openName, setOpenName] = useState<string | null>(null)
  const [collapsed, toggle] = useCollapsed('trading-plans')
  const plans = q.data?.plans ?? []

  return (
    <div
      data-testid="trading-plans-widget"
      className="mb-3 rounded border border-[var(--color-border)] bg-[var(--color-panel)] p-2.5"
    >
      <div className="flex items-center gap-2 mb-2 text-[10px] text-[var(--color-dim)]">
        <button
          onClick={toggle}
          title={collapsed ? '展开' : '折叠'}
          className="flex items-center gap-1 text-[var(--color-text)] font-semibold text-[11px] hover:opacity-80"
        >
          {collapsed ? <ChevronRight size={12} /> : <ChevronDown size={12} />}
          📋 交易计划
        </button>
        <span className="italic hidden sm:inline">
          · ~/trading_plans 里的纪律卡 / 事件计划
        </span>
        <span className="ml-auto flex items-center gap-2">
          <FreshnessChip updatedAt={q.dataUpdatedAt} isFetching={q.isFetching} isError={q.isError} staleAfterMin={30} />
          {q.data && <span className="font-mono text-[9.5px]">{plans.length} plans</span>}
        </span>
      </div>

      {!collapsed && (<>
      {q.isLoading && (
        <div className="text-[10px] italic text-[var(--color-dim)] py-1">loading…</div>
      )}
      {q.isError && (
        <div className="text-[10px] text-[var(--color-red)] py-1">
          加载失败: {(q.error as Error).message.slice(0, 140)}
        </div>
      )}
      {!q.isLoading && !q.isError && plans.length === 0 && (
        <div className="text-[10px] italic text-[var(--color-dim)] py-1.5 leading-snug">
          {q.data?.note ?? '暂无交易计划 — ~/trading_plans 为空。'}
        </div>
      )}

      {plans.length > 0 && (
        <div className="flex flex-col gap-0.5">
          {plans.map((p) => (
            <button
              key={p.filename}
              data-testid={`trading-plan-row-${p.filename}`}
              onClick={() => setOpenName(p.filename)}
              className="w-full text-left flex items-center gap-2 px-1.5 py-1 rounded hover:bg-[var(--color-accent)]/[0.06] transition"
            >
              <FileText size={12} className="text-[var(--color-dim)] flex-shrink-0" />
              <span className="text-[11px] text-[var(--color-text)] truncate flex-1 min-w-0">
                {p.title ?? p.filename}
              </span>
              <span className="text-[8.5px] font-mono text-[var(--color-dim)] flex-shrink-0">
                {p.mtime.slice(0, 10)} · {(p.size / 1024).toFixed(1)}k
              </span>
            </button>
          ))}
        </div>
      )}
      </>)}

      {openName && <TradingPlanModal name={openName} onClose={() => setOpenName(null)} />}
    </div>
  )
}
