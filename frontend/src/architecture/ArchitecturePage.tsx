import { useEffect } from 'react'
import { AppShell } from '../components/AppShell'
import { navigate } from '../router'
import { decisions, diagrams, overview, roadmap } from './content'
import { DecisionsSection } from './DecisionsSection'
import { DiagramCard } from './DiagramCard'
import { OverviewSection } from './OverviewSection'
import { PromptHistorySection } from './PromptHistorySection'
import { RoadmapSection } from './RoadmapSection'
import { Toc } from './Toc'
import type { TocItem } from './Toc'

const LAST_UPDATED = '2026-11-17'

const TOC: TocItem[] = [
  { id: 'overview', label: 'Overview' },
  {
    id: 'diagrams',
    label: 'Diagrams',
    children: diagrams.map((d) => ({ id: `diagram-${d.id}`, label: d.title })),
  },
  { id: 'decisions', label: 'Decisions' },
  { id: 'prompt-history', label: 'Prompt history' },
  { id: 'roadmap', label: 'Production roadmap' },
]

export function ArchitecturePage() {
  useEffect(() => {
    const previous = document.title
    document.title = 'System design · Telescope'
    return () => {
      document.title = previous
    }
  }, [])

  // Deep links such as /architecture#decisions: scroll once the content exists.
  useEffect(() => {
    const id = window.location.hash.slice(1)
    if (id) document.getElementById(id)?.scrollIntoView()
  }, [])

  return (
    <AppShell
      org=""
      rateLimit={null}
      onSubmit={(org) => navigate(`/?org=${encodeURIComponent(org)}`)}
    >
      <header className="arch-header">
        <h1>System design</h1>
        <p className="arch-subtitle">
          How Telescope fetches, caches and serves a GitHub organisation’s
          repositories, why it is built that way, and what would change for
          production.
        </p>
        <p className="arch-meta">
          Last updated {LAST_UPDATED} · Source:{' '}
          <code>docs/architecture.md</code> in the repository
        </p>
      </header>
      <div className="arch-layout">
        <Toc items={TOC} />
        <div className="arch-content">
          <OverviewSection overview={overview} />
          <section
            id="diagrams"
            className="arch-section"
            aria-labelledby="diagrams-title"
          >
            <h2 id="diagrams-title">Diagrams</h2>
            <p className="arch-lede">
              Nine views of the system. Wide diagrams scroll sideways inside
              their card; use full screen to zoom and pan.
            </p>
            <div className="diagram-list">
              {diagrams.map((d) => (
                <DiagramCard key={d.id} diagram={d} />
              ))}
            </div>
          </section>
          <DecisionsSection decisions={decisions} />
          <PromptHistorySection />
          <RoadmapSection roadmap={roadmap} />
        </div>
      </div>
    </AppShell>
  )
}
