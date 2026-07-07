/**
 * InvestmentPhilosophyWidget — your "Ulysses contract".
 *
 * v0.12 structure — 道简单, 术千变万化. The framework holds only 道;
 * tactics are generated per-trade, never enumerated here.
 *
 *   📜 v0.X · 复盘 Nd 前 · [今日已 review] [编辑]
 *   ──────────────────────────────────────
 *   🌟 总纲  (always visible — 1 句话; 「收益/风险/认知三角」带 "?" 解释)
 *      · 自洽持有者  (identity, subtitle)
 *      · 无固定持有期 (time_horizon, subtitle)
 *   🔒 L0 铁律 — 永不破            [collapsible]
 *   🧭 L1 判断过程 — a→b→c→d→e     [collapsible]
 *   📍 观察 — 只汇报, 不进「道」    [collapsible]
 */
import { useState, useEffect, useRef } from 'react'
import { NestedGroup } from '@/components/ui/Card'
import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query'
import {
  Compass, Edit3, Save, X, ChevronDown, ChevronRight,
  AlertTriangle, RotateCw, HelpCircle,
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

/** The exact phrase in north_star that gets the "?" explainer. */
const TRIANGLE_TERM = '收益 / 风险 / 认知三角'


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
          · 道简单, 术千变万化 · 防自己冲动 · 每月 review
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
        <NestedGroup className="text-[11px]">
          {/* 总纲 — always front and center */}
          <div className="rounded border border-amber-500/30 bg-amber-500/5 p-2.5">
            <div className="text-[9px] uppercase tracking-wider text-amber-300/80 mb-1">
              🌟 总纲（道）— 1 句话不能丢
            </div>
            <div className="text-[13px] text-[var(--color-text)] font-medium leading-relaxed">
              <NorthStar text={p.north_star} help={p.circle_competence} />
            </div>
            {/* identity + horizon as quiet subtitles under the 道 */}
            {(p.identity || p.time_horizon) && (
              <div className="mt-2 pt-2 border-t border-amber-500/20 space-y-1 text-[10px] text-[var(--color-dim)] leading-relaxed">
                {p.identity && <div>👤 {p.identity}</div>}
                {p.time_horizon && <div>⏰ {p.time_horizon}</div>}
              </div>
            )}
          </div>

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

          {/* Collapsible sections — only 道, no 术 */}
          <Section title="🔒 L0 铁律 — 永不破"
                   k="l0" openSections={openSections} toggle={toggleSection}>
            <Markdown text={p.hedge_plan} />
          </Section>

          <Section title="🧭 L1 判断过程 — a → b → c → d → e"
                   k="l1" openSections={openSections} toggle={toggleSection}>
            <Markdown text={p.entry_rules} />
            {p.exit_rules && (
              <div className="mt-2 pt-2 border-t border-[var(--color-border)]/30">
                <Markdown text={p.exit_rules} />
              </div>
            )}
          </Section>

          <Section title="📍 观察 — 只汇报, 不进「道」"
                   k="obs" openSections={openSections} toggle={toggleSection}>
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
              <Edit3 size={10} /> 编辑
            </button>
          </div>
        </NestedGroup>
      )}

      {editing && (
        <EditModal philosophy={p} onClose={() => setEditing(null)} />
      )}
    </div>
  )
}


/**
 * Renders the 总纲 sentence, attaching a click-toggle "?" explainer to
 * the 收益/风险/认知三角 phrase so it can be reviewed any time. Click
 * (not hover) — works on touch / mobile.
 */
function NorthStar({ text, help }: { text?: string; help?: string }) {
  if (!text) return <span className="italic text-[var(--color-dim)]">(空 — 点编辑添加)</span>
  const idx = text.indexOf(TRIANGLE_TERM)
  if (idx < 0 || !help) return <span>{text}</span>
  const before = text.slice(0, idx)
  const after = text.slice(idx + TRIANGLE_TERM.length)
  return (
    <span>
      {before}
      <span className="font-semibold text-amber-200">{TRIANGLE_TERM}</span>
      <TriangleHelp help={help} />
      {after}
    </span>
  )
}


function TriangleHelp({ help }: { help: string }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLSpanElement>(null)

  useEffect(() => {
    if (!open) return
    function onDown(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    function onKey(e: KeyboardEvent) { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  return (
    <span ref={ref} className="relative inline-block align-baseline">
      <button
        onClick={(e) => { e.stopPropagation(); setOpen(o => !o) }}
        className="ml-0.5 -mt-1 inline-flex align-text-top text-amber-300/80 hover:text-amber-200"
        title="收益 / 风险 / 认知三角 是什么 — 点开复习"
        aria-label="收益/风险/认知三角 解释"
        data-testid="triangle-help-toggle"
      >
        <HelpCircle size={12} />
      </button>
      {open && (
        <div
          data-testid="triangle-help-popover"
          className="absolute z-50 mt-1 left-0 top-full w-[320px] max-w-[80vw] px-3 py-2.5 rounded-md bg-[#0e1219] border border-amber-500/50 shadow-lg shadow-black/40 text-[11px] leading-[1.6] text-[var(--color-text)] font-normal text-left"
        >
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-[9px] uppercase tracking-wider text-amber-300">
              🔺 收益 / 风险 / 认知 三角
            </span>
            <button
              onClick={(e) => { e.stopPropagation(); setOpen(false) }}
              className="text-[var(--color-dim)] hover:text-[var(--color-text)]"
            >
              <X size={11} />
            </button>
          </div>
          <Markdown text={help} />
        </div>
      )}
    </span>
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
        const trimmed = line.trim()
        if (/^[-•·]/.test(trimmed)) {
          const nested = /^\s+/.test(line)   // indented sub-bullet
          const body = trimmed.replace(/^[-•·]\s*/, '')
          return (
            <div key={i} className={nested ? 'pl-8 -indent-3 text-[var(--color-dim)]' : 'pl-4 -indent-3'}>
              {nested ? '–' : '·'} {body}
            </div>
          )
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
    time_horizon:          philosophy.time_horizon ?? '',
    circle_competence:     philosophy.circle_competence ?? '',
    hedge_plan:            philosophy.hedge_plan ?? '',
    entry_rules:           philosophy.entry_rules ?? '',
    exit_rules:            philosophy.exit_rules ?? '',
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
            ['north_star',            '🌟 总纲 — 1 句话(含「收益 / 风险 / 认知三角」)', 3],
            ['identity',              '👤 自洽持有者 — 我是什么 investor', 4],
            ['time_horizon',          '⏰ 持有期', 3],
            ['circle_competence',     '🔺 收益/风险/认知三角 — 总纲里 "?" 弹出的解释', 12],
            ['hedge_plan',            '🔒 L0 铁律 — 永不破(下行可承受)', 5],
            ['entry_rules',           '🧭 L1 判断过程 — a → b → c → d → e', 12],
            ['exit_rules',            '➖ 卖出补充 — 卖也走 L1(可留空)', 5],
            ['disagreement_protocol', '📍 观察 — 只汇报, 不进「道」', 8],
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
              placeholder="e.g. '某次大波动让我重审 L1 的 c, 把 d 改成收益/亏损概率分开估'"
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
