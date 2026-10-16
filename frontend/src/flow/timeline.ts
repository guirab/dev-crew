import type { StageKey, StageStatus } from '../contracts/aliases'
import type { EpicView, LogLine, StageView, TaskView } from '../contracts/generated'
import { formatClock, formatDuration, formatUsd } from '../lib/format'
import { EPIC_TONE } from './lanes'

/** Os nós da linha do tempo da tarefa, na ordem em que aparecem. */
export type NodeKey = 'task' | 'interview' | 'plan' | 'execution' | 'next' | 'review' | 'result'

/** done = passou · you = sua vez · run = trabalhando · todo = ainda não chegou · err = falhou · pause = limite. */
export type NodeTone = 'done' | 'you' | 'run' | 'todo' | 'err' | 'pause'

export interface TimelineNode {
  key: NodeKey
  icon: string
  name: string
  /** Resumo de uma linha ao lado do nome. */
  summary: string
  /** Duração e custo, à direita. */
  meta: string
  tone: NodeTone
}

const TERMINAL_FAIL: readonly TaskView['phase'][] = ['failed', 'cancelled']

const STAGE_TONE: Record<StageStatus, NodeTone> = {
  idle: 'todo',
  pick: 'todo',
  skipped: 'todo',
  active: 'run',
  waiting: 'you',
  error: 'err',
  done: 'done',
}

/** Tom de um nó que junta estágios: sua vez > falhou > trabalhando > tudo pronto > ainda não chegou. */
function mergeTones(tones: readonly NodeTone[]): NodeTone {
  for (const tone of ['you', 'err', 'run'] as const) if (tones.includes(tone)) return tone
  if (tones.every((tone) => tone === 'done')) return 'done'
  return tones.includes('done') ? 'run' : 'todo'
}

const plural = (n: number, one: string, many: string) => `${String(n)} ${n === 1 ? one : many}`

/** Segundos entre a primeira e a última linha de log; `null` sem duas linhas válidas. */
export function logSpan(logs: readonly LogLine[]): number | null {
  const times = logs.map((line) => Date.parse(line.ts)).filter((t) => !Number.isNaN(t))
  if (times.length < 2) return null
  return (Math.max(...times) - Math.min(...times)) / 1000
}

function meta(logs: readonly LogLine[], cost = 0): string {
  const span = logSpan(logs)
  return [
    span !== null && span >= 1 ? formatDuration(span) : null,
    cost > 0 ? formatUsd(cost) : null,
  ]
    .filter((part) => part !== null)
    .join(' · ')
}

const logsOf = (...stages: StageView[]) => stages.flatMap((stage) => stage.logs)

/** As faixas que entram no nó Execução: épicos e integrações (o review final tem nó próprio). */
export function executionLanes(view: TaskView): EpicView[] {
  return view.epics.filter((lane) => lane.kind !== 'review')
}

export const reviewLane = (view: TaskView): EpicView | undefined =>
  view.epics.find((lane) => lane.kind === 'review')

/** Plano dividido em épicos (antes ou depois de aprovar). */
export const isSplit = (view: TaskView): boolean =>
  view.epics.length > 0 || (view.plan?.execution === 'epics' && view.plan.epics.length > 0)

function taskNode(view: TaskView): TimelineNode {
  return {
    key: 'task',
    icon: '▤',
    name: 'Tarefa',
    summary: view.description ? 'descrição + repositório' : view.repo,
    meta: formatClock(view.started_at).slice(0, 5),
    tone: 'done',
  }
}

function interviewNode(view: TaskView): TimelineNode {
  const stage = view.stages.interviewer
  const tone = STAGE_TONE[stage.status]
  const interview = view.interview
  const rounds = Math.max(0, ...(interview?.turns.map((turn) => turn.round) ?? []))
  let summary = stage.now ?? ''
  if (tone === 'done' && interview) {
    summary = `${plural(rounds, 'rodada', 'rodadas')} · ${plural(interview.decisions.length, 'decisão', 'decisões')}`
  } else if (tone === 'you' && interview && interview.pending.length > 0) {
    summary = `rodada ${String(rounds + 1)}`
  } else if (tone === 'todo') {
    summary = 'pergunta o que faltar'
  }
  return {
    key: 'interview',
    icon: 'EN',
    name: tone === 'done' ? 'Entrevista' : 'Entrevistador',
    summary,
    meta: meta(stage.logs),
    tone,
  }
}

function planNode(view: TaskView): TimelineNode {
  const { planner, approval } = view.stages
  const tone = mergeTones([STAGE_TONE[planner.status], STAGE_TONE[approval.status]])
  const plan = view.plan
  let summary = (approval.status === 'idle' ? planner.now : approval.now) ?? ''
  if (plan && (tone === 'you' || tone === 'done')) {
    const shape =
      plan.execution === 'epics' && plan.epics.length > 0
        ? plural(plan.epics.length, 'épico', 'épicos')
        : `${plural(plan.steps.length, 'passo', 'passos')} · ${plural(plan.files.length, 'arquivo', 'arquivos')}`
    summary = view.estimate ? `${shape} · estimativa ~${formatUsd(view.estimate.usd)}` : shape
  } else if (tone === 'todo') {
    summary = 'planeja depois da entrevista'
  }
  return {
    key: 'plan',
    icon: 'PL',
    name: approval.status === 'done' ? 'Plano aprovado' : 'Planner',
    summary,
    // só o trabalho do Planner: o log da aprovação contaria o tempo esperando você
    meta: meta(planner.logs),
    tone,
  }
}

function singleExecution(view: TaskView): TimelineNode {
  const { developer, tester } = view.stages
  const tone = mergeTones([STAGE_TONE[developer.status], STAGE_TONE[tester.status]])
  const last = view.test_runs.at(-1)
  const who =
    developer.status === 'active' ? 'Developer' : tester.status === 'active' ? 'Tester' : null
  let summary = ''
  if (who) summary = `${who} trabalhando`
  else if (tone === 'done' && last) summary = `${String(last.passed)}/${String(last.total)} testes`
  else if (tone !== 'todo') summary = view.escalation?.reason ?? tester.now ?? developer.now ?? ''
  return {
    key: 'execution',
    icon: '▶',
    name: 'Execução',
    summary,
    meta: meta(logsOf(developer, tester)),
    tone,
  }
}

function epicsExecution(view: TaskView): TimelineNode {
  const lanes = executionLanes(view)
  const tones = lanes.map((lane) => EPIC_TONE[lane.status])
  const epics = lanes.filter((lane) => lane.kind === 'epic')
  const merged = epics.filter((lane) => lane.status === 'merged').length
  let tone: NodeTone = 'todo'
  if (view.phase === 'awaiting_selection') tone = 'done'
  else if (tones.includes('attention')) tone = 'you'
  else if (tones.includes('running') || tones.includes('preparing')) tone = 'run'
  else if (lanes.length > 0 && tones.every((t) => t === 'done')) tone = 'done'
  else if (view.phase === 'executing') tone = 'run'
  const summary =
    tone === 'todo'
      ? ''
      : tone === 'done'
        ? plural(merged, 'épico pronto', 'épicos prontos')
        : `${String(merged)} de ${String(epics.length)} prontos`
  return {
    key: 'execution',
    icon: '▶',
    name: 'Execução',
    summary,
    meta: meta(
      lanes.flatMap((lane) =>
        logsOf(lane.stages.developer, lane.stages.tester, lane.stages.reviewer),
      ),
      lanes.reduce((sum, lane) => sum + lane.cost_usd, 0),
    ),
    tone,
  }
}

function reviewNode(view: TaskView): TimelineNode {
  const lane = reviewLane(view)
  const stage = lane ? lane.stages.reviewer : view.stages.reviewer
  const tone = lane
    ? EPIC_TONE[lane.status] === 'attention'
      ? 'you'
      : STAGE_TONE[stage.status]
    : STAGE_TONE[stage.status]
  const review = lane ? lane.review : view.review
  // pediu ajuste: o estágio volta a idle enquanto o Developer corrige (replanejar desaprova o plano)
  const sentBack =
    tone === 'todo' &&
    review?.verdict === 'changes_requested' &&
    view.stages.approval.status === 'done'
  const summary = sentBack
    ? 'pediu ajuste · voltou pro Developer'
    : tone === 'done' && review?.verdict === 'approved'
      ? 'aprovado'
      : tone === 'todo'
        ? ''
        : (stage.now ?? '')
  return {
    key: 'review',
    icon: 'RV',
    name: isSplit(view) ? 'Review final' : 'Reviewer',
    summary,
    meta: meta(stage.logs, lane?.cost_usd ?? 0),
    tone: sentBack ? 'done' : tone,
  }
}

function resultNode(view: TaskView): TimelineNode {
  const stage = view.stages.done
  const tone = STAGE_TONE[stage.status]
  const final = view.final
  return {
    key: 'result',
    icon: '✓',
    name: tone === 'done' ? 'Pronto pra commitar' : 'Resultado',
    summary: '',
    meta: final ? `${formatDuration(final.duration_s)} · ${formatUsd(final.cost_usd)}` : '',
    tone,
  }
}

/**
 * Os nós da tarefa, do que passou ao que vem. A Tarefa some depois do plano aprovado; com épicos, a
 * Execução junta as faixas e o review final ganha nó próprio. Tarefa que falhou para no nó que falhou.
 */
export function timelineNodes(view: TaskView): TimelineNode[] {
  const nodes: TimelineNode[] = []
  if (view.stages.approval.status !== 'done') nodes.push(taskNode(view))
  nodes.push(interviewNode(view), planNode(view))
  nodes.push(isSplit(view) ? epicsExecution(view) : singleExecution(view))
  if (view.phase === 'awaiting_selection') {
    nodes.push({ key: 'next', icon: '⎇', name: 'Próximo lote', summary: '', meta: '', tone: 'you' })
  }
  nodes.push(reviewNode(view), resultNode(view))

  const STAGE_NODE: Record<NonNullable<TaskView['escalation']>['stage'], NodeKey> = {
    interviewer: 'interview',
    planner: 'plan',
    developer: 'execution',
    tester: 'execution',
    reviewer: 'review',
  }
  const esc = view.escalation
  const escalated = esc && !esc.epic_id ? STAGE_NODE[esc.stage] : null
  if (!TERMINAL_FAIL.includes(view.phase)) {
    // tarefa viva: estágio em erro é uma volta do loop (trabalhando) ou a escalada (sua vez)
    for (const node of nodes) {
      if (node.key === escalated) node.tone = 'you'
      else if (node.tone === 'err') node.tone = 'run'
    }
  }
  if (TERMINAL_FAIL.includes(view.phase)) {
    // cancelada: o resumo do nó interrompido não repete o último log (ex.: falha antiga do Tester)
    const cut = view.phase === 'cancelled' ? { summary: 'cancelada' } : {}
    return nodes
      .filter((node) => node.tone !== 'todo')
      .map((node) => (node.tone === 'done' ? node : { ...node, ...cut, tone: 'err' }))
  }
  if (view.phase === 'limited') {
    const current = nodes.find((node) => node.tone === 'run' || node.tone === 'you')
    if (current) Object.assign(current, { tone: 'pause', icon: '⏸', summary: 'pausada' })
  }
  return nodes
}

/** Abre sozinho: o que precisa de você, o que falhou, a execução de épicos rodando e o resultado. */
export function opensByDefault(node: TimelineNode, view: TaskView): boolean {
  if (node.tone === 'you' || node.tone === 'err' || node.tone === 'pause') return true
  if (node.key === 'execution' && node.tone === 'run') return isSplit(view)
  return node.key === 'result' && node.tone === 'done'
}

/** O estágio que falhou dentro de um nó (pra mostrar a causa); `null` sem erro. */
export function failedStage(view: TaskView, key: NodeKey): StageView | null {
  const keys: Record<NodeKey, readonly StageKey[]> = {
    task: ['manual'],
    interview: ['interviewer'],
    plan: ['planner', 'approval'],
    execution: ['developer', 'tester'],
    next: [],
    review: ['reviewer'],
    result: ['done'],
  }
  if (key === 'review') {
    const lane = reviewLane(view)
    if (lane) return lane.stages.reviewer.status === 'error' ? lane.stages.reviewer : null
  }
  return keys[key].map((k) => view.stages[k]).find((stage) => stage.status === 'error') ?? null
}
