import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { server } from '../test/server'
import { fixture } from '../test/fixtures'
import { ApiError, CommandError, fetchCurrentTask, fetchRepos, postCommand } from './client'

describe('GETs tipados', () => {
  it('lista repos', async () => {
    server.use(
      http.get('*/api/repos', () => HttpResponse.json([{ name: 'a', base_branch: 'main' }])),
    )
    await expect(fetchRepos()).resolves.toEqual([{ name: 'a', base_branch: 'main' }])
  })

  it('GET /api/task devolve TaskView ou null', async () => {
    server.use(http.get('*/api/task', () => HttpResponse.json(fixture('done'))))
    await expect(fetchCurrentTask()).resolves.toMatchObject({ task_id: 'T-107' })
    server.use(http.get('*/api/task', () => HttpResponse.json(null)))
    await expect(fetchCurrentTask()).resolves.toBeNull()
  })

  it('resposta fora do contrato vira ApiError', async () => {
    server.use(http.get('*/api/repos', () => HttpResponse.json({ nope: true })))
    await expect(fetchRepos()).rejects.toBeInstanceOf(ApiError)
  })

  it('HTTP 500 vira ApiError com status', async () => {
    server.use(http.get('*/api/repos', () => new HttpResponse(null, { status: 500 })))
    await expect(fetchRepos()).rejects.toMatchObject({ status: 500 })
  })
})

describe('postCommand', () => {
  it('envia o Command como JSON e devolve o CommandReply', async () => {
    let received: unknown
    server.use(
      http.post('*/api/commands', async ({ request }) => {
        received = await request.json()
        return HttpResponse.json({ ok: true, error: null, view: fixture('planning') })
      }),
    )
    const reply = await postCommand({ type: 'approve_plan' })
    expect(received).toEqual({ type: 'approve_plan' })
    expect(reply.ok).toBe(true)
    expect(reply.view?.task_id).toBe('T-107')
  })

  it('409 com CommandReply vira CommandError com a mensagem do servidor', async () => {
    server.use(
      http.post('*/api/commands', () =>
        HttpResponse.json(
          { ok: false, error: 'Já existe uma tarefa ativa.', view: null },
          { status: 409 },
        ),
      ),
    )
    const error = await postCommand({
      type: 'start_task',
      repo: 'r',
      title: 't',
    }).catch((e: unknown) => e)
    expect(error).toBeInstanceOf(CommandError)
    expect(error).toMatchObject({ status: 409, message: 'Já existe uma tarefa ativa.' })
  })

  it('422 no formato FastAPI ({detail: string}) também vira mensagem legível', async () => {
    server.use(
      http.post('*/api/commands', () =>
        HttpResponse.json({ detail: 'Título obrigatório' }, { status: 422 }),
      ),
    )
    await expect(postCommand({ type: 'cancel_task' })).rejects.toMatchObject({
      status: 422,
      message: 'Título obrigatório',
    })
  })

  it('422 com detail em lista cai na mensagem genérica com o status', async () => {
    server.use(
      http.post('*/api/commands', () =>
        HttpResponse.json({ detail: [{ loc: ['body'], msg: 'x' }] }, { status: 422 }),
      ),
    )
    await expect(postCommand({ type: 'cancel_task' })).rejects.toMatchObject({
      message: 'Comando recusado (422).',
    })
  })

  it('ok:false com HTTP 200 também é erro', async () => {
    server.use(
      http.post('*/api/commands', () =>
        HttpResponse.json({ ok: false, error: 'nope', view: null }),
      ),
    )
    await expect(postCommand({ type: 'cancel_task' })).rejects.toMatchObject({ message: 'nope' })
  })

  it('falha de rede vira CommandError status 0', async () => {
    server.use(http.post('*/api/commands', () => HttpResponse.error()))
    await expect(postCommand({ type: 'cancel_task' })).rejects.toMatchObject({
      name: 'CommandError',
      status: 0,
    })
  })
})
