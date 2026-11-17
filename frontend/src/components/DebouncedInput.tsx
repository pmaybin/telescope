import { useEffect, useRef, useState } from 'react'

type Props = {
  id: string
  value: string
  onCommit: (value: string) => void
  delayMs?: number
  type?: string
  min?: number
  list?: string
  placeholder?: string
}

/** Text input that commits on Enter/blur, or after the user pauses typing. */
export function DebouncedInput({
  value,
  onCommit,
  delayMs = 300,
  ...rest
}: Props) {
  const [draft, setDraft] = useState(value)
  const committed = useRef(value)

  // Follow external changes (back/forward, "clear filters").
  const [seenValue, setSeenValue] = useState(value)
  if (seenValue !== value) {
    setSeenValue(value)
    setDraft(value)
  }
  useEffect(() => {
    committed.current = value
  }, [value])

  const commit = (v: string) => {
    if (v === committed.current) return
    committed.current = v
    onCommit(v)
  }

  useEffect(() => {
    if (draft === committed.current) return
    const t = setTimeout(() => commit(draft), delayMs)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft, delayMs])

  return (
    <input
      {...rest}
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={() => commit(draft)}
      onKeyDown={(e) => {
        if (e.key === 'Enter') commit(draft)
      }}
    />
  )
}
