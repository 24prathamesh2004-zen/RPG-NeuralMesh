import { useEffect, useState } from 'react'
import { AppWindow, LoaderCircle, RefreshCw } from 'lucide-react'
import { getApplications } from '../services/api'
import type { ConnectedApplication } from '../services/api'
import { formatDateTime, formatFact } from '../lib/format'

export default function ApplicationsPage() {
  const [apps, setApps] = useState<ConnectedApplication[]>([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  const load = async () => {
    setLoading(true)
    setError('')
    try {
      setApps((await getApplications()).data.applications)
    } catch (reason) {
      setError((reason as { response?: { data?: { detail?: string } } }).response?.data?.detail ?? 'The applications could not be read.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void load() }, [])

  return (
    <div className="mesh-data-page">
      <header className="mesh-page-heading">
        <div><div className="mesh-eyebrow">Connected applications</div><h1>Applications</h1><p>Each application has its own list of terms and asks the mesh for context in the same way. It never keeps the documents of a company or the sharing rules.</p></div>
        <button type="button" className="mesh-outline-action" onClick={() => void load()} disabled={loading}><RefreshCw size={14} className={loading ? 'animate-spin' : ''} />Refresh</button>
      </header>
      {error && <div role="alert" className="mesh-alert error">{error}</div>}
      {loading && !apps.length && <div className="mesh-alert pending"><LoaderCircle size={16} className="animate-spin" />Reading…</div>}
      <div className="app-cards">
        {apps.map((app) => (
          <section className="mesh-section-panel" key={app.id}>
            <div className="mesh-section-heading"><div><div className="mesh-eyebrow">{app.domain} domain</div><h2>{app.name}</h2></div><AppWindow size={17} className="mesh-accent-icon" /></div>
            <p className="app-identity"><strong>Identity</strong> <code>{app.identity}</code></p>
            <div className="app-facts">
              {Object.entries(app.facts).map(([k, v]) => <div key={k}><strong className={/^[\d.,% ]+$/.test(String(formatFact(v))) ? undefined : 'words'}>{formatFact(v)}</strong><span>{k.replace(/_/g, ' ')}</span></div>)}
            </div>
            <h3>Tools it calls</h3>
            <div className="app-tools">{app.tools.map((t) => <code key={t}>{t}</code>)}</div>
            <h3>What it loaded</h3>
            <p className="app-loaded">{app.loaded.entities} entities and {app.loaded.links} links from {app.loaded.sources.length} source{app.loaded.sources.length === 1 ? '' : 's'}{app.loaded.warnings > 0 && `, ${app.loaded.warnings} ${app.loaded.warnings === 1 ? 'link' : 'links'} whose other end is not loaded yet`}</p>
            {app.loaded.sources.length > 0 && <ul className="app-sources">{app.loaded.sources.map((s) => <li key={s}><code>{s}</code></li>)}</ul>}
            {app.imports && <>
              <h3>Packs it sends</h3>
              <p className="app-loaded">{app.imports.kept} kept{app.imports.last_loaded_at ? `, last one loaded ${formatDateTime(app.imports.last_loaded_at)}` : ''}</p>
              {app.imports.last_send
                ? <p className="app-loaded">Latest send {formatDateTime(app.imports.last_send.at)}: {app.imports.last_send.loaded} loaded, {app.imports.last_send.unchanged} unchanged, {app.imports.last_send.refused} refused</p>
                : <p className="app-loaded">No send recorded yet</p>}
              {app.imports.refused.length > 0
                ? <><p className="app-loaded">Refused, and not loaded since:</p>
                  <ul className="app-refusals">{app.imports.refused.map((r) => <li key={r.pack_id}><code>{r.pack_id}</code> {formatDateTime(r.at)}: {r.reason ?? 'No reason given'}</li>)}</ul></>
                : app.imports.last_send && <p className="app-loaded">Every pack it sent is loaded.</p>}
            </>}
            <p className="mesh-panel-footnote">{app.note}</p>
          </section>
        ))}
      </div>
    </div>
  )
}
