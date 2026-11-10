import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { BookOpen, MessageCircle, Send, Trash2, X } from 'lucide-react'
import axios from 'axios'

// Help chat about the NeuralMesh application. Ask NeuralMesh answers about company knowledge, this chat about the app.
// Mounted beside <App /> in main.tsx, shown only when signed in and not on the sign-in page.

const TOKEN_KEY = 'rpg-neuralmesh-token'
const HISTORY_KEY = 'rpg-neuralmesh-help-chat'

interface HelpSource { source: string; title: string; section: string }
interface ChatMessage { role: 'user' | 'assistant'; content: string; sources?: HelpSource[]; mode?: 'model' | 'passages'; error?: boolean }

const SUGGESTIONS = [
  'Give me a quick overview of NeuralMesh',
  'I am new here. Where do I start?',
  'How do I ask a question across RPG companies?',
  'How do I find an expert in another company?',
  'Why is some information withheld from me?',
  'How do I share a document with other companies?',
  'Is my company\'s data safe when I use this?',
  'How is this chat different from Ask NeuralMesh?',
]

function readHistory(): ChatMessage[] {
  try {
    const raw = sessionStorage.getItem(HISTORY_KEY)
    return raw ? (JSON.parse(raw) as ChatMessage[]) : []
  } catch {
    return []
  }
}

/* Minimal Markdown to React: headings, bullet and numbered lists, bold, italics, inline code, code blocks. No HTML injection. */
function inline(text: string, key: string): ReactNode[] {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`|_[^_]+_|\*[^*]+\*)/g).filter(Boolean)
  return parts.map((part, i) => {
    const k = `${key}-${i}`
    if (part.startsWith('**') && part.endsWith('**')) return <strong key={k}>{part.slice(2, -2)}</strong>
    if (part.startsWith('`') && part.endsWith('`')) return <code key={k} className="rounded bg-slate-100 px-1 text-[12px]">{part.slice(1, -1)}</code>
    if ((part.startsWith('_') && part.endsWith('_')) || (part.startsWith('*') && part.endsWith('*'))) return <em key={k}>{part.slice(1, -1)}</em>
    return <span key={k}>{part}</span>
  })
}

function Markdown({ text }: { text: string }) {
  const blocks: ReactNode[] = []
  const lines = text.replace(/\r/g, '').split('\n')
  let list: { ordered: boolean; items: string[] } | null = null
  let para: string[] = []
  let code: string[] | null = null
  const flushPara = () => {
    if (para.length) blocks.push(<p key={`p${blocks.length}`} className="mb-2 last:mb-0">{inline(para.join(' '), `p${blocks.length}`)}</p>)
    para = []
  }
  const flushList = () => {
    if (!list) return
    const items = list.items.map((item, i) => <li key={i}>{inline(item, `l${blocks.length}-${i}`)}</li>)
    blocks.push(list.ordered
      ? <ol key={`o${blocks.length}`} className="mb-2 ml-5 list-decimal space-y-1 last:mb-0">{items}</ol>
      : <ul key={`u${blocks.length}`} className="mb-2 ml-5 list-disc space-y-1 last:mb-0">{items}</ul>)
    list = null
  }
  for (const line of lines) {
    if (line.trim().startsWith('```')) {
      if (code) {
        blocks.push(<pre key={`c${blocks.length}`} className="mb-2 overflow-x-auto rounded bg-slate-900 p-2 text-[12px] text-slate-100">{code.join('\n')}</pre>)
        code = null
      } else {
        flushPara(); flushList(); code = []
      }
      continue
    }
    if (code) { code.push(line); continue }
    const heading = line.match(/^#{1,4}\s+(.*)$/)
    const bullet = line.match(/^\s*[-*]\s+(.*)$/)
    const numbered = line.match(/^\s*\d+[.)]\s+(.*)$/)
    if (heading) {
      flushPara(); flushList()
      blocks.push(<p key={`h${blocks.length}`} className="mb-1 font-semibold">{inline(heading[1], `h${blocks.length}`)}</p>)
    } else if (bullet || numbered) {
      flushPara()
      const ordered = Boolean(numbered)
      if (list && list.ordered !== ordered) flushList()
      if (!list) list = { ordered, items: [] }
      list.items.push((bullet ?? numbered)![1])
    } else if (!line.trim()) {
      flushPara(); flushList()
    } else {
      flushList(); para.push(line.trim())
    }
  }
  if (code) blocks.push(<pre key="cend" className="mb-2 overflow-x-auto rounded bg-slate-900 p-2 text-[12px] text-slate-100">{(code as string[]).join('\n')}</pre>)
  flushPara(); flushList()
  return <>{blocks}</>
}

export default function HelpChat() {
  const [signedIn, setSignedIn] = useState(() => Boolean(localStorage.getItem(TOKEN_KEY)))
  const [path, setPath] = useState(() => window.location.pathname)
  const [open, setOpen] = useState(false)
  const [messages, setMessages] = useState<ChatMessage[]>(readHistory)
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const listRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  // The chat sits outside the router and the auth context, so it follows sign-in and the page by a light check.
  useEffect(() => {
    const check = () => {
      setSignedIn(Boolean(localStorage.getItem(TOKEN_KEY)))
      setPath(window.location.pathname)
    }
    const timer = window.setInterval(check, 1500)
    window.addEventListener('storage', check)
    window.addEventListener('popstate', check)
    return () => { window.clearInterval(timer); window.removeEventListener('storage', check); window.removeEventListener('popstate', check) }
  }, [])

  useEffect(() => {
    try { sessionStorage.setItem(HISTORY_KEY, JSON.stringify(messages.slice(-30))) } catch { /* storage may be blocked */ }
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages, loading])

  useEffect(() => { if (open) window.setTimeout(() => inputRef.current?.focus(), 50) }, [open])

  if (!signedIn || path.startsWith('/auth')) return null

  const send = async (text: string) => {
    const question = text.trim()
    if (!question || loading) return
    const history = messages.filter((m) => !m.error).map(({ role, content }) => ({ role, content: content.slice(0, 4000) })).slice(-8)
    setMessages((prev) => [...prev, { role: 'user', content: question }])
    setInput('')
    setLoading(true)
    try {
      const token = localStorage.getItem(TOKEN_KEY)
      const { data } = await axios.post('/api/v1/help/chat', { question: question.slice(0, 2000), history, page: window.location.pathname }, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        timeout: 90_000,
      })
      setMessages((prev) => [...prev, { role: 'assistant', content: data.answer, sources: data.sources, mode: data.mode }])
    } catch (err) {
      const status = axios.isAxiosError(err) ? err.response?.status : undefined
      const message = status === 401 ? 'Your session has ended. Sign in again to use the help chat.'
        : 'The help chat could not answer just now. Try again in a moment.'
      setMessages((prev) => [...prev, { role: 'assistant', content: message, error: true }])
    } finally {
      setLoading(false)
    }
  }

  return (
    <>
      {open && (
        <section
          role="dialog"
          aria-label="NeuralMesh help chat"
          className="fixed bottom-24 right-4 z-50 flex h-[min(620px,calc(100vh-8rem))] w-[min(400px,calc(100vw-2rem))] flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl"
        >
          <header className="flex items-center gap-3 border-b border-slate-200 bg-indigo-600 px-4 py-3 text-white">
            <span className="grid h-8 w-8 place-items-center rounded-full bg-white/20"><MessageCircle size={17} /></span>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-semibold">NeuralMesh help</p>
              <p className="truncate text-xs text-indigo-100">Questions about using the app. Company knowledge: Ask NeuralMesh</p>
            </div>
            <button type="button" aria-label="Clear the conversation" title="Clear" onClick={() => setMessages([])} className="rounded p-1.5 hover:bg-white/15"><Trash2 size={15} /></button>
            <button type="button" aria-label="Close the help chat" title="Close" onClick={() => setOpen(false)} className="rounded p-1.5 hover:bg-white/15"><X size={16} /></button>
          </header>

          <div ref={listRef} className="flex-1 space-y-3 overflow-y-auto bg-slate-50 px-4 py-4 text-sm text-slate-800">
            {messages.length === 0 && (
              <div className="space-y-3">
                <p className="text-slate-600">Ask how to use NeuralMesh: pages, uploads, context graphs, policies, approvals or any term you see.</p>
                <div className="flex flex-col gap-2">
                  {SUGGESTIONS.map((s) => (
                    <button key={s} type="button" onClick={() => send(s)} className="rounded-lg border border-indigo-200 bg-white px-3 py-2 text-left text-[13px] text-indigo-700 hover:bg-indigo-50">{s}</button>
                  ))}
                </div>
              </div>
            )}
            {messages.map((m, i) => (
              <div key={i} className={m.role === 'user' ? 'flex justify-end' : 'flex justify-start'}>
                <div className={m.role === 'user'
                  ? 'max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-sm bg-indigo-600 px-3 py-2 text-white'
                  : `max-w-[92%] rounded-2xl rounded-bl-sm border px-3 py-2 ${m.error ? 'border-rose-200 bg-rose-50 text-rose-800' : 'border-slate-200 bg-white'}`}>
                  {m.role === 'user' ? m.content : <Markdown text={m.content} />}
                  {m.sources && m.sources.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1 border-t border-slate-100 pt-2">
                      {m.sources.map((s) => (
                        <span key={`${s.source}-${s.section}`} title={`${s.title} > ${s.section} (${s.source})`} className="inline-flex max-w-full items-center gap-1 truncate rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600">
                          <BookOpen size={10} /> {s.section}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ))}
            {loading && (
              <div className="flex justify-start">
                <div className="flex gap-1 rounded-2xl rounded-bl-sm border border-slate-200 bg-white px-3 py-3" aria-label="Writing an answer">
                  <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-slate-400" />
                  <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-slate-400 [animation-delay:150ms]" />
                  <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-slate-400 [animation-delay:300ms]" />
                </div>
              </div>
            )}
          </div>

          <form onSubmit={(e) => { e.preventDefault(); send(input) }} className="flex items-end gap-2 border-t border-slate-200 bg-white p-3">
            <textarea
              ref={inputRef}
              value={input}
              rows={1}
              maxLength={2000}
              placeholder="Ask about NeuralMesh..."
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(input) } }}
              className="max-h-28 min-h-[38px] flex-1 resize-none rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none"
            />
            <button type="submit" aria-label="Send" disabled={loading || !input.trim()} className="grid h-[38px] w-[38px] place-items-center rounded-lg bg-indigo-600 text-white disabled:opacity-40"><Send size={15} /></button>
          </form>
        </section>
      )}

      <button
        type="button"
        aria-label={open ? 'Close the help chat' : 'Open the help chat'}
        title="NeuralMesh help"
        onClick={() => setOpen((v) => !v)}
        className="fixed bottom-5 right-5 z-50 grid h-14 w-14 place-items-center rounded-full bg-indigo-600 text-white shadow-xl transition hover:scale-105 hover:bg-indigo-700"
      >
        {open ? <X size={22} /> : <MessageCircle size={24} />}
      </button>
    </>
  )
}
