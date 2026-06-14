import { useEffect, useRef, useState } from 'react'
import { cn } from '@/lib/utils'
import { useHealth } from '@/lib/api'
import { ResearchTab } from '@/tabs/Research'
import { TradingTab } from '@/tabs/Trading'
import { CoreTab } from '@/tabs/Core'
import { AuditTab } from '@/tabs/Audit'
import { SettingsTab } from '@/tabs/Settings'
import { LearningTab } from '@/tabs/Learning'
import { LegacyTab } from '@/tabs/Legacy'
import { StrategiesTab } from '@/tabs/Strategies'
import { DataLakeTab } from '@/tabs/DataLake'
import { WatchlistTab } from '@/tabs/Watchlist'
import { CognitionMapTab } from '@/tabs/CognitionMap'
import { SerenityTab } from '@/tabs/Serenity'
import { CommandPalette } from '@/components/chat/CommandPalette'
import type { DigestFocus } from '@/components/widgets/DigestView'
import { FinIntegrityBadge } from '@/components/widgets/FinIntegrityBadge'
import { PdtCounter } from '@/components/widgets/PdtCounter'
import { AsOfPicker } from '@/components/widgets/AsOfPicker'
import { ScannerHealthBadge } from '@/components/widgets/ScannerHealthBadge'
import { Sparkles, LineChart, Zap, ClipboardList, Settings as SettingsIcon, Command, BookOpen, Database, GraduationCap, Menu, X, RotateCw, Landmark, Network, ChevronDown, Boxes } from 'lucide-react'
import { StockResearchProvider } from '@/components/research/StockResearchContext'
import { StockResearchDrawer } from '@/components/research/StockResearchDrawer'
import { WhaleResearchProvider } from '@/components/research/WhaleResearchContext'
import { WhaleProfileDrawer } from '@/components/research/WhaleProfileDrawer'

// 'legacy' is intentionally NOT in main nav. Reachable via Settings →
// "Open legacy dashboard" or by appending ?legacy=1 to the URL.
// 'watchlist' kept in the union for any legacy ?tab=watchlist deep
// link; it routes to <WatchlistTab> which still works as a standalone
// page even though it's no longer in the nav array.
// 2026-05-22: 'paper' tab folded into the new 'trading' tab (short-term
// trading desk). Paper trading is part of the trading workflow, not a
// standalone surface. 'paper' kept in the union only for old deep links
// (routes to the Trading tab).
type Tab = 'research' | 'serenity' | 'strategies' | 'core' | 'trading' | 'paper' | 'audit' | 'data_lake' | 'learning' | 'cognition' | 'watchlist' | 'settings' | 'legacy'

const TABS: Array<{ id: Tab; label: string; icon: React.ComponentType<{ size?: number }> }> = [
  // 2026-05-08: Watchlist removed from nav — content embedded as a
  // section at top of the Strategies tab. User feedback was "零零散散
  // 不好集中看" (scattered, hard to view together).
  { id: 'research',   label: 'Research',   icon: LineChart },
  { id: 'serenity',   label: 'Serenity',   icon: Sparkles },
  { id: 'strategies', label: 'Strategies', icon: BookOpen },
  // Bucket ① — long-term core holdings: risk monitor + systematic hedge overlay.
  { id: 'core',       label: 'Core',       icon: Landmark },
  // 2026-05-22: Short-term Trading Desk — TPS + NL→quant setup distillation
  // + backtest + paper validation. Folds in the old standalone Paper tab.
  { id: 'trading',    label: 'Trading',    icon: Zap },
  { id: 'audit',      label: 'Audit',      icon: ClipboardList },
  // Phase B6-Step2: Data Lake tab — provenance browser over the raw
  // store (B1-B3) and the dep_hash compute cache (B4-B5).
  { id: 'data_lake',  label: 'Data Lake',  icon: Database },
  // Phase L (2026-05-04): investing case-study library — daily fresh
  // material from miniflux + Tavily + LLM gate, plus 14 hand-curated
  // evergreen Chinese-first cases.
  { id: 'learning',   label: 'Learning',   icon: GraduationCap },
  // Cognition Map — personal world-model knowledge graph (md+git vault +
  // provenance-coloured force graph). See agent/finance/cognition_map.py.
  { id: 'cognition',  label: 'Cognition',  icon: Network },
  { id: 'settings',   label: 'Settings',   icon: SettingsIcon },
]

// Desktop grouped nav (9 flat tabs → 5 top-level + a right-side 系统 dropdown).
// Mobile keeps the flat TABS list above (a vertical drawer isn't cluttered).
type NavIcon = React.ComponentType<{ size?: number }>
type NavSingle = { id: Tab; label: string; icon: NavIcon }
type NavGroupDef = { group: string; icon: NavIcon; items: NavSingle[] }

const NAV_GROUPS: Array<NavSingle | NavGroupDef> = [
  { id: 'research',   label: 'Research',   icon: LineChart },
  { id: 'serenity',   label: 'Serenity',   icon: Sparkles },
  { id: 'strategies', label: 'Strategies', icon: BookOpen },
  { group: '持仓', icon: Landmark, items: [
    { id: 'core',    label: 'Core · 长线',    icon: Landmark },
    { id: 'trading', label: 'Trading · 短线', icon: Zap },
  ] },
  { group: '知识', icon: Network, items: [
    { id: 'cognition',  label: 'Cognition · 认知图',  icon: Network },
    { id: 'learning',   label: 'Learning · 案例库',   icon: GraduationCap },
  ] },
  { id: 'settings', label: 'Settings', icon: SettingsIcon },
]
// Low-frequency infra surfaces — tucked into a right-aligned 系统 dropdown.
const SYSTEM_ITEMS: NavSingle[] = [
  { id: 'audit',     label: 'Audit · 审计追踪', icon: ClipboardList },
  { id: 'data_lake', label: 'Data Lake · 溯源', icon: Database },
]

function NavGroupMenu({ label, icon: Icon, items, tab, onPick, open, onToggle, align = 'left' }: {
  label: string; icon: NavIcon; items: NavSingle[]; tab: Tab
  onPick: (id: Tab) => void; open: boolean; onToggle: (v: string | null) => void
  align?: 'left' | 'right'
}) {
  const ref = useRef<HTMLDivElement>(null)
  // Close on click outside (NOT mouse-leave: the menu is absolutely positioned
  // outside the button box, so mouse-leave fired before the cursor reached the
  // items and the dropdown was unselectable).
  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onToggle(null)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open, onToggle])
  const active = items.some(i => i.id === tab)
  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => onToggle(open ? null : label)}
        className={cn('flex items-center gap-1.5 px-3 py-1 rounded text-xs transition',
          active ? 'bg-[var(--color-border)] text-[var(--color-accent)]'
                 : 'text-[var(--color-dim)] hover:text-[var(--color-text)] hover:bg-[var(--color-border)]/50')}
      >
        <Icon size={12} /> {label} <ChevronDown size={10} className={open ? 'rotate-180' : ''} />
      </button>
      {open && (
        <div className={cn('absolute z-50 mt-1 min-w-[170px] bg-[var(--color-panel)] border border-[var(--color-border)] rounded shadow-xl py-1',
          align === 'right' ? 'right-0' : 'left-0')}>
          {items.map(it => (
            <button key={it.id} data-testid={`tab-${it.id}`}
              onClick={() => { onPick(it.id); onToggle(null) }}
              className={cn('w-full flex items-center gap-2 px-3 py-1.5 text-xs text-left transition',
                tab === it.id ? 'text-[var(--color-accent)] bg-[var(--color-border)]/60'
                              : 'text-[var(--color-text)] hover:bg-[var(--color-border)]/50')}>
              <it.icon size={12} /> {it.label}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

export default function App() {
  const [tab, setTab] = useState<Tab>(() => {
    if (typeof window !== 'undefined' && window.location.search.includes('legacy=1')) {
      return 'legacy'
    }
    return 'research'
  })
  const [projectId, setProjectId] = useState<string>(
    () => localStorage.getItem('neomind.project') ?? 'fin-core'
  )
  const [auditReqFilter, setAuditReqFilter] = useState<string | null>(null)
  const [pendingChatPrompt, setPendingChatPrompt] = useState<string | null>(null)
  const [pendingChatContext, setPendingChatContext] = useState<{ symbol?: string; project?: boolean } | null>(null)
  const [paletteOpen, setPaletteOpen] = useState(false)
  // Mobile nav drawer — hamburger toggles. Auto-closes when user
  // picks a tab (so the underlying content shows immediately).
  const [mobileNavOpen, setMobileNavOpen] = useState(false)
  // Which desktop nav dropdown (持仓 / 知识 / 系统) is open, by label.
  const [openMenu, setOpenMenu] = useState<string | null>(null)
  // 2026-05-19: self-restart admin button — POSTs /api/admin/restart
  // then polls /api/health until the new process comes up, then reloads.
  const [restarting, setRestarting] = useState(false)
  async function restartServer() {
    if (restarting) return
    if (!confirm('重启 dashboard server? (~3-5 秒, 然后页面会自动 reload)')) return
    setRestarting(true)
    try {
      await fetch('/api/admin/restart', { method: 'POST' })
    } catch { /* expected — connection dies as server execs */ }
    // Poll /api/health every 500ms; once it comes back, hard reload
    const startedAt = Date.now()
    const poll = async () => {
      try {
        const r = await fetch('/api/health', { cache: 'no-store' })
        if (r.ok) { location.reload(); return }
      } catch { /* still down */ }
      if (Date.now() - startedAt > 30_000) {
        alert('重启超时 — server 没回应. 手动检查 /tmp/dashboard.log')
        setRestarting(false)
        return
      }
      setTimeout(poll, 500)
    }
    setTimeout(poll, 1500)  // give it 1.5s before first check
  }
  const [digestFocus, setDigestFocus] = useState<DigestFocus | null>(null)
  // Phase 5 V4: focused strategy id when arriving from a call's
  // strategy_match chip. Carries a nonce so clicking the same chip
  // twice re-triggers the focus animation in StrategiesTab.
  const [strategyFocus, setStrategyFocus] = useState<{ id: string; nonce: number } | null>(null)
  // Phase A (temporal replay): global as_of value. 'live' (default)
  // means use current lattice synth; YYYY-MM-DD reads the snapshot
  // for that date. Threaded into Research + Strategies tabs so they
  // stay time-coherent. See docs/design/2026-04-26_temporal-replay-architecture.md
  const [appAsOf, setAppAsOf] = useState<string>(
    () => localStorage.getItem('neomind.as_of') ?? 'live',
  )
  function setAsOfPersist(next: string) {
    setAppAsOf(next)
    if (next === 'live') localStorage.removeItem('neomind.as_of')
    else localStorage.setItem('neomind.as_of', next)
  }
  const health = useHealth()

  // Global ⌘K / Ctrl+K — command palette. Works from any tab.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setPaletteOpen(o => !o)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  function switchProject(p: string) {
    setProjectId(p)
    try { localStorage.setItem('neomind.project', p) } catch {}
  }

  function jumpToAudit(reqId: string) {
    setAuditReqFilter(reqId)
    setTab('audit')
  }

  /**
   * `ctx` carries the synthesis hint — when set, the chat's next
   * message includes a DASHBOARD STATE block so the agent sees the
   * widget data (position, earnings, technical pills, etc.) alongside
   * the prompt text. Widgets that ask-about-a-symbol should pass
   * `{symbol: "AAPL"}`; slash commands that scan the whole project
   * pass `{project: true}`.
   */
  function jumpToChat(prompt: string, ctx?: { symbol?: string; project?: boolean }) {
    setPendingChatPrompt(prompt)
    setPendingChatContext(ctx ?? null)
    // Chat tab removed 2026-05-01 — Strategies right rail is the
    // only ChatPanel mount, so all "ask agent" jumps land there.
    setTab('strategies')
  }

  /**
   * Reverse of jumpToChat: from a chat citation chip, jump back
   * to Research and light up the evidence rows for `symbol`.
   * Nonce bumps every call so clicking the same cite twice still
   * re-triggers the highlight animation.
   *
   * Phase 6 followup: also accepts a `widgetId` so the Strategies
   * tab can deep-link into the lattice graph focused on a specific
   * L0 widget node (closing the strategy → widget → lattice loop).
   */
  function jumpToResearch(focus: { symbol?: string; widgetId?: string; nodeId?: string }) {
    setDigestFocus({
      symbol:   focus.symbol,
      widgetId: focus.widgetId,
      nodeId:   focus.nodeId,
      nonce:    Date.now(),
    })
    setTab('research')
  }

  /**
   * Phase 5 V4: arrive at the Strategies tab focused on a specific
   * catalog entry. Used when the user clicks a call's strategy_match
   * chip in the Research tab — closes the lattice → catalog loop.
   */
  function jumpToStrategies(strategyId: string) {
    setStrategyFocus({ id: strategyId, nonce: Date.now() })
    setTab('strategies')
  }

  return (
    <StockResearchProvider projectId={projectId}>
    <WhaleResearchProvider>
    <div className="h-full flex flex-col">
      <StockResearchDrawer />
      <WhaleProfileDrawer />
      {/* Top nav.
          Layout strategy:
            - <md (mobile): hamburger button + brand only. Tabs and
              status widgets all live in the slide-in drawer (rendered
              below header). Drawer auto-closes on tab pick.
            - >=md (desktop): full inline nav + status widgets, exactly
              as before. */}
      <header className="flex flex-wrap items-center gap-2 md:gap-4 px-3 md:px-4 py-2 bg-[var(--color-panel)] border-b border-[var(--color-border)] shrink-0 min-w-0">
        {/* Mobile-only hamburger */}
        <button
          aria-label="Open navigation"
          data-testid="mobile-nav-toggle"
          onClick={() => setMobileNavOpen(true)}
          className="md:hidden p-1 -ml-1 text-[var(--color-text)] hover:text-[var(--color-accent)] flex-shrink-0"
        >
          <Menu size={18} />
        </button>

        <div className="flex items-center gap-2 text-[var(--color-text)] min-w-0">
          <Sparkles size={15} className="text-[var(--color-accent)] flex-shrink-0" />
          <span className="font-semibold truncate">neomind / fin</span>
        </div>

        {/* Desktop-only inline nav — grouped (持仓/知识 dropdowns) */}
        <nav className="hidden md:flex items-center gap-1" data-testid="top-nav">
          {NAV_GROUPS.map(e => (
            'items' in e ? (
              <NavGroupMenu
                key={e.group} label={e.group} icon={e.icon} items={e.items}
                tab={tab} onPick={setTab} open={openMenu === e.group} onToggle={setOpenMenu}
              />
            ) : (
              <button
                key={e.id}
                data-testid={`tab-${e.id}`}
                onClick={() => setTab(e.id)}
                className={cn(
                  'flex items-center gap-1.5 px-3 py-1 rounded text-xs transition',
                  tab === e.id
                    ? 'bg-[var(--color-border)] text-[var(--color-accent)]'
                    : 'text-[var(--color-dim)] hover:text-[var(--color-text)] hover:bg-[var(--color-border)]/50',
                )}
              >
                <e.icon size={12} />
                {e.label}
              </button>
            )
          ))}
        </nav>

        <div className="flex-1" />

        {/* Active tab name visible on mobile so user knows where they are */}
        <span className="md:hidden text-[11px] text-[var(--color-accent)] truncate">
          {TABS.find(t => t.id === tab)?.label ?? ''}
        </span>

        {/* 系统 — low-frequency infra surfaces, tucked right (desktop) */}
        <div className="hidden md:block">
          <NavGroupMenu
            label="系统" icon={Boxes} items={SYSTEM_ITEMS}
            tab={tab} onPick={setTab} open={openMenu === '系统'} onToggle={setOpenMenu} align="right"
          />
        </div>

        {/* ⌘K — desktop only (no keyboard on mobile) */}
        <button
          data-testid="palette-open"
          onClick={() => setPaletteOpen(true)}
          className="hidden md:flex items-center gap-1.5 text-[10px] text-[var(--color-dim)] hover:text-[var(--color-text)] border border-[var(--color-border)] rounded px-2 py-1 transition"
          title="Command palette — ⌘K / Ctrl+K"
        >
          <Command size={10} />
          <span>K</span>
        </button>

        {/* Status widgets — desktop only (move to drawer on mobile) */}
        <div className="hidden md:flex items-center gap-2 text-[10px] text-[var(--color-dim)]">
          <AsOfPicker projectId={projectId} value={appAsOf} onChange={setAsOfPersist} />
          <PdtCounter />
          <FinIntegrityBadge />
          <ScannerHealthBadge />
          <span>Project: <code className="text-[var(--color-accent)]">{projectId}</code></span>
          <span className={health.data ? 'text-[var(--color-green)]' : 'text-[var(--color-red)]'}>
            ● {health.data ? `healthy · ${health.data.version}` : 'unreachable'}
          </span>
          <button
            onClick={restartServer}
            disabled={restarting}
            className={'flex items-center gap-1 text-[10px] border border-[var(--color-border)] rounded px-2 py-1 transition ' +
              (restarting
                ? 'text-[var(--color-amber)] cursor-wait'
                : 'text-[var(--color-dim)] hover:text-[var(--color-text)] hover:border-[var(--color-accent)]')}
            title="重启 dashboard server (~3-5 秒, 然后页面自动 reload)"
          >
            <RotateCw size={10} className={restarting ? 'animate-spin' : ''} />
            <span>{restarting ? '重启中...' : '重启'}</span>
          </button>
        </div>
      </header>

      {/* Mobile drawer — slides in from left. Backdrop closes it. */}
      {mobileNavOpen && (
        <div className="md:hidden fixed inset-0 z-50 flex" data-testid="mobile-nav-drawer">
          {/* Drawer panel */}
          <div className="w-[78vw] max-w-[320px] h-full bg-[var(--color-panel)] border-r border-[var(--color-border)] flex flex-col overflow-y-auto shadow-2xl">
            <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--color-border)]">
              <div className="flex items-center gap-2">
                <Sparkles size={15} className="text-[var(--color-accent)]" />
                <span className="font-semibold text-[var(--color-text)]">neomind / fin</span>
              </div>
              <button
                aria-label="Close navigation"
                onClick={() => setMobileNavOpen(false)}
                className="p-1 text-[var(--color-dim)] hover:text-[var(--color-text)]"
              >
                <X size={18} />
              </button>
            </div>

            {/* Tabs */}
            <nav className="flex flex-col py-2">
              {TABS.map(({ id, label, icon: Icon }) => (
                <button
                  key={id}
                  data-testid={`mobile-tab-${id}`}
                  onClick={() => { setTab(id); setMobileNavOpen(false) }}
                  className={cn(
                    'flex items-center gap-2.5 px-4 py-3 text-[13px] transition text-left',
                    tab === id
                      ? 'bg-[var(--color-border)] text-[var(--color-accent)]'
                      : 'text-[var(--color-text)] hover:bg-[var(--color-border)]/50',
                  )}
                >
                  <Icon size={15} />
                  {label}
                </button>
              ))}
            </nav>

            {/* Status section */}
            <div className="mt-auto px-4 py-3 border-t border-[var(--color-border)] space-y-2 text-[11px] text-[var(--color-dim)]">
              <div className="flex items-center justify-between">
                <span>Project:</span>
                <code className="text-[var(--color-accent)]">{projectId}</code>
              </div>
              <div className="flex items-center justify-between">
                <span>Status:</span>
                <span className={health.data ? 'text-[var(--color-green)]' : 'text-[var(--color-red)]'}>
                  ● {health.data ? `healthy · ${health.data.version}` : 'unreachable'}
                </span>
              </div>
              <div className="pt-2 border-t border-[var(--color-border)] flex flex-wrap items-center gap-2">
                <AsOfPicker projectId={projectId} value={appAsOf} onChange={setAsOfPersist} />
                <PdtCounter />
                <FinIntegrityBadge />
              </div>
            </div>
          </div>
          {/* Backdrop */}
          <div
            className="flex-1 bg-black/50"
            onClick={() => setMobileNavOpen(false)}
            aria-label="Close navigation backdrop"
          />
        </div>
      )}

      <CommandPalette
        open={paletteOpen}
        onClose={() => setPaletteOpen(false)}
        onPick={(cmd) => {
          // Route to Strategies (which hosts the only ChatPanel mount
          // since the standalone Chat tab was removed) with the
          // command queued as pending prompt. ChatPanel's useEffect
          // populates input; user hits enter to send.
          setPendingChatPrompt(cmd)
          setPendingChatContext(null)   // workflow commands inject context server-side
          setTab('strategies')
        }}
      />

      {/* Active tab.
          Research + Strategies are always-mounted (display:none when
          inactive) so local state — selected lattice node, expanded
          strategy card, scroll position, mode toggles — survives a
          tab switch. The user reported losing context after a cross-
          tab jump; this fixes it. Other tabs are conditionally
          rendered as before since they don't carry rich local state. */}
      <main className="flex-1 overflow-hidden flex flex-col">
        <div
          className="flex-1 overflow-hidden flex flex-col"
          style={{ display: tab === 'research' ? 'flex' : 'none' }}
        >
          <ResearchTab
            projectId={projectId}
            onJumpToChat={jumpToChat}
            digestFocus={digestFocus}
            onJumpToStrategies={jumpToStrategies}
            asOf={appAsOf}
          />
        </div>
        <div
          className="flex-1 overflow-hidden flex flex-col"
          style={{ display: tab === 'strategies' ? 'flex' : 'none' }}
        >
          <StrategiesTab
            projectId={projectId}
            onJumpToChat={(p, ctx) => jumpToChat(p, ctx)}
            focus={strategyFocus}
            onJumpToResearch={(widgetId) => jumpToResearch({ widgetId })}
            onJumpToResearchNode={(nodeId) => jumpToResearch({ nodeId })}
            asOf={appAsOf}
            onChangeAsOf={setAsOfPersist}
            onJumpToAudit={jumpToAudit}
            onNavigateToResearch={jumpToResearch}
            pendingPrompt={pendingChatPrompt}
            pendingContext={pendingChatContext}
            onConsumePendingPrompt={() => {
              setPendingChatPrompt(null)
              setPendingChatContext(null)
            }}
          />
        </div>
        {tab === 'core' && <CoreTab />}
        {(tab === 'trading' || tab === 'paper') && <TradingTab projectId={projectId} />}
        {tab === 'audit'    && (
          <AuditTab
            initialReqFilter={auditReqFilter}
            onConsumeFilter={() => setAuditReqFilter(null)}
          />
        )}
        {tab === 'data_lake' && <DataLakeTab projectId={projectId} />}
        {tab === 'learning' && <LearningTab />}
        {tab === 'cognition' && <CognitionMapTab projectId={projectId} />}
        {tab === 'watchlist' && <WatchlistTab />}
        {tab === 'serenity' && <SerenityTab />}
        {tab === 'settings' && (
          <SettingsTab
            projectId={projectId}
            onProjectChange={switchProject}
            onOpenLegacy={() => setTab('legacy')}
          />
        )}
        {tab === 'legacy'   && (
          <LegacyTab
            projectId={projectId}
            onJumpToChat={jumpToChat}
            digestFocus={digestFocus}
          />
        )}
      </main>
    </div>
    </WhaleResearchProvider>
    </StockResearchProvider>
  )
}
