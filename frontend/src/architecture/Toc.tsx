import { useEffect, useMemo, useState } from 'react'

export type TocItem = { id: string; label: string; children?: TocItem[] }

function flatten(items: TocItem[]): string[] {
  return items.flatMap((i) => [i.id, ...flatten(i.children ?? [])])
}

/** Id of the last section whose top has scrolled past the sticky chrome. */
function useScrollSpy(ids: string[]): [string, (id: string) => void] {
  const [active, setActive] = useState(ids[0] ?? '')
  useEffect(() => {
    let frame = 0
    const update = () => {
      frame = 0
      const line = window.innerHeight * 0.25
      let current = ids[0] ?? ''
      for (const id of ids) {
        const el = document.getElementById(id)
        if (el && el.getBoundingClientRect().top <= line) current = id
      }
      setActive(current)
    }
    const onScroll = () => {
      if (!frame) frame = window.requestAnimationFrame(update)
    }
    window.addEventListener('scroll', onScroll, { passive: true })
    window.addEventListener('resize', onScroll)
    return () => {
      window.removeEventListener('scroll', onScroll)
      window.removeEventListener('resize', onScroll)
      if (frame) window.cancelAnimationFrame(frame)
    }
  }, [ids])
  return [active, setActive]
}

export function Toc({ items }: { items: TocItem[] }) {
  const ids = useMemo(() => flatten(items), [items])
  const [active, setActive] = useScrollSpy(ids)

  const link = (item: TocItem, nested = false) => (
    <a
      href={`#${item.id}`}
      className={nested ? 'toc-link toc-nested' : 'toc-link'}
      aria-current={active === item.id ? 'location' : undefined}
      onClick={() => setActive(item.id)}
    >
      {item.label}
    </a>
  )

  return (
    <nav className="toc" aria-label="On this page">
      <p className="toc-title">On this page</p>
      <ul>
        {items.map((item) => (
          <li key={item.id}>
            {link(item)}
            {item.children && (
              <ul className="toc-sub">
                {item.children.map((c) => (
                  <li key={c.id}>{link(c, true)}</li>
                ))}
              </ul>
            )}
          </li>
        ))}
      </ul>
    </nav>
  )
}
