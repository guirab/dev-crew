import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { EpicView, StageView, TaskView } from '../contracts/generated'
import { fixture } from '../test/fixtures'
import { EpicBoard, laneLevels } from './EpicBoard'
import { selectionTotal } from '../bodies/EpicList'

const idle: StageView = { status: 'idle', now: null, logs: [] }

function lane(id: string, status: EpicView['status'], over: Partial<EpicView> = {}): EpicView {
  return {
    id,
    kind: 'epic',
    title: `Épico ${id}`,
    goal: `objetivo ${id}`,
    size: 'M',
    depends_on: [],
    status,
    stages: { developer: idle, tester: idle, reviewer: idle },
    edges: {},
    active_edge: null,
    counters: {
      dev_round: 0,
      test_attempt: 0,
      max_test_attempts: 3,
      review_round: 0,
      max_review_rounds: 2,
    },
    dev_rounds: [],
    test_runs: [],
    review: null,
    escalation: null,
    branch: `crew/T-7-${id}`,
    worktree_path: null,
    commit: null,
    commit_message: null,
    cost_usd: 0,
    tokens: 0,
    ...over,
  }
}

const view = (lanes: EpicView[]): TaskView => ({ ...fixture('developing'), epics: lanes })

const column = (name: string) => screen.getByRole('group', { name })
const active = (now: string): StageView => ({ status: 'active', now, logs: [] })

describe('EpicBoard', () => {
  it.each([
    ['pending', 'A fazer'],
    ['waiting', 'A fazer'],
    ['preparing', 'Em andamento'],
    ['running', 'Em andamento'],
    ['merging', 'Em andamento'],
    ['escalated', 'Precisa de você'],
    ['limited', 'Precisa de você'],
    ['failed', 'Precisa de você'],
    ['merged', 'Concluído'],
  ] as const)('status %s cai em %s', (status, name) => {
    render(<EpicBoard view={view([lane('E1', status)])} />)
    expect(within(column(name)).getByText('Épico E1')).toBeInTheDocument()
    expect(screen.getAllByText('Épico E1')).toHaveLength(1)
  })

  it('mostra as quatro colunas mesmo vazias, com estado vazio', () => {
    render(<EpicBoard view={view([])} />)
    for (const name of ['A fazer', 'Em andamento', 'Precisa de você', 'Concluído']) {
      expect(within(column(name)).getByText('nada aqui')).toBeInTheDocument()
    }
  })

  it('move o card de coluna quando o status muda', () => {
    const { rerender } = render(<EpicBoard view={view([lane('E1', 'waiting')])} />)
    expect(within(column('A fazer')).getByText('Épico E1')).toBeInTheDocument()
    rerender(<EpicBoard view={view([lane('E1', 'running')])} />)
    expect(within(column('A fazer')).queryByText('Épico E1')).not.toBeInTheDocument()
    expect(within(column('Em andamento')).getByText('Épico E1')).toBeInTheDocument()
  })

  it('mantém a ordem de view.epics dentro da coluna', () => {
    render(<EpicBoard view={view([lane('E2', 'waiting'), lane('E1', 'waiting')])} />)
    const titles = within(column('A fazer')).getAllByText(/^Épico E/)
    expect(titles.map((t) => t.textContent)).toEqual(['Épico E2', 'Épico E1'])
  })

  it('mostra id, título, dependências e tokens no card fechado', () => {
    render(
      <EpicBoard
        view={view([lane('E3', 'waiting', { depends_on: ['E1', 'E2'], tokens: 1500 })])}
      />,
    )
    const card = column('A fazer')
    expect(within(card).getByText('E3')).toBeInTheDocument()
    expect(within(card).getByText(/depende de E1, E2/)).toBeInTheDocument()
    expect(within(card).getByText(/tok/)).toBeInTheDocument()
    expect(within(card).getByText('objetivo E3')).toBeInTheDocument()
  })

  it('mostra a etapa atual só com estágio ativo', () => {
    const stages = { developer: idle, tester: active('rodando'), reviewer: idle }
    render(<EpicBoard view={view([lane('E1', 'running', { stages })])} />)
    expect(within(column('Em andamento')).getByText('etapa: Tester')).toBeInTheDocument()
  })

  it('mostra Merge no terceiro estágio de ticket e Reviewer no review final', () => {
    const stages = { developer: idle, tester: idle, reviewer: active('juntando') }
    render(
      <EpicBoard
        view={view([
          lane('E1', 'merging', { stages }),
          lane('R', 'running', { kind: 'review', title: 'Review final', stages }),
        ])}
      />,
    )
    expect(screen.getByText('etapa: Merge')).toBeInTheDocument()
    expect(screen.getByText('etapa: Reviewer')).toBeInTheDocument()
  })

  it('não mostra etapa em A fazer nem em Concluído', () => {
    const stages = { developer: active('x'), tester: idle, reviewer: idle }
    render(
      <EpicBoard
        view={view([lane('E1', 'waiting', { stages }), lane('E2', 'merged', { stages })])}
      />,
    )
    expect(screen.queryByText(/etapa:/)).not.toBeInTheDocument()
  })

  it('integração mostra ⇄ e o review final é um card', () => {
    render(
      <EpicBoard
        view={view([
          lane('I1', 'escalated', { kind: 'integration', title: 'Integração E1' }),
          lane('R', 'waiting', { kind: 'review', title: 'Review final' }),
        ])}
      />,
    )
    expect(within(column('Precisa de você')).getByText('⇄')).toBeInTheDocument()
    expect(within(column('A fazer')).getByText('Review final')).toBeInTheDocument()
  })

  it('clicar no card abre o corpo da faixa dentro dele', async () => {
    const user = userEvent.setup()
    render(<EpicBoard view={view([lane('E1', 'running')])} />)
    const button = screen.getByRole('button', { name: /Épico E1/ })
    expect(button).toHaveAttribute('aria-expanded', 'false')
    await user.click(button)
    expect(button).toHaveAttribute('aria-expanded', 'true')
    const region = within(column('Em andamento')).getByRole('region', { name: 'Épico E1' })
    expect(within(region).getByText(/branch crew\/T-7-E1/)).toBeInTheDocument()
    expect(within(region).getByText('Developer')).toBeInTheDocument()
    expect(within(region).getByText('Tester')).toBeInTheDocument()
    expect(within(region).getByText('Merge')).toBeInTheDocument()
  })

  it('no review final o terceiro estágio é o Reviewer', async () => {
    const user = userEvent.setup()
    render(
      <EpicBoard view={view([lane('R', 'running', { kind: 'review', title: 'Review final' })])} />,
    )
    await user.click(screen.getByRole('button', { name: /Review final/ }))
    const region = screen.getByRole('region', { name: 'Review final' })
    expect(within(region).getByText('Reviewer')).toBeInTheDocument()
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
    const { container } = render(
      <EpicBoard view={view([lane('E1', 'running', { stages, counters })])} />,
    )
    const chips = [...container.querySelectorAll('[data-lane="E1"] i')]
    expect(chips.map((i) => [i.textContent, i.getAttribute('data-status')])).toEqual([
      ['Dev', 'done'],
      ['Test', 'active'],
      ['Merge', 'idle'],
    ])
    expect(container.querySelector('[data-lane="E1"] b')).toHaveTextContent('↺2')
  })

  it('não aparece em A fazer', () => {
    const { container } = render(<EpicBoard view={view([lane('E1', 'waiting')])} />)
    expect(container.querySelector('[data-lane="E1"] i')).toBeNull()
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
