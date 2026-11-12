import { useEffect, useState } from 'react'
import { ArrowRight, CheckCircle2, CircleHelp, LoaderCircle, Network, ShieldCheck } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { useMeshScope } from '../context/MeshScopeContext'
import { getDashboardSnapshot } from '../services/api'
import type { CompanyId, DashboardSnapshot } from '../services/api'
import { actionWords, decisionLabel, decisionTone, levelWords } from '../lib/format'

const NODES: { id: CompanyId; label: string; tone: string; level: string }[] = [
  { id: 'ceat', label: 'CEAT', tone: '#e8590c', level: 'L2 · Retrieval' },
  { id: 'kec', label: 'KEC International', tone: '#1c7ed6', level: 'L2 · Retrieval' },
  { id: 'zensar', label: 'Zensar', tone: '#7048e8', level: 'L2 · Retrieval' },
  { id: 'harrisons', label: 'Harrisons Malayalam', tone: '#5c940d', level: 'L1 · Summaries' },
]

export default function DashboardPage() {
  const { user } = useAuth()
  const { selectedNodes } = useMeshScope()
  const [snapshot, setSnapshot] = useState<DashboardSnapshot | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [questionsPerWeek, setQuestionsPerWeek] = useState(600)

  useEffect(() => {
    getDashboardSnapshot()
      .then(({ data }) => setSnapshot(data))
      .catch(() => setError('Live dashboard activity is unavailable. Check that the backend and subsidiary nodes are running.'))
      .finally(() => setLoading(false))
  }, [])

  const scopedNodes = snapshot?.nodes.filter((node) => selectedNodes.includes(node.node_id)) ?? []
  const nodeRows = snapshot?.nodes.length
    ? snapshot.nodes.map((node) => ({ id: node.node_id, label: node.company, tone: node.tone ?? NODES.find((item) => item.id === node.node_id)?.tone ?? '#68756d', level: node.level }))
    : NODES
  const companyName = (id: string) => (id === 'group' ? 'Group' : nodeRows.find((node) => node.id === id)?.label ?? id)
  const decisions = snapshot?.search_decisions ?? 0
  const allowedRate = decisions ? Math.round((snapshot?.allowed_decisions ?? 0) * 100 / decisions) : 0
  const estimatedMonthlyBenefit = questionsPerWeek * 4.3 * 0.55 * (40 / 60) * 1500 / 100000

  return (
    <div className="dashboard-page">
      <header className="mesh-page-heading">
        <div>
          <div className="mesh-eyebrow">Pilot overview</div>
          <h1>Group knowledge, connected</h1>
          <p>Subsidiaries retain their source systems. The mesh routes questions to their independent knowledge nodes.</p>
        </div>
        <Link to="/ask" className="mesh-primary-action">Ask the group <ArrowRight size={16} /></Link>
      </header>

      <section className="mesh-kpi-grid" aria-label="Pilot facts">
        <article className="mesh-kpi"><span className="mesh-kpi-icon green"><Network size={18} /></span><div><strong>{loading ? '…' : `${snapshot?.connected_nodes ?? 0}/${snapshot?.total_nodes ?? 4}`}</strong><span>Independent nodes online</span></div></article>
        <article className="mesh-kpi"><span className="mesh-kpi-icon coral"><ShieldCheck size={18} /></span><div><strong>0</strong><span>Source records copied to the centre</span>{(snapshot?.ingested_graphs ?? 0) > 0 && <span>{snapshot?.ingested_graphs} {snapshot?.ingested_graphs === 1 ? 'graph' : 'graphs'} ingested as JSON kept at the centre</span>}</div></article>
        <article className="mesh-kpi"><span className="mesh-kpi-icon gold"><CheckCircle2 size={18} /></span><div><strong>{selectedNodes.filter((id) => !snapshot?.nodes.find((node) => node.node_id === id)?.shared).length}</strong><span>Companies in your scope</span></div></article>
        <article className="mesh-kpi"><span className="mesh-kpi-icon teal"><CircleHelp size={18} /></span><div><strong>{loading ? '…' : snapshot?.pending_approvals ?? 0}</strong><span>Pending approvals</span></div></article>
      </section>

      <div className="dashboard-columns">
        <div className="dashboard-stack">
          <section className="mesh-section-panel">
            <div className="mesh-section-heading"><div><div className="mesh-eyebrow">Local knowledge nodes</div><h2>Pilot companies</h2></div><Link to="/nodes" className="mesh-text-link">Node details <ArrowRight size={14} /></Link></div>
            <div className="mesh-node-table" role="table" aria-label="Pilot company nodes">
              <div className="mesh-node-table-head" role="row"><span>Company</span><span>Node level</span><span>Health</span></div>
              {nodeRows.map((node) => {
                const live = snapshot?.nodes.find((item) => item.node_id === node.id)
                return <div className="mesh-node-table-row" role="row" key={node.id}><span className="mesh-company-name"><i style={{ backgroundColor: node.tone }} />{node.label}</span><span>{levelWords(live?.level ?? node.level)}</span><span className={`mesh-result-state ${live?.status === 'healthy' ? 'success' : 'warning'}`}>{loading ? 'Checking' : live?.status === 'healthy' ? 'Healthy' : 'Unavailable'}</span></div>
              })}
            </div>
            <p className="mesh-panel-footnote">Live MCP health and capability checks · {scopedNodes.length} companies in current scope</p>
          </section>
          <section className="mesh-section-panel"><div className="mesh-section-heading"><div><div className="mesh-eyebrow">Recent decisions</div><h2>Node activity</h2></div><Link to="/governance" className="mesh-text-link">Full decision log <ArrowRight size={14} /></Link></div>
            {loading && <div className="mesh-alert pending"><LoaderCircle size={15} className="animate-spin" />Loading recent activity</div>}
            {error && <div className="mesh-alert error">{error}</div>}
            {!loading && !error && <div className="dashboard-recent-list">{(snapshot?.recent_activity ?? []).slice(0, 5).map((event, index) => <div key={`${event.trace_id}-${index}`}><span className="dashboard-recent-dot" /><span className="dashboard-recent-company">{companyName(event.node_id)}</span><span className="dashboard-recent-action">{actionWords(event.action)} · {event.datapoint_id}{event.caller_company && event.caller_company !== event.node_id ? ` · asked by ${companyName(event.caller_company)}` : ''}</span><span className={`dashboard-recent-decision ${decisionTone(event.decision)}`}>{decisionLabel(event.decision)}</span></div>)}{!snapshot?.recent_activity.length && <p className="mesh-panel-footnote">No requests yet. Ask the CEAT–Harrisons pilot question to create the first activity.</p>}</div>}
          </section>
          <section className="mesh-section-panel"><div className="mesh-section-heading"><div><div className="mesh-eyebrow">Knowledge flow</div><h2>Search decisions by node</h2></div></div><div className="mesh-flow-bars">{nodeRows.map((node) => { const count = snapshot?.activity_by_node[node.id] ?? 0; const max = Math.max(1, ...Object.values(snapshot?.activity_by_node ?? {})); return <div key={node.id}><span>{node.label}</span><div><i style={{ width: `${count ? Math.max(4, count * 100 / max) : 0}%`, background: node.tone }} /></div><b>{count}</b></div> })}</div><p className="mesh-panel-footnote">Counts are derived from subsidiary-local decision audit entries; query text is never shown.</p></section>
        </div>

        <div className="dashboard-stack">
          <aside className="mesh-section-panel mesh-principle-panel">
            <div className="mesh-section-heading"><div><div className="mesh-eyebrow">Observed activity</div><h2>Decision outcomes</h2></div><span className="mesh-live-label"><i />From node audit ledgers</span></div>
            <div className="mesh-activity-kpi"><strong>{decisions}</strong><span>Search decisions recorded</span></div>
            <div className="mesh-outcome-bars"><div><span>Allowed</span><div className="mesh-outcome-track"><i className="allowed" style={{ width: `${allowedRate}%` }} /></div><b>{snapshot?.allowed_decisions ?? 0}</b></div><div><span>Blocked</span><div className="mesh-outcome-track"><i className="blocked" style={{ width: `${decisions ? 100 - allowedRate : 0}%` }} /></div><b>{snapshot?.blocked_decisions ?? 0}</b></div></div>
            <Link to="/governance" className="mesh-text-link">Review governance activity <ArrowRight size={14} /></Link>
          </aside>
          <section className="mesh-section-panel mesh-principle-panel"><div className="mesh-eyebrow">Current account</div><h2>{user?.display_name}</h2><p>{user?.company_name} · {user?.expert_profile ? `Opted-in expert · ${user.expert_profile.job_title}` : 'Group user'}</p><Link to="/experts" className="mesh-text-link">Explore experts <ArrowRight size={14} /></Link></section>
          <section className="mesh-section-panel roi-panel"><div className="mesh-eyebrow">Illustrative only</div><h2>Potential monthly value</h2><p>Scenario estimate, not measured POC savings.</p><label htmlFor="roi-volume">Questions per week <strong>{questionsPerWeek}</strong></label><input id="roi-volume" type="range" min="100" max="2000" step="50" value={questionsPerWeek} onChange={(event) => setQuestionsPerWeek(Number(event.target.value))} /><div className="roi-value">₹{Math.max(0, estimatedMonthlyBenefit - 12).toFixed(1)} L <span>estimated net/month</span></div><small>Assumptions: 55% useful · 40 minutes saved · ₹1,500/hour · ₹12 L monthly run cost.</small></section>
        </div>
      </div>
      <section className="mesh-ask-strip"><div><strong>What can the group help solve?</strong><span>Start with a question. Choose the companies it should reach.</span></div><Link to="/ask" aria-label="Ask NeuralMesh"><ArrowRight size={18} /></Link></section>
    </div>
  )
}
