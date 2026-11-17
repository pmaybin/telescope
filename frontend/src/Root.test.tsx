import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { decisions, diagrams } from './architecture/content'
import { Root } from './Root'

const { renderMock, initializeMock } = vi.hoisted(() => ({
  renderMock: vi.fn(async (id: string, source: string) => ({
    svg: `<svg id="${id}" viewBox="0 0 100 50"><text>${source.split('\n')[0]}</text></svg>`,
  })),
  initializeMock: vi.fn(),
}))
vi.mock('mermaid', () => ({
  default: { initialize: initializeMock, render: renderMock },
}))

beforeEach(() => {
  renderMock.mockClear()
  initializeMock.mockClear()
  sessionStorage.clear()
  document.documentElement.removeAttribute('data-theme')
})

function open(path: string) {
  window.history.replaceState(null, '', path)
  render(<Root />)
}

/** Opens the lazily loaded architecture page and waits for it. */
async function openArchitecture() {
  open('/architecture')
  await screen.findByRole('heading', { level: 1, name: 'System design' })
}

describe('routing and navigation', () => {
  it('opens the architecture page from the nav and returns to Explore', async () => {
    open('/')
    const nav = screen.getByRole('navigation', { name: 'Primary' })
    expect(within(nav).getByRole('link', { name: 'Explore' })).toHaveAttribute(
      'aria-current',
      'page',
    )

    await userEvent.click(
      within(nav).getByRole('link', { name: 'Architecture' }),
    )
    expect(
      await screen.findByRole('heading', { level: 1, name: 'System design' }),
    ).toBeInTheDocument()
    expect(window.location.pathname).toBe('/architecture')
    expect(
      screen.getByRole('navigation', { name: 'On this page' }),
    ).toBeInTheDocument()
    // The top bar remounts with the page, so query it again.
    const nav2 = screen.getByRole('navigation', { name: 'Primary' })
    expect(
      within(nav2).getByRole('link', { name: 'Architecture' }),
    ).toHaveAttribute('aria-current', 'page')

    await userEvent.click(within(nav2).getByRole('link', { name: 'Explore' }))
    expect(window.location.pathname).toBe('/')
    expect(screen.getByRole('status')).toHaveTextContent(
      /enter a github organisation/i,
    )
  })

  it('restores the Explore query string when coming back', async () => {
    open('/?org=acme&language=Go')
    await userEvent.click(screen.getByRole('link', { name: 'Architecture' }))
    expect(window.location.search).toBe('')
    await userEvent.click(screen.getByRole('link', { name: 'Explore' }))
    expect(window.location.search).toBe('?org=acme&language=Go')
  })

  it('handles browser back from the architecture page', async () => {
    open('/')
    await userEvent.click(screen.getByRole('link', { name: 'Architecture' }))
    await screen.findByRole('heading', { name: 'System design' })
    act(() => {
      window.history.back()
    })
    await waitFor(() =>
      expect(
        screen.queryByRole('heading', { name: 'System design' }),
      ).not.toBeInTheDocument(),
    )
  })

  it('searching from the architecture page goes to Explore for that org', async () => {
    await openArchitecture()
    await userEvent.type(screen.getByLabelText('Organisation'), 'acme{Enter}')
    expect(window.location.pathname).toBe('/')
    expect(window.location.search).toBe('?org=acme')
  })
})

describe('architecture page', () => {
  it('lists every diagram in the table of contents and renders them', async () => {
    await openArchitecture()
    const toc = screen.getByRole('navigation', { name: 'On this page' })
    for (const d of diagrams) {
      expect(within(toc).getByRole('link', { name: d.title })).toHaveAttribute(
        'href',
        `#diagram-${d.id}`,
      )
    }
    await waitFor(() =>
      expect(renderMock).toHaveBeenCalledTimes(diagrams.length),
    )
    expect(await screen.findAllByRole('img')).toHaveLength(diagrams.length)
    const config = initializeMock.mock.calls[0][0]
    expect(config).toMatchObject({
      startOnLoad: false,
      securityLevel: 'strict',
      theme: 'base',
    })
  })

  it('re-renders every diagram when the theme changes', async () => {
    await openArchitecture()
    await waitFor(() =>
      expect(renderMock).toHaveBeenCalledTimes(diagrams.length),
    )
    await screen.findAllByRole('img')
    act(() => {
      document.documentElement.setAttribute('data-theme', 'dark')
    })
    await waitFor(() =>
      expect(renderMock).toHaveBeenCalledTimes(diagrams.length * 2),
    )
    expect(initializeMock.mock.calls.at(-1)?.[0].themeVariables.darkMode).toBe(
      true,
    )
  })

  it('shows the source and an error state when a render fails', async () => {
    renderMock.mockRejectedValueOnce(new Error('Parse error on line 2'))
    await openArchitecture()
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Parse error on line 2')
    expect(alert).toHaveTextContent(diagrams[0].source.split('\n')[0])
  })

  it('toggles the diagram source', async () => {
    await openArchitecture()
    const card = screen
      .getByRole('heading', { name: diagrams[0].title })
      .closest('article')!
    await userEvent.click(
      within(card).getByRole('button', { name: 'View source' }),
    )
    expect(card.querySelector('pre')).toHaveTextContent(
      diagrams[0].source.split('\n')[0],
    )
    await userEvent.click(
      within(card).getByRole('button', { name: 'Hide source' }),
    )
    expect(card.querySelector('pre')).toBeNull()
  })

  it('filters decisions by text and expands all', async () => {
    await openArchitecture()
    expect(screen.getAllByTestId('adr-card')).toHaveLength(decisions.length)

    const target = decisions[2]
    await userEvent.type(
      screen.getByLabelText('Search decisions'),
      target.title.slice(0, 12),
    )
    const cards = screen.getAllByTestId('adr-card')
    expect(cards.length).toBeLessThan(decisions.length)
    expect(within(cards[0]).getByText(`ADR-${target.adr}`)).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Expand all' }))
    expect(screen.getAllByText('Alternatives considered')).toHaveLength(
      cards.length,
    )
    await userEvent.click(screen.getByRole('button', { name: 'Collapse all' }))
    expect(screen.queryByText('Alternatives considered')).toBeNull()

    await userEvent.clear(screen.getByLabelText('Search decisions'))
    await userEvent.type(screen.getByLabelText('Search decisions'), 'zzzzqqq')
    expect(screen.queryAllByTestId('adr-card')).toHaveLength(0)
    expect(screen.getByText(/No decisions match/)).toBeInTheDocument()
  })
})
