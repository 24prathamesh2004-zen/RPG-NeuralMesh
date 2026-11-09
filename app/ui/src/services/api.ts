import axios from 'axios'

// In dev, Vite proxies /api -> VITE_API_URL. In production, the nginx container
// proxies /api -> BACKEND_URL. The app always calls the relative /api/v1 base.
const api = axios.create({
  baseURL: '/api/v1',
  timeout: 90_000, // LLM chains can take 30-60s under load
})

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('rpg-neuralmesh-token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// A company with a Mesh Node, as config/nodes.yaml names it (ceat, kec, raychem, ...)
export type CompanyId = string

export interface ExpertProfile {
  job_title: string
  skills: string[]
  consent: boolean
}

export interface UserAccount {
  user_id: string
  email: string
  display_name: string
  company: CompanyId
  company_name: string
  roles: string[]
  expert_profile: ExpertProfile | null
}

export interface AccountResponse {
  access_token: string
  token_type: string
  user: UserAccount
}

export interface MeshNodeResult {
  node_id: CompanyId
  status: string
  results: Record<string, unknown>[]
  withheld: Record<string, unknown>[]
  error?: string | null
}

export type MeshPurpose = 'problem_solving' | 'compliance' | 'bid_support' | 'learning' | 'career_mobility'

export interface EvidenceRecord {
  schema_version: '1.0'
  evidence_id: string
  kind: 'summary' | 'chunk' | 'aggregate' | 'metadata' | 'relationship' | 'expert'
  node: string
  datapoint?: string | null
  document?: string | null
  title?: string | null
  version?: string | null
  stale?: boolean
  superseded_by?: string | null
  mode?: string | null
  sensitivity?: string | null
  decision?: string | null
  rule_id?: string | null
  reason?: string | null
  text?: string | null
  citation?: string | null
  concepts?: string[]
  score?: number | null
  suspicious?: boolean
}

export interface MeshLink {
  id: string
  type: string
  source: string
  target: string
  note?: string | null
  status: string
  approvals: { subsidiary: string; role: string; date: string; decision?: string }[]
  source_title?: string
  target_title?: string
  sides?: string[]
  confidence?: number | null
}

export interface MeshRouting {
  method?: 'graph' | 'classifier' | 'user' | 'named' | 'own' | 'context' | 'none'
  concepts?: string[]
  concept_labels?: Record<string, string>
  subsidiaries?: string[]
  narrowed_out?: string[]
  reason?: string
}

export interface MeshQueryResponse {
  question: string
  purpose: string
  status: 'ok' | 'partial' | 'needs_node_choice'
  answer: string | null
  answer_status: 'answered' | 'evidence_only' | 'check_failed'
  answer_reason?: string | null
  citations: string[]
  cached: boolean
  routing: MeshRouting
  evidence: EvidenceRecord[]
  also_found: EvidenceRecord[]
  relationships: MeshLink[]
  omitted: number
  node_results: MeshNodeResult[]
  sources: Record<string, unknown>[]
  withheld: Record<string, unknown>[]
}

export interface MeshNodeInfo {
  node_id: CompanyId
  company: string
  tone?: string
  status: string
  level: string
  port: number
  schema_version: string
  datapoint_count: number
  datapoints: Record<string, unknown>[]
  packs?: { pack_id: string; domain: string; documents: number; published_at: string }[]
  profile?: string
  owner: string
  error?: string
}

export interface GraphCheck { rule: string; meaning: string; failures: number; examples: string[]; ok: boolean; action?: string }

export interface MeshGraphView {
  nodes: { id: string; type: string; label: string; subsidiary?: string | null }[]
  edges: { id: string; type: string; source: string; target: string; status: string }[]
  counts: Record<string, number>
  exports: Record<string, string>
  revision?: number
  checks?: GraphCheck[]
  reports?: Record<string, { nodes: number; edges: number; warnings: number; retired_edges: number; retired_nodes: number }>
}

export interface ExpertMatch {
  node_id: CompanyId
  expert_id: string
  company: string
  role: string
  skills: string[]
  evidence: string[]
  // the titles of the evidence documents, in the order of evidence
  evidence_titles?: string[]
  match_score: number
  name?: string
  name_available_after_intro_approval: boolean
}

export interface GovernanceRequest {
  request_id: string
  requester_sub: string
  requester_company: string
  kind: string
  datapoint_id: string
  target_id?: string | null
  mode: string
  purpose: string
  requested_at: string
  node_id: CompanyId
  company: string
  title: string
  owner_role: string
}

export interface AuditEntry {
  timestamp: string
  trace_id: string
  node_id: CompanyId
  caller_sub?: string
  caller_company?: string
  action: string
  datapoint_id: string
  // the datapoint's title, absent for a never-leave datapoint of another company
  datapoint_title?: string | null
  // the title is kept back: the datapoint never leaves the node's company
  datapoint_hidden?: boolean
  decision: string
  rule_id: string
  request_id?: string | null
  grant_id?: string | null
}

export interface DashboardSnapshot {
  nodes: MeshNodeInfo[]
  connected_nodes: number
  total_nodes: number
  search_decisions: number
  allowed_decisions: number
  blocked_decisions: number
  pending_approvals: number
  activity_by_node: Record<string, number>
  recent_activity: AuditEntry[]
  synthetic: boolean
}

export interface SessionResponse {
  session_id: string
  current_step: string
  step_status: string
  messages: { role: string; agent?: string; content: string }[]
  collected: Record<string, unknown>
}

export const checkHealth = () => api.get<{ status: string }>('/health')

export const startSession = (message: string, context?: Record<string, unknown>) =>
  api.post<SessionResponse>('/example/start', { message, context })

export const resumeSession = (session_id: string, message: string) =>
  api.post<SessionResponse>('/example/resume', { session_id, message })

export const getSession = (session_id: string) =>
  api.get<SessionResponse>(`/example/${session_id}`)

export const signUp = (payload: {
  email: string
  password: string
  display_name: string
  company: CompanyId
  expert_opt_in: boolean
  expert_title?: string
  expert_skills?: string[]
}) => api.post<AccountResponse>('/auth/signup', payload)

export const signIn = (email: string, password: string) =>
  api.post<AccountResponse>('/auth/signin', { email, password })

export const getCurrentUser = () => api.get<UserAccount>('/auth/me')
export const getCompanies = () => api.get<{ companies: { id: CompanyId; label: string }[] }>('/auth/companies')

export const queryMesh = (payload: {
  question: string
  nodes?: CompanyId[]
  purpose: MeshPurpose
}) => api.post<MeshQueryResponse>('/mesh/query', payload)
export const getMeshGraph = () => api.get<MeshGraphView>('/mesh/graph')
export const refreshMeshGraph = () => api.post<{ exports: Record<string, string> }>('/mesh/graph/refresh')
export const getMeshLinks = () => api.get<{ links: MeshLink[] }>('/mesh/graph/links')
export const reviewMeshLink = (id: string, subsidiary: string, decision: 'approve' | 'reject') =>
  api.post<MeshLink>(`/mesh/graph/links/${id}/review`, { subsidiary, decision })

// Entries an application proposed for the graph, by application and link type. A side approves an entry for its own
// company, and "group" is the side a mesh admin approves as curator.
export interface ProposalEntry {
  id: string
  source: string
  target: string
  source_title: string
  target_title: string
  status: 'proposed' | 'approved' | 'rejected'
  sides: string[]
  reviewed_by: string[]
  you_review: string[]
}
export interface ProposalGroup {
  application: string
  name: string
  type: string
  counts: { proposed: number; approved: number; rejected: number }
  sides: string[]
  pending_for_you: number
  entries: ProposalEntry[]
  // the kinds of entity at each end of the group's links ("Asset", "AssetFamily")
  from_types?: string[]
  to_types?: string[]
}
export const getProposals = () => api.get<{ groups: ProposalGroup[]; your_sides: string[] }>('/mesh/proposals')
export const reviewProposals = (payload: { decision: 'approve' | 'reject'; ids?: string[]; application?: string; type?: string }) =>
  api.post<{ reviewed: number; decision: string }>('/mesh/proposals/review', payload)

export const getDashboardSnapshot = () => api.get<DashboardSnapshot>('/mesh/dashboard')
export const getMeshNodes = () => api.get<{ nodes: MeshNodeInfo[] }>('/mesh/nodes')
export const searchExperts = (payload: { query: string; purpose: string; nodes: CompanyId[] }) =>
  api.post<{ nodes: { node_id: CompanyId; status: string; experts: ExpertMatch[] }[]; experts: ExpertMatch[] }>('/mesh/experts/search', payload)
export const requestExpertIntroduction = (nodeId: CompanyId, payload: { expert_id: string; purpose: string; justification: string }) =>
  api.post(`/mesh/experts/${nodeId}/intro`, payload)
export const getGovernanceSnapshot = () => api.get<{ pending: GovernanceRequest[]; audit: AuditEntry[]; mode: string }>('/mesh/governance')
export const reviewAccessRequest = (nodeId: CompanyId, requestId: string, decision: 'approve' | 'deny', hours = 24) =>
  api.post(`/mesh/governance/${nodeId}/requests/${requestId}/review`, { decision, hours })
export interface GraphDomains {
  domains: { domain: string; entities: number; links: number
    node_types: { type: string; count: number; description: string }[]
    edge_types: { type: string; from: string[]; to: string[]; group: string; symmetric: boolean; counts: Record<string, number> }[] }[]
  groups: Record<string, string[]>
  sources: Record<string, { nodes: number; edges: number; warnings: number }>
  revision: number
  checks: GraphCheck[]
}
export interface ConnectedApplication {
  id: string; name: string; domain: string; identity: string; tools: string[]
  loaded: { sources: string[]; entities: number; links: number; warnings: number }
  facts: Record<string, string | number | null>
  note: string
  imports?: {
    kept: number
    last_loaded_at: string | null
    last_send: { at: string; loaded: number; unchanged: number; refused: number } | null
    // every pack whose latest result is a refusal
    refused: { pack_id: string; at: string; reason: string | null }[]
  }
}
export const getGraphDomains = () => api.get<GraphDomains>('/mesh/domains')
export interface AuditChainCheck { nodes: { node_id: string; company: string; entries: number; valid: boolean }[]; valid: boolean }
export const verifyAuditChains = () => api.get<AuditChainCheck>('/mesh/governance/audit/verify')
export const getApplications = () => api.get<{ applications: ConnectedApplication[]; revision: number }>('/mesh/applications')
export const getAdminSnapshot = () => api.get<{
  registry: MeshNodeInfo[]
  ontology: { concept: string; aliases: string[] }[]
  guardrails: { id: string; label: string; enabled: boolean }[]
  orchestrator_stage: string
  model_policy: { strict_mode: boolean; answer_model_ready: boolean; steps: Record<string, { model: string; tier: string; max_input_tokens: number }> }
}>('/mesh/admin')

export default api
