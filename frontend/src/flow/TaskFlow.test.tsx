import { act, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'
import type { EpicView, StageView, TaskView } from '../contracts/generated'
import { useCrewStore } from '../store/crew'
import { focusPanel, isStageOpen, scrollIntoViewMock, stageCard } from '../test/dom'
import { fixture } from '../test/fixtures'
import { renderWithClient } from '../test/render'
import { autoFocus, railSteps } from './rail'
import { TaskFlow } from './TaskFlow'

const idle: StageView = { status: 'idle', now: null, logs: [] }

function lane(id: string, status: EpicView['status']): EpicView {
  return {
    id,
    kind: 'epic',
    title: `Épico ${id}`,
    goal: '',
    size: 'S',
    depends_on: [],
    status,
    stages: { developer: idle, tester: idle, reviewer: idle },
    edges: {},
    active_edge: null,
    counters: fixture('developing').counters,
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

const steps = () => screen.getAllByRole('tab').map((tab) => tab.getAttribute('data-stage') ?? '')

describe('railSteps / autoFocus', () => {
  it('execução única: 8 etapas na ordem do fluxo', () => {
    expect(railSteps(fixture('developing')).map((s) => s.key)).toEqual([
      'manual',
      'interviewer',
      'planner',
      'approval',
      'developer',
      'tester',
      'reviewer',
      'done',
    ])
  })

  it('com épicos, Developer/Tester/Reviewer viram "Épicos" com o status de cada faixa', () => {
    const view: TaskView = {
      ...fixture('developing'),
      phase: 'executing',
      epics: [lane('E1', 'merged'), lane('E2', 'running')],
    }
    const rail = railSteps(view)
    expect(rail.map((s) => s.key)).toEqual([
      'manual',
      'interviewer',
      'planner',
      'approval',
      'epics',
      'done',
    ])
    expect(rail[4]).toMatchObject({
      status: 'active',
      tag: '1 rodando',
    })
  })

  it.each([
    ['interviewing', 'interviewer'],
    ['awaiting_approval', 'approval'],
    ['planning', 'planner'],
    ['developing', 'developer'],
    ['escalated', 'tester'],
    ['done', 'done'],
  ])('%s: foco automático em %s', (name, key) => {
    expect(autoFocus(railSteps(fixture(name))).key).toBe(key)
  })
})

describe('TaskFlow', () => {
  beforeEach(() => {
    scrollIntoViewMock.mockClear()
  })

  it('trilho com status e conectores de view; painel mostra a etapa em foco', () => {
    renderWithClient(<TaskFlow view={fixture('developing')} />)
    expect(steps()).toEqual(railSteps(fixture('developing')).map((s) => s.key))
    expect(stageCard('developer')).toHaveAttribute('data-status', 'active')
    expect(stageCard('approval')).toHaveAttribute('data-status', 'done')
    expect(isStageOpen('developer')).toBe(true)
    expect(within(focusPanel()).getAllByText('Editando shop/report.py').length).toBeGreaterThan(0)
    expect(
      document.querySelector('[data-connector="approval"]')?.getAttribute('data-state'),
    ).not.toBe('idle')
  })

  it('tag mostra os contadores (tester 3/3 na escalada)', () => {
    renderWithClient(<TaskFlow view={fixture('escalated')} />)
    expect(stageCard('tester')).toHaveTextContent('precisa de você · 3/3')
    expect(isStageOpen('tester')).toBe(true) // escalada: foco no que precisa de você
  })

  it('clicar numa etapa fixa o foco; snapshots novos não tiram', async () => {
    const user = userEvent.setup()
    const view = fixture('developing')
    const { rerender } = renderWithClient(<TaskFlow view={view} />)
    await user.click(stageCard('planner'))
    expect(isStageOpen('planner')).toBe(true)
    expect(focusPanel()).toHaveAttribute('data-focus', 'planner')

    rerender(<TaskFlow view={{ ...view }} />)
    expect(focusPanel()).toHaveAttribute('data-focus', 'planner')
  })

  it('a etapa fixada solta quando o usuário age nela (waiting → done) e o foco segue a ação', async () => {
    const user = userEvent.setup()
    const waiting = fixture('awaiting_approval')
    const { rerender } = renderWithClient(<TaskFlow view={waiting} />)
    await user.click(stageCard('approval'))
    rerender(<TaskFlow view={fixture('developing')} />)
    expect(focusPanel()).toHaveAttribute('data-focus', 'developer')
  })

  it('a linha de progresso do WS aparece no painel até o próximo snapshot', () => {
    useCrewStore.getState().applyView(fixture('developing')) // o store só aceita progresso da tarefa atual
    renderWithClient(<TaskFlow view={fixture('developing')} />)
    act(() => {
      useCrewStore.getState().applyProgress({
        type: 'progress',
        task_id: fixture('developing').task_id,
        data: { agent: 'developer', job_id: 'j1', kind: 'status', text: 'Rodando ruff' },
      })
    })
    expect(within(focusPanel()).getAllByText('Rodando ruff').length).toBeGreaterThan(0)
  })

  it('a etapa Tarefa mostra título, descrição e repo', async () => {
    const user = userEvent.setup()
    const view = fixture('developing')
    renderWithClient(<TaskFlow view={view} />)
    await user.click(stageCard('manual'))
    expect(within(focusPanel()).getByText(view.title)).toBeInTheDocument()
    expect(within(focusPanel()).getByText(`Repo: ${view.repo}`)).toBeInTheDocument()
  })

  it('com épicos o painel mostra as faixas e não há etapa Developer', () => {
    const view: TaskView = {
      ...fixture('developing'),
      phase: 'executing',
      epics: [lane('E1', 'running')],
    }
    renderWithClient(<TaskFlow view={view} />)
    expect(isStageOpen('epics')).toBe(true)
    expect(within(focusPanel()).getByRole('region', { name: 'Épicos' })).toBeInTheDocument()
    expect(document.querySelector('[data-stage="developer"]')).toBeNull()
  })

  it('CTA da faixa Agora fixa a etapa e rola até o painel; pedido de antes de montar é ignorado', () => {
    act(() => {
      useCrewStore.getState().focusOn('planner')
    })
    renderWithClient(<TaskFlow view={fixture('awaiting_approval')} />)
    expect(focusPanel()).toHaveAttribute('data-focus', 'approval')

    act(() => {
      useCrewStore.getState().focusOn('interviewer')
    })
    expect(focusPanel()).toHaveAttribute('data-focus', 'interviewer')
    expect(scrollIntoViewMock).toHaveBeenCalled()
  })
})
