import type { StageStatus } from '../contracts/aliases'
import type { EpicView, TaskView } from '../contracts/generated'

type EpicStatus = EpicView['status']

export const EPIC_STATUS_LABEL: Record<EpicStatus, string> = {
  pending: 'pendente',
  waiting: 'na fila',
  preparing: 'preparando',
  running: 'em execução',
  escalated: 'precisa de você',
  limited: 'parado no limite',
  merging: 'juntando',
  merged: 'pronto',
  failed: 'falhou',
}

/** Como o card da faixa se pinta (mesmas cores dos cards de estágio). */
export const EPIC_CARD_STATUS: Record<EpicStatus, StageStatus> = {
  pending: 'idle',
  waiting: 'idle',
  preparing: 'active',
  running: 'active',
  escalated: 'error',
  limited: 'error',
  merging: 'active',
  merged: 'done',
  failed: 'error',
}

/**
 * A faixa vista como uma tarefa: os corpos de Developer/Tester/Reviewer leem `view.dev_rounds`,
 * `view.escalation` etc., então eles servem pras faixas sem mudança.
 */
export function laneView(view: TaskView, lane: EpicView): TaskView {
  return {
    ...view,
    stages: {
      ...view.stages,
      developer: lane.stages.developer,
      tester: lane.stages.tester,
      reviewer: lane.stages.reviewer,
    },
    edges: lane.edges,
    active_edge: lane.active_edge,
    counters: lane.counters,
    dev_rounds: lane.dev_rounds,
    test_runs: lane.test_runs,
    review: lane.review,
    escalation: lane.escalation,
  }
}

/** Linha de status do card fechado: o que a faixa está fazendo agora. */
export function laneSummary(lane: EpicView): string {
  if (lane.status === 'merged' && lane.commit) return `juntado · ${lane.commit.slice(0, 8)}`
  if (lane.escalation) return lane.escalation.reason
  for (const key of ['reviewer', 'tester', 'developer'] as const) {
    const stage = lane.stages[key]
    if ((stage.status === 'active' || stage.status === 'error') && stage.now) return stage.now
  }
  return lane.goal || EPIC_STATUS_LABEL[lane.status]
}
