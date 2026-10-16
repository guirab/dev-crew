import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { EpicView, StageView, TaskView } from '../contracts/generated'
import { fixture } from '../test/fixtures'
import { renderWithClient } from '../test/render'
import { activityEvents, MAX_EVENTS } from './activity'
import { ActivityFeed } from './ActivityFeed'

const at = (minute: number) => `2026-10-14T12:${String(minute).padStart(2, '0')}:00Z`
const stage = (lines: [number, string][]): StageView => ({
  status: 'done',
  now: null,
  logs: lines.map(([m, text]) => ({ ts: at(m), text })),
})

function lane(id: string, kind: EpicView['kind'], dev: StageView, merge: StageView): EpicView {
  return {
    id,
    kind,
    title: id,
    goal: '',
    size: 'S',
    depends_on: [],
    status: 'merged',
    stages: { developer: dev, tester: stage([]), reviewer: merge },
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

function view(): TaskView {
  const base = fixture('developing')
  const empty = stage([])
  return {
    ...base,
    stages: {
      ...base.stages,
      manual: empty,
      interviewer: stage([[1, 'rodada 1']]),
      planner: stage([[3, 'plano pronto']]),
      approval: empty,
      developer: stage([[5, 'editando a.py']]),
      tester: empty,
      reviewer: empty,
      done: empty,
    },
  }
}

describe('activityEvents', () => {
  it('junta os logs de todos os estágios + progresso ao vivo, do mais novo pro mais antigo', () => {
    const progress = { developer: [{ ts: at(6), text: 'rodando ruff' }] }
    expect(activityEvents(view(), progress).map((e) => `${e.who}: ${e.text}`)).toEqual([
      'Developer: rodando ruff',
      'Developer: editando a.py',
      'Planner: plano pronto',
      'Entrevistador: rodada 1',
    ])
  })

  it('logs das faixas levam o id; o 3º estágio do ticket é Merge e o do review final é Reviewer', () => {
    const v = {
      ...view(),
      epics: [
        lane('E1', 'epic', stage([[7, 'feito']]), stage([[8, 'commit abc']])),
        lane('REV', 'review', stage([]), stage([[9, 'aprovado']])),
      ],
    }
    expect(activityEvents(v).slice(0, 3)).toEqual([
      { ts: at(9), who: 'Reviewer', lane: 'REV', text: 'aprovado', attention: false },
      { ts: at(8), who: 'Merge', lane: 'E1', text: 'commit abc', attention: false },
      { ts: at(7), who: 'Developer', lane: 'E1', text: 'feito', attention: false },
    ])
  })

  it(`guarda só os ${String(MAX_EVENTS)} mais novos`, () => {
    const lines: [number, string][] = Array.from({ length: MAX_EVENTS + 5 }, (_, i) => [
      i % 60,
      `l${String(i)}`,
    ])
    expect(
      activityEvents({ ...view(), stages: { ...view().stages, developer: stage(lines) } }),
    ).toHaveLength(MAX_EVENTS)
  })
})

describe('ActivityFeed', () => {
  const feed = () => screen.getByRole('complementary', { name: 'Atividade' })

  it('filtra por agente na execução única', async () => {
    const user = userEvent.setup()
    renderWithClient(<ActivityFeed view={view()} />)
    expect(within(feed()).getAllByRole('listitem')).toHaveLength(3)
    await user.click(within(feed()).getByRole('combobox', { name: 'Filtrar por agente' }))
    await user.click(await screen.findByRole('option', { name: 'Planner' }))
    expect(within(feed()).getAllByRole('listitem')).toHaveLength(1)
    expect(within(feed()).getByText('plano pronto')).toBeInTheDocument()
    await user.click(within(feed()).getByRole('button', { name: 'Tudo' }))
    expect(within(feed()).getAllByRole('listitem')).toHaveLength(3)
  })

  it('com épicos: precisa de você, erros e agrupamento das faixas', async () => {
    const user = userEvent.setup()
    const v: TaskView = {
      ...view(),
      epics: [
        lane('E1', 'epic', stage([[7, 'Preparando o worktree']]), stage([])),
        lane('E2', 'epic', stage([[7, 'Preparando o worktree']]), stage([])),
        {
          ...lane('E3', 'epic', stage([[8, 'Tester falhou 3 vezes']]), stage([])),
          status: 'escalated',
        },
      ],
    }
    renderWithClient(<ActivityFeed view={v} />)
    // mesmo texto no mesmo segundo: uma linha só com as faixas
    const grouped = within(feed()).getByText('Preparando o worktree').closest('li')
    expect(grouped).toHaveTextContent('E1E2')
    expect(within(feed()).getByText('Tester falhou 3 vezes').closest('li')).toHaveAttribute(
      'data-highlight',
      'true',
    )
    await user.click(within(feed()).getByRole('button', { name: 'Precisa de você · 1' }))
    expect(within(feed()).getAllByRole('listitem')).toHaveLength(1)
    await user.click(within(feed()).getByRole('button', { name: 'Erros' }))
    expect(within(feed()).getByText('Tester falhou 3 vezes')).toBeInTheDocument()
  })

  it('mensagem longa fica cortada até "mostrar tudo"', async () => {
    const user = userEvent.setup()
    const long = 'x'.repeat(200)
    renderWithClient(
      <ActivityFeed
        view={{ ...view(), stages: { ...view().stages, planner: stage([[3, long]]) } }}
      />,
    )
    await user.click(within(feed()).getByRole('button', { name: 'mostrar tudo' }))
    expect(within(feed()).queryByRole('button', { name: 'mostrar tudo' })).not.toBeInTheDocument()
  })

  it('recolhe pra coluna fina com o contador e abre de novo', async () => {
    const user = userEvent.setup()
    renderWithClient(<ActivityFeed view={fixture('awaiting_approval')} />)
    await user.click(screen.getByRole('button', { name: 'Recolher feed' }))
    expect(feed()).toHaveAttribute('data-feed', 'closed')
    expect(within(feed()).queryByRole('list')).not.toBeInTheDocument()
    expect(within(feed()).getByTitle('1 precisa de você')).toHaveTextContent('1')
    await user.click(screen.getByRole('button', { name: 'Abrir feed' }))
    expect(feed()).toHaveAttribute('data-feed', 'open')
  })
})
