import type { StageStatus } from '../contracts/aliases'
import type { TaskView } from '../contracts/generated'
import { EPIC_CARD_STATUS, EPIC_TONE, lanesNeedingYou } from './lanes'
import { STAGE_META, stageIcon, stageTag } from './stages'
import type { ConnectorId, FlowStageKey } from './stages'

/** Uma etapa do trilho: a tarefa (origem), um estágio do fluxo ou o conjunto de épicos. */
export type RailKey = 'manual' | FlowStageKey | 'epics'

export interface RailStep {
  key: RailKey
  title: string
  icon: string
  status: StageStatus
  /** Texto curto ao lado do rótulo: "trabalhando · 2/3", "1 precisa de você"... */
  tag: string
  /** Conector antes da etapa (`null` na primeira). */
  connector: ConnectorId | null
}

const SINGLE: readonly [FlowStageKey, ConnectorId][] = [
  ['developer', 'approval'],
  ['tester', 'develop'],
  ['reviewer', 'test'],
]

/** Como a etapa "Épicos" se pinta: quem precisa de você > quem trabalha > tudo pronto. */
export function epicsStatus(view: TaskView): StageStatus {
  const statuses = view.epics.map((lane) => EPIC_CARD_STATUS[EPIC_TONE[lane.status]])
  if (view.phase === 'awaiting_selection') return 'waiting'
  if (statuses.includes('error')) return 'error'
  if (statuses.includes('active')) return 'active'
  if (statuses.length > 0 && statuses.every((s) => s === 'done')) return 'done'
  return view.phase === 'executing' ? 'active' : 'idle'
}

/** O x/y prontos fica só na faixa Agora: o trilho diz o que pede atenção, senão quantos rodam. */
function epicsTag(view: TaskView): string {
  const needing = lanesNeedingYou(view.epics).length
  if (needing > 0) return `${String(needing)} precisa de você`
  const running = view.epics.filter((lane) => EPIC_CARD_STATUS[EPIC_TONE[lane.status]] === 'active')
  return running.length > 0 ? `${String(running.length)} rodando` : ''
}

function stageStep(view: TaskView, key: FlowStageKey, connector: ConnectorId): RailStep {
  const { status } = view.stages[key]
  return {
    key,
    title: STAGE_META[key].title,
    icon: stageIcon(key, status),
    status,
    tag: stageTag(key, status, view.counters),
    connector,
  }
}

export type RailSteps = [RailStep, ...RailStep[]]

/** As etapas do trilho, na ordem do fluxo. Com épicos, Developer/Tester/Reviewer viram uma etapa só. */
export function railSteps(view: TaskView): RailSteps {
  const manual = view.stages.manual.status
  const steps: RailSteps = [
    {
      key: 'manual',
      title: 'Tarefa',
      icon: manual === 'done' ? '✓' : STAGE_META.manual.icon,
      status: manual,
      tag: '',
      connector: null,
    },
    stageStep(view, 'interviewer', 'source'),
    stageStep(view, 'planner', 'interview'),
    stageStep(view, 'approval', 'plan'),
  ]
  if (view.epics.length > 0) {
    const status = epicsStatus(view)
    steps.push({
      key: 'epics',
      title: 'Épicos',
      icon: status === 'done' ? '✓' : status === 'error' ? '!' : '≡',
      status,
      tag: epicsTag(view),
      connector: 'approval',
    })
  } else {
    for (const [key, connector] of SINGLE) steps.push(stageStep(view, key, connector))
  }
  steps.push(stageStep(view, 'done', 'finish'))
  return steps
}

/** Etapa em foco sem escolha do usuário: a que precisa de você, senão a ativa, senão a última pronta. */
export function autoFocus(steps: Readonly<RailSteps>): RailStep {
  const last = (status: StageStatus) => [...steps].reverse().find((step) => step.status === status)
  const needsYou = steps.find((step) => step.status === 'waiting' || step.status === 'error')
  return needsYou ?? last('active') ?? last('done') ?? steps[0]
}
