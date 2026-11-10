// One name and one colour for each decision a node records (ALLOWED_BY_CEILING, ALLOWED_SUMMARY_ONLY,
// BLOCKED_BY_POLICY, ...), and one way to show a date, on every page.

export type Tone = 'success' | 'warning' | 'danger'

export function decisionTone(decision: string): Tone {
  if (decision.startsWith('ALLOWED')) return 'success'
  if (decision.startsWith('BLOCKED')) return 'danger'
  return 'warning'
}

// "BLOCKED_BY_POLICY" -> "Blocked by policy"
export function decisionLabel(decision: string): string {
  const words = decision.toLowerCase().replace(/_/g, ' ').trim()
  return words.charAt(0).toUpperCase() + words.slice(1)
}

const ISO_DATE_TIME = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/

// "2026-11-07T14:55:49.693712+00:00" -> "7 Nov 2026, 14:55" (or "7 Nov 2026, 14:55:49") in the viewer's time zone.
// Day before month on every page, so 8 November is never read as 11 August. Anything that is not a date as it is.
export function formatDateTime(value: string, seconds = false): string {
  const when = new Date(value)
  if (Number.isNaN(when.getTime())) return value
  return when.toLocaleString('en-GB', {
    day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', ...(seconds ? { second: '2-digit' } : {}),
  })
}

export function formatFact(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'string' && ISO_DATE_TIME.test(value)) return formatDateTime(value)
  return String(value)
}

// The sentences of a written answer, split by the rule of the answer check (app/services/context/check.py): a sentence
// ends at ., ! or ? (or a closing citation bracket) followed by a space and a capital letter, "[" or the marker, never
// after an abbreviation such as "e.g." or "i.e.". The marker is held aside while splitting, so its own "]" never cuts
// it from the sentence it opens.
export const NOT_IN_EVIDENCE = '[NOT IN EVIDENCE]'
const HOLD = '\u0000NOEVIDENCE\u0000'
const SENTENCE_END = /(?<=[.!?\]])(?<!\b(?:[Ee]\.g|[Ii]\.e|vs|cf|approx|incl|[Nn]o|Dr|Mr|Ms|Mrs)\.)\s+(?=[A-Z[\u0000])/

export function answerSentences(text: string): string[] {
  return text
    .split(NOT_IN_EVIDENCE).join(HOLD)
    .split(SENTENCE_END)
    .map((sentence) => sentence.split(HOLD).join(NOT_IN_EVIDENCE).trim())
    .filter(Boolean)
}

// The rules of the nodes' policy in plain words, for the decision log and the withheld lists. R-NL-<n> is the
// never-leave rule of one company.
const RULES: Record<string, string> = {
  'R-PURPOSE-01': 'Not shared for this purpose',
  'R-EXPOSURE-01': 'Shared as far as the owner allows for this datapoint',
  'R-AGG-01': 'Only totals over enough records, never single records',
  'R-ROLE-01': 'The caller\'s role may not read this node',
  'R-CALLER-01': 'The caller was checked',
  'R-MODE-01': 'Asked for an unknown way of sharing',
  'R-DP-UNKNOWN': 'Unknown datapoint',
  'R-EXPORT-01': 'Only the mesh service may read the node\'s metadata',
  'R-GATED-MISSING': 'Needs an approved request first',
  'R-GRANT-REVOKED': 'An approved access was withdrawn',
  'R-OWNER-APPROVAL': 'The owner approved a request',
  'R-OWNER-DENIAL': 'The owner denied a request',
  'R-EXPERT-CONSENT': 'Only experts who opted in are searched',
  'R-EXPERT-INTRO': 'An introduction needs the owner\'s approval',
  'R-LIVE-01': 'A live lookup at the node',
}

export function ruleMeaning(rule?: string | null): string {
  if (!rule) return ''
  if (/^R-NL-\d+$/.test(rule)) return 'Never leaves its company'
  return RULES[rule] ?? ''
}

// How far a datapoint is shared: the exposure codes of the nodes in words.
const MODES: Record<string, string> = { MD: 'Title only', SUM: 'Approved summary', RAG: 'Document passages', LIVE: 'Live lookup' }

export const modeLabel = (mode?: string | null) => MODES[String(mode ?? '').toUpperCase()] ?? String(mode ?? '')

// The reasons the nodes give for a withheld item, in words for the person who asked.
const REASONS: Record<string, string> = {
  'Purpose is not allowed for this datapoint': 'Not shared for this purpose',
  'Purpose is not allowed': 'Not shared for this purpose',
  'Datapoint is metadata-only': 'Only its title is shared',
  'Owner approval is required': 'Needs the owner\'s approval',
  'Requested mode exceeds the exposure ceiling': 'Asked for more than the owner shares',
  'Datapoint is in a blackout window': 'Not shared during a blackout period',
  'Caller role is not allowed': 'Your role may not read it',
}

export const plainReason = (reason?: string | null) => (reason ? REASONS[reason] ?? reason : '')

// The answer's citations as the numbers of the evidence cards ("[2]"), by the document a card holds. A citation of
// an item that has no card (a withheld item) keeps its id, without the number of a text chunk.
export function citationsAsNumbers(text: string, documents: string[]): string {
  const base = (id: string) => id.split('#')[0]
  const cards = documents.map(base)
  return text.replace(/\[([^\]]+)\]/g, (whole, tag: string) => {
    if (tag === 'NOT IN EVIDENCE') return whole
    const at = cards.indexOf(base(tag))
    return at >= 0 ? `[${at + 1}]` : `[${base(tag)}]`
  })
}

// An entity type of the graph in words: "AssetFamily" reads "asset family", "HRPolicy" reads "HR policy".
export const typeWords = (type: string) =>
  type.replace(/([a-z])([A-Z])/g, '$1 $2').replace(/([A-Z]+)([A-Z][a-z])/g, '$1 $2')
    .split(' ').map((w) => (/^[A-Z]{2,}$/.test(w) ? w : w.toLowerCase())).join(' ')

// A link kind of the graph in words: "IN_DATAPOINT" reads "in datapoint".
export const linkWords = (kind: string) => kind.replace(/_/g, ' ').toLowerCase()

// The actions of the nodes' ledger in words.
const ACTIONS: Record<string, string> = {
  search: 'Search', summarize: 'Summary', find_experts: 'Expert search', describe_capabilities: 'Capabilities read',
  export_graph: 'Metadata export', request_access: 'Access request', request_intro: 'Introduction request',
  review: 'Owner review', live: 'Live lookup', health: 'Health check',
}
export const actionWords = (action: string) => ACTIONS[action] ?? action.replace(/_/g, ' ')

// The mesh's one sentence form for a withheld item ("Withheld: <title>, reason: <reason> [<id>].") in plain words,
// with the reason the Withheld panel gives too and no id.
export function plainWithheld(sentence: string): string {
  // the prompt's form "Withheld: <title>, reason: <reason> [id]." and the stand-in model's form "Withheld: <title> (<reason>) [id]."
  const item = /^Withheld: (.+?)(?:, reason: (.+?)| \(([^()]+)\))\s*(?:\[[^\]]+\])?\.?$/.exec(sentence)
  if (!item) return sentence
  const reason = plainReason(item[2] ?? item[3] ?? '')
  return `Withheld: ${item[1].replace(/\.$/, '')}. ${reason.charAt(0).toUpperCase()}${reason.slice(1)}.`
}

// The codes of a node profile in words: "(SUM)" reads "(approved summary)".
export const profileWords = (text: string) =>
  text.replace(/\((MD|SUM|RAG|LIVE)\)/g, (_, code: string) => `(${modeLabel(code).toLowerCase()})`)

// The level of a node in words, as the dashboard shows it.
export const levelWords = (level?: string | null) =>
  level === 'L1' ? 'L1 · Summaries only' : level === 'L2' ? 'L2 · Summaries and passages' : String(level ?? '')

// The sharing rule of a catalogue item in plain words, as the Add input and Search pages show it
export function sharingWords(rule?: { ceiling?: string | null; never_leave?: boolean; company?: string | null; shared?: boolean } | null, company?: string | null): string {
  if (!rule) return ''
  if (rule.shared) return 'Shared with every connected company'
  const who = company || rule.company || 'the company'
  if (rule.never_leave) return `Never leaves ${who}`
  switch (String(rule.ceiling ?? '').toUpperCase()) {
    case 'MD': return `Title only leaves ${who}`
    case 'SUM': return `Summary leaves ${who}`
    case 'RAG': return `Full text leaves ${who}`
    case 'LIVE': return `Asked live from ${who}`
    default: return ''
  }
}
