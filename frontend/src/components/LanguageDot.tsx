import type { CSSProperties } from 'react'
import { languageColor } from '../format'

export function LanguageDot({ language }: { language: string }) {
  return (
    <span
      className="lang-dot"
      aria-hidden="true"
      style={{ '--dot': languageColor(language) } as CSSProperties}
    />
  )
}
