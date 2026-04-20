import { ChatPanel } from '@/components/chat/ChatPanel'

interface Props { projectId: string }

export function ChatTab({ projectId }: Props) {
  return (
    <div className="h-full max-w-4xl mx-auto">
      <ChatPanel projectId={projectId} />
    </div>
  )
}
