import { useCallback, useEffect, useMemo, useState } from 'react'

export type UrlPatch = Record<string, string | undefined>

/**
 * The URL query string is the single source of truth for page state.
 * Updates use `history.pushState`; back/forward is handled via `popstate`.
 * Any patch that does not itself set `cursor` (or `offset`) clears it, because
 * a position is only valid for the filters/sort it was issued for.
 */
export function useUrlState(): {
  params: URLSearchParams
  update: (patch: UrlPatch) => void
} {
  const [search, setSearch] = useState(() => window.location.search)

  useEffect(() => {
    const onPop = () => setSearch(window.location.search)
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])

  const params = useMemo(() => new URLSearchParams(search), [search])

  const update = useCallback((patch: UrlPatch) => {
    const next = new URLSearchParams(window.location.search)
    for (const [key, value] of Object.entries(patch)) {
      if (value === undefined || value === '') next.delete(key)
      else next.set(key, value)
    }
    if (!('cursor' in patch)) next.delete('cursor')
    if (!('offset' in patch)) next.delete('offset')
    const qs = next.toString()
    if (qs === window.location.search.replace(/^\?/, '')) return
    window.history.pushState(null, '', qs ? `?${qs}` : window.location.pathname)
    setSearch(window.location.search)
  }, [])

  return { params, update }
}
