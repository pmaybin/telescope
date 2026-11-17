import { lazy, Suspense } from 'react'
import App from './App'
import { usePathname } from './router'

// The design page (content, diagrams UI) is only fetched when visited.
const ArchitecturePage = lazy(() =>
  import('./architecture/ArchitecturePage').then((m) => ({
    default: m.ArchitecturePage,
  })),
)

/** Chooses the page for the current pathname. */
export function Root() {
  const path = usePathname()
  return path.replace(/\/+$/, '') === '/architecture' ? (
    <Suspense fallback={null}>
      <ArchitecturePage />
    </Suspense>
  ) : (
    <App />
  )
}
