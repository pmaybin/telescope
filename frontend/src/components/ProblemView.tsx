import {
  CloudOff,
  Gauge,
  Link2Off,
  RotateCcw,
  SearchX,
  TriangleAlert,
} from 'lucide-react'
import type { Problem } from '../api/client'
import { absoluteTime } from '../format'
import { OrgChips } from './OrgChips'
import { StateView } from './StateView'

type Props = {
  problem: Problem
  retryAfterHeader: number | null
  onRetry: () => void
  onRestart: () => void
  onPickOrg: (org: string) => void
}

function resetInfo(seconds: number | null): string {
  if (seconds === null)
    return 'GitHub did not say when the limit resets; try again in a few minutes.'
  const at = new Date(Date.now() + seconds * 1000).toISOString()
  return `The limit resets in about ${seconds} second${seconds === 1 ? '' : 's'} (at ${absoluteTime(at)}).`
}

const RetryButton = ({ onRetry }: { onRetry: () => void }) => (
  <button type="button" className="btn btn-primary" onClick={onRetry}>
    <RotateCcw size={14} aria-hidden="true" />
    Retry
  </button>
)

export function ProblemView({
  problem,
  retryAfterHeader,
  onRetry,
  onRestart,
  onPickOrg,
}: Props) {
  const slug = problem.type.split('/').pop() ?? ''

  if (problem.status === 404) {
    return (
      <StateView
        role="alert"
        icon={SearchX}
        title="Organisation not found"
        actions={<OrgChips onPick={onPickOrg} />}
      >
        <p>Check the spelling and try again, or start from one of these.</p>
      </StateView>
    )
  }
  if (problem.status === 400 && slug === 'invalid-cursor') {
    return (
      <StateView
        role="alert"
        icon={Link2Off}
        tone="warning"
        title="This page link is no longer valid"
        actions={
          <button type="button" className="btn btn-primary" onClick={onRestart}>
            Back to first page
          </button>
        }
      >
        <p>
          It was issued for different filters or sorting. Start again from the
          first page.
        </p>
      </StateView>
    )
  }
  if (slug === 'upstream-rate-limited') {
    const seconds = problem.retry_after ?? retryAfterHeader
    return (
      <StateView
        role="alert"
        icon={Gauge}
        tone="warning"
        title="GitHub rate limit reached"
        actions={<RetryButton onRetry={onRetry} />}
      >
        <p>
          Unauthenticated requests are limited to 60 per hour, and loading an
          organisation uses several. {resetInfo(seconds)}
        </p>
        <p>
          Configure a GitHub token on the server to raise the limit to 5,000 per
          hour.
        </p>
      </StateView>
    )
  }
  if (problem.status >= 500 || problem.status === 0) {
    const timeout = problem.status === 504
    return (
      <StateView
        role="alert"
        icon={CloudOff}
        tone="danger"
        title={
          timeout ? 'GitHub took too long to respond' : 'Service unavailable'
        }
        actions={<RetryButton onRetry={onRetry} />}
      >
        <p>
          {timeout
            ? 'GitHub took too long to respond (timeout).'
            : 'GitHub or the server is unavailable right now.'}
        </p>
      </StateView>
    )
  }
  return (
    <StateView
      role="alert"
      icon={TriangleAlert}
      tone="danger"
      title={problem.title}
    >
      {problem.detail && <p>{problem.detail}</p>}
    </StateView>
  )
}
