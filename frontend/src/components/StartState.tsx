import { Telescope } from 'lucide-react'
import { OrgChips } from './OrgChips'

export function StartState({ onPick }: { onPick: (org: string) => void }) {
  return (
    <section className="card hero">
      <span className="icon-circle">
        <Telescope size={26} aria-hidden="true" />
      </span>
      <h2>Explore any GitHub organisation</h2>
      <p role="status">
        Enter a GitHub organisation above to list, filter and sort its
        repositories.
      </p>
      <span className="chip-label">Try an example</span>
      <OrgChips onPick={onPick} />
    </section>
  )
}
