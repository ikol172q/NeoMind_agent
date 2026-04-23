/**
 * API client + TanStack Query hooks for the NeoMind backend.
 *
 * All calls go to same-origin (`/api/*`, `/openbb/*`, `/audit`)
 * so in dev they're proxied to 127.0.0.1:8001 via Vite, and in
 * prod they hit the same FastAPI that serves this bundle.
 */
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'

async function fetchJSON<T = unknown>(url: string, init?: RequestInit): Promise<T> {
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

export interface LatticeCall {
  id: string
  claim: string
  grounds: string[]           // theme_ids
  warrant: string
  qualifier: string
  rebuttal: string
  confidence: 'high' | 'medium' | 'low'
  time_horizon: 'intraday' | 'days' | 'weeks' | 'quarter'
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
}

export function useLatticeCalls(project_id: string) {
  return useQuery({
    queryKey: ['lattice_calls', project_id],
    queryFn: () => fetchJSON<LatticePayload>(
      `/api/lattice/calls?project_id=${encodeURIComponent(project_id)}`,
    ),
    enabled: !!project_id,
    staleTime: 10 * 60_000,     // server L3 cache is 15min; stay fresh for 10
    refetchInterval: 15 * 60_000,
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

export function useLatticeGraph(project_id: string) {
  return useQuery({
    queryKey: ['lattice_graph', project_id],
    queryFn: () => fetchJSON<LatticeGraphPayload>(
      `/api/lattice/graph?project_id=${encodeURIComponent(project_id)}`,
    ),
    enabled: !!project_id,
    staleTime: 10 * 60_000,
    refetchInterval: 15 * 60_000,
    refetchOnWindowFocus: false,
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

export async function setLatticeLanguage(lang: 'en' | 'zh-CN-mixed' | 'clear') {
  const r = await fetch(
    `/api/lattice/language?lang=${encodeURIComponent(lang)}`,
    { method: 'POST' },
  )
  if (!r.ok) throw new Error(`set language failed: ${r.status}`)
  return (await r.json()) as Omit<LatticeLanguageState, 'available'>
}


export function useLatticeTrace(project_id: string, node_id: string | null) {
  return useQuery({
    queryKey: ['lattice_trace', project_id, node_id],
    queryFn: () => fetchJSON<LatticeTracePayload>(
      `/api/lattice/trace/${encodeURIComponent(node_id!)}?project_id=${encodeURIComponent(project_id)}`,
    ),
    enabled: !!project_id && !!node_id,
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
