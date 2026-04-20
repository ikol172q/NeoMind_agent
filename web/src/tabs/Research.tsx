import { Responsive, WidthProvider, type Layout } from 'react-grid-layout'
import 'react-grid-layout/css/styles.css'
import 'react-resizable/css/styles.css'
import { USQuoteCard } from '@/components/widgets/USQuoteCard'
import { CNQuoteCard } from '@/components/widgets/CNQuoteCard'
import { CNInfoCard } from '@/components/widgets/CNInfoCard'
import { NewsList } from '@/components/widgets/NewsList'
import { HistoryTable } from '@/components/widgets/HistoryTable'
import { ChartWidget } from '@/components/widgets/ChartWidget'
import { WatchlistWidget } from '@/components/widgets/WatchlistWidget'
import { SectorHeatmapWidget } from '@/components/widgets/SectorHeatmapWidget'
import { RSGridWidget } from '@/components/widgets/RSGridWidget'
import { EarningsWidget } from '@/components/widgets/EarningsWidget'
import { PortfolioHeatmapWidget } from '@/components/widgets/PortfolioHeatmapWidget'
import { MultiChartWidget } from '@/components/widgets/MultiChartWidget'
import { FundExplorerWidget } from '@/components/widgets/FundExplorerWidget'

const ResponsiveGridLayout = WidthProvider(Responsive)

// v9 adds the fund/ETF explorer (Tier-2 #7). Lives in the detail
// band under the charts so you can drill from a symbol chart into
// fund-level profile + holdings.
const LS_KEY = 'neomind.research.layout.v9'

const DEFAULT_LAYOUT: Layout[] = [
  // Hero row — visible on first paint
  { i: 'watchlist', x: 0,  y: 0,  w: 5,  h: 12 },
  { i: 'news',      x: 5,  y: 0,  w: 4,  h: 12 },
  { i: 'us_quote',  x: 9,  y: 0,  w: 3,  h: 6 },
  { i: 'cn_quote',  x: 9,  y: 6,  w: 3,  h: 6 },
  // Analytics band
  { i: 'portfolio', x: 0,  y: 12, w: 6,  h: 9 },
  { i: 'earnings',  x: 6,  y: 12, w: 6,  h: 9 },
  { i: 'rs_grid',   x: 0,  y: 21, w: 6,  h: 9 },
  { i: 'sectors',   x: 6,  y: 21, w: 6,  h: 9 },
  // Detail band — single-symbol candles + multi-symbol overlay
  { i: 'chart',      x: 0,  y: 30, w: 6, h: 10 },
  { i: 'multi_chart',x: 6,  y: 30, w: 6, h: 10 },
  { i: 'fund',       x: 0,  y: 40, w: 6, h: 12 },
  { i: 'cn_info',    x: 6,  y: 40, w: 6, h: 12 },
  // Reference
  { i: 'history',   x: 0,  y: 52, w: 12, h: 8 },
]

function loadLayout(): Layout[] {
  try {
    const raw = localStorage.getItem(LS_KEY)
    if (raw) return JSON.parse(raw) as Layout[]
  } catch {}
  return DEFAULT_LAYOUT
}

interface Props {
  projectId: string
  onJumpToChat?: (prompt: string) => void
}

export function ResearchTab({ projectId, onJumpToChat }: Props) {
  const layout = loadLayout()

  return (
    // Own scroll container — App's <main> is overflow-hidden (Chat/
    // Audit/Paper fill-to-viewport tabs need that), but Research's
    // grid expands vertically past the fold. Without this wrapper
    // the user would be stuck on the hero row forever.
    <div
      data-testid="research-scroll"
      className="h-full overflow-y-auto overflow-x-hidden"
    >
      <ResponsiveGridLayout
      className="layout"
      layouts={{ lg: layout, md: layout, sm: layout, xs: layout }}
      breakpoints={{ lg: 1200, md: 996, sm: 768, xs: 0 }}
      cols={{ lg: 12, md: 12, sm: 8, xs: 4 }}
      rowHeight={32}
      draggableHandle=".cursor-move, .drag-handle"
      // Inputs / buttons / selects inside a widget must not trigger a
      // grid-drag on mousedown — otherwise clicking "Add" on the
      // watchlist (and every other button inside a widget) gets
      // swallowed before the onClick handler can fire. Matches the
      // pattern react-grid-layout recommends for interactive cards.
      draggableCancel="input, select, textarea, button, a, [contenteditable='true']"
      margin={[10, 10]}
      onLayoutChange={(l) => {
        try { localStorage.setItem(LS_KEY, JSON.stringify(l)) } catch {}
      }}
    >
      <div key="watchlist"><div className="drag-handle h-full cursor-move"><WatchlistWidget projectId={projectId} onJumpToChat={onJumpToChat} /></div></div>
      <div key="us_quote"><div className="drag-handle h-full cursor-move"><USQuoteCard /></div></div>
      <div key="cn_quote"><div className="drag-handle h-full cursor-move"><CNQuoteCard /></div></div>
      <div key="cn_info"><div className="drag-handle h-full cursor-move"><CNInfoCard /></div></div>
      <div key="portfolio"><div className="drag-handle h-full cursor-move"><PortfolioHeatmapWidget projectId={projectId} onJumpToChat={onJumpToChat} /></div></div>
      <div key="earnings"><div className="drag-handle h-full cursor-move"><EarningsWidget projectId={projectId} onJumpToChat={onJumpToChat} /></div></div>
      <div key="sectors"><div className="drag-handle h-full cursor-move"><SectorHeatmapWidget onJumpToChat={onJumpToChat} /></div></div>
      <div key="rs_grid"><div className="drag-handle h-full cursor-move"><RSGridWidget onJumpToChat={onJumpToChat} /></div></div>
      <div key="chart"><div className="drag-handle h-full cursor-move"><ChartWidget /></div></div>
      <div key="multi_chart"><div className="drag-handle h-full cursor-move"><MultiChartWidget onJumpToChat={onJumpToChat} /></div></div>
      <div key="fund"><div className="drag-handle h-full cursor-move"><FundExplorerWidget onJumpToChat={onJumpToChat} /></div></div>
      <div key="news"><div className="drag-handle h-full cursor-move"><NewsList /></div></div>
      <div key="history"><div className="drag-handle h-full cursor-move"><HistoryTable projectId={projectId} /></div></div>
      </ResponsiveGridLayout>
    </div>
  )
}
