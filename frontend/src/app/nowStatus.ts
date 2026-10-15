import type { StageKey } from '../contracts/aliases'
import type { LogLine, TaskView } from '../contracts/generated'
import { laneSummary } from '../flow/lanes'
import { FLOW_STAGES, withProgress } from '../flow/stages'
import type { FlowStageKey } from '../flow/stages'
import { describe } from './tabStatus'
import type { FaviconKind } from './tabStatus'

/** Onde o CTA da faixa leva: um card do fluxo ou a seção de épicos. */
export type FocusTarget = FlowStageKey | 'epics'

export interface NowStatus {
  tone: Exclude<FaviconKind, 'base'>
  headline: string
  /** O que está acontecendo agora (linha do agente, motivo da escalada...); `null` sem nada a dizer. */
  detail: string | null
  cta: { label: string; target: FocusTarget } | null
}

const LANE_BUSY: readonly string[] = ['preparing', 'running', 'merging']

function detail(view: TaskView, progress: Partial<Record<StageKey, LogLine[]>>): string | null {
  if (view.escalation) return view.escalation.reason
  if (view.limit) return view.limit.message
  if (view.phase === 'done') return view.stages.done.now
  if (view.phase === 'failed' || view.phase === 'cancelled') return null
  const lanes = view.epics.filter((lane) => LANE_BUSY.includes(lane.status))
  if (lanes[0]) {
    const more = lanes.length > 1 ? ` (+${String(lanes.length - 1)} em paralelo)` : ''
    return `${lanes[0].id} · ${laneSummary(lanes[0])}${more}`
  }
  for (const key of FLOW_STAGES) {
    const stage = withProgress(view.stages[key], progress[key])
    if (['active', 'waiting', 'error'].includes(stage.status) && stage.now) return stage.now
  }
  return null
}

function cta(view: TaskView): NowStatus['cta'] {
  switch (view.phase) {
    case 'interviewing':
      return view.stages.interviewer.status === 'waiting'
        ? { label: 'Responder entrevista', target: 'interviewer' }
        : null
    case 'awaiting_approval':
      return { label: 'Revisar plano', target: 'approval' }
    case 'awaiting_selection':
      return { label: 'Escolher épicos', target: 'epics' }
    case 'escalated':
      if (!view.escalation) return null
      return {
        label: 'Resolver escalada',
        target: view.escalation.epic_id ? 'epics' : view.escalation.stage,
      }
    case 'done':
      return { label: 'Ver resultado', target: 'done' }
    default:
      return null
  }
}

/** Faixa "Agora": o estado da tarefa numa linha, o que o agente faz e, se for a vez do usuário, o CTA. */
export function nowStatus(
  view: TaskView,
  progress: Partial<Record<StageKey, LogLine[]>> = {},
): NowStatus {
  const { state, favicon } = describe(view)
  return {
    tone: favicon === 'base' ? 'working' : favicon,
    // a bolinha do título da aba vira a cor da faixa aqui
    headline: state.replace(/^● /, ''),
    detail: detail(view, progress),
    cta: cta(view),
  }
}
