import type { Problem } from '../api/client'
import { absoluteTime } from '../format'

type Props = {
  problem: Problem
  retryAfterHeader: number | null
  onRetry: () => void
  onRestart: () => void
}

function resetInfo(seconds: number | null): string {
  if (seconds === null)
    return 'GitHub did not say when the limit resets; try again in a few minutes.'
  const at = new Date(Date.now() + seconds * 1000).toISOString()
  return `The limit resets in about ${seconds} second${seconds === 1 ? '' : 's'} (at ${absoluteTime(at)}).`
}

export function ProblemView({
  problem,
  retryAfterHeader,
  onRetry,
  onRestart,
}: Props) {
  const slug = problem.type.split('/').pop() ?? ''

  if (problem.status === 404) {
    return (
      <div role="alert" className="error">
        <strong>Organisation not found.</strong> Check the spelling and try
        again.
      </div>
    )
  }
  if (problem.status === 400 && slug === 'invalid-cursor') {
    return (
      <div role="alert" className="error">
        <p>This page link is no longer valid for the current filters.</p>
        <button type="button" onClick={onRestart}>
          Restart from first page
        </button>
      </div>
    )
  }
  if (slug === 'upstream-rate-limited') {
    const seconds = problem.retry_after ?? retryAfterHeader
    return (
      <div role="alert" className="error">
        <p>
          <strong>GitHub rate limit reached.</strong> Unauthenticated requests
          are limited to 60 per hour, and loading an organisation uses several.{' '}
          {resetInfo(seconds)}
        </p>
        <p>
          Configure a GitHub token on the server to raise the limit to 5,000 per
          hour.
        </p>
        <button type="button" onClick={onRetry}>
          Retry
        </button>
      </div>
    )
  }
  if (problem.status >= 500 || problem.status === 0) {
    const timeout = problem.status === 504
    return (
      <div role="alert" className="error">
        <p>
          {timeout
            ? 'GitHub took too long to respond (timeout).'
            : 'GitHub or the server is unavailable right now.'}
        </p>
        <button type="button" onClick={onRetry}>
          Retry
        </button>
      </div>
    )
  }
  return (
    <div role="alert" className="error">
      <strong>{problem.title}</strong>
      {problem.detail ? `: ${problem.detail}` : null}
    </div>
  )
}
