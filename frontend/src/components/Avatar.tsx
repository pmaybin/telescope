import type { CSSProperties } from 'react'
import { hashString } from '../format'

/** Initials avatar with a colour derived from the name (no network images). */
export function Avatar({ name, small }: { name: string; small?: boolean }) {
  const hue = hashString(name.toLowerCase()) % 360
  return (
    <span
      className={small ? 'avatar avatar-sm' : 'avatar'}
      aria-hidden="true"
      style={{ '--avatar-bg': `hsl(${hue} 50% 40%)` } as CSSProperties}
    >
      {name.slice(0, 2).toUpperCase()}
    </span>
  )
}
