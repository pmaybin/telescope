import { PAGE_SIZES } from '../format'
import { DebouncedInput } from './DebouncedInput'

type Props = {
  language: string
  minStars: string
  archived: string
  type: string
  sort: string
  order: string
  limit: string
  paging: string
  languages: string[]
  onChange: (patch: Record<string, string | undefined>) => void
}

export function Controls(p: Props) {
  return (
    <div className="controls">
      <div>
        <label htmlFor="language">Language</label>{' '}
        <DebouncedInput
          id="language"
          list="languages"
          value={p.language}
          onCommit={(v) => p.onChange({ language: v.trim() })}
          placeholder="any"
        />
        <datalist id="languages">
          {p.languages.map((l) => (
            <option key={l} value={l} />
          ))}
        </datalist>
        <small> Use “none” for repositories with no language.</small>
      </div>
      <div>
        <label htmlFor="min_stars">Min stars</label>{' '}
        <DebouncedInput
          id="min_stars"
          type="number"
          min={0}
          value={p.minStars}
          onCommit={(v) => p.onChange({ min_stars: v })}
        />
      </div>
      <div>
        <label htmlFor="archived">Archived</label>{' '}
        <select
          id="archived"
          value={p.archived}
          onChange={(e) =>
            p.onChange({ archived: e.target.value || undefined })
          }
        >
          <option value="">Any</option>
          <option value="true">Yes</option>
          <option value="false">No</option>
        </select>
      </div>
      <div>
        <label htmlFor="type">Type</label>{' '}
        <select
          id="type"
          value={p.type}
          onChange={(e) => p.onChange({ type: e.target.value })}
        >
          <option value="all">All</option>
          <option value="sources">Sources</option>
          <option value="forks">Forks</option>
        </select>
      </div>
      <div>
        <label htmlFor="sort">Sort</label>{' '}
        <select
          id="sort"
          value={p.sort}
          onChange={(e) => p.onChange({ sort: e.target.value })}
        >
          <option value="stars">Stars</option>
          <option value="updated">Updated</option>
          <option value="pushed">Pushed</option>
          <option value="name">Name</option>
        </select>
      </div>
      <div>
        <label htmlFor="order">Order</label>{' '}
        <select
          id="order"
          value={p.order}
          onChange={(e) => p.onChange({ order: e.target.value || undefined })}
        >
          <option value="">Default</option>
          <option value="asc">Ascending</option>
          <option value="desc">Descending</option>
        </select>
      </div>
      <div>
        <label htmlFor="paging">Paging</label>{' '}
        <select
          id="paging"
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
      <div>
        <label htmlFor="limit">Page size</label>{' '}
        <select
          id="limit"
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
    </div>
  )
}
