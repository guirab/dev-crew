import type { Counters, LogLine, StageView, TaskView } from '../contracts/generated'
import type { EdgeKey, StageKey, StageStatus } from '../contracts/aliases'

/** Apresentação fixa por estágio. Textos portados de mockup/index.html. */
export interface StageMeta {
  title: string
  desc: string
  icon: string
}

export const STAGE_META: Record<StageKey, StageMeta> = {
  manual: { title: 'Manual', desc: 'Você descreve a tarefa', icon: 'M' },
  interviewer: {
    title: 'Entrevistador',
    desc: 'Pergunta em rodadas até a tarefa ficar clara',
    icon: 'E',
  },
  planner: { title: 'Planner', desc: 'Lê a tarefa e o repo, monta o plano', icon: 'P' },
  approval: {
    title: 'Aprovação do plano',
    desc: 'Você aprova ou pede ajuste antes do código',
    icon: '◆',
  },
  developer: { title: 'Developer', desc: 'Implementa o plano no repo local', icon: 'D' },
  tester: { title: 'Tester', desc: 'Escreve e roda os testes', icon: 'T' },
  reviewer: {
    title: 'Reviewer',
    desc: 'Revisa o diff: bugs, segurança, padrões do repo',
    icon: 'R',
  },
  done: {
    title: 'Concluída',
    desc: 'Alterações locais + mensagem de commit sugerida',
    icon: '✓',
  },
}

export const STATUS_TAG: Record<StageStatus, string> = {
  idle: '',
  pick: '',
  active: 'trabalhando',
  waiting: 'aguardando você',
  done: 'ok',
  error: 'precisa de você',
  skipped: 'pulado',
}

/** Ordem vertical do fluxo (sem o card de origem, que fica no topo). */
export const FLOW_STAGES = [
  'interviewer',
  'planner',
  'approval',
  'developer',
  'tester',
  'reviewer',
  'done',
] as const satisfies readonly StageKey[]

export type FlowStageKey = (typeof FLOW_STAGES)[number]

export type ConnectorState = 'idle' | 'on' | 'active'

/**
 * Cada conector vertical acende por uma ou mais arestas de `view.edges`.
 * Mesmo mapa do mockup.
 */
export const CONNECTOR_EDGES = {
  source: ['ma-iv'],
  interview: ['iv-pl'],
  plan: ['pl-ap'],
  approval: ['ap-dv'],
  develop: ['dv-ts'],
  test: ['ts-rv'],
  finish: ['rv-dn'],
  /** loop lateral "↺ falhou" (Tester → Developer) */
  loopFail: ['ts-dv'],
  /** loop lateral "↺ ajustes" (Reviewer → Developer) */
  loopAdjust: ['rv-dv'],
} as const satisfies Record<string, readonly EdgeKey[]>

export type ConnectorId = keyof typeof CONNECTOR_EDGES

/** Estágio de destino de cada aresta: pra onde rolar quando a aresta fica ativa. */
export const EDGE_TARGET: Record<EdgeKey, StageKey> = {
  'ma-iv': 'interviewer',
  'iv-pl': 'planner',
  'pl-ap': 'approval',
  'ap-dv': 'developer',
  'dv-ts': 'tester',
  'ts-rv': 'reviewer',
  'rv-dn': 'done',
  'ts-dv': 'developer',
  'rv-dv': 'developer',
}

export function connectorState(
  edges: TaskView['edges'] | null | undefined,
  ids: readonly EdgeKey[],
): ConnectorState {
  if (!edges) return 'idle'
  const states = ids.map((id) => edges[id])
  if (states.includes('active')) return 'active'
  return states.some((s) => s !== undefined) ? 'on' : 'idle'
}

/** Descrição do card: `stage.now` quando há trabalho/resultado; senão a descrição fixa. */
export function stageDescription(key: StageKey, stage: StageView | null): string {
  if (!stage?.now) return STAGE_META[key].desc
  if (stage.status === 'idle' || stage.status === 'pick' || stage.status === 'skipped') {
    return STAGE_META[key].desc
  }
  return stage.now
}

export function stageIcon(key: StageKey, status: StageStatus): string {
  if (status === 'done') return '✓'
  if (status === 'error') return '!'
  return STAGE_META[key].icon
}

/** Contador à direita do rótulo: `tester 2/3`, `reviewer 1/2`, `developer rodada n`. */
export function stageCounter(key: StageKey, counters: Counters | null | undefined): string {
  if (!counters) return ''
  switch (key) {
    case 'tester':
      return counters.test_attempt > 0
        ? `${counters.test_attempt}/${counters.max_test_attempts}`
        : ''
    case 'reviewer':
      return counters.review_round > 0
        ? `${counters.review_round}/${counters.max_review_rounds}`
        : ''
    case 'developer':
      return counters.dev_round > 0 ? `rodada ${counters.dev_round}` : ''
    default:
      return ''
  }
}

export function stageTag(
  key: StageKey,
  status: StageStatus,
  counters: Counters | null | undefined,
): string {
  return [STATUS_TAG[status], stageCounter(key, counters)].filter(Boolean).join(' · ')
}

/** Estágio sem tarefa: só o card de origem fica em `pick`; o resto `idle`. */
export function emptyStage(key: StageKey): StageView {
  return { status: key === 'manual' ? 'pick' : 'idle', now: null, logs: [] }
}

/**
 * Cards que devem fechar sozinhos entre dois snapshots da mesma tarefa: o usuário já agiu
 * (saiu de `waiting` pra concluído/ocioso) ou a escalada foi resolvida. Nunca abre nada.
 */
export function stagesToCollapse(prev: TaskView | null, next: TaskView | null): StageKey[] {
  if (prev?.task_id !== next?.task_id || !prev || !next) return []
  const keys: StageKey[] = FLOW_STAGES.filter((key) => {
    const before = prev.stages[key].status
    const after = next.stages[key].status
    return before === 'waiting' && (after === 'done' || after === 'idle' || after === 'skipped')
  })
  if (prev.escalation && !next.escalation) keys.push(prev.escalation.stage)
  return keys
}

/**
 * Sobrepõe as linhas de progresso (WS, entre snapshots) ao estágio ativo.
 * O snapshot seguinte é a verdade: o store descarta o progresso a cada `view`.
 */
export function withProgress(stage: StageView, lines: readonly LogLine[] | undefined): StageView {
  const last = lines?.at(-1)
  if (!lines || !last || stage.status !== 'active') return stage
  return { ...stage, now: last.text, logs: [...stage.logs, ...lines] }
}
