import { useEffect, useMemo, useRef, useState } from 'react'
import { Braces, LoaderCircle, Upload } from 'lucide-react'
import { addUpload, getMeshNodes, getUploadItems } from '../services/api'
import type { MeshNodeInfo, UploadItem, UploadRecord } from '../services/api'
import { sharingWords } from '../lib/format'

const MAX_BYTES = 20_000_000
const EXAMPLE = JSON.stringify({
  title: 'Natural rubber storage review',
  records: [
    { topic: 'Natural rubber', finding: 'Keep rubber lots covered and ventilated. Check moisture and ageing before mixing.' },
    { topic: 'Latex spoilage', finding: 'Compare storage time and temperature to reduce pre-coagulation during transport.' },
  ],
}, null, 2)

function inspectJson(text: string): { valid: boolean; error: string; summary: string } {
  const invalid = (error: string) => ({ valid: false, error, summary: '' })
  if (!text.trim()) return invalid('')
  if (new Blob([text]).size > MAX_BYTES) return invalid('The JSON is larger than 20 MB.')
  try {
    const value: unknown = JSON.parse(text)
    if (value === null || typeof value !== 'object') return invalid('Enter a JSON object or an array of business records.')
    if (Object.keys(value).length === 0) return invalid('Add some business records or document content; the JSON is empty.')
    if ('format' in value && value.format === 'neuralmesh.knowledge-pack') return invalid('Knowledge packs use the context import tool. Enter business records or document content here.')
    const count = Object.keys(value).length
    return { valid: true, error: '', summary: Array.isArray(value) ? `Valid JSON · ${count} array ${count === 1 ? 'entry' : 'entries'}` : `Valid JSON · ${count} top-level ${count === 1 ? 'field' : 'fields'}` }
  } catch (reason) {
    return invalid(`Invalid JSON. ${reason instanceof Error ? reason.message : 'Check the quotes, commas and brackets.'}`)
  }
}

function errorDetail(reason: unknown, fallback: string): string {
  const detail = (reason as { response?: { data?: { detail?: unknown } } }).response?.data?.detail
  return typeof detail === 'string' ? detail : fallback
}

export default function CreateJsonGraphTab({ onCreated }: { onCreated: (record: UploadRecord) => void }) {
  const [text, setText] = useState('')
  const [filename, setFilename] = useState('business-records.json')
  const [graphName, setGraphName] = useState('')
  const [nodes, setNodes] = useState<MeshNodeInfo[]>([])
  const [nodeId, setNodeId] = useState('')
  const [items, setItems] = useState<UploadItem[]>([])
  const [code, setCode] = useState('')
  const [loadingNodes, setLoadingNodes] = useState(true)
  const [loadingItems, setLoadingItems] = useState(false)
  const [loadError, setLoadError] = useState('')
  const [retry, setRetry] = useState(0)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [reading, setReading] = useState(false)
  const fileInput = useRef<HTMLInputElement>(null)
  const fileRead = useRef(0)
  const submitting = useRef(false)
  const validation = useMemo(() => inspectJson(text), [text])
  const node = nodes.find((n) => n.node_id === nodeId)
  const item = items.find((i) => i.code === code)

  useEffect(() => {
    let stale = false
    setLoadingNodes(true)
    setLoadError('')
    getMeshNodes().then(({ data }) => {
      if (stale) return
      const sorted = [...data.nodes].sort((a, b) => Number(Boolean(b.shared)) - Number(Boolean(a.shared)))
      setNodes(sorted)
      setNodeId((current) => sorted.some((n) => n.node_id === current) ? current : sorted[0]?.node_id ?? '')
      if (!sorted.length) setLoadError('No companies are available. Try loading them again.')
    }).catch((reason) => { if (!stale) setLoadError(errorDetail(reason, 'The companies could not be loaded.')) })
      .finally(() => { if (!stale) setLoadingNodes(false) })
    return () => { stale = true }
  }, [retry])

  useEffect(() => {
    if (!nodeId) return
    let stale = false
    setItems([])
    setCode('')
    setLoadingItems(true)
    setLoadError('')
    getUploadItems(nodeId).then(({ data }) => {
      if (stale) return
      const usable = data.items.filter((i) => i.ceiling !== 'LIVE')
      setItems(usable)
      setCode(usable[0]?.code ?? '')
      if (!usable.length) setLoadError('This company has no catalogue item for documents. Choose another company.')
    }).catch((reason) => { if (!stale) setLoadError(errorDetail(reason, 'The catalogue items could not be loaded.')) })
      .finally(() => { if (!stale) setLoadingItems(false) })
    return () => { stale = true }
  }, [nodeId, retry])

  useEffect(() => () => { fileRead.current += 1 }, [])

  const changeText = (value: string) => {
    fileRead.current += 1
    setReading(false)
    setText(value)
    setError('')
  }

  const loadFile = async (file: File | undefined) => {
    if (!file) return
    const read = ++fileRead.current
    setError('')
    if (!file.name.toLowerCase().endsWith('.json')) { setError('Choose a .json file.'); setReading(false); return }
    if (file.size > MAX_BYTES) { setError('The JSON file is larger than 20 MB.'); setReading(false); return }
    setReading(true)
    try {
      const content = await file.text()
      if (read !== fileRead.current) return
      setText(content.replace(/^\uFEFF/, ''))
      setFilename(file.name)
    } catch {
      if (read === fileRead.current) setError('The JSON file could not be read. Try again or paste its content below.')
    } finally {
      if (read === fileRead.current) setReading(false)
    }
  }

  const ready = validation.valid && Boolean(graphName.trim() && nodeId && item) && !loadingNodes && !loadingItems && !loadError && !reading
  const create = async () => {
    if (!ready || submitting.current) return
    submitting.current = true
    setBusy(true)
    setError('')
    const form = new FormData()
    form.append('file', new File([text], filename, { type: 'application/json' }))
    form.append('node_id', nodeId)
    form.append('datapoint', code)
    form.append('graph_name', graphName.trim())
    try {
      const { data } = await addUpload(form)
      onCreated(data)
    } catch (reason) {
      setError(errorDetail(reason, 'The graph could not be created. Your JSON is still here; please try again.'))
    } finally {
      submitting.current = false
      setBusy(false)
    }
  }

  return (
    <section className="mesh-section-panel" aria-label="Create a graph from JSON">
      <div className="mesh-section-heading"><div><h2>Create a graph from JSON</h2><p className="mesh-panel-footnote">Paste business records or document content, or load a JSON file. The content is saved as one input, with links to recognized concepts in the mesh.</p></div></div>
      <form className="context-form" aria-label="Create from JSON" onSubmit={(event) => { event.preventDefault(); void create() }}>
        <fieldset className="context-json-fields" disabled={busy}>
          <div className="context-form-actions">
            <button type="button" className="mesh-outline-action" onClick={() => fileInput.current?.click()}><Upload size={15} />Load JSON file</button>
            <input ref={fileInput} type="file" accept=".json,application/json" hidden aria-label="JSON file" onChange={(event) => { void loadFile(event.target.files?.[0]); event.target.value = '' }} />
            <button type="button" className="mesh-outline-action" onClick={() => { changeText(EXAMPLE); setFilename('business-records.json'); setGraphName((name) => name || 'Natural rubber storage review') }}>Use example</button>
            <button type="button" className="mesh-outline-action" disabled={!validation.valid || reading} onClick={() => changeText(JSON.stringify(JSON.parse(text), null, 2))}>Format JSON</button>
          </div>
          <label>JSON input
            <textarea className="mesh-field context-json-input" value={text} spellCheck={false} placeholder={'{\n  "title": "My document",\n  "content": "Business information to add to the graph"\n}'} aria-describedby="json-input-status" aria-invalid={Boolean(validation.error)} onChange={(event) => changeText(event.target.value)} />
          </label>
          <p id="json-input-status" className={`mesh-panel-footnote${validation.error ? ' context-json-error' : ''}`} aria-live="polite">{reading ? 'Reading the JSON file…' : validation.error || validation.summary || 'A JSON object or an array of records, up to 20 MB.'}</p>
          <label>Graph name
            <input className="mesh-field" value={graphName} maxLength={80} required placeholder="Name this context graph" onChange={(event) => { setGraphName(event.target.value); setError('') }} />
          </label>
          <div className="context-form-row">
            <label>Company
              <select className="mesh-field" value={nodeId} disabled={loadingNodes} onChange={(event) => { setNodeId(event.target.value); setItems([]); setCode(''); setError('') }}>
                {!nodes.length && <option value="">{loadingNodes ? 'Loading companies…' : 'No companies available'}</option>}
                {nodes.map((n) => <option key={n.node_id} value={n.node_id}>{n.company}</option>)}
              </select>
              <span>{node?.shared ? 'For content that belongs to no single company' : 'The company that owns this content'}</span>
            </label>
            <label>Catalogue item
              <select className="mesh-field" value={code} disabled={loadingItems || !items.length} onChange={(event) => { setCode(event.target.value); setError('') }}>
                {!items.length && <option value="">{loadingItems ? 'Loading catalogue items…' : 'No items available'}</option>}
                {items.map((i) => <option key={i.code} value={i.code}>{i.code} · {i.title}</option>)}
              </select>
              <span>{item ? sharingWords({ ...item, shared: node?.shared }, node?.company ?? nodeId) : 'Determines how much of the content other companies can see'}</span>
            </label>
          </div>
          {loadError && <div role="alert" className="mesh-alert error">{loadError}<button type="button" className="mesh-outline-action" onClick={() => setRetry((n) => n + 1)}>Retry loading</button></div>}
          {error && <div role="alert" className="mesh-alert error">{error}</div>}
          <div className="context-form-actions"><button type="submit" className="mesh-primary-action" disabled={!ready || busy}>{busy ? <LoaderCircle size={15} className="animate-spin" /> : <Braces size={15} />}{busy ? 'Creating and linking…' : 'Create graph'}</button></div>
          <p className="mesh-panel-footnote" role="status">{busy ? 'Saving the input and building its graph. This can take a little while.' : 'The saved graph will open under Uploaded inputs.'}</p>
        </fieldset>
      </form>
    </section>
  )
}
