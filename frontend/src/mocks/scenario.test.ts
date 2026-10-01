import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { isTaskView } from '../api/guards'
import type { TaskView, WsMessage } from '../contracts/generated'
import { ScenarioBackend } from './scenario'

const AZURE = {
  type: 'start_task',
  source: 'azure',
  repo: 'portal-vendas',
  work_item_id: 4821,
} as const
const MANUAL = {
  type: 'start_task',
  source: 'manual',
  repo: 'api-pedidos',
  title: 'Exportar pedidos filtrados em CSV',
  description: 'Exportar a listagem',
} as const

function view(backend: ScenarioBackend): TaskView {
  const v = backend.getView()
  if (!v) throw new Error('sem tarefa')
  return v
}

/** Roda os timers do cenário até ele parar num ponto de espera humana (ou terminar). */
const settle = () => vi.runAllTimersAsync()

describe('ScenarioBackend', () => {
  let backend: ScenarioBackend
  let messages: WsMessage[]

  beforeEach(() => {
    vi.useFakeTimers()
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    backend = new ScenarioBackend({ now: () => new Date() })
    messages = []
    backend.subscribe((m) => messages.push(m))
  })

  afterEach(() => {
    backend.dispose()
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('sem tarefa: view null', () => {
    expect(backend.getView()).toBeNull()
  })

  it('fluxo azure completo: plano → aprovação → dev → 1º teste falha → review pede mudanças → done', async () => {
    const started = backend.handle(AZURE)
    expect(started.status).toBe(200)
    expect(view(backend)).toMatchObject({
      source: 'azure',
      ref: 'AB#4821',
      phase: 'planning',
      active_edge: 'az-pl',
    })
    expect(view(backend).stages.interviewer.status).toBe('skipped')

    await settle()
    expect(view(backend)).toMatchObject({ phase: 'awaiting_approval', active_edge: 'pl-ap' })
    expect(view(backend).stages.approval.status).toBe('waiting')
    expect(view(backend).plan?.steps).toHaveLength(4)

    expect(backend.handle({ type: 'approve_plan' }).status).toBe(200)
    await settle()

    const done = view(backend)
    expect(done.phase).toBe('done')
    expect(done.stages.done.status).toBe('done')
    expect(done.test_runs.map((r) => r.ok)).toEqual([false, true, true]) // 1º falha, depois passa
    expect(done.dev_rounds).toHaveLength(3) // plano + correção do teste + review
    expect(done.counters).toMatchObject({ review_round: 2, test_attempt: 0 })
    expect(done.review?.verdict).toBe('approved')
    expect(done.review?.comments.every((c) => c.resolved)).toBe(true)
    expect(done.final?.commit_message).toContain('Refs: AB#4821')
    expect(done.final?.files.length).toBeGreaterThan(0)
    expect(done.edges['rv-dn']).toBe('on')
    expect(done.active_edge).toBeNull()
  })

  it('todo snapshot emitido cumpre o contrato TaskView', async () => {
    backend.handle(AZURE)
    await settle()
    backend.handle({ type: 'approve_plan' })
    await settle()

    const views = messages.flatMap((m) => (m.type === 'view' ? [m.data] : []))
    expect(views.length).toBeGreaterThan(20)
    for (const v of views) expect(isTaskView(v)).toBe(true)
    expect(messages.some((m) => m.type === 'progress')).toBe(true)
  })

  it('fluxo manual: entrevista de 3 perguntas (aceitar e responder), spec fecha e segue pro plano', async () => {
    backend.handle(MANUAL)
    let v = view(backend)
    expect(v).toMatchObject({ phase: 'interviewing', active_edge: 'ma-iv' })
    expect(v.stages.azure.status).toBe('skipped')
    expect(v.stages.interviewer.status).toBe('waiting')
    expect(v.interview?.pending?.topic).toBe('Fora de escopo')

    expect(backend.handle({ type: 'answer_interview', text: null }).status).toBe(200) // aceita
    v = view(backend)
    expect(v.interview?.turns[0]).toMatchObject({ accepted_recommendation: true })
    expect(v.interview?.pending?.topic).toBe('Critérios de aceite')

    backend.handle({ type: 'answer_interview', text: 'Intervalo inclusivo' })
    expect(view(backend).interview?.turns[1]).toMatchObject({
      answer: 'Intervalo inclusivo',
      accepted_recommendation: false,
    })

    backend.handle({ type: 'answer_interview', text: null })
    v = view(backend)
    expect(v.interview?.pending).toBeNull()
    expect(v.interview?.decisions).toHaveLength(3)
    expect(v.stages.interviewer.status).toBe('done')

    await settle()
    v = view(backend)
    expect(v.phase).toBe('awaiting_approval')
    expect(v.plan?.acceptance_criteria[0]).toContain('Intervalo inclusivo')
  })

  it('ajuste de plano volta pro Planner e depois pra aprovação', async () => {
    backend.handle(AZURE)
    await settle()
    const adjust = backend.handle({ type: 'adjust_plan', text: 'não mexer no auth' })
    expect(adjust.status).toBe(200)
    expect(view(backend).stages.approval.status).toBe('idle')
    expect(view(backend).stages.planner.now).toContain('não mexer no auth')
    await settle()
    expect(view(backend).stages.approval.status).toBe('waiting')
  })

  it('forceEscalate: Tester falha até o limite e escala; instruir retoma e conclui', async () => {
    backend.setForceEscalate(true)
    backend.handle(AZURE)
    await settle()
    backend.handle({ type: 'approve_plan' })
    await settle()

    const escalated = view(backend)
    expect(escalated.phase).toBe('escalated')
    expect(escalated.escalation).toMatchObject({ stage: 'tester' })
    expect(escalated.stages.tester.status).toBe('error')
    expect(escalated.counters).toMatchObject({ test_attempt: 3, max_test_attempts: 3 })

    expect(backend.handle({ type: 'escalation', action: 'instruct', text: '  ' }).status).toBe(422)
    expect(
      backend.handle({ type: 'escalation', action: 'instruct', text: 'usar fake timers' }).status,
    ).toBe(200)
    expect(backend.forceEscalate).toBe(false)
    await settle()
    expect(view(backend).phase).toBe('done')
  })

  it('escalada: +2 tentativas sobe o limite; replanejar volta pro Planner', async () => {
    backend.setForceEscalate(true)
    backend.handle(AZURE)
    await settle()
    backend.handle({ type: 'approve_plan' })
    await settle()

    backend.handle({ type: 'escalation', action: 'replan' })
    await settle()
    expect(view(backend)).toMatchObject({ phase: 'awaiting_approval', escalation: null })

    backend.setForceEscalate(true)
    backend.handle({ type: 'approve_plan' })
    await settle()
    expect(view(backend).phase).toBe('escalated')
    backend.handle({ type: 'escalation', action: 'more_attempts' })
    expect(view(backend).counters.max_test_attempts).toBe(5)
  })

  it('cancelar encerra o fluxo em andamento', async () => {
    backend.handle(AZURE)
    await vi.advanceTimersByTimeAsync(500)
    expect(backend.handle({ type: 'cancel_task' }).status).toBe(200)
    await settle()
    const v = view(backend)
    expect(v.phase).toBe('cancelled')
    expect(v.stages.planner.status).toBe('idle')
    expect(v.plan).toBeNull() // o fluxo cancelado não continuou
  })

  describe('validação dos comandos', () => {
    it('409 ao iniciar com tarefa ativa; permitido após terminar', () => {
      backend.handle(AZURE)
      expect(backend.handle(AZURE).status).toBe(409)
      backend.handle({ type: 'cancel_task' })
      expect(backend.handle(MANUAL).status).toBe(200)
      expect(view(backend).task_id).toBe('T-108')
    })

    it('422 pra work item, repo ou título inválidos', () => {
      expect(backend.handle({ ...AZURE, work_item_id: 1 }).status).toBe(422)
      expect(backend.handle({ ...AZURE, repo: 'nao-existe' }).status).toBe(422)
      expect(backend.handle({ ...MANUAL, title: '   ' }).status).toBe(422)
      expect(backend.getView()).toBeNull()
    })

    it('409 pra comandos fora de contexto', () => {
      for (const cmd of [
        { type: 'approve_plan' },
        { type: 'answer_interview', text: null },
        { type: 'cancel_task' },
        { type: 'escalation', action: 'replan' },
      ] as const) {
        const outcome = backend.handle(cmd)
        expect(outcome.status).toBe(409)
        expect(outcome.reply.ok).toBe(false)
      }
    })

    it('422 pra resposta e ajuste vazios', () => {
      backend.handle(MANUAL)
      expect(backend.handle({ type: 'answer_interview', text: '  ' }).status).toBe(422)
    })
  })
})
