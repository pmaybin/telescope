import { createOpenApiHttp } from 'openapi-msw'
import type { paths } from '../api/schema'
import type { Repo, RepoPage } from '../api/client'

export const http = createOpenApiHttp<paths>({
  baseUrl: 'http://telescope.test',
})

export const PROBLEM_HEADERS = { 'content-type': 'application/problem+json' }

export function makeRepo(over: Partial<Repo> = {}): Repo {
  return {
    id: 1,
    name: 'guava',
    full_name: 'acme/guava',
    html_url: 'https://github.com/acme/guava',
    description: 'Core libraries',
    language: 'Java',
    stars: 12345,
    forks: 10,
    open_issues: 2,
    archived: false,
    fork: false,
    license: null,
    topics: [],
    created_at: '2020-01-01T00:00:00Z',
    updated_at: '2020-02-01T00:00:00Z',
    pushed_at: '2020-03-01T00:00:00Z',
    ...over,
  }
}

export function makePage(over: Partial<RepoPage> = {}): RepoPage {
  const items = over.items ?? [makeRepo()]
  return {
    org: 'acme',
    items,
    page: {
      limit: 30,
      total: items.length,
      has_next: false,
      has_prev: false,
      next_cursor: null,
      prev_cursor: null,
    },
    snapshot: {
      id: 'snap1',
      fetched_at: '2026-11-17T10:00:00Z',
      repo_count: items.length,
      stale: false,
      cursor_from_older_snapshot: false,
    },
    rate_limit: {
      authenticated: false,
      limit: 60,
      remaining: 31,
      reset_at: null,
    },
    ...over,
  }
}
