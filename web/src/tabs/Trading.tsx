import { useState, useEffect, useReducer } from 'react'
import { nestedRailClass } from '@/components/ui/Card'
import {
  useTradingPolicy, useUpdateTradingPolicy,
  useTradingSetups, useSaveTradingSetup, useDeleteTradingSetup,
  useDistillSetup, useBacktestSetup, useSetupChartQuery, useCompareSetups,
  useTradingState, useSetHalt, useFlatten, useScanTrade, useRefreshPositions, usePortfolioRisk,
  useCombos, useSaveCombo, useDeleteCombo, useBacktestCombo,
  useReviewSetups, useRegime, useWatchlist,
  useSetAutoTrade, useSaveOptimizedCombo,
  fetchOptimizePlan, fetchComboAdhoc,
  useJournal, useSaveJournal, useDeleteJournal, useJournalWeekly, useSyncJournal,
  useCockpit,
  fetchIbkrStatus, fetchIbkrAccount, fetchIbkrPositions,
  fetchIbkrOpenOrders, postVenue, postIbkrTestOrder, postIbkrCancelAll,
  postIbkrSnapshot, fetchIbkrLog,
  fetchIbkrFlexConfig, postIbkrFlexConfig, postIbkrFlexSync, postIbkrReconcile, postBudget,
  type JournalEntry, type IbkrStatus, type IbkrAccount, type IbkrPositions, type IbkrOpenOrders, type IbkrLog, type IbkrFlexStatus, type IbkrReconcile,
  type TradingSetup, type QuantSpec, type BacktestResult, type ScanTradeResult,
  type TradingChartData, type CompareRow, type TradingCombo, type ComboBacktest,
  type BacktestStats,
} from '@/lib/api'

// localStorage: remember the last symbol the user verified per setup, so the
// curve + stats + trade detail come back automatically after a page reload.
const CHART_VIEW_KEY = 'neomind.trading.chartViews'
function loadChartViews(): Record<string, string> {
  try { return JSON.parse(localStorage.getItem(CHART_VIEW_KEY) || '{}') } catch { return {} }
}
function saveChartView(setupId: string, symbol: string) {
  const m = loadChartViews(); m[setupId] = symbol
  localStorage.setItem(CHART_VIEW_KEY, JSON.stringify(m))
}
function clearChartView(setupId: string) {
  const m = loadChartViews(); delete m[setupId]
  localStorage.setItem(CHART_VIEW_KEY, JSON.stringify(m))
}
import {
  PaperAccountCard, PaperPositionsTable, PaperTradesTable, PaperOrderForm,
} from '@/components/widgets/PaperPanel'
import { fmtTs, todayLocal } from '@/lib/utils'

interface Props { projectId: string }

// ── Lightweight toast / status tracker (module-level, no context) ──
// Every async action fires one so you always know "what happened after I clicked".
type Toast = { id: number; msg: string; type: 'info' | 'success' | 'error' }
let _toasts: Toast[] = []
let _listeners: Array<() => void> = []
let _toastId = 0
function toast(msg: string, type: Toast['type'] = 'info') {
  const t: Toast = { id: ++_toastId, msg, type }
  _toasts = [..._toasts, t]; _listeners.forEach(l => l())
  setTimeout(() => { _toasts = _toasts.filter(x => x.id !== t.id); _listeners.forEach(l => l()) },
    type === 'error' ? 7000 : 3500)
}
function Toaster() {
  const [, force] = useReducer(x => x + 1, 0)
  useEffect(() => { const l = () => force(); _listeners.push(l); return () => { _listeners = _listeners.filter(x => x !== l) } }, [])
  return (
    <div className="fixed bottom-4 right-4 z-[9999] space-y-1.5 max-w-[360px]">
      {_toasts.map(t => (
        <div key={t.id} className={`text-[11px] px-3 py-2 rounded shadow-lg border ${
          t.type === 'error' ? 'bg-[var(--color-red)]/20 border-[var(--color-red)]/50 text-[var(--color-red)]'
            : t.type === 'success' ? 'bg-[var(--color-green)]/20 border-[var(--color-green)]/50 text-[var(--color-green)]'
            : 'bg-[var(--color-panel)] border-[var(--color-border)] text-[var(--color-text)]'}`}>
          {t.type === 'error' ? '✗ ' : t.type === 'success' ? '✓ ' : '⏳ '}{t.msg}
        </div>
      ))}
    </div>
  )
}
// helper: wrap a mutation's lifecycle in toasts
function toastify<T>(label: string, p: Promise<T>, ok?: (r: T) => string): Promise<T> {
  toast(`${label}…`, 'info')
  return p.then(r => { toast(ok ? ok(r) : `${label} 完成`, 'success'); return r })
          .catch(e => { toast(`${label} 失败: ${String(e?.message || e).slice(0, 80)}`, 'error'); throw e })
}
const SYMBOL_RE = /^[A-Z][A-Z0-9.\-]{0,8}$/
function isValidSymbol(s: string): boolean { return SYMBOL_RE.test(s.toUpperCase().trim()) }
// time windows — include SHORT ones for short-term testing
const LOOKBACKS = ['1mo', '3mo', '6mo', '1y', '2y', '3y', '5y']

// Reusable chip-based symbol picker (no comma-typing; highlighted removable chips)
function SymbolPicker({ symbols, onChange, watchlist }: { symbols: string[]; onChange: (s: string[]) => void; watchlist?: string[] }) {
  const [input, setInput] = useState('')
  const [err, setErr] = useState('')
  function add() {
    const parts = input.split(/[,，\s]+/).map(s => s.toUpperCase().trim()).filter(Boolean)
    const bad = parts.filter(p => !isValidSymbol(p))
    if (bad.length) { setErr(`无效代码: ${bad.join(', ')}（应为字母开头，如 AAPL）`); return }
    onChange(Array.from(new Set([...symbols, ...parts]))); setInput(''); setErr('')
  }
  return (
    <span className="inline-flex items-center gap-1 flex-wrap">
      {symbols.map(s => (
        <span key={s} className="px-1.5 py-0.5 rounded bg-[var(--color-accent)]/15 text-[var(--color-accent)] font-mono text-[10px] flex items-center gap-1">
          {s}<button onClick={() => onChange(symbols.filter(x => x !== s))} className="text-[var(--color-red)]">✕</button>
        </span>
      ))}
      <input value={input} onChange={e => { setInput(e.target.value); setErr('') }} onKeyDown={e => e.key === 'Enter' && add()}
        placeholder="代码 回车/+" className="w-28 bg-[var(--color-bg)] border border-[var(--color-border)] rounded px-1.5 py-0.5 font-mono text-[10px] text-[var(--color-text)]" />
      <button onClick={add} disabled={!input.trim()} className="text-[10px] px-1.5 py-0.5 rounded bg-[var(--color-accent)]/20 text-[var(--color-accent)] border border-[var(--color-accent)]/40">+</button>
      {watchlist && watchlist.length > 0 && (
        <button onClick={() => onChange(Array.from(new Set([...symbols, ...watchlist])))}
          className="text-[9px] px-1.5 py-0.5 rounded border border-[var(--color-border)] text-[var(--color-dim)]">用 watchlist</button>
      )}
      {err && <span className="text-[9px] text-[var(--color-red)]">{err}</span>}
    </span>
  )
}

// ════════════════════════════════════════════════════════════
//  Trading one-page: TPS · Setups (NL→quant) · backtest · paper
//  Deliberately separate from the long-term smart-money stack —
//  short-term needs its own toolkit (those 13F signals are quarterly).
// ════════════════════════════════════════════════════════════

export function TradingTab({ projectId }: Props) {
  return (
    <div className="h-full overflow-y-auto overflow-x-hidden">
      <Toaster />
      <div className="p-3 space-y-3 max-w-[1200px] mx-auto">
        {/* Bucket ② banner — distinct from Core (bucket ①) */}
        <div className="text-[11px] rounded p-2 border border-[var(--color-yellow)]/40 bg-[var(--color-yellow)]/10 flex items-center gap-2 flex-wrap">
          <span className="font-semibold text-[var(--color-yellow)]">⚡ 桶② 量化 swing 沙盒</span>
          <span className="text-[var(--color-dim)]">ring-fenced <b>小资金、纯股票</b>，用来<b>验证 edge + 练纪律</b>（不是用来打败你的长期核心仓）。与「Core」(桶① 长期持仓) 是<b>不同的钱</b>，严格分账。</span>
        </div>
        {/* Mode banner — paper vs IBKR depends on the venue selector below */}
        <div className="text-[11px] rounded p-2 border border-[var(--color-green)]/40 bg-[var(--color-green)]/10 flex items-center gap-2 flex-wrap">
          <span className="font-semibold text-[var(--color-green)]">📝 模拟模式 (Paper)</span>
          <span className="text-[var(--color-dim)]">默认<b>本地模拟</b>。执行去向可在下方 IBKR 面板切到 <b>IBKR 账户</b>（paper 与真钱同一路径，仅账户不同）。期权<b>只用于对冲</b>，且在 Core 桶做，不在这里。</span>
        </div>
        <div className="text-[12px] text-[var(--color-dim)] leading-relaxed bg-[var(--color-panel)] border border-[var(--color-border)] rounded p-2.5">
          <span className="text-[var(--color-text)] font-semibold">⚡ 短线交易台 (Trading Desk)</span>
          {' '}— 与左侧长期 smart-money 信号<b>完全隔离</b>。一切自动化（扫描/进场/跑分），
          你只需在下面这条<b>紧急制动条</b>上手动干预。
        </div>
        <EmergencyBrakeBar projectId={projectId} />
        <IbkrPanel />
        <TodayCockpit projectId={projectId} />
        <TradingPolicyPanel />
        <JournalPanel projectId={projectId} />
        <SetupsPanel projectId={projectId} />
        <CombosPanel projectId={projectId} />
        <ComboOptimizerPanel projectId={projectId} />
        <StrategyComparePanel />
        <PipelinePanel />
        <PaperSection projectId={projectId} />
      </div>
    </div>
  )
}

// ════════════════════════════════════════════════════════════
//  Emergency brake bar — the ONLY manual controls
//  Exported so the Strategies-tab DeskStrip can render the exact
//  same controls verbatim (single-sourced halt/auto/flatten logic).
// ════════════════════════════════════════════════════════════
export function EmergencyBrakeBar({ projectId }: { projectId: string }) {
  const { data: state } = useTradingState()
  const { data: regime } = useRegime()
  const setHalt = useSetHalt()
  const setAuto = useSetAutoTrade()
  const flatten = useFlatten(projectId)
  const refresh = useRefreshPositions(projectId)
  const [flatMsg, setFlatMsg] = useState<string | null>(null)
  const halted = !!state?.global_halt
  const autoArmed = state?.auto_trade !== 0
  const byKill = state?.halted_by === 'kill_switch'

  return (
    <div className={`rounded border p-2.5 flex items-center gap-3 flex-wrap ${halted ? 'border-[var(--color-red)] bg-[var(--color-red)]/10' : 'border-[var(--color-border)] bg-[var(--color-bg)]'}`}>
      <span className="text-[11px] font-semibold text-[var(--color-text)]">🧯 紧急制动</span>
      {/* Global halt toggle */}
      <button
        onClick={() => setHalt.mutate({ on: !halted, reason: halted ? undefined : '用户手动停止' })}
        disabled={setHalt.isPending}
        className={`text-[11px] px-3 py-1 rounded font-semibold border ${halted
          ? 'bg-[var(--color-green)]/20 text-[var(--color-green)] border-[var(--color-green)]/50'
          : 'bg-[var(--color-red)]/20 text-[var(--color-red)] border-[var(--color-red)]/50'}`}>
        {halted ? '▶ 恢复交易' : '🛑 全局停止交易'}
      </button>
      {/* Disconnect / connect automated entry (master switch) */}
      <button
        onClick={() => { toastify(autoArmed ? '断开自动进场' : '接通自动进场', setAuto.mutateAsync(!autoArmed)) }}
        disabled={setAuto.isPending}
        title="一键断开/接通自动进场（独立于紧急停止）"
        className={`text-[11px] px-3 py-1 rounded border font-semibold ${autoArmed
          ? 'border-[var(--color-yellow)]/50 text-[var(--color-yellow)]' : 'border-[var(--color-green)]/50 text-[var(--color-green)]'}`}>
        {autoArmed ? '🔌 断开自动进场' : '🔗 接通自动进场'}
      </button>
      {/* Flatten all */}
      <button
        onClick={() => { if (confirm('全部平仓：立即市价平掉所有 paper 持仓？')) toastify('全部平仓', flatten.mutateAsync(), (r) => `已平 ${r.flattened} 个仓`).then((r) => setFlatMsg(`已平 ${r.flattened} 个仓`)).catch(()=>{}) }}
        disabled={flatten.isPending}
        className="text-[11px] px-3 py-1 rounded border border-[var(--color-red)]/50 text-[var(--color-red)] hover:bg-[var(--color-red)]/10">
        🚪 全部平仓
      </button>
      {flatMsg && <span className="text-[10px] text-[var(--color-dim)]">{flatMsg}</span>}
      {/* Refresh — settle stop/target/OCO with latest prices */}
      <button
        onClick={() => refresh.mutate()}
        disabled={refresh.isPending}
        title="拉最新价喂给 paper engine，结算挂着的止盈/止损/OCO"
        className="text-[10px] px-2 py-1 rounded border border-[var(--color-border)] text-[var(--color-dim)] hover:text-[var(--color-text)]">
        {refresh.isPending ? '刷新中…' : '↻ 结算挂单'}
      </button>
      {refresh.data && <span className="text-[9px] text-[var(--color-dim)]">更新 {refresh.data.n} · 结算 {refresh.data.orders_settled}</span>}
      {regime && (
        <span className={`text-[10px] px-2 py-0.5 rounded border ${regime.regime === 'risk_off'
          ? 'text-[var(--color-red)] border-[var(--color-red)]/40' : 'text-[var(--color-green)] border-[var(--color-green)]/40'}`}
          title={regime.note}>
          {regime.regime === 'risk_off' ? '🌧 risk-off (停新仓)' : regime.regime === 'risk_on' ? '☀️ risk-on' : 'regime ?'}
          {regime.spy ? ` · SPY ${regime.spy}/${regime.spy_sma200}` : ''}
        </span>
      )}
      {/* Status */}
      <span className="ml-auto text-[10px]">
        {halted ? (
          <span className="text-[var(--color-red)]">
            ⏸ 交易已停止{byKill ? '（kill-switch 自动触发）' : ''}{state?.halt_reason ? ` · ${state.halt_reason}` : ''}
          </span>
        ) : !autoArmed ? (
          <span className="text-[var(--color-yellow)]">🔌 自动进场已断开（扫描只报告，不下单）</span>
        ) : (
          <span className="text-[var(--color-green)]">● 自动进场已武装 (paper)</span>
        )}
      </span>
    </div>
  )
}

// ── Section wrapper ──
function Section({ title, subtitle, right, children }: {
  title: string; subtitle?: string; right?: React.ReactNode; children: React.ReactNode
}) {
  return (
    <div className="border border-[var(--color-border)] rounded bg-[var(--color-bg)]">
      <div className="flex items-center gap-2 px-3 py-2 border-b border-[var(--color-border)] flex-wrap">
        <span className="text-[12px] font-semibold text-[var(--color-text)]">{title}</span>
        {subtitle && <span className="text-[10px] text-[var(--color-dim)] italic">{subtitle}</span>}
        <span className="ml-auto">{right}</span>
      </div>
      <div className="p-3">{children}</div>
    </div>
  )
}

// ════════════════════════════════════════════════════════════
//  ① Trading Policy
// ════════════════════════════════════════════════════════════
type TpsDraft = {
  north_star: string; identity: string; entry_protocol: string; exit_protocol: string
  kill_switch: string; execution_rules: string; validation_rules: string; tax_note: string
  red_lines: string  // newline-separated
  risk_rules: Record<string, unknown>
}

function TradingPolicyPanel() {
  const { data: tps, isLoading } = useTradingPolicy()
  const update = useUpdateTradingPolicy()
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState<TpsDraft | null>(null)

  if (isLoading) return <Section title="🛡 短线交易理念 (TPS)"><div className="text-[10px] text-[var(--color-dim)]">loading…</div></Section>
  if (!tps) return null

  function startEdit() {
    setDraft({
      north_star: tps!.north_star ?? '', identity: tps!.identity ?? '',
      entry_protocol: tps!.entry_protocol ?? '', exit_protocol: tps!.exit_protocol ?? '',
      kill_switch: tps!.kill_switch ?? '', execution_rules: tps!.execution_rules ?? '',
      validation_rules: tps!.validation_rules ?? '', tax_note: tps!.tax_note ?? '',
      red_lines: (tps!.red_lines ?? []).join('\n'),
      risk_rules: { ...(tps!.risk_rules ?? {}) },
    })
    setEditing(true)
  }
  function save() {
    if (!draft) return
    update.mutate({
      north_star: draft.north_star, identity: draft.identity,
      entry_protocol: draft.entry_protocol, exit_protocol: draft.exit_protocol,
      kill_switch: draft.kill_switch, execution_rules: draft.execution_rules,
      validation_rules: draft.validation_rules, tax_note: draft.tax_note,
      red_lines: draft.red_lines.split('\n').map(s => s.trim()).filter(Boolean),
      risk_rules: draft.risk_rules,
      change_note: 'edit via Trading tab',
    }, { onSuccess: () => setEditing(false) })
  }

  return (
    <Section
      title="🛡 短线交易理念 (TPS)"
      subtitle={`${tps.version} · 独立于长期 IPS · 红线优先`}
      right={
        editing ? (
          <span className="flex gap-1.5">
            <button onClick={save} disabled={update.isPending}
              className="text-[10px] px-2 py-0.5 rounded bg-[var(--color-accent)]/20 text-[var(--color-accent)] border border-[var(--color-accent)]/40">
              {update.isPending ? '保存中…' : '保存'}</button>
            <button onClick={() => setEditing(false)}
              className="text-[10px] px-2 py-0.5 rounded border border-[var(--color-border)] text-[var(--color-dim)]">取消</button>
          </span>
        ) : (
          <button onClick={startEdit}
            className="text-[10px] px-2 py-0.5 rounded border border-[var(--color-border)] text-[var(--color-dim)] hover:text-[var(--color-text)]">编辑</button>
        )
      }
    >
      {editing && draft ? (
        <div className="space-y-2">
          <Field label="🎯 北极星 (为什么做短线)" value={draft.north_star} onChange={(v) => setDraft({ ...draft, north_star: v })} />
          <Field label="🧭 身份 (我是什么交易者)" value={draft.identity} onChange={(v) => setDraft({ ...draft, identity: v })} />
          <label className="block">
            <span className="text-[10px] text-[var(--color-dim)]">🚫 红线 (每行一条)</span>
            <textarea value={draft.red_lines} onChange={(e) => setDraft({ ...draft, red_lines: e.target.value })} rows={7}
              className="w-full mt-0.5 text-[11px] bg-[var(--color-panel)] border border-[var(--color-border)] rounded px-2 py-1 text-[var(--color-text)] resize-y font-mono leading-[1.5]" />
          </label>
          <div>
            <span className="text-[10px] text-[var(--color-dim)]">📐 风控参数</span>
            <div className="flex flex-wrap gap-2 mt-1">
              {Object.entries(draft.risk_rules).map(([k, v]) => (
                <label key={k} className="text-[9px] flex items-center gap-1">
                  <span className="text-[var(--color-dim)] font-mono">{k}</span>
                  {typeof v === 'boolean' ? (
                    <input type="checkbox" checked={v} onChange={(e) => setDraft({ ...draft, risk_rules: { ...draft.risk_rules, [k]: e.target.checked } })} />
                  ) : (
                    <input type="number" value={v as number} step="0.5"
                      onChange={(e) => setDraft({ ...draft, risk_rules: { ...draft.risk_rules, [k]: parseFloat(e.target.value) } })}
                      className="w-16 bg-[var(--color-panel)] border border-[var(--color-border)] rounded px-1 py-0.5 text-[var(--color-text)] font-mono" />
                  )}
                </label>
              ))}
            </div>
          </div>
          <Field label="🎬 进场协议" value={draft.entry_protocol} onChange={(v) => setDraft({ ...draft, entry_protocol: v })} />
          <Field label="🚪 出场协议" value={draft.exit_protocol} onChange={(v) => setDraft({ ...draft, exit_protocol: v })} />
          <Field label="⛔ Kill-switch" value={draft.kill_switch} onChange={(v) => setDraft({ ...draft, kill_switch: v })} />
          <Field label="⚙️ 执行规则" value={draft.execution_rules} onChange={(v) => setDraft({ ...draft, execution_rules: v })} />
          <Field label="🔬 验证规则" value={draft.validation_rules} onChange={(v) => setDraft({ ...draft, validation_rules: v })} />
          <Field label="💸 税务备注" value={draft.tax_note} onChange={(v) => setDraft({ ...draft, tax_note: v })} />
        </div>
      ) : (
        <div className="space-y-2.5 text-[11px]">
          <Row k="🎯 北极星" v={tps.north_star} />
          <Row k="🧭 身份" v={tps.identity} />
          {tps.red_lines && tps.red_lines.length > 0 && (
            <div>
              <div className="text-[10px] text-[var(--color-dim)] mb-1">🚫 红线 (hard rules)</div>
              <ul className="space-y-0.5">
                {tps.red_lines.map((r, i) => (
                  <li key={i} className="text-[10.5px] text-[var(--color-text)]/90 flex gap-1.5">
                    <span className="text-[var(--color-red)]">•</span><span>{r}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {tps.risk_rules && (
            <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-[10px]">
              <span className="text-[var(--color-dim)]">📐 风控:</span>
              {Object.entries(tps.risk_rules).map(([k, v]) => (
                <span key={k} className="font-mono">
                  <span className="text-[var(--color-dim)]">{k}=</span>
                  <span className={typeof v === 'boolean' ? (v ? 'text-[var(--color-green)]' : 'text-[var(--color-red)]') : 'text-[var(--color-text)]'}>{String(v)}</span>
                </span>
              ))}
            </div>
          )}
          <Row k="🎬 进场" v={tps.entry_protocol} />
          <Row k="🚪 出场" v={tps.exit_protocol} />
          <Row k="⛔ Kill-switch" v={tps.kill_switch} />
          <Row k="⚙️ 执行" v={tps.execution_rules} />
          <Row k="🔬 验证" v={tps.validation_rules} />
          <Row k="💸 税" v={tps.tax_note} />
        </div>
      )}
    </Section>
  )
}

function Row({ k, v }: { k: string; v?: string }) {
  if (!v) return null
  return (
    <div className="flex gap-2 leading-[1.5]">
      <span className="text-[var(--color-dim)] w-[78px] flex-shrink-0 text-[10px]">{k}</span>
      <span className="text-[var(--color-text)]/90 flex-1">{v}</span>
    </div>
  )
}

function Field({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <label className="block">
      <span className="text-[10px] text-[var(--color-dim)]">{label}</span>
      <textarea value={value} onChange={(e) => onChange(e.target.value)} rows={2}
        className="w-full mt-0.5 text-[11px] bg-[var(--color-panel)] border border-[var(--color-border)] rounded px-2 py-1 text-[var(--color-text)] resize-y" />
    </label>
  )
}

// ════════════════════════════════════════════════════════════
//  ② Setups (NL→quant distillation + backtest)
// ════════════════════════════════════════════════════════════
function SetupsPanel({ projectId }: { projectId: string }) {
  const { data, isLoading } = useTradingSetups()
  const scan = useScanTrade(projectId)
  const review = useReviewSetups()
  const [editingId, setEditingId] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)

  const setups = data?.setups ?? []

  return (
    <Section
      title="📐 策略库 / Setups · 跑分排序"
      subtitle="文字 → 量化公式 → 回测 → 自动进场"
      right={
        <span className="flex gap-1.5 items-center">
          <button onClick={() => review.mutate()} disabled={review.isPending}
            className="text-[10px] px-2 py-0.5 rounded border border-[var(--color-border)] text-[var(--color-dim)] hover:text-[var(--color-text)]"
            title="自动退役表现差的策略 + 给改进建议(改动需你确认)">
            {review.isPending ? '复审中…' : '🔄 复审策略'}</button>
          <button onClick={() => toastify('扫描并自动进场', scan.mutateAsync(), (r) => `触发 ${r.n_triggers} · 自动进场 ${r.n_executed}${r.risk_off ? ' (risk-off停新仓)' : ''}`).catch(() => {})} disabled={scan.isPending}
            className="text-[10px] px-2 py-0.5 rounded border border-[var(--color-accent)]/40 text-[var(--color-accent)] hover:bg-[var(--color-accent)]/10"
            title="扫描已武装(paper/live)setup 并自动下 paper 单（受全局停止 gate）">
            {scan.isPending ? '扫描+下单中…' : '⚡ 扫描并自动进场'}</button>
          <button onClick={() => { setCreating(true); setEditingId(null) }}
            className="text-[10px] px-2 py-0.5 rounded bg-[var(--color-accent)]/20 text-[var(--color-accent)] border border-[var(--color-accent)]/40">+ 新 setup</button>
        </span>
      }
    >
      {review.data && (
        <div className="mb-2 text-[10px] bg-[var(--color-panel)]/60 rounded p-2 space-y-0.5">
          <div>🔄 复审: 自动退役 <b className="text-[var(--color-red)]">{review.data.n_retired}</b> · 改进建议 <b className="text-[var(--color-yellow)]">{review.data.n_suggestions}</b></div>
          {review.data.retired.map((r, i) => <div key={i} className="text-[var(--color-red)]">⊘ 退役 {r.name}: {r.reason}</div>)}
          {review.data.suggestions.map((s, i) => (
            <div key={i} className="text-[var(--color-dim)]">💡 {s.name}: {s.tips.join('；')}（建议，需你点 ✎ 改公式 确认）</div>
          ))}
        </div>
      )}
      {scan.data && <ScanTradeReport res={scan.data} />}
      {creating && (
        <SetupEditor onClose={() => setCreating(false)} />
      )}
      {isLoading ? (
        <div className="text-[10px] text-[var(--color-dim)]">loading…</div>
      ) : setups.length === 0 && !creating ? (
        <div className="text-[10.5px] text-[var(--color-dim)] py-3 text-center">
          还没有 setup。点 "+ 新 setup" 用自然语言描述你的入场/出场规则，蒸馏成量化公式。
        </div>
      ) : (
        <div className="space-y-2">
          {setups.map((s) => (
            <SetupCard key={s.setup_id} setup={s}
              editing={editingId === s.setup_id}
              onEdit={() => setEditingId(editingId === s.setup_id ? null : s.setup_id)} />
          ))}
        </div>
      )}
    </Section>
  )
}

function ScanTradeReport({ res }: { res: ScanTradeResult }) {
  const ks = res.kill_switch
  return (
    <div className="mb-2 text-[10px] bg-[var(--color-panel)]/60 rounded p-2 space-y-1">
      <div>
        ⚡ 扫描 {res.scanned} 标的 · 触发 <b className="text-[var(--color-accent)]">{res.n_triggers}</b>
        {' '}· 自动进场 <b className="text-[var(--color-green)]">{res.n_executed}</b>
        {res.halted && <span className="ml-2 text-[var(--color-red)]">🛑 全局停止中，未执行</span>}
        {res.risk_off && <span className="ml-2 text-[var(--color-red)]">🌧 risk-off：停新仓</span>}
      </div>
      {res.regime && (
        <div className={res.risk_off ? 'text-[var(--color-red)]' : 'text-[var(--color-green)]'}>{res.regime.note}</div>
      )}
      {ks?.breached && (
        <div className="text-[var(--color-red)]">⛔ {ks.reason} → 已自动停止，请复盘后手动恢复</div>
      )}
      {!ks?.breached && (
        <div className="text-[var(--color-dim)] text-[9px]">
          kill-switch 监控: 回撤 {ks?.total_pnl_pct}% (限 -{ks?.dd_limit_pct}%) · 连亏 {ks?.consecutive_losses} (限 {ks?.consec_limit})
        </div>
      )}
      {res.executed.map((e, i) => (
        <div key={i} className="text-[var(--color-green)]">
          ✅ {e.symbol} ×{e.qty} @ {e.entry_px} · stop {e.stop_px} ({e.setup_name})
        </div>
      ))}
      {res.triggers.filter(t => t.skipped).map((t, i) => (
        <div key={`s${i}`} className="text-[var(--color-dim)]">
          ⊘ {t.symbol} 触发但跳过: {t.skipped} ({t.setup_name})
        </div>
      ))}
    </div>
  )
}

const STATUS_STYLE: Record<string, string> = {
  idea: 'text-[var(--color-dim)] border-[var(--color-border)]',
  paper: 'text-[var(--color-blue)] border-[var(--color-blue)]/40',
  live: 'text-[var(--color-green)] border-[var(--color-green)]/40',
  retired: 'text-[var(--color-dim)] border-[var(--color-border)] opacity-60',
}

const GRADE_STYLE: Record<string, string> = {
  A: 'text-[var(--color-green)] border-[var(--color-green)]/50',
  B: 'text-[var(--color-blue)] border-[var(--color-blue)]/50',
  C: 'text-[var(--color-yellow)] border-[var(--color-yellow)]/50',
  D: 'text-[var(--color-red)] border-[var(--color-red)]/50',
}

// Per-setup pipeline trace: 文字 → 公式 → 量化 → 验证 → 部署. Makes "how did
// we get to the final result" visible — each stage shows done/pending.
function FlowStrip({ setup }: { setup: TradingSetup }) {
  const conds = setup.quant_spec?.entry?.conditions?.length ?? 0
  const stages = [
    { n: '①', label: '文字', done: !!setup.nl_description, hint: '自然语言意图' },
    { n: '②', label: '公式', done: conds > 0, hint: `${conds} 条规则` },
    { n: '③', label: '量化', done: !!setup.quant_spec?.exit, hint: 'spec(止损/目标/sizing)' },
    { n: '④', label: '验证', done: !!(setup.backtest_stats?.n_trades), hint: '回测' },
    { n: '⑤', label: '部署', done: setup.status === 'paper' || setup.status === 'live', hint: setup.status },
  ]
  return (
    <div className="flex items-center gap-0.5 flex-wrap text-[8px]">
      {stages.map((s, i) => (
        <span key={i} className="flex items-center gap-0.5">
          <span title={s.hint}
            className={`px-1 py-0.5 rounded ${s.done
              ? 'bg-[var(--color-green)]/15 text-[var(--color-green)]'
              : 'bg-[var(--color-panel)] text-[var(--color-dim)]'}`}>
            {s.n}{s.label}{s.done ? '✓' : '·'}
          </span>
          {i < stages.length - 1 && <span className="text-[var(--color-dim)]">→</span>}
        </span>
      ))}
    </div>
  )
}

function SetupCard({ setup, editing, onEdit }: { setup: TradingSetup; editing: boolean; onEdit: () => void }) {
  const del = useDeleteTradingSetup()
  const bt = useBacktestSetup()  // saves stats for scoring (side effect)
  const remembered = loadChartViews()[setup.setup_id]
  const [symbol, setSymbol] = useState(remembered || 'AAPL')
  const [verifySymbol, setVerifySymbol] = useState<string | null>(remembered || null)
  const chartQ = useSetupChartQuery(setup.setup_id, verifySymbol || '', !!verifySymbol)
  const [editingSpec, setEditingSpec] = useState(false)
  const stats = setup.backtest_stats

  function runVerify() {
    setVerifySymbol(symbol)
    saveChartView(setup.setup_id, symbol)
    bt.mutate({ setup_id: setup.setup_id, symbol })  // refresh persisted stats → score
  }
  function closeVerify() {
    setVerifySymbol(null)
    clearChartView(setup.setup_id)
  }

  return (
    <div className="border border-[var(--color-border)] rounded bg-[var(--color-panel)]/40">
      <div className="flex items-center gap-2 px-2.5 py-1.5 flex-wrap">
        <span className="text-[11px] font-semibold text-[var(--color-text)]">{setup.name}</span>
        <span className={`text-[8.5px] px-1.5 py-0.5 rounded border ${STATUS_STYLE[setup.status] ?? STATUS_STYLE.idea}`}>{setup.status}</span>
        {setup.score && (
          <span className={`text-[8.5px] px-1.5 py-0.5 rounded border font-mono ${GRADE_STYLE[setup.score.grade] ?? GRADE_STYLE.C}`}
            title={`expectancy ${setup.score.expectancy_R}R · ${setup.score.n_trades} 笔 · 置信 ${setup.score.confidence}${setup.score.robustness ? ' · 稳健性 '+setup.score.robustness : ''}`}>
            🏅{setup.score.grade} {setup.score.score}{setup.score.overfit ? ' ⚠️过拟合' : ''}
          </span>
        )}
        <span className="text-[8.5px] text-[var(--color-dim)] font-mono">v{setup.version}</span>
        {stats && stats.n_trades > 0 && (
          <span className="text-[9px] text-[var(--color-dim)]">
            回测: <b className={(stats.win_rate ?? 0) >= 50 ? 'text-[var(--color-green)]' : 'text-[var(--color-red)]'}>{stats.win_rate}%</b> 胜率 · {stats.n_trades} 笔 · avgR {stats.avg_R} · {stats.symbol}
          </span>
        )}
        <span className="ml-auto flex gap-1.5">
          <button onClick={onEdit} className="text-[9px] px-1.5 py-0.5 rounded border border-[var(--color-border)] text-[var(--color-dim)] hover:text-[var(--color-text)]">{editing ? '收起' : '编辑'}</button>
          <button onClick={() => { if (confirm(`删除 setup「${setup.name}」?`)) del.mutate(setup.setup_id) }}
            className="text-[9px] px-1.5 py-0.5 rounded border border-[var(--color-red)]/40 text-[var(--color-red)]">删</button>
        </span>
      </div>
      <div className="px-2.5 pb-1"><FlowStrip setup={setup} /></div>
      {setup.nl_description && (
        <div className="px-2.5 pb-1.5 text-[10px] text-[var(--color-dim)] italic leading-[1.5]">
          <span className="text-[var(--color-accent)] not-italic">①文字 </span>“{setup.nl_description}”
        </div>
      )}
      {setup.quant_spec && (
        <div className="px-2.5 pb-2">
          <div className="text-[8px] text-[var(--color-accent)] mb-0.5 flex items-center gap-2">
            ②公式 → ③量化
            <button onClick={() => setEditingSpec(v => !v)}
              className="text-[var(--color-dim)] hover:text-[var(--color-text)] not-italic">
              {editingSpec ? '✕ 关闭' : '✎ 直接改公式'}</button>
          </div>
          {editingSpec
            ? <SpecEditor setup={setup} onClose={() => setEditingSpec(false)} />
            : <SpecView spec={setup.quant_spec} />}
        </div>
      )}
      {/* inline verify (回测 + 曲线), persists across reload via localStorage */}
      <div className="px-2.5 pb-1 flex items-center gap-2 flex-wrap">
        <span className="text-[8px] text-[var(--color-accent)]">④验证</span>
        <input value={symbol} onChange={(e) => setSymbol(e.target.value.toUpperCase())}
          className="w-20 text-[10px] bg-[var(--color-bg)] border border-[var(--color-border)] rounded px-1.5 py-0.5 font-mono text-[var(--color-text)]" />
        <button onClick={runVerify} disabled={chartQ.isFetching || bt.isPending}
          className="text-[10px] px-2 py-0.5 rounded border border-[var(--color-accent)]/40 text-[var(--color-accent)]"
          title="回测统计 + 价格曲线 + 历史买卖点，一起出；刷新后保留">
          {chartQ.isFetching ? '验证中…' : '▶ 回测 + 买卖曲线'}</button>
        {verifySymbol && (
          <button onClick={closeVerify} className="text-[9px] text-[var(--color-dim)] hover:text-[var(--color-text)]">✕ 关闭</button>
        )}
      </div>
      {chartQ.data && !chartQ.data.error && (
        <div className="px-2.5 pb-2 space-y-1">
          <BacktestResultView res={chartQ.data as BacktestResult} />
          <SetupChart data={chartQ.data} />
        </div>
      )}
      {chartQ.data?.error && <div className="px-2.5 pb-2 text-[9px] text-[var(--color-red)]">{chartQ.data.error}</div>}
      {editing && <SetupEditor setup={setup} onClose={onEdit} />}
    </div>
  )
}

// ── Quant spec visualization ──
function SpecView({ spec }: { spec: QuantSpec }) {
  const conds = spec.entry?.conditions ?? []
  return (
    <div className="text-[10px] font-mono bg-[var(--color-bg)] rounded p-2 space-y-1 border border-[var(--color-border)]/50">
      <div className="flex gap-2 flex-wrap text-[var(--color-dim)]">
        <span>⏱ {spec.timeframe ?? '1d'}</span>
        <span>lookback {spec.lookback ?? '1y'}</span>
        <span>dir {spec.direction ?? 'long'}</span>
      </div>
      <div>
        <span className="text-[var(--color-dim)]">进场 ({spec.entry?.logic ?? 'AND'}):</span>
        {conds.map((c, i) => (
          <div key={i} className="ml-2 flex flex-wrap items-baseline gap-x-1">
            <span className="text-[var(--color-dim)]">{i === 0 ? '•' : (spec.entry?.logic === 'OR' ? '或' : '且')}</span>
            <span className="text-[var(--color-accent)]">{c.left}</span>
            <span className="text-[var(--color-text)]">{c.op}</span>
            {c.rmult && c.rmult !== 1 ? <span className="text-[var(--color-yellow)]">{c.rmult}×</span> : null}
            <span className="text-[var(--color-yellow)]">{String(c.right)}</span>
            {c.note && <span className="text-[var(--color-dim)] italic text-[8.5px]">← {c.note}</span>}
          </div>
        ))}
      </div>
      <div className="text-[var(--color-dim)]">
        出场: stop <span className="text-[var(--color-red)]">{spec.exit?.stop?.type} {spec.exit?.stop?.value}</span>
        {' · '}target <span className="text-[var(--color-green)]">{spec.exit?.target?.type} {spec.exit?.target?.value}</span>
        {spec.exit?.time_stop_bars ? <span> · time-stop {spec.exit.time_stop_bars} bars</span> : null}
      </div>
    </div>
  )
}

// Direct quant_spec editor — adjust thresholds/conditions WITHOUT rewriting
// the NL (no lossy re-distill). Saves a new version; re-backtest immediately.
const OP_OPTIONS = ['<', '>', '<=', '>=', 'cross_above', 'cross_below', '==']
function SpecEditor({ setup, onClose }: { setup: TradingSetup; onClose: () => void }) {
  const save = useSaveTradingSetup()
  const [spec, setSpec] = useState<QuantSpec>(() => JSON.parse(JSON.stringify(setup.quant_spec ?? {})))
  const conds = spec.entry?.conditions ?? []

  function setConds(next: typeof conds) {
    setSpec({ ...spec, entry: { ...(spec.entry ?? {}), conditions: next } })
  }
  function updateCond(i: number, patch: Partial<typeof conds[number]>) {
    setConds(conds.map((c, j) => j === i ? { ...c, ...patch } : c))
  }
  const inp = "bg-[var(--color-panel)] border border-[var(--color-border)] rounded px-1 py-0.5 text-[var(--color-text)] text-[9.5px]"

  return (
    <div className="bg-[var(--color-bg)] rounded border border-[var(--color-accent)]/30 p-2 space-y-2 text-[9.5px]">
      <div className="flex gap-2 items-center flex-wrap">
        <label>timeframe <select className={inp} value={spec.timeframe ?? '1d'} onChange={e => setSpec({ ...spec, timeframe: e.target.value })}>
          {['1d', '1h', '30m', '15m', '1wk'].map(t => <option key={t}>{t}</option>)}</select></label>
        <label>lookback <select className={inp} value={spec.lookback ?? '1y'} onChange={e => setSpec({ ...spec, lookback: e.target.value })}>
          {['6mo', '1y', '2y', '3y', '5y'].map(t => <option key={t}>{t}</option>)}</select></label>
        <label>逻辑 <select className={inp} value={spec.entry?.logic ?? 'AND'} onChange={e => setSpec({ ...spec, entry: { ...(spec.entry ?? {}), logic: e.target.value } })}>
          <option>AND</option><option>OR</option></select></label>
      </div>
      <div className="space-y-1">
        <div className="text-[var(--color-dim)]">进场条件:</div>
        {conds.map((c, i) => (
          <div key={i} className="flex gap-1 items-center flex-wrap">
            <input className={`${inp} w-24`} value={c.left} placeholder="rsi(14)" onChange={e => updateCond(i, { left: e.target.value })} />
            <select className={inp} value={c.op} onChange={e => updateCond(i, { op: e.target.value })}>
              {OP_OPTIONS.map(o => <option key={o}>{o}</option>)}</select>
            <input className={`${inp} w-24`} value={String(c.right)} placeholder="30 或 sma(50)" onChange={e => updateCond(i, { right: e.target.value })} />
            <input className={`${inp} w-12`} type="number" step="0.1" value={c.rmult ?? ''} placeholder="×" title="右值倍数(如成交量×1.5)" onChange={e => updateCond(i, { rmult: e.target.value ? parseFloat(e.target.value) : undefined })} />
            <input className={`${inp} flex-1 min-w-[100px]`} value={c.note ?? ''} placeholder="为什么/出处" onChange={e => updateCond(i, { note: e.target.value })} />
            <button onClick={() => setConds(conds.filter((_, j) => j !== i))} className="text-[var(--color-red)]">✕</button>
          </div>
        ))}
        <button onClick={() => setConds([...conds, { left: 'close', op: '>', right: 'sma(50)' }])}
          className="text-[var(--color-accent)]">+ 加条件</button>
      </div>
      <div className="flex gap-2 items-center flex-wrap border-t border-[var(--color-border)]/40 pt-1.5">
        <label>止损 <select className={inp} value={spec.exit?.stop?.type ?? 'atr'} onChange={e => setSpec({ ...spec, exit: { ...(spec.exit ?? {}), stop: { type: e.target.value, value: spec.exit?.stop?.value ?? 2 } } })}>
          <option value="atr">atr</option><option value="pct">pct</option></select></label>
        <input className={`${inp} w-14`} type="number" step="0.1" value={spec.exit?.stop?.value ?? 2}
          onChange={e => setSpec({ ...spec, exit: { ...(spec.exit ?? {}), stop: { type: spec.exit?.stop?.type ?? 'atr', value: parseFloat(e.target.value) } } })} />
        <label>目标 <select className={inp} value={spec.exit?.target?.type ?? 'rr'} onChange={e => setSpec({ ...spec, exit: { ...(spec.exit ?? {}), target: { type: e.target.value, value: spec.exit?.target?.value ?? 2 } } })}>
          <option value="rr">rr</option><option value="pct">pct</option></select></label>
        <input className={`${inp} w-14`} type="number" step="0.1" value={spec.exit?.target?.value ?? 2}
          onChange={e => setSpec({ ...spec, exit: { ...(spec.exit ?? {}), target: { type: spec.exit?.target?.type ?? 'rr', value: parseFloat(e.target.value) } } })} />
        <label>time-stop <input className={`${inp} w-12`} type="number" value={spec.exit?.time_stop_bars ?? 0}
          onChange={e => setSpec({ ...spec, exit: { ...(spec.exit ?? {}), time_stop_bars: parseInt(e.target.value) || 0 } })} /></label>
      </div>
      <div className="flex gap-2">
        <button onClick={() => save.mutate({ setup_id: setup.setup_id, body: { quant_spec: spec, change_note: 'edit spec directly' } }, { onSuccess: onClose })}
          disabled={save.isPending}
          className="text-[10px] px-2.5 py-1 rounded bg-[var(--color-green)]/20 text-[var(--color-green)] border border-[var(--color-green)]/40">
          {save.isPending ? '保存中…' : '💾 保存公式 (回测见效)'}</button>
        <button onClick={onClose} className="text-[10px] px-2 py-1 rounded border border-[var(--color-border)] text-[var(--color-dim)]">取消</button>
      </div>
    </div>
  )
}

function BacktestResultView({ res }: { res: BacktestResult }) {
  const [showTrades, setShowTrades] = useState(false)
  if (res.error) return <span className="text-[9px] text-[var(--color-red)]">{res.error}</span>
  const s = res.stats
  if (!s) return null
  const trades = res.trades ?? []
  return (
    <span className="text-[9.5px] flex flex-wrap gap-x-2.5 items-baseline">
      <span>胜率 <b className={(s.win_rate ?? 0) >= 50 ? 'text-[var(--color-green)]' : 'text-[var(--color-red)]'}>{s.win_rate ?? '—'}%</b></span>
      <span>{s.n_trades} 笔</span>
      <span>avgR <b>{s.avg_R ?? '—'}</b></span>
      <span>总收益 <b className={s.total_return_pct >= 0 ? 'text-[var(--color-green)]' : 'text-[var(--color-red)]'}>{s.total_return_pct}%</b></span>
      <span>maxDD {s.max_drawdown_pct}%</span>
      {s.buy_hold_pct != null && (
        <span title="同窗口买入持有该股的收益" className={s.beats_buy_hold ? 'text-[var(--color-green)]' : 'text-[var(--color-red)]'}>
          {s.beats_buy_hold ? '✓跑赢' : '✗跑输'}买入持有({s.buy_hold_pct}%)
        </span>
      )}
      {trades.length > 0 && (
        <button onClick={() => setShowTrades(v => !v)}
          className="text-[var(--color-accent)] hover:underline">{showTrades ? '收起明细' : `🔍 ${trades.length} 笔明细`}</button>
      )}
      {res.robustness && res.is_stats && res.oos_stats && (
        <span className="w-full flex flex-wrap gap-x-2 items-center">
          <span className={
            res.robustness.verdict === 'overfit' ? 'text-[var(--color-red)]'
              : res.robustness.verdict === 'weak' ? 'text-[var(--color-yellow)]'
              : res.robustness.verdict === 'robust' ? 'text-[var(--color-green)]' : 'text-[var(--color-dim)]'
          }>
            {res.robustness.verdict === 'overfit' ? '⚠️ 过拟合' : res.robustness.verdict === 'weak' ? '⚠ 偏弱'
              : res.robustness.verdict === 'robust' ? '✓ 稳健' : '— 样本不足'}
          </span>
          <span className="text-[var(--color-dim)] text-[9px]">
            样本内 {res.is_stats.n_trades}笔/avgR{res.is_stats.avg_R ?? '—'} · 样本外 {res.oos_stats.n_trades}笔/avgR{res.oos_stats.avg_R ?? '—'}
            {res.oos_cutoff ? ` (切于 ${res.oos_cutoff})` : ''}
          </span>
        </span>
      )}
      {s.assumptions && <span className="text-[var(--color-dim)] italic w-full">⚠️ {s.assumptions}</span>}
      {showTrades && (
        <div className="w-full mt-1 space-y-1">
          {trades.slice(0, 30).map((t, i) => (
            <div key={i} className="bg-[var(--color-bg)] rounded px-1.5 py-1 border border-[var(--color-border)]/40">
              <div className="flex flex-wrap gap-x-2 text-[9px]">
                <span className="font-mono">{t.entry_date}→{t.exit_date}</span>
                <span className={t.return_pct >= 0 ? 'text-[var(--color-green)]' : 'text-[var(--color-red)]'}>
                  {t.return_pct >= 0 ? '+' : ''}{t.return_pct}% ({t.R}R)
                </span>
                <span className="text-[var(--color-dim)]">{t.reason} · {t.bars_held}d</span>
              </div>
              {t.entry_detail && t.entry_detail.length > 0 && (
                <div className="mt-0.5 space-y-0.5">
                  {t.entry_detail.map((d, j) => (
                    <div key={j} className="text-[8.5px] font-mono text-[var(--color-dim)]">
                      <span className="text-[var(--color-accent)]">{d.left}</span>
                      {d.lval != null ? `=${d.lval}` : ''} {d.op} <span className="text-[var(--color-yellow)]">{d.right}</span>
                      {d.rval != null ? `=${d.rval}` : ''}
                      {d.note ? <span className="italic"> ← {d.note}</span> : null}
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </span>
  )
}

// ── Inline SVG price chart with entry/exit trigger markers ──
function SetupChart({ data }: { data: TradingChartData }) {
  if (data.error) return <div className="text-[9px] text-[var(--color-red)]">{data.error}</div>
  const series = data.series ?? []
  const trades = data.trades ?? []
  if (series.length < 2) return <div className="text-[9px] text-[var(--color-dim)]">数据不足</div>

  const W = 760, H = 120, padL = 4, padR = 4, padT = 8, padB = 14
  const closes = series.map(p => p.close)
  const lo = Math.min(...closes), hi = Math.max(...closes)
  const span = hi - lo || 1
  const dateIdx = new Map(series.map((p, i) => [p.date, i]))
  const x = (i: number) => padL + (i / (series.length - 1)) * (W - padL - padR)
  const y = (v: number) => padT + (1 - (v - lo) / span) * (H - padT - padB)
  const path = series.map((p, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(p.close).toFixed(1)}`).join(' ')

  // marker positions: nearest series index for each trade's entry/exit date
  const nearest = (date: string): number | null => {
    if (dateIdx.has(date)) return dateIdx.get(date)!
    let best: number | null = null
    for (let i = 0; i < series.length; i++) if (series[i].date <= date) best = i
    return best
  }

  return (
    <div className="bg-[var(--color-bg)] rounded border border-[var(--color-border)]/50 p-1.5">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ height: 120 }} preserveAspectRatio="none">
        <polyline points={path.replace(/[ML]/g, ' ')} fill="none" stroke="var(--color-dim)" strokeWidth="1" opacity="0.85" />
        {trades.map((t, i) => {
          const ei = nearest(t.entry_date), xi = nearest(t.exit_date)
          const win = t.return_pct >= 0
          return (
            <g key={i}>
              {ei != null && <circle cx={x(ei)} cy={y(t.entry_px)} r="3" fill="var(--color-accent)" />}
              {xi != null && <circle cx={x(xi)} cy={y(t.exit_px)} r="3"
                fill={win ? 'var(--color-green)' : 'var(--color-red)'} />}
              {ei != null && xi != null && (
                <line x1={x(ei)} y1={y(t.entry_px)} x2={x(xi)} y2={y(t.exit_px)}
                  stroke={win ? 'var(--color-green)' : 'var(--color-red)'} strokeWidth="1" opacity="0.5" />
              )}
            </g>
          )
        })}
      </svg>
      <div className="flex gap-3 text-[8.5px] text-[var(--color-dim)] mt-0.5">
        <span>{data.symbol} · {series[0].date} → {series[series.length - 1].date}</span>
        <span><span className="text-[var(--color-accent)]">●</span> 进场</span>
        <span><span className="text-[var(--color-green)]">●</span> 盈利出</span>
        <span><span className="text-[var(--color-red)]">●</span> 亏损出</span>
        <span className="ml-auto">{trades.length} 笔触发</span>
      </div>
    </div>
  )
}

// ── Setup editor (create or edit) with NL→quant distillation ──
function SetupEditor({ setup, onClose }: { setup?: TradingSetup; onClose: () => void }) {
  const save = useSaveTradingSetup()
  const distill = useDistillSetup()
  const [name, setName] = useState(setup?.name ?? '')
  const [nl, setNl] = useState(setup?.nl_description ?? '')
  const [status, setStatus] = useState<TradingSetup['status']>(setup?.status ?? 'idea')
  const [spec, setSpec] = useState<QuantSpec | undefined>(setup?.quant_spec)

  function doDistill() {
    distill.mutate({ nl_description: nl, current_spec: spec }, {
      onSuccess: (r) => setSpec(r.quant_spec),
    })
  }
  function doSave() {
    save.mutate({
      setup_id: setup?.setup_id,
      body: { name: name || '未命名 setup', nl_description: nl, status, quant_spec: spec, change_note: setup ? 'edit' : 'create' },
    }, { onSuccess: onClose })
  }

  return (
    <div className="border-t border-[var(--color-border)] p-2.5 space-y-2 bg-[var(--color-bg)]">
      <div className="flex gap-2 items-center">
        <input placeholder="setup 名称" value={name} onChange={(e) => setName(e.target.value)}
          className="flex-1 text-[11px] bg-[var(--color-panel)] border border-[var(--color-border)] rounded px-2 py-1 text-[var(--color-text)]" />
        <select value={status} onChange={(e) => setStatus(e.target.value as TradingSetup['status'])}
          className="text-[10px] bg-[var(--color-panel)] border border-[var(--color-border)] rounded px-1.5 py-1 text-[var(--color-text)]">
          <option value="idea">idea</option>
          <option value="paper">paper</option>
          <option value="live">live</option>
          <option value="retired">retired</option>
        </select>
      </div>
      <textarea placeholder="用自然语言描述入场/出场规则。例: 当 RSI(14) 跌破 30 超卖，且收盘价在 200 日均线上方时买入；用 2 倍 ATR 止损，目标盈亏比 2:1，最多持有 15 天。"
        value={nl} onChange={(e) => setNl(e.target.value)} rows={3}
        className="w-full text-[11px] bg-[var(--color-panel)] border border-[var(--color-border)] rounded px-2 py-1 text-[var(--color-text)] resize-y" />
      <div className="flex gap-2 items-center flex-wrap">
        <button onClick={doDistill} disabled={distill.isPending || !nl.trim()}
          className="text-[10px] px-2.5 py-1 rounded bg-[var(--color-accent)]/20 text-[var(--color-accent)] border border-[var(--color-accent)]/40">
          {distill.isPending ? '🧪 蒸馏中…' : '🧪 蒸馏成量化公式'}</button>
        {distill.isError && <span className="text-[9px] text-[var(--color-red)]">蒸馏失败 (LLM 未启动?): {String(distill.error?.message).slice(0, 80)}</span>}
        <button onClick={doSave} disabled={save.isPending}
          className="text-[10px] px-2.5 py-1 rounded bg-[var(--color-green)]/20 text-[var(--color-green)] border border-[var(--color-green)]/40 ml-auto">
          {save.isPending ? '保存中…' : '💾 保存 setup'}</button>
        <button onClick={onClose} className="text-[10px] px-2 py-1 rounded border border-[var(--color-border)] text-[var(--color-dim)]">取消</button>
      </div>
      {spec && (
        <div>
          <div className="text-[9px] text-[var(--color-dim)] mb-1">蒸馏结果 (可保存后回测):</div>
          <SpecView spec={spec} />
        </div>
      )}
    </div>
  )
}

// ════════════════════════════════════════════════════════════
//  Combos — modular strategy combinations (add/remove) + portfolio backtest
// ════════════════════════════════════════════════════════════
function CombosPanel({ projectId }: { projectId: string }) {
  const { data } = useCombos()
  const { data: setupsData } = useTradingSetups()
  const saveCombo = useSaveCombo()
  const combos = data?.combos ?? []
  const setups = setupsData?.setups ?? []

  return (
    <Section title="🧩 策略组合 (Combo)" subtitle="把多个策略组成一个系统，共享资金回测 → 看分散效果"
      right={
        <button onClick={() => saveCombo.mutate({ body: { name: '新组合', members: [], symbols: [], status: 'idea' } })}
          className="text-[10px] px-2 py-0.5 rounded bg-[var(--color-accent)]/20 text-[var(--color-accent)] border border-[var(--color-accent)]/40">+ 新组合</button>
      }>
      {combos.length === 0 ? (
        <div className="text-[10.5px] text-[var(--color-dim)] py-2">还没有组合。点 "+ 新组合"，从策略库挑几个策略组成一个系统。<b>组合会自动保存，刷新后还在。</b></div>
      ) : (
        <div className="space-y-2">
          {combos.map(c => <ComboCard key={c.combo_id} combo={c} allSetups={setups} projectId={projectId} />)}
        </div>
      )}
    </Section>
  )
}

function ComboCard({ combo, allSetups, projectId }: { combo: TradingCombo; allSetups: TradingSetup[]; projectId: string }) {
  const save = useSaveCombo()
  const del = useDeleteCombo()
  const bt = useBacktestCombo()
  const wl = useWatchlist(projectId)
  const members = combo.members ?? []
  const symbols = combo.symbols ?? []
  const memberIds = new Set(members.map(m => m.setup_id))
  const available = allSetups.filter(s => !memberIds.has(s.setup_id))
  const wlTickers: string[] = ((wl.data?.entries ?? []) as Array<{ symbol?: string }>).map(e => (e.symbol || '').toUpperCase()).filter(Boolean)
  const [symInput, setSymInput] = useState('')

  function addMember(setupId: string) {
    save.mutate({ combo_id: combo.combo_id, body: { members: [...members, { setup_id: setupId, weight: 1 }] } })
  }
  function removeMember(setupId: string) {
    save.mutate({ combo_id: combo.combo_id, body: { members: members.filter(m => m.setup_id !== setupId) } })
  }
  function setWeight(setupId: string, w: number) {
    save.mutate({ combo_id: combo.combo_id, body: { members: members.map(m => m.setup_id === setupId ? { ...m, weight: w } : m) } })
  }
  function changeStatus(next: string) {
    // real-money safety: going 'live' is the only status that would (with a
    // broker) place real orders → require explicit confirmation.
    if (next === 'live' && !window.confirm('设为 live = 真实下单意图。当前无 IBKR 连接，仍为模拟(paper)。确认切到 live?')) return
    save.mutate({ combo_id: combo.combo_id, body: { status: next as TradingCombo['status'] } })
  }
  function addSymbols(list: string[]) {
    const merged = Array.from(new Set([...symbols, ...list.map(s => s.toUpperCase().trim()).filter(Boolean)]))
    if (merged.length !== symbols.length) save.mutate({ combo_id: combo.combo_id, body: { symbols: merged } })
  }
  function commitSymInput() {
    if (symInput.trim()) addSymbols(symInput.split(/[,，\s]+/))
    setSymInput('')
  }
  function removeSymbol(s: string) {
    save.mutate({ combo_id: combo.combo_id, body: { symbols: symbols.filter(x => x !== s) } })
  }
  const nameOf = (id: string) => allSetups.find(s => s.setup_id === id)?.name ?? id
  const canBacktest = members.length > 0 && symbols.length > 0

  return (
    <div className="border border-[var(--color-border)] rounded bg-[var(--color-panel)]/40 p-2.5 space-y-2">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-[8px] text-[var(--color-dim)]">名称</span>
        <input defaultValue={combo.name} onBlur={e => { if (e.target.value !== combo.name) save.mutate({ combo_id: combo.combo_id, body: { name: e.target.value } }) }}
          className="text-[11px] font-semibold bg-[var(--color-bg)] border border-[var(--color-border)] rounded px-1.5 py-0.5 text-[var(--color-text)] focus:border-[var(--color-accent)] outline-none" />
        <select value={combo.status} onChange={e => changeStatus(e.target.value)}
          className="text-[9px] bg-[var(--color-bg)] border border-[var(--color-border)] rounded px-1 py-0.5 text-[var(--color-text)]">
          {['idea', 'paper', 'live', 'retired'].map(s => <option key={s}>{s}</option>)}</select>
        <span className="text-[8px] text-[var(--color-green)]" title="组合改动自动写库，刷新后还在">✓ 自动保存</span>
        {combo.stats && combo.stats.n_trades > 0 && (
          <span className="text-[9px] text-[var(--color-dim)]">上次组合回测: {combo.stats.win_rate}% · {combo.stats.n_trades}笔 · 收益{combo.stats.total_return_pct}% · maxDD{combo.stats.max_drawdown_pct}%</span>
        )}
        <button onClick={() => { window.confirm(`删除组合「${combo.name}」?`) && del.mutate(combo.combo_id) }}
          className="ml-auto text-[9px] px-1.5 py-0.5 rounded border border-[var(--color-red)]/40 text-[var(--color-red)]">删</button>
      </div>
      {/* members */}
      <div className="flex flex-wrap gap-1 items-center text-[9.5px]">
        <span className="text-[var(--color-dim)] w-[52px]">成员策略</span>
        {members.length === 0 && <span className="text-[var(--color-dim)] italic">（空，从右边下拉加）</span>}
        {members.map(m => (
          <span key={m.setup_id} className="px-1.5 py-0.5 rounded bg-[var(--color-accent)]/15 text-[var(--color-accent)] flex items-center gap-1">
            {nameOf(m.setup_id)}
            <span className="text-[var(--color-dim)]" title="权重（影响该策略的资金分配）">×</span>
            <input type="number" step="0.5" min="0.5" defaultValue={m.weight ?? 1}
              onBlur={e => { const w = parseFloat(e.target.value); if (w && w !== (m.weight ?? 1)) setWeight(m.setup_id, w) }}
              className="w-9 bg-[var(--color-bg)] border border-[var(--color-border)] rounded px-0.5 text-[var(--color-text)] text-[8.5px]" />
            <button onClick={() => removeMember(m.setup_id)} className="text-[var(--color-red)]">✕</button>
          </span>
        ))}
        {available.length > 0 && (
          <select value="" onChange={e => e.target.value && addMember(e.target.value)}
            className="text-[9px] bg-[var(--color-bg)] border border-[var(--color-border)] rounded px-1 py-0.5 text-[var(--color-accent)]">
            <option value="">+ 加策略</option>
            {available.map(s => <option key={s.setup_id} value={s.setup_id}>{s.name}</option>)}</select>
        )}
      </div>
      {/* symbols — clear input + add button + watchlist quick-add */}
      <div className="flex flex-wrap gap-1 items-center text-[9.5px]">
        <span className="text-[var(--color-dim)] w-[52px]">分配标的</span>
        {symbols.map(s => (
          <span key={s} className="px-1.5 py-0.5 rounded bg-[var(--color-panel)] font-mono flex items-center gap-1">
            {s}<button onClick={() => removeSymbol(s)} className="text-[var(--color-red)]">✕</button>
          </span>
        ))}
        <input value={symInput} onChange={e => setSymInput(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') commitSymInput() }}
          placeholder="输入代码如 AAPL，回车或点添加"
          className="w-44 bg-[var(--color-bg)] border border-[var(--color-border)] rounded px-1.5 py-0.5 font-mono text-[var(--color-text)]" />
        <button onClick={commitSymInput} disabled={!symInput.trim()}
          className="text-[9px] px-1.5 py-0.5 rounded bg-[var(--color-accent)]/20 text-[var(--color-accent)] border border-[var(--color-accent)]/40">添加</button>
        {wlTickers.length > 0 && (
          <button onClick={() => addSymbols(wlTickers)}
            className="text-[9px] px-1.5 py-0.5 rounded border border-[var(--color-border)] text-[var(--color-dim)] hover:text-[var(--color-text)]"
            title={`加入 watchlist 全部 ${wlTickers.length} 个`}>+ 用 watchlist ({wlTickers.length})</button>
        )}
      </div>
      {/* backtest — never silently disabled; explain what's missing */}
      <div className="flex items-center gap-2 flex-wrap">
        <button onClick={() => canBacktest && bt.mutate({ combo_id: combo.combo_id })} disabled={bt.isPending}
          className={`text-[10px] px-2 py-0.5 rounded border ${canBacktest ? 'border-[var(--color-accent)]/40 text-[var(--color-accent)]' : 'border-[var(--color-border)] text-[var(--color-dim)]'}`}>
          {bt.isPending ? '⏳ 组合回测中…(多策略×多标的, 约10-20秒)' : '▶ 组合回测 (共享资金)'}</button>
        {!canBacktest && <span className="text-[9px] text-[var(--color-yellow)]">← 先加{members.length === 0 ? '成员策略' : ''}{members.length === 0 && symbols.length === 0 ? ' + ' : ''}{symbols.length === 0 ? '分配标的' : ''}</span>}
        {bt.data?.error && <span className="text-[9px] text-[var(--color-red)]">{bt.data.error}</span>}
      </div>
      {bt.isPending && <div className="text-[9px] text-[var(--color-dim)]">跑组合回测要把每个成员策略在每个标的上回放，请稍候…</div>}
      {bt.data && !bt.data.error && <ComboBacktestView res={bt.data} />}
    </div>
  )
}

function ComboBacktestView({ res }: { res: ComboBacktest }) {
  const s = res.stats
  const curve = res.equity_curve ?? []
  return (
    <div className="bg-[var(--color-bg)] rounded border border-[var(--color-border)]/50 p-2 space-y-1.5">
      {s && (
        <div className="text-[9.5px] flex flex-wrap gap-x-2.5">
          <span>组合胜率 <b className={(s.win_rate ?? 0) >= 50 ? 'text-[var(--color-green)]' : 'text-[var(--color-red)]'}>{s.win_rate ?? '—'}%</b></span>
          <span>{s.n_trades} 笔</span><span>avgR {s.avg_R ?? '—'}</span>
          <span>总收益 <b className={(s.total_return_pct ?? 0) >= 0 ? 'text-[var(--color-green)]' : 'text-[var(--color-red)]'}>{s.total_return_pct}%</b></span>
          <span className="text-[var(--color-green)]">maxDD {s.max_drawdown_pct}%</span>
          {s.buy_hold_pct != null && (
            <span className={s.beats_buy_hold ? 'text-[var(--color-green)]' : 'text-[var(--color-red)]'}>
              {s.beats_buy_hold ? '✓跑赢' : '✗跑输'}买入持有({s.buy_hold_pct}%)
            </span>
          )}
        </div>
      )}
      {curve.length > 1 && <EquityCurve curve={curve} capital={res.capital ?? 100000} />}
      {res.contributions && res.contributions.length > 0 && (
        <div className="text-[9px] text-[var(--color-dim)]">
          各策略贡献: {res.contributions.map(c => `${c.name}(${c.n}笔${c.win_rate != null ? '/' + c.win_rate + '%' : ''})`).join(' · ')}
        </div>
      )}
      {s?.assumptions && <div className="text-[8.5px] text-[var(--color-dim)] italic">⚠️ {s.assumptions}</div>}
    </div>
  )
}

function EquityCurve({ curve, capital }: { curve: { date: string; equity: number }[]; capital: number }) {
  const W = 760, H = 90, padT = 6, padB = 6
  const eq = curve.map(p => p.equity)
  const lo = Math.min(capital, ...eq), hi = Math.max(capital, ...eq), span = hi - lo || 1
  const x = (i: number) => (i / (curve.length - 1)) * W
  const y = (v: number) => padT + (1 - (v - lo) / span) * (H - padT - padB)
  const path = curve.map((p, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(p.equity).toFixed(1)}`).join(' ')
  const baseY = y(capital)
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ height: 90 }} preserveAspectRatio="none">
      <line x1="0" y1={baseY} x2={W} y2={baseY} stroke="var(--color-dim)" strokeWidth="0.5" strokeDasharray="3 3" opacity="0.5" />
      <polyline points={path.replace(/[ML]/g, ' ')} fill="none" stroke="var(--color-green)" strokeWidth="1.2" />
    </svg>
  )
}

// ════════════════════════════════════════════════════════════
//  Combo Optimizer — one-click test ALL combinations, rank them
// ════════════════════════════════════════════════════════════
interface OptRow {
  member_ids: string[]; names: string[]; size: number; is_single: boolean
  stats: BacktestStats; score: number; equity?: { date: string; equity: number }[]
  start?: string; end?: string; n_bars?: number
}
function ComboOptimizerPanel({ projectId }: { projectId: string }) {
  const saveCombo = useSaveOptimizedCombo()
  const wl = useWatchlist(projectId)
  const [symbols, setSymbols] = useState<string[]>(['AAPL', 'MSFT', 'NVDA'])
  const [maxSize, setMaxSize] = useState(3)
  const [lookback, setLookback] = useState('3y')
  const [running, setRunning] = useState(false)
  const [progress, setProgress] = useState({ done: 0, total: 0 })
  const [rows, setRows] = useState<OptRow[]>([])
  const [sel, setSel] = useState<number | null>(null)
  const [window, setWindow] = useState<{ start?: string; end?: string; bars?: number }>({})
  const wlTickers = ((wl.data?.entries ?? []) as Array<{ symbol?: string }>).map(e => e.symbol).filter(Boolean) as string[]

  async function run() {
    if (symbols.length === 0) { toast('先加至少 1 个标的', 'error'); return }
    setRunning(true); setRows([]); setSel(null); setProgress({ done: 0, total: 0 })
    try {
      const plan = await fetchOptimizePlan(symbols.join(','), maxSize)
      if (plan.error) { toast(plan.error, 'error'); setRunning(false); return }
      setProgress({ done: 0, total: plan.subsets.length })
      toast(`开始测 ${plan.subsets.length} 个组合…`, 'info')
      const collected: OptRow[] = []
      for (let i = 0; i < plan.subsets.length; i++) {
        const sub = plan.subsets[i]
        try {
          const res = await fetchComboAdhoc(sub.member_ids, symbols, lookback)
          if (!res.error && res.stats) {
            const st = res.stats
            const ret = st.total_return_pct || 0, dd = st.max_drawdown_pct || 0, n = st.n_trades || 0
            const score = n >= 5 ? +(ret / Math.max(dd, 1)).toFixed(2) : +((ret / Math.max(dd, 1)) * (n / 5)).toFixed(2)
            collected.push({ ...sub, stats: st, score, equity: res.equity_curve, start: res.start_date, end: res.end_date, n_bars: res.n_bars })
            collected.sort((a, b) => b.score - a.score)
            setRows([...collected])
            if (res.start_date) setWindow({ start: res.start_date, end: res.end_date, bars: res.n_bars })
          }
        } catch { /* skip failed subset */ }
        setProgress({ done: i + 1, total: plan.subsets.length })
      }
      toast(`测完 ${collected.length} 个组合，最优分 ${collected[0]?.score ?? '—'}`, 'success')
    } catch (e) {
      toast(`优化失败: ${String((e as Error)?.message).slice(0, 60)}`, 'error')
    } finally { setRunning(false) }
  }

  const bestSingle = rows.find(r => r.is_single)
  const shortWin = ['1mo', '3mo'].includes(lookback)

  return (
    <Section title="🔬 一键找最优组合 (Optimizer)" subtitle="测所有单策略+组合在同一标的+时间窗，按风险调整收益排名">
      <div className="flex items-center gap-2 mb-2 flex-wrap text-[10px]">
        <span className="text-[var(--color-dim)]">标的</span>
        <SymbolPicker symbols={symbols} onChange={setSymbols} watchlist={wlTickers} />
        <span className="text-[var(--color-dim)]">最多组合</span>
        <select value={maxSize} onChange={e => setMaxSize(parseInt(e.target.value))}
          className="bg-[var(--color-bg)] border border-[var(--color-border)] rounded px-1 py-0.5 text-[var(--color-text)]">
          {[1, 2, 3, 4].map(n => <option key={n} value={n}>{n} 个</option>)}</select>
        <span className="text-[var(--color-dim)]">时间窗</span>
        <select value={lookback} onChange={e => setLookback(e.target.value)}
          className="bg-[var(--color-bg)] border border-[var(--color-border)] rounded px-1 py-0.5 text-[var(--color-text)]">
          {LOOKBACKS.map(l => <option key={l}>{l}</option>)}</select>
        <button onClick={run} disabled={running}
          className="px-2.5 py-1 rounded bg-[var(--color-accent)]/20 text-[var(--color-accent)] border border-[var(--color-accent)]/40">
          {running ? `⏳ ${progress.done}/${progress.total}` : '🔬 一键测所有组合'}</button>
      </div>
      {shortWin && <div className="text-[9px] text-[var(--color-yellow)] mb-1">⚠ 短窗口({lookback}): 长周期指标(如 sma200)需要更多历史，可能触发很少甚至 0 笔 —— 这正是短线回测的坑（样本太少，结论不可信）。</div>}
      {/* progress bar */}
      {running && progress.total > 0 && (
        <div className="mb-2">
          <div className="h-1.5 bg-[var(--color-panel)] rounded overflow-hidden">
            <div className="h-full bg-[var(--color-accent)] transition-all" style={{ width: `${(progress.done / progress.total) * 100}%` }} />
          </div>
          <div className="text-[9px] text-[var(--color-dim)] mt-0.5">测试中 {progress.done}/{progress.total}（每个组合在 {symbols.join(',')} 上跑 {lookback} 回测）…</div>
        </div>
      )}
      {rows.length > 0 && (
        <div className="overflow-x-auto">
          <div className="text-[9px] text-[var(--color-dim)] mb-1">
            已测 <b>{rows.length}</b> 个 · 时间窗 <b className="text-[var(--color-text)]">{window.start} → {window.end}</b>（{window.bars} 交易日）·
            🥇最优: {rows[0]?.is_single ? '单策略' : `组合×${rows[0]?.size}`} · 最优单策略: {bestSingle?.names.join('+') ?? '—'} · 点行看曲线
          </div>
          <table className="w-full text-[9.5px] border-collapse">
            <thead><tr className="text-[var(--color-dim)] text-left border-b border-[var(--color-border)]">
              <th className="py-1 pr-2">#</th><th className="pr-2">类型</th><th className="pr-2">策略 / 组合</th>
              <th className="pr-2 text-right">分</th><th className="pr-2 text-right">收益</th><th className="pr-2 text-right">maxDD</th>
              <th className="pr-2 text-right">avgR</th><th className="pr-2 text-right">笔</th><th className="pr-2"></th>
            </tr></thead>
            <tbody>
              {rows.slice(0, 25).map((r, i) => (
                <tr key={i} onClick={() => setSel(sel === i ? null : i)}
                  className={`border-b border-[var(--color-border)]/30 cursor-pointer hover:bg-[var(--color-panel)]/40 ${i === 0 ? 'bg-[var(--color-green)]/8' : ''} ${sel === i ? 'bg-[var(--color-accent)]/10' : ''}`}>
                  <td className="py-1 pr-2 text-[var(--color-dim)]">{i === 0 ? '🥇' : i + 1}</td>
                  <td className="pr-2"><span className={r.is_single ? 'text-[var(--color-dim)]' : 'text-[var(--color-accent)]'}>{r.is_single ? '单' : `组×${r.size}`}</span></td>
                  <td className="pr-2 text-[var(--color-text)]">{r.names.join(' + ')}</td>
                  <td className="pr-2 text-right font-mono font-semibold">{r.score}</td>
                  <td className={`pr-2 text-right font-mono ${(r.stats.total_return_pct ?? 0) >= 0 ? 'text-[var(--color-green)]' : 'text-[var(--color-red)]'}`}>{r.stats.total_return_pct}%</td>
                  <td className="pr-2 text-right font-mono text-[var(--color-dim)]">{r.stats.max_drawdown_pct}%</td>
                  <td className="pr-2 text-right font-mono">{r.stats.avg_R ?? '—'}</td>
                  <td className="pr-2 text-right font-mono text-[var(--color-dim)]">{r.stats.n_trades}</td>
                  <td className="pr-2">
                    {!r.is_single && (
                      <button onClick={(e) => { e.stopPropagation(); toastify('保存组合', saveCombo.mutateAsync({ member_ids: r.member_ids.join(','), symbols: symbols.join(','), name: r.names.map(m => m.slice(0, 6)).join('+') }), () => '已存为组合').catch(() => {}) }}
                        className="text-[8.5px] text-[var(--color-accent)] hover:underline">+ 存</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {/* selected row's equity curve */}
          {sel != null && rows[sel]?.equity && rows[sel].equity!.length > 1 && (
            <div className="mt-2 bg-[var(--color-bg)] rounded border border-[var(--color-border)]/50 p-2">
              <div className="text-[9px] text-[var(--color-dim)] mb-1">📈 {rows[sel].names.join(' + ')} · 权益曲线 ({rows[sel].start}→{rows[sel].end})</div>
              <EquityCurve curve={rows[sel].equity!} capital={100000} />
            </div>
          )}
          <div className="text-[8.5px] text-[var(--color-dim)] mt-1.5 italic">
            分 = 总收益/最大回撤（风险调整，越高越好，&lt;5笔按样本折扣）。全部模拟，已扣滑点。点任意行看它的权益曲线。
          </div>
        </div>
      )}
    </Section>
  )
}

// ════════════════════════════════════════════════════════════
//  Strategy comparison — all setups on the SAME symbol/period
// ════════════════════════════════════════════════════════════
function StrategyComparePanel() {
  const compare = useCompareSetups()
  const [symbol, setSymbol] = useState('AAPL')
  const [lookback, setLookback] = useState('3y')
  const rows = compare.data?.rows ?? []
  const bestRet = Math.max(0, ...rows.map(r => r.stats?.total_return_pct ?? 0))

  return (
    <Section title="⚖️ 策略对比" subtitle="同一标的+周期下，所有策略 head-to-head（公平对比）">
      <div className="flex items-center gap-2 mb-2 flex-wrap text-[10px]">
        <span className="text-[var(--color-dim)]">标的</span>
        <input value={symbol} onChange={e => setSymbol(e.target.value.toUpperCase())}
          className="w-20 bg-[var(--color-bg)] border border-[var(--color-border)] rounded px-1.5 py-0.5 font-mono text-[var(--color-text)]" />
        <span className="text-[var(--color-dim)]">周期</span>
        <select value={lookback} onChange={e => setLookback(e.target.value)}
          className="bg-[var(--color-bg)] border border-[var(--color-border)] rounded px-1 py-0.5 text-[var(--color-text)]">
          {LOOKBACKS.map(l => <option key={l}>{l}</option>)}
        </select>
        <button onClick={() => compare.mutate({ symbol, lookback })} disabled={compare.isPending}
          className="px-2.5 py-1 rounded bg-[var(--color-accent)]/20 text-[var(--color-accent)] border border-[var(--color-accent)]/40">
          {compare.isPending ? '对比中…' : '⚖️ 对比全部策略'}</button>
      </div>
      {rows.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-[10px] border-collapse">
            <thead>
              <tr className="text-[var(--color-dim)] text-left border-b border-[var(--color-border)]">
                <th className="py-1 pr-2">策略</th><th className="pr-2">状态</th>
                <th className="pr-2 text-right">笔数</th><th className="pr-2 text-right">胜率</th>
                <th className="pr-2 text-right">avgR</th><th className="pr-2 text-right">总收益</th>
                <th className="pr-2 text-right">maxDD</th><th className="pr-2 text-right">评级</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => <CompareRowView key={r.setup_id} r={r} rank={i} bestRet={bestRet} />)}
            </tbody>
          </table>
          <div className="text-[8.5px] text-[var(--color-dim)] mt-1.5 italic">
            ⚖️ 全部在 {compare.data?.symbol} · {compare.data?.lookback} 同基准；评级含样本量置信度（少量交易不会虚高）。
            想把多个策略<b>组合成一个系统</b>(共享资金、合并权益曲线)是更深的 portfolio 回测——要的话我加。
          </div>
        </div>
      )}
      {compare.data && rows.length === 0 && (
        <div className="text-[10px] text-[var(--color-dim)]">没有可对比的 setup（需有 entry 条件）。</div>
      )}
    </Section>
  )
}

function CompareRowView({ r, rank, bestRet }: { r: CompareRow; rank: number; bestRet: number }) {
  const s = r.stats || {}
  const ret = s.total_return_pct ?? 0
  const isBest = rank === 0 && (r.score?.score ?? -1) > 0
  return (
    <tr className={`border-b border-[var(--color-border)]/30 ${isBest ? 'bg-[var(--color-green)]/8' : ''}`}>
      <td className="py-1 pr-2 text-[var(--color-text)]">{isBest ? '🥇 ' : ''}{r.name}</td>
      <td className="pr-2 text-[var(--color-dim)]">{r.status}</td>
      <td className="pr-2 text-right font-mono">{s.n_trades ?? 0}</td>
      <td className="pr-2 text-right font-mono">{s.win_rate != null ? `${s.win_rate}%` : '—'}</td>
      <td className={`pr-2 text-right font-mono ${(s.avg_R ?? 0) >= 0 ? 'text-[var(--color-green)]' : 'text-[var(--color-red)]'}`}>{s.avg_R ?? '—'}</td>
      <td className={`pr-2 text-right font-mono ${ret >= 0 ? 'text-[var(--color-green)]' : 'text-[var(--color-red)]'}`}>
        {ret}%
        <span className="inline-block ml-1 align-middle h-1.5 bg-[var(--color-green)]/40 rounded" style={{ width: bestRet > 0 ? `${Math.max(0, (ret / bestRet) * 24)}px` : '0' }} />
      </td>
      <td className="pr-2 text-right font-mono text-[var(--color-dim)]">{s.max_drawdown_pct ?? '—'}%</td>
      <td className="pr-2 text-right font-mono">{r.score?.grade ?? '—'}</td>
    </tr>
  )
}

// ════════════════════════════════════════════════════════════
//  Today cockpit — one-screen morning view (the daily routine)
// ════════════════════════════════════════════════════════════
function TodayCockpit({ projectId }: { projectId: string }) {
  const { data, isFetching, refetch } = useCockpit(projectId)
  return (
    <Section title={`🌅 交易计划 · ${todayLocal()}`} subtitle="一屏看全：行情 / 持仓(止损·目标·R) / 临近财报 / 待复盘"
      right={<button onClick={() => refetch()} disabled={isFetching}
        className="text-[10px] px-2 py-0.5 rounded border border-[var(--color-border)] text-[var(--color-dim)] hover:text-[var(--color-text)]">{isFetching ? '刷新中…' : '↻ 刷新'}</button>}>
      {!data ? <div className="text-[10px] text-[var(--color-dim)]">{isFetching ? '加载中…(查行情/财报)' : '—'}</div> : (
        <div className="space-y-2 text-[10px]">
          {/* line 1: regime + auto status */}
          <div className="flex items-center gap-3 flex-wrap">
            <span className={data.regime.regime === 'risk_off' ? 'text-[var(--color-red)]' : 'text-[var(--color-green)]'}>
              {data.regime.regime === 'risk_off' ? '🌧 risk-off' : '☀️ risk-on'} ({data.regime.spy}/{data.regime.spy_sma200})
            </span>
            <span className={data.halted ? 'text-[var(--color-red)]' : data.auto_armed ? 'text-[var(--color-green)]' : 'text-[var(--color-yellow)]'}>
              {data.halted ? '🛑 已停止' : data.auto_armed ? '● 自动进场武装' : '🔌 自动进场已断开'}
            </span>
            <span className="text-[var(--color-dim)]">持仓 {data.n_positions} · 待复盘日志 {data.open_journal}</span>
            {data.venue === 'ibkr'
              ? <span className={data.ibkr_connected ? 'text-[var(--color-green)]' : 'text-[var(--color-red)]'}>
                  🔗 真相=IBKR {data.account ? `${data.account}` : ''} {data.is_paper ? '(paper)' : data.account ? '(⚠真实)' : ''}{data.net_liquidation != null ? ` · NetLiq $${Math.round(data.net_liquidation).toLocaleString()}` : ''}{!data.ibkr_connected ? ' · 未连接!' : ''}
                </span>
              : <span className="text-[var(--color-dim)]">真相=模拟引擎</span>}
          </div>
          {/* held into earnings — high priority warning */}
          {data.held_into_earnings.length > 0 && (
            <div className="text-[var(--color-red)]">⚠️ 持仓临近财报（考虑离场，别持仓过 earnings）: {data.held_into_earnings.map(e => `${e.symbol} ${e.days_until}d`).join(' · ')}</div>
          )}
          {/* positions cockpit */}
          {data.positions.length > 0 && (
            <table className="w-full text-[9.5px] border-collapse">
              <thead><tr className="text-[var(--color-dim)] text-left border-b border-[var(--color-border)]">
                <th className="py-0.5 pr-2">持仓</th><th className="pr-2 text-right">数量</th><th className="pr-2 text-right">成本</th>
                <th className="pr-2 text-right">现价</th><th className="pr-2 text-right">未实现</th>
                <th className="pr-2 text-right">止损</th><th className="pr-2 text-right">目标</th><th className="pr-2 text-right">R</th><th className="pr-2 text-right">天</th>
              </tr></thead>
              <tbody>
                {data.positions.map(p => (
                  <tr key={p.symbol} className="border-b border-[var(--color-border)]/30">
                    <td className="py-0.5 pr-2 font-mono text-[var(--color-text)]">{p.symbol}</td>
                    <td className="pr-2 text-right font-mono">{p.qty}</td>
                    <td className="pr-2 text-right font-mono">{p.entry}</td>
                    <td className="pr-2 text-right font-mono">{p.current ?? '—'}</td>
                    <td className={`pr-2 text-right font-mono ${(p.unrealized_pct ?? 0) >= 0 ? 'text-[var(--color-green)]' : 'text-[var(--color-red)]'}`}>{p.unrealized_pct != null ? `${p.unrealized_pct}%` : '—'}</td>
                    <td className="pr-2 text-right font-mono text-[var(--color-red)]">{p.stop ?? '—'}</td>
                    <td className="pr-2 text-right font-mono text-[var(--color-green)]">{p.target ?? '—'}</td>
                    <td className="pr-2 text-right font-mono">{p.R ?? '—'}</td>
                    <td className="pr-2 text-right font-mono text-[var(--color-dim)]">{p.days ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {data.positions.length === 0 && <div className="text-[var(--color-dim)]">当前无持仓。</div>}
          {/* upcoming earnings on universe */}
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-[var(--color-dim)]">📅 持仓临近财报:</span>
            {data.earnings_soon.length === 0 ? <span className="text-[var(--color-green)]">持仓无临近财报 ✓（新进场已被扫描财报守卫拦截）</span>
              : data.earnings_soon.map(e => (
                <span key={e.symbol} className="px-1.5 py-0.5 rounded bg-[var(--color-yellow)]/15 text-[var(--color-yellow)] font-mono">{e.symbol} {e.days_until}d</span>
              ))}
          </div>
        </div>
      )}
    </Section>
  )
}

// ════════════════════════════════════════════════════════════
//  Trade Journal + Weekly Review (the discipline layer)
// ════════════════════════════════════════════════════════════
const CATALYSTS = ['technical', 'earnings', 'sector', 'macro', 'other']
const EXIT_REASONS = ['target', 'stop', 'time', 'discretionary']
function JournalPanel({ projectId }: { projectId: string }) {
  const { data } = useJournal()
  const save = useSaveJournal()
  const del = useDeleteJournal()
  const sync = useSyncJournal(projectId)
  const { data: weekly } = useJournalWeekly(7)
  const allEntries = data?.entries ?? []
  // filters — search trades over time
  const [days, setDays] = useState(0)          // 0 = all time
  const [statusF, setStatusF] = useState('')    // '' | open | closed
  const [symF, setSymF] = useState('')
  const cutoff = days > 0 ? new Date(Date.now() - days * 86400000).toISOString().slice(0, 10) : ''
  const entries = allEntries.filter(j =>
    (!statusF || j.status === statusF) &&
    (!symF || (j.symbol || '').toUpperCase().includes(symF.toUpperCase())) &&
    (!cutoff || (j.exit_date || j.entry_date || '') >= cutoff))

  return (
    <Section title="📓 交易记录 + 复盘" subtitle="按时间/标的/状态查历史交易；记 thesis/情绪/守纪律/教训 — 慢反馈变可量化 edge"
      right={
        <span className="flex gap-1.5 items-center">
          <button onClick={() => sync.mutate(undefined, { onSuccess: (r) => toast(`同步: 自动平仓 ${r.closed} 笔`, 'success') })} disabled={sync.isPending}
            className="text-[10px] px-2 py-0.5 rounded border border-[var(--color-border)] text-[var(--color-dim)] hover:text-[var(--color-text)]"
            title="把已退出 paper 仓的日志自动标记平仓+填收益">{sync.isPending ? '同步中…' : '↻ 同步平仓'}</button>
          <button onClick={() => { save.mutate({ symbol: '', setup_name: '手动记录', status: 'open', catalyst: 'technical', entry_date: new Date().toISOString().slice(0, 10) }, { onSuccess: () => toast('已新建一条日志，点"标注"填写', 'success') }) }}
            className="text-[10px] px-2 py-0.5 rounded bg-[var(--color-accent)]/20 text-[var(--color-accent)] border border-[var(--color-accent)]/40">+ 手动记一笔</button>
        </span>
      }>
      {/* filter bar — search trades over time */}
      <div className="flex items-center gap-2 mb-2 flex-wrap text-[9.5px]">
        <span className="text-[var(--color-dim)]">时间</span>
        {[[0, '全部'], [7, '近7天'], [30, '近30天'], [90, '近90天']].map(([d, label]) => (
          <button key={d as number} onClick={() => setDays(d as number)}
            className={`px-1.5 py-0.5 rounded border ${days === d ? 'bg-[var(--color-accent)]/20 text-[var(--color-accent)] border-[var(--color-accent)]/40' : 'border-[var(--color-border)] text-[var(--color-dim)]'}`}>{label}</button>
        ))}
        <span className="text-[var(--color-dim)] ml-1">状态</span>
        <select value={statusF} onChange={e => setStatusF(e.target.value)} className="bg-[var(--color-bg)] border border-[var(--color-border)] rounded px-1 py-0.5 text-[var(--color-text)]">
          <option value="">全部</option><option value="open">持仓中</option><option value="closed">已平仓</option></select>
        <input value={symF} onChange={e => setSymF(e.target.value)} placeholder="搜标的" className="w-20 bg-[var(--color-bg)] border border-[var(--color-border)] rounded px-1.5 py-0.5 font-mono text-[var(--color-text)]" />
        <span className="text-[var(--color-dim)] ml-auto">{entries.length}/{allEntries.length} 笔</span>
      </div>
      {/* weekly review summary */}
      {weekly && weekly.n > 0 && (
        <div className="mb-2 text-[10px] bg-[var(--color-panel)]/60 rounded p-2 flex flex-wrap gap-x-3 gap-y-0.5">
          <span className="font-semibold text-[var(--color-text)]">📊 近 {weekly.days} 天复盘:</span>
          <span>{weekly.n} 笔</span>
          <span>胜率 <b className={(weekly.win_rate ?? 0) >= 50 ? 'text-[var(--color-green)]' : 'text-[var(--color-red)]'}>{weekly.win_rate}%</b></span>
          <span>avgR {weekly.avg_R ?? '—'}</span>
          <span>平均收益 {weekly.avg_return_pct}%</span>
          <span>守纪律 <b className={(weekly.followed_plan_pct ?? 0) >= 80 ? 'text-[var(--color-green)]' : 'text-[var(--color-yellow)]'}>{weekly.followed_plan_pct}%</b></span>
          {weekly.by_catalyst?.map(c => <span key={c.catalyst} className="text-[var(--color-dim)]">{c.catalyst}: {c.n}笔/{c.win_rate}%</span>)}
        </div>
      )}
      {weekly && weekly.n === 0 && <div className="mb-2 text-[9px] text-[var(--color-dim)]">近 7 天无已平仓记录。自动进场会自动建日志条目；也可手动记。</div>}
      {entries.length === 0 ? (
        <div className="text-[10.5px] text-[var(--color-dim)] py-2">还没有日志。自动进场时会自动建条目，或点"+ 手动记一笔"。</div>
      ) : (
        <div className="space-y-1.5">
          {entries.slice(0, 30).map(j => <JournalRow key={j.journal_id} j={j} onSave={(f) => save.mutate({ journal_id: j.journal_id, ...f })} onDelete={() => { if (confirm('删除这条日志?')) del.mutate(j.journal_id) }} />)}
        </div>
      )}
    </Section>
  )
}

function JournalRow({ j, onSave, onDelete }: { j: JournalEntry; onSave: (f: Partial<JournalEntry>) => void; onDelete: () => void }) {
  const [open, setOpen] = useState(false)
  const inp = "bg-[var(--color-panel)] border border-[var(--color-border)] rounded px-1 py-0.5 text-[var(--color-text)] text-[9.5px]"
  return (
    <div className="border border-[var(--color-border)] rounded bg-[var(--color-panel)]/40 p-2">
      <div className="flex items-center gap-2 flex-wrap text-[10px]">
        <span className={`px-1.5 py-0.5 rounded text-[8.5px] border ${j.status === 'open' ? 'text-[var(--color-blue)] border-[var(--color-blue)]/40' : 'text-[var(--color-dim)] border-[var(--color-border)]'}`}>{j.status === 'open' ? '持仓中' : '已平仓'}</span>
        <span className="font-mono font-semibold text-[var(--color-text)]">{j.symbol || '—'}</span>
        <span className="text-[var(--color-dim)]">{j.setup_name}</span>
        <span className="text-[var(--color-dim)] text-[9px]">{j.entry_date} @ {j.entry_px}</span>
        {j.status === 'closed' && j.return_pct != null && (
          <span className={j.return_pct >= 0 ? 'text-[var(--color-green)]' : 'text-[var(--color-red)]'}>{j.return_pct >= 0 ? '+' : ''}{j.return_pct}% ({j.r_multiple}R · {j.exit_reason})</span>
        )}
        {j.followed_plan === 1 && <span className="text-[8.5px] text-[var(--color-green)]">✓守纪律</span>}
        {j.followed_plan === 0 && <span className="text-[8.5px] text-[var(--color-red)]">✗破纪律</span>}
        <span className="ml-auto flex gap-1.5">
          <button onClick={() => setOpen(v => !v)} className="text-[9px] text-[var(--color-dim)] hover:text-[var(--color-text)]">{open ? '收起' : '标注'}</button>
          <button onClick={onDelete} className="text-[9px] text-[var(--color-red)]">删</button>
        </span>
      </div>
      {j.thesis && !open && <div className="text-[9px] text-[var(--color-dim)] italic mt-0.5">“{j.thesis}”</div>}
      {open && (
        <div className={`mt-2 space-y-1.5 text-[9.5px] ${nestedRailClass}`}>
          <label className="block"><span className="text-[var(--color-dim)]">thesis (为什么进):</span>
            <textarea defaultValue={j.thesis} onBlur={e => e.target.value !== j.thesis && onSave({ thesis: e.target.value })} rows={2} className={`${inp} w-full mt-0.5 resize-y`} /></label>
          <div className="flex gap-2 flex-wrap items-center">
            <label>catalyst <select defaultValue={j.catalyst || 'technical'} onChange={e => onSave({ catalyst: e.target.value })} className={inp}>{CATALYSTS.map(c => <option key={c}>{c}</option>)}</select></label>
            <label>情绪 <input defaultValue={j.emotion || ''} onBlur={e => e.target.value !== (j.emotion || '') && onSave({ emotion: e.target.value })} placeholder="冷静/FOMO/焦虑" className={`${inp} w-24`} /></label>
            <label>守纪律 <select defaultValue={j.followed_plan == null ? '' : String(j.followed_plan)} onChange={e => onSave({ followed_plan: e.target.value === '' ? null : parseInt(e.target.value) })} className={inp}>
              <option value="">?</option><option value="1">是</option><option value="0">否</option></select></label>
          </div>
          {j.status === 'open' ? (
            <div className="flex gap-2 items-center flex-wrap border-t border-[var(--color-border)]/40 pt-1.5">
              <span className="text-[var(--color-dim)]">平仓:</span>
              <select id={`er-${j.journal_id}`} className={inp} defaultValue="target">{EXIT_REASONS.map(r => <option key={r}>{r}</option>)}</select>
              <input id={`ret-${j.journal_id}`} type="number" step="0.1" placeholder="收益%" className={`${inp} w-16`} />
              <input id={`r-${j.journal_id}`} type="number" step="0.1" placeholder="R" className={`${inp} w-12`} />
              <button onClick={() => {
                const er = (document.getElementById(`er-${j.journal_id}`) as HTMLSelectElement)?.value
                const ret = parseFloat((document.getElementById(`ret-${j.journal_id}`) as HTMLInputElement)?.value)
                const r = parseFloat((document.getElementById(`r-${j.journal_id}`) as HTMLInputElement)?.value)
                onSave({ status: 'closed', exit_reason: er, return_pct: isNaN(ret) ? undefined : ret, r_multiple: isNaN(r) ? undefined : r, exit_date: new Date().toISOString().slice(0, 10) })
              }} className="text-[9px] px-2 py-0.5 rounded bg-[var(--color-green)]/20 text-[var(--color-green)] border border-[var(--color-green)]/40">标记平仓</button>
            </div>
          ) : null}
          <label className="block"><span className="text-[var(--color-dim)]">教训/复盘:</span>
            <textarea defaultValue={j.lesson} onBlur={e => e.target.value !== (j.lesson || '') && onSave({ lesson: e.target.value })} rows={2} className={`${inp} w-full mt-0.5 resize-y`} /></label>
        </div>
      )}
    </div>
  )
}

// ════════════════════════════════════════════════════════════
//  IBKR — READ-ONLY (real account view; never places orders)
// ════════════════════════════════════════════════════════════
function IbkrPanel() {
  const [status, setStatus] = useState<IbkrStatus | null>(null)
  const [acct, setAcct] = useState<IbkrAccount | null>(null)
  const [pos, setPos] = useState<IbkrPositions | null>(null)
  const [orders, setOrders] = useState<IbkrOpenOrders | null>(null)
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [log, setLog] = useState<IbkrLog | null>(null)
  const [logSym, setLogSym] = useState('')
  const [logKind, setLogKind] = useState('')
  const [flex, setFlex] = useState<IbkrFlexStatus | null>(null)
  const [flexTok, setFlexTok] = useState('')
  const [flexQid, setFlexQid] = useState('')
  const [recon, setRecon] = useState<IbkrReconcile | null>(null)
  const [budgetInput, setBudgetInput] = useState('')
  const tstate = useTradingState()

  useEffect(() => { fetchIbkrFlexConfig().then(setFlex).catch(() => {}) }, [])

  async function saveFlex() {
    if (!flexTok.trim() || !flexQid.trim()) { toast('请填 Flex token + query id', 'error'); return }
    setBusy('flexcfg')
    try {
      const r = await postIbkrFlexConfig(flexTok.trim(), flexQid.trim())
      setFlex(r); setFlexTok('')   // clear token from the input after saving
      toast('✅ Flex 凭证已保存（token 不会再回显）', 'success')
    } catch (e) { toast(`保存失败: ${String((e as Error)?.message).slice(0, 40)}`, 'error') }
    finally { setBusy(null) }
  }

  async function syncFlex() {
    setBusy('flexsync')
    try {
      const r = await postIbkrFlexSync()
      if (r.ok) { const a = r.archived || {}; toast(`✅ Flex 已同步：成交${a.trades ?? 0}/持仓${a.positions ?? 0}/现金${a.cash ?? 0}`, 'success'); await loadLog() }
      else toast(`Flex 同步失败: ${(r.error || '').slice(0, 70)}`, 'error')
    } catch (e) { toast(`Flex 同步失败: ${String((e as Error)?.message).slice(0, 40)}`, 'error') }
    finally { setBusy(null) }
  }

  async function reconcile() {
    setBusy('recon'); setRecon(null)
    try {
      const r = await postIbkrReconcile()
      setRecon(r)
      if (!r.ok) toast(`对账失败: ${(r.error || '').slice(0, 70)}`, 'error')
      else if (r.summary?.complete) toast(`✅ 对账完整：${r.summary.matched} 笔与 IBKR 官方账本一致，无遗漏`, 'success')
      else toast(`⚠️ 对账发现 ${r.summary?.flex_only} 笔 IBKR 有、本地无 — 已用 Flex 补全`, 'error')
      await loadLog()
    } catch (e) { toast(`对账失败: ${String((e as Error)?.message).slice(0, 40)}`, 'error') }
    finally { setBusy(null) }
  }
  const venue = tstate.data?.venue || (tstate.data?.ibkr_route ? 'ibkr' : 'sim')
  const isPaper = !!status?.connected && status.is_paper !== false

  async function loadLog() {
    setBusy('log')
    try {
      const r = await fetchIbkrLog({ symbol: logSym.trim().toUpperCase() || undefined, kind: logKind || undefined, limit: 200 })
      setLog(r)
      if (r.n === 0) toast('归档为空（还没有记录过 IBKR 操作）', 'info')
    } catch (e) { toast(`读取归档失败: ${String((e as Error)?.message).slice(0, 40)}`, 'error') }
    finally { setBusy(null) }
  }

  async function snapshot() {
    setBusy('snap')
    try {
      const r = await postIbkrSnapshot()
      if (r.ok) { const c = r.captured || {}; toast(`📸 已归档：账户${c.account ?? 0}/持仓${c.positions ?? 0}/挂单${c.open_orders ?? 0}/成交${c.fills ?? 0}`, 'success'); await loadLog() }
      else toast(`快照失败: ${(r.error || '').slice(0, 50)}`, 'error')
    } catch (e) { toast(`快照失败: ${String((e as Error)?.message).slice(0, 40)}`, 'error') }
    finally { setBusy(null) }
  }

  async function connect() {
    setLoading(true); setAcct(null); setPos(null); setOrders(null)
    try {
      const s = await fetchIbkrStatus(); setStatus(s)
      if (s.connected) {
        toast(s.is_paper ? `IBKR paper 已连接 (${s.accounts?.join(',')})` : 'IBKR 已连接', 'success')
        const [a, p, o] = await Promise.all([fetchIbkrAccount(), fetchIbkrPositions(), fetchIbkrOpenOrders()])
        setAcct(a); setPos(p); setOrders(o)
      } else {
        toast(`IBKR 未连接: ${(s.error || '').slice(0, 50)}`, 'error')
      }
    } catch (e) {
      toast(`IBKR 连接失败: ${String((e as Error)?.message).slice(0, 50)}`, 'error')
    } finally { setLoading(false) }
  }

  async function switchVenue(v: 'sim' | 'ibkr') {
    if (v === venue) return
    setBusy('venue')
    try {
      await postVenue(v)
      await tstate.refetch()
      toast(v === 'ibkr'
        ? '✅ 执行去向=IBKR：自动进场直接下到 IBKR 账户，IBKR 即唯一真相（与真钱同一路径）'
        : '执行去向=模拟引擎（离线/即时成交，仅供回测+干跑）', 'success')
    } catch (e) { toast(`切换失败: ${String((e as Error)?.message).slice(0, 40)}`, 'error') }
    finally { setBusy(null) }
  }

  async function saveBudget() {
    const v = parseFloat(budgetInput)
    if (isNaN(v) || v < 0) { toast('预算需为 ≥0 的数字（0=按 TPS 百分比）', 'error'); return }
    setBusy('budget')
    try {
      await postBudget(v); await tstate.refetch()
      toast(v > 0 ? `✅ 预算 = $${v.toLocaleString()}（风险/单仓% 以此为基数）` : '预算=按 TPS budget_pct% 推算', 'success')
    } catch (e) { toast(`保存失败: ${String((e as Error)?.message).slice(0, 40)}`, 'error') }
    finally { setBusy(null) }
  }

  async function testOrder() {
    setBusy('test')
    try {
      // resting limit far below market → sits PENDING (proves pipe, won't fill)
      const r = await postIbkrTestOrder('AAPL', 1, 1)
      const v = r.verify
      if (v) {
        const n = v.total_confirming_sources ?? 0
        if (v.verdict === 'verified') toast(`✅ 测试单已下 + 双重核对通过 (${n} 个独立来源确认, acct ${r.account})`, 'success')
        else if (v.verdict === 'rejected') toast(`已记录：测试单被 IBKR 拒绝 (一致：账本里也查无此单)。原因多半是 Gateway 还开着 Read-Only`, 'info')
        else toast(`⚠️ 异常：单子已 ack 但 ${n} 个来源都查不到 — 已记 UNCONFIRMED 待排查`, 'error')
      } else if (r.ok) toast(`测试单已下 (acct ${r.account})`, 'success')
      else toast(`测试单失败: ${(r.error || '').slice(0, 60)}`, 'error')
      const o = await fetchIbkrOpenOrders(); setOrders(o); await loadLog()
    } catch (e) { toast(`测试单失败: ${String((e as Error)?.message).slice(0, 40)}`, 'error') }
    finally { setBusy(null) }
  }

  async function cancelAll() {
    setBusy('cancel')
    try {
      const r = await postIbkrCancelAll()
      if (r.ok) { toast(`已撤销 ${r.cancelled ?? 0} 笔挂单`, 'success'); const o = await fetchIbkrOpenOrders(); setOrders(o) }
      else toast(`撤单失败: ${(r.error || '').slice(0, 60)}`, 'error')
    } catch (e) { toast(`撤单失败: ${String((e as Error)?.message).slice(0, 40)}`, 'error') }
    finally { setBusy(null) }
  }

  return (
    <Section title="🔗 IBKR Paper 连接" subtitle="执行去向=IBKR 时，paper 与真钱同一条路径（仅 DU 账户，永不碰真实账户）"
      right={<button onClick={connect} disabled={loading}
        className="text-[10px] px-2.5 py-0.5 rounded bg-[var(--color-accent)]/20 text-[var(--color-accent)] border border-[var(--color-accent)]/40">{loading ? '连接中…(≤6秒)' : '🔗 连接 / 刷新'}</button>}>
      <div className="text-[10px] rounded p-2 border border-[var(--color-yellow)]/40 bg-[var(--color-yellow)]/10 mb-2">
        <b className="text-[var(--color-yellow)]">🛡 双重防护</b>
        <span className="text-[var(--color-dim)]"> — 读取走 <span className="font-mono">readonly=True</span>；唯一的下单路径有<b>硬性 DU 账户闸门</b>：下单前校验所有账户都以 <span className="font-mono">DU</span> 开头（IBKR paper 前缀），一旦检测到真实账户（U…）<b>立即中止、不下任何单</b>。真实账户结构上不可能被触达。</span>
      </div>

      {/* ── Execution venue = single source of truth (ALWAYS visible) ── */}
      <div className="rounded border border-[var(--color-accent)]/40 p-2 mb-2 space-y-1 bg-[var(--color-accent)]/5">
        <div className="flex items-center justify-between gap-2 flex-wrap">
          <b className="text-[11px] text-[var(--color-text)]">⚙️ 执行去向 / 唯一真相</b>
          <div className="flex rounded overflow-hidden border border-[var(--color-border)] text-[10px]">
            <button onClick={() => switchVenue('sim')} disabled={busy === 'venue'}
              className={`px-3 py-0.5 ${venue === 'sim' ? 'bg-[var(--color-accent)]/30 text-[var(--color-accent)] font-semibold' : 'text-[var(--color-dim)]'}`}>模拟引擎</button>
            <button onClick={() => switchVenue('ibkr')} disabled={busy === 'venue'}
              className={`px-3 py-0.5 ${venue === 'ibkr' ? 'bg-[var(--color-green)]/30 text-[var(--color-green)] font-semibold' : 'text-[var(--color-dim)]'}`}>IBKR 账户（沙盒=真实同路径）</button>
          </div>
        </div>
        {venue === 'ibkr'
          ? <div className="text-[9.5px] text-[var(--color-green)] leading-[1.5]">✓ 自动进场直接走 IBKR，Cockpit/盈亏以 IBKR 为唯一真相。<b>这条路径和真钱 100% 相同</b>，唯一区别=登录的账户（paper DU 4002 / live U 4001）。</div>
          : <div className="text-[9.5px] text-[var(--color-dim)] leading-[1.5]">当前=<b>模拟引擎</b>（离线/即时，仅回测+干跑）。要让 paper 与真钱<b>同一条路径</b>（真沙盒），点右侧 <b>IBKR 账户</b>。</div>}
        <div className="flex items-center gap-1.5 flex-wrap text-[10px] pt-0.5">
          <span className="text-[var(--color-dim)]">💰 交易预算(USD)：</span>
          <input value={budgetInput} onChange={e => setBudgetInput(e.target.value)}
            placeholder={String(tstate.data?.trading_budget_usd || 0)} inputMode="decimal"
            className="w-24 px-1.5 py-0.5 rounded bg-[var(--color-bg)] border border-[var(--color-border)] text-[var(--color-text)]" />
          <button onClick={saveBudget} disabled={busy === 'budget'}
            className="px-2 py-0.5 rounded bg-[var(--color-accent)]/15 text-[var(--color-accent)] border border-[var(--color-accent)]/40">
            {busy === 'budget' ? '…' : '设预算'}
          </button>
          <span className="text-[var(--color-dim)]">
            当前 {tstate.data?.trading_budget_usd ? `$${Number(tstate.data.trading_budget_usd).toLocaleString()}` : '按 TPS %（'+'1.5% of NetLiq）'}；风险/单仓 % 以此为基数（0=用百分比）。
          </span>
        </div>
      </div>

      {!status && <div className="text-[10px] text-[var(--color-dim)]">点"连接"读取你的 paper 账户（需先启动 IB Gateway 并用 paper 凭证登录、开 API、端口 4002）。</div>}
      {status && !status.connected && (
        <div className="text-[10px] space-y-1">
          <div className="text-[var(--color-red)]">未连接{status.lib_missing ? '（缺 ib_async/ib_insync 库）' : ''}: {status.error}</div>
          <div className="text-[var(--color-dim)] leading-[1.6]">
            <b>接入步骤</b>：① 启动 <b>IB Gateway</b> 用 <b>paper 凭证</b>登录（模拟交易）；② API 设置里开 <b>Socket Clients + Read-Only API</b>，端口 <b>4002</b>；③ 重启 server（已设 <span className="font-mono">IB_GATEWAY_PORT=4002</span>），再点"连接"。
          </div>
        </div>
      )}
      {status?.connected && (
        <div className="text-[10px] space-y-2">
          <div className={isPaper ? 'text-[var(--color-green)]' : 'text-[var(--color-red)]'}>
            {isPaper ? '✓' : '⚠'} 已连接 · 账户 {status.accounts?.join(', ')} · server v{status.server_version} · {isPaper ? 'PAPER (DU)' : '⚠ 非 paper 账户 — 下单已禁用'}
          </div>
          {acct?.values && (
            <div className="flex flex-wrap gap-x-3 gap-y-0.5">
              {Object.entries(acct.values).map(([k, v]) => (
                <span key={k} className="font-mono"><span className="text-[var(--color-dim)]">{k}</span> {v}</span>
              ))}
            </div>
          )}

          {/* ── Order actions (venue selector is now always-visible above) ── */}
          {isPaper && (
            <div className="rounded border border-[var(--color-border)] p-2 space-y-1.5 bg-[var(--color-panel)]">
              <div className="flex gap-2 flex-wrap">
                <button onClick={testOrder} disabled={!!busy}
                  className="text-[10px] px-2.5 py-0.5 rounded bg-[var(--color-accent)]/15 text-[var(--color-accent)] border border-[var(--color-accent)]/40">
                  {busy === 'test' ? '下单中…' : '🧪 下 1 笔测试挂单 (AAPL @$1，待撤)'}
                </button>
                <button onClick={cancelAll} disabled={!!busy}
                  className="text-[10px] px-2.5 py-0.5 rounded bg-[var(--color-dim)]/15 text-[var(--color-dim)] border border-[var(--color-border)]">
                  {busy === 'cancel' ? '撤销中…' : '🧹 撤销全部挂单'}
                </button>
              </div>
              <div className="text-[9px] text-[var(--color-dim)] leading-[1.5]">
                ⚠️ 若下单报 <span className="font-mono">Read-Only mode (321)</span>：IB Gateway → Configure → Settings → API <b>取消勾选 Read-Only API</b> 保存（DU 账户闸门仍拦截真实单）。行情默认走<b>延迟(~15m)</b>，真实时需 Finnhub 付费 key 或 IBKR 行情订阅。
              </div>
            </div>
          )}

          {/* ── Open orders in IBKR paper ── */}
          {orders?.orders && orders.orders.length > 0 && (
            <table className="w-full text-[9.5px] border-collapse">
              <thead><tr className="text-[var(--color-dim)] text-left border-b border-[var(--color-border)]">
                <th className="py-0.5 pr-2">IBKR 挂单</th><th className="pr-2">方向</th><th className="pr-2 text-right">数量</th><th className="pr-2">类型</th><th className="pr-2 text-right">价</th><th className="pr-2">状态</th>
              </tr></thead>
              <tbody>
                {orders.orders.map((o) => (
                  <tr key={o.order_id} className="border-b border-[var(--color-border)]/30">
                    <td className="py-0.5 pr-2 font-mono text-[var(--color-text)]">{o.symbol}</td>
                    <td className="pr-2">{o.action}</td>
                    <td className="pr-2 text-right font-mono">{o.qty}</td>
                    <td className="pr-2 text-[var(--color-dim)]">{o.type}</td>
                    <td className="pr-2 text-right font-mono">{o.limit ?? o.stop ?? '—'}</td>
                    <td className="pr-2 text-[var(--color-dim)]">{o.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {pos?.positions && pos.positions.length > 0 ? (
            <table className="w-full text-[9.5px] border-collapse">
              <thead><tr className="text-[var(--color-dim)] text-left border-b border-[var(--color-border)]">
                <th className="py-0.5 pr-2">IBKR 持仓</th><th className="pr-2">类型</th><th className="pr-2 text-right">数量</th><th className="pr-2 text-right">均价</th><th className="pr-2">账户</th>
              </tr></thead>
              <tbody>
                {pos.positions.map((p, i) => (
                  <tr key={i} className="border-b border-[var(--color-border)]/30">
                    <td className="py-0.5 pr-2 font-mono text-[var(--color-text)]">{p.symbol}</td>
                    <td className="pr-2 text-[var(--color-dim)]">{p.sec_type}</td>
                    <td className="pr-2 text-right font-mono">{p.position}</td>
                    <td className="pr-2 text-right font-mono">{p.avg_cost}</td>
                    <td className="pr-2 text-[var(--color-dim)] font-mono">{p.account}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : pos && <div className="text-[var(--color-dim)]">IBKR paper 无持仓。</div>}

          <div className="text-[9.5px] text-[var(--color-dim)] leading-[1.5] border-t border-[var(--color-border)] pt-1.5">
            <b>看实时成交/盈亏</b>：进 IBKR paper 后，用 IBKR 自家工具看最爽 — ① <b>TWS</b> 桌面端（最全，实时 tick/盈亏/成交）；② <b>Client Portal</b> 网页（Portfolio / Trades / Performance）；③ <b>IBKR 手机 App</b>。三个都登 <b>paper 账户</b>即可，无需额外配置。本面板这里是只读快照。
          </div>
        </div>
      )}

      {/* ── Durable local archive (queryable even with Gateway OFF) ── */}
      <div className="mt-2 rounded border border-[var(--color-border)] p-2 space-y-1.5 bg-[var(--color-panel)]">
        <div className="flex items-center justify-between gap-2 flex-wrap">
          <b className="text-[var(--color-text)]">📜 IBKR 回溯归档（本地永久存，Gateway 关了也能查）</b>
          <div className="flex gap-1.5">
            <button onClick={snapshot} disabled={!!busy}
              className="text-[10px] px-2 py-0.5 rounded bg-[var(--color-green)]/15 text-[var(--color-green)] border border-[var(--color-green)]/40">
              {busy === 'snap' ? '归档中…' : '📸 存快照'}
            </button>
            <button onClick={loadLog} disabled={!!busy}
              className="text-[10px] px-2 py-0.5 rounded bg-[var(--color-accent)]/15 text-[var(--color-accent)] border border-[var(--color-accent)]/40">
              {busy === 'log' ? '查询…' : '🔍 查归档'}
            </button>
          </div>
        </div>
        <div className="flex gap-1.5 flex-wrap items-center text-[10px]">
          <input value={logSym} onChange={e => setLogSym(e.target.value)} placeholder="标的(如 AAPL)"
            className="w-28 px-1.5 py-0.5 rounded bg-[var(--color-bg)] border border-[var(--color-border)] text-[var(--color-text)]" />
          <select value={logKind} onChange={e => setLogKind(e.target.value)}
            className="px-1.5 py-0.5 rounded bg-[var(--color-bg)] border border-[var(--color-border)] text-[var(--color-text)]">
            <option value="">全部类型</option>
            <option value="order">下单 order</option>
            <option value="fill">成交 fill</option>
            <option value="position">持仓 position</option>
            <option value="open_order">挂单 open_order</option>
            <option value="account">账户 account</option>
          </select>
          {log && <span className="text-[var(--color-dim)]">{log.n} 条</span>}
        </div>
        {log && log.rows.length > 0 && (
          <div className="max-h-64 overflow-y-auto">
            <table className="w-full text-[9px] border-collapse">
              <thead className="sticky top-0 bg-[var(--color-panel)]"><tr className="text-[var(--color-dim)] text-left border-b border-[var(--color-border)]">
                <th className="py-0.5 pr-2">时间(UTC)</th><th className="pr-2">类型</th><th className="pr-2">标的</th><th className="pr-2">方向</th><th className="pr-2 text-right">数量</th><th className="pr-2 text-right">价</th><th className="pr-2">状态</th><th className="pr-2">来源</th>
              </tr></thead>
              <tbody>
                {log.rows.map(r => {
                  const bad = r.status === 'UNCONFIRMED' || r.kind === 'snapshot_error' || r.kind === 'order_error' || r.status === 'exception'
                  const good = r.kind === 'order_verify' && r.status === 'verified'
                  return (
                  <tr key={r.id} className={`border-b border-[var(--color-border)]/30 ${bad ? 'bg-[var(--color-red)]/10' : ''}`}>
                    <td className="py-0.5 pr-2 font-mono text-[var(--color-dim)]">{fmtTs(r.ts)}</td>
                    <td className="pr-2">{r.kind}</td>
                    <td className="pr-2 font-mono text-[var(--color-text)]">{r.symbol || '—'}</td>
                    <td className="pr-2">{r.action || '—'}</td>
                    <td className="pr-2 text-right font-mono">{r.qty ?? '—'}</td>
                    <td className="pr-2 text-right font-mono">{r.price ?? '—'}</td>
                    <td className={`pr-2 ${bad ? 'text-[var(--color-red)] font-semibold' : good ? 'text-[var(--color-green)]' : 'text-[var(--color-dim)]'}`}>{r.status || '—'}</td>
                    <td className="pr-2 text-[var(--color-dim)]">{r.source || '—'}</td>
                  </tr>
                )})}
              </tbody>
            </table>
          </div>
        )}
        {log && log.rows.length === 0 && <div className="text-[9.5px] text-[var(--color-dim)]">归档为空。开启镜像后自动入场会写入；或现在点"📸 存快照"抓一次当前状态。</div>}
        <div className="text-[9px] text-[var(--color-dim)] leading-[1.5]">
          每笔镜像/测试下单都<b>自动入库</b>；每次自动扫描（开镜像时）会存一次完整快照。
        </div>
      </div>

      {/* ── Flex Web Service backstop (authoritative, lossless) ── */}
      <div className="mt-2 rounded border border-[var(--color-border)] p-2 space-y-1.5 bg-[var(--color-panel)]">
        <div className="flex items-center justify-between gap-2 flex-wrap">
          <b className="text-[var(--color-text)]">🧾 Flex 兜底（IBKR 官方对账，永不漏单）</b>
          <span className={`text-[10px] ${flex?.configured ? 'text-[var(--color-green)]' : 'text-[var(--color-dim)]'}`}>
            {flex?.configured ? `✓ 已配置 (query ${flex.query_id})` : '未配置'}
          </span>
        </div>
        <div className="text-[9px] text-[var(--color-dim)] leading-[1.5]">
          这是<b>真正的兜底</b>：即使 Gateway 整天没开、实时快照漏了某笔成交，IBKR 服务器端的 Flex 对账单仍有完整记录（按 tradeID 去重，永不重复）。
          先在 <b>Client Portal → Performance & Reports → Flex Queries</b> 建一个 Activity 查询（含 Trades/Open Positions/Cash），拿到 <b>Query ID</b>；再到 Flex Web Service 生成 <b>token</b>。填进来即可（token 保存后不再回显，也不会被任何接口返回）。
        </div>
        <div className="flex gap-1.5 flex-wrap items-center text-[10px]">
          <input value={flexTok} onChange={e => setFlexTok(e.target.value)} placeholder="Flex token" type="password"
            className="w-40 px-1.5 py-0.5 rounded bg-[var(--color-bg)] border border-[var(--color-border)] text-[var(--color-text)]" />
          <input value={flexQid} onChange={e => setFlexQid(e.target.value)} placeholder="Query ID"
            className="w-28 px-1.5 py-0.5 rounded bg-[var(--color-bg)] border border-[var(--color-border)] text-[var(--color-text)]" />
          <button onClick={saveFlex} disabled={!!busy}
            className="px-2 py-0.5 rounded bg-[var(--color-accent)]/15 text-[var(--color-accent)] border border-[var(--color-accent)]/40">
            {busy === 'flexcfg' ? '保存…' : '保存凭证'}
          </button>
          <button onClick={syncFlex} disabled={!!busy || !flex?.configured}
            className="px-2 py-0.5 rounded bg-[var(--color-green)]/15 text-[var(--color-green)] border border-[var(--color-green)]/40 disabled:opacity-40">
            {busy === 'flexsync' ? '同步…' : '🔄 立即同步'}
          </button>
          <button onClick={reconcile} disabled={!!busy || !flex?.configured}
            className="px-2 py-0.5 rounded bg-[var(--color-accent)]/15 text-[var(--color-accent)] border border-[var(--color-accent)]/40 disabled:opacity-40">
            {busy === 'recon' ? '对账…' : '🔍 对账（vs 官方账本）'}
          </button>
        </div>
        {recon?.summary && (
          <div className={`text-[10px] rounded p-1.5 border ${recon.summary.complete ? 'border-[var(--color-green)]/40 bg-[var(--color-green)]/10' : 'border-[var(--color-red)]/40 bg-[var(--color-red)]/10'}`}>
            <div>
              {recon.summary.complete
                ? <span className="text-[var(--color-green)] font-semibold">✓ 完整：{recon.summary.matched} 笔与 IBKR 官方账本逐笔一致，无遗漏</span>
                : <span className="text-[var(--color-red)] font-semibold">⚠️ {recon.summary.flex_only} 笔 IBKR 官方有、本地实时没抓到（已被 Flex 兜底补入归档）</span>}
            </div>
            <div className="text-[var(--color-dim)] mt-0.5">Flex 成交 {recon.summary.flex_trades} · 本地 fill {recon.summary.local_fills} · 匹配 {recon.summary.matched} · 仅本地 {recon.summary.local_only}（多为未成交/同日延迟）</div>
            {recon.flex_only && recon.flex_only.length > 0 && (
              <div className="mt-1 text-[9px] text-[var(--color-red)]">仅 IBKR 有：{recon.flex_only.map((r, i) => <span key={i} className="mr-2 font-mono">{r.symbol} {r.side} {r.qty}@{r.price}×{r.count}</span>)}</div>
            )}
          </div>
        )}
        <div className="text-[9px] text-[var(--color-dim)]">配置后每天收盘后（22:00 UTC）自动同步一次；也可随时"立即同步"。"对账"按 标的/方向/数量/价 多重集比对，证明本地日志对得上官方账本。</div>
      </div>
    </Section>
  )
}

// ════════════════════════════════════════════════════════════
//  ③ Data source & pipeline (explainer)
// ════════════════════════════════════════════════════════════
function PipelinePanel() {
  const STAGES = [
    { n: '①', t: '文字 / 意图', d: '自然语言描述策略+来源', io: '你写 / 研究' },
    { n: '②', t: '公式', d: 'LLM 蒸馏成指标条件 (entry rules)', io: '本地 LLM' },
    { n: '③', t: '量化 spec', d: '止损/目标/sizing/timeframe，可执行', io: 'quant_spec JSON' },
    { n: '④', t: '验证', d: '真实 OHLCV 回测 + 触发图 + 跑分', io: 'yfinance + 评估器' },
    { n: '⑤', t: '部署', d: 'armed(paper/live) → 自动进场+OCO', io: 'paper engine' },
  ]
  return (
    <Section title="🔄 策略构建流程 (NL → 公式 → 量化)" subtitle="每个 setup 都走这条流水线；卡片上的 ①②③④⑤ 对应这里">
      <div className="flex items-stretch gap-1 flex-wrap mb-2">
        {STAGES.map((s, i) => (
          <div key={i} className="flex items-stretch gap-1">
            <div className="bg-[var(--color-panel)] border border-[var(--color-border)] rounded p-1.5 w-[130px]">
              <div className="text-[10px] font-semibold text-[var(--color-accent)]">{s.n} {s.t}</div>
              <div className="text-[8.5px] text-[var(--color-dim)] leading-[1.4] mt-0.5">{s.d}</div>
              <div className="text-[8px] text-[var(--color-text)]/60 mt-1 font-mono">{s.io}</div>
            </div>
            {i < STAGES.length - 1 && <div className="flex items-center text-[var(--color-accent)] text-[12px]">→</div>}
          </div>
        ))}
      </div>
      <div className="text-[9.5px] text-[var(--color-dim)] space-y-1 leading-[1.6] border-t border-[var(--color-border)]/40 pt-2">
        <div>📊 <b>数据源</b>: yfinance OHLCV (日/时/分线) 供回测/扫描 · paper 成交走 DataHub 实时报价。实盘执行走 IBKR venue（连 Gateway 时；DU 账户闸门 + allow_live 双保险）。</div>
        <div>🧮 <b>指标库</b>: SMA·EMA·RSI(Wilder)·MACD·Bollinger·ATR·vol_sma·highest/lowest(N日突破)。</div>
        <div>🧪 <b>回测假设</b>: long-only·单仓·信号bar收盘进场·盘中触stop/target·无滑点佣金·历史≠未来。</div>
        <div>🔁 <b>可溯源</b>: 改①文字→重蒸②③；④回测/图验证；⑤部署受全局停止+kill-switch gate。每步可查可改。</div>
      </div>
    </Section>
  )
}

// ════════════════════════════════════════════════════════════
//  ④ Paper trading (folded in from old Paper tab)
// ════════════════════════════════════════════════════════════
function PaperSection({ projectId }: { projectId: string }) {
  const risk = usePortfolioRisk(projectId)
  const tstate = useTradingState()
  const isIbkr = (tstate.data?.venue || (tstate.data?.ibkr_route ? 'ibkr' : 'sim')) === 'ibkr'
  return (
    <Section title="📝 内部模拟引擎 (离线)" subtitle="离线即时回测/干跑账户 — 与你的实时真相分开"
      right={
        <button onClick={() => risk.mutate()} disabled={risk.isPending}
          className="text-[10px] px-2 py-0.5 rounded border border-[var(--color-border)] text-[var(--color-dim)] hover:text-[var(--color-text)]"
          title="持仓两两相关性 + 集中风险警告">
          {risk.isPending ? '算相关性…' : '🔗 组合相关性'}</button>
      }>
      {isIbkr && (
        <div className="mb-2 text-[9.5px] rounded p-1.5 border border-[var(--color-yellow)]/40 bg-[var(--color-yellow)]/10 text-[var(--color-dim)]">
          ⚠️ 当前执行去向=<b>IBKR</b>，你的<b>真相在上面的「交易计划」(IBKR 账户)</b>。这里是<b>独立的离线模拟引擎</b>，仅供回测/干跑，<b>不反映</b>你的 IBKR 实时持仓/盈亏。
        </div>
      )}
      {risk.data && (
        <div className="mb-2 text-[10px] bg-[var(--color-panel)]/60 rounded p-2">
          <div className="text-[var(--color-dim)]">{risk.data.n_positions} 个持仓 · 相关性阈值 {risk.data.threshold}</div>
          {risk.data.warnings.length > 0 ? (
            risk.data.warnings.map((w, i) => (
              <div key={i} className="text-[var(--color-red)]">⚠️ {w.a} 与 {w.b} 相关 {w.corr} — 集中风险（看似分散实为一注）</div>
            ))
          ) : (
            <div className="text-[var(--color-green)]">✓ 持仓间无高相关（&lt;{risk.data.threshold}），分散性 OK</div>
          )}
        </div>
      )}
      <div className="grid gap-3" style={{ gridTemplateColumns: '1fr 1fr' }}>
        <div className="col-span-2"><PaperAccountCard projectId={projectId} /></div>
        <PaperPositionsTable projectId={projectId} />
        <PaperOrderForm projectId={projectId} />
        <div className="col-span-2"><PaperTradesTable projectId={projectId} /></div>
      </div>
    </Section>
  )
}
