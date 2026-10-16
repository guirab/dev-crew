import type { EpicView, TaskView } from '../contracts/generated'
import { isTaskView } from '../api/guards'

const modules = import.meta.glob('../../../contracts/fixtures/view.*.json', {
  eager: true,
  import: 'default',
})

/** Todas as fixtures de `contracts/fixtures`, por nome (`escalated`, `done`, ...). */
export const fixtures: Record<string, TaskView> = {}

for (const [path, data] of Object.entries(modules)) {
  const name = /view\.([\w-]+)\.json$/.exec(path)?.[1]
  if (!name) continue
  if (!isTaskView(data)) throw new Error(`fixture ${name} fora do contrato`)
  fixtures[name] = data
}

export function fixture(name: string): TaskView {
  const view = fixtures[name]
  if (!view) throw new Error(`fixture ${name} não encontrada`)
  return view
}

const idleStage = { status: 'idle' as const, now: null, logs: [] }

/** Uma faixa de plano dividido com valores neutros; `over` troca o que o teste precisa. */
export function epicLane(
  id: string,
  status: EpicView['status'],
  over: Partial<EpicView> = {},
): EpicView {
  return {
    id,
    kind: 'epic',
    title: `Épico ${id}`,
    goal: `objetivo ${id}`,
    size: 'M',
    depends_on: [],
    status,
    stages: { developer: idleStage, tester: idleStage, reviewer: idleStage },
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
