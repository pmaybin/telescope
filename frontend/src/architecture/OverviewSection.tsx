import {
  Activity,
  DatabaseZap,
  FileCode2,
  Gauge,
  LifeBuoy,
  ShieldCheck,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import type { Overview } from './content'

const ICONS: LucideIcon[] = [
  FileCode2,
  DatabaseZap,
  ShieldCheck,
  LifeBuoy,
  Gauge,
  Activity,
]

/** Splits "Title: body" into its parts; the title is the text before the first colon. */
function splitPrinciple(text: string): [string, string] {
  const i = text.indexOf(':')
  return i === -1 ? [text, ''] : [text.slice(0, i), text.slice(i + 1).trim()]
}

export function OverviewSection({ overview }: { overview: Overview }) {
  return (
    <section
      id="overview"
      className="arch-section"
      aria-labelledby="overview-title"
    >
      <h2 id="overview-title">Overview</h2>
      <div className="prose">
        {overview.paragraphs.map((p) => (
          <p key={p}>{p}</p>
        ))}
      </div>
      <h3 className="arch-subhead">Design principles</h3>
      <ul className="principles">
        {overview.principles.map((p, i) => {
          const Icon = ICONS[i % ICONS.length]
          const [title, body] = splitPrinciple(p)
          return (
            <li key={p} className="card principle">
              <span className="principle-icon">
                <Icon size={18} aria-hidden="true" />
              </span>
              <div>
                <h4>{title}</h4>
                {body && <p>{body}</p>}
              </div>
            </li>
          )
        })}
      </ul>
    </section>
  )
}
