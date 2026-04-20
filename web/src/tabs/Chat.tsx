import { ChatPanel } from '@/components/chat/ChatPanel'

interface Props {
  projectId: string
  onJumpToAudit?: (reqId: string) => void
  /** A prompt queued by another tab (e.g. watchlist "ask agent"
   *  button). Pre-fills the input when ChatPanel mounts. */
  pendingPrompt?: string | null
  onConsumePendingPrompt?: () => void
}

export function ChatTab({
  projectId,
  onJumpToAudit,
  pendingPrompt,
  onConsumePendingPrompt,
}: Props) {
  return (
    <div className="h-full">
      <ChatPanel
        projectId={projectId}
        onJumpToAudit={onJumpToAudit}
        pendingPrompt={pendingPrompt}
        onConsumePendingPrompt={onConsumePendingPrompt}
      />
    </div>
  )
}
