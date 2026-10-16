import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { Epic, EpicView, Plan, StageView, TaskView } from '../contracts/generated'
import { captureCommands } from '../test/commands'
import { fixture } from '../test/fixtures'
import { renderWithClient } from '../test/render'
import { DoneBody } from '../bodies/DoneBody'
import { EpicsSection } from './EpicsSection'

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

const epic = (id: string, deps: string[] = []): Epic => ({
  id,
  title: `Épico ${id}`,
  goal: `objetivo ${id}`,
  steps: ['s'],
  files: [{ path: `${id}.py`, change: 'A' }],
  depends_on: deps,
  acceptance_criteria: ['ok'],
  size: 'M',
})

function splitView(lanes: EpicView[], phase: TaskView['phase'] = 'executing'): TaskView {
  const base = fixture('developing')
  if (!base.plan) throw new Error('fixture sem plano')
  const plan: Plan = {
    ...base.plan,
    execution: 'epics',
    split_rationale: 'porque',
    epics: [epic('E1'), epic('E2'), epic('E3', ['E1', 'E2'])],
  }
  return { ...base, phase, plan, epics: lanes }
}

const rows = () =>
  screen
    .getAllByRole('row')
    .map((row) => row.getAttribute('data-lane'))
    .filter(Boolean)

const escalatedE2 = (over: Partial<EpicView> = {}) =>
  lane('E2', 'escalated', {
    stages: {
      developer: idle,
      tester: { status: 'error', now: 'Limite 3/3', logs: [] },
      reviewer: idle,
    },
    escalation: { stage: 'tester', reason: '3 falhas consecutivas de teste', epic_id: 'E2' },
    ...over,
  })

describe('EpicsSection', () => {
  it('abre na tabela, ordenada por precisa de você, rodando, preparando, na fila, pronto', () => {
    const view = splitView([
      lane('E1', 'merged'),
      lane('E2', 'pending'),
      lane('E3', 'running'),
      escalatedE2({ id: 'E4' }),
      lane('E5', 'preparing'),
    ])
    renderWithClient(<EpicsSection view={view} />)
    expect(screen.getByRole('tab', { name: 'Tabela' })).toHaveAttribute('aria-selected', 'true')
    expect(rows()).toEqual(['E4', 'E3', 'E5', 'E2', 'E1'])
    expect(
      screen.getByText('1 precisa de você · 2 rodando · 1 na fila · 1 pronto'),
    ).toBeInTheDocument()
  })

  it('a linha mostra status, etapa, tokens, custo e dependências', () => {
    const running = lane('E1', 'running', {
      stages: {
        developer: idle,
        tester: { status: 'active', now: 'npm test', logs: [] },
        reviewer: idle,
      },
      tokens: 9100,
      cost_usd: 0.61,
      depends_on: ['E0'],
    })
    renderWithClient(<EpicsSection view={splitView([running])} />)
    const row = screen.getByRole('row', { name: /E1 · Épico E1/ })
    expect(within(row).getByText('rodando')).toBeInTheDocument()
    expect(within(row).getByText('Tester')).toBeInTheDocument()
    expect(within(row).getByText('9,1 mil')).toBeInTheDocument()
    expect(within(row).getByText('$0.61')).toBeInTheDocument()
    expect(within(row).getByText('E0')).toBeInTheDocument()
  })

  it('board e grafo são vistas alternativas; o NextBatch fica em todas', async () => {
    const user = userEvent.setup()
    const view = splitView([lane('E1', 'merged'), lane('E2', 'pending')], 'awaiting_selection')
    renderWithClient(<EpicsSection view={view} />)
    expect(screen.getByRole('group', { name: 'Próximos épicos' })).toBeInTheDocument()
    await user.click(screen.getByRole('tab', { name: 'Board' }))
    expect(screen.getByRole('group', { name: 'Pronto' })).toBeInTheDocument()
    expect(screen.queryByRole('group', { name: 'Rodando' })).not.toBeInTheDocument()
    await user.click(screen.getByRole('tab', { name: 'Grafo' }))
    expect(screen.getByRole('group', { name: 'Nível 1' })).toBeInTheDocument()
    expect(screen.getByRole('group', { name: 'Próximos épicos' })).toBeInTheDocument()
  })

  it('escalada vira Alert no topo com motivo, quem espera e +2 tentativas', async () => {
    const commands = captureCommands()
    const user = userEvent.setup()
    const view = splitView([escalatedE2(), lane('E3', 'waiting', { depends_on: ['E2'] })])
    renderWithClient(<EpicsSection view={view} />)
    const alert = screen.getByRole('alert')
    expect(alert).toHaveTextContent('E2 · Épico E2 precisa de você')
    expect(alert).toHaveTextContent('3 falhas consecutivas de teste. E3 está esperando o E2.')
    await user.click(within(alert).getByRole('button', { name: '+2 tentativas' }))
    await waitFor(() => {
      expect(commands.received).toEqual([
        { type: 'escalation', action: 'more_attempts', epic_id: 'E2' },
      ])
    })
  })

  it('sem nada parado, sem Alert', () => {
    renderWithClient(<EpicsSection view={splitView([lane('E1', 'running')])} />)
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('"Abrir E2" abre o painel lateral na aba Resolver; Esc fecha', async () => {
    const user = userEvent.setup()
    const run = {
      type: 'test' as const,
      ok: false,
      passed: 30,
      total: 32,
      failures: [{ test: 'ManualForm > título', message: 'Unable to find a label' }],
      coverage: null,
      command: 'npm test',
      tests_written: [],
    }
    renderWithClient(<EpicsSection view={splitView([escalatedE2({ test_runs: [run, run] })])} />)
    await user.click(screen.getByRole('button', { name: 'Abrir E2' }))
    const sheet = screen.getByRole('dialog', { name: 'Épico E2' })
    expect(within(sheet).getByRole('tab', { name: 'Resolver' })).toHaveAttribute(
      'aria-selected',
      'true',
    )
    expect(within(sheet).getByText('Última saída do Tester')).toBeInTheDocument()
    expect(within(sheet).getByText(/Unable to find a label/)).toBeInTheDocument()
    expect(
      within(sheet).getByRole('textbox', { name: 'Instrução pro Developer' }),
    ).toBeInTheDocument()
    expect(
      within(sheet).queryByRole('button', { name: 'Voltar pro Planner' }),
    ).not.toBeInTheDocument()
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('clicar na linha (ou Enter nela) abre o épico; o X fecha', async () => {
    const user = userEvent.setup()
    renderWithClient(<EpicsSection view={splitView([lane('E1', 'running')])} />)
    await user.click(screen.getByRole('row', { name: /E1 · Épico E1/ }))
    expect(screen.getByRole('dialog', { name: 'Épico E1' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Fechar' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()

    screen.getByRole('row', { name: /E1 · Épico E1/ }).focus()
    await user.keyboard('{Enter}')
    expect(screen.getByRole('dialog', { name: 'Épico E1' })).toBeInTheDocument()
  })

  it('o ticket tem abas Developer, Tester e Merge; o review final tem Reviewer', async () => {
    const user = userEvent.setup()
    const review = lane('REV', 'running', { kind: 'review', title: 'Review final' })
    renderWithClient(<EpicsSection view={splitView([lane('E1', 'running'), review])} />)
    await user.click(screen.getByRole('row', { name: /E1 · Épico E1/ }))
    let sheet = screen.getByRole('dialog')
    expect(
      within(sheet)
        .getAllByRole('tab')
        .map((t) => t.textContent),
    ).toEqual(['Developer', 'Tester', 'Merge', 'Log'])
    await user.keyboard('{Escape}')
    await user.click(screen.getByRole('row', { name: /REV · Review final/ }))
    sheet = screen.getByRole('dialog')
    expect(within(sheet).getByRole('tab', { name: 'Reviewer' })).toBeInTheDocument()
  })

  it('lote pronto: escolhe os próximos ou conclui', async () => {
    const commands = captureCommands()
    const user = userEvent.setup()
    const view = splitView(
      [lane('E1', 'merged'), lane('E2', 'pending'), lane('E3', 'pending')],
      'awaiting_selection',
    )
    renderWithClient(<EpicsSection view={view} />)
    expect(screen.getByRole('checkbox', { name: 'rodar E1 agora' })).toBeDisabled()
    await user.click(screen.getByRole('checkbox', { name: 'rodar E3 agora' }))
    await user.click(screen.getByRole('button', { name: 'Rodar 1 épico' }))
    await user.click(screen.getByRole('button', { name: 'Concluir agora' }))
    await waitFor(() => {
      expect(commands.received).toEqual([
        { type: 'run_epics', epics: ['E2'] },
        { type: 'finish_task' },
      ])
    })
  })
})

describe('DoneBody de plano dividido', () => {
  it('lista os commits por épico e o que ficou pendente', () => {
    const base = fixture('done')
    if (!base.final) throw new Error('fixture sem final')
    const view: TaskView = {
      ...base,
      epics: [lane('E1', 'merged')],
      final: {
        ...base.final,
        tokens: 123_000,
        commits: [{ epic_id: 'E1', sha: 'abcdef123456', message: 'feat(E1): núcleo\n\ncorpo' }],
        pending_epics: ['E3'],
        plan_doc: 'docs/plano/T-7.md',
      },
    }
    renderWithClient(<DoneBody view={view} stage={view.stages.done} />)
    expect(screen.getByText(/feat\(E1\): núcleo/)).toBeInTheDocument()
    expect(screen.getByText('Ficaram pendentes no plano: E3')).toBeInTheDocument()
    expect(screen.getByText('plano salvo em docs/plano/T-7.md')).toBeInTheDocument()
    expect(screen.getByText('123,0 mil')).toBeInTheDocument()
    expect(screen.getByText(/commitado na branch, sem push/)).toBeInTheDocument()
  })
})
