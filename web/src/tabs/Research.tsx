import { useState } from 'react'
import { DigestView, type DigestFocus } from '@/components/widgets/DigestView'
import { ResearchConfigDrawer } from '@/components/widgets/ResearchConfigDrawer'

interface Props {
  projectId: string
  onJumpToChat?: (prompt: string, ctx?: { symbol?: string; project?: boolean }) => void
  digestFocus?: DigestFocus | null
}

// V11: Research is now lattice-focused. The widget grid (Watchlist,
// Quote, Heatmap, Earnings, RS, Correlation, Sectors, etc.) has
// been moved to LegacyTab — accessible from Settings → "Open legacy
// dashboard". Rationale: NeoMind's USP is information distillation
// (the lattice graph + Toulmin calls). The competing dashboard view
// duplicated public products (TradingView/Yahoo/Koyfin) without
// adding value, and split user attention.
//
// V11.1: gear button (passed into DigestView's header so it sits in
// the natural toolbar row, not absolutely-positioned overlapping
// past/check/budgets/lang) opens a drawer for editing watchlist +
// portfolio (the inputs that feed L0).
export function ResearchTab({ projectId, onJumpToChat, digestFocus }: Props) {
  const [configOpen, setConfigOpen] = useState(false)

  return (
    <div
      data-testid="research-scroll"
      className="h-full overflow-y-auto overflow-x-hidden p-3"
    >
      <DigestView
        projectId={projectId}
        onJumpToChat={onJumpToChat}
        focus={digestFocus}
        onOpenConfig={() => setConfigOpen(true)}
      />

      <ResearchConfigDrawer
        open={configOpen}
        onClose={() => setConfigOpen(false)}
        projectId={projectId}
        onJumpToChat={onJumpToChat}
      />
    </div>
  )
}
