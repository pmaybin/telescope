import type { ReactNode } from 'react'
import type { RepoPage } from '../api/client'
import { TopBar } from './TopBar'

/** Top bar plus centred content column; reusable by other pages. */
export function AppShell({
  org,
  rateLimit,
  onSubmit,
  children,
}: {
  org: string
  rateLimit: RepoPage['rate_limit'] | null
  onSubmit: (org: string) => void
  children: ReactNode
}) {
  return (
    <>
      <TopBar org={org} rateLimit={rateLimit} onSubmit={onSubmit} />
      <main className="container">{children}</main>
    </>
  )
}
