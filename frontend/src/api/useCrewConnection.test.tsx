import { waitFor } from '@testing-library/react'
import { http, HttpResponse, ws } from 'msw'
import { describe, expect, it } from 'vitest'
import { createRestHandlers, createWsHandler } from '../mocks/handlers'
import { ScenarioBackend } from '../mocks/scenario'
import { useCrewStore } from '../store/crew'
import { fixture } from '../test/fixtures'
import { renderWithClient } from '../test/render'
import { server } from '../test/server'
import { CrewConnection } from '../app/CrewConnection'

describe('CrewConnection (WS + REST via MSW)', () => {
  it('recebe views e progress pelo WS e hidrata via REST ao conectar', async () => {
    const backend = new ScenarioBackend({ speed: 5000 })
    const { handler } = createWsHandler(backend)
    server.use(...createRestHandlers(backend), handler)

    renderWithClient(<CrewConnection />)
    await waitFor(() => {
      expect(useCrewStore.getState().connection).toBe('open')
    })
    await waitFor(() => {
      expect(useCrewStore.getState().hydrated).toBe(true)
    })
    expect(useCrewStore.getState().view).toBeNull()

    backend.handle({
      type: 'start_task',
      repo: 'portal-vendas',
      title: 'Filtro por intervalo de datas',
    })
    await waitFor(() => {
      expect(useCrewStore.getState().view?.task_id).toBe('T-107')
    })
    await waitFor(() => {
      expect(useCrewStore.getState().view?.stages.interviewer.status).toBe('waiting')
    })
    backend.dispose()
  })

  it('se o REST falha, não trava: marca hidratado e espera o snapshot do WS', async () => {
    const backend = new ScenarioBackend({ speed: 5000 })
    const { handler } = createWsHandler(backend)
    server.use(
      http.get('*/api/task', () => new HttpResponse(null, { status: 500 })),
      handler,
    )
    renderWithClient(<CrewConnection />)
    await waitFor(() => {
      expect(useCrewStore.getState().hydrated).toBe(true)
    })
    backend.dispose()
  })

  it('re-hidrata via GET /api/task quando o WS não manda snapshot ao conectar', async () => {
    const quietSocket = ws.link('*/ws').addEventListener('connection', () => undefined)
    server.use(
      http.get('*/api/task', () => HttpResponse.json(fixture('done'))),
      quietSocket,
    )

    renderWithClient(<CrewConnection />)
    await waitFor(() => {
      expect(useCrewStore.getState().view?.phase).toBe('done')
    })
  })
})
