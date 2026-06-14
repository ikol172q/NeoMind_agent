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

// ── Serenity research corpus (一手语料库) ──────────────────
export interface RPost {
  post_id: string; platform: string; kind: string; created_at: string | null
  url: string | null; title: string | null; text: string
  is_reply: number; tickers: string[]; media_paths: string[]
  metrics: Record<string, number | null>; source_method: string
}
export function useResearchStats() {
  return useQuery({ queryKey: ['research', 'stats'], queryFn: () => fetchJSON<any>('/api/research/stats'), staleTime: 60000 })
}
export function useResearchChokepoint() {
  return useQuery({ queryKey: ['research', 'chokepoint'], queryFn: () => fetchJSON<any>('/api/research/chokepoint_map'), staleTime: 60000 })
}
export function useResearchAnalysis() {
  return useQuery({ queryKey: ['research', 'analysis'], queryFn: () => fetchJSON<any>('/api/research/analysis'), staleTime: 300000 })
}
export function useResearchSupplyChain() {
  return useQuery({ queryKey: ['research', 'supply_chain'], queryFn: () => fetchJSON<any>('/api/research/supply_chain'), staleTime: 60000 })
}
export function useResearchTimeline() {
  return useQuery({ queryKey: ['research', 'timeline'], queryFn: () => fetchJSON<any>('/api/research/timeline'), staleTime: 60000 })
}
export function useResearchProfile(ticker: string | null) {
  return useQuery({
    queryKey: ['research', 'profile', ticker],
    queryFn: () => fetchJSON<any>(`/api/research/profile/${encodeURIComponent((ticker || '').replace('$', ''))}`),
    enabled: !!ticker, staleTime: 300000,
  })
}
export function useResearchPosts(params: { ticker?: string; q?: string; originals_only?: boolean; limit?: number }) {
  const sp = new URLSearchParams()
  if (params.ticker) sp.set('ticker', params.ticker)
  if (params.q) sp.set('q', params.q)
  if (params.originals_only) sp.set('originals_only', 'true')
  sp.set('limit', String(params.limit ?? 80))
  const qs = sp.toString()
  return useQuery({ queryKey: ['research', 'posts', qs], queryFn: () => fetchJSON<RPost[]>(`/api/research/posts?${qs}`), placeholderData: keepPreviousData })
}
export function useResearchOutcomes() {
  return useQuery({ queryKey: ['research', 'outcomes'], queryFn: () => fetchJSON<any>('/api/research/outcomes?top_n=25'), staleTime: 300000 })
}
export function useResearchSync() {
  const qc = useQueryClient()
  return useMutation({ mutationFn: () => fetchJSON('/api/research/sync', { method: 'POST' }), onSuccess: () => qc.invalidateQueries({ queryKey: ['research'] }) })
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

// ── Streaming chat ──────────────────────────────────────
// (Fleet-backed dispatchChat + getTask removed 2026-05-01 — SPA only
// uses streamChat below. Fleet task-polling endpoint /api/tasks/{id}
// still served by backend for OpenBB Workspace copilot.)

export interface StreamCallbacks {
  onDelta: (chunk: string) => void
  onDone: (info: {
    req_id: string;
    duration_ms: number;
    total_tokens?: number;
    /** Tokens of the prompt the LLM saw (system + history + new user
     *  message). Used by the chat header to render a context-window
     *  status bar. */
    prompt_tokens?: number;
    /** Active model's advertised max context window size, in tokens.
     *  Pulled from agent.constants.models.get_active_max_context. */
    max_context?: number;
    /** True when the backend auto-compacted this turn (older history
     *  was summarized to keep prompt tokens under the threshold). */
    compacted?: boolean;
    content_length: number;
    /** URLs the LLM emitted that failed HEAD verification — surfaced
     *  by agent.llm_url_guard. Per-URL fallback is a Google search
     *  URL the UI can render so the user is never silently shown a
     *  broken link. */
    url_warnings?: Array<{ url: string; fallback: string; host: string }>;
  }) => void
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
  session_id?: string | null,
): AbortController {
  const ac = new AbortController()
  const qs = new URLSearchParams({ project_id, message })
  if (ctx?.symbol) qs.set('context_symbol', ctx.symbol)
  if (ctx?.project) qs.set('context_project', 'true')
  if (session_id) qs.set('session_id', session_id)

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
      // Track whether we got a clean termination (`done` event) so we
      // can distinguish a normal end from a connection drop.  Without
      // this the UI's pending spinner stayed forever when uvicorn
      // restarted mid-stream or when the network silently closed.
      let sawDoneEvent = false
      // Idle timeout: if no chunk for N seconds, treat as hung.  Real
      // DeepSeek streams emit at least one chunk every couple of
      // seconds; 60s is generous.
      const IDLE_MS = 60_000
      let idleTimer: ReturnType<typeof setTimeout> | null = null
      const resetIdle = () => {
        if (idleTimer) clearTimeout(idleTimer)
        idleTimer = setTimeout(() => {
          ac.abort()
          cb.onError('stream idle for 60s — connection likely dropped')
        }, IDLE_MS)
      }
      resetIdle()
      try {
        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          resetIdle()
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
                sawDoneEvent = true
                cb.onDone(payload)
              } else if (event === 'error') {
                cb.onError(String(payload.detail ?? 'stream error'))
              }
            } catch (_) {
              // skip non-JSON frames (heartbeats etc.)
            }
          }
        }
      } finally {
        if (idleTimer) clearTimeout(idleTimer)
      }
      // Reader closed without a `done` event — this is the case where
      // uvicorn restarts mid-stream, the network drops, or the
      // connection times out at the proxy.  Fire onError so the UI
      // exits its pending state instead of spinning forever.
      if (!sawDoneEvent) {
        cb.onError('stream closed without final event — connection dropped or backend restarted')
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
  //
  // BUG FIX: ``'live'`` is a sentinel string callers pass when there
  // is NO historical pin (it shares the type with date strings to
  // simplify call sites).  Treat it as "no date" — otherwise we hit
  // /api/lattice/snapshot?date=live which 500s on backend (since
  // 'live' is not a valid YYYY-MM-DD snapshot file).
  const lang = useLatticeLanguage()
  const active = lang.data?.active
  const budgets = useLatticeBudgets()
  const bh = budgets.data?.effective_hash
  const isHistorical = !!date && date !== 'live'
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

// ── timezone helpers for as-of dates ───────────────────────────
//
// Bug: snapshot.date is the SERVER's UTC calendar date (e.g.
// "2026-04-27" for a snapshot recorded at 02:40Z).  But the user
// thinks of dates in their local time (the same recording is
// "04/26 7:40 PM" Pacific).  AsOfPicker's dropdown rows show local
// (correct) but the audit panel + as-of banner showed the raw UTC
// string ("2026-04-27") — confusing two-different-numbers UX.
//
// These helpers translate at the display / input boundary using
// the snapshot list as ground truth (recorded_at carries the true
// instant; toLocaleDateString() is the canonical local YMD).

/** Convert "YYYY-MM-DD" → Date at midnight LOCAL. */
function ymdToDate(ymd: string): Date {
  const [y, m, d] = ymd.split('-').map(Number)
  return new Date(y, m - 1, d)
}
/** Convert ISO timestamp → "YYYY-MM-DD" in LOCAL time. */
function isoToLocalYMD(iso: string | null | undefined): string {
  if (!iso) return ''
  try {
    const d = new Date(iso)
    const yyyy = d.getFullYear()
    const mm = String(d.getMonth() + 1).padStart(2, '0')
    const dd = String(d.getDate()).padStart(2, '0')
    return `${yyyy}-${mm}-${dd}`
  } catch {
    return ''
  }
}

/** asOf is stored as the snapshot's UTC date string, but the user
 *  thinks in their local timezone.  Given asOf + snapshots list,
 *  return the LOCAL YMD that corresponds to it (matches the label
 *  shown in AsOfPicker's dropdown).  Falls back to asOf itself
 *  (unchanged) when no snapshot matches — better than throwing. */
export function asOfToLocalYMD(
  asOf: string,
  snapshots: LatticeSnapshotEntry[] | undefined,
): string {
  if (!asOf || asOf === 'live') return asOf
  const matched = (snapshots ?? []).find((s) => s.date === asOf)
  const local = isoToLocalYMD(matched?.recorded_at)
  return local || asOf  // fall back to UTC YMD if no match
}

/** Reverse: user picks a date in the date-input (always LOCAL YMD),
 *  return the snapshot.date (UTC) that maps to it so we can store
 *  it in asOf.  When no exact snapshot matches, return the local
 *  YMD itself — caller will end up showing the friendly "no snapshot
 *  for X" empty state from DigestView. */
export function localYMDToAsOf(
  localYMD: string,
  snapshots: LatticeSnapshotEntry[] | undefined,
): string {
  if (!localYMD) return localYMD
  // Find snapshot whose recorded_at falls on this local date
  const target = ymdToDate(localYMD).getTime()
  const tomorrow = target + 24 * 60 * 60 * 1000
  const matched = (snapshots ?? []).find((s) => {
    if (!s.recorded_at) return false
    const t = new Date(s.recorded_at).getTime()
    return t >= target && t < tomorrow
  })
  return matched?.date ?? localYMD
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
  /** Set when the session was started from a Stock Research Drawer's
   *  Chat tab — used by drawer to filter "past sessions about ROKU".
   *  Old sessions created before this column existed return null. */
  ticker_tag?: string | null
}

export interface StoredMessage {
  role: 'user' | 'assistant' | 'error' | 'system'
  content: string
  ts?: string
  req_id?: string
}

export async function createChatSession(
  project_id: string,
  ticker?: string | null,
): Promise<{ session_id: string; created_at: string; ticker_tag?: string | null }> {
  const qs = new URLSearchParams({ project_id })
  if (ticker) qs.set('ticker', ticker)
  return fetchJSON(`/api/chat_sessions?${qs}`, { method: 'POST' })
}

export function useChatSessions(project_id: string, ticker?: string | null) {
  const qs = new URLSearchParams({ project_id, limit: '100' })
  if (ticker) qs.set('ticker', ticker)
  return useQuery({
    // ticker is part of the cache key so different tickers (or the
    // unfiltered view) don't pollute each other.
    queryKey: ['chat_sessions', project_id, ticker ?? null],
    queryFn: () => fetchJSON<{ project_id: string; count: number; sessions: ChatSessionSummary[] }>(
      `/api/chat_sessions?${qs}`,
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

/** Bounds passed to /api/scheduler/runs/{job_name}. ISO 8601 strings,
 *  inclusive on both sides. ``null``/``undefined`` = no bound. */
export interface SchedulerRunsBounds {
  startedAfter?: string | null
  startedBefore?: string | null
}

export function useSchedulerRuns(
  jobName: string,
  limit = 10,
  bounds?: SchedulerRunsBounds,
) {
  const after = bounds?.startedAfter ?? null
  const before = bounds?.startedBefore ?? null
  return useQuery({
    // Keep the bounds in the cache key so flipping the TimeScope
    // pill triggers a refetch (and doesn't leak the previous result
    // into the new view).
    queryKey: ['fin_scheduler_runs', jobName, limit, after, before],
    queryFn: () => {
      const params = new URLSearchParams({ limit: String(limit) })
      if (after)  params.set('started_after',  after)
      if (before) params.set('started_before', before)
      return fetchJSON<{
        job: string
        count: number
        runs: SchedulerRun[]
        filters: {
          limit: number
          started_after: string | null
          started_before: string | null
        }
      }>(`/api/scheduler/runs/${jobName}?${params.toString()}`)
    },
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

export interface RegimeFingerprintScores {
  risk_appetite_score:     number | null
  volatility_regime_score: number | null
  breadth_score:           number | null
  event_density_score:     number | null
  flow_score:              number | null
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
      scorer_version?: 'regime_v2' | 'categorical_v1'
      fingerprint_date?: string | null
      fingerprint?: RegimeFingerprintScores | null
    }>(
      `/api/strategies/lattice-fit?project_id=${encodeURIComponent(projectId)}` +
      (asOf && asOf !== 'live' ? `&as_of=${encodeURIComponent(asOf)}` : ''),
    ),
    enabled: !!projectId,
    staleTime: 60_000,
    retry: false,
  })
}

// ── /api/regime/* — 5-bucket regime fingerprint ───────────────

export interface RegimeFingerprint {
  fingerprint_date:        string
  risk_appetite_score:     number | null
  volatility_regime_score: number | null
  breadth_score:           number | null
  event_density_score:     number | null
  flow_score:              number | null
  components?: {
    risk_appetite?:     Record<string, Record<string, number | null> | { value?: number }>
    volatility_regime?: Record<string, Record<string, number | null> | { value?: number }>
    breadth?:           Record<string, Record<string, number | null> | { value?: number }>
    event_density?:     Record<string, Record<string, number | null> | { value?: number }>
    flow?:              Record<string, Record<string, number | null> | { value?: number }>
  }
  inputs?:  Record<string, Record<string, unknown>>
  sources?: Record<string, Record<string, string>>
  todos?:   string[]
}

export function useRegimeFingerprint(date?: string | null) {
  return useQuery({
    queryKey: ['regime_fingerprint', date ?? 'today'],
    queryFn: () => {
      const url = (date && date !== 'live')
        ? `/api/regime/at?date=${encodeURIComponent(date)}`
        : `/api/regime/today`
      return fetchJSON<RegimeFingerprint>(url)
    },
    staleTime: 60_000,
    retry: false,
  })
}


// ── Step F: MMR-diversified portfolio (top1 + alternatives) ────────


export interface PortfolioEntry {
  strategy_id: string
  name_en?: string
  name_zh?: string
  horizon?: string
  difficulty?: number
  asset_class?: string
  score: number
  score_breakdown?: Record<string, unknown>
  formula?: string
  _mmr_score?: number
  _diversity_from_top?: number
}

export interface PortfolioSelection {
  top: PortfolioEntry | null
  alternatives: PortfolioEntry[]
  selection_method: string
  lambda: number
  n_alternatives: number
  n_candidates_considered?: number
  fingerprint_date?: string
  fingerprint?: RegimeFingerprintScores | null
  note?: string
}

export function usePortfolioSelection(
  date?: string | null,
  nAlternatives: number = 5,
  lambdaWeight: number = 0.65,
) {
  return useQuery({
    queryKey: ['portfolio_selection', date ?? 'today', nAlternatives, lambdaWeight],
    queryFn: () => {
      const params = new URLSearchParams()
      if (date && date !== 'live') params.set('as_of', date)
      params.set('n_alternatives', String(nAlternatives))
      params.set('lambda_weight', String(lambdaWeight))
      return fetchJSON<PortfolioSelection>(`/api/regime/portfolio?${params}`)
    },
    staleTime: 60_000,
    retry: false,
  })
}


// ── decision_traces (Audit tab drill view) ─────────────────────────


export interface DecisionTrace {
  trace_id: string
  fingerprint_date: string
  strategy_id: string
  score: number
  rank: number
  alternative_weight: number
  formula: string
  computed_at: string
  breakdown?: Record<string, unknown> | null
  lattice_node_refs?: string[] | null
  knn_neighbor_dates?: string[] | null
  constraint_check?: Record<string, unknown> | null
  portfolio_fit?: Record<string, unknown> | null
}

// ── Settings #92: user prefs (4-question onboarding) ──────────────


export interface UserPrefs {
  options_level: number                    // 0..3
  max_drawdown_tolerance: number           // 0..1
  income_vs_growth: number                 // 0..1
  max_position_concentration: number       // 0..1
  _source?: 'saved' | 'default'
  _path?: string
  _defaults?: Partial<UserPrefs>
}

export function useUserPrefs() {
  return useQuery({
    queryKey: ['user_prefs'],
    queryFn: () => fetchJSON<UserPrefs>('/api/regime/prefs'),
    staleTime: 60_000,
    retry: false,
  })
}

export async function saveUserPrefs(prefs: Partial<UserPrefs>): Promise<UserPrefs> {
  const r = await fetch('/api/regime/prefs', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(prefs),
  })
  if (!r.ok) {
    const txt = await r.text().catch(() => '')
    throw new Error(`saveUserPrefs ${r.status}: ${txt}`)
  }
  const data = await r.json()
  return data.merged as UserPrefs
}


// ── Phase L: NeoMind Live — push signal system ────────────────────


export interface UserWatchlistEntry {
  ticker:     string
  added_at:   string
  note?:      string | null
  importance: number
}

export interface UserWatchlistPayload {
  user_watchlist:  UserWatchlistEntry[]
  supply_chain:    string[]
  total_universe:  string[]
}

export function useUserWatchlist() {
  return useQuery({
    queryKey: ['user_watchlist'],
    queryFn: () => fetchJSON<UserWatchlistPayload>('/api/regime/watchlist'),
    staleTime: 60_000,
    retry: false,
  })
}

export async function saveWatchlistBulk(tickers: string[]): Promise<{
  added: string[]; removed: string[]; current: string[]
}> {
  const r = await fetch('/api/regime/watchlist/bulk', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ tickers }),
  })
  if (!r.ok) throw new Error(`saveWatchlistBulk ${r.status}`)
  return r.json()
}

export async function triggerWatchlistScan(): Promise<{
  scanner: string
  n_tickers: number
  n_emitted: number
  new_confluences: number
  took_ms: number
}> {
  const r = await fetch('/api/regime/scan/watchlist', { method: 'POST' })
  if (!r.ok) throw new Error(`scan ${r.status}`)
  return r.json()
}

export async function triggerAllScans(): Promise<{
  scanners: Record<string, unknown>
  new_confluences: number
}> {
  // include_13f=true is REQUIRED — backend default is False, so without
  // this query string the 13F whale scanner (Buffett/Bridgewater/etc) is
  // silently skipped on every "立即扫描" click. That's why BRK data
  // stayed stale even though the button "ran". See
  // agent/finance/regime/api.py:372-475.
  const r = await fetch('/api/regime/scan/all?include_13f=true', { method: 'POST' })
  if (!r.ok) throw new Error(`scan/all ${r.status}`)
  return r.json()
}


export interface SignalEvent {
  event_id:         string
  scanner_name:     string
  ticker?:          string | null
  theme?:           string | null
  signal_type:      string
  severity:         'high' | 'med' | 'low'
  title:            string
  body?:            Record<string, unknown> | null
  source_url?:      string | null
  source_timestamp?: string | null
  detected_at:      string
}

export interface SignalConfluence {
  confluence_id:   string
  ticker?:         string | null
  theme?:          string | null
  headline:        string
  n_sources:       number
  color:           'green' | 'amber' | 'red' | 'gray'
  interpretation?: string | null
  detected_at:     string
  expires_at:      string
  event_ids?:      string[]
  events?:         SignalEvent[]
  dismissed?:      number
}

export function useTodaySignals(limit: number = 3) {
  return useQuery({
    queryKey: ['signals_today', limit],
    queryFn: () => fetchJSON<{ n: number; signals: SignalConfluence[] }>(
      `/api/regime/signals/today?limit=${limit}`,
    ),
    staleTime: 30_000,
    refetchInterval: 60_000,         // poll every minute
    retry: false,
  })
}

// 2026-05-19: per-whale top-N (solves the firehose problem where 2-3
// busy whales monopolize the latest-N slots and others vanish).
// Backend uses SQLite window function so it's a single round-trip.
export interface WhaleGroupedSignals {
  whale_key:     string
  whale:         string
  horizon:       string
  bias:          string
  style:         string
  signal_weight: number
  n_events:      number
  events:        SignalEvent[]
}
export function useSignalsByWhale(opts: {
  scanner?: string
  limit_per_whale?: number
} = {}) {
  const { scanner = '13f', limit_per_whale = 10 } = opts
  return useQuery({
    queryKey: ['signals_by_whale', scanner, limit_per_whale],
    queryFn: () => {
      const params = new URLSearchParams()
      params.set('scanner', scanner)
      params.set('limit_per_whale', String(limit_per_whale))
      return fetchJSON<{
        scanner: string
        limit_per_whale: number
        n_whales_with_events: number
        n_whales_total: number
        whales: WhaleGroupedSignals[]
      }>(`/api/regime/whales_by_whale?${params}`)
    },
    staleTime: 30_000,
    refetchInterval: 60_000,
    retry: false,
  })
}

// 2026-05-19: per-whale research summary (Tavily + LLM synthesis +
// URL-validated). One row per generation, latest = is_active.
export interface WhaleResearchValidatedLink {
  url:          string
  http_status?: number | null
  ok:           boolean
  validated_at: string
  error?:       string
}
export interface WhaleResearchNewsItem {
  title:     string
  url:       string
  published: string
  source:    string
  summary:   string
  relevance: string
}
export interface WhaleResearchSummary {
  investment_logic:        string
  aum_market_position:     string
  recent_moves_synthesis:  string
  recent_news:             WhaleResearchNewsItem[]
  controversies_risks:     string
  key_things_to_know:      string[]
  all_links_validated:     WhaleResearchValidatedLink[]
  _meta?: Record<string, unknown>
}
export interface WhaleResearchRow {
  id:               number
  whale_key:        string
  generated_at:     string
  model_used:       string
  n_search_results: number
  n_urls_validated: number
  error_message?:   string
  is_active?:       number
  exists:           boolean
  summary?:         WhaleResearchSummary | null
}
export function useWhaleResearch(whaleKey: string | null) {
  return useQuery({
    queryKey: ['whale-research', whaleKey],
    queryFn: () => fetchJSON<WhaleResearchRow>(
      `/api/regime/whales/${whaleKey}/research`),
    enabled: !!whaleKey,
    staleTime: 60_000 * 10,
  })
}
export function useRegenWhaleResearch() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (whaleKey: string) =>
      fetchJSON<WhaleResearchRow>(
        `/api/regime/whales/${whaleKey}/research/regenerate`,
        { method: 'POST' }),
    onSuccess: (_data, whaleKey) => {
      qc.invalidateQueries({ queryKey: ['whale-research', whaleKey] })
      qc.invalidateQueries({ queryKey: ['whale-research-history', whaleKey] })
    },
  })
}
export function useWhaleResearchHistory(whaleKey: string | null) {
  return useQuery({
    queryKey: ['whale-research-history', whaleKey],
    queryFn: () => fetchJSON<{
      whale_key: string; n: number;
      history: Array<{
        id: number; generated_at: string; model_used: string;
        n_search_results: number; n_urls_validated: number;
        is_active: number; error_message?: string;
      }>
    }>(`/api/regime/whales/${whaleKey}/research/history?limit=10`),
    enabled: !!whaleKey,
    staleTime: 60_000 * 30,
  })
}


// 2026-05-22: Decision Scorecard — synthesizes all signals into a
// suggested lean (add/hold/trim/sell/watch_only/pass) + degree.
export interface ScorecardSource {
  label: string
  url: string | null
  kind: string
  validated: boolean
}
export interface ScorecardWhaleDetail {
  whale: string
  whale_key: string
  action: string
  date: string
  url: string | null
  weight: number
}
export interface ScorecardMetric {
  k: string
  v: string
  verdict: 'good' | 'ok' | 'bad'
}
export interface ScorecardLens {
  score: number
  read: string
  pending?: boolean
  conv_raw?: number
  buyers?: string[]
  sellers?: string[]
  insider_buys?: number
  activist?: string[]
  pe?: number | null
  pe_kind?: string | null
  held?: boolean
  weight?: number
  metrics?: ScorecardMetric[]
  sources?: ScorecardSource[]
  detail?: ScorecardWhaleDetail[]
}
export interface DecisionScorecard {
  ticker: string
  held: boolean
  suggested_lean: 'add' | 'hold' | 'trim' | 'sell' | 'watch_only' | 'pass'
  degree: string
  raw_score: number
  summary: string
  lenses: {
    quality: ScorecardLens
    positioning: ScorecardLens
    valuation: ScorecardLens
    fit: ScorecardLens
  }
  help: Record<string, string>
  disclaimer: string
}
export function useScorecard(ticker: string | null) {
  return useQuery({
    queryKey: ['scorecard', ticker],
    queryFn: () => fetchJSON<DecisionScorecard>(
      `/api/regime/scorecard/${encodeURIComponent(ticker!)}`),
    enabled: !!ticker,
    staleTime: 60_000 * 5,
    retry: false,
  })
}


export function useRecentSignals(opts: {
  limit?:   number
  ticker?:  string
  scanner?: string
} = {}) {
  const { limit = 50, ticker, scanner } = opts
  return useQuery({
    queryKey: ['signals_recent', limit, ticker ?? '', scanner ?? ''],
    queryFn: () => {
      const params = new URLSearchParams()
      params.set('limit', String(limit))
      if (ticker)  params.set('ticker', ticker)
      if (scanner) params.set('scanner', scanner)
      return fetchJSON<{ n: number; events: SignalEvent[] }>(
        `/api/regime/signals/recent?${params}`,
      )
    },
    staleTime: 15_000,
    refetchInterval: 30_000,         // live-ish stream — poll every 30s
    retry: false,
  })
}

// Phase M1b — analysis_runs feed for NeoMindLive "ops" view.
export interface AnalysisRun {
  run_id:        string
  job_name:      string
  run_type?:     string | null
  status:        string                         // running | completed | failed
  started_at:    string
  completed_at?: string | null
  duration_s?:   number | null
  rows_written?: number | null
  error_message?: string | null
  summary?:      Record<string, unknown> | null
}

export function useRecentRuns(limit = 50) {
  return useQuery({
    queryKey: ['regime', 'runs', limit],
    queryFn: () =>
      fetchJSON<{ n: number; runs: AnalysisRun[] }>(
        `/api/regime/runs?limit=${limit}`,
      ),
    // Phase M1b: keep this snappy — when the user clicks "立即扫描" the
    // run row appears as `running` within 10s, then flips to `completed`
    // a few polls later.  Cheap query (5–10 SQLite rows).
    staleTime: 5_000,
    refetchInterval: 10_000,
    retry: false,
  })
}


export async function dismissSignal(confluenceId: string): Promise<boolean> {
  const r = await fetch(
    `/api/regime/signals/dismiss/${encodeURIComponent(confluenceId)}`,
    { method: 'POST' },
  )
  if (!r.ok) return false
  const data = await r.json()
  return !!data.ok
}


// ── Risk Dashboard (Phase H — 6-dimension math-backed view) ───────


export interface RiskBucketFit {
  strategy_pref: 'high' | 'low' | 'neutral'
  sensitivity:   number
  today:         'high' | 'low' | 'neutral'
  today_value:   number
  fit:           'good' | 'warning' | 'bad' | 'neutral'
}

export interface RiskDashboardEntry {
  strategy_id:      string
  name_zh?:         string
  name_en?:         string
  horizon?:         string
  asset_class?:     string
  hold_days:        number
  fingerprint_date: string
  data_quality:     'real' | 'proxy_only'

  return_distribution: {
    n: number
    median?:        number
    p10?:           number
    p25?:           number
    p75?:           number
    p90?:           number
    mean?:          number
    std?:           number
    k_nn?:          number
    neighbor_dates?: string[]
    error?:         string
  }

  tail_risk: {
    n: number
    confidence?:        number
    var?:               number
    cvar?:              number
    max_drawdown?:      number
    max_drawdown_date?: string
    win_rate?:          number
    loss_rate?:         number
    error?:             string
  }

  position_sizing: {
    n: number
    win_rate?:         number
    avg_win?:          number
    avg_loss?:         number
    gain_loss_ratio?:  number
    kelly?:            number | null
    half_kelly?:       number | null
    interpretation?:   string
    error?:            string
  }

  hedge_candidates: {
    n_candidates?: number
    top?: Array<{
      strategy_id:  string
      correlation:  number
      n_overlap:    number
      size_ratio:   number
    }>
    error?: string
  }

  stop_loss: {
    n?: number
    sigma?:          number
    suggested_stop?: number
    atr_multiple?:   number
    time_stop_days?: number
    coverage?:       number
    interpretation?: string
    error?:          string
  }

  regime_fit: {
    buckets:    Record<string, RiskBucketFit>
    n_good:     number
    n_warning:  number
    n_bad:      number
    n_neutral:  number
    fit_score:  number
    verdict:    'strong_fit' | 'ok_fit' | 'weak_fit' | 'bad_fit'
  }

  walk_forward?: {
    strategy_id?:        string
    n_total?:            number
    is_n?:               number
    oos_n?:              number
    is_sharpe_ann?:      number
    oos_sharpe_ann?:     number
    is_oos_gap?:         number
    overfitting_ratio?:  number | null
    deflated_sharpe?: {
      observed_sr:     number
      n_trials:        number
      n_obs:           number
      skewness:        number
      kurtosis:        number
      sr_max_expected: number
      sr_se:           number
      z_score:         number
      dsr_prob:        number
      interpretation:  string
    }
    verdict?:            'ship' | 'promising' | 'noise' | 'overfit' | 'uncertain'
    error?:              string
  }

  recommendation: {
    color:            'green' | 'amber' | 'red' | 'gray'
    reasons_for:      string[]
    reasons_against:  string[]
    interpretation:   string
    paper_trade_required?: boolean
  }
}

export function useRiskDashboard(opts: {
  strategyId: string
  asOf?: string | null
  holdDays?: number
}) {
  const { strategyId, asOf, holdDays = 30 } = opts
  return useQuery({
    queryKey: ['risk_dashboard', strategyId, asOf ?? 'today', holdDays],
    queryFn: () => {
      const params = new URLSearchParams()
      params.set('strategy_id', strategyId)
      if (asOf) params.set('as_of', asOf)
      params.set('hold_days', String(holdDays))
      return fetchJSON<RiskDashboardEntry>(`/api/regime/dashboard?${params}`)
    },
    staleTime: 60_000,
    retry: false,
    enabled: !!strategyId,
  })
}

export function useRiskDashboardAll(opts: {
  asOf?: string | null
  holdDays?: number
  limit?: number
} = {}) {
  const { asOf, holdDays = 30, limit = 36 } = opts
  return useQuery({
    queryKey: ['risk_dashboard_all', asOf ?? 'today', holdDays, limit],
    queryFn: () => {
      const params = new URLSearchParams()
      if (asOf) params.set('as_of', asOf)
      params.set('hold_days', String(holdDays))
      params.set('limit', String(limit))
      return fetchJSON<{
        fingerprint_date: string
        n: number
        strategies: RiskDashboardEntry[]
      }>(`/api/regime/dashboard/all?${params}`)
    },
    staleTime: 60_000,
    retry: false,
  })
}


// ── Backtest recall (per-strategy calibration) ────────────────────


export interface BacktestRecallEntry {
  strategy_id: string
  n_runs: number
  mean_predicted: number
  mean_realized: number
  median_realized: number
  hit_rate: number | null
  p_calibration_high: number | null
  p_calibration_low: number | null
  delta_high_low: number | null
  spearman_corr: number | null
  n_high: number
  n_low: number
}

export interface BacktestRecallPayload {
  strategies: BacktestRecallEntry[]
  n_total_rows: number
  score_cutoff: number
  hold_days: number
}

export function useBacktestRecall(opts: {
  holdDays?: number
  scoreCutoff?: number
  strategyId?: string | null
} = {}) {
  const { holdDays = 30, scoreCutoff = 4.0, strategyId } = opts
  return useQuery({
    queryKey: ['backtest_recall', holdDays, scoreCutoff, strategyId ?? 'all'],
    queryFn: () => {
      const params = new URLSearchParams()
      params.set('hold_days', String(holdDays))
      params.set('score_cutoff', String(scoreCutoff))
      if (strategyId) params.set('strategy_id', strategyId)
      return fetchJSON<BacktestRecallPayload>(`/api/regime/backtest/recall?${params}`)
    },
    staleTime: 60_000,
    retry: false,
  })
}


export interface BacktestRow {
  result_id: string
  fingerprint_date: string
  strategy_id: string
  predicted_score: number
  rank: number
  hold_days: number
  realized_pnl_pct: number | null
  underlying_return: number | null
  method: string
  notes?: Record<string, unknown> | null
  computed_at: string
}

export function useBacktestRows(opts: {
  fingerprintDate?: string | null
  strategyId?: string | null
  holdDays?: number
  limit?: number
} = {}) {
  const { fingerprintDate, strategyId, holdDays = 30, limit = 500 } = opts
  return useQuery({
    queryKey: ['backtest_rows', fingerprintDate ?? 'all', strategyId ?? 'all', holdDays, limit],
    queryFn: () => {
      const params = new URLSearchParams()
      params.set('hold_days', String(holdDays))
      params.set('limit', String(limit))
      if (fingerprintDate) params.set('fingerprint_date', fingerprintDate)
      if (strategyId) params.set('strategy_id', strategyId)
      return fetchJSON<{ count: number, results: BacktestRow[] }>(
        `/api/regime/backtest/rows?${params}`
      )
    },
    staleTime: 60_000,
    retry: false,
    enabled: !!(fingerprintDate || strategyId),
  })
}


export function useDecisionTraces(opts: {
  date?: string | null
  strategyId?: string | null
  limit?: number
} = {}) {
  const { date, strategyId, limit = 200 } = opts
  return useQuery({
    queryKey: ['decision_traces', date ?? 'all', strategyId ?? 'all', limit],
    queryFn: () => {
      const params = new URLSearchParams()
      if (date) params.set('fingerprint_date', date)
      if (strategyId) params.set('strategy_id', strategyId)
      params.set('limit', String(limit))
      return fetchJSON<{ count: number, traces: DecisionTrace[] }>(
        `/api/regime/traces?${params}`
      )
    },
    staleTime: 30_000,
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


// ─── Stock Research Drawer (Phase R1) ─────────────────────────────

export interface StockProfile {
  ticker: string
  name?: string | null
  sector?: string | null
  summary?: string | null
  segments: Array<{ name: string; pct: number; note?: string }>
  upstream: Array<{ ticker: string; name: string; role: string }>
  downstream: Array<{ ticker: string; name: string; role: string }>
  competitors: Array<{ ticker: string; name: string; note?: string }>
  catalysts: Array<{ when: string; what: string; severity: 'high' | 'med' | 'low' }>
  risks: string[]
  style_verdict?: string | null
  quick_stats?: { price?: string; marketCap?: string; pe?: string }
  user_status?: 'researching' | 'watching' | 'pass' | 'own' | null
  user_status_reason?: string | null
  user_status_ts?: string | null
  generated_at?: string | null
  generated_model?: string | null
  source_citations: Array<{ id: number; url: string; title: string; verified?: boolean }>
}

export interface StockExposureEvent {
  // 2026-05-10 Phase W: event_id added so chain panel + note trigger
  // selector can reference real signal_events rows (not array indices).
  event_id?: string
  scanner: string
  signal_type: string
  severity: 'high' | 'med' | 'low'
  title: string
  body: Record<string, unknown>
  source_url?: string | null
  source_timestamp?: string | null
  detected_at: string
}

export interface StockNote {
  id: number
  ticker: string
  ts: string
  body: string
  tag?: string | null
  source: 'user' | 'llm-extract'
  // Phase W: optional trigger linkage
  trigger_signal_id?: string | null
  trigger_fact_id?: number | null
  trigger_thesis_id?: string | null
}

export function useStockProfile(ticker: string | null) {
  return useQuery<StockProfile | null>({
    queryKey: ['stock-profile', ticker],
    queryFn: async () => {
      if (!ticker) return null
      try {
        return await fetchJSON<StockProfile>(`/api/stock/${encodeURIComponent(ticker)}/profile`)
      } catch (e: any) {
        // 404 = no cached profile yet — UI shows "click ✨ regenerate"
        if (String(e?.message || '').includes('404')) return null
        throw e
      }
    },
    enabled: !!ticker,
    staleTime: 5 * 60_000,
    retry: false,
  })
}

export function useStockExposure(ticker: string | null) {
  return useQuery<{ ticker: string; n: number; events: StockExposureEvent[] }>({
    queryKey: ['stock-exposure', ticker],
    queryFn: () => fetchJSON(`/api/stock/${encodeURIComponent(ticker!)}/exposure?max_age_days=365`),
    enabled: !!ticker,
    staleTime: 60_000,
    refetchInterval: 60_000,
    retry: false,
  })
}

export function useStockNotes(ticker: string | null) {
  return useQuery<{ ticker: string; notes: StockNote[] }>({
    queryKey: ['stock-notes', ticker],
    queryFn: () => fetchJSON(`/api/stock/${encodeURIComponent(ticker!)}/notes`),
    enabled: !!ticker,
    staleTime: 30_000,
    retry: false,
  })
}

export function useRegenStockProfile() {
  const qc = useQueryClient()
  return useMutation<StockProfile, Error, string>({
    mutationFn: (ticker) => fetchJSON<StockProfile>(
      `/api/stock/${encodeURIComponent(ticker)}/profile`,
      { method: 'POST' },
    ),
    onSuccess: (data, ticker) => {
      qc.setQueryData(['stock-profile', ticker], data)
    },
  })
}

export function useUpdateStockStatus() {
  const qc = useQueryClient()
  return useMutation<StockProfile, Error, { ticker: string; status: string; reason: string }>({
    mutationFn: ({ ticker, status, reason }) => fetchJSON<StockProfile>(
      `/api/stock/${encodeURIComponent(ticker)}/status`,
      {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status, reason }),
      },
    ),
    onSuccess: (data, vars) => {
      qc.setQueryData(['stock-profile', vars.ticker], (prev: StockProfile | null) => ({
        ...(prev ?? { ticker: vars.ticker, segments: [], upstream: [], downstream: [],
                     competitors: [], catalysts: [], risks: [], source_citations: [] } as any),
        ...data,
      }))
    },
  })
}

export function useAppendStockNote() {
  const qc = useQueryClient()
  return useMutation<StockNote, Error, {
    ticker: string; body: string; tag?: string
    // Phase W: optional trigger linkage
    trigger_signal_id?: string
    trigger_fact_id?: number
    trigger_thesis_id?: string
  }>({
    mutationFn: ({ ticker, body, tag,
                  trigger_signal_id, trigger_fact_id, trigger_thesis_id }) =>
      fetchJSON<StockNote>(
        `/api/stock/${encodeURIComponent(ticker)}/notes`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            body, tag,
            trigger_signal_id, trigger_fact_id, trigger_thesis_id,
          }),
        },
      ),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ['stock-notes', vars.ticker] })
    },
  })
}

// ── Architecture graph (Settings → Architecture sub-page) ────────
export interface ArchModule {
  id: string
  name: string
  group: string
  groupLabel: string
  color: string
  path: string
  lines: number
  totalClasses: number
  totalFunctions: number
  moduleDoc?: string
  classes?: string[]
}

export interface ArchEdge {
  source: string
  target: string
  synthetic?: boolean
}

export interface ArchitectureData {
  modules: ArchModule[]
  edges: ArchEdge[]
  generated_at: number
  size_bytes: number
}

export function useArchitecture() {
  return useQuery<ArchitectureData>({
    queryKey: ['architecture'],
    queryFn: () => fetchJSON<ArchitectureData>('/api/architecture'),
    staleTime: 60_000,
  })
}

export function useRegenArchitecture() {
  const qc = useQueryClient()
  return useMutation<{ ok: boolean; duration_ms: number }, Error, void>({
    mutationFn: () => fetchJSON('/api/architecture/regenerate', { method: 'POST' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['architecture'] }),
  })
}

// ── SEC-anchored research (Phase B) ─────────────────────────────
// Parallel to useStockProfile (LLM-only, fast). These hooks read
// agent.finance.anchored_research output, which is anchored to real
// SEC 10-K text with verbatim-quote validation.
// Phase W (2026-05-10) Pillar 2 — every anchored fact carries
// quality fields used by the chain panel for PRO/CONTRA forced
// display, opacity-by-confidence, and stale warnings.
export interface AnchoredFactBase {
  fact_id?:           number          // SQLite row id, used for 👎 corrections
  evidence_quote:     string
  source_url:         string
  source_section:     string
  confidence?:        number | null    // 0-1 LLM self-report or proxy
  polarity?:          'pro' | 'contra' | 'neutral' | null
  is_stale?:          boolean          // filing_date > 18mo old
  requires_reextract?: boolean         // user flagged or model bumped
}

export interface AnchoredCompetitor extends AnchoredFactBase {
  name: string
  ticker?: string | null
}
export interface AnchoredRisk extends AnchoredFactBase {
  headline: string
  category: string
  severity_signal?: string | null
}
export interface AnchoredBusinessSummary extends AnchoredFactBase {
  sentence: string
}
export interface AnchoredCustomer extends AnchoredFactBase {
  name: string
  ticker?: string | null
  concentration_pct?: number | null
}
export interface AnchoredSupplier extends AnchoredFactBase {
  name: string
  ticker?: string | null
  criticality?: string | null
}
export interface AnchoredSegment extends AnchoredFactBase {
  name: string
  revenue_pct?: number | null
  period?: string | null
}
export interface AnchoredFacts {
  ticker: string
  facts: {
    competitor?: AnchoredCompetitor[]
    risk?: AnchoredRisk[]
    business_summary?: AnchoredBusinessSummary[]
    customer?: AnchoredCustomer[]
    supplier?: AnchoredSupplier[]
    segment?: AnchoredSegment[]
  }
  meta: {
    source_url: string
    source_filing_date: string
    extracted_at: string
    req_id?: string
  } | null
}

export function useAnchoredFacts(ticker: string | null) {
  return useQuery<AnchoredFacts>({
    queryKey: ['anchored-facts', ticker],
    queryFn: () => fetchJSON<AnchoredFacts>(
      `/api/stock/${encodeURIComponent(ticker!)}/anchored`),
    enabled: !!ticker,
    staleTime: 60_000,
    retry: false,
  })
}


// ── Phase W (2026-05-10) Pillar 2: fact corrections (👎 button) ──
//
// User flags an extracted fact as wrong → server records in
// fact_corrections + sets requires_reextract=1 → UI hides flagged
// fact by default. Per plan §5 Pillar 2 + §2 philosophy: user is
// quality-control authority, not the LLM.

export type FactCorrectionAction = 'mark_wrong' | 'suggest_polarity' | 'suggest_value'

// ── Phase 3 (2026-05-10): Earnings history + scanner health ──
//
// Per plan §5 Pillar 3 + §7 Phase 3.

export interface EarningsHistoryRow {
  earnings_date:  string
  eps_est?:       number | null
  eps_actual?:    number | null
  surprise_pct?:  number | null
}

export interface EarningsHistoryResp {
  ticker:   string
  history:  EarningsHistoryRow[]
  count:    number
}

export function useEarningsHistory(ticker: string | null, limit: number = 8) {
  return useQuery<EarningsHistoryResp>({
    queryKey: ['earnings-history', ticker, limit],
    queryFn:  () => fetchJSON<EarningsHistoryResp>(
      `/api/stock/${encodeURIComponent(ticker ?? '')}/earnings/history?limit=${limit}`),
    enabled:  !!ticker,
    staleTime: 24 * 60 * 60_000,    // earnings_history cached daily
  })
}


export interface ScannerHealthJob {
  name:                   string
  cron:                   string
  expected_interval_min:  number
  last_success_at?:       string | null
  minutes_since_success?: number | null
  is_stale:               boolean
}

export interface ScannerHealthResp {
  jobs:       ScannerHealthJob[]
  n_jobs:     number
  n_stale:    number
  checked_at: string
}

export function useScannerHealth() {
  return useQuery<ScannerHealthResp>({
    queryKey: ['scanner-health'],
    queryFn:  () => fetchJSON<ScannerHealthResp>('/api/scheduler/scanner_health'),
    staleTime: 5 * 60_000,
    refetchInterval: 5 * 60_000,
  })
}


export function useCorrectFact() {
  const qc = useQueryClient()
  return useMutation<
    { ok: boolean; fact_id: number; action: string },
    Error,
    {
      fact_id: number
      ticker: string  // for invalidation
      user_action: FactCorrectionAction
      user_note?: string
    }
  >({
    mutationFn: ({ fact_id, ticker: _t, user_action, user_note }) =>
      fetchJSON(`/api/stock/anchored/facts/${fact_id}/correct`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_action, user_note }),
      }),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ['anchored-facts', vars.ticker] })
    },
  })
}


export interface AnchoredRegenResult {
  ticker: string
  results: Record<string, {
    fact_type?: string
    n_emitted?: number
    n_verified?: number
    n_dropped?: number
    drop_reasons?: string[]
    duration_ms?: number
    error?: string
    status?: number
  }>
}

export function useRegenAnchored() {
  const qc = useQueryClient()
  return useMutation<AnchoredRegenResult, Error, string>({
    mutationFn: (ticker) => fetchJSON<AnchoredRegenResult>(
      `/api/stock/${encodeURIComponent(ticker)}/anchored/regenerate`,
      { method: 'POST' },
    ),
    onSuccess: (_data, ticker) => {
      qc.invalidateQueries({ queryKey: ['anchored-facts', ticker] })
    },
  })
}

// ── Live market overlay (yfinance) ───────────────────────────────
export interface LiveQuote {
  ticker: string
  price: number | null
  market_cap: number | null
  trailing_pe: number | null
  forward_pe: number | null
  fifty_two_week_high: number | null
  fifty_two_week_low: number | null
  day_change_pct: number | null
  year_change_pct: number | null
  name: string | null
  sector: string | null
  industry: string | null
  currency: string | null
  exchange: string | null
  fetched_at: string
}

export interface NextEarnings {
  ticker: string
  next_date: string | null
  days_until?: number | null
  eps_estimate_avg?: number | null
  eps_estimate_low?: number | null
  eps_estimate_high?: number | null
  revenue_estimate_avg?: number | null
  fetched_at?: string
}

export function useLiveQuote(ticker: string | null) {
  return useQuery<LiveQuote>({
    queryKey: ['live-quote', ticker],
    queryFn: () => fetchJSON<LiveQuote>(`/api/stock/${encodeURIComponent(ticker!)}/quote`),
    enabled: !!ticker,
    staleTime: 30_000,
    refetchInterval: 60_000,
    retry: false,
  })
}

export function useNextEarnings(ticker: string | null) {
  return useQuery<NextEarnings>({
    queryKey: ['next-earnings', ticker],
    queryFn: () => fetchJSON<NextEarnings>(`/api/stock/${encodeURIComponent(ticker!)}/earnings`),
    enabled: !!ticker,
    staleTime: 6 * 3600_000,
    retry: false,
  })
}

// ── Per-ticker news (miniflux native search, both title+content) ──
export interface TickerNewsEntry {
  id: number
  title: string
  url: string
  published_at: string
  feed_title: string
  snippet: string
}
export interface TickerNewsResp {
  ticker: string
  count: number
  entries: TickerNewsEntry[]
  fetched_at: string
  fallback_search_url: string
}
export function useTickerNews(ticker: string | null, limit = 20) {
  return useQuery<TickerNewsResp>({
    queryKey: ['ticker-news', ticker, limit],
    queryFn: () => fetchJSON<TickerNewsResp>(
      `/api/news/by_ticker/${encodeURIComponent(ticker!)}?limit=${limit}`),
    enabled: !!ticker,
    staleTime: 5 * 60_000,
    retry: false,
  })
}

// ── Learning library (Phase L) ──────────────────────────────────
export interface LearningCase {
  slug: string
  title: string
  title_zh: string
  source_url?: string | null
  source_name?: string | null
  summary_zh: string
  body?: string | null
  language: string
  themes: string[]
  tickers: string[]
  era: string | null
  difficulty: string | null
  is_classic: boolean
  is_fresh: boolean
  kind?: 'case' | 'memo' | 'book' | 'news'
  availability?: 'public_domain' | 'free_web' | 'paid' | null
  purchase_url?: string | null
  fetched_at: string
  shown_count: number
  last_shown_at: string | null
}

export interface LearningBooksResp {
  total: number
  grouped: {
    public_domain?: LearningCase[]
    free_web?: LearningCase[]
    paid?: LearningCase[]
  }
}

export interface LearningToday {
  fresh: LearningCase[]
  classic: LearningCase | null
  fetched_at: string
}

export interface LearningLibraryResp {
  total: number
  count: number
  cases: LearningCase[]
}

export interface LearningTheme { theme: string; count: number }

export function useLearningToday() {
  return useQuery<LearningToday>({
    queryKey: ['learning-today'],
    queryFn: () => fetchJSON<LearningToday>('/api/learning/today'),
    staleTime: 60_000,
    refetchInterval: 5 * 60_000,
  })
}

export function useLearningLibrary(filters: {
  theme?: string; era?: string; language?: string; q?: string
  limit?: number; offset?: number
} = {}) {
  const qs = new URLSearchParams()
  if (filters.theme)    qs.set('theme', filters.theme)
  if (filters.era)      qs.set('era', filters.era)
  if (filters.language) qs.set('language', filters.language)
  if (filters.q)        qs.set('q', filters.q)
  qs.set('limit', String(filters.limit ?? 50))
  qs.set('offset', String(filters.offset ?? 0))
  return useQuery<LearningLibraryResp>({
    queryKey: ['learning-library', filters],
    queryFn: () => fetchJSON<LearningLibraryResp>(`/api/learning/library?${qs}`),
    staleTime: 60_000,
  })
}

export function useLearningThemes() {
  return useQuery<{ themes: LearningTheme[] }>({
    queryKey: ['learning-themes'],
    queryFn: () => fetchJSON<{ themes: LearningTheme[] }>('/api/learning/themes'),
    staleTime: 5 * 60_000,
  })
}

export function useLearningBooks() {
  return useQuery<LearningBooksResp>({
    queryKey: ['learning-books'],
    queryFn: () => fetchJSON<LearningBooksResp>('/api/learning/books'),
    staleTime: 5 * 60_000,
  })
}

export function useLearningCase(slug: string | null) {
  return useQuery<LearningCase>({
    queryKey: ['learning-case', slug],
    queryFn: () => fetchJSON<LearningCase>(`/api/learning/cases/${encodeURIComponent(slug!)}`),
    enabled: !!slug,
    staleTime: 60_000,
  })
}

export function useRefreshLearning() {
  const qc = useQueryClient()
  return useMutation<{ new_slugs?: string[]; n_accepted?: number }, Error, void>({
    mutationFn: () => fetchJSON('/api/learning/refresh', { method: 'POST' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['learning-today'] })
      qc.invalidateQueries({ queryKey: ['learning-library'] })
      qc.invalidateQueries({ queryKey: ['learning-themes'] })
    },
  })
}

export function useMarkLearningSeen() {
  return useMutation<{ ok: boolean }, Error, string>({
    mutationFn: (slug) => fetchJSON(
      `/api/learning/cases/${encodeURIComponent(slug)}/seen`,
      { method: 'POST' }),
  })
}


// ── Watchlist tiers (hub-and-spoke) ──────────────────────────────
//
// Distinct from the legacy /api/watchlist (JSON file per project).
// These endpoints work directly against the SQLite user_watchlist
// table and add tier/parent_ticker/last_reviewed_at semantics that
// drive the new Watchlist tab + the StockResearchDrawer promote
// buttons. See agent/finance/watchlist_tiers.py for backend.

export type WatchlistTier = 'core' | 'adjacent' | 'watching'

export interface WatchlistEntry {
  ticker:           string
  tier:             WatchlistTier
  parent_ticker:    string | null
  note:             string
  importance:       number
  added_at:         string
  last_reviewed_at: string | null
  days_since_review: number | null
  n_facts:          number
}

export interface WatchlistTiersResp {
  tiers:  Record<WatchlistTier, WatchlistEntry[]>
  totals: Record<WatchlistTier, number>
  fetched_at: string
}

export interface WatchlistSuggestion {
  name:           string
  ticker:         string
  evidence_quote: string
  source_url:     string
}

export interface WatchlistSuggestionsResp {
  ticker: string
  suggestions: {
    competitor: WatchlistSuggestion[]
    customer:   WatchlistSuggestion[]
    supplier:   WatchlistSuggestion[]
  }
}

export interface OutsideRingCandidate {
  ticker:    string
  n_events:  number
  n_sources: number
  n_high:    number
  latest_at: string
}

export interface OutsideRingResp {
  candidates:    OutsideRingCandidate[]
  lookback_days: number
  fetched_at:    string
}

export function useWatchlistTiers() {
  return useQuery<WatchlistTiersResp>({
    queryKey: ['watchlist-tiers'],
    queryFn:  () => fetchJSON<WatchlistTiersResp>('/api/watchlist/tiers'),
    staleTime: 30_000,
  })
}

export function useWatchlistPromote() {
  const qc = useQueryClient()
  return useMutation<
    { ok: boolean; ticker: string; tier: string; parent_ticker: string | null;
      velocity_warning?: string | null },
    Error,
    { ticker: string; tier: WatchlistTier; parent_ticker?: string; note?: string; importance?: number }
  >({
    mutationFn: (a) => fetchJSON(
      `/api/watchlist/promote/${encodeURIComponent(a.ticker)}`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          tier:           a.tier,
          parent_ticker:  a.parent_ticker,
          note:           a.note,
          importance:     a.importance ?? 1,
        }),
      },
    ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['watchlist-tiers'] })
      qc.invalidateQueries({ queryKey: ['watchlist-outside-ring'] })
      // Onion graph depends on tier membership — without this the
      // newly-promoted ticker doesn't render until refetchInterval fires.
      qc.invalidateQueries({ queryKey: ['portfolio-view'] })
    },
  })
}

export function useWatchlistTouch() {
  return useMutation<{ ok: boolean; in_watchlist: boolean }, Error, string>({
    mutationFn: (ticker) => fetchJSON(
      `/api/watchlist/touch/${encodeURIComponent(ticker)}`,
      { method: 'POST' }),
  })
}

export function useWatchlistRemoveTier() {
  const qc = useQueryClient()
  return useMutation<{ ok: boolean }, Error, string>({
    mutationFn: (ticker) => fetchJSON(
      `/api/watchlist/tickers/${encodeURIComponent(ticker)}`,
      { method: 'DELETE' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['watchlist-tiers'] })
      // Removed ticker (and any of its adjacent children's spoke edges)
      // must disappear from the onion immediately, not after polling.
      qc.invalidateQueries({ queryKey: ['portfolio-view'] })
      qc.invalidateQueries({ queryKey: ['watchlist-outside-ring'] })
    },
  })
}

export function useWatchlistSuggestions(ticker: string | null) {
  return useQuery<WatchlistSuggestionsResp>({
    queryKey: ['watchlist-suggestions', ticker],
    queryFn:  () => fetchJSON<WatchlistSuggestionsResp>(
      `/api/watchlist/suggestions/${encodeURIComponent(ticker ?? '')}`),
    enabled:  !!ticker,
    staleTime: 60_000,
  })
}

export function useWatchlistOutsideRing() {
  return useQuery<OutsideRingResp>({
    queryKey: ['watchlist-outside-ring'],
    queryFn:  () => fetchJSON<OutsideRingResp>('/api/watchlist/outside_ring'),
    staleTime: 5 * 60_000,
  })
}


// ── Phase W (2026-05-10): Investment theses ─────────────────────
//
// See plans/2026-05-10_lattice-onion-integration.md §5 Pillar 4.
// Theses are OPTIONAL — backend will accept body without all sections,
// but `missing_sections` is returned as a soft warning. UI surfaces
// it as a non-blocking hint.

export type ThesisStatus = 'active' | 'invalidated' | 'realized' | 'requires_review'

export interface InvestmentThesis {
  thesis_id:               string
  ticker:                  string
  created_at:              string
  body_md:                 string
  supporting_fact_ids:     number[]
  supporting_signal_types: string[]
  status:                  ThesisStatus
  invalidated_at?:         string | null
  invalidated_reason?:     string | null
  last_health_check_at?:   string | null
  sections: {
    bull_case:     string
    bear_case:     string
    exit_triggers: string
    horizon:       string
  }
  missing_sections: string[]   // ['Bear case', ...] if not all required present
  // Phase 4: only present on single-thesis GET (not list)
  exit_triggers_evaluated?: EvaluatedExitTrigger[]
}

export interface EvaluatedExitTrigger {
  raw:             string
  checked_in_md:   boolean
  kind:            'drawdown' | 'earnings_miss' | 'regulatory' | 'manual'
  threshold_pct:   number | null
  text:            string
  fired:           boolean | null   // null = manual, can't auto-eval
  current_value:   number | null
  explanation:     string
}

export interface ExitTriggersResp {
  thesis_id:  string
  ticker:     string
  triggers:   EvaluatedExitTrigger[]
  n_fired:    number
  n_unfired:  number
  n_manual:   number
}

export function useExitTriggers(thesisId: string | null) {
  return useQuery<ExitTriggersResp>({
    queryKey: ['exit-triggers', thesisId],
    queryFn:  () => fetchJSON<ExitTriggersResp>(
      `/api/theses/${encodeURIComponent(thesisId ?? '')}/exit_triggers`),
    enabled:  !!thesisId,
    staleTime: 60_000,
  })
}


// User preferences (Phase 4) — chain panel thresholds.
// NOTE: distinct from UserPrefs (which is regime-related risk prefs).
export interface DecisionPrefs {
  max_position_pct:        number
  max_sector_pct:          number
  benchmark_ticker:        string
  review_window_core:      number
  review_window_adjacent:  number
  review_window_watching:  number
}

export function useDecisionPrefs() {
  return useQuery<{ preferences: DecisionPrefs; fetched_at: string }>({
    queryKey: ['decision-prefs'],
    queryFn:  () => fetchJSON('/api/preferences'),
    staleTime: 5 * 60_000,
  })
}


// ── Phase 5 (2026-05-10): Portfolio onion+chain unified graph ──
//
// Per plan §5 Pillar 1. Frontend renders this as concentric rings
// (onion) with selectively-materialized chain edges.

export interface PortfolioGraphNode {
  id:               string
  // 'held_unwatched' = user owns tax_lots for this ticker but it isn't
  // in any watchlist tier → no research surface; surfaced explicitly so
  // the gap is impossible to miss.
  // 'external' = 10-K relation target NOT in user watchlist; only emitted
  // when include_external_edges=true on the backend.
  tier:             'core' | 'adjacent' | 'watching' | 'outside' | 'held_unwatched' | 'external'
  // 2026-05-19: server-computed visual layer. Decoupled from `tier`
  // (user-facing watchlist categorization) so the picture can re-order
  // by "what actually matters TODAY" without disturbing the user's
  // watchlist classification.
  render_tier?:     'held' | 'buy_candidate' | 'watchlist' | 'outside' | 'external'
  buy_candidate_score?: number
  parent?:          string | null
  // Position overlay — non-null only for tickers user actually owns.
  held_qty?:        number | null
  held_cost?:       number | null
  // Label for external nodes (name from 10-K text when ticker is unresolved).
  external_label?:  string | null
  // Earnings catalyst overlay — days until next earnings if known.
  // Frontend draws a glow ring when ≤5 days (urgent catalyst).
  next_earnings_days?: number | null
  n_facts:          number
  stale_days?:      number | null
  is_stale:         boolean
  fresh_signal_24h: boolean
  n_active_theses:  number
  thesis_status?:   'active' | 'requires_review' | null
  n_unresolved_disagreements?: number
  is_conflicted?:   boolean
  importance?:      number   // 1=normal, 2=priority — border thickness
  // Outside-ring fields (only present when tier='outside')
  n_outside_events?:  number
  n_outside_sources?: number
  n_outside_high?:    number
  outside_latest_at?: string | null
  // Force-graph adds these at runtime
  x?:               number
  y?:               number
}

export interface PortfolioGraphEdge {
  source:  string
  target:  string
  kind:    'spoke' | 'competitor' | 'customer' | 'supplier'
  label:   string
}

export interface PortfolioGraph {
  nodes:        PortfolioGraphNode[]
  edges:        PortfolioGraphEdge[]
  n_nodes:      number
  n_edges:      number
  n_spoke:      number
  n_relations:  number
  fetched_at:   string
  as_of?:       string | null
  is_historical?: boolean
}

// ── Lazy multi-hop chain expansion ──
// Per plan §5 Pillar 1 enhancement #1: when user expands selection
// beyond hop 1, fetch the chain graph including non-watchlist
// entities (e.g. TSMC's risks) so they render as faint placeholders.
export interface ChainNode {
  id:           string   // ticker if available, else `name:<entity-name>`
  label:        string
  ticker:       string | null
  name:         string | null
  in_watchlist: boolean
  tier:         'watchlist' | 'external'
  hop:          number   // 0=origin, 1=direct, 2=neighbors-of
}
export interface ChainEdge {
  source: string
  target: string
  kind:   'competitor' | 'customer' | 'supplier'
  hop:    number
}
export interface ChainResp {
  origin:  string
  hop:     number
  nodes:   ChainNode[]
  edges:   ChainEdge[]
  n_nodes: number
  n_edges: number
}
export function useChain(ticker: string | null, hop: number) {
  return useQuery<ChainResp>({
    queryKey: ['chain', ticker, hop],
    queryFn:  () => fetchJSON(`/api/lattice/chain/${encodeURIComponent(ticker ?? '')}?hop=${hop}`),
    enabled:  !!ticker && hop >= 2,   // hop 1 is already in portfolio_view
    staleTime: 60_000,
  })
}

export interface DisagreementSource {
  scanner:     string
  signal_type: string
  position:    string
  // Enriched with the underlying signal_event (2026-05-16):
  event_id?:   string | null
  source_url?: string | null
  title?:      string | null
  severity?:   string | null
  ts?:         string | null
}
export interface DisagreementItem {
  disagreement_id: string
  headline:        string
  sources:         DisagreementSource[]
  detected_at:     string
}
export function useTickerDisagreements(ticker: string | null) {
  return useQuery<{ ticker: string; items: DisagreementItem[]; n: number }>({
    queryKey: ['ticker-disagreements', ticker],
    queryFn:  () => fetchJSON(`/api/lattice/disagreements/${encodeURIComponent(ticker ?? '')}`),
    enabled:  !!ticker,
    staleTime: 30_000,
  })
}

export function useResolveDisagreement() {
  const qc = useQueryClient()
  return useMutation<{ ok: boolean }, Error, { disagreement_id: string; ticker: string; note?: string }>({
    mutationFn: ({ disagreement_id, note }) => fetchJSON(
      `/api/lattice/disagreements/${encodeURIComponent(disagreement_id)}/resolve${note ? `?note=${encodeURIComponent(note)}` : ''}`,
      { method: 'POST' },
    ),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ['ticker-disagreements', vars.ticker] })
      qc.invalidateQueries({ queryKey: ['portfolio-view'] })
    },
  })
}

export function usePortfolioView(asOf?: string | null, includeExternalEdges?: boolean) {
  const params = new URLSearchParams()
  if (asOf) params.set('as_of', asOf)
  if (includeExternalEdges) params.set('include_external_edges', 'true')
  const qs = params.toString() ? `?${params.toString()}` : ''
  return useQuery<PortfolioGraph>({
    queryKey: ['portfolio-view', asOf ?? 'now', includeExternalEdges ? 'ext' : 'no-ext'],
    queryFn:  () => fetchJSON<PortfolioGraph>(`/api/lattice/portfolio_view${qs}`),
    staleTime: 60_000,
    // Historical snapshots don't change — only poll the live view.
    // 30s matches the cadence of useRecentSignals so the
    // fresh_signal_24h pulse refreshes in roughly the same window
    // scanner events land in the DB.
    refetchInterval: asOf ? false : 30_000,
  })
}

export interface ThesesListResp {
  theses: InvestmentThesis[]
  count:  number
}

export function useTheses(ticker: string | null, status: 'active' | 'all' = 'active') {
  const qs = new URLSearchParams()
  if (ticker) qs.set('ticker', ticker)
  qs.set('status', status)
  return useQuery<ThesesListResp>({
    queryKey: ['theses', ticker ?? 'all', status],
    queryFn:  () => fetchJSON<ThesesListResp>(`/api/theses?${qs}`),
    staleTime: 30_000,
    enabled:  ticker !== null,   // don't fetch the all-theses list unless explicitly asked
  })
}

// ── Priority list (2026-05-16) ─────────────────────────────────
// "What should I look at first today?" — single ranked top-N merged
// across confluence / thesis-review / outside-ring / near-earnings /
// stale-core streams. Held tickers get 2× boost.

export interface PriorityListReason {
  stream: string  // 'confluence' | 'thesis_review' | 'outside' | 'earnings' | 'held_earnings' | 'stale_core' | 'closed_lot'
  text:   string  // human-readable explanation
  score:  number  // this stream's contribution to total — for transparency
}

export interface PriorityListItem {
  ticker:    string
  score:     number
  streams:   string[]                // unique sorted set (for tally badges)
  reasons:   PriorityListReason[]    // paired {stream,text} preserving insert order
  held:      boolean
  is_core:   boolean
  held_cost: number | null
}

export interface PriorityListResp {
  items:               PriorityListItem[]
  n_total_candidates:  number
  computed_at:         string
  weights:             Record<string, number>
}

// ── Smart-money cross-cut per ticker (2026-05-16) ──────────────
// Reuse useRecentSignals with scanner filter to surface smart-money
// events specifically for one ticker. Avoids adding a new endpoint —
// the data is already exposed via /api/regime/signals/recent.

export function useTickerSignalsByScanner(
  ticker: string | null,
  scanner: '13f' | 'insider_form4' | 'stock_act' | 'house_clerk_pdf',
  limit: number = 12,
) {
  return useQuery<{ n: number; events: SignalEvent[] }>({
    queryKey: ['ticker-signals', ticker, scanner, limit],
    queryFn:  () => fetchJSON(
      `/api/regime/signals/recent?ticker=${encodeURIComponent(ticker ?? '')}&scanner=${scanner}&limit=${limit}`),
    enabled:  !!ticker,
    staleTime: 60_000,
  })
}


// ── User decisions (2026-05-16) ────────────────────────────────
// Record + replay investment decisions with basis for audit.

export type DecisionKind = 'hold' | 'trim' | 'add' | 'sell' | 'watch_only' | 'pass'

export interface UserDecision {
  decision_id:     string
  kind:            DecisionKind
  basis_event_ids: string[]
  basis_fact_ids:  number[]
  note:            string
  decided_at:      string
}

export function useDecisions(ticker: string | null) {
  return useQuery<{ ticker: string; items: UserDecision[]; n: number }>({
    queryKey: ['decisions', ticker],
    queryFn:  () => fetchJSON(`/api/stock/${encodeURIComponent(ticker ?? '')}/decisions`),
    enabled:  !!ticker,
    staleTime: 30_000,
  })
}

export interface DecisionOutcome {
  decision_id: string
  ticker:      string
  decided_at:  string
  decision_kind: string
  decision_note: string
  outcome: {
    price_move: {
      start_date: string; start_close: number;
      end_date: string; end_close: number;
      pct: number; days: number;
    } | null
    thesis_changes: Array<{ thesis_id: string; change: string; ts: string }>
    subsequent: Array<{
      scanner: string; type: string; severity: string;
      title: string; source_url: string | null; ts: string;
    }>
    closes: Array<{ close_date: string; realized_pnl: number }>
  }
}

export function useDecisionOutcome(ticker: string | null, decisionId: string | null) {
  return useQuery<DecisionOutcome>({
    queryKey: ['decision-outcome', ticker, decisionId],
    queryFn:  () => fetchJSON(
      `/api/stock/${encodeURIComponent(ticker ?? '')}/decisions/${encodeURIComponent(decisionId ?? '')}/outcome`),
    enabled:  !!ticker && !!decisionId,
    staleTime: 60_000,
  })
}


export function useRecordDecision() {
  const qc = useQueryClient()
  return useMutation<
    { ok: boolean; decision_id: string; decided_at: string },
    Error,
    { ticker: string; kind: DecisionKind; basis_event_ids?: string[]; basis_fact_ids?: number[]; note?: string }
  >({
    mutationFn: ({ ticker, ...body }) => fetchJSON(
      `/api/stock/${encodeURIComponent(ticker)}/decisions`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      },
    ),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ['decisions', vars.ticker] })
    },
  })
}


// ── Delta-since-review (2026-05-16) ────────────────────────────
// "What changed since I last looked at this ticker" — pulls signals,
// thesis state, price move, new facts, closed lots since the anchor
// timestamp (last_reviewed_at or 14d fallback). Powers the banner at
// the top of StockResearchDrawer.

export interface DeltaSinceReview {
  ticker:         string
  anchor_at:      string
  anchor_source:  string   // 'last_reviewed_at' | 'fallback_*'
  days_since:     number
  signals: Array<{
    scanner:  string
    type:     string
    severity: string
    title:    string
    ts:       string
  }>
  scanner_tally:  Record<string, number>
  thesis_changes: Array<{
    thesis_id: string
    status:    string
    change:    'created' | 'invalidated' | 'flagged_review'
    ts:        string
  }>
  price_delta: {
    start_date:  string
    start_close: number
    end_date:    string
    end_close:   number
    pct:         number
  } | null
  new_facts_by_type: Record<string, number>
  closed_lots: Array<{
    close_date:     string
    realized_pnl:   number
    close_quantity: number
  }>
  total_changes: number
}

export function useDeltaSinceReview(ticker: string | null) {
  return useQuery<DeltaSinceReview>({
    queryKey: ['delta-since-review', ticker],
    queryFn:  () => fetchJSON<DeltaSinceReview>(
      `/api/stock/${encodeURIComponent(ticker ?? '')}/delta_since_review`),
    enabled:  !!ticker,
    staleTime: 30_000,
  })
}

export function usePriorityList(limit: number = 5) {
  return useQuery<PriorityListResp>({
    queryKey: ['priority-list', limit],
    queryFn:  () => fetchJSON<PriorityListResp>(
      `/api/dashboard/priority_list?limit=${limit}`),
    staleTime: 60_000,
    refetchInterval: 60_000,  // recompute every minute — composite of 5 sources
  })
}

export function useThesisTemplate() {
  return useQuery<{ body_md: string }>({
    queryKey: ['thesis-template'],
    queryFn:  () => fetchJSON<{ body_md: string }>('/api/theses/template'),
    staleTime: 24 * 60 * 60_000,    // template is static; cache 24h
  })
}

export function useCreateThesis() {
  const qc = useQueryClient()
  return useMutation<
    { thesis_id: string; ticker: string; missing_sections: string[] },
    Error,
    {
      ticker: string
      body_md: string
      supporting_fact_ids?: number[]
      supporting_signal_types?: string[]
    }
  >({
    mutationFn: (a) => fetchJSON('/api/theses', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(a),
    }),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ['theses', vars.ticker] })
      qc.invalidateQueries({ queryKey: ['watchlist-audit', vars.ticker] })
    },
  })
}

export function useUpdateThesis() {
  const qc = useQueryClient()
  return useMutation<
    { ok: boolean; thesis_id: string },
    Error,
    {
      thesis_id: string
      ticker: string  // for query invalidation only, not sent to server
      body_md?: string
      supporting_fact_ids?: number[]
      supporting_signal_types?: string[]
    }
  >({
    mutationFn: ({ thesis_id, ticker: _ticker, ...patch }) =>
      fetchJSON(`/api/theses/${encodeURIComponent(thesis_id)}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(patch),
      }),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ['theses', vars.ticker] })
    },
  })
}

export function useInvalidateThesis() {
  const qc = useQueryClient()
  return useMutation<
    { ok: boolean; thesis_id: string; status: string },
    Error,
    { thesis_id: string; ticker: string; reason: string }
  >({
    mutationFn: ({ thesis_id, reason }) =>
      fetchJSON(`/api/theses/${encodeURIComponent(thesis_id)}/invalidate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason }),
      }),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ['theses', vars.ticker] })
      qc.invalidateQueries({ queryKey: ['watchlist-audit', vars.ticker] })
    },
  })
}


// ── Phase W: Watchlist audit (history of promote/demote/drop/thesis) ──
//
// Powers the chain panel's INCOMING section ("why on radar").

export interface WatchlistAuditEvent {
  audit_id:       string
  action:         'promote' | 'demote' | 'drop' | 'review' | 'note' | 'thesis_create' | 'thesis_invalidate'
  from_tier:      string | null
  to_tier:        string | null
  trigger_kind:   string | null   // 'fact' | 'signal' | 'thesis' | 'manual'
  trigger_ref_id: string | null
  ts:             string
  note:           string | null
}

export interface WatchlistAuditResp {
  ticker: string
  events: WatchlistAuditEvent[]
  count:  number
}

export function useWatchlistAudit(ticker: string | null) {
  return useQuery<WatchlistAuditResp>({
    queryKey: ['watchlist-audit', ticker],
    queryFn:  () => fetchJSON<WatchlistAuditResp>(
      `/api/watchlist/audit/${encodeURIComponent(ticker ?? '')}`),
    enabled:  !!ticker,
    staleTime: 30_000,
  })
}


// ── Phase 1B (2026-05-10): Manual positions + portfolio summary ──
//
// See plans/2026-05-10_lattice-onion-integration.md §5 Pillar 5/6
// + §11 OQ "positions data source = manual UI" (default).

export interface TaxLot {
  lot_id:           number
  account_id:       string
  symbol:           string
  market:           string
  asset_class:      string
  open_date:        string
  open_price:       number
  open_quantity:    number
  open_fees:        number
  close_date?:      string | null
  close_price?:     number | null
  close_quantity?:  number | null
  close_fees?:      number | null
  realized_gain_loss?: number | null
  holding_period_qualified?: 'short_term' | 'long_term' | null
  notes?:           string | null
  created_at:       string
  updated_at:       string
}

export interface EnrichedLot extends TaxLot {
  days_held:         number
  is_long_term:      boolean
  days_until_lt:     number
  lot_cost_basis:    number
  lot_market_value?: number | null
  lot_unrealized?:   number | null
}

export interface PositionByTickerResp {
  ticker: string
  lots:   EnrichedLot[]
  summary: {
    total_quantity:   number
    total_cost:       number
    avg_cost:         number
    current_price?:   number | null
    market_value?:    number | null
    unrealized?:      number | null
    unrealized_pct?:  number | null
    n_lots:           number
  } | null
}

export interface PortfolioSummary {
  n_lots:         number
  n_tickers:      number
  total_value:    number
  total_cost:     number
  unrealized:     number
  unrealized_pct: number
  by_ticker: Array<{
    ticker:        string
    quantity:      number
    cost:          number
    current_price?: number | null
    market_value?: number | null
    unrealized?:   number | null
    unrealized_pct?: number | null
    n_lots:        number
    sector:        string
    weight_pct?:   number | null
  }>
  by_sector: Array<{
    sector: string
    value:  number
    pct:    number
  }>
  benchmark:    string
  vs_benchmark: {
    benchmark:              string
    portfolio_lifetime_pct: number
    windows: Record<string, { benchmark_pct: number | null }>
    note?:                  string
  } | null
  fetched_at:   string
}

export function usePortfolioSummary(benchmark: string = 'SPY') {
  return useQuery<PortfolioSummary>({
    queryKey: ['portfolio-summary', benchmark],
    queryFn:  () => fetchJSON<PortfolioSummary>(`/api/positions/summary?benchmark=${benchmark}`),
    staleTime: 60_000,
    refetchInterval: 5 * 60_000,
  })
}

export function usePositionByTicker(ticker: string | null) {
  return useQuery<PositionByTickerResp>({
    queryKey: ['position-by-ticker', ticker],
    queryFn:  () => fetchJSON<PositionByTickerResp>(
      `/api/positions/by_ticker/${encodeURIComponent(ticker ?? '')}`),
    enabled:  !!ticker,
    staleTime: 60_000,
  })
}

export function usePositionsLots(filter: {
  ticker?: string; account_id?: string; open_only?: boolean
} = {}) {
  const qs = new URLSearchParams()
  if (filter.ticker) qs.set('ticker', filter.ticker)
  if (filter.account_id) qs.set('account_id', filter.account_id)
  qs.set('open_only', String(filter.open_only ?? true))
  return useQuery<{ lots: TaxLot[]; count: number }>({
    queryKey: ['positions-lots', filter],
    queryFn:  () => fetchJSON(`/api/positions/lots?${qs}`),
    staleTime: 30_000,
  })
}

export function useAddLot() {
  const qc = useQueryClient()
  return useMutation<TaxLot, Error, {
    symbol: string
    market?: string
    asset_class?: string
    open_date: string
    open_price: number
    open_quantity: number
    open_fees?: number
    account_id?: string
    notes?: string
  }>({
    mutationFn: (a) => fetchJSON('/api/positions/lots', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(a),
    }),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ['positions-lots'] })
      qc.invalidateQueries({ queryKey: ['portfolio-summary'] })
      qc.invalidateQueries({ queryKey: ['position-by-ticker', vars.symbol] })
    },
  })
}

export function useQuickSetHoldings() {
  const qc = useQueryClient()
  return useMutation<
    { action: string; lot_id?: number; lot?: TaxLot },
    Error,
    { ticker: string; shares: number; cost_basis?: number; notes?: string }
  >({
    mutationFn: (body) => fetchJSON('/api/positions/quick_set', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
    onSuccess: (_d, vars) => {
      qc.invalidateQueries({ queryKey: ['positions-lots'] })
      qc.invalidateQueries({ queryKey: ['portfolio-summary'] })
      qc.invalidateQueries({ queryKey: ['position-by-ticker', vars.ticker] })
    },
  })
}


export function useUpdateLot() {
  const qc = useQueryClient()
  return useMutation<TaxLot, Error, {
    lot_id: number
    open_price?: number
    open_quantity?: number
    open_fees?: number
    open_date?: string
    notes?: string
  }>({
    mutationFn: ({ lot_id, ...patch }) =>
      fetchJSON(`/api/positions/lots/${lot_id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(patch),
      }),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ['positions-lots'] })
      qc.invalidateQueries({ queryKey: ['portfolio-summary'] })
      qc.invalidateQueries({ queryKey: ['position-by-ticker', data.symbol] })
    },
  })
}

export function useDeleteLot() {
  const qc = useQueryClient()
  return useMutation<{ ok: boolean }, Error, { lot_id: number; ticker: string }>({
    mutationFn: ({ lot_id }) =>
      fetchJSON(`/api/positions/lots/${lot_id}`, { method: 'DELETE' }),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ['positions-lots'] })
      qc.invalidateQueries({ queryKey: ['portfolio-summary'] })
      qc.invalidateQueries({ queryKey: ['position-by-ticker', vars.ticker] })
      // Onion node carries position weight (held_qty / held_cost). Close
      // or delete must update the size+overlay immediately.
      qc.invalidateQueries({ queryKey: ['portfolio-view'] })
    },
  })
}

export function useCloseLot() {
  const qc = useQueryClient()
  return useMutation<TaxLot, Error, {
    lot_id: number
    ticker: string  // for invalidation
    close_date: string
    close_price: number
    close_quantity?: number
    close_fees?: number
  }>({
    mutationFn: ({ lot_id, ticker: _t, ...body }) =>
      fetchJSON(`/api/positions/lots/${lot_id}/close`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ['positions-lots'] })
      qc.invalidateQueries({ queryKey: ['portfolio-summary'] })
      qc.invalidateQueries({ queryKey: ['position-by-ticker', vars.ticker] })
      // Onion node carries position weight (held_qty / held_cost). Close
      // or delete must update the size+overlay immediately.
      qc.invalidateQueries({ queryKey: ['portfolio-view'] })
    },
  })
}

// ── Short-term Trading Desk ───────────────────────────────
// Separate from the long-term smart-money stack. TPS + setup CRUD +
// NL→quant distillation + backtest + paper-parallel scan.

export interface TradingPolicy {
  version: string
  north_star?: string
  identity?: string
  red_lines?: string[]
  risk_rules?: Record<string, unknown>
  entry_protocol?: string
  exit_protocol?: string
  kill_switch?: string
  execution_rules?: string
  validation_rules?: string
  tax_note?: string
  review_cadence?: string
  last_reviewed_at?: string
  change_note?: string
}

export interface QuantCondition { left: string; op: string; right: string | number; rmult?: number; note?: string }
export interface EntryDetailRow { left: string; op: string; right: string; lval: number | null; rval: number | null; note?: string }
export interface QuantSpec {
  timeframe?: string
  lookback?: string
  direction?: string
  entry?: { logic?: string; conditions?: QuantCondition[] }
  exit?: { stop?: { type: string; value: number }; target?: { type: string; value: number }; time_stop_bars?: number }
  sizing?: { risk_pct?: number; max_pos_pct?: number }
}
export interface BacktestStats {
  n_trades: number; win_rate: number | null; avg_R: number | null
  total_return_pct: number; max_drawdown_pct: number; avg_bars_held: number | null
  best_R?: number; worst_R?: number; assumptions?: string; symbol?: string
  buy_hold_pct?: number; beats_buy_hold?: boolean
}
export interface BacktestTrade {
  entry_date: string; entry_px: number; exit_date: string; exit_px: number
  reason: string; bars_held: number; return_pct: number; R: number
  entry_detail?: EntryDetailRow[]
}
export interface Robustness { verdict: 'robust' | 'weak' | 'overfit' | 'unknown'; note: string }
export interface BacktestResult {
  symbol?: string; timeframe?: string; n_bars?: number
  trades?: BacktestTrade[]; stats?: BacktestStats; error?: string
  is_stats?: BacktestStats; oos_stats?: BacktestStats; robustness?: Robustness; oos_cutoff?: string
}
export interface TradingSetup {
  setup_id: string; version: number; name: string
  status: 'idea' | 'paper' | 'live' | 'retired'
  nl_description?: string
  quant_spec?: QuantSpec
  backtest_stats?: BacktestStats
  score?: { score: number; grade: string; expectancy_R: number; win_rate: number; n_trades: number; confidence: number; robustness?: string; overfit?: boolean } | null
  change_note?: string; created_at?: string; updated_at?: string
}

export function useTradingPolicy() {
  return useQuery({
    queryKey: ['trading-policy'],
    queryFn: () => fetchJSON<TradingPolicy>('/api/trading/policy'),
    staleTime: 60_000,
  })
}

export function useUpdateTradingPolicy() {
  const qc = useQueryClient()
  return useMutation<TradingPolicy, Error, Partial<TradingPolicy>>({
    mutationFn: (body) => fetchJSON('/api/trading/policy', {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['trading-policy'] }),
  })
}

export function useTradingSetups() {
  return useQuery({
    queryKey: ['trading-setups'],
    queryFn: () => fetchJSON<{ setups: TradingSetup[]; n: number }>('/api/trading/setups'),
    staleTime: 30_000,
  })
}

export function useSaveTradingSetup() {
  const qc = useQueryClient()
  return useMutation<TradingSetup, Error, { setup_id?: string; body: Partial<TradingSetup> }>({
    mutationFn: ({ setup_id, body }) => fetchJSON(
      setup_id ? `/api/trading/setups/${encodeURIComponent(setup_id)}` : '/api/trading/setups',
      { method: setup_id ? 'PUT' : 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['trading-setups'] }),
  })
}

export function useDeleteTradingSetup() {
  const qc = useQueryClient()
  return useMutation<{ ok: boolean }, Error, string>({
    mutationFn: (setup_id) => fetchJSON(`/api/trading/setups/${encodeURIComponent(setup_id)}`,
      { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['trading-setups'] }),
  })
}

export function useDistillSetup() {
  return useMutation<{ ok: boolean; quant_spec: QuantSpec }, Error, { nl_description: string; current_spec?: QuantSpec }>({
    mutationFn: (body) => fetchJSON('/api/trading/setups/distill', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  })
}

export function useBacktestSetup() {
  const qc = useQueryClient()
  return useMutation<BacktestResult, Error, { setup_id: string; symbol: string; quant_spec?: QuantSpec }>({
    mutationFn: ({ setup_id, symbol, quant_spec }) => fetchJSON(
      `/api/trading/setups/${encodeURIComponent(setup_id)}/backtest`,
      { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol, quant_spec }) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['trading-setups'] }),
  })
}

export function useBacktestAdhoc() {
  return useMutation<BacktestResult, Error, { symbol: string; quant_spec: QuantSpec }>({
    mutationFn: (body) => fetchJSON('/api/trading/backtest_adhoc', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  })
}

export interface TradingChartPoint { date: string; close: number }
export interface TradingChartData {
  symbol?: string; series?: TradingChartPoint[]; trades?: BacktestTrade[]
  stats?: BacktestStats; error?: string
  is_stats?: BacktestStats; oos_stats?: BacktestStats; robustness?: Robustness; oos_cutoff?: string
}
export interface PortfolioRisk {
  symbols: string[]; matrix: { symbol: string; row: (number | null)[] }[]
  warnings: { a: string; b: string; corr: number }[]; threshold: number; n_positions: number
}
export function useSetupChart() {
  return useMutation<TradingChartData, Error, { setup_id: string; symbol: string }>({
    mutationFn: ({ setup_id, symbol }) => fetchJSON(
      `/api/trading/setups/${encodeURIComponent(setup_id)}/chart`,
      { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol }) }),
  })
}

// Query variant — cacheable + auto-runs when enabled, so the verify view
// (curve + stats + trade detail) survives a page reload (driven by a
// localStorage-remembered symbol).
export function useSetupChartQuery(setupId: string, symbol: string, enabled: boolean) {
  return useQuery({
    queryKey: ['setup-chart', setupId, symbol],
    queryFn: () => fetchJSON<TradingChartData>(
      `/api/trading/setups/${encodeURIComponent(setupId)}/chart`,
      { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol }) }),
    enabled: enabled && !!symbol,
    staleTime: 5 * 60_000,
    retry: false,
  })
}

// Combos — modular strategy combinations + shared-capital portfolio backtest.
export interface ComboMember { setup_id: string; weight?: number }
export interface TradingCombo {
  combo_id: string; name: string; members?: ComboMember[]; symbols?: string[]
  status: 'idea' | 'paper' | 'live' | 'retired'; stats?: BacktestStats
}
export interface ComboBacktest {
  symbols?: string[]; n_members?: number; stats?: BacktestStats; error?: string
  equity_curve?: { date: string; equity: number }[]
  contributions?: { setup_id: string; name: string; n: number; win_rate: number | null; avg_R: number | null }[]
  capital?: number
}
export function useCombos() {
  return useQuery({ queryKey: ['trading-combos'], queryFn: () => fetchJSON<{ combos: TradingCombo[]; n: number }>('/api/trading/combos'), staleTime: 30_000 })
}
export function useSaveCombo() {
  const qc = useQueryClient()
  return useMutation<TradingCombo, Error, { combo_id?: string; body: Partial<TradingCombo> }>({
    mutationFn: ({ combo_id, body }) => fetchJSON(
      combo_id ? `/api/trading/combos/${encodeURIComponent(combo_id)}` : '/api/trading/combos',
      { method: combo_id ? 'PUT' : 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['trading-combos'] }),
  })
}
export function useDeleteCombo() {
  const qc = useQueryClient()
  return useMutation<{ ok: boolean }, Error, string>({
    mutationFn: (id) => fetchJSON(`/api/trading/combos/${encodeURIComponent(id)}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['trading-combos'] }),
  })
}
export function useBacktestCombo() {
  const qc = useQueryClient()
  return useMutation<ComboBacktest, Error, { combo_id: string; lookback?: string }>({
    mutationFn: ({ combo_id, lookback }) => fetchJSON(
      `/api/trading/combos/${encodeURIComponent(combo_id)}/backtest?lookback=${encodeURIComponent(lookback || '3y')}`,
      { method: 'POST' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['trading-combos'] }),
  })
}

// Strategy comparison — run every setup on the same symbol/period.
export interface CompareRow { setup_id: string; name: string; status: string; stats: BacktestStats; score: { score: number; grade: string } | null }
export function useCompareSetups() {
  return useMutation<{ symbol: string; lookback: string; rows: CompareRow[] }, Error, { symbol: string; lookback: string }>({
    mutationFn: ({ symbol, lookback }) => fetchJSON(
      `/api/trading/compare?symbol=${encodeURIComponent(symbol)}&lookback=${encodeURIComponent(lookback)}`,
      { method: 'POST' }),
  })
}

export interface ScanTrigger { setup_id: string; setup_name: string; symbol: string; as_of: string; entry_px: number }
export function useScanSetups() {
  return useMutation<{ n_triggers: number; triggers: ScanTrigger[]; scanned: number }, Error, void>({
    mutationFn: () => fetchJSON('/api/trading/scan', { method: 'POST' }),
  })
}

// ── Trading state / emergency brakes / automated scan ──
export interface TradingState {
  global_halt: number; halt_reason?: string | null; halted_by?: string | null
  auto_trade: number; ibkr_route?: number; venue?: string; allow_live?: number; trading_budget_usd?: number; updated_at?: string
}
export interface SetupScore { score: number; grade: string; expectancy_R: number; win_rate: number; n_trades: number; confidence: number }
export interface ScanTradeExec extends ScanTrigger { stop_px?: number; qty?: number; entry_status?: string; stop_placed?: boolean; skipped?: string }
export interface MarketRegime { regime: 'risk_on' | 'risk_off' | 'unknown'; spy?: number; spy_sma200?: number; note: string }
export interface ScanTradeResult {
  halted: boolean
  kill_switch: { breached: boolean; reason?: string | null; total_pnl_pct: number; consecutive_losses: number; dd_limit_pct: number; consec_limit: number }
  regime?: MarketRegime; risk_off?: boolean
  n_triggers: number; triggers: ScanTradeExec[]
  n_executed: number; executed: ScanTradeExec[]; scanned: number
}
export interface ReviewResult {
  retired: { setup_id: string; name: string; reason: string }[]
  suggestions: { setup_id: string; name: string; tips: string[] }[]
  n_retired: number; n_suggestions: number
}
export function useReviewSetups() {
  const qc = useQueryClient()
  return useMutation<ReviewResult, Error, void>({
    mutationFn: () => fetchJSON('/api/trading/review?auto_retire=true', { method: 'POST' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['trading-setups'] }),
  })
}
export function useRegime() {
  return useQuery({ queryKey: ['trading-regime'], queryFn: () => fetchJSON<MarketRegime>('/api/trading/regime'), staleTime: 5 * 60_000 })
}

// Earnings calendar guard
export interface EarningsRow { symbol: string; next_earnings_date?: string | null; days_until?: number | null }
export function useTradingEarnings(symbols: string) {
  return useQuery({
    queryKey: ['trading-earnings', symbols],
    queryFn: () => fetchJSON<{ earnings: Record<string, EarningsRow>; upcoming: EarningsRow[]; guard_days: number }>(
      `/api/trading/earnings?symbols=${encodeURIComponent(symbols)}`, { method: 'POST' }),
    enabled: !!symbols, staleTime: 30 * 60_000, retry: false,
  })
}

// Trade journal + weekly review
export interface JournalEntry {
  journal_id: string; symbol?: string; setup_name?: string; status: 'open' | 'closed'
  thesis?: string; catalyst?: string; emotion?: string; followed_plan?: number | null
  entry_date?: string; entry_px?: number; stop_px?: number; target_px?: number
  exit_date?: string; exit_px?: number; exit_reason?: string; return_pct?: number; r_multiple?: number; lesson?: string
}
export interface WeeklyReview {
  days: number; n: number; win_rate?: number; avg_R?: number | null; avg_return_pct?: number
  followed_plan_pct?: number; by_catalyst?: { catalyst: string; n: number; win_rate: number }[]; note?: string
}
export function useJournal() {
  return useQuery({ queryKey: ['trade-journal'], queryFn: () => fetchJSON<{ entries: JournalEntry[]; n: number }>('/api/trading/journal'), staleTime: 10_000 })
}
export function useSaveJournal() {
  const qc = useQueryClient()
  return useMutation<JournalEntry, Error, Partial<JournalEntry>>({
    mutationFn: (body) => fetchJSON('/api/trading/journal', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['trade-journal'] }); qc.invalidateQueries({ queryKey: ['journal-weekly'] }) },
  })
}
export function useDeleteJournal() {
  const qc = useQueryClient()
  return useMutation<{ ok: boolean }, Error, string>({
    mutationFn: (id) => fetchJSON(`/api/trading/journal/${encodeURIComponent(id)}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['trade-journal'] }),
  })
}
export function useSyncJournal(projectId: string) {
  const qc = useQueryClient()
  return useMutation<{ closed: number }, Error, void>({
    mutationFn: () => fetchJSON(`/api/trading/journal/sync?project_id=${encodeURIComponent(projectId)}`, { method: 'POST' }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['trade-journal'] }); qc.invalidateQueries({ queryKey: ['journal-weekly'] }) },
  })
}
export function useJournalWeekly(days = 7) {
  return useQuery({ queryKey: ['journal-weekly', days], queryFn: () => fetchJSON<WeeklyReview>(`/api/trading/journal/weekly?days=${days}`), staleTime: 10_000 })
}

export interface CockpitPosition { symbol: string; qty: number; entry: number; current: number | null; stop: number | null; target: number | null; R: number | null; unrealized_pct: number | null; days: number | null }
export interface Cockpit {
  regime: MarketRegime; halted: boolean; auto_armed: boolean
  venue?: string; ibkr_connected?: boolean; account?: string | null; is_paper?: boolean; net_liquidation?: number | null; ibkr_error?: string | null
  positions: CockpitPosition[]; n_positions: number
  earnings_soon: EarningsRow[]; held_into_earnings: EarningsRow[]; open_journal: number
}
export const postVenue = (venue: 'sim' | 'ibkr') => fetchJSON<TradingState>(`/api/trading/venue?venue=${venue}`, { method: 'POST' })

// Bucket ① — long-term core holdings risk monitor
export interface CoreHolding { ticker: string; qty: number; price: number | null; value: number | null; weight_pct: number | null; unrealized_pct: number | null; sector?: string }
export interface CoreRisk {
  total_value: number; total_cost?: number; unrealized?: number; unrealized_pct?: number; n_tickers: number
  holdings: CoreHolding[]
  by_sector?: Array<{ sector: string; value: number; pct: number }>
  regime?: MarketRegime
  concentration?: { largest: { ticker: string; pct: number }; top3_pct: number; hhi: number }
  risk?: { ann_vol_pct?: number; max_drawdown_1y_pct?: number; beta_qqq?: number; beta_spy?: number; error?: string }
  correlation_warnings?: Array<{ a: string; b: string; corr: number }>
  correlation_threshold?: number
  note?: string
}
export function useCoreRisk() {
  return useQuery({
    queryKey: ['core-risk'],
    queryFn: () => fetchJSON<CoreRisk>('/api/portfolio/core_risk'),
    staleTime: 60_000,
    retry: false,
  })
}
export interface HedgeScenario { qqq_move_pct: number; port_loss_unhedged: number; put_net_payoff: number; port_loss_hedged: number }
export interface HedgePlan {
  total_value: number; realized_beta_qqq?: number | null; hedge_beta?: number; coverage?: number; otm_pct?: number
  qqq_spot?: number; strike?: number; expiry?: string; premium_per_share?: number; premium_per_contract?: number; iv_pct?: number
  contracts?: number; cost?: number; cost_pct?: number; hedged_notional?: number
  scenarios?: HedgeScenario[]
  rule_status?: { regime?: string; regime_risk_off?: boolean; max_drawdown_1y_pct?: number | null; triggered?: boolean; reason?: string }
  order_ticket?: string; caveats?: string[]; note?: string; error?: string
}
export const fetchHedgePlan = (coverage: number, otm_pct: number) =>
  fetchJSON<HedgePlan>(`/api/portfolio/hedge_plan?coverage=${coverage}&otm_pct=${otm_pct}`)
export interface HedgeExecResult { ok: boolean; needs_confirm?: boolean; message?: string; error?: string; paper?: boolean; account?: string; result?: { ok: boolean; error?: string; status?: string; order_id?: number } }
export const postHedgeExecute = (coverage: number, otm_pct: number, confirm: boolean) =>
  fetchJSON<HedgeExecResult>(`/api/portfolio/hedge_execute?coverage=${coverage}&otm_pct=${otm_pct}&confirm=${confirm}`, { method: 'POST' })
export const postBudget = (usd: number) => fetchJSON<TradingState>(`/api/trading/budget?usd=${usd}`, { method: 'POST' })
// IBKR — read paths are readonly; the ONE order path (place_paper_bracket) is
// DU-account-guarded so it can only ever touch a paper (DU…) account.
// Button-triggered (each call opens a socket to the gateway).
export interface IbkrStatus { connected: boolean; readonly: boolean; error?: string; lib_missing?: boolean; accounts?: string[]; server_version?: number; is_paper?: boolean; order_enabled?: boolean; config?: { host: string; port: number; client_id: number } }
export interface IbkrAccount { connected: boolean; readonly: boolean; error?: string; values?: Record<string, string> }
export interface IbkrPositions { connected: boolean; readonly: boolean; error?: string; positions?: Array<{ symbol: string; sec_type: string; position: number; avg_cost: number; account: string }> }
export interface IbkrOrderRow { order_id: number; symbol: string; action: string; qty: number; type: string; limit?: number | null; stop?: number | null; status: string; filled: number; remaining: number; oca?: string }
export interface IbkrOpenOrders { connected: boolean; error?: string; orders?: IbkrOrderRow[] }
export interface IbkrVerify { verdict: string; sent_ok?: boolean; independent_confirms?: number; total_confirming_sources?: number; checks?: Record<string, { ok: boolean; n: number; err?: string }> }
export interface IbkrOrderResult { ok: boolean; error?: string; account?: string; orders?: Array<{ order_id: number; kind: string; action: string; qty: number; status: string }>; verify?: IbkrVerify }
export const fetchIbkrStatus = () => fetchJSON<IbkrStatus>('/api/trading/ibkr/status')
export const fetchIbkrAccount = () => fetchJSON<IbkrAccount>('/api/trading/ibkr/account')
export const fetchIbkrPositions = () => fetchJSON<IbkrPositions>('/api/trading/ibkr/positions')
export const fetchIbkrOpenOrders = () => fetchJSON<IbkrOpenOrders>('/api/trading/ibkr/open_orders')
export const postIbkrRoute = (on: boolean) => fetchJSON<{ ibkr_route?: number }>(`/api/trading/ibkr/route?on=${on}`, { method: 'POST' })
export const postIbkrTestOrder = (symbol: string, quantity: number, limitPrice?: number) =>
  fetchJSON<IbkrOrderResult>(`/api/trading/ibkr/test_order?symbol=${encodeURIComponent(symbol)}&quantity=${quantity}${limitPrice != null ? `&limit_price=${limitPrice}` : ''}`, { method: 'POST' })
export const postIbkrCancelAll = () => fetchJSON<{ ok: boolean; error?: string; cancelled?: number }>('/api/trading/ibkr/cancel_all', { method: 'POST' })
export interface IbkrLogRow { id: number; ts: string; kind: string; account?: string; symbol?: string; action?: string; qty?: number; order_type?: string; price?: number; status?: string; source?: string; detail?: string }
export interface IbkrLog { n: number; rows: IbkrLogRow[] }
export const postIbkrSnapshot = () => fetchJSON<{ ok?: boolean; error?: string; ts?: string; captured?: Record<string, number> }>('/api/trading/ibkr/snapshot', { method: 'POST' })
export const fetchIbkrLog = (p: { symbol?: string; kind?: string; limit?: number } = {}) => {
  const q = new URLSearchParams()
  if (p.symbol) q.set('symbol', p.symbol)
  if (p.kind) q.set('kind', p.kind)
  q.set('limit', String(p.limit ?? 200))
  return fetchJSON<IbkrLog>(`/api/trading/ibkr/log?${q.toString()}`)
}
// Flex Web Service backstop — token is NEVER returned by the API.
export interface IbkrFlexStatus { configured: boolean; query_id?: string | null }
export const fetchIbkrFlexConfig = () => fetchJSON<IbkrFlexStatus>('/api/trading/ibkr/flex/config')
export const postIbkrFlexConfig = (token: string, query_id: string) =>
  fetchJSON<IbkrFlexStatus>('/api/trading/ibkr/flex/config', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ token, query_id }) })
export const postIbkrFlexSync = () =>
  fetchJSON<{ ok: boolean; error?: string; account?: string; archived?: Record<string, number> }>('/api/trading/ibkr/flex/sync', { method: 'POST' })
export interface IbkrReconcile { ok: boolean; error?: string; summary?: { flex_trades: number; local_fills: number; matched: number; flex_only: number; local_only: number; complete: boolean }; flex_only?: Array<{ symbol: string; side: string; qty: number; price: number; count: number }>; local_only?: Array<{ symbol: string; side: string; qty: number; price: number; count: number }> }
export const postIbkrReconcile = () => fetchJSON<IbkrReconcile>('/api/trading/ibkr/flex/reconcile?sync=true', { method: 'POST' })

export function useCockpit(projectId: string) {
  return useQuery({
    queryKey: ['trading-cockpit', projectId],
    queryFn: () => fetchJSON<Cockpit>(`/api/trading/cockpit?project_id=${encodeURIComponent(projectId)}`, { method: 'POST' }),
    staleTime: 30_000,
  })
}

export function useSetAutoTrade() {
  const qc = useQueryClient()
  return useMutation<TradingState, Error, boolean>({
    mutationFn: (on) => fetchJSON(`/api/trading/auto_trade?on=${on}`, { method: 'POST' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['trading-state'] }),
  })
}

export interface OptimizeRow {
  size: number; is_single: boolean; members: string[]; member_ids: string[]
  n_trades: number; win_rate: number | null; total_return_pct: number; max_drawdown_pct: number
  avg_R: number | null; score: number
}
export interface OptimizeResult {
  symbols?: string[]; lookback?: string; n_tested?: number; rows: OptimizeRow[]
  best_overall?: OptimizeRow; best_single?: OptimizeRow; candidates?: string[]; error?: string
}
export function useOptimizeCombos() {
  return useMutation<OptimizeResult, Error, { symbols: string; max_size: number; lookback: string }>({
    mutationFn: ({ symbols, max_size, lookback }) => fetchJSON(
      `/api/trading/optimize?symbols=${encodeURIComponent(symbols)}&max_size=${max_size}&lookback=${encodeURIComponent(lookback)}`,
      { method: 'POST' }),
  })
}
export interface OptimizeSubset { member_ids: string[]; names: string[]; size: number; is_single: boolean }
export async function fetchOptimizePlan(symbols: string, maxSize: number): Promise<{ subsets: OptimizeSubset[]; n: number; candidates: string[]; error?: string }> {
  return fetchJSON(`/api/trading/optimize/plan?symbols=${encodeURIComponent(symbols)}&max_size=${maxSize}`, { method: 'POST' })
}
export async function fetchComboAdhoc(member_ids: string[], symbols: string[], lookback: string): Promise<ComboBacktest & { start_date?: string; end_date?: string; n_bars?: number }> {
  return fetchJSON('/api/trading/backtest_combo_adhoc', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ member_ids, symbols, lookback }),
  })
}

export function useSaveOptimizedCombo() {
  const qc = useQueryClient()
  return useMutation<TradingCombo, Error, { member_ids: string; symbols: string; name: string }>({
    mutationFn: ({ member_ids, symbols, name }) => fetchJSON(
      `/api/trading/optimize/save?member_ids=${encodeURIComponent(member_ids)}&symbols=${encodeURIComponent(symbols)}&name=${encodeURIComponent(name)}`,
      { method: 'POST' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['trading-combos'] }),
  })
}

export function useTradingState() {
  return useQuery({
    queryKey: ['trading-state'],
    queryFn: () => fetchJSON<TradingState>('/api/trading/state'),
    refetchInterval: 15_000,
  })
}

export function useSetHalt() {
  const qc = useQueryClient()
  return useMutation<TradingState, Error, { on: boolean; reason?: string }>({
    mutationFn: ({ on, reason }) => fetchJSON(
      `/api/trading/halt?on=${on}${reason ? `&reason=${encodeURIComponent(reason)}` : ''}`,
      { method: 'POST' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['trading-state'] }),
  })
}

export function useFlatten(projectId: string) {
  const qc = useQueryClient()
  return useMutation<{ flattened: number; positions: unknown[] }, Error, void>({
    mutationFn: () => fetchJSON(`/api/trading/flatten?project_id=${encodeURIComponent(projectId)}`, { method: 'POST' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['paper-positions'] })
      qc.invalidateQueries({ queryKey: ['paper-account'] })
    },
  })
}

export function useRefreshPositions(projectId: string) {
  const qc = useQueryClient()
  return useMutation<{ updated: { symbol: string; price: number }[]; n: number; orders_settled: number }, Error, void>({
    mutationFn: () => fetchJSON(`/api/trading/refresh_positions?project_id=${encodeURIComponent(projectId)}`, { method: 'POST' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['paper-positions'] })
      qc.invalidateQueries({ queryKey: ['paper-account'] })
      qc.invalidateQueries({ queryKey: ['paper-trades'] })
    },
  })
}

export function usePortfolioRisk(projectId: string) {
  return useMutation<PortfolioRisk, Error, void>({
    mutationFn: () => fetchJSON(`/api/trading/portfolio_risk?project_id=${encodeURIComponent(projectId)}`, { method: 'POST' }),
  })
}

export function useScanTrade(projectId: string) {
  const qc = useQueryClient()
  return useMutation<ScanTradeResult, Error, void>({
    mutationFn: () => fetchJSON(`/api/trading/scan_trade?project_id=${encodeURIComponent(projectId)}`, { method: 'POST' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['paper-positions'] })
      qc.invalidateQueries({ queryKey: ['paper-account'] })
      qc.invalidateQueries({ queryKey: ['trading-state'] })
    },
  })
}
