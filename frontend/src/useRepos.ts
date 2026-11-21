import { useCallback, useEffect, useState } from 'react'
import { api } from './api/client'
import type { Problem, RepoQuery } from './api/client'
import { asProgressive, isComplete } from './api/progressive'
import type { ProgressivePage } from './api/progressive'

const DEFAULT_POLL_MS = 1000
const MIN_POLL_MS = 500

export type RepoState = {
  data: ProgressivePage | null
  problem: Problem | null
  /** `Retry-After` header (seconds), used if the body lacks `retry_after`. */
  retryAfterHeader: number | null
  loading: boolean
}

type Settled = {
  /** Which request (org + query + attempt) this outcome belongs to. */
  key: string
  /** Last successful page; kept across requests so the UI can dim it while loading. */
  data: ProgressivePage | null
  problem: Problem | null
  retryAfterHeader: number | null
  /** Delay before re-polling a provisional (incomplete) response. */
  pollMs: number
}

function networkProblem(): Problem {
  return {
    type: 'about:blank#network-error',
    title: 'Network error',
    status: 0,
    detail: 'Could not reach the server.',
  }
}

/**
 * Fetch one page from our backend. Aborts the in-flight request whenever the
 * org/query changes. Keeps the previous data while loading so the UI can dim it.
 */
export function useRepos(
  org: string | null,
  query: RepoQuery,
): RepoState & { retry: () => void } {
  const [settled, setSettled] = useState<Settled>({
    key: '',
    data: null,
    problem: null,
    retryAfterHeader: null,
    pollMs: DEFAULT_POLL_MS,
  })
  const [tick, setTick] = useState(0)
  const [attempt, setAttempt] = useState(0)
  const queryKey = JSON.stringify(query)
  const key = org ? JSON.stringify([org, queryKey, attempt]) : ''

  useEffect(() => {
    if (!org) return
    const controller = new AbortController()
    const parsed = JSON.parse(queryKey) as RepoQuery
    const fail = (problem: Problem, retryAfterHeader: number | null) =>
      setSettled((s) => ({
        key,
        data: s.data,
        problem,
        retryAfterHeader,
        pollMs: s.pollMs,
      }))
    api
      .GET('/api/orgs/{org}/repos', {
        params: { path: { org }, query: parsed },
        signal: controller.signal,
      })
      .then(({ data, error, response }) => {
        if (controller.signal.aborted) return
        if (data) {
          const hint = Number(response.headers.get('Retry-After'))
          setSettled({
            key,
            data: asProgressive(data),
            problem: null,
            retryAfterHeader: null,
            pollMs:
              Number.isFinite(hint) && hint > 0
                ? Math.max(MIN_POLL_MS, hint * 1000)
                : DEFAULT_POLL_MS,
          })
        } else {
          const header = Number(response.headers.get('Retry-After'))
          fail(
            error ?? networkProblem(),
            Number.isFinite(header) && header > 0 ? header : null,
          )
        }
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return
        if (err instanceof DOMException && err.name === 'AbortError') return
        fail(networkProblem(), null)
      })
    return () => controller.abort()
  }, [org, queryKey, attempt, key, tick])

  // While the snapshot is provisional, poll again. The request key is
  // unchanged, so the previous rows stay put and swap in place on completion.
  const polling =
    settled.key === key && !settled.problem && !isComplete(settled.data)
  useEffect(() => {
    if (!polling) return
    const t = setTimeout(() => setTick((n) => n + 1), settled.pollMs)
    return () => clearTimeout(t)
  }, [polling, settled])

  const retry = useCallback(() => setAttempt((n) => n + 1), [])

  if (!org) {
    return {
      data: null,
      problem: null,
      retryAfterHeader: null,
      loading: false,
      retry,
    }
  }
  const current = settled.key === key
  return {
    data: settled.data,
    problem: current ? settled.problem : null,
    retryAfterHeader: current ? settled.retryAfterHeader : null,
    loading: !current,
    retry,
  }
}
