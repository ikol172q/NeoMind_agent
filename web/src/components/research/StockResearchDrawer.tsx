/**
 * Stock Research Drawer — DEMO with mock data.
 *
 * UX prototype the user can click around to validate layout + tab
 * structure before we wire backend (stock_profiles table, NeoMind
 * generators, news synthesizer, chat ticker-context).
 *
 * Real version (post-feedback) will:
 *   - GET /api/stock/{ticker}/profile (LLM-cached business summary)
 *   - GET /api/stock/{ticker}/exposure (signal_events join, real data)
 *   - GET /api/stock/{ticker}/upstream + /downstream (LLM-extracted)
 *   - GET /api/stock/{ticker}/news (filtered + LLM-summarized)
 *   - GET/POST /api/stock/{ticker}/notes (per-user notes)
 *   - Open chat with ticker pre-injected as system context
 *
 * Mock data deliberately rich for NVDA so the user can judge UX
 * fidelity. Other tickers fall back to a stub.
 */
import { useState, useEffect } from 'react'
import { useStockResearch } from './StockResearchContext'
import { ChatPanel } from '@/components/chat/ChatPanel'
import { X, ExternalLink, Sparkles, BarChart3, Network, Newspaper, NotebookPen, MessagesSquare, Building2 } from 'lucide-react'

type Status = 'researching' | 'watching' | 'pass' | 'own'

interface UserStatus {
  status: Status
  reason: string
  ts: string
}

// localStorage-backed status store. Keyed by ticker so each stock has
// its own decision history. Real version moves to stock_profiles table.
function loadUserStatus(ticker: string): UserStatus | null {
  try {
    const raw = localStorage.getItem(`neomind.research.status.${ticker}`)
    return raw ? JSON.parse(raw) : null
  } catch { return null }
}
function saveUserStatus(ticker: string, s: UserStatus) {
  try {
    localStorage.setItem(`neomind.research.status.${ticker}`, JSON.stringify(s))
  } catch { /* ignore quota */ }
}

type TabKey = 'overview' | 'smart_money' | 'supply_chain' | 'news' | 'notes' | 'chat'

interface MockProfile {
  name: string
  sector: string
  ceo?: string
  founded?: string
  hq?: string
  marketCap?: string
  pe?: string
  price?: string
  status?: 'researching' | 'watching' | 'pass' | 'own'
  styleVerdict?: string
  summary: string
  segments: Array<{ name: string; pct: number; note?: string }>
  upstream: Array<{ ticker: string; name: string; role: string }>
  downstream: Array<{ ticker: string; name: string; role: string }>
  competitors: Array<{ ticker: string; name: string; note?: string }>
  catalysts: Array<{ when: string; what: string; severity: 'high' | 'med' | 'low' }>
  risks: string[]
  smartMoney: Array<{ source: string; who: string; action: string; when: string; size?: string }>
  news: Array<{ date: string; headline: string; severity: 'high' | 'med' | 'low'; summary: string }>
  notes: Array<{ ts: string; body: string; tag?: string }>
  generatedAt: string
}

const MOCK_PROFILES: Record<string, MockProfile> = {
  NVDA: {
    name: 'NVIDIA Corporation',
    sector: 'Semiconductors · GPU / AI accelerator',
    ceo: 'Jensen Huang',
    founded: '1993',
    hq: 'Santa Clara, CA',
    marketCap: '$4.85T',
    pe: '40.5',
    price: '$198.45',
    status: 'researching',
    styleVerdict: '🟢 长期持有候选 · 🟠 估值较贵需 timing',
    summary:
      'NVIDIA 设计 GPU 与 AI 加速芯片. 2022 年生成式 AI 爆发后, 数据中心营收 18 个月内从公司营收的 ~30% 涨到 78%, 成为 AI infrastructure 实质垄断者 (~95% 训练市场). 护城河来自 CUDA 软件生态 + 跟 TSMC 高端制程深度绑定 + 跟 hyperscalers 长期供应合约. 主要风险: 客户集中度高 (top 4 hyperscaler 占 ~50% 营收), 中国出口管制不确定性, AMD/Custom ASIC (Google TPU/Amazon Trainium) 竞争加剧.',
    segments: [
      { name: '数据中心 (AI/HPC)', pct: 78, note: 'Hopper H100/H200 + Blackwell B100/B200' },
      { name: '游戏 GPU (GeForce)', pct: 12, note: 'RTX 50 系列周期高峰' },
      { name: '专业可视化 (Quadro)', pct: 5 },
      { name: '汽车 (Drive)', pct: 3 },
      { name: 'OEM / 其他', pct: 2 },
    ],
    upstream: [
      { ticker: 'TSM', name: 'Taiwan Semiconductor', role: '独家 GPU 代工 (5nm/3nm/2nm)' },
      { ticker: 'ASML', name: 'ASML Holding', role: 'EUV 光刻机给 TSM (间接关键)' },
      { ticker: 'SOXX', name: '半导体 ETF (代理)', role: '全行业 health 跟踪' },
      { ticker: 'AMAT', name: 'Applied Materials', role: 'wafer 制造设备给 TSM' },
      { ticker: '005930.KS', name: 'Samsung Electronics', role: 'HBM 高带宽内存' },
      { ticker: 'MU', name: 'Micron', role: 'HBM3e 第二供应商' },
    ],
    downstream: [
      { ticker: 'MSFT', name: 'Microsoft (Azure)', role: 'top 客户 ~17% 营收 (Azure AI)' },
      { ticker: 'META', name: 'Meta', role: '~12% 营收 (训练 LLaMA)' },
      { ticker: 'GOOGL', name: 'Alphabet (GCP)', role: '~10% (但同时自研 TPU 是替代风险)' },
      { ticker: 'AMZN', name: 'Amazon (AWS)', role: '~9% (同时自研 Trainium 是风险)' },
      { ticker: 'ORCL', name: 'Oracle', role: '$10B+ 订单 (近期 OCI 扩张)' },
      { ticker: 'CRWV', name: 'CoreWeave', role: 'GPU 云原生新势力 大客户' },
    ],
    competitors: [
      { ticker: 'AMD', name: 'AMD', note: 'MI300X 数据中心 GPU 追赶, 距离 NVDA 1-2 代' },
      { ticker: 'INTC', name: 'Intel', note: 'Gaudi 3 加速器, 市场份额低' },
      { ticker: 'GOOGL', name: 'Google TPU', note: '内部自用, 但 GCP 客户可选' },
      { ticker: 'AMZN', name: 'Amazon Trainium', note: '内部自用 + AWS 客户' },
    ],
    catalysts: [
      { when: '2026-05-21', what: 'Q1 FY27 earnings — guide 决定下半年节奏', severity: 'high' },
      { when: '2026-06-09', what: 'COMPUTEX 2026 keynote — Blackwell Ultra 细节', severity: 'high' },
      { when: '2026 H2', what: '中国 H20 出口许可证审查节点', severity: 'med' },
      { when: '2026 Q4', what: 'Rubin 架构正式发布', severity: 'med' },
    ],
    risks: [
      '客户集中度: top 4 hyperscaler 占 ~50% 营收, 任一减 capex 影响显著',
      '自研 ASIC 替代: Google TPU / Amazon Trainium 已 production, 边际侵蚀',
      'AI capex 周期: 若大模型训练 demand 明显放缓, NVDA 估值压缩快',
      '中国出口管制: 营收 ~17% 受 H20 / 后续型号许可影响',
      'TSM 集中风险: 独家代工, TSM 任何 disruption 直接传导',
    ],
    smartMoney: [
      { source: 'House Clerk PDF', who: 'Pelosi (众)', action: '买 NVDA call options $250k-$500k', when: '2025-01-14', size: '$250k-$500k' },
      { source: 'House Clerk PDF', who: 'Pelosi (众)', action: '行权 500 calls (50,000 sh @ $12)', when: '2024-12-20', size: '$500k-$1M' },
      { source: 'House Clerk PDF', who: 'Pelosi (众)', action: '卖出 10,000 sh', when: '2024-12-31', size: '$1M-$5M' },
      { source: '13F', who: 'Cathie Wood (ARK)', action: '新建仓 NVDA', when: '2026-02-11', size: '~$234M' },
      { source: '13F', who: 'Druckenmiller (Duquesne)', action: '加仓 NVDA', when: '2026-02-17' },
      { source: '13F', who: 'Bridgewater (Dalio)', action: '加仓 NVDA', when: '2026-02-13' },
      { source: '13F', who: 'D.E. Shaw', action: '新建仓 NVDA', when: '2026-02-17' },
      { source: 'Form 4', who: 'NVDA 内部人 (3 名)', action: '内部人买入 (cluster)', when: '2026-04-15', size: '$420K' },
    ],
    news: [
      { date: '2026-04-30', headline: 'NVDA 与 Saudi PIF 签署 AI 数据中心 $40B 多年订单', severity: 'high',
        summary: '中东主权基金成为继 hyperscaler 之后的第三大需求来源. 多年合约锁定 long-term revenue visibility.' },
      { date: '2026-04-22', headline: 'Trump 政府批准 H20 中国出口许可', severity: 'high',
        summary: '解除 2025 年 4 月停产令, 中国营收预计 2026 H2 部分恢复, 但仍低于 2024 峰值.' },
      { date: '2026-04-10', headline: 'Blackwell Ultra (B200) 量产爬坡符合预期', severity: 'med',
        summary: '供应链消息显示 Q2 出货量符合上次电话会议 guidance. 无明显延期信号.' },
    ],
    notes: [
      { ts: '2026-04-15', body: 'Pelosi 1月买的 calls strike $80, expiry 1/16/26 — 已经 expire. 需要查她是否 roll over.', tag: 'investigate' },
      { ts: '2026-04-20', body: 'PE 40 跟 AMD 138 比是合理的 — 盈利支撑. 但对比 Buffett 式 long hold 我会等 PE 降到 30 以下加仓.', tag: 'valuation_concern' },
    ],
    generatedAt: '2026-05-02 14:23 (cached, click "regenerate" to refresh)',
  },
}

function fallback(ticker: string): MockProfile {
  return {
    name: `${ticker} (尚未生成 profile)`,
    sector: '需要点 ✨ regenerate 让 NeoMind 拉数据生成',
    summary: `这个 ticker (${ticker}) 还没在 stock_profiles cache 里. 真实版本会在你第一次打开时调用 NeoMind LLM (~$0.01) 自动生成一份带 source 的 business summary, 然后缓存. 后续打开秒开 (free).`,
    segments: [],
    upstream: [],
    downstream: [],
    competitors: [],
    catalysts: [],
    risks: [],
    smartMoney: [],
    news: [],
    notes: [],
    generatedAt: 'never',
  }
}


export function StockResearchDrawer() {
  const { ticker, projectId, closeTicker, openTicker } = useStockResearch()
  const [tab, setTab] = useState<TabKey>('overview')
  // User status (persisted to localStorage). Tab switches don't lose
  // it. Loaded fresh per ticker open.
  const [userStatus, setUserStatus] = useState<UserStatus | null>(null)
  const [statusEditing, setStatusEditing] = useState<Status | null>(null)
  const [statusReasonDraft, setStatusReasonDraft] = useState('')

  useEffect(() => {
    if (!ticker) return
    setTab('overview')
    setUserStatus(loadUserStatus(ticker))
    setStatusEditing(null)
    setStatusReasonDraft('')
  }, [ticker])

  if (!ticker) return null
  const profile = MOCK_PROFILES[ticker] ?? fallback(ticker)
  // Effective status: user override > mock default > 'researching'
  const effectiveStatus: Status | undefined = userStatus?.status ?? profile.status

  function commitStatus(skipReason: boolean) {
    if (!ticker || !statusEditing) return
    const reason = skipReason ? '(no reason given)' : statusReasonDraft.trim()
    if (!skipReason && !reason) return
    const newStatus: UserStatus = {
      status: statusEditing,
      reason: reason || '(empty)',
      ts: new Date().toISOString(),
    }
    saveUserStatus(ticker, newStatus)
    setUserStatus(newStatus)
    setStatusEditing(null)
    setStatusReasonDraft('')
  }

  const tabs: Array<{ k: TabKey; label: string; icon: typeof BarChart3 }> = [
    { k: 'overview',     label: 'Overview',         icon: Building2 },
    { k: 'smart_money',  label: 'Smart Money 接触', icon: BarChart3 },
    { k: 'supply_chain', label: '上下游',            icon: Network },
    { k: 'news',         label: 'News',              icon: Newspaper },
    { k: 'notes',        label: '我的笔记',          icon: NotebookPen },
    { k: 'chat',         label: 'Chat',              icon: MessagesSquare },
  ]

  // Status color map moved to STATUS_COLOR constant near
  // StatusPillSelector below (single source of truth).

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/40 z-40"
        onClick={closeTicker}
      />
      {/* Drawer */}
      <div className="fixed top-0 right-0 h-full w-[820px] max-w-[90vw] bg-[var(--color-bg)] border-l border-[var(--color-border)] z-50 flex flex-col shadow-2xl">
        {/* Header */}
        <div className="flex items-start gap-3 px-4 py-3 border-b border-[var(--color-border)] bg-[var(--color-panel)]/60">
          <div className="flex-1">
            <div className="flex items-center gap-3 flex-wrap">
              <span className="text-xl font-bold text-[var(--color-text)] font-mono">{ticker}</span>
              <span className="text-sm text-[var(--color-text)]">{profile.name}</span>
              <StatusPillSelector
                current={effectiveStatus}
                userStatus={userStatus}
                onPick={(s) => {
                  setStatusEditing(s)
                  setStatusReasonDraft('')
                }}
              />
            </div>
            <div className="text-[10px] text-[var(--color-dim)] mt-1 flex items-center gap-3 flex-wrap">
              <span>{profile.sector}</span>
              {profile.price && <span>· {profile.price}</span>}
              {profile.marketCap && <span>· cap {profile.marketCap}</span>}
              {profile.pe && <span>· PE {profile.pe}</span>}
              {profile.styleVerdict && (
                <span className="ml-2 italic">{profile.styleVerdict}</span>
              )}
            </div>
          </div>
          <button
            onClick={closeTicker}
            className="text-[var(--color-dim)] hover:text-[var(--color-text)] p-1 rounded"
            title="ESC to close"
          >
            <X size={16} />
          </button>
        </div>

        {/* Status reason editor (shown only while user is committing
            a new status — light-weight friction so 6 months later they
            remember WHY they marked it pass / own / etc.) */}
        {statusEditing && (
          <div className="flex items-center gap-2 px-4 py-2 bg-[var(--color-accent)]/10 border-b border-[var(--color-accent)]/40">
            <span className="text-[10px] text-[var(--color-text)] font-semibold">
              {statusEditing === 'researching' && '🔍 researching'}
              {statusEditing === 'watching'    && '👀 watching'}
              {statusEditing === 'pass'        && '✕ pass'}
              {statusEditing === 'own'         && '✓ own'}
            </span>
            <span className="text-[10px] text-[var(--color-dim)]">理由 (一句话):</span>
            <input
              type="text"
              autoFocus
              value={statusReasonDraft}
              onChange={(e) => setStatusReasonDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') commitStatus(false)
                if (e.key === 'Escape') setStatusEditing(null)
              }}
              placeholder="e.g. PE 太高 + 等中国出口管制明朗 (Enter 保存, Esc 取消)"
              className="flex-1 bg-[var(--color-bg)] border border-[var(--color-border)] rounded px-2 py-0.5 text-[10px] outline-none"
            />
            <button
              onClick={() => commitStatus(false)}
              disabled={!statusReasonDraft.trim()}
              className="text-[10px] px-2 py-0.5 rounded border border-[var(--color-accent)] text-[var(--color-accent)] hover:bg-[var(--color-accent)]/10 disabled:opacity-40"
            >
              保存
            </button>
            <button
              onClick={() => commitStatus(true)}
              className="text-[10px] px-2 py-0.5 rounded border border-[var(--color-border)] text-[var(--color-dim)] hover:text-[var(--color-text)]"
              title="跳过 (不推荐, 半年后会忘理由)"
            >
              跳过
            </button>
          </div>
        )}

        {/* Tab strip */}
        <div className="flex border-b border-[var(--color-border)] bg-[var(--color-bg)]">
          {tabs.map((t) => (
            <button
              key={t.k}
              onClick={() => setTab(t.k)}
              className={
                'flex items-center gap-1.5 px-3 py-2 text-[11px] border-b-2 transition ' +
                (tab === t.k
                  ? 'border-[var(--color-accent)] text-[var(--color-text)]'
                  : 'border-transparent text-[var(--color-dim)] hover:text-[var(--color-text)]')
              }
            >
              <t.icon size={11} />
              {t.label}
            </button>
          ))}
        </div>

        {/* Content area (scrollable) */}
        <div className="flex-1 overflow-y-auto p-4 text-[var(--color-text)] text-[12px] leading-[1.6]">
          {tab === 'overview' && (
            <>
              <div className="mb-3 flex items-center gap-2 text-[10px] text-[var(--color-dim)]">
                <Sparkles size={10} className="text-[var(--color-accent)]" />
                NeoMind generated · {profile.generatedAt}
                <button
                  className="ml-auto px-2 py-0.5 rounded border border-[var(--color-border)] hover:border-[var(--color-accent)] text-[var(--color-text)]"
                  onClick={() => alert('demo: 真实版本会触发 LLM 重新生成 business summary (~$0.01, 30-60s)')}
                >
                  ✨ regenerate
                </button>
                <a
                  href={`https://www.tradingview.com/symbols/${encodeURIComponent(ticker)}/`}
                  target="_blank" rel="noopener noreferrer"
                  className="px-2 py-0.5 rounded border border-[var(--color-border)] hover:border-[var(--color-accent)] text-[var(--color-text)] flex items-center gap-1"
                >
                  TradingView <ExternalLink size={9} />
                </a>
                <a
                  href={`https://finance.yahoo.com/quote/${encodeURIComponent(ticker)}`}
                  target="_blank" rel="noopener noreferrer"
                  className="px-2 py-0.5 rounded border border-[var(--color-border)] hover:border-[var(--color-accent)] text-[var(--color-text)] flex items-center gap-1"
                >
                  Yahoo <ExternalLink size={9} />
                </a>
              </div>

              <h3 className="text-[12px] font-semibold mb-1.5">业务概览</h3>
              <p className="mb-3 text-[11px] leading-[1.7]">{profile.summary}</p>

              {profile.segments.length > 0 && (
                <>
                  <h3 className="text-[12px] font-semibold mb-1.5">业务分段</h3>
                  <div className="space-y-1 mb-3">
                    {profile.segments.map((s) => (
                      <div key={s.name} className="flex items-center gap-2 text-[11px]">
                        <div className="w-24 flex-shrink-0">{s.name}</div>
                        <div className="flex-1 h-1.5 bg-[var(--color-panel)] rounded">
                          <div
                            className="h-full bg-[var(--color-accent)] rounded"
                            style={{ width: `${s.pct}%` }}
                          />
                        </div>
                        <span className="text-[10px] text-[var(--color-dim)] font-mono w-10 text-right">{s.pct}%</span>
                        {s.note && <span className="text-[9.5px] text-[var(--color-dim)] flex-1">{s.note}</span>}
                      </div>
                    ))}
                  </div>
                </>
              )}

              {profile.catalysts.length > 0 && (
                <>
                  <h3 className="text-[12px] font-semibold mb-1.5">未来催化剂</h3>
                  <div className="space-y-1 mb-3">
                    {profile.catalysts.map((c, i) => (
                      <div key={i} className="flex items-start gap-2 text-[11px]">
                        <span className={`text-[9px] font-mono w-20 flex-shrink-0 ${
                          c.severity === 'high' ? 'text-red-400' :
                          c.severity === 'med'  ? 'text-amber-400' : 'text-[var(--color-dim)]'
                        }`}>{c.when}</span>
                        <span className="flex-1">{c.what}</span>
                      </div>
                    ))}
                  </div>
                </>
              )}

              {profile.risks.length > 0 && (
                <>
                  <h3 className="text-[12px] font-semibold mb-1.5 text-red-300">主要风险</h3>
                  <ul className="space-y-1 mb-3 list-disc pl-4">
                    {profile.risks.map((r, i) => (
                      <li key={i} className="text-[11px]">{r}</li>
                    ))}
                  </ul>
                </>
              )}
            </>
          )}

          {tab === 'smart_money' && (
            <>
              <div className="mb-3 text-[10px] text-[var(--color-dim)]">
                所有跟 {ticker} 相关的 Smart Money 接触 (跨 4 source). 真实版会从 signal_events table join 实时.
              </div>
              {profile.smartMoney.length === 0 ? (
                <div className="text-[11px] italic text-[var(--color-dim)]">无 Smart Money 接触.</div>
              ) : (
                <div className="space-y-1">
                  {profile.smartMoney.map((m, i) => (
                    <div key={i} className="flex items-start gap-2 text-[11px] py-1 px-2 border border-[var(--color-border)]/40 rounded">
                      <span className="text-[9px] font-mono w-20 flex-shrink-0 text-[var(--color-dim)]">{m.source}</span>
                      <span className="font-semibold w-44 flex-shrink-0">{m.who}</span>
                      <span className="flex-1">{m.action}</span>
                      {m.size && <span className="text-[10px] text-[var(--color-text)] font-mono">{m.size}</span>}
                      <span className="text-[9px] text-[var(--color-dim)] font-mono w-20 text-right">{m.when}</span>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}

          {tab === 'supply_chain' && (
            <>
              <div className="mb-3 text-[10px] text-[var(--color-dim)]">
                LLM-extracted 自 SEC 10-K + 行业知识. 每个 ticker 可点 → 打开它的 drawer (graph navigation).
              </div>

              <h3 className="text-[12px] font-semibold mb-2 text-green-300">⬆ Upstream (供应商)</h3>
              <div className="space-y-1 mb-4">
                {profile.upstream.map((u) => (
                  <div key={u.ticker} className="flex items-start gap-2 text-[11px] py-1 px-2 border border-[var(--color-border)]/40 rounded">
                    <button
                      onClick={() => openTicker(u.ticker)}
                      className="font-mono w-20 flex-shrink-0 text-[var(--color-accent)] hover:underline text-left"
                    >
                      {u.ticker}
                    </button>
                    <span className="w-44 flex-shrink-0">{u.name}</span>
                    <span className="text-[10px] text-[var(--color-dim)] flex-1">{u.role}</span>
                  </div>
                ))}
              </div>

              <h3 className="text-[12px] font-semibold mb-2 text-blue-300">⬇ Downstream (大客户)</h3>
              <div className="space-y-1 mb-4">
                {profile.downstream.map((d) => (
                  <div key={d.ticker} className="flex items-start gap-2 text-[11px] py-1 px-2 border border-[var(--color-border)]/40 rounded">
                    <button
                      onClick={() => openTicker(d.ticker)}
                      className="font-mono w-20 flex-shrink-0 text-[var(--color-accent)] hover:underline text-left"
                    >
                      {d.ticker}
                    </button>
                    <span className="w-44 flex-shrink-0">{d.name}</span>
                    <span className="text-[10px] text-[var(--color-dim)] flex-1">{d.role}</span>
                  </div>
                ))}
              </div>

              <h3 className="text-[12px] font-semibold mb-2 text-amber-300">⚔ Competitors</h3>
              <div className="space-y-1">
                {profile.competitors.map((c) => (
                  <div key={c.ticker} className="flex items-start gap-2 text-[11px] py-1 px-2 border border-[var(--color-border)]/40 rounded">
                    <button
                      onClick={() => openTicker(c.ticker)}
                      className="font-mono w-20 flex-shrink-0 text-[var(--color-accent)] hover:underline text-left"
                    >
                      {c.ticker}
                    </button>
                    <span className="w-44 flex-shrink-0">{c.name}</span>
                    <span className="text-[10px] text-[var(--color-dim)] flex-1">{c.note}</span>
                  </div>
                ))}
              </div>
            </>
          )}

          {tab === 'news' && (
            <>
              <div className="mb-3 text-[10px] text-[var(--color-dim)]">
                LLM 过滤过的 material events (筛掉 clickbait). 真实版会从 news_scanner pipeline + Quiver/finnhub 拉.
              </div>
              <div className="space-y-2">
                {profile.news.map((n, i) => (
                  <div key={i} className="border border-[var(--color-border)]/40 rounded p-2">
                    <div className="flex items-start gap-2 mb-1">
                      <span className={`text-[9px] font-mono w-20 flex-shrink-0 ${
                        n.severity === 'high' ? 'text-red-400' : 'text-amber-400'
                      }`}>{n.date}</span>
                      <span className="text-[11px] font-semibold flex-1">{n.headline}</span>
                    </div>
                    <p className="text-[10px] text-[var(--color-dim)] ml-22">{n.summary}</p>
                  </div>
                ))}
              </div>
            </>
          )}

          {tab === 'notes' && (
            <>
              <div className="mb-3 text-[10px] text-[var(--color-dim)]">
                你的笔记 + LLM 抽取的 tag (e.g. valuation_concern). 永不被 LLM overwrite.
              </div>
              <div className="space-y-2 mb-4">
                {profile.notes.map((n, i) => (
                  <div key={i} className="border border-[var(--color-border)]/40 rounded p-2">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-[9px] font-mono text-[var(--color-dim)]">{n.ts}</span>
                      {n.tag && (
                        <span className="text-[9px] font-mono px-1.5 py-0 rounded border border-[var(--color-amber)]/40 text-[var(--color-amber)]">
                          {n.tag}
                        </span>
                      )}
                    </div>
                    <p className="text-[11px]">{n.body}</p>
                  </div>
                ))}
              </div>
              <div className="border border-dashed border-[var(--color-border)] rounded p-2">
                <textarea
                  className="w-full bg-transparent text-[11px] outline-none resize-none"
                  rows={3}
                  placeholder="写一条笔记… 真实版会 LLM 抽取 tag 并存到 stock_notes table"
                  disabled
                />
                <button className="text-[10px] mt-1 px-2 py-0.5 rounded border border-[var(--color-border)] text-[var(--color-dim)]" disabled>
                  add note (demo disabled)
                </button>
              </div>
            </>
          )}

          {tab === 'chat' && (
            <DrawerChatTab ticker={ticker} projectId={projectId} />
          )}
        </div>
      </div>
    </>
  )
}


// ─── Status pill — clickable, opens 4-option dropdown ─────────────

const STATUS_LABEL: Record<Status, string> = {
  researching: '🔍 researching',
  watching:    '👀 watching',
  pass:        '✕ pass',
  own:         '✓ own',
}
const STATUS_COLOR: Record<Status, string> = {
  researching: 'bg-amber-500/20 text-amber-300 border-amber-500/40',
  watching:    'bg-blue-500/20 text-blue-300 border-blue-500/40',
  pass:        'bg-red-500/20 text-red-300 border-red-500/40',
  own:         'bg-green-500/20 text-green-300 border-green-500/40',
}

function StatusPillSelector({
  current, userStatus, onPick,
}: {
  current?: Status
  userStatus: UserStatus | null
  onPick: (s: Status) => void
}) {
  const [open, setOpen] = useState(false)
  return (
    <div className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className={`text-[10px] font-mono px-1.5 py-0.5 rounded border hover:brightness-125 ${
          current ? STATUS_COLOR[current] : 'border-[var(--color-border)] text-[var(--color-dim)]'
        }`}
        title={
          userStatus
            ? `状态: ${STATUS_LABEL[userStatus.status]}\n理由: ${userStatus.reason}\n更新: ${new Date(userStatus.ts).toLocaleString()}\n\n点击改变`
            : '点击设置状态 (researching / watching / pass / own) — 强制要求一句话理由, 6 个月后回看'
        }
      >
        {current ? STATUS_LABEL[current] : '⊕ set status'}
        <span className="ml-1 text-[8px]">▾</span>
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-50" onClick={() => setOpen(false)} />
          <div className="absolute top-full left-0 mt-1 bg-[var(--color-bg)] border border-[var(--color-border)] rounded shadow-lg z-50 w-44">
            {(Object.keys(STATUS_LABEL) as Status[]).map((s) => (
              <button
                key={s}
                onClick={() => { onPick(s); setOpen(false) }}
                className={`block w-full text-left px-2 py-1 text-[10px] hover:bg-[var(--color-panel)] ${
                  s === current ? 'bg-[var(--color-panel)]/50' : ''
                }`}
              >
                {STATUS_LABEL[s]}
                <span className="text-[8px] text-[var(--color-dim)] ml-1">
                  {s === 'researching' && '研究中, 未决定'}
                  {s === 'watching'    && '看好, 等 timing'}
                  {s === 'pass'        && '决定不买'}
                  {s === 'own'         && '已持有'}
                </span>
              </button>
            ))}
            {userStatus?.reason && (
              <div className="border-t border-[var(--color-border)] px-2 py-1.5 text-[8.5px] text-[var(--color-dim)] italic">
                上次理由: {userStatus.reason}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}


// ─── Drawer Chat Tab — embeds real ChatPanel + ticker context ─────

const DRAWER_SESSIONS_KEY = 'neomind.research.drawer_sessions'

interface DrawerSession {
  ticker: string
  pid: string
  ts: string
  preview: string  // first user message
}

function loadDrawerSessions(ticker: string): DrawerSession[] {
  try {
    const raw = localStorage.getItem(DRAWER_SESSIONS_KEY)
    const all = raw ? JSON.parse(raw) as DrawerSession[] : []
    return all.filter((s) => s.ticker === ticker)
  } catch { return [] }
}

function DrawerChatTab({ ticker, projectId }: { ticker: string; projectId: string }) {
  // Auto-inject ticker context into the next message via the existing
  // ChatPanel `pendingContext` mechanism. The user types as normal but
  // the agent's system prompt gets `context_symbol={ticker}` appended,
  // so it knows we're talking about NVDA.
  const [pendingPrompt, setPendingPrompt] = useState<string | null>(null)
  const [pendingContext, setPendingContext] = useState<{ symbol?: string } | null>(null)
  const [drawerSessions] = useState(() => loadDrawerSessions(ticker))

  // First time the user opens this tab for a fresh ticker, we auto-
  // prime the context flag so the very first send carries it.
  useEffect(() => {
    setPendingContext({ symbol: ticker })
  }, [ticker])

  return (
    <div className="flex flex-col h-full -m-4">
      {/* Tiny ticker-scoped session list at top — drawer-local view
          of the global chat_sessions store (these sessions also
          appear in the main Strategies tab session list). */}
      {drawerSessions.length > 0 && (
        <div className="px-3 py-2 border-b border-[var(--color-border)] bg-[var(--color-panel)]/20">
          <div className="text-[9.5px] text-[var(--color-dim)] mb-1.5 flex items-center gap-2">
            <span className="font-semibold">在 drawer 里聊过的 sessions ({drawerSessions.length}):</span>
            <span className="text-[8.5px] italic">同样出现在主界面 session list</span>
          </div>
          <div className="flex flex-wrap gap-1">
            {drawerSessions.slice(0, 5).map((s, i) => (
              <button
                key={i}
                className="text-[9px] px-2 py-0.5 rounded border border-[var(--color-border)] hover:border-[var(--color-accent)] text-[var(--color-text)] truncate max-w-[200px]"
                title={`${new Date(s.ts).toLocaleString()}\n${s.preview}`}
                onClick={() => alert('demo: 真实版会 restore 这个 session 继续聊')}
              >
                {s.preview.slice(0, 30)}…
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Real ChatPanel embed — pending context auto-injects ticker */}
      <div className="flex-1 min-h-0">
        <ChatPanel
          projectId={projectId}
          pendingPrompt={pendingPrompt}
          pendingContext={pendingContext}
          onConsumePendingPrompt={() => {
            setPendingPrompt(null)
            // Keep symbol context active for follow-up turns in this
            // ticker session — clear only when drawer closes.
          }}
          hideSessions={true}  // drawer has its own session list above
        />
      </div>

      {/* Quick prompt suggestions to seed the conversation */}
      <div className="px-3 py-2 border-t border-[var(--color-border)] bg-[var(--color-panel)]/20">
        <div className="text-[9px] text-[var(--color-dim)] mb-1">建议问 (点击发送):</div>
        <div className="flex flex-wrap gap-1">
          {[
            `${ticker} 估值合理吗? 给我 PE / PS / 现金流的对比`,
            `${ticker} 上下游受制于谁? 最大风险节点是?`,
            `${ticker} vs 直接竞争对手谁的护城河更深?`,
            `如果 AI capex 周期见顶, ${ticker} 估值压缩多少?`,
          ].map((p) => (
            <button
              key={p}
              onClick={() => setPendingPrompt(p)}
              className="text-[9px] px-2 py-0.5 rounded border border-[var(--color-border)] hover:border-[var(--color-accent)] text-[var(--color-dim)] hover:text-[var(--color-text)]"
            >
              {p.slice(0, 30)}…
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}
