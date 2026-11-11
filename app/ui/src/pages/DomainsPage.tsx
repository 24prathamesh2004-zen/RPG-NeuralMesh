import { useEffect, useState } from 'react'
import { Layers, LoaderCircle, RefreshCw } from 'lucide-react'
import { getGraphDomains } from '../services/api'
import type { GraphDomains } from '../services/api'
import { linkWords } from '../lib/format'

export default function DomainsPage() {
  const [data, setData] = useState<GraphDomains | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  const load = async () => {
    setLoading(true)
    setError('')
    try {
      setData((await getGraphDomains()).data)
    } catch (reason) {
      setError((reason as { response?: { data?: { detail?: string } } }).response?.data?.detail ?? 'The domains could not be read.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void load() }, [])

  return (
    <div className="mesh-data-page">
      <header className="mesh-page-heading">
        <div><div className="mesh-eyebrow">Graph rules</div><h1>Domains</h1><p>The layers of the context graph. Each domain brings its own kinds of entity and link, written in one rules file, and the counts below are what the graph holds today.</p></div>
        <button type="button" className="mesh-outline-action" onClick={() => void load()} disabled={loading}><RefreshCw size={14} className={loading ? 'animate-spin' : ''} />Refresh</button>
      </header>
      {error && <div role="alert" className="mesh-alert error">{error}</div>}
      {loading && !data && <div className="mesh-alert pending"><LoaderCircle size={16} className="animate-spin" />Reading the graph rules…</div>}
      {data && <>
        <div className="mesh-kpi-row">
          {data.domains.map((d) => <div className="mesh-kpi" key={d.domain}><span className="mesh-kpi-icon green"><Layers size={16} /></span><div><strong>{d.entities}</strong><span>{d.domain}: {d.entities} entities, {d.links} links</span></div></div>)}
        </div>
        {data.domains.map((d) => (
          <section className="mesh-section-panel" key={d.domain}>
            <div className="mesh-section-heading"><div><div className="mesh-eyebrow">Domain</div><h2>{d.domain}</h2></div><span className="mesh-result-state success">{d.node_types.length} entity kinds · {d.edge_types.length} link kinds</span></div>
            <div className="domain-columns">
              <div>
                <h3>Entities</h3>
                <div className="mesh-table-wrap"><table className="mesh-table"><thead><tr><th>Kind</th><th>Live</th><th>Meaning</th></tr></thead><tbody>
                  {d.node_types.map((n) => <tr key={n.type}><td><strong>{n.type}</strong></td><td>{n.count}</td><td>{n.description}</td></tr>)}
                </tbody></table></div>
              </div>
              <div>
                <h3>Links</h3>
                <div className="mesh-table-wrap"><table className="mesh-table"><thead><tr><th>Kind</th><th>From</th><th>To</th><th>Group</th><th>Approved</th><th>Proposed</th></tr></thead><tbody>
                  {d.edge_types.map((e) => <tr key={e.type}><td title={e.type}><strong>{linkWords(e.type)}</strong>{e.symmetric && <small> both ways</small>}</td><td>{e.from.join(', ')}</td><td>{e.to.join(', ')}</td><td>{e.group}</td><td>{e.counts.approved ?? 0}</td><td>{e.counts.proposed ?? 0}</td></tr>)}
                </tbody></table></div>
                <p className="mesh-panel-footnote">Group: structure links come with the data, hop links are the ones the router may follow to related entries, judgement links are written by a person or an extraction step, and similarity links are computed. A judgement or similarity link between two companies counts only after both owners approve it. A link marked "both ways" reads the same in each direction.</p>
              </div>
            </div>
          </section>
        ))}
        <section className="mesh-section-panel">
          <div className="mesh-section-heading"><div><div className="mesh-eyebrow">Last loads</div><h2>Sources</h2></div><span className="mesh-result-state success">revision {data.revision}</span></div>
          <div className="mesh-table-wrap"><table className="mesh-table"><thead><tr><th>Source</th><th>Entities</th><th>Links</th><th>Unresolved references</th></tr></thead><tbody>
            {Object.entries(data.sources).sort().map(([s, r]) => <tr key={s}><td><code>{s}</code></td><td>{r.nodes}</td><td>{r.edges}</td><td>{r.warnings}</td></tr>)}
          </tbody></table></div>
          <p className="mesh-panel-footnote">An unresolved reference is a link whose other end arrives with a later load. The dangling-link check on Mesh Nodes reports any that never arrives.</p>
        </section>
      </>}
    </div>
  )
}
