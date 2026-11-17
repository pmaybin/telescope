import createClient from 'openapi-fetch'
import type { components, paths } from './schema'

export type RepoPage = components['schemas']['RepoPage']
export type Repo = components['schemas']['Repo']
export type Problem = components['schemas']['Problem']
export type RepoQuery = NonNullable<
  paths['/api/orgs/{org}/repos']['get']['parameters']['query']
>

/** Typed client for our backend only. The frontend never calls GitHub directly. */
export const api = createClient<paths>({
  baseUrl: import.meta.env.VITE_API_BASE_URL ?? '',
})
