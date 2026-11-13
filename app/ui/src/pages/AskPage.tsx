import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import type { FormEvent } from 'react'
import type { CSSProperties } from 'react'
import { AlertTriangle, Check, CircleCheck, GitBranch, LoaderCircle, LockKeyhole, Send, ServerOff, Waypoints } from 'lucide-react'
import { getMeshNodes, queryMesh } from '../services/api'
import type { CompanyId, EvidenceRecord, MeshPurpose, MeshQueryResponse } from '../services/api'
import { useMeshScope } from '../context/MeshScopeContext'
import { answerSentences, citationsAsNumbers, modeLabel, plainReason, plainWithheld, ruleMeaning } from '../lib/format'

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

// what an input of a context graph states, by the link that carries it
const STATED: Record<string, string> = { HAS_DECISION: 'Decision:', HAS_ACTION: 'Action:', HAS_RISK: 'Risk:' }
const ROUTE_LABELS: Record<string, string> = {
  graph: 'Routed by the mesh graph',
  classifier: 'Routed from node profiles',
  named: 'Routed to the companies named',
  own: 'No company matched the wording, so your own company was asked',
  context_graph: 'Routed by the context graph the question matches',
  user: 'Nodes you chose',
  none: 'No node matched',
}

const plural = (count: number, one: string, many: string) => `${count} ${count === 1 ? one : many}`
// The text of an aggregate record: one note line, then one group per line as "column value, column value".
const aggregateTable = (text: string) => {
  const [note, ...lines] = text.split('\n')
  const tail = lines.find((line) => line.endsWith('not shown.'))
  const groups = lines.filter((line) => line && line !== tail).map((line) => line.split(', ').map((cell) => {
    const at = cell.indexOf(' ')
    return at > 0 ? [cell.slice(0, at), cell.slice(at + 1)] : [cell, '']
  }))
  return { note, tail, columns: (groups[0] ?? []).map(([name]) => name.replace(/_/g, ' ')), rows: groups.map((cells) => cells.map(([, value]) => value)) }
}
// An answer sentence for the page: each citation as the number of its evidence card, and the marker of what the
// evidence does not hold in words.
const shownSentence = (sentence: string, documents: string[]) =>
  citationsAsNumbers(plainWithheld(sentence), documents).replace(/^\[NOT IN EVIDENCE\]\s*/, 'Not in the evidence: ')

const SOURCES_FIRST = 5 // source cards shown before View more

export default function AskPage() {
  const [params] = useSearchParams()
  const [question, setQuestion] = useState(params.get('q') || EXAMPLE_QUESTION)
  const { selectedNodes, setSelectedNodes } = useMeshScope()
  const [purpose, setPurpose] = useState<MeshPurpose>('problem_solving')
  const [chooseNodes, setChooseNodes] = useState(false)
  const [allSources, setAllSources] = useState(false) // every source card is shown. The first 5 show until View more is pressed
  const [nodeList, setNodeList] = useState(NODES)
  useEffect(() => {
    getMeshNodes()
      .then(({ data }) => setNodeList(data.nodes.map((node) => ({ id: node.node_id, label: node.company, tone: node.tone ?? NODES.find((item) => item.id === node.node_id)?.tone ?? '#68756d' }))))
      .catch(() => undefined)
  }, [])
  const displayNode = (id: string) => nodeList.find((node) => node.id === id)?.label ?? id
  const [response, setResponse] = useState<MeshQueryResponse | null>(null)
  // the evidence cards: the nodes' search results, then the grouped figures computed for the question
  const aggregates = response?.evidence.filter((item) => item.kind === 'aggregate') ?? []
  const sourceIds = new Set((response?.sources ?? []).map((item) => String(item.doc_id ?? '').split('#')[0]))
  // summaries reached through an approved link come back as evidence only, so they get a card too
  const linked = response?.evidence.filter((item) => item.kind === 'summary' && !sourceIds.has(item.evidence_id.split('#')[0]) && !sourceIds.has(String(item.document ?? ''))) ?? []
  const asCard = (item: EvidenceRecord, extra: Record<string, unknown>) => ({ ...item, doc_id: item.evidence_id, node_id: item.node, datapoint_id: item.datapoint?.split(':')[1], ...extra })
  const cards: Record<string, unknown>[] = response
    ? [...response.sources, ...linked.map((item) => asCard(item, {})), ...aggregates.map((item) => asCard(item, { aggregate: true }))]
    : []
  const seconds = response ? response.steps.reduce((sum, step) => sum + step.ms, 0) / 1000 : 0
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
    setAllSources(false)
    try {
      const { data } = await queryMesh({ question: question.trim(), nodes: chooseNodes ? selectedNodes : undefined, purpose })
      setResponse(data)
      if (data.routing.method === 'none') setChooseNodes(true)  // nothing matched: the company list opens for a choice
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
          <p>Ask in your own words. Each company answers only with what its sharing rules allow.</p>
        </div>
        {response && <span className={`mesh-result-state ${response.status === 'ok' ? 'success' : 'warning'}`}>{response.status === 'ok' ? 'All routed nodes responded' : response.status === 'partial' ? 'Partial response' : 'No node matched. Choose the nodes to ask.'}</span>}
      </header>

      <form onSubmit={submit} className="ask-composer">
        <div className="ask-composer-main">
          <label htmlFor="mesh-question">Question</label>
          <textarea id="mesh-question" value={question} onChange={(event) => setQuestion(event.target.value)} rows={3} maxLength={2000} placeholder={EXAMPLE_QUESTION} />
          <div className="ask-field-meta"><span>Ask about one topic or several</span><span>{question.length}/2000</span></div>

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
                      {active ? <Check size={13} className="ask-node-check" /> : <span className="ask-node-dot" />}
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
          <LockKeyhole size={14} /> The node of each company checks its own sharing rules before anything is sent out.
        </div>
      </form>

      {error && <div role="alert" className="mesh-alert error"><AlertTriangle size={18} />{error}</div>}
      {busy && <div className="mesh-alert pending"><LoaderCircle size={18} className="animate-spin" />{chooseNodes ? `Requesting evidence from ${selectedNodes.length} independent node${selectedNodes.length === 1 ? '' : 's'}…` : 'Routing the question and requesting evidence…'}</div>}

      {response && (
        <div className="ask-results-grid">
          <section className="ask-results-section" aria-labelledby="evidence-heading">
            <div className="ask-section-heading"><h2 id="evidence-heading">Retrieved evidence</h2><span>{plural(cards.length, 'source', 'sources')} · {plural(new Set(cards.map((item) => String(item.node_id ?? String(item.doc_id ?? '').split(':')[0]))).size, 'company', 'companies')}</span></div>
            {response.routing.method && <div className="mesh-answer-panel"><div className="mesh-answer-title"><GitBranch size={13} /> {ROUTE_LABELS[response.routing.method] ?? response.routing.method}</div>
              <p>{(response.routing.subsidiaries ?? []).map(displayNode).join(', ') || 'None'}{response.routing.concepts?.length ? ` · topics: ${response.routing.concepts.map((c) => response.routing.concept_labels?.[c] ?? c).join(', ')}` : ''}</p></div>}
            {response.routing.question_check && response.routing.question_check.intent !== 'clear' && response.routing.question_check.suggestions.length > 0 && <div className="mesh-answer-panel"><div className="mesh-answer-title">Did you mean</div>
              <div className="ask-suggestions">{response.routing.question_check.suggestions.map((q) => <button type="button" key={q} className="mesh-outline-action" onClick={() => { setQuestion(q); window.scrollTo({ top: 0, behavior: 'smooth' }) }}>{q}</button>)}</div></div>}
            {response.routing.question_check?.intent === 'clear' && response.routing.question_check.understood_as && response.routing.question_check.understood_as.toLowerCase() !== response.question.toLowerCase() && <div className="mesh-alert note">Understood as: {response.routing.question_check.understood_as}</div>}
            {(response.routing.context_graphs?.length ?? 0) > 0 && <div className="mesh-answer-panel"><div className="mesh-answer-title"><Waypoints size={13} /> Context graphs this question is about</div>
              {response.routing.context_graphs!.map((g) => <p key={g.id}><strong>{g.name}</strong>{g.chosen ? (g.why ? ` · ${g.why}` : '') : ' · also touched by the question'}<br /><span className="ask-graph-description">{g.description}</span>
                {g.answer && <span className="ask-graph-answer"><b>From this graph:</b> {g.answer}</span>}
                {(g.found?.links.length ?? 0) > 0 && <span className="ask-graph-links">{g.found!.links.map((l, i) => STATED[l.type] ? <span key={i}><em>{STATED[l.type]}</em> {l.target} <span className="ask-graph-description">({l.source})</span></span> : <span key={i}>{l.source} <em>{l.type.toLowerCase().replace(/_/g, ' ')}</em> {l.target}</span>)}</span>}</p>)}</div>}
            {response.answer
              ? <div className="mesh-answer-panel"><div className="mesh-answer-title">Answer · {seconds.toFixed(1)} s{response.cached ? ' · reused from the same question asked before' : ''}</div>{answerSentences(response.answer).map((sentence, index) => <p key={index} className={sentence.startsWith('[NOT IN EVIDENCE]') ? 'ask-not-in-evidence' : ''}>{shownSentence(sentence, cards.map((s) => String(s.doc_id ?? '')))}</p>)}</div>
              : response.answer_reason && <div className="mesh-alert note">{response.answer_reason}</div>}
            {response.omitted > 0 && <div className="mesh-alert note">{response.omitted} {response.omitted === 1 ? 'item is' : 'items are'} not shown. An item is left out when the answer has no room for it or when a newer version replaced it.</div>}
            {response.relationships.length > 0 && <div className="mesh-answer-panel"><div className="mesh-answer-title">Approved links</div>
              {response.relationships.map((link) => <p key={link.id} title={`${link.source} and ${link.target}`}><b>{link.source_title ?? link.source}</b> {LINK_LABELS[link.type] ?? link.type} <b>{link.target_title ?? link.target}</b>{link.note ? ` · ${link.note}` : ''}</p>)}</div>}
          </section>

          <aside className="ask-side-column">
            {response.also_found.length > 0 && <section className="mesh-side-panel">
              <div className="mesh-side-heading"><h2>Found, not used in the answer</h2><span>{response.also_found.length}</span></div>
              <ul className="mesh-node-responses">{response.also_found.map((item) => <li key={item.evidence_id}><span className="mesh-response-copy"><strong title={item.title ?? item.evidence_id}>{item.title ?? item.evidence_id}</strong><small>{item.citation}</small></span></li>)}</ul>
            </section>}
            <section className="mesh-side-panel">
              <div className="mesh-side-heading"><h2>Node responses</h2><span>{response.node_results.length}</span></div>
              <ul className="mesh-node-responses">
                {response.node_results.map((node) => <li key={node.node_id}><span className={`mesh-response-icon ${node.status === 'ok' ? 'good' : 'bad'}`}>{node.status === 'ok' ? <CircleCheck size={15} /> : node.status.includes('UNAVAILABLE') ? <ServerOff size={15} /> : <AlertTriangle size={15} />}</span><span className="mesh-response-copy"><strong>{displayNode(node.node_id)}</strong><small>{node.status === 'ok' ? `${node.results.length} allowed · ${node.withheld.length} withheld` : node.status}</small></span></li>)}
              </ul>
            </section>
            {response.withheld.length > 0 && <section className="mesh-side-panel withheld-panel">
              <div className="mesh-side-heading"><h2><LockKeyhole size={15} />Withheld by policy</h2><span>{response.withheld.length}</span></div>
              <ul>{response.withheld.map((item, index) => <li key={`${String(item.evidence_id ?? index)}-${index}`}><strong>{String(item.title ?? item.datapoint ?? 'Restricted item')}</strong><small>{plainReason(String(item.reason ?? '')) || ruleMeaning(String(item.rule_id ?? '')) || 'Not available'}</small></li>)}</ul>
            </section>}
          </aside>
          <div className="ask-sources-wide">{/* the sources use the whole width of the page, below the answer and the side panels */}
            {cards.length ? <div className="ask-source-list">
              {cards.slice(0, allSources ? cards.length : SOURCES_FIRST).map((source, index) => {
                const nodeId = String(source.node_id ?? String(source.doc_id ?? '').split(':')[0])
                const table = source.aggregate ? aggregateTable(String(source.text ?? '')) : null
                return (
                    <article key={`${String(source.doc_id ?? index)}-${index}`} className="ask-source" style={{ '--node-tone': nodeList.find((node) => node.id === nodeId)?.tone ?? '#68756d' } as CSSProperties}>
                    <div className="ask-source-title-row">
                      <span className="ask-source-number">{index + 1}</span>
                      <div className="min-w-0 flex-1"><div className="ask-source-title">{String(source.title ?? source.citation ?? 'Cited source')}</div><div className="ask-source-meta">{displayNode(nodeId)} <span>·</span> {String(source.datapoint_id ?? 'SOURCE')}</div></div>
                      {Boolean(source.stale) && <span className="mesh-result-state warning">Stale</span>}
                    </div>
                    {table
                      ? <><p className="ask-source-text">{table.note}</p>
                        <div className="ask-aggregate-wrap"><table className="ask-aggregate-table"><thead><tr>{table.columns.map((column) => <th key={column}>{column}</th>)}</tr></thead>
                          <tbody>{table.rows.map((row, rowIndex) => <tr key={rowIndex}>{row.map((value, cellIndex) => <td key={cellIndex}>{value}</td>)}</tr>)}</tbody></table></div>
                        {table.tail && <p className="ask-source-text">{table.tail}</p>}</>
                      : <p className="ask-source-text">{String(source.text ?? source.summary ?? '')}</p>}
                    {typeof source.superseded_by === 'string' && <p className="ask-source-meta">Replaced by {source.superseded_by}</p>}
                    <div className="ask-source-footer"><span className="ask-mode-tag" title={`Shared as: ${String(source.mode ?? 'SUM')}`}>{source.aggregate ? 'Grouped figures, computed now' : modeLabel(String(source.mode ?? 'SUM'))}</span><span className="ask-citation"><CircleCheck size={13} />{String(source.citation ?? 'Citation available')}</span>
                    </div>
                  </article>
                )
              })}
              {cards.length > SOURCES_FIRST && <button type="button" className="mesh-outline-action ask-source-more" aria-expanded={allSources} onClick={() => setAllSources((v) => !v)}>{allSources ? 'View fewer' : `View more (${cards.length - SOURCES_FIRST})`}</button>}
            </div> : <div className="ask-empty-results">No approved evidence was returned for this question.</div>}
          </div>
        </div>
      )}
    </div>
  )
}