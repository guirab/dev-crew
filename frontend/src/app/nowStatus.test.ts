import { describe, expect, it } from 'vitest'
import type { EpicView, TaskView } from '../contracts/generated'
import { fixture } from '../test/fixtures'
import { nowStatus } from './nowStatus'

function lane(id: string, status: EpicView['status'], now: string | null): EpicView {
  const base = fixture('developing')
  const stage = { status: 'active' as const, now, logs: [] }
  const idle = { status: 'idle' as const, now: null, logs: [] }
  return {
    id,
    kind: 'epic',
    title: `Épico ${id}`,
    goal: '',
    size: 'S',
    depends_on: [],
    status,
    stages: { developer: stage, tester: idle, reviewer: idle },
    edges: {},
    active_edge: null,
    counters: base.counters,
    dev_rounds: [],
    test_runs: [],
    review: null,
    escalation: null,
    branch: null,
    worktree_path: null,
    commit: null,
    commit_message: null,
    cost_usd: 0,
    tokens: 0,
  }
}

describe('nowStatus', () => {
  it('agente trabalhando: tom working, linha do estágio ativo, sem CTA', () => {
    expect(nowStatus(fixture('developing'))).toEqual({
      tone: 'working',
      headline: 'Developer trabalhando',
      detail: 'Editando shop/report.py',
      cta: null,
    })
  })

  it('a última linha de progresso do WS passa na frente do snapshot', () => {
    const progress = { developer: [{ ts: '2026-10-14T12:00:00Z', text: 'Rodando ruff' }] }
    expect(nowStatus(fixture('developing'), progress).detail).toBe('Rodando ruff')
  })

  it('entrevista esperando resposta: CTA leva ao Entrevistador', () => {
    const status = nowStatus(fixture('interviewing'))
    expect(status.tone).toBe('attention')
    expect(status.headline).toBe('Precisa de você: responda a entrevista')
    expect(status.cta).toEqual({ label: 'Responder entrevista', target: 'interviewer' })
  })

  it('aprovação: CTA leva ao card de aprovação', () => {
    expect(nowStatus(fixture('awaiting_approval')).cta).toEqual({
      label: 'Revisar plano',
      target: 'approval',
    })
  })

  it('escalada mostra o motivo e leva ao estágio que escalou', () => {
    const status = nowStatus(fixture('escalated'))
    expect(status.detail).toBe('3 falhas consecutivas de teste')
    expect(status.cta).toEqual({ label: 'Resolver escalada', target: 'tester' })
  })

  it('escalada de um épico leva à seção de épicos', () => {
    const escalation = { stage: 'developer' as const, reason: 'travou', epic_id: 'E2' }
    expect(nowStatus({ ...fixture('escalated'), escalation }).cta?.target).toBe('epics')
  })

  it('épicos em execução: primeira faixa ocupada + quantas mais em paralelo', () => {
    const view: TaskView = {
      ...fixture('developing'),
      phase: 'executing',
      epics: [
        lane('E1', 'merged', null),
        lane('E2', 'running', 'Editando HistoryList.tsx'),
        lane('E3', 'running', 'npm test'),
      ],
    }
    const status = nowStatus(view)
    expect(status.headline).toBe('Épicos em execução')
    expect(status.detail).toBe('E2 · Editando HistoryList.tsx (+1 em paralelo)')
  })

  it('épico esperando você: resume o paralelo e o CTA abre o épico', () => {
    const escalated: EpicView = {
      ...lane('E2', 'escalated', null),
      escalation: { stage: 'tester', reason: 'Tester falhou 3 vezes seguidas', epic_id: 'E2' },
    }
    const view: TaskView = {
      ...fixture('developing'),
      phase: 'executing',
      epics: [
        lane('E1', 'running', 'x'),
        escalated,
        lane('E3', 'preparing', null),
        lane('E4', 'merged', null),
      ],
    }
    expect(nowStatus(view)).toEqual({
      tone: 'attention',
      headline: 'Épicos em execução · 1 precisa de você',
      detail: 'E2 · Tester falhou 3 vezes seguidas — 2 épicos seguem rodando',
      cta: { label: 'Resolver E2', target: 'epics', epic: 'E2' },
    })
  })

  it('limite de uso: tom de erro com a mensagem do limite, sem CTA (o banner tem Retomar)', () => {
    const limit = { kind: 'session' as const, resets_at: null, message: 'Limite da sessão' }
    const status = nowStatus({ ...fixture('developing'), phase: 'limited', limit })
    expect(status.tone).toBe('error')
    expect(status.detail).toBe('Limite da sessão')
    expect(status.cta).toBeNull()
  })

  it('concluída: leva ao resultado', () => {
    const status = nowStatus(fixture('done'))
    expect(status).toMatchObject({ tone: 'done', headline: '✓ Concluída' })
    expect(status.detail).toBe(fixture('done').stages.done.now)
    expect(status.cta).toEqual({ label: 'Ver resultado', target: 'done' })
  })

  it.each(['failed', 'cancelled'] as const)('%s: sem detalhe nem CTA', (phase) => {
    const status = nowStatus({ ...fixture('done'), phase })
    expect(status.tone).toBe('error')
    expect(status.detail).toBeNull()
    expect(status.cta).toBeNull()
  })
})
