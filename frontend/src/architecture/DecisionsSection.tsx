import {
  ChevronDown,
  ChevronsDownUp,
  ChevronsUpDown,
  Search,
} from 'lucide-react'
import { useMemo, useState } from 'react'
import type { Decision } from './content'

function matches(d: Decision, q: string): boolean {
  const hay = `${d.adr} ${d.title} ${d.decision} ${d.why}`.toLowerCase()
  return hay.includes(q)
}

/** "Name: explanation" lists render the name in bold. */
function Item({ text }: { text: string }) {
  const i = text.indexOf(': ')
  if (i === -1 || i > 40) return <li>{text}</li>
  return (
    <li>
      <strong>{text.slice(0, i)}</strong>
      {text.slice(i)}
    </li>
  )
}

function DecisionCard({
  d,
  open,
  onToggle,
}: {
  d: Decision
  open: boolean
  onToggle: () => void
}) {
  const bodyId = `adr-${d.adr}-body`
  return (
    <article className="card adr" data-open={open} data-testid="adr-card">
      <h3 className="adr-head">
        <button
          type="button"
          aria-expanded={open}
          aria-controls={bodyId}
          onClick={onToggle}
        >
          <span className="adr-badge">ADR-{d.adr}</span>
          <span className="adr-title">{d.title}</span>
          <ChevronDown size={18} aria-hidden="true" className="adr-chevron" />
        </button>
      </h3>
      {!open && <p className="adr-preview">{d.decision}</p>}
      {open && (
        <div className="adr-body" id={bodyId}>
          <dl>
            <div>
              <dt>Decision</dt>
              <dd>{d.decision}</dd>
            </div>
            <div>
              <dt>Why</dt>
              <dd>{d.why}</dd>
            </div>
            <div>
              <dt>Alternatives considered</dt>
              <dd>
                <ul className="adr-list">
                  {d.alternatives.map((a) => (
                    <Item key={a} text={a} />
                  ))}
                </ul>
              </dd>
            </div>
            <div>
              <dt>Trade-offs</dt>
              <dd>
                <ul className="adr-list">
                  {d.tradeoffs.map((t) => (
                    <li key={t}>{t}</li>
                  ))}
                </ul>
              </dd>
            </div>
            <div>
              <dt>Revisit when</dt>
              <dd>{d.revisitWhen}</dd>
            </div>
          </dl>
        </div>
      )}
    </article>
  )
}

export function DecisionsSection({ decisions }: { decisions: Decision[] }) {
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState<ReadonlySet<string>>(new Set())
  const q = query.trim().toLowerCase()
  const shown = useMemo(
    () => (q ? decisions.filter((d) => matches(d, q)) : decisions),
    [decisions, q],
  )
  const toggle = (adr: string) =>
    setOpen((prev) => {
      const next = new Set(prev)
      if (!next.delete(adr)) next.add(adr)
      return next
    })
  const allOpen = shown.length > 0 && shown.every((d) => open.has(d.adr))

  return (
    <section
      id="decisions"
      className="arch-section"
      aria-labelledby="decisions-title"
    >
      <h2 id="decisions-title">Decisions</h2>
      <p className="arch-lede">
        One record per significant choice: what was decided, why, what else was
        considered and when to revisit it.
      </p>
      <div className="decisions-toolbar">
        <div className="input-group">
          <Search size={16} aria-hidden="true" />
          <input
            className="input"
            type="search"
            aria-label="Search decisions"
            placeholder="Search title, decision or reasoning"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <span className="decisions-count" role="status">
          {shown.length === decisions.length
            ? `${decisions.length} decisions`
            : `${shown.length} of ${decisions.length} decisions`}
        </span>
        <button
          type="button"
          className="btn btn-sm"
          disabled={shown.length === 0}
          onClick={() =>
            setOpen(allOpen ? new Set() : new Set(shown.map((d) => d.adr)))
          }
        >
          {allOpen ? (
            <ChevronsDownUp size={14} aria-hidden="true" />
          ) : (
            <ChevronsUpDown size={14} aria-hidden="true" />
          )}
          {allOpen ? 'Collapse all' : 'Expand all'}
        </button>
      </div>
      <div className="adr-list-wrap">
        {shown.map((d) => (
          <DecisionCard
            key={d.adr}
            d={d}
            open={open.has(d.adr)}
            onToggle={() => toggle(d.adr)}
          />
        ))}
        {shown.length === 0 && (
          <p className="card adr-empty">No decisions match “{query.trim()}”.</p>
        )}
      </div>
    </section>
  )
}
