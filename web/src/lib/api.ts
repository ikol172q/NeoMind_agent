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
export function streamChat(
  project_id: string,
  message: string,
  cb: StreamCallbacks,
): AbortController {
  const ac = new AbortController()
  const qs = new URLSearchParams({ project_id, message })

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
