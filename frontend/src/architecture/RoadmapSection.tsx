import { CircleDashed, Lightbulb } from 'lucide-react'
import type { RoadmapArea } from './content'

export function RoadmapSection({ roadmap }: { roadmap: RoadmapArea[] }) {
  return (
    <section
      id="roadmap"
      className="arch-section"
      aria-labelledby="roadmap-title"
    >
      <h2 id="roadmap-title">Production roadmap</h2>
      <p className="arch-lede">
        What exists today in each area, and what would change to run this in
        production.
      </p>
      <div className="roadmap-grid">
        {roadmap.map((r) => (
          <article key={r.area} className="card road">
            <h3>{r.area}</h3>
            <div className="road-now">
              <span className="road-label">Now</span>
              <p>{r.now}</p>
            </div>
            <div>
              <span className="road-label">Next</span>
              <ul className="road-next">
                {r.next.map((n) => (
                  <li key={n}>
                    <CircleDashed size={15} aria-hidden="true" />
                    <span>{n}</span>
                  </li>
                ))}
              </ul>
            </div>
            <p className="road-why">
              <Lightbulb size={14} aria-hidden="true" />
              <span>{r.why}</span>
            </p>
          </article>
        ))}
      </div>
    </section>
  )
}
