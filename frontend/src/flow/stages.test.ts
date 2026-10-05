import { describe, expect, it } from 'vitest'
import type { EdgeKey } from '../contracts/aliases'
import type { StageView, TaskView } from '../contracts/generated'
import { fixture } from '../test/fixtures'
import {
  CONNECTOR_EDGES,
  EDGE_TARGET,
  FLOW_STAGES,
  STAGE_META,
  connectorState,
  emptyStage,
  stageCounter,
  stageDescription,
  stageIcon,
  stageTag,
  stagesToCollapse,
  withProgress,
} from './stages'

const stage = (overrides: Partial<StageView>): StageView => ({
  status: 'idle',
  now: null,
  logs: [],
  ...overrides,
})

describe('connectorState (mapa conector → arestas, igual ao mockup)', () => {
  it('é idle sem arestas ou sem view', () => {
    expect(connectorState({}, CONNECTOR_EDGES.source)).toBe('idle')
    expect(connectorState(null, CONNECTOR_EDGES.source)).toBe('idle')
  })

  it('é "on" quando qualquer aresta do conector existe', () => {
    expect(connectorState({ 'ma-iv': 'on' }, CONNECTOR_EDGES.source)).toBe('on')
  })

  it('é "active" quando qualquer aresta do conector está ativa (active vence on)', () => {
    expect(connectorState({ 'iv-pl': 'on', 'pl-ap': 'active' }, CONNECTOR_EDGES.plan)).toBe(
      'active',
    )
    expect(connectorState({ 'ts-dv': 'on', 'rv-dv': 'active' }, CONNECTOR_EDGES.loopAdjust)).toBe(
      'active',
    )
  })

  it('ma-iv só acende o conector de origem; iv-pl só o seguinte', () => {
    expect(connectorState({ 'ma-iv': 'on' }, CONNECTOR_EDGES.interview)).toBe('idle')
    expect(connectorState({ 'iv-pl': 'on' }, CONNECTOR_EDGES.source)).toBe('idle')
    expect(connectorState({ 'iv-pl': 'on' }, CONNECTOR_EDGES.interview)).toBe('on')
  })

  it('loops laterais usam ts-dv e rv-dv', () => {
    const edges = { 'ts-dv': 'active', 'rv-dv': 'on' } as const
    expect(connectorState(edges, CONNECTOR_EDGES.loopFail)).toBe('active')
    expect(connectorState(edges, CONNECTOR_EDGES.loopAdjust)).toBe('on')
  })

  it('cobre as 9 arestas do contrato com um conector ou loop', () => {
    const covered = new Set<string>(Object.values(CONNECTOR_EDGES).flat())
    const all: EdgeKey[] = [
      'ma-iv',
      'iv-pl',
      'pl-ap',
      'ap-dv',
      'dv-ts',
      'ts-rv',
      'rv-dn',
      'ts-dv',
      'rv-dv',
    ]
    for (const edge of all) expect(covered.has(edge)).toBe(true)
  })

  it('reproduz os conectores da fixture reviewing', () => {
    const { edges } = fixture('reviewing')
    expect(connectorState(edges, CONNECTOR_EDGES.test)).toBe('active')
    expect(connectorState(edges, CONNECTOR_EDGES.finish)).toBe('idle')
    expect(connectorState(edges, CONNECTOR_EDGES.loopFail)).toBe('on')
    expect(connectorState(edges, CONNECTOR_EDGES.loopAdjust)).toBe('idle')
  })
})

describe('EDGE_TARGET', () => {
  it('aponta cada aresta pro card que ela alimenta', () => {
    expect(EDGE_TARGET['ma-iv']).toBe('interviewer')
    expect(EDGE_TARGET['pl-ap']).toBe('approval')
    expect(EDGE_TARGET['ts-dv']).toBe('developer')
    expect(EDGE_TARGET['rv-dv']).toBe('developer')
    expect(EDGE_TARGET['rv-dn']).toBe('done')
  })
})

describe('stageDescription', () => {
  it('usa stage.now quando há trabalho/resultado', () => {
    for (const status of ['active', 'waiting', 'done', 'error'] as const) {
      expect(stageDescription('planner', stage({ status, now: 'fazendo X' }))).toBe('fazendo X')
    }
  })

  it('usa a descrição fixa em idle/pick/skipped, mesmo com now preenchido', () => {
    for (const status of ['idle', 'pick', 'skipped'] as const) {
      expect(stageDescription('planner', stage({ status, now: 'resto' }))).toBe(
        STAGE_META.planner.desc,
      )
    }
  })

  it('usa a descrição fixa quando now é null ou o estágio não existe', () => {
    expect(stageDescription('tester', stage({ status: 'active', now: null }))).toBe(
      STAGE_META.tester.desc,
    )
    expect(stageDescription('tester', null)).toBe(STAGE_META.tester.desc)
  })
})

describe('stageTag / stageCounter', () => {
  const counters = fixture('escalated').counters

  it('mostra rótulo do status + contador', () => {
    expect(stageTag('tester', 'error', counters)).toBe('precisa de você · 3/3')
    expect(stageTag('developer', 'done', counters)).toBe('ok · rodada 3')
    expect(stageTag('reviewer', 'active', { ...counters, review_round: 1 })).toBe(
      'trabalhando · 1/2',
    )
  })

  it('sem contador mostra só o status; sem nada, vazio', () => {
    expect(stageTag('planner', 'done', counters)).toBe('ok')
    expect(stageTag('planner', 'idle', counters)).toBe('')
    expect(stageTag('tester', 'idle', { ...counters, test_attempt: 0 })).toBe('')
    expect(stageCounter('tester', undefined)).toBe('')
  })

  it('contadores zerados não aparecem', () => {
    const zero = { ...counters, dev_round: 0, test_attempt: 0, review_round: 0 }
    expect(stageCounter('developer', zero)).toBe('')
    expect(stageCounter('reviewer', zero)).toBe('')
  })
})

describe('stageIcon', () => {
  it('✓ quando done, ! quando error, senão o ícone do estágio', () => {
    expect(stageIcon('tester', 'done')).toBe('✓')
    expect(stageIcon('tester', 'error')).toBe('!')
    expect(stageIcon('tester', 'active')).toBe('T')
  })
})

describe('emptyStage', () => {
  it('só o card de origem fica em pick', () => {
    expect(emptyStage('manual').status).toBe('pick')
    for (const key of FLOW_STAGES) expect(emptyStage(key).status).toBe('idle')
  })
})

describe('withProgress', () => {
  const active = stage({
    status: 'active',
    now: 'antes',
    logs: [{ ts: '2026-10-01T12:00:00Z', text: 'a' }],
  })
  const lines = [{ ts: '2026-10-01T12:00:05Z', text: 'Editando src/x.py' }]

  it('sobrepõe a última linha e anexa o log no estágio ativo', () => {
    const result = withProgress(active, lines)
    expect(result.now).toBe('Editando src/x.py')
    expect(result.logs).toHaveLength(2)
  })

  it('ignora progresso fora do estágio ativo ou vazio', () => {
    const done = stage({ status: 'done', now: 'ok' })
    expect(withProgress(done, lines)).toBe(done)
    expect(withProgress(active, [])).toBe(active)
    expect(withProgress(active, undefined)).toBe(active)
  })
})

describe('stagesToCollapse', () => {
  const withStatus = (
    view: TaskView,
    patch: Partial<Record<keyof TaskView['stages'], StageView>>,
  ) => ({
    ...view,
    stages: { ...view.stages, ...patch },
  })

  it('fecha o card que saiu de waiting pra done/idle', () => {
    const prev = fixture('awaiting_approval')
    const next = withStatus(prev, { approval: stage({ status: 'done' }) })
    expect(stagesToCollapse(prev, next)).toEqual(['approval'])
    const adjusted = withStatus(prev, { approval: stage({ status: 'idle' }) })
    expect(stagesToCollapse(prev, adjusted)).toEqual(['approval'])
  })

  it('não fecha waiting → active (entrevistador calculando a próxima pergunta)', () => {
    const prev = fixture('interviewing')
    const next = withStatus(prev, { interviewer: stage({ status: 'active' }) })
    expect(stagesToCollapse(prev, next)).toEqual([])
  })

  it('fecha o card da escalada quando ela é resolvida', () => {
    const prev = fixture('escalated')
    const next = { ...prev, escalation: null }
    expect(stagesToCollapse(prev, next)).toEqual(['tester'])
  })

  it('não mexe em nada entre tarefas diferentes ou sem snapshot', () => {
    const a = fixture('awaiting_approval')
    const b = { ...fixture('done'), task_id: 'T-999' }
    expect(stagesToCollapse(a, b)).toEqual([])
    expect(stagesToCollapse(null, a)).toEqual([])
    expect(stagesToCollapse(a, null)).toEqual([])
  })
})
