import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Braces, Check, Copy, Download, FilePlus2, FileUp, FolderUp, LoaderCircle, Pencil, RefreshCw, Upload, X, Search, Trash2, Waypoints } from 'lucide-react'
import { useAuth } from '../auth/AuthContext'
import MeshGraphExplorer, { TYPE_COLOURS } from '../components/MeshGraphExplorer'
import { addUpload, addUploads, checkGraph, checkUploads, clearContextGraph, decideLink, describeGraph, downloadContextGraph, dropContextGraph, dropIngestedGraph, getContextGraph, getGraphEntity, getIngestedGraph, getIngestedGraphs, getIngestedGraphView, getIngestSample, getMeshNodes, getGraphTemplate, getUploadItems, getUploads, ingestGraph, keepInput, removeUpload, renderJsonTemplate, searchGraph, suggestUpload } from '../services/api'
import type { BatchPlan, BatchResult, CompanyId, ContextGraphSummary, GraphDescription, ExportFormat, UploadSuggestion, ContextGraphView, GraphEntity, GraphSearchResult, IngestedGraphSummary, IngestRefusal, IngestResult, MeshNodeInfo, NewItemArea, UploadItem, UploadRecord } from '../services/api'
import { formatDateTime, linkWords, sharingWords, typeWords } from '../lib/format'

type Tab = 'inputs' | 'upload'
interface Focus { graph: string; doc: string | null }
const KIND_WORDS: Record<string, string> = {
  sop: 'Procedure', rca: 'Root cause analysis', playbook: 'Playbook', post_mortem: 'Post-mortem', standard: 'Standard', report: 'Report',
  policy: 'Policy', wiki: 'Wiki page', aggregate: 'Aggregate figures', note: 'Note', study_material: 'Study material', role_profile: 'Role profile', other: 'Other',
}
const NEW_ITEM = 'new' // the value of the Catalogue item choice that names a new item
const MATCH_WORDS: Record<string, string> = { phrase: 'named in the text', words: 'all its words in the text', tag: 'from a tag' }
const FORMAT_WORDS: Record<string, string> = { json: 'Structured JSON', graphml: 'GraphML (for graph tools)', csv: 'CSV (one row per entity and link)', pack: 'Knowledge pack (the documents)' }
const NEW_GRAPH = 'new' // the context graph choice that opens a new graph with the name typed
const REVEAL_ALL_UP_TO = 40 // entities drawn at once. A larger context graph opens from its companies and items, as the mesh graph does
const START_MOST_LINKED = 15 // a larger ingested graph opens from its most linked nodes, since its types are the person's own
const SEARCH_MIN = 2 // letters typed before the graph is searched as well as the list
const SEARCH_PAUSE_MS = 400 // the pause in typing after which the graph is searched, so not every letter asks the server

const detail = (reason: unknown, fallback: string) => (reason as { response?: { data?: { detail?: string } } }).response?.data?.detail ?? fallback
const companyOf = (u: UploadRecord) => u.company ?? u.node_id.toUpperCase()
const kindOf = (u: UploadRecord) => (u.document.kind === 'other' && u.document.kind_label) || KIND_WORDS[u.document.kind] || u.document.kind
const itemOf = (u: UploadRecord) => u.sharing.item_title ?? u.document.datapoint.split(':')[1]
const statusOf = (u: UploadRecord) => (u.status === 'removed' ? `Removed ${u.removed ? formatDateTime(u.removed.at) : ''}` : u.in_graph ? 'In the graph' : 'Not in the graph yet')
const words = (u: UploadRecord) => [u.document.title, u.document.id, u.upload.file, companyOf(u), itemOf(u), u.document.datapoint, kindOf(u), u.document.tags.join(' '),
  u.document.summary ?? '', u.context_graph.name, u.status === 'removed' ? 'removed' : ''].join(' ').toLowerCase()
const matches = (text: string, q: string) => q.toLowerCase().split(/\s+/).filter(Boolean).every((w) => text.includes(w))
const stampOf = (g: IngestedGraphSummary) => g.updated ?? g.created
// a graph loaded from the JSON of an uploaded graph that is listed: it is shown under that graph, never as a row of its own
const correctionOf = (g: IngestedGraphSummary, graphs: ContextGraphSummary[]) => Boolean(g.corrects && graphs.some((u) => u.id === g.corrects))
const entityCompany = (e: { company?: string | null; subsidiary?: string | null }) => e.company ?? (e.subsidiary ? e.subsidiary.toUpperCase() : '')
const linkCount = (r: GraphSearchResult) => { const n = Object.values(r.connections).reduce((sum, c) => sum + c, 0); return `${n} ${n === 1 ? 'link' : 'links'}` }
const saveJson = (data: unknown, name: string) => {
  const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }))
  Object.assign(document.createElement('a'), { href: url, download: name }).click()
  URL.revokeObjectURL(url)
}
const JSON_FILE = /\.json$/i
// a graph JSON goes to the check and ingest, any other file is read as a document. A .json file that is not valid JSON
// is taken as a graph JSON, so the place to fix is shown
const isGraphJson = (text: string) => {
  try { const d = JSON.parse(text); return Boolean(d) && typeof d === 'object' && !Array.isArray(d) && ['nodes', 'edges', 'relationships'].some((k) => k in d) } catch { return true }
}
const fileNameOf = (name: string) => name.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '') || 'graph'
// the three most linked nodes and their neighbours, up to START_MOST_LINKED, so the first drawing shows links
// what a larger uploaded graph opens with: its company, item, inputs and topics, and the things most linked in it. The
// rest opens with Show all, or by a double-click on a point
const KEY_THINGS = 12
const STATEMENT_KINDS = ['Decision', 'Action', 'Risk'] // what the inputs state: listed under each input, drawn when their chip is pressed
const hiddenKinds = (view: ContextGraphView) => (view.nodes.length > REVEAL_ALL_UP_TO ? STATEMENT_KINDS : [])
const STRUCTURE = new Set(['Subsidiary', 'Datapoint', 'Document', 'Concept'])
const keyPoints = (view: ContextGraphView) => {
  const degree = new Map<string, number>()
  for (const e of view.edges) for (const end of [e.source, e.target]) degree.set(end, (degree.get(end) ?? 0) + 1)
  const things = view.nodes.filter((n) => !STRUCTURE.has(n.type) && (degree.get(n.id) ?? 0) >= 3)
    .sort((a, b) => (degree.get(b.id) ?? 0) - (degree.get(a.id) ?? 0)).slice(0, KEY_THINGS)
  return [...view.nodes.filter((n) => STRUCTURE.has(n.type)).map((n) => n.id), ...things.map((n) => n.id)]
}

const mostLinked = (view: ContextGraphView) => {
  const degree = new Map<string, number>()
  const near = new Map<string, string[]>()
  for (const e of view.edges) {
    for (const end of [e.source, e.target]) degree.set(end, (degree.get(end) ?? 0) + 1)
    near.set(e.source, [...(near.get(e.source) ?? []), e.target])
    near.set(e.target, [...(near.get(e.target) ?? []), e.source])
  }
  const byDegree = (ids: string[]) => [...ids].sort((a, b) => (degree.get(b) ?? 0) - (degree.get(a) ?? 0))
  const hubs = byDegree(view.nodes.map((n) => n.id)).slice(0, 3)
  return [...new Set([...hubs, ...hubs.flatMap((hub) => byDegree(near.get(hub) ?? []))])].slice(0, START_MOST_LINKED)
}

export default function ContextGraphPage() {
  const { user } = useAuth()
  const isAdmin = user?.roles.includes('mesh_admin') ?? false
  const [tab, setTab] = useState<Tab>('inputs')
  const [uploads, setUploads] = useState<UploadRecord[]>([])
  const [graphs, setGraphs] = useState<ContextGraphSummary[]>([])
  const [ingested, setIngested] = useState<IngestedGraphSummary[]>([])
  const [kinds, setKinds] = useState<string[]>([])
  const [exportFormats, setExportFormats] = useState<ExportFormat[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [focus, setFocus] = useState<Focus | null>(null)
  const clearFocus = useCallback(() => setFocus(null), [])
  const [addTarget, setAddTarget] = useState<string | null>(null) // the graph chosen with "Upload input to this graph"

  const load = async () => {
    setLoading(true)
    setError('')
    try {
      const [{ data }, kept] = await Promise.all([getUploads(), getIngestedGraphs().then((r) => r.data.graphs).catch(() => null)])
      setUploads(data.uploads)
      setGraphs(data.graphs)
      setKinds(data.kinds)
      setExportFormats(data.export_format_list ?? data.export_formats.map((id) => ({ id, name: id, custom: false })))
      if (kept) setIngested(kept)
      else setError('The ingested graphs could not be read.')
    } catch (reason) {
      setError(detail(reason, 'The uploaded graphs could not be read.'))
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => { void load() }, [])

  return (
    <div className="mesh-data-page">
      <header className="mesh-page-heading">
        <div><div className="mesh-eyebrow">Knowledge in the graph</div><h1>Context graph</h1><p>The inputs uploaded into the mesh and the graphs ingested as JSON, with the part of the graph each one made. One search finds them and the topics, skills and documents you may see.</p></div>
        <button type="button" className="mesh-outline-action" onClick={() => void load()} disabled={loading}><RefreshCw size={14} className={loading ? 'animate-spin' : ''} />Refresh</button>
      </header>
      {error && <div role="alert" className="mesh-alert error">{error}</div>}
      <div className="mesh-tabs" role="tablist" aria-label="Context graph views">
        <button type="button" role="tab" aria-selected={tab === 'inputs'} className={tab === 'inputs' ? 'active' : ''} onClick={() => setTab('inputs')}><Waypoints size={15} />Uploaded graphs <span>{graphs.length + ingested.filter((g) => !correctionOf(g, graphs)).length}</span></button>
        <button type="button" role="tab" aria-selected={tab === 'upload'} className={tab === 'upload' ? 'active' : ''} onClick={() => setTab('upload')}><FileUp size={15} />Upload input</button>
      </div>
      {tab === 'inputs' && <UploadsTab uploads={uploads} graphs={graphs} ingested={ingested} loading={loading} isAdmin={isAdmin} company={user?.company ?? ''} focus={focus} onFocusUsed={clearFocus} onChanged={() => void load()} onAddTo={(graphId) => { setAddTarget(graphId); setTab('upload') }} />}
      {tab === 'upload' && <UploadInputTab isAdmin={isAdmin} companyName={user?.company_name ?? ''} graphs={graphs} ingested={ingested} initialGraph={addTarget}
        onSaved={() => { setAddTarget(null); void load() }} onOpen={(graphId) => { setFocus({ graph: graphId, doc: null }); setTab('inputs') }} />}
    </div>
  )
}

type Row = { kind: 'upload'; graph: ContextGraphSummary; hits: UploadRecord[]; at: string } | { kind: 'ingested'; graph: IngestedGraphSummary; at: string }

function UploadsTab({ uploads, graphs, ingested, loading, isAdmin, company, focus, onFocusUsed, onChanged, onAddTo }: { uploads: UploadRecord[]; graphs: ContextGraphSummary[]; ingested: IngestedGraphSummary[]; loading: boolean; isAdmin: boolean; company: string; focus: Focus | null; onFocusUsed: () => void; onChanged: () => void; onAddTo: (graphId: string) => void }) {
  const [q, setQ] = useState('')
  const [graphId, setGraphId] = useState<string | null>(null)
  const [openDocs, setOpenDocs] = useState<string[]>([]) // the inputs whose details are open, the last one opened at the end
  const [pane, setPane] = useState<'inputs' | 'graph' | 'use'>('inputs') // the part of the chosen graph that shows: its inputs, its drawing or how an application uses it
  const docId = openDocs[openDocs.length - 1] ?? null
  const setDocId = (id: string | null) => { setOpenDocs(id ? [id] : []); if (id) setPane('inputs') }
  const toggleDoc = (id: string) => setOpenDocs((open) => (open.includes(id) ? open.filter((x) => x !== id) : [...open, id])) // the others stay open, to compare
  const [loadedView, setView] = useState<ContextGraphView | null>(null)
  const [viewError, setViewError] = useState('')
  const [format, setFormat] = useState('json') // the JSON file in the standard JSON structure, the same file Upload input gives
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState('')
  const [found, setFound] = useState<{ query: string; results: GraphSearchResult[]; byVector: boolean } | null>(null) // what the graph search found
  const [searchError, setSearchError] = useState('')
  const [entity, setEntity] = useState<GraphEntity | null>(null) // a topic, skill, item or document chosen from the search
  const [entityError, setEntityError] = useState('')
  const asked = useRef(0) // the latest entity asked for: an older answer that comes later is not shown

  const graph = graphs.find((g) => g.id === graphId) ?? null
  const correction = graph ? ingested.find((g) => g.corrects === graph.id) ?? null : null // the graph loaded from its JSON: drawn in its place
  const kept = ingested.find((g) => g.id === graphId) ?? correction // an ingested graph: the person's own nodes and edges
  const keptId = kept?.id ?? null
  const view = loadedView && loadedView.id === (keptId ?? graphId) ? loadedView : null // the drawing of the graph chosen, never of the one before it
  const keptKey = kept ? `${kept.id}:${stampOf(kept).at}` : ''
  const emptied = graph !== null && graph.inputs === 0 // every input of the graph was removed: nothing to draw
  // every graph of the list, the latest first. live: it has something to draw
  const ordered = useMemo(() => [...graphs.map((g) => ({ id: g.id, at: g.latest, live: g.inputs > 0 })),
    ...ingested.filter((g) => !correctionOf(g, graphs)).map((g) => ({ id: g.id, at: stampOf(g).at, live: true }))].sort((a, b) => b.at.localeCompare(a.at)), [graphs, ingested])
  const nextAfter = (gone: string) => (ordered.find((g) => g.id !== gone && g.live) ?? null)?.id ?? null
  useEffect(() => {
    if (focus) {
      setGraphId(focus.graph)
      setDocId(focus.doc)
      onFocusUsed()
    } else if (!loading && (!graphId || !ordered.some((g) => g.id === graphId))) {
      setGraphId((ordered.find((g) => g.live) ?? ordered[0])?.id ?? null) // the top row that has something to draw. A graph dropped elsewhere is left
    }
  }, [focus, ordered, graphId, loading, onFocusUsed])
  useEffect(() => { // an ingested graph is drawn again only when it changed
    if (!keptId || !keptKey) return
    let stale = false // the answer of a graph left before it came is not shown
    setView(null)
    setViewError('')
    getIngestedGraphView(keptId).then(({ data }) => { if (!stale) setView(data) })
      .catch((reason) => { if (!stale) setViewError(detail(reason, 'The context graph could not be read.')) })
    return () => { stale = true }
  }, [keptId, keptKey])
  useEffect(() => { // an uploaded graph is drawn again after every load of the uploads
    if (!graphId || keptKey || graphId.startsWith('cg-')) return
    let stale = false
    setView(null)
    setViewError('')
    if (emptied) return
    getContextGraph(graphId).then(({ data }) => { if (!stale) setView(data) })
      .catch((reason) => { if (!stale) setViewError(detail(reason, 'The context graph could not be read.')) })
    return () => { stale = true }
  }, [graphId, uploads, emptied, keptKey])
  const start = useMemo(() => (!view ? undefined : kept ? mostLinked(view) : keyPoints(view)), [kept, view])
  useEffect(() => { // the one search box also searches the graph, once the typing stops
    const query = q.trim()
    setSearchError('')
    if (!query) { asked.current += 1; setEntity(null); setEntityError('') } // an emptied box goes back to the graph chosen
    if (query.length < SEARCH_MIN) { setFound(null); return }
    let stale = false
    const timer = window.setTimeout(() => {
      searchGraph(query).then(({ data }) => { if (!stale) setFound({ query, results: data.results, byVector: data.by_vector }) })
        .catch((reason) => { if (!stale) setSearchError(detail(reason, 'The search of the graph did not answer.')) })
    }, SEARCH_PAUSE_MS)
    return () => { stale = true; window.clearTimeout(timer) }
  }, [q])
  const graphFound = found && found.query === q.trim() ? found : null
  const searching = q.trim().length >= SEARCH_MIN && !graphFound && !searchError
  const byDoc = useMemo(() => new Map(uploads.map((u) => [u.document.id, u])), [uploads]) // an uploaded input is in the graph under its document id
  const shownFound = graphFound ?? (searching ? found : null) // while a new answer is on its way the last one stays, so the list does not jump
  const more = useMemo(() => (shownFound?.results ?? []).filter((r) => !byDoc.has(r.id)), [shownFound, byDoc]) // what the graph holds besides the inputs listed

  // the list: every context graph whose name, or one of whose inputs, holds every word typed or is found by the graph search,
  // the latest first. An input the graph search finds is shown here under its graph, never a second time below
  const rows = useMemo<Row[]>(() => {
    const query = q.trim()
    const foundInputs = (shownFound?.results ?? []).map((r) => byDoc.get(r.id)).filter((u): u is UploadRecord => Boolean(u)) // the same answer as More in the graph
    const uploaded: Row[] = graphs.flatMap((graph) => {
      const inputs = uploads.filter((u) => u.context_graph.id === graph.id)
      const byName = !query || matches(graph.name.toLowerCase(), query)
      const foundHere = foundInputs.filter((u) => u.context_graph.id === graph.id) // first, so a click opens the input the search found
      const hits = !query ? [] : byName ? foundHere // a graph that matches by name: only the inputs the search found, not every input
        : [...new Map([...foundHere, ...inputs.filter((u) => matches(words(u), query))].map((u) => [u.document.id, u])).values()]
      return byName || hits.length > 0 ? [{ kind: 'upload' as const, graph, hits, at: graph.latest }] : []
    })
    const own: Row[] = ingested.filter((g) => !correctionOf(g, graphs)).filter((g) => !query || matches(`${g.name} ${g.company_name} ${g.description ?? ''} ${Object.keys(g.node_types).join(' ')} ingested json`.toLowerCase(), query))
      .map((graph) => ({ kind: 'ingested' as const, graph, at: stampOf(graph).at }))
    return [...uploaded, ...own].sort((a, b) => b.at.localeCompare(a.at))
  }, [graphs, uploads, ingested, q, graphFound, byDoc])

  const inputs = uploads.filter((u) => u.context_graph.id === graphId)
  const current = inputs.find((u) => u.document.id === docId) ?? null
  const openGraph = (row: Row) => { // the graph itself. Each matching input line of the row opens its input
    asked.current += 1
    setEntity(null)
    setEntityError('')
    setGraphId(row.graph.id)
    setDocId(null)
  }
  const openInput = (u: UploadRecord) => {
    asked.current += 1
    setEntity(null)
    setEntityError('')
    setGraphId(u.context_graph.id)
    setDocId(u.document.id)
  }
  const openEntity = (id: string) => {
    const n = (asked.current += 1)
    setEntityError('')
    getGraphEntity(id).then(({ data }) => { if (n === asked.current) setEntity(data) })
      .catch((reason) => { if (n === asked.current) setEntityError(detail(reason, 'The entity could not be read.')) })
  }

  const download = async () => {
    if (!graph || !view) return
    setActionError('')
    try {
      if (format === 'json') {
        const made = await renderJsonTemplate(graph.id)
        const made_url = URL.createObjectURL(new Blob([JSON.stringify(made.data.output, null, 2)], { type: 'application/json' }))
        Object.assign(document.createElement('a'), { href: made_url, download: `context_graph_${graph.name.toLowerCase().replace(/[^a-z0-9]+/g, '_')}.json` }).click()
        URL.revokeObjectURL(made_url)
        return
      }
      const { data, headers } = await downloadContextGraph(graph.id, format)
      const name = /filename="([^"]+)"/.exec(String(headers['content-disposition'] ?? ''))?.[1] ?? `context_graph.${format}`
      const url = URL.createObjectURL(data)
      const link = Object.assign(document.createElement('a'), { href: url, download: name })
      link.click()
      URL.revokeObjectURL(url)
    } catch {
      setActionError('The context graph could not be downloaded.')
    }
  }
  const drop = () => {
    if (!graph) return
    const kept = inputs.filter((u) => u.status === 'accepted')
    const lines = kept.map((u) => `"${u.document.title}" (${companyOf(u)})`).join('\n')
    if (!window.confirm(`Drop the context graph "${graph.name}"?\n\nIts ${kept.length} ${kept.length === 1 ? 'input leaves' : 'inputs leave'} the packs, the indexes and the graph:\n${lines}\n\nThe upload records stay, marked removed.${correction ? ` The graph corrected with JSON, "${correction.name}", is dropped with it.` : ''}`)) return
    setBusy(true)
    setActionError('')
    dropContextGraph(graph.id).then(({ data }) => {
      setDocId(null)
      setGraphId(nextAfter(graph.id))
      if (Object.keys(data.failed ?? {}).length) setActionError(`The inputs are marked removed, but a pack could not be rebuilt: ${Object.entries(data.failed).map(([pack, why]) => `${pack} (${why})`).join(', ')}. Drop the graph again to retry.`)
      onChanged()
    }).catch((reason) => setActionError(detail(reason, 'The context graph was not dropped.'))).finally(() => setBusy(false))
  }
  const clear = () => { // a graph with no input left: off the list, its removed records kept on disk
    if (!graph) return
    if (!window.confirm(`Remove "${graph.name}" from the list?\n\nIt has no input left. Its ${graph.removed} removed ${graph.removed === 1 ? 'record is' : 'records are'} no longer listed. The ${graph.removed === 1 ? 'record stays' : 'records stay'} on disk as the upload history.`)) return
    setBusy(true)
    setActionError('')
    clearContextGraph(graph.id).then(() => { setDocId(null); setGraphId(nextAfter(graph.id)); onChanged() })
      .catch((reason) => setActionError(detail(reason, 'The graph was not removed from the list.'))).finally(() => setBusy(false))
  }
  const reviewOf = (docId: string) => view?.review?.find((r) => r.document === docId)?.reason ?? ''
  const keep = (u: UploadRecord) => {
    setBusy(true)
    setActionError('')
    keepInput(u.document.id).then(() => onChanged()).catch((reason) => setActionError(detail(reason, 'The input was not kept.'))).finally(() => setBusy(false))
  }
  const remove = (current: UploadRecord) => {
    if (!window.confirm(`Remove "${current.document.title}" from the pack, the index and the graph? The upload record stays, marked removed.`)) return
    setBusy(true)
    setActionError('')
    removeUpload(current.document.id).then(() => { setOpenDocs((open) => open.filter((x) => x !== current.document.id)); onChanged() }).catch((reason) => setActionError(detail(reason, 'The document was not removed.'))).finally(() => setBusy(false))
  }

  const nothing = !uploads.length && !ingested.length
  if (loading && nothing) return <div className="mesh-alert pending"><LoaderCircle size={15} className="animate-spin" />Loading uploaded graphs</div>
  return (
    <div className="context-graph-grid">
      <div className="context-upload-list">
        <div className="context-upload-search"><Search size={14} /><input className="mesh-field" value={q} onChange={(event) => setQ(event.target.value)} placeholder="Search graphs, inputs, topics and skills" aria-label="Search graphs, inputs, topics and skills" /></div>
        {nothing && !q.trim() && <div className="ask-empty-results">No input has been uploaded or ingested yet.</div>}
        <div role="list" aria-label="Context graphs" className="context-upload-list">
          {rows.map((row) => row.kind === 'upload' ? (
            <div role="listitem" key={row.graph.id} className={`context-upload-row with-inputs ${row.graph.id === graphId && !entity ? 'active' : ''}`}>
              <button type="button" className="context-row-open" onClick={() => openGraph(row)}>
                <strong>{row.graph.name}</strong>
                <small>{row.graph.inputs} {row.graph.inputs === 1 ? 'input' : 'inputs'}{row.graph.removed ? ` · ${row.graph.removed} removed` : ''}{row.graph.companies.length ? ` · ${row.graph.companies.join(', ')}` : ''}</small>
                <small>Latest {formatDateTime(row.graph.latest)}{ingested.some((g) => g.corrects === row.graph.id) ? ' · Corrected with JSON' : ''}</small>
              </button>
              {row.hits.map((u) => <button type="button" key={u.document.id} className={`context-match ${u.document.id === docId && row.graph.id === graphId && !entity ? 'active' : ''}`} onClick={() => openInput(u)}>{u.document.title} · {companyOf(u)}</button>)}
            </div>
          ) : (
            <button type="button" role="listitem" key={row.graph.id} className={`context-upload-row ${row.graph.id === graphId && !entity ? 'active' : ''}`} onClick={() => openGraph(row)}>
              <strong>{row.graph.name}</strong>
              <small>Ingested JSON · {row.graph.nodes} {row.graph.nodes === 1 ? 'node' : 'nodes'} · {row.graph.edges} {row.graph.edges === 1 ? 'edge' : 'edges'} · {row.graph.company_name}</small>
              <small>Latest {formatDateTime(row.at)}</small>
            </button>
          ))}
        </div>
        {q.trim() && !rows.length && !more.length && !searching && !searchError && <div className="ask-empty-results">Nothing matches {q}.</div>}
        {searchError && <div role="alert" className="mesh-alert error">{searchError}</div>}
        {more.length > 0 && <div className="mesh-eyebrow" id="context-more">More in the graph</div>}
        {more.length > 0 && shownFound?.byVector && <p className="mesh-panel-footnote">No name matched your words. These entries are the closest in meaning.</p>}
        {more.length > 0 && <div role="list" aria-labelledby="context-more" className="context-upload-list">
          {more.map((r) => (
            <button type="button" role="listitem" key={r.id} className={`context-upload-row ${entity?.id === r.id ? 'active' : ''}`} onClick={() => openEntity(r.id)}>
              <strong>{r.label}</strong>
              <span className="context-type"><i style={{ background: TYPE_COLOURS[r.type] ?? '#adb5bd' }} />{typeWords(r.type)}</span>
              <small>{[entityCompany(r) || null, r.sharing ? sharingWords(r.sharing, entityCompany(r)) : null, linkCount(r), r.matched === 'alias or tag' ? 'Other name or tag' : r.matched === 'label' ? null : r.matched].filter(Boolean).join(' · ')}</small>
            </button>
          ))}
        </div>}
      </div>
      <div className="dashboard-stack">
        {entityError && <div role="alert" className="mesh-alert error">{entityError}</div>}
        {!entity && !graph && !kept && more.length > 0 && <div className="ask-empty-results">Choose a result to see its links.</div>}
        {entity ? <EntityPanel entity={entity} byDoc={byDoc} onOpen={openEntity} onOpenInput={openInput} /> : <>
        {graph && <section className="mesh-section-panel context-detail" aria-label="Context graph">
          <div className="mesh-section-heading"><div><div className="mesh-eyebrow">Context graph</div><h2>{graph.name}</h2>
              <small className="mesh-panel-footnote" style={{ margin: 0 }}>{graph.inputs} {graph.inputs === 1 ? 'input' : 'inputs'}{graph.removed ? ` · ${graph.removed} removed` : ''}{graph.companies.length ? ` · ${graph.companies.join(', ')}` : ''}</small></div>
            {isAdmin && <div className="context-graph-actions">
              {graph.inputs > 0 && <button type="button" className="mesh-primary-action" onClick={() => onAddTo(graph.id)}><FilePlus2 size={15} />Upload input to this graph</button>}
              {graph.inputs === 0 && <button type="button" className="mesh-outline-action danger" disabled={busy} onClick={clear} aria-label="Remove from the list">{busy ? <LoaderCircle size={14} className="animate-spin" /> : <Trash2 size={14} />}Remove from the list</button>}
              {graph.inputs > 0 && <button type="button" className="mesh-outline-action danger" disabled={busy} onClick={drop}>{busy ? <LoaderCircle size={14} className="animate-spin" /> : <Trash2 size={14} />}Drop graph</button>}
            </div>}</div>
          {view?.description && <GraphDescriptionBlock key={graph.id} graphId={graph.id} description={view.description} onSaved={onChanged} />}
          <div className="mesh-tabs" role="tablist" aria-label="Parts of the context graph">
            <button type="button" role="tab" aria-selected={pane === 'inputs'} className={pane === 'inputs' ? 'active' : ''} onClick={() => setPane('inputs')}>Inputs <span>{inputs.length}</span></button>
            <button type="button" role="tab" aria-selected={pane === 'graph'} className={pane === 'graph' ? 'active' : ''} onClick={() => setPane('graph')}><Waypoints size={15} />Graph</button>
            <button type="button" role="tab" aria-selected={pane === 'use'} className={pane === 'use' ? 'active' : ''} onClick={() => setPane('use')}><Braces size={15} />Use this graph</button>
          </div>
          {pane === 'use' && <UseGraph graphId={graph.id} />}
          {pane === 'inputs' && <div className="context-inputs" role="list" aria-label="Inputs of the context graph">
            {inputs.map((u) => (
              <Fragment key={u.document.id}>
                <button type="button" role="listitem" className={`context-upload-row ${openDocs.includes(u.document.id) ? 'active' : ''}`} aria-expanded={openDocs.includes(u.document.id)} onClick={() => toggleDoc(u.document.id)}>
                  <strong>{u.document.title}</strong>
                  <small>{companyOf(u)} · {itemOf(u)} · {kindOf(u)}</small>
                  <small>{u.upload.file} · {formatDateTime(u.upload.at)} · {statusOf(u)}{reviewOf(u.document.id) ? ' · To review' : ''}</small>
                </button>
                {openDocs.includes(u.document.id) && <div className="context-input-detail">
            {reviewOf(u.document.id) && <div className="mesh-alert note context-review">
              <span>{reviewOf(u.document.id)} Keep it if it belongs here, or remove it.</span>
              {(isAdmin || u.node_id === company) && <button type="button" className="mesh-outline-action" disabled={busy} onClick={() => keep(u)}>Keep in this graph</button>}
            </div>}{/* the details open under their input and stay open until it is pressed again */}

            <div className="mesh-section-heading" style={{ marginBottom: 0 }}><div><div className="mesh-eyebrow">{companyOf(u)}</div><h2>{u.document.title}</h2></div><span className={`mesh-result-state ${u.in_graph ? 'success' : 'warning'}`}>{sharingWords(u.sharing, companyOf(u))}</span></div>
            <dl>
              <dt>Document</dt><dd>{u.document.id}</dd>
              <dt>Catalogue item</dt><dd>{u.sharing.item_title ?? u.document.datapoint}</dd>
              <dt>Kind</dt><dd>{kindOf(u)} · version {u.document.version}</dd>
              <dt>File</dt><dd>{u.upload.file} · {u.upload.format} · {u.upload.chars.toLocaleString()} characters of text</dd>
              <dt>Uploaded</dt><dd>{formatDateTime(u.upload.at)} by the {u.upload.by_role.toLowerCase()} of {u.upload.by_company_name ?? u.upload.by_company}</dd>
              {u.document.tags.length > 0 && <><dt>Tags</dt><dd>{u.document.tags.join(', ')}</dd></>}
              {u.document.summary && <><dt>Start of the file</dt><dd>{startOf(u.document.summary)}</dd></>}
              <dt>Who can read it</dt><dd>{readersOf(u.sharing, companyOf(u))}</dd>
            </dl>
            {view && <FoundLinks view={view} docId={u.document.id} canDecide={isAdmin || u.node_id === company} onDecided={onChanged} />}
            {isAdmin && u.status !== 'removed' && <div style={{ display: 'flex', justifyContent: 'flex-end' }}><button type="button" className="mesh-outline-action danger" disabled={busy} onClick={() => remove(u)}>{busy ? <LoaderCircle size={14} className="animate-spin" /> : null}Remove this input</button></div>}
          
                </div>}
              </Fragment>
            ))}
          </div>}
          <div className="context-download">
            {!correction && <>
            <label htmlFor="context-format" className="mesh-panel-footnote" style={{ margin: 0 }}>Download this context graph as</label>
            <select id="context-format" value={format} onChange={(event) => setFormat(event.target.value)}>{Object.keys(FORMAT_WORDS).map((f) => <option key={f} value={f}>{FORMAT_WORDS[f]}</option>)}</select>
            <button type="button" className="mesh-outline-action" onClick={() => void download()} disabled={!view}><Download size={14} />Download</button>
            </>}
          </div>
          {actionError && <div role="alert" className="mesh-alert error">{actionError}</div>}
        </section>}
        {kept && (!graph || pane === 'graph') && <IngestedPanel key={kept.id} graph={kept} onDropped={() => { if (kept !== correction) setGraphId(nextAfter(kept.id)); onChanged() }} />}
        {(graph ? pane === 'graph' : Boolean(kept)) && <section className="mesh-section-panel" aria-label="Graph of the inputs">
          <div className="mesh-section-heading"><div><div className="mesh-eyebrow">Context graph</div><h2>{kept ? 'Nodes and edges' : 'What these inputs are linked to'}</h2></div>{view && <small className="mesh-panel-footnote" style={{ margin: 0 }}>{kept ? `${view.nodes.length} ${view.nodes.length === 1 ? 'node' : 'nodes'} · ${view.edges.length} ${view.edges.length === 1 ? 'edge' : 'edges'}` : `${view.documents.length} ${view.documents.length === 1 ? 'input' : 'inputs'} · ${view.nodes.length} entities · ${view.edges.length} links`}</small>}</div>
          {viewError && <div className="mesh-alert error">{viewError}</div>}
          {emptied && <div className="ask-empty-results">Every input of this context graph was removed. The records stay in the list.</div>}
          {!view && !viewError && !emptied && <div className="mesh-alert pending"><LoaderCircle size={15} className="animate-spin" />Loading the context graph</div>}
          {view && <MeshGraphExplorer key={view.id} graph={view} revealAll={view.nodes.length <= REVEAL_ALL_UP_TO} startIds={start} edgeLabels={Boolean(kept)} hideAtStart={kept ? [] : hiddenKinds(view)} />}
          {view && !kept && <div className="context-concepts" aria-label="Linked entities">{view.nodes.filter((n) => !view.documents.includes(n.id)).map((n) => <span key={n.id} title={n.type}>{typeWords(n.type)}: {n.label}{current?.concept_matches?.[n.id] ? ` (${MATCH_WORDS[current.concept_matches[n.id]]})` : ''}</span>)}</div>}
        </section>}
        </>}
      </div>
    </div>
  )
}

// the first lines of a file as kept in its record. A transcript repeats the speaker ("Asha: Asha: ..."), said once here
const startOf = (text: string) => text.replace(/([^\s:][^:\n]{1,40}):\s+\1:/g, '$1:')
// who can read the first lines of an input, by the sharing rule of its catalogue item
const readersOf = (rule: UploadRecord['sharing'], company: string) => {
  if (rule.shared) return 'Every connected company can read the full file.'
  if (rule.never_leave) return `Only ${company}. Other companies see nothing of this file.`
  switch (String(rule.ceiling ?? '').toUpperCase()) {
    case 'MD': return `Other companies see the title only. The text stays in ${company}.`
    case 'SUM': return `Other companies can read these first lines. The full file stays in ${company}.`
    case 'RAG': return 'Other companies can read the full file.'
    default: return `${company}.`
  }
}

// why a file fits a graph, said with the concepts both name. The reason text of the model is not shown: it is free text
const fitWords = (s: UploadSuggestion) => {
  const names = s.graph.shared.map((id) => s.concepts.find((c) => c.id === id)?.label).filter(Boolean) as string[]
  if (!names.length) return ''
  if (names.length > 3) return `, which also covers ${names.slice(0, 3).join(', ')} and ${names.length - 3} more`
  return `, which also covers ${names.length > 1 ? `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}` : names[0]}`
}

// One form for both ways in. A file is read and its fields filled (mesh admins). A graph JSON is pasted or chosen, checked
// and held. Add to the graph or Append to the graph then keeps what the form holds: the file, the JSON, or both
type Checked = { kind: 'upload'; record: UploadRecord } | { kind: 'ingested'; result: IngestResult } | { kind: 'batch'; result: BatchResult }
interface Held { text: string; name: string; result: IngestResult } // a graph JSON that passed the check and is not kept yet

function UploadInputTab({ isAdmin, companyName, graphs, ingested, initialGraph, onSaved, onOpen }: { isAdmin: boolean; companyName: string; graphs: ContextGraphSummary[]; ingested: IngestedGraphSummary[]; initialGraph: string | null; onSaved: () => void; onOpen: (graphId: string) => void }) {
  const [pasting, setPasting] = useState<{ text: string; name: string } | null>(null) // the JSON box is open
  const [held, setHeld] = useState<Held | null>(null)
  const [handoff, setHandoff] = useState<File | null>(null) // a document chosen in the JSON box, read by the form
  const [checked, setChecked] = useState<Checked | null>(null) // what was just kept, shown below the form for a quick check
  return <>
    {pasting && <IngestTab companyName={companyName} isAdmin={isAdmin} initialText={pasting.text} initialName={pasting.name}
      onChecked={(text, name, result) => { setHeld({ text, name, result }); setPasting(null) }} onCancel={() => setPasting(null)}
      onDocument={isAdmin ? (file) => { setHandoff(file); setPasting(null) } : undefined} />}
    <div hidden={Boolean(pasting)}>{/* kept while the JSON box is open, so the file and the filled fields stay */}
      <UploadTab isAdmin={isAdmin} graphs={graphs} ingested={ingested} initialGraph={initialGraph} initialFile={handoff} held={held}
        onPasteJson={(text, name) => { setHandoff(null); setPasting({ text, name }) }} onRemoveJson={() => setHeld(null)}
        onSaved={(what, keepJson) => { setChecked(what); if (!keepJson) setHeld(null); onSaved() }} />
    </div>
    {checked && (checked.kind === 'batch' ? <BatchOutcome result={checked.result} onOpen={onOpen} /> : <QuickCheck checked={checked} onOpen={onOpen} />)}
  </>
}

// The graph just added or ingested, drawn with what was kept, so it can be checked without leaving Upload input
// The graphs a folder or a zip made, with the files kept in each. The graph chosen is drawn with its notes, as after one file
function BatchOutcome({ result, onOpen }: { result: BatchResult; onOpen: (graphId: string) => void }) {
  const [graphId, setGraphId] = useState(result.graphs[0]?.id ?? '')
  const [view, setView] = useState<ContextGraphView | null>(null)
  const [error, setError] = useState('')
  const graph = result.graphs.find((g) => g.id === graphId) ?? null
  const files = result.saved.filter((r) => r.context_graph.id === graphId)
  useEffect(() => {
    if (!graphId) return
    let stale = false // the drawing of a graph left before its answer came is not shown
    setView(null)
    setError('')
    getContextGraph(graphId).then(({ data }) => { if (!stale) setView(data) }).catch((reason) => { if (!stale) setError(detail(reason, 'The graph could not be drawn.')) })
    return () => { stale = true }
  }, [graphId, result])
  const download = () => {
    if (!graph) return
    setError('')
    renderJsonTemplate(graph.id).then(({ data }) => saveJson(data.output, `context_graph_${fileNameOf(graph.name)}.json`)).catch(() => setError('The JSON could not be downloaded.'))
  }
  return (
    <section className="mesh-section-panel context-detail" aria-label="Quick check">
      <div className="mesh-section-heading"><div><div className="mesh-eyebrow">Added to the graph</div><h2>{plural(result.saved.length, 'file')} in {plural(result.graphs.length, 'context graph')}</h2>
          {result.refused.length > 0 && <small className="mesh-panel-footnote" style={{ margin: 0 }}>{plural(result.refused.length, 'file')} not kept</small>}</div>
        {graph && <div className="context-graph-actions">
          <button type="button" className="mesh-outline-action" onClick={download}><Download size={14} />Download JSON</button>
          <button type="button" className="mesh-primary-action" onClick={() => onOpen(graph.id)}><Waypoints size={15} />Open in Uploaded graphs</button>
        </div>}</div>
      {result.graphs.length > 1 && <div className="context-inputs" role="list" aria-label="Context graphs made">
        {result.graphs.map((g) => (
          <button type="button" role="listitem" key={g.id} className={`context-upload-row ${g.id === graphId ? 'active' : ''}`} onClick={() => setGraphId(g.id)}>
            <strong>{g.name}</strong>
            <small>{plural(g.files, 'file')} added</small>
          </button>
        ))}
      </div>}
      {graph && <>
        <div className="mesh-section-heading" style={{ marginBottom: 0 }}><div><div className="mesh-eyebrow">Context graph</div><h2>{graph.name}</h2></div></div>
        {/* the drawing first, then the files that made it */}
        {error && <div role="alert" className="mesh-alert error">{error}</div>}
        {!view && !error && <div className="mesh-alert pending"><LoaderCircle size={15} className="animate-spin" />Drawing the graph</div>}
        {view && <MeshGraphExplorer key={view.id} graph={view} revealAll={view.nodes.length <= REVEAL_ALL_UP_TO} startIds={keyPoints(view)} hideAtStart={hiddenKinds(view)} />}
        <div className="mesh-eyebrow">Files added</div>
        <div className="context-inputs" role="list" aria-label="Files added">
          {files.map((r) => (
            <div role="listitem" key={r.document.id} className="context-upload-row">
              <strong>{r.document.title}</strong>
              <small>{r.path} · {kindOf(r)} · {plural(r.document.concepts?.length ?? 0, 'concept')} linked · {plural(r.rebuild?.index_rows ?? 0, 'passage')} can be searched{r.extraction?.links ? ` · ${plural(r.extraction.links, 'link')} found in the text` : ''}</small>
            </div>
          ))}
        </div>
      </>}
      {result.refused.length > 0 && <div className="context-ingest-outcome">Not kept<ul className="context-ingest-list">{result.refused.map((x) => <li key={x.path}>{x.path}: {x.reason}</li>)}</ul></div>}
      {result.new_item && <small className="mesh-panel-footnote">New catalogue item {result.new_item.code} · {result.new_item.title}</small>}
      {result.notes.map((n) => <small key={n} className="mesh-panel-footnote">{n}</small>)}
    </section>
  )
}

function QuickCheck({ checked, onOpen }: { checked: Exclude<Checked, { kind: 'batch' }>; onOpen: (graphId: string) => void }) {
  const [view, setView] = useState<ContextGraphView | null>(null)
  const [error, setError] = useState('')
  const ingestedGraph = checked.kind === 'ingested' ? checked.result.graph : null
  const graphId = checked.kind === 'upload' ? checked.record.context_graph.id : checked.result.graph.id
  const name = checked.kind === 'upload' ? checked.record.context_graph.name : checked.result.graph.name
  useEffect(() => {
    let stale = false // the drawing of a graph checked before this one is not shown
    setView(null)
    setError('')
    const ask = checked.kind === 'upload' ? getContextGraph(graphId) : getIngestedGraphView(graphId)
    ask.then(({ data }) => { if (!stale) setView(data) }).catch((reason) => { if (!stale) setError(detail(reason, 'The graph could not be drawn.')) })
    return () => { stale = true }
  }, [checked, graphId])
  const start = useMemo(() => (!view ? undefined : ingestedGraph ? mostLinked(view) : keyPoints(view)), [ingestedGraph, view])
  const download = () => {
    setError('')
    const made = checked.kind === 'upload' ? renderJsonTemplate(graphId).then(({ data }) => data.output) : getIngestedGraph(graphId).then(({ data }) => data)
    made.then((data) => saveJson(data, `context_graph_${fileNameOf(name)}.json`)).catch(() => setError('The JSON could not be downloaded.'))
  }
  let eyebrow = ''
  let line = ''
  let notes: [string, string[]][] = []
  if (checked.kind === 'upload') {
    const r = checked.record
    eyebrow = 'Added to the graph'
    line = `${r.document.title} · ${r.document.id} · ${kindOf(r)} · ${plural(r.document.concepts?.length ?? 0, 'concept')} linked · ${plural(r.rebuild?.index_rows ?? 0, 'passage')} can be searched${r.extraction?.links ? ` · ${plural(r.extraction.links, 'link')} found in the text, to review` : ''}`
    notes = [['Notes', [r.new_item ? `New catalogue item ${r.new_item.code} · ${r.new_item.title}` : '', r.refresh && !r.refresh.startsWith('loaded') ? `The shared graph was not updated: ${r.refresh}` : ''].filter(Boolean)]]
  } else {
    const { result } = checked
    const g = result.graph
    eyebrow = result.unchanged ? 'Unchanged' : g.corrects ? 'Corrected with JSON' : result.replaced ? 'Replaced' : 'Ingested'
    line = `${g.id} · ${g.company_name} · ${plural(g.nodes, 'node')} · ${plural(g.edges, 'edge')} · ${g.sensitivity} · ${sharingOf(g)}`
    notes = [['Filled in', result.filled], ['Defaults used', result.defaults], ['Not read', result.ignored], ['Warnings', result.warnings]]
  }
  return (
    <section className="mesh-section-panel context-detail" aria-label="Quick check">
      <div className="mesh-section-heading"><div><div className="mesh-eyebrow">{eyebrow}</div><h2>{name}</h2>
          <small className="mesh-panel-footnote" style={{ margin: 0 }}>{line}</small></div>
        <div className="context-graph-actions">
          <button type="button" className="mesh-outline-action" onClick={download}><Download size={14} />Download JSON</button>
          <button type="button" className="mesh-primary-action" onClick={() => onOpen(ingestedGraph ? ingestedGraph.corrects ?? ingestedGraph.id : graphId)}><Waypoints size={15} />Open in Uploaded graphs</button>
        </div></div>
      {notes.filter(([, items]) => items.length > 0).map(([title, items]) => <div key={title} className="context-ingest-outcome">{title}<ul className="context-ingest-list">{items.map((item, i) => <li key={i}>{item}</li>)}</ul></div>)}
      {ingestedGraph && <small className="mesh-panel-footnote">Applications query it with <code>POST {ingestedGraph.endpoints.query}</code></small>}
      {error && <div role="alert" className="mesh-alert error">{error}</div>}
      {!view && !error && <div className="mesh-alert pending"><LoaderCircle size={15} className="animate-spin" />Drawing the graph</div>}
      {view && <MeshGraphExplorer key={view.id} graph={view} revealAll={view.nodes.length <= REVEAL_ALL_UP_TO} startIds={start} edgeLabels={Boolean(ingestedGraph)} hideAtStart={ingestedGraph ? [] : hiddenKinds(view)} />}
    </section>
  )
}

function UploadTab({ isAdmin, graphs, ingested, initialGraph, initialFile, held, onPasteJson, onRemoveJson, onSaved }: { isAdmin: boolean; graphs: ContextGraphSummary[]; ingested: IngestedGraphSummary[]; initialGraph: string | null; initialFile: File | null; held: Held | null; onPasteJson: (text: string, name: string) => void; onRemoveJson: () => void; onSaved: (what: Checked, keepJson?: boolean) => void }) {
  const [nodes, setNodes] = useState<MeshNodeInfo[]>([])
  const [nodeId, setNodeId] = useState<CompanyId>('')
  const [items, setItems] = useState<UploadItem[]>([])
  const [areas, setAreas] = useState<NewItemArea[]>([])
  const [newItemTitle, setNewItemTitle] = useState('')
  const [newItemArea, setNewItemArea] = useState('')
  const [itemsLoaded, setItemsLoaded] = useState(0) // counts reloads, so a new item appears in the list after its upload
  const [fields, setFields] = useState<Record<string, Record<string, string>>>({})
  const [templateText, setTemplateText] = useState('')
  const [own, setOwn] = useState(false) // the chosen graph has a template of its own
  // NOTE: false is the rule since 2026-11-10: one standard structure for every graph, shown read-only. The editing below
  // (Edit, Upload, the changed template sent with the upload) is kept and comes back when the server turns the switch on
  const [canChange, setCanChange] = useState(false)
  const [edited, setEdited] = useState(false) // the template was changed on this form and is not kept yet
  const editedNow = useRef(false)
  const [editing, setEditing] = useState(false)
  const [preview, setPreview] = useState('')
  const [templateNote, setTemplateNote] = useState('')
  let parsedTemplate: unknown = null
  try { parsedTemplate = templateText ? JSON.parse(templateText) : null } catch { parsedTemplate = null }
  const templateOk = parsedTemplate !== null && typeof parsedTemplate === 'object' && !Array.isArray(parsedTemplate)
  const markEdited = (value: boolean) => { editedNow.current = value; setEdited(value) }
  const editTemplate = (text: string) => { setTemplateText(text); markEdited(true); setPreview('') }
  const loadTemplateFile = (picked: File | null) => { if (picked) void picked.text().then((text) => { editTemplate(text); setEditing(true) }) }
  const downloadTemplate = () => {
    const url = URL.createObjectURL(new Blob([templateText], { type: 'application/json' }))
    Object.assign(document.createElement('a'), { href: url, download: 'context_graph_json_structure.json' }).click()
    URL.revokeObjectURL(url)
  }
  const previewTemplate = () => {
    if (!chosen) { setTemplateNote('A preview needs an existing context graph. Choose one in Context graph.'); return }
    setTemplateNote('')
    renderJsonTemplate(chosen.id, parsedTemplate).then(({ data }) => setPreview(JSON.stringify(data.output, null, 2)))
      .catch((reason) => { setPreview(''); setTemplateNote(detail(reason, 'The JSON structure could not be used.')) })
  }
  const [code, setCode] = useState('')
  const [graphChoice, setGraphChoice] = useState(initialGraph && graphs.some((g) => g.id === initialGraph && g.inputs > 0) ? initialGraph : '') // the graph Append to the graph adds to
  const [graphName, setGraphName] = useState('')
  const [title, setTitle] = useState('')
  const [tags, setTags] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [suggestion, setSuggestion] = useState<UploadSuggestion | null>(null) // what the file says about itself, read before the upload
  const [reading, setReading] = useState(false)
  const reads = useRef(0) // counts the files chosen: the answer for a file that was replaced before it came is passed over
  const offered = useRef<UploadSuggestion | null>(null) // the last suggestion put into the fields. It stays when a file is taken away or cannot be read
  const fileInput = useRef<HTMLInputElement>(null)
  const folderInput = useRef<HTMLInputElement | null>(null)
  // many files, a folder or one zip: checked by the server before anything is kept
  const [batch, setBatch] = useState<{ files: File[]; paths: string[]; label: string } | null>(null)
  const [plan, setPlan] = useState<BatchPlan | null>(null)
  const [planning, setPlanning] = useState(false)
  const [batchItem, setBatchItem] = useState('') // the name of the new catalogue item the check was run with
  const [batchGraph, setBatchGraph] = useState('') // the graph name typed for a set that makes one graph. Empty: the name of the folder
  const [batchGraphText, setBatchGraphText] = useState<string | null>(null) // what is typed in Name of the graph. null: not touched, the name of the folder shows
  const batchForm = (set: { files: File[]; paths: string[] }, check: boolean) => {
    const form = new FormData()
    set.files.forEach((f, i) => { form.append('files', f); form.append('paths', set.paths[i]) })
    form.append('node_id', nodeId)
    form.append('datapoint', code)
    form.append('check', String(check))
    if (code === NEW_ITEM) { form.append('new_item_title', batchItem); form.append('new_item_area', newItemArea) }
    if (batchGraph) form.append('graph_name', batchGraph)
    return form
  }
  const chooseFiles = (list: FileList | null, fromFolder = false) => {
    const picked = [...(list ?? [])]
    if (!fromFolder && picked.length <= 1 && !/\.zip$/i.test(picked[0]?.name ?? '')) { setBatch(null); setPlan(null); chooseFile(picked[0] ?? null); return }
    if (!picked.length) return
    reads.current += 1 // a single file being read is passed over
    setFile(null)
    setSuggestion(null)
    setReading(false)
    setError('')
    const paths = picked.map((f) => (f as File & { webkitRelativePath?: string }).webkitRelativePath || f.name)
    const label = picked.length === 1 ? picked[0].name : fromFolder ? `the folder ${paths[0].split('/')[0]}` : `${picked.length} files`
    setPlan(null)
    setBatchGraph('')
    setBatchGraphText(null)
    setBatch({ files: picked, paths, label })
  }
  // the name of the set, from the zip or the folder: "Final_Knowledge_Documents 1.zip" gives "Final Knowledge Documents 1"
  const setName = batch ? (batch.files.length === 1 ? batch.files[0].name.replace(/\.zip$/i, '') : batch.paths[0].includes('/') ? batch.paths[0].split('/')[0] : '').replace(/[_-]+/g, ' ').trim() : ''
  useEffect(() => { // a new item for a set of files takes the name of the set, until the person types one
    if (batch && code === NEW_ITEM && !newItemTitle && setName) { setNewItemTitle(setName.slice(0, 120)); setBatchItem(setName.slice(0, 120)) }
  }, [batch, code])
  const batchKey = batch ? `${batch.label}:${batch.files.length}:${batch.files.reduce((n, f) => n + f.size, 0)}:${nodeId}:${code}:${code === NEW_ITEM ? `${batchItem}:${newItemArea}` : ''}:${batchGraph}` : ''
  useEffect(() => { // the check runs again when the company, the catalogue item or a name changes, since they apply to every file
    if (!batch || !nodeId || !code) return
    if (code === NEW_ITEM && (batchItem.trim().length < 3 || !newItemArea)) { setPlan(null); return }
    let stale = false
    setPlanning(true)
    setError('')
    checkUploads(batchForm(batch, true)).then(({ data }) => { if (!stale) setPlan(data) })
      .catch((reason) => { if (!stale) { setPlan(null); setError(detail(reason, 'The files could not be read.')) } })
      .finally(() => { if (!stale) setPlanning(false) })
    return () => { stale = true }
  }, [batchKey])
  const clearBatch = () => { setBatch(null); setPlan(null); if (fileInput.current) fileInput.current.value = ''; if (folderInput.current) folderInput.current.value = '' }
  const chooseFile = (picked: File | null) => {
    if (picked && !isAdmin) { // only a mesh admin uploads documents: anyone else gives a graph JSON
      if (!JSON_FILE.test(picked.name)) { setError('A mesh admin uploads documents. Choose a graph JSON (.json).'); return }
      picked.text().then((text) => onPasteJson(text, picked.name)).catch(() => setError(`${picked.name} could not be read.`))
      if (fileInput.current) fileInput.current.value = ''
      return
    }
    if (picked && JSON_FILE.test(picked.name) && picked.size <= MAX_JSON_BYTES) { // a graph JSON goes to the JSON box, any other .json is a document
      const read = ++reads.current
      picked.text().then((text) => { if (read === reads.current) { if (isGraphJson(text)) { if (fileInput.current) fileInput.current.value = ''; onPasteJson(text, picked.name) } else readDocument(picked, read) } })
        .catch(() => { if (read === reads.current) readDocument(picked, read) })
      return
    }
    readDocument(picked, ++reads.current)
  }
  const readDocument = (picked: File | null, read: number) => {
    setFile(picked)
    setSuggestion(null)
    if (!picked) { setReading(false); return }
    const form = new FormData()
    form.append('file', picked)
    form.append('node_id', nodeId)
    form.append('datapoint', code)
    setReading(true)
    setError('')
    suggestUpload(form).then(({ data }) => {
      if (read !== reads.current) return
      // a field still empty, or still holding the last suggestion, takes the new one. A field the person typed in stays
      const last = offered.current
      setTitle((t) => (!t || t === last?.title ? data.title : t))
      setTags((t) => (!t || t === last?.tags.join(', ') ? data.tags.join(', ') : t))
      // a graph the person chose stays chosen: only an empty choice, or the one the last file suggested, follows the new file
      const lastSuggested = last ? (last.graph.mode === 'append' ? last.graph.id ?? '' : NEW_GRAPH) : ''
      const follows = (c: string) => !c || c === lastSuggested
      setGraphChoice((c) => (follows(c) ? (data.graph.mode === 'append' && data.graph.id ? data.graph.id : NEW_GRAPH) : c))
      setGraphName((n) => (!n || n === last?.graph.name ? (data.graph.mode === 'new' ? data.graph.name : '') : n))
      offered.current = data
      setSuggestion(data)
    }).catch((reason) => { if (read === reads.current) setError(detail(reason, 'The file could not be read.')) })
      .finally(() => { if (read === reads.current) setReading(false) })
  }
  useEffect(() => { // a document chosen on the JSON form is read here, and shown in the File field
    if (!initialFile) return
    try {
      const chosenFiles = new DataTransfer()
      chosenFiles.items.add(initialFile)
      if (fileInput.current) fileInput.current.files = chosenFiles.files
    } catch { /* the file is still read. Only its name is not shown in the field */ }
    readDocument(initialFile, ++reads.current)
  }, [initialFile])
  useEffect(() => {
    getMeshNodes().then(({ data }) => {
      const sorted = [...data.nodes].sort((a, b) => Number(Boolean(b.shared)) - Number(Boolean(a.shared))) // the shared node first, and chosen by default
      setNodes(sorted)
      setNodeId((chosen) => chosen || sorted[0]?.node_id || '') // a company already chosen stays chosen
    }).catch(() => undefined)
  }, [])
  useEffect(() => {
    if (!nodeId) return
    let stale = false // the items of a company left before its answer came are not shown
    getUploadItems(nodeId).then(({ data }) => {
      if (stale) return
      const usable = data.items.filter((i) => i.ceiling !== 'LIVE')
      setItems(usable)
      setAreas(data.new_item_areas ?? [])
      setNewItemArea((a) => (data.new_item_areas ?? []).some((x) => x.domain === a) ? a : data.new_item_areas?.[0]?.domain ?? '')
      setCode((c) => (usable.some((i) => i.code === c) ? c : usable[0]?.code ?? ''))
    }).catch(() => { if (!stale) { setItems([]); setAreas([]); setCode('') } })
    return () => { stale = true }
  }, [nodeId, itemsLoaded])
  const node = nodes.find((n) => n.node_id === nodeId)
  const item = items.find((i) => i.code === code)
  const open = isAdmin ? graphs.filter((g) => g.inputs > 0) : [] // graphs made from documents: only a mesh admin adds to them
  const chosen = open.find((g) => g.id === graphChoice)
  const jsonOnly = !file && Boolean(held) // the form holds a checked JSON and no file
  const replaceable = ingested.filter((g) => g.can_change && !g.corrects) // graphs ingested as JSON that this person may replace
  const chosenKept = jsonOnly ? replaceable.find((g) => g.id === graphChoice) : undefined
  useEffect(() => { // a checked JSON fills the company and the context graph, unless a file already decided them
    if (!held || file) return
    const g = held.result.graph
    if (isAdmin && nodes.some((n) => n.node_id === g.company)) setNodeId(g.company)
    const target = g.corrects ?? g.id
    if (target && (open.some((o) => o.id === target) || replaceable.some((o) => o.id === target))) setGraphChoice(target)
    else { setGraphChoice(NEW_GRAPH); setGraphName(g.name) }
  }, [held])
  const isNewItem = code === NEW_ITEM
  const chosenId = chosen?.id
  useEffect(() => {
    let stale = false // the template of a graph left before its answer came is not shown
    getGraphTemplate(chosenId).then(({ data }) => {
      if (stale) return
      setFields(data.fields)
      setOwn(data.own)
      setCanChange(data.can_change)
      if (!editedNow.current) { setTemplateText(JSON.stringify(data.template, null, 2)); setPreview('') } // a template changed on the form stays
    }).catch(() => undefined)
    return () => { stale = true }
  }, [chosenId])
  const ready = Boolean(file && !reading && nodeId && code && (!isNewItem || (newItemTitle.trim().length >= 3 && newItemArea))
    && (!(edited && canChange) || templateOk)) // the template is sent only when it was changed here, so only then it has to be a JSON object
  const isNewGraph = graphChoice === NEW_GRAPH
  const oneGraph = batch && plan && plan.graphs.length === 1 ? plan.graphs[0] : null // a set that makes one graph may carry a JSON and a typed name
  const graphNamePending = batchGraphText !== null && (!batchGraphText.trim() || (batchGraphText.trim() !== batchGraph && batchGraphText.trim() !== oneGraph?.name)) // typed and not checked yet, or emptied
  const canAdd = batch ? Boolean(plan && plan.ok > 0 && !planning && (code !== NEW_ITEM || batchItem === newItemTitle.trim()) && !graphNamePending) : isNewGraph && Boolean(graphName.trim()) && (ready || jsonOnly)
  const canAppend = !batch && ((ready && Boolean(chosen)) || (jsonOnly && Boolean(chosen || chosenKept)))
  // the checked JSON as it is kept: the form's company and graph name win, and graph_id names the graph it replaces or corrects
  const jsonText = (graphId: string | null, name: string | null) => {
    const data = { ...(JSON.parse(held?.text ?? '{}') as Record<string, unknown>) }
    delete data.graph_id
    if (graphId) data.graph_id = graphId
    if (isAdmin && node) { data.company = node.company; delete data.companies }
    if (name) data.graph = name
    return JSON.stringify(data)
  }
  const refusalWords = (reason: unknown) => {
    const body = (reason as { response?: { data?: IngestRefusal } }).response?.data
    return body && Array.isArray(body.problems) ? `${body.detail} ${body.problems.slice(0, 5).join(' · ')}` : detail(reason, 'The JSON was not kept.')
  }

  const submit = async (mode: 'add' | 'append') => {
    if (!(mode === 'add' ? canAdd : canAppend)) return
    setBusy(true)
    setError('')
    if (batch) { // every file the check passed is kept, each in the graph of its folder
      try {
        const { data } = await addUploads(batchForm(batch, false))
        clearBatch()
        if (data.new_item) { setCode(data.new_item.code); setNewItemTitle(''); setBatchItem(''); setItemsLoaded((n) => n + 1) }
        if (held && data.graphs.length === 1 && data.saved.length > 0) { // the files are kept: the checked JSON is kept as the drawing of their graph
          try {
            await ingestGraph(jsonText(data.graphs[0].id, data.graphs[0].name))
            onSaved({ kind: 'batch', result: { ...data, notes: [...data.notes, 'Your JSON is kept as the drawing of this graph.'] } })
          } catch (reason) {
            onSaved({ kind: 'batch', result: data }, true)
            setError(`The files were kept in "${data.graphs[0].name}", but your JSON was not. ${refusalWords(reason)} Change the JSON, then press Append to the graph with this graph chosen.`)
          }
          return
        }
        onSaved({ kind: 'batch', result: data }, true)
      } catch (reason) {
        setError(detail(reason, 'The files were not kept.'))
      } finally {
        setBusy(false)
      }
      return
    }
    if (!file) { // the checked JSON alone: a new graph, or the graph chosen replaced or corrected
      try {
        const { data } = await ingestGraph(jsonText(mode === 'append' ? graphChoice : null, mode === 'add' ? graphName.trim() : null))
        setGraphName('')
        setGraphChoice('')
        onSaved({ kind: 'ingested', result: data })
      } catch (reason) {
        setError(refusalWords(reason))
      } finally {
        setBusy(false)
      }
      return
    }
    const form = new FormData()
    form.append('file', file)
    form.append('node_id', nodeId)
    form.append('datapoint', code)
    if (isNewItem) { form.append('new_item_title', newItemTitle.trim()); form.append('new_item_area', newItemArea) }
    form.append('title', title)
    form.append('tags', tags)
    form.append(mode === 'add' ? 'graph_name' : 'graph_id', mode === 'add' ? graphName.trim() : graphChoice)
    if (edited && canChange) form.append('output_template', templateText) // kept with the context graph, checked before the file is kept
    try {
      const { data } = await addUpload(form)
      if (mode === 'add') { setGraphName(''); setGraphChoice(data.context_graph.id) } // the new graph is now an existing one
      if (data.new_item) { setCode(data.new_item.code); setNewItemTitle(''); setItemsLoaded((n) => n + 1) }
      if (edited && canChange) { markEdited(false); getGraphTemplate(data.context_graph.id).then((r) => setOwn(r.data.own)).catch(() => undefined) }
      reads.current += 1 // the file is kept: the form is cleared, so the same file is not added twice
      setFile(null)
      setSuggestion(null)
      offered.current = null
      setTitle('')
      setTags('')
      if (fileInput.current) fileInput.current.value = ''
      if (!held) { onSaved({ kind: 'upload', record: data }); return }
      try { // the file is kept: the checked JSON is kept as the drawing of its graph
        const { data: kept } = await ingestGraph(jsonText(data.context_graph.id, data.context_graph.name))
        onSaved({ kind: 'ingested', result: kept })
      } catch (reason) {
        onSaved({ kind: 'upload', record: data }, true)
        setGraphChoice(data.context_graph.id)
        setError(`The file was kept in "${data.context_graph.name}", but your JSON was not. ${refusalWords(reason)} Change the JSON, then press Append to the graph with this graph chosen.`)
      }
    } catch (reason) {
      setError(detail(reason, 'The file was not kept.'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="mesh-section-panel">
      <form className="context-form" onSubmit={(event) => { event.preventDefault(); void submit(canAdd ? 'add' : 'append') }} aria-label="Upload input">
        <div className="context-file-field">
          <label htmlFor="context-file">File</label>
          <div className="context-file-row">
            <input ref={fileInput} id="context-file" className="mesh-field" type="file" accept={isAdmin ? '.txt,.md,.csv,.json,.pdf,.docx,.zip' : '.json,application/json'} multiple={isAdmin} onChange={(event) => (isAdmin ? chooseFiles(event.target.files) : chooseFile(event.target.files?.[0] ?? null))} />
            {isAdmin && <>
              <label className="mesh-outline-action" style={{ display: 'inline-flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}><FolderUp size={15} aria-hidden />Choose a folder<input ref={(el) => { folderInput.current = el; if (el) { el.setAttribute('webkitdirectory', ''); el.setAttribute('directory', '') } }} type="file" multiple hidden onChange={(event) => chooseFiles(event.target.files, true)} /></label>
              {batch && <button type="button" className="mesh-outline-action" onClick={clearBatch}><X size={15} aria-hidden />Clear the files</button>}
            </>}
          </div>
          <span>{batch ? (planning ? `Reading ${batch.label}` : plan ? `Read ${batch.label}: ${plural(plan.ok, 'file')} for ${plural(plan.graphs.length, 'context graph')}${plan.refused ? `, ${plural(plan.refused, 'file')} cannot be kept` : ''}. Each subfolder is one graph` : `Chosen: ${batch.label}`)
            : reading ? 'Reading the file' : suggestion
            ? `Read from the file${suggestion.decided_by === 'model' ? ' and confirmed by the model' : ''}: kind ${KIND_WORDS[suggestion.kind.kind] ?? suggestion.kind.label ?? suggestion.kind.kind}, ${suggestion.concepts.length || 'no known'} ${suggestion.concepts.length === 1 ? 'concept' : 'concepts'}. ${suggestion.graph.mode === 'append' ? `It fits the context graph "${suggestion.graph.name}"${fitWords(suggestion)}` : 'No existing context graph fits, so it starts a new one'}. Every field below can be changed`
            : !isAdmin ? 'A graph JSON (.json) with nodes and edges. A mesh admin uploads documents'
            : 'A document (.txt, .md, .csv, .json, .pdf or .docx, up to 20 MB), several documents, a .zip of a folder, or a graph JSON with nodes and edges'}</span>
        </div>
        {batch && plan && <div className="context-batch" aria-label="Files to add">
          <table><thead><tr><th>File</th><th>Context graph</th><th>Title</th><th>Kind</th><th></th></tr></thead>
            <tbody>{plan.entries.map((x) => x.status === 'ok'
              ? <tr key={x.path}><td>{x.path}</td><td>{x.graph}{x.graph_id ? '' : ' (new)'}</td><td>{x.title}</td><td>{KIND_WORDS[x.kind ?? ''] ?? x.kind}</td><td><em className="approved">will be added</em></td></tr>
              : <tr key={x.path} className="refused"><td>{x.path}</td><td colSpan={3}>{x.reason}</td><td><em>not kept</em></td></tr>)}</tbody></table>
          {plan.notes.map((n) => <small key={n}>{n}</small>)}
        </div>}
        {isAdmin && <div className="context-form-row">
          <label>Company
            <select className="mesh-field" value={nodeId} onChange={(event) => setNodeId(event.target.value)}>{nodes.map((n) => <option key={n.node_id} value={n.node_id}>{n.company}</option>)}</select>
            <span>{jsonOnly ? 'The company that owns the graph, taken from your JSON' : node?.shared ? 'For a file that belongs to no single company' : 'The company that owns the file'}</span>
          </label>
          {!jsonOnly && <label>Catalogue item
            <select className="mesh-field" value={code} onChange={(event) => setCode(event.target.value)}>
              {items.map((i) => <option key={i.code} value={i.code}>{i.code} · {i.title}</option>)}
              {areas.length > 0 && <option value={NEW_ITEM}>Other: a new item</option>}
            </select>
            <span>{isNewItem ? sharingWords({ ceiling: 'MD', never_leave: true }, node?.company ?? nodeId) : item ? sharingWords({ ...item, shared: node?.shared }, node?.company ?? nodeId) : 'Decides how much of the file other companies can see'}</span>
          </label>}
        </div>}
        {isAdmin && !jsonOnly && isNewItem && <div className="context-form-row">
          <label>Name of the new item
            <input className="mesh-field" value={newItemTitle} maxLength={120} onChange={(event) => setNewItemTitle(event.target.value)} onBlur={() => setBatchItem(newItemTitle.trim())} />
            <span>At least 3 letters</span>
          </label>
          <label>Area
            <select className="mesh-field" value={newItemArea} onChange={(event) => setNewItemArea(event.target.value)}>{areas.map((a) => <option key={a.domain} value={a.domain}>{a.title.charAt(0).toUpperCase() + a.title.slice(1)}</option>)}</select>
            <span>The knowledge area the new item belongs to</span>
          </label>
        </div>}
        {!batch && <div className="context-form-row">
          <label>Context graph
            <select className="mesh-field" value={graphChoice} onChange={(event) => setGraphChoice(event.target.value)}>
              <option value="">Choose a graph</option>
              {open.map((g) => <option key={g.id} value={g.id}>{g.name} · {g.inputs} {g.inputs === 1 ? 'input' : 'inputs'}</option>)}
              {(jsonOnly || !isAdmin) && replaceable.map((g) => <option key={g.id} value={g.id}>{g.name} · graph JSON</option>)}
              <option value={NEW_GRAPH}>New context graph</option>
            </select>
            <span>{chosenKept ? `Append replaces this graph with your JSON`
              : chosen && jsonOnly ? 'Append keeps your JSON as the corrected drawing of this graph. Its inputs stay'
              : chosen ? `Append adds the file to this graph${held ? ' and keeps your JSON as its drawing' : ''}. It has ${chosen.inputs} ${chosen.inputs === 1 ? 'input' : 'inputs'}${chosen.companies.length ? ` from ${chosen.companies.join(', ')}` : ''}`
              : isNewGraph ? (file ? `Add creates a new graph with the file${held ? ' and keeps your JSON as its drawing' : ''}` : 'Add creates a new graph from your JSON')
              : file || !isAdmin ? 'Chosen from the file once the file is read' : 'Choose a file, or paste a graph JSON'}</span>
          </label>
          {isNewGraph && <label>Name of the new graph
            <input className="mesh-field" value={graphName} maxLength={80} onChange={(event) => setGraphName(event.target.value)} />
            <span>{suggestion && graphName === suggestion.graph.name ? 'Taken from the title of the file' : 'Needed before Add to the graph'}</span>
          </label>}
        </div>}
        {isAdmin && !jsonOnly && !batch && <div className="context-form-row">
          <label>Title
            <input className="mesh-field" value={title} maxLength={200} onChange={(event) => setTitle(event.target.value)} />
            <span>{suggestion && title === suggestion.title ? 'Taken from the file' : 'Leave empty to take it from the file'}</span>
          </label>
          <label>Tags
            <input className="mesh-field" value={tags} onChange={(event) => setTags(event.target.value)} />
            <span>{suggestion && tags === suggestion.tags.join(', ') ? 'The concepts found in the file' : 'Separated by commas. Leave empty to take them from the file'}</span>
          </label>
        </div>}
        {oneGraph && oneGraph.new && <div className="context-form-row">
          <label>Name of the graph
            <input className="mesh-field" value={batchGraphText ?? oneGraph.name} maxLength={80} onChange={(event) => setBatchGraphText(event.target.value)}
              onBlur={() => { const t = (batchGraphText ?? '').trim(); if (!t) { setBatchGraph(''); setBatchGraphText(null) } else if (t !== oneGraph.name) setBatchGraph(t) }} />
            <span>{batchGraphText !== null && !batchGraphText.trim() ? 'Type a name. An empty field takes the name of the folder again' : 'Taken from the name of the folder. Every file listed goes into this graph'}</span>
          </label>
        </div>}
        <div className="context-form-row" style={batch && !oneGraph ? { display: 'none' } : undefined}>
          <div className="context-template-actions">
            <span className="context-template-label">{canChange ? 'JSON structure' : 'Graph JSON'}</span>
            <div className="context-template-buttons">
              {canChange && <button type="button" className="mesh-outline-action" aria-label={editing ? 'Close the JSON structure' : 'Edit the JSON structure'} aria-expanded={editing} onClick={() => setEditing((e) => !e)}>{editing ? <X size={15} aria-hidden /> : <Pencil size={15} aria-hidden />}{editing ? 'Close' : 'Edit'}</button>}
              {canChange && <button type="button" className="mesh-outline-action" aria-label="Download the JSON structure" onClick={downloadTemplate} disabled={!templateOk}><Download size={15} aria-hidden />Download</button>}
              {held ? <>
                <button type="button" className="mesh-outline-action" onClick={() => onPasteJson(held.text, held.name)}><Pencil size={15} aria-hidden />Change</button>
                <button type="button" className="mesh-outline-action" onClick={onRemoveJson}><X size={15} aria-hidden />Remove</button>
              </> : <button type="button" className="mesh-outline-action" onClick={() => onPasteJson('', '')}><Braces size={15} aria-hidden />Paste a graph JSON</button>}
              {canChange && <label className="mesh-outline-action" aria-label="Upload a JSON structure"><Upload size={15} aria-hidden />Upload<input type="file" accept=".json" hidden onChange={(event) => { loadTemplateFile(event.target.files?.[0] ?? null); event.target.value = '' }} /></label>}
            </div>
            <span className="context-template-hint">{held ? `Checked: "${held.result.graph.name}" · ${plural(held.result.graph.nodes, 'node')} · ${plural(held.result.graph.edges, 'edge')} · ${held.result.graph.sensitivity}. Add or Append keeps it`
              : !canChange ? 'Have your own graph as JSON? Paste it and press Ingest. Add or Append then keeps it'
              : edited ? `Changed. ${chosen ? 'Append' : 'Add'} saves it with ${chosen ? `"${chosen.name}"` : 'the new graph'}`
              : own && chosen ? `The JSON file of "${chosen.name}" follows this JSON structure` : 'The JSON file of the context graph follows this JSON structure. It can be changed'}</span>
          </div>
        </div>
        {editing && canChange && <div className="context-template-editor">
          <textarea className="mesh-field" value={templateText} spellCheck={false} readOnly={!canChange} aria-label="JSON structure" onChange={(event) => { if (canChange) editTemplate(event.target.value) }} />
          {!canChange ? <span>{'A name in { } is replaced by a value from the graph. A block with "$each" is repeated for each document, node or edge.'}</span> : <span>{templateOk ? 'A name in { } is replaced by a value from the graph. A block with "$each" is repeated for each document, node, edge or concept.' : 'The JSON structure is not valid JSON yet.'} Names that can be used: {Object.entries(fields).filter(([scope]) => scope !== 'link').map(([scope, f]) => `${scope}: ${Object.keys(f).map((k) => `{${k}}`).join(' ')}`).join(' · ')}</span>}
          <div className="context-form-actions">
            <button type="button" className="mesh-outline-action" disabled={!templateOk} onClick={previewTemplate}>Preview</button>
          </div>
          {templateNote && <div className="mesh-alert note">{templateNote}</div>}
          {preview && <pre className="context-template-preview" aria-label="Preview">{preview}</pre>}
        </div>}
        {error && <div role="alert" className="mesh-alert error">{error}</div>}
        <div className="context-form-actions">
          <button type="button" className="mesh-primary-action" disabled={busy || !canAdd} onClick={() => void submit('add')}>{busy ? <LoaderCircle size={15} className="animate-spin" /> : <FileUp size={15} />}{busy ? (file || batch ? 'Reading and linking' : 'Keeping the graph') : batch && plan ? `Add ${plural(plan.ok, 'file')} to the graph` : 'Add to the graph'}</button>
          <button type="button" className="mesh-outline-action" disabled={busy || !canAppend} onClick={() => void submit('append')}><FileUp size={15} />Append to the graph</button>
        </div>
      </form>
    </section>
  )
}

// An ingested graph: its sharing rule, whether the data is invented, who ingested it, and the route to query it by its id
const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`
const sharingOf = (g: IngestedGraphSummary) => (g.sharing === 'group' ? 'Every company of the group' : `${g.company_name} and mesh admins only`)

function IngestedPanel({ graph, onDropped }: { graph: IngestedGraphSummary; onDropped: () => void }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const stamp = stampOf(graph)
  const download = () => {
    setError('')
    getIngestedGraph(graph.id).then(({ data }) => saveJson(data, `context_graph_${fileNameOf(graph.name)}.json`)).catch(() => setError('The JSON could not be downloaded.'))
  }
  const drop = () => {
    if (!window.confirm(`Drop the ${graph.corrects ? 'correction of' : 'context graph'} "${graph.name}"?\n\nIts ${plural(graph.nodes, 'node')} and ${plural(graph.edges, 'edge')} are deleted. The ingest log keeps its id, name, company and counts.${graph.corrects ? ' The uploaded graph and its inputs stay, drawn as they were uploaded.' : ''}`)) return
    setBusy(true)
    setError('')
    dropIngestedGraph(graph.id).then(() => onDropped()).catch((reason) => setError(detail(reason, 'The context graph was not dropped.'))).finally(() => setBusy(false))
  }
  return (
    <section className="mesh-section-panel context-detail" aria-label="Context graph">
      <div className="mesh-section-heading"><div><div className="mesh-eyebrow">{graph.corrects ? 'Corrected with JSON' : 'Ingested JSON'}</div><h2>{graph.name}</h2>
          <small className="mesh-panel-footnote" style={{ margin: 0 }}>{plural(graph.nodes, 'node')} · {plural(graph.edges, 'edge')} · {graph.company_name}</small></div>
        {graph.can_change && <div className="context-graph-actions">
          <button type="button" className="mesh-outline-action danger" disabled={busy} onClick={drop}>{busy ? <LoaderCircle size={14} className="animate-spin" /> : <Trash2 size={14} />}{graph.corrects ? 'Drop the correction' : 'Drop graph'}</button>
        </div>}</div>
      <dl>
        <dt>Graph id</dt><dd>{graph.id}</dd>
        <dt>Sharing</dt><dd>{sharingOf(graph)} · {graph.sensitivity}</dd>
        <dt>Data</dt><dd>{graph.synthetic ? 'Invented for testing' : 'Real data'}</dd>
        {graph.description && <><dt>Description</dt><dd>{graph.description}</dd></>}
        <dt>{graph.updated ? 'Replaced' : 'Ingested'}</dt><dd>{formatDateTime(stamp.at)} by the {stamp.by_role.toLowerCase()} of {stamp.by_company_name ?? stamp.by_company}</dd>
        <dt>Query</dt><dd><code>POST {graph.endpoints.query}</code></dd>
      </dl>
      <div className="context-download"><button type="button" className="mesh-outline-action" onClick={download}><Download size={14} />Download JSON</button></div>
      {error && <div role="alert" className="mesh-alert error">{error}</div>}
    </section>
  )
}

const MAX_JSON_BYTES = 8_000_000 // the largest JSON the server takes

// The person owns the data: the JSON they wrote or chose is checked here and kept nothing of. Check names each place to fix,
// or hands the JSON back to the form, where Add to the graph or Append to the graph keeps it as written
function IngestTab({ companyName, isAdmin, initialText, initialName, onChecked, onCancel, onDocument }: { companyName: string; isAdmin: boolean; initialText: string; initialName: string; onChecked: (text: string, name: string, result: IngestResult) => void; onCancel: () => void; onDocument?: (file: File) => void }) {
  const [text, setText] = useState(initialText)
  const [fileName, setFileName] = useState(initialName)
  const [busy, setBusy] = useState(false)
  const [refusal, setRefusal] = useState<IngestRefusal | null>(null) // stays while the person fixes the places it names
  const [error, setError] = useState('')
  const reads = useRef(0) // the text of a file replaced before it was read is passed over
  const parsed = useMemo(() => {
    if (!text.trim()) return { ok: false, note: '' }
    try { JSON.parse(text); return { ok: true, note: '' } } catch (reason) { return { ok: false, note: `Not valid JSON yet: ${(reason as Error).message}` } }
  }, [text])
  const chooseFile = (picked: File | null) => {
    if (!picked) return
    const read = ++reads.current
    setRefusal(null)
    setError('')
    if (onDocument && (!JSON_FILE.test(picked.name) || picked.size > MAX_JSON_BYTES)) { onDocument(picked); return } // a document goes to the document form
    if (picked.size > MAX_JSON_BYTES) { setError(`${picked.name} has more than ${MAX_JSON_BYTES.toLocaleString()} bytes, the largest JSON that can be ingested.`); return }
    picked.text().then((content) => {
      if (read !== reads.current) return
      if (onDocument && !isGraphJson(content)) { onDocument(picked); return }
      setText(content)
      setFileName(picked.name)
    })
      .catch(() => { if (read === reads.current) setError(`${picked.name} could not be read.`) })
  }
  const downloadSample = () => {
    setError('')
    getIngestSample().then(({ data }) => saveJson(data, 'context_graph_sample.json')).catch(() => setError('The sample could not be downloaded.'))
  }
  const check = async () => {
    if (!parsed.ok || busy) return
    setBusy(true)
    setRefusal(null)
    setError('')
    try {
      const { data } = await checkGraph(text) // the text as written: numbers and keys reach the server unchanged. Nothing is kept
      onChecked(text, fileName, data) // the JSON is held by the form until Add to the graph or Append to the graph
    } catch (reason) {
      const body = (reason as { response?: { data?: IngestRefusal } }).response?.data
      if (body && Array.isArray(body.problems)) setRefusal(body)
      else setError(detail(reason, 'The JSON could not be checked.'))
    } finally {
      setBusy(false)
    }
  }
  const shown = refusal?.problems.slice(0, 30) ?? []
  return (
    <section className="mesh-section-panel">
      <form className="context-form" aria-label="Upload input" onSubmit={(event) => { event.preventDefault(); void check() }}>
        <div className="context-form-row">
          <label>File
            <input className="mesh-field" type="file" accept={onDocument ? '.txt,.md,.csv,.json,.pdf,.docx' : '.json,application/json'} onChange={(event) => { chooseFile(event.target.files?.[0] ?? null); event.target.value = '' }} />
            <span>{fileName ? `Read from ${fileName}. It can be changed below` : 'A graph JSON (.json), or paste it below'}</span>
          </label>
          <div className="context-template-actions">
            <span className="context-template-label">Sample</span>
            <div className="context-template-buttons">
              <button type="button" className="mesh-outline-action" onClick={downloadSample}><Download size={15} aria-hidden />Download sample</button>
              </div>
            <span className="context-template-hint">A small invented graph for {companyName || 'your company'} in the JSON structure</span>
          </div>
        </div>
        <label>JSON
          <textarea className="mesh-field context-ingest-text" value={text} spellCheck={false} onChange={(event) => { setText(event.target.value); setFileName('') }} aria-label="JSON" />
          {parsed.note && <span className="context-parse-note">{parsed.note}</span>}
          <span>{`Needed: "graph" (its name), "company", "nodes" with "type" and "name", and "edges" with "type", "source" and "target". Optional: "sensitivity" (Restricted when missing), "sharing" ("company" when missing, or "group"), "description", and "aliases" and "properties" on a node or an edge. A missing "synthetic" means real data. Keep "graph_id" to replace the graph the JSON came from. `}
            {isAdmin ? 'A mesh admin may name any company and mark a graph as invented with "synthetic": true. A graph of Others needs "sharing": "group".' : `"company" is ${companyName || 'your company'}.`}</span>
        </label>
        {error && <div role="alert" className="mesh-alert error">{error}</div>}
        {refusal && <div role="alert" className="mesh-alert error context-ingest-outcome">
          <strong>{refusal.detail}</strong>
          <ul className="context-ingest-list">{shown.map((problem, i) => <li key={i}>{problem}</li>)}</ul>
          {refusal.problems.length > shown.length && <span>and {refusal.problems.length - shown.length} more</span>}
          <span>Places count from 0, so nodes[0] is the first node.</span>
        </div>}
        <div className="context-form-actions">
          <button type="submit" className="mesh-primary-action" disabled={busy || !parsed.ok}>{busy ? <LoaderCircle size={15} className="animate-spin" /> : <Braces size={15} />}{busy ? 'Ingesting' : 'Ingest'}</button>
          <button type="button" className="mesh-outline-action" onClick={onCancel}>Back to the form</button>
        </div>
      </form>
    </section>
  )
}

// The points to look at in a graph: an input with no concept, a copy, a node with no edge, links waiting for review
// The links taken from the text of one input: each with its sentence, proposed until a mesh admin or the owning company decides
// the state of a link found in the text, said by what settled it: a relation the sentence states, the two topics named
// in full in several sentences, a person, or nobody yet
const linkState = (e: ContextGraphView['edges'][number]) =>
  e.settled_reason === 'relation' ? 'stated in the text'
    : e.settled_reason === 'repeated' ? `named together in ${e.sentences ?? 2} sentences`
      : e.settled_by === 'model' ? 'checked by the model'
        : e.status === 'proposed' ? (e.priority === 'high' ? 'to review' : 'unsure, low priority')
          : e.status === 'approved' ? 'approved by a person' : e.status

// what an input states, by the link that carries it
const STATED: Record<string, string> = { HAS_DECISION: 'Decision', HAS_ACTION: 'Action', HAS_RISK: 'Risk' }

function FoundLinks({ view, docId, canDecide, onDecided }: { view: ContextGraphView; docId: string; canDecide: boolean; onDecided: () => void }) {
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const rank = (e: ContextGraphView['edges'][number]) => (e.status === 'proposed' && e.priority === 'high' ? 0 : e.status === 'proposed' ? 1 : 2)
  const links = view.edges.filter((e) => e.by && e.document === docId && e.type !== 'ABOUT').sort((a, b) => rank(a) - rank(b)) // the ones a person is asked about first
  const aside = (view.set_aside ?? []).filter((e) => e.document === docId)
  if (!links.length && !aside.length) return null
  const label = (id: string) => view.nodes.find((n) => n.id === id)?.label ?? id
  const decide = (linkId: string, status: 'approved' | 'rejected') => {
    setBusy(linkId)
    setError('')
    decideLink(docId, linkId, status).then(() => onDecided()).catch((reason) => setError(detail(reason, 'The link was not changed.'))).finally(() => setBusy(''))
  }
  return (
    <div className="context-found" aria-label="Links found in the text">
      <div className="mesh-eyebrow">Found in the text</div>
      <ul>{links.map((e) => (
        <li key={e.id}>
          {STATED[e.type]
            ? <span><strong>{STATED[e.type]}</strong> {label(e.target)}</span>
            : <><span><strong>{label(e.source)}</strong> {linkWords(e.type)} <strong>{label(e.target)}</strong> <em className={e.status}>{linkState(e)}</em></span>
              <small>"{e.evidence}"{e.by === 'model' ? ' · found by the model' : ''}{e.check_reason ? ` · ${e.check_reason}` : ''}</small></>}
          {canDecide && <span className="context-found-actions">
            {e.status !== 'approved' && <button type="button" className="mesh-outline-action" disabled={busy === e.id} onClick={() => decide(e.id, 'approved')}>Approve</button>}
            <button type="button" className="mesh-outline-action danger" disabled={busy === e.id} onClick={() => decide(e.id, 'rejected')}>Reject</button>
          </span>}
        </li>
      ))}
      {aside.map((e) => (
        <li key={e.id} className="context-found-aside">
          <span><strong>{e.source_label}</strong> {linkWords(e.type)} <strong>{e.target_label}</strong> <em className="rejected">{e.why === 'not_needed' ? 'left out as not needed' : 'set aside by the model'}</em></span>
          <small>"{e.evidence}"{e.reason ? ` · ${e.reason}` : ''}</small>
          {canDecide && <span className="context-found-actions"><button type="button" className="mesh-outline-action" disabled={busy === e.id} onClick={() => decide(e.id, 'approved')}>Approve</button></span>}
        </li>
      ))}</ul>
      {error && <div role="alert" className="mesh-alert error">{error}</div>}
    </div>
  )
}

// What the graph is about. The text is made by code from the inputs until a person writes one, and an emptied text
// brings the made one back
function GraphDescriptionBlock({ graphId, description, onSaved }: { graphId: string; description: GraphDescription; onSaved: () => void }) {
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState(description.text)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const save = (value: string) => {
    setBusy(true)
    setError('')
    describeGraph(graphId, value).then(() => { setEditing(false); onSaved() }).catch((reason) => setError(detail(reason, 'The description was not saved.'))).finally(() => setBusy(false))
  }
  return (
    <div className="context-description" aria-label="Description of the context graph">
      <div className="context-description-head"><span className="mesh-eyebrow">Description</span>
        {description.can_write && !editing && <button type="button" className="mesh-link-action" onClick={() => { setText(description.text); setEditing(true) }}><Pencil size={13} />Edit</button>}</div>
      {!editing && <p>{description.text}</p>}
      {editing && <>
        <textarea className="mesh-field" rows={4} maxLength={1000} value={text} onChange={(event) => setText(event.target.value)} aria-label="Description" />
        <div className="context-form-actions">
          <button type="button" className="mesh-primary-action" disabled={busy || text.trim().length < 20} onClick={() => save(text)}>{busy ? <LoaderCircle size={14} className="animate-spin" /> : null}Save</button>
          <button type="button" className="mesh-outline-action" disabled={busy} onClick={() => setEditing(false)}>Cancel</button>
          {description.by === 'person' && <button type="button" className="mesh-outline-action" disabled={busy} onClick={() => save('')}>Use the one made from the inputs</button>}
        </div>
      </>}
      {error && <div role="alert" className="mesh-alert error">{error}</div>}
    </div>
  )
}

// How an application reads and queries the graph: its id and the three calls, with the id already in them
function UseGraph({ graphId }: { graphId: string }) {
  const [copied, setCopied] = useState('')
  const base = `${window.location.origin}/api/v1/context-graphs/${graphId}`
  const calls = [
    { name: 'Read the graph as JSON', text: `curl -H "Authorization: Bearer $TOKEN" \\\n  ${base}` },
    { name: 'Ask the graph a question', text: `curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \\\n  -d '{"question": "Which topics does this graph cover?"}' \\\n  ${base}/query` },
    { name: 'List its node types and link types', text: `curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \\\n  -d '{"overview": true}' \\\n  ${base}/query` },
    { name: 'Ask without a graph id', text: `curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \\\n  -d '{"question": "Who approves the Letter of Confirmation?"}' \\\n  ${window.location.origin}/api/v1/context-graphs/query` },
  ]
  const copy = (name: string, text: string) => { void navigator.clipboard?.writeText(text).then(() => { setCopied(name); window.setTimeout(() => setCopied(''), 1500) }) }
  return (
    <div className="context-use" aria-label="Use this graph">
      <dl><dt>Graph id</dt><dd><code>{graphId}</code></dd><dt>Access</dt><dd>Each call carries the token of the application or the person. The answer holds only what that caller may see.</dd></dl>
      {calls.map((c) => <div key={c.name} className="context-use-call">
        <div><strong>{c.name}</strong><button type="button" className="mesh-link-action" onClick={() => copy(c.name, c.text)}>{copied === c.name ? <Check size={13} /> : <Copy size={13} />}{copied === c.name ? 'Copied' : 'Copy'}</button></div>
        <pre>{c.text}</pre>
      </div>)}
      <p className="mesh-panel-footnote">Without a graph id the mesh chooses the graph among the ones the caller may see, and the answer names it. The query call with an id also takes a node with its neighbours, nodes or links by type, the path between two nodes, and the nodes most similar to one.</p>
    </div>
  )
}

// a topic, skill, catalogue item or document the search found, with its links. A linked document that is an uploaded input
// opens under its graph, as the list shows it
function EntityPanel({ entity, byDoc, onOpen, onOpenInput }: { entity: GraphEntity; byDoc: Map<string, UploadRecord>; onOpen: (id: string) => void; onOpenInput: (u: UploadRecord) => void }) {
  const navigate = useNavigate()
  const groups = Object.entries(entity.related ?? {})
  const company = entityCompany(entity)
  const askAbout = () => {
    const who = entity.sharing?.shared ? 'the shared inputs' : company || 'the group'
    const question = entity.type === 'Document' ? `What ${entity.sharing?.shared ? 'do' : 'does'} ${who} say in "${entity.label}"?` : `How does ${who} handle ${entity.label}?`
    navigate(`/ask?q=${encodeURIComponent(question)}`)
  }
  return (
    <section className="mesh-section-panel context-detail" aria-label="Entity">
      <div className="mesh-section-heading"><div><div className="mesh-eyebrow">{typeWords(entity.type)}{company ? ` · ${company}` : ''}</div><h2>{entity.label}</h2></div>
        <button type="button" className="mesh-outline-action" onClick={askAbout}>Ask about this</button></div>
      <dl>
        <dt>Id</dt><dd>{entity.id}</dd>
        {entity.aliases.length > 0 && <><dt>Other names</dt><dd>{entity.aliases.join(', ')}</dd></>}
        {entity.sharing && <><dt>Sharing rule</dt><dd>{sharingWords(entity.sharing, entityCompany(entity))}{entity.sharing.item ? ` · ${entity.sharing.code} ${entity.sharing.item}` : ''}</dd></>}
        {entity.owner && <><dt>Owner</dt><dd>{String(entity.owner) === entity.subsidiary ? entityCompany(entity) : String(entity.owner)}</dd></>}
        {Object.entries(entity.properties).filter(([k, v]) => !['subsidiary', 'datapoint', 'aliases', 'shared'].includes(k) && v != null && v !== '' && !(Array.isArray(v) && !v.length)).map(([k, v]) => <Fragment key={k}><dt>{k.charAt(0).toUpperCase() + k.slice(1).replace(/_/g, ' ')}</dt><dd>{Array.isArray(v) ? v.join(', ') : String(v)}</dd></Fragment>)}
      </dl>
      <div className="context-related">
        {!groups.length && <small>No links shown to you.</small>}
        {groups.map(([type, items]) => <div key={type}><h4>{linkWords(type)} ({items.length})</h4><ul>{items.map((i) => {
          const input = i.type === 'Document' ? byDoc.get(i.id) : undefined
          return <li key={i.id}><button type="button" onClick={() => (input ? onOpenInput(input) : onOpen(i.id))} title={i.type}>{i.label}</button></li>
        })}</ul></div>)}
      </div>
    </section>
  )
}
