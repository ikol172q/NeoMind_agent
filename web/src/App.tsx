import { useEffect, useState } from 'react'
import { cn } from '@/lib/utils'
import { useHealth } from '@/lib/api'
import { ResearchTab } from '@/tabs/Research'
import { ChatTab } from '@/tabs/Chat'
import { PaperTab } from '@/tabs/Paper'
import { AuditTab } from '@/tabs/Audit'
import { SettingsTab } from '@/tabs/Settings'
import { CommandPalette } from '@/components/chat/CommandPalette'
import type { DigestFocus } from '@/components/widgets/DigestView'
import { Sparkles, LineChart, MessagesSquare, Wallet, ClipboardList, Settings as SettingsIcon, Command } from 'lucide-react'

type Tab = 'research' | 'chat' | 'paper' | 'audit' | 'settings'

const TABS: Array<{ id: Tab; label: string; icon: React.ComponentType<{ size?: number }> }> = [
  { id: 'research', label: 'Research', icon: LineChart },
  { id: 'chat',     label: 'Chat',     icon: MessagesSquare },
  { id: 'paper',    label: 'Paper',    icon: Wallet },
  { id: 'audit',    label: 'Audit',    icon: ClipboardList },
  { id: 'settings', label: 'Settings', icon: SettingsIcon },
]

export default function App() {
  const [tab, setTab] = useState<Tab>('research')
  const [projectId, setProjectId] = useState<string>(
    () => localStorage.getItem('neomind.project') ?? 'fin-core'
  )
  const [auditReqFilter, setAuditReqFilter] = useState<string | null>(null)
  const [pendingChatPrompt, setPendingChatPrompt] = useState<string | null>(null)
  const [pendingChatContext, setPendingChatContext] = useState<{ symbol?: string; project?: boolean } | null>(null)
  const [paletteOpen, setPaletteOpen] = useState(false)
  const [digestFocus, setDigestFocus] = useState<DigestFocus | null>(null)
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
    setTab('chat')
  }

  /**
   * Reverse of jumpToChat: from a chat citation chip, jump back
   * to Research and light up the evidence rows for `symbol`.
   * Nonce bumps every call so clicking the same cite twice still
   * re-triggers the highlight animation.
   */
  function jumpToResearch(focus: { symbol?: string }) {
    setDigestFocus({ symbol: focus.symbol, nonce: Date.now() })
    setTab('research')
  }

  return (
    <div className="h-full flex flex-col">
      {/* Top nav */}
      <header className="flex items-center gap-4 px-4 py-2 bg-[var(--color-panel)] border-b border-[var(--color-border)] shrink-0">
        <div className="flex items-center gap-2 text-[var(--color-text)]">
          <Sparkles size={15} className="text-[var(--color-accent)]" />
          <span className="font-semibold">neomind / fin</span>
        </div>
        <nav className="flex items-center gap-1" data-testid="top-nav">
          {TABS.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              data-testid={`tab-${id}`}
              onClick={() => setTab(id)}
              className={cn(
                'flex items-center gap-1.5 px-3 py-1 rounded text-xs transition',
                tab === id
                  ? 'bg-[var(--color-border)] text-[var(--color-accent)]'
                  : 'text-[var(--color-dim)] hover:text-[var(--color-text)] hover:bg-[var(--color-border)]/50',
              )}
            >
              <Icon size={12} />
              {label}
            </button>
          ))}
        </nav>
        <div className="flex-1" />
        <button
          data-testid="palette-open"
          onClick={() => setPaletteOpen(true)}
          className="flex items-center gap-1.5 text-[10px] text-[var(--color-dim)] hover:text-[var(--color-text)] border border-[var(--color-border)] rounded px-2 py-1 transition"
          title="Command palette — ⌘K / Ctrl+K"
        >
          <Command size={10} />
          <span>K</span>
        </button>
        <div className="flex items-center gap-3 text-[10px] text-[var(--color-dim)]">
          <span>Project: <code className="text-[var(--color-accent)]">{projectId}</code></span>
          <span className={health.data ? 'text-[var(--color-green)]' : 'text-[var(--color-red)]'}>
            ● {health.data ? `healthy · ${health.data.version}` : 'unreachable'}
          </span>
        </div>
      </header>

      <CommandPalette
        open={paletteOpen}
        onClose={() => setPaletteOpen(false)}
        onPick={(cmd) => {
          // Route to chat tab with the command queued as pending prompt.
          // ChatPanel's useEffect populates input, user hits enter to send.
          setPendingChatPrompt(cmd)
          setPendingChatContext(null)   // workflow commands inject context server-side
          setTab('chat')
        }}
      />

      {/* Active tab */}
      <main className="flex-1 overflow-hidden">
        {tab === 'research' && (
          <ResearchTab
            projectId={projectId}
            onJumpToChat={jumpToChat}
            digestFocus={digestFocus}
          />
        )}
        {tab === 'chat'     && (
          <ChatTab
            projectId={projectId}
            onJumpToAudit={jumpToAudit}
            onNavigateToResearch={jumpToResearch}
            pendingPrompt={pendingChatPrompt}
            pendingContext={pendingChatContext}
            onConsumePendingPrompt={() => {
              setPendingChatPrompt(null)
              setPendingChatContext(null)
            }}
          />
        )}
        {tab === 'paper'    && <PaperTab projectId={projectId} />}
        {tab === 'audit'    && (
          <AuditTab
            initialReqFilter={auditReqFilter}
            onConsumeFilter={() => setAuditReqFilter(null)}
          />
        )}
        {tab === 'settings' && <SettingsTab projectId={projectId} onProjectChange={switchProject} />}
      </main>
    </div>
  )
}
