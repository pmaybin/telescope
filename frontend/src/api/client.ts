import createClient from 'openapi-fetch'
import { authMiddleware } from './auth'
import type { components, paths } from './schema'

export type RepoPage = components['schemas']['RepoPage']
export type Repo = components['schemas']['Repo']
export type Problem = components['schemas']['Problem']
export type RepoQuery = NonNullable<
  paths['/api/orgs/{org}/repos']['get']['parameters']['query']
>

/** Typed client for our backend only. The frontend never calls GitHub directly. */
const baseUrl = import.meta.env.VITE_API_BASE_URL ?? ''
export const api = createClient<paths>({ baseUrl })
api.use(authMiddleware(baseUrl))
