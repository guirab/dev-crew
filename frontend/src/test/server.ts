import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { REPOS } from '../mocks/data'

/**
 * Servidor MSW compartilhado pelos testes (listen/reset/close no setup global).
 * Os GETs de listas têm resposta padrão; `/api/commands` e `/api/task` cada teste define.
 */
export const server = setupServer(http.get('*/api/repos', () => HttpResponse.json(REPOS)))
