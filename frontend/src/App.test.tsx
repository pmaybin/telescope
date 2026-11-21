import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import App from './App'
import { http, makePage, makeRepo, PROBLEM_HEADERS } from './test/fixtures'
import { server } from './test/server'

/** Registers a handler that records every request's query string. */
function serve(respond: (q: URLSearchParams) => ReturnType<typeof makePage>) {
  const seen: URLSearchParams[] = []
  server.use(
    http.get('/api/orgs/{org}/repos', ({ request, response }) => {
      const q = new URL(request.url).searchParams
      seen.push(q)
      return response(200).json(respond(q))
    }),
  )
  return seen
}

function open(search: string) {
  window.history.replaceState(null, '', `/${search}`)
  render(<App />)
}

describe('App', () => {
  it('prompts for an org initially and does not fetch', () => {
    open('')
    expect(screen.getByRole('status')).toHaveTextContent(
      /enter a github organisation/i,
    )
  })

  it('validates the org login client-side', async () => {
    open('')
    await userEvent.type(screen.getByLabelText('Organisation'), '-bad-')
    await userEvent.click(screen.getByRole('button', { name: 'Explore' }))
    expect(screen.getByRole('alert')).toHaveTextContent(
      /valid GitHub organisation/i,
    )
    expect(window.location.search).toBe('')
  })

  it('loads on submit, renders rows and sends parsed query params', async () => {
    const seen = serve(() =>
      makePage({
        items: [
          makeRepo({ id: 1, name: 'guava', stars: 12345, archived: true }),
          makeRepo({ id: 2, name: 'forked', fork: true }),
        ],
      }),
    )
    open('')
    await userEvent.type(screen.getByLabelText('Organisation'), 'acme')
    await userEvent.click(screen.getByRole('button', { name: 'Explore' }))

    const link = await screen.findByRole('link', { name: 'guava' })
    expect(link).toHaveAttribute('href', 'https://github.com/acme/guava')
    expect(link).toHaveAttribute('target', '_blank')
    expect(screen.getAllByText('12.3k')).toHaveLength(2)
    expect(screen.getAllByTitle('12,345 stars')).toHaveLength(2)
    expect(screen.getByText('archived')).toBeInTheDocument()
    expect(screen.getByText('fork')).toBeInTheDocument()
    expect(window.location.search).toBe('?org=acme')
    expect(seen).toHaveLength(1)
    expect(seen[0]?.get('sort')).toBe('stars')
    expect(seen[0]?.get('limit')).toBe('30')
    expect(
      screen.getByLabelText(/rate limit: 31 of 60 remaining \(anonymous\)/i),
    ).toBeInTheDocument()
  })

  it('renders placeholders for null description and language', async () => {
    serve(() =>
      makePage({ items: [makeRepo({ description: null, language: null })] }),
    )
    open('?org=acme')
    expect(await screen.findByText('No description')).toBeInTheDocument()
    expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(1)
  })

  it('shows the empty state with a working clear-filters button', async () => {
    const seen = serve((q) =>
      q.get('min_stars')
        ? makePage({ items: [] })
        : makePage({ items: [makeRepo()] }),
    )
    open('?org=acme&min_stars=99999')
    expect(
      await screen.findByText(/no repositories match these filters/i),
    ).toBeInTheDocument()
    await userEvent.click(
      screen.getByRole('button', { name: /clear filters/i }),
    )
    expect(
      await screen.findByRole('link', { name: 'guava' }),
    ).toBeInTheDocument()
    expect(window.location.search).toBe('?org=acme')
    expect(seen.at(-1)?.has('min_stars')).toBe(false)
  })

  it('shows organisation not found on 404', async () => {
    server.use(
      http.get('/api/orgs/{org}/repos', ({ response }) =>
        response(404).json(
          {
            type: 'https://telescope.local/problems/org-not-found',
            title: 'Not found',
            status: 404,
          },
          { headers: PROBLEM_HEADERS },
        ),
      ),
    )
    open('?org=nope')
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Organisation not found',
    )
  })

  it('explains rate limiting with reset info', async () => {
    server.use(
      http.get('/api/orgs/{org}/repos', ({ response }) =>
        response(503).json(
          {
            type: 'https://telescope.local/problems/upstream-rate-limited',
            title: 'Rate limited',
            status: 503,
            retry_after: 120,
          },
          { headers: PROBLEM_HEADERS },
        ),
      ),
    )
    open('?org=acme')
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(/rate limit/i)
    expect(alert).toHaveTextContent(/resets in about 120 seconds/i)
    expect(alert).toHaveTextContent(/token/i)
  })

  it('offers restart on invalid cursor', async () => {
    const seen: (string | null)[] = []
    server.use(
      http.get('/api/orgs/{org}/repos', ({ request, response }) => {
        const cursor = new URL(request.url).searchParams.get('cursor')
        seen.push(cursor)
        if (cursor)
          return response(400).json(
            {
              type: 'https://telescope.local/problems/invalid-cursor',
              title: 'Bad',
              status: 400,
            },
            { headers: PROBLEM_HEADERS },
          )
        return response(200).json(makePage())
      }),
    )
    open('?org=acme&cursor=junk')
    await userEvent.click(
      await screen.findByRole('button', { name: /back to first page/i }),
    )
    expect(
      await screen.findByRole('link', { name: 'guava' }),
    ).toBeInTheDocument()
    expect(window.location.search).toBe('?org=acme')
    expect(seen).toEqual(['junk', null])
  })

  it('shows the stale banner', async () => {
    serve(() =>
      makePage({
        snapshot: {
          id: 's',
          fetched_at: '2026-11-17T10:00:00Z',
          repo_count: 1,
          stale: true,
          complete: true,
          cursor_from_older_snapshot: false,
        },
      }),
    )
    open('?org=acme')
    expect(
      await screen.findByText(/showing cached data from/i),
    ).toHaveTextContent(/github is currently unavailable/i)
  })

  it('Next sends the cursor and updates the URL', async () => {
    const seen = serve((q) =>
      q.get('cursor')
        ? makePage({ items: [makeRepo({ id: 2, name: 'second' })] })
        : makePage({
            page: {
              limit: 30,
              total: 2,
              has_next: true,
              has_prev: false,
              next_cursor: 'CUR1',
              prev_cursor: null,
            },
          }),
    )
    open('?org=acme')
    await screen.findByRole('link', { name: 'guava' })
    expect(screen.getByRole('button', { name: 'Prev' })).toBeDisabled()
    await userEvent.click(screen.getByRole('button', { name: 'Next' }))
    expect(
      await screen.findByRole('link', { name: 'second' }),
    ).toBeInTheDocument()
    expect(seen.at(-1)?.get('cursor')).toBe('CUR1')
    expect(window.location.search).toContain('cursor=CUR1')
  })

  it('changing a filter updates the URL and drops the cursor', async () => {
    const seen = serve(() => makePage())
    open('?org=acme&cursor=CUR1')
    await screen.findByRole('link', { name: 'guava' })
    await userEvent.click(screen.getByRole('radio', { name: 'Forks' }))
    await waitFor(() => expect(seen.at(-1)?.get('type')).toBe('forks'))
    expect(seen.at(-1)?.has('cursor')).toBe(false)
    expect(window.location.search).toBe('?org=acme&type=forks')
  })

  it('back button restores the previous state', async () => {
    const seen = serve(() => makePage())
    open('?org=acme')
    await screen.findByRole('link', { name: 'guava' })
    await userEvent.selectOptions(screen.getByLabelText('Sort'), 'name')
    await waitFor(() => expect(seen.at(-1)?.get('sort')).toBe('name'))
    window.history.back()
    await waitFor(() => expect(seen.at(-1)?.get('sort')).toBe('stars'))
    expect(screen.getByLabelText('Sort')).toHaveValue('stars')
  })

  it('offset mode sends offset, shows Page X of Y and updates the URL', async () => {
    const seen = serve((q) =>
      makePage({
        page: {
          limit: 10,
          total: 25,
          has_next: true,
          has_prev: Number(q.get('offset') ?? 0) > 0,
          next_cursor: null,
          prev_cursor: null,
          offset: Number(q.get('offset') ?? 0),
        },
      }),
    )
    open('?org=acme&paging=offset&limit=10')
    await screen.findByRole('link', { name: 'guava' })
    expect(seen.at(-1)?.get('offset')).toBe('0')
    expect(seen.at(-1)?.has('cursor')).toBe(false)
    expect(screen.getByText(/page 1 of 3/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Prev' })).toBeDisabled()

    await userEvent.click(screen.getByRole('button', { name: 'Next' }))
    await waitFor(() => expect(seen.at(-1)?.get('offset')).toBe('10'))
    expect(window.location.search).toContain('offset=10')
    expect(await screen.findByText(/page 2 of 3/i)).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Last' }))
    await waitFor(() => expect(seen.at(-1)?.get('offset')).toBe('20'))
    expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled()
  })

  it('switching paging mode or filters resets offset', async () => {
    const seen = serve(() => makePage())
    open('?org=acme&paging=offset&offset=20&limit=10')
    await screen.findByRole('link', { name: 'guava' })
    expect(seen.at(-1)?.get('offset')).toBe('20')
    await userEvent.click(screen.getByRole('radio', { name: 'Forks' }))
    await waitFor(() => expect(seen.at(-1)?.get('type')).toBe('forks'))
    expect(seen.at(-1)?.get('offset')).toBe('0')
    expect(window.location.search).not.toContain('offset=')
    await userEvent.selectOptions(screen.getByLabelText('Paging'), 'cursor')
    await waitFor(() => expect(seen.at(-1)?.has('offset')).toBe(false))
    expect(window.location.search).not.toContain('paging=')
  })

  it('clicking a column header sorts by it and a second click flips the order', async () => {
    const seen = serve(() => makePage())
    open('?org=acme')
    await screen.findByRole('link', { name: 'guava' })
    await userEvent.click(screen.getByRole('button', { name: 'Name' }))
    await waitFor(() => expect(seen.at(-1)?.get('sort')).toBe('name'))
    expect(window.location.search).toBe('?org=acme&sort=name')
    expect(screen.getByLabelText('Sort')).toHaveValue('name')
    await userEvent.click(screen.getByRole('button', { name: 'Name' }))
    await waitFor(() => expect(seen.at(-1)?.get('order')).toBe('desc'))
    expect(window.location.search).toContain('order=desc')
  })

  it('the order toggle flips the order', async () => {
    const seen = serve(() => makePage())
    open('?org=acme')
    await screen.findByRole('link', { name: 'guava' })
    await userEvent.click(
      screen.getByRole('button', { name: /^order: descending/i }),
    )
    await waitFor(() => expect(seen.at(-1)?.get('order')).toBe('asc'))
    expect(window.location.search).toBe('?org=acme&order=asc')
    await userEvent.click(
      screen.getByRole('button', { name: /^order: ascending/i }),
    )
    await waitFor(() => expect(seen.at(-1)?.get('order')).toBe('desc'))
  })

  it('example org chips load an organisation', async () => {
    const seen = serve(() => makePage({ org: 'google' }))
    open('')
    await userEvent.click(screen.getByRole('button', { name: 'google' }))
    expect(
      await screen.findByRole('link', { name: 'guava' }),
    ).toBeInTheDocument()
    expect(window.location.search).toBe('?org=google')
    expect(seen).toHaveLength(1)
  })

  it('filter chips are removable and Reset clears all filters', async () => {
    serve(() => makePage())
    open('?org=acme&language=Go&type=forks')
    await screen.findByRole('link', { name: 'guava' })
    await userEvent.click(
      screen.getByRole('button', { name: /remove filter language: go/i }),
    )
    expect(window.location.search).toBe('?org=acme&type=forks')
    await userEvent.click(screen.getByRole('button', { name: 'Reset' }))
    expect(window.location.search).toBe('?org=acme')
  })

  it('theme toggle flips data-theme and persists the choice', async () => {
    localStorage.removeItem('telescope-theme')
    document.documentElement.removeAttribute('data-theme')
    open('')
    await userEvent.click(
      screen.getByRole('button', { name: 'Switch to dark theme' }),
    )
    expect(document.documentElement).toHaveAttribute('data-theme', 'dark')
    expect(localStorage.getItem('telescope-theme')).toBe('dark')
    await userEvent.click(
      screen.getByRole('button', { name: 'Switch to light theme' }),
    )
    expect(document.documentElement).toHaveAttribute('data-theme', 'light')
    expect(localStorage.getItem('telescope-theme')).toBe('light')
    localStorage.removeItem('telescope-theme')
    document.documentElement.removeAttribute('data-theme')
  })
})

describe('auth and quota problems', () => {
  const problem = (slug: string, status: 401 | 403 | 429, extra = {}) =>
    server.use(
      http.get('/api/orgs/{org}/repos', ({ response }) =>
        response(status).json(
          {
            type: `https://telescope.local/problems/${slug}`,
            title: slug,
            status,
            ...extra,
          },
          { headers: PROBLEM_HEADERS },
        ),
      ),
    )

  it('shows a countdown for client-rate-limited and auto-retries', async () => {
    let calls = 0
    server.use(
      http.get('/api/orgs/{org}/repos', ({ response }) => {
        calls++
        if (calls > 1)
          return response(200).json(makePage({ items: [makeRepo()] }))
        return response(429).json(
          {
            type: 'https://telescope.local/problems/client-rate-limited',
            title: 'Too many requests',
            status: 429,
            retry_after: 1,
          },
          { headers: PROBLEM_HEADERS },
        )
      }),
    )
    open('?org=acme')
    expect(
      await screen.findByText(/slow down — try again in 1s/i),
    ).toBeInTheDocument()
    expect(
      await screen.findByText('guava', {}, { timeout: 4000 }),
    ).toBeInTheDocument()
    expect(calls).toBe(2)
  })

  it('explains an exhausted upstream budget', async () => {
    problem('upstream-budget-exceeded', 429, { retry_after: 120 })
    open('?org=acme')
    expect(
      await screen.findByText(/cached orgs still work/i),
    ).toHaveTextContent(/retry in 2 min/i)
  })

  it('explains an org that is not allowlisted', async () => {
    problem('org-not-allowed', 403)
    open('?org=acme')
    expect(
      await screen.findByText(/isn't on the allowlist/i),
    ).toBeInTheDocument()
  })

  it('shows not signed in on 401', async () => {
    problem('unauthorized', 401)
    open('?org=acme')
    expect(await screen.findByText('Not signed in')).toBeInTheDocument()
  })
})
