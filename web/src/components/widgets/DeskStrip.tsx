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
 */
import { useCoreRisk, useCockpit, useTradingState } from '@/lib/api'
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
  children,
}: {
  role: keyof typeof ROLE_COLOR
  title: string
  right?: React.ReactNode
  children: React.ReactNode
}) {
  const color = ROLE_COLOR[role]
  return (
    <div
      className="rounded border border-[var(--color-border)] bg-[var(--color-panel)] px-2.5 py-1.5 flex flex-col gap-1 min-w-0"
      style={{ borderLeft: `3px solid ${color}` }}
    >
      <div className="flex items-center gap-1.5">
        <span
          className="text-[8.5px] font-semibold uppercase tracking-wider"
          style={{ color }}
        >
          {title}
        </span>
        {right && <span className="ml-auto">{right}</span>}
      </div>
      {children}
    </div>
  )
}

// ① Schwab 核心 — long-term core holdings (bucket ①).
function SchwabCard() {
  const q = useCoreRisk()
  const d = q.data
  const c = d?.concentration
  const concentrated = !!c && (c.top3_pct > 60 || c.hhi > 0.25)
  return (
    <AccountCard role="schwab" title="Schwab 核心">
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

// ② IBKR 量化 — quant swing sandbox execution venue (bucket ②).
function IbkrCard({ projectId }: { projectId: string }) {
  const q = useCockpit(projectId)
  const d = q.data
  const isIbkr = d?.venue === 'ibkr'
  const connected = !!d?.ibkr_connected
  return (
    <AccountCard
      role="ibkr"
      title="IBKR 量化"
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
      ) : (
        <div className="flex flex-col gap-0.5">
          <div className="text-[13px] font-semibold text-[var(--color-text)] font-mono">
            {fmtUsd(d.net_liquidation)}
          </div>
          <div className="text-[9px] text-[var(--color-dim)]">
            NetLiq · {d.account ?? '—'} {d.is_paper ? '(paper)' : d.account ? '(⚠真实)' : ''}
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

export function DeskStrip({ projectId }: { projectId: string }) {
  const state = useTradingState()
  const budget = state.data?.trading_budget_usd
  const venue = state.data?.venue

  return (
    <div className="mb-3 flex flex-col gap-2">
      {/* header + budget/venue pills */}
      <div className="flex items-center gap-2 flex-wrap text-[10px]">
        <span className="font-semibold text-[var(--color-text)]">🎛 交易台驾驶舱</span>
        <span className="text-[var(--color-dim)] hidden sm:inline">
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

      {/* three account role cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
        <SchwabCard />
        <IbkrCard projectId={projectId} />
        <PaperCard venue={venue} />
      </div>
    </div>
  )
}
