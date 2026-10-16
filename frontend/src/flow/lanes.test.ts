import { describe, expect, it } from 'vitest'
import { epicLane as lane } from '../test/fixtures'
import { dependentsOf, epicProgress, epicsSummary, lanesNeedingYou, sortLanes } from './lanes'

describe('sortLanes', () => {
  it('precisa de você, rodando, preparando, na fila, pronto; empates na ordem do plano', () => {
    const sorted = sortLanes([
      lane('E1', 'merged'),
      lane('E2', 'pending'),
      lane('E3', 'running'),
      lane('E4', 'escalated'),
      lane('E5', 'preparing'),
      lane('E6', 'merging'),
      lane('E7', 'failed'),
      lane('E8', 'waiting'),
    ])
    expect(sorted.map((l) => l.id)).toEqual(['E4', 'E7', 'E3', 'E6', 'E5', 'E2', 'E8', 'E1'])
  })

  it('não mexe no array original', () => {
    const lanes = [lane('E1', 'merged'), lane('E2', 'escalated')]
    sortLanes(lanes)
    expect(lanes.map((l) => l.id)).toEqual(['E1', 'E2'])
  })
})

describe('lanesNeedingYou / dependentsOf', () => {
  it('só escalada e falha esperam você', () => {
    const lanes = [lane('E1', 'escalated'), lane('E2', 'failed'), lane('E3', 'limited')]
    expect(lanesNeedingYou(lanes).map((l) => l.id)).toEqual(['E1', 'E2'])
  })

  it('dependentes ainda não juntados', () => {
    const lanes = [
      lane('E2', 'escalated'),
      lane('E3', 'waiting', { depends_on: ['E2'] }),
      lane('E4', 'merged', { depends_on: ['E2'] }),
    ]
    expect(dependentsOf(lanes, 'E2').map((l) => l.id)).toEqual(['E3'])
  })
})

describe('epicProgress / epicsSummary', () => {
  const lanes = [
    lane('E1', 'running'),
    lane('E2', 'escalated'),
    lane('E3', 'preparing'),
    lane('E4', 'merged'),
    lane('E5', 'waiting'),
    lane('REV', 'pending', { kind: 'review', title: 'Review final' }),
  ]

  it('conta só épicos (sem o review final)', () => {
    expect(epicProgress(lanes)).toEqual({ done: 1, total: 5 })
  })

  it('resume por grupo, preparando conta como rodando, sem grupo vazio', () => {
    expect(epicsSummary(lanes)).toBe('1 precisa de você · 2 rodando · 1 na fila · 1 pronto')
    expect(epicsSummary([lane('E1', 'merged')])).toBe('1 pronto')
  })
})
