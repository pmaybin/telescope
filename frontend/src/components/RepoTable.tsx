import type { Repo } from '../api/client'
import { absoluteTime, formatNumber, relativeTime } from '../format'

export function RepoTable({
  items,
  sort,
  dimmed,
}: {
  items: Repo[]
  sort: string
  dimmed: boolean
}) {
  const useP = sort === 'pushed'
  const timeLabel = useP ? 'Last pushed' : 'Last updated'
  return (
    <table className={dimmed ? 'dimmed' : undefined} aria-busy={dimmed}>
      <thead>
        <tr>
          <th>Name</th>
          <th>Description</th>
          <th>Language</th>
          <th className="num">Stars</th>
          <th>{timeLabel}</th>
        </tr>
      </thead>
      <tbody>
        {items.map((r) => {
          const ts = useP ? r.pushed_at : r.updated_at
          return (
            <tr key={r.id}>
              <td>
                <a href={r.html_url} target="_blank" rel="noreferrer">
                  {r.name}
                </a>
                {r.archived && <span className="badge">archived</span>}
                {r.fork && <span className="badge">fork</span>}
              </td>
              <td>
                {r.description ?? <span className="muted">No description</span>}
              </td>
              <td>{r.language ?? '—'}</td>
              <td className="num">{formatNumber(r.stars)}</td>
              <td>
                {ts ? (
                  <time dateTime={ts} title={absoluteTime(ts)}>
                    {relativeTime(ts)}
                  </time>
                ) : (
                  '—'
                )}
              </td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}
