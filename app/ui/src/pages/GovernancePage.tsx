import { useEffect, useState } from 'react'
import { Check, Clock3, FileSearch, Fingerprint, GitBranch, LoaderCircle, RefreshCw, ShieldAlert, X } from 'lucide-react'
import { getGovernanceSnapshot, getMeshLinks, getMeshNodes, reviewAccessRequest, reviewMeshLink } from '../services/api'
import type { AuditEntry, GovernanceRequest, MeshLink } from '../services/api'

export default function GovernancePage() {
  const [tab, setTab] = useState<'requests' | 'links' | 'audit'>('requests')
  const [links, setLinks] = useState<MeshLink[]>([])
  const [names, setNames] = useState<Record<string, string>>({})
  const [pending, setPending] = useState<GovernanceRequest[]>([])
  const [audit, setAudit] = useState<AuditEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [busyId, setBusyId] = useState('')
  const [error, setError] = useState('')

  const refresh = async () => {
    setLoading(true)
    setError('')
    try {
      const { data } = await getGovernanceSnapshot()
      setPending(data.pending)
      setAudit(data.audit)
      setLinks((await getMeshLinks()).data.links)
      getMeshNodes().then(({ data }) => setNames(Object.fromEntries(data.nodes.map((node) => [node.node_id, node.company])))).catch(() => undefined)
    } catch (reason) {
      setError((reason as { response?: { data?: { detail?: string } } }).response?.data?.detail ?? 'Could not load grant and audit state.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void refresh() }, [])

  const decide = async (item: GovernanceRequest, decision: 'approve' | 'deny') => {
    setBusyId(item.request_id)
    setError('')
    try {
      await reviewAccessRequest(item.node_id, item.request_id, decision, 24)
      await refresh()
    } catch (reason) {
      setError((reason as { response?: { data?: { detail?: string } } }).response?.data?.detail ?? 'Review action failed.')
    } finally {
      setBusyId('')
    }
  }

  const reviewLink = async (link: MeshLink, side: string, decision: 'approve' | 'reject') => {
    setBusyId(`${link.id}-${side}`)
    setError('')
    try {
      await reviewMeshLink(link.id, side, decision)
      await refresh()
    } catch (reason) {
      setError((reason as { response?: { data?: { detail?: string } } }).response?.data?.detail ?? 'Link review failed.')
    } finally {
      setBusyId('')
    }
  }

  return (
    <div className="mesh-data-page">
      <header className="mesh-page-heading"><div><div className="mesh-eyebrow">Access and evidence</div><h1>Governance</h1><p>Review synthetic pilot requests and inspect the content-free decision ledger.</p></div><button type="button" className="mesh-outline-action" onClick={() => void refresh()} disabled={loading}><RefreshCw size={14} className={loading ? 'animate-spin' : ''} />Refresh</button></header>
      <div className="mesh-governance-notice"><ShieldAlert size={16} /><span><strong>POC review controls.</strong> Decisions below simulate the configured subsidiary owner role for local demo accounts only.</span></div>
      {error && <div role="alert" className="mesh-alert error">{error}</div>}
      <div className="mesh-tabs" role="tablist" aria-label="Governance views">
        <button type="button" role="tab" aria-selected={tab === 'requests'} className={tab === 'requests' ? 'active' : ''} onClick={() => setTab('requests')}><Clock3 size={15} />Approvals <span>{pending.length}</span></button>
        <button type="button" role="tab" aria-selected={tab === 'links'} className={tab === 'links' ? 'active' : ''} onClick={() => setTab('links')}><GitBranch size={15} />Links between companies <span>{links.filter((l) => l.status === 'proposed').length}</span></button>
        <button type="button" role="tab" aria-selected={tab === 'audit'} className={tab === 'audit' ? 'active' : ''} onClick={() => setTab('audit')}><Fingerprint size={15} />Decision log <span>{audit.length}</span></button>
      </div>
      {loading && <div className="mesh-alert pending"><LoaderCircle size={16} className="animate-spin" />Loading node-local governance records…</div>}
      {!loading && tab === 'requests' && <section className="governance-list">
        {pending.map((item) => <article className="governance-request" key={item.request_id}>
          <div className="governance-request-heading"><span className="governance-request-id">{item.request_id}</span><span className="mesh-result-state warning">Pending</span><span className="governance-node-label">{item.company}</span></div>
          <h2>{item.title}</h2>
          <div className="governance-request-meta"><span>Requester {item.requester_company}</span><span>Kind {item.kind}</span><span>Requested {item.mode}</span><span>Owner {item.owner_role}</span></div>
          <p>Purpose: {item.purpose.replace(/_/g, ' ')}</p>
          {item.target_id && <p>Expert profile: {item.target_id} · requester-only reveal after approval</p>}
          <div className="governance-request-actions"><button type="button" className="mesh-outline-action danger" disabled={busyId === item.request_id} onClick={() => void decide(item, 'deny')}><X size={14} />Deny</button><button type="button" className="mesh-primary-action" disabled={busyId === item.request_id} onClick={() => void decide(item, 'approve')}>{busyId === item.request_id ? <LoaderCircle size={14} className="animate-spin" /> : <Check size={14} />}Approve 24 hours</button></div>
        </article>)}
        {!pending.length && !error && <div className="ask-empty-results">No pending requests. New access and expert-introduction requests will appear here.</div>}
      </section>}
      {!loading && tab === 'links' && <section className="governance-list">
        {links.map((link) => {
          const approved = new Set(link.approvals.filter((a) => a.decision !== 'reject').map((a) => a.subsidiary))
          return <article className="governance-request" key={link.id}>
            <div className="governance-request-heading"><span className="governance-request-id">{link.id}</span><span className={`mesh-result-state ${link.status === 'approved' ? 'success' : 'warning'}`}>{link.status}</span><span className="governance-node-label">{link.type.replace(/_/g, ' ').toLowerCase()}</span></div>
            <h2>{link.source_title} → {link.target_title}</h2>
            {link.note && <p>{link.note}</p>}
            <div className="governance-request-meta"><span>{link.source}</span><span>{link.target}</span>{link.confidence != null && link.confidence < 1 && <span>Extraction score {link.confidence}</span>}</div>
            {link.status === 'proposed' && <div className="governance-request-actions">{(link.sides ?? []).map((side) => approved.has(side)
              ? <span key={side} className="mesh-result-state success">{names[side] ?? side} approved</span>
              : <span key={side} className="governance-request-actions">
                  <button type="button" className="mesh-outline-action danger" disabled={busyId === `${link.id}-${side}`} onClick={() => void reviewLink(link, side, 'reject')}><X size={14} />Reject for {names[side] ?? side}</button>
                  <button type="button" className="mesh-primary-action" disabled={busyId === `${link.id}-${side}`} onClick={() => void reviewLink(link, side, 'approve')}><Check size={14} />Approve for {names[side] ?? side}</button>
                </span>)}</div>}
          </article>
        })}
        {!links.length && <div className="ask-empty-results">No links between companies.</div>}
      </section>}
      {!loading && tab === 'audit' && <section className="mesh-section-panel audit-panel">
        <div className="mesh-audit-heading"><div><h2>Node decision ledger</h2><p>Decisions and identifiers only. Query text and source content are not recorded.</p></div><span className="mesh-result-state success">Hash chained</span></div>
        {audit.length ? <div className="mesh-audit-table-wrap"><table className="mesh-audit-table"><thead><tr><th>Time</th><th>Node</th><th>Caller company</th><th>Action</th><th>Datapoint</th><th>Decision</th><th>Rule</th></tr></thead><tbody>{audit.map((entry, index) => <tr key={`${entry.trace_id}-${index}`}><td>{entry.timestamp ? new Date(entry.timestamp).toLocaleString() : '—'}</td><td>{entry.node_id}</td><td>{entry.caller_company ?? '—'}</td><td>{entry.action}</td><td>{entry.datapoint_id}</td><td><span className={`mesh-result-state ${entry.decision.startsWith('BLOCKED') ? 'warning' : 'success'}`}>{entry.decision}</span></td><td>{entry.rule_id}</td></tr>)}</tbody></table></div> : <div className="ask-empty-results">No decisions recorded yet.</div>}
      </section>}
      <div className="mesh-page-footnote"><FileSearch size={14} />Each subsidiary node retains its own grant database and audit chain.</div>
    </div>
  )
}
