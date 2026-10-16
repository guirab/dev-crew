import type { EpicView, TaskView } from '../contracts/generated'

type EpicStatus = EpicView['status']

export const EPIC_STATUS_LABEL: Record<EpicStatus, string> = {
  pending: 'pendente',
  waiting: 'na fila',
  preparing: 'preparando',
  running: 'rodando',
  escalated: 'precisa de você',
  limited: 'parado no limite',
  merging: 'juntando',
  merged: 'pronto',
  failed: 'falhou',
}

/** Grupo de cada status no nó Execução: precisa de você · rodando (preparando) · na fila · prontos. */
export type EpicTone = 'attention' | 'running' | 'preparing' | 'queued' | 'done'

export const EPIC_TONE: Record<EpicStatus, EpicTone> = {
  escalated: 'attention',
  failed: 'attention',
  // parado no limite: a ação (Retomar) mora no nó pausado, não no épico
  limited: 'running',
  running: 'running',
  merging: 'running',
  preparing: 'preparing',
  pending: 'queued',
  waiting: 'queued',
  merged: 'done',
}

/** Faixas paradas esperando uma decisão sua: abrem sozinhas no nó Execução. */
export function lanesNeedingYou(lanes: readonly EpicView[]): EpicView[] {
  return lanes.filter((lane) => lane.status === 'escalated' || lane.status === 'failed')
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
