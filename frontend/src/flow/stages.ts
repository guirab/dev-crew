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

/** Segunda origem (D58): não é um estágio do fluxo, só abre o formulário de projeto novo. */
export const NEW_PROJECT_META: StageMeta = {
  title: 'Novo projeto',
  desc: 'Do zero: pasta, git, stack e plano',
  icon: '+',
}

/** Terceira origem: registra um repositório git que já existe no disco; não inicia tarefa. */
export const ADD_REPO_META: StageMeta = {
  title: 'Adicionar repositório',
  desc: 'Uma pasta git que já existe no disco',
  icon: '⊕',
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

/** Contador n/máx de quem tem máximo definido (Tester, Reviewer); `null` sem contagem > 0. */
function boundedCounter(
  key: StageKey,
  counters: Counters | null | undefined,
): { n: number; max: number } | null {
  if (!counters) return null
  if (key === 'tester' && counters.test_attempt > 0) {
    return { n: counters.test_attempt, max: counters.max_test_attempts }
  }
  if (key === 'reviewer' && counters.review_round > 0) {
    return { n: counters.review_round, max: counters.max_review_rounds }
  }
  return null
}

/** Contador à direita do rótulo: `tester 2/3`, `reviewer 1/2`, `developer rodada n`. */
export function stageCounter(key: StageKey, counters: Counters | null | undefined): string {
  if (!counters) return ''
  const bounded = boundedCounter(key, counters)
  if (bounded) return `${bounded.n}/${bounded.max}`
  switch (key) {
    case 'developer':
      return counters.dev_round > 0 ? `rodada ${counters.dev_round}` : ''
    default:
      return ''
  }
}

export type StageProgress = { kind: 'determinate'; value: number } | { kind: 'indeterminate' }

const PROGRESS_STAGES: readonly StageKey[] = [
  'interviewer',
  'planner',
  'developer',
  'tester',
  'reviewer',
]

/**
 * Barra de progresso do card. O backend não emite porcentagem: usa só o status e os contadores.
 * Tester/Reviewer: n/máx; Entrevistador/Planner/Developer: indeterminada enquanto `active`.
 */
export function stageProgress(
  key: StageKey,
  status: StageStatus,
  counters: Counters | null | undefined,
): StageProgress | null {
  if (!PROGRESS_STAGES.includes(key)) return null
  if (status === 'done') return { kind: 'determinate', value: 1 }
  if (status !== 'active' && status !== 'waiting' && status !== 'error') return null
  const bounded = boundedCounter(key, counters)
  if (bounded && bounded.max > 0) {
    return { kind: 'determinate', value: Math.min(Math.max(bounded.n / bounded.max, 0), 1) }
  }
  return status === 'active' ? { kind: 'indeterminate' } : null
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
 * Sobrepõe as linhas de progresso (WS, entre snapshots) ao estágio ativo.
 * O snapshot seguinte é a verdade: o store descarta o progresso a cada `view`.
 */
export function withProgress(stage: StageView, lines: readonly LogLine[] | undefined): StageView {
  const last = lines?.at(-1)
  if (!lines || !last || stage.status !== 'active') return stage
  return { ...stage, now: last.text, logs: [...stage.logs, ...lines] }
}
