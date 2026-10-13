import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { Epic, EpicView, Plan, StageView, TaskView } from '../contracts/generated'
import { captureCommands } from '../test/commands'
import { fixture } from '../test/fixtures'
import { renderWithClient } from '../test/render'
import { DoneBody } from '../bodies/DoneBody'
import { EpicsSection } from './EpicsSection'
import { FlowColumn } from './FlowColumn'

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

describe('EpicsSection', () => {
  it('uma faixa por épico, com status e o que está acontecendo', () => {
    const running = lane('E1', 'running', {
      stages: {
        developer: { status: 'active', now: 'Editando core.py', logs: [] },
        tester: idle,
        reviewer: idle,
      },
    })
    const view = splitView([
      running,
      lane('E2', 'merged', { commit: 'abcdef123456' }),
      lane('E3', 'waiting'),
    ])
    renderWithClient(<EpicsSection view={view} />)
    expect(screen.getByText('1/3 prontos · 1 em paralelo')).toBeInTheDocument()
    expect(screen.getByText('Editando core.py')).toBeInTheDocument()
    expect(screen.getByText('juntado · abcdef12')).toBeInTheDocument()
    expect(screen.getByText('na fila')).toBeInTheDocument()
  })

  it('o ticket abre Developer, Tester e Merge (sem Reviewer, D68)', async () => {
    const user = userEvent.setup()
    renderWithClient(<EpicsSection view={splitView([lane('E1', 'running')])} />)
    await user.click(screen.getByRole('button', { name: /Épico E1/ }))
    const region = screen.getByRole('region', { name: 'Épico E1' })
    for (const title of ['Developer', 'Tester', 'Merge']) {
      expect(within(region).getByText(title)).toBeInTheDocument()
    }
    expect(within(region).queryByText('Reviewer')).not.toBeInTheDocument()
  })

  it('o review final abre Developer, Tester e Reviewer', async () => {
    const user = userEvent.setup()
    const review = lane('REV', 'running', { kind: 'review', title: 'Review final' })
    renderWithClient(<EpicsSection view={splitView([lane('E1', 'merged'), review])} />)
    await user.click(screen.getByRole('button', { name: /Review final/ }))
    const region = screen.getByRole('region', { name: 'Review final' })
    for (const title of ['Developer', 'Tester', 'Reviewer']) {
      expect(within(region).getByText(title)).toBeInTheDocument()
    }
  })

  it('escalada de uma faixa manda o épico e não oferece replanejar', async () => {
    const commands = captureCommands()
    const user = userEvent.setup()
    const escalated = lane('E2', 'escalated', {
      stages: {
        developer: idle,
        tester: { status: 'error', now: 'Limite 3/3', logs: [] },
        reviewer: idle,
      },
      escalation: { stage: 'tester', reason: '3 falhas consecutivas de teste', epic_id: 'E2' },
    })
    renderWithClient(<EpicsSection view={splitView([escalated])} />)
    await user.click(screen.getByRole('button', { name: /Épico E2/ }))
    await user.click(screen.getByRole('button', { name: /Tester/ }))
    expect(screen.queryByRole('button', { name: 'Voltar pro Planner' })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '+2 tentativas' }))
    await waitFor(() => {
      expect(commands.received).toEqual([
        { type: 'escalation', action: 'more_attempts', epic_id: 'E2' },
      ])
    })
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

  it('o fluxo troca o trilho Developer/Tester/Reviewer pelas faixas', () => {
    renderWithClient(<FlowColumn view={splitView([lane('E1', 'running')])} />)
    expect(screen.getByRole('region', { name: 'Épicos' })).toBeInTheDocument()
    expect(document.getElementById('stage-developer')).toBeNull()
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
