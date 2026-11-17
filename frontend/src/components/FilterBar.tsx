import { ArrowDown, ArrowUp, RotateCcw, Star, X } from 'lucide-react'
import { PAGE_SIZES } from '../format'
import { DebouncedInput } from './DebouncedInput'
import { SegmentedControl } from './SegmentedControl'

export type Patch = Record<string, string | undefined>

type Props = {
  language: string
  minStars: string
  archived: string
  type: string
  sort: string
  /** Effective order (explicit or the default for the sort key). */
  order: 'asc' | 'desc'
  limit: string
  paging: string
  languages: string[]
  onChange: (patch: Patch) => void
  onReset: () => void
}

export function FilterBar(p: Props) {
  const chips: { key: string; label: string; clear: Patch }[] = []
  if (p.language)
    chips.push({
      key: 'language',
      label: `Language: ${p.language}`,
      clear: { language: undefined },
    })
  if (p.minStars)
    chips.push({
      key: 'min_stars',
      label: `Stars ≥ ${p.minStars}`,
      clear: { min_stars: undefined },
    })
  if (p.archived)
    chips.push({
      key: 'archived',
      label: p.archived === 'true' ? 'Archived only' : 'Active only',
      clear: { archived: undefined },
    })
  if (p.type !== 'all')
    chips.push({
      key: 'type',
      label: p.type === 'forks' ? 'Forks only' : 'Sources only',
      clear: { type: undefined },
    })
  const active = chips.length > 0
  const orderName = p.order === 'asc' ? 'ascending' : 'descending'

  return (
    <section className="card filters" aria-label="Filters">
      <div className="filter-grid">
        <div className="field f-language">
          <label className="field-label" htmlFor="language">
            Language
          </label>
          <DebouncedInput
            id="language"
            list="languages"
            value={p.language}
            onCommit={(v) => p.onChange({ language: v.trim() })}
            placeholder="Any (or “none”)"
            title="Type “none” for repositories with no language"
          />
          <datalist id="languages">
            {p.languages.map((l) => (
              <option key={l} value={l} />
            ))}
          </datalist>
        </div>
        <div className="field f-stars">
          <label className="field-label" htmlFor="min_stars">
            Min stars
          </label>
          <DebouncedInput
            id="min_stars"
            type="number"
            min={0}
            value={p.minStars}
            placeholder="0"
            icon={<Star size={14} aria-hidden="true" />}
            onCommit={(v) => p.onChange({ min_stars: v })}
          />
        </div>
        <div className="f-archived">
          <SegmentedControl
            label="Archived"
            value={p.archived}
            options={[
              { value: '', label: 'Any' },
              { value: 'false', label: 'Active' },
              { value: 'true', label: 'Archived' },
            ]}
            onChange={(v) => p.onChange({ archived: v || undefined })}
          />
        </div>
        <div className="f-type">
          <SegmentedControl
            label="Type"
            value={p.type}
            options={[
              { value: 'all', label: 'All' },
              { value: 'sources', label: 'Sources' },
              { value: 'forks', label: 'Forks' },
            ]}
            onChange={(v) => p.onChange({ type: v === 'all' ? undefined : v })}
          />
        </div>
        <div className="field f-sort">
          <label className="field-label" htmlFor="sort">
            Sort
          </label>
          <div className="field-row">
            <select
              id="sort"
              className="select"
              value={p.sort}
              onChange={(e) => p.onChange({ sort: e.target.value })}
            >
              <option value="stars">Stars</option>
              <option value="updated">Updated</option>
              <option value="pushed">Pushed</option>
              <option value="name">Name</option>
            </select>
            <button
              type="button"
              className="btn btn-icon"
              aria-label={`Order: ${orderName}. Switch to ${p.order === 'asc' ? 'descending' : 'ascending'}`}
              title={`Order: ${orderName} (click to flip)`}
              onClick={() =>
                p.onChange({ order: p.order === 'asc' ? 'desc' : 'asc' })
              }
            >
              {p.order === 'asc' ? (
                <ArrowUp size={16} />
              ) : (
                <ArrowDown size={16} />
              )}
            </button>
          </div>
        </div>
        <div className="field f-size">
          <label className="field-label" htmlFor="limit">
            Page size
          </label>
          <select
            id="limit"
            className="select"
            value={p.limit}
            onChange={(e) => p.onChange({ limit: e.target.value })}
          >
            {PAGE_SIZES.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </div>
        <div className="field f-paging">
          <label className="field-label" htmlFor="paging">
            Paging
          </label>
          <select
            id="paging"
            className="select"
            value={p.paging}
            onChange={(e) =>
              p.onChange({
                paging: e.target.value === 'offset' ? 'offset' : undefined,
              })
            }
          >
            <option value="cursor">Cursor</option>
            <option value="offset">Offset</option>
          </select>
        </div>
        <div className="f-actions">
          {active && (
            <button type="button" className="btn btn-ghost" onClick={p.onReset}>
              <RotateCcw size={14} aria-hidden="true" />
              Reset
            </button>
          )}
        </div>
      </div>
      {active && (
        <div className="active-filters">
          <span className="chip-label">Active filters</span>
          {chips.map((c) => (
            <span key={c.key} className="filter-chip">
              {c.label}
              <button
                type="button"
                aria-label={`Remove filter ${c.label}`}
                onClick={() => p.onChange(c.clear)}
              >
                <X size={12} aria-hidden="true" />
              </button>
            </span>
          ))}
        </div>
      )}
    </section>
  )
}
