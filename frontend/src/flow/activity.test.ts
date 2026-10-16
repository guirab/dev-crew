import { describe, expect, it } from 'vitest'
import type { TaskView } from '../contracts/generated'
import { epicLane as lane, fixture } from '../test/fixtures'
import { activityEvents, attentionCount, filterEvents, groupEvents } from './activity'
import type { ActivityEvent } from './activity'

const ev = (ts: string, who: string, lane: string | null, text: string, attention = false) =>
  ({ ts, who, lane, text, attention }) satisfies ActivityEvent

describe('groupEvents', () => {
  it('mesmo agente, texto e segundo em faixas diferentes viram uma linha com as faixas', () => {
    const rows = groupEvents([
      ev('2026-10-16T19:33:16.900Z', 'Developer', 'E1', 'Preparando o worktree'),
      ev('2026-10-16T19:33:16.500Z', 'Developer', 'E2', 'Preparando o worktree'),
      ev('2026-10-16T19:33:16.100Z', 'Developer', 'E4', 'Preparando o worktree'),
      ev('2026-10-16T19:33:15.900Z', 'Developer', 'E5', 'Preparando o worktree'),
    ])
    expect(rows.map((r) => r.lanes)).toEqual([['E1', 'E2', 'E4'], ['E5']])
  })

  it('texto ou agente diferente não agrupa; sem faixa nunca agrupa', () => {
    const rows = groupEvents([
      ev('2026-10-16T19:00:00Z', 'Developer', 'E1', 'a'),
      ev('2026-10-16T19:00:00Z', 'Developer', 'E2', 'b'),
      ev('2026-10-16T19:00:00Z', 'Tester', 'E3', 'b'),
      ev('2026-10-16T19:00:00Z', 'Planner', null, 'x'),
      ev('2026-10-16T19:00:00Z', 'Planner', null, 'x'),
    ])
    expect(rows).toHaveLength(5)
  })

  it('destaca só o evento mais novo de cada faixa que espera você', () => {
    const rows = groupEvents([
      ev('2026-10-16T19:48:02Z', 'Tester', 'E2', '3ª falha', true),
      ev('2026-10-16T19:47:40Z', 'Merge', 'E4', 'juntado'),
      ev('2026-10-16T19:40:00Z', 'Tester', 'E2', '2ª falha', true),
    ])
    expect(rows.map((r) => r.highlight)).toEqual([true, false, false])
  })
})

describe('filterEvents', () => {
  const events = [
    ev('3', 'Tester', 'E2', 'FALHOU · 2 testes', true),
    ev('2', 'Developer', 'E1', 'Editando a.ts'),
    ev('1', 'Tester', 'E1', 'Tester falhou na rodada 1'),
  ]

  it('precisa de você, erros e origem', () => {
    expect(filterEvents(events, 'all', null, true)).toHaveLength(3)
    expect(filterEvents(events, 'attention', null, true).map((e) => e.ts)).toEqual(['3'])
    expect(filterEvents(events, 'errors', null, true).map((e) => e.ts)).toEqual(['3', '1'])
    expect(filterEvents(events, 'all', 'E1', true).map((e) => e.ts)).toEqual(['2', '1'])
    expect(filterEvents(events, 'all', 'Tester', false).map((e) => e.ts)).toEqual(['3', '1'])
  })
})

describe('activityEvents / attentionCount', () => {
  it('marca os eventos da faixa escalada e conta quem espera você', () => {
    const log = (text: string) => ({
      status: 'active' as const,
      now: text,
      logs: [{ ts: '2026-10-16T19:00:00Z', text }],
    })
    const idle = { status: 'idle' as const, now: null, logs: [] }
    const view: TaskView = {
      ...fixture('developing'),
      phase: 'executing',
      epics: [
        lane('E1', 'running', { stages: { developer: log('a'), tester: idle, reviewer: idle } }),
        lane('E2', 'escalated', { stages: { developer: idle, tester: log('b'), reviewer: idle } }),
      ],
    }
    const byLane = activityEvents(view)
      .filter((e) => e.lane)
      .map((e) => `${String(e.lane)}:${String(e.attention)}`)
    expect(byLane.sort()).toEqual(['E1:false', 'E2:true'])
    expect(attentionCount(view)).toBe(1)
  })

  it('sem épicos conta as etapas esperando você', () => {
    expect(attentionCount(fixture('awaiting_approval'))).toBe(1)
    expect(attentionCount(fixture('developing'))).toBe(0)
  })
})
