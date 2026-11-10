import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { ArrowRight, Network, UserRoundPlus } from 'lucide-react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { getCompanies } from '../services/api'
import type { CompanyId } from '../services/api'

// Shown until the API answers with the registered companies (GET /auth/companies)
const COMPANIES: { id: CompanyId; label: string }[] = [
  { id: 'ceat', label: 'CEAT' },
  { id: 'kec', label: 'KEC International' },
  { id: 'zensar', label: 'Zensar' },
  { id: 'harrisons', label: 'Harrisons Malayalam' },
]

const DEMO_PASSWORD = 'MeshPilot!2026'
const DEMO_ACCOUNTS: { email: string; label: string }[] = [
  { email: 'presenter@neuralmesh.local', label: 'Group presenter · Zensar' },
  { email: 'ceat.expert@neuralmesh.local', label: 'Materials expert · CEAT' },
  { email: 'kec.expert@neuralmesh.local', label: 'Integration expert · KEC' },
  { email: 'zensar.expert@neuralmesh.local', label: 'AI delivery expert · Zensar' },
  { email: 'harrisons.expert@neuralmesh.local', label: 'Estate operations expert · Harrisons' },
]

export default function AuthPage() {
  const { user, signIn, signUp } = useAuth()
  const navigate = useNavigate()
  const [mode, setMode] = useState<'signin' | 'signup'>('signin')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [company, setCompany] = useState<CompanyId>('ceat')
  const [companies, setCompanies] = useState(COMPANIES)
  useEffect(() => {
    getCompanies().then(({ data }) => { if (data.companies.length) setCompanies(data.companies) }).catch(() => undefined)
  }, [])
  const [expertOptIn, setExpertOptIn] = useState(false)
  const [expertTitle, setExpertTitle] = useState('')
  const [expertSkills, setExpertSkills] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  if (user) return <Navigate to="/ask" replace />

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      if (mode === 'signin') {
        await signIn(email, password)
      } else {
        await signUp({
          email,
          password,
          display_name: displayName,
          company,
          expert_opt_in: expertOptIn,
          expert_title: expertTitle,
          expert_skills: expertSkills.split(',').map((skill) => skill.trim()).filter(Boolean),
        })
      }
      navigate('/ask', { replace: true })
    } catch (requestError: unknown) {
      const message = (requestError as { response?: { data?: { detail?: string } } })
        .response?.data?.detail
      setError(typeof message === 'string' ? message : 'Could not connect to NeuralMesh. Check the API and try again.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="auth-page min-h-screen grid lg:grid-cols-[minmax(0,1.1fr)_minmax(420px,0.9fr)]">
      <section className="auth-story flex flex-col justify-between p-8 sm:p-12 lg:p-16">
        <div className="flex items-center gap-3 text-white">
          <div className="grid h-10 w-10 place-items-center rounded-xl bg-white/15 ring-1 ring-white/30">
            <Network size={20} />
          </div>
          <span className="font-semibold">RPG NeuralMesh</span>
        </div>
        <div className="max-w-xl py-16 lg:py-0">
          <p className="mb-4 text-xs font-semibold uppercase tracking-[0.18em] text-emerald-200">Shared expertise, locally governed</p>
          <h1 className="max-w-lg text-4xl font-semibold leading-tight text-white sm:text-5xl">
            Find the knowledge your next problem needs.
          </h1>
          <p className="mt-6 max-w-lg text-base leading-7 text-white/75">
            Ask across subsidiary knowledge nodes. Each company keeps its sources and decides what can be shared.
          </p>
        </div>
        <p className="text-xs text-white/60">Synthetic data pilot · Local POC identity</p>
      </section>

      <section className="flex items-center justify-center bg-[#f4f5fb] px-5 py-10 sm:px-10">
        <div className="w-full max-w-md">
          <div className="mb-8 flex gap-2 border-b border-stone-200">
            <button type="button" onClick={() => setMode('signin')} className={`auth-tab ${mode === 'signin' ? 'active' : ''}`}>Sign in</button>
            <button type="button" onClick={() => setMode('signup')} className={`auth-tab ${mode === 'signup' ? 'active' : ''}`}>Create account</button>
          </div>
          <h2 className="text-2xl font-semibold text-stone-900">{mode === 'signin' ? 'Welcome back' : 'Join your subsidiary node'}</h2>
          <p className="mt-2 text-sm text-stone-600">
            {mode === 'signin' ? 'Sign in to ask and discover approved expertise.' : 'Create a POC account and optionally share your expert profile.'}
          </p>

          <form onSubmit={submit} className="mt-7 space-y-4">
            {mode === 'signup' && (
              <label className="block text-sm font-medium text-stone-700">
                Your name
                <input required minLength={2} value={displayName} onChange={(event) => setDisplayName(event.target.value)} className="auth-input mt-1.5" autoComplete="name" />
              </label>
            )}
            <label className="block text-sm font-medium text-stone-700">
              Work email
              <input required type="email" value={email} onChange={(event) => setEmail(event.target.value)} className="auth-input mt-1.5" autoComplete="email" />
            </label>
            <label className="block text-sm font-medium text-stone-700">
              Password
              <input required minLength={10} type="password" value={password} onChange={(event) => setPassword(event.target.value)} className="auth-input mt-1.5" autoComplete={mode === 'signin' ? 'current-password' : 'new-password'} />
            </label>
            {mode === 'signup' && (
              <>
                <label className="block text-sm font-medium text-stone-700">
                  Subsidiary
                  <select value={company} onChange={(event) => setCompany(event.target.value as CompanyId)} className="auth-input mt-1.5">
                    {companies.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
                  </select>
                </label>
                <label className="flex cursor-pointer items-start gap-3 rounded-lg border border-stone-200 bg-white p-3 text-sm text-stone-700">
                  <input type="checkbox" checked={expertOptIn} onChange={(event) => setExpertOptIn(event.target.checked)} className="mt-0.5 accent-indigo-600" />
                  <span><span className="block font-medium">I want to be discoverable as an expert</span><span className="mt-1 block text-xs text-stone-600">Only role and skills are searchable. Your name requires an approved introduction.</span></span>
                </label>
                {expertOptIn && (
                  <>
                    <label className="block text-sm font-medium text-stone-700">Role or title<input required value={expertTitle} onChange={(event) => setExpertTitle(event.target.value)} className="auth-input mt-1.5" placeholder="Quality engineer" /></label>
                    <label className="block text-sm font-medium text-stone-700">Skills, comma separated<input required value={expertSkills} onChange={(event) => setExpertSkills(event.target.value)} className="auth-input mt-1.5" placeholder="supplier quality, materials" /></label>
                  </>
                )}
              </>
            )}
            {error && <p role="alert" className="rounded-md bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</p>}
            <button type="submit" disabled={busy} className="flex w-full items-center justify-center gap-2 rounded-lg bg-[#4c5fd5] px-4 py-3 text-sm font-semibold text-white transition hover:bg-[#3f51c5] disabled:opacity-60">
              {busy ? 'Please wait…' : mode === 'signin' ? 'Sign in' : 'Create account'}
              {!busy && (mode === 'signup' ? <UserRoundPlus size={16} /> : <ArrowRight size={16} />)}
            </button>
          </form>
          {import.meta.env.DEV && mode === 'signin' && (
            <section className="demo-login-panel" aria-label="Presentation demo accounts">
              <div className="demo-login-heading"><strong>Presentation accounts</strong><span>Local synthetic data</span></div>
              <div className="demo-login-list">
                {DEMO_ACCOUNTS.map((account) => (
                  <button
                    type="button"
                    key={account.email}
                    className="demo-login-choice"
                    onClick={() => { setEmail(account.email); setPassword(DEMO_PASSWORD); setError('') }}
                  >
                    <span><strong>{account.label}</strong><small>{account.email}</small></span>
                    <ArrowRight size={14} />
                  </button>
                ))}
              </div>
              <p>Shared demo password: <code>{DEMO_PASSWORD}</code></p>
            </section>
          )}
          <p className="mt-5 text-center text-xs text-stone-600">POC accounts use synthetic data and are stored locally.</p>
          <Link to="/" className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:rounded focus:bg-white focus:px-3 focus:py-2 focus:text-sm">Back to dashboard</Link>
        </div>
      </section>
    </main>
  )
}