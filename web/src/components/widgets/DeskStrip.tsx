/**
 * DeskStrip — compact "account state + ops control" cockpit bar.
 *
 * Additive widget mounted at the very top of the Strategies (home) tab.
 * The account roles + emergency controls otherwise live only on the
 * Core (bucket ①) and Trading (bucket ②) tabs, so the main page had no
 * at-a-glance "where's my money / is anything armed" view. This strip
 * surfaces exactly that in one compact row — pure reuse, no new endpoints:
 *
 *   • EmergencyBrakeBar (exported from Trading.tsx) — halt/resume, auto-
 *     trade toggle, flatten, settle, regime pill, status. Rendered verbatim
 *     so the control logic stays single-sourced.
 *   • useTradingState  → budget + venue pills (trading_budget_usd / venue).
 *   • useCoreRisk      → Schwab 核心 card (total_value / unrealized_pct / 集中度).
 *   • useCockpit       → IBKR 量化 card (venue / ibkr_connected / net_liquidation).
 *
 * Each panel degrades to an independent placeholder — one failing hook
 * never blanks the whole strip.
 *
 * 2026-07-06 — from readout to launcher (all additive, same channels):
 *   • TodoChip (📋 今天 N 个待办) reuses usePriorityList(5) + the global
 *     openTicker channel (same as PriorityListWidget) — a glance shows
 *     what to look at today, a click opens the stock research drawer.
 *   • Account cards deep-link: Schwab → onNavigate('core'), IBKR →
 *     onNavigate('trading'), so the strip routes into the full tab.
 */
import { useEffect, useRef, useState } from 'react'
import { cn } from '@/lib/utils'
import { useCoreRisk, useCockpit, useTradingState, usePriorityList, useIbkrSpreads } from '@/lib/api'
import type { IbkrSpread } from '@/lib/api'
import { useStockResearch } from '@/components/research/StockResearchContext'
import { EmergencyBrakeBar } from '@/tabs/Trading'

// Account-role edge colors. --color-amber isn't a defined token; use the
// same `var(--color-amber,#e5a200)` fallback the rest of this app uses.
const ROLE_COLOR = {
  schwab: 'var(--color-blue)',
  ibkr: 'var(--color-amber,#e5a200)',
  paper: 'var(--color-dim)',
} as const

const fmtUsd = (n?: number | null) =>
  n == null || !isFinite(n) ? '—' : `$${Math.round(n).toLocaleString()}`

function Placeholder({ text }: { text: string }) {
  return <div className="text-[9px] text-[var(--color-dim)] italic leading-[1.4]">{text}</div>
}

function AccountCard({
  role,
  title,
  right,
  onClick,
  navHint,
  children,
}: {
  role: keyof typeof ROLE_COLOR
  title: string
  right?: React.ReactNode
  /** When set, the whole card becomes a click target (→ deep-dive tab). */
  onClick?: () => void
  /** Subtle "→ Core" / "→ Trading" affordance shown next to the title. */
  navHint?: string
  children: React.ReactNode
}) {
  const color = ROLE_COLOR[role]
  const clickable = !!onClick
  return (
    <div
      onClick={onClick}
      role={clickable ? 'button' : undefined}
      tabIndex={clickable ? 0 : undefined}
      onKeyDown={
        clickable
          ? (e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault()
                onClick!()
              }
            }
          : undefined
      }
      className={cn(
        'rounded border border-[var(--color-border)] bg-[var(--color-panel)] px-2.5 py-1.5 flex flex-col gap-1 min-w-0 transition',
        clickable &&
          'group cursor-pointer hover:border-[var(--color-accent)]/60 hover:bg-[var(--color-accent)]/[0.04]',
      )}
      style={{ borderLeft: `3px solid ${color}` }}
    >
      <div className="flex items-center gap-1.5">
        <span
          className="text-[8.5px] font-semibold uppercase tracking-wider"
          style={{ color }}
        >
          {title}
        </span>
        {navHint && (
          <span className="text-[8px] font-medium text-[var(--color-dim)] transition group-hover:text-[var(--color-accent)]">
            {navHint}
          </span>
        )}
        {right && <span className="ml-auto">{right}</span>}
      </div>
      {children}
    </div>
  )
}

// ① Schwab 核心 — long-term core holdings (bucket ①).
function SchwabCard({ onNavigate }: { onNavigate?: (tab: string) => void }) {
  const q = useCoreRisk()
  const d = q.data
  const c = d?.concentration
  const concentrated = !!c && (c.top3_pct > 60 || c.hhi > 0.25)
  return (
    <AccountCard
      role="schwab"
      title="Schwab 核心"
      onClick={onNavigate ? () => onNavigate('core') : undefined}
      navHint={onNavigate ? '→ Core' : undefined}
    >
      {q.isLoading ? (
        <Placeholder text="加载中…" />
      ) : q.isError ? (
        <Placeholder text="暂无数据（core_risk 未就绪）" />
      ) : !d || d.n_tickers === 0 ? (
        <Placeholder text={d?.note ?? '无核心持仓'} />
      ) : (
        <div className="flex flex-col gap-0.5">
          <div className="flex items-baseline gap-2 flex-wrap">
            <span className="text-[13px] font-semibold text-[var(--color-text)] font-mono">
              {fmtUsd(d.total_value)}
            </span>
            <span
              className="text-[10px] font-mono"
              style={{ color: (d.unrealized_pct ?? 0) >= 0 ? 'var(--color-green)' : 'var(--color-red)' }}
            >
              浮盈 {(d.unrealized_pct ?? 0) >= 0 ? '+' : ''}
              {(d.unrealized_pct ?? 0).toFixed(1)}%
            </span>
          </div>
          {c && (
            <div
              className="text-[9px]"
              style={{ color: concentrated ? 'var(--color-red)' : 'var(--color-dim)' }}
            >
              {concentrated ? '⚠️ ' : ''}集中度 前3 {c.top3_pct}% · 最大 {c.largest.ticker} {c.largest.pct}%
            </div>
          )}
        </div>
      )}
    </AccountCard>
  )
}

// Status → dot color for an option spread. winning=绿 / at_risk=琥珀 /
// breached=红 / unknown=灰 (fallback = unknown).
const SPREAD_STATUS: Record<IbkrSpread['status'], string> = {
  winning: 'var(--color-green)',
  at_risk: 'var(--color-amber,#e5a200)',
  breached: 'var(--color-red)',
  unknown: 'var(--color-dim)',
}

// Drop a trailing `.0` from whole-number strikes (140.0 → "140", 140.5 → "140.5").
const fmtStrike = (s?: number | null) => (s == null ? '?' : String(s))

// One compact line per option spread: SYMBOL 卖{K}P · {dte}d⚠ · ●垫{cushion}% +${maxP}/−${maxL}
function SpreadRow({ s }: { s: IbkrSpread }) {
  const dotColor = SPREAD_STATUS[s.status] ?? SPREAD_STATUS.unknown
  const warn = s.dte <= 5
  const dteColor = s.dte <= 2 ? 'var(--color-red)' : warn ? 'var(--color-amber,#e5a200)' : 'var(--color-dim)'
  const mp = s.max_profit == null ? '—' : `+$${Math.round(s.max_profit)}`
  const ml = s.max_loss == null ? '—' : `−$${Math.round(s.max_loss)}`
  return (
    <div className="flex items-center gap-1 text-[9px] font-mono leading-[1.6] min-w-0">
      <span className="font-bold text-[var(--color-text)]">{s.symbol}</span>
      <span className="text-[var(--color-dim)]">卖{fmtStrike(s.short_strike)}{s.right}</span>
      <span className="text-[var(--color-dim)]">·</span>
      <span style={{ color: dteColor, fontWeight: warn ? 600 : 400 }}>
        {s.dte}d{warn ? '⚠' : ''}
      </span>
      <span className="text-[var(--color-dim)]">·</span>
      <span className="inline-flex items-center gap-0.5 text-[var(--color-dim)]">
        <span className="inline-block w-[6px] h-[6px] rounded-full flex-shrink-0" style={{ background: dotColor }} />
        {s.cushion_pct != null && `垫${s.cushion_pct}%`}
      </span>
      <span className="ml-auto flex items-center gap-0.5 flex-shrink-0">
        <span style={{ color: 'var(--color-green)' }}>{mp}</span>
        <span className="text-[var(--color-dim)]">/</span>
        <span style={{ color: 'var(--color-red)' }}>{ml}</span>
      </span>
    </div>
  )
}

// ② IBKR 量化 — quant swing sandbox execution venue (bucket ②).
function IbkrCard({ projectId, onNavigate }: { projectId: string; onNavigate?: (tab: string) => void }) {
  const q = useCockpit(projectId)
  const sp = useIbkrSpreads()
  const d = q.data
  const isIbkr = d?.venue === 'ibkr'
  const connected = !!d?.ibkr_connected
  const spreads = sp.data?.spreads ?? []
  return (
    <AccountCard
      role="ibkr"
      title="IBKR 量化"
      onClick={onNavigate ? () => onNavigate('trading') : undefined}
      navHint={onNavigate ? '→ Trading' : undefined}
      right={
        d ? (
          <span
            className="text-[8px] px-1 py-0.5 rounded border font-mono"
            style={{
              borderColor: isIbkr && connected ? 'var(--color-green)' : 'var(--color-dim)',
              color: isIbkr && connected ? 'var(--color-green)' : 'var(--color-dim)',
            }}
          >
            {isIbkr ? (connected ? '● 已连接' : '○ 未连接') : 'sim'}
          </span>
        ) : undefined
      }
    >
      {q.isLoading ? (
        <Placeholder text="加载中…" />
      ) : q.isError ? (
        <Placeholder text="暂无数据（cockpit 未就绪）" />
      ) : !d ? (
        <Placeholder text="—" />
      ) : !isIbkr ? (
        <Placeholder text="执行路由=模拟引擎（未切 IBKR）" />
      ) : !connected ? (
        <Placeholder text="IBKR 未连接（gateway 未运行？）" />
      ) : spreads.length > 0 ? (
        // Has live option spreads → surface them; NetLiq demoted to a small line.
        <div className="flex flex-col gap-1 min-w-0">
          <div className="flex flex-col gap-0.5 min-w-0">
            {spreads.map((s) => (
              <SpreadRow key={`${s.symbol}-${s.expiry}-${s.short_strike}`} s={s} />
            ))}
          </div>
          <div className="text-[9px] text-[var(--color-dim)]">
            NetLiq {fmtUsd(d.net_liquidation)} · {d.account ?? '—'} {d.is_paper ? '(paper)' : d.account ? '(⚠真实)' : ''}
          </div>
        </div>
      ) : (
        // Connected but no spreads (loading, error, or genuinely none) → NetLiq.
        <div className="flex flex-col gap-0.5">
          <div className="text-[13px] font-semibold text-[var(--color-text)] font-mono">
            {fmtUsd(d.net_liquidation)}
          </div>
          <div className="text-[9px] text-[var(--color-dim)]">
            {sp.isLoading
              ? '加载期权价差…'
              : sp.isError
                ? 'NetLiq · 价差暂不可用'
                : '无期权价差'}{' '}
            · {d.account ?? '—'} {d.is_paper ? '(paper)' : d.account ? '(⚠真实)' : ''}
          </div>
        </div>
      )}
    </AccountCard>
  )
}

// ③ Paper — local sim sandbox (dormant unless it's the active venue).
function PaperCard({ venue }: { venue?: string }) {
  const active = venue !== 'ibkr'
  return (
    <AccountCard role="paper" title="Paper 沙盒">
      <div className="text-[10px] text-[var(--color-text)]">
        {active ? '● 当前执行目标' : '○ 休眠'}
      </div>
      <div className="text-[9px] text-[var(--color-dim)] leading-[1.4]">
        本地模拟引擎——桶② 量化 swing 在这里验证 edge / 练纪律，不动真钱。
      </div>
    </AccountCard>
  )
}

// 📋 今天 N 个待办 — the "往前开" launcher. Reuses the exact priority
// feed + openTicker channel the PriorityListWidget already uses, so the
// strip stops being a passive readout and becomes an action surface:
// one glance = what to look at today, one click = into the stock drawer.
function TodoChip() {
  const q = usePriorityList(5)
  const { openTicker } = useStockResearch()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  // Close the dropdown on any outside click (matches the app's nav menus).
  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open])

  const items = q.data?.items ?? []
  const n = q.data?.n_total_candidates ?? items.length
  // Clickable only when we actually have candidates to open.
  const clickable = !q.isLoading && !q.isError && n > 0

  const label = q.isError
    ? '📋 待办暂不可用'
    : q.isLoading
      ? '📋 待办加载中…'
      : n > 0
        ? `📋 今天 ${n} 个待办`
        : '📋 今天无待办'

  return (
    <div className="relative" ref={ref}>
      <button
        data-testid="desk-todo-chip"
        onClick={() => clickable && setOpen((o) => !o)}
        disabled={!clickable}
        title={clickable ? '今天该先看的候选 — 点开列表，一点直接进个股抽屉' : undefined}
        className={cn(
          'flex items-center gap-1 px-2 py-0.5 rounded border font-semibold transition',
          clickable
            ? 'border-[var(--color-accent)]/50 bg-[var(--color-accent)]/10 text-[var(--color-accent)] hover:bg-[var(--color-accent)]/20 cursor-pointer'
            : 'border-[var(--color-border)] text-[var(--color-dim)] cursor-default',
        )}
      >
        <span>{label}</span>
        {clickable && <span className="text-[8px]">{open ? '▴' : '▾'}</span>}
      </button>

      {open && clickable && (
        <div
          data-testid="desk-todo-popover"
          className="absolute z-50 mt-1 left-0 w-[300px] max-w-[86vw] rounded border border-[var(--color-border)] bg-[var(--color-panel)] shadow-xl p-1"
        >
          <div className="px-2 py-1 text-[8.5px] uppercase tracking-wider text-[var(--color-dim)]">
            今天先看这几个 · 点一条进研究抽屉
          </div>
          {items.slice(0, 5).map((it, i) => (
            <button
              key={it.ticker}
              onClick={() => {
                openTicker(it.ticker)
                setOpen(false)
              }}
              title={`打开 ${it.ticker} 研究抽屉`}
              className="w-full text-left px-2 py-1.5 rounded hover:bg-[var(--color-accent)]/[0.08] transition flex items-start gap-1.5"
            >
              <span className="font-mono text-[9px] text-[var(--color-dim)] w-4 flex-shrink-0 mt-[1px]">
                #{i + 1}
              </span>
              <span className="font-mono font-bold text-[11px] text-[var(--color-text)] flex-shrink-0">
                {it.ticker}
              </span>
              <span className="text-[9.5px] text-[var(--color-dim)] leading-[1.3] min-w-0 truncate">
                {it.reasons[0]?.text ?? '—'}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

export function DeskStrip({
  projectId,
  onNavigate,
}: {
  projectId: string
  /** Deep-dive routing: Schwab card → 'core', IBKR card → 'trading'. */
  onNavigate?: (tab: string) => void
}) {
  const state = useTradingState()
  const budget = state.data?.trading_budget_usd
  const venue = state.data?.venue

  return (
    <div className="mb-3 flex flex-col gap-2">
      {/* header + 待办 launcher + budget/venue pills */}
      <div className="flex items-center gap-2 flex-wrap text-[10px]">
        <span className="font-semibold text-[var(--color-text)]">🎛 交易台驾驶舱</span>
        <TodoChip />
        <span className="text-[var(--color-dim)] hidden md:inline">
          账户状态 + 操作控制（原本散在 Core / Trading tab）
        </span>
        <span className="ml-auto flex items-center gap-1.5">
          <span className="px-1.5 py-0.5 rounded border border-[var(--color-border)] text-[var(--color-dim)] font-mono">
            预算 {budget ? `$${Number(budget).toLocaleString()}` : '按 TPS %'}
          </span>
          {venue && (
            <span className="px-1.5 py-0.5 rounded border border-[var(--color-border)] text-[var(--color-dim)] font-mono">
              venue: {venue}
            </span>
          )}
        </span>
      </div>

      {/* ops row — reuse the canonical emergency-brake controls verbatim */}
      <EmergencyBrakeBar projectId={projectId} />

      {/* three account role cards — Schwab/IBKR click through to their deep-dive tab */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
        <SchwabCard onNavigate={onNavigate} />
        <IbkrCard projectId={projectId} onNavigate={onNavigate} />
        <PaperCard venue={venue} />
      </div>
    </div>
  )
}
