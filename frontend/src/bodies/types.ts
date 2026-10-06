import type { StageView, TaskView } from '../contracts/generated'

/** Props comuns dos corpos expandidos. `view` é `null` quando não há tarefa. */
export interface BodyProps {
  view: TaskView | null
  /** Estágio já com o progresso ao vivo sobreposto. */
  stage: StageView
}
