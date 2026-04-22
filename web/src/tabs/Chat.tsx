import { ChatPanel } from '@/components/chat/ChatPanel'

interface Props {
  projectId: string
  onJumpToAudit?: (reqId: string) => void
  /** Reverse of onJumpToChat — fired when a citation chip in an
   *  assistant reply is clicked. Routes the user to the Research
   *  tab with the DigestView focused on the cited symbol. */
  onNavigateToResearch?: (focus: { symbol?: string }) => void
  /** A prompt queued by another tab (e.g. watchlist "ask agent"
   *  button). Pre-fills the input when ChatPanel mounts. */
  pendingPrompt?: string | null
  /** Optional synthesis context to attach to the next send. */
  pendingContext?: { symbol?: string; project?: boolean } | null
  onConsumePendingPrompt?: () => void
}

export function ChatTab({
  projectId,
  onJumpToAudit,
  onNavigateToResearch,
  pendingPrompt,
  pendingContext,
  onConsumePendingPrompt,
}: Props) {
  return (
    <div className="h-full">
      <ChatPanel
        projectId={projectId}
        onJumpToAudit={onJumpToAudit}
        onNavigateToResearch={onNavigateToResearch}
        pendingPrompt={pendingPrompt}
        pendingContext={pendingContext}
        onConsumePendingPrompt={onConsumePendingPrompt}
      />
    </div>
  )
}
