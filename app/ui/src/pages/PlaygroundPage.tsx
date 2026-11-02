import { useState } from 'react'
import { Send } from 'lucide-react'
import { startSession, resumeSession, type SessionResponse } from '../services/api'

export default function PlaygroundPage() {
  const [session, setSession] = useState<SessionResponse | null>(null)
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const send = async () => {
    if (!input.trim() || busy) return
    setBusy(true)
    setError('')
    try {
      const res = session
        ? await resumeSession(session.session_id, input)
        : await startSession(input)
      setSession(res.data)
      setInput('')
    } catch (e) {
      setError('Request failed — is the API running?')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="max-w-3xl mx-auto space-y-4 animate-fade-in">
      <div>
        <h2 className="text-2xl font-bold text-gray-900">Agent Playground</h2>
        <p className="text-gray-500 mt-1">Talk to the example agent graph over the /api/v1/example route.</p>
      </div>

      <div className="card p-4 min-h-[320px] flex flex-col gap-3">
        <div className="flex-1 space-y-3 overflow-y-auto">
          {session?.messages.map((m, i) => (
            <div
              key={i}
              className={`max-w-[80%] px-4 py-2 rounded-2xl text-sm ${
                m.role === 'user'
                  ? 'ml-auto bg-gradient-zen text-white'
                  : 'bg-gray-100 text-gray-800'
              }`}
            >
              {m.agent && m.role !== 'user' && (
                <div className="text-[10px] uppercase tracking-wide opacity-60 mb-0.5">{m.agent}</div>
              )}
              {m.content}
            </div>
          ))}
          {!session && <div className="text-gray-400 text-sm">Send a message to start a session.</div>}
        </div>

        {error && <div className="text-sm text-red-600">{error}</div>}

        <div className="flex gap-2">
          <input
            className="flex-1 border border-gray-200 rounded-xl px-4 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-zen-400"
            placeholder="Type a message…"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && send()}
          />
          <button
            onClick={send}
            disabled={busy}
            className="bg-gradient-zen text-white px-4 rounded-xl flex items-center gap-2 disabled:opacity-50"
          >
            <Send size={16} /> Send
          </button>
        </div>
      </div>

      {session && (
        <div className="text-xs text-gray-400">
          session {session.session_id} · step {session.current_step} · {session.step_status}
        </div>
      )}
    </div>
  )
}
