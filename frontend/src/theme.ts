import { useCallback, useState, useSyncExternalStore } from 'react'

export type Theme = 'light' | 'dark'
export const THEME_KEY = 'telescope-theme'

function systemTheme(): Theme {
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches
    ? 'dark'
    : 'light'
}

function stored(): Theme | null {
  try {
    const v = localStorage.getItem(THEME_KEY)
    return v === 'light' || v === 'dark' ? v : null
  } catch {
    return null
  }
}

/** Applies the persisted theme (if any) to <html>. Also honours `?theme=`. */
export function initTheme(): void {
  const q = new URLSearchParams(window.location.search).get('theme')
  const t = q === 'light' || q === 'dark' ? q : stored()
  if (t) document.documentElement.setAttribute('data-theme', t)
}

/** Current theme (explicit choice, else the OS preference) and a toggle. */
export function useTheme(): { theme: Theme; toggle: () => void } {
  const [theme, setTheme] = useState<Theme>(
    () =>
      (document.documentElement.getAttribute('data-theme') as Theme | null) ??
      systemTheme(),
  )
  const toggle = useCallback(() => {
    const next: Theme = theme === 'dark' ? 'light' : 'dark'
    document.documentElement.setAttribute('data-theme', next)
    try {
      localStorage.setItem(THEME_KEY, next)
    } catch {
      /* storage unavailable: the choice just lasts for this session */
    }
    setTheme(next)
  }, [theme])
  return { theme, toggle }
}

/**
 * The theme currently applied to <html>, following `data-theme` mutations
 * (the toggle, `?theme=`) and falling back to the OS preference.
 */
export function useAppliedTheme(): Theme {
  return useSyncExternalStore(
    (cb) => {
      const obs = new MutationObserver(cb)
      obs.observe(document.documentElement, {
        attributes: true,
        attributeFilter: ['data-theme'],
      })
      return () => obs.disconnect()
    },
    () =>
      (document.documentElement.getAttribute('data-theme') as Theme | null) ??
      systemTheme(),
  )
}
