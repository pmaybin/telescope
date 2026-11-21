import { http as mswHttp, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'

/** Default: server not in dev auth mode, so no token is minted. */
export const server = setupServer(
  mswHttp.post('http://telescope.test/api/dev/token', () =>
    HttpResponse.json({}, { status: 404 }),
  ),
)
