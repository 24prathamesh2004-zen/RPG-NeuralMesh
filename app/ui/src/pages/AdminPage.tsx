import { useEffect, useState } from 'react'
import { Activity, BookOpen, CheckCircle2, CircleDashed, LoaderCircle, RefreshCw, ShieldCheck, XCircle } from 'lucide-react'
import { getAdminSnapshot } from '../services/api'
import type { MeshNodeInfo } from '../services/api'

interface AdminSnapshot {
  registry: MeshNodeInfo[]
  ontology: { concept: string; aliases: string[] }[]
  guardrails: { id: string; label: string; enabled: boolean }[]
  model_policy: { strict_mode: boolean; answer_model_ready: boolean; steps: Record<string, { model: string; tier: string; max_input_tokens: number }> }
  orchestrator_stage: string
}

export default function AdminPage() {
  const [snapshot, setSnapshot] = useState<AdminSnapshot | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const refresh = async () => {
    setLoading(true)
    setError('')
    try {
      const { data } = await getAdminSnapshot()
      setSnapshot(data)
    } catch (reason) {
      setError((reason as { response?: { data?: { detail?: string } } }).response?.data?.detail ?? 'Could not load mesh configuration.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void refresh() }, [])

  return (
    <div className="mesh-data-page">
      <header className="mesh-page-heading"><div><div className="mesh-eyebrow">Shared mesh configuration</div><h1>Admin</h1><p>Inspect the live registry, shared vocabulary and POC guardrail/model configuration.</p></div><button type="button" className="mesh-outline-action" onClick={() => void refresh()} disabled={loading}><RefreshCw size={14} className={loading ? 'animate-spin' : ''} />Refresh registry</button></header>
      {error && <div role="alert" className="mesh-alert error">{error}</div>}
      {loading && !snapshot && <div className="mesh-alert pending"><LoaderCircle size={16} className="animate-spin" />Reading registry from subsidiary MCP servers…</div>}
      {snapshot && <>
        <section className="admin-pipeline">
          <div className="admin-pipeline-heading"><div><div className="mesh-eyebrow">Orchestrator status</div><h2>Parallel MCP evidence fan-out</h2></div><span className={`mesh-result-state ${snapshot.model_policy.answer_model_ready ? 'success' : 'warning'}`}>{snapshot.model_policy.answer_model_ready ? 'Answer model ready' : 'Evidence only, no answer model'}</span></div>
          <div className="admin-pipeline-steps">{['Question + purpose', 'Graph routing', 'Subsidiary MCP nodes', 'Policy-filtered evidence', 'Answer and 7 checks'].map((step, index) => <div className={`admin-pipeline-step ${index < 4 || snapshot.model_policy.answer_model_ready ? 'active' : ''}`} key={step}><span>{index < 4 || snapshot.model_policy.answer_model_ready ? <CheckCircle2 size={15} /> : <CircleDashed size={15} />}</span><strong>{step}</strong></div>)}</div>
          <p>Steps: {snapshot.orchestrator_stage.replace(/_/g, ', ')}. The question is routed on the graph, the selected nodes return policy-filtered evidence, and the answer is written from that evidence and checked by seven rules.</p>
        </section>
        <div className="admin-columns">
          <section className="mesh-section-panel">
            <div className="mesh-section-heading"><div><div className="mesh-eyebrow">Node registry</div><h2>Independent MCP endpoints</h2></div></div>
            <div className="admin-registry-list">{snapshot.registry.map((node) => <article key={node.node_id}><span className={`mesh-response-icon ${node.status === 'healthy' ? 'good' : 'bad'}`}>{node.status === 'healthy' ? <CheckCircle2 size={15} /> : <XCircle size={15} />}</span><div><strong>{node.company}</strong><small>{node.node_id} · schema {node.schema_version} · {node.datapoint_count} datapoints</small></div><span className="admin-endpoint">:{node.port}/mcp</span></article>)}</div>
          </section>
          <section className="mesh-section-panel">
            <div className="mesh-section-heading"><div><div className="mesh-eyebrow">Model policy</div><h2>Answer model</h2></div><Activity size={17} className="mesh-accent-icon" /></div>
            <div className="admin-model-name">{snapshot.model_policy.steps.answer?.model ?? 'none'}</div>
            <span className={`mesh-result-state ${snapshot.model_policy.answer_model_ready ? 'success' : 'warning'}`}>{snapshot.model_policy.answer_model_ready ? 'Key configured' : 'Key not configured'}</span>
            <p className="mesh-panel-footnote">The key is server-side only and is never returned to the browser.</p>
          </section>
        </div>
        <div className="admin-columns admin-columns-bottom">
          <section className="mesh-section-panel"><div className="mesh-section-heading"><div><div className="mesh-eyebrow">Shared vocabulary</div><h2>Ontology mappings</h2></div><BookOpen size={17} className="mesh-accent-icon" /></div><div className="admin-ontology-list">{snapshot.ontology.map((item) => <div key={item.concept}><strong>{item.concept}</strong><span>{item.aliases.join(' · ')}</span></div>)}</div></section>
          <section className="mesh-section-panel"><div className="mesh-section-heading"><div><div className="mesh-eyebrow">Policy pipeline</div><h2>Guardrails</h2></div><ShieldCheck size={17} className="mesh-accent-icon" /></div><div className="admin-guardrails">{snapshot.guardrails.map((item) => <div key={item.id}><span>{item.label}</span><strong className={item.enabled ? 'enabled' : 'disabled'}>{item.enabled ? 'On' : 'Off'}</strong></div>)}</div></section>
        </div>
      </>}
    </div>
  )
}
