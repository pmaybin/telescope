import { useMemo } from 'react'
import type { RepoQuery } from './api/client'
import { Controls } from './components/Controls'
import { OrgForm } from './components/OrgForm'
import { ProblemView } from './components/ProblemView'
import { RepoTable } from './components/RepoTable'
import { absoluteTime, formatNumber, ORG_PATTERN, PAGE_SIZES } from './format'
import { useRepos } from './useRepos'
import { useUrlState } from './useUrlState'

const oneOf = <T extends string>(
  v: string | null,
  allowed: readonly T[],
): T | undefined => allowed.find((a) => a === v)

const FILTER_KEYS = [
  'language',
  'min_stars',
  'archived',
  'type',
  'sort',
  'order',
  'limit',
  'paging',
]

function App() {
  const { params, update } = useUrlState()

  const rawOrg = params.get('org') ?? ''
  const org = ORG_PATTERN.test(rawOrg) ? rawOrg : null
  const language = params.get('language') ?? ''
  const minStarsRaw = params.get('min_stars') ?? ''
  const archived = oneOf(params.get('archived'), ['true', 'false'] as const)
  const type =
    oneOf(params.get('type'), ['all', 'sources', 'forks'] as const) ?? 'all'
  const sort =
    oneOf(params.get('sort'), [
      'stars',
      'updated',
      'pushed',
      'name',
    ] as const) ?? 'stars'
  const order = oneOf(params.get('order'), ['asc', 'desc'] as const)
  const limitNum = Number(params.get('limit'))
  const limit = PAGE_SIZES.includes(limitNum) ? limitNum : 30
  const paging =
    oneOf(params.get('paging'), ['cursor', 'offset'] as const) ?? 'cursor'
  const offsetNum = Number(params.get('offset'))
  const offset =
    paging === 'offset' && Number.isInteger(offsetNum) && offsetNum > 0
      ? Math.min(offsetNum, 100_000)
      : 0
  const cursor =
    paging === 'cursor' ? params.get('cursor') || undefined : undefined

  const minStarsNum = minStarsRaw === '' ? NaN : Number(minStarsRaw)
  const minStars =
    Number.isInteger(minStarsNum) && minStarsNum >= 0 ? minStarsNum : undefined

  const query: RepoQuery = {
    language: language || undefined,
    min_stars: minStars,
    archived: archived === undefined ? undefined : archived === 'true',
    type,
    sort,
    order,
    limit,
    cursor,
    offset: paging === 'offset' ? offset : undefined,
  }

  const { data, problem, retryAfterHeader, loading, retry } = useRepos(
    org,
    query,
  )

  const languages = useMemo(
    () =>
      [
        ...new Set(
          (data?.items ?? [])
            .map((r) => r.language)
            .filter((l): l is string => !!l),
        ),
      ].sort(),
    [data],
  )

  const clearFilters = () =>
    update(Object.fromEntries(FILTER_KEYS.map((k) => [k, undefined])))

  return (
    <main>
      <h1>Telescope</h1>
      <OrgForm org={rawOrg} onSubmit={(o) => update({ org: o })} />

      {rawOrg && !org && (
        <p role="alert" className="error">
          “{rawOrg}” is not a valid GitHub organisation login.
        </p>
      )}

      {!rawOrg && (
        <p role="status" className="muted">
          Enter a GitHub organisation above to list its repositories.
        </p>
      )}

      {org && (
        <>
          <Controls
            language={language}
            minStars={minStarsRaw}
            archived={archived ?? ''}
            type={type}
            sort={sort}
            order={order ?? ''}
            limit={String(limit)}
            paging={paging}
            languages={languages}
            onChange={update}
          />

          {loading && (
            <p role="status">
              Loading… (first load of a large org can take a few seconds)
            </p>
          )}

          {problem && (
            <ProblemView
              problem={problem}
              retryAfterHeader={retryAfterHeader}
              onRetry={retry}
              onRestart={() => update({ cursor: undefined, offset: undefined })}
            />
          )}

          {data && data.snapshot.stale && (
            <p role="status" className="banner">
              Showing cached data from {absoluteTime(data.snapshot.fetched_at)};
              GitHub is currently unavailable.
            </p>
          )}
          {data && data.snapshot.cursor_from_older_snapshot && (
            <p role="status" className="banner">
              Data refreshed while paging; order may have shifted.
            </p>
          )}

          {data && data.items.length === 0 && !loading && !problem && (
            <p role="status">
              No repositories match these filters.{' '}
              <button type="button" onClick={clearFilters}>
                Clear filters
              </button>
            </p>
          )}

          {data && data.items.length > 0 && (
            <RepoTable items={data.items} sort={sort} dimmed={loading} />
          )}

          {data && paging === 'offset' && data.page.total > 0 && (
            <nav className="pager" aria-label="Pagination">
              <button
                type="button"
                disabled={offset === 0}
                onClick={() => update({ offset: undefined })}
              >
                First
              </button>{' '}
              <button
                type="button"
                disabled={offset === 0}
                onClick={() =>
                  update({ offset: String(Math.max(0, offset - limit)) })
                }
              >
                Prev
              </button>{' '}
              <button
                type="button"
                disabled={offset + limit >= data.page.total}
                onClick={() => update({ offset: String(offset + limit) })}
              >
                Next
              </button>{' '}
              <button
                type="button"
                disabled={offset + limit >= data.page.total}
                onClick={() =>
                  update({
                    offset: String(
                      (Math.ceil(data.page.total / limit) - 1) * limit,
                    ),
                  })
                }
              >
                Last
              </button>{' '}
              <span>
                Page {formatNumber(Math.floor(offset / limit) + 1)} of{' '}
                {formatNumber(Math.max(1, Math.ceil(data.page.total / limit)))}{' '}
                ({formatNumber(data.page.total)} matching in {data.org})
              </span>
            </nav>
          )}

          {data && paging === 'cursor' && data.items.length > 0 && (
            <>
              <nav className="pager" aria-label="Pagination">
                <button
                  type="button"
                  disabled={!data.page.has_prev || !data.page.prev_cursor}
                  onClick={() =>
                    update({ cursor: data.page.prev_cursor ?? undefined })
                  }
                >
                  Prev
                </button>{' '}
                <button
                  type="button"
                  disabled={!data.page.has_next || !data.page.next_cursor}
                  onClick={() =>
                    update({ cursor: data.page.next_cursor ?? undefined })
                  }
                >
                  Next
                </button>{' '}
                <span>
                  Showing {formatNumber(data.items.length)} of{' '}
                  {formatNumber(data.page.total)} matching (
                  {formatNumber(data.snapshot.repo_count)} repos in {data.org})
                </span>
              </nav>
            </>
          )}

          {data && (
            <footer className="muted">
              GitHub rate limit: {data.rate_limit.remaining ?? '?'}/
              {data.rate_limit.limit ?? '?'} remaining, authenticated:{' '}
              {data.rate_limit.authenticated ? 'yes' : 'no'}
            </footer>
          )}
        </>
      )}
    </main>
  )
}

export default App
