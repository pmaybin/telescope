import { useSyncExternalStore } from 'react'

/**
 * A tiny pathname router: `/` is Explore, `/architecture` is the design page.
 * Navigation uses `history.pushState`; back/forward arrives as `popstate`.
 */
const EXPLORE_SEARCH_KEY = 'telescope-explore-search'
const listeners = new Set<() => void>()

function subscribe(cb: () => void): () => void {
  listeners.add(cb)
  window.addEventListener('popstate', cb)
  return () => {
    listeners.delete(cb)
    window.removeEventListener('popstate', cb)
  }
}

export function usePathname(): string {
  return useSyncExternalStore(subscribe, () => window.location.pathname)
}

function stashedSearch(): string {
  try {
    return sessionStorage.getItem(EXPLORE_SEARCH_KEY) ?? ''
  } catch {
    return ''
  }
}

/** The Explore URL to return to, including the last query string. */
export function exploreHref(): string {
  return `/${stashedSearch()}`
}

/** Navigates to `to` (path plus optional query) without a page load. */
export function navigate(to: string): void {
  // Remember the Explore query so switching back restores the same view.
  if (window.location.pathname === '/') {
    try {
      sessionStorage.setItem(EXPLORE_SEARCH_KEY, window.location.search)
    } catch {
      /* storage unavailable: Explore just starts clean */
    }
  }
  window.history.pushState(null, '', to)
  listeners.forEach((l) => l())
}
