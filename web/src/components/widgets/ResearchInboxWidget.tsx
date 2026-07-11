/**
 * ResearchInboxWidget — 🔬 研究收件箱.
 *
 * Surfaces the output of the research_loop machine: auto-generated
 * investment theses. These are written for off-book small caps
 * (SSP/LILA/MOBI/EFOR/FCBM…) that have NO ticker drawer, so a
 * per-ticker view can't reach them — this is a flat cross-ticker feed.
 *
 * Each row: ticker + conviction (parsed from body_md) + status +
 * created date. Click a row → expand the full thesis body_md rendered
 * with MiniMarkdown, in place. Additive home-tab panel; read-only.
 *
 * Reads useAllTheses() → GET /api/theses (no ticker = active set).
 */
import { useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { useAllTheses, type InvestmentThesis, type ThesisStatus } from '@/lib/api'
import { MiniMarkdown } from '@/components/widgets/MiniMarkdown'

// Conviction chip color (disciplined theses embed "**Conviction: MED**").
const CONVICTION_COLOR: Record<string, string> = {
  HIGH:   'var(--color-green)',
  MED:    'var(--color-amber,#e5a200)',
  MEDIUM: 'var(--color-amber,#e5a200)',
  LOW:    'var(--color-dim)',
}

// Status → short zh label + color.
const STATUS_META: Record<ThesisStatus, { label: string; color: string }> = {
  active:           { label: '活跃',   color: 'var(--color-green)' },
  requires_review:  { label: '待复核', color: 'var(--color-amber,#e5a200)' },
  invalidated:      { label: '已失效', color: 'var(--color-red)' },
  realized:         { label: '已兑现', color: 'var(--color-blue,#5fa8ff)' },
}

// Pull "Conviction: LOW/MED/HIGH" out of the disciplined-thesis body.
function parseConviction(md: string): string | null {
  const m = /Conviction:\s*(HIGH|MEDIUM|MED|LOW)/i.exec(md)
  return m ? m[1].toUpperCase() : null
}

function ThesisRow({
  t,
  expanded,
  onToggle,
}: {
  t: InvestmentThesis
  expanded: boolean
  onToggle: () => void
}) {
  const conviction = parseConviction(t.body_md)
  const status = STATUS_META[t.status] ?? { label: t.status, color: 'var(--color-dim)' }
  return (
    <div data-testid={`thesis-row-${t.ticker}`} className="py-0.5">
      <button
        onClick={onToggle}
        className="w-full text-left flex items-center gap-2 px-1 py-1 rounded hover:bg-[var(--color-accent)]/[0.06] transition"
      >
        <span className="text-[var(--color-dim)] flex-shrink-0">
          {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        </span>
        <span className="font-mono font-bold text-[11px] text-[var(--color-text)] w-14 flex-shrink-0">
          {t.ticker}
        </span>
        {conviction && (
          <span
            className="text-[8px] px-1.5 py-0.5 rounded border font-mono flex-shrink-0"
            style={{
              borderColor: CONVICTION_COLOR[conviction] ?? 'var(--color-dim)',
              color:       CONVICTION_COLOR[conviction] ?? 'var(--color-dim)',
            }}
          >
            {conviction}
          </span>
        )}
        <span
          className="text-[8px] px-1.5 py-0.5 rounded border font-mono flex-shrink-0"
          style={{ borderColor: status.color, color: status.color }}
        >
          {status.label}
        </span>
        <span className="ml-auto text-[8.5px] font-mono text-[var(--color-dim)] flex-shrink-0">
          {t.created_at.slice(0, 10)}
        </span>
      </button>
      {expanded && (
        <div className="mt-1 mb-1.5 ml-6 mr-1 px-2.5 py-2 rounded border border-[var(--color-border)] bg-[var(--color-bg)]/40 text-[10.5px] max-h-[55vh] overflow-y-auto">
          <MiniMarkdown text={t.body_md} />
        </div>
      )}
    </div>
  )
}

export function ResearchInboxWidget() {
  const q = useAllTheses()
  const [expanded, setExpanded] = useState<string | null>(null)
  const theses = q.data?.theses ?? []

  return (
    <div
      data-testid="research-inbox-widget"
      className="mb-3 rounded border border-[var(--color-border)] bg-[var(--color-panel)] p-2.5"
    >
      <div className="flex items-center gap-2 mb-2 text-[10px] text-[var(--color-dim)]">
        <span className="text-[var(--color-text)] flex items-center gap-1 font-semibold text-[11px]">
          🔬 研究收件箱
        </span>
        <span className="italic hidden sm:inline">
          · research_loop 自动生成的 thesis（含表外小盘）
        </span>
        {q.data && (
          <span className="ml-auto font-mono text-[9.5px]">{theses.length} theses</span>
        )}
      </div>

      {q.isLoading && (
        <div className="text-[10px] italic text-[var(--color-dim)] py-1">loading…</div>
      )}
      {q.isError && (
        <div className="text-[10px] text-[var(--color-red)] py-1">
          加载失败: {(q.error as Error).message.slice(0, 140)}
        </div>
      )}
      {!q.isLoading && !q.isError && theses.length === 0 && (
        <div className="text-[10px] italic text-[var(--color-dim)] py-1.5 leading-snug">
          暂无 thesis — research_loop 还没产出，或都已归档。
        </div>
      )}

      {theses.length > 0 && (
        <div className="flex flex-col divide-y divide-[var(--color-border)]/40">
          {theses.map((t) => (
            <ThesisRow
              key={t.thesis_id}
              t={t}
              expanded={expanded === t.thesis_id}
              onToggle={() => setExpanded(expanded === t.thesis_id ? null : t.thesis_id)}
            />
          ))}
        </div>
      )}
    </div>
  )
}
