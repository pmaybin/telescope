import { http as mswHttp, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { server } from '../test/server'
import { makePage } from '../test/fixtures'
import { api } from './client'
import { setMintTimeoutForTests } from './auth'

const BASE = 'http://telescope.test'
const list = () =>
  api.GET('/api/orgs/{org}/repos', { params: { path: { org: 'acme' } } })

function devAuth(tokens: string[] = ['tok-1', 'tok-2']) {
  const log = { mints: 0, auth: [] as (string | null)[] }
  server.use(
    mswHttp.post(`${BASE}/api/dev/token`, async () => {
      const access_token = tokens[Math.min(log.mints, tokens.length - 1)]
      log.mints++
      await new Promise((r) => setTimeout(r, 10))
      return HttpResponse.json({
        access_token,
        token_type: 'Bearer',
        expires_in: 3600,
      })
    }),
  )
  return log
}

describe('auth middleware', () => {
  it('mints once and sends the token as Bearer', async () => {
    const log = devAuth()
    server.use(
      mswHttp.get(`${BASE}/api/orgs/:org/repos`, ({ request }) => {
        log.auth.push(request.headers.get('authorization'))
        return HttpResponse.json(makePage())
      }),
    )
    await list()
    await list()
    expect(log.mints).toBe(1)
    expect(log.auth).toEqual(['Bearer tok-1', 'Bearer tok-1'])
  })

  it('sends no Authorization header when dev auth is off (404)', async () => {
    let mints = 0
    const seen: (string | null)[] = []
    server.use(
      mswHttp.post(`${BASE}/api/dev/token`, () => {
        mints++
        return HttpResponse.json({}, { status: 404 })
      }),
      mswHttp.get(`${BASE}/api/orgs/:org/repos`, ({ request }) => {
        seen.push(request.headers.get('authorization'))
        return HttpResponse.json(makePage())
      }),
    )
    await list()
    await list()
    expect(seen).toEqual([null, null])
    expect(mints).toBe(1)
  })

  it('re-mints and retries once on 401', async () => {
    const log = devAuth()
    server.use(
      mswHttp.get(`${BASE}/api/orgs/:org/repos`, ({ request }) => {
        const a = request.headers.get('authorization')
        log.auth.push(a)
        return a === 'Bearer tok-2'
          ? HttpResponse.json(makePage())
          : HttpResponse.json(
              {
                type: 'https://telescope.local/problems/unauthorized',
                title: 'Unauthorized',
                status: 401,
              },
              { status: 401 },
            )
      }),
    )
    const { data } = await list()
    expect(data).toBeDefined()
    expect(log.mints).toBe(2)
    expect(log.auth).toEqual(['Bearer tok-1', 'Bearer tok-2'])
  })

  it('gives up after a single retry', async () => {
    const log = devAuth()
    server.use(
      mswHttp.get(`${BASE}/api/orgs/:org/repos`, ({ request }) => {
        log.auth.push(request.headers.get('authorization'))
        return HttpResponse.json(
          {
            type: 'https://telescope.local/problems/unauthorized',
            title: 'Unauthorized',
            status: 401,
          },
          { status: 401 },
        )
      }),
    )
    const { response } = await list()
    expect(response.status).toBe(401)
    expect(log.auth).toHaveLength(2)
  })

  it('shares one mint between concurrent requests', async () => {
    const log = devAuth()
    server.use(
      mswHttp.get(`${BASE}/api/orgs/:org/repos`, () =>
        HttpResponse.json(makePage()),
      ),
    )
    await Promise.all([list(), list(), list()])
    expect(log.mints).toBe(1)
  })

  it('a hanging mint times out instead of blocking every request', async () => {
    setMintTimeoutForTests(50)
    const seen: (string | null)[] = []
    server.use(
      mswHttp.post(`${BASE}/api/dev/token`, () => new Promise<never>(() => {})),
      mswHttp.get(`${BASE}/api/orgs/:org/repos`, ({ request }) => {
        seen.push(request.headers.get('authorization'))
        return HttpResponse.json(makePage())
      }),
    )
    const { data } = await list()
    expect(data).toBeTruthy()
    expect(seen[0]).toBeNull()
  })

  it('a transient 404 from the mint heals on the next 401', async () => {
    let mints = 0
    const seen: (string | null)[] = []
    server.use(
      mswHttp.post(`${BASE}/api/dev/token`, () => {
        mints++
        return mints === 1
          ? HttpResponse.json({}, { status: 404 }) // API mid hot-reload
          : HttpResponse.json({
              access_token: 'tok-ok',
              token_type: 'Bearer',
              expires_in: 3600,
            })
      }),
      mswHttp.get(`${BASE}/api/orgs/:org/repos`, ({ request }) => {
        const auth = request.headers.get('authorization')
        seen.push(auth)
        return auth
          ? HttpResponse.json(makePage())
          : HttpResponse.json({ status: 401 }, { status: 401 })
      }),
    )
    const { data } = await list()
    expect(data).toBeTruthy()
    expect(seen).toEqual([null, 'Bearer tok-ok'])
    expect(mints).toBe(2)
  })
})
