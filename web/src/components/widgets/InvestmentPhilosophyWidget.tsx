/**
 * InvestmentPhilosophyWidget — your "Ulysses contract".
 *
 * Industry-standard Investment Policy Statement (IPS) adapted for an
 * individual concentrated investor. Designed to be:
 *   · READABLE in 5 minutes when emotion runs hot
 *   · EDITABLE incrementally (every save = new version)
 *   · ANCHOR for self — agent references it when discussing trades
 *
 * Layout (Buffett's "Owner's Manual" + Marks memo + Dalio Principles):
 *   📜 v1.X · last reviewed YYYY-MM-DD · [edit] [history]
 *   ──────────────────────────────────────
 *   🌟 NORTH STAR  (always visible — 1 sentence)
 *   👤 Identity                   [collapsible]
 *   💡 Core Beliefs (N axioms)    [collapsible]
 *   🎯 Circle of Competence       [collapsible]
 *   ⏰ Time Horizon + Sizing       [collapsible]
 *   ➕ Entry Rules                 [collapsible]
 *   ➖ Exit Rules                  [collapsible]
 *   🛡️ Hedge & Risk Plan           [collapsible]
 *   ⚖️ Disagreement Protocol       [collapsible]
 */
import { useState, useEffect } from 'react'
import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query'
import {
  Compass, Edit3, Save, X, ChevronDown, ChevronRight,
  AlertTriangle, RotateCw,
} from 'lucide-react'

interface Philosophy {
  version?:               string
  north_star?:            string
  identity?:              string
  beliefs?:               Array<{ claim: string; why?: string; falsified_if?: string }>
  beliefs_json?:          string
  circle_competence?:     string
  time_horizon?:          string
  sizing_rules?:          Record<string, unknown>
  sizing_rules_json?:     string
  entry_rules?:           string
  exit_rules?:            string
  hedge_plan?:            string
  disagreement_protocol?: string
  review_cadence?:        string
  last_reviewed_at?:      string
  change_note?:           string
  updated_at?:            string
}


function usePhilosophy() {
  return useQuery<Philosophy>({
    queryKey: ['philosophy'],
    queryFn:  () => fetch('/api/philosophy').then(r => r.json()),
    staleTime: 60_000,
  })
}


function useUpdatePhilosophy() {
  const qc = useQueryClient()
  return useMutation<Philosophy, Error, Partial<Philosophy> & { change_note?: string }>({
    mutationFn: (body) => fetch('/api/philosophy', {
      method:  'PUT',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(body),
    }).then(r => r.json()),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['philosophy'] }),
  })
}


function useTouchReview() {
  const qc = useQueryClient()
  return useMutation<Philosophy, Error, void>({
    mutationFn: () => fetch('/api/philosophy/touch_review', {
      method: 'POST',
    }).then(r => r.json()),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['philosophy'] }),
  })
}


function daysSince(iso?: string): number | null {
  if (!iso) return null
  const t = Date.parse(iso)
  if (isNaN(t)) return null
  return Math.floor((Date.now() - t) / 86400000)
}


export function InvestmentPhilosophyWidget() {
  const q = usePhilosophy()
  const touchMu = useTouchReview()
  const [collapsed, setCollapsed] = useState<boolean>(() =>
    typeof window !== 'undefined'
      && localStorage.getItem('strategies.philosophy.collapsed') === '1'
  )
  const [openSections, setOpenSections] = useState<Set<string>>(new Set())
  const [editing, setEditing] = useState<string | null>(null)

  function toggle() {
    const next = !collapsed
    setCollapsed(next)
    try { localStorage.setItem('strategies.philosophy.collapsed', next ? '1' : '0') } catch {}
  }

  function toggleSection(k: string) {
    const next = new Set(openSections)
    if (next.has(k)) next.delete(k); else next.add(k)
    setOpenSections(next)
  }

  const p: Philosophy = q.data || {}
  const daysReviewed = daysSince(p.last_reviewed_at)
  const reviewStale = daysReviewed != null && daysReviewed > 30

  return (
    <div
      data-testid="investment-philosophy-widget"
      className="mb-3 rounded border border-[var(--color-border)] bg-[var(--color-panel)]/60"
    >
      {/* Header — always visible */}
      <button
        onClick={toggle}
        className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-[var(--color-border)]/20 group"
      >
        {collapsed
          ? <ChevronRight size={14} className="text-[var(--color-dim)]" />
          : <ChevronDown size={14} className="text-[var(--color-dim)]" />}
        <Compass size={14} className="text-amber-300 flex-shrink-0" />
        <span className="text-[12px] font-semibold text-[var(--color-text)] flex-shrink-0">
          📜 投资理念
        </span>
        <span className="text-[10px] text-[var(--color-dim)] italic">
          · Ulysses contract · 防自己冲动 · 每月 review
        </span>
        <span className="ml-auto flex items-center gap-2 text-[10px]">
          <span className="text-[var(--color-dim)] font-mono">{p.version || 'v0'}</span>
          {p.last_reviewed_at && (
            <span className={reviewStale ? 'text-amber-300 flex items-center gap-1' : 'text-[var(--color-dim)]'}>
              {reviewStale && <AlertTriangle size={10} />}
              复盘 {daysReviewed}d 前
            </span>
          )}
        </span>
      </button>

      {!collapsed && (
        <div className="px-3 pb-3 space-y-3 text-[11px]">
          {/* NORTH STAR — always front and center */}
          {p.north_star && (
            <div className="rounded border border-amber-500/30 bg-amber-500/5 p-2.5">
              <div className="text-[9px] uppercase tracking-wider text-amber-300/80 mb-1 flex items-center gap-1">
                🌟 NORTH STAR — 1 句话不能丢
              </div>
              <div className="text-[13px] text-[var(--color-text)] font-medium leading-relaxed">
                {p.north_star}
              </div>
            </div>
          )}

          {/* Quick-actions row */}
          <div className="flex items-center gap-2 text-[10px]">
            <button
              onClick={() => touchMu.mutate()}
              disabled={touchMu.isPending}
              className="px-2 py-1 rounded border border-[var(--color-accent)]/40 text-[var(--color-accent)] hover:bg-[var(--color-accent)]/10 flex items-center gap-1 disabled:opacity-50"
              title="标记今天为'已复盘', 不改任何内容"
              data-testid="philosophy-touch-review"
            >
              <RotateCw size={10} /> 今日已 review
            </button>
            <span className="text-[var(--color-dim)] italic">
              · {p.review_cadence || 'monthly'} cadence · 每次 edit 自动 bump version
            </span>
          </div>

          {/* Collapsible sections */}
          <Section title="👤 Identity — 我是什么 investor"
                   k="identity" openSections={openSections} toggle={toggleSection}>
            <Markdown text={p.identity} />
          </Section>

          <Section title={`💡 Core Beliefs — ${(p.beliefs?.length ?? 0)} axioms 我在 bet 的`}
                   k="beliefs" openSections={openSections} toggle={toggleSection}>
            <BeliefsList beliefs={p.beliefs} />
          </Section>

          <Section title="🎯 Circle of Competence — 我会做 / 不会做"
                   k="circle" openSections={openSections} toggle={toggleSection}>
            <Markdown text={p.circle_competence} />
          </Section>

          <Section title="⏰ Time Horizon + 仓位规则"
                   k="sizing" openSections={openSections} toggle={toggleSection}>
            <Markdown text={p.time_horizon} />
            {p.sizing_rules && (
              <SizingRulesGrid rules={p.sizing_rules as Record<string, unknown>} />
            )}
          </Section>

          <Section title="➕ Entry Rules — 什么情况下买入"
                   k="entry" openSections={openSections} toggle={toggleSection}>
            <Markdown text={p.entry_rules} />
          </Section>

          <Section title="➖ Exit Rules — 什么情况下卖出"
                   k="exit" openSections={openSections} toggle={toggleSection}>
            <Markdown text={p.exit_rules} />
          </Section>

          <Section title="🛡️ Hedge & Risk Plan — 主线失败怎么办"
                   k="hedge" openSections={openSections} toggle={toggleSection}>
            <Markdown text={p.hedge_plan} />
          </Section>

          <Section title="⚖️ Disagreement Protocol — 跟 smart money 反向时"
                   k="disagree" openSections={openSections} toggle={toggleSection}>
            <Markdown text={p.disagreement_protocol} />
          </Section>

          {/* Edit / version footer */}
          <div className="flex items-center justify-between pt-2 border-t border-[var(--color-border)]/40 text-[9px] text-[var(--color-dim)]">
            <span>{p.version} · 上次保存 {p.updated_at?.slice(0, 10)} · {p.change_note}</span>
            <button
              onClick={() => setEditing('all')}
              className="hover:text-[var(--color-text)] flex items-center gap-1"
              data-testid="philosophy-edit"
            >
              <Edit3 size={10} /> 编辑 (打开完整 IPS 文档)
            </button>
          </div>
        </div>
      )}

      {editing && (
        <EditModal philosophy={p} onClose={() => setEditing(null)} />
      )}
    </div>
  )
}


function Section({ title, k, openSections, toggle, children }: {
  title: string; k: string;
  openSections: Set<string>;
  toggle: (k: string) => void;
  children: React.ReactNode
}) {
  const isOpen = openSections.has(k)
  return (
    <div className="rounded border border-[var(--color-border)]/40">
      <button
        onClick={() => toggle(k)}
        className="w-full flex items-center gap-2 px-2 py-1.5 text-left hover:bg-[var(--color-border)]/10"
      >
        {isOpen
          ? <ChevronDown size={11} className="text-[var(--color-dim)]" />
          : <ChevronRight size={11} className="text-[var(--color-dim)]" />}
        <span className="text-[11px] font-semibold text-[var(--color-text)]">{title}</span>
      </button>
      {isOpen && (
        <div className="px-3 pb-2.5 pt-1 text-[var(--color-text)]/85">
          {children}
        </div>
      )}
    </div>
  )
}


function Markdown({ text }: { text?: string }) {
  if (!text) return <span className="italic text-[var(--color-dim)]">(空 — 点编辑添加)</span>
  // Minimal markdown rendering: line breaks + bold (**...**) + bullets
  const lines = text.split('\n')
  return (
    <div className="space-y-1 leading-relaxed">
      {lines.map((line, i) => {
        if (!line.trim()) return <div key={i} className="h-1" />
        if (line.startsWith('**') && line.endsWith('**')) {
          return <div key={i} className="font-semibold text-[var(--color-text)] mt-1">{line.slice(2, -2)}</div>
        }
        if (/^[-•]/.test(line.trim())) {
          return <div key={i} className="pl-4 -indent-3">· {line.replace(/^[-•]\s*/, '')}</div>
        }
        // Inline bold conversion
        const segments = line.split(/(\*\*[^*]+\*\*)/g)
        return (
          <div key={i}>
            {segments.map((seg, j) =>
              seg.startsWith('**') && seg.endsWith('**')
                ? <span key={j} className="font-semibold text-[var(--color-text)]">{seg.slice(2, -2)}</span>
                : <span key={j}>{seg}</span>
            )}
          </div>
        )
      })}
    </div>
  )
}


function BeliefsList({ beliefs }: { beliefs?: Array<{ claim: string; why?: string; falsified_if?: string }> }) {
  if (!beliefs || !beliefs.length) {
    return <span className="italic text-[var(--color-dim)]">(空)</span>
  }
  return (
    <div className="space-y-2">
      {beliefs.map((b, i) => (
        <div key={i} className="rounded border border-[var(--color-border)]/30 p-2 bg-[var(--color-bg)]/30">
          <div className="text-[11px] font-semibold text-[var(--color-text)]">
            #{i + 1} {b.claim}
          </div>
          {b.why && (
            <div className="text-[10px] text-[var(--color-dim)] mt-1">
              <span className="text-[var(--color-text)]/60">why:</span> {b.why}
            </div>
          )}
          {b.falsified_if && (
            <div className="text-[10px] text-amber-300/80 mt-1">
              <span className="text-amber-300">falsified if:</span> {b.falsified_if}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}


function SizingRulesGrid({ rules }: { rules: Record<string, unknown> }) {
  const entries = Object.entries(rules)
  if (!entries.length) return null
  return (
    <div className="mt-2 grid grid-cols-2 gap-1 text-[10px]">
      {entries.map(([k, v]) => {
        if (k === 'notes') {
          return (
            <div key={k} className="col-span-2 mt-1 italic text-amber-300/70">
              📝 {String(v)}
            </div>
          )
        }
        const v_str = typeof v === 'number' && k.endsWith('_pct')
          ? `${(v * 100).toFixed(0)}%`
          : String(v)
        return (
          <div key={k} className="flex items-center justify-between border-b border-[var(--color-border)]/30 py-0.5">
            <span className="text-[var(--color-dim)]">{k.replace(/_/g, ' ')}</span>
            <span className="font-mono text-[var(--color-text)]">{v_str}</span>
          </div>
        )
      })}
    </div>
  )
}


function EditModal({ philosophy, onClose }: { philosophy: Philosophy; onClose: () => void }) {
  const updateMu = useUpdatePhilosophy()
  // ESC closes modal (consistent with whale drawer + stock drawer)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  const [draft, setDraft] = useState({
    north_star:            philosophy.north_star ?? '',
    identity:              philosophy.identity ?? '',
    circle_competence:     philosophy.circle_competence ?? '',
    time_horizon:          philosophy.time_horizon ?? '',
    entry_rules:           philosophy.entry_rules ?? '',
    exit_rules:            philosophy.exit_rules ?? '',
    hedge_plan:            philosophy.hedge_plan ?? '',
    disagreement_protocol: philosophy.disagreement_protocol ?? '',
  })
  const [changeNote, setChangeNote] = useState('')

  function save() {
    updateMu.mutate(
      { ...draft, change_note: changeNote || '编辑' },
      { onSuccess: () => onClose() },
    )
  }

  return (
    <>
      <div className="fixed inset-0 bg-black/50 z-40" onClick={onClose} />
      <div className="fixed top-[5vh] left-1/2 -translate-x-1/2 w-[760px] max-w-[92vw] bg-[var(--color-bg)] border border-[var(--color-border)] rounded shadow-2xl z-50 flex flex-col"
           style={{ maxHeight: '90dvh' }}>
        <div className="flex items-start gap-3 px-4 py-3 border-b border-[var(--color-border)] bg-[var(--color-panel)]/60">
          <Compass size={16} className="text-amber-300 mt-0.5" />
          <div className="flex-1">
            <h2 className="text-[14px] font-semibold">📜 编辑你的投资理念</h2>
            <div className="text-[10px] text-[var(--color-dim)] mt-0.5">
              保存 = bump 版本号. 写"change_note"记下这次为什么改, 未来回看用.
            </div>
          </div>
          <button onClick={onClose} className="text-[var(--color-dim)] hover:text-[var(--color-text)] p-1">
            <X size={16} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-3 text-[11px]">
          {([
            ['north_star',            '🌟 NORTH STAR — 1 句话核心目标', 2],
            ['identity',              '👤 Identity — 你是什么 investor', 3],
            ['circle_competence',     '🎯 Circle of Competence — 会做 / 不会做', 4],
            ['time_horizon',          '⏰ Time Horizon — 默认持有期', 3],
            ['entry_rules',           '➕ Entry Rules — 什么情况下买入', 10],
            ['exit_rules',            '➖ Exit Rules — 什么情况下卖出', 10],
            ['hedge_plan',            '🛡️ Hedge & Risk Plan — 主线失败怎么办', 12],
            ['disagreement_protocol', '⚖️ Disagreement Protocol — 跟 smart money 反向时', 10],
          ] as const).map(([key, label, rows]) => (
            <div key={key}>
              <div className="text-[10px] text-[var(--color-dim)] uppercase tracking-wider mb-1">{label}</div>
              <textarea
                rows={rows}
                value={draft[key as keyof typeof draft]}
                onChange={(e) => setDraft({ ...draft, [key]: e.target.value })}
                className="w-full bg-[var(--color-panel)] border border-[var(--color-border)] rounded px-2 py-1.5 text-[11px] font-mono outline-none focus:border-[var(--color-accent)] resize-y leading-relaxed"
                data-testid={`philosophy-edit-${key}`}
              />
            </div>
          ))}

          <div>
            <div className="text-[10px] text-[var(--color-dim)] uppercase tracking-wider mb-1">
              📝 Change note — 这次为什么改 (会进版本日志, 未来回看用)
            </div>
            <input
              type="text"
              value={changeNote}
              onChange={(e) => setChangeNote(e.target.value)}
              placeholder="e.g. 'Tepper减仓 NVDA 让我重新审视, 加了 belief #6'"
              className="w-full bg-[var(--color-panel)] border border-[var(--color-border)] rounded px-2 py-1.5 text-[11px] outline-none focus:border-[var(--color-accent)]"
              data-testid="philosophy-change-note"
            />
          </div>
        </div>

        <div className="flex items-center gap-2 px-4 py-3 border-t border-[var(--color-border)] bg-[var(--color-panel)]/60">
          <button
            onClick={save}
            disabled={updateMu.isPending}
            className="text-[11px] px-3 py-1 rounded border border-emerald-500/40 hover:bg-emerald-500/10 text-emerald-300 flex items-center gap-1 disabled:opacity-50"
            data-testid="philosophy-save"
          >
            <Save size={11} /> {updateMu.isPending ? '保存中…' : '保存 (bump version)'}
          </button>
          <button
            onClick={onClose}
            className="text-[11px] px-3 py-1 rounded border border-[var(--color-border)] text-[var(--color-dim)] hover:text-[var(--color-text)]"
          >
            Cancel
          </button>
          {updateMu.error && (
            <span className="text-[10px] text-red-300 ml-auto">err: {updateMu.error.message}</span>
          )}
        </div>
      </div>
    </>
  )
}
