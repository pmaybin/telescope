import { ORG_EXAMPLES } from '../format'
import { Avatar } from './Avatar'

export function OrgChips({ onPick }: { onPick: (org: string) => void }) {
  return (
    <div className="org-chips">
      {ORG_EXAMPLES.map((o) => (
        <button
          key={o}
          type="button"
          className="org-chip"
          onClick={() => onPick(o)}
        >
          <Avatar name={o} small />
          {o}
        </button>
      ))}
    </div>
  )
}
