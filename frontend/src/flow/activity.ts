import type { StageKey } from '../contracts/aliases'
import type { LogLine, TaskView } from '../contracts/generated'
import { lanesNeedingYou } from './lanes'
import { FLOW_STAGES, STAGE_META } from './stages'

const STAGE_KEYS: readonly StageKey[] = ['manual', ...FLOW_STAGES]

export interface ActivityEvent {
  ts: string
  /** Quem fez: "Developer", "Tester", "Merge"... */
  who: string
  /** Faixa (épico, integração ou review final); `null` fora do plano dividido. */
  lane: string | null
  text: string
  /** Veio de uma faixa ou etapa que está esperando você agora. */
  attention: boolean
}

/** Quanto o feed guarda: os logs só crescem e o DOM não precisa de tudo. */
export const MAX_EVENTS = 300

const NEEDS_YOU: readonly string[] = ['waiting', 'error']

/**
 * Feed único da tarefa: logs de todos os estágios, de todas as faixas e o progresso ao vivo (WS),
 * do mais novo pro mais antigo.
 */
export function activityEvents(
  view: TaskView,
  progress: Partial<Record<StageKey, LogLine[]>> = {},
): ActivityEvent[] {
  const events: ActivityEvent[] = []
  const push = (
    lines: readonly LogLine[],
    who: string,
    lane: string | null,
    attention: boolean,
  ) => {
    for (const line of lines) events.push({ ts: line.ts, who, lane, text: line.text, attention })
  }
  for (const key of STAGE_KEYS) {
    const attention = NEEDS_YOU.includes(view.stages[key].status)
    push(view.stages[key].logs, STAGE_META[key].title, null, attention)
    push(progress[key] ?? [], STAGE_META[key].title, null, attention)
  }
  const needing = new Set(lanesNeedingYou(view.epics).map((lane) => lane.id))
  for (const lane of view.epics) {
    for (const key of ['developer', 'tester', 'reviewer'] as const) {
      // nos tickets o 3º estágio é o merge do dev-crew; só o review final tem Reviewer (D68)
      const who = key === 'reviewer' && lane.kind !== 'review' ? 'Merge' : STAGE_META[key].title
      push(lane.stages[key].logs, who, lane.id, needing.has(lane.id))
    }
  }
  // ISO 8601 em UTC ordena como texto; o sort é estável, então empates mantêm a ordem do fluxo
  events.sort((a, b) => (a.ts < b.ts ? 1 : a.ts > b.ts ? -1 : 0))
  return events.slice(0, MAX_EVENTS)
}

/** Quantas faixas (com épicos) ou etapas esperam você: o contador do filtro e do feed recolhido. */
export function attentionCount(view: TaskView): number {
  if (view.epics.length > 0) return lanesNeedingYou(view.epics).length
  return STAGE_KEYS.filter((key) => NEEDS_YOU.includes(view.stages[key].status)).length
}

export type FeedMode = 'all' | 'attention' | 'errors'

// shortcut: erro detectado pelo texto do log (o LogLine não tem nível); trocar se o contrato ganhar um
const ERROR_TEXT = /falh|fail|erro|error|exce/i

function isErrorEvent(event: ActivityEvent): boolean {
  return ERROR_TEXT.test(event.text)
}

/** Filtros do feed: modo (tudo, precisa de você, erros) e origem (faixa com épicos, agente sem). */
export function filterEvents(
  events: readonly ActivityEvent[],
  mode: FeedMode,
  source: string | null,
  split: boolean,
): ActivityEvent[] {
  return events.filter(
    (e) =>
      (mode === 'all' || (mode === 'attention' ? e.attention : isErrorEvent(e))) &&
      (source === null || (split ? e.lane : e.who) === source),
  )
}

export interface ActivityRow {
  ts: string
  who: string
  text: string
  /** Faixas que fizeram a mesma coisa no mesmo segundo (vazio fora do plano dividido). */
  lanes: string[]
  /** O evento mais novo de quem espera você: a linha que se destaca. */
  highlight: boolean
}

/** Eventos seguidos com o mesmo agente, texto e segundo viram uma linha com as faixas juntas. */
export function groupEvents(events: readonly ActivityEvent[]): ActivityRow[] {
  const rows: ActivityRow[] = []
  const highlighted = new Set<string>()
  // a linha aberta e o evento que a abriu
  let last: { row: ActivityRow; event: ActivityEvent } | null = null
  for (const e of events) {
    if (
      last?.event.ts.slice(0, 19) === e.ts.slice(0, 19) &&
      last.event.who === e.who &&
      last.event.text === e.text &&
      e.lane !== null &&
      !last.row.lanes.includes(e.lane)
    ) {
      last.row.lanes.push(e.lane)
      continue
    }
    const source = e.lane ?? e.who
    const highlight = e.attention && !highlighted.has(source)
    if (highlight) highlighted.add(source)
    const row = { ts: e.ts, who: e.who, text: e.text, lanes: e.lane ? [e.lane] : [], highlight }
    rows.push(row)
    last = { row, event: e }
  }
  return rows
}
