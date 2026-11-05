import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import type { CSSProperties } from 'react'
import { AlertTriangle, ArrowUpRight, CircleCheck, Clock3, GitBranch, LoaderCircle, LockKeyhole, Send, ServerOff } from 'lucide-react'
import { getMeshNodes, queryMesh } from '../services/api'
import type { CompanyId, MeshPurpose, MeshQueryResponse } from '../services/api'
import { useMeshScope } from '../context/MeshScopeContext'

const NODES: { id: CompanyId; label: string; tone: string }[] = [
  { id: 'ceat', label: 'CEAT', tone: '#e8590c' },
  { id: 'kec', label: 'KEC International', tone: '#1c7ed6' },
  { id: 'zensar', label: 'Zensar', tone: '#7048e8' },
  { id: 'harrisons', label: 'Harrisons Malayalam', tone: '#5c940d' },
]

const EXAMPLE_QUESTION = "What rubber-compound learnings from CEAT could reduce Harrisons Malayalam's latex spoilage?"

const LINK_LABELS: Record<string, string> = {
  ADDRESSES_GAP: 'addresses the gap in',
  CORROBORATES: 'supports',
  CONFLICTS_WITH: 'conflicts with',
  SUPERSEDES: 'replaces',
}

const ROUTE_LABELS: Record<string, string> = {
  graph: 'Routed by the mesh graph',
  classifier: 'Routed from node profiles',
  named: 'Routed to the companies named',
  user: 'Nodes you chose',
  none: 'No node matched',
}

export default function AskPage() {
  const [question, setQuestion] = useState(EXAMPLE_QUESTION)
  const { selectedNodes, setSelectedNodes } = useMeshScope()
  const [purpose, setPurpose] = useState<MeshPurpose>('problem_solving')
  const [chooseNodes, setChooseNodes] = useState(false)
  const [nodeList, setNodeList] = useState(NODES)
  useEffect(() => {
    getMeshNodes()
      .then(({ data }) => setNodeList(data.nodes.map((node) => ({ id: node.node_id, label: node.company, tone: NODES.find((item) => item.id === node.node_id)?.tone ?? '#68756d' }))))
      .catch(() => undefined)
  }, [])
  const displayNode = (id: string) => nodeList.find((node) => node.id === id)?.label ?? id
  const [response, setResponse] = useState<MeshQueryResponse | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const toggleNode = (node: CompanyId) => {
    setSelectedNodes(selectedNodes.includes(node)
      ? selectedNodes.filter((id) => id !== node)
      : [...selectedNodes, node])
  }

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (!question.trim() || (chooseNodes && !selectedNodes.length) || busy) return
    setBusy(true)
    setError('')
    setResponse(null)
    try {
      const { data } = await queryMesh({ question: question.trim(), nodes: chooseNodes ? selectedNodes : undefined, purpose })
      setResponse(data)
    } catch (requestError: unknown) {
      const message = (requestError as { response?: { data?: { detail?: string } } })
        .response?.data?.detail
      setError(typeof message === 'string' ? message : 'Could not reach the mesh. Check that the selected subsidiary nodes are running.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="ask-page">
      <header className="mesh-page-heading">
        <div>
          <div className="mesh-eyebrow">Cross-subsidiary query</div>
          <h1>Ask NeuralMesh</h1>
          <p>Ask in your own words. Selected subsidiary nodes return only policy-approved evidence.</p>
        </div>
        {response && <span className={`mesh-result-state ${response.status === 'ok' ? 'success' : 'warning'}`}>{response.status === 'ok' ? 'All routed nodes responded' : response.status === 'partial' ? 'Partial response' : 'No node matched. Choose the nodes to ask.'}</span>}
      </header>

      <form onSubmit={submit} className="ask-composer">
        <div className="ask-composer-main">
          <label htmlFor="mesh-question">Question</label>
          <textarea id="mesh-question" value={question} onChange={(event) => setQuestion(event.target.value)} rows={3} maxLength={2000} placeholder={EXAMPLE_QUESTION} />
          <div className="ask-field-meta"><span>Use any wording or domain combination</span><span>{question.length}/2000</span></div>

          <div className="ask-controls">
            <fieldset>
              <legend>
                <label className="ask-node-chip selected" style={{ '--node-tone': '#495057' } as CSSProperties}>
                  <input type="checkbox" checked={chooseNodes} onChange={() => setChooseNodes(!chooseNodes)} />
                  Choose nodes myself
                </label>
              </legend>
              {chooseNodes && <div className="ask-node-list">
                {nodeList.map((node) => {
                  const active = selectedNodes.includes(node.id)
                  return (
                      <label key={node.id} className={`ask-node-chip ${active ? 'selected' : ''}`} style={{ '--node-tone': node.tone } as CSSProperties}>
                      <input type="checkbox" checked={active} onChange={() => toggleNode(node.id)} />
                      <span className="ask-node-dot" />
                      {node.label}
                    </label>
                  )
                })}
              </div>}
            </fieldset>
            <div className="ask-submit-row">
              <label>Purpose
                <select value={purpose} onChange={(event) => setPurpose(event.target.value as typeof purpose)}>
                  <option value="problem_solving">Problem solving</option>
                  <option value="compliance">Compliance</option>
                  <option value="bid_support">Bid support</option>
                  <option value="learning">Learning</option>
                  <option value="career_mobility">Career mobility</option>
                </select>
              </label>
              <button type="submit" disabled={busy || !question.trim() || (chooseNodes && selectedNodes.length === 0)} className="ask-submit-button">
                {busy ? <LoaderCircle size={16} className="animate-spin" /> : <Send size={16} />}
                {busy ? 'Searching nodes' : 'Ask NeuralMesh'}
              </button>
            </div>
          </div>
        </div>
        <div className="ask-composer-foot">
          <LockKeyhole size={14} /> Each node applies its own exposure rules before evidence leaves its subsidiary.
        </div>
      </form>

      {error && <div role="alert" className="mesh-alert error"><AlertTriangle size={18} />{error}</div>}
      {busy && <div className="mesh-alert pending"><LoaderCircle size={18} className="animate-spin" />{chooseNodes ? `Requesting evidence from ${selectedNodes.length} independent node${selectedNodes.length === 1 ? '' : 's'}…` : 'Routing the question and requesting evidence…'}</div>}

      {response && (
        <div className="ask-results-grid">
          <section className="ask-results-section" aria-labelledby="evidence-heading">
            <div className="ask-section-heading"><h2 id="evidence-heading">Retrieved evidence</h2><span>{response.sources.length} sources · {new Set(response.sources.map((item) => String(item.node_id ?? String(item.doc_id ?? '').split(':')[0]))).size} companies</span></div>
            {response.routing.method && <div className="mesh-answer-panel"><div className="mesh-answer-title"><GitBranch size={13} /> {ROUTE_LABELS[response.routing.method] ?? response.routing.method}</div>
              <p>{(response.routing.subsidiaries ?? []).map(displayNode).join(', ') || 'None'}{response.routing.concepts?.length ? ` · ${response.routing.concepts.map((c) => response.routing.concept_labels?.[c] ?? c).join(', ')}` : ''}</p></div>}
            {response.answer
              ? <div className="mesh-answer-panel"><div className="mesh-answer-title">Answer{response.cached ? ' · reused' : ''}</div>{response.answer.split(/(?<=[.!?\]])\s+(?=[A-Z[])/).map((sentence, index) => <p key={index} className={sentence.startsWith('[NOT IN EVIDENCE]') ? 'ask-not-in-evidence' : ''}>{sentence}</p>)}</div>
              : response.answer_reason && <div className="mesh-alert note">{response.answer_reason}</div>}
            {response.omitted > 0 && <div className="mesh-alert note">Partial set: {response.omitted} {response.omitted === 1 ? 'item was' : 'items were'} left out for size or replaced by a newer version.</div>}
            {response.relationships.length > 0 && <div className="mesh-answer-panel"><div className="mesh-answer-title">Approved links</div>
              {response.relationships.map((link) => <p key={link.id}><b>{link.source_title ?? link.source}</b> {LINK_LABELS[link.type] ?? link.type} <b>{link.target_title ?? link.target}</b>{link.note ? ` · ${link.note}` : ''} <span className="ask-source-meta">({link.source} and {link.target})</span></p>)}</div>}
            {response.sources.length ? <div className="ask-source-list">
              {response.sources.map((source, index) => {
                const nodeId = String(source.node_id ?? String(source.doc_id ?? '').split(':')[0])
                return (
                    <article key={`${String(source.doc_id ?? index)}-${index}`} className="ask-source" style={{ '--node-tone': nodeList.find((node) => node.id === nodeId)?.tone ?? '#68756d' } as CSSProperties}>
                    <div className="ask-source-title-row">
                      <span className="ask-source-number">{index + 1}</span>
                      <div className="min-w-0 flex-1"><div className="ask-source-title">{String(source.title ?? source.citation ?? 'Cited source')}</div><div className="ask-source-meta">{displayNode(nodeId)} <span>·</span> {String(source.datapoint_id ?? 'SOURCE')}</div></div>
                      {Boolean(source.stale) && <span className="mesh-result-state warning">Stale</span>}
                    </div>
                    <p className="ask-source-text">{String(source.text ?? source.summary ?? '')}</p>
                    {typeof source.superseded_by === 'string' && <p className="ask-source-meta">Replaced by {source.superseded_by}</p>}
                    <div className="ask-source-footer"><span className="ask-mode-tag">{String(source.mode ?? 'approved summary')}</span><span className="ask-citation"><CircleCheck size={13} />{String(source.citation ?? 'Citation available')}</span>
                      {typeof source.doc_id === 'string' && <span title={source.doc_id} className="ask-source-ref"><ArrowUpRight size={13} />Source ref</span>}
                    </div>
                  </article>
                )
              })}
            </div> : <div className="ask-empty-results">No approved evidence was returned for this question.</div>}
          </section>

          <aside className="ask-side-column">
            {response.also_found.length > 0 && <section className="mesh-side-panel">
              <div className="mesh-side-heading"><h2>Also found</h2><span>{response.also_found.length}</span></div>
              <ul className="mesh-node-responses">{response.also_found.map((item) => <li key={item.evidence_id}><span className="mesh-response-copy"><strong>{item.title ?? item.evidence_id}</strong><small>{item.citation}</small></span></li>)}</ul>
            </section>}
            <section className="mesh-side-panel">
              <div className="mesh-side-heading"><h2>Node responses</h2><span>{response.node_results.length}</span></div>
              <ul className="mesh-node-responses">
                {response.node_results.map((node) => <li key={node.node_id}><span className={`mesh-response-icon ${node.status === 'ok' ? 'good' : 'bad'}`}>{node.status === 'ok' ? <CircleCheck size={15} /> : node.status.includes('UNAVAILABLE') ? <ServerOff size={15} /> : <AlertTriangle size={15} />}</span><span className="mesh-response-copy"><strong>{displayNode(node.node_id)}</strong><small>{node.status === 'ok' ? `${node.results.length} allowed · ${node.withheld.length} withheld` : node.status}</small></span><span className="mesh-response-latency"><Clock3 size={12} />Node</span></li>)}
              </ul>
            </section>
            {response.withheld.length > 0 && <section className="mesh-side-panel withheld-panel">
              <div className="mesh-side-heading"><h2><LockKeyhole size={15} />Withheld by policy</h2><span>{response.withheld.length}</span></div>
              <ul>{response.withheld.map((item, index) => <li key={`${String(item.evidence_id ?? index)}-${index}`}><strong>{String(item.title ?? item.datapoint ?? 'Restricted item')}</strong><small>{String(item.reason ?? item.rule_id ?? item.decision ?? 'Not available')}</small></li>)}</ul>
            </section>}
          </aside>
        </div>
      )}
    </div>
  )
}