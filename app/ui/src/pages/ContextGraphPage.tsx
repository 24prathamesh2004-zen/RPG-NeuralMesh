import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { Download, Eye, FilePlus2, FileUp, LoaderCircle, Pencil, RefreshCw, Upload, X, Search, Trash2, Waypoints } from 'lucide-react'
import { useAuth } from '../auth/AuthContext'
import MeshGraphExplorer, { TYPE_COLOURS } from '../components/MeshGraphExplorer'
import { addUpload, downloadContextGraph, dropContextGraph, getContextGraph, getGraphEntity, getMeshNodes, getGraphTemplate, getUploadItems, getUploads, removeUpload, renderJsonTemplate, searchGraph, suggestUpload } from '../services/api'
import type { CompanyId, ContextGraphSummary, ExportFormat, UploadSuggestion, ContextGraphView, GraphEntity, GraphSearchResult, MeshNodeInfo, NewItemArea, UploadItem, UploadRecord } from '../services/api'
import { formatDateTime, linkWords, sharingWords, typeWords } from '../lib/format'

type Tab = 'inputs' | 'add' | 'search'
interface Focus { graph: string; doc: string | null }
const KIND_WORDS: Record<string, string> = {
  sop: 'Procedure', rca: 'Root cause analysis', playbook: 'Playbook', post_mortem: 'Post-mortem', standard: 'Standard', report: 'Report',
  policy: 'Policy', wiki: 'Wiki page', aggregate: 'Aggregate figures', note: 'Note', study_material: 'Study material', role_profile: 'Role profile', other: 'Other',
}
const NEW_ITEM = 'new' // the value of the Catalogue item choice that names a new item
const MATCH_WORDS: Record<string, string> = { phrase: 'named in the text', words: 'all its words in the text', tag: 'from a tag' }
const FORMAT_WORDS: Record<string, string> = { json: 'Structured JSON', graphml: 'GraphML (for graph tools)', csv: 'CSV (one row per entity and link)', pack: 'Knowledge pack (the documents)' }
const NEW_GRAPH = 'new' // the context graph choice that opens a new graph with the name typed
const REVEAL_ALL_UP_TO = 80 // entities drawn at once. A larger context graph opens from its companies and items, as the mesh graph does

const detail = (reason: unknown, fallback: string) => (reason as { response?: { data?: { detail?: string } } }).response?.data?.detail ?? fallback
const companyOf = (u: UploadRecord) => u.company ?? u.node_id.toUpperCase()
const kindOf = (u: UploadRecord) => (u.document.kind === 'other' && u.document.kind_label) || KIND_WORDS[u.document.kind] || u.document.kind
const itemOf = (u: UploadRecord) => u.sharing.item_title ?? u.document.datapoint.split(':')[1]
const statusOf = (u: UploadRecord) => (u.status === 'removed' ? `Removed ${u.removed ? formatDateTime(u.removed.at) : ''}` : u.in_graph ? 'In the graph' : 'Not in the graph yet')
const words = (u: UploadRecord) => [u.document.title, u.document.id, u.upload.file, companyOf(u), itemOf(u), u.document.datapoint, kindOf(u), u.document.tags.join(' '),
  u.document.summary ?? '', u.context_graph.name, u.status === 'removed' ? 'removed' : ''].join(' ').toLowerCase()
const matches = (text: string, q: string) => q.toLowerCase().split(/\s+/).filter(Boolean).every((w) => text.includes(w))

export default function ContextGraphPage() {
  const { user } = useAuth()
  const isAdmin = user?.roles.includes('mesh_admin') ?? false
  const [tab, setTab] = useState<Tab>('inputs')
  const [uploads, setUploads] = useState<UploadRecord[]>([])
  const [graphs, setGraphs] = useState<ContextGraphSummary[]>([])
  const [kinds, setKinds] = useState<string[]>([])
  const [exportFormats, setExportFormats] = useState<ExportFormat[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [focus, setFocus] = useState<Focus | null>(null)
  const clearFocus = useCallback(() => setFocus(null), [])
  const [addTarget, setAddTarget] = useState<string | null>(null) // the graph chosen with "Add input to this graph"

  const load = async () => {
    setLoading(true)
    setError('')
    try {
      const { data } = await getUploads()
      setUploads(data.uploads)
      setGraphs(data.graphs)
      setKinds(data.kinds)
      setExportFormats(data.export_format_list ?? data.export_formats.map((id) => ({ id, name: id, custom: false })))
    } catch (reason) {
      setError(detail(reason, 'The uploaded inputs could not be read.'))
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => { void load() }, [])

  return (
    <div className="mesh-data-page">
      <header className="mesh-page-heading">
        <div><div className="mesh-eyebrow">Knowledge in the graph</div><h1>Context graph</h1><p>The inputs uploaded into the mesh, grouped into named context graphs, the part of the graph each one made, and a search over every entity you may see.</p></div>
        <button type="button" className="mesh-outline-action" onClick={() => void load()} disabled={loading}><RefreshCw size={14} className={loading ? 'animate-spin' : ''} />Refresh</button>
      </header>
      {error && <div role="alert" className="mesh-alert error">{error}</div>}
      <div className="mesh-tabs" role="tablist" aria-label="Context graph views">
        <button type="button" role="tab" aria-selected={tab === 'inputs'} className={tab === 'inputs' ? 'active' : ''} onClick={() => setTab('inputs')}><Waypoints size={15} />Uploaded inputs <span>{uploads.length}</span></button>
        <button type="button" role="tab" aria-selected={tab === 'add'} className={tab === 'add' ? 'active' : ''} onClick={() => setTab('add')}><FileUp size={15} />Add input</button>
        <button type="button" role="tab" aria-selected={tab === 'search'} className={tab === 'search' ? 'active' : ''} onClick={() => setTab('search')}><Search size={15} />Search the graph</button>
      </div>
      {tab === 'inputs' && <UploadsTab uploads={uploads} graphs={graphs} loading={loading} isAdmin={isAdmin} focus={focus} onFocusUsed={clearFocus} onChanged={() => void load()} onAddTo={(graphId) => { setAddTarget(graphId); setTab('add') }} />}
      {tab === 'add' && (isAdmin
        ? <AddTab graphs={graphs} initialGraph={addTarget} onAdded={(record) => { setAddTarget(null); setFocus({ graph: record.context_graph.id, doc: record.document.id }); void load().then(() => setTab('inputs')) }} />
        : <div className="ask-empty-results">A mesh admin adds inputs. Your company's uploads and the shared inputs are listed under Uploaded inputs.</div>)}
      {tab === 'search' && <SearchTab />}
    </div>
  )
}

function UploadsTab({ uploads, graphs, loading, isAdmin, focus, onFocusUsed, onChanged, onAddTo }: { uploads: UploadRecord[]; graphs: ContextGraphSummary[]; loading: boolean; isAdmin: boolean; focus: Focus | null; onFocusUsed: () => void; onChanged: () => void; onAddTo: (graphId: string) => void }) {
  const [q, setQ] = useState('')
  const [graphId, setGraphId] = useState<string | null>(null)
  const [docId, setDocId] = useState<string | null>(null)
  const [view, setView] = useState<ContextGraphView | null>(null)
  const [viewError, setViewError] = useState('')
  const [format, setFormat] = useState('json') // the JSON file in the output template of the graph, the same file Add input gives
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState('')

  const graph = graphs.find((g) => g.id === graphId) ?? null
  const emptied = graph !== null && graph.inputs === 0 // every input of the graph was removed: nothing to draw
  useEffect(() => {
    if (focus) {
      setGraphId(focus.graph)
      setDocId(focus.doc)
      onFocusUsed()
    } else if (!graphId && graphs.length) {
      setGraphId((graphs.find((g) => g.inputs > 0) ?? graphs[0]).id)
    }
  }, [focus, graphs, graphId, onFocusUsed])
  useEffect(() => {
    if (!graphId) return
    let stale = false // the answer of a graph left before it came is not shown
    setView(null)
    setViewError('')
    if (emptied) return
    getContextGraph(graphId).then(({ data }) => { if (!stale) setView(data) }).catch((reason) => { if (!stale) setViewError(detail(reason, 'The context graph could not be read.')) })
    return () => { stale = true }
  }, [graphId, uploads, emptied])

  // the list: every context graph whose name, or one of whose inputs, holds every word typed
  const rows = useMemo(() => {
    const query = q.trim()
    return graphs.map((graph) => {
      const inputs = uploads.filter((u) => u.context_graph.id === graph.id)
      const byName = !query || matches(graph.name.toLowerCase(), query)
      const hits = query && !byName ? inputs.filter((u) => matches(words(u), query)) : []
      return { graph, hits, shown: byName || hits.length > 0 }
    }).filter((row) => row.shown)
  }, [graphs, uploads, q])

  const inputs = uploads.filter((u) => u.context_graph.id === graphId)
  const current = inputs.find((u) => u.document.id === docId) ?? null

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
    if (!window.confirm(`Drop the context graph "${graph.name}"?\n\nIts ${kept.length} ${kept.length === 1 ? 'input leaves' : 'inputs leave'} the packs, the indexes and the graph:\n${lines}\n\nThe upload records stay, marked removed.`)) return
    setBusy(true)
    setActionError('')
    dropContextGraph(graph.id).then(({ data }) => {
      setDocId(null)
      const next = graphs.find((g) => g.id !== graph.id && g.inputs > 0)
      if (next) setGraphId(next.id)
      if (Object.keys(data.failed ?? {}).length) setActionError(`The inputs are marked removed, but a pack could not be rebuilt: ${Object.entries(data.failed).map(([pack, why]) => `${pack} (${why})`).join(', ')}. Drop the graph again to retry.`)
      onChanged()
    }).catch((reason) => setActionError(detail(reason, 'The context graph was not dropped.'))).finally(() => setBusy(false))
  }
  const remove = () => {
    if (!current) return
    if (!window.confirm(`Remove "${current.document.title}" from the pack, the index and the graph? The upload record stays, marked removed.`)) return
    setBusy(true)
    setActionError('')
    removeUpload(current.document.id).then(() => onChanged()).catch((reason) => setActionError(detail(reason, 'The document was not removed.'))).finally(() => setBusy(false))
  }

  if (loading && !uploads.length) return <div className="mesh-alert pending"><LoaderCircle size={15} className="animate-spin" />Loading uploaded inputs</div>
  if (!uploads.length) return <div className="ask-empty-results">No input has been uploaded yet.</div>
  return (
    <div className="context-graph-grid">
      <div className="context-upload-list">
        <div className="context-upload-search"><Search size={14} /><input className="mesh-field" value={q} onChange={(event) => setQ(event.target.value)} placeholder="Search the inputs" aria-label="Search the inputs" /></div>
        <div role="list" aria-label="Context graphs" className="context-upload-list">
          {rows.map(({ graph: g, hits }) => (
            <button type="button" role="listitem" key={g.id} className={`context-upload-row ${g.id === graphId ? 'active' : ''}`} onClick={() => { setGraphId(g.id); setDocId(null) }}>
              <strong>{g.name}</strong>
              <small>{g.inputs} {g.inputs === 1 ? 'input' : 'inputs'}{g.removed ? ` · ${g.removed} removed` : ''}{g.companies.length ? ` · ${g.companies.join(', ')}` : ''}</small>
              <small>Latest {formatDateTime(g.latest)}</small>
              {hits.map((u) => <small key={u.document.id} className="context-match">{u.document.title} · {companyOf(u)}</small>)}
            </button>
          ))}
          {!rows.length && <div className="ask-empty-results">No input matches {q}.</div>}
        </div>
      </div>
      <div className="dashboard-stack">
        {graph && <section className="mesh-section-panel context-detail" aria-label="Context graph">
          <div className="mesh-section-heading"><div><div className="mesh-eyebrow">Context graph</div><h2>{graph.name}</h2>
              <small className="mesh-panel-footnote" style={{ margin: 0 }}>{graph.inputs} {graph.inputs === 1 ? 'input' : 'inputs'}{graph.removed ? ` · ${graph.removed} removed` : ''}{graph.companies.length ? ` · ${graph.companies.join(', ')}` : ''}</small></div>
            {isAdmin && <div className="context-graph-actions">
              <button type="button" className="mesh-primary-action" onClick={() => onAddTo(graph.id)}><FilePlus2 size={15} />Add input to this graph</button>
              {graph.inputs > 0 && <button type="button" className="mesh-outline-action danger" disabled={busy} onClick={drop}>{busy ? <LoaderCircle size={14} className="animate-spin" /> : <Trash2 size={14} />}Drop graph</button>}
            </div>}</div>
          <div className="context-inputs" role="list" aria-label="Inputs of the context graph">
            {inputs.map((u) => (
              <button type="button" role="listitem" key={u.document.id} className={`context-upload-row ${u.document.id === docId ? 'active' : ''}`} onClick={() => setDocId(u.document.id === docId ? null : u.document.id)}>
                <strong>{u.document.title}</strong>
                <small>{companyOf(u)} · {itemOf(u)} · {kindOf(u)}</small>
                <small>{u.upload.file} · {formatDateTime(u.upload.at)} · {statusOf(u)}</small>
              </button>
            ))}
          </div>
          {current && <>
            <div className="mesh-section-heading" style={{ marginBottom: 0 }}><div><div className="mesh-eyebrow">{companyOf(current)}</div><h2>{current.document.title}</h2></div><span className={`mesh-result-state ${current.in_graph ? 'success' : 'warning'}`}>{sharingWords(current.sharing, companyOf(current))}</span></div>
            <dl>
              <dt>Document</dt><dd>{current.document.id}</dd>
              <dt>Catalogue item</dt><dd>{current.sharing.item_title ?? current.document.datapoint}</dd>
              <dt>Kind</dt><dd>{kindOf(current)} · version {current.document.version}</dd>
              <dt>File</dt><dd>{current.upload.file} · {current.upload.format} · {current.upload.chars.toLocaleString()} characters of text</dd>
              <dt>Uploaded</dt><dd>{formatDateTime(current.upload.at)} by the {current.upload.by_role.toLowerCase()} of {current.upload.by_company_name ?? current.upload.by_company}</dd>
              {current.document.tags.length > 0 && <><dt>Tags</dt><dd>{current.document.tags.join(', ')}</dd></>}
            </dl>
            {current.document.summary && <p className="mesh-panel-footnote">{current.sharing.shared ? 'What every company may read, the first sentences of the file: ' : 'What the group may read under a summary item, the first sentences of the file: '}{current.document.summary}</p>}
          </>}
          <div className="context-download">
            <label htmlFor="context-format" className="mesh-panel-footnote" style={{ margin: 0 }}>Download this context graph as</label>
            <select id="context-format" value={format} onChange={(event) => setFormat(event.target.value)}>{Object.keys(FORMAT_WORDS).map((f) => <option key={f} value={f}>{FORMAT_WORDS[f]}</option>)}</select>
            <button type="button" className="mesh-outline-action" onClick={() => void download()} disabled={!view}><Download size={14} />Download</button>
            {isAdmin && current && current.status !== 'removed' && <button type="button" className="mesh-outline-action danger" disabled={busy} onClick={remove}>{busy ? <LoaderCircle size={14} className="animate-spin" /> : null}Remove this input</button>}
          </div>
          {actionError && <div role="alert" className="mesh-alert error">{actionError}</div>}
        </section>}
        <section className="mesh-section-panel" aria-label="Graph of the inputs">
          <div className="mesh-section-heading"><div><div className="mesh-eyebrow">Context graph</div><h2>What these inputs are linked to</h2></div>{view && <small className="mesh-panel-footnote" style={{ margin: 0 }}>{view.documents.length} {view.documents.length === 1 ? 'input' : 'inputs'} · {view.nodes.length} entities · {view.edges.length} links</small>}</div>
          {viewError && <div className="mesh-alert error">{viewError}</div>}
          {emptied && <div className="ask-empty-results">Every input of this context graph was removed. The records stay in the list.</div>}
          {!view && !viewError && !emptied && <div className="mesh-alert pending"><LoaderCircle size={15} className="animate-spin" />Loading the context graph</div>}
          {view && <MeshGraphExplorer graph={view} revealAll={view.nodes.length <= REVEAL_ALL_UP_TO} />}
          {view && <div className="context-concepts" aria-label="Linked entities">{view.nodes.filter((n) => !view.documents.includes(n.id)).map((n) => <span key={n.id} title={n.type}>{typeWords(n.type)}: {n.label}{current?.concept_matches?.[n.id] ? ` (${MATCH_WORDS[current.concept_matches[n.id]]})` : ''}</span>)}</div>}
        </section>
      </div>
    </div>
  )
}

// why a file fits a graph, said with the concepts both name. The reason text of the model is not shown: it is free text
const fitWords = (s: UploadSuggestion) => {
  const names = s.graph.shared.map((id) => s.concepts.find((c) => c.id === id)?.label).filter(Boolean) as string[]
  if (!names.length) return ''
  if (names.length > 3) return `, which also covers ${names.slice(0, 3).join(', ')} and ${names.length - 3} more`
  return `, which also covers ${names.length > 1 ? `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}` : names[0]}`
}

function AddTab({ graphs, initialGraph, onAdded }: { graphs: ContextGraphSummary[]; initialGraph: string | null; onAdded: (record: UploadRecord) => void }) {
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
    Object.assign(document.createElement('a'), { href: url, download: 'output_template.json' }).click()
    URL.revokeObjectURL(url)
  }
  const previewTemplate = () => {
    if (!chosen) { setTemplateNote('A preview needs an existing context graph. Choose one in Context graph.'); return }
    setTemplateNote('')
    renderJsonTemplate(chosen.id, parsedTemplate).then(({ data }) => setPreview(JSON.stringify(data.output, null, 2)))
      .catch((reason) => { setPreview(''); setTemplateNote(detail(reason, 'The template could not be used.')) })
  }
  const [code, setCode] = useState('')
  const [graphChoice, setGraphChoice] = useState(initialGraph && graphs.some((g) => g.id === initialGraph && g.inputs > 0) ? initialGraph : '') // the graph Append to the graph adds to
  const [graphName, setGraphName] = useState('')
  const [title, setTitle] = useState('')
  const [tags, setTags] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [done, setDone] = useState<UploadRecord | null>(null)
  const [suggestion, setSuggestion] = useState<UploadSuggestion | null>(null) // what the file says about itself, read before the upload
  const [reading, setReading] = useState(false)
  const reads = useRef(0) // counts the files chosen: the answer for a file that was replaced before it came is passed over
  const offered = useRef<UploadSuggestion | null>(null) // the last suggestion put into the fields. It stays when a file is taken away or cannot be read
  const chooseFile = (picked: File | null) => {
    const read = ++reads.current
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
  const open = graphs.filter((g) => g.inputs > 0)
  const chosen = open.find((g) => g.id === graphChoice)
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
  const canAdd = ready && isNewGraph && Boolean(graphName.trim())
  const canAppend = ready && Boolean(chosen)

  const submit = async (mode: 'add' | 'append') => {
    if (!file || !(mode === 'add' ? canAdd : canAppend)) return
    setBusy(true)
    setError('')
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
      setDone(data)
      if (mode === 'add') { setGraphName(''); setGraphChoice(data.context_graph.id) } // the new graph is now an existing one
      if (data.new_item) { setCode(data.new_item.code); setNewItemTitle(''); setItemsLoaded((n) => n + 1) }
      {
        try {
          if (edited && canChange) { markEdited(false); setOwn((await getGraphTemplate(data.context_graph.id)).data.own) }
          const made = await renderJsonTemplate(data.context_graph.id)
          const url = URL.createObjectURL(new Blob([JSON.stringify(made.data.output, null, 2)], { type: 'application/json' }))
          Object.assign(document.createElement('a'), { href: url, download: `context_graph_${data.context_graph.name.toLowerCase().replace(/[^a-z0-9]+/g, '_')}.json` }).click()
          URL.revokeObjectURL(url)
        } catch (reason) {
          setError(detail(reason, 'The file was saved, but the JSON file could not be made. Download it on Uploaded inputs.'))
          return
        }
      }
      onAdded(data)
    } catch (reason) {
      setError(detail(reason, 'The file was not kept.'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="mesh-section-panel">
      <form className="context-form" onSubmit={(event) => { event.preventDefault(); void submit(canAdd ? 'add' : 'append') }} aria-label="Add input">
        <label>File
          <input className="mesh-field" type="file" accept=".txt,.md,.csv,.json,.pdf,.docx" onChange={(event) => chooseFile(event.target.files?.[0] ?? null)} />
          <span>{reading ? 'Reading the file' : suggestion
            ? `Read from the file${suggestion.decided_by === 'model' ? ' and confirmed by the model' : ''}: kind ${KIND_WORDS[suggestion.kind.kind] ?? suggestion.kind.label ?? suggestion.kind.kind}, ${suggestion.concepts.length || 'no known'} ${suggestion.concepts.length === 1 ? 'concept' : 'concepts'}. ${suggestion.graph.mode === 'append' ? `It fits the context graph "${suggestion.graph.name}"${fitWords(suggestion)}` : 'No existing context graph fits, so it starts a new one'}. Every field below can be changed`
            : '.txt, .md, .csv, .json, .pdf or .docx, up to 20 MB. The title, the tags and the context graph are filled in from the file'}</span>
        </label>
        <div className="context-form-row">
          <label>Company
            <select className="mesh-field" value={nodeId} onChange={(event) => setNodeId(event.target.value)}>{nodes.map((n) => <option key={n.node_id} value={n.node_id}>{n.company}</option>)}</select>
            <span>{node?.shared ? 'For a file that belongs to no single company' : 'The company that owns the file'}</span>
          </label>
          <label>Catalogue item
            <select className="mesh-field" value={code} onChange={(event) => setCode(event.target.value)}>
              {items.map((i) => <option key={i.code} value={i.code}>{i.code} · {i.title}</option>)}
              {areas.length > 0 && <option value={NEW_ITEM}>Other: a new item</option>}
            </select>
            <span>{isNewItem ? sharingWords({ ceiling: 'MD', never_leave: true }, node?.company ?? nodeId) : item ? sharingWords({ ...item, shared: node?.shared }, node?.company ?? nodeId) : 'Decides how much of the file other companies can see'}</span>
          </label>
        </div>
        {isNewItem && <div className="context-form-row">
          <label>Name of the new item
            <input className="mesh-field" value={newItemTitle} maxLength={120} onChange={(event) => setNewItemTitle(event.target.value)} />
            <span>At least 3 letters</span>
          </label>
          <label>Area
            <select className="mesh-field" value={newItemArea} onChange={(event) => setNewItemArea(event.target.value)}>{areas.map((a) => <option key={a.domain} value={a.domain}>{a.title.charAt(0).toUpperCase() + a.title.slice(1)}</option>)}</select>
            <span>The knowledge area the new item belongs to</span>
          </label>
        </div>}
        <div className="context-form-row">
          <label>Context graph
            <select className="mesh-field" value={graphChoice} onChange={(event) => setGraphChoice(event.target.value)}>
              <option value="">Choose a graph</option>
              {open.map((g) => <option key={g.id} value={g.id}>{g.name} · {g.inputs} {g.inputs === 1 ? 'input' : 'inputs'}</option>)}
              <option value={NEW_GRAPH}>New context graph</option>
            </select>
            <span>{chosen ? `Append adds the file to this graph. It has ${chosen.inputs} ${chosen.inputs === 1 ? 'input' : 'inputs'}${chosen.companies.length ? ` from ${chosen.companies.join(', ')}` : ''}` : isNewGraph ? 'Add creates a new graph with the file' : 'Chosen from the file once the file is read'}</span>
          </label>
          {isNewGraph && <label>Name of the new graph
            <input className="mesh-field" value={graphName} maxLength={80} onChange={(event) => setGraphName(event.target.value)} />
            <span>{suggestion && graphName === suggestion.graph.name ? 'Taken from the title of the file' : 'Needed before Add to the graph'}</span>
          </label>}
        </div>
        <div className="context-form-row">
          <label>Title
            <input className="mesh-field" value={title} maxLength={200} onChange={(event) => setTitle(event.target.value)} />
            <span>{suggestion && title === suggestion.title ? 'Taken from the file' : 'Leave empty to take it from the file'}</span>
          </label>
          <label>Tags
            <input className="mesh-field" value={tags} onChange={(event) => setTags(event.target.value)} />
            <span>{suggestion && tags === suggestion.tags.join(', ') ? 'The concepts found in the file' : 'Separated by commas. Leave empty to take them from the file'}</span>
          </label>
        </div>
        <div className="context-form-row">
          <div className="context-template-actions">
            <span className="context-template-label">Output template</span>
            <div className="context-template-buttons">
              <button type="button" className="mesh-outline-action" aria-label={editing ? 'Close the template' : canChange ? 'Edit template' : 'View template'} aria-expanded={editing} onClick={() => setEditing((e) => !e)}>{editing ? <X size={15} aria-hidden /> : canChange ? <Pencil size={15} aria-hidden /> : <Eye size={15} aria-hidden />}{editing ? 'Close' : canChange ? 'Edit' : 'View'}</button>
              <button type="button" className="mesh-outline-action" aria-label="Download template" onClick={downloadTemplate} disabled={!templateOk}><Download size={15} aria-hidden />Download</button>
              {canChange && <label className="mesh-outline-action" aria-label="Upload a template"><Upload size={15} aria-hidden />Upload<input type="file" accept=".json" hidden onChange={(event) => { loadTemplateFile(event.target.files?.[0] ?? null); event.target.value = '' }} /></label>}
            </div>
            <span className="context-template-hint">{!canChange ? 'Every context graph gives its JSON file in this structure. A value a graph does not have is written as null'
              : edited ? `Changed. ${chosen ? 'Append' : 'Add'} saves it with ${chosen ? `"${chosen.name}"` : 'the new graph'}`
              : own && chosen ? `The JSON file of "${chosen.name}" follows this template` : 'The JSON file of the context graph follows this template. It can be changed'}</span>
          </div>
        </div>
        {editing && <div className="context-template-editor">
          <textarea className="mesh-field" value={templateText} spellCheck={false} readOnly={!canChange} aria-label="Template" onChange={(event) => { if (canChange) editTemplate(event.target.value) }} />
          {!canChange ? <span>{'A name in { } is replaced by a value from the graph. A block with "$each" is repeated for each document, node or edge.'}</span> : <span>{templateOk ? 'A name in { } is replaced by a value from the graph. A block with "$each" is repeated for each document, node, edge or concept.' : 'The template is not valid JSON yet.'} Names that can be used: {Object.entries(fields).filter(([scope]) => scope !== 'link').map(([scope, f]) => `${scope}: ${Object.keys(f).map((k) => `{${k}}`).join(' ')}`).join(' · ')}</span>}
          <div className="context-form-actions">
            <button type="button" className="mesh-outline-action" disabled={!templateOk} onClick={previewTemplate}>Preview</button>
          </div>
          {templateNote && <div className="mesh-alert note">{templateNote}</div>}
          {preview && <pre className="context-template-preview" aria-label="Preview">{preview}</pre>}
        </div>}
        {error && <div role="alert" className="mesh-alert error">{error}</div>}
        {done && <div className="mesh-alert note">Saved as {done.document.id} in the context graph "{done.context_graph.name}".{done.new_item ? ` New item ${done.new_item.code} · ${done.new_item.title}.` : ''}{` Kind: ${kindOf(done)}${done.kind_detected ? ` (${done.kind_detected.by === 'model' ? 'detected by the model' : 'detected by word rules'})` : ''}.`} {done.document.concepts?.length ?? 0} concepts linked, {done.rebuild?.index_rows ?? 0} passages can be searched.{done.refresh && !done.refresh.startsWith('loaded') ? ` The shared graph was not updated: ${done.refresh}.` : ''}</div>}
        <div className="context-form-actions">
          <button type="button" className="mesh-primary-action" disabled={busy || !canAdd} onClick={() => void submit('add')}>{busy ? <LoaderCircle size={15} className="animate-spin" /> : <FileUp size={15} />}{busy ? 'Reading and linking' : 'Add to the graph'}</button>
          <button type="button" className="mesh-outline-action" disabled={busy || !canAppend} onClick={() => void submit('append')}><FileUp size={15} />Append to the graph</button>
        </div>
      </form>
    </section>
  )
}

function SearchTab() {
  const navigate = useNavigate()
  const [q, setQ] = useState('')
  const [results, setResults] = useState<GraphSearchResult[]>([])
  const [byVector, setByVector] = useState(false)
  const [searched, setSearched] = useState('') // the query that ran
  const [busy, setBusy] = useState(false)
  const [entity, setEntity] = useState<GraphEntity | null>(null)
  const [error, setError] = useState('')
  const companyName = (e: { company?: string | null; subsidiary?: string | null }) => e.company ?? (e.subsidiary ? e.subsidiary.toUpperCase() : '')

  const run = async (event?: FormEvent) => {
    event?.preventDefault()
    if (!q.trim()) return
    setBusy(true)
    setError('')
    try {
      const { data } = await searchGraph(q.trim())
      setResults(data.results)
      setByVector(data.by_vector)
      setSearched(q.trim())
      setEntity(null)
    } catch (reason) {
      setError(detail(reason, 'The search did not answer.'))
    } finally {
      setBusy(false)
    }
  }
  const open = async (id: string) => {
    try {
      setEntity((await getGraphEntity(id)).data)
    } catch (reason) {
      setError(detail(reason, 'The entity could not be read.'))
    }
  }
  const askAbout = (e: GraphEntity) => {
    const who = e.sharing?.shared ? 'the shared inputs' : companyName(e) || 'the group'
    const question = e.type === 'Document' ? `What ${e.sharing?.shared ? 'do' : 'does'} ${who} say in "${e.label}"?` : `How does ${who} handle ${e.label}?`
    navigate(`/ask?q=${encodeURIComponent(question)}`)
  }
  const groups = useMemo(() => Object.entries(entity?.related ?? {}), [entity])

  return (
    <div className="dashboard-stack">
      <form className="context-search-form" onSubmit={(event) => void run(event)} role="search">
        <input className="mesh-field" value={q} onChange={(event) => setQ(event.target.value)} placeholder="A topic, skill, document title, tag or catalogue code" aria-label="Search the graph" />
        <button type="submit" className="mesh-primary-action" disabled={busy || !q.trim()}>{busy ? <LoaderCircle size={15} className="animate-spin" /> : <Search size={15} />}Search</button>
      </form>
      {error && <div role="alert" className="mesh-alert error">{error}</div>}
      {searched && !results.length && <div className="ask-empty-results">Nothing in the graph matches {searched}.</div>}
      {results.length > 0 && <div className="context-graph-grid">
        <div className="context-results" role="list" aria-label="Search results">
          {byVector && <p className="mesh-panel-footnote">No name matched the words, so these are the closest concepts by meaning.</p>}
          {results.map((r) => (
            <button type="button" role="listitem" key={r.id} className={`context-result ${entity?.id === r.id ? 'active' : ''}`} onClick={() => void open(r.id)}>
              <strong>{r.label}</strong>
              <span className="context-type"><i style={{ background: TYPE_COLOURS[r.type] ?? '#adb5bd' }} />{typeWords(r.type)}</span>
              <small>{[companyName(r) || null, r.sharing ? sharingWords(r.sharing, companyName(r)) : null, `${Object.values(r.connections).reduce((n, c) => n + c, 0)} links`].filter(Boolean).join(' · ')}</small>
              <small>{r.matched === 'label' ? 'Name' : r.matched === 'alias or tag' ? 'Other name or tag' : r.matched}</small>
            </button>
          ))}
        </div>
        <section className="mesh-section-panel context-detail" aria-label="Entity">
          {!entity && <div className="ask-empty-results">Choose a result to see its links.</div>}
          {entity && <>
            <div className="mesh-section-heading"><div><div className="mesh-eyebrow">{typeWords(entity.type)}{companyName(entity) ? ` · ${companyName(entity)}` : ''}</div><h2>{entity.label}</h2></div>
              <button type="button" className="mesh-outline-action" onClick={() => askAbout(entity)}>Ask about this</button></div>
            <dl>
              <dt>Id</dt><dd>{entity.id}</dd>
              {entity.aliases.length > 0 && <><dt>Other names</dt><dd>{entity.aliases.join(', ')}</dd></>}
              {entity.sharing && <><dt>Sharing rule</dt><dd>{sharingWords(entity.sharing, companyName(entity))}{entity.sharing.item ? ` · ${entity.sharing.code} ${entity.sharing.item}` : ''}</dd></>}
              {entity.owner && <><dt>Owner</dt><dd>{String(entity.owner) === entity.subsidiary ? companyName(entity) : String(entity.owner)}</dd></>}
              {Object.entries(entity.properties).filter(([k, v]) => !['subsidiary', 'datapoint', 'aliases', 'shared'].includes(k) && v != null && v !== '' && !(Array.isArray(v) && !v.length)).map(([k, v]) => <Fragment key={k}><dt>{k.charAt(0).toUpperCase() + k.slice(1).replace(/_/g, ' ')}</dt><dd>{Array.isArray(v) ? v.join(', ') : String(v)}</dd></Fragment>)}
            </dl>
            <div className="context-related">
              {!groups.length && <small>No links shown to you.</small>}
              {groups.map(([type, items]) => <div key={type}><h4>{linkWords(type)} ({items.length})</h4><ul>{items.map((i) => <li key={i.id}><button type="button" onClick={() => void open(i.id)} title={i.type}>{i.label}</button></li>)}</ul></div>)}
            </div>
          </>}
        </section>
      </div>}
    </div>
  )
}
