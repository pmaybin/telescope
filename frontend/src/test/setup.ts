import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterAll, afterEach } from 'vitest'
import { resetAuth } from '../api/auth'
import { server } from './server'

// Must be set before src/api/client.ts is imported: Node's fetch needs absolute URLs.
import.meta.env.VITE_API_BASE_URL = 'http://telescope.test'

// Listen at import time (not in beforeAll) so MSW patches fetch before the client captures it.
server.listen({ onUnhandledFrame: 'error' })
afterEach(() => {
  cleanup()
  resetAuth()
  server.resetHandlers()
  window.history.replaceState(null, '', '/')
})
afterAll(() => server.close())
