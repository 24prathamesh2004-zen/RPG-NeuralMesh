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
  method?: 'graph' | 'classifier' | 'user' | 'named' | 'own' | 'context' | 'context_graph' | 'none'
  question_check?: { intent: 'clear' | 'unclear' | 'off_topic' | 'greeting' | 'unknown'; understood_as: string; suggestions: string[]; reason: string } | null // how the question was understood, and full questions to ask instead of an unclear one
  context_graphs?: { id: string; name: string; kind: 'uploaded' | 'ingested'; description: string; matched_on: 'things' | 'concepts' | 'words' | 'meaning'; shared_things?: string[]; shared_concepts: string[]; shared_words: string[]; answer?: string | null; answer_note?: string | null; chosen?: boolean; why?: string; found?: { nodes: string[]; links: { source: string; type: string; target: string }[] } }[] // the context graphs the question is about, and what the first one holds about it
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
  // the steps of the flow with their time in milliseconds, in order
  steps: { step: string; ms: number }[]
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
  shared?: boolean
  error?: string
}

export interface GraphCheck { rule: string; meaning: string; failures: number; examples: string[]; ok: boolean; action?: string }

export interface MeshGraphView {
  nodes: { id: string; type: string; label: string; subsidiary?: string | null }[]
  edges: { id: string; type: string; source: string; target: string; status: string; evidence?: string; by?: 'code' | 'model' | 'calculated'; document?: string; settled_by?: 'rule' | 'model'; settled_reason?: 'relation' | 'repeated' | 'checked' | 'not_supported' | 'not_needed'; sentences?: number; priority?: 'high' | 'low'; check_reason?: string }[] // evidence, by and document: a link taken from the text of an upload
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
  ingested_graphs?: number // graphs a person wrote as JSON, kept by the central service
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

// ── Uploaded inputs and graph search ─────────────────────────────────────────
export interface SharingRule { ceiling: string | null; never_leave: boolean; company?: string | null; item?: string | null; code?: string | null; item_title?: string | null; shared?: boolean }
export interface ContextGraphRef { id: string; name: string }
export interface ContextGraphSummary { id: string; name: string; inputs: number; removed: number; nodes: CompanyId[]; companies: string[]; latest: string }
export interface UploadRecord {
  synthetic?: boolean // true when the file was sent as invented data. A record without it is real
  node_id: CompanyId
  company?: string
  context_graph: ContextGraphRef
  status: 'accepted' | 'rejected' | 'removed'
  removed?: { by_role: string; by_company: string; at: string } | null
  document: { id: string; datapoint: string; title: string; kind: string; kind_label?: string; version: string; tags: string[]; summary?: string; concepts?: string[] }
  extraction?: { entities: number; links: number; proposed: number; model?: string | null; failed?: string } | null // what was taken from the text
  upload: { file: string; format: string; chars: number; sha256: string; by_role: string; by_company: string; by_company_name?: string; at: string }
  concept_matches?: Record<string, 'phrase' | 'words' | 'tag'>
  sharing: SharingRule
  in_graph?: boolean
  rebuild?: { pack_id: string; documents: number; index_rows: number; vectors: number | null }
  new_item?: { code: string; title: string; domain: string }
  kind_detected?: { by: 'model' | 'rules'; reason: string }
  refresh?: string
  graph?: UploadGraph | null
}
export interface UploadGraph extends Pick<MeshGraphView, 'nodes' | 'edges' | 'counts'> { centre: string }
export interface QualityNote { level: 'ok' | 'warn' | 'note'; text: string }
export interface GraphDescription { text: string; by: 'person' | 'model' | 'code'; at?: string; can_write: boolean }
export interface ContextGraphView extends Pick<MeshGraphView, 'nodes' | 'edges' | 'counts'> {
  id: string; name: string; documents: string[]; quality?: QualityNote[]
  description?: GraphDescription // what the graph is about: written by a person, or made by code from the inputs
  review?: { document: string; reason: string }[] // the inputs that do not match the rest of the graph, until a person keeps or removes them
  set_aside?: { id: string; type: string; source: string; target: string; source_label: string; target_label: string; evidence: string; document: string; reason: string; why?: 'not_needed' | 'not_supported' }[] // links the model's check left out: not stated by the sentence, or noise
}
export const describeGraph = (graphId: string, text: string) => api.put<{ id: string; description: GraphDescription }>(`/mesh/uploads/graphs/${graphId}/description`, { text })
export const keepInput = (docId: string) => api.post(`/mesh/uploads/${docId}/keep`)
export const decideLink = (docId: string, linkId: string, status: 'approved' | 'rejected') => api.post(`/mesh/uploads/${docId}/links/${linkId}`, { status })
export interface UploadItem { code: string; title: string; ceiling: string; never_leave: boolean; owner_role?: string | null; domain: string }
export interface NewItemArea { letter: string; domain: string; title: string }
export interface GraphSearchResult {
  id: string; type: string; label: string; subsidiary?: string | null; company?: string | null; owner?: string | null; matched: string
  sharing: SharingRule | null; connections: Record<string, number>
}
export interface GraphEntity {
  id: string; type: string; label: string; layer: string; owner?: string | null; subsidiary?: string | null; company?: string | null; retired: boolean; aliases: string[]
  properties: Record<string, unknown>; connections: Record<string, number>; sharing: SharingRule | null
  related: Record<string, { id: string; type: string; label: string; status: string; edge_status: string; properties?: Record<string, unknown> }[]>
}
export interface ExportFormat { id: string; name: string; extension?: string; custom: boolean }
export interface NewExportFormat { name: string; extension: string; escape: string; header: string; node_line: string; edge_line: string; footer: string }
export const getUploads = () => api.get<{ uploads: UploadRecord[]; graphs: ContextGraphSummary[]; kinds: string[]; formats: string[]; export_formats: string[]; export_format_list: ExportFormat[] }>('/mesh/uploads')
export const addExportFormat = (fields: NewExportFormat) => api.post<{ format: ExportFormat; export_format_list: ExportFormat[] }>('/mesh/uploads/formats', fields)
export interface UploadSuggestion {
  title: string; tags: string[]; kind: { kind: string; label: string; by: 'model' | 'rules'; reason: string }
  concepts: { id: string; label: string; how: string }[]
  graph: { mode: 'append' | 'new'; id: string | null; name: string; shared: string[]; reason: string }
  decided_by: 'model' | 'code'
}
export const suggestUpload = (form: FormData) => api.post<UploadSuggestion>('/mesh/uploads/suggest', form, { headers: { 'Content-Type': 'multipart/form-data' }, timeout: 120_000 })
export interface GraphTemplate { template: unknown; own: boolean; suggested: unknown; fields: Record<string, Record<string, string>>; can_change: boolean }
// the JSON structure of a context graph: its own when one is kept with it, else the standard one. Without an id, the standard one
export const getGraphTemplate = (graphId?: string) => api.get<GraphTemplate>('/mesh/uploads/json-templates', { params: graphId ? { graph_id: graphId } : {} })
// without a template the graph is given in the template kept with it
export const renderJsonTemplate = (graphId: string, template?: unknown) => api.post<{ output: unknown }>('/mesh/uploads/json-templates/render', template === undefined ? { graph_id: graphId } : { graph_id: graphId, template })
export const uploadExportTemplate = (form: FormData) => api.post<{ format: ExportFormat; export_format_list: ExportFormat[] }>('/mesh/uploads/formats/file', form, { headers: { 'Content-Type': 'multipart/form-data' } })
export const removeExportFormat = (formatId: string) => api.delete<{ removed: string; export_format_list: ExportFormat[] }>(`/mesh/uploads/formats/${encodeURIComponent(formatId)}`)
export const getUploadItems = (nodeId: CompanyId) => api.get<{ node_id: CompanyId; items: UploadItem[]; new_item_areas?: NewItemArea[] }>(`/mesh/uploads/items/${nodeId}`)
export interface BatchEntry { path: string; file?: string; status: 'ok' | 'refused'; reason?: string; graph?: string; graph_id?: string | null; title?: string; kind?: string; company?: string; item?: string }
export interface BatchPlan { name: string; new_item?: { title: string; area: string } | null; entries: BatchEntry[]; graphs: { name: string; id: string | null; new: boolean; files: number }[]; ok: number; refused: number; notes: string[] }
export interface BatchResult { saved: (UploadRecord & { path: string })[]; refused: BatchEntry[]; graphs: (ContextGraphRef & { files: number })[]; new_item?: { code: string; title: string } | null; notes: string[] }
// many files, a folder or one zip: the same form with check=true reads every file and keeps nothing
export const checkUploads = (form: FormData) => api.post<BatchPlan>('/mesh/uploads/batch', form, { headers: { 'Content-Type': 'multipart/form-data' }, timeout: 600_000 })
export const addUploads = (form: FormData) => api.post<BatchResult>('/mesh/uploads/batch', form, { headers: { 'Content-Type': 'multipart/form-data' }, timeout: 1_800_000 })
export const addUpload = (form: FormData) => api.post<UploadRecord>('/mesh/uploads', form, { headers: { 'Content-Type': 'multipart/form-data' }, timeout: 300_000 })
export const removeUpload = (docId: string) => api.delete<UploadRecord>(`/mesh/uploads/${encodeURIComponent(docId)}`)
export const getUploadGraph = (docId: string) => api.get<UploadGraph>(`/mesh/uploads/${encodeURIComponent(docId)}/graph`)
export const downloadUploadGraph = (docId: string, format: string) =>
  api.get<Blob>(`/mesh/uploads/${encodeURIComponent(docId)}/graph`, { params: { format }, responseType: 'blob' })
export const getContextGraph = (graphId: string) => api.get<ContextGraphView>(`/mesh/uploads/graphs/${encodeURIComponent(graphId)}`)
export const downloadContextGraph = (graphId: string, format: string) =>
  api.get<Blob>(`/mesh/uploads/graphs/${encodeURIComponent(graphId)}`, { params: { format }, responseType: 'blob' })
export const dropContextGraph = (graphId: string) =>
  api.delete<{ graph: ContextGraphRef; removed: UploadRecord[]; rebuilt: string[]; failed: Record<string, string>; refresh: Record<string, string>; corrections_dropped?: string[] }>(`/mesh/uploads/graphs/${encodeURIComponent(graphId)}`)
export const clearContextGraph = (graphId: string) => api.post<{ graph: ContextGraphRef; cleared: number }>(`/mesh/uploads/graphs/${encodeURIComponent(graphId)}/clear`)
export const searchGraph = (q: string) => api.get<{ query: string; results: GraphSearchResult[]; by_vector: boolean; total: number }>('/mesh/graph/search', { params: { q } })
export const getGraphEntity = (id: string) => api.get<GraphEntity>(`/mesh/graph/entity/${id}`)

// Ingested context graphs: the JSON a person writes, kept as written (services/context_graph_ingest.py)
export interface IngestedGraphStamp { at: string; by_role: string; by_company: string; by_company_name?: string }
export interface IngestedGraphSummary {
  id: string; name: string; company: CompanyId; company_name: string; description?: string | null
  sensitivity: 'Public' | 'Internal' | 'Confidential' | 'Restricted'; sharing: 'company' | 'group'; synthetic: boolean
  nodes: number; edges: number; node_types: Record<string, number>; edge_types: Record<string, number>
  created: IngestedGraphStamp; updated?: IngestedGraphStamp | null; can_change: boolean
  corrects?: string | null // the id of the uploaded graph this graph corrects, loaded from that graph's JSON
  endpoints: { graph: string; view: string; query: string }
}
export interface IngestReport { filled: string[]; defaults: string[]; ignored: string[]; warnings: string[] }
export interface IngestResult extends IngestReport { graph: IngestedGraphSummary; replaced: boolean; unchanged: boolean; checked_only?: boolean }
export interface IngestRefusal extends IngestReport { detail: string; problems: string[] }
export const ingestGraph = (text: string) => api.post<IngestResult>('/context-graphs', text, { headers: { 'Content-Type': 'application/json' }, timeout: 300_000 }) // the text as written
export const checkGraph = (text: string) => api.post<IngestResult>('/context-graphs', text, { params: { check: true }, headers: { 'Content-Type': 'application/json' }, timeout: 300_000 }) // checks and keeps nothing
export const getIngestedGraphs = () => api.get<{ graphs: IngestedGraphSummary[] }>('/context-graphs')
export const getIngestSample = () => api.get<Record<string, unknown>>('/context-graphs/sample')
export const getIngestedGraph = (graphId: string) => api.get<Record<string, unknown>>(`/context-graphs/${encodeURIComponent(graphId)}`)
export const getIngestedGraphView = (graphId: string) => api.get<ContextGraphView & { graph: IngestedGraphSummary }>(`/context-graphs/${encodeURIComponent(graphId)}/view`)
export const dropIngestedGraph = (graphId: string) => api.delete<{ dropped: { id: string; name: string; company: CompanyId; company_name: string; nodes: number; edges: number } }>(`/context-graphs/${encodeURIComponent(graphId)}`)
