import { useState } from 'react'
import type { FormEvent } from 'react'
import { ORG_PATTERN } from '../format'

export function OrgForm({
  org,
  onSubmit,
}: {
  org: string
  onSubmit: (org: string) => void
}) {
  const [draft, setDraft] = useState(org)
  const [error, setError] = useState<string | null>(null)

  // Follow external changes (back/forward) using the render-time derived-state pattern.
  const [seenOrg, setSeenOrg] = useState(org)
  if (seenOrg !== org) {
    setSeenOrg(org)
    setDraft(org)
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
    <form onSubmit={submit} className="org-form">
      <label htmlFor="org">Organisation</label>{' '}
      <input
        id="org"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        placeholder="e.g. google"
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? 'org-error' : undefined}
      />{' '}
      <button type="submit">Load</button>
      {error && (
        <p id="org-error" role="alert" className="error">
          {error}
        </p>
      )}
    </form>
  )
}
