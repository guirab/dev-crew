import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { EpicView, StageView } from '../contracts/generated'
import { epicLane as lane } from '../test/fixtures'
import { EpicBoard, laneLevels } from './EpicBoard'
import { selectionTotal } from '../bodies/EpicList'

const idle: StageView = { status: 'idle', now: null, logs: [] }
const active = (now: string): StageView => ({ status: 'active', now, logs: [] })
const column = (name: string) => screen.getByRole('group', { name })
const board = (lanes: EpicView[], onOpen = vi.fn()) =>
  render(<EpicBoard lanes={lanes} onOpen={onOpen} />)

describe('EpicBoard', () => {
  it.each([
    ['pending', 'Na fila'],
    ['waiting', 'Na fila'],
    ['preparing', 'Rodando'],
    ['running', 'Rodando'],
    ['merging', 'Rodando'],
    ['escalated', 'Precisa de você'],
    ['limited', 'Precisa de você'],
    ['failed', 'Precisa de você'],
    ['merged', 'Pronto'],
  ] as const)('status %s cai em %s', (status, name) => {
    board([lane('E1', status)])
    expect(within(column(name)).getByText('Épico E1')).toBeInTheDocument()
    expect(screen.getAllByText('Épico E1')).toHaveLength(1)
  })

  it('só mostra as colunas que têm épico', () => {
    board([lane('E1', 'running'), lane('E2', 'merged')])
    expect(screen.getAllByRole('group').map((g) => g.getAttribute('aria-label'))).toEqual([
      'Rodando',
      'Pronto',
    ])
  })

  it('card compacto: id, título, tokens; sem pipeline na fila', () => {
    const { container } = board([
      lane('E3', 'waiting', { tokens: 1500 }),
      lane('E1', 'running', { tokens: 2000 }),
    ])
    const card = column('Na fila')
    expect(within(card).getByText('E3')).toBeInTheDocument()
    expect(within(card).getByText(/1,5 mil tok/)).toBeInTheDocument()
    expect(container.querySelector('[data-lane="E3"] i')).toBeNull()
    expect(container.querySelector('[data-lane="E1"] i')).not.toBeNull()
  })

  it('integração mostra ⇄', () => {
    board([lane('I1', 'escalated', { kind: 'integration', title: 'Integração E1' })])
    expect(within(column('Precisa de você')).getByText('⇄')).toBeInTheDocument()
  })

  it('clicar no card abre o épico no painel lateral', async () => {
    const user = userEvent.setup()
    const onOpen = vi.fn()
    board([lane('E1', 'running')], onOpen)
    await user.click(screen.getByRole('button', { name: /Épico E1/ }))
    expect(onOpen).toHaveBeenCalledWith('E1')
  })
})

describe('mini-pipeline do card', () => {
  it('pinta Dev/Test/Merge pelo status de cada estágio e conta as voltas', () => {
    const stages = {
      developer: { ...idle, status: 'done' as const },
      tester: active('x'),
      reviewer: idle,
    }
    const counters = { ...lane('E1', 'running').counters, dev_round: 3 }
    const { container } = board([lane('E1', 'running', { stages, counters })])
    const chips = [...container.querySelectorAll('[data-lane="E1"] i')]
    expect(chips.map((i) => [i.textContent, i.getAttribute('data-status')])).toEqual([
      ['Dev', 'done'],
      ['Test', 'active'],
      ['Merge', 'idle'],
    ])
    expect(container.querySelector('[data-lane="E1"] b[title]')).toHaveTextContent('↺2')
  })

  it('no review final o terceiro é Rev', () => {
    const { container } = board([lane('R', 'running', { kind: 'review', title: 'Review final' })])
    expect(container.querySelector('[data-lane="R"] i:last-of-type')).toHaveTextContent('Rev')
  })
})

describe('laneLevels (vista Grafo)', () => {
  it('agrupa por profundidade de dependência; review final por último', () => {
    const levels = laneLevels([
      lane('REV', 'pending', { kind: 'review' }),
      lane('E3', 'pending', { depends_on: ['E2'] }),
      lane('E1', 'pending'),
      lane('E2', 'pending', { depends_on: ['E1'] }),
      lane('E4', 'pending'),
    ])
    expect(levels.map((level) => level.map((l) => l.id))).toEqual([
      ['E1', 'E4'],
      ['E2'],
      ['E3'],
      ['REV'],
    ])
  })

  it('dependência desconhecida ou ciclo não trava', () => {
    const levels = laneLevels([
      lane('A', 'pending', { depends_on: ['B', 'X'] }),
      lane('B', 'pending', { depends_on: ['A'] }),
    ])
    expect(
      levels
        .flat()
        .map((l) => l.id)
        .sort(),
    ).toEqual(['A', 'B'])
  })
})

describe('selectionTotal', () => {
  const estimates = [
    { epic_id: 'E1', tokens: 40_000, usd: 1.2 },
    { epic_id: 'E2', tokens: 60_000, usd: 0.6 },
  ]
  it('soma as estimativas dos marcados', () => {
    expect(selectionTotal(['E1', 'E2'], estimates)).toBe('2 épicos · ~100,0 mil tokens · ~$1.80')
  })
  it('sem estimativa mostra só a contagem', () => {
    expect(selectionTotal(['E3'], estimates)).toBe('1 épico')
  })
})
