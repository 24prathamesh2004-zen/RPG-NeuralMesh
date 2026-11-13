import { useEffect, useMemo, useState } from 'react'
import type { CSSProperties } from 'react'
import { Activity, AlertTriangle, Boxes, ChevronDown, ChevronUp, LoaderCircle, RefreshCw } from 'lucide-react'
import { getMeshGraph, getMeshNodes, refreshMeshGraph } from '../services/api'
import type { MeshGraphView, MeshNodeInfo } from '../services/api'
import MeshGraphExplorer from '../components/MeshGraphExplorer'
import { levelWords, modeLabel, profileWords } from '../lib/format'

function MeshGraphPanel() {
  const [graph, setGraph] = useState<MeshGraphView | null>(null)
  const [busy, setBusy] = useState(false)
  const load = async (refresh = false) => {
    setBusy(true)
    try {
      if (refresh) await refreshMeshGraph()
      setGraph((await getMeshGraph()).data)
    } finally {
      setBusy(false)
    }
  }
  useEffect(() => { void load() }, [])
  if (!graph) return null
  return (
    <section className="mesh-section-panel">
      <div className="mesh-side-heading"><h2>Mesh graph</h2><button type="button" className="mesh-outline-action" onClick={() => void load(true)} disabled={busy}><RefreshCw size={14} className={busy ? 'animate-spin' : ''} />Reload from nodes</button></div>
      <MeshGraphExplorer graph={graph} />
      <p className="mesh-node-profile">{Object.entries(graph.exports ?? {}).map(([n, s]) => `${n}: ${s}`).join(' · ')}{graph.revision != null && ` · revision ${graph.revision}`}</p>
      {graph.checks && graph.checks.length > 0 && <ul className="mesh-graph-checks">{graph.checks.map((c) => <li key={c.rule}><span className={`mesh-result-state ${c.ok ? 'success' : 'warning'}`}>{c.ok ? 'ok' : `${c.failures} found`}</span><span>{c.meaning}</span>{!c.ok && <small>{c.examples.join(', ')}{c.action ? ` · ${c.action}` : ''}</small>}</li>)}</ul>}
    </section>
  )
}

export default function MeshNodesPage() {
  const [nodes, setNodes] = useState<MeshNodeInfo[]>([])
  const [expanded, setExpanded] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const refresh = async () => {
    setLoading(true)
    setError('')
    try {
      const { data } = await getMeshNodes()
      setNodes(data.nodes)
    } catch (reason) {
      setError((reason as { response?: { data?: { detail?: string } } }).response?.data?.detail ?? 'Could not load subsidiary node status.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void refresh() }, [])

  const connected = nodes.filter((node) => node.status === 'healthy').length
  return (
    <div className="mesh-data-page">
      <header className="mesh-page-heading"><div><div className="mesh-eyebrow">Subsidiary connectivity</div><h1>Mesh Nodes</h1><p>Each company runs its own node and decides what it shares. Documents and their text stay at the node. The centre holds only titles, links and counts.</p></div><button type="button" className="mesh-outline-action" onClick={() => void refresh()} disabled={loading}><RefreshCw size={14} className={loading ? 'animate-spin' : ''} />Refresh status</button></header>
      <section className="mesh-node-summary"><span className="mesh-node-summary-icon"><Activity size={18} /></span><strong>{connected} / {nodes.length || 4}</strong><span>nodes responding now</span><span className="mesh-node-summary-note">Checked live</span></section>
      {error && <div className="mesh-alert error"><AlertTriangle size={17} />{error}</div>}
      {loading && nodes.length === 0 && <div className="mesh-alert pending"><LoaderCircle size={17} className="animate-spin" />Checking the node of each company…</div>}
      <section className="mesh-node-cards">
        {nodes.map((node) => <article className="mesh-node-card" key={node.node_id} style={{ '--node-tone': node.tone ?? '#68708f' } as CSSProperties}>
          <div className="mesh-node-card-top"><span className="mesh-node-company-mark"><Boxes size={17} /></span><span className={`mesh-result-state ${node.status === 'healthy' ? 'success' : 'warning'}`}><i />{node.status === 'healthy' ? 'Healthy' : 'Unavailable'}</span></div>
          <h2>{node.company}</h2><p>{node.owner}</p>
          <div className="mesh-node-level"><span>{levelWords(node.level)}</span><span>Pack format {node.schema_version}</span></div>
          <div className="mesh-node-card-stats"><div><strong>{node.datapoint_count}</strong><span>Catalogue items</span></div><div><strong>{node.packs?.length ?? 0}</strong><span>Knowledge packs</span></div></div>
          <button type="button" className="mesh-node-expand" onClick={() => setExpanded(expanded === node.node_id ? null : node.node_id)}>{expanded === node.node_id ? 'Hide capabilities' : 'View capabilities'}{expanded === node.node_id ? <ChevronUp size={14} /> : <ChevronDown size={14} />}</button>
          {expanded === node.node_id && node.profile && <p className="mesh-node-profile">{profileWords(node.profile)}</p>}
          {expanded === node.node_id && <div className="mesh-capability-list">{node.datapoints.map((dp) => <div key={String(dp.datapoint_id)}><span><b>{String(dp.datapoint_id)}</b>{String(dp.title)}</span><em title={`Exposure ${String(dp.exposure_ceiling)}`}>{modeLabel(String(dp.exposure_ceiling))}</em></div>)}
            <p className="mesh-panel-footnote">The most each catalogue item shares: full text, summary, title only, or nothing. An item that never leaves its company is listed only to that company. Its documents are never shared. A person of another company sees at most the title of a document that matched a question, marked as withheld.</p></div>}
          {node.error && <p className="mesh-node-error">{node.error}</p>}
        </article>)}
      </section>
      {!loading && nodes.length === 0 && !error && <div className="ask-empty-results">No node registry results returned.</div>}
      <MeshGraphPanel />
    </div>
  )
}
