import type { RepoPage } from './client'

/** ADR-0012 progressive cold load; these are aliases of the generated contract types. */
export type ProgressivePage = RepoPage
export type ProvisionalReason = NonNullable<
  RepoPage['page']['provisional_reason']
>
export type Progress = NonNullable<RepoPage['snapshot']['progress']>

/** Identity, kept so call sites stay readable. */
export const asProgressive = (p: RepoPage): ProgressivePage => p

/** `complete` defaults to true when absent (older servers). */
export const isComplete = (p: ProgressivePage | null): boolean =>
  p?.snapshot.complete !== false
