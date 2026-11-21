import type { Middleware } from 'openapi-fetch'

/** Response of POST /api/dev/token (not in the generated schema yet). */
export type DevToken = {
  access_token: string
  token_type: 'Bearer'
  expires_in: number
}

/** Refresh this many ms before the token actually expires. */
const REFRESH_MARGIN_MS = 60_000
/** A mint that hangs (e.g. the API restarting mid-request) must not block every request. */
let mintTimeoutMs = 5_000
/** "No dev auth" is re-checked after this long, so a transient 404 (hot reload) heals. */
const NO_DEV_AUTH_TTL_MS = 30_000

type State = {
  token: string | null
  expiresAt: number
  /** Until when /api/dev/token is assumed absent (it answered 404): production, the
   * gateway injects the header. Expires so a transient 404 cannot stick. */
  noDevAuthUntil: number
  inflight: Promise<string | null> | null
}

// The token lives in module memory only; never in localStorage or cookies.
const state: State = {
  token: null,
  expiresAt: 0,
  noDevAuthUntil: 0,
  inflight: null,
}

const noDevAuth = () => Date.now() < state.noDevAuthUntil

/** Tests only: shorten the mint timeout. */
export function setMintTimeoutForTests(ms: number) {
  mintTimeoutMs = ms
}

/** Forget everything (tests). */
export function resetAuth() {
  mintTimeoutMs = 5_000
  state.token = null
  state.expiresAt = 0
  state.noDevAuthUntil = 0
  state.inflight = null
}

async function mint(baseUrl: string): Promise<string | null> {
  const res = await fetch(`${baseUrl}/api/dev/token`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: '{}',
    signal: AbortSignal.timeout(mintTimeoutMs),
  })
  if (res.status === 404) {
    state.noDevAuthUntil = Date.now() + NO_DEV_AUTH_TTL_MS
    state.token = null
    return null
  }
  if (!res.ok) {
    state.token = null
    return null
  }
  const body = (await res.json()) as DevToken
  state.token = body.access_token
  state.expiresAt = Date.now() + body.expires_in * 1000 - REFRESH_MARGIN_MS
  return state.token
}

/** Single in-flight mint shared by concurrent callers. */
function ensureMinted(baseUrl: string): Promise<string | null> {
  state.inflight ??= mint(baseUrl)
    .catch(() => null)
    .finally(() => {
      state.inflight = null
    })
  return state.inflight
}

async function currentToken(baseUrl: string): Promise<string | null> {
  if (noDevAuth()) return null
  if (state.token && Date.now() < state.expiresAt) return state.token
  return ensureMinted(baseUrl)
}

/** openapi-fetch middleware: Bearer auth, re-mint and retry once on 401. */
export function authMiddleware(baseUrl: string): Middleware {
  const pending = new Map<string, Request>()
  return {
    async onRequest({ request, id }) {
      const token = await currentToken(baseUrl)
      if (token) request.headers.set('Authorization', `Bearer ${token}`)
      pending.set(id, request.clone())
      return request
    },
    async onResponse({ response, id }) {
      const original = pending.get(id)
      pending.delete(id)
      if (response.status !== 401 || !original) return response
      // The server wants a token we don't have: re-check dev auth even if it once 404'd.
      state.noDevAuthUntil = 0
      state.token = null
      const token = await ensureMinted(baseUrl)
      if (!token) return response
      original.headers.set('Authorization', `Bearer ${token}`)
      return fetch(original)
    },
    onError({ id }) {
      pending.delete(id)
    },
  }
}
