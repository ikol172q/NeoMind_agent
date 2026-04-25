import { useHealth, useProjects } from '@/lib/api'
import { Card, CardHeader, CardBody } from '@/components/ui/Card'
import { useQuery } from '@tanstack/react-query'

interface Props {
  projectId: string
  onProjectChange: (p: string) => void
  onOpenLegacy?: () => void
}

export function SettingsTab({ projectId, onProjectChange, onOpenLegacy }: Props) {
  const health = useHealth()
  const projects = useProjects()
  const newsHealth = useQuery({
    queryKey: ['news_health'],
    queryFn: async () => (await fetch('/api/news/health')).json() as Promise<{ ok: boolean; reason?: string }>,
  })

  return (
    <div className="p-4 grid gap-3 max-w-3xl mx-auto">
      <Card>
        <CardHeader title="Project" />
        <CardBody>
          <div className="text-xs text-[var(--color-dim)] mb-2">
            Switch active investment project. Audit + paper trading + chat all scope to this project.
          </div>
          <select
            value={projectId}
            onChange={e => onProjectChange(e.target.value)}
            className="bg-[#0e1219] border border-[var(--color-border)] rounded px-2 py-1.5 text-xs"
          >
            {(projects.data?.projects ?? [projectId]).map(p => (
              <option key={p} value={p}>{p}</option>
            ))}
          </select>
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Backend health" />
        <CardBody>
          <div className="grid grid-cols-2 gap-y-1.5 gap-x-3 text-xs">
            <div className="text-[var(--color-dim)]">Dashboard</div>
            <div>{health.data ? `✓ ${health.data.version}` : '✗ unreachable'}</div>
            <div className="text-[var(--color-dim)]">Investment root</div>
            <div className="truncate">{health.data?.investment_root ?? '—'}</div>
            <div className="text-[var(--color-dim)]">Miniflux (news)</div>
            <div>
              {newsHealth.data?.ok
                ? '✓ connected'
                : <span className="text-[var(--color-dim)]">{newsHealth.data?.reason ?? '✗ not configured'}</span>}
            </div>
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Data storage" subtitle="All files are local" />
        <CardBody>
          <div className="grid grid-cols-[auto_1fr] gap-y-1.5 gap-x-3 text-[11px]">
            <code className="text-[var(--color-dim)]">~/Desktop/Investment/</code>
            <div>Project trades / analyses / journals</div>
            <code className="text-[var(--color-dim)]">~/Desktop/Investment/_audit/</code>
            <div>LLM call audit (append-only JSONL per day)</div>
            <code className="text-[var(--color-dim)]">~/.neomind/</code>
            <div>Fleet state (mailboxes, transcripts)</div>
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Legacy dashboard" subtitle="Old widget grid (Quote / Heatmap / Earnings / RS / Correlation / etc.)" />
        <CardBody>
          <div className="text-xs text-[var(--color-dim)] mb-2">
            The dashboard widget grid was removed from Research in V11 to keep the
            lattice (information distillation) as the single focus. The full grid
            is preserved here — your saved layout still applies.
            <br /><br />
            For market data exploration, prefer external products (TradingView, Yahoo
            Finance, Koyfin, Finviz). The legacy grid is kept as a safety net /
            reference.
          </div>
          <button
            data-testid="open-legacy-dashboard"
            onClick={() => onOpenLegacy?.()}
            className="text-xs px-3 py-1.5 rounded border border-[var(--color-border)] hover:bg-[var(--color-border)]/40 transition"
          >
            Open legacy dashboard →
          </button>
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="About" />
        <CardBody>
          <div className="text-xs text-[var(--color-dim)]">
            NeoMind Fin dashboard · React 19 + Vite 6 + TanStack Query · 100% local, no SaaS.
          </div>
        </CardBody>
      </Card>
    </div>
  )
}
