const numberFormat = new Intl.NumberFormat()
export const formatNumber = (n: number): string => numberFormat.format(n)

export const ORG_PATTERN = /^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$/

const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ['year', 365 * 24 * 3600],
  ['month', 30 * 24 * 3600],
  ['week', 7 * 24 * 3600],
  ['day', 24 * 3600],
  ['hour', 3600],
  ['minute', 60],
]

const rtf = new Intl.RelativeTimeFormat('en', { numeric: 'auto' })

/** "3 days ago" style text. */
export function relativeTime(iso: string, now: number = Date.now()): string {
  if (Math.abs(Date.parse(iso) - now) < 60_000) return 'just now'
  const seconds = Math.round((Date.parse(iso) - now) / 1000)
  for (const [unit, size] of UNITS) {
    if (Math.abs(seconds) >= size)
      return rtf.format(Math.round(seconds / size), unit)
  }
  return rtf.format(seconds, 'second')
}

export function absoluteTime(iso: string): string {
  return new Date(iso).toLocaleString()
}
export const PAGE_SIZES = [10, 30, 50, 100]

const compact = new Intl.NumberFormat('en', {
  notation: 'compact',
  maximumFractionDigits: 1,
})
/** 12345 -> "12.3k". */
export const formatCompact = (n: number): string =>
  n < 1000 ? String(n) : compact.format(n).replace('K', 'k')

export function hashString(s: string): number {
  let h = 0
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0
  return h
}

export const ORG_EXAMPLES = ['google', 'microsoft', 'facebook', 'vercel']

const LANGUAGE_COLORS: Record<string, string> = {
  JavaScript: '#f1e05a',
  TypeScript: '#3178c6',
  Python: '#3572a5',
  Java: '#b07219',
  Go: '#00add8',
  Rust: '#dea584',
  C: '#6e6e6e',
  'C++': '#f34b7d',
  'C#': '#178600',
  Ruby: '#701516',
  PHP: '#4f5d95',
  Swift: '#f05138',
  Kotlin: '#a97bff',
  Shell: '#89e051',
  HTML: '#e34c26',
  CSS: '#563d7c',
  Dart: '#00b4ab',
  Scala: '#c22d40',
  'Objective-C': '#438eff',
  'Jupyter Notebook': '#da5b0b',
  Starlark: '#76d275',
  Lua: '#4a4aa8',
  Vue: '#41b883',
  Haskell: '#5e5086',
  Elixir: '#6e4a7e',
}

/** GitHub's colour for common languages, else a deterministic hash colour. */
export function languageColor(name: string): string {
  return LANGUAGE_COLORS[name] ?? `hsl(${hashString(name) % 360} 55% 52%)`
}
