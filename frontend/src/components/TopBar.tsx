import { Search } from 'lucide-react'
import { useState } from 'react'
import type { FormEvent } from 'react'
import type { RepoPage } from '../api/client'
import { ORG_PATTERN } from '../format'
import { RateLimitPill } from './RateLimitPill'
import { ThemeToggle } from './ThemeToggle'

type Props = {
  org: string
  rateLimit: RepoPage['rate_limit'] | null
  onSubmit: (org: string) => void
}

export function TopBar({ org, rateLimit, onSubmit }: Props) {
  const [draft, setDraft] = useState(org)
  const [error, setError] = useState<string | null>(null)

  // Follow external changes (back/forward) using the render-time derived-state pattern.
  const [seenOrg, setSeenOrg] = useState(org)
  if (seenOrg !== org) {
    setSeenOrg(org)
    setDraft(org)
    setError(null)
  }

  const submit = (e: FormEvent) => {
    e.preventDefault()
    const value = draft.trim()
    if (!ORG_PATTERN.test(value)) {
      setError(
        'Enter a valid GitHub organisation login (letters, digits and hyphens, max 39).',
      )
      return
    }
    setError(null)
    onSubmit(value)
  }

  return (
    <header className="topbar">
      <div className="topbar-inner">
        <div className="topbar-left">
          <a className="brand" href="/" aria-label="Telescope home">
            <img src="/favicon.svg" alt="" />
            Telescope
          </a>
          {/* Navigation links ("Explore" | "Architecture") go here. */}
        </div>
        <form onSubmit={submit} className="org-form" role="search">
          <label htmlFor="org" className="sr-only">
            Organisation
          </label>
          <div className="input-group">
            <Search size={16} aria-hidden="true" />
            <span className="input-prefix" aria-hidden="true">
              github.com/
            </span>
            <input
              id="org"
              className="input"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="organisation"
              autoComplete="off"
              spellCheck={false}
              aria-invalid={error ? true : undefined}
              aria-describedby={error ? 'org-error' : undefined}
            />
          </div>
          <button type="submit" className="btn btn-primary">
            Explore
          </button>
          {error && (
            <p id="org-error" role="alert" className="org-error">
              {error}
            </p>
          )}
        </form>
        <div className="topbar-right">
          <RateLimitPill info={rateLimit} />
          <ThemeToggle />
        </div>
      </div>
    </header>
  )
}
