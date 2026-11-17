import { Lock, LockOpen } from 'lucide-react'
import type { RepoPage } from '../api/client'
import { absoluteTime, formatNumber } from '../format'

type Info = RepoPage['rate_limit']

export function RateLimitPill({ info }: { info: Info | null }) {
  if (!info) return null
  const { remaining, limit, authenticated } = info
  const ratio =
    remaining !== null && limit ? Math.min(1, remaining / limit) : null
  const level =
    ratio === null
      ? 'unknown'
      : ratio > 0.5
        ? 'ok'
        : ratio > 0.2
          ? 'warn'
          : 'low'
  const who = authenticated ? 'Authenticated' : 'Anonymous'
  const fmt = (n: number | null) => (n === null ? '?' : formatNumber(n))
  const reset = info.reset_at ? `, resets ${absoluteTime(info.reset_at)}` : ''
  const label = `GitHub rate limit: ${fmt(remaining)} of ${fmt(limit)} remaining (${who})${reset}`
  return (
    <div
      className="rate-pill"
      data-level={level}
      title={label}
      aria-label={label}
      role="img"
    >
      {authenticated ? <Lock size={14} /> : <LockOpen size={14} />}
      <span className="meter" aria-hidden="true">
        <span style={{ width: `${Math.round((ratio ?? 0) * 100)}%` }} />
      </span>
      <span>
        {fmt(remaining)}
        <span className="rate-sep">/</span>
        {fmt(limit)}
      </span>
    </div>
  )
}
