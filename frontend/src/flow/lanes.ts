import type { StageStatus } from '../contracts/aliases'
import type { EpicView, StageView, TaskView } from '../contracts/generated'

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

/** Grupo de exibição de cada status: cor da borda, ordem da tabela e coluna do board. */
export type EpicTone = 'attention' | 'running' | 'preparing' | 'queued' | 'done'

export const EPIC_TONE: Record<EpicStatus, EpicTone> = {
  escalated: 'attention',
  limited: 'attention',
  failed: 'attention',
  running: 'running',
  merging: 'running',
  preparing: 'preparing',
  pending: 'queued',
  waiting: 'queued',
  merged: 'done',
}

/** Como a etapa "Épicos" do trilho se pinta (mesmas cores dos estágios). */
export const EPIC_CARD_STATUS: Record<EpicTone, StageStatus> = {
  attention: 'error',
  running: 'active',
  preparing: 'active',
  queued: 'idle',
  done: 'done',
}

const TONE_ORDER: readonly EpicTone[] = ['attention', 'running', 'preparing', 'queued', 'done']

/** Ordem da tabela: precisa de você, rodando, preparando, na fila, pronto. Empates mantêm `view.epics`. */
export function sortLanes(lanes: readonly EpicView[]): EpicView[] {
  const rank = (lane: EpicView) => TONE_ORDER.indexOf(EPIC_TONE[lane.status])
  return [...lanes].sort((a, b) => rank(a) - rank(b))
}

/** Faixas paradas esperando uma decisão sua: viram Alert na seção e o CTA da faixa Agora. */
export function lanesNeedingYou(lanes: readonly EpicView[]): EpicView[] {
  return lanes.filter((lane) => lane.status === 'escalated' || lane.status === 'failed')
}

/** Faixas que ainda esperam `id` terminar. */
export function dependentsOf(lanes: readonly EpicView[], id: string): EpicView[] {
  return lanes.filter((lane) => lane.status !== 'merged' && lane.depends_on.includes(id))
}

/** O contador único da tela (faixa Agora): épicos juntados / épicos do plano. */
export function epicProgress(lanes: readonly EpicView[]): { done: number; total: number } {
  const epics = lanes.filter((lane) => lane.kind === 'epic')
  return { done: epics.filter((lane) => lane.status === 'merged').length, total: epics.length }
}

export type BoardColumn = 'attention' | 'doing' | 'todo' | 'done'

/** As colunas do board, na ordem em que aparecem. */
export const BOARD_COLUMNS: readonly { id: BoardColumn; label: string }[] = [
  { id: 'attention', label: 'Precisa de você' },
  { id: 'doing', label: 'Rodando' },
  { id: 'todo', label: 'Na fila' },
  { id: 'done', label: 'Pronto' },
]

/** Em que coluna do board cada grupo cai. */
export const TONE_COLUMN: Record<EpicTone, BoardColumn> = {
  attention: 'attention',
  running: 'doing',
  preparing: 'doing',
  queued: 'todo',
  done: 'done',
}

/** "1 precisa de você · 3 rodando · 1 na fila · 1 pronto", sem o review final e sem grupo vazio. */
export function epicsSummary(lanes: readonly EpicView[]): string {
  const counted = lanes.filter((lane) => lane.kind !== 'review')
  return BOARD_COLUMNS.map((column) => {
    const n = counted.filter((lane) => TONE_COLUMN[EPIC_TONE[lane.status]] === column.id).length
    return n > 0 ? `${String(n)} ${column.label.toLowerCase()}` : null
  })
    .filter((part) => part !== null)
    .join(' · ')
}

/**
 * A etapa em que a faixa está agora (Developer, Tester, Merge; Reviewer no review final), só quando há
 * estágio ativo ou em erro. Faixas na fila e prontas não têm etapa.
 */
export function laneStage(lane: EpicView): string | null {
  const tone = EPIC_TONE[lane.status]
  if (tone === 'queued' || tone === 'done') return null
  for (const key of ['reviewer', 'tester', 'developer'] as const) {
    const status = lane.stages[key].status
    if (status !== 'active' && status !== 'error') continue
    if (key === 'reviewer') return lane.kind === 'review' ? 'Reviewer' : 'Merge'
    return key === 'tester' ? 'Tester' : 'Developer'
  }
  return null
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

/**
 * Num ticket (e na integração) o terceiro estágio não é o Reviewer (D68): os testes passaram, o dev-crew
 * commita e junta na branch da tarefa. O Reviewer roda uma vez só, na faixa "Review final".
 */
const MERGE_DESC = 'Commit e merge na branch da tarefa'

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
