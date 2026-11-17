import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  ExternalLink,
  Star,
} from 'lucide-react'
import type { Repo } from '../api/client'
import {
  absoluteTime,
  formatCompact,
  formatNumber,
  relativeTime,
} from '../format'
import { LanguageDot } from './LanguageDot'

type SortKey = 'name' | 'stars' | 'updated'

function ColumnGroup() {
  return (
    <colgroup>
      <col className="col-name" />
      <col />
      <col className="col-lang" />
      <col className="col-stars" />
      <col className="col-updated" />
    </colgroup>
  )
}

function SortHeader({
  col,
  label,
  active,
  order,
  onSort,
  className,
}: {
  col: SortKey
  label: string
  active: boolean
  order: 'asc' | 'desc'
  onSort: (col: SortKey) => void
  className?: string
}) {
  const Icon = !active ? ArrowUpDown : order === 'asc' ? ArrowUp : ArrowDown
  return (
    <th
      className={className}
      aria-sort={
        active ? (order === 'asc' ? 'ascending' : 'descending') : 'none'
      }
    >
      <button
        type="button"
        className="sort-btn"
        data-active={active}
        onClick={() => onSort(col)}
      >
        {label}
        <Icon size={12} aria-hidden="true" />
      </button>
    </th>
  )
}

function Head({
  sort,
  order,
  onSort,
}: {
  sort: string
  order: 'asc' | 'desc'
  onSort: (col: SortKey) => void
}) {
  return (
    <thead>
      <tr>
        <SortHeader
          col="name"
          label="Name"
          active={sort === 'name'}
          order={order}
          onSort={onSort}
        />
        <th>Description</th>
        <th>Language</th>
        <SortHeader
          col="stars"
          label="Stars"
          active={sort === 'stars'}
          order={order}
          onSort={onSort}
          className="num"
        />
        <SortHeader
          col="updated"
          label={sort === 'pushed' ? 'Pushed' : 'Updated'}
          active={sort === 'updated' || sort === 'pushed'}
          order={order}
          onSort={onSort}
          className="num updated-cell"
        />
      </tr>
    </thead>
  )
}

export function RepoTable({
  items,
  sort,
  order,
  dimmed,
  onSort,
}: {
  items: Repo[]
  sort: string
  order: 'asc' | 'desc'
  dimmed: boolean
  onSort: (col: SortKey) => void
}) {
  const usePushed = sort === 'pushed'
  return (
    <table className="repo-table" data-dimmed={dimmed} aria-busy={dimmed}>
      <ColumnGroup />
      <Head sort={sort} order={order} onSort={onSort} />
      <tbody>
        {items.map((r) => {
          const ts = usePushed ? r.pushed_at : r.updated_at
          return (
            <tr key={r.id}>
              <td className="name-td">
                <div className="name-cell">
                  <a
                    className="repo-link"
                    href={r.html_url}
                    target="_blank"
                    rel="noreferrer"
                    title={r.full_name}
                  >
                    <span>{r.name}</span>
                    <ExternalLink size={12} aria-hidden="true" />
                  </a>
                  {r.archived && <span className="pill">archived</span>}
                  {r.fork && <span className="pill">fork</span>}
                </div>
              </td>
              <td className="desc-td">
                {r.description ? (
                  <div className="desc" title={r.description}>
                    {r.description}
                  </div>
                ) : (
                  <div className="desc muted">No description</div>
                )}
                {r.topics.length > 0 && (
                  <div className="topics">
                    {r.topics.slice(0, 3).map((t) => (
                      <span key={t} className="topic" title={t}>
                        {t}
                      </span>
                    ))}
                  </div>
                )}
              </td>
              <td className="lang-td">
                {r.language ? (
                  <span className="lang" title={r.language}>
                    <LanguageDot language={r.language} />
                    <span>{r.language}</span>
                  </span>
                ) : (
                  <span className="muted">—</span>
                )}
              </td>
              <td className="num stars-td">
                <span
                  className="stars"
                  title={`${formatNumber(r.stars)} stars`}
                >
                  <Star size={13} aria-hidden="true" />
                  <span>{formatCompact(r.stars)}</span>
                </span>
              </td>
              <td className="num updated-cell updated-td updated">
                {ts ? (
                  <time dateTime={ts} title={absoluteTime(ts)}>
                    {relativeTime(ts)}
                  </time>
                ) : (
                  <span>—</span>
                )}
              </td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

/** Same columns and row height as the real table, so loading causes no shift. */
export function SkeletonTable({
  rows,
  sort,
  order,
}: {
  rows: number
  sort: string
  order: 'asc' | 'desc'
}) {
  return (
    <table className="repo-table" aria-hidden="true">
      <ColumnGroup />
      <Head sort={sort} order={order} onSort={() => undefined} />
      <tbody>
        {Array.from({ length: rows }, (_, i) => (
          <tr key={i}>
            <td className="name-td">
              <span
                className="skel"
                style={{ width: `${55 + ((i * 17) % 35)}%` }}
              />
            </td>
            <td className="desc-td">
              <span
                className="skel"
                style={{ width: `${60 + ((i * 13) % 35)}%` }}
              />
              <span
                className="skel"
                style={{ width: `${30 + ((i * 23) % 40)}%` }}
              />
            </td>
            <td className="lang-td">
              <span className="skel" style={{ width: '60%' }} />
            </td>
            <td className="num stars-td">
              <span
                className="skel"
                style={{ width: 40, marginLeft: 'auto' }}
              />
            </td>
            <td className="num updated-cell updated-td">
              <span
                className="skel"
                style={{ width: 64, marginLeft: 'auto' }}
              />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
