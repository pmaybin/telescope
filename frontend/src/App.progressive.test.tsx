import { render, screen, waitFor, within } from '@testing-library/react'
import { HttpResponse, http as mswHttp } from 'msw'
import { describe, expect, it } from 'vitest'
import App from './App'
import type { ProgressivePage } from './api/progressive'
import { makePage, makeRepo } from './test/fixtures'
import { server } from './test/server'

const URL_ = 'http://telescope.test/api/orgs/:org/repos'

function provisional(
  over: {
    items?: ReturnType<typeof makeRepo>[]
    progress?: { pages_done: number; pages_total: number | null }
    reason?: string | null
    total?: number | null
  } = {},
): ProgressivePage {
  const base = makePage({ items: over.items ?? [makeRepo()] })
  return {
    ...base,
    page: {
      ...base.page,
      total: over.total === undefined ? null : over.total,
      provisional_reason: over.reason ?? null,
    },
    snapshot: {
      ...base.snapshot,
      id: null,
      fetched_at: null,
      repo_count: null,
      complete: false,
      progress: over.progress ?? { pages_done: 1, pages_total: 3 },
    },
  } as ProgressivePage
}

function serveSequence(responses: ProgressivePage[]) {
  const calls = { n: 0 }
  server.use(
    mswHttp.get(URL_, () => {
      const body = responses[Math.min(calls.n, responses.length - 1)]
      const incomplete = body.snapshot.complete === false
      calls.n++
      return HttpResponse.json(body, {
        headers: incomplete ? { 'Retry-After': '1' } : {},
      })
    }),
  )
  return calls
}

function open() {
  window.history.replaceState(null, '', '/?org=acme&paging=offset')
  render(<App />)
}

describe('progressive cold load', () => {
  it('shows banner + disabled paging, then swaps rows in place and stops polling', async () => {
    const calls = serveSequence([
      provisional({ total: 40, progress: { pages_done: 1, pages_total: 3 } }),
      makePage({
        items: [makeRepo(), makeRepo({ id: 2, name: 'second' })],
      }),
    ])
    open()

    expect(await screen.findByText('guava')).toBeInTheDocument()
    expect(
      screen.getByText('Loading all repositories… 1/3 pages'),
    ).toBeInTheDocument()
    expect(screen.getByText('~40 repositories')).toBeInTheDocument()
    expect(screen.getByText('Provisional')).toBeInTheDocument()
    const bar = screen.getByRole('progressbar', { name: 'Loading progress' })
    expect(bar).toHaveAttribute('aria-valuenow', '1')
    expect(bar).toHaveAttribute('aria-valuemax', '3')
    const next = screen.getByRole('button', { name: 'Next' })
    expect(next).toBeDisabled()
    expect(next).toHaveAttribute('title', 'Available once loading finishes')

    expect(
      await screen.findByText('second', {}, { timeout: 4000 }),
    ).toBeVisible()
    await waitFor(() =>
      expect(screen.queryByText(/Loading all repositories/)).toBeNull(),
    )
    expect(screen.getByText('guava')).toBeInTheDocument()
    expect(calls.n).toBe(2)
    await new Promise((r) => setTimeout(r, 1500))
    expect(calls.n).toBe(2)
  })

  it('renders skeleton rows, not the empty state, for empty provisional pages', async () => {
    serveSequence([
      provisional({ items: [], reason: 'preview-disabled', total: null }),
    ])
    open()
    expect(
      await screen.findByText('Loading all repositories… 1/3 pages'),
    ).toBeInTheDocument()
    expect(screen.queryByText(/No repositories/)).toBeNull()
    const table = document.querySelector('table.repo-table')
    expect(table).not.toBeNull()
    expect(
      within(table as HTMLElement).queryAllByRole('row', { hidden: true })
        .length,
    ).toBeGreaterThan(1)
    expect(document.querySelectorAll('.skel').length).toBeGreaterThan(0)
  })

  it('uses an indeterminate bar when pages_total is null', async () => {
    serveSequence([
      provisional({
        items: [],
        reason: 'preview-skipped',
        progress: { pages_done: 0, pages_total: null },
      }),
    ])
    open()
    expect(await screen.findByText('Loading repositories…')).toBeInTheDocument()
    const bar = screen.getByRole('progressbar', { name: 'Loading progress' })
    expect(bar).toHaveAttribute('data-indeterminate', 'true')
    expect(bar).not.toHaveAttribute('aria-valuenow')
    expect(screen.queryByText(/repositories$/)).toBeNull()
  })

  it('does not crash on null snapshot fields', async () => {
    serveSequence([provisional({ total: null })])
    open()
    expect(await screen.findByText('guava')).toBeInTheDocument()
    expect(
      screen.getByRole('navigation', { name: 'Pagination' }),
    ).toHaveTextContent(/^Showing 1/)
  })
})
