import { describe, expect, it } from 'vitest'
import type { TaskView } from '../contracts/generated'
import { epicLane, fixture } from '../test/fixtures'
import { logSpan, opensByDefault, timelineNodes } from './timeline'

const tones = (view: TaskView) =>
  Object.fromEntries(timelineNodes(view).map((node) => [node.key, node.tone]))

function splitView(view: TaskView, over: Partial<TaskView> = {}): TaskView {
  return {
    ...view,
    phase: 'executing',
    stages: {
      ...view.stages,
      developer: { status: 'idle', now: null, logs: [] },
    },
    epics: [
      epicLane('E1', 'merged'),
      epicLane('E2', 'escalated', {
        escalation: { stage: 'tester', reason: 'Tester falhou 3 vezes', epic_id: 'E2' },
      }),
      epicLane('E3', 'running'),
      epicLane('REV', 'pending', { kind: 'review', title: 'Review final' }),
    ],
    ...over,
  }
}

describe('timelineNodes', () => {
  it('entrevista esperando você: Tarefa pronta, Entrevistador na sua vez, o resto cinza', () => {
    expect(tones(fixture('interviewing'))).toEqual({
      task: 'done',
      interview: 'you',
      plan: 'todo',
      execution: 'todo',
      review: 'todo',
      result: 'todo',
    })
  })

  it('plano aprovado: a Tarefa sai e o nó vira "Plano aprovado"', () => {
    const nodes = timelineNodes(fixture('developing'))
    expect(nodes.map((n) => n.key)).toEqual(['interview', 'plan', 'execution', 'review', 'result'])
    expect(nodes[1]).toMatchObject({ name: 'Plano aprovado', tone: 'done' })
    expect(nodes[2]).toMatchObject({ tone: 'run', summary: 'Developer trabalhando' })
  })

  it('escalada fora de épico: o nó do estágio fica na sua vez (não em falha)', () => {
    expect(tones(fixture('escalated')).execution).toBe('you')
  })

  it('tarefa viva com estágio em erro (volta do loop) segue trabalhando', () => {
    const base = fixture('developing')
    const view: TaskView = {
      ...base,
      phase: 'developing',
      stages: { ...base.stages, tester: { status: 'error', now: 'FALHOU', logs: [] } },
    }
    expect(tones(view).execution).toBe('run')
  })

  it('Reviewer pediu ajuste: o nó diz que devolveu ao Developer (não fica cinza)', () => {
    const base = fixture('developing')
    const review: TaskView['review'] = {
      type: 'review',
      verdict: 'changes_requested',
      comments: [],
      commit_message: null,
    }
    const node = timelineNodes({ ...base, review }).find((n) => n.key === 'review')
    expect(node).toMatchObject({ tone: 'done', summary: 'pediu ajuste · voltou pro Developer' })

    // replanejar desaprova o plano: o pedido antigo não conta mais
    const replanning: TaskView = {
      ...base,
      phase: 'planning',
      review,
      stages: { ...base.stages, approval: { status: 'idle', now: null, logs: [] } },
    }
    expect(tones(replanning).review).toBe('todo')

    // review final de épicos: a faixa REV volta pro Developer da faixa
    const split = splitView(base, {
      epics: [epicLane('E1', 'merged'), epicLane('REV', 'running', { kind: 'review', review })],
    })
    expect(timelineNodes(split).find((n) => n.key === 'review')).toMatchObject({
      name: 'Review final',
      tone: 'done',
      summary: 'pediu ajuste · voltou pro Developer',
    })
  })

  it('duração do plano é a do Planner, sem o tempo esperando aprovação', () => {
    const base = fixture('developing')
    const at = (s: number) => new Date(Date.UTC(2026, 9, 16, 9, 0, s)).toISOString()
    const view: TaskView = {
      ...base,
      stages: {
        ...base.stages,
        planner: {
          status: 'done',
          now: null,
          logs: [
            { ts: at(0), text: 'a' },
            { ts: at(5), text: 'b' },
          ],
        },
        approval: {
          status: 'done',
          now: null,
          logs: [
            { ts: at(5), text: 'c' },
            { ts: at(419), text: 'd' },
          ],
        },
      },
    }
    expect(timelineNodes(view).find((n) => n.key === 'plan')?.meta).toBe('5s')
  })

  it('concluída: tudo pronto e o resultado abre sozinho', () => {
    const view = fixture('done')
    const nodes = timelineNodes(view)
    expect(nodes.every((n) => n.tone === 'done')).toBe(true)
    const result = nodes.at(-1)
    expect(result).toMatchObject({ key: 'result', name: 'Pronto pra commitar' })
    expect(result && opensByDefault(result, view)).toBe(true)
  })

  it('falhou: para no nó que falhou, sem os futuros', () => {
    const base = fixture('developing')
    const view: TaskView = {
      ...base,
      phase: 'failed',
      stages: { ...base.stages, developer: { status: 'error', now: 'npm ci', logs: [] } },
    }
    expect(tones(view)).toEqual({ interview: 'done', plan: 'done', execution: 'err' })
  })

  it('cancelada: o nó interrompido diz "cancelada", não o último log do Tester', () => {
    const base = fixture('developing')
    const view: TaskView = {
      ...base,
      phase: 'cancelled',
      stages: {
        ...base.stages,
        developer: { status: 'error', now: 'Cancelada pelo usuário', logs: [] },
        tester: { status: 'idle', now: 'FALHOU · 46/48 · tentativa 1/3', logs: [] },
      },
    }
    expect(timelineNodes(view).at(-1)).toMatchObject({
      key: 'execution',
      tone: 'err',
      summary: 'cancelada',
    })
  })

  it('limite: o nó atual pausa', () => {
    const view: TaskView = { ...fixture('developing'), phase: 'limited' }
    expect(timelineNodes(view)[2]).toMatchObject({
      key: 'execution',
      tone: 'pause',
      summary: 'pausada',
    })
  })

  it('épicos: Execução na sua vez com escalado, contagem de prontos e review final à parte', () => {
    const view = splitView(fixture('developing'))
    const nodes = timelineNodes(view)
    expect(nodes.find((n) => n.key === 'execution')).toMatchObject({
      tone: 'you',
      summary: '1 de 3 prontos',
    })
    expect(nodes.find((n) => n.key === 'review')).toMatchObject({
      name: 'Review final',
      tone: 'todo',
    })
  })

  it('próximo lote: Execução pronta e um nó "Próximo lote" na sua vez', () => {
    const view = splitView(fixture('developing'), {
      phase: 'awaiting_selection',
      epics: [epicLane('E1', 'merged'), epicLane('E2', 'pending')],
    })
    expect(tones(view)).toMatchObject({ execution: 'done', next: 'you', review: 'todo' })
  })
})

describe('logSpan', () => {
  it('segundos entre a primeira e a última linha', () => {
    expect(
      logSpan([
        { ts: '2026-10-16T12:00:00Z', text: 'a' },
        { ts: '2026-10-16T12:02:30Z', text: 'b' },
      ]),
    ).toBe(150)
    expect(logSpan([{ ts: '2026-10-16T12:00:00Z', text: 'a' }])).toBeNull()
  })
})
