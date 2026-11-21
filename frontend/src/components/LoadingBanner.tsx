import { useEffect, useState } from 'react'
import type { ProgressivePage } from '../api/progressive'
import { isComplete } from '../api/progressive'
import { formatNumber } from '../format'

const FADE_MS = 300

/**
 * Slim banner shown while the backend is still walking all pages (ADR-0012).
 * Stays mounted briefly after completion so it can fade out.
 */
export function LoadingBanner({ data }: { data: ProgressivePage | null }) {
  const loading = !!data && !isComplete(data)
  const [last, setLast] = useState<ProgressivePage | null>(null)
  const [mounted, setMounted] = useState(loading)

  // Derive state during render (no effect) while a load is in progress.
  if (loading && last !== data) setLast(data)
  if (loading && !mounted) setMounted(true)

  useEffect(() => {
    if (loading) return
    const t = setTimeout(() => setMounted(false), FADE_MS)
    return () => clearTimeout(t)
  }, [loading])

  const shown = loading ? data : last
  if (!mounted || !shown) return null

  const progress = shown.snapshot.progress ?? null
  const done = progress?.pages_done ?? 0
  const total = progress?.pages_total ?? null
  const repos = shown.page.total
  const provisional = shown.items.length > 0
  const label =
    total === null
      ? 'Loading repositories…'
      : `Loading all repositories… ${formatNumber(done)}/${formatNumber(total)} pages`

  return (
    <div
      className="loading-banner"
      data-leaving={!loading}
      role="status"
      aria-live="polite"
    >
      <div className="loading-banner-row">
        <span className="spinner" aria-hidden="true" />
        <span className="loading-banner-text">{label}</span>
        {repos !== null && repos !== undefined && (
          <span className="loading-banner-meta">
            ~{formatNumber(repos)} repositories
          </span>
        )}
        {provisional && (
          <span
            className="pill"
            title="Showing a preview; the full list is still loading"
          >
            Provisional
          </span>
        )}
      </div>
      <div
        className="loading-bar"
        data-indeterminate={total === null}
        role="progressbar"
        aria-label="Loading progress"
        {...(total === null
          ? {}
          : {
              'aria-valuemin': 0,
              'aria-valuemax': total,
              'aria-valuenow': Math.min(done, total),
            })}
      >
        <span
          style={
            total === null
              ? undefined
              : { width: `${total ? Math.min(100, (done / total) * 100) : 0}%` }
          }
        />
      </div>
    </div>
  )
}
