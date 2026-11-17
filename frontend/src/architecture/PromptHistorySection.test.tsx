import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'
import log from './prompt-log.json'
import { PromptHistorySection } from './PromptHistorySection'

beforeEach(() => {
  window.history.replaceState(null, '', '/architecture')
})

async function expand() {
  await userEvent.click(
    screen.getByRole('button', { name: /show prompt history/i }),
  )
  await screen.findAllByTestId('prompt-item')
}

describe('PromptHistorySection', () => {
  it('is collapsed by default with a one-line summary and no entries', () => {
    render(<PromptHistorySection />)
    const toggle = screen.getByRole('button', { name: /prompt history/i })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(toggle).toHaveTextContent(/\d+ prompts · \d+ human · \d+ architect/)
    expect(screen.queryByTestId('prompt-item')).not.toBeInTheDocument()
  })

  it('lists every entry once expanded', async () => {
    render(<PromptHistorySection />)
    await expand()
    expect(screen.getAllByTestId('prompt-item')).toHaveLength(
      log.entries.length,
    )
  })

  it('expands from the #prompt-history deep link', async () => {
    window.history.replaceState(null, '', '/architecture#prompt-history')
    render(<PromptHistorySection />)
    expect(
      (await screen.findAllByTestId('prompt-item')).length,
    ).toBeGreaterThan(0)
  })

  it('narrows by actor and by search', async () => {
    render(<PromptHistorySection />)
    await expand()
    const total = log.entries.length
    const humans = log.entries.filter((e) => e.actor === 'human').length

    await userEvent.click(screen.getByRole('radio', { name: /^Human/ }))
    expect(screen.getAllByTestId('prompt-item')).toHaveLength(humans)

    await userEvent.click(screen.getByRole('radio', { name: /^All/ }))
    expect(screen.getAllByTestId('prompt-item')).toHaveLength(total)

    await userEvent.type(
      screen.getByRole('searchbox', { name: 'Search prompts' }),
      'zzz-no-such-prompt-zzz',
    )
    expect(screen.queryByTestId('prompt-item')).not.toBeInTheDocument()
    expect(screen.getByText('No prompts match.')).toBeInTheDocument()
  })

  it('reveals the full prompt on Show prompt', async () => {
    render(<PromptHistorySection />)
    await expand()
    const item = screen.getAllByTestId('prompt-item')[0]
    expect(item.querySelector('pre')).toBeNull()
    await userEvent.click(
      within(item).getByRole('button', { name: 'Show prompt' }),
    )
    const pre = item.querySelector('pre')
    expect(pre).not.toBeNull()
    expect(pre?.textContent).toBe(log.entries[0].prompt)
  })
})
