/**
 * API client + TanStack Query hooks for the NeoMind backend.
 *
 * All calls go to same-origin (`/api/*`, `/openbb/*`, `/audit`)
 * so in dev they're proxied to 127.0.0.1:8001 via Vite, and in
 * prod they hit the same FastAPI that serves this bundle.
 */
import { useQuery, useMutation, useQueryClient, keepPreviousData } from '@tanstack/react-query'

export async function fetchJSON<T = unknown>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, init)
  if (!r.ok) {
    const body = await r.text().catch(() => '')
    throw new Error(`HTTP ${r.status} ${url}: ${body.slice(0, 200)}`)
  }
  return r.json() as Promise<T>
}

// ── Health ────────────────────────────────────────────────
export function useHealth() {
  return useQuery({
    queryKey: ['health'],
    queryFn: () => fetchJSON<{ status: string; version: string; investment_root: string }>('/api/health'),
    refetchInterval: 15000,
  })
}

// ── Projects ──────────────────────────────────────────────
export function useProjects() {
  return useQuery({
    queryKey: ['projects'],
    queryFn: () => fetchJSON<{ projects: string[] }>('/api/projects'),
    staleTime: 30000,
  })
}

// ── Quote ────────────────────────────────────────────────
export interface Quote {
  symbol: string
  price: number | null
  change: number | null
  change_pct: number | null
  volume: number | null
  high: number | null
  low: number | null
  open: number | null
  prev_close: number | null
  name?: string
  market?: string
  currency?: string
  market_status?: string
  source?: string
}

export function useQuote(symbol: string | null) {
  return useQuery({
    queryKey: ['quote', symbol],
    queryFn: () => fetchJSON<Quote>(`/api/quote/${encodeURIComponent(symbol!)}`),
    enabled: !!symbol,
    refetchInterval: 30000,
  })
}

// ── CN Quote / Chart / Info ────────────────────────────
export interface CNQuote {
  symbol: string
  price: number
  change: number | null
  change_pct: number | null
  volume: number | null
  turnover: number | null
  high: number | null
  low: number | null
  open: number | null
  prev_close: number | null
  limit_up: number | null
  limit_down: number | null
  turnover_rate_pct: number | null
}

export function useCNQuote(code: string | null) {
  return useQuery({
    queryKey: ['cn_quote', code],
    queryFn: () => fetchJSON<CNQuote>(`/api/cn/quote/${encodeURIComponent(code!)}`),
    enabled: !!code && /^\d{6}$/.test(code),
    refetchInterval: 30000,
  })
}

export interface CNInfo {
  symbol: string
  name: string
  industry: string | null
  listed_date: string | null
  total_shares: number | null
  float_shares: number | null
  market_cap: number | null
  float_market_cap: number | null
  last_price: number | null
}

export function useCNInfo(code: string | null) {
  return useQuery({
    queryKey: ['cn_info', code],
    queryFn: () => fetchJSON<CNInfo>(`/api/cn/info/${encodeURIComponent(code!)}`),
    enabled: !!code && /^\d{6}$/.test(code),
    staleTime: 3600_000,
  })
}

export interface Bar { date: string; open: number; high: number; low: number; close: number; volume: number }
export interface History { symbol: string; market: string; currency: string; bars: Bar[] }

export function useCNHistory(code: string | null, days = 90) {
  return useQuery({
    queryKey: ['cn_history', code, days],
    queryFn: () => fetchJSON<History>(`/api/cn/history/${encodeURIComponent(code!)}?days=${days}`),
    enabled: !!code && /^\d{6}$/.test(code),
    staleTime: 60_000,
  })
}

// ── News ─────────────────────────────────────────────────
export interface NewsEntry {
  id: number
  title: string
  url: string
  published_at: string
  feed_title: string
  snippet: string
}

export function useNews(params: { symbols?: string; limit?: number; categoryId?: number | null } = {}) {
  const qs = new URLSearchParams()
  if (params.symbols) qs.set('symbols', params.symbols)
  if (params.categoryId != null) qs.set('category_id', String(params.categoryId))
  qs.set('limit', String(params.limit ?? 20))
  return useQuery({
    queryKey: ['news', params.symbols ?? '', params.limit ?? 20, params.categoryId ?? 'all'],
    queryFn: () => fetchJSON<{ count: number; entries: NewsEntry[] }>(`/api/news?${qs}`),
    refetchInterval: 120_000,
  })
}

export interface NewsCategory {
  id: number
  title: string
  feed_count: number
}

export function useNewsCategories() {
  return useQuery({
    queryKey: ['news_categories'],
    queryFn: () => fetchJSON<{ categories: NewsCategory[] }>('/api/news/categories'),
    staleTime: 300_000,
  })
}

// ── Analysis history ────────────────────────────────────
export interface AnalysisItem {
  written_at: string
  symbol: string
  signal?: {
    signal?: string
    confidence?: number
    reason?: string
    risk_level?: string
    target_price?: number | null
  }
}

export function useHistory(projectId: string, limit = 20) {
  return useQuery({
    queryKey: ['history', projectId, limit],
    queryFn: () => fetchJSON<{ project_id: string; count: number; items: AnalysisItem[] }>(
      `/api/history?project_id=${projectId}&limit=${limit}`,
    ),
    enabled: !!projectId,
    staleTime: 30_000,
  })
}

// ── Paper trading ────────────────────────────────────────
export function usePaperAccount(projectId: string) {
  return useQuery({
    queryKey: ['paper', 'account', projectId],
    queryFn: () => fetchJSON<Record<string, unknown>>(`/api/paper/account?project_id=${projectId}`),
    enabled: !!projectId,
    refetchInterval: 15_000,
  })
}

export function usePaperPositions(projectId: string) {
  return useQuery({
    queryKey: ['paper', 'positions', projectId],
    queryFn: () => fetchJSON<{ positions: Array<Record<string, unknown>> }>(`/api/paper/positions?project_id=${projectId}`),
    enabled: !!projectId,
    refetchInterval: 15_000,
  })
}

export function usePaperTrades(projectId: string, limit = 50) {
  return useQuery({
    queryKey: ['paper', 'trades', projectId, limit],
    queryFn: () => fetchJSON<{ trades: Array<Record<string, unknown>> }>(`/api/paper/trades?project_id=${projectId}&limit=${limit}`),
    enabled: !!projectId,
    refetchInterval: 15_000,
  })
}

export async function refreshPaperPrices(projectId: string): Promise<void> {
  await fetchJSON(`/api/paper/refresh?project_id=${encodeURIComponent(projectId)}`, { method: 'POST' })
}

// Typed position / account shapes so widgets don't have to cast
// Record<string, unknown> fields individually.
export interface PaperPosition {
  symbol: string
  quantity: number
  entry_price: number
  current_price: number
  side: 'buy' | 'sell'
  opened_at: string
  unrealized_pnl: number
  unrealized_pnl_pct: number
}

export interface PaperAccount {
  initial_capital: number
  cash: number
  equity: number
  unrealized_pnl: number
  realized_pnl: number
  total_pnl: number
  total_pnl_pct: number
  total_trades: number
  winning_trades: number
  losing_trades: number
  win_rate: number
  positions: number
  open_orders: number
  project_id: string
}

export function usePaperOrder() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (args: {
      project_id: string
      symbol: string
      side: 'buy' | 'sell'
      quantity: number
      order_type: 'market' | 'limit' | 'stop'
      price?: number
      stop_price?: number
    }) => {
      const qs = new URLSearchParams()
      for (const [k, v] of Object.entries(args)) {
        if (v !== undefined && v !== null) qs.set(k, String(v))
      }
      return fetchJSON<{ order: Record<string, unknown> }>(
        `/api/paper/order?${qs}`, { method: 'POST' },
      )
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['paper'] })
    },
  })
}

// ── Audit ────────────────────────────────────────────────
export interface AuditEntry {
  req_id: string
  task_id: string | null
  project_id: string | null
  ts: string
  agent_id: string | null
  endpoint: string | null
  kind: 'request' | 'response' | 'error'
  payload: Record<string, unknown>
}

export function useAuditRecent(params: { limit?: number; kind?: string; days?: number } = {}) {
  const qs = new URLSearchParams()
  qs.set('limit', String(params.limit ?? 50))
  qs.set('days', String(params.days ?? 1))
  if (params.kind) qs.set('kind', params.kind)
  return useQuery({
    queryKey: ['audit', 'recent', params.limit ?? 50, params.kind ?? '', params.days ?? 1],
    queryFn: () => fetchJSON<{ entries: AuditEntry[]; audit_root: string }>(`/api/audit/recent?${qs}`),
    refetchInterval: 10_000,
  })
}

export function useAuditStats(days = 1) {
  return useQuery({
    queryKey: ['audit', 'stats', days],
    queryFn: () => fetchJSON<{
      total_entries: number
      by_kind: Record<string, number>
      tokens_in: number
      tokens_out: number
    }>(`/api/audit/stats?days=${days}`),
    refetchInterval: 15_000,
  })
}

// ── Chat ─────────────────────────────────────────────────
export async function dispatchChat(project_id: string, message: string): Promise<string> {
  const qs = new URLSearchParams({ project_id, message })
  const r = await fetchJSON<{ task_id: string }>(`/api/chat?${qs}`, { method: 'POST' })
  return r.task_id
}

export async function getTask(task_id: string) {
  return fetchJSON<{ status: string; reply?: string; error?: string }>(
    `/api/tasks/${encodeURIComponent(task_id)}`,
  )
}

// ── Streaming chat ──────────────────────────────────────
export interface StreamCallbacks {
  onDelta: (chunk: string) => void
  onDone: (info: { req_id: string; duration_ms: number; total_tokens?: number; content_length: number }) => void
  onError: (err: string) => void
}

/**
 * Stream a chat message via /api/chat_stream. Token-by-token
 * updates via onDelta; final req_id via onDone (for audit linking).
 * Returns an AbortController so the caller can cancel mid-stream.
 */
export interface StreamContext {
  /** When set, server fetches /api/synthesis/symbol/{sym} and injects
   *  a DASHBOARD STATE block into the system prompt. */
  symbol?: string
  /** When true, server injects a project-wide synthesis snapshot
   *  (used by /brief + /check slash commands). */
  project?: boolean
}

export function streamChat(
  project_id: string,
  message: string,
  cb: StreamCallbacks,
  ctx?: StreamContext,
): AbortController {
  const ac = new AbortController()
  const qs = new URLSearchParams({ project_id, message })
  if (ctx?.symbol) qs.set('context_symbol', ctx.symbol)
  if (ctx?.project) qs.set('context_project', 'true')

  ;(async () => {
    try {
      const resp = await fetch(`/api/chat_stream?${qs}`, {
        method: 'POST',
        signal: ac.signal,
        headers: { Accept: 'text/event-stream' },
      })
      if (!resp.ok) {
        cb.onError(`HTTP ${resp.status}: ${await resp.text().catch(() => '')}`)
        return
      }
      if (!resp.body) {
        cb.onError('no response body')
        return
      }
      const reader = resp.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        // sse_starlette emits CRLF line endings; normalize to LF so
        // the frame splitter ("\n\n") works reliably.
        buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')
        let nl: number
        while ((nl = buffer.indexOf('\n\n')) !== -1) {
          const frame = buffer.slice(0, nl)
          buffer = buffer.slice(nl + 2)
          let data = ''
          let event = 'message'
          for (const line of frame.split('\n')) {
            if (line.startsWith('event:')) event = line.slice(6).trim()
            else if (line.startsWith('data:')) data += line.slice(5).trim()
          }
          if (!data) continue
          try {
            const payload = JSON.parse(data)
            if (event === 'delta' && typeof payload.content === 'string') {
              cb.onDelta(payload.content)
            } else if (event === 'done') {
              cb.onDone(payload)
            } else if (event === 'error') {
              cb.onError(String(payload.detail ?? 'stream error'))
            }
          } catch (_) {
            // skip non-JSON frames (heartbeats etc.)
          }
        }
      }
    } catch (e: unknown) {
      if ((e as DOMException)?.name !== 'AbortError') {
        cb.onError(e instanceof Error ? e.message : String(e))
      }
    }
  })()

  return ac
}

// ── Earnings + IV ────────────────────────────────────────
export interface EarningsEntry {
  symbol: string
  next_earnings_date: string | null
  days_until: number | null
  eps_estimate_avg: number | null
  eps_estimate_high: number | null
  eps_estimate_low: number | null
  hist_moves: Array<{ date: string; pct: number }>
  avg_abs_move_pct: number | null
  rv_30d_pct: number | null
  atm_iv_pct: number | null
  price: number | null
  error?: string
}

export function useEarnings(project_id: string) {
  return useQuery({
    queryKey: ['earnings', project_id],
    queryFn: () => fetchJSON<{ count: number; entries: EarningsEntry[] }>(
      `/api/earnings?project_id=${encodeURIComponent(project_id)}`,
    ),
    enabled: !!project_id,
    staleTime: 5 * 60_000,
    refetchInterval: 10 * 60_000,
  })
}

// ── Relative strength ───────────────────────────────────
export interface RSEntry {
  symbol: string
  price: number
  return_3m: number | null
  return_6m: number | null
  return_ytd: number | null
}

export function useRS(market: 'US' = 'US', limit = 100) {
  return useQuery({
    queryKey: ['rs', market, limit],
    queryFn: () => fetchJSON<{ market: string; count: number; entries: RSEntry[] }>(
      `/api/rs?market=${market}&limit=${limit}`,
    ),
    staleTime: 10 * 60_000,
  })
}

// ── Sectors (heatmap) ───────────────────────────────────
export interface SectorEntry {
  name: string
  symbol: string
  price: number
  change_pct: number
  size: number
  leader?: string
  leader_pct?: number
}

export function useSectors(market: 'US' | 'CN') {
  return useQuery({
    queryKey: ['sectors', market],
    queryFn: () => fetchJSON<{ market: string; count: number; sectors: SectorEntry[]; fetched_at_epoch: number }>(
      `/api/sectors?market=${market}`,
    ),
    staleTime: 45_000,
    refetchInterval: 60_000,
  })
}

// ── Portfolio attribution (Phase 6) ─────────────────────
export interface AttribPos {
  symbol: string
  sector: string
  quantity: number
  prior_close: number | null
  current_price: number
  contrib_usd: number
  contrib_pct_today: number | null
  pct_of_total: number | null
}
export interface AttribSector {
  sector: string
  contrib_usd: number
  contrib_pct_of_total: number | null
}
export function useAttribution(project_id: string) {
  return useQuery({
    queryKey: ['attribution', project_id],
    queryFn: () => fetchJSON<{
      project_id: string
      by_position: AttribPos[]
      by_sector: AttribSector[]
      total_pnl_today_usd: number
    }>(`/api/attribution?project_id=${encodeURIComponent(project_id)}`),
    enabled: !!project_id,
    staleTime: 5 * 60_000,
    refetchInterval: 10 * 60_000,
  })
}

// ── Correlation matrix (Phase 6) ────────────────────────
export interface CorrelationData {
  project_id: string
  symbols: string[]
  matrix: number[][]
  window_days: number
  note: string | null
}
export function useCorrelation(project_id: string, days: number = 90, enabled: boolean = true) {
  return useQuery({
    queryKey: ['correlation', project_id, days],
    queryFn: () => fetchJSON<CorrelationData>(
      `/api/correlation?project_id=${encodeURIComponent(project_id)}&days=${days}`,
    ),
    enabled: enabled && !!project_id,
    staleTime: 30 * 60_000,
  })
}

// ── Anomaly flags (Phase 5) ─────────────────────────────
export interface AnomalyFlag {
  kind: string
  symbol: string
  message: string
  severity: 'alert' | 'warn' | 'info'
}

export function useAnomalies(project_id: string) {
  return useQuery({
    queryKey: ['anomalies', project_id],
    queryFn: () => fetchJSON<{ project_id: string; count: number; flags: AnomalyFlag[] }>(
      `/api/anomalies?project_id=${encodeURIComponent(project_id)}`,
    ),
    enabled: !!project_id,
    staleTime: 90_000,
    refetchInterval: 2 * 60_000,
  })
}

// ── Factor grades (Phase 3: 3-tier drill) ───────────────
export interface FactorAxis {
  grade: string   // "A+" | "A" | "B" | "C" | "D" | "F" | "—"
  raw: number | null
  note: string
}

export interface FactorGrades {
  symbol: string
  overall_grade: string
  axes: {
    momentum: FactorAxis
    value: FactorAxis
    quality: FactorAxis
    growth: FactorAxis
    revisions: FactorAxis
  }
  fetched_at_epoch: number
}

export function useFactors(symbol: string | null, enabled: boolean) {
  return useQuery({
    queryKey: ['factors', symbol],
    queryFn: () => fetchJSON<FactorGrades>(`/api/factors/${encodeURIComponent(symbol!)}`),
    enabled: enabled && !!symbol,
    staleTime: 9 * 60_000,
  })
}

// ── Per-symbol insight for hover tooltips (Phase 2) ─────
export interface SymbolInsight {
  symbol: string
  text: string
  req_id: string
  fetched_at: string
  duration_ms: number
}

export function useSymbolInsight(project_id: string, symbol: string | null, enabled: boolean) {
  return useQuery({
    queryKey: ['insight', project_id, symbol],
    queryFn: () => fetchJSON<SymbolInsight>(
      `/api/insight/symbol/${encodeURIComponent(symbol!)}?project_id=${encodeURIComponent(project_id)}`,
    ),
    enabled: enabled && !!symbol && !!project_id,
    staleTime: 4 * 60_000,
    refetchOnWindowFocus: false,
  })
}

// ── Research narrative brief (Phase 1) ──────────────────
export interface ResearchBrief {
  project_id: string
  text: string
  req_id: string
  fetched_at: string
  duration_ms: number
}

export function useResearchBrief(project_id: string) {
  return useQuery({
    queryKey: ['research_brief', project_id],
    queryFn: () => fetchJSON<ResearchBrief>(
      `/api/research_brief?project_id=${encodeURIComponent(project_id)}`,
    ),
    enabled: !!project_id,
    staleTime: 4 * 60_000,      // server caches 5min; client shows fresh for 4
    refetchInterval: 5 * 60_000,
    refetchOnWindowFocus: false,
  })
}

// ── Insight Lattice (L1 → L2 → L3) ──────────────────────

export interface LatticeObservation {
  id: string
  kind: string
  text: string
  tags: string[]
  severity: 'alert' | 'warn' | 'info'
  numbers?: Record<string, number>
  source?: Record<string, unknown>
}

export interface LatticeThemeMember {
  obs_id: string
  weight: number
}

export interface LatticeTheme {
  id: string
  title: string
  narrative: string
  narrative_source: 'llm' | 'template_fallback'
  members: LatticeThemeMember[]
  tags: string[]
  severity: 'alert' | 'warn' | 'info'
  cited_numbers?: string[]
}

export interface LatticeStrategyMatch {
  strategy_id: string
  name_en: string | null
  name_zh: string | null
  horizon: string | null
  difficulty: number | null
  defined_risk: boolean | null
  pdt_relevant?: boolean | null
  score: number
  score_breakdown: Record<string, number>
}

export interface LatticeCall {
  id: string
  claim: string
  grounds: string[]           // theme_ids
  warrant: string
  qualifier: string
  rebuttal: string
  confidence: 'high' | 'medium' | 'low'
  time_horizon: 'intraday' | 'days' | 'weeks' | 'quarter'
  /** Phase 5 V3 — best-fit catalog entry from docs/strategies/strategies.yaml.
   *  Attached deterministically by agent.finance.lattice.strategy_matcher
   *  in build_calls. Null when no strategy clears the score threshold. */
  strategy_match?: LatticeStrategyMatch | null
}

export interface LatticePayload {
  project_id: string
  observations: LatticeObservation[]
  /** Optional L1.5 layer between observations and themes. Populated
   *  when `sub_themes:` is set in lattice_taxonomy.yaml (n=4 lattice).
   *  Empty array when the YAML has no sub_themes block (n=3). */
  sub_themes?: LatticeTheme[]
  themes: LatticeTheme[]
  calls: LatticeCall[]
  taxonomy_version: number
  fetched_at: string
  duration_ms: number
  /** B5/B6: provenance breadcrumb. Present on /api/lattice/calls (and
   *  themes/observations) when the response was produced through the
   *  dep_hash cache. Absent on historical snapshot reads (the snapshot
   *  envelope carries its own metadata).
   *
   *  ``dep_hash`` is the SHA-256 of every byte that fed this compute.
   *  ``compute_run_id`` is the cache row id — clickable to drill into
   *  /api/compute/runs/{id}.  ``cache_hit`` distinguishes "served from
   *  cache" vs "freshly computed".  Cross-link fields (themes_*, obs_*)
   *  let the UI render the L3 ← L2 ← L1 lineage chain. */
  run_meta?: LatticeRunMeta
}

export interface LatticeRunMeta {
  dep_hash: string
  compute_run_id: string | null
  cache_hit: boolean
  started_at: string
  completed_at: string | null
  taxonomy_version: string | null
  code_git_sha: string
  pipeline_version: string
  prompt_template_version?: string
  llm_model_id?: string
  llm_temperature?: number
  step: 'observations' | 'themes' | 'calls'
  // Lineage cross-links (present on themes & calls, not observations)
  themes_dep_hash?: string | null
  themes_compute_run_id?: string | null
  themes_cache_hit?: boolean | null
  obs_dep_hash?: string | null
  obs_compute_run_id?: string | null
  obs_cache_hit?: boolean | null
  // Inputs summary (observations-step only)
  inputs_summary?: {
    n_symbols?: number
    symbols?: string[]
    n_news_entries?: number
    n_anomalies?: number
    has_positions?: boolean
    has_watchlist?: boolean
    error?: string
  }
  // B7: validation report roll-up
  validation_state?: 'pass' | 'warn' | 'fail' | 'unknown'
  validation_summary?: {
    n_total?: number
    n_pass?: number
    n_warn?: number
    n_fail?: number
    n_unknown?: number
  }
}

export function useLatticeCalls(project_id: string, date?: string | null) {
  // Key on (language, budget_hash): backend keeps separate caches per
  // (lang, budget) combo, so RQ should too — flipping knobs back to a
  // seen combo is an in-memory hit.
  //
  // V8: when `date` is passed, fetch an archived snapshot instead of
  // live /calls. Historical snapshots are frozen artifacts (don't care
  // about current runtime overrides).
  const lang = useLatticeLanguage()
  const active = lang.data?.active
  const budgets = useLatticeBudgets()
  const bh = budgets.data?.effective_hash
  const isHistorical = !!date
  return useQuery({
    queryKey: isHistorical
      ? ['lattice_calls_snapshot', project_id, date]
      : ['lattice_calls', project_id, active, bh],
    queryFn: () => fetchJSON<LatticePayload>(
      isHistorical
        ? `/api/lattice/snapshot?project_id=${encodeURIComponent(project_id)}&date=${encodeURIComponent(date!)}`
        : `/api/lattice/calls?project_id=${encodeURIComponent(project_id)}`,
    ),
    enabled: !!project_id && (isHistorical || (!!active && !!bh)),
    staleTime: isHistorical ? Infinity : 10 * 60_000,
    refetchInterval: isHistorical ? false : 15 * 60_000,
    refetchOnWindowFocus: false,
    retry: isHistorical ? false : 3,
    // Keep the prior data rendered while a key change (language /
    // budget / snapshot-date flip) fetches fresh — avoids blank viz
    // during in-flight refetches.
    placeholderData: keepPreviousData,
  })
}

export interface LatticeSnapshotEntry {
  date: string
  size_bytes: number
  output_language: 'en' | 'zh-CN-mixed' | null
  recorded_at: string | null
}

// ── V10·A2 live self-check ─────────────────────────────

export interface SelfcheckEntry {
  name: string
  label: string
  pass: boolean
  detail: string
  offenders?: unknown[]
}
export interface SelfcheckReport {
  project_id: string
  summary: string
  all_pass: boolean
  checks: SelfcheckEntry[]
}
export function useLatticeSelfcheck(project_id: string, enabled: boolean) {
  return useQuery({
    queryKey: ['lattice_selfcheck', project_id],
    queryFn: () => fetchJSON<SelfcheckReport>(
      `/api/lattice/selfcheck?project_id=${encodeURIComponent(project_id)}`,
    ),
    enabled: !!project_id && enabled,
    staleTime: 30_000,
    retry: false,
  })
}


export function useLatticeSnapshots(project_id: string) {
  return useQuery({
    queryKey: ['lattice_snapshots', project_id],
    queryFn: () => fetchJSON<{ project_id: string; snapshots: LatticeSnapshotEntry[] }>(
      `/api/lattice/snapshots?project_id=${encodeURIComponent(project_id)}`,
    ),
    enabled: !!project_id,
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  })
}

// ── /api/lattice/graph — structural view for V3 viz ────
//
// Shape mirrors agent/finance/lattice/graph.py output exactly.
// Every field here has a backend test that pins it; if this
// type drifts from the backend shape, the frontend TypeScript
// strict compile catches it. See tests/test_lattice_graph_builder.py
// + tests/test_lattice_endpoint_coherence.py.

export type LatticeLayer = 'L0' | 'L1' | 'L1.5' | 'L2' | 'L3'
export type LatticeProvenance =
  | 'source' | 'deterministic' | 'llm' | 'llm+validator' | 'llm+mmr'
export type LatticeEdgeKind = 'source_emission' | 'membership' | 'grounds'

export interface LatticeGraphNode {
  id: string
  layer: LatticeLayer
  label: string
  provenance: {
    computed_by: LatticeProvenance
    method: string
    model: string | null
    inputs: string[]   // upstream node ids
  }
  attrs: Record<string, unknown>
}

/** Computation breakdown for a membership edge. Always present
 *  on kind=='membership' edges. */
export interface MembershipComputationDetail {
  jaccard_num: number
  jaccard_den: number
  any_of_matched: string[]
  any_of_required: string[]
  all_of_required: string[]
  all_of_satisfied: boolean
  base: number
  severity: string
  severity_bonus: number
  final: number
}

export interface LatticeGraphEdge {
  source: string
  target: string
  kind: LatticeEdgeKind
  weight: number | null       // present on membership only
  computation: {
    method: string
    detail: Record<string, unknown>   // shape varies by kind
  }
}

export interface LatticeGraphPayload {
  nodes: LatticeGraphNode[]
  edges: LatticeGraphEdge[]
  meta: {
    project_id: string
    taxonomy_version: number
    fetched_at: string
    duration_ms?: number
    layer_counts: Record<LatticeLayer, number>
    edge_counts: Record<LatticeEdgeKind, number>
  }
}

export function useLatticeGraph(project_id: string, asOf?: string | null) {
  const lang = useLatticeLanguage()
  const active = lang.data?.active
  const budgets = useLatticeBudgets()
  const bh = budgets.data?.effective_hash
  const historical = !!asOf && asOf !== 'live'
  return useQuery({
    queryKey: historical
      ? ['lattice_graph_snapshot', project_id, asOf]
      : ['lattice_graph', project_id, active, bh],
    queryFn: () => fetchJSON<LatticeGraphPayload>(
      `/api/lattice/graph?project_id=${encodeURIComponent(project_id)}` +
      (historical ? `&as_of=${encodeURIComponent(asOf!)}` : ''),
    ),
    enabled: !!project_id && (historical || (!!active && !!bh)),
    staleTime: historical ? Infinity : 10 * 60_000,
    refetchInterval: historical ? false : 15 * 60_000,
    refetchOnWindowFocus: false,
    placeholderData: keepPreviousData,
  })
}


// ── /api/lattice/trace/{node_id} — V6 deep trace ────────

/** Shape of the server-side trace. The `trace` field is intentionally
 *  Record<string, unknown> because backend emits different shapes per
 *  layer (narrative LLM call vs. call candidate pool vs. deterministic
 *  note). The UI renders a layer-specific view. */
export interface LatticeTracePayload {
  node_id: string
  layer: LatticeLayer
  trace: Record<string, unknown>
}

// ── Lattice language runtime toggle ────────────────────

export interface LatticeLanguageState {
  active: 'en' | 'zh-CN-mixed'
  override: 'en' | 'zh-CN-mixed' | null
  yaml_default: 'en' | 'zh-CN-mixed'
  available: Array<'en' | 'zh-CN-mixed'>
}

export function useLatticeLanguage() {
  return useQuery({
    queryKey: ['lattice_language'],
    queryFn: () => fetchJSON<LatticeLanguageState>('/api/lattice/language'),
    staleTime: 30_000,
  })
}

// ── V9 layer-budget runtime override ───────────────────

export interface LatticeLayerBudget {
  max_items: number | null
  min_members: number | null
  max_candidates: number | null
  mmr_lambda: number | null
}
export interface LatticeBudgets {
  observations: LatticeLayerBudget
  sub_themes: LatticeLayerBudget
  themes: LatticeLayerBudget
  calls: LatticeLayerBudget
}
export interface LatticeBudgetsState {
  effective: LatticeBudgets
  override: LatticeBudgets | null
  yaml_default: LatticeBudgets
  effective_hash: string
}
export function useLatticeBudgets() {
  return useQuery({
    queryKey: ['lattice_budgets'],
    queryFn: () => fetchJSON<LatticeBudgetsState>('/api/lattice/budgets'),
    staleTime: 30_000,
  })
}
/** POST the override (partial tree; pass `{}` to clear). Returns the
 *  new effective state + hash. Caller is responsible for setting the
 *  RQ cache (optimistic) + invalidating budget-keyed queries. */
export async function setLatticeBudgets(
  override: Partial<{ [K in keyof LatticeBudgets]: Partial<LatticeLayerBudget> }>,
): Promise<Pick<LatticeBudgetsState, 'effective' | 'override' | 'effective_hash'>> {
  const r = await fetch('/api/lattice/budgets', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(override),
  })
  if (!r.ok) {
    const body = await r.text().catch(() => '')
    throw new Error(`set budgets failed: ${r.status} ${body.slice(0, 200)}`)
  }
  return r.json()
}


export async function setLatticeLanguage(lang: 'en' | 'zh-CN-mixed' | 'clear') {
  const r = await fetch(
    `/api/lattice/language?lang=${encodeURIComponent(lang)}`,
    { method: 'POST' },
  )
  if (!r.ok) throw new Error(`set language failed: ${r.status}`)
  return (await r.json()) as Omit<LatticeLanguageState, 'available'>
}


export function useLatticeTrace(project_id: string, node_id: string | null) {
  const lang = useLatticeLanguage()
  const active = lang.data?.active
  return useQuery({
    queryKey: ['lattice_trace', project_id, node_id, active],
    queryFn: () => fetchJSON<LatticeTracePayload>(
      `/api/lattice/trace/${encodeURIComponent(node_id!)}?project_id=${encodeURIComponent(project_id)}`,
    ),
    enabled: !!project_id && !!node_id && !!active,
    staleTime: 60_000,
    retry: false,           // 404 means no trace captured; don't retry
    refetchOnWindowFocus: false,
  })
}

// ── Market sentiment gauge ──────────────────────────────
export interface SentimentSubscore {
  score: number | null
  [key: string]: unknown
}
export interface SentimentData {
  composite_score: number | null
  label: string
  components: {
    vix: SentimentSubscore & { raw?: number; percentile_pct?: number }
    spy_momentum: SentimentSubscore & { return_20d_pct?: number }
    breadth: SentimentSubscore & { up?: number; down?: number; total?: number }
  }
  fetched_at_epoch: number
}

export function useSentiment() {
  return useQuery({
    queryKey: ['sentiment'],
    queryFn: () => fetchJSON<SentimentData>('/api/sentiment'),
    staleTime: 8 * 60_000,
    refetchInterval: 10 * 60_000,
  })
}

// ── Fund / ETF deep-dive ────────────────────────────────
export interface FundHolding { symbol: string; name: string; weight_pct: number }
export interface FundInfo {
  symbol: string
  short_name: string
  long_name: string
  family: string
  category: string
  quote_type: string
  is_etf: boolean
  nav_price: number | null
  last_price: number | null
  total_assets: number | null
  expense_ratio_pct: number | null
  yield_pct: number | null
  ytd_return_pct: number | null
  three_year_return_pct: number | null
  five_year_return_pct: number | null
  trailing_pe: number | null
  asset_classes: Record<string, number>
  top_holdings: FundHolding[]
}

export function useFund(symbol: string | null) {
  return useQuery({
    queryKey: ['fund', symbol],
    queryFn: () => fetchJSON<FundInfo>(`/api/fund/${encodeURIComponent(symbol!)}`),
    enabled: !!symbol,
    staleTime: 10 * 60_000,
  })
}

// ── Watchlist ───────────────────────────────────────────
export interface WatchEntry {
  symbol: string
  market: 'US' | 'CN' | 'HK'
  note: string
  added_at?: string
  updated_at?: string
}

export function useWatchlist(project_id: string) {
  return useQuery({
    queryKey: ['watchlist', project_id],
    queryFn: () => fetchJSON<{ project_id: string; count: number; entries: WatchEntry[] }>(
      `/api/watchlist?project_id=${encodeURIComponent(project_id)}`,
    ),
    enabled: !!project_id,
    staleTime: 5_000,
  })
}

export function useWatchlistUpsert(project_id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (entry: { symbol: string; market: string; note?: string }) =>
      fetchJSON<{ ok: boolean; count: number }>(
        `/api/watchlist?project_id=${encodeURIComponent(project_id)}`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ symbol: entry.symbol, market: entry.market, note: entry.note ?? '' }),
        },
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['watchlist', project_id] }),
  })
}

export function useWatchlistPatchNote(project_id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (args: { symbol: string; market: string; note: string }) =>
      fetchJSON<{ ok: boolean }>(
        `/api/watchlist/${encodeURIComponent(args.symbol)}?project_id=${encodeURIComponent(project_id)}&market=${encodeURIComponent(args.market)}`,
        {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ note: args.note }),
        },
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['watchlist', project_id] }),
  })
}

export function useWatchlistRemove(project_id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (args: { symbol: string; market: string }) =>
      fetchJSON<{ ok: boolean; count: number }>(
        `/api/watchlist/${encodeURIComponent(args.symbol)}?project_id=${encodeURIComponent(project_id)}&market=${encodeURIComponent(args.market)}`,
        { method: 'DELETE' },
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['watchlist', project_id] }),
  })
}

// ── Chat sessions (persistence) ────────────────────────
export interface ChatSessionSummary {
  session_id: string
  created_at: string
  updated_at?: string
  title: string
  message_count: number
}

export interface StoredMessage {
  role: 'user' | 'assistant' | 'error' | 'system'
  content: string
  ts?: string
  req_id?: string
}

export async function createChatSession(project_id: string): Promise<{ session_id: string; created_at: string }> {
  return fetchJSON(`/api/chat_sessions?project_id=${encodeURIComponent(project_id)}`, { method: 'POST' })
}

export function useChatSessions(project_id: string) {
  return useQuery({
    queryKey: ['chat_sessions', project_id],
    queryFn: () => fetchJSON<{ project_id: string; count: number; sessions: ChatSessionSummary[] }>(
      `/api/chat_sessions?project_id=${encodeURIComponent(project_id)}&limit=100`,
    ),
    enabled: !!project_id,
    staleTime: 10_000,
  })
}

export async function loadChatSession(project_id: string, session_id: string) {
  return fetchJSON<{ project_id: string; session_id: string; meta: Record<string, unknown>; messages: StoredMessage[] }>(
    `/api/chat_sessions/${encodeURIComponent(session_id)}?project_id=${encodeURIComponent(project_id)}`,
  )
}

export async function appendChatMessage(
  project_id: string,
  session_id: string,
  message: StoredMessage,
): Promise<void> {
  await fetchJSON(`/api/chat_sessions/${encodeURIComponent(session_id)}/append?project_id=${encodeURIComponent(project_id)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(message),
  })
}

export async function archiveChatSession(project_id: string, session_id: string): Promise<void> {
  await fetchJSON(`/api/chat_sessions/${encodeURIComponent(session_id)}?project_id=${encodeURIComponent(project_id)}`, {
    method: 'DELETE',
  })
}

// ── Chart (indicator-enriched) ──────────────────────────
export interface ChartData {
  symbol: string
  period: string
  interval: string
  bars: Bar[]
  indicators: Record<string, unknown>
}

export function useChart(symbol: string | null, period = '3mo', interval = '1d') {
  return useQuery({
    queryKey: ['chart', symbol, period, interval],
    queryFn: () => fetchJSON<ChartData>(
      `/api/chart/${encodeURIComponent(symbol!)}?period=${period}&interval=${interval}&indicators=sma20,ema20,bb,rsi,macd`,
    ),
    enabled: !!symbol,
    staleTime: 60_000,
  })
}

// ── Fin Data Platform (Phase 1+) ──────────────────────────
//
// Hooks for the SQLite store + scheduler + integrity check + strategy
// catalog. Same shape as the lattice selfcheck so the UI badge
// pattern is reusable.

export interface FinIntegrityCheck {
  name: string
  label: string
  layer: string
  pass: boolean
  detail: string
  offenders?: unknown[]
  error?: string
}

export interface FinIntegrityReport {
  summary: string
  all_pass: boolean
  timestamp: string
  checks: FinIntegrityCheck[]
}

export function useFinIntegrity(enabled: boolean) {
  return useQuery({
    queryKey: ['fin_integrity'],
    queryFn: () => fetchJSON<FinIntegrityReport>('/api/integrity/check'),
    enabled,
    staleTime: 30_000,
    retry: false,
  })
}

export interface FinDbHealth {
  ok: boolean
  schema_version: number
  db_path: string
  counts: Record<string, number>
}

export function useFinDbHealth() {
  return useQuery({
    queryKey: ['fin_db_health'],
    queryFn: () => fetchJSON<FinDbHealth>('/api/db/health'),
    refetchInterval: 60_000,
    retry: false,
  })
}

export interface FinSchedulerJob {
  name: string
  description: string
  default_cron: string
  cron_expression: string
  enabled: boolean
  last_run_id: string | null
  last_run_at: string | null
  last_run_status: 'completed' | 'failed' | 'cancelled' | null
  consecutive_failures: number
  next_run_at: string | null
}

export function useFinSchedulerJobs() {
  return useQuery({
    queryKey: ['fin_scheduler_jobs'],
    queryFn: () => fetchJSON<{ count: number; jobs: FinSchedulerJob[] }>('/api/scheduler/jobs'),
    refetchInterval: 60_000,
    retry: false,
  })
}

/** One past run of a scheduler job, with its rich summary parsed
 *  out of `metadata_json`.  Powers the Strategies-tab "Last Audit"
 *  panel (and any future "did it actually run?" surfaces). */
export interface SchedulerRun {
  run_id: string
  run_type: 'scheduled' | 'manual' | 'force_rerun' | 'backfill'
  job_name: string
  started_at: string                       // ISO UTC
  completed_at: string | null              // ISO UTC, null while still running
  status: 'running' | 'completed' | 'failed' | 'cancelled'
  error_message: string | null
  rows_written: number | null
  duration_seconds: number | null
  /** Job-specific summary.  For audit_strategies these keys exist:
   *    audited_n / promoted_n / still_unverified / errors_n /
   *    sample[] / explanation
   *  Always defensive — older rows or other jobs may not have them. */
  metadata: {
    audited_n?: number
    promoted_n?: number
    still_unverified?: number
    errors_n?: number
    sample?: Array<{
      strategy_id: string
      state: string
      n_corpus_blobs: number
      n_supported: number
      n_unsupported: number
    }>
    explanation?: string
    // permissive — ignore other keys
    [k: string]: unknown
  }
}

export function useSchedulerRuns(jobName: string, limit = 10) {
  return useQuery({
    queryKey: ['fin_scheduler_runs', jobName, limit],
    queryFn: () =>
      fetchJSON<{ job: string; count: number; runs: SchedulerRun[] }>(
        `/api/scheduler/runs/${jobName}?limit=${limit}`,
      ),
    refetchInterval: 60_000,
    retry: false,
  })
}

// ── Strategies catalog (Phase 3 subagent output) ──────────

export interface StrategyTaxTreatment {
  qualifies_long_term: boolean
  wash_sale_risk: 'low' | 'medium' | 'high'
  section_1256: boolean
  notes: string
}

export interface StrategyEntry {
  id: string
  name_en: string
  name_zh: string
  horizon: 'long_term' | 'months' | 'weeks' | 'swing' | 'days' | 'intraday'
  difficulty: 1 | 2 | 3 | 4 | 5
  min_capital_usd: number
  asset_class: 'stock' | 'etf' | 'options' | 'crypto' | 'adr' | 'mixed'
  market: 'us' | 'cn_via_adr' | 'crypto' | 'global'
  defined_risk: boolean
  max_loss: string
  pdt_relevant: boolean
  tax_treatment: StrategyTaxTreatment
  data_requirements: string[]
  typical_win_rate: string
  feasible_at_10k: boolean
  feasible_at_10k_reason: string
  starter_step: string
  key_risks: string[]
  sources: string[]
  /** Anti-hallucination guard (Layer 1). Default 'unverified' — Phase 3
   *  research subagent's content has not been audited against real
   *  RawStore bytes.  UI shows a ⚠ chip on every entry whose state is
   *  not 'verified' / 'rawstore_grounded'.  Decision-path code paths
   *  (strategy_matcher) only see entries with trusted state. */
  provenance: {
    state: 'unverified' | 'partially_verified' | 'verified' | 'rawstore_grounded'
    source: string
  }
}

// ── Lineage: what L1 obs the fin SQLite store emits into the lattice ──

export interface FinLatticeObs {
  id: string
  kind: string
  text: string
  numbers: Record<string, number>
  tags: string[]
  source: { widget: string; symbol?: string; field?: string; generator?: string }
  severity: 'info' | 'warn' | 'alert'
  confidence: number
}

export interface FinLatticeObsReport {
  available: boolean
  count: number
  obs: FinLatticeObs[]
  feeds_into: string
  explanation: string
  reason?: string
}

export function useFinLatticeObs(enabled: boolean) {
  return useQuery({
    queryKey: ['fin_lattice_obs'],
    queryFn: () => fetchJSON<FinLatticeObsReport>('/api/db/lattice-obs'),
    enabled,
    staleTime: 30_000,
    retry: false,
  })
}

export function useFinStrategies() {
  return useQuery({
    queryKey: ['fin_strategies'],
    queryFn: () => fetchJSON<{
      count: number
      strategies: StrategyEntry[]
      by_horizon: Record<string, number>
    }>('/api/strategies'),
    staleTime: 5 * 60_000,
    retry: false,
  })
}

// Per-strategy "fit" against today's lattice themes — answers
// 'no L3 calls today, what's relevant?' Used by Strategies tab to
// show a fit score on every card even when no real call exists.
export interface StrategyFitEntry {
  strategy_id: string
  name_en: string | null
  name_zh: string | null
  horizon: string
  difficulty: number | null
  asset_class: string | null
  defined_risk: boolean | null
  pdt_relevant: boolean | null
  score: number
  score_breakdown: Record<string, number>
}

// ── Phase 6 Step 4: bidirectional widget index ───────────

export interface WidgetMeta {
  id: string
  status: 'available' | 'planned' | 'deprecated'
  label_en: string | null
  label_zh: string | null
  description: string | null
}

export interface StrategyWidgetCoverage {
  id: string
  name_en: string | null
  name_zh: string | null
  horizon: string | null
  widgets: WidgetMeta[]
  available_count: number
  planned_count: number
  unresolved: string[]
  free_text_requirements: string[]
}

export interface WidgetCoverageReport {
  strategies: StrategyWidgetCoverage[]
  summary: {
    total_strategies: number
    fully_available: number
    has_planned_gaps: number
    has_unresolved: number
  }
  explanation: string
}

export function useFinWidgetCoverage() {
  return useQuery({
    queryKey: ['fin_widget_coverage'],
    queryFn: () => fetchJSON<WidgetCoverageReport>('/api/strategies/widget-coverage'),
    staleTime: 5 * 60_000,
    retry: false,
  })
}

// Reverse map: widget id → strategies that need it. Phase 6 Step 6.
// Used by LatticeTracePanel to render 'Powered by N strategies' on L0
// widget nodes — closes the audit loop the other direction.

export interface WidgetReverseStrategy {
  id: string
  name_en: string | null
  name_zh: string | null
  horizon: string | null
  difficulty: number | null
  feasible_at_10k: boolean | null
}

export interface WidgetReverseReport {
  widget: WidgetMeta & { fields?: string[]; description?: string }
  strategy_count: number
  strategies: WidgetReverseStrategy[]
  explanation: string
}

export function useWidgetStrategies(widgetId: string | null | undefined) {
  return useQuery({
    queryKey: ['widget_strategies', widgetId],
    queryFn: () =>
      fetchJSON<WidgetReverseReport>(
        `/api/lattice/widgets/${encodeURIComponent(widgetId!)}/strategies`,
      ),
    enabled: !!widgetId,
    staleTime: 5 * 60_000,
    retry: false,
  })
}

export function useFinStrategiesFit(projectId: string, asOf?: string | null) {
  return useQuery({
    queryKey: ['fin_strategies_fit', projectId, asOf ?? 'live'],
    queryFn: () => fetchJSON<{
      project_id: string
      themes_count: number
      calls_count: number
      strategies_count: number
      fit: StrategyFitEntry[]
      explanation: string
    }>(
      `/api/strategies/lattice-fit?project_id=${encodeURIComponent(projectId)}` +
      (asOf && asOf !== 'live' ? `&as_of=${encodeURIComponent(asOf)}` : ''),
    ),
    enabled: !!projectId,
    staleTime: 60_000,
    retry: false,
  })
}


// ── Phase 6 followup #1: detailed past run log ───────────────────
//
// /api/db/runs (already exists in agent/finance/persistence/api.py)
// returns the full analysis_runs history — every scheduler tick or
// manual run leaves a row.  UI surfaces this as a timeline view so
// the user can audit "what did the agent actually do, when, and
// did it succeed?".

export interface FinPastRun {
  run_id: string
  run_type: 'scheduled' | 'manual' | 'force_rerun' | 'backfill' | string
  job_name: string
  started_at: string
  completed_at: string | null
  status: 'running' | 'completed' | 'failed' | 'cancelled' | string
  error_message: string | null
  universe_size: number | null
  rows_written: number | null
  duration_seconds: number | null
  metadata_json?: string | null
  metadata?: Record<string, unknown> | null
}

export function useFinPastRuns(opts?: { jobName?: string; limit?: number }) {
  const job = opts?.jobName
  const limit = opts?.limit ?? 50
  return useQuery({
    queryKey: ['fin_past_runs', job ?? null, limit],
    queryFn: () =>
      fetchJSON<{ count: number; runs: FinPastRun[] }>(
        `/api/db/runs?limit=${limit}${job ? `&job_name=${encodeURIComponent(job)}` : ''}`,
      ),
    refetchInterval: 30_000,
    staleTime: 10_000,
  })
}


export interface FinRunRows {
  run: FinPastRun
  total_rows: number
  by_table: Record<string, {
    count: number
    rows: Array<Record<string, unknown>>
    error?: string
    match_method?: string
  }>
  explanation: string
}

/** Phase 6 followup: drill-down into the actual rows written by one
 *  run. Fired only when a row is expanded — keeps closed rows free. */
export function useFinRunRows(runId: string | null | undefined, enabled: boolean) {
  return useQuery({
    queryKey: ['fin_run_rows', runId],
    queryFn: () =>
      fetchJSON<FinRunRows>(
        `/api/db/runs/${encodeURIComponent(runId!)}/rows?limit=100`,
      ),
    enabled: !!runId && enabled,
    staleTime: 60_000,
    retry: false,
  })
}


// ── Phase 6 followup: L2 ↔ Strategy bidirectional ─────────────────
//
// Forward (theme → strategies):  /api/strategies/by-theme?theme_id=X
//   Used by lattice trace inspector for L2 nodes.
//
// Reverse (strategy → today's themes):  /api/strategies/{id}/themes-today
//   Used by Strategies card 'TODAY MATCHING THEMES' section.

export interface ThemeMatchingStrategy {
  strategy_id: string
  name_en: string | null
  name_zh: string | null
  horizon: string
  difficulty: number | null
  asset_class: string | null
  defined_risk: boolean | null
  pdt_relevant: boolean | null
  feasible_at_10k: boolean | null
  score: number
  score_breakdown: Record<string, number>
}

export interface StrategiesByTheme {
  theme_id: string
  theme_title: string | null
  count: number
  strategies: ThemeMatchingStrategy[]
  explanation: string
}

export function useStrategiesByTheme(
  projectId: string | null | undefined,
  themeId: string | null | undefined,
  asOf?: string | null,
) {
  return useQuery({
    queryKey: ['strategies_by_theme', projectId, themeId, asOf ?? 'live'],
    queryFn: () =>
      fetchJSON<StrategiesByTheme>(
        `/api/strategies/by-theme?project_id=${encodeURIComponent(projectId!)}` +
        `&theme_id=${encodeURIComponent(themeId!)}` +
        (asOf && asOf !== 'live' ? `&as_of=${encodeURIComponent(asOf)}` : ''),
      ),
    enabled: !!projectId && !!themeId,
    staleTime: 60_000,
    retry: false,
  })
}


export interface StrategyTheme {
  theme_id: string
  theme_title: string | null
  score: number
  score_breakdown: Record<string, number>
}

export interface StrategyThemesToday {
  strategy_id: string
  count: number
  themes: StrategyTheme[]
  explanation: string
}

export function useStrategyThemesToday(
  strategyId: string | null | undefined,
  projectId: string,
  asOf?: string | null,
) {
  return useQuery({
    queryKey: ['strategy_themes_as_of', strategyId, projectId, asOf ?? 'live'],
    queryFn: () =>
      fetchJSON<StrategyThemesToday>(
        `/api/strategies/${encodeURIComponent(strategyId!)}/themes-as-of` +
        `?project_id=${encodeURIComponent(projectId)}` +
        (asOf && asOf !== 'live' ? `&as_of=${encodeURIComponent(asOf)}` : ''),
      ),
    enabled: !!strategyId && !!projectId,
    staleTime: 60_000,
    retry: false,
  })
}


// ── Phase 6 followup #2: time-aware Strategies ──────────────────
//
// /api/strategies/time-aware returns days-until-next-event for each
// catalog strategy that's event-driven (FOMC, quad witching, Russell
// rebalance, earnings season, etc).  Strategies without a calendar
// trigger get null — they're "always-on" (DCA, factor tilts, …).

export interface StrategyTimeAware {
  id: string
  days_until: number | null
  event_label: string | null
  event_date: string | null   // ISO yyyy-mm-dd
  urgency: 'imminent' | 'soon' | 'upcoming' | 'distant' | 'none'
}

export function useFinStrategiesTimeAware(projectId: string) {
  return useQuery({
    queryKey: ['fin_strategies_time_aware', projectId],
    queryFn: () =>
      fetchJSON<{ count: number; entries: StrategyTimeAware[]; computed_at: string }>(
        `/api/strategies/time-aware?project_id=${encodeURIComponent(projectId)}`,
      ),
    enabled: !!projectId,
    staleTime: 5 * 60_000,
    retry: false,
  })
}


// ── Phase 6 followup #3: bilingual one-button switch helper ─────
//
// Existing `useLatticeLanguage()` already exposes the active mode
// ('en' | 'zh-CN-mixed') and `setLatticeLanguage()` flips it
// globally.  This helper picks the right side of any bilingual
// `(en, zh)` pair so renders stay in sync with the toggle.

export function pickLang(
  en: string | null | undefined,
  zh: string | null | undefined,
  active: 'en' | 'zh-CN-mixed' | undefined,
): string {
  // bilingual fallback — if one side is missing, show the other
  const enS = (en ?? '').trim()
  const zhS = (zh ?? '').trim()
  if (active === 'en') return enS || zhS
  if (active === 'zh-CN-mixed') return zhS || enS
  // unknown / loading — show both, "zh / en"
  if (zhS && enS) return `${zhS} / ${enS}`
  return zhS || enS
}
