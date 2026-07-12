/**
 * Cognition Map API hooks (feature-scoped; reuses fetchJSON from api.ts).
 * Backend: agent/finance/cognition_map_router.py  (/api/map/*)
 */
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { fetchJSON } from './api'

export type ProvState = 'unverified' | 'partially_verified' | 'verified' | 'rawstore_grounded'

// Provenance → colour, used everywhere a node/edge is drawn (req7 at-a-glance).
export const PROV_COLOR: Record<ProvState, string> = {
  unverified:        '#ef4444', // red — candidate / untrusted
  partially_verified:'#f59e0b', // amber — some claims confirmed
  verified:          '#22c55e', // green — auditor confirmed
  rawstore_grounded: '#3b82f6', // blue — every source is raw://sha256 (strongest)
}
export const PROV_LABEL: Record<ProvState, string> = {
  unverified: '未验证', partially_verified: '部分验证',
  verified: '已验证', rawstore_grounded: '源已锚定',
}
export const TRUSTED_STATES: ProvState[] = ['verified', 'rawstore_grounded']

export interface MapNodeRow {
  id: string; title: string; type: string
  prov_state: ProvState; confidence: string; origin: string
  created: string; last_checked: string; updated_at?: string
}
export interface MapEdgeRow {
  source_id: string; target_id: string; rel: string
  weight: number; state: ProvState; note?: string | null
}
export interface MapGraph { project_id: string; lens: string | null; nodes: MapNodeRow[]; edges: MapEdgeRow[] }

export interface MapMeta {
  node_types: string[]
  edge_types: Record<string, string>
  lenses: Record<string, string[]>
  confidence_levels: string[]
  provenance_states: ProvState[]
  trusted_states: ProvState[]
}

export interface NodeDetail extends MapNodeRow {
  body: string
  sources: string[]
  edges: Array<{ target: string; rel: string; weight: number; state: ProvState; note?: string | null }>
  provenance: { state: ProvState; source: string }
  dimensions: Record<string, unknown>
}

export function useMapMeta() {
  return useQuery({
    queryKey: ['map-meta'],
    queryFn: () => fetchJSON<MapMeta>('/api/map/meta'),
    staleTime: 300_000,
  })
}

export function useMapGraph(projectId: string, lens: string | null) {
  return useQuery({
    queryKey: ['map-graph', projectId, lens],
    queryFn: () => fetchJSON<MapGraph>(
      `/api/map/graph?project_id=${encodeURIComponent(projectId)}` +
      (lens ? `&lens=${encodeURIComponent(lens)}` : '')),
    enabled: !!projectId,
  })
}

export interface SearchResult extends MapNodeRow { score: number }
export function useMapSearch(projectId: string, q: string, enabled: boolean) {
  return useQuery({
    queryKey: ['map-search', projectId, q],
    queryFn: () => fetchJSON<{ ok: boolean; reason?: string; results: SearchResult[] }>(
      `/api/map/search?project_id=${encodeURIComponent(projectId)}&q=${encodeURIComponent(q)}&top_k=20`),
    enabled: !!projectId && enabled && q.trim().length > 0,
  })
}

export function useMapNode(projectId: string, id: string | null) {
  return useQuery({
    queryKey: ['map-node', projectId, id],
    queryFn: () => fetchJSON<NodeDetail>(
      `/api/map/node?project_id=${encodeURIComponent(projectId)}&id=${encodeURIComponent(id!)}`),
    enabled: !!projectId && !!id,
  })
}

export function useSaveNode(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (node: Record<string, unknown>) =>
      fetchJSON<MapNodeRow>(`/api/map/node?project_id=${encodeURIComponent(projectId)}`,
        { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(node) }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['map-graph', projectId] })
      qc.invalidateQueries({ queryKey: ['map-node', projectId] })
      qc.invalidateQueries({ queryKey: ['map-selfcheck', projectId] })
    },
  })
}

export function useLinkNodes(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (link: { source_id: string; target: string; rel: string; weight?: number; note?: string }) =>
      fetchJSON(`/api/map/link?project_id=${encodeURIComponent(projectId)}`,
        { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(link) }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['map-graph', projectId] })
      qc.invalidateQueries({ queryKey: ['map-selfcheck', projectId] })
    },
  })
}

export function useDeleteNode(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      fetchJSON(`/api/map/node?project_id=${encodeURIComponent(projectId)}&id=${encodeURIComponent(id)}`,
        { method: 'DELETE' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['map-graph', projectId] })
      qc.invalidateQueries({ queryKey: ['map-selfcheck', projectId] })
    },
  })
}

// ── verification (Phase 3) ────────────────────────────────────────────
export interface SelfcheckIssue { node_id: string; title: string; severity: string; kind: string; detail: string }
export interface SelfcheckReport {
  project_id: string; node_count: number; issue_count: number
  by_severity: Record<string, number>; by_kind: Record<string, number>; issues: SelfcheckIssue[]
}

export function useSelfcheck(projectId: string, enabled: boolean) {
  return useQuery({
    queryKey: ['map-selfcheck', projectId],
    queryFn: () => fetchJSON<SelfcheckReport>(`/api/map/selfcheck?project_id=${encodeURIComponent(projectId)}`),
    enabled: !!projectId && enabled,
  })
}

export function useGround(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (b: { node_id: string; url: string; phrase: string }) =>
      fetchJSON<{ ok: boolean; state?: string; reason?: string; raw_ref?: string }>(
        `/api/map/ground?project_id=${encodeURIComponent(projectId)}`,
        { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['map-graph', projectId] })
      qc.invalidateQueries({ queryKey: ['map-node', projectId] })
      qc.invalidateQueries({ queryKey: ['map-selfcheck', projectId] })
    },
  })
}

// ── LLM connect / expand (Phase 4) — return suggestions, never auto-write ──
export interface ConnectResult {
  ok: boolean; reason?: string; detail?: string; model_used?: string
  existing_path?: Array<{ from: string; to: string; rel: string }> | null
  suggestion?: { source_id: string; target: string; rel: string; weight: number; reason: string; state: string }
}
export interface ExpandResult {
  ok: boolean; reason?: string; detail?: string; model_used?: string
  suggestions?: Array<{ title: string; type: string; why: string; origin: string; provenance_state: string }>
}

export function useConnect(projectId: string) {
  return useMutation({
    mutationFn: (b: { a: string; b: string; allow_cloud: boolean }) =>
      fetchJSON<ConnectResult>(`/api/map/connect?project_id=${encodeURIComponent(projectId)}`,
        { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) }),
  })
}

export function useExpand(projectId: string) {
  return useMutation({
    mutationFn: (b: { node_id: string; allow_cloud: boolean }) =>
      fetchJSON<ExpandResult>(`/api/map/expand?project_id=${encodeURIComponent(projectId)}`,
        { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) }),
  })
}
