import { Check, ChevronDown, Copy, Search } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import meta from './prompt-log-meta.json'
import { SegmentedControl } from '../components/SegmentedControl'

export type PromptEntry = {
  n: number
  timestamp_utc: string
  actor: string
  from: string
  to: string
  model: string
  effort: string
  bead_id: string
  summary: string
  prompt: string
}
type PromptLog = { generated_from: string; entries: PromptEntry[] }

type Kind = 'human' | 'architect' | 'researcher'
const KIND_LABEL: Record<Kind, string> = {
  human: 'Human',
  architect: 'Architect→subagent',
  researcher: 'Researcher',
}

function kindOf(e: PromptEntry): Kind {
  if (e.actor === 'human') return 'human'
  if (e.actor === 'researcher' || e.to === 'researcher') return 'researcher'
  return 'architect'
}

const hhmm = (iso: string) => iso.slice(11, 16)

function elapsed(from: string, to: string): string {
  const mins = Math.max(
    0,
    Math.round((Date.parse(to) - Date.parse(from)) / 60000),
  )
  return `+${Math.floor(mins / 60)}:${String(mins % 60).padStart(2, '0')}`
}

function matches(e: PromptEntry, q: string): boolean {
  return `${e.summary} ${e.prompt} ${e.bead_id}`.toLowerCase().includes(q)
}

function summaryLine(): string {
  if (meta.count === 0) return 'No prompts logged'
  return `${meta.count} prompts · ${meta.human} human · ${meta.count - meta.human} architect→subagent · ${meta.first} … ${meta.last}`
}

function TimelineItem({ entry, start }: { entry: PromptEntry; start: string }) {
  const [show, setShow] = useState(false)
  const [copied, setCopied] = useState(false)
  const kind = kindOf(entry)
  const bodyId = `prompt-${entry.n}-body`

  const copy = () => {
    void navigator.clipboard?.writeText(entry.prompt).then(() => {
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    })
  }

  return (
    <li className="tl-item" data-kind={kind} data-testid="prompt-item">
      <span className="tl-dot" aria-hidden="true" />
      <div className="tl-meta">
        <time dateTime={entry.timestamp_utc} title={entry.timestamp_utc}>
          {hhmm(entry.timestamp_utc)} UTC
        </time>
        <span className="tl-elapsed">
          {elapsed(start, entry.timestamp_utc)}
        </span>
        <span className="tl-actor" data-kind={kind}>
          {kind === 'human' ? 'Human' : 'Architect'}
        </span>
        <span className="tl-route">
          {entry.from} → {entry.to}
        </span>
        {entry.model && <span className="tl-pill">{entry.model}</span>}
        {entry.effort && <span className="tl-pill">{entry.effort}</span>}
        {entry.bead_id && (
          <span className="tl-pill tl-bead">{entry.bead_id}</span>
        )}
      </div>
      <h4 className="tl-title">{entry.summary}</h4>
      <button
        type="button"
        className="btn btn-sm tl-toggle"
        aria-expanded={show}
        aria-controls={bodyId}
        onClick={() => setShow((s) => !s)}
      >
        {show ? 'Hide prompt' : 'Show prompt'}
      </button>
      {show && (
        <div className="tl-prompt source-block" id={bodyId}>
          <button
            type="button"
            className="btn btn-sm source-copy"
            onClick={copy}
          >
            {copied ? (
              <Check size={14} aria-hidden="true" />
            ) : (
              <Copy size={14} aria-hidden="true" />
            )}
            {copied ? 'Copied' : 'Copy'}
          </button>
          <pre>{entry.prompt}</pre>
        </div>
      )}
    </li>
  )
}

function Timeline({ entries }: { entries: PromptEntry[] }) {
  const [kind, setKind] = useState<'all' | Kind>('all')
  const [query, setQuery] = useState('')
  const q = query.trim().toLowerCase()

  const present = useMemo(
    () =>
      (Object.keys(KIND_LABEL) as Kind[]).filter((k) =>
        entries.some((e) => kindOf(e) === k),
      ),
    [entries],
  )
  const shown = useMemo(
    () =>
      entries.filter(
        (e) => (kind === 'all' || kindOf(e) === kind) && (!q || matches(e, q)),
      ),
    [entries, kind, q],
  )
  const options = [
    { value: 'all', label: `All (${entries.length})` },
    ...present.map((k) => ({
      value: k,
      label: `${KIND_LABEL[k]} (${entries.filter((e) => kindOf(e) === k).length})`,
    })),
  ]

  return (
    <>
      <p className="arch-lede">
        The human prompts the architect (Opus), which plans, reviews and
        delegates implementation to Sonnet subagents and researchers. Every
        prompt is logged by <code>scripts/log_prompt.py</code>; the source is{' '}
        <code>docs/prompts/prompt-log.csv</code>.
      </p>
      <div className="decisions-toolbar">
        <SegmentedControl
          label="Actor"
          value={kind}
          options={options}
          onChange={(v) => setKind(v as 'all' | Kind)}
        />
        <div className="input-group">
          <Search size={16} aria-hidden="true" />
          <input
            className="input"
            type="search"
            aria-label="Search prompts"
            placeholder="Search summary, prompt or bead"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <span className="decisions-count" role="status">
          {shown.length === entries.length
            ? `${entries.length} prompts`
            : `${shown.length} of ${entries.length} prompts`}
        </span>
      </div>
      {shown.length === 0 ? (
        <p className="adr-empty">No prompts match.</p>
      ) : (
        <ol className="timeline">
          {shown.map((e) => (
            <TimelineItem
              key={e.n}
              entry={e}
              start={entries[0].timestamp_utc}
            />
          ))}
        </ol>
      )}
    </>
  )
}

export function PromptHistorySection() {
  const [open, setOpen] = useState(
    () => window.location.hash === '#prompt-history',
  )
  const [log, setLog] = useState<PromptLog | null>(null)
  const [failed, setFailed] = useState(false)

  // The log is ~140 kB: fetch it as its own chunk, only once expanded.
  useEffect(() => {
    if (!open || log) return
    let cancelled = false
    import('./prompt-log.json')
      .then((m) => {
        if (!cancelled) setLog(m.default as PromptLog)
      })
      .catch(() => {
        if (!cancelled) setFailed(true)
      })
    return () => {
      cancelled = true
    }
  }, [open, log])

  return (
    <section
      id="prompt-history"
      className="arch-section"
      aria-labelledby="prompt-history-title"
    >
      <h2 id="prompt-history-title">Prompt history</h2>
      <div className="card prompt-card" data-open={open}>
        <button
          type="button"
          className="prompt-toggle"
          aria-expanded={open}
          aria-controls="prompt-history-body"
          onClick={() => setOpen((o) => !o)}
        >
          <span className="prompt-toggle-text">
            <span className="adr-title">
              {open ? 'Hide prompt history' : 'Show prompt history'}
            </span>
            <span className="prompt-summary">{summaryLine()}</span>
          </span>
          <ChevronDown size={18} aria-hidden="true" className="adr-chevron" />
        </button>
        {open && (
          <div className="prompt-body" id="prompt-history-body">
            {failed ? (
              <p className="adr-empty">Could not load the prompt history.</p>
            ) : log ? (
              <Timeline entries={log.entries} />
            ) : (
              <p className="adr-empty" role="status">
                Loading…
              </p>
            )}
          </div>
        )}
      </div>
    </section>
  )
}
