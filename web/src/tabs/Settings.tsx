import {
  useHealth, useProjects,
  useUserPrefs, saveUserPrefs, type UserPrefs,
  useUserWatchlist, saveWatchlistBulk,
} from '@/lib/api'
import { Card, CardHeader, CardBody } from '@/components/ui/Card'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, useEffect } from 'react'
import { ArchitectureView } from '@/components/architecture/ArchitectureView'

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
    <div className="flex-1 overflow-y-auto">
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

      <WatchlistCard />

      <UserPrefsCard />

      <Card>
        <CardHeader title="About" />
        <CardBody>
          <div className="text-xs text-[var(--color-dim)]">
            NeoMind Fin dashboard · React 19 + Vite 6 + TanStack Query · 100% local, no SaaS.
          </div>
        </CardBody>
      </Card>
      </div>

      {/* Architecture explorer breaks out of max-w-3xl since the
          force-graph wants horizontal room. Replaces the old
          plans/architecture_interactive.html standalone file. */}
      <div className="px-4 pb-4 max-w-7xl mx-auto">
        <Card>
          <CardHeader
            title="Codebase architecture"
            subtitle="AST-parsed module dependency graph"
          />
          <CardBody>
            <ArchitectureView />
          </CardBody>
        </Card>
      </div>
    </div>
  )
}


// ── Phase L: watchlist editor ──────────────────────────────────────


function WatchlistCard() {
  const q  = useUserWatchlist()
  const qc = useQueryClient()
  const [draft, setDraft] = useState<string>('')
  const [saving, setSaving] = useState(false)
  const [savedMsg, setSavedMsg] = useState<string>('')

  useEffect(() => {
    if (q.data?.user_watchlist) {
      const tickers = q.data.user_watchlist.map(w => w.ticker).join(', ')
      setDraft(tickers)
    }
  }, [q.data])

  const onSave = async () => {
    setSaving(true)
    try {
      const list = draft
        .replace(/[,\n]/g, ' ')
        .split(/\s+/)
        .filter(Boolean)
      const result = await saveWatchlistBulk(list)
      setSavedMsg(`✓ +${result.added.length} −${result.removed.length} = ${result.current.length}`)
      await qc.invalidateQueries({ queryKey: ['watchlist'] })
      setTimeout(() => setSavedMsg(''), 2500)
    } finally {
      setSaving(false)
    }
  }

  if (q.isLoading) return null

  return (
    <Card>
      <CardHeader title="📋 Watchlist — your individual stocks" />
      <CardBody>
        <div className="text-xs text-[var(--color-dim)] mb-2 leading-[1.5]">
          NeoMind 后台每小时扫描这些 ticker + 自动展开的科技上下游 = 你不用盯着看。
          只在 ≥2 个独立信号源（价格 / 13F / 国会 / 新闻 / earnings）汇合时打扰你。
          <br />
          <span className="text-[10px]">
            输入格式: ticker 用逗号或空格分隔 (e.g.{' '}
            <span className="font-mono">AAPL, NVDA TSLA, META</span>)
          </span>
        </div>

        <textarea
          data-testid="watchlist-input"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="AAPL, TSLA, META, MSFT, NVDA, AMD, ARM, GOOGL, APP"
          className="w-full bg-[var(--color-panel)] border border-[var(--color-border)] rounded px-2 py-1.5 text-xs font-mono"
          rows={3}
        />

        <div className="flex items-center gap-3 mt-2">
          <button
            data-testid="watchlist-save"
            onClick={onSave}
            disabled={saving}
            className="px-3 py-1 rounded bg-[var(--color-accent)]/15 border border-[var(--color-accent)]/60 text-[var(--color-accent)] text-xs hover:bg-[var(--color-accent)]/25"
          >
            {saving ? '保存中…' : '保存 / Save'}
          </button>
          {savedMsg && (
            <span className="text-[10px] text-[var(--color-green)]">{savedMsg}</span>
          )}
          <span className="ml-auto text-[10px] text-[var(--color-dim)] font-mono">
            user: {q.data?.user_watchlist.length ?? 0} · supply chain: {q.data?.supply_chain.length ?? 0}
          </span>
        </div>

        {q.data?.user_watchlist?.length ? (
          <div className="mt-3 text-[10px] space-y-0.5">
            <div className="uppercase tracking-wider text-[8.5px] text-[var(--color-dim)] mb-1">
              当前 watchlist + 自动展开:
            </div>
            <div className="font-mono text-[10px] text-[var(--color-text)] flex flex-wrap gap-1">
              {q.data.user_watchlist.map((w) => (
                <span
                  key={w.ticker}
                  className="px-1.5 py-0.5 rounded bg-[var(--color-accent)]/15 border border-[var(--color-accent)]/40 text-[var(--color-accent)]"
                  title="manual"
                >
                  {w.ticker}
                </span>
              ))}
              {q.data.supply_chain.map((t) => (
                <span
                  key={t}
                  className="px-1.5 py-0.5 rounded bg-[var(--color-panel)]/60 border border-[var(--color-border)] text-[var(--color-dim)]"
                  title="auto-expanded supply chain"
                >
                  {t}
                </span>
              ))}
            </div>
            <div className="mt-1 text-[8.5px] italic text-[var(--color-dim)] leading-[1.4]">
              <span className="text-[var(--color-accent)]">绿色 = 你手动加的</span>;
              {' '}<span>灰色 = 自动展开的科技上下游</span> (在
              <span className="font-mono"> agent/finance/regime/signals.py:SUPPLY_CHAIN_MAP</span> 维护)
            </div>
          </div>
        ) : null}
      </CardBody>
    </Card>
  )
}


// ── #92: 4-question user prefs onboarding ──────────────────────────


function UserPrefsCard() {
  const q = useUserPrefs()
  const qc = useQueryClient()
  const [draft, setDraft] = useState<Partial<UserPrefs>>({})
  const [saved, setSaved] = useState<boolean>(false)

  useEffect(() => {
    if (q.data) {
      setDraft({
        options_level:                q.data.options_level,
        max_drawdown_tolerance:       q.data.max_drawdown_tolerance,
        income_vs_growth:             q.data.income_vs_growth,
        max_position_concentration:   q.data.max_position_concentration,
      })
    }
  }, [q.data])

  const onSave = async () => {
    await saveUserPrefs(draft)
    setSaved(true)
    setTimeout(() => setSaved(false), 1500)
    await qc.invalidateQueries({ queryKey: ['user_prefs'] })
    await qc.invalidateQueries({ queryKey: ['portfolio_selection'] })
  }

  if (q.isLoading) return null
  const status = q.data?._source === 'saved' ? '已保存 / saved' : '使用默认值 / using defaults'

  return (
    <Card>
      <CardHeader title="🧭 投资偏好 / Your investment style (4 questions)" />
      <CardBody>
        <div className="text-xs text-[var(--color-dim)] mb-3">
          这些设置直接影响 Strategies tab 的推荐排序（scorer 的 utility weights 会读取它们）。
          {' '}<span className="text-[var(--color-text)]">{status}</span>
        </div>

        <div className="grid gap-3" data-testid="user-prefs-form">
          <div>
            <label className="text-xs text-[var(--color-text)] block mb-1">
              1. 期权熟练度 / Options level
            </label>
            <div className="flex gap-1.5">
              {[
                { v: 0, label: '不会 / None' },
                { v: 1, label: '只买入或备兑 / Covered' },
                { v: 2, label: '价差 / Spreads' },
                { v: 3, label: '裸卖 / Naked' },
              ].map(opt => (
                <button
                  key={opt.v}
                  data-testid={`prefs-options-level-${opt.v}`}
                  onClick={() => setDraft({ ...draft, options_level: opt.v })}
                  className={
                    'px-2 py-1 rounded border text-[10px] transition ' +
                    ((draft.options_level ?? 0) === opt.v
                      ? 'border-[var(--color-accent)] bg-[var(--color-accent)]/15 text-[var(--color-accent)]'
                      : 'border-[var(--color-border)] hover:border-[var(--color-accent)]/40')
                  }
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>

          <div>
            <label className="text-xs text-[var(--color-text)] block mb-1">
              2. 可承受的最大回撤 / Max drawdown tolerance
              {' '}<span className="text-[var(--color-dim)] text-[10px]">
                ({((draft.max_drawdown_tolerance ?? 0.15) * 100).toFixed(0)}%)
              </span>
            </label>
            <input
              type="range"
              data-testid="prefs-max-drawdown"
              min={0.05} max={0.50} step={0.01}
              value={draft.max_drawdown_tolerance ?? 0.15}
              onChange={(e) => setDraft({ ...draft, max_drawdown_tolerance: parseFloat(e.target.value) })}
              className="w-full"
            />
          </div>

          <div>
            <label className="text-xs text-[var(--color-text)] block mb-1">
              3. 现金流 vs 资本增长 / Income vs growth
              {' '}<span className="text-[var(--color-dim)] text-[10px]">
                ({(draft.income_vs_growth ?? 0.5) < 0.4 ? '偏增长 growth' :
                  (draft.income_vs_growth ?? 0.5) > 0.6 ? '偏现金流 income' : '平衡 balanced'})
              </span>
            </label>
            <input
              type="range"
              data-testid="prefs-income-growth"
              min={0} max={1} step={0.05}
              value={draft.income_vs_growth ?? 0.5}
              onChange={(e) => setDraft({ ...draft, income_vs_growth: parseFloat(e.target.value) })}
              className="w-full"
            />
          </div>

          <div>
            <label className="text-xs text-[var(--color-text)] block mb-1">
              4. 单一仓位最大占比 / Max position concentration
              {' '}<span className="text-[var(--color-dim)] text-[10px]">
                ({((draft.max_position_concentration ?? 0.25) * 100).toFixed(0)}%)
              </span>
            </label>
            <input
              type="range"
              data-testid="prefs-max-concentration"
              min={0.05} max={0.80} step={0.01}
              value={draft.max_position_concentration ?? 0.25}
              onChange={(e) => setDraft({ ...draft, max_position_concentration: parseFloat(e.target.value) })}
              className="w-full"
            />
          </div>

          <div className="flex items-center gap-3 mt-1">
            <button
              data-testid="prefs-save"
              onClick={onSave}
              className="px-3 py-1.5 rounded bg-[var(--color-accent)]/15 border border-[var(--color-accent)]/60 text-[var(--color-accent)] text-xs hover:bg-[var(--color-accent)]/25 transition"
            >
              {saved ? '✓ 已保存' : '保存 / Save'}
            </button>
            <span className="text-[10px] text-[var(--color-dim)] font-mono truncate">
              → {q.data?._path ?? '~/.neomind/fin/user_prefs.json'}
            </span>
          </div>
        </div>
      </CardBody>
    </Card>
  )
}
