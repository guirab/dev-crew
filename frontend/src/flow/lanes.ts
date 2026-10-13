import type { StageStatus } from '../contracts/aliases'
import type { EpicView, StageView, TaskView } from '../contracts/generated'
import type { StageMeta } from './stages'

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

const MERGE_DESC = 'Commit e merge na branch da tarefa'

/**
 * Num ticket (e na integração) o terceiro estágio não é o Reviewer (D68): os testes passaram, o dev-crew
 * commita e junta na branch da tarefa. O Reviewer roda uma vez só, na faixa "Review final".
 */
export function mergeMeta(status: StageStatus): StageMeta {
  const icon = status === 'done' ? '✓' : status === 'error' ? '!' : '⤵'
  return { title: 'Merge', desc: MERGE_DESC, icon }
}

export function mergeDescription(stage: StageView): string {
  return stage.now && stage.status !== 'idle' ? stage.now : MERGE_DESC
}

/** Linha de status do card fechado: o que a faixa está fazendo agora. */
export function laneSummary(lane: EpicView): string {
  if (lane.status === 'merged' && lane.commit) return `juntado · ${lane.commit.slice(0, 8)}`
  if (lane.status === 'merged' && lane.kind === 'review') {
    const rounds = lane.counters.review_round
    return `aprovado · ${String(rounds)} rodada${rounds === 1 ? '' : 's'} de review`
  }
  if (lane.escalation) return lane.escalation.reason
  for (const key of ['reviewer', 'tester', 'developer'] as const) {
    const stage = lane.stages[key]
    if ((stage.status === 'active' || stage.status === 'error') && stage.now) return stage.now
  }
  return lane.goal || EPIC_STATUS_LABEL[lane.status]
}
