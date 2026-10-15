import type { StageKey } from '../contracts/aliases'
import type { LogLine, TaskView } from '../contracts/generated'
import { FLOW_STAGES, STAGE_META } from './stages'

const STAGE_KEYS: readonly StageKey[] = ['manual', ...FLOW_STAGES]

export interface ActivityEvent {
  ts: string
  /** Quem fez: "Developer", "Tester", "Merge"... */
  who: string
  /** Faixa (épico, integração ou review final); `null` fora do plano dividido. */
  lane: string | null
  text: string
}

/** Quanto o feed guarda: os logs só crescem e o DOM não precisa de tudo. */
export const MAX_EVENTS = 300

/**
 * Feed único da tarefa: logs de todos os estágios, de todas as faixas e o progresso ao vivo (WS),
 * do mais novo pro mais antigo.
 */
export function activityEvents(
  view: TaskView,
  progress: Partial<Record<StageKey, LogLine[]>> = {},
): ActivityEvent[] {
  const events: ActivityEvent[] = []
  const push = (lines: readonly LogLine[], who: string, lane: string | null) => {
    for (const line of lines) events.push({ ts: line.ts, who, lane, text: line.text })
  }
  for (const key of STAGE_KEYS) {
    push(view.stages[key].logs, STAGE_META[key].title, null)
    push(progress[key] ?? [], STAGE_META[key].title, null)
  }
  for (const lane of view.epics) {
    for (const key of ['developer', 'tester', 'reviewer'] as const) {
      // nos tickets o 3º estágio é o merge do dev-crew; só o review final tem Reviewer (D68)
      const who = key === 'reviewer' && lane.kind !== 'review' ? 'Merge' : STAGE_META[key].title
      push(lane.stages[key].logs, who, lane.id)
    }
  }
  // ISO 8601 em UTC ordena como texto; o sort é estável, então empates mantêm a ordem do fluxo
  events.sort((a, b) => (a.ts < b.ts ? 1 : a.ts > b.ts ? -1 : 0))
  return events.slice(0, MAX_EVENTS)
}
