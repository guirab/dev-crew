import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { REPOS } from '../mocks/data'
import { MockFolders } from '../mocks/folders'

/**
 * Servidor MSW compartilhado pelos testes (listen/reset/close no setup global).
 * Os GETs de listas têm resposta padrão; `/api/commands` e `/api/task` cada teste define.
 * As pastas vêm do disco fictício do modo mock (um `MockFolders` novo por requisição).
 */
export const server = setupServer(
  http.get('*/api/repos', () => HttpResponse.json(REPOS)),
  http.get('*/api/tasks', () => HttpResponse.json([])),
  http.get('*/api/folders', ({ request }) => {
    const path = new URL(request.url).searchParams.get('path') ?? undefined
    const listing = new MockFolders().list(path)
    return listing
      ? HttpResponse.json(listing)
      : HttpResponse.json({ detail: `a pasta não existe: ${path ?? ''}` }, { status: 404 })
  }),
  http.get('*/api/folders/probe', ({ request }) => {
    const path = new URL(request.url).searchParams.get('path') ?? ''
    const probe = new MockFolders().probe(path)
    return probe
      ? HttpResponse.json(probe)
      : HttpResponse.json({ detail: `a pasta não existe: ${path}` }, { status: 404 })
  }),
)
