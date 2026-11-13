import { useEffect, useState } from 'react'
import { useAuth } from '../auth/AuthContext'
import { Check, Clock3, FileSearch, Fingerprint, GitBranch, ListChecks, LoaderCircle, RefreshCw, ShieldAlert, X } from 'lucide-react'
import { getGovernanceSnapshot, getMeshLinks, getMeshNodes, getProposals, reviewAccessRequest, reviewMeshLink, reviewProposals, verifyAuditChains } from '../services/api'
import type { AuditChainCheck, AuditEntry, GovernanceRequest, MeshLink, ProposalGroup } from '../services/api'
import { actionWords, decisionLabel, decisionTone, formatDateTime, modeLabel, ruleMeaning, typeWords } from '../lib/format'

export default function GovernancePage() {
  const { user } = useAuth()
  const myCompany = user?.company ?? ''
  const actsForEveryOwner = (user?.roles ?? []).includes('mesh_admin')
  const [tab, setTab] = useState<'requests' | 'links' | 'entries' | 'audit'>('requests')
  const [groups, setGroups] = useState<ProposalGroup[]>([])
  const [yourSides, setYourSides] = useState<string[]>([])
  const [openGroup, setOpenGroup] = useState('')
  const [links, setLinks] = useState<MeshLink[]>([])
  const [names, setNames] = useState<Record<string, string>>({})
  const [pending, setPending] = useState<GovernanceRequest[]>([])
  const [audit, setAudit] = useState<AuditEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [busyId, setBusyId] = useState('')
  const [error, setError] = useState('')
  const [chain, setChain] = useState<AuditChainCheck | null>(null)
  const [checking, setChecking] = useState(false)

  const refresh = async () => {
    setLoading(true)
    setError('')
    try {
      const { data } = await getGovernanceSnapshot()
      setPending(data.pending)
      setAudit(data.audit)
      setLinks((await getMeshLinks()).data.links)
      const proposals = (await getProposals()).data
      setGroups(proposals.groups)
      setYourSides(proposals.your_sides)
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

  // An entry is approved by each side: a company for its own entities, the group curator for shared vocabulary.
  const sideName = (side: string) => (side === 'group' ? 'Group curator' : names[side] ?? side)
  const companyName = (id?: string | null) => (!id ? '—' : id === 'group' ? 'Group' : names[id] ?? id)
  const checkChain = async () => {
    setChecking(true)
    setError('')
    try {
      setChain((await verifyAuditChains()).data)
    } catch (reason) {
      setError((reason as { response?: { data?: { detail?: string } } }).response?.data?.detail ?? 'The chains could not be checked.')
    } finally {
      setChecking(false)
    }
  }
  const reviewEntries = async (key: string, payload: { decision: 'approve' | 'reject'; ids?: string[]; application?: string; type?: string }) => {
    setBusyId(key)
    setError('')
    try {
      await reviewProposals(payload)
      await refresh()
    } catch (reason) {
      setError((reason as { response?: { data?: { detail?: string } } }).response?.data?.detail ?? 'The review failed.')
    } finally {
      setBusyId('')
    }
  }

  return (
    <div className="mesh-data-page">
      <header className="mesh-page-heading"><div><div className="mesh-eyebrow">Access and evidence</div><h1>Governance</h1><p>Approve or deny requests for access and for expert introductions, and read the decision log. The log holds no question text and no document text.</p></div><button type="button" className="mesh-outline-action" onClick={() => void refresh()} disabled={loading}><RefreshCw size={14} className={loading ? 'animate-spin' : ''} />Refresh</button></header>
      <div className="mesh-governance-notice"><ShieldAlert size={16} /><span><strong>Demo review.</strong> A decision made here stands in for the owner at the company and applies to the demo accounts only.</span></div>
      {error && <div role="alert" className="mesh-alert error">{error}</div>}
      <div className="mesh-tabs" role="tablist" aria-label="Governance views">
        <button type="button" role="tab" aria-selected={tab === 'requests'} className={tab === 'requests' ? 'active' : ''} onClick={() => setTab('requests')}><Clock3 size={15} />Approvals <span>{pending.length}</span></button>
        <button type="button" role="tab" aria-selected={tab === 'links'} className={tab === 'links' ? 'active' : ''} onClick={() => setTab('links')}><GitBranch size={15} />Links between companies <span>{links.filter((l) => l.status === 'proposed').length}</span></button>
        <button type="button" role="tab" aria-selected={tab === 'entries'} className={tab === 'entries' ? 'active' : ''} onClick={() => setTab('entries')}><ListChecks size={15} />Application entries <span>{groups.reduce((n, g) => n + g.counts.proposed, 0)}</span></button>
        <button type="button" role="tab" aria-selected={tab === 'audit'} className={tab === 'audit' ? 'active' : ''} onClick={() => setTab('audit')}><Fingerprint size={15} />Decision log <span>{audit.length}</span></button>
      </div>
      {loading && <div className="mesh-alert pending"><LoaderCircle size={16} className="animate-spin" />Loading node-local governance records…</div>}
      {!loading && tab === 'requests' && <section className="governance-list">
        {pending.map((item) => <article className="governance-request" key={item.request_id}>
          <div className="governance-request-heading"><span className="governance-request-id">{item.request_id}</span><span className="mesh-result-state warning">Pending</span><span className="governance-node-label">{item.company}</span></div>
          <h2>{item.title}</h2>
          <div className="governance-request-meta"><span>Asked by {companyName(item.requester_company)}</span><span>{item.kind === 'intro' ? 'Introduction to an expert' : `Access: ${modeLabel(item.mode)}`}</span><span>Decided by the {item.owner_role}</span></div>
          <p>Purpose: {item.purpose.replace(/_/g, ' ')}</p>
          {item.target_id && <p>Expert profile {item.target_id}. After approval only the person who asked sees the name.</p>}
          {item.node_id === myCompany || actsForEveryOwner
            ? <div className="governance-request-actions"><button type="button" className="mesh-outline-action danger" disabled={busyId === item.request_id} onClick={() => void decide(item, 'deny')}><X size={14} />Deny</button><button type="button" className="mesh-primary-action" disabled={busyId === item.request_id} onClick={() => void decide(item, 'approve')}>{busyId === item.request_id ? <LoaderCircle size={14} className="animate-spin" /> : <Check size={14} />}Approve 24 hours</button></div>
            : <div className="governance-request-actions"><span className="mesh-result-state warning">Waiting for {item.company}</span></div>}
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
            <div className="governance-request-meta"><span>{link.source}</span><span>{link.target}</span>{link.confidence != null && link.confidence < 1 && <span>Found by text extraction, confidence {link.confidence}</span>}</div>
            {link.status === 'proposed' && <div className="governance-request-actions">{(link.sides ?? []).map((side) => approved.has(side)
              ? <span key={side} className="mesh-result-state success">{names[side] ?? side} approved</span>
              : side === myCompany
                ? <span key={side} className="governance-request-actions">
                    <button type="button" className="mesh-outline-action danger" disabled={busyId === `${link.id}-${side}`} onClick={() => void reviewLink(link, side, 'reject')}><X size={14} />Reject for {names[side] ?? side}</button>
                    <button type="button" className="mesh-primary-action" disabled={busyId === `${link.id}-${side}`} onClick={() => void reviewLink(link, side, 'approve')}><Check size={14} />Approve for {names[side] ?? side}</button>
                  </span>
                : <span key={side} className="mesh-result-state warning">Waiting for {names[side] ?? side}</span>)}</div>}
          </article>
        })}
        {!links.length && <div className="ask-empty-results">No links between companies.</div>}
      </section>}
      {!loading && tab === 'entries' && <section className="governance-list">
        <p className="mesh-panel-footnote">Links an application proposed between its own vocabulary and the companies' data, for example an asset of Snap and Score that belongs to an asset family. A link is used in answers only after both ends approve it. A company approves the end in its own data, and the group curator approves the end in the shared vocabulary. Each card shows the entries of one kind and how many still wait. Your buttons decide only the entries that wait for your side.</p>
        {groups.map((group) => {
          const key = `${group.application}:${group.type}`
          const mine = group.sides.filter((side) => yourSides.includes(side)).map(sideName).join(' and ')
          const words = group.type.replace(/_/g, ' ').toLowerCase()
          return <article className="governance-request" key={key}>
            <div className="governance-request-heading"><span className="proposal-app">{group.name}</span><span className={`mesh-result-state ${group.counts.proposed ? 'warning' : 'success'}`}>{group.counts.proposed ? `${group.counts.proposed} proposed` : 'All reviewed'}</span><span className="governance-node-label">{group.entries.length} entries</span></div>
            <h2>{words.charAt(0).toUpperCase() + words.slice(1)}{group.from_types?.length ? `: ${group.from_types.map(typeWords).join(', ')} → ${(group.to_types ?? []).map(typeWords).join(', ')}` : ''}</h2>
            <div className="governance-request-meta"><span>{group.counts.proposed ? 'Needs approval from' : 'Reviewed by'} {group.sides.map(sideName).join(', ')}</span><span>{group.counts.approved} approved</span><span>{group.counts.rejected} rejected</span></div>
            <div className="governance-request-actions">
              <button type="button" className="mesh-outline-action" aria-expanded={openGroup === key} onClick={() => setOpenGroup(openGroup === key ? '' : key)}>{openGroup === key ? 'Hide entries' : 'Show entries'}</button>
              {group.pending_for_you > 0 && <>
                <button type="button" className="mesh-outline-action danger" disabled={busyId === key} onClick={() => void reviewEntries(key, { decision: 'reject', application: group.application, type: group.type })}><X size={14} />Reject {group.pending_for_you} for {mine}</button>
                <button type="button" className="mesh-primary-action" disabled={busyId === key} onClick={() => void reviewEntries(key, { decision: 'approve', application: group.application, type: group.type })}>{busyId === key ? <LoaderCircle size={14} className="animate-spin" /> : <Check size={14} />}Approve {group.pending_for_you} for {mine}</button>
              </>}
            </div>
            {openGroup === key && <ul className="proposal-entries">
              {group.entries.map((entry) => <li key={entry.id}>
                <span>{entry.source_title} → {entry.target_title}</span>
                <span className={`mesh-result-state ${entry.status === 'approved' ? 'success' : entry.status === 'rejected' ? 'danger' : 'warning'}`}>{entry.status}</span>
                {entry.you_review.length > 0 && <span className="proposal-entry-actions">
                  <button type="button" className="mesh-outline-action danger" disabled={busyId === entry.id} onClick={() => void reviewEntries(entry.id, { decision: 'reject', ids: [entry.id] })}><X size={14} />Reject</button>
                  <button type="button" className="mesh-outline-action" disabled={busyId === entry.id} onClick={() => void reviewEntries(entry.id, { decision: 'approve', ids: [entry.id] })}><Check size={14} />Approve</button>
                </span>}
              </li>)}
            </ul>}
          </article>
        })}
        {!groups.length && <div className="ask-empty-results">No application has proposed entries.</div>}
      </section>}
      {!loading && tab === 'audit' && <section className="mesh-section-panel audit-panel">
        <div className="mesh-audit-heading"><div><h2>Node decision ledger</h2><p>Each entry records a decision and its ids. Question text and document text are not recorded. Each node ties every entry to the one before it, so a changed, added or removed entry shows as a break when you press Check the chains.</p></div>
          <button type="button" className="mesh-outline-action" onClick={() => void checkChain()} disabled={checking}>{checking ? <LoaderCircle size={14} className="animate-spin" /> : <Fingerprint size={14} />}Check the chains</button></div>
        {chain && <div className={`mesh-alert ${chain.valid ? 'note' : 'error'}`}>{chain.valid
          ? (chain.nodes.length ? `The chain is intact at ${chain.nodes.length === 1 ? chain.nodes[0].company : `all ${chain.nodes.length} nodes`} (${chain.nodes.reduce((n, c) => n + c.entries, 0)} entries).` : 'There is no ledger of your company to check.')
          : `The chain is broken at ${chain.nodes.filter((c) => !c.valid).map((c) => c.company).join(', ')}. The other nodes are intact.`}</div>}
        {audit.length ? <div className="mesh-audit-table-wrap"><table className="mesh-audit-table"><thead><tr><th>Time</th><th>Decision</th><th>Node of</th><th>Asked by</th><th>Action</th><th>Datapoint</th><th>Rule applied</th></tr></thead><tbody>{audit.map((entry, index) => <tr key={`${entry.trace_id}-${index}`}><td>{entry.timestamp ? formatDateTime(entry.timestamp, true) : '—'}</td><td><span className={`mesh-result-state ${decisionTone(entry.decision)}`}>{decisionLabel(entry.decision)}</span></td><td>{companyName(entry.node_id)}</td><td>{companyName(entry.caller_company)}</td><td>{actionWords(entry.action)}</td><td>{entry.datapoint_id}{entry.datapoint_title ? ` · ${entry.datapoint_title}` : entry.datapoint_hidden ? ` · kept at ${companyName(entry.node_id)}` : ''}</td><td title={entry.rule_id}>{ruleMeaning(entry.rule_id) || entry.rule_id}</td></tr>)}</tbody></table></div> : <div className="ask-empty-results">No decisions recorded yet.</div>}
      </section>}
      <div className="mesh-page-footnote"><FileSearch size={14} />The node of each company keeps its own approvals and its own decision log.</div>
    </div>
  )
}
