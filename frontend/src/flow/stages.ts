import type { LogLine, StageView } from '../contracts/generated'
import type { StageKey } from '../contracts/aliases'

/** Nome de cada estágio na UI (título da aba, avisos). */
export const STAGE_META: Record<StageKey, { title: string }> = {
  manual: { title: 'Manual' },
  interviewer: { title: 'Entrevistador' },
  planner: { title: 'Planner' },
  approval: { title: 'Aprovação do plano' },
  developer: { title: 'Developer' },
  tester: { title: 'Tester' },
  reviewer: { title: 'Reviewer' },
  done: { title: 'Concluída' },
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
