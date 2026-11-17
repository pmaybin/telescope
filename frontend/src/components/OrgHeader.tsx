import { ExternalLink } from 'lucide-react'
import type { RepoPage } from '../api/client'
import { absoluteTime, formatNumber, relativeTime } from '../format'
import { Avatar } from './Avatar'

export function OrgHeader({
  org,
  data,
}: {
  org: string
  data: RepoPage | null
}) {
  const name = data?.org ?? org
  const snap = data?.snapshot
  const status = !snap
    ? null
    : snap.stale
      ? (['Stale', 'warning'] as const)
      : snap.cursor_from_older_snapshot
        ? (['Refreshed while paging', 'info'] as const)
        : (['Fresh', 'success'] as const)
  const value = (v: string | null, small = false) =>
    v === null ? (
      <span className="stat-value">
        <span className="skel" style={{ width: 64 }} />
      </span>
    ) : (
      <span className={small ? 'stat-value small' : 'stat-value'}>{v}</span>
    )
  return (
    <section className="org-header" aria-label="Organisation overview">
      <div className="org-title">
        <Avatar name={name} />
        <div className="org-title-text">
          <h1>{name}</h1>
          <a
            className="ext-link"
            href={`https://github.com/${name}`}
            target="_blank"
            rel="noreferrer"
          >
            github.com/{name}
            <ExternalLink size={12} aria-hidden="true" />
          </a>
        </div>
      </div>
      <div className="stats">
        <div className="card stat">
          <span className="stat-label">Repositories</span>
          {data ? value(formatNumber(snap!.repo_count)) : value(null)}
        </div>
        <div className="card stat">
          <span className="stat-label">Matching</span>
          {data ? value(formatNumber(data.page.total)) : value(null)}
        </div>
        <div className="card stat">
          <span className="stat-label">Snapshot</span>
          {snap ? (
            <span
              className="stat-value small"
              title={absoluteTime(snap.fetched_at)}
            >
              {relativeTime(snap.fetched_at)}
            </span>
          ) : (
            value(null)
          )}
        </div>
        <div className="card stat">
          <span className="stat-label">Status</span>
          <span className="stat-value">
            {status ? (
              <span className="badge-status" data-tone={status[1]}>
                {status[0]}
              </span>
            ) : (
              <span className="skel" style={{ width: 64 }} />
            )}
          </span>
        </div>
      </div>
    </section>
  )
}
