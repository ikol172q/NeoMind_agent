import { useState } from 'react'
import { cn } from '@/lib/utils'
import { useHealth } from '@/lib/api'
import { ResearchTab } from '@/tabs/Research'
import { ChatTab } from '@/tabs/Chat'
import { PaperTab } from '@/tabs/Paper'
import { AuditTab } from '@/tabs/Audit'
import { SettingsTab } from '@/tabs/Settings'
import { Sparkles, LineChart, MessagesSquare, Wallet, ClipboardList, Settings as SettingsIcon } from 'lucide-react'

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
  const health = useHealth()

  function switchProject(p: string) {
    setProjectId(p)
    try { localStorage.setItem('neomind.project', p) } catch {}
  }

  function jumpToAudit(reqId: string) {
    setAuditReqFilter(reqId)
    setTab('audit')
  }

  function jumpToChat(prompt: string) {
    setPendingChatPrompt(prompt)
    setTab('chat')
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
        <div className="flex items-center gap-3 text-[10px] text-[var(--color-dim)]">
          <span>Project: <code className="text-[var(--color-accent)]">{projectId}</code></span>
          <span className={health.data ? 'text-[var(--color-green)]' : 'text-[var(--color-red)]'}>
            ● {health.data ? `healthy · ${health.data.version}` : 'unreachable'}
          </span>
        </div>
      </header>

      {/* Active tab */}
      <main className="flex-1 overflow-hidden">
        {tab === 'research' && <ResearchTab projectId={projectId} onJumpToChat={jumpToChat} />}
        {tab === 'chat'     && (
          <ChatTab
            projectId={projectId}
            onJumpToAudit={jumpToAudit}
            pendingPrompt={pendingChatPrompt}
            onConsumePendingPrompt={() => setPendingChatPrompt(null)}
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
