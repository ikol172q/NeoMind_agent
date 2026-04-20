import { ChatPanel } from '@/components/chat/ChatPanel'

interface Props {
  projectId: string
  onJumpToAudit?: (reqId: string) => void
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
  pendingPrompt,
  pendingContext,
  onConsumePendingPrompt,
}: Props) {
  return (
    <div className="h-full">
      <ChatPanel
        projectId={projectId}
        onJumpToAudit={onJumpToAudit}
        pendingPrompt={pendingPrompt}
        pendingContext={pendingContext}
        onConsumePendingPrompt={onConsumePendingPrompt}
      />
    </div>
  )
}
