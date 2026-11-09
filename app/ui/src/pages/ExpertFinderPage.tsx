import { useState } from 'react'
import { ArrowRight, LoaderCircle, Search, UserRound, UserRoundPlus } from 'lucide-react'
import { searchExperts, requestExpertIntroduction } from '../services/api'
import type { ExpertMatch } from '../services/api'
import { useMeshScope } from '../context/MeshScopeContext'
import { useAuth } from '../auth/AuthContext'

const EXAMPLE_QUERY = 'natural rubber quality, integration, or estate operations'

export default function ExpertFinderPage() {
  const { user } = useAuth()
  const { selectedNodes } = useMeshScope()
  const [query, setQuery] = useState('')
  const [purpose, setPurpose] = useState<'problem_solving' | 'compliance' | 'bid_support'>('problem_solving')
  const [experts, setExperts] = useState<ExpertMatch[]>([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [requested, setRequested] = useState<string[]>([])

  const search = async () => {
    if (!query.trim() || !selectedNodes.length || busy) return
    setBusy(true)
    setError('')
    try {
      const { data } = await searchExperts({ query: query.trim(), purpose, nodes: selectedNodes })
      setExperts(data.experts)
    } catch (reason) {
      setError((reason as { response?: { data?: { detail?: string } } }).response?.data?.detail ?? 'Expert search failed. Check the selected subsidiary nodes.')
    } finally {
      setBusy(false)
    }
  }

  const requestIntro = async (expert: ExpertMatch) => {
    const nodeId = expert.node_id
    if (!nodeId) return
    try {
      await requestExpertIntroduction(nodeId, {
        expert_id: expert.expert_id,
        purpose,
        justification: `Request an introduction to discuss ${expert.skills.slice(0, 2).join(' and ')} for a cross-subsidiary pilot question.`,
      })
      setRequested((items) => [...items, expert.expert_id])
    } catch (reason) {
      setError((reason as { response?: { data?: { detail?: string } } }).response?.data?.detail ?? 'Could not request the introduction.')
    }
  }

  return (
    <div className="mesh-data-page">
      <header className="mesh-page-heading">
        <div><div className="mesh-eyebrow">People and expertise</div><h1>Expert Finder</h1><p>Search opted-in expertise across the subsidiaries in your current scope.</p></div>
      </header>
      <section className="mesh-section-panel expert-search-panel">
        <label htmlFor="expert-query">Describe the experience you need</label>
        <div className="expert-search-row"><div className="expert-query-wrap"><Search size={16} /><input id="expert-query" value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={(event) => event.key === 'Enter' && void search()} placeholder={EXAMPLE_QUERY} /></div>
          <label className="expert-purpose">Purpose<select value={purpose} onChange={(event) => setPurpose(event.target.value as typeof purpose)}><option value="problem_solving">Problem solving</option><option value="compliance">Compliance</option><option value="bid_support">Bid support</option></select></label>
          <button type="button" className="mesh-primary-action" onClick={() => void search()} disabled={busy || !query.trim()}>{busy ? <LoaderCircle size={15} className="animate-spin" /> : <Search size={15} />}Search experts</button>
        </div>
        <p className="mesh-panel-footnote">Only opted-in role, skill and evidence fields are searchable. Names require an approved introduction.</p>
      </section>
      {error && <div className="mesh-alert error">{error}</div>}
      {experts.length > 0 && <div className="expert-results-heading"><h2>Matched expertise</h2><span>{experts.length} opted-in {experts.length === 1 ? 'profile' : 'profiles'}</span></div>}
      <section className="expert-results">
        {experts.map((expert) => <article className="expert-result" key={`${expert.expert_id}-${expert.company}`}>
          <div className="expert-avatar"><UserRound size={19} /></div>
          <div className="expert-result-main"><div className="expert-role">{expert.role}</div><div className="expert-company">{expert.company}{expert.company === user?.company_name && ' · your company'}</div>
            <div className="expert-skills">{expert.skills.map((skill) => <span key={skill}>{skill}</span>)}</div>
            {expert.evidence.length > 0 && <div className="expert-evidence">Evidence: {(expert.evidence_titles?.length ? expert.evidence_titles : expert.evidence).join(' · ')}</div>}
          </div>
          <div className="expert-result-action">
            {expert.name && <span className="expert-revealed-name">{expert.name}</span>}
            {requested.includes(expert.expert_id) ? <span className="mesh-result-state success">Introduction requested</span> : <button type="button" className="mesh-outline-action" onClick={() => void requestIntro(expert)}><UserRoundPlus size={14} />Request intro <ArrowRight size={13} /></button>}
          </div>
        </article>)}
        {!busy && query && experts.length === 0 && !error && <div className="ask-empty-results">No opted-in profiles matched. Try a related skill or another subsidiary scope.</div>}
        {!query && <div className="expert-empty-state"><UserRound size={22} /><strong>Search the mesh’s opted-in experts</strong><span>Matches come from consented profiles maintained by each subsidiary.</span></div>}
      </section>
    </div>
  )
}
