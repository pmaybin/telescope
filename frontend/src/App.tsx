import { Info, SearchX, TriangleAlert } from 'lucide-react'
import { useMemo } from 'react'
import type { RepoQuery } from './api/client'
import { AppShell } from './components/AppShell'
import { FilterBar } from './components/FilterBar'
import { OrgHeader } from './components/OrgHeader'
import { LoadingBanner } from './components/LoadingBanner'
import { Pagination } from './components/Pagination'
import { ProblemView } from './components/ProblemView'
import { RepoTable, SkeletonTable } from './components/RepoTable'
import { StartState } from './components/StartState'
import { StateView } from './components/StateView'
import { isComplete } from './api/progressive'
import { absoluteTime, ORG_PATTERN, PAGE_SIZES } from './format'
import { useRepos } from './useRepos'
import { useUrlState } from './useUrlState'

const oneOf = <T extends string>(
  v: string | null,
  allowed: readonly T[],
): T | undefined => allowed.find((a) => a === v)

const FILTER_KEYS = ['language', 'min_stars', 'archived', 'type']

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

  // Ignore data that belongs to a previously viewed organisation.
  const shown =
    data && org && data.org.toLowerCase() === org.toLowerCase() ? data : null

  const languages = useMemo(
    () =>
      [
        ...new Set(
          (shown?.items ?? [])
            .map((r) => r.language)
            .filter((l): l is string => !!l),
        ),
      ].sort(),
    [shown],
  )

  const clearFilters = () =>
    update(Object.fromEntries(FILTER_KEYS.map((k) => [k, undefined])))
  const loadOrg = (o: string) => update({ org: o })
  const restart = () => update({ cursor: undefined, offset: undefined })

  const effectiveOrder = order ?? (sort === 'name' ? 'asc' : 'desc')
  const onSort = (col: 'name' | 'stars' | 'updated') => {
    const same = col === sort || (col === 'updated' && sort === 'pushed')
    if (same) update({ order: effectiveOrder === 'asc' ? 'desc' : 'asc' })
    else update({ sort: col, order: undefined })
  }

  const filtersActive =
    !!language ||
    minStars !== undefined ||
    archived !== undefined ||
    type !== 'all'
  const showFilters = !(problem && problem.status === 404)
  const firstLoad = loading && !shown && !problem

  let content: React.ReactNode = null
  if (problem) {
    content = (
      <ProblemView
        problem={problem}
        retryAfterHeader={retryAfterHeader}
        onRetry={retry}
        onRestart={restart}
        onPickOrg={loadOrg}
      />
    )
  } else if (firstLoad) {
    content = (
      <>
        <div className="loading-hint" role="status">
          <span className="spinner" aria-hidden="true" />
          Fetching all repositories from GitHub. Large orgs can take a few
          seconds.
        </div>
        <SkeletonTable
          rows={Math.min(limit, 10)}
          sort={sort}
          order={effectiveOrder}
        />
        <div className="pagination" aria-hidden="true">
          <span className="skel" style={{ width: 120 }} />
        </div>
      </>
    )
  } else if (shown) {
    const complete = isComplete(shown)
    const empty = shown.items.length === 0 && complete
    const skeleton = shown.items.length === 0 && !complete
    content = (
      <>
        <LoadingBanner data={shown} />
        {shown.snapshot.stale && (
          <p role="status" className="alert-inline" data-tone="warning">
            <TriangleAlert size={14} aria-hidden="true" />
            <span>
              Showing cached data
              {shown.snapshot.fetched_at &&
                ` from ${absoluteTime(shown.snapshot.fetched_at)}`}
              ; GitHub is currently unavailable.
            </span>
          </p>
        )}
        {shown.snapshot.cursor_from_older_snapshot && (
          <p role="status" className="alert-inline" data-tone="info">
            <Info size={14} aria-hidden="true" />
            <span>Data refreshed while paging; order may have shifted.</span>
          </p>
        )}
        {skeleton ? (
          <SkeletonTable
            rows={Math.min(limit, 10)}
            sort={sort}
            order={effectiveOrder}
          />
        ) : empty ? (
          <StateView
            role="status"
            icon={SearchX}
            title={
              filtersActive
                ? 'No repositories match these filters'
                : 'No repositories to show'
            }
            actions={
              filtersActive ? (
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={clearFilters}
                >
                  Clear filters
                </button>
              ) : undefined
            }
          >
            <p>
              {filtersActive
                ? 'Try a different language, lower the minimum stars or remove a filter.'
                : 'There is nothing on this page.'}
            </p>
          </StateView>
        ) : (
          <RepoTable
            items={shown.items}
            sort={sort}
            order={effectiveOrder}
            dimmed={loading}
            onSort={onSort}
          />
        )}
        {!(empty && shown.page.total === 0) && (
          <Pagination
            data={shown}
            paging={paging}
            offset={offset}
            limit={limit}
            onChange={update}
          />
        )}
      </>
    )
  }

  return (
    <AppShell
      org={rawOrg}
      rateLimit={data?.rate_limit ?? null}
      onSubmit={loadOrg}
    >
      {!rawOrg && <StartState onPick={loadOrg} />}

      {rawOrg && !org && (
        <section className="card">
          <StateView
            role="alert"
            icon={TriangleAlert}
            tone="danger"
            title="Not a valid organisation"
          >
            <p>“{rawOrg}” is not a valid GitHub organisation login.</p>
          </StateView>
        </section>
      )}

      {org && (
        <>
          {showFilters && <OrgHeader org={org} data={shown} />}
          {showFilters && (
            <FilterBar
              language={language}
              minStars={minStarsRaw}
              archived={archived ?? ''}
              type={type}
              sort={sort}
              order={effectiveOrder}
              limit={String(limit)}
              paging={paging}
              languages={languages}
              onChange={update}
              onReset={clearFilters}
            />
          )}
          <section className="card results" aria-label="Repositories">
            {loading && shown && !problem && (
              <div
                className="progress"
                role="progressbar"
                aria-label="Refreshing"
              />
            )}
            {content}
          </section>
        </>
      )}
    </AppShell>
  )
}

export default App
