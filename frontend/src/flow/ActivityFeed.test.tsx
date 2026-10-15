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
      { ts: at(9), who: 'Reviewer', lane: 'REV', text: 'aprovado' },
      { ts: at(8), who: 'Merge', lane: 'E1', text: 'commit abc' },
      { ts: at(7), who: 'Developer', lane: 'E1', text: 'feito' },
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
  it('filtra por agente na execução única', async () => {
    const user = userEvent.setup()
    renderWithClient(<ActivityFeed view={view()} />)
    const feed = screen.getByRole('complementary', { name: 'Atividade' })
    expect(within(feed).getAllByRole('listitem')).toHaveLength(3)
    await user.click(within(feed).getByRole('button', { name: 'Planner' }))
    expect(within(feed).getAllByRole('listitem')).toHaveLength(1)
    expect(within(feed).getByText('plano pronto')).toBeInTheDocument()
    await user.click(within(feed).getByRole('button', { name: 'Tudo' }))
    expect(within(feed).getAllByRole('listitem')).toHaveLength(3)
  })

  it('com épicos filtra por faixa', async () => {
    const user = userEvent.setup()
    const v = {
      ...view(),
      epics: [
        lane('E1', 'epic', stage([[7, 'feito E1']]), stage([])),
        lane('E2', 'epic', stage([[8, 'feito E2']]), stage([])),
      ],
    }
    renderWithClient(<ActivityFeed view={v} />)
    await user.click(screen.getByRole('button', { name: 'E2' }))
    expect(screen.getAllByRole('listitem')).toHaveLength(1)
    expect(screen.getByText('feito E2')).toBeInTheDocument()
  })
})
