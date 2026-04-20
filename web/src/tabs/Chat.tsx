import { ChatPanel } from '@/components/chat/ChatPanel'

interface Props {
  projectId: string
  onJumpToAudit?: (reqId: string) => void
}

export function ChatTab({ projectId, onJumpToAudit }: Props) {
  return (
    <div className="h-full">
      <ChatPanel projectId={projectId} onJumpToAudit={onJumpToAudit} />
    </div>
  )
}
